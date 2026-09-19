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
    selected: list[dict[str, Any]] = []
    used = 0
    for result in results:
        length = len(result["text_simplified"])
        if selected and used + length > budget:
            continue
        selected.append(result)
        used += length
    return selected, used


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
    classic_payload: dict[str, Any] = {"results": [], "route": {}, "terms": [], "elapsed_ms": 0.0}
    if not safety_first or args.include_classics_after_safety:
        classic_connection = classic_search.connect(args.classics_db)
        try:
            search_args = SimpleNamespace(
                query=args.query,
                terms=args.terms,
                canon=args.canon,
                work=args.work,
                layers=args.layers,
                author=args.author,
                limit_core=args.limit_core,
                limit_commentary=args.limit_commentary,
                limit_total=args.limit_total,
                candidate_limit=args.candidate_limit,
            )
            classic_payload = classic_search.search(classic_connection, search_args)
        finally:
            classic_connection.close()

    core = [item for item in classic_payload["results"] if item["layer"] == "core"]
    extension = [item for item in classic_payload["results"] if item["layer"] != "core"]
    core_budget = max(1, round(args.character_budget * 0.45))
    extension_budget = max(1, args.character_budget - core_budget)
    core, core_chars = fit_budget(core, core_budget)
    extension, extension_chars = fit_budget(extension, extension_budget)
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

    return {
        "schema_version": 1,
        "runtime_status": "candidate-runnable",
        "query": args.query,
        "safety_first": {
            "required": safety_first,
            "message": classification["safety_message"],
            "classic_retrieval_deferred": safety_first and not args.include_classics_after_safety,
        },
        "classification": classification,
        "classic_search": {
            "terms": classic_payload.get("terms", []),
            "route": classic_payload.get("route", {}),
            "database_build_status": classic_payload.get("database_build_status", "candidate"),
            "quarantined_passages_excluded": classic_payload.get("quarantined_passages_excluded", 290),
            "elapsed_ms": classic_payload.get("elapsed_ms", 0.0),
        },
        "A_core": core,
        "B_physicians": extension,
        "C_modern": {
            "required": classification["modern_layer_required"],
            "cache": cache,
            "online_search_plan": online_plan,
        },
        "context_budget": {
            "maximum_characters": args.character_budget,
            "selected_characters": core_chars + extension_chars,
            "core_characters": core_chars,
            "physician_characters": extension_chars,
        },
        "answer_contract": {
            "order": ["一句话结论", "🟩 A｜原典", "🟧 B｜历代医家", "🟦 C｜现代医学"],
            "omit_C_when": "classification.level=M0",
            "classic_quote_field": "text_simplified",
            "classic_quote_ids": [item["id"] for item in [*core, *extension]],
            "modern_cache_record_ids": [item["id"] for item in cache["records"] if item["citation_recommended"]],
            "rules": [
                "原文、医家观点、AI解释和现代来源结论分开标记。",
                "直接引文只能逐字复制本研究包中的text_simplified。",
                "不把中医证候或理论概念直接等同于现代疾病和解剖结构。",
                "不诊断、不开方、不换算个人剂量、不建议停换药。",
                "没有命中时写当前所收工作底本未检得，不作历史绝对否定。",
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
    parser.add_argument("--canon", choices=["auto", "huangdi", "zhongjing", "nanjing", "wenbing"], default="auto")
    parser.add_argument("--work", default="auto")
    parser.add_argument("--layers", default="all")
    parser.add_argument("--author")
    parser.add_argument("--limit-core", type=int, default=3)
    parser.add_argument("--limit-commentary", type=int, default=3)
    parser.add_argument("--limit-total", type=int, default=6)
    parser.add_argument("--candidate-limit", type=int, default=240)
    parser.add_argument("--character-budget", type=int, default=2500)
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
    payload = prepare(args)
    print(json.dumps(payload, ensure_ascii=False, indent=None if args.compact else 2))


if __name__ == "__main__":
    main()
