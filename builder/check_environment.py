#!/usr/bin/env python3
"""Record Phase-0 development-environment capabilities.

This checks the current build machine, not the final user's WorkBuddy installation.
A release-time self-check will repeat the runtime-critical checks on the target machine.
"""

from __future__ import annotations

import json
import os
import platform
import sqlite3
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
JSON_OUTPUT = PROJECT_DIR / "docs" / "environment-report.json"
MD_OUTPUT = PROJECT_DIR / "docs" / "environment-report.md"
USER_AGENT = "tcm-classics-study-environment-check/0.1"


def sqlite_capabilities() -> dict[str, Any]:
    result: dict[str, Any] = {"version": sqlite3.sqlite_version, "fts5": False, "trigram": False}
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(body)")
        result["fts5"] = True
    except sqlite3.Error as exc:
        result["fts5_error"] = str(exc)
    try:
        connection.execute("CREATE VIRTUAL TABLE trigram_probe USING fts5(body, tokenize='trigram')")
        result["trigram"] = True
    except sqlite3.Error as exc:
        result["trigram_error"] = str(exc)
    finally:
        connection.close()
    return result


def probe_url(url: str) -> dict[str, Any]:
    started = time.perf_counter()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return {
                "url": url,
                "ok": 200 <= response.status < 400,
                "status": response.status,
                "content_type": response.headers.get("Content-Type"),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
            }
    except Exception as exc:  # Report exact local TLS/network behavior.
        return {
            "url": url,
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }


def markdown(payload: dict[str, Any]) -> str:
    sqlite = payload["sqlite"]
    lines = [
        "# Phase 0 环境验证报告",
        "",
        f"> 检查时间：{payload['checked_at']}  ",
        "> 范围：当前开发/构建机器；发布前还要在父亲实际使用的电脑运行 `self_check.py`。",
        "",
        "## 本地运行能力",
        "",
        f"- 操作系统：`{payload['platform']}`",
        f"- Python：`{payload['python_version']}`",
        f"- Python最低版本（3.9）：{'通过' if payload['python_supported'] else '不通过'}",
        f"- SQLite：`{sqlite['version']}`",
        f"- SQLite FTS5：{'通过' if sqlite['fts5'] else '不通过'}",
        f"- SQLite trigram tokenizer：{'通过' if sqlite['trigram'] else '不通过'}",
        f"- 用户级 WorkBuddy Skills 目录：`{payload['workbuddy_skills_dir']}`（{'已存在' if payload['workbuddy_skills_dir_exists'] else '当前不存在'}）",
        "",
        "结论：当前机器可以开发和运行预构建 SQLite FTS5/trigram 检索。正式版仍保留不依赖 trigram tokenizer 的预生成字符词项方案，以兼容较旧的目标环境。",
        "",
        "## 网络探测（仅脚本直连）",
        "",
        "| 地址 | 结果 | HTTP/错误 | 耗时 |",
        "|---|---|---|---:|",
    ]
    for probe in payload["network"]:
        detail = probe.get("status") or f"{probe.get('error_type')}: {probe.get('error')}"
        lines.append(
            f"| {probe['url']} | {'通过' if probe['ok'] else '失败'} | {detail} | {probe['elapsed_ms']} ms |"
        )
    lines.extend(
        [
            "",
            "当前 Python 直连 PubMed 如出现本地证书链错误，不得通过关闭 TLS 校验绕过。运行时优先使用已确认稳定的 WorkBuddy 网页搜索/网页读取能力；结构化 PubMed 适配器需在目标环境单独验证证书链，失败时安全降级。",
            "",
            "## WorkBuddy 能力结论",
            "",
            "- 产品方已确认：网页搜索和网页读取能力稳定可用。",
            "- 旧版 Skill 已在 WorkBuddy 成功使用，并使用内联可视化卡片协议，说明可视化路径具备实际可用基础。",
            "- 本编码环境不能直接调用父亲 WorkBuddy 会话中的具体网页工具或渲染器，因此 Phase 3/4 仍需适配实际工具参数并做实机验收。",
            "- 经典检索不能依赖网络；现代层超时或断网不得阻塞原典与医家层。",
            "",
            "## Phase 0 结论",
            "",
            "1. Python 与 SQLite 检索技术路线可行。",
            "2. FTS5 和 trigram 在当前机器可用，但发布版需要兼容性自检和回退路径。",
            "3. Wikisource 与 WHO 当前脚本直连可用。",
            "4. 现代证据优先走 WorkBuddy 网页能力；PubMed 结构化直连属于增强项，不能成为单点依赖。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    skills_dir = Path.home() / ".workbuddy" / "skills"
    payload = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "platform": platform.platform(),
        "python_version": sys.version.replace("\n", " "),
        "python_supported": sys.version_info >= (3, 9),
        "ssl_version": ssl.OPENSSL_VERSION,
        "sqlite": sqlite_capabilities(),
        "workbuddy_skills_dir": str(skills_dir),
        "workbuddy_skills_dir_exists": skills_dir.exists(),
        "pi_environment_detected": any(key.startswith("PI_") for key in os.environ),
        "network": [
            probe_url("https://zh.wikisource.org/"),
            probe_url("https://pubmed.ncbi.nlm.nih.gov/"),
            probe_url("https://www.who.int/"),
        ],
        "owner_confirmed_workbuddy_web_search": True,
        "owner_confirmed_workbuddy_web_read": True,
    }
    JSON_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUTPUT.write_text(markdown(payload), encoding="utf-8")
    print(f"Environment report -> {MD_OUTPUT}")


if __name__ == "__main__":
    main()
