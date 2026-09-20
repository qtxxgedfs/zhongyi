#!/usr/bin/env python3
"""Build the fixed-revision source-lock candidate, attribution manifest, and NOTICE.

A final ``sources/source-lock.json`` is emitted only when the quality report's release
gate passes. Otherwise this script intentionally emits ``source-lock.candidate.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = PROJECT_DIR / "sources" / "source-inventory.json"
DEFAULT_QUALITY = PROJECT_DIR / "sources" / "quality-report.json"
DEFAULT_COMPLETENESS = PROJECT_DIR / "sources" / "completeness-manifest.json"
DEFAULT_PROCESSED = PROJECT_DIR / "sources" / "processed" / "summary.json"
DEFAULT_CONVERSION = PROJECT_DIR / "build" / "intermediate" / "converted" / "summary.json"
DEFAULT_CANDIDATE = PROJECT_DIR / "sources" / "source-lock.candidate.json"
DEFAULT_FINAL = PROJECT_DIR / "sources" / "source-lock.json"
DEFAULT_MANIFEST = PROJECT_DIR / "sources" / "source-manifest.json"
DEFAULT_NOTICE = PROJECT_DIR / "NOTICE.md"
DEFAULT_SKILL_NOTICE = PROJECT_DIR / "skill" / "tcm-classics-study" / "NOTICE.md"
DEFAULT_EXCLUSIONS = PROJECT_DIR / "sources" / "corpus-exclusions.json"
PROOFREAD_RE = re.compile(r"<pagequality\s+level=[\"']?(\d)", flags=re.I)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fixed_revision_url(page_url: str, revision_id: int) -> str:
    separator = "&" if "?" in page_url else "?"
    return f"{page_url}{separator}oldid={revision_id}"


def proofread_level(path: Path) -> int | None:
    match = PROOFREAD_RE.search(path.read_text(encoding="utf-8"))
    return int(match.group(1)) if match else None


def notice_text(manifest_status: str, source_count: int, page_count: int) -> str:
    status_note = (
        "当前来源清单已通过发布质量闸门。"
        if manifest_status == "final"
        else "当前为可运行的固定修订候选；质量精修尚未完成，不得称为最终无条件发布底本。"
    )
    return f"""# NOTICE — 中医四部经典研读语料

## 状态

{status_note}

本产品所用的是**工作底本**，不是无异文、无错误的唯一权威文本。语料包含
{source_count} 种作品、{page_count} 个固定页面快照。逐页标题、链接、固定修订号、
访问时间和 SHA-256 见 `sources/source-manifest.json`（候选Skill内为
`data/source-manifest.json`）。

## Wikisource 文本

- 来源网站：中文维基文库（Wikisource）
- 网站使用条款：https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use/en
- 文本再利用许可：https://creativecommons.org/licenses/by-sa/4.0/
- 原古籍作品属于公版范围；维基文库转录文本及其可版权化编辑按 CC BY-SA 4.0
  署名—相同方式共享条件处理。
- 固定修订链接同时指向页面历史和贡献者记录，构成逐页署名追溯入口。

## 本项目所作修改

本项目对固定 wikitext 快照进行模板展开、版式标记清理、缺字模板解析、Unicode
规范化、繁简转换、医学字符阅读规范化、说话者/内容角色标注和检索字段生成。
原始转录层人工字符修复记录在 `sources/normalization/manual-character-repairs.json`；
为保持既有段落 ID 而在切分后执行的影像确认修订记录在
`sources/normalization/passage-text-corrections.json`；繁简阅读覆盖规则记录在
`sources/normalization/conversion-overrides.json`。含未解字的最小完整语义单元保留在隔离库中，但检索字段置空，禁止搜索和引用；隔离清单见 `sources/corpus-exclusions.json`。

## 现代医学来源

`data/evidence-cache.sqlite` 只保存本项目撰写的中文证据摘要、结构化判断和来源元数据，不保存NCCIH、CDC、NHS等网站的网页全文。来源标题、机构、日期、URL、页面核验日期和抓取内容哈希用于追溯，不表示外部网页采用与古籍语料相同的许可。在线使用仍须遵守各来源网站条款。

## 不包含的内容

本项目不打包 Wikisource、互联网档案馆或其他机构的扫描影像，也不打包现代医学来源网页全文。扫描影像和外部网页可能有独立权利和使用条件，不能因文字或事实可引用而推定其他内容可打包。

## 相同方式共享

