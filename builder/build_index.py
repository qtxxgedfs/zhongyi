#!/usr/bin/env python3
"""Build the candidate runtime SQLite corpus from clean, citable passages only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from opencc import OpenCC

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = PROJECT_DIR / "sources" / "source-inventory.json"
DEFAULT_PROCESSED = PROJECT_DIR / "sources" / "processed"
DEFAULT_ALIASES = PROJECT_DIR / "sources" / "search-aliases.json"
DEFAULT_QUALITY = PROJECT_DIR / "sources" / "quality-report.json"
DEFAULT_EXCLUSIONS = PROJECT_DIR / "sources" / "corpus-exclusions.json"
DEFAULT_SCHEMA = PROJECT_DIR / "schemas" / "classics.sql"
DEFAULT_OUTPUT = PROJECT_DIR / "build" / "classics.sqlite"
DEFAULT_MANIFEST = PROJECT_DIR / "build" / "classics-index-manifest.json"
SEARCH_CHAR_RE = re.compile(r"[^0-9a-z\u3400-\u9fff\U00020000-\U0003134f]+", flags=re.I)
SEARCH_PHRASE_OVERRIDES = {"五藏": "五脏", "欬": "咳", "痺": "痹"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(value: str, to_simplified: OpenCC) -> str:
    normalized = to_simplified.convert(value).lower()
    for source, target in SEARCH_PHRASE_OVERRIDES.items():
        normalized = normalized.replace(source, target)
    return SEARCH_CHAR_RE.sub("", normalized)


def bigram_tokens(value: str) -> str:
    if not value:
        return ""
    if len(value) == 1:
        return value
    return " ".join(dict.fromkeys(value[index : index + 2] for index in range(len(value) - 1)))


def binary_hash(value: str) -> bytes:
    return bytes.fromhex(value)


def insert_metadata(
    connection: sqlite3.Connection,
    inventory: dict[str, Any],
    processed: dict[str, dict[str, Any]],
    aliases: dict[str, Any],
    to_simplified: OpenCC,
) -> dict[tuple[str, str, int], int]:
    for source in inventory["sources"]:
        source_id = source["id"]
        summary = processed[source_id]
        connection.execute(
            """
            INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                source["provider"],
                source["page_title"],
                source["page_url"],
                source["retrieved_at"],
                json.dumps(source["license"], ensure_ascii=False, separators=(",", ":")),
                source["textual_status"],
                binary_hash(source["aggregate_raw_sha256"]),
                binary_hash(summary["traditional_aggregate_sha256"]),
                binary_hash(summary["simplified_aggregate_sha256"]),
                binary_hash(summary["citable_simplified_sha256"]),
                summary["passage_count"],
                summary["citable_passage_count"],
                summary["quarantined_passage_count"],
            ),
        )
        connection.execute(
            """
            INSERT INTO works(id, canon, layer, title, author, relationship_json, edition_label, source_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                source["canon"],
                source["layer"],
                source["title"],
                source["author"],
                json.dumps(source["relationship"], ensure_ascii=False, separators=(",", ":")),
                source["edition_label"],
                source_id,
            ),
        )
        connection.executemany(
            "INSERT INTO work_targets(work_id, target_work) VALUES (?, ?)",
            [(source_id, target) for target in source["target_works"]],
        )

    page_ids: dict[tuple[str, str, int], int] = {}
    for source in inventory["sources"]:
        for page in source["pages"]:
            cursor = connection.execute(
                """
                INSERT INTO source_pages(source_id, title_source, title_simplified, revision_id, raw_sha256)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    source["id"],
                    page["title"],
                    to_simplified.convert(page["title"]),
                    page["revision_id"],
                    binary_hash(page["raw_sha256"]),
                ),
            )
            page_ids[(source["id"], page["title"], page["revision_id"])] = cursor.lastrowid

    for item in aliases["aliases"]:
        connection.execute(
            """
            INSERT INTO aliases(alias, normalized_alias, canonical, kind, work_id, target_work, canon)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["alias"],
                normalize(item["alias"], to_simplified),
                item["canonical"],
                item["kind"],
                item.get("work_id"),
                item.get("target_work"),
                item.get("canon"),
            ),
        )
    return page_ids


def insert_passages(
    connection: sqlite3.Connection,
    inventory: dict[str, Any],
    processed_dir: Path,
    to_simplified: OpenCC,
    page_ids: dict[tuple[str, str, int], int],
) -> tuple[int, int]:
    work_metadata = {source["id"]: source for source in inventory["sources"]}
    inserted = 0
    skipped_quarantine = 0
    passage_sql = """
        INSERT INTO passages(
            id, work_id, sequence, location_id, source_page_id, text_simplified, content_sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    fts_sql = """
        INSERT INTO passage_fts(rowid, title_tokens, body_tokens)
        VALUES (?, ?, ?)
    """
    location_ids: dict[tuple[str, str, str, str, str, str], int] = {}
    for source_id, source in work_metadata.items():
        path = processed_dir / source_id / "passages.jsonl"
        title_prefix = normalize(source["title"] + source["author"], to_simplified)
        for passage in read_jsonl(path):
            if not passage["citation_allowed"] or not passage["search_allowed"]:
                skipped_quarantine += 1
                continue
            if passage["quality_status"] != "clean" or not passage["text_search"]:
                raise RuntimeError(f"Invalid citable passage for indexing: {passage['id']}")
            location_key = (
                source_id,
                passage["volume"],
                passage["section"],
                passage["subsection"],
                passage["speaker"],
                passage["speaker_type"],
            )
            location_id = location_ids.get(location_key)
            if location_id is None:
                location_cursor = connection.execute(
                    """
                    INSERT INTO locations(work_id, volume, section, subsection, speaker, speaker_type)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    location_key,
                )
                location_id = location_cursor.lastrowid
                location_ids[location_key] = location_id
            page_key = (source_id, passage["source_page_title"], passage["source_revision_id"])
            if page_key not in page_ids:
                raise RuntimeError(f"Passage references an unknown fixed page: {passage['id']} {page_key}")
            passage_cursor = connection.execute(
                passage_sql,
                (
                    passage["id"],
                    source_id,
                    passage["sequence"],
                    location_id,
                    page_ids[page_key],
                    passage["text_simplified"],
                    binary_hash(passage["content_sha256"]),
                ),
            )
            title_text = normalize(
                title_prefix
                + passage["volume"]
                + passage["section"]
                + passage["subsection"]
                + passage["speaker"],
                to_simplified,
            )
            connection.execute(
                fts_sql,
                (
                    passage_cursor.lastrowid,
                    bigram_tokens(title_text),
                    bigram_tokens(normalize(passage["text_search"], to_simplified)),
                ),
            )
            inserted += 1
            if inserted % 5000 == 0:
                print(f"Indexed {inserted} citable passages...")
    return inserted, skipped_quarantine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED)
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    parser.add_argument("--quality", type=Path, default=DEFAULT_QUALITY)
    parser.add_argument("--exclusions", type=Path, default=DEFAULT_EXCLUSIONS)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    inventory = load_json(args.inventory)
    quality = load_json(args.quality)
    processed_payload = load_json(args.processed_dir / "summary.json")
    processed = {item["source_id"]: item for item in processed_payload["sources"]}
    aliases = load_json(args.aliases)
    if quality["overall"].get("citable_corpus_status") != "pass":
        raise SystemExit("Refusing to index: citable corpus quality gate is not pass")
    expected_citable = quality["overall"]["citable_passage_count"]
    expected_quarantine = quality["overall"]["quarantined_passage_count"]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    started = time.perf_counter()
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(
            """
            PRAGMA page_size = 8192;
            PRAGMA journal_mode = OFF;
            PRAGMA synchronous = OFF;
            PRAGMA temp_store = MEMORY;
            PRAGMA cache_size = -200000;
            """
        )
        connection.executescript(args.schema.read_text(encoding="utf-8"))
        connection.execute("INSERT INTO passage_fts(passage_fts, rank) VALUES ('automerge', 0)")
        to_simplified = OpenCC("t2s")
        with connection:
            page_ids = insert_metadata(connection, inventory, processed, aliases, to_simplified)
            inserted, skipped = insert_passages(
                connection, inventory, args.processed_dir, to_simplified, page_ids
            )
            if inserted != expected_citable:
                raise RuntimeError(f"Indexed {inserted}; expected {expected_citable}")
            if skipped != expected_quarantine:
                raise RuntimeError(f"Skipped {skipped}; expected quarantine {expected_quarantine}")
            metadata = {
                "schema_version": "2",
                "build_status": "candidate" if quality["overall"]["release_gate_status"] != "pass" else "final",
                "built_at": quality["generated_at"],
                "source_count": str(len(inventory["sources"])),
                "passage_count": str(inserted),
                "quarantined_passages_excluded": str(skipped),
                "quality_report_sha256": sha256_file(args.quality),
                "corpus_exclusions_sha256": sha256_file(args.exclusions),
                "source_inventory_sha256": sha256_file(args.inventory),
                "processed_summary_sha256": sha256_file(args.processed_dir / "summary.json"),
                "search_aliases_sha256": sha256_file(args.aliases),
                "schema_sha256": sha256_file(args.schema),
                "search_index": "pretokenized-unique-overlapping-bigrams-fts5",
            }
            connection.executemany("INSERT INTO schema_info(key, value) VALUES (?, ?)", metadata.items())
        connection.execute("INSERT INTO passage_fts(passage_fts) VALUES ('optimize')")
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    finally:
        connection.close()
    os.replace(temporary, args.output)
    elapsed = time.perf_counter() - started
    size = args.output.stat().st_size
    manifest = {
        "schema_version": 1,
        "status": "candidate" if quality["overall"]["release_gate_status"] != "pass" else "final",
        "generated_at": quality["generated_at"],
        "database_path": str(args.output.relative_to(PROJECT_DIR)).replace("\\", "/"),
        "database_sha256": sha256_file(args.output),
        "database_size_bytes": size,
        "source_count": len(inventory["sources"]),
        "citable_passage_count": expected_citable,
        "quarantined_passages_excluded": expected_quarantine,
        "index_algorithm": "pretokenized-unique-overlapping-bigrams-fts5",
        "inputs": {
            "quality_report_sha256": sha256_file(args.quality),
            "corpus_exclusions_sha256": sha256_file(args.exclusions),
            "source_inventory_sha256": sha256_file(args.inventory),
            "processed_summary_sha256": sha256_file(args.processed_dir / "summary.json"),
            "search_aliases_sha256": sha256_file(args.aliases),
            "schema_sha256": sha256_file(args.schema),
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Built {args.output}: {expected_citable} citable passages, "
        f"{expected_quarantine} quarantined passages excluded, {size / 1024 / 1024:.1f} MiB, {elapsed:.1f}s"
    )


if __name__ == "__main__":
    main()
