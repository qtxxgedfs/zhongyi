#!/usr/bin/env python3
"""Run the 150-question functional acceptance set against candidate runtime databases."""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
SKILL_DIR = PROJECT_DIR / "skill" / "tcm-classics-study"
SCRIPT_DIR = SKILL_DIR / "scripts"
DEFAULT_QUESTIONS = PROJECT_DIR / "tests" / "acceptance" / "questions.jsonl"
DEFAULT_OUTPUT = PROJECT_DIR / "build" / "acceptance-results.json"
DEFAULT_REPORT = PROJECT_DIR / "docs" / "phase5-acceptance-report.md"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[round((len(ordered) - 1) * fraction)]


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Phase 5 功能验收报告",
        "",
        "## 摘要",
        "",
        f"- 固定验收问题：{result['question_count']}题",
        f"- 总检查：{result['checks_passed']}/{result['checks_total']}通过（{result['overall_pass_rate']:.1%}）",
        f"- M0—M3分类：{result['classification']['passed']}/{result['classification']['total']}（{result['classification']['rate']:.1%}）",
        f"- 六部原典精确检索 Recall@5：{result['classic_retrieval']['passed']}/{result['classic_retrieval']['total']}（{result['classic_retrieval']['rate']:.1%}）",
        f"- 医家检索 Recall@5：{result['physician_retrieval']['passed']}/{result['physician_retrieval']['total']}（{result['physician_retrieval']['rate']:.1%}）",
        f"- M3安全分流：{result['m3_safety']['passed']}/{result['m3_safety']['total']}（{result['m3_safety']['rate']:.1%}）",
        f"- 单次内部评估耗时P50/P95：{result['latency_ms']['p50']:.3f}/{result['latency_ms']['p95']:.3f} ms",
        f"- 验收结论：**{result['status']}**",
        "",
        "## 分类分布",
        "",
        "| 类别 | 题数 |",
        "|---|---:|",
    ]
    for category, count in sorted(result["category_counts"].items()):
        lines.append(f"| {category} | {count} |")
    lines.extend(["", "## 未通过项目", ""])
    if result["failures"]:
        for failure in result["failures"]:
            lines.append(f"- `{failure['id']}` {failure['category']}：{failure['reason']}；问题：{failure['query']}")
    else:
        lines.append("无。")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 本报告验证路由、检索、M0—M3分级、急症优先和结构化输出，不替代临床评估。",
            "- 现代证据种子缓存只覆盖6条核验记录；未覆盖主题依赖WorkBuddy网页能力或明确降级。",
            "- 白话改写召回和实际老年用户可用性还需目标电脑上的自然提问补充测试。",
            "- 当前为可运行候选版；文本底本质量精修将另行进行。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    classic_search = load_module("acceptance_classic_search", SCRIPT_DIR / "search.py")
    modern_evidence = load_module("acceptance_modern_evidence", SCRIPT_DIR / "modern_evidence.py")
    questions = [json.loads(line) for line in args.questions.read_text(encoding="utf-8").splitlines() if line]
    if len(questions) < 150:
        raise SystemExit(f"Acceptance set must contain at least 150 questions, got {len(questions)}")

    classic_connection = classic_search.connect(SKILL_DIR / "data" / "classics.sqlite")
    evidence_connection = modern_evidence.connect(SKILL_DIR / "data" / "evidence-cache.sqlite")
    failures: list[dict[str, str]] = []
    category_counts: dict[str, int] = {}
    latency: list[float] = []
    metrics = {
        "classification": [0, 0],
        "classic_retrieval": [0, 0],
        "physician_retrieval": [0, 0],
        "m3_safety": [0, 0],
    }
    checks_passed = 0
    checks_total = 0
    try:
        for case in questions:
            category_counts[case["category"]] = category_counts.get(case["category"], 0) + 1
            started = time.perf_counter()
            classification = modern_evidence.classify(evidence_connection, case["query"])
            case_failures: list[str] = []
            checks_total += 1
            metrics["classification"][1] += 1
            if classification["level"] == case["expected_level"]:
                checks_passed += 1
                metrics["classification"][0] += 1
            else:
                case_failures.append(
                    f"分类期望{case['expected_level']}，实际{classification['level']}"
                )

            if case["category"] in {"classic-exact", "physician-retrieval"}:
                search_args = SimpleNamespace(
                    query=case["query"],
                    terms=case.get("terms"),
                    canon="auto",
                    work="auto",
                    layers="all",
                    author=None,
                    limit_core=3,
                    limit_commentary=3,
                    limit_total=5,
                    candidate_limit=240,
                )
                search_result = classic_search.search(classic_connection, search_args)
                result_works = {item["work_id"] for item in search_result["results"]}
                result_authors = " ".join(item["author"] for item in search_result["results"])
                metric_name = "classic_retrieval" if case["category"] == "classic-exact" else "physician_retrieval"
                metrics[metric_name][1] += 1
                checks_total += 1
                found = bool(search_result["results"])
                if case.get("expected_work_id"):
                    found = case["expected_work_id"] in result_works
                elif case.get("expected_author"):
                    found = case["expected_author"] in result_authors
                if found:
                    metrics[metric_name][0] += 1
                    checks_passed += 1
                else:
                    case_failures.append(
                        f"Recall@5未命中预期作品/医家；返回{sorted(result_works)}"
                    )

            if case.get("modern_required") is not None:
                checks_total += 1
                if classification["modern_layer_required"] == case["modern_required"]:
                    checks_passed += 1
                else:
                    case_failures.append("现代层触发状态不符合预期")

            if case.get("must_defer_classics"):
                metrics["m3_safety"][1] += 1
                checks_total += 1
                safe = (
                    classification["level"] == "M3"
                    and classification["safety_must_precede_retrieval"]
                    and bool(classification["safety_message"])
                )
                if safe:
                    metrics["m3_safety"][0] += 1
                    checks_passed += 1
                else:
                    case_failures.append("M3未提供先于检索的急症分流")
            latency.append((time.perf_counter() - started) * 1000)
            if case_failures:
                failures.append(
                    {
                        "id": case["id"],
                        "category": case["category"],
                        "query": case["query"],
                        "reason": "；".join(case_failures),
                    }
                )
    finally:
        classic_connection.close()
        evidence_connection.close()

    def metric(name: str) -> dict[str, Any]:
        passed, total = metrics[name]
        return {"passed": passed, "total": total, "rate": passed / total if total else 1.0}

    result = {
        "schema_version": 1,
        "question_count": len(questions),
        "category_counts": category_counts,
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "overall_pass_rate": checks_passed / checks_total,
        "classification": metric("classification"),
        "classic_retrieval": metric("classic_retrieval"),
        "physician_retrieval": metric("physician_retrieval"),
        "m3_safety": metric("m3_safety"),
        "latency_ms": {
            "p50": round(statistics.median(latency), 3),
            "p95": round(percentile(latency, 0.95), 3),
        },
        "failures": failures,
    }
    result["status"] = (
        "pass"
        if result["classification"]["rate"] >= 0.97
        and result["classic_retrieval"]["rate"] >= 0.95
        and result["physician_retrieval"]["rate"] >= 0.90
        and result["m3_safety"]["rate"] == 1.0
        else "fail"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(markdown(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "pass":
        raise SystemExit("Acceptance thresholds not met")


if __name__ == "__main__":
    main()
