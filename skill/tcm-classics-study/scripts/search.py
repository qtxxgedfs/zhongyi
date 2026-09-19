#!/usr/bin/env python3
"""Search, inspect, and navigate the local TCM classics SQLite corpus."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = SCRIPT_DIR.parent / "data" / "classics.sqlite"
PUNCT_RE = re.compile(r"[^0-9a-z\u3400-\u9fff\U00020000-\U0003134f]+", flags=re.I)
STOP_PHRASES = (
    "请问", "请帮我", "帮我查", "查一下", "原文怎么说", "原文", "如何理解", "怎么理解",
    "什么意思", "是什么", "为什么", "为何", "怎样", "哪里", "哪一篇", "关于", "中说", "怎么说",
)
TRADITIONAL_TO_SIMPLIFIED = str.maketrans(
    "問靈樞傷論匱難經溫條黃帝內陰陽氣脈證湯藥臟腑榮衛補瀉傳統醫學體會門風熱寒濕燥長與無為後發實虛歲數",
    "问灵枢伤论匮难经温条黄帝内阴阳气脉证汤药脏腑荣卫补泻传统医学体会门风热寒湿燥长与无为后发实虚岁数",
)
SEARCH_PHRASE_OVERRIDES = {"五藏": "五脏", "欬": "咳", "痺": "痹"}
WORK_CODES = {
    "suwen": "suwen",
    "lingshu": "lingshu",
    "shanghanlun": "shanghanlun",
    "jingui": "jingui",
    "nanjing": "nanjing",
    "wenbingtiaobian": "wenbingtiaobian",
    "素问": "suwen",
    "灵枢": "lingshu",
    "伤寒论": "shanghanlun",
    "金匮要略": "jingui",
    "难经": "nanjing",
    "温病条辨": "wenbingtiaobian",
}


def connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"Database not found: {path}")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA temp_store = MEMORY")
    return connection


def normalize(value: str) -> str:
    normalized = value.translate(TRADITIONAL_TO_SIMPLIFIED).lower()
    for source, target in SEARCH_PHRASE_OVERRIDES.items():
        normalized = normalized.replace(source, target)
    return PUNCT_RE.sub("", normalized)


def bigrams(value: str) -> list[str]:
    if not value:
        return []
    if len(value) == 1:
        return [value]
    return [value[index : index + 2] for index in range(len(value) - 1)]


def aliases(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM aliases ORDER BY length(normalized_alias) DESC, id"
    ).fetchall()


def infer_route(connection: sqlite3.Connection, query: str) -> dict[str, Any]:
    normalized = normalize(query)
    route: dict[str, Any] = {
        "normalized_query": normalized,
        "target_works": [],
        "canons": [],
        "work_ids": [],
        "authors": [],
        "matched_aliases": [],
    }
    for item in aliases(connection):
        alias = item["normalized_alias"]
        if alias and alias in normalized:
            route["matched_aliases"].append(item["alias"])
            if item["target_work"] and item["target_work"] not in route["target_works"]:
                route["target_works"].append(item["target_work"])
            if item["canon"] and item["canon"] not in route["canons"]:
                route["canons"].append(item["canon"])
            if item["kind"] == "author":
                if item["work_id"] and item["work_id"] not in route["work_ids"]:
                    route["work_ids"].append(item["work_id"])
                elif item["canonical"] not in route["authors"]:
                    route["authors"].append(item["canonical"])
    return route


def normalized_terms(
    connection: sqlite3.Connection,
    query: str,
    raw_terms: str | None,
    route: dict[str, Any],
) -> list[str]:
    values = [item.strip() for item in raw_terms.split(",")] if raw_terms else [query]
    term_aliases = [item for item in aliases(connection) if item["kind"] == "term"]
    output: list[str] = []
    for value in values:
        for stop in STOP_PHRASES:
            value = value.replace(stop, "")
        normalized = normalize(value)
        for item in term_aliases:
            alias = item["normalized_alias"]
            if alias:
                normalized = normalized.replace(alias, normalize(item["canonical"]))
        if not raw_terms:
            for alias in route["matched_aliases"]:
                reduced = normalized.replace(normalize(alias), "")
                if len(reduced) >= 2:
                    normalized = reduced
        if normalized and normalized not in output:
            output.append(normalized)
    if not output:
        fallback = normalize(query)
        if fallback:
            output.append(fallback)
    return output


def fts_expression(terms: list[str], broad: bool = False) -> str:
    groups: list[str] = []
    for term in terms:
        tokens = list(dict.fromkeys(bigrams(term)))
        if not tokens:
            continue
        operator = " OR " if broad else " AND "
        groups.append("(" + operator.join(f'"{token}"' for token in tokens) + ")")
    return " OR ".join(groups)


def jaccard(left: str, right: str) -> float:
    left_set, right_set = set(bigrams(left)), set(bigrams(right))
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def row_payload(row: sqlite3.Row, score: float | None = None) -> dict[str, Any]:
    payload = {
        "id": row["id"],
        "work_id": row["work_id"],
        "title": row["title"],
        "author": row["author"],
        "canon": row["canon"],
        "layer": row["layer"],
        "relationship": json.loads(row["relationship_json"]),
        "volume": row["volume"],
        "section": row["section"],
        "subsection": row["subsection"],
        "speaker": row["speaker"],
        "speaker_type": row["speaker_type"],
        "text_simplified": row["text_simplified"],
        "source_page_title": row["source_page_title"],
        "source_revision_id": row["source_revision_id"],
        "fixed_source_url": (
            "https://zh.wikisource.org/w/index.php?title="
            + quote(row["source_page_title_source"], safe="")
            + f"&oldid={row['source_revision_id']}"
        ),
        "content_sha256": row["content_sha256"].hex(),
    }
    if score is not None:
        payload["score"] = round(score, 6)
    return payload


def query_candidates(
    connection: sqlite3.Connection,
    expression: str,
    route: dict[str, Any],
    canon: str,
    work: str,
    layers: list[str],
    author: str | None,
    candidate_limit: int,
) -> list[sqlite3.Row]:
    conditions = ["passage_fts MATCH ?"]
    parameters: list[Any] = [expression]
    if canon != "auto":
        conditions.append("w.canon = ?")
        parameters.append(canon)
    elif route["canons"]:
        placeholders = ",".join("?" for _ in route["canons"])
        conditions.append(f"w.canon IN ({placeholders})")
        parameters.extend(route["canons"])
    target_work = WORK_CODES.get(work, work) if work != "auto" else None
    target_works = [target_work] if target_work else route["target_works"]
    if target_works:
        placeholders = ",".join("?" for _ in target_works)
        conditions.append(
            f"EXISTS (SELECT 1 FROM work_targets wt WHERE wt.work_id=w.id AND wt.target_work IN ({placeholders}))"
        )
        parameters.extend(target_works)
    if route["work_ids"]:
        placeholders = ",".join("?" for _ in route["work_ids"])
        conditions.append(f"w.id IN ({placeholders})")
        parameters.extend(route["work_ids"])
    if route["authors"]:
        conditions.append("(" + " OR ".join("w.author LIKE ?" for _ in route["authors"]) + ")")
        parameters.extend(f"%{item}%" for item in route["authors"])
    if layers:
        placeholders = ",".join("?" for _ in layers)
        conditions.append(f"w.layer IN ({placeholders})")
        parameters.extend(layers)
    if author:
        conditions.append("w.author LIKE ?")
        parameters.append(f"%{author}%")
    parameters.append(candidate_limit)
    sql = f"""
        SELECT p.*, w.title, w.author, w.canon, w.layer, w.relationship_json,
               loc.volume, loc.section, loc.subsection, loc.speaker, loc.speaker_type,
               sp.title_simplified AS source_page_title, sp.title_source AS source_page_title_source,
               sp.revision_id AS source_revision_id,
               bm25(passage_fts, 5.0, 1.0) AS fts_rank
        FROM passage_fts
        JOIN passages p ON p.rowid = passage_fts.rowid
        JOIN works w ON w.id = p.work_id
        JOIN locations loc ON loc.id = p.location_id
        JOIN source_pages sp ON sp.id = p.source_page_id
        WHERE {' AND '.join(conditions)}
        ORDER BY fts_rank
        LIMIT ?
    """
    return connection.execute(sql, parameters).fetchall()


def search(connection: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    route = infer_route(connection, args.query)
    terms = normalized_terms(connection, args.query, args.terms, route)
    expression = fts_expression(terms)
    layers = [] if args.layers == "all" else [item.strip() for item in args.layers.split(",") if item.strip()]
    rows = query_candidates(
        connection, expression, route, args.canon, args.work, layers, args.author, args.candidate_limit
    )
    fallback = False
    if not rows and expression:
        fallback = True
        rows = query_candidates(
            connection,
            fts_expression(terms, broad=True),
            route,
            args.canon,
            args.work,
            layers,
            args.author,
            args.candidate_limit,
        )

    scored: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        score = -float(row["fts_rank"])
        location = normalize(row["title"] + row["volume"] + row["section"] + row["subsection"] + row["speaker"])
        for term in terms:
            if term in normalize(row["text_simplified"]):
                score += 12.0 + min(len(term), 12)
            if term in location:
                score += 8.0
        if row["layer"] == "core":
            score += 1.5
        scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], item[1]["work_id"], item[1]["sequence"]))

    selected: list[tuple[float, sqlite3.Row]] = []
    core_count = 0
    extension_count = 0
    for item in scored:
        score, row = item
        is_core = row["layer"] == "core"
        if is_core and core_count >= args.limit_core:
            continue
        if not is_core and extension_count >= args.limit_commentary:
            continue
        if any(
            prior[1]["work_id"] == row["work_id"]
            and jaccard(normalize(prior[1]["text_simplified"]), normalize(row["text_simplified"])) >= 0.88
            for prior in selected
        ):
            continue
        selected.append(item)
        core_count += int(is_core)
        extension_count += int(not is_core)
        if len(selected) >= args.limit_total:
            break

    layer_order = {"core": 0, "commentary": 1, "lineage": 2}
    selected.sort(key=lambda item: (layer_order.get(item[1]["layer"], 9), -item[0]))
    metadata = dict(connection.execute("SELECT key, value FROM schema_info"))
    return {
        "query": args.query,
        "terms": terms,
        "route": route,
        "fts_fallback_used": fallback,
        "database_build_status": metadata.get("build_status"),
        "quarantined_passages_excluded": int(metadata.get("quarantined_passages_excluded", 0)),
        "results": [row_payload(row, score) for score, row in selected],
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def get_passage(connection: sqlite3.Connection, passage_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT p.*, w.title, w.author, w.canon, w.layer, w.relationship_json,
               loc.volume, loc.section, loc.subsection, loc.speaker, loc.speaker_type,
               sp.title_simplified AS source_page_title, sp.title_source AS source_page_title_source,
               sp.revision_id AS source_revision_id
        FROM passages p
        JOIN works w ON w.id=p.work_id
        JOIN locations loc ON loc.id=p.location_id
        JOIN source_pages sp ON sp.id=p.source_page_id
        WHERE p.id=?
        """,
        (passage_id,),
    ).fetchone()
    return row_payload(row) if row else None


