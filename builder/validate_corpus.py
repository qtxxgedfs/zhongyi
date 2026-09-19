#!/usr/bin/env python3
"""Validate Phase 1 corpus integrity, completeness, cleanup, and source quality."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = PROJECT_DIR / "sources" / "source-inventory.json"
DEFAULT_PROCESSED = PROJECT_DIR / "sources" / "processed"
DEFAULT_EXTRACT_SUMMARY = PROJECT_DIR / "build" / "intermediate" / "extracted" / "summary.json"
DEFAULT_CONVERT_SUMMARY = PROJECT_DIR / "build" / "intermediate" / "converted" / "summary.json"
DEFAULT_OUTPUT = PROJECT_DIR / "sources" / "quality-report.json"
DEFAULT_COMPLETENESS = PROJECT_DIR / "sources" / "completeness-manifest.json"
DEFAULT_MARKDOWN = PROJECT_DIR / "docs" / "phase1-quality-report.md"
HEADING_RE = re.compile(r"^\s*=+\s*(.*?)\s*=+\s*$", flags=re.MULTILINE)
VOLUME_RE = re.compile(r"卷(?:第)?(?:[〇零一二三四五六七八九十百千]+|\d+)")
PROOFREAD_RE = re.compile(r"<pagequality\s+level=[\"']?(\d)", flags=re.I)
PUA_RANGES = (
    (0xE000, 0xF8FF),
    (0xF0000, 0xFFFFD),
    (0x100000, 0x10FFFD),
)
BLOCKING_PATTERNS = {
    "unicode-replacement-character": re.compile("�"),
    "residual-wiki-template": re.compile(r"\{\{|\}\}"),
    "residual-html-or-pseudo-tag": re.compile(r"</?(?:篇名|目[录錄]|noinclude|onlyinclude|poem|ref)\b", flags=re.I),
    "residual-image-artifact": re.compile(r"\\p[^\\\s]*\.bmp|\.bmp\\r", flags=re.I),
    "null-byte": re.compile("\x00"),
}
WARNING_PATTERNS = {
    "known-ui-text-intrusion": re.compile("滚动条|滾動條"),
    "legacy-glyph-placeholder-ht-kt": re.compile(r"(?<![A-Za-z])(?:HT|KT)(?![A-Za-z])"),
    "explicit-missing-glyph": re.compile(r"〔(?:未识别字\d+|原文缺字(?::[^〕]+)?|四库缺字\d+)〕"),
    "mojibake-keyword": re.compile("锟斤拷|烫烫烫|屯屯屯"),
}


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


def has_pua(text: str) -> bool:
    return any(start <= ord(char) <= end for char in text for start, end in PUA_RANGES)


def source_raw_metrics(source: dict[str, Any]) -> dict[str, Any]:
    headings: list[str] = []
    volumes: set[str] = set()
    proofread_levels: Counter[str] = Counter()
    hash_mismatches: list[str] = []
    included_raw_characters = 0
    low_quality_categories: Counter[str] = Counter()
    for page in source["pages"]:
        path = PROJECT_DIR / page["raw_wikitext_path"]
        if sha256_file(path) != page["raw_sha256"]:
            hash_mismatches.append(page["title"])
        for category in page.get("categories", []):
            percentage = re.fullmatch(r"Category:(25|50|75)%", category)
            if percentage:
                low_quality_categories[percentage.group(1) + "%"] += 1
        if not page["include_in_corpus"]:
            continue
        raw = path.read_text(encoding="utf-8")
        included_raw_characters += len(raw)
        headings.extend(HEADING_RE.findall(raw))
        for level in PROOFREAD_RE.findall(raw):
            proofread_levels[level] += 1
        logical_title = page.get("parent_title") or page["title"]
        leaf = logical_title.rsplit("/", 1)[-1]
        if VOLUME_RE.search(leaf):
            volumes.add(leaf)
    return {
        "raw_hash_mismatch_count": len(hash_mismatches),
        "raw_hash_mismatch_titles": hash_mismatches[:10],
        "included_raw_characters": included_raw_characters,
        "heading_count": len(headings),
        "distinct_volume_count": len(volumes),
        "proofread_page_levels": dict(sorted(proofread_levels.items())),
        "low_quality_category_pages": dict(sorted(low_quality_categories.items())),
    }


def structural_result(source: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    expected = source.get("expected_structure")
    if not expected:
        observed = sum(page["include_in_corpus"] for page in source["pages"])
        return {
            "kind": "nonempty-corpus",
            "expected_count": None,
            "minimum_accepted": 1,
            "observed_count": observed,
            "status": "pass" if observed >= 1 else "fail",
            "method": "included logical or transcluded page count",
        }
    kind = expected["kind"]
    if kind == "volume":
        observed = raw["distinct_volume_count"]
        method = "distinct included page/parent title containing a volume label"
    else:
        observed = raw["heading_count"]
        method = "MediaWiki heading count in included snapshots; includes labeled prefaces where present"
    return {
        **expected,
        "observed_count": observed,
        "status": "pass" if observed >= expected["minimum_accepted"] else "fail",
        "method": method,
    }


def scan_passages(path: Path) -> dict[str, Any]:
    blocking: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    citable_warnings: Counter[str] = Counter()
    blocking_examples: dict[str, list[str]] = {}
    warning_examples: dict[str, list[str]] = {}
    speaker_types: Counter[str] = Counter()
    speakers: Counter[str] = Counter()
    duplicate_hashes: Counter[str] = Counter()
    passage_count = 0
    citable_count = 0
    quarantine_count = 0
    total_characters = 0
    citable_characters = 0
    quarantine_characters = 0
    previous_id = None
    previous_record: dict[str, Any] | None = None
    previous_citable_record: dict[str, Any] | None = None
    broken_links = 0
    broken_citable_links = 0

    for record in read_jsonl(path):
        passage_count += 1
        text = record["text_simplified"]
        citable = record.get("citation_allowed", True)
        searchable = record.get("search_allowed", True)
        total_characters += len(text)
        speaker_types[record["speaker_type"]] += 1
        speakers[record["speaker"]] += 1
        duplicate_hashes[record["content_sha256"]] += 1
        if citable:
            citable_count += 1
            citable_characters += len(text)
            if record.get("quality_status") != "clean" or not searchable:
                blocking["invalid-citable-quality-status"] += 1
            expected_previous_citable = (
                previous_citable_record["id"] if previous_citable_record is not None else None
            )
            if record.get("previous_citable_id") != expected_previous_citable:
                broken_citable_links += 1
            if previous_citable_record is not None and previous_citable_record.get("next_citable_id") != record["id"]:
                broken_citable_links += 1
            previous_citable_record = record
        else:
            quarantine_count += 1
            quarantine_characters += len(text)
            if record.get("quality_status") != "quarantined" or searchable:
                blocking["invalid-quarantine-status"] += 1
            if record.get("text_search"):
                blocking["quarantine-search-text-leak"] += 1
            if record.get("previous_citable_id") is not None or record.get("next_citable_id") is not None:
                blocking["quarantine-citable-link-leak"] += 1
            if not record.get("quality_flags"):
                blocking["quarantine-without-disclosed-reason"] += 1

        if unicodedata.normalize("NFC", text) != text:
            blocking["non-nfc-display-text"] += 1
        if has_pua(text) or has_pua(record["text_traditional"]):
            blocking["private-use-character"] += 1
        for name, pattern in BLOCKING_PATTERNS.items():
            if pattern.search(text):
                blocking[name] += 1
                blocking_examples.setdefault(name, [])
                if len(blocking_examples[name]) < 3:
                    blocking_examples[name].append(text[:180])
        for name, pattern in WARNING_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                warnings[name] += len(matches)
                if citable:
                    citable_warnings[name] += len(matches)
                warning_examples.setdefault(name, [])
                if len(warning_examples[name]) < 3:
                    warning_examples[name].append(text[:180])
        if record["previous_id"] != previous_id:
            broken_links += 1
        if previous_record is not None and previous_record["next_id"] != record["id"]:
            broken_links += 1
        previous_id = record["id"]
        previous_record = record
    if previous_record is not None and previous_record["next_id"] is not None:
        broken_links += 1
    if previous_citable_record is not None and previous_citable_record.get("next_citable_id") is not None:
        broken_citable_links += 1
    if broken_links:
        blocking["broken-passage-links"] = broken_links
    if broken_citable_links:
        blocking["broken-citable-links"] = broken_citable_links
    duplicate_instances = sum(count - 1 for count in duplicate_hashes.values() if count > 1)
    return {
        "passage_count": passage_count,
        "citable_passage_count": citable_count,
        "quarantined_passage_count": quarantine_count,
        "simplified_character_count": total_characters,
        "citable_character_count": citable_characters,
        "quarantined_character_count": quarantine_characters,
        "blocking_issues": dict(sorted(blocking.items())),
        "blocking_examples": blocking_examples,
        "warnings": dict(sorted(warnings.items())),
        "citable_warnings": dict(sorted(citable_warnings.items())),
        "warning_examples": warning_examples,
        "speaker_type_counts": dict(speaker_types.most_common()),
        "top_speakers": dict(speakers.most_common(12)),
        "duplicate_passage_instances": duplicate_instances,
    }


def upstream_quality_blocks(source: dict[str, Any], raw: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    percentages = raw["low_quality_category_pages"]
    # These are release-quality blockers, not hash-lock blockers. They require either
    # a second licensed base or documented manual sampling before final publication.
    if source["layer"] == "core" and (percentages.get("25%") or percentages.get("50%")):
        reasons.append("core source has upstream 25%/50% quality category and lacks completed second-base collation")
    levels = raw["proofread_page_levels"]
    if int(levels.get("0", 0)) + int(levels.get("1", 0)):
        reasons.append(
            f"ProofreadPage contains {int(levels.get('0', 0)) + int(levels.get('1', 0))} unproofread/problem pages"
        )
    return reasons


def markdown_report(report: dict[str, Any], completeness: dict[str, Any]) -> str:
    overall = report["overall"]
    lines = [
        "# Phase 1 语料质量报告",
        "",
        f"生成时间：`{report['generated_at']}`",
        "",
        "## 结论",
        "",
        f"- 固定修订与原始哈希完整性：**{overall['raw_integrity_status']}**",
        f"- 结构完整性：**{overall['structural_status']}**",
        f"- 清洗与隔离检查：**{overall['cleanup_status']}**",
        f"- 可引用语料未解字检查：**{overall['citable_corpus_status']}**",
        f"- 发布质量闸门：**{overall['release_gate_status']}**",
        "",
        "当前语料已经可以作为**固定修订的构建候选**继续索引和抽检；但发布质量闸门未通过时，",
        "不得把候选来源锁称为最终无条件发布锁，也不得把工作底本称为唯一权威文本。",
        "",
        "## 总量",
        "",
        f"- 来源：{overall['source_count']} 种",
        f"- 固定页面快照：{overall['snapshot_page_count']} 页",
        f"- 纳入语料页面：{overall['included_page_count']} 页",
        f"- 全部段落：{overall['passage_count']} 条",
        f"- 可引用段落：{overall['citable_passage_count']} 条",
        f"- 隔离段落：{overall['quarantined_passage_count']} 条",
        f"- 全部简体显示字符：{overall['simplified_character_count']:,}",
        f"- 隔离字符：{overall['quarantined_character_count']:,}",
        "",
        "## 完整性清单",
        "",
        "| 来源 | 结构类型 | 预期/最低 | 观察值 | 状态 |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in completeness["sources"]:
        expected = "—" if item["expected_count"] is None else str(item["expected_count"])
        lines.append(
            f"| `{item['source_id']}` | {item['kind']} | {expected}/{item['minimum_accepted']} | "
            f"{item['observed_count']} | {item['status']} |"
        )
    lines.extend(["", "## 阻断发布的来源级风险", ""])
    if report["blocking_release_reasons"]:
        for item in report["blocking_release_reasons"]:
            lines.append(f"- `{item['source_id']}`：{item['reason']}")
    else:
        lines.append("- 无。")
    lines.extend(["", "## 清洗与字符检查", ""])
    lines.append(
        "硬错误包括残留模板/伪标签、HTML、Unicode 私用区、替换字符、图片路径和断裂的上下文链接。"
    )
    lines.append(
        "缺字和HT/KT不会被静默删除：受影响的最小完整语义单元进入隔离库，检索字段置空，禁止引用；可引用语料必须为零未解字。"
    )
    lines.extend([
        "",
        "| 来源 | 全部段落 | 可引用 | 隔离 | 硬错误 | 隔离警告数 | 主要说话者类型 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ])
    for source in report["sources"]:
        lines.append(
            f"| `{source['source_id']}` | {source['passage_count']} | "
            f"{source['citable_passage_count']} | {source['quarantined_passage_count']} | "
            f"{sum(source['blocking_issues'].values())} | {sum(source['warnings'].values())} | "
            f"{', '.join(f'{k}:{v}' for k, v in list(source['speaker_type_counts'].items())[:4])} |"
        )
    lines.extend(
        [
            "",
            "## 已知高风险",
            "",
            "- 王冰本 ProofreadPage 的低校对等级按页面计入，不因抽取成功而降级为普通警告。",
            "- 核心《素问》《灵枢》《伤寒论》等上游低质量标记，需要第二许可明确底本的差异检查或人工抽检记录。",
            "- `mixed` 表示自动规则不能可靠区分原文与注文；前端必须如实显示，不得自动冒认作者。",
            "- `text_source`、`text_traditional` 仅用于后台校核；用户直接引文必须使用 `text_simplified`。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED)
    parser.add_argument("--extract-summary", type=Path, default=DEFAULT_EXTRACT_SUMMARY)
    parser.add_argument("--convert-summary", type=Path, default=DEFAULT_CONVERT_SUMMARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--completeness-output", type=Path, default=DEFAULT_COMPLETENESS)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()

    inventory = load_json(args.inventory)
    extract = {item["source_id"]: item for item in load_json(args.extract_summary)["sources"]}
    convert = {item["source_id"]: item for item in load_json(args.convert_summary)["sources"]}
    processed = {
        item["source_id"]: item
        for item in load_json(args.processed_dir / "summary.json")["sources"]
    }
    source_reports: list[dict[str, Any]] = []
    completeness_items: list[dict[str, Any]] = []
    release_blocks: list[dict[str, str]] = []

    for source in inventory["sources"]:
        source_id = source["id"]
        raw = source_raw_metrics(source)
        structure = structural_result(source, raw)
        passage_path = args.processed_dir / source_id / "passages.jsonl"
        passage = scan_passages(passage_path)
        extracted_characters = extract[source_id]["statistics"].get("extracted_characters", 0)
        ratio = extracted_characters / raw["included_raw_characters"] if raw["included_raw_characters"] else 0.0
        source_report = {
            "source_id": source_id,
            **raw,
            **passage,
            "extraction_to_raw_character_ratio": round(ratio, 6),
            "conversion_hashes": {
                "source": convert[source_id]["source_aggregate_sha256"],
                "traditional": convert[source_id]["traditional_aggregate_sha256"],
                "simplified": convert[source_id]["simplified_aggregate_sha256"],
                "search": convert[source_id]["search_aggregate_sha256"],
            },
            "processed_hashes": {
                "source": processed[source_id]["source_aggregate_sha256"],
                "traditional": processed[source_id]["traditional_aggregate_sha256"],
                "simplified": processed[source_id]["simplified_aggregate_sha256"],
                "search": processed[source_id]["search_aggregate_sha256"],
                "citable_traditional": processed[source_id]["citable_traditional_sha256"],
                "citable_simplified": processed[source_id]["citable_simplified_sha256"],
                "citable_search": processed[source_id]["citable_search_sha256"],
            },
            "structure": structure,
        }
        source_reports.append(source_report)
        completeness_items.append({"source_id": source_id, **structure})
        if raw["raw_hash_mismatch_count"]:
            release_blocks.append({"source_id": source_id, "reason": "raw snapshot SHA-256 mismatch"})
        if structure["status"] != "pass":
            release_blocks.append({"source_id": source_id, "reason": "expected structure did not meet minimum"})
        if passage["blocking_issues"]:
            release_blocks.append({"source_id": source_id, "reason": "processed text contains cleanup hard errors"})
        if passage["passage_count"] == 0 or ratio < 0.2:
            release_blocks.append({"source_id": source_id, "reason": "empty or implausibly low extraction coverage"})
        if passage["citable_warnings"]:
            release_blocks.append(
                {
                    "source_id": source_id,
                    "reason": "citable corpus still contains unresolved source warnings: "
                    + ", ".join(
                        f"{key}={value}" for key, value in sorted(passage["citable_warnings"].items())
                    ),
                }
            )
        if source["layer"] == "core" and passage["quarantined_passage_count"]:
            release_blocks.append(
                {
                    "source_id": source_id,
                    "reason": (
                        "core work contains "
                        f"{passage['quarantined_passage_count']} quarantined unresolved semantic units"
                    ),
                }
            )
        for reason in upstream_quality_blocks(source, raw):
            release_blocks.append({"source_id": source_id, "reason": reason})

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    overall = {
        "source_count": len(source_reports),
        "snapshot_page_count": sum(len(source["pages"]) for source in inventory["sources"]),
        "included_page_count": sum(sum(page["include_in_corpus"] for page in source["pages"]) for source in inventory["sources"]),
        "passage_count": sum(item["passage_count"] for item in source_reports),
        "citable_passage_count": sum(item["citable_passage_count"] for item in source_reports),
        "quarantined_passage_count": sum(item["quarantined_passage_count"] for item in source_reports),
        "simplified_character_count": sum(item["simplified_character_count"] for item in source_reports),
        "citable_character_count": sum(item["citable_character_count"] for item in source_reports),
        "quarantined_character_count": sum(item["quarantined_character_count"] for item in source_reports),
        "raw_integrity_status": "pass" if all(item["raw_hash_mismatch_count"] == 0 for item in source_reports) else "fail",
        "structural_status": "pass" if all(item["structure"]["status"] == "pass" for item in source_reports) else "fail",
        "citable_corpus_status": (
            "pass"
            if all(not item["citable_warnings"] for item in source_reports)
            else "fail"
        ),
        "cleanup_status": (
            "fail"
            if any(item["blocking_issues"] or item["citable_warnings"] for item in source_reports)
            else "pass-with-quarantine"
            if any(item["quarantined_passage_count"] for item in source_reports)
            else "pass"
        ),
        "release_gate_status": "pass" if not release_blocks else "blocked",
    }
    report = {
        "schema_version": 1,
        "generated_at": generated_at,
        "overall": overall,
        "blocking_release_reasons": release_blocks,
        "sources": source_reports,
    }
    completeness = {"schema_version": 1, "generated_at": generated_at, "sources": completeness_items}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.completeness_output.write_text(
        json.dumps(completeness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text(markdown_report(report, completeness), encoding="utf-8")
    print(json.dumps(overall, ensure_ascii=False, indent=2))
    if release_blocks:
        print(f"Release quality gate BLOCKED by {len(release_blocks)} source-level reasons")


if __name__ == "__main__":
    main()
