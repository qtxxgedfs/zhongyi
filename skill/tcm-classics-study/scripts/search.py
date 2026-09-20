#!/usr/bin/env python3
"""Search, inspect, and navigate the local TCM classics SQLite corpus."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_DB = SKILL_DIR / "data" / "classics.sqlite"
DEFAULT_RULES = SKILL_DIR / "data" / "query-rules.json"
PUNCT_RE = re.compile(r"[^0-9a-z\u3400-\u9fff\U00020000-\U0003134f]+", flags=re.I)
SENTENCE_RE = re.compile(r"[^。！？；!?]+[。！？；!?]?", flags=re.S)
QUOTED_RE = re.compile(r"[“\"「『]([^”\"」』]{2,40})[”\"」』]")
QUANTITY_ONLY_RE = re.compile(r"^[零〇一二三四五六七八九十百千万半两升合钱分厘枚个味斤]+$")
QUESTION_FRAGMENT_RE = re.compile(r"(?:何也|奈何|何如|愿闻|敢问|何谓也)[。！？?]?$" )
REFERENTIAL_FRAGMENT_RE = re.compile(r"^(?:方)?(?:见|详)(?:上|下|前|后|本篇)|^(?:同上|如上|方见上|一云.+)$")
TRADITIONAL_TO_SIMPLIFIED = str.maketrans(
    "問靈樞傷論匱難經溫條黃帝內陰陽氣脈證湯藥臟腑榮衛補瀉傳統醫學體會門風熱寒濕燥長與無為後發實虛歲數鬭鑄錐",
    "问灵枢伤论匮难经温条黄帝内阴阳气脉证汤药脏腑荣卫补泻传统医学体会门风热寒湿燥长与无为后发实虚岁数斗铸锥",
)
SEARCH_PHRASE_OVERRIDES = {"五藏": "五脏", "欬": "咳", "痺": "痹", "鬬": "斗"}
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
MATCH_TIER_LABELS = {
    "A": "直接原句命中",
    "B": "高覆盖相关命中",
    "C": "部分直接相关",
    "context": "连续上下文",
}


def connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"Database not found: {path}")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA temp_store = MEMORY")
    return connection


@lru_cache(maxsize=4)
def load_rules(path: str) -> dict[str, Any]:
    rule_path = Path(path)
    if not rule_path.exists():
        raise SystemExit(f"Query rules not found: {rule_path}")
    payload = json.loads(rule_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise SystemExit(f"Unsupported query rules schema: {payload.get('schema_version')}")
    return payload


def rules_for(args: argparse.Namespace | None = None) -> dict[str, Any]:
    path = getattr(args, "rules", DEFAULT_RULES) if args is not None else DEFAULT_RULES
    return load_rules(str(Path(path).resolve()))


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


def infer_route(
    connection: sqlite3.Connection,
    query: str,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = rules or rules_for()
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
            if item["alias"] not in route["matched_aliases"]:
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
    for author_route in rules.get("author_routes", []):
        for alias in author_route.get("aliases", []):
            if normalize(alias) not in normalized:
                continue
            if alias not in route["matched_aliases"]:
                route["matched_aliases"].append(alias)
            for target in author_route.get("target_works", []):
                if target not in route["target_works"]:
                    route["target_works"].append(target)
            break
    return route


def infer_intent(query: str, route: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize(query)
    if any(normalize(cue) in normalized for cue in ("前后文", "上下文", "上一段", "下一段", "展开")):
        mode = "context"
    elif any(normalize(cue) in normalized for cue in ("比较", "异同", "不同", "分歧")):
        mode = "compare"
    elif any(normalize(cue) in normalized for cue in ("原文", "原句", "出处", "哪一篇", "在哪里", "怎么说")):
        mode = "quote_lookup"
    elif route["work_ids"] or route["authors"] or any(
        normalize(cue) in normalized for cue in ("注释", "注家", "医家", "解释")
    ):
        mode = "physician"
    else:
        mode = "study"
    broad_hits = [item for item in rules.get("broad_concepts", []) if normalize(item) in normalized]
    has_scope = bool(route["target_works"] or route["canons"] or route["work_ids"] or route["authors"])
    scope_too_broad = bool(broad_hits and not has_scope and mode == "study")
    return {
        "mode": mode,
        "scope_too_broad": scope_too_broad,
        "broad_concepts": broad_hits,
    }


def apply_term_aliases(
    value: str,
    alias_rows: Iterable[sqlite3.Row],
) -> str:
    normalized = normalize(value)
    for item in alias_rows:
        if item["kind"] != "term":
            continue
        alias = item["normalized_alias"]
        if alias:
            normalized = normalized.replace(alias, normalize(item["canonical"]))
    return normalized


def _add_term(
    output: list[str],
    sources: list[dict[str, str]],
    value: str,
    source: str,
    alias_rows: Iterable[sqlite3.Row],
) -> None:
    normalized = apply_term_aliases(value, alias_rows)
    if len(normalized) < 2 or normalized in output:
        return
    output.append(normalized)
    sources.append({"term": normalized, "source": source})


def build_query_plan(
    connection: sqlite3.Connection,
    query: str,
    raw_terms: str | None,
    route: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    alias_rows = aliases(connection)
    intent = infer_intent(query, route, rules)
    terms: list[str] = []
    term_sources: list[dict[str, str]] = []
    matched_expansions: list[str] = []
    preferred_passage_ids: list[str] = []
    keep_scope_warning = False
    if raw_terms:
        for value in raw_terms.split(","):
            _add_term(terms, term_sources, value.strip(), "explicit", alias_rows)
    else:
        normalized_query = normalize(query)
        for expansion in rules.get("expansions", []):
            if any(normalize(trigger) in normalized_query for trigger in expansion.get("triggers", [])):
                matched_expansions.append(expansion["id"])
                keep_scope_warning = keep_scope_warning or bool(expansion.get("keep_scope_warning"))
                for passage_id in expansion.get("preferred_passage_ids", []):
                    if passage_id not in preferred_passage_ids:
                        preferred_passage_ids.append(passage_id)
                for term in expansion.get("terms", []):
                    _add_term(terms, term_sources, term, f"expansion:{expansion['id']}", alias_rows)

        for quoted in QUOTED_RE.findall(query):
            _add_term(terms, term_sources, quoted, "quoted", alias_rows)

        if matched_expansions and not keep_scope_warning:
            intent["scope_too_broad"] = False
        residual = normalized_query
        removable = [*route["matched_aliases"]]
        for author_route in rules.get("author_routes", []):
            removable.extend(author_route.get("aliases", []))
        removable.extend(rules.get("task_phrases", []))
        removable.extend(rules.get("filler_phrases", []))
        for phrase in sorted({normalize(item) for item in removable if item}, key=len, reverse=True):
            residual = residual.replace(phrase, "")
        residual = residual.strip()
        if not matched_expansions and 2 <= len(residual) <= 18:
            _add_term(terms, term_sources, residual, "query", alias_rows)
        elif not terms and residual:
            _add_term(terms, term_sources, residual[:32], "query-long", alias_rows)

    return {
        "intent": intent,
        "terms": terms,
        "term_sources": term_sources,
        "matched_expansions": matched_expansions,
        "preferred_passage_ids": preferred_passage_ids,
        "explicit_terms_supplied": bool(raw_terms),
    }


def normalized_terms(
    connection: sqlite3.Connection,
    query: str,
    raw_terms: str | None,
    route: dict[str, Any],
) -> list[str]:
    """Backward-compatible helper used by external callers."""
    return build_query_plan(connection, query, raw_terms, route, rules_for())["terms"]


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


def base_row_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "work_id": row["work_id"],
        "sequence": row["sequence"],
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


def row_payload(row: sqlite3.Row, score: float | None = None) -> dict[str, Any]:
    """Backward-compatible payload helper."""
    payload = base_row_payload(row)
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
    if not expression:
        return []
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


def relaxed_route(route: dict[str, Any]) -> dict[str, Any]:
    return {
        **route,
        "target_works": [],
        "canons": [],
        "work_ids": [],
        "authors": [],
    }


def fragment_reason(text: str) -> str | None:
    cleaned = normalize(text)
    if len(cleaned) < 8:
        return "too-short"
    if QUANTITY_ONLY_RE.fullmatch(cleaned):
        return "quantity-only"
    if REFERENTIAL_FRAGMENT_RE.search(cleaned):
        return "reference-only"
    if cleaned in {"阙", "缺", "阙文", "缺文"}:
        return "missing-text-marker"
    if len(cleaned) < 8 and (text.lstrip().startswith("（") or text.lstrip().startswith("(")):
        return "short-parenthetical"
    return None


def analyze_candidate(
    row: sqlite3.Row,
    terms: list[str],
    intent: dict[str, Any],
    channel: str,
    route_scope: str,
    preferred_passage_ids: set[str] | None = None,
) -> dict[str, Any]:
    body = normalize(row["text_simplified"])
    location_text = normalize(
        row["title"] + row["volume"] + row["section"] + row["subsection"] + row["speaker"]
    )
    term_details: list[dict[str, Any]] = []
    for term in terms:
        tokens = set(bigrams(term))
        body_tokens = set(bigrams(body))
        location_tokens = set(bigrams(location_text))
        exact_body = bool(term and term in body)
        exact_location = bool(term and term in location_text)
        body_coverage = len(tokens & body_tokens) / len(tokens) if tokens else 0.0
        location_coverage = len(tokens & location_tokens) / len(tokens) if tokens else 0.0
        coverage = max(body_coverage, location_coverage)
        term_details.append(
            {
                "term": term,
                "exact_body": exact_body,
                "exact_location": exact_location,
                "coverage": coverage,
                "matched_bigrams": len(tokens & (body_tokens | location_tokens)),
                "term_bigrams": len(tokens),
            }
        )
    best = max(
        term_details,
        key=lambda item: (
            item["exact_body"],
            item["exact_location"],
            item["coverage"],
            len(item["term"]),
        ),
        default={
            "term": "",
            "exact_body": False,
            "exact_location": False,
            "coverage": 0.0,
            "matched_bigrams": 0,
            "term_bigrams": 0,
        },
    )
    if best["exact_body"]:
        tier = "A"
    elif best["exact_location"] or best["coverage"] >= 0.82:
        tier = "B"
    elif best["coverage"] >= 0.52 and best["matched_bigrams"] >= 2:
        tier = "C"
    else:
        tier = "D"

    fts_score = -float(row["fts_rank"])
    tier_bonus = {"A": 80.0, "B": 46.0, "C": 22.0, "D": 0.0}[tier]
    score = fts_score + tier_bonus + best["coverage"] * 18.0
    if best["exact_body"]:
        score += min(len(best["term"]), 16)
    if row["layer"] == "core":
        score += 12.0 if intent["mode"] == "quote_lookup" else 3.5
    if preferred_passage_ids and row["id"] in preferred_passage_ids:
        score += 60.0
    length = len(row["text_simplified"])
    if 30 <= length <= 360:
        score += 4.0
    elif length < 10:
        score -= 18.0
    elif length < 20:
        score -= 7.0
    elif length > 520:
        score -= 3.0
    if QUESTION_FRAGMENT_RE.search(row["text_simplified"].strip()) and length < 32:
        score -= 15.0
    reason = fragment_reason(row["text_simplified"])
    if reason:
        score -= 100.0
    useful = tier in {"A", "B", "C"} and reason is None
    return {
        "tier": tier,
        "label": MATCH_TIER_LABELS.get(tier, "弱相关候选"),
        "best_term": best["term"],
        "matched_terms": [item["term"] for item in term_details if item["exact_body"]],
        "coverage": round(float(best["coverage"]), 4),
        "exact_phrase": bool(best["exact_body"]),
        "location_match": bool(best["exact_location"]),
        "channel": channel,
        "route_scope": route_scope,
        "preferred_passage": bool(preferred_passage_ids and row["id"] in preferred_passage_ids),
        "standalone_quality": "insufficient" if reason else "usable",
        "suppression_reason": reason,
        "useful": useful,
        "score": score,
    }


def score_rows(
    rows: list[sqlite3.Row],
    terms: list[str],
    intent: dict[str, Any],
    channel: str,
    route_scope: str,
    preferred_passage_ids: set[str] | None = None,
) -> list[tuple[dict[str, Any], sqlite3.Row]]:
    scored = [
        (analyze_candidate(row, terms, intent, channel, route_scope, preferred_passage_ids), row)
        for row in rows
    ]
    scored.sort(key=lambda item: (-item[0]["score"], item[1]["work_id"], item[1]["sequence"]))
    return scored


def has_direct(scored: list[tuple[dict[str, Any], sqlite3.Row]]) -> bool:
    return any(item[0]["useful"] and item[0]["tier"] in {"A", "B"} for item in scored)


def has_exact_term(scored: list[tuple[dict[str, Any], sqlite3.Row]], term: str) -> bool:
    return any(item[0]["useful"] and term in item[0]["matched_terms"] for item in scored)


def has_exact_core(scored: list[tuple[dict[str, Any], sqlite3.Row]], term: str) -> bool:
    return any(
        item[0]["useful"]
        and term in item[0]["matched_terms"]
        and item[1]["layer"] == "core"
        for item in scored
    )


def has_preferred(
    scored: list[tuple[dict[str, Any], sqlite3.Row]], preferred_passage_ids: set[str]
) -> bool:
    return any(item[0]["useful"] and item[1]["id"] in preferred_passage_ids for item in scored)


def best_sentence(text: str, term: str) -> tuple[str, int, int]:
    if not text:
        return "", 0, 0
    spans = [(match.group(0), match.start(), match.end()) for match in SENTENCE_RE.finditer(text)]
    if not spans:
        spans = [(text, 0, len(text))]
    normalized_term = normalize(term)
    term_tokens = set(bigrams(normalized_term))

    def sentence_score(item: tuple[str, int, int]) -> tuple[int, float, int]:
        sentence = normalize(item[0])
        exact = int(bool(normalized_term and normalized_term in sentence))
        tokens = set(bigrams(sentence))
        coverage = len(tokens & term_tokens) / len(term_tokens) if term_tokens else 0.0
        return exact, coverage, -len(item[0])

    sentence, start, end = max(spans, key=sentence_score)
    index = spans.index((sentence, start, end))
    left = right = index
    while len(sentence) < 64:
        if right + 1 < len(spans) and len(sentence + spans[right + 1][0]) <= 260:
            right += 1
            sentence += spans[right][0]
            end = spans[right][2]
            continue
        if left > 0 and len(spans[left - 1][0] + sentence) <= 260:
            left -= 1
            sentence = spans[left][0] + sentence
            start = spans[left][1]
            continue
        break
    if len(sentence) <= 320:
        return sentence.strip(), start, end

    raw_index = text.find(term) if term else -1
    if raw_index < start or raw_index >= end:
        raw_index = start + max(0, len(sentence) // 2)
    window_start = max(start, raw_index - 110)
    window_end = min(end, window_start + 240)
    clause_breaks = "，、：；。！？,;!?"
    for position in range(window_start, min(raw_index, len(text))):
        if text[position] in clause_breaks:
            window_start = position + 1
    for position in range(min(end, window_start + 100), window_end):
        if text[position] in clause_breaks:
            window_end = position + 1
    excerpt = text[window_start:window_end].strip()
    return excerpt or sentence[:240].strip(), window_start, window_end


def context_links(connection: sqlite3.Connection, work_id: str, sequence: int) -> dict[str, Any]:
    previous = connection.execute(
        "SELECT id FROM passages WHERE work_id=? AND sequence<? ORDER BY sequence DESC LIMIT 1",
        (work_id, sequence),
    ).fetchone()
    following = connection.execute(
        "SELECT id FROM passages WHERE work_id=? AND sequence>? ORDER BY sequence LIMIT 1",
        (work_id, sequence),
    ).fetchone()
    return {
        "previous_id": previous["id"] if previous else None,
        "next_id": following["id"] if following else None,
        "expand_command": f"context --id {work_id}:{sequence}",
    }


def decorate_payload(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    payload = base_row_payload(row)
    core_quote, quote_start, quote_end = best_sentence(row["text_simplified"], analysis["best_term"])
    payload.update(
        {
            "score": round(float(analysis["score"]), 6),
            "match": {key: value for key, value in analysis.items() if key not in {"score", "useful"}},
            "core_quote": core_quote,
            "core_quote_start": quote_start,
            "core_quote_end": quote_end,
            "core_quote_characters": len(core_quote),
            "full_text_characters": len(row["text_simplified"]),
            "full_text_available": core_quote != row["text_simplified"],
            "context": context_links(connection, row["work_id"], row["sequence"]),
        }
    )
    payload["context"]["expand_command"] = f"python scripts/search.py context --id {row['id']} --before 1 --after 1"
    return payload


def select_results(
    scored: list[tuple[dict[str, Any], sqlite3.Row]],
    args: argparse.Namespace,
) -> tuple[list[tuple[dict[str, Any], sqlite3.Row]], dict[str, int]]:
    selected: list[tuple[dict[str, Any], sqlite3.Row]] = []
    counts = Counter()
    core_count = 0
    extension_count = 0
    per_work: Counter[str] = Counter()
    explicit_author = bool(getattr(args, "author", None))
    tier_order = {"A": 0, "B": 1, "C": 2}
    ranked = sorted(
        scored,
        key=lambda item: (
            0 if item[0].get("preferred_passage") else 1,
            tier_order.get(item[0]["tier"], 9),
            0 if item[1]["layer"] == "core" else 1,
            -item[0]["score"],
        ),
    )
    for analysis, row in ranked:
        if not analysis["useful"]:
            counts["weak_or_fragment"] += 1
            continue
        is_core = row["layer"] == "core"
        if is_core and core_count >= args.limit_core:
            counts["layer_limit"] += 1
            continue
        if not is_core and extension_count >= args.limit_commentary:
            counts["layer_limit"] += 1
            continue
        if is_core and per_work[row["work_id"]] >= 2:
            counts["same_work_limit"] += 1
            continue
        if not is_core and not explicit_author and per_work[row["work_id"]] >= 1:
            counts["same_work_limit"] += 1
            continue
        if any(
            jaccard(normalize(prior[1]["text_simplified"]), normalize(row["text_simplified"])) >= 0.90
            for prior in selected
        ):
            counts["near_duplicate"] += 1
            continue
        selected.append((analysis, row))
        per_work[row["work_id"]] += 1
        core_count += int(is_core)
        extension_count += int(not is_core)
        if len(selected) >= args.limit_total:
            break
    selected.sort(
        key=lambda item: (
            0 if item[0].get("preferred_passage") else 1,
            tier_order.get(item[0]["tier"], 9),
            0 if item[1]["layer"] == "core" else 1,
            -item[0]["score"],
        )
    )
    return selected, dict(counts)


def inferred_route_is_active(route: dict[str, Any]) -> bool:
    return any(route[key] for key in ("target_works", "canons", "work_ids", "authors"))


def search(connection: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    rules = rules_for(args)
    route = infer_route(connection, args.query, rules)
    plan = build_query_plan(connection, args.query, args.terms, route, rules)
    terms = plan["terms"]
    intent = plan["intent"]
    layers = [] if args.layers == "all" else [item.strip() for item in args.layers.split(",") if item.strip()]
    strict_expression = fts_expression(terms)
    broad_expression = fts_expression(terms, broad=True)
    candidate_limit = max(args.candidate_limit, args.limit_total * 20)

    preferred_passage_ids = set(plan["preferred_passage_ids"])
    strict_rows = query_candidates(
        connection, strict_expression, route, args.canon, args.work, layers, args.author, candidate_limit
    )
    scored = score_rows(
        strict_rows, terms, intent, "all-bigrams", "strict", preferred_passage_ids
    )
    fts_fallback = False
    route_fallback = False
    route_conflict = False

    allow_route_fallback = getattr(args, "route_fallback", True)
    explicit_filters = args.canon != "auto" or args.work != "auto" or bool(args.author)
    if (
        allow_route_fallback
        and not explicit_filters
        and inferred_route_is_active(route)
        and bool(plan["matched_expansions"])
        and (
            not has_direct(scored)
            or bool(
                plan["matched_expansions"]
                and terms
                and not has_exact_term(scored, terms[0])
            )
            or bool(
                intent["mode"] == "quote_lookup"
                and terms
                and not has_exact_core(scored, terms[0])
            )
            or bool(
                preferred_passage_ids
                and not has_preferred(scored, preferred_passage_ids)
            )
        )
        and strict_expression
    ):
        fallback_rows = query_candidates(
            connection,
            strict_expression,
            relaxed_route(route),
            "auto",
            "auto",
            layers,
            None,
            candidate_limit,
        )
        fallback_scored = score_rows(
            fallback_rows, terms, intent, "all-bigrams", "relaxed", preferred_passage_ids
        )
        fallback_is_better = has_direct(fallback_scored) and (
            not terms
            or (
                preferred_passage_ids
                and has_preferred(fallback_scored, preferred_passage_ids)
                and not has_preferred(scored, preferred_passage_ids)
            )
            or (
                intent["mode"] == "quote_lookup"
                and has_exact_core(fallback_scored, terms[0])
                and not has_exact_core(scored, terms[0])
            )
            or (
                has_exact_term(fallback_scored, terms[0])
                and not has_exact_term(scored, terms[0])
            )
            or not has_direct(scored)
        )
        if fallback_is_better:
            scored = fallback_scored
            route_fallback = True
            route_conflict = True

    if not has_direct(scored) and broad_expression:
        fts_fallback = True
        active_route = relaxed_route(route) if route_fallback else route
        broad_rows = query_candidates(
            connection,
            broad_expression,
            active_route,
            "auto" if route_fallback else args.canon,
            "auto" if route_fallback else args.work,
            layers,
            None if route_fallback else args.author,
            candidate_limit,
        )
        broad_scored = score_rows(
            broad_rows,
            terms,
            intent,
            "broad-bigrams",
            "relaxed" if route_fallback else "strict",
            preferred_passage_ids,
        )
        if not any(item[0]["useful"] for item in scored):
            scored = broad_scored
        else:
            seen = {item[1]["id"] for item in scored}
            scored.extend(item for item in broad_scored if item[1]["id"] not in seen)
            scored.sort(key=lambda item: (-item[0]["score"], item[1]["work_id"], item[1]["sequence"]))

    if (
        allow_route_fallback
        and not explicit_filters
        and inferred_route_is_active(route)
        and not route_fallback
        and not any(item[0]["useful"] for item in scored)
        and broad_expression
    ):
        relaxed_rows = query_candidates(
            connection,
            broad_expression,
            relaxed_route(route),
            "auto",
            "auto",
            layers,
            None,
            candidate_limit,
        )
        relaxed_scored = score_rows(
            relaxed_rows, terms, intent, "broad-bigrams", "relaxed", preferred_passage_ids
        )
        if any(item[0]["useful"] for item in relaxed_scored):
            scored = relaxed_scored
            route_fallback = True
            route_conflict = True
            fts_fallback = True

    if plan["matched_expansions"] and terms and has_exact_term(scored, terms[0]):
        scored = [
            item
            for item in scored
            if terms[0] in item[0]["matched_terms"]
            or item[1]["id"] in preferred_passage_ids
        ]
    if intent["mode"] == "quote_lookup":
        scored.sort(
            key=lambda item: (
                0 if item[1]["layer"] == "core" else 1,
                -item[0]["score"],
                item[1]["work_id"],
                item[1]["sequence"],
            )
        )
    selected, omitted = select_results(scored, args)
    if intent["scope_too_broad"] and selected:
        representative = next((item for item in selected if item[1]["layer"] == "core"), selected[0])
        selected = [representative]
        omitted["broad_scope_not_displayed"] = max(0, len(scored) - 1)
    results = [decorate_payload(connection, row, analysis) for analysis, row in selected]
    recovered_works = list(dict.fromkeys(item["title"] for item in results))
    no_results = not results
    clarification_required = no_results or intent["scope_too_broad"]
    if no_results:
        clarification_reason = "no-direct-match"
        clarification_prompt = "当前工作底本未检得足够直接且可独立理解的材料，请补充书名、原句片段或一个更具体的关键词。"
    elif intent["scope_too_broad"]:
        clarification_reason = "scope-too-broad"
        clarification_prompt = "问题范围较大；以下只给一条代表性材料。继续研读时请限定篇章、概念或医家。"
    else:
        clarification_reason = ""
        clarification_prompt = ""

    metadata = dict(connection.execute("SELECT key, value FROM schema_info"))
    return {
        "query": args.query,
        "terms": terms,
        "query_plan": plan,
        "route": route,
        "route_resolution": {
            "mode": "relaxed-fallback" if route_fallback else "strict",
            "conflict_detected": route_conflict,
            "requested_aliases": route["matched_aliases"],
            "recovered_works": recovered_works if route_conflict else [],
            "message": (
                "按用户所述书名或医家未检得高质量直接命中，已放宽范围；回答时必须明确提示可能记混。"
                if route_conflict
                else ""
            ),
        },
        "needs_clarification": {
            "required": clarification_required,
            "reason": clarification_reason,
            "prompt": clarification_prompt,
        },
        "quality_policy": {
            "principle": rules.get("policy", "宁缺毋滥"),
            "displayed_results": len(results),
            "omitted_candidates": omitted,
        },
        "fts_fallback_used": fts_fallback,
        "database_build_status": metadata.get("build_status"),
        "quarantined_passages_excluded": int(metadata.get("quarantined_passages_excluded", 0)),
        "results": results,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def select_passage_row(connection: sqlite3.Connection, where: str, parameters: tuple[Any, ...]) -> sqlite3.Row | None:
    return connection.execute(
        f"""
        SELECT p.*, w.title, w.author, w.canon, w.layer, w.relationship_json,
               loc.volume, loc.section, loc.subsection, loc.speaker, loc.speaker_type,
               sp.title_simplified AS source_page_title, sp.title_source AS source_page_title_source,
               sp.revision_id AS source_revision_id
        FROM passages p
        JOIN works w ON w.id=p.work_id
        JOIN locations loc ON loc.id=p.location_id
        JOIN source_pages sp ON sp.id=p.source_page_id
        WHERE {where}
        """,
        parameters,
    ).fetchone()


def get_passage(connection: sqlite3.Connection, passage_id: str) -> dict[str, Any] | None:
    row = select_passage_row(connection, "p.id=?", (passage_id,))
    if not row:
        return None
    payload = base_row_payload(row)
    payload.update(
        {
            "core_quote": row["text_simplified"],
            "core_quote_start": 0,
            "core_quote_end": len(row["text_simplified"]),
            "core_quote_characters": len(row["text_simplified"]),
            "full_text_characters": len(row["text_simplified"]),
            "full_text_available": False,
            "context": context_links(connection, row["work_id"], row["sequence"]),
        }
    )
    payload["context"]["expand_command"] = f"python scripts/search.py context --id {row['id']} --before 1 --after 1"
    return payload


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
    rows = [*prior, *following]
    results: list[dict[str, Any]] = []
    for row in rows:
        payload = base_row_payload(row)
        payload.update(
            {
                "core_quote": row["text_simplified"],
                "core_quote_start": 0,
                "core_quote_end": len(row["text_simplified"]),
                "core_quote_characters": len(row["text_simplified"]),
                "full_text_characters": len(row["text_simplified"]),
                "full_text_available": False,
                "context_role": (
                    "anchor"
                    if row["id"] == passage_id
                    else "before"
                    if row["sequence"] < anchor["sequence"]
                    else "after"
                ),
            }
        )
        results.append(payload)
    return {
        "id": passage_id,
        "work_id": anchor["work_id"],
        "before": before,
        "after": after,
        "results": results,
    }


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
    result.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    subparsers = result.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--terms", help="Comma-separated high-value classic terms")
    search_parser.add_argument("--canon", choices=["auto", "huangdi", "zhongjing", "nanjing", "wenbing"], default="auto")
    search_parser.add_argument("--work", default="auto")
    search_parser.add_argument("--layers", default="all", help="all or comma-separated core,commentary,lineage")
    search_parser.add_argument("--author")
    search_parser.add_argument("--limit-core", type=int, default=2)
    search_parser.add_argument("--limit-commentary", type=int, default=2)
    search_parser.add_argument("--limit-total", type=int, default=4)
    search_parser.add_argument("--candidate-limit", type=int, default=240)
    search_parser.add_argument("--no-route-fallback", dest="route_fallback", action="store_false")
    search_parser.set_defaults(route_fallback=True)

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
