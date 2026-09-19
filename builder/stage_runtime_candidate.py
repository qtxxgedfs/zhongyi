#!/usr/bin/env python3
"""Stage a runnable Skill from quality-gated candidate databases without calling it final."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SKILL_DIR = PROJECT_DIR / "skill" / "tcm-classics-study"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classic-db", type=Path, default=PROJECT_DIR / "build" / "classics.sqlite")
    parser.add_argument(
        "--classic-manifest", type=Path, default=PROJECT_DIR / "build" / "classics-index-manifest.json"
    )
    parser.add_argument(
        "--evidence-db", type=Path, default=DEFAULT_SKILL_DIR / "data" / "evidence-cache.sqlite"
    )
    parser.add_argument(
        "--evidence-manifest",
        type=Path,
        default=DEFAULT_SKILL_DIR / "data" / "evidence-cache.manifest.json",
    )
    parser.add_argument("--skill-dir", type=Path, default=DEFAULT_SKILL_DIR)
    args = parser.parse_args()

    quality = load_json(PROJECT_DIR / "sources" / "quality-report.json")
    if quality["overall"]["citable_corpus_status"] != "pass":
        raise SystemExit("Refusing to stage: citable corpus status is not pass")
    classic_manifest = load_json(args.classic_manifest)
    evidence_manifest = load_json(args.evidence_manifest)
    if sha256_file(args.classic_db) != classic_manifest["database_sha256"]:
        raise SystemExit("Classic database hash does not match its manifest")
    if sha256_file(args.evidence_db) != evidence_manifest["database_sha256"]:
        raise SystemExit("Evidence database hash does not match its manifest")

    data_dir = args.skill_dir / "data"
    classic_destination = data_dir / "classics.sqlite"
    if args.classic_db.resolve() != classic_destination.resolve():
        copy_atomic(args.classic_db, classic_destination)
    deployed_classic_manifest = dict(classic_manifest)
    deployed_classic_manifest["database_path"] = "skill/tcm-classics-study/data/classics.sqlite"
    (data_dir / "classics-index-manifest.json").write_text(
        json.dumps(deployed_classic_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    copy_atomic(PROJECT_DIR / "sources" / "source-manifest.json", data_dir / "source-manifest.json")

    runtime_files = [
        args.skill_dir / "SKILL.md",
        args.skill_dir / "USER_GUIDE.md",
        args.skill_dir / "NOTICE.md",
        args.skill_dir / "scripts" / "search.py",
        args.skill_dir / "scripts" / "modern_evidence.py",
        args.skill_dir / "scripts" / "study.py",
        args.skill_dir / "scripts" / "render.py",
        args.skill_dir / "scripts" / "self_check.py",
        *sorted((args.skill_dir / "references").glob("*.md")),
        classic_destination,
        data_dir / "classics-index-manifest.json",
        args.evidence_db,
        args.evidence_manifest,
        data_dir / "source-manifest.json",
    ]
    runtime_manifest = {
        "schema_version": 1,
        "status": "candidate-runnable",
        "release_gate_status": quality["overall"]["release_gate_status"],
        "citable_corpus_status": quality["overall"]["citable_corpus_status"],
        "warning": "可运行候选版，不是最终无条件发布版；隔离语料不在运行时数据库中。",
        "classic_passage_count": quality["overall"]["citable_passage_count"],
        "quarantined_passages_excluded": quality["overall"]["quarantined_passage_count"],
        "modern_verified_record_count": evidence_manifest["verified_record_count"],
        "files": [
            {
                "path": str(path.relative_to(args.skill_dir)).replace("\\", "/"),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in runtime_files
        ],
    }
    output = data_dir / "runtime-candidate-manifest.json"
    output.write_text(json.dumps(runtime_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Staged runnable candidate in {args.skill_dir}: "
        f"{runtime_manifest['classic_passage_count']} classic passages, "
        f"{runtime_manifest['modern_verified_record_count']} modern records"
    )


if __name__ == "__main__":
    main()
