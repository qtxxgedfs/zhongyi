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
    "A": "正文命中检索词（不等于整问已获支持）",
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
    works = connection.execute("SELECT id, title, author, layer FROM works").fetchall()
    route.update({"author_groups": [], "title_work_ids": [], "excluded_work_ids": [],
                  "hard_scope": False})
    # Longest source names consume their spans before embedded canon names.
    source_aliases = [dict(item) for item in aliases(connection) if item["kind"] != "term"]
    for work in works:
        if work["layer"] == "core":
            continue
        names = [work["title"].strip("《》")]
        names.extend(rules.get("work_title_aliases", {}).get(work["id"], []))
        for name in names:
            source_aliases.append({"alias": name, "kind": "title", "work_id": work["id"],
                                   "canonical": work["title"], "target_work": None, "canon": None})
    for author_route in rules.get("author_routes", []):
        for name in author_route["aliases"]:
            source_aliases.append({"alias": name, "kind": "author", "work_id": None,
                                   "canonical": author_route["canonical"],
                                   "target_work": None, "canon": None})
    occupied: set[int] = set()
    groups: dict[str, dict[str, Any]] = {}
    for item in sorted(source_aliases, key=lambda item: -len(normalize(item["alias"]))):
        alias = normalize(item["alias"])
        if not alias:
            continue
        for match in re.finditer(re.escape(alias), normalized):
            span = set(range(match.start(), match.end()))
            if span & occupied:
                continue
            occupied.update(span)
            route["matched_aliases"].append(item["alias"])
            excluded = bool(re.search(r"(?:不看|不查|不要|排除|不包括|不含)$", normalized[:match.start()]))
            ids = ([item["work_id"]] if item.get("work_id") else
                   [work["id"] for work in works if normalize(item["canonical"]) in normalize(work["author"])])
            if excluded:
                if item.get("target_work"):
                    ids = [row[0] for row in connection.execute(
                        "SELECT work_id FROM work_targets WHERE target_work=?", (item["target_work"],))]
                route["excluded_work_ids"].extend(ids)
                route["hard_scope"] = True
                continue
            if item["kind"] == "author":
                group = groups.setdefault(item["canonical"], {"label": item["canonical"], "work_ids": []})
                group["work_ids"].extend(ids)
            elif item["kind"] == "title":
                route["title_work_ids"].extend(ids)
            if item.get("target_work"):
                route["target_works"].append(item["target_work"])
            if item.get("canon"):
                route["canons"].append(item["canon"])
    for group in groups.values():
        group["work_ids"] = list(dict.fromkeys(group["work_ids"]))
        route["author_groups"].append(group)
        route["work_ids"].extend(group["work_ids"])
    for key in ("target_works", "canons", "work_ids", "title_work_ids", "excluded_work_ids", "matched_aliases"):
        route[key] = list(dict.fromkeys(route[key]))
    route["hard_scope"] = route["hard_scope"] or any(cue in normalized for cue in (
        "只看", "只查", "只在", "仅看", "仅查", "仅在", "限定", "不要其他", "不要扩展", "不扩展"))
    return route


