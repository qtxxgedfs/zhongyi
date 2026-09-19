#!/usr/bin/env python3
"""Benchmark the candidate SQLite search CLI with representative classic queries."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_DIR / "build" / "classics.sqlite"
DEFAULT_SCRIPT = PROJECT_DIR / "skill" / "tcm-classics-study" / "scripts" / "search.py"
DEFAULT_OUTPUT = PROJECT_DIR / "build" / "index-benchmark.json"
DEFAULT_REPORT = PROJECT_DIR / "docs" / "phase2-index-report.md"

SCENARIOS = [
    {"name": "suwen-core", "query": "《素问》治未病怎么说", "terms": "治未病", "target": "suwen", "work": "core-suwen"},
    {"name": "lingshu-core", "query": "《灵枢》怎样谈营卫", "terms": "营卫", "target": "lingshu", "work": "core-lingshu"},
    {"name": "shanghan-core", "query": "《伤寒论》桂枝汤原文", "terms": "桂枝汤", "target": "shanghanlun", "work": "core-shanghanlun"},
    {"name": "jingui-core", "query": "《金匮要略》百合病原文", "terms": "百合病", "target": "jingui", "work": "core-jingui"},
    {"name": "nanjing-core", "query": "《难经》为什么独取寸口", "terms": "独取寸口", "target": "nanjing", "work": "core-nanjing"},
    {"name": "wenbing-core", "query": "《温病条辨》上焦如羽", "terms": "上焦如羽", "target": "wenbingtiaobian", "work": "core-wenbingtiaobian"},
    {"name": "author-zhangjingyue", "query": "张景岳怎样解释治未病", "terms": "治未病", "work": "commentary-neijing-leijing"},
    {"name": "author-wangbing", "query": "王冰注阴阳应象", "terms": "阴阳应象", "work": "commentary-suwen-wangbing"},
    {"name": "author-youtaijing", "query": "尤在泾怎样解释痉湿暍", "terms": "痉湿暍"},
    {"name": "lineage-yetianshi", "query": "叶天士卫气营血", "terms": "卫气营血", "work": "lineage-wenbing-yetianshi"},
    {"name": "cross-canon", "query": "六部经典怎样谈阴阳", "terms": "阴阳"},
    {"name": "traditional-query", "query": "《傷寒論》太陽病", "terms": "太陽病", "target": "shanghanlun", "work": "core-shanghanlun"},
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def run_query(script: Path, database: Path, scenario: dict[str, str]) -> tuple[dict[str, Any], float]:
    command = [
        sys.executable,
        str(script),
        "--db",
        str(database),
        "search",
        "--query",
        scenario["query"],
        "--terms",
        scenario["terms"],
        "--limit-total",
        "8",
        "--limit-core",
        "4",
        "--limit-commentary",
        "4",
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    wall_ms = (time.perf_counter() - started) * 1000
    return json.loads(completed.stdout), wall_ms


def markdown(payload: dict[str, Any], database: Path) -> str:
    lines = [
        "# Phase 2 SQLite 索引与检索原型报告",
        "",
        "## 产物",
        "",
        f"- 候选数据库：`{database.relative_to(PROJECT_DIR).as_posix()}`",
        f"- 文件大小：{payload['database_size_mib']:.1f} MiB",
        f"- SHA-256：`{payload['database_sha256']}`",
        f"- 可检索段落：{payload['passage_count']:,}",
        f"- 明确排除的隔离段落：{payload['quarantined_passages_excluded']:,}",
        "- 构建清单：`build/classics-index-manifest.json`（含数据库及全部索引输入 SHA-256）",
        "- 索引：SQLite FTS5；预分词去重重叠二元字符组；运行时不加载全量 JSON。",
        "- 数据库状态：`candidate`；Phase 1 发布闸门未通过前不得改称最终发布数据库。",
        "",
        "## 性能",
        "",
        f"在本机构建后热文件缓存条件下，对{payload['scenario_count']}类查询各运行{payload['repetitions']}次：",
        "",
        f"- CLI 内部检索中位数：{payload['latency_ms']['internal_p50']:.3f} ms",
        f"- CLI 内部检索 P95：{payload['latency_ms']['internal_p95']:.3f} ms",
        f"- 含 Python 进程启动的端到端中位数：{payload['latency_ms']['wall_p50']:.3f} ms",
        f"- 含 Python 进程启动的端到端 P95：{payload['latency_ms']['wall_p95']:.3f} ms",
        f"- 路由/召回检查：{payload['checks_passed']}/{payload['checks_total']} 通过",
        "",
        "## 查询检查",
        "",
        "| 场景 | 结果数 | 首条 | 指定作品是否召回 | 路由是否通过 |",
        "|---|---:|---|---|---|",
    ]
    for item in payload["scenarios"]:
        lines.append(
            f"| {item['name']} | {item['result_count']} | `{item['first_result']}` | "
            f"{'是' if item['expected_work_found'] else '不适用/否'} | {'是' if item['route_passed'] else '不适用/否'} |"
        )
    lines.extend(
        [
            "",
            "## 质量边界",
            "",
            "- 构建器只在 `citable_corpus_status=pass` 时建索引。",
            "- 290条隔离段没有进入 `passages` 或 FTS，无法经普通检索、段落读取或上下文接口取得。",
            "- CLI 只输出 `text_simplified` 作为显示/直接引文字段，不输出 `text_search`。",
            "- 当前性能数据是开发机基准；目标 WorkBuddy 电脑仍须实机验收。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")

    all_internal: list[float] = []
    all_wall: list[float] = []
    scenario_results: list[dict[str, Any]] = []
    checks_passed = 0
    checks_total = 0
    for scenario in SCENARIOS:
        runs = [run_query(args.script, args.db, scenario) for _ in range(args.repetitions)]
        payload = runs[-1][0]
        all_internal.extend(run[0]["elapsed_ms"] for run in runs)
        all_wall.extend(run[1] for run in runs)
        work_ids = {item["work_id"] for item in payload["results"]}
        expected_work_found = scenario.get("work") in work_ids if scenario.get("work") else True
        route_passed = scenario.get("target") in payload["route"]["target_works"] if scenario.get("target") else True
        checks_total += 2
        checks_passed += int(expected_work_found) + int(route_passed)
        scenario_results.append(
            {
                "name": scenario["name"],
                "result_count": len(payload["results"]),
                "first_result": payload["results"][0]["id"] if payload["results"] else "",
                "expected_work_found": expected_work_found,
                "route_passed": route_passed,
                "internal_median_ms": round(statistics.median(run[0]["elapsed_ms"] for run in runs), 3),
                "wall_median_ms": round(statistics.median(run[1] for run in runs), 3),
            }
        )

    with sqlite3_connect(args.db) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM schema_info"))
    result = {
        "database": str(args.db),
        "database_size_mib": round(args.db.stat().st_size / 1024 / 1024, 3),
        "database_sha256": sha256_file(args.db),
        "passage_count": int(metadata["passage_count"]),
        "quarantined_passages_excluded": int(metadata["quarantined_passages_excluded"]),
        "scenario_count": len(SCENARIOS),
        "repetitions": args.repetitions,
        "latency_ms": {
            "internal_p50": round(statistics.median(all_internal), 3),
            "internal_p95": round(percentile(all_internal, 0.95), 3),
            "wall_p50": round(statistics.median(all_wall), 3),
            "wall_p95": round(percentile(all_wall, 0.95), 3),
        },
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "scenarios": scenario_results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(markdown(result, args.db), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if checks_passed != checks_total:
        raise SystemExit(f"Benchmark retrieval checks failed: {checks_passed}/{checks_total}")


def sqlite3_connect(path: Path):
    import sqlite3

    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


if __name__ == "__main__":
    main()
