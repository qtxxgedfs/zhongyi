#!/usr/bin/env python3
"""Run reader-like natural questions and explicit multi-turn context checks."""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
SKILL_DIR = PROJECT_DIR / "skill" / "tcm-classics-study"
SEARCH_SCRIPT = SKILL_DIR / "scripts" / "search.py"
DEFAULT_QUESTIONS = PROJECT_DIR / "tests" / "natural" / "questions.jsonl"
DEFAULT_CONVERSATIONS = PROJECT_DIR / "tests" / "natural" / "conversations.jsonl"
DEFAULT_OUTPUT = PROJECT_DIR / "build" / "natural-acceptance-results.json"
DEFAULT_REPORT = PROJECT_DIR / "docs" / "phase6-usability-report.md"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def search_args(search_module, query: str) -> SimpleNamespace:
    return SimpleNamespace(
        query=query,
        terms=None,
        rules=search_module.DEFAULT_RULES,
        canon="auto",
        work="auto",
        layers="all",
        author=None,
        limit_core=2,
        limit_commentary=2,
        limit_total=4,
        candidate_limit=240,
        route_fallback=True,
    )


def acceptable_first(case: dict[str, Any], results: list[dict[str, Any]]) -> bool:
    if not case.get("acceptable_top_ids") and not case.get("acceptable_work_ids"):
        return True
    if not results:
        return False
    first = results[0]
    return (
        first["id"] in case.get("acceptable_top_ids", [])
        or first["work_id"] in case.get("acceptable_work_ids", [])
    )


def ratio(passed: int, total: int) -> dict[str, Any]:
    return {"passed": passed, "total": total, "rate": passed / total if total else 1.0}


def markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase 6 自然问法与结果可用性报告",
        "",
        "## 摘要",
        "",
        f"- 单轮自然问法：{payload['single_turn_count']}题",
        f"- 连续追问：{payload['conversation_count']}组、{payload['conversation_turn_count']}轮",
        f"- 自然问法主结果/备选首条可接受率：{payload['top1_acceptance']['passed']}/{payload['top1_acceptance']['total']}（{payload['top1_acceptance']['rate']:.1%}；10题宽泛问题不预设唯一首条）",
        f"- 范围行为（含不应回退的反例）：{payload['route_recovery']['passed']}/{payload['route_recovery']['total']}（{payload['route_recovery']['rate']:.1%}）",
        f"- 澄清行为符合预期：{payload['clarification']['passed']}/{payload['clarification']['total']}（{payload['clarification']['rate']:.1%}）",
        f"- 展示结果无独立残片：{payload['result_quality']['passed']}/{payload['result_quality']['total']}（{payload['result_quality']['rate']:.1%}）",
        f"- 连续上下文锚点：{payload['conversation_context']['passed']}/{payload['conversation_context']['total']}（{payload['conversation_context']['rate']:.1%}）",
        f"- 检索耗时 P50/P95：{payload['latency_ms']['p50']:.3f}/{payload['latency_ms']['p95']:.3f} ms",
        f"- 结论：**{payload['status']}**",
        "",
        "## 分类分布",
        "",
        "| 类别 | 题数 |",
        "|---|---:|",
    ]
    for category, count in sorted(payload["category_counts"].items()):
        lines.append(f"| {category} | {count} |")
    lines.extend(["", "## 未通过项目", ""])
    if payload["failures"]:
        for failure in payload["failures"]:
            lines.append(
                f"- `{failure['id']}` {failure['check']}：{failure['reason']}；问题：{failure['query']}"
            )
    else:
        lines.append("无。")
    lines.extend(
        [
            "",
            "## 测试集边界",
            "",
            "- 本集使用接近普通读者的口语、记忆残片、来源记混、宽泛问题和连续追问，不向检索器提供人工 `terms`。",
            "- 当前问题由项目内人工整理，不包含用户日志或个人健康信息；后续获得真实、去身份化读者问法后应逐步替换开发样本。",
            "- 1.1.1修订NQ033/035/037/038的预期：指定书籍/医家的解释题保留原范围，范围外结果单列备选；原问题和备选目标ID未变。",
            "- 所有60题均断言范围冲突（未标注时默认false），并检查主结果与备选的引文质量。自然医家/比较/预算回归另见test_refinement_runtime.py。",
            "- 本报告检查检索与材料组织，不以自动指标替代对白话解释准确性和医家分歧的人工评审。",
            "- 原有150题继续作为精确召回和安全回归集，本集不替代它。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--conversations", type=Path, default=DEFAULT_CONVERSATIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    search_module = load_module("natural_acceptance_search", SEARCH_SCRIPT)
    questions = load_jsonl(args.questions)
    conversations = load_jsonl(args.conversations)
    if len(questions) != 60:
        raise SystemExit(f"Natural single-turn set must contain 60 questions, got {len(questions)}")
    if len(conversations) != 10:
        raise SystemExit(f"Natural conversation set must contain 10 conversations, got {len(conversations)}")

    connection = search_module.connect(SKILL_DIR / "data" / "classics.sqlite")
    failures: list[dict[str, str]] = []
    categories: Counter[str] = Counter()
    latency: list[float] = []
    top1_passed = top1_total = 0
    route_passed = route_total = 0
    clarification_passed = clarification_total = 0
    quality_passed = quality_total = 0
    conversation_passed = conversation_total = 0
    conversation_turn_count = 0
    try:
        for case in questions:
            categories[case["category"]] += 1
            started = time.perf_counter()
            payload = search_module.search(connection, search_args(search_module, case["query"]))
            latency.append((time.perf_counter() - started) * 1000)
            results = payload["results"]
            evaluated_results = payload[case.get("result_channel", "results")]
            if case.get("expected_primary_empty") and results:
                failures.append({"id": case["id"], "check": "scope-substitution", "query": case["query"],
                                 "reason": "范围外备选不得代替指定范围结果"})

            if case.get("acceptable_top_ids") or case.get("acceptable_work_ids"):
                top1_total += 1
                if acceptable_first(case, evaluated_results):
                    top1_passed += 1
                else:
                    failures.append(
                        {
                            "id": case["id"],
                            "check": "top1",
                            "query": case["query"],
                            "reason": "首条不在可接受集合；实际=" + (evaluated_results[0]["id"] if evaluated_results else "无结果"),
                        }
                    )

            expected_conflict = case.get("expected_route_conflict", False)
            if expected_conflict is not None:
                route_total += 1
                actual = payload["route_resolution"]["conflict_detected"]
                if actual is expected_conflict:
                    route_passed += 1
                else:
                    failures.append(
                        {
                            "id": case["id"],
                            "check": "route-recovery",
                            "query": case["query"],
                            "reason": f"期望 conflict={expected_conflict}，实际={actual}",
                        }
                    )

            expected_clarification = case.get("expected_clarification", False)
            clarification_total += 1
            actual_clarification = payload["needs_clarification"]["required"]
            if actual_clarification is expected_clarification:
                clarification_passed += 1
            else:
                failures.append(
                    {
                        "id": case["id"],
                        "check": "clarification",
                        "query": case["query"],
                        "reason": f"期望 required={expected_clarification}，实际={actual_clarification}",
                    }
                )

            quality_total += 1
            quality_ok = all(
                item.get("match", {}).get("tier") in {"A", "B", "C"}
                and item.get("match", {}).get("standalone_quality") == "usable"
                and bool(item.get("core_quote"))
                and item["core_quote"] in item.get("text_simplified", "")
                and len(item["core_quote"]) <= 320
                for item in [*results, *payload.get("alternative_results", [])]
            )
            if quality_ok:
                quality_passed += 1
            else:
                failures.append(
                    {
                        "id": case["id"],
                        "check": "result-quality",
                        "query": case["query"],
                        "reason": "展示结果含弱相关、独立残片或超过320字的默认核心引文",
                    }
                )

        for conversation in conversations:
            initial = conversation["initial"]
            started = time.perf_counter()
            payload = search_module.search(connection, search_args(search_module, initial["query"]))
            latency.append((time.perf_counter() - started) * 1000)
            conversation_turn_count += 1
            conversation_total += 1
            if not acceptable_first(initial, payload["results"]):
                failures.append(
                    {
                        "id": conversation["id"],
                        "check": "conversation-initial",
                        "query": initial["query"],
                        "reason": "首轮未得到可接受锚点",
                    }
                )
                continue
            anchor_id = payload["results"][0]["id"]
            all_follow_ups_ok = True
            for follow_up in conversation["follow_ups"]:
                conversation_turn_count += 1
                context = search_module.context(
                    connection,
                    anchor_id,
                    follow_up["before"],
                    follow_up["after"],
                )
                ids = [item["id"] for item in context["results"]]
                anchor_rows = [item for item in context["results"] if item.get("context_role") == "anchor"]
                expected_max = follow_up["before"] + follow_up["after"] + 1
                if (
                    context.get("error")
                    or ids.count(anchor_id) != 1
                    or len(anchor_rows) != 1
                    or len(ids) > expected_max
                    or any(item["work_id"] != context["work_id"] for item in context["results"])
                ):
                    all_follow_ups_ok = False
                    failures.append(
                        {
                            "id": conversation["id"],
                            "check": "conversation-context",
                            "query": follow_up["query"],
                            "reason": f"锚点或连续上下文不正确；anchor={anchor_id}，返回={ids}",
                        }
                    )
            if all_follow_ups_ok:
                conversation_passed += 1
    finally:
        connection.close()

    result = {
        "schema_version": 1,
        "single_turn_count": len(questions),
        "conversation_count": len(conversations),
        "conversation_turn_count": conversation_turn_count,
        "category_counts": dict(categories),
        "top1_acceptance": ratio(top1_passed, top1_total),
        "route_recovery": ratio(route_passed, route_total),
        "clarification": ratio(clarification_passed, clarification_total),
        "result_quality": ratio(quality_passed, quality_total),
        "conversation_context": ratio(conversation_passed, conversation_total),
        "latency_ms": {
            "p50": round(statistics.median(latency), 3),
            "p95": round(percentile(latency, 0.95), 3),
        },
        "failures": failures,
    }
    result["status"] = (
        "pass"
        if not failures and result["top1_acceptance"]["rate"] >= 0.90
        and result["route_recovery"]["rate"] == 1.0
        and result["clarification"]["rate"] >= 0.95
        and result["result_quality"]["rate"] == 1.0
        and result["conversation_context"]["rate"] == 1.0
        else "fail"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(markdown(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "pass":
        raise SystemExit("Natural-language acceptance thresholds not met")


if __name__ == "__main__":
    main()