分发含 Wikisource 衍生文本的版本时，应同时保留本 NOTICE、逐页来源清单、修改
说明和 CC BY-SA 4.0 链接，并按相同许可证提供受该许可证约束的衍生文本部分。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--quality", type=Path, default=DEFAULT_QUALITY)
    parser.add_argument("--completeness", type=Path, default=DEFAULT_COMPLETENESS)
    parser.add_argument("--processed-summary", type=Path, default=DEFAULT_PROCESSED)
    parser.add_argument("--conversion-summary", type=Path, default=DEFAULT_CONVERSION)
    parser.add_argument("--candidate-output", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--final-output", type=Path, default=DEFAULT_FINAL)
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--notice-output", type=Path, default=DEFAULT_NOTICE)
    parser.add_argument("--skill-notice-output", type=Path, default=DEFAULT_SKILL_NOTICE)
    parser.add_argument("--exclusions", type=Path, default=DEFAULT_EXCLUSIONS)
    args = parser.parse_args()

    inventory = load_json(args.inventory)
    quality = load_json(args.quality)
    completeness = {item["source_id"]: item for item in load_json(args.completeness)["sources"]}
    processed = {item["source_id"]: item for item in load_json(args.processed_summary)["sources"]}
    conversion = load_json(args.conversion_summary)
    quality_sources = {item["source_id"]: item for item in quality["sources"]}
    blocks_by_source: dict[str, list[str]] = defaultdict(list)
    for item in quality["blocking_release_reasons"]:
        blocks_by_source[item["source_id"]].append(item["reason"])

    lock_status = "final" if quality["overall"]["release_gate_status"] == "pass" else "candidate-blocked"
    locked_sources: list[dict[str, Any]] = []
    manifest_sources: list[dict[str, Any]] = []
    page_total = 0
    included_page_total = 0

    for source in inventory["sources"]:
        source_id = source["id"]
        source_pages: list[dict[str, Any]] = []
        manifest_pages: list[dict[str, Any]] = []
        for page in source["pages"]:
            raw_path = PROJECT_DIR / page["raw_wikitext_path"]
            fixed_url = fixed_revision_url(page["page_url"], page["revision_id"])
            page_lock = {
                "title": page["title"],
                "page_url": page["page_url"],
                "fixed_revision_url": fixed_url,
                "revision_id": page["revision_id"],
                "revision_timestamp": page["revision_timestamp"],
                "source_sha1": page.get("source_sha1"),
                "source_size": page.get("source_size"),
                "content_model": page.get("content_model"),
                "role": page["role"],
                "include_in_corpus": page["include_in_corpus"],
                "parent_title": page.get("parent_title"),
                "proofread_quality_level": proofread_level(raw_path),
                "raw_wikitext_path": page["raw_wikitext_path"],
                "raw_sha256": page["raw_sha256"],
                "categories": page.get("categories", []),
            }
            source_pages.append(page_lock)
            manifest_pages.append(
                {
                    "title": page["title"],
                    "fixed_revision_url": fixed_url,
                    "revision_id": page["revision_id"],
                    "revision_timestamp": page["revision_timestamp"],
                    "include_in_corpus": page["include_in_corpus"],
                    "raw_sha256": page["raw_sha256"],
                }
            )
            page_total += 1
            included_page_total += int(page["include_in_corpus"])

        processed_item = processed[source_id]
        source_quality = quality_sources[source_id]
        processed_path = PROJECT_DIR / processed_item["processed_path"]
        locked_sources.append(
            {
                "id": source_id,
                "layer": source["layer"],
                "canon": source["canon"],
                "target_works": source["target_works"],
                "author": source["author"],
                "title": source["title"],
                "relationship": source["relationship"],
                "provider": source["provider"],
                "page_title": source["page_title"],
                "page_url": source["page_url"],
                "edition_label": source["edition_label"],
                "retrieved_at": source["retrieved_at"],
                "license": source["license"],
                "textual_status": source["textual_status"],
                "quality_note": source.get("quality_note", ""),
                "scope_note": source.get("scope_note", ""),
                "speaker_method": source.get("speaker_method", ""),
                "pages": source_pages,
                "aggregate_raw_sha256": source["aggregate_raw_sha256"],
                "processed": {
                    "path": processed_item["processed_path"],
                    "passage_count": processed_item["passage_count"],
                    "citable_passage_count": processed_item["citable_passage_count"],
                    "quarantined_passage_count": processed_item["quarantined_passage_count"],
                    "source_sha256": processed_item["source_aggregate_sha256"],
                    "traditional_sha256": processed_item["traditional_aggregate_sha256"],
                    "simplified_sha256": processed_item["simplified_aggregate_sha256"],
                    "search_sha256": processed_item["search_aggregate_sha256"],
                    "citable_traditional_sha256": processed_item["citable_traditional_sha256"],
                    "citable_simplified_sha256": processed_item["citable_simplified_sha256"],
                    "citable_search_sha256": processed_item["citable_search_sha256"],
                    "file_sha256": sha256_file(processed_path),
                },
                "completeness": completeness[source_id],
                "speaker_separation": {
                    "method": source.get("speaker_method", ""),
                    "speaker_type_counts": source_quality["speaker_type_counts"],
                    "top_speakers": source_quality["top_speakers"],
                },
                "quality_gate": {
                    "status": (
                        "blocked"
                        if blocks_by_source[source_id]
                        else "pass-with-quarantine"
                        if processed_item["quarantined_passage_count"]
                        else "pass"
                    ),
                    "blocking_reasons": blocks_by_source[source_id],
                    "warnings": source_quality["warnings"],
                },
            }
        )
        manifest_sources.append(
            {
                "id": source_id,
                "title": source["title"],
                "author": source["author"],
                "layer": source["layer"],
                "relationship": source["relationship"],
                "edition_label": source["edition_label"],
                "root_page_url": source["page_url"],
                "retrieved_at": source["retrieved_at"],
                "license_expression": source["license"]["expression"],
                "passage_count": processed_item["passage_count"],
                "citable_passage_count": processed_item["citable_passage_count"],
                "quarantined_passage_count": processed_item["quarantined_passage_count"],
                "pages": manifest_pages,
            }
        )

    quality_relative = args.quality.relative_to(PROJECT_DIR).as_posix()
    lock = {
        "schema_version": 2,
        "lock_status": lock_status,
        "locked_at": quality["generated_at"],
        "work_base_disclaimer": "本产品所用工作底本；不是无异文、无错误的唯一权威文本。",
        "quality_report": {
            "path": quality_relative,
            "sha256": sha256_file(args.quality),
            "release_gate_status": quality["overall"]["release_gate_status"],
            "blocking_reason_count": len(quality["blocking_release_reasons"]),
        },
        "quality_policy": {
            "raw_snapshots_unchanged": True,
            "unresolved_glyphs_allowed_in_citable_corpus": False,
            "quarantined_passages_searchable": False,
            "quarantined_passages_citable": False,
            "unit_rule": "smallest reliably detectable complete semantic unit",
            "core_quarantine_blocks_release": True,
            "extension_quarantine_may_be_accepted_with_full_disclosure": True,
            "exclusions_path": args.exclusions.relative_to(PROJECT_DIR).as_posix(),
            "exclusions_sha256": sha256_file(args.exclusions),
        },
        "normalization": {
            "opencc_engine": conversion["engine"],
            "opencc_version": conversion["engine_version"],
            "traditional_config": conversion["traditional_config"],
            "simplified_config": conversion["simplified_config"],
            "character_map_path": "sources/normalization/skchar-map.json",
            "source_dependencies_path": "sources/normalization/source-dependencies.json",
            "manual_repairs_path": "sources/normalization/manual-character-repairs.json",
            "passage_text_corrections_path": "sources/normalization/passage-text-corrections.json",
            "passage_text_corrections_sha256": sha256_file(
                PROJECT_DIR / "sources" / "normalization" / "passage-text-corrections.json"
            ),
            "conversion_overrides_path": "sources/normalization/conversion-overrides.json",
        },
        "sources": locked_sources,
    }
    output = args.final_output if lock_status == "final" else args.candidate_output
    output.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if lock_status != "final" and args.final_output.exists():
        raise SystemExit(
            f"Quality gate is blocked, but {args.final_output} already exists; remove or review it manually."
        )

    manifest = {
        "schema_version": 1,
        "manifest_status": lock_status,
        "generated_at": quality["generated_at"],
        "work_base_disclaimer": lock["work_base_disclaimer"],
        "attribution": {
            "provider": "Chinese Wikisource",
            "site_terms_url": "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use/en",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "modifications": "wikitext cleanup, glyph resolution, role labeling, normalization, simplified display conversion, and search normalization",
            "scan_images_packaged": False,
        },
        "source_count": len(manifest_sources),
        "snapshot_page_count": page_total,
        "included_page_count": included_page_total,
        "passage_count": quality["overall"]["passage_count"],
        "citable_passage_count": quality["overall"]["citable_passage_count"],
        "quarantined_passage_count": quality["overall"]["quarantined_passage_count"],
        "exclusions_path": "sources/corpus-exclusions.json",
        "sources": manifest_sources,
    }
    args.manifest_output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    notice = notice_text(lock_status, len(manifest_sources), page_total)
    args.notice_output.write_text(notice, encoding="utf-8")
    args.skill_notice_output.parent.mkdir(parents=True, exist_ok=True)
    args.skill_notice_output.write_text(notice, encoding="utf-8")
    print(f"{lock_status}: {len(locked_sources)} sources, {page_total} fixed pages -> {output}")
    if lock_status != "final":
        print("Final source-lock.json intentionally NOT generated because the release quality gate is blocked.")


if __name__ == "__main__":
    main()
