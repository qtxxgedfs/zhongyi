#!/usr/bin/env python3
"""Validate curated modern evidence metadata and build the bundled SQLite cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import jsonschema
from opencc import OpenCC

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA_SQL = PROJECT_DIR / "schemas" / "evidence-cache.sql"
DEFAULT_RECORD_SCHEMA = PROJECT_DIR / "schemas" / "evidence-records.schema.json"
DEFAULT_REGISTRY = PROJECT_DIR / "sources" / "modern" / "source-registry.json"
DEFAULT_TOPICS = PROJECT_DIR / "sources" / "modern" / "evidence-topics.json"
DEFAULT_RECORDS = PROJECT_DIR / "sources" / "modern" / "evidence-records.json"
DEFAULT_SOURCE_AUDIT = PROJECT_DIR / "sources" / "modern" / "evidence-source-audit.json"
DEFAULT_OUTPUT = PROJECT_DIR / "skill" / "tcm-classics-study" / "data" / "evidence-cache.sqlite"
DEFAULT_MANIFEST = PROJECT_DIR / "skill" / "tcm-classics-study" / "data" / "evidence-cache.manifest.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def domain_allowed(url: str, domains: list[str]) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return any(hostname == domain or hostname.endswith("." + domain) for domain in domains)


def validate_inputs(
    registry: dict[str, Any],
    topics: dict[str, Any],
    records: dict[str, Any],
    source_audit: dict[str, Any],
    record_schema: dict[str, Any],
) -> None:
    jsonschema.Draft202012Validator(
        record_schema, format_checker=jsonschema.FormatChecker()
    ).validate(records)
    if registry.get("schema_version") != 1 or topics.get("schema_version") != 1:
        raise ValueError("Modern evidence registry/topic schema version must be 1")

    source_by_id = {item["id"]: item for item in registry["sources"]}
    topic_by_id = {item["id"]: item for item in topics["topics"]}
    if len(source_by_id) != len(registry["sources"]):
        raise ValueError("Duplicate source registry ID")
    if len(topic_by_id) != len(topics["topics"]):
        raise ValueError("Duplicate topic ID")
    audit_by_record: dict[str, dict[str, Any]] = {}
    for page in source_audit["pages"]:
        for record_id in page["record_ids"]:
            if record_id in audit_by_record:
                raise ValueError(f"Evidence record appears on multiple audit pages: {record_id}")
            audit_by_record[record_id] = page
    record_ids: set[str] = set()
    aliases: set[tuple[str, str]] = set()
    for topic in topics["topics"]:
        for alias in topic["aliases"]:
            key = (alias, topic["id"])
            if key in aliases:
                raise ValueError(f"Duplicate topic alias: {key}")
            aliases.add(key)
    for record in records["records"]:
        if record["id"] in record_ids:
            raise ValueError(f"Duplicate evidence record ID: {record['id']}")
        record_ids.add(record["id"])
        source = source_by_id.get(record["source_registry_id"])
        if source is None:
            raise ValueError(f"Unknown source registry ID in {record['id']}")
        if source["organization"] != record["source_organization"]:
            raise ValueError(f"Source organization mismatch in {record['id']}")
        if not domain_allowed(record["url"], source["domains"]):
            raise ValueError(f"URL domain is not approved for {record['id']}: {record['url']}")
        if date.fromisoformat(record["verified_at"]) > date.fromisoformat(record["expires_at"]):
            raise ValueError(f"expires_at precedes verified_at in {record['id']}")
        audit = audit_by_record.get(record["id"])
        if audit is None:
            raise ValueError(f"Evidence record lacks source audit entry: {record['id']}")
        if (
            audit["url"] != record["url"]
            or audit["sha256"] != record["source_content_sha256"]
            or audit["source_registry_id"] != record["source_registry_id"]
            or audit["http_status"] != 200
        ):
            raise ValueError(f"Evidence source audit mismatch in {record['id']}")
        linked_topics: set[str] = set()
        for link in record["topics"]:
            if link["id"] not in topic_by_id:
                raise ValueError(f"Unknown topic {link['id']} in {record['id']}")
            if link["id"] in linked_topics:
                raise ValueError(f"Duplicate topic {link['id']} in {record['id']}")
            linked_topics.add(link["id"])
    if set(audit_by_record) != record_ids:
        raise ValueError("Evidence source audit and record ID sets do not match")


def insert_data(
    connection: sqlite3.Connection,
    registry: dict[str, Any],
    topics: dict[str, Any],
    records: dict[str, Any],
    converter: OpenCC,
) -> None:
    for source in registry["sources"]:
        connection.execute(
            "INSERT INTO source_registry VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                source["id"],
                source["organization"],
                source["source_type"],
                source["priority"],
                json.dumps(source["domains"], ensure_ascii=False, separators=(",", ":")),
                json.dumps(source["allowed_uses"], ensure_ascii=False, separators=(",", ":")),
                source["notes_zh"],
            ),
        )
    for topic in topics["topics"]:
        connection.execute(
            "INSERT INTO topics VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                topic["id"],
                topic["title_zh"],
                topic["category"],
                topic["default_level"],
                topic["refresh_days"],
                json.dumps(topic["search_terms_zh"], ensure_ascii=False, separators=(",", ":")),
                json.dumps(topic["search_terms_en"], ensure_ascii=False, separators=(",", ":")),
            ),
        )
        connection.executemany(
            "INSERT INTO topic_aliases(alias, normalized_alias, topic_id) VALUES (?, ?, ?)",
            [
                (alias, converter.convert(alias).lower().replace(" ", ""), topic["id"])
                for alias in topic["aliases"]
            ],
        )
    for record in records["records"]:
        connection.execute(
            """
            INSERT INTO evidence_records(
                id, summary_zh, conclusion_direction, directness, evidence_type, confidence,
                limitations_zh, population_zh, intervention_zh, outcomes_zh, source_registry_id,
                source_title, source_organization, publication_date, url, doi, pmid, language,
                verified_at, expires_at, source_content_sha256, verification_method, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["summary_zh"],
                record["conclusion_direction"],
                record["directness"],
                record["evidence_type"],
                record["confidence"],
                record["limitations_zh"],
                record["population_zh"],
                record["intervention_zh"],
                record["outcomes_zh"],
                record["source_registry_id"],
                record["source_title"],
                record["source_organization"],
                record["publication_date"],
                record["url"],
                record["doi"],
                record["pmid"],
                record["language"],
                record["verified_at"],
                record["expires_at"],
                bytes.fromhex(record["source_content_sha256"]),
                record["verification_method"],
                record["status"],
            ),
        )
        connection.executemany(
            "INSERT INTO evidence_record_topics(record_id, topic_id, relevance) VALUES (?, ?, ?)",
            [(record["id"], link["id"], link["relevance"]) for link in record["topics"]],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-sql", type=Path, default=DEFAULT_SCHEMA_SQL)
    parser.add_argument("--record-schema", type=Path, default=DEFAULT_RECORD_SCHEMA)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--source-audit", type=Path, default=DEFAULT_SOURCE_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    registry = load_json(args.registry)
    topics = load_json(args.topics)
    records = load_json(args.records)
    source_audit = load_json(args.source_audit)
    record_schema = load_json(args.record_schema)
    validate_inputs(registry, topics, records, source_audit, record_schema)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;")
        connection.executescript(args.schema_sql.read_text(encoding="utf-8"))
        with connection:
            insert_data(connection, registry, topics, records, OpenCC("t2s"))
            metadata = {
                "schema_version": "1",
                "cache_status": "curated-seed",
                "source_registry_count": str(len(registry["sources"])),
                "topic_count": str(len(topics["topics"])),
                "verified_record_count": str(sum(item["status"] == "verified" for item in records["records"])),
                "source_registry_sha256": sha256_file(args.registry),
                "topics_sha256": sha256_file(args.topics),
                "records_sha256": sha256_file(args.records),
                "source_audit_sha256": sha256_file(args.source_audit),
                "schema_sha256": sha256_file(args.schema_sql),
                "record_schema_sha256": sha256_file(args.record_schema),
                "latest_verification_date": max((item["verified_at"] for item in records["records"]), default=""),
            }
            connection.executemany("INSERT INTO cache_info(key, value) VALUES (?, ?)", metadata.items())
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Evidence cache integrity check failed: {integrity}")
    finally:
        connection.close()
    os.replace(temporary, args.output)

    manifest = {
        "schema_version": 1,
        "status": "curated-seed",
        "database_path": str(args.output.relative_to(PROJECT_DIR)).replace("\\", "/"),
        "database_sha256": sha256_file(args.output),
        "database_size_bytes": args.output.stat().st_size,
        "source_registry_count": len(registry["sources"]),
        "topic_count": len(topics["topics"]),
        "verified_record_count": sum(item["status"] == "verified" for item in records["records"]),
        "inputs": {
            "source_registry_sha256": sha256_file(args.registry),
            "topics_sha256": sha256_file(args.topics),
            "records_sha256": sha256_file(args.records),
            "source_audit_sha256": sha256_file(args.source_audit),
            "schema_sha256": sha256_file(args.schema_sql),
            "record_schema_sha256": sha256_file(args.record_schema),
        },
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Built {args.output}: {manifest['topic_count']} topics, "
        f"{manifest['verified_record_count']} verified records, "
        f"{manifest['database_size_bytes'] / 1024:.1f} KiB"
    )


if __name__ == "__main__":
    main()
