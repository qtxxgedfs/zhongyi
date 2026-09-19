#!/usr/bin/env python3
"""Render a study.py research packet as accessible Markdown or standalone HTML."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any


def clean_inline(value: str) -> str:
    return " ".join(value.replace("\x00", "").split())


def location(item: dict[str, Any]) -> str:
    parts = [item.get("title", ""), item.get("volume", ""), item.get("section", ""), item.get("subsection", "")]
    return " · ".join(clean_inline(part) for part in parts if part)


def quote_markdown(value: str) -> str:
    return "\n".join("> " + line for line in value.splitlines() if line.strip())


def conclusion(packet: dict[str, Any]) -> str:
    level = packet["classification"]["level"]
    if level == "M3":
        return packet["safety_first"]["message"]
    if level == "M2":
        return "以下将古籍记载与现代疗效或安全证据严格分开；内容用于研读，不构成个体诊疗或用药建议。"
    if level == "M1":
        return "古典理论与现代医学概念通常不能直接等同；以下先列工作底本文献，再说明可核验的对应边界。"
    return "以下是当前所收工作底本中的原典和医家材料；本题属于文献研读，不强行附会现代医学。"


def markdown_item(item: dict[str, Any], label: str) -> list[str]:
    author = clean_inline(item.get("author", ""))
    speaker = clean_inline(item.get("speaker", ""))
    lines = [f"### {label}｜{clean_inline(item['title'])}", "", f"**{label}原文**", "", quote_markdown(item["text_simplified"]), ""]
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
    lines.extend(["## 一句话结论", "", conclusion(packet), "", "---", "", "## 🟩 A｜原典", ""])
    if packet["A_core"]:
        for item in packet["A_core"]:
            lines.extend(markdown_item(item, "原典"))
    elif packet["safety_first"]["classic_retrieval_deferred"]:
        lines.extend(["急症风险问题已暂缓古籍检索；处理现实安全后，才可另作纯文献研读。", ""])
    else:
        lines.extend(["当前所收工作底本未检得足够匹配的原典段落。", ""])

    lines.extend(["---", "", "## 🟧 B｜历代医家", ""])
    if packet["B_physicians"]:
        for item in packet["B_physicians"]:
            lines.extend(markdown_item(item, "医家"))
    else:
        lines.extend(["当前所收工作底本未检得合格的医家材料；不凭模型记忆补造。", ""])

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
    for item in items:
        output.append(
            "<article>"
            f"<h3>{html.escape(clean_inline(item['title']))}</h3>"
            f"<blockquote>{html.escape(item['text_simplified'])}</blockquote>"
            f"<p><strong>作者/题署：</strong>{html.escape(clean_inline(item.get('author', '')))}</p>"
            f"<p><strong>出处：</strong>{html.escape(location(item))}</p>"
            f"<p class=\"source\"><strong>段落ID：</strong>{html.escape(item['id'])}；"
            f"<a href=\"{html.escape(item['fixed_source_url'], quote=True)}\">固定修订 oldid={item['source_revision_id']}</a></p>"
            "</article>"
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
    cards.append(card_html("一句话结论", "summary", f"<p>{html.escape(conclusion(packet))}</p>"))
    core_empty = "急症风险问题已暂缓古籍检索。" if packet["safety_first"]["classic_retrieval_deferred"] else "当前所收工作底本未检得足够匹配的原典段落。"
    cards.append(card_html("🟩 A｜原典", "core", classic_html(packet["A_core"], core_empty)))
    cards.append(card_html("🟧 B｜历代医家", "physicians", classic_html(packet["B_physicians"], "当前未检得合格医家材料，不凭记忆补造。")))
    if packet["C_modern"]["required"]:
        cards.append(
            card_html(
                "🟦 C｜现代医学",
                "modern",
                modern_html(packet["C_modern"]["cache"]["records"], packet["C_modern"]["online_search_plan"]["required"]),
            )
        )
    style = """
:root{color-scheme:light;font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#f4f1e8;color:#17202a}
body{margin:0 auto;max-width:920px;padding:24px;font-size:18px;line-height:1.75}
h1{font-size:30px;line-height:1.3}h2{font-size:23px;margin-top:0}h3{font-size:20px}
.card{border:3px solid #273746;padding:20px;margin:18px 0;background:#fff}
.summary{background:#fff9db}.core{background:#eaf7ea;border-color:#176b2c}.physicians{background:#fff0dc;border-color:#9a4d00}.modern{background:#e8f2ff;border-color:#145a9c}.safety{background:#fff0f0;border-color:#9c1c1c}
blockquote{margin:12px 0;padding:14px 18px;border-left:6px solid #273746;background:rgba(255,255,255,.72);font-size:19px}
.source{font-size:16px}a{color:#0645ad;text-decoration:underline;text-underline-offset:3px}strong{font-weight:750}
@media(max-width:640px){body{padding:14px;font-size:17px}.card{padding:15px}h1{font-size:26px}h2{font-size:21px}}
@media print{body{max-width:none}.card{break-inside:avoid;background:#fff}}
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
