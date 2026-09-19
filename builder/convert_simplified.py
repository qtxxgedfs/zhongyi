#!/usr/bin/env python3
"""Generate traditional working, simplified display, and search-only text fields."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from opencc import OpenCC

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_DIR / "build" / "intermediate" / "extracted"
DEFAULT_OUTPUT = PROJECT_DIR / "build" / "intermediate" / "converted"
DEFAULT_OVERRIDES = PROJECT_DIR / "sources" / "normalization" / "conversion-overrides.json"
CJK_OR_ALNUM_RE = re.compile(r"[^0-9a-z\u3400-\u9fff\U00020000-\U0003134f]+", flags=re.I)
PLACEHOLDER_RE = re.compile(r"〔(?:未识别字\d+|原文缺字|四库缺字\d+)〕")


def records(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def aggregate_hash(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def apply_replacements(text: str, replacements: list[dict[str, str]], stats: Counter[str]) -> str:
    for item in replacements:
        count = text.count(item["from"])
        if count:
            text = text.replace(item["from"], item["to"])
            stats[f"replacement:{item['from']}->{item['to']}"] += count
    return text


def apply_contextual_rules(text: str, rules: list[dict[str, str]], stats: Counter[str]) -> str:
    for index, rule in enumerate(rules, 1):
        text, count = re.subn(rule["pattern"], rule["replacement"], text)
        if count:
            stats[f"contextual_rule:{index}"] += count
    return text


def normalize_search(text: str, search_replacements: list[dict[str, str]]) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = PLACEHOLDER_RE.sub("", text)
    for item in search_replacements:
        text = text.replace(item["from"], item["to"])
    return CJK_OR_ALNUM_RE.sub("", text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    args = parser.parse_args()

    overrides = json.loads(args.overrides.read_text(encoding="utf-8"))
    display_replacements = overrides["display_replacements"]
    contextual_display_rules = overrides.get("contextual_display_rules", [])
    search_replacements = overrides["search_only_replacements"]
    to_traditional = OpenCC("s2t")
    to_simplified = OpenCC("t2s")
    version = importlib.metadata.version("opencc-python-reimplemented")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []

    for input_path in sorted(args.input_dir.glob("*.jsonl")):
        stats: Counter[str] = Counter()
        converted: list[dict[str, Any]] = []
        for block in records(input_path):
            source = unicodedata.normalize("NFC", block["text_source"])
            traditional = unicodedata.normalize("NFC", to_traditional.convert(source))
            simplified = unicodedata.normalize("NFC", to_simplified.convert(traditional))
            simplified = apply_replacements(simplified, display_replacements, stats)
            simplified = apply_contextual_rules(simplified, contextual_display_rules, stats)
            search = normalize_search(simplified, search_replacements)
            location_fields: dict[str, str] = {}
            for field in ("volume", "section", "subsection", "speaker"):
                source_value = block[field]
                traditional_value = unicodedata.normalize("NFC", to_traditional.convert(source_value))
                simplified_value = unicodedata.normalize("NFC", to_simplified.convert(traditional_value))
                location_fields[f"{field}_source"] = source_value
                location_fields[f"{field}_traditional"] = traditional_value
                location_fields[field] = simplified_value
            converted.append(
                {
                    **block,
                    **location_fields,
                    "text_traditional": traditional,
                    "text_simplified": simplified,
                    "text_search": search,
                }
            )
            stats["source_characters"] += len(source)
            stats["traditional_characters"] += len(traditional)
            stats["simplified_characters"] += len(simplified)
            stats["search_characters"] += len(search)
            stats["traditional_diff_characters"] += sum(
                left != right for left, right in zip(source, traditional)
            ) + abs(len(source) - len(traditional))
            stats["simplified_diff_characters"] += sum(
                left != right for left, right in zip(traditional, simplified)
            ) + abs(len(traditional) - len(simplified))

        output_path = args.output_dir / input_path.name
        with output_path.open("w", encoding="utf-8", newline="\n") as handle:
            for block in converted:
                handle.write(json.dumps(block, ensure_ascii=False, separators=(",", ":")) + "\n")
        summaries.append(
            {
                "source_id": input_path.stem,
                "block_count": len(converted),
                "statistics": dict(sorted(stats.items())),
                "source_aggregate_sha256": aggregate_hash(x["text_source"] for x in converted),
                "traditional_aggregate_sha256": aggregate_hash(x["text_traditional"] for x in converted),
                "simplified_aggregate_sha256": aggregate_hash(x["text_simplified"] for x in converted),
                "search_aggregate_sha256": aggregate_hash(x["text_search"] for x in converted),
            }
        )
        print(f"{input_path.stem}: converted {len(converted)} blocks")

    summary = {
        "schema_version": 1,
        "engine": "opencc-python-reimplemented",
        "engine_version": version,
        "traditional_config": "s2t",
        "simplified_config": "t2s",
        "overrides": args.overrides.relative_to(PROJECT_DIR).as_posix(),
        "sources": summaries,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Converted {len(summaries)} sources with OpenCC {version}")


if __name__ == "__main__":
    main()
