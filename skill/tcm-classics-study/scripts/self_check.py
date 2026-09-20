#!/usr/bin/env python3
"""Verify that the staged candidate Skill is intact and runnable."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SKILL_DIR / "data"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def check_database(path: Path) -> tuple[sqlite3.Connection, str]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    return connection, connection.execute("PRAGMA integrity_check").fetchone()[0]


def run_json_script(script: str, *arguments: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SKILL_DIR / "scripts" / script), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def check_study_and_render(errors: list[str]) -> tuple[bool, bool, bool]:
    study_smoke = False
    markdown_render_smoke = False
    m3_classic_retrieval_deferred = False
    try:
        packet = run_json_script(
            "study.py",
            "--query",
            "《素问》治未病在说什么，和现代预防有什么区别",
            "--terms",
            "治未病",
        )
        study_smoke = (
            packet.get("schema_version") == 2
            and packet.get("standard_study_only") is True
            and packet.get("interaction_principle") == "宁缺毋滥"
            and packet.get("classification", {}).get("level") == "M1"
            and bool(packet.get("A_core"))
            and bool(packet.get("B_physicians"))
            and packet.get("context_budget", {}).get("selected_characters", 2501) <= 2500
            and packet.get("answer_contract", {}).get("mode") == "standard"
        )
        if not study_smoke:
            errors.append("study-packet-smoke-failed")

        with tempfile.TemporaryDirectory() as directory:
            packet_path = Path(directory) / "packet.json"
            output_path = Path(directory) / "answer.md"
            packet_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(SKILL_DIR / "scripts" / "render.py"),
                    "--input",
                    str(packet_path),
                    "--format",
                    "markdown",
                    "--output",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            rendered = output_path.read_text(encoding="utf-8")
        markdown_render_smoke = (
            "## 🟩 A｜原典" in rendered
            and "## 🟧 B｜历代医家" in rendered
            and packet["A_core"][0]["text_simplified"] in rendered
        )
        if not markdown_render_smoke:
            errors.append("markdown-render-smoke-failed")

        emergency = run_json_script(
            "study.py",
            "--query",
            "我父亲突然说话不清楚，一侧手脚没力怎么办",
        )
        m3_classic_retrieval_deferred = (
            emergency.get("classification", {}).get("level") == "M3"
            and emergency.get("safety_first", {}).get("classic_retrieval_deferred") is True
            and emergency.get("A_core") == []
            and emergency.get("B_physicians") == []
        )
        if not m3_classic_retrieval_deferred:
            errors.append("m3-classic-retrieval-not-deferred")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        errors.append(f"study-render-smoke-error:{type(error).__name__}")
    return study_smoke, markdown_render_smoke, m3_classic_retrieval_deferred


def check_usability(errors: list[str]) -> tuple[bool, bool, bool, bool]:
    natural_search_smoke = False
    fragment_suppression_smoke = False
    route_recovery_smoke = False
    broad_scope_smoke = False
    try:
        remembered = run_json_script(
            "search.py",
            "search",
            "--query",
            "我记得病了才治就像口渴才挖井",
        )
        natural_search_smoke = bool(remembered.get("results")) and remembered["results"][0]["id"] == "SW-000004"
        if not natural_search_smoke:
            errors.append("natural-search-smoke-failed")

        formula = run_json_script(
            "search.py",
            "search",
            "--query",
            "桂枝汤那段简单说说",
        )
        fragment_suppression_smoke = (
            bool(formula.get("results"))
            and formula["results"][0]["id"] == "SHL-000054"
            and all(item.get("match", {}).get("standalone_quality") == "usable" for item in formula["results"])
            and all(len(item.get("core_quote", "")) <= 320 for item in formula["results"])
        )
        if not fragment_suppression_smoke:
            errors.append("fragment-suppression-smoke-failed")

        mixed = run_json_script(
            "search.py",
            "search",
            "--query",
            "《难经》里是不是有渴了才挖井的比喻",
        )
        route_recovery_smoke = (
            bool(mixed.get("results"))
            and mixed["results"][0]["id"] == "SW-000004"
            and mixed.get("route_resolution", {}).get("conflict_detected") is True
        )
        if not route_recovery_smoke:
            errors.append("route-recovery-smoke-failed")

        broad = run_json_script(
            "search.py",
            "search",
            "--query",
            "阴阳到底怎么理解",
        )
        broad_scope_smoke = (
            broad.get("needs_clarification", {}).get("required") is True
            and len(broad.get("results", [])) == 1
        )
        if not broad_scope_smoke:
            errors.append("broad-scope-smoke-failed")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        errors.append(f"usability-smoke-error:{type(error).__name__}")
    return natural_search_smoke, fragment_suppression_smoke, route_recovery_smoke, broad_scope_smoke


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    errors: list[str] = []
    runtime = load_json(DATA_DIR / "runtime-candidate-manifest.json")
    if not runtime.get("project_version"):
        errors.append("runtime-project-version-missing")
    classic_manifest = load_json(DATA_DIR / "classics-index-manifest.json")
    evidence_manifest = load_json(DATA_DIR / "evidence-cache.manifest.json")
    for item in runtime["files"]:
        path = SKILL_DIR / item["path"]
        if not path.exists():
            errors.append(f"missing:{item['path']}")
        elif sha256_file(path) != item["sha256"]:
            errors.append(f"hash-mismatch:{item['path']}")

    classic_path = DATA_DIR / "classics.sqlite"
    evidence_path = DATA_DIR / "evidence-cache.sqlite"
    if sha256_file(classic_path) != classic_manifest["database_sha256"]:
        errors.append("classic-database-manifest-hash-mismatch")
    if sha256_file(evidence_path) != evidence_manifest["database_sha256"]:
        errors.append("evidence-database-manifest-hash-mismatch")

    classic, classic_integrity = check_database(classic_path)
    evidence, evidence_integrity = check_database(evidence_path)
    try:
        classic_count = classic.execute("SELECT count(*) FROM passages").fetchone()[0]
        quarantine_excluded = int(
            classic.execute("SELECT value FROM schema_info WHERE key='quarantined_passages_excluded'").fetchone()[0]
        )
        known = classic.execute(
            """
            SELECT count(*) FROM passage_fts
            JOIN passages p ON p.rowid=passage_fts.rowid
            WHERE passage_fts MATCH '\"治未\" AND \"未病\"' AND p.id='SW-000004'
            """
        ).fetchone()[0]
        modern_count = evidence.execute(
            "SELECT count(*) FROM evidence_records WHERE status='verified'"
        ).fetchone()[0]
    finally:
        classic.close()
        evidence.close()
    if classic_integrity != "ok":
        errors.append("classic-database-integrity-failed")
    if evidence_integrity != "ok":
        errors.append("evidence-database-integrity-failed")
    if classic_count != runtime["classic_passage_count"]:
        errors.append("classic-passage-count-mismatch")
    if quarantine_excluded != runtime["quarantined_passages_excluded"]:
        errors.append("quarantine-exclusion-count-mismatch")
    if modern_count != runtime["modern_verified_record_count"]:
        errors.append("modern-evidence-count-mismatch")
    if known != 1:
        errors.append("classic-search-smoke-failed")

    study_smoke, markdown_render_smoke, m3_classic_retrieval_deferred = check_study_and_render(errors)
    natural_search_smoke, fragment_suppression_smoke, route_recovery_smoke, broad_scope_smoke = check_usability(errors)

    payload = {
        "status": "pass" if not errors else "fail",
        "project_version": runtime.get("project_version", ""),
        "runtime_status": runtime["status"],
        "release_gate_status": runtime["release_gate_status"],
        "classic_integrity": classic_integrity,
        "evidence_integrity": evidence_integrity,
        "classic_passage_count": classic_count,
        "quarantined_passages_excluded": quarantine_excluded,
        "modern_verified_record_count": modern_count,
        "classic_search_smoke": known == 1,
        "study_packet_smoke": study_smoke,
        "markdown_render_smoke": markdown_render_smoke,
        "m3_classic_retrieval_deferred": m3_classic_retrieval_deferred,
        "natural_search_smoke": natural_search_smoke,
        "fragment_suppression_smoke": fragment_suppression_smoke,
        "route_recovery_smoke": route_recovery_smoke,
        "broad_scope_smoke": broad_scope_smoke,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