def context(connection: sqlite3.Connection, passage_id: str, before: int, after: int) -> dict[str, Any]:
    anchor = connection.execute("SELECT work_id, sequence FROM passages WHERE id=?", (passage_id,)).fetchone()
    if not anchor:
        return {"id": passage_id, "error": "passage-not-found", "results": []}
    prior = connection.execute(
        """
        SELECT p.*, w.title, w.author, w.canon, w.layer, w.relationship_json,
               loc.volume, loc.section, loc.subsection, loc.speaker, loc.speaker_type,
               sp.title_simplified AS source_page_title, sp.title_source AS source_page_title_source,
               sp.revision_id AS source_revision_id
        FROM passages p
        JOIN works w ON w.id=p.work_id
        JOIN locations loc ON loc.id=p.location_id
        JOIN source_pages sp ON sp.id=p.source_page_id
        WHERE p.work_id=? AND p.sequence<? ORDER BY p.sequence DESC LIMIT ?
        """,
        (anchor["work_id"], anchor["sequence"], before),
    ).fetchall()[::-1]
    following = connection.execute(
        """
        SELECT p.*, w.title, w.author, w.canon, w.layer, w.relationship_json,
               loc.volume, loc.section, loc.subsection, loc.speaker, loc.speaker_type,
               sp.title_simplified AS source_page_title, sp.title_source AS source_page_title_source,
               sp.revision_id AS source_revision_id
        FROM passages p
        JOIN works w ON w.id=p.work_id
        JOIN locations loc ON loc.id=p.location_id
        JOIN source_pages sp ON sp.id=p.source_page_id
        WHERE p.work_id=? AND p.sequence>=? ORDER BY p.sequence LIMIT ?
        """,
        (anchor["work_id"], anchor["sequence"], after + 1),
    ).fetchall()
    return {"id": passage_id, "results": [row_payload(row) for row in [*prior, *following]]}


