#!/usr/bin/env python3
"""Split converted blocks into citable passages and a non-citable quarantine corpus.

Raw and processed source text is never destructively deleted. Any unresolved glyph,
legacy HT/KT placeholder, or known UI-text intrusion is isolated at the smallest
reliably detectable semantic unit and excluded from search/citation fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

PROJECT_DIR = Path(__file__).resolve().parents[1]
BUILDER_DIR = Path(__file__).resolve().parent
if str(BUILDER_DIR) not in sys.path:
    sys.path.insert(0, str(BUILDER_DIR))

from convert_simplified import normalize_search  # noqa: E402

DEFAULT_INPUT = PROJECT_DIR / "build" / "intermediate" / "converted"
DEFAULT_OUTPUT = PROJECT_DIR / "sources" / "processed"
DEFAULT_QUARANTINE = PROJECT_DIR / "sources" / "quarantine"
DEFAULT_EXCLUSIONS = PROJECT_DIR / "sources" / "corpus-exclusions.json"
DEFAULT_OVERRIDES = PROJECT_DIR / "sources" / "normalization" / "conversion-overrides.json"
DEFAULT_CORRECTIONS = (
    PROJECT_DIR / "sources" / "normalization" / "passage-text-corrections.json"
)
DEFAULT_MAX_CHARS = 700
DEFAULT_MIN_CHARS = 220
PREFERRED_BREAK_RE = re.compile(r"[。！？；!?](?:[”’」』》】])?")
SECONDARY_BREAK_RE = re.compile(r"[，、：,:](?:[”’」』》】])?")
ISSUE_PATTERNS = {
    "explicit-missing-glyph": re.compile(r"〔(?:未识别字\d+|原文缺字(?::[^〕]+)?|四库缺字\d+)〕"),
    "legacy-glyph-placeholder-ht-kt": re.compile(r"(?<![A-Za-z])(?:HT|KT)(?![A-Za-z])"),
    "known-ui-text-intrusion": re.compile(r"滚动条|滾動條"),
    "unicode-replacement-character": re.compile("�"),
    "private-use-character": re.compile(r"[\ue000-\uf8ff\U000f0000-\U000ffffd\U00100000-\U0010fffd]"),
}
QUARANTINE_REASONS = {
    "explicit-missing-glyph": "来源存在尚未确认的缺字",
    "legacy-glyph-placeholder-ht-kt": "来源含HT/KT旧转录占位符，原字未确认",
    "known-ui-text-intrusion": "来源疑似混入网页界面文字",
    "unicode-replacement-character": "来源含Unicode替换字符",
    "private-use-character": "来源含未解析私用区字符",
}


def read_records(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def split_ranges(text: str, minimum: int, maximum: int) -> list[tuple[int, int]]:
    if len(text) <= maximum:
        return [(0, len(text))]
    ranges: list[tuple[int, int]] = []
    start = 0
    while len(text) - start > maximum:
        window = text[start : start + maximum]
        candidates = [match.end() for match in PREFERRED_BREAK_RE.finditer(window)]
        cut = max((value for value in candidates if value >= minimum), default=0)
        if not cut:
            secondary = [match.end() for match in SECONDARY_BREAK_RE.finditer(window)]
            cut = max((value for value in secondary if value >= minimum), default=0)
        if not cut:
            cut = maximum
        ranges.append((start, start + cut))
        start += cut
    if start < len(text):
        ranges.append((start, len(text)))
    return ranges


def issue_counts(text: str) -> Counter[str]:
    result: Counter[str] = Counter()
    for issue_type, pattern in ISSUE_PATTERNS.items():
        result[issue_type] = len(pattern.findall(text))
        if not result[issue_type]:
            del result[issue_type]
    return result


def sentence_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = 0
    for match in PREFERRED_BREAK_RE.finditer(text):
        if match.end() > start:
            ranges.append((start, match.end()))
            start = match.end()
    if start < len(text):
        ranges.append((start, len(text)))
    return ranges or [(0, len(text))]


def semantic_ranges(
    text: str,
    speaker_type: str,
    minimum: int,
    maximum: int,
) -> list[tuple[int, int, Counter[str]]]:
    """Return bounded ranges while keeping contaminated semantic units isolated."""
    all_issues = issue_counts(text)
    if not all_issues:
        return [(start, end, Counter()) for start, end in split_ranges(text, minimum, maximum)]

    # A dialogue extraction block is one speaker turn. If a missing glyph occurs in
    # that turn, splitting out one sentence could falsely imply an intact quotation.
    units = [(0, len(text))] if speaker_type == "dialogue" else sentence_ranges(text)
    output: list[tuple[int, int, Counter[str]]] = []
    clean_start: int | None = None
    clean_end: int | None = None

    def flush_clean() -> None:
        nonlocal clean_start, clean_end
        if clean_start is None or clean_end is None:
            return
        for start, end in split_ranges(text[clean_start:clean_end], minimum, maximum):
            output.append((clean_start + start, clean_start + end, Counter()))
        clean_start = clean_end = None

    for start, end in units:
        unit_issues = issue_counts(text[start:end])
        if unit_issues:
            flush_clean()
            # If an unpunctuated logical line is long, every bounded child remains
            # quarantined; no clean fragment is fabricated around an uncertain glyph.
            for child_start, child_end in split_ranges(text[start:end], minimum, maximum):
                output.append((start + child_start, start + child_end, unit_issues.copy()))
        else:
            if clean_start is None:
                clean_start = start
            clean_end = end
    flush_clean()
    return output


def work_prefix(source_id: str) -> str:
    abbreviations = {
        "core-suwen": "SW",
        "core-lingshu": "LS",
        "core-shanghanlun": "SHL",
        "core-jingui": "JKY",
        "core-nanjing": "NJ",
        "core-wenbingtiaobian": "WBTB",
    }
    return abbreviations.get(source_id, re.sub(r"[^A-Z0-9]+", "-", source_id.upper()).strip("-"))


def aggregate_hash(passages: list[dict[str, Any]], field: str) -> str:
    digest = hashlib.sha256()
    for passage in passages:
        digest.update(passage[field].encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def index_corrections(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}
    seen_ids: set[str] = set()
    for correction in payload["corrections"]:
        correction_id = correction["id"]
        if correction_id in seen_ids:
            raise SystemExit(f"Duplicate passage correction ID: {correction_id}")
        seen_ids.add(correction_id)
        passage_id = correction["passage_id"]
        indexed.setdefault(passage_id, []).append(correction)
    return indexed


def apply_passage_corrections(
    passage_id: str,
    source_id: str,
    texts: dict[str, str],
    corrections_by_passage: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, str], list[str]]:
    applied: list[str] = []
    for correction in corrections_by_passage.get(passage_id, []):
        correction_id = correction["id"]
        if correction["source_id"] != source_id:
            raise SystemExit(
                f"Passage correction {correction_id} expected source "
                f"{correction['source_id']}, got {source_id}"
            )
        for field, replacement in correction["fields"].items():
            if field not in texts:
                raise SystemExit(f"Passage correction {correction_id} has unknown field: {field}")
            before = replacement["before"]
            expected = replacement.get("expected_occurrences", 1)
            observed = texts[field].count(before)
            if observed != expected:
                raise SystemExit(
                    f"Passage correction {correction_id} expected {expected} occurrence(s) "
                    f"of {before!r} in {passage_id}.{field}, got {observed}"
                )
            texts[field] = texts[field].replace(before, replacement["after"])
        applied.append(correction_id)
    return texts, applied


def add_links(passages: list[dict[str, Any]]) -> None:
    for index, passage in enumerate(passages):
        passage["previous_id"] = passages[index - 1]["id"] if index > 0 else None
        passage["next_id"] = passages[index + 1]["id"] if index + 1 < len(passages) else None
        passage["previous_citable_id"] = None
        passage["next_citable_id"] = None
    citable_indices = [index for index, passage in enumerate(passages) if passage["citation_allowed"]]
    for position, index in enumerate(citable_indices):
        passages[index]["previous_citable_id"] = (
            passages[citable_indices[position - 1]]["id"] if position > 0 else None
        )
        passages[index]["next_citable_id"] = (
            passages[citable_indices[position + 1]]["id"]
            if position + 1 < len(citable_indices)
            else None
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--quarantine-dir", type=Path, default=DEFAULT_QUARANTINE)
    parser.add_argument("--exclusions-output", type=Path, default=DEFAULT_EXCLUSIONS)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--corrections", type=Path, default=DEFAULT_CORRECTIONS)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS)
    args = parser.parse_args()
    if args.min_chars < 1 or args.max_chars <= args.min_chars:
        raise SystemExit("--max-chars must be greater than --min-chars >= 1")

    override_payload = json.loads(args.overrides.read_text(encoding="utf-8"))
    search_replacements = override_payload["search_only_replacements"]
    correction_payload = json.loads(args.corrections.read_text(encoding="utf-8"))
    corrections_by_passage = index_corrections(correction_payload)
    correction_apply_counts: Counter[str] = Counter()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.quarantine_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    quarantined_passages: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []

    for input_path in sorted(args.input_dir.glob("*.jsonl")):
        source_id = input_path.stem
        passages: list[dict[str, Any]] = []
        stats: Counter[str] = Counter()
        prefix = work_prefix(source_id)
        for block in read_records(input_path):
            ranges = semantic_ranges(
                block["text_simplified"], block["speaker_type"], args.min_chars, args.max_chars
            )
            if len(ranges) > 1:
                stats["split_blocks"] += 1
            for segment_index, (start, end, inherited_issues) in enumerate(ranges, 1):
                text_source = block["text_source"][start:end].strip()
                text_traditional = block["text_traditional"][start:end].strip()
                text_simplified = block["text_simplified"][start:end].strip()
                if not text_simplified:
                    continue
                if not re.search(r"[0-9A-Za-z\u3400-\u9fff\U00020000-\U0003134f]", text_simplified):
                    stats["dropped_format_only_segments"] += 1
                    continue
                sequence = len(passages) + 1
                passage_id = f"{prefix}-{sequence:06d}"
                texts, correction_ids = apply_passage_corrections(
                    passage_id,
                    source_id,
                    {
                        "text_source": text_source,
                        "text_traditional": text_traditional,
                        "text_simplified": text_simplified,
                    },
                    corrections_by_passage,
                )
                text_source = texts["text_source"]
                text_traditional = texts["text_traditional"]
                text_simplified = texts["text_simplified"]
                for correction_id in correction_ids:
                    correction_apply_counts[correction_id] += 1
                if correction_ids:
                    stats["documented_text_corrections"] += len(correction_ids)
                detected_issues = issue_counts(text_simplified)
                # Corrected passages retain their pre-correction semantic boundaries,
                # but only still-detectable issues may keep them in quarantine.
                quarantine_issues = (
                    detected_issues if correction_ids else inherited_issues or detected_issues
                )
                is_quarantined = bool(quarantine_issues)
                quality_flags = sorted(quarantine_issues)
                passage = {
                    "id": passage_id,
                    "work_id": source_id,
                    "source_id": source_id,
                    "sequence": sequence,
                    "segment_group_id": block["temporary_id"],
                    "segment_index": segment_index,
                    "segment_count": len(ranges),
                    "previous_id": None,
                    "next_id": None,
                    "previous_citable_id": None,
                    "next_citable_id": None,
                    "source_page_title": block["source_page_title"],
                    "source_revision_id": block["source_revision_id"],
                    "source_raw_sha256": block["source_raw_sha256"],
                    "volume": block["volume"],
                    "section": block["section"],
                    "subsection": block["subsection"],
                    "volume_traditional": block["volume_traditional"],
                    "section_traditional": block["section_traditional"],
                    "subsection_traditional": block["subsection_traditional"],
                    "speaker": block["speaker"],
                    "speaker_traditional": block["speaker_traditional"],
                    "speaker_type": block["speaker_type"],
                    "quality_status": "quarantined" if is_quarantined else "clean",
                    "citation_allowed": not is_quarantined,
                    "search_allowed": not is_quarantined,
                    "quality_flags": quality_flags,
                    "issue_counts": dict(sorted(detected_issues.items())),
                    "quarantine_reason": (
                        "；".join(QUARANTINE_REASONS[item] for item in quality_flags)
                        if is_quarantined
                        else ""
                    ),
                    "text_source": text_source,
                    "text_traditional": text_traditional,
                    "text_simplified": text_simplified,
                    # Deliberately empty for quarantined passages as a second barrier
                    # against accidental indexing. The readable audit text remains.
                    "text_search": (
                        "" if is_quarantined else normalize_search(text_simplified, search_replacements)
                    ),
                    "content_sha256": hashlib.sha256(text_traditional.encode("utf-8")).hexdigest(),
                }
                if correction_ids:
                    passage["correction_ids"] = correction_ids
                passages.append(passage)
                stats["passages"] += 1
                stats["characters_simplified"] += len(text_simplified)
                stats[f"speaker_type:{passage['speaker_type']}"] += 1
                if is_quarantined:
                    stats["quarantined_passages"] += 1
                    stats["quarantined_characters"] += len(text_simplified)
                    for issue_type, count in detected_issues.items():
                        stats[f"quarantine_issue:{issue_type}"] += count
                else:
                    stats["citable_passages"] += 1
                    stats["citable_characters"] += len(text_simplified)

        add_links(passages)
        source_quarantine = [passage for passage in passages if not passage["citation_allowed"]]
        quarantined_passages.extend(source_quarantine)
        for passage in source_quarantine:
            exclusions.append(
                {
                    "passage_id": passage["id"],
                    "source_id": passage["source_id"],
                    "source_page_title": passage["source_page_title"],
                    "source_revision_id": passage["source_revision_id"],
                    "source_raw_sha256": passage["source_raw_sha256"],
                    "volume": passage["volume"],
                    "section": passage["section"],
                    "subsection": passage["subsection"],
                    "speaker": passage["speaker"],
                    "speaker_type": passage["speaker_type"],
                    "issue_types": passage["quality_flags"],
                    "issue_counts": passage["issue_counts"],
                    "reason": passage["quarantine_reason"],
                    "resolution_status": "unresolved",
                    "citation_allowed": False,
                    "search_allowed": False,
                    "text_simplified": passage["text_simplified"],
                }
            )

        source_dir = args.output_dir / source_id
        source_dir.mkdir(parents=True, exist_ok=True)
        output_path = source_dir / "passages.jsonl"
        with output_path.open("w", encoding="utf-8", newline="\n") as handle:
            for passage in passages:
                handle.write(json.dumps(passage, ensure_ascii=False, separators=(",", ":")) + "\n")
        citable = [passage for passage in passages if passage["citation_allowed"]]
        summary = {
            "source_id": source_id,
            "passage_count": len(passages),
            "citable_passage_count": len(citable),
            "quarantined_passage_count": len(source_quarantine),
            "statistics": dict(sorted(stats.items())),
            "source_aggregate_sha256": aggregate_hash(passages, "text_source"),
            "traditional_aggregate_sha256": aggregate_hash(passages, "text_traditional"),
            "simplified_aggregate_sha256": aggregate_hash(passages, "text_simplified"),
            "search_aggregate_sha256": aggregate_hash(passages, "text_search"),
            "citable_traditional_sha256": aggregate_hash(citable, "text_traditional"),
            "citable_simplified_sha256": aggregate_hash(citable, "text_simplified"),
            "citable_search_sha256": aggregate_hash(citable, "text_search"),
            "processed_path": output_path.relative_to(PROJECT_DIR).as_posix(),
            "max_simplified_characters": max((len(item["text_simplified"]) for item in passages), default=0),
        }
        (source_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        summaries.append(summary)
        print(
            f"{source_id}: {len(passages)} passages; "
            f"{len(citable)} citable; {len(source_quarantine)} quarantined"
        )

    expected_correction_ids = {
        correction["id"] for correction in correction_payload["corrections"]
    }
    incorrectly_applied = {
        correction_id: correction_apply_counts.get(correction_id, 0)
        for correction_id in sorted(expected_correction_ids)
        if correction_apply_counts.get(correction_id, 0) != 1
    }
    if incorrectly_applied:
        raise SystemExit(
            "Every documented passage correction must apply exactly once: "
            + json.dumps(incorrectly_applied, ensure_ascii=False, sort_keys=True)
        )

    correction_audit = {
        "path": args.corrections.relative_to(PROJECT_DIR).as_posix(),
        "sha256": sha256_file(args.corrections),
        "applied_count": sum(correction_apply_counts.values()),
    }
    quarantine_path = args.quarantine_dir / "passages.jsonl"
    with quarantine_path.open("w", encoding="utf-8", newline="\n") as handle:
        for passage in quarantined_passages:
            handle.write(json.dumps(passage, ensure_ascii=False, separators=(",", ":")) + "\n")
    quarantine_summary = {
        "schema_version": 1,
        "policy": "Unresolved units are retained for audit but excluded from citation and search.",
        "passage_count": len(quarantined_passages),
        "issue_occurrences": dict(
            sorted(
                Counter(
                    {
                        issue_type: sum(
                            passage["issue_counts"].get(issue_type, 0)
                            for passage in quarantined_passages
                        )
                        for issue_type in ISSUE_PATTERNS
                    }
                ).items()
            )
        ),
        "processed_path": quarantine_path.relative_to(PROJECT_DIR).as_posix(),
    }
    (args.quarantine_dir / "summary.json").write_text(
        json.dumps(quarantine_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.exclusions_output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy": {
                    "raw_snapshots_unchanged": True,
                    "unresolved_glyphs_allowed_in_citable_corpus": False,
                    "quarantined_passages_searchable": False,
                    "quarantined_passages_citable": False,
                    "unit_rule": "smallest reliably detectable complete semantic unit",
                    "core_quarantine_blocks_release": True,
                    "extension_quarantine_may_be_accepted_with_full_disclosure": True,
                },
                "quarantined_passage_count": len(exclusions),
                "issue_occurrences": quarantine_summary["issue_occurrences"],
                "documented_text_corrections": correction_audit,
                "exclusions": exclusions,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    total_passages = sum(item["passage_count"] for item in summaries)
    total_citable = sum(item["citable_passage_count"] for item in summaries)
    (args.output_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "segmentation": {
                    "minimum_characters": args.min_chars,
                    "maximum_characters": args.max_chars,
                    "unresolved_unit_policy": "quarantine",
                },
                "passage_count": total_passages,
                "citable_passage_count": total_citable,
                "quarantined_passage_count": len(quarantined_passages),
                "documented_text_corrections": correction_audit,
                "sources": summaries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Segmented {len(summaries)} sources into {total_passages} passages; "
        f"{total_citable} citable; {len(quarantined_passages)} quarantined"
    )


if __name__ == "__main__":
    main()
