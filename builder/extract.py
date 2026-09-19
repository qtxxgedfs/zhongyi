#!/usr/bin/env python3
"""Extract structured text blocks from the frozen Wikisource wikitext snapshots.

This is deliberately conservative: source annotations become separate blocks, known
speaker labels are retained, and unresolved glyphs become explicit placeholders rather
than being silently discarded. Output is a build intermediate consumed by
``convert_simplified.py`` and ``segment.py``.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = PROJECT_DIR / "sources" / "source-inventory.json"
DEFAULT_CHARACTER_MAP = PROJECT_DIR / "sources" / "normalization" / "skchar-map.json"
DEFAULT_REPAIRS = PROJECT_DIR / "sources" / "normalization" / "manual-character-repairs.json"
DEFAULT_OUTPUT = PROJECT_DIR / "build" / "intermediate" / "extracted"

HEADING_TOKEN = "⟦TCM-HEADING:{level}:{title}⟧"
ANN_START_TOKEN = "⟦TCM-ANN-START:{speaker}:{kind}⟧"
ANN_END_TOKEN = "⟦TCM-ANN-END⟧"
QUOTE_START_TOKEN = "⟦TCM-QUOTE-START⟧"
QUOTE_END_TOKEN = "⟦TCM-QUOTE-END⟧"
TOKEN_RE = re.compile(
    r"(⟦TCM-HEADING:\d+:[^⟧]*⟧|⟦TCM-ANN-START:[^:⟧]*:[^⟧]*⟧|"
    r"⟦TCM-ANN-END⟧|⟦TCM-QUOTE-START⟧|⟦TCM-QUOTE-END⟧)"
)
INNER_TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}", flags=re.DOTALL)
STRUCTURAL_TEMPLATES = {
    "header", "header2", "textquality", "skqs header", "skqs footer",
    "pd-old", "vtext2start", "未校訂", "未校订", "未排版", "split",
    "傳統漢字化", "传统汉字化", "傳統漢字", "传统汉字", "noteta",
    "wikipedia", "檢索", "检索", "醫療", "医疗", "中醫", "中医",
    "wjd", "s2t", "傷寒論注", "伤寒论注", "難經注", "难经注",
}
QUOTE_END_LINE_RE = re.compile(
    r"^(?:按[、，,:：。]|案[、，,:：。]|[注註释釋解]曰|[论論]曰|"
    r"[丁呂吕楊杨虞滑馬马張张王志柯方喻尤徐成高]氏?[曰云]|"
    r"簡案|简案|《[^》]{1,30}》[曰云])"
)
EXPLICIT_SPEAKER_RE = re.compile(
    r"(?:^|(?<=[。！？；：「”』]))"
    r"(?:黃帝|黄帝|帝|岐伯|歧伯|伯高|雷公|少俞|少師|少师|"
    r"問|问|答|師|师|新校正|丁|呂|吕|楊|杨|虞|滑|馬|马|張|张|"
    r"志|柯|方|喻|尤|徐|成|王|高|簡案|简案)(?:氏)?"
    r"(?:問|问|對|对|答)?(?:曰|云|按)[：:]?"
)
CJK_RE = r"[\u3400-\u9fff\U00020000-\U0003134f]"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_template_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().replace("_", " ")).lower()


def visible_template_args(parts: list[str]) -> list[str]:
    return [part.strip() for part in parts if part.strip() and "=" not in part]


def annotation(speaker: str, kind: str, text: str) -> str:
    return ANN_START_TOKEN.format(speaker=speaker, kind=kind) + text + ANN_END_TOKEN


def apply_manual_repairs(text: str, source_id: str, repairs: list[dict[str, Any]]) -> tuple[str, int]:
    applied = 0
    for repair in repairs:
        if repair["source_id"] != source_id:
            continue
        source_sequence = repair["source_sequence"].encode("ascii").decode("unicode_escape")
        count = text.count(source_sequence)
        if count:
            text = text.replace(source_sequence, repair["replacement"])
            applied += count
    return text, applied


def replace_templates(
    text: str,
    source: dict[str, Any],
    character_maps: dict[str, dict[str, dict[str, Any]]],
    stats: Counter[str],
) -> str:
    source_id = source["id"]
    default_annotation_speaker = source["author"].split("（", 1)[0]

    def replacement(match: re.Match[str]) -> str:
        raw = match.group(1)
        parts = raw.split("|")
        name = normalize_template_name(parts[0])
        args = [part.strip() for part in parts[1:]]
        stats[f"template:{name}"] += 1

        if name in STRUCTURAL_TEMPLATES:
            return ""
        if name in {"skchar", "skchar2"}:
            template_name = "SKchar2" if name == "skchar2" else "SKchar"
            code = args[0] if args else ""
            entry = character_maps.get(template_name, {}).get(code)
            if not entry:
                stats[f"unresolved:{template_name}"] += 1
                return f"〔未识别字{code or '?'}〕"
            if entry["resolution"] == "unresolved_placeholder":
                stats[f"unresolved:{template_name}"] += 1
            elif entry["resolution"] == "module_descriptive_variant":
                stats[f"descriptive_variant:{template_name}"] += 1
            return entry["value"]
        if name == "pua":
            return "".join(visible_template_args(args))
        if name in {"sk anchor", "anchor"}:
            title = "".join(visible_template_args(args))
            return HEADING_TOKEN.format(level=3, title=title) if title else ""
        if name in {"sk notes", "sk note"}:
            body = "".join(visible_template_args(args))
            return annotation(default_annotation_speaker, "commentary", body) if body else ""
        if name == "雙行註文":
            body = "".join(visible_template_args(args))
            speaker = "新校正" if "新校正" in body else "王冰"
            kind = "textual_collation" if speaker == "新校正" else "commentary"
            return annotation(speaker, kind, body) if body else ""
        if name in {"*", "**"}:
            visible = visible_template_args(args)
            if name == "**" and visible:
                base = visible[0]
                note = "".join(visible[1:])
                return base + (annotation("校注", "textual_collation", note) if note else "")
            note = "".join(visible)
            return annotation("校注", "textual_collation", note) if note else ""
        if name == "yl":
            return "".join(visible_template_args(args))
        if name == "?":
            stats["explicit_missing_glyph"] += 1
            return "〔原文缺字〕"

        visible = visible_template_args(args)
        if visible:
            stats[f"unknown_template_preserved:{name}"] += 1
            return "".join(visible)
        stats[f"unknown_template_removed:{name}"] += 1
        return ""

    previous = None
    rounds = 0
    while "{{" in text and text != previous and rounds < 20:
        previous = text
        text = INNER_TEMPLATE_RE.sub(replacement, text)
        rounds += 1
    if "{{" in text or "}}" in text:
        stats["residual_template_markup"] += text.count("{{") + text.count("}}")
    return text


def preprocess_lines(text: str, source: dict[str, Any]) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if source["id"] in {"commentary-suwen-zhangzhicong", "commentary-lingshu-zhangzhicong"}:
        speaker = source["author"].split("（", 1)[0]
        text = text.replace("（", ANN_START_TOKEN.format(speaker=speaker, kind="commentary") + "（")
        text = text.replace("）", "）" + ANN_END_TOKEN)
    lines = text.splitlines()
    output: list[str] = []
    in_quote = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        heading_match = re.match(r"^(={2,6})\s*(.*?)\s*\1\s*$", stripped)
        pseudo_heading = re.match(r"^<篇名>\s*(.*)$", stripped)
        pseudo_toc = re.match(r"^<目[录錄]>\s*(.*)$", stripped)
        formula_heading = re.match(r"^:+;\s*(.*)$", stripped)
        if in_quote and (
            not stripped
            or heading_match
            or pseudo_heading
            or pseudo_toc
            or QUOTE_END_LINE_RE.match(stripped)
        ):
            output.append(QUOTE_END_TOKEN)
            in_quote = False
        if heading_match:
            output.append(
                HEADING_TOKEN.format(level=len(heading_match.group(1)), title=heading_match.group(2))
            )
            continue
        if pseudo_heading:
            title = pseudo_heading.group(1).strip()
            if title:
                output.append(HEADING_TOKEN.format(level=3, title=title))
            continue
        if pseudo_toc:
            title = pseudo_toc.group(1).strip()
            if title:
                output.append(HEADING_TOKEN.format(level=2, title=title))
            continue
        if formula_heading:
            output.append(HEADING_TOKEN.format(level=4, title=formula_heading.group(1).strip()))
            continue
        if re.match(r"^(?:书名|書名|作者|朝代|年份)\s*[：:]", stripped):
            continue
        property_match = re.match(r"^属性\s*[：:]\s*(.*)$", stripped)
        if property_match:
            output.append(QUOTE_START_TOKEN)
            output.append(property_match.group(1))
            in_quote = True
            continue
        # Short standalone printed headings on ProofreadPage scan pages.
        if len(stripped) <= 42 and re.search(
            r"(?:篇第[〇零一二三四五六七八九十百千0-9]+|第[〇零一二三四五六七八九十百千0-9]+篇)$",
            stripped,
        ):
            output.append(HEADING_TOKEN.format(level=3, title=stripped))
            continue
        output.append(line)
    if in_quote:
        output.append(QUOTE_END_TOKEN)
    return "\n".join(output)


def strip_wikitext_markup(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<noinclude\b[^>]*>.*?</noinclude>", "", text, flags=re.I | re.DOTALL)
    text = re.sub(r"<ref\b[^>]*>.*?</ref>", "", text, flags=re.I | re.DOTALL)
    text = re.sub(r"<ref\b[^>]*/>", "", text, flags=re.I)
    text = re.sub(r"<(?:onlyinclude|includeonly|poem|div|span|small|big|center)\b[^>]*>", "", text, flags=re.I)
    text = re.sub(r"</(?:onlyinclude|includeonly|poem|div|span|small|big|center)>", "", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"-\{(?:[^:{}]+:)?(.*?)-\}", r"\1", text, flags=re.DOTALL)

    def internal_link(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        label = (match.group(2) or target).strip()
        if re.match(r"^(?:File|Image|Category|文件|檔案|分类|分類):", target, flags=re.I):
            return ""
        return label

    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", internal_link, text)
    text = re.sub(r"\[(?:https?://|//)\S+(?:\s+([^\]]+))?\]", lambda m: m.group(1) or "", text)
    text = re.sub(r"'{2,5}", "", text)
    text = re.sub(r"^\s*[|!]\s*[-+}]?.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s:*#;]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\\p[^\\\s]*?\.bmp", "", text, flags=re.I)
    text = text.replace("\\r", "").replace("\\x", "")
    return text


def clean_plain_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "", text)
    text = re.sub(fr"(?<={CJK_RE})\s+(?={CJK_RE})", "", text)
    text = re.sub(r"\s+([，。；：！？、）》】])", r"\1", text)
    return text.strip(" \t\n")


def explicit_speaker(value: str, fallback: str) -> str:
    match = re.match(
        r"(黃帝|黄帝|帝|岐伯|歧伯|伯高|雷公|少俞|少師|少师|問|问|答|師|师|"
        r"新校正|丁|呂|吕|楊|杨|虞|滑|馬|马|張|张|志|柯|方|喻|尤|徐|成|王|高|簡案|简案)",
        value,
    )
    if not match:
        return fallback
    label = match.group(1)
    aliases = {
        "帝": "黄帝", "黃帝": "黄帝", "歧伯": "岐伯", "問": "问者", "问": "问者",
        "答": "答者", "師": "师", "简案": "丹波元简", "簡案": "丹波元简",
        "志": "张志聪", "馬": "马莳", "马": "马莳", "張": "张介宾/张氏",
        "张": "张介宾/张氏", "呂": "吕广", "吕": "吕广", "楊": "杨玄操",
        "杨": "杨玄操", "丁": "丁德用", "虞": "虞庶", "滑": "滑寿",
    }
    return aliases.get(label, label)


def split_explicit_speakers(text: str, fallback: str) -> Iterable[tuple[str, str]]:
    matches = list(EXPLICIT_SPEAKER_RE.finditer(text))
    if not matches:
        cleaned = clean_plain_text(text)
        if cleaned:
            yield cleaned, fallback
        return
    if matches[0].start() > 0:
        prefix = clean_plain_text(text[: matches[0].start()])
        if prefix:
            yield prefix, fallback
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        piece = clean_plain_text(text[match.start() : end])
        if piece:
            yield piece, explicit_speaker(piece, fallback)


def page_volume(page: dict[str, Any]) -> str:
    title = page.get("parent_title") or page["title"]
    leaf = title.rsplit("/", 1)[-1]
    if re.search(r"(?:卷|序|目録|目錄|原病篇)", leaf):
        return leaf
    return ""


def default_speaker(source: dict[str, Any]) -> tuple[str, str]:
    special = {
        "commentary-suwen-wangbing": ("经文", "quoted_core"),
        "commentary-neijing-leijing": ("经文辑录", "quoted_core"),
        "commentary-jingui-xubin": ("张仲景原文", "quoted_core"),
    }
    if source["id"] in special:
        return special[source["id"]]
    if source["layer"] == "core":
        return ("原典", "core_text")
    return (source["author"].split("（", 1)[0], "commentary" if source["layer"] == "commentary" else "lineage")


def extract_source(
    source: dict[str, Any],
    character_maps: dict[str, dict[str, dict[str, Any]]],
    repairs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats: Counter[str] = Counter()
    blocks: list[dict[str, Any]] = []
    current_volume = ""
    current_section = ""
    current_subsection = ""
    base_speaker, base_type = default_speaker(source)

    for page_sequence, page in enumerate(source["pages"]):
        if not page["include_in_corpus"]:
            continue
        inferred_volume = page_volume(page)
        if inferred_volume:
            current_volume = inferred_volume
        raw = (PROJECT_DIR / page["raw_wikitext_path"]).read_text(encoding="utf-8")
        stats["raw_characters"] += len(raw)
        raw, repair_count_before = apply_manual_repairs(raw, source["id"], repairs)
        stats["manual_repairs"] += repair_count_before
        text = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
        text = re.sub(r"<noinclude\b[^>]*>.*?</noinclude>", "", text, flags=re.I | re.DOTALL)
        text = preprocess_lines(text, source)
        text = replace_templates(text, source, character_maps, stats)
        text, repair_count_after = apply_manual_repairs(text, source["id"], repairs)
        stats["manual_repairs"] += repair_count_after
        text = strip_wikitext_markup(text)

        speaker = base_speaker
        speaker_type = base_type
        mode_stack: list[tuple[str, str]] = []
        block_sequence_on_page = 0
        for token_or_text in TOKEN_RE.split(text):
            if not token_or_text:
                continue
            heading = re.fullmatch(r"⟦TCM-HEADING:(\d+):(.*?)⟧", token_or_text)
            annotation_start = re.fullmatch(r"⟦TCM-ANN-START:([^:⟧]*):([^⟧]*)⟧", token_or_text)
            if heading:
                level = int(heading.group(1))
                title = clean_plain_text(heading.group(2))
                if not title:
                    continue
                if level <= 2 and "卷" in title:
                    current_volume = title
                    current_section = ""
                    current_subsection = ""
                elif level <= 3:
                    current_section = title
                    current_subsection = ""
                else:
                    current_subsection = title
                stats["headings"] += 1
                continue
            if annotation_start:
                mode_stack.append((speaker, speaker_type))
                speaker = annotation_start.group(1) or base_speaker
                speaker_type = annotation_start.group(2) or "commentary"
                continue
            if token_or_text == ANN_END_TOKEN or token_or_text == QUOTE_END_TOKEN:
                speaker, speaker_type = mode_stack.pop() if mode_stack else (base_speaker, base_type)
                continue
            if token_or_text == QUOTE_START_TOKEN:
                mode_stack.append((speaker, speaker_type))
                if "序" in current_section:
                    speaker, speaker_type = base_speaker, "preface"
                elif source["id"] == "commentary-nanjing-jizhu":
                    speaker, speaker_type = "所引原文", "quoted_core"
                else:
                    speaker, speaker_type = "原文与注文混排", "mixed"
                continue

            preserve_siku_lines = source["id"] in {
                "commentary-neijing-leijing",
                "commentary-shanghan-yuchang",
                "commentary-jingui-xubin",
            }
            paragraph_pattern = r"\n+" if preserve_siku_lines else r"\n\s*\n+"
            for paragraph in re.split(paragraph_pattern, token_or_text):
                cleaned_paragraph = clean_plain_text(paragraph)
                if not cleaned_paragraph or not re.search(fr"{CJK_RE}|[A-Za-z0-9]", cleaned_paragraph):
                    continue
                role_parts: list[tuple[str, str, str]] = [(cleaned_paragraph, speaker, speaker_type)]
                if source["id"] == "commentary-jingui-xubin":
                    note_match = re.search(r"(?:註|注)曰", cleaned_paragraph)
                    if note_match:
                        role_parts = []
                        if note_match.start() > 0:
                            role_parts.append((cleaned_paragraph[: note_match.start()], "张仲景原文", "quoted_core"))
                        role_parts.append((cleaned_paragraph[note_match.start() :], "徐彬", "commentary"))
                    elif re.match(r"(?:論|论)曰", cleaned_paragraph):
                        role_parts = [(cleaned_paragraph, "徐彬", "commentary")]
                for role_text, role_speaker, role_type in role_parts:
                    for piece, piece_speaker in split_explicit_speakers(role_text, role_speaker):
                        effective_type = role_type
                        if piece_speaker != role_speaker and role_type in {"core_text", "quoted_core"}:
                            effective_type = "dialogue"
                        blocks.append(
                            {
                                "temporary_id": f"{source['id']}:{page_sequence:04d}:{block_sequence_on_page:04d}",
                                "work_id": source["id"],
                                "source_id": source["id"],
                                "layer": source["layer"],
                                "canon": source["canon"],
                                "target_works": source["target_works"],
                                "source_page_title": page["title"],
                                "source_revision_id": page["revision_id"],
                                "source_raw_sha256": page["raw_sha256"],
                                "volume": current_volume,
                                "section": current_section,
                                "subsection": current_subsection,
                                "speaker": piece_speaker,
                                "speaker_type": effective_type,
                                "text_source": piece,
                            }
                        )
                        block_sequence_on_page += 1
                        stats["extracted_characters"] += len(piece)

    summary = {
        "source_id": source["id"],
        "block_count": len(blocks),
        "statistics": dict(sorted(stats.items())),
        "speaker_counts": dict(Counter(block["speaker"] for block in blocks).most_common()),
        "speaker_type_counts": dict(Counter(block["speaker_type"] for block in blocks).most_common()),
    }
    return blocks, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--character-map", type=Path, default=DEFAULT_CHARACTER_MAP)
    parser.add_argument("--repairs", type=Path, default=DEFAULT_REPAIRS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    inventory = load_json(args.inventory)
    character_maps = load_json(args.character_map)["maps"]
    repairs = load_json(args.repairs)["repairs"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []

    for source in inventory["sources"]:
        blocks, summary = extract_source(source, character_maps, repairs)
        output = args.output_dir / f"{source['id']}.jsonl"
        with output.open("w", encoding="utf-8", newline="\n") as handle:
            for block in blocks:
                handle.write(json.dumps(block, ensure_ascii=False, separators=(",", ":")) + "\n")
        summaries.append(summary)
        print(f"{source['id']}: {len(blocks)} extracted blocks")

    (args.output_dir / "summary.json").write_text(
        json.dumps({"schema_version": 1, "sources": summaries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Extracted {len(summaries)} sources -> {args.output_dir}")


if __name__ == "__main__":
    main()