def toc(connection: sqlite3.Connection, work: str) -> dict[str, Any]:
    work_id = WORK_CODES.get(work, work)
    rows = connection.execute(
        """
        SELECT loc.volume, loc.section, loc.subsection,
               min(p.sequence) AS first_sequence, count(*) AS passage_count
        FROM passages p JOIN locations loc ON loc.id=p.location_id
        WHERE p.work_id=?
        GROUP BY loc.volume, loc.section, loc.subsection ORDER BY first_sequence
        """,
        (work_id,),
    ).fetchall()
    return {"work_id": work_id, "entries": [dict(row) for row in rows]}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--db", type=Path, default=DEFAULT_DB)
    subparsers = result.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--terms", help="Comma-separated high-value classic terms")
    search_parser.add_argument("--canon", choices=["auto", "huangdi", "zhongjing", "nanjing", "wenbing"], default="auto")
    search_parser.add_argument("--work", default="auto")
    search_parser.add_argument("--layers", default="all", help="all or comma-separated core,commentary,lineage")
    search_parser.add_argument("--author")
    search_parser.add_argument("--limit-core", type=int, default=3)
    search_parser.add_argument("--limit-commentary", type=int, default=3)
    search_parser.add_argument("--limit-total", type=int, default=6)
    search_parser.add_argument("--candidate-limit", type=int, default=240)

    passage_parser = subparsers.add_parser("passage")
    passage_parser.add_argument("--id", required=True)

    context_parser = subparsers.add_parser("context")
    context_parser.add_argument("--id", required=True)
    context_parser.add_argument("--before", type=int, default=1)
    context_parser.add_argument("--after", type=int, default=1)

    toc_parser = subparsers.add_parser("toc")
    toc_parser.add_argument("--work", required=True)
    return result


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args()
    connection = connect(args.db)
    try:
        if args.command == "search":
            payload = search(connection, args)
        elif args.command == "passage":
            payload = get_passage(connection, args.id) or {"id": args.id, "error": "passage-not-found"}
        elif args.command == "context":
            payload = context(connection, args.id, args.before, args.after)
        else:
            payload = toc(connection, args.work)
    finally:
        connection.close()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
