#!/usr/bin/env python3
"""Audit and benchmark the supplied legacy zhongjing-study Skill archive."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = PROJECT_DIR.parent / "zhongjing-study-skill.zip"
JSON_OUTPUT = PROJECT_DIR / "docs" / "legacy-skill-audit.json"
MD_OUTPUT = PROJECT_DIR / "docs" / "legacy-skill-audit.md"
QUERIES = ["桂枝汤", "太阳病", "治未病", "发热恶寒头痛"]


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def benchmark(skill_dir: Path, query: str, layer: str, repeats: int) -> dict:
    timings: list[float] = []
    output_bytes = 0
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    command = [
        sys.executable,
        str(skill_dir / "scripts" / "search_corpus.py"),
        "--query",
        query,
        "--layer",
        layer,
        "--limit",
        "8",
    ]
    for _ in range(repeats):
        started = time.perf_counter()
        result = subprocess.run(command, cwd=skill_dir, env=env, capture_output=True, check=False)
        timings.append((time.perf_counter() - started) * 1000)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
        output_bytes = len(result.stdout)
    return {
        "query": query,
        "layer": layer,
        "repeats": repeats,
        "median_ms": round(statistics.median(timings), 1),
        "min_ms": round(min(timings), 1),
        "max_ms": round(max(timings), 1),
        "output_bytes": output_bytes,
    }


def markdown(payload: dict) -> str:
    lines = [
        "# 旧版 zhongjing-study Skill 审计",
        "",
        f"> 审计时间：{payload['audited_at']}  ",
        f"> 输入：`{payload['archive']}`",
        "",
        "## 规模",
        "",
        f"- ZIP大小：{payload['archive_bytes']:,} bytes",
        f"- 解压文件数：{payload['file_count']}",
        f"- 解压总大小：{payload['uncompressed_bytes']:,} bytes",
        f"- 登记来源：{payload['source_count']}（核心 {payload['core_source_count']}，后世 {payload['later_source_count']}）",
        f"- 正文语料：核心 {payload['core_corpus_bytes']:,} bytes，后世 {payload['later_corpus_bytes']:,} bytes",
        f"- JSON索引：{payload['index_bytes']:,} bytes，{payload['index_record_count']:,} 条",
        f"- 来源目录中的文件是否全部存在：{'是' if payload['all_registered_paths_exist'] else '否'}",
        "",
        "## 本机脚本基准",
        "",
        "每组运行多次并取中位数；只统计检索脚本，不包含 WorkBuddy 模型推理和网页访问。",
        "",
        "| 查询 | 层 | 中位耗时 | 范围 | 输出大小 |",
        "|---|---|---:|---:|---:|",
    ]
    for row in payload["benchmarks"]:
        lines.append(
            f"| {row['query']} | {row['layer']} | {row['median_ms']} ms | {row['min_ms']}—{row['max_ms']} ms | {row['output_bytes']:,} bytes |"
        )
    lines.extend(
        [
            "",
            "## 已确认的性能原因",
            "",
            "1. `search_corpus.py` 每次运行都完整读取并 `json.loads` 整个 `corpus_index.json`。即使选择 `--layer core`，全部JSON仍先被解析。",
            "2. 索引是正文副本，不是倒排索引；查询仍逐条遍历候选记录。",
            "3. `score()` 对每条记录重新规范化正文，并在每条记录评分时重复计算同一个查询的 `chinese_ngrams(query)`。",
            "4. 全部命中项进入列表后整体排序，没有只维护前N名。",
            "5. 默认可输出8个完整段落；后世段落很长时，返回体积显著增加，随后还会增加模型上下文和推理时间。",
            "6. 回答协议和现代联网会带来额外读取/网络调用，但不是本地检索全扫描的根因。",
            "",
            "## 结论",
            "",
            "旧版不是让模型在每次问答前逐本阅读全文；模型通常只看到脚本返回的命中段落。主要瓶颈是脚本在每次进程中重新加载大JSON、线性评分全部记录，并可能返回过长上下文。新版本应使用预构建 SQLite 索引、按经典路由和分层限量输出。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    archive = args.zip.resolve()

    with tempfile.TemporaryDirectory(prefix="tcm-legacy-audit-") as temp_name:
        temp = Path(temp_name)
        with ZipFile(archive) as zip_file:
            infos = zip_file.infolist()
            zip_file.extractall(temp)
        skill_dir = next(path.parent for path in temp.rglob("SKILL.md") if path.parent.name == "zhongjing-study")
        catalog_path = skill_dir / "data" / "source_catalog.json"
        index_path = skill_dir / "data" / "corpus_index.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        index = json.loads(index_path.read_text(encoding="utf-8"))
        sources = catalog["sources"]
        benchmarks = [
            benchmark(skill_dir, query, layer, args.repeats)
            for query in QUERIES
            for layer in ("core", "all")
        ]
        payload = {
            "schema_version": 1,
            "audited_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "archive": str(archive),
            "archive_bytes": archive.stat().st_size,
            "file_count": len([info for info in infos if not info.is_dir()]),
            "uncompressed_bytes": sum(info.file_size for info in infos),
            "source_count": len(sources),
            "core_source_count": sum(source["layer"] == "core" for source in sources),
            "later_source_count": sum(source["layer"] == "later" for source in sources),
            "core_corpus_bytes": directory_size(skill_dir / "corpus" / "core"),
            "later_corpus_bytes": directory_size(skill_dir / "corpus" / "later"),
            "index_bytes": index_path.stat().st_size,
            "index_record_count": index["record_count"],
            "all_registered_paths_exist": all((skill_dir / source["path"]).exists() for source in sources),
            "benchmarks": benchmarks,
        }

    JSON_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUTPUT.write_text(markdown(payload), encoding="utf-8")
    print(f"Legacy audit -> {MD_OUTPUT}")


if __name__ == "__main__":
    main()
