#!/usr/bin/env python
"""Sync the published newsletter archive into the Supabase read model.

This is intentionally downstream of the existing collection/classification
pipeline. GitHub Actions still builds the daily archive first; this script
then publishes only the public read model that the Vercel app needs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.newsletter.src.daily_news_common import normalize_url  # noqa: E402
from services.newsletter.src.newsletter_atomic_sync import publish_atomic  # noqa: E402


DEFAULT_ARCHIVE = REPO_ROOT / "services" / "newsletter" / "deploy" / "site" / "archive.json"
DEFAULT_PAYLOAD_OUT = REPO_ROOT / "exports" / "daily_news" / "newsletter_supabase_payload.json"
DEFAULT_ARCHIVE_URL = "https://pkkong.github.io/kpef-newsletter/archive.json"
DEFAULT_ISSUE_LIMIT = 30
DEFAULT_REST_RETRIES = 4
DEFAULT_REST_TIMEOUT_SECONDS = 30
DEFAULT_DELETE_BATCH_SIZE = 50
RETRIABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


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


def read_archive(path: Path, archive_url: str = DEFAULT_ARCHIVE_URL) -> list[dict[str, Any]]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        request = Request(
            archive_url,
            headers={"User-Agent": "kpef-newsletter-supabase-sync/1.0"},
        )
        with urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("archive.json must be a list of issue entries")
    return [row for row in data if isinstance(row, dict)]


def prepare_payload(archive: list[dict[str, Any]], issue_date: str | None = None) -> dict[str, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    issue_rows_by_date: dict[str, dict[str, Any]] = {}
    issue_counts: dict[str, int] = {}
    articles_by_url: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    article_dates: dict[str, str] = {}
    issue_articles: list[dict[str, Any]] = []
    tag_rows: list[dict[str, Any]] = []
    entity_rows: list[dict[str, Any]] = []

    for issue in archive:
        report_date = _clean_text(issue.get("reportDate"))
        if not report_date or (issue_date and report_date != issue_date):
            continue
        article_rows = [row for row in issue.get("articles") or [] if isinstance(row, dict)]
        issue_row = {
            "issue_date": report_date,
            "visible_date": _clean_text(issue.get("visibleDate")) or report_date,
            "basis": _clean_text(issue.get("basis")),
            "status": "published",
            "article_count": 0,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        issues.append(issue_row)
        issue_rows_by_date[report_date] = issue_row
        seen_in_issue: set[str] = set()
        for fallback_rank, article in enumerate(article_rows):
            source_url = _clean_text(article.get("url") or article.get("sourceUrl"))
            normalized = normalize_url(source_url)
            if not normalized or normalized in seen_in_issue:
                continue
            seen_in_issue.add(normalized)
            section = _clean_text(article.get("section")) or "Market"
            sub_category = _clean_text(article.get("subCategory"))
            raw_section = _clean_text(article.get("rawSection")) or section
            article_payload = {
                "normalized_url": normalized,
                "source_url": source_url,
                "source_domain": _clean_text(article.get("sourceDomain")),
                "publisher": _clean_text(article.get("source") or article.get("publisher")),
                "title": _clean_text(article.get("title")),
                "summary_text": _clean_text(article.get("summaryText")),
                "summary_lines": _clean_list(article.get("summaryLines")),
                "section": section,
                "sub_category": sub_category or None,
                "raw_section": raw_section,
                "source_icon_url": _clean_text(article.get("sourceIconUrl")) or None,
                "source_icon_style": _clean_text(article.get("sourceIconStyle")) or None,
                "tag_version": _clean_text(article.get("tagVersion")) or None,
                "gp_names": _clean_list(article.get("gpNames")),
                "lp_names": _clean_list(article.get("lpNames")),
                "search_terms": _clean_list(article.get("searchTerms")),
            }
            if not article_payload["title"]:
                continue
            if report_date >= article_dates.get(normalized, ""):
                articles_by_url[normalized] = article_payload
                article_dates[normalized] = report_date
            issue_articles.append(
                {
                    "issue_date": report_date,
                    "normalized_url": normalized,
                    "rank": _clean_int(article.get("rank"), fallback_rank),
                    "section_order": _clean_int(article.get("sectionOrder"), 999),
                }
            )
            issue_counts[report_date] = issue_counts.get(report_date, 0) + 1
    # Article metadata is canonical per URL. Repeated appearances on different
    # dates share the newest metadata and must not repeat an upsert conflict key.
    for normalized, article in articles_by_url.items():
        tag_rows.append({"normalized_url": normalized, "tag_type": "section", "tag_value": article["section"], "tag_source": "archive"})
        if article["sub_category"]:
            tag_rows.append({"normalized_url": normalized, "tag_type": "sub_category", "tag_value": article["sub_category"], "tag_source": "archive"})
        for kind, names in [("GP", article["gp_names"]), ("LP", article["lp_names"])]:
            for name in names:
                entity_rows.append({"normalized_url": normalized, "entity_type": kind, "entity_name": name, "link_source": "archive"})

    for report_date, count in issue_counts.items():
        if report_date in issue_rows_by_date:
            issue_rows_by_date[report_date]["article_count"] = count

    return {
        "issues": issues,
        "articles": list(articles_by_url.values()),
        "issue_articles": issue_articles,
        "tags": tag_rows,
        "entities": entity_rows,
    }


def select_sync_archive(
    archive: list[dict[str, Any]],
    *,
    issue_date: str | None = None,
    issue_limit: int = DEFAULT_ISSUE_LIMIT,
) -> list[dict[str, Any]]:
    """Select the issue range that should be written to Supabase.

    Date-specific sync remains available for debugging. Routine operation uses
    the same rolling archive depth as the static mirror so Vercel can render the
    same date-navigation experience.
    """

    if issue_date:
        return [row for row in archive if row.get("reportDate") == issue_date]
    if issue_limit <= 0:
        return list(archive)
    return list(archive[:issue_limit])


def _supabase_key() -> str:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY is required for --apply")
    return key


def _supabase_url() -> str:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("SUPABASE_URL is required for --apply")
    return url


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _rest_retries() -> int:
    return max(1, _env_int("NEWSLETTER_SUPABASE_REST_RETRIES", DEFAULT_REST_RETRIES))


def _rest_timeout_seconds() -> int:
    return max(5, _env_int("NEWSLETTER_SUPABASE_REST_TIMEOUT_SECONDS", DEFAULT_REST_TIMEOUT_SECONDS))


def _retry_delay_seconds(attempt_index: int) -> float:
    return min(8.0, 0.75 * (2 ** attempt_index))


def _rest_request(
    table: str,
    *,
    method: str = "GET",
    query: dict[str, str] | None = None,
    payload: object | None = None,
    prefer: str | None = None,
) -> Any:
    base_url = _supabase_url()
    key = _supabase_key()
    url = f"{base_url}/rest/v1/{table}"
    if query:
        url = f"{url}?{urlencode(query)}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    attempts = _rest_retries()
    timeout_seconds = _rest_timeout_seconds()
    last_error: BaseException | None = None
    for attempt_index in range(attempts):
        request = Request(url, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                text = response.read().decode("utf-8")
                return json.loads(text) if text else None
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code not in RETRIABLE_HTTP_STATUS_CODES or attempt_index == attempts - 1:
                raise RuntimeError(f"Supabase {method} {table} failed: HTTP {exc.code} {detail}") from exc
            last_error = RuntimeError(f"HTTP {exc.code} {detail}")
        except (URLError, TimeoutError, ConnectionResetError) as exc:
            if attempt_index == attempts - 1:
                raise RuntimeError(f"Supabase {method} {table} failed: {exc}") from exc
            last_error = exc

        delay_seconds = _retry_delay_seconds(attempt_index)
        print(
            f"supabase_rest_retry method={method} table={table} "
            f"attempt={attempt_index + 1}/{attempts} delay_seconds={delay_seconds:.2f} error={last_error}",
            file=sys.stderr,
        )
        time.sleep(delay_seconds)

    raise RuntimeError(f"Supabase {method} {table} failed after {attempts} attempts: {last_error}")


def _upsert(table: str, rows: list[dict[str, Any]], on_conflict: str, select: str | None = None) -> Any:
    if not rows:
        return []
    query = {"on_conflict": on_conflict}
    if select:
        query["select"] = select
    return _rest_request(
        table,
        method="POST",
        query=query,
        payload=rows,
        prefer="resolution=merge-duplicates,return=representation",
    )


def _delete(table: str, query: dict[str, str]) -> None:
    _rest_request(
        table,
        method="DELETE",
        query=query,
        prefer="return=minimal",
    )


def _delete_many(table: str, column: str, values: list[str], batch_size: int = DEFAULT_DELETE_BATCH_SIZE) -> None:
    clean_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean_value = _clean_text(value)
        if clean_value and clean_value not in seen:
            clean_values.append(clean_value)
            seen.add(clean_value)
    if not clean_values:
        return

    for start in range(0, len(clean_values), max(1, batch_size)):
        batch = clean_values[start : start + batch_size]
        _delete(table, {column: f"in.({','.join(batch)})"})


def apply_payload(payload: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """Publish all selected issues and their metadata as one DB transaction."""
    return publish_atomic(payload, model="public", request=_rest_request)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync public newsletter archive rows to Supabase")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--archive-url", default=DEFAULT_ARCHIVE_URL)
    parser.add_argument("--date", default="")
    parser.add_argument(
        "--issue-limit",
        type=int,
        default=DEFAULT_ISSUE_LIMIT,
        help="Maximum recent issues to sync when --date is omitted. Use 0 for all issues.",
    )
    parser.add_argument("--payload-out", type=Path, default=DEFAULT_PAYLOAD_OUT)
    parser.add_argument("--apply", action="store_true", help="Write to Supabase. Without this, only write a payload preview.")
    args = parser.parse_args()

    archive = read_archive(args.archive, args.archive_url)
    selected_archive = select_sync_archive(
        archive,
        issue_date=args.date or None,
        issue_limit=args.issue_limit,
    )
    payload = prepare_payload(selected_archive, args.date or None)
    if not payload["issues"]:
        selected = args.date or "all dates"
        raise SystemExit(f"No newsletter issues found for {selected}")

    args.payload_out.parent.mkdir(parents=True, exist_ok=True)
    args.payload_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"payload_out={args.payload_out}")
    print(
        "payload_counts="
        + json.dumps({key: len(value) for key, value in payload.items()}, ensure_ascii=False, sort_keys=True)
    )

    if args.apply:
        result = apply_payload(payload)
        print("supabase_sync=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print("supabase_sync=skipped --apply not set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
