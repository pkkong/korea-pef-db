"""Data access for the standalone newsletter web app."""

from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_ARCHIVE_URL = "https://pkkong.github.io/kpef-newsletter/archive.json"
DEFAULT_RAW_ARCHIVE_URL = "https://raw.githubusercontent.com/pkkong/kpef-newsletter/gh-pages/archive.json"
DEFAULT_CACHE_SECONDS = 300
DEFAULT_STALE_IF_ERROR_SECONDS = 3600
DEFAULT_FALLBACK_BUDGET_SECONDS = 4
DEFAULT_SUPABASE_ISSUE_LIMIT = 30
DEFAULT_SUPABASE_ROW_LIMIT = 1200

_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "archive": [],
    "source": "empty",
    "last_success_at": None,
}


class NewsletterDataError(RuntimeError):
    """No upstream or recent last-good archive can serve this request."""


UPSTREAM_ERRORS = (OSError, ValueError, UnicodeDecodeError)


def archive_cache_status() -> dict[str, Any]:
    last_success = _CACHE.get("last_success_at")
    return {
        "last_success_at": (
            datetime.fromtimestamp(float(last_success), timezone.utc).isoformat(timespec="seconds")
            if last_success is not None else None
        ),
        "cache_age_seconds": max(0, int(time.time() - float(last_success))) if last_success is not None else None,
        "last_success_source": _CACHE.get("source", "empty"),
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


def _clean_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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

    # Issue rows are the date-navigation source of truth. Article rows are an
    # inner join view, so dates with zero articles would otherwise disappear.
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
                "articleCount": _clean_int(issue.get("article_count"), 0),
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
                "articleCount": 0,
                "articles": [],
            },
        )
        rank_int = _clean_int(row.get("rank"), len(entry["articles"]))
        section_order = _clean_int(row.get("section_order"), 999)
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
            "sectionOrder": section_order,
            "gpNames": _clean_list(row.get("gp_names")),
            "lpNames": _clean_list(row.get("lp_names")),
            "searchTerms": _clean_list(row.get("search_terms")),
        }
        if article["title"] and article["url"]:
            entry["articles"].append(article)
    for entry in grouped.values():
        entry["articles"].sort(key=lambda item: int(item.get("rank") or 0))
        entry["articleCount"] = len(entry["articles"])
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


def _filter_article_rows_to_issues(
    rows: list[dict[str, Any]],
    issue_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not issue_rows:
        return rows
    issue_dates = {_clean_text(row.get("issue_date")) for row in issue_rows}
    return [row for row in rows if _clean_text(row.get("issue_date")) in issue_dates]


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
    article_rows = [row for row in rows if isinstance(row, dict)]
    article_rows = _filter_article_rows_to_issues(article_rows, issue_rows)
    return archive_from_supabase_rows(article_rows, issue_rows)


def fetch_archive_url() -> list[dict[str, Any]]:
    archive_url = os.environ.get("NEWSLETTER_ARCHIVE_URL", DEFAULT_ARCHIVE_URL)
    return fetch_archive_url_from(archive_url)


def fetch_archive_url_from(archive_url: str, timeout: float = 20) -> list[dict[str, Any]]:
    data = _request_json(
        archive_url,
        headers={"User-Agent": "kpef-newsletter-vercel/1.0"},
        timeout=timeout,
    )
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def archive_fallback_urls() -> list[str]:
    urls = [
        os.environ.get("NEWSLETTER_ARCHIVE_URL", DEFAULT_ARCHIVE_URL),
        os.environ.get("NEWSLETTER_RAW_ARCHIVE_URL", DEFAULT_RAW_ARCHIVE_URL),
    ]
    deduped: list[str] = []
    for url in urls:
        clean_url = _clean_text(url)
        if clean_url and clean_url not in deduped:
            deduped.append(clean_url)
    return deduped


def archive_latest_status(archive: list[dict[str, Any]]) -> tuple[str, int]:
    for issue in archive:
        report_date = _clean_text(issue.get("reportDate"))
        articles = issue.get("articles") or []
        article_count = len(articles) if isinstance(articles, list) else _clean_int(issue.get("articleCount"), 0)
        if report_date:
            return report_date, article_count
    return "", 0


def archive_is_newer(candidate: list[dict[str, Any]], current: list[dict[str, Any]]) -> bool:
    candidate_date, candidate_count = archive_latest_status(candidate)
    current_date, current_count = archive_latest_status(current)
    if candidate_count <= 0:
        return False
    if not current_date:
        return True
    if candidate_date > current_date:
        return True
    # A corrected issue can contain fewer articles. A cached mirror with more
    # rows is not a newer version and must not replace the published DB issue.
    return False


def fetch_best_archive_fallback(current_archive: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    best_archive: list[dict[str, Any]] = []
    had_response = False
    budget = max(0.1, float(os.environ.get("NEWSLETTER_FALLBACK_BUDGET_SECONDS", str(DEFAULT_FALLBACK_BUDGET_SECONDS))))
    deadline = time.monotonic() + budget
    for url in archive_fallback_urls():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            candidate = fetch_archive_url_from(url, timeout=min(remaining, budget / 2))
        except UPSTREAM_ERRORS:
            continue
        had_response = True
        # A published date with no articles is still a valid issue on cold start.
        if (candidate and not current_archive or archive_is_newer(candidate, current_archive)) and (
            not best_archive or archive_is_newer(candidate, best_archive)
        ):
            best_archive = candidate
    return best_archive, "archive_fallback" if best_archive else ("archive" if had_response and not current_archive else "")


def load_archive(force_refresh: bool = False) -> tuple[list[dict[str, Any]], str]:
    now = time.time()
    if not force_refresh and now < float(_CACHE.get("expires_at") or 0):
        return list(_CACHE["archive"]), str(_CACHE["source"])

    cache_seconds = int(os.environ.get("NEWSLETTER_CACHE_SECONDS", str(DEFAULT_CACHE_SECONDS)))
    source = "supabase"
    try:
        archive = fetch_supabase_archive()
    except UPSTREAM_ERRORS:
        archive = []

    if archive:
        fallback_archive, fallback_source = fetch_best_archive_fallback(archive)
        if fallback_archive:
            archive, source = fallback_archive, fallback_source
    else:
        archive, source = fetch_best_archive_fallback([])
        if not source:
            stale_seconds = max(0, int(os.environ.get("NEWSLETTER_STALE_IF_ERROR_SECONDS", str(DEFAULT_STALE_IF_ERROR_SECONDS))))
            stale_until = float(_CACHE.get("expires_at") or 0) + stale_seconds
            if _CACHE.get("last_success_at") is not None and time.time() < stale_until:
                return list(_CACHE["archive"]), "stale_cache"
            raise NewsletterDataError("Newsletter sources are temporarily unavailable")

    _CACHE["archive"] = archive
    _CACHE["source"] = source
    _CACHE["last_success_at"] = time.time()
    _CACHE["expires_at"] = float(_CACHE["last_success_at"]) + max(cache_seconds, 30)
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
