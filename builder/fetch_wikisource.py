#!/usr/bin/env python3
"""Freeze selected Chinese Wikisource pages and save exact UTF-8 wikitext snapshots.

The script consumes the Phase-0 selection rather than rediscovering titles. It lists
subpages, applies the reviewed work scope, fetches the latest revision content through
the MediaWiki API, records page-level revision IDs and SHA-256 hashes, and writes an
intermediate inventory. A later validation step promotes that inventory to
``sources/source-lock.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_DIR = Path(__file__).resolve().parents[1]
BUILDER_DIR = Path(__file__).resolve().parent
if str(BUILDER_DIR) not in sys.path:
    sys.path.insert(0, str(BUILDER_DIR))

from audit_wikisource import WikisourceClient  # noqa: E402

DEFAULT_CANDIDATES = PROJECT_DIR / "sources" / "source-candidates.json"
DEFAULT_SELECTION = PROJECT_DIR / "sources" / "source-selection.json"
DEFAULT_AUDIT = PROJECT_DIR / "sources" / "wikisource-audit.json"
DEFAULT_CONFIG = PROJECT_DIR / "sources" / "phase1-work-config.json"
DEFAULT_RAW = PROJECT_DIR / "sources" / "raw"
DEFAULT_OUTPUT = PROJECT_DIR / "sources" / "source-inventory.json"
DEFAULT_CACHE = PROJECT_DIR / "sources" / "cache" / "wikisource-api"

CHINESE_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                  "六": 6, "七": 7, "八": 8, "九": 9}
CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chinese_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    if all(char in CHINESE_DIGITS for char in value):
        result = 0
        for char in value:
            result = result * 10 + CHINESE_DIGITS[char]
        return result
    total = 0
    current = 0
    for char in value:
        if char in CHINESE_DIGITS:
            current = CHINESE_DIGITS[char]
        elif char in CHINESE_UNITS:
            unit = CHINESE_UNITS[char]
            total += (current or 1) * unit
            current = 0
    return total + current


def natural_page_key(title: str) -> tuple[int, int, int, str]:
    leaf = title.rsplit("/", 1)[-1]
    if re.search(r"(?:序|提要|目録|目錄)$", leaf):
        return (0, 0, 0, leaf)
    if leaf == "原病篇":
        return (1, 0, 0, leaf)
    if leaf == "卷首":
        return (2, 0, 0, leaf)
    match = re.search(r"卷第?([〇零一二三四五六七八九十百千0-9]+)([上中下]?)$", leaf)
    if not match:
        match = re.search(r"第([〇零一二三四五六七八九十百千0-9]+)卷$", leaf)
    if match:
        suffix = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
        suffix_order = {"": 0, "上": 1, "中": 2, "下": 3}.get(suffix, 9)
        return (3, chinese_number(match.group(1)), suffix_order, leaf)
    return (9, 0, 0, leaf)


def normalize_relationship(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return value
    return [part.strip() for part in value.split(",") if part.strip()]


def selected_works(
    candidates_path: Path, selection_path: Path, audit_path: Path
) -> list[dict[str, Any]]:
    candidates_payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
    candidates = {work["id"]: work for work in candidates_payload["works"]}
    audits = {work["id"]: work for work in audit_payload["works"]}

    works: list[dict[str, Any]] = []
    for source_id in selection["selected_candidate_ids"]:
        work = dict(candidates[source_id])
        audit = audits[source_id]
        selected = audit.get("selected_candidate") or {}
        page_info = audit.get("page_info") or {}
        if not selected or page_info.get("missing"):
            raise RuntimeError(f"Selected source has no resolved page: {source_id}")
        work["relationship"] = normalize_relationship(work["relationship"])
        work["page_title"] = page_info.get("title") or selected["title"]
        work["page_url"] = page_info.get("full_url") or selected.get("url")
        work["subpage_prefix"] = audit.get("subpage_prefix")
        works.append(work)

    for replacement in selection["added_replacements"]:
        work = dict(replacement)
        work["relationship"] = normalize_relationship(work["relationship"])
        works.append(work)

    if len(works) != selection["selection_count"]["total_unique_works"]:
        raise RuntimeError("Selected work count does not match source-selection.json")
    return works


def list_subpages(
    client: WikisourceClient, root_title: str, configured_prefix: str | None,
    exact_prefix: bool,
) -> list[str]:
    if configured_prefix:
        prefix = configured_prefix if exact_prefix else configured_prefix.rstrip("/") + "/"
    else:
        prefix = root_title.rstrip("/") + "/"
    titles: list[str] = []
    continuation: dict[str, Any] = {}
    while True:
        payload = client.query(
            "phase1-subpages",
            {
                "action": "query",
                "list": "allpages",
                "apnamespace": 0,
                "apprefix": prefix,
                "aplimit": "max",
                **continuation,
            },
        )
        titles.extend(item["title"] for item in payload.get("query", {}).get("allpages", []))
        continuation = payload.get("continue", {})
        if not continuation:
            break
    return sorted(set(titles), key=natural_page_key)


def chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def fetch_page_batch(client: WikisourceClient, titles: list[str]) -> dict[str, dict[str, Any]]:
    payload = client.query(
        "phase1-revision-content",
        {
            "action": "query",
            "prop": "info|revisions|categories",
            "inprop": "url",
            "rvprop": "ids|timestamp|size|sha1|content|contentmodel",
            "rvslots": "main",
            "cllimit": "max",
            "redirects": 1,
            "titles": "|".join(titles),
        },
    )
    query = payload.get("query", {})
    pages = query.get("pages", [])
    by_canonical = {page.get("title", ""): page for page in pages}
    aliases = {
        item["from"]: item["to"]
        for key in ("normalized", "redirects")
        for item in query.get(key, [])
    }
    result: dict[str, dict[str, Any]] = {}
    for requested in titles:
        resolved = requested
        visited: set[str] = set()
        while resolved in aliases and resolved not in visited:
            visited.add(resolved)
            resolved = aliases[resolved]
        page = by_canonical.get(resolved) or by_canonical.get(requested)
        if not page or "missing" in page:
            raise RuntimeError(f"Missing Wikisource page while freezing: {requested}")
        revisions = page.get("revisions", [])
        if not revisions:
            raise RuntimeError(f"No revision returned for Wikisource page: {requested}")
        revision = revisions[0]
        slot = revision.get("slots", {}).get("main", {})
        content = slot.get("content")
        if content is None:
            raise RuntimeError(f"No main-slot content returned for: {requested}")
        result[requested] = {
            "requested_title": requested,
            "title": page["title"],
            "page_id": page.get("pageid"),
            "page_url": page.get("fullurl") or (
                "https://zh.wikisource.org/wiki/" + urllib.parse.quote(page["title"].replace(" ", "_"))
            ),
            "revision_id": revision["revid"],
            "revision_timestamp": revision["timestamp"],
            "source_sha1": revision.get("sha1"),
            "source_size": revision.get("size"),
            "content_model": slot.get("contentmodel") or revision.get("contentmodel"),
            "categories": sorted(item["title"] for item in page.get("categories", [])),
            "content": content,
        }
    return result


def transcluded_page_references(wikitext: str, parent_title: str) -> list[dict[str, Any]]:
    """Expand ProofreadPage ``<pages>`` ranges into Page-namespace titles."""
    references: list[dict[str, Any]] = []
    for tag in re.findall(r"<pages\b[^>]*>", wikitext, flags=re.IGNORECASE):
        attributes = {
            name.lower(): value
            for name, _quote, value in re.findall(
                r"([\w-]+)\s*=\s*([\"'])(.*?)\2", tag, flags=re.DOTALL
            )
        }
        index = attributes.get("index")
        first = attributes.get("from")
        last = attributes.get("to")
        if not index or not first or not last or not first.isdigit() or not last.isdigit():
            raise RuntimeError(f"Unsupported ProofreadPage transclusion in {parent_title}: {tag}")
        start, end = int(first), int(last)
        if end < start or end - start > 2000:
            raise RuntimeError(f"Invalid ProofreadPage range in {parent_title}: {tag}")
        for scan_number in range(start, end + 1):
            references.append(
                {
                    "title": f"Page:{index}/{scan_number}",
                    "parent_title": parent_title,
                    "scan_number": scan_number,
                }
            )
    return references


def aggregate_pages_sha(pages: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for page in pages:
        digest.update(page["title"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(page["revision_id"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(page["raw_sha256"].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--delay", type=float, default=0.75)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--batch-size", type=int, default=5)
    args = parser.parse_args()

    config_payload = json.loads(args.config.read_text(encoding="utf-8"))
    work_configs = config_payload["works"]
    works = selected_works(args.candidates, args.selection, args.audit)
    client = WikisourceClient(args.cache_dir, args.delay, args.refresh)
    retrieved_at = utc_now()
    inventory_sources: list[dict[str, Any]] = []

    for work_index, work in enumerate(works, 1):
        source_id = work["id"]
        work_config = work_configs[source_id]
        root_title = work["page_title"]
        all_subpages = list_subpages(
            client,
            root_title,
            work.get("subpage_prefix"),
            bool(work_config.get("subpage_prefix_exact")),
        )
        expected_subpages = work_config.get("expected_subpages")
        if expected_subpages is not None and len(all_subpages) != expected_subpages:
            raise RuntimeError(
                f"{source_id}: expected {expected_subpages} subpages, found {len(all_subpages)}"
            )

        include_pattern = work_config.get("corpus_title_include_regex")
        if include_pattern:
            matcher = re.compile(include_pattern)
            included_subpages = [title for title in all_subpages if matcher.search(title)]
        else:
            included_subpages = list(all_subpages)
        expected_included = work_config.get("expected_included_subpages")
        if expected_included is not None and len(included_subpages) != expected_included:
            raise RuntimeError(
                f"{source_id}: expected {expected_included} included subpages, "
                f"found {len(included_subpages)}"
            )

        include_root = (
            config_payload["defaults"]["include_root_in_corpus_when_no_subpages_exist"]
            if not all_subpages
            else config_payload["defaults"]["include_root_in_corpus_when_subpages_exist"]
        )
        requested_titles = [root_title, *included_subpages]
        fetched: dict[str, dict[str, Any]] = {}
        for batch in chunks(requested_titles, max(1, args.batch_size)):
            fetched.update(fetch_page_batch(client, batch))

        transclusion_refs_by_parent: dict[str, list[dict[str, Any]]] = {}
        all_transclusion_titles: list[str] = []
        for requested_title in requested_titles:
            references = transcluded_page_references(
                fetched[requested_title]["content"], requested_title
            )
            transclusion_refs_by_parent[requested_title] = references
            all_transclusion_titles.extend(item["title"] for item in references)
        if len(all_transclusion_titles) != len(set(all_transclusion_titles)):
            raise RuntimeError(f"{source_id}: duplicate ProofreadPage transclusion detected")
        transcluded_fetched: dict[str, dict[str, Any]] = {}
        for batch in chunks(all_transclusion_titles, max(1, args.batch_size)):
            transcluded_fetched.update(fetch_page_batch(client, batch))

        ordered_pages: list[tuple[dict[str, Any], str, bool, str | None, int | None]] = []
        for source_page_index, requested_title in enumerate(requested_titles):
            refs = transclusion_refs_by_parent[requested_title]
            source_role = "root" if source_page_index == 0 else "subpage"
            source_included = (include_root if source_page_index == 0 else True) and not refs
            ordered_pages.append(
                (fetched[requested_title], source_role, source_included, None, None)
            )
            for reference in refs:
                ordered_pages.append(
                    (
                        transcluded_fetched[reference["title"]],
                        "transcluded-page",
                        True,
                        requested_title,
                        reference["scan_number"],
                    )
                )

        work_dir = args.raw_dir / source_id
        work_dir.mkdir(parents=True, exist_ok=True)
        page_records: list[dict[str, Any]] = []
        for page_index, (page, role, page_included, parent_title, scan_number) in enumerate(ordered_pages):
            page = dict(page)
            content_bytes = page.pop("content").encode("utf-8")
            filename = f"{page_index:04d}.wikitext"
            snapshot_path = work_dir / filename
            snapshot_path.write_bytes(content_bytes)
            page_record = {
                **page,
                "role": role,
                "include_in_corpus": page_included,
                "retrieved_at": retrieved_at,
                "raw_wikitext_path": snapshot_path.relative_to(PROJECT_DIR).as_posix(),
                "raw_sha256": sha256_bytes(content_bytes),
            }
            if parent_title is not None:
                page_record["parent_title"] = parent_title
                page_record["scan_number"] = scan_number
            page_records.append(page_record)

        source_manifest = {
            "id": source_id,
            "layer": work["layer"],
            "canon": work["canon"],
            "target_works": work["target_works"],
            "author": work["author"],
            "title": work["title"],
            "relationship": work["relationship"],
            "provider": "zh-wikisource",
            "page_title": page_records[0]["title"],
            "page_url": page_records[0]["page_url"],
            "edition_label": work_config["edition_label"],
            "retrieved_at": retrieved_at,
            "license": config_payload["license"],
            "textual_status": work_config.get(
                "textual_status", config_payload["defaults"]["textual_status"]
            ),
            "quality_note": work_config.get("quality_note", ""),
            "scope_note": work_config.get("scope_note", ""),
            "speaker_method": config_payload["defaults"]["speaker_method"],
            "subpage_prefix": work.get("subpage_prefix") or root_title.rstrip("/") + "/",
            "enumerated_subpage_count": len(all_subpages),
            "included_subpage_count": len(included_subpages),
            "transcluded_page_count": len(all_transclusion_titles),
            "excluded_subpage_titles": [
                title for title in all_subpages if title not in set(included_subpages)
            ],
            "expected_structure": work_config.get("expected_structure"),
            "pages": page_records,
            "aggregate_raw_sha256": aggregate_pages_sha(page_records),
        }
        (work_dir / "manifest.json").write_text(
            json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        inventory_sources.append(source_manifest)
        print(
            f"[{work_index:02d}/{len(works)}] {source_id}: "
            f"{len(page_records)} snapshots, {len(included_subpages)} corpus subpages, "
            f"{len(all_transclusion_titles)} scan pages"
        )

    inventory = {
        "schema_version": 1,
        "generated_at": retrieved_at,
        "generator": "builder/fetch_wikisource.py",
        "selection": args.selection.relative_to(PROJECT_DIR).as_posix(),
        "config": args.config.relative_to(PROJECT_DIR).as_posix(),
        "sources": inventory_sources,
    }
    args.output.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Frozen {len(inventory_sources)} sources -> {args.output}")


if __name__ == "__main__":
    main()
