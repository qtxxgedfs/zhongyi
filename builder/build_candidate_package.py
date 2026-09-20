#!/usr/bin/env python3
"""Build and install-test the runnable candidate Skill ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SKILL_DIR = PROJECT_DIR / "skill" / "tcm-classics-study"
DEFAULT_OUTPUT = PROJECT_DIR / "dist" / "tcm-classics-study-candidate.zip"
DEFAULT_EXTERNAL_MANIFEST = PROJECT_DIR / "dist" / "tcm-classics-study-candidate.manifest.json"
EXCLUDED_SUFFIXES = (".pyc", ".sqlite-wal", ".sqlite-shm")
EXCLUDED_NAMES = {"package-candidate-manifest.json", "evidence-cache.runtime.sqlite"}
REQUIRED_RUNTIME_PATHS = {
    "SKILL.md",
    "USER_GUIDE.md",
    "scripts/search.py",
    "scripts/modern_evidence.py",
    "scripts/study.py",
    "scripts/render.py",
    "scripts/self_check.py",
    "data/classics.sqlite",
    "data/query-rules.json",
    "data/evidence-cache.sqlite",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def package_files(skill_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in skill_dir.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and not path.name.endswith(EXCLUDED_SUFFIXES)
        and path.name not in EXCLUDED_NAMES
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", type=Path, default=DEFAULT_SKILL_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--external-manifest", type=Path, default=DEFAULT_EXTERNAL_MANIFEST)
    args = parser.parse_args()

    project_version = (PROJECT_DIR / "VERSION").read_text(encoding="utf-8").strip()
    quality = load_json(PROJECT_DIR / "sources" / "quality-report.json")
    acceptance = load_json(PROJECT_DIR / "build" / "acceptance-results.json")
    natural_acceptance = load_json(PROJECT_DIR / "build" / "natural-acceptance-results.json")
    runtime = load_json(args.skill_dir / "data" / "runtime-candidate-manifest.json")
    if quality["overall"]["citable_corpus_status"] != "pass":
        raise SystemExit("Refusing to package: citable corpus status is not pass")
    if acceptance["status"] != "pass" or acceptance["question_count"] < 150:
        raise SystemExit("Refusing to package: acceptance report is missing or failed")
    if (
        natural_acceptance["status"] != "pass"
        or natural_acceptance["single_turn_count"] < 60
        or natural_acceptance["conversation_count"] < 10
    ):
        raise SystemExit("Refusing to package: natural-language acceptance is missing or failed")
    if runtime["status"] != "candidate-runnable":
        raise SystemExit("Refusing to package: runtime was not staged as candidate-runnable")
    if runtime.get("project_version") != project_version:
        raise SystemExit("Refusing to package: staged runtime version does not match VERSION")
    runtime_paths = {item["path"] for item in runtime["files"]}
    missing_runtime_paths = sorted(REQUIRED_RUNTIME_PATHS - runtime_paths)
    if missing_runtime_paths:
        raise SystemExit(
            "Refusing to package: runtime manifest is missing " + ", ".join(missing_runtime_paths)
        )

    self_check = subprocess.run(
        [sys.executable, str(args.skill_dir / "scripts" / "self_check.py")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if json.loads(self_check.stdout)["status"] != "pass":
        raise SystemExit("Refusing to package: runtime self-check failed")

    files = package_files(args.skill_dir)
    internal_manifest = {
        "schema_version": 1,
        "project_version": project_version,
        "package_status": "candidate-runnable",
        "release_gate_status": quality["overall"]["release_gate_status"],
        "warning": "功能验收已通过；文本底本质量线仍待后续精修。本包不得改称最终无条件发布版。",
        "acceptance": {
            "question_count": acceptance["question_count"],
            "checks_passed": acceptance["checks_passed"],
            "checks_total": acceptance["checks_total"],
            "status": acceptance["status"],
        },
        "natural_acceptance": {
            "single_turn_count": natural_acceptance["single_turn_count"],
            "conversation_count": natural_acceptance["conversation_count"],
            "top1_rate": natural_acceptance["top1_acceptance"]["rate"],
            "route_recovery_rate": natural_acceptance["route_recovery"]["rate"],
            "conversation_context_rate": natural_acceptance["conversation_context"]["rate"],
            "status": natural_acceptance["status"],
        },
        "corpus": {
            "citable_passages": quality["overall"]["citable_passage_count"],
            "quarantined_passages_excluded": quality["overall"]["quarantined_passage_count"],
            "citable_corpus_status": quality["overall"]["citable_corpus_status"],
        },
        "files": [
            {
                "path": str(path.relative_to(args.skill_dir)).replace("\\", "/"),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in files
        ],
    }
    internal_path = args.skill_dir / "data" / "package-candidate-manifest.json"
    internal_path.write_text(json.dumps(internal_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files.append(internal_path)
    files.sort()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.unlink(missing_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, (Path(args.skill_dir.name) / path.relative_to(args.skill_dir)).as_posix())

    with tempfile.TemporaryDirectory() as directory:
        install_root = Path(directory)
        with zipfile.ZipFile(args.output) as archive:
            archive.extractall(install_root)
        installed = install_root / args.skill_dir.name
        completed = subprocess.run(
            [sys.executable, str(installed / "scripts" / "self_check.py")],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        install_result = json.loads(completed.stdout)
        if install_result["status"] != "pass":
            raise SystemExit("Extracted package self-check failed")

    external_manifest = {
        "schema_version": 1,
        "project_version": project_version,
        "package_status": "candidate-runnable",
        "zip_path": str(args.output.relative_to(PROJECT_DIR)).replace("\\", "/"),
        "zip_sha256": sha256_file(args.output),
        "zip_size_bytes": args.output.stat().st_size,
        "top_level_directory": args.skill_dir.name,
        "file_count": len(files),
        "install_test": "pass",
        "runtime_self_check": install_result,
        "acceptance_status": acceptance["status"],
        "natural_acceptance_status": natural_acceptance["status"],
        "release_gate_status": quality["overall"]["release_gate_status"],
    }
    args.external_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.external_manifest.write_text(
        json.dumps(external_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Built and install-tested {args.output}: {len(files)} files, "
        f"{args.output.stat().st_size / 1024 / 1024:.1f} MiB, "
        f"sha256={external_manifest['zip_sha256']}"
    )


if __name__ == "__main__":
    main()