def infer_intent(query: str, route: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize(query)
    if any(normalize(cue) in normalized for cue in ("前后文", "上下文", "上一段", "下一段", "展开")):
        mode = "context"
    elif any(normalize(cue) in normalized for cue in ("比较", "异同", "不同", "分歧", "区别", "对照", "分别")) or len(route.get("author_groups", [])) > 1 or len(route["target_works"]) > 1 or len(route.get("title_work_ids", [])) > 1:
        mode = "compare"
    elif route["work_ids"] or route["authors"] or route.get("title_work_ids"):
        mode = "physician"
    elif any(normalize(cue) in normalized for cue in ("原文", "原句", "出处", "哪一篇", "在哪里", "怎么说")):
        mode = "quote_lookup"
    elif any(normalize(cue) in normalized for cue in ("注释", "注家", "医家", "解释")):
        mode = "physician"
    else:
        mode = "study"
    broad_hits = [item for item in rules.get("broad_concepts", []) if normalize(item) in normalized]
    has_scope = bool(route["target_works"] or route["work_ids"] or route["authors"] or route.get("title_work_ids"))
    scope_too_broad = bool(broad_hits and not has_scope and mode == "study")
    return {
        "mode": mode,
        "scope_too_broad": scope_too_broad,
        "broad_concepts": broad_hits,
        "source_lookup": any(cue in normalized for cue in (
            "我记得", "记不清", "好像", "是不是", "出自", "出处", "原话", "原句", "那句"))
            or ("原文" in normalized and not (route["work_ids"] or route.get("title_work_ids"))),
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
    matched_triggers: list[str] = []
    quoted_terms: list[str] = []
    focus_terms: list[str] = []
    if raw_terms:
        for value in raw_terms.split(","):
            _add_term(terms, term_sources, value.strip(), "explicit", alias_rows)
    else:
        normalized_query = normalize(query)
        for quoted in QUOTED_RE.findall(query):
            _add_term(quoted_terms, [], quoted, "quoted", alias_rows)
            _add_term(terms, term_sources, quoted, "quoted", alias_rows)
        for expansion in rules.get("expansions", []):
            if any(normalize(trigger) in normalized_query for trigger in expansion.get("triggers", [])):
                matched_expansions.append(expansion["id"])
                matched_triggers.extend(trigger for trigger in expansion.get("triggers", [])
                                        if normalize(trigger) in normalized_query)
                keep_scope_warning = keep_scope_warning or bool(expansion.get("keep_scope_warning"))
                for passage_id in expansion.get("preferred_passage_ids", []):
                    if passage_id not in preferred_passage_ids:
                        preferred_passage_ids.append(passage_id)
                for term in expansion.get("terms", []):
                    _add_term(terms, term_sources, term, f"expansion:{expansion['id']}", alias_rows)

        if matched_expansions and not keep_scope_warning:
            intent["scope_too_broad"] = False
        residual = normalized_query
        removable = [*route["matched_aliases"], *matched_triggers, *quoted_terms]
        for author_route in rules.get("author_routes", []):
            removable.extend(author_route.get("aliases", []))
        removable.extend(rules.get("task_phrases", []))
        removable.extend(rules.get("filler_phrases", []))
        for phrase in sorted({normalize(item) for item in removable if item}, key=len, reverse=True):
            residual = residual.replace(phrase, "|")
        active_focus_rules = [focus for focus in rules.get("focus_rules", [])
                              if any(normalize(trigger) in normalized_query for trigger in focus["triggers"])]
        for focus in active_focus_rules:
            for trigger in focus["triggers"]:
                residual = residual.replace(normalize(trigger), "|")
        # Keep content words instead of discarding the rest of an expanded question.
        fragments = re.split(r"[|的与和及对里呢吗]|(?:请|比较|解释|怎样谈|如何谈|有什么|不要其他医家|不看|只看|只查|不要|原因|服后|治疗)", residual)
        for fragment in fragments:
            fragment = fragment.strip()
            if not 2 <= len(fragment) <= 18:
                continue
            if matched_expansions:
                # A residual must have indexed support; conversational filler is not a focus.
                rows = connection.execute(
                    "SELECT p.text_simplified FROM passage_fts JOIN passages p ON p.rowid=passage_fts.rowid "
                    "WHERE passage_fts MATCH ? LIMIT 40", (fts_expression([fragment]),)).fetchall()
                if not any(normalize(fragment) in normalize(row[0]) for row in rows):
                    continue
                _add_term(focus_terms, [], fragment, "focus", alias_rows)
            _add_term(terms, term_sources, fragment, "query", alias_rows)
        for focus in rules.get("focus_rules", []):
            if any(normalize(trigger) in normalized_query for trigger in focus["triggers"]):
                for term in focus["terms"]:
                    normalized_term = apply_term_aliases(term, alias_rows)
                    if normalized_term not in focus_terms:
                        focus_terms.append(normalized_term)
                    _add_term(terms, term_sources, term, "focus", alias_rows)
        if not terms:
            residual = residual.replace("|", "")
            if residual:
                _add_term(terms, term_sources, residual[:32], "query-long", alias_rows)

    topic_terms = [item["term"] for item in term_sources if item["source"].startswith("expansion:")]
    if not topic_terms:
        topic_terms = list(quoted_terms or [item["term"] for item in term_sources if item["source"] != "focus"] or terms)
    intent["quoted_terms"] = quoted_terms
    intent["focus_terms"] = focus_terms
    intent["topic_terms"] = topic_terms
    if quoted_terms or focus_terms:
        preferred_passage_ids = []
    return {
        "intent": intent,
        "terms": terms,
        "term_sources": term_sources,
        "matched_expansions": matched_expansions,
        "preferred_passage_ids": preferred_passage_ids,
        "explicit_terms_supplied": bool(raw_terms),
        "quoted_terms": quoted_terms,
        "focus_terms": focus_terms,
        "topic_terms": topic_terms,
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
    if target_work and target_work.startswith(("core-", "commentary-", "lineage-")):
        conditions.append("w.id = ?")
        parameters.append(target_work)
        target_works = []
    else:
        target_works = [target_work] if target_work else route["target_works"]
    source_union = (route.get("compare_sources") and work == "auto")
    if source_union:
        ids = route.get("title_work_ids", []) + ["core-" + target for target in target_works]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conditions.append(f"w.id IN ({placeholders})")
            parameters.extend(ids)
        target_works = []
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
    for key, operator in (("title_work_ids", "IN"), ("excluded_work_ids", "NOT IN")):
        if key == "title_work_ids" and source_union:
            continue
        if route.get(key):
            placeholders = ",".join("?" for _ in route[key])
            conditions.append(f"w.id {operator} ({placeholders})")
            parameters.extend(route[key])
    if route["authors"]:
        conditions.append("(" + " OR ".join("w.author LIKE ?" for _ in route["authors"]) + ")")
        parameters.extend(f"%{item}%" for item in route["authors"])
    if layers:
        placeholders = ",".join("?" for _ in layers)
        conditions.append(f"w.layer IN ({placeholders})")
        parameters.extend(layers)
    if author:
        author_route = infer_route(connection, author)
        if author_route["work_ids"]:
            placeholders = ",".join("?" for _ in author_route["work_ids"])
            conditions.append(f"w.id IN ({placeholders})")
            parameters.extend(author_route["work_ids"])
        else:
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
        "title_work_ids": [],
        "author_groups": [],
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
    body_tokens = set(bigrams(body))
    location_tokens = set(bigrams(location_text))
    for term in terms:
        tokens = set(bigrams(term))
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
    quoted = intent.get("quoted_terms", [])
    focus = intent.get("focus_terms", [])
    topics = intent.get("topic_terms", [])
    quoted_matches = [term for term in quoted if term in body]
    focus_matches = [term for term in focus if term in body]
    topic_matches = [term for term in topics if term in body or term in location_text]
    useful = tier in {"A", "B", "C"} and reason is None
    if quoted and (not quoted_matches or (intent["mode"] != "compare" and len(quoted_matches) != len(quoted))):
        useful = False
        reason = reason or "quoted-phrase-not-found"
    if focus and (not focus_matches or not topic_matches):
        useful = False
        reason = reason or "focus-not-supported"
    score += 120 * len(quoted_matches) + 24 * len(focus_matches) + 12 * len(topic_matches)
    if quoted_matches or focus_matches:
        best = {**best, "term": (quoted_matches or focus_matches)[0]}
    return {
        "tier": tier,
        "label": MATCH_TIER_LABELS.get(tier, "弱相关候选"),
        "best_term": best["term"],
        "matched_terms": [item["term"] for item in term_details if item["exact_body"]],
        "matched_location_terms": [item["term"] for item in term_details if item["exact_location"]],
        "quoted_matches": quoted_matches,
        "focus_matches": focus_matches,
        "quote_context_terms": topics if focus and not quoted else [],
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
    return any(item[0]["useful"] and item[0]["tier"] in {"A", "B"}
               and item[1]["speaker_type"] != "quoted_core" for item in scored)


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


def best_sentence(text: str, term: str, companion_terms: list[str] | None = None) -> tuple[str, int, int]:
    if not text:
        return "", 0, 0
    spans = [(match.group(0), match.start(), match.end()) for match in SENTENCE_RE.finditer(text)]
    if not spans:
        spans = [(text, 0, len(text))]
    normalized_term = normalize(term)
    term_tokens = set(bigrams(normalized_term))

    def sentence_score(item: tuple[str, int, int]) -> tuple:
        sentence = normalize(item[0])
        exact = int(bool(normalized_term and normalized_term in sentence))
        tokens = set(bigrams(sentence))
        coverage = len(tokens & term_tokens) / len(term_tokens) if term_tokens else 0.0
        companion = int(any(word in sentence for word in (companion_terms or [])))
        return int(exact and companion), companion, exact, coverage, -len(item[0])

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
    core_quote, quote_start, quote_end = best_sentence(
        row["text_simplified"], analysis["best_term"], analysis.get("quote_context_terms"))
    # Strip-aware offsets must identify the actual continuous database substring.
    quote_start = row["text_simplified"].find(core_quote, quote_start)
    quote_end = quote_start + len(core_quote)
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


def matches_group(item: Any, analysis: dict[str, Any], group: dict[str, Any]) -> bool:
    if group.get("work_ids"):
        return item["work_id"] in group["work_ids"] and (
            group.get("kind") != "author" or item["speaker_type"] != "quoted_core")
    return group.get("term") in analysis.get("matched_terms", [])


def comparison_groups(connection, route: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    groups = [{**group, "kind": "author"} for group in route.get("author_groups", [])]
    if groups:
        return groups
    if plan["intent"]["mode"] != "compare":
        return []
    for work_id in route.get("title_work_ids", []):
        title = connection.execute("SELECT title FROM works WHERE id=?", (work_id,)).fetchone()[0]
        groups.append({"label": title, "kind": "work", "work_ids": [work_id]})
    for work in route["target_works"]:
        title = connection.execute("SELECT title FROM works WHERE id=?", ("core-" + work,)).fetchone()[0]
        groups.append({"label": title, "kind": "work", "work_ids": ["core-" + work]})
    if not groups:
        comparison_terms = (plan["quoted_terms"] or
                            (plan["focus_terms"] if len(plan["focus_terms"]) > 1 else plan["topic_terms"]))
        groups = [{"label": term, "kind": "term", "term": term} for term in comparison_terms]
    return groups


def coverage_report(groups, scored, selected) -> list[dict[str, Any]]:
    return [{**group, "status": (
        "matched" if any(matches_group(row, analysis, group) for analysis, row in selected) else
        "not-displayed" if any(analysis["useful"] and matches_group(row, analysis, group)
                               for analysis, row in scored) else "not-found")}
            for group in groups]


def select_results(
    scored: list[tuple[dict[str, Any], sqlite3.Row]],
    args: argparse.Namespace,
    groups: list[dict[str, Any]] | None = None,
    scoped_author: bool = False,
) -> tuple[list[tuple[dict[str, Any], sqlite3.Row]], dict[str, int]]:
    selected: list[tuple[dict[str, Any], sqlite3.Row]] = []
    counts = Counter()
    per_work: Counter[str] = Counter()
    groups = groups or []
    covered: set[int] = set()
    tier_order = {"A": 0, "B": 1, "C": 2}
    ranked = sorted(scored, key=lambda item: (
        -len(item[0].get("quoted_matches", [])), -len(item[0].get("focus_matches", [])),
        0 if item[0].get("preferred_passage") else 1,
        tier_order.get(item[0]["tier"], 9), 0 if item[1]["layer"] == "core" else 1,
        -item[0]["score"], item[1]["id"]))
    commentary_limit = args.limit_commentary
    if commentary_limit > 0 and len(groups) > 1:
        commentary_limit = max(commentary_limit, sum(group["kind"] == "author" for group in groups))
    while ranked and len(selected) < args.limit_total:
        # Reserve representation for every requested comparison object before filling extras.
        index = next((i for i, (analysis, row) in enumerate(ranked)
                      if analysis["useful"] and any(j not in covered and matches_group(row, analysis, group)
                                                   for j, group in enumerate(groups))), 0)
        analysis, row = ranked.pop(index)
        if not analysis["useful"]:
            counts["weak_or_fragment"] += 1
            continue
        if row["speaker_type"] == "quoted_core":
            counts["quoted_core"] += 1
            continue
        is_core = row["layer"] == "core"
        layer_count = sum((prior[1]["layer"] == "core") == is_core for prior in selected)
        if layer_count >= (args.limit_core if is_core else commentary_limit):
            counts["layer_limit"] += 1
            continue
        per_work_limit = 2 if is_core or scoped_author or args.author else 1
        if per_work[row["work_id"]] >= per_work_limit:
            counts["same_work_limit"] += 1
            continue
        new_groups = {j for j, group in enumerate(groups) if matches_group(row, analysis, group)} - covered
        if not new_groups and any(
            jaccard(normalize(prior[1]["text_simplified"]), normalize(row["text_simplified"])) >= 0.90
            for prior in selected
        ):
            counts["near_duplicate"] += 1
            continue
        selected.append((analysis, row))
        per_work[row["work_id"]] += 1
        covered.update(new_groups)
    return selected, dict(counts)


def inferred_route_is_active(route: dict[str, Any]) -> bool:
    return any(route.get(key) for key in ("target_works", "canons", "work_ids", "authors", "title_work_ids"))


def search(connection: sqlite3.Connection, args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    rules = rules_for(args)
    route = infer_route(connection, args.query, rules)
    if args.author:
        explicit_route = infer_route(connection, args.author, rules)
        route["work_ids"] = explicit_route["work_ids"]
        route["author_groups"] = explicit_route["author_groups"]
        route["authors"] = []
    plan = build_query_plan(connection, args.query, args.terms, route, rules)
    terms = plan["terms"]
    intent = plan["intent"]
    route["compare_sources"] = bool(intent["mode"] == "compare" and route["title_work_ids"]
                                    and route["target_works"] and not route["author_groups"])
    layers = [] if args.layers == "all" else [item.strip() for item in args.layers.split(",") if item.strip()]
    if not layers and any(cue in normalize(args.query) for cue in ("只看原典", "仅看原典", "只查原典")):
        layers = ["core"]
    strict_expression = fts_expression(terms)
    broad_expression = fts_expression(terms, broad=True)
    candidate_limit = max(args.candidate_limit, args.limit_total * 20)

    preferred_passage_ids = set(plan["preferred_passage_ids"])
    groups = comparison_groups(connection, route, plan)
    fts_fallback = False

    def sufficient(items, scoped=True):
        if scoped and route["target_works"] and not (route["work_ids"] or route["title_work_ids"]):
            # An associated commentary is not proof that the named original contains a phrase.
            items = [item for item in items if item[1]["work_id"] in
                     {"core-" + work for work in route["target_works"]}]
        if not has_direct(items):
            return False
        # A paraphrase's main phrase must be supported; a generic synonym alone
        # does not establish the remembered wording. Never inspect preferred IDs here.
        if plan["matched_expansions"] and terms and intent["mode"] != "compare" and not plan["focus_terms"]:
            return any(a["useful"] and terms[0] in a["matched_terms"] + a["matched_location_terms"]
                       and r["speaker_type"] != "quoted_core" for a, r in items)
        return True

    def retrieve(active_route, scope, expression, channel, scoped=True):
        rows = query_candidates(connection, expression, active_route,
                                args.canon if scoped else "auto", args.work if scoped else "auto",
                                layers, args.author if scoped else None, candidate_limit)
        items = score_rows(rows, terms, intent, channel, scope, preferred_passage_ids)
        if plan["matched_expansions"] and terms and intent["mode"] != "compare" and not plan["focus_terms"]:
            for analysis, _ in items:
                if terms[0] not in analysis["matched_terms"] + analysis["matched_location_terms"]:
                    analysis["useful"] = False
                    analysis["suppression_reason"] = "main-phrase-not-supported"
        return items

    def merge(left, right):
        seen = {row["id"] for _, row in left}
        return left + [item for item in right if item[1]["id"] not in seen]

    scored = retrieve(route, "strict", strict_expression, "all-bigrams")
    for term in plan["quoted_terms"] + plan["focus_terms"]:
        if len(term) >= 2:
            expression = fts_expression([term])
            if plan["focus_terms"] and plan["topic_terms"]:
                expression = "(" + expression + ") AND (" + fts_expression(plan["topic_terms"]) + ")"
            scored = merge(scored, retrieve(route, "strict", expression, "query-detail"))
    # Per-object indexed recall prevents a prolific author/work from exhausting the pool.
    if len(groups) > 1:
        for group in groups:
            group_route = route
            expression = strict_expression
            if group.get("work_ids"):
                group_route = {**route, "work_ids": group["work_ids"]}
            else:
                expression = fts_expression([group["term"]])
            scored = merge(scored, retrieve(group_route, "strict", expression, "comparison-object"))
    if not sufficient(scored) and broad_expression:
        fts_fallback = True
        scored = merge(scored, retrieve(route, "strict", broad_expression, "broad-bigrams"))

    strict_scored = scored
    alternative_scored = []
    route_fallback = False
    explicit_filters = args.canon != "auto" or args.work != "auto" or bool(args.author)
    can_expand = (getattr(args, "route_fallback", True) and not explicit_filters
                  and not route.get("hard_scope") and inferred_route_is_active(route))
    if can_expand and not sufficient(scored):
        fallback = retrieve(relaxed_route(route), "alternative", strict_expression, "all-bigrams", False)
        if not sufficient(fallback, False) and broad_expression:
            fts_fallback = True
            fallback = merge(fallback, retrieve(relaxed_route(route), "alternative", broad_expression,
                                                "broad-bigrams", False))
        if sufficient(fallback, False):
            strict_ids = {row["id"] for _, row in scored}
            alternative_scored = [item for item in fallback if item[1]["id"] not in strict_ids]
            # Only source-identification questions may promote outside-scope results.
            if sufficient(alternative_scored, False) and intent["source_lookup"] and intent["mode"] != "compare":
                scored = alternative_scored
                route_fallback = True
    selected, omitted = select_results(scored, args, [] if route_fallback else groups,
                                       bool(route["author_groups"] or route["title_work_ids"]) and not route_fallback)
    alternatives, _ = select_results(alternative_scored, args)
    if route_fallback:
        alternatives = []
    coverage = coverage_report(groups, strict_scored, [] if route_fallback else selected)
    if intent["scope_too_broad"] and selected:
        representative = next((item for item in selected if item[1]["layer"] == "core"), selected[0])
        selected = [representative]
        omitted["broad_scope_not_displayed"] = max(0, len(scored) - 1)
    results = [decorate_payload(connection, row, analysis) for analysis, row in selected]
    alternative_results = [decorate_payload(connection, row, analysis) for analysis, row in alternatives[:2]]
    recovered_works = list(dict.fromkeys(item["title"] for item in (results if route_fallback else alternative_results)))
    no_results = not results
    missing_groups = [group["label"] for group in coverage if group["status"] != "matched"]
    clarification_required = no_results or intent["scope_too_broad"] or (len(groups) > 1 and bool(missing_groups))
    if no_results:
        limited = any(a["useful"] and r["speaker_type"] != "quoted_core" for a, r in scored)
        quoted_only = any(a["useful"] and r["speaker_type"] == "quoted_core" for a, r in strict_scored)
        clarification_reason = "quoted-core-only" if quoted_only else "no-direct-match"
        clarification_prompt = ("指定范围仅检得经文转引，尚无足够直接的医家注文。" if quoted_only else
                                "当前指定范围未检得足够直接且可独立理解的材料，请补充原句片段或具体关键词。")
        if limited:
            clarification_reason = "selection-limited"
            clarification_prompt = "已检得相关材料，但本次条数限制未允许展示；请调整结果条数，不代表未检得。"
    elif alternative_results and not sufficient(strict_scored):
        clarification_required = True
        clarification_reason = "source-not-supported"
        clarification_prompt = "指定范围的材料尚不足以支持所询原句；范围外结果仅作备选，不能混同来源。"
    elif missing_groups and len(groups) > 1:
        clarification_reason = "incomplete-comparison"
        clarification_prompt = "以下对象尚无可展示的直接材料：" + "、".join(missing_groups) + "；不能据此完成全部比较。"
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
            "conflict_detected": route_fallback,
            "alternatives_available": bool(alternative_results),
            "hard_scope": bool(route.get("hard_scope") or explicit_filters),
            "requested_aliases": route["matched_aliases"],
            "recovered_works": recovered_works,
            "message": (
                "指定范围未检得所询内容的足够直接支持；范围外检得" + "、".join(recovered_works)
                + ("，以下作为出处核对结果，不归属于原指定来源。" if route_fallback else
                   "，仅列为备选，不代表指定医家的观点。")
                if recovered_works else ""
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
        "scope_coverage": coverage,
        "alternative_results": alternative_results,
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
