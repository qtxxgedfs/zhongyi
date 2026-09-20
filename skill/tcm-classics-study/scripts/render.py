#!/usr/bin/env python3
"""Render a study.py research packet as accessible Markdown or standalone HTML."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any


RELATION_LABELS = {
    "direct_commentary": "直接注释", "textual_collation": "校勘辨析",
    "reordering": "重订编次", "classification": "分类整理",
    "theoretical_extension": "理论发挥", "clinical_extension": "临床阐发",
    "disagreement": "作品含辨析或分歧（不代表本段已有分歧）",
    "lineage_predecessor": "前导学术源流（非后世注家）",
}


def relation_labels(item: dict[str, Any]) -> str:
    return "、".join(RELATION_LABELS.get(label, label) for label in item.get("relationship", []))


def clean_inline(value: str) -> str:
    return " ".join(value.replace("\x00", "").split())


def location(item: dict[str, Any]) -> str:
    parts = [item.get("title", ""), item.get("volume", ""), item.get("section", ""), item.get("subsection", "")]
    return " · ".join(clean_inline(part) for part in parts if part)


def quote_markdown(value: str) -> str:
    return "\n".join("> " + line for line in value.splitlines() if line.strip())


def conclusion(packet: dict[str, Any]) -> str:
    """A deterministic reading notice, not an AI-generated topic conclusion."""
    level = packet["classification"]["level"]
    if level == "M3":
        return packet["safety_first"]["message"]
    if level == "M2":
        return "以下将古籍记载与现代疗效或安全证据严格分开；内容用于研读，不构成个体诊疗或用药建议。"
    if level == "M1":
        return "古典理论与现代医学概念通常不能直接等同；以下先列工作底本文献，再说明可核验的对应边界。"
    return "以下为本次检得的材料预览，不是已完成的白话研读；主旨、逐句解释和关键词由宿主依据引文另行组织。"


def route_notice(packet: dict[str, Any]) -> str:
    return clean_inline(
        packet.get("classic_search", {}).get("route_resolution", {}).get("message", "")
    )


def clarification(packet: dict[str, Any]) -> str:
    item = packet.get("classic_search", {}).get("needs_clarification", {})
    return clean_inline(item.get("prompt", "")) if item.get("required") else ""


def markdown_item(item: dict[str, Any], label: str) -> list[str]:
    author = clean_inline(item.get("author", ""))
    speaker = clean_inline(item.get("speaker", ""))
    core_quote = item.get("core_quote") or item["text_simplified"]
    lines = [f"### {label}｜{clean_inline(item['title'])}", ""]
    match = item.get("match", {})
    if match.get("label"):
        lines.extend([f"**匹配说明：** {clean_inline(match['label'])}  "])
    if item.get("context_role"):
        role_labels = {"before": "上文", "anchor": "本段", "after": "下文"}
        lines.extend([f"**上下文位置：** {role_labels.get(item['context_role'], item['context_role'])}  "])
    lines.extend([f"**{label}核心引文**", "", quote_markdown(core_quote), ""])
    if item.get("full_text_available"):
        lines.extend(
            [
                f"**完整段落：** 本段共{item.get('full_text_characters', len(item['text_simplified']))}字，默认未展开；可按段落ID继续查看全文或前后文。",
                "",
            ]
        )
    if item.get("layer") != "core" and item.get("relationship"):
        lines.extend([f"**材料关系：** {relation_labels(item)}  "])
    if item.get("speaker_type") == "quoted_core":
        lines.extend(["**材料性质：** 注书转引经文，不作为医家的独立观点。  "])
    if author:
        lines.extend([f"**作者/题署：** {author}  "])
    if speaker:
        lines.extend([f"**本段说话者：** {speaker}  "])
    lines.extend(
        [
            f"**出处：** {location(item)}  ",
            f"**段落ID：** `{item['id']}`  ",
            f"**固定修订：** [{clean_inline(item['source_page_title'])} · oldid={item['source_revision_id']}]({item['fixed_source_url']})",
            "",
        ]
    )
    return lines


def modern_markdown(record: dict[str, Any]) -> list[str]:
    source = record["source"]
    return [
        f"### 现代证据｜{record['conclusion_label_zh']}",
        "",
        f"**结论：** {clean_inline(record['summary_zh'])}",
        "",
        f"**对应直接性：** {record['directness_label_zh']}  ",
        f"**证据类型：** {record['evidence_type_label_zh']}  ",
        f"**可信度：** {record['confidence_label_zh']}  ",
        f"**主要限制：** {clean_inline(record['limitations_zh'])}",
        "",
        f"**来源：** {clean_inline(source['organization'])}，[{clean_inline(source['title'])}]({source['url']})，{source['publication_date']}  ",
        f"**最近核验：** {source['verified_at']}；缓存有效至 {source['expires_at']}",
        "",
    ]


def render_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# 中医经典研读",
        "",
        f"**问题：** {clean_inline(packet['query'])}",
        "",
    ]
    if packet["safety_first"]["required"]:
        lines.extend(["## ⚠️ 先看安全提醒", "", f"**{clean_inline(packet['safety_first']['message'])}**", "", "---", ""])
    notice = route_notice(packet)
    if notice:
        lines.extend(["## 范围核对", "", f"**{notice}**", ""])
    clarify = clarification(packet)
    if clarify:
        lines.extend(["## 范围提示", "", clarify, ""])
    lines.extend(["## 材料预览说明", "", conclusion(packet), ""])
    if packet["A_core"]:
        lines.extend(["---", "", "## 🟩 A｜原典", ""])
        for item in packet["A_core"]:
            lines.extend(markdown_item(item, "原典"))
    elif packet["safety_first"]["classic_retrieval_deferred"]:
        lines.extend(["急症风险问题已暂缓古籍检索；处理现实安全后，才可另作纯文献研读。", ""])
    elif not packet["B_physicians"] and not clarify:
        lines.extend(["本次没有可展示的指定范围材料，请补充范围或原句。", ""])

    if packet["B_physicians"]:
        lines.extend(["---", "", "## 🟧 B｜历代医家", ""])
        for item in packet["B_physicians"]:
            lines.extend(markdown_item(item, "医家"))

    if packet.get("source_alternatives"):
        lines.extend(["---", "", "## 范围外备选｜不代表指定医家的观点", ""])
        for item in packet["source_alternatives"]:
            lines.extend(markdown_item(item, "备选材料"))
    omitted = packet.get("classic_search", {}).get("quality_policy", {}).get("budget_omitted", [])
    if omitted:
        lines.extend(["### 已检得但因预算未展示", "",
                      "、".join(f"`{item['id']}`（{item['characters']}字）" for item in omitted),
                      "", "可增加字符预算后按ID读取；这不表示未检得。", ""])

    modern = packet["C_modern"]
    if modern["required"]:
        lines.extend(["---", "", "## 🟦 C｜现代医学", ""])
        records = [item for item in modern["cache"]["records"] if item["citation_recommended"]]
        if records:
            for record in records:
                lines.extend(modern_markdown(record))
        if modern["online_search_plan"]["required"]:
            lines.extend(
                [
                    "**联网核验状态：** 当前缓存缺失、覆盖不完整、已过期，或用户要求最新资料；需按检索计划读取完整来源页面。",
                    "",
                ]
            )
        if not records:
            lines.extend(["当前没有可直接引用的有效缓存。若联网失败，本次不提供未经核验的现代疗效结论。", ""])

    anchor = packet.get("answer_contract", {}).get("primary_passage_id")
    if anchor:
        lines.extend(
            [
                "---",
                "",
                "### 继续研读",
                "",
                f"如需全文或前后文，可继续追问并使用本次主段落ID：`{anchor}`。",
                "",
            ]
        )
    lines.extend(
        [
            "---",
            "",
            "### 使用边界",
            "",
            "- 本产品使用可追溯的工作底本，不声称是无异文、无错误的唯一权威文本。",
            "- 隔离内容不会进入搜索或引文。",
            "- 不提供个体诊断、处方、剂量换算、停换药或以古方替代急救的建议。",
            "",
        ]
    )
    return "\n".join(lines)


def card_html(title: str, css_class: str, body: str) -> str:
    return f'<section class="card {css_class}"><h2>{html.escape(title)}</h2>{body}</section>'


def classic_html(items: list[dict[str, Any]], empty: str) -> str:
    if not items:
        return f"<p>{html.escape(empty)}</p>"
    output: list[str] = []
    role_labels = {"before": "上文", "anchor": "本段", "after": "下文"}
    for item in items:
        core_quote = item.get("core_quote") or item["text_simplified"]
        match = item.get("match", {})
        metadata: list[str] = []
        if match.get("label"):
            metadata.append(f"<p><strong>匹配说明：</strong>{html.escape(match['label'])}</p>")
        if item.get("context_role"):
            metadata.append(
                f"<p><strong>上下文位置：</strong>{html.escape(role_labels.get(item['context_role'], item['context_role']))}</p>"
            )
        if item.get("relationship") and item.get("layer") != "core":
            metadata.append(
                f"<p><strong>材料关系：</strong>{html.escape(relation_labels(item))}</p>"
            )
        if item.get("speaker_type") == "quoted_core":
            metadata.append("<p><strong>材料性质：</strong>注书转引经文，不作为医家的独立观点。</p>")
        if item.get("speaker"):
            metadata.append(f"<p><strong>本段说话者：</strong>{html.escape(item['speaker'])}</p>")
        full_text = ""
        if item.get("full_text_available"):
            full_text = (
                "<details><summary>展开完整段落（"
                f"{item.get('full_text_characters', len(item['text_simplified']))}字）</summary>"
                f"<blockquote>{html.escape(item['text_simplified'])}</blockquote></details>"
            )
        output.append(
            "<article>"
            f"<h3>{html.escape(clean_inline(item['title']))}</h3>"
            + f"<p><strong>核心引文：</strong></p><blockquote>{html.escape(core_quote)}</blockquote>"
            + full_text
            + "<details><summary>出处与材料信息</summary>" + "".join(metadata)
            + f"<p><strong>作者/题署：</strong>{html.escape(clean_inline(item.get('author', '')))}</p>"
            f"<p><strong>出处：</strong>{html.escape(location(item))}</p>"
            f"<p class=\"source\"><strong>段落ID：</strong>{html.escape(item['id'])}；"
            f"<a href=\"{html.escape(item['fixed_source_url'], quote=True)}\">固定修订 oldid={item['source_revision_id']}</a></p>"
            "</details></article>"
        )
    return "".join(output)


def modern_html(records: list[dict[str, Any]], needs_online: bool) -> str:
    output: list[str] = []
    for record in records:
        if not record["citation_recommended"]:
            continue
        source = record["source"]
        output.append(
            "<article>"
            f"<h3>{html.escape(record['conclusion_label_zh'])}</h3>"
            f"<p><strong>结论：</strong>{html.escape(record['summary_zh'])}</p>"
            f"<p><strong>直接性：</strong>{html.escape(record['directness_label_zh'])}；"
            f"<strong>证据类型：</strong>{html.escape(record['evidence_type_label_zh'])}；"
            f"<strong>可信度：</strong>{html.escape(record['confidence_label_zh'])}</p>"
            f"<p><strong>限制：</strong>{html.escape(record['limitations_zh'])}</p>"
            f"<p class=\"source\"><strong>来源：</strong>{html.escape(source['organization'])}，"
            f"<a href=\"{html.escape(source['url'], quote=True)}\">{html.escape(source['title'])}</a>，"
            f"{html.escape(source['publication_date'])}；核验 {html.escape(source['verified_at'])}</p>"
            "</article>"
        )
    if needs_online:
        output.append("<p><strong>需要联网核验：</strong>缓存不足、已过期或用户要求最新资料；搜索摘要不能作为证据。</p>")
    if not output:
        output.append("<p>当前没有可直接引用的有效现代证据缓存；联网失败时不补造结论。</p>")
    return "".join(output)


def render_html(packet: dict[str, Any]) -> str:
    cards: list[str] = []
    if packet["safety_first"]["required"]:
        cards.append(card_html("⚠️ 先看安全提醒", "safety", f"<p><strong>{html.escape(packet['safety_first']['message'])}</strong></p>"))
    notice = route_notice(packet)
    if notice:
        cards.append(card_html("范围核对", "notice", f"<p><strong>{html.escape(notice)}</strong></p>"))
    clarify = clarification(packet)
    if clarify:
        cards.append(card_html("范围提示", "notice", f"<p>{html.escape(clarify)}</p>"))
    cards.append(card_html("材料预览说明", "summary", f"<p>{html.escape(conclusion(packet))}</p>"))
    if packet["A_core"]:
        cards.append(card_html("🟩 A｜原典", "core", classic_html(packet["A_core"], "")))
    elif packet["safety_first"]["classic_retrieval_deferred"]:
        cards.append(card_html("古籍检索状态", "notice", "<p>急症风险问题已暂缓古籍检索。</p>"))
    elif not packet["B_physicians"] and not clarify:
        cards.append(card_html("检索状态", "notice", "<p>本次没有可展示的指定范围材料，请补充范围或原句。</p>"))
    if packet["B_physicians"]:
        cards.append(card_html("🟧 B｜历代医家", "physicians", classic_html(packet["B_physicians"], "")))
    if packet.get("source_alternatives"):
        cards.append(card_html("范围外备选｜不代表指定医家的观点", "notice",
                               classic_html(packet["source_alternatives"], "")))
    omitted = packet.get("classic_search", {}).get("quality_policy", {}).get("budget_omitted", [])
    if omitted:
        text = "、".join(f"{item['id']}（{item['characters']}字）" for item in omitted)
        cards.append(card_html("已检得但因预算未展示", "notice",
                               f"<p>{html.escape(text)}</p><p>可增加字符预算后按ID读取；这不表示未检得。</p>"))
    if packet["C_modern"]["required"]:
        cards.append(
            card_html(
                "🟦 C｜现代医学",
                "modern",
                modern_html(packet["C_modern"]["cache"]["records"], packet["C_modern"]["online_search_plan"]["required"]),
            )
        )
    anchor = packet.get("answer_contract", {}).get("primary_passage_id")
    if anchor:
        cards.append(card_html("继续研读", "follow-up", f"<p>如需全文或前后文，可继续追问主段落 <code>{html.escape(anchor)}</code>。</p>"))
    style = """
