#!/usr/bin/env python3
"""Audit candidate works against Chinese Wikisource without downloading corpus text.

This Phase-0 tool discovers likely title pages, records current revision metadata, and
counts direct/recursive subpages. Its selection is intentionally provisional: a human
must still inspect edition, completeness, transcription quality, and licensing before
source-lock.json is created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_DIR / "sources" / "source-candidates.json"
DEFAULT_OUTPUT = PROJECT_DIR / "sources" / "wikisource-audit.json"
DEFAULT_REPORT = PROJECT_DIR / "docs" / "wikisource-source-audit.md"
DEFAULT_CACHE = PROJECT_DIR / "sources" / "cache" / "wikisource-api"
API_URL = "https://zh.wikisource.org/w/api.php"
USER_AGENT = (
    "tcm-classics-study-source-audit/0.1 "
    "(educational corpus audit; local noncommercial development)"
)

VARIANT_MAP = str.maketrans(
    {
        "註": "注",
        "畧": "略",
        "黃": "黄",
        "內": "内",
        "經": "经",
        "靈": "灵",
        "樞": "枢",
        "傷": "伤",
        "論": "论",
        "條": "条",
        "溫": "温",
        "熱": "热",
        "濕": "湿",
        "時": "时",
        "淺": "浅",
        "廣": "广",
        "補": "补",
        "證": "证",
        "發": "发",
        "類": "类",
        "貫": "贯",
        "難": "难",
        "釋": "释",
        "訂": "订",
        "輯": "辑",
        "醫": "医",
    }
)


def normalized_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(VARIANT_MAP).lower()
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", value)


def cache_path(cache_dir: Path, operation: str, params: dict[str, Any]) -> Path:
    key = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    return cache_dir / f"{operation}-{digest}.json"


class WikisourceClient:
    def __init__(self, cache_dir: Path, delay: float, refresh: bool) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = max(0.0, delay)
        self.refresh = refresh
        self.last_request = 0.0

    def query(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        common = {"format": "json", "formatversion": 2, "maxlag": 5}
        request_params = {**common, **params}
        cached = cache_path(self.cache_dir, operation, request_params)
        if cached.exists() and not self.refresh:
            return json.loads(cached.read_text(encoding="utf-8"))

        for attempt in range(6):
            wait = self.delay - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            url = API_URL + "?" + urllib.parse.urlencode(request_params)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.last_request = time.monotonic()
                if "error" in payload:
                    raise RuntimeError(f"MediaWiki API error: {payload['error']}")
                cached.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                return payload
            except urllib.error.HTTPError as exc:
                self.last_request = time.monotonic()
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 5:
                    raise
                retry_after = exc.headers.get("Retry-After")
                seconds = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1)
                time.sleep(min(seconds, 60.0))
            except (urllib.error.URLError, TimeoutError):
                self.last_request = time.monotonic()
                if attempt == 5:
                    raise
                time.sleep(min(2 ** (attempt + 1), 30.0))
        raise AssertionError("unreachable")

    def open_search(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        payload = self.query(
            "opensearch",
            {
                "action": "opensearch",
                "search": query,
                "namespace": 0,
                "limit": limit,
            },
        )
        titles = payload[1] if len(payload) > 1 else []
        descriptions = payload[2] if len(payload) > 2 else []
        urls = payload[3] if len(payload) > 3 else []
        return [
            {
                "title": title,
                "description": descriptions[index] if index < len(descriptions) else "",
                "url": urls[index] if index < len(urls) else "",
            }
            for index, title in enumerate(titles)
        ]

    def page_info(self, titles: list[str]) -> dict[str, dict[str, Any]]:
        if not titles:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for start in range(0, len(titles), 40):
            batch = titles[start : start + 40]
            payload = self.query(
                "page-info",
                {
                    "action": "query",
                    "prop": "info|revisions",
                    "inprop": "url",
                    "rvprop": "ids|timestamp|size",
                    "redirects": 1,
                    "titles": "|".join(batch),
                },
            )
            batch_info: dict[str, dict[str, Any]] = {}
            for page in payload.get("query", {}).get("pages", []):
                revisions = page.get("revisions", [])
                revision = revisions[0] if revisions else {}
                info = {
                    "page_id": page.get("pageid"),
                    "title": page.get("title"),
                    "full_url": page.get("fullurl"),
                    "page_length": page.get("length"),
                    "latest_revid": page.get("lastrevid") or revision.get("revid"),
                    "revision_timestamp": revision.get("timestamp"),
                    "revision_size": revision.get("size"),
                    "missing": "missing" in page,
                }
                batch_info[page.get("title", "")] = info
                result[page.get("title", "")] = info

            aliases = {
                item["from"]: item["to"]
                for key in ("normalized", "redirects")
                for item in payload.get("query", {}).get(key, [])
            }
            for requested in batch:
                resolved = requested
                seen: set[str] = set()
                while resolved in aliases and resolved not in seen:
                    seen.add(resolved)
                    resolved = aliases[resolved]
                if resolved in batch_info:
                    result[requested] = batch_info[resolved]
        return result

    def subpage_count(self, title: str, *, exact_prefix: bool = False) -> int:
        prefix = title if exact_prefix else title.rstrip("/") + "/"
        count = 0
        continuation: dict[str, Any] = {}
        while True:
            payload = self.query(
                "subpages",
                {
                    "action": "query",
                    "list": "allpages",
                    "apnamespace": 0,
                    "apprefix": prefix,
                    "aplimit": "max",
                    **continuation,
                },
            )
            count += len(payload.get("query", {}).get("allpages", []))
            continuation = payload.get("continue", {})
            if not continuation:
                break
        return count


def candidate_score(query: str, title: str) -> float:
    q = normalized_title(query)
    t = normalized_title(title)
    if not q or not t:
        return 0.0
    score = 0.0
    if q == t:
        score = 100.0
    elif t.startswith(q):
        score = 90.0
    elif q in t:
        score = 78.0
    elif t in q:
        score = 70.0
    else:
        q_chars, t_chars = set(q), set(t)
        score = 60.0 * len(q_chars & t_chars) / max(1, len(q_chars | t_chars))
    if "/" in title:
        score -= 12.0
    suffix = t[len(q) :] if t.startswith(q) else ""
    if suffix in {"序", "略", "校义", "集注"}:
        score -= 20.0
    if any(marker in title for marker in ("總目", "图书集成", "圖書集成", "續文獻通考")):
        score -= 30.0
    return round(max(score, 0.0), 2)


def discover_work(client: WikisourceClient, work: dict[str, Any]) -> dict[str, Any]:
    preferred = work.get("preferred_wikisource_title")
    if preferred:
        selected = {
            "title": preferred,
            "description": "Configured after manual title review",
            "url": "https://zh.wikisource.org/wiki/" + urllib.parse.quote(preferred.replace(" ", "_")),
            "matched_query": "configured-title",
            "score": 100.0,
        }
        return {
            **{key: work[key] for key in ("id", "layer", "canon", "target_works", "author", "title", "relationship")},
            "queries_attempted": [],
            "status": "configured-title",
            "selected_candidate": selected,
            "search_candidates": [selected],
            "subpage_prefix": work.get("subpage_prefix"),
        }

    found: dict[str, dict[str, Any]] = {}
    attempted: list[str] = []
    for query in work["wikisource_queries"]:
        attempted.append(query)
        for result in client.open_search(query):
            score = candidate_score(query, result["title"])
            current = found.get(result["title"])
            item = {**result, "matched_query": query, "score": score}
            if current is None or score > current["score"]:
                found[result["title"]] = item
        best = max((item["score"] for item in found.values()), default=0.0)
        if best >= 100.0:
            break
    ranked = sorted(found.values(), key=lambda item: (-item["score"], item["title"]))
    selected = ranked[0] if ranked else None
    if not selected:
        status = "not-found"
    elif selected["score"] >= 90:
        status = "likely-title-match"
    elif selected["score"] >= 70:
        status = "needs-title-review"
    else:
        status = "weak-match"
    return {
        **{key: work[key] for key in ("id", "layer", "canon", "target_works", "author", "title", "relationship")},
        "queries_attempted": attempted,
        "status": status,
        "selected_candidate": selected,
        "search_candidates": ranked[:10],
    }


def markdown_report(payload: dict[str, Any]) -> str:
    works = payload["works"]
    counts: dict[str, int] = {}
    for work in works:
        counts[work["status"]] = counts.get(work["status"], 0) + 1
    lines = [
        "# 中文维基文库来源自动审计",
        "",
        f"> 生成时间：{payload['generated_at']}  ",
        "> 状态：自动发现结果，尚未等同于人工批准或最终 `source-lock.json`。",
        "",
        "## 摘要",
        "",
        f"- 候选作品：{len(works)} 部",
    ]
    for status in ("configured-title", "likely-title-match", "needs-title-review", "weak-match", "not-found"):
        lines.append(f"- `{status}`：{counts.get(status, 0)}")
    lines.extend(
        [
            "",
            "## 自动发现结果",
            "",
            "| 层 | 计划作品 | 自动匹配页面 | 分数 | 页面字符 | 子页面 | 修订号 | 状态 |",
            "|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for work in works:
        selected = work.get("selected_candidate") or {}
        info = work.get("page_info") or {}
        url = info.get("full_url") or selected.get("url") or ""
        page_title = selected.get("title") or "—"
        linked = f"[{page_title}]({url})" if url else page_title
        lines.append(
            "| {layer} | {title} | {linked} | {score} | {length} | {subs} | {rev} | `{status}` |".format(
                layer=work["layer"],
                title=work["title"].replace("|", "\\|"),
                linked=linked.replace("|", "\\|"),
                score=selected.get("score", "—"),
                length=info.get("page_length") or "—",
                subs=work.get("subpage_count", "未查"),
                rev=info.get("latest_revid") or "—",
                status=work["status"],
            )
        )
    lines.extend(
        [
            "",
            "## 人工审计仍需完成",
            "",
            "- 打开页面核对真实作者、底本、卷数、缺卷和校勘状态。",
            "- 区分目录页、汇总页、四库本/四部丛刊本和单卷子页面。",
            "- 核对正文、原注、新校正、后人按语的说话者边界。",
            "- 核对页面许可和影像/转录状态；公开可见不自动等于可重新打包。",
            "- 为不合格项目评估已获准使用的其他开放古籍库。",
            "- 只有人工通过的页面才写入 `sources/source-lock.json`。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--delay", type=float, default=1.0, help="Minimum seconds between live API calls")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached API responses")
    parser.add_argument("--skip-subpages", action="store_true")
    args = parser.parse_args()

    candidates = json.loads(args.input.read_text(encoding="utf-8"))
    client = WikisourceClient(args.cache_dir, args.delay, args.refresh)
    audits = [discover_work(client, work) for work in candidates["works"]]

    selected_titles = [
        work["selected_candidate"]["title"]
        for work in audits
        if work.get("selected_candidate")
    ]
    page_info = client.page_info(selected_titles)
    for work in audits:
        selected = work.get("selected_candidate")
        if not selected:
            continue
        work["page_info"] = page_info.get(selected["title"], {})
        if not args.skip_subpages:
            configured_prefix = work.get("subpage_prefix")
            prefix = configured_prefix or selected["title"]
            work["subpage_count"] = client.subpage_count(
                prefix, exact_prefix=bool(configured_prefix)
            )

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_candidates": str(args.input.relative_to(PROJECT_DIR)),
        "method": "MediaWiki OpenSearch + page revision metadata + title-prefix subpage count",
        "disclaimer": "Automated title discovery is not final bibliographic or licensing approval.",
        "works": audits,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(markdown_report(payload), encoding="utf-8")
    print(f"Audited {len(audits)} works -> {args.output}")
    print(f"Report -> {args.report}")


if __name__ == "__main__":
    main()
