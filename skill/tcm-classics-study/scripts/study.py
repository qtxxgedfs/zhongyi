#!/usr/bin/env python3
"""Prepare one quality-gated A/B/C research packet for a WorkBuddy answer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import modern_evidence
import search as classic_search

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_CLASSICS = SKILL_DIR / "data" / "classics.sqlite"
DEFAULT_EVIDENCE = SKILL_DIR / "data" / "evidence-cache.sqlite"


def fit_budget(results: list[dict[str, Any]], budget: int) -> tuple[list[dict[str, Any]], int]:
    """Keep whole, traceable passages without ever exceeding the assigned budget."""
    selected: list[dict[str, Any]] = []
    used = 0
    for result in results:
        length = len(result["text_simplified"])
        if used + length > budget:
            continue
        selected.append(result)
        used += length
    return selected, used


def anchored_payload(
    connection,
    anchor_id: str,
    before: int,
    after: int,
) -> dict[str, Any]:
    payload = classic_search.context(connection, anchor_id, before, after)
    metadata = dict(connection.execute("SELECT key, value FROM schema_info"))
    missing = bool(payload.get("error"))
    return {
        "results": payload.get("results", []),
        "route": {"anchor_id": anchor_id},
        "route_resolution": {
            "mode": "anchored-context",
            "conflict_detected": False,
            "requested_aliases": [],
            "recovered_works": [],
            "message": "",
        },
        "query_plan": {
            "intent": {"mode": "context", "scope_too_broad": False, "broad_concepts": []},
            "terms": [],
            "term_sources": [],
            "matched_expansions": [],
            "preferred_passage_ids": [anchor_id],
            "explicit_terms_supplied": False,
        },
        "needs_clarification": {
            "required": missing,
            "reason": "anchor-not-found" if missing else "",
            "prompt": "未找到上一轮段落，请提供有效段落ID。" if missing else "",
        },
        "quality_policy": {
            "principle": "宁缺毋滥：只展开明确指定段落的连续上下文。",
            "displayed_results": len(payload.get("results", [])),
            "omitted_candidates": {},
        },
        "terms": [],
        "database_build_status": metadata.get("build_status", "candidate"),
        "quarantined_passages_excluded": int(metadata.get("quarantined_passages_excluded", 0)),
        "elapsed_ms": 0.0,
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    evidence_connection = modern_evidence.connect(args.evidence_db)
    try:
        classification = modern_evidence.classify(evidence_connection, args.query)
        cache = modern_evidence.lookup(
            evidence_connection,
            classification,
            args.topics,
            modern_evidence.parse_date(args.as_of),
            args.include_stale,
        )
        online_plan = modern_evidence.search_plan(classification, cache)
    finally:
        evidence_connection.close()

    safety_first = classification["level"] == "M3"
    classic_payload: dict[str, Any] = {
        "results": [],
        "route": {},
        "route_resolution": {},
        "query_plan": {},
        "needs_clarification": {"required": False, "reason": "", "prompt": ""},
        "quality_policy": {"principle": "宁缺毋滥", "displayed_results": 0, "omitted_candidates": {}},
        "terms": [],
        "elapsed_ms": 0.0,
    }
    if safety_first and not args.include_classics_after_safety:
        # Read only build metadata; do not retrieve classical passages before the
        # emergency-first response has been produced.
        classic_connection = classic_search.connect(args.classics_db)
        try:
            metadata = dict(classic_connection.execute("SELECT key, value FROM schema_info"))
            classic_payload["database_build_status"] = metadata.get("build_status", "candidate")
            classic_payload["quarantined_passages_excluded"] = int(
                metadata.get("quarantined_passages_excluded", 0)
            )
        finally:
            classic_connection.close()
    if not safety_first or args.include_classics_after_safety:
        classic_connection = classic_search.connect(args.classics_db)
        try:
            if args.anchor_id:
                classic_payload = anchored_payload(
                    classic_connection,
                    args.anchor_id,
                    args.context_before,
                    args.context_after,
                )
            else:
                search_args = SimpleNamespace(
                    query=args.query,
                    terms=args.terms,
                    rules=args.query_rules,
                    canon=args.canon,
                    work=args.work,
                    layers=args.layers,
                    author=args.author,
                    limit_core=args.limit_core,
                    limit_commentary=args.limit_commentary,
                    limit_total=args.limit_total,
                    candidate_limit=args.candidate_limit,
                    route_fallback=getattr(args, "route_fallback", True),
                )
                classic_payload = classic_search.search(classic_connection, search_args)
        finally:
            classic_connection.close()

    retrieved = classic_payload["results"]
    ordered = list(retrieved)
    anchor = next((item for item in retrieved if item["id"] == args.anchor_id), None)
    anchor_over_budget = bool(anchor and len(anchor["text_simplified"]) > args.character_budget)
    if anchor:
        ordered.sort(key=lambda item: (item["id"] != args.anchor_id,
                                      abs(item["sequence"] - anchor["sequence"])))
    # Share the full budget across layers. Never silently replace an oversized anchor
    # with its neighbour, and never change text_simplified to a fabricated/truncated passage.
    selected, used = fit_budget([] if anchor_over_budget else ordered, args.character_budget)
    primary_passage_id = (args.anchor_id if anchor and not anchor_over_budget else
                          selected[0]["id"] if selected and not args.anchor_id else None)
    if args.anchor_id:
        selected.sort(key=lambda item: item["sequence"])
    core = [item for item in selected if item["layer"] == "core"]
    extension = [item for item in selected if item["layer"] != "core"]
    core_chars = sum(len(item["text_simplified"]) for item in core)
    extension_chars = used - core_chars
    alternatives, alternative_chars = fit_budget(classic_payload.get("alternative_results", []),
                                                  args.character_budget - used)
    selected_ids = {item["id"] for item in selected}
    budget_omitted = [{"id": item["id"], "characters": len(item["text_simplified"]),
                       "reason": "anchor-over-budget" if anchor_over_budget else "character-budget"}
                      for item in retrieved if item["id"] not in selected_ids]
    alternative_ids = {item["id"] for item in alternatives}
    budget_omitted.extend({"id": item["id"], "characters": len(item["text_simplified"]),
                           "reason": "character-budget", "scope": "alternative"}
                          for item in classic_payload.get("alternative_results", [])
                          if item["id"] not in alternative_ids)
    coverage = classic_payload.get("scope_coverage", [])
    for group in coverage:
        if group["status"] == "matched" and not any(
            classic_search.matches_group(item, item.get("match", {}), group) for item in selected
        ):
            group["status"] = "not-displayed-budget"
    missing_groups = [group["label"] for group in coverage if group["status"] != "matched"]
    if anchor_over_budget or (retrieved and not selected):
        classic_payload["needs_clarification"] = {
            "required": True, "reason": "anchor-over-budget" if anchor_over_budget else "budget-excluded",
            "prompt": "已检得材料，但完整段落超过本次预算，尚未展示；请增加字符预算后按段落ID读取，不代表未检得。",
        }
    elif missing_groups and len(coverage) > 1:
        classic_payload["needs_clarification"] = {
            "required": True, "reason": "incomplete-comparison",
            "prompt": "以下对象尚无可展示的直接材料：" + "、".join(missing_groups) + "；不能据此完成全部比较。",
        }
    quality = classic_payload["quality_policy"]
    quality["retrieved_results"] = len(retrieved)
    quality["displayed_results"] = len(selected)
    quality["budget_omitted"] = budget_omitted
    quality["displayed_alternatives"] = len(alternatives)
    quality["alternative_budget_omitted_ids"] = [item["id"] for item in classic_payload.get("alternative_results", [])
                                                if item["id"] not in alternative_ids]
    classic_payload["scope_coverage"] = coverage

    warnings = [
        "本产品使用可追溯工作底本，不声称是无异文、无错误的唯一权威文本。",
        "隔离段落不在运行时数据库中，不能被检索或引用。",
    ]
    if classic_payload.get("database_build_status") == "candidate":
        warnings.append("经典数据库为可运行候选版，后续仍会继续底本质量精修。")
    if safety_first:
        warnings.append("M3问题默认暂缓古籍检索，必须先呈现急救分流；不得用古方替代急救。")
    if classification["modern_layer_required"] and not cache["records"]:
        warnings.append("本地缓存没有可用现代证据；联网失败时不得凭模型记忆补造现代结论。")
    if classic_payload.get("route_resolution", {}).get("message"):
        warnings.append(classic_payload["route_resolution"]["message"])
    if budget_omitted:
        warnings.append("部分已检得段落因字符预算未展示，详见quality_policy.budget_omitted；不代表未检得。")
    if classic_payload.get("needs_clarification", {}).get("required"):
        warnings.append(classic_payload["needs_clarification"]["prompt"])

    classic_quote_ids = [item["id"] for item in [*selected, *alternatives]]
    required_sections = ["一句话主旨"]
    if core:
        required_sections.append("🟩 A｜原典")
    if extension:
        required_sections.append("🟧 B｜历代医家")
    if classification["modern_layer_required"]:
        required_sections.append("🟦 C｜现代医学")

    return {
        "schema_version": 2,
        "runtime_status": "candidate-runnable",
        "query": args.query,
        "interaction_principle": "宁缺毋滥",
        "standard_study_only": True,
        "safety_first": {
            "required": safety_first,
            "message": classification["safety_message"],
            "classic_retrieval_deferred": safety_first and not args.include_classics_after_safety,
        },
        "classification": classification,
        "classic_search": {
            "terms": classic_payload.get("terms", []),
            "query_plan": classic_payload.get("query_plan", {}),
            "route": classic_payload.get("route", {}),
            "route_resolution": classic_payload.get("route_resolution", {}),
            "needs_clarification": classic_payload.get("needs_clarification", {}),
            "quality_policy": classic_payload.get("quality_policy", {}),
            "database_build_status": classic_payload.get("database_build_status", "candidate"),
            "quarantined_passages_excluded": classic_payload.get("quarantined_passages_excluded", 0),
            "elapsed_ms": classic_payload.get("elapsed_ms", 0.0),
            "anchor_id": args.anchor_id,
            "scope_coverage": coverage,
        },
        "source_alternatives": alternatives,
        "A_core": core,
        "B_physicians": extension,
        "C_modern": {
            "required": classification["modern_layer_required"],
            "cache": cache,
            "online_search_plan": online_plan,
        },
        "context_budget": {
            "maximum_characters": args.character_budget,
            "selected_characters": used + alternative_chars,
            "core_characters": core_chars,
            "physician_characters": extension_chars,
            "alternative_characters": alternative_chars,
        },
        "answer_contract": {
            "protocol_version": 2,
            "mode": "standard",
            "interaction_principle": "宁缺毋滥：不为凑数展示弱相关、残缺或无法独立解释的材料。",
            "required_sections": required_sections,
            "omit_A_when": "本次未展示原典；指定医家或预算未展示不得表述为原典不存在",
            "omit_B_when": "没有直接相关且可独立解释的医家材料",
            "source_alternatives_rule": "范围外备选必须单独标注实际作者与作品，不能充当指定医家的观点或补齐比较。",
            "quoted_core_rule": "上下文中的quoted_core仅为注书转引经文，不是注家的独立观点。",
            "comparison_complete": not missing_groups,
            "omit_C_when": "classification.level=M0",
            "classic_quote_field": "text_simplified",
            "default_display_quote_field": "core_quote",
            "classic_quote_ids": classic_quote_ids,
            "primary_passage_id": primary_passage_id,
            "modern_cache_record_ids": [
                item["id"] for item in cache["records"] if item["citation_recommended"]
            ],
            "standard_protocol": [
                "先用一句话说明本次材料能够支持的主旨，不把概括冒充古籍原文。",
                "原典默认展示最相关的核心引文；完整段落和前后文留作继续追问，不堆砌材料。",
                "对核心引文逐句解释，每句先列数据库原句，再标明白话研读解释。",
                "解释3至5个真正影响理解的关键词，并指出古今词义或常见误解。",
                "只有医家材料与本题直接相关时才列B层；比较相同点和不同点时逐项绑定引文ID。",
                "材料不足以确认医家分歧时明确说不足，不从作品级标签推造段落观点。",
                "问题存在合理现代对应时说明对应边界、证据直接性和限制；纯文献题不强加C层。",
            ],
            "route_conflict_rule": (
                "客观说明指定范围的检索情况与范围外材料的实际来源，不推断用户记错，不混淆归属。"
                if classic_payload.get("route_resolution", {}).get("message")
                else "not-applicable"
            ),
            "clarification_rule": (
                classic_payload.get("needs_clarification", {}).get("prompt", "")
                if classic_payload.get("needs_clarification", {}).get("required")
                else "not-required"
            ),
            "follow_up": {
                "state_storage": "none",
                "anchor_id": primary_passage_id,
                "instruction": (
                    "用户追问上一条、前后文或全文时，将本字段的anchor_id作为下一次study.py --anchor-id；"
                    "不得保存隐式用户查询日志。"
                ),
            },
            "rules": [
                "原文、医家观点、AI研读解释和现代来源结论分开标记。",
                "直接引文只能逐字复制本研究包允许的text_simplified或其连续子串core_quote。",
                "不把中医证候或理论概念直接等同于现代疾病和解剖结构。",
                "不诊断、不开方、不换算个人剂量、不建议停换药。",
                "没有高质量命中时写当前所收工作底本未检得足够直接的材料，不作历史绝对否定。",
            ],
        },
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--terms", help="Comma-separated classic search terms")
    parser.add_argument("--topics", help="Comma-separated explicit modern topic IDs")
    parser.add_argument("--classics-db", type=Path, default=DEFAULT_CLASSICS)
    parser.add_argument("--evidence-db", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--query-rules", type=Path, default=classic_search.DEFAULT_RULES)
    parser.add_argument("--canon", choices=["auto", "huangdi", "zhongjing", "nanjing", "wenbing"], default="auto")
    parser.add_argument("--work", default="auto")
    parser.add_argument("--layers", default="all")
    parser.add_argument("--author")
    parser.add_argument("--no-route-fallback", dest="route_fallback", action="store_false")
    parser.add_argument("--limit-core", type=int, default=2)
    parser.add_argument("--limit-commentary", type=int, default=2)
    parser.add_argument("--limit-total", type=int, default=4)
    parser.add_argument("--candidate-limit", type=int, default=240)
    parser.add_argument("--character-budget", type=int, default=2500)
    parser.add_argument("--anchor-id", help="Explicit previous passage ID for a context follow-up")
    parser.add_argument("--context-before", type=int, default=1)
    parser.add_argument("--context-after", type=int, default=1)
    parser.add_argument("--as-of")
    parser.add_argument("--include-stale", action="store_true")
    parser.add_argument("--include-classics-after-safety", action="store_true")
    parser.add_argument("--compact", action="store_true")
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    if args.character_budget < 500 or args.character_budget > 10000:
        raise SystemExit("--character-budget must be between 500 and 10000")
    if args.context_before < 0 or args.context_after < 0:
        raise SystemExit("--context-before and --context-after must be non-negative")
    payload = prepare(args)
    print(json.dumps(payload, ensure_ascii=False, indent=None if args.compact else 2))


if __name__ == "__main__":
    main()