:root{color-scheme:light;font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#f4f1e8;color:#17202a}
body{margin:0 auto;max-width:920px;padding:24px;font-size:18px;line-height:1.75}
h1{font-size:30px;line-height:1.3}h2{font-size:23px;margin-top:0}h3{font-size:20px}
.card{border:3px solid #273746;padding:20px;margin:18px 0;background:#fff}
.summary{background:#fff9db}.core{background:#eaf7ea;border-color:#176b2c}.physicians{background:#fff0dc;border-color:#9a4d00}.modern{background:#e8f2ff;border-color:#145a9c}.safety{background:#fff0f0;border-color:#9c1c1c}.notice{background:#fff9e6;border-color:#7a5a00}.follow-up{background:#f5f5f5}
blockquote{margin:12px 0;padding:14px 18px;border-left:6px solid #273746;background:rgba(255,255,255,.72);font-size:19px}
details{margin:12px 0}summary{cursor:pointer;font-weight:700;text-decoration:underline}.source{font-size:16px}a{color:#0645ad;text-decoration:underline;text-underline-offset:3px}strong{font-weight:750}
@media(max-width:640px){body{padding:14px;font-size:17px}.card{padding:15px}h1{font-size:26px}h2{font-size:21px}}
@media print{body{max-width:none}.card{break-inside:avoid;background:#fff}details>blockquote{display:block}}
""".strip()
    boundary = "<section class=\"card\"><h2>使用边界</h2><ul><li>工作底本不是唯一权威文本。</li><li>隔离内容不可检索或引用。</li><li>不诊断、不开方、不换算个人剂量、不建议停换药。</li></ul></section>"
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>中医经典研读</title><style>{style}</style></head><body>"
        f"<h1>中医经典研读</h1><p><strong>问题：</strong>{html.escape(clean_inline(packet['query']))}</p>"
        + "".join(cards)
        + boundary
        + "</body></html>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--format", choices=["markdown", "html"], default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    packet = json.loads(args.input.read_text(encoding="utf-8"))
    result = render_markdown(packet) if args.format == "markdown" else render_html(packet)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8")
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print(result)


if __name__ == "__main__":
    main()
