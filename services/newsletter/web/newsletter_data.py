"""Data access for the standalone newsletter web app."""

from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_ARCHIVE_URL = "https://pkkong.github.io/kpef-newsletter/archive.json"
DEFAULT_CACHE_SECONDS = 300
DEFAULT_SUPABASE_ISSUE_LIMIT = 30
DEFAULT_SUPABASE_ROW_LIMIT = 1200

_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "archive": [],
    "source": "empty",
}


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _clean_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_text(item)
        if text and text not in seen:
            seen.add(text)
            rows.append(text)
    return rows


def _request_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> Any:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _supabase_config() -> tuple[str, str]:
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    public_key = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    return base_url, public_key or ""


def _supabase_headers(public_key: str) -> dict[str, str]:
    return {
        "apikey": public_key,
        "Authorization": f"Bearer {public_key}",
        "Accept": "application/json",
    }


def archive_from_supabase_rows(
    rows: list[dict[str, Any]],
    issue_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    grouped: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

    for issue in issue_rows or []:
        issue_date = _clean_text(issue.get("issue_date"))
        if not issue_date:
            continue
        grouped.setdefault(
            issue_date,
            {
                "reportDate": issue_date,
                "visibleDate": _clean_text(issue.get("visible_date")) or issue_date,
                "basis": _clean_text(issue.get("basis")),
                "articles": [],
            },
        )

    for row in rows:
        issue_date = _clean_text(row.get("issue_date"))
        if not issue_date:
            continue
        entry = grouped.setdefault(
            issue_date,
            {
                "reportDate": issue_date,
                "visibleDate": _clean_text(row.get("visible_date")) or issue_date,
                "basis": _clean_text(row.get("basis")),
                "articles": [],
            },
        )
        rank = row.get("rank")
        try:
            rank_int = int(rank)
        except (TypeError, ValueError):
            rank_int = len(entry["articles"])
        article = {
            "id": _clean_text(row.get("article_id")) or f"article-{issue_date}-{rank_int}",
            "rank": rank_int,
            "section": _clean_text(row.get("section")) or "Market",
            "subCategory": _clean_text(row.get("sub_category")),
            "rawSection": _clean_text(row.get("raw_section")),
            "title": _clean_text(row.get("title")),
            "source": _clean_text(row.get("publisher")),
            "sourceIconUrl": _clean_text(row.get("source_icon_url")),
            "sourceIconStyle": _clean_text(row.get("source_icon_style")),
            "url": _clean_text(row.get("source_url")),
            "summaryText": _clean_text(row.get("summary_text")),
            "summaryLines": _clean_list(row.get("summary_lines")),
            "tagVersion": _clean_text(row.get("tag_version")),
            "sectionOrder": row.get("section_order") or 999,
            "gpNames": _clean_list(row.get("gp_names")),
            "lpNames": _clean_list(row.get("lp_names")),
            "searchTerms": _clean_list(row.get("search_terms")),
        }
        if article["title"] and article["url"]:
            entry["articles"].append(article)
    for entry in grouped.values():
        entry["articles"].sort(key=lambda item: int(item.get("rank") or 0))
    return list(grouped.values())


def fetch_supabase_issues(limit: int | None = None) -> list[dict[str, Any]]:
    base_url, public_key = _supabase_config()
    if not base_url or not public_key:
        return []
    issue_limit = limit or int(
        os.environ.get("NEWSLETTER_SUPABASE_ISSUE_LIMIT", str(DEFAULT_SUPABASE_ISSUE_LIMIT))
    )
    query = urlencode(
        {
            "select": "issue_date,visible_date,basis,article_count",
            "status": "eq.published",
            "order": "issue_date.desc",
            "limit": str(issue_limit),
        }
    )
    url = f"{base_url}/rest/v1/newsletter_issues?{query}"
    rows = _request_json(url, headers=_supabase_headers(public_key))
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def fetch_supabase_archive(limit: int | None = None) -> list[dict[str, Any]]:
    base_url, public_key = _supabase_config()
    if not base_url or not public_key:
        return []
    issue_rows = fetch_supabase_issues()
    row_limit = limit or int(os.environ.get("NEWSLETTER_SUPABASE_ROW_LIMIT", str(DEFAULT_SUPABASE_ROW_LIMIT)))
    query = urlencode(
        {
            "select": "*",
            "order": "issue_date.desc,rank.asc",
            "limit": str(row_limit),
        }
    )
    url = f"{base_url}/rest/v1/newsletter_public_issue_articles?{query}"
    rows = _request_json(
        url,
        headers=_supabase_headers(public_key),
    )
    if not isinstance(rows, list):
        return []
    return archive_from_supabase_rows([row for row in rows if isinstance(row, dict)], issue_rows)


def fetch_archive_url() -> list[dict[str, Any]]:
    archive_url = os.environ.get("NEWSLETTER_ARCHIVE_URL", DEFAULT_ARCHIVE_URL)
    data = _request_json(
        archive_url,
        headers={"User-Agent": "kpef-newsletter-vercel/1.0"},
    )
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def load_archive(force_refresh: bool = False) -> tuple[list[dict[str, Any]], str]:
    now = time.time()
    if not force_refresh and now < float(_CACHE.get("expires_at") or 0):
        return list(_CACHE["archive"]), str(_CACHE["source"])

    cache_seconds = int(os.environ.get("NEWSLETTER_CACHE_SECONDS", str(DEFAULT_CACHE_SECONDS)))
    source = "supabase"
    try:
        archive = fetch_supabase_archive()
        if not archive:
            source = "archive"
            archive = fetch_archive_url()
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        source = "archive"
        archive = fetch_archive_url()

    _CACHE["archive"] = archive
    _CACHE["source"] = source
    _CACHE["expires_at"] = now + max(cache_seconds, 30)
    return list(archive), source


def select_issue(archive: list[dict[str, Any]], issue_date: str = "") -> dict[str, Any]:
    if issue_date:
        for issue in archive:
            if issue.get("reportDate") == issue_date:
                return issue
    return archive[0] if archive else {"reportDate": "", "visibleDate": "", "articles": []}


def filter_articles(issue: dict[str, Any], query: str = "") -> list[dict[str, Any]]:
    articles = [row for row in issue.get("articles") or [] if isinstance(row, dict)]
    needle = _clean_text(query).lower()
    if not needle:
        return articles
    filtered: list[dict[str, Any]] = []
    for article in articles:
        haystack = " ".join(
            [
                _clean_text(article.get("title")),
                _clean_text(article.get("source")),
                _clean_text(article.get("section")),
                _clean_text(article.get("subCategory")),
                _clean_text(article.get("summaryText")),
                " ".join(_clean_list(article.get("gpNames"))),
                " ".join(_clean_list(article.get("lpNames"))),
                " ".join(_clean_list(article.get("searchTerms"))),
            ]
        ).lower()
        if needle in haystack:
            filtered.append(article)
    return filtered


def grouped_sections(articles: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: "OrderedDict[str, list[dict[str, Any]]]" = OrderedDict()
    for article in articles:
        section = _clean_text(article.get("section")) or "Market"
        grouped.setdefault(section, []).append(article)
    return list(grouped.items())
