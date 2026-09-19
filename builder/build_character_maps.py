#!/usr/bin/env python3
"""Freeze Wikisource character helpers and build auditable normalization maps."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
BUILDER_DIR = Path(__file__).resolve().parent
if str(BUILDER_DIR) not in sys.path:
    sys.path.insert(0, str(BUILDER_DIR))

from audit_wikisource import WikisourceClient  # noqa: E402
from fetch_wikisource import fetch_page_batch  # noqa: E402

DEFAULT_INVENTORY = PROJECT_DIR / "sources" / "source-inventory.json"
DEFAULT_RAW_DEPENDENCIES = PROJECT_DIR / "sources" / "raw" / "_dependencies"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "sources" / "normalization"
DEFAULT_CACHE = PROJECT_DIR / "sources" / "cache" / "wikisource-api"
ENTRY_RE = re.compile(
    r"^\['(?P<code>\d+)'\]\s*=\s*\{\s*"
    r"(?P<primary>nil|\"(?:\\.|[^\"])*\")"
    r"(?:\s*,\s*(?P<fallback>\"(?:\\.|[^\"])*\"))?\s*\}\s*,?\s*$",
    flags=re.MULTILINE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_lua_string(token: str | None) -> str | None:
    if token is None or token == "nil":
        return None
    # The SKchar table uses JSON-compatible double-quoted strings.
    return json.loads(token)


def used_skchar_codes(inventory: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    usages: dict[str, dict[str, set[str]]] = {"SKchar": {}, "SKchar2": {}}
    for source in inventory["sources"]:
        for page in source["pages"]:
            if not page["include_in_corpus"]:
                continue
            text = (PROJECT_DIR / page["raw_wikitext_path"]).read_text(encoding="utf-8")
            for template in usages:
                pattern = r"\{\{\s*" + template + r"\s*\|\s*([0-9]+)"
                for code in re.findall(pattern, text, flags=re.I):
                    usages[template].setdefault(code, set()).add(source["id"])
    return {
        template: {code: sorted(source_ids) for code, source_ids in usage.items()}
        for template, usage in usages.items()
    }


def parse_module_entries(module: str) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {
        code: {"value": f"〔未识别字{code}〕", "resolution": "unresolved_placeholder"}
        for code in re.findall(r"^\['(\d+)'\]\s*=\s*\{\s*\}\s*,?\s*$", module, flags=re.MULTILINE)
    }
    for match in ENTRY_RE.finditer(module):
        primary = decode_lua_string(match.group("primary"))
        fallback = decode_lua_string(match.group("fallback"))
        if primary:
            value = primary
            resolution = "module_unicode"
        elif fallback:
            value = fallback
            resolution = "module_descriptive_variant"
        else:
            value = f"〔未识别字{match.group('code')}〕"
            resolution = "unresolved_placeholder"
        entries[match.group("code")] = {"value": value, "resolution": resolution}
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DEPENDENCIES)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    usage = used_skchar_codes(inventory)
    client = WikisourceClient(args.cache_dir, args.delay, args.refresh)
    fetched = fetch_page_batch(
        client, ["Template:SKchar", "Module:SKchar", "Template:SKchar2", "Module:SKchar2"]
    )
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = utc_now()
    dependencies: list[dict[str, Any]] = []

    filenames = {
        "Template:SKchar": "Template-SKchar.wikitext",
        "Module:SKchar": "Module-SKchar.lua",
        "Template:SKchar2": "Template-SKchar2.wikitext",
        "Module:SKchar2": "Module-SKchar2.lua",
    }
    for requested, filename in filenames.items():
        page = fetched[requested]
        content = page["content"].encode("utf-8")
        path = args.raw_dir / filename
        path.write_bytes(content)
        dependencies.append(
            {
                "title": page["title"],
                "page_url": page["page_url"],
                "revision_id": page["revision_id"],
                "revision_timestamp": page["revision_timestamp"],
                "source_sha1": page["source_sha1"],
                "retrieved_at": retrieved_at,
                "raw_path": path.relative_to(PROJECT_DIR).as_posix(),
                "raw_sha256": sha256(content),
            }
        )

    selected_maps: dict[str, dict[str, dict[str, Any]]] = {}
    for template in ("SKchar", "SKchar2"):
        all_entries = parse_module_entries(fetched[f"Module:{template}"]["content"])
        missing = sorted(set(usage[template]) - set(all_entries), key=int)
        if missing:
            raise RuntimeError(f"Used {template} codes missing from frozen module: {missing}")
        selected_maps[template] = {
            code: {**all_entries[code], "source_ids": usage[template][code]}
            for code in sorted(usage[template], key=int)
        }
    map_payload = {
        "schema_version": 1,
        "generated_at": retrieved_at,
        "description": "Resolved from fixed revisions of Wikisource character modules. Descriptive variants are explicit fallbacks when a module itself uses an image glyph.",
        "dependencies": dependencies,
        "used_code_count": sum(len(entries) for entries in selected_maps.values()),
        "maps": selected_maps,
    }
    (args.output_dir / "skchar-map.json").write_text(
        json.dumps(map_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    repairs = {
        "schema_version": 1,
        "generated_at": retrieved_at,
        "repairs": [
            {
                "source_id": "core-jingui",
                "source_sequence": "\\uf544\\uf6a5\\uf545",
                "replacement": "㽲",
                "context": "产后腹中㽲痛，当归生姜羊肉汤主之",
                "basis": "Cross-checked against the same passage in Wikisource's 四库全书《御纂医宗金鉴》, which encodes U+3F72 㽲.",
            },
            {
                "source_id": "core-nanjing",
                "source_sequence": "\\uf069",
                "replacement": "啘",
                "context": "掌中热而啘",
                "basis": "Cross-checked against multiple Wikisource transcriptions quoting 难经第十六难; 滑寿注释为‘啘，干呕也’.",
            },
        ],
    }
    (args.output_dir / "manual-character-repairs.json").write_text(
        json.dumps(repairs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "source-dependencies.json").write_text(
        json.dumps({"schema_version": 1, "dependencies": dependencies}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Resolved {sum(len(entries) for entries in selected_maps.values())} used character codes; "
        f"froze {len(dependencies)} dependencies"
    )


if __name__ == "__main__":
    main()
