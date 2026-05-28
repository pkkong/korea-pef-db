#!/usr/bin/env python
"""Validate daily news clipping outputs and local automation health."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

from daily_news_common import (
    DEFAULT_DB,
    DEFAULT_ENV,
DEFAULT_EXPORT_DIR,
    DEFAULT_SOURCES,
    REPO_ROOT,
    normalize_url,
    read_csv_rows,
    today_seoul,
)
from run_daily_news_pipeline import (
    EXPORT_MIN_QUALITY_SCORE,
    SECTION_LABELS,
    coverage_window_label,
    is_near_duplicate_title_key,
    normalize_title_key,
)


REQUIRED_TABLES = [
    "news_source",
    "news_run",
    "news_document",
    "news_tag",
    "news_entity_link",
]
VALID_CATEGORY_LABELS = set(SECTION_LABELS.values())
MARKDOWN_LINK_RE = re.compile(r"- \[(?P<title>.+?)\]\((?P<url>https?://[^)]+)\)")


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def note(self, message: str) -> None:
        self.info.append(message)

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": not self.errors,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
        }


def compact_date(report_date: str) -> str:
    return report_date.replace("-", "")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def markdown_links(markdown_text: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in markdown_text.splitlines():
        match = MARKDOWN_LINK_RE.match(line)
        if match:
            current = match.groupdict()
            current["publisher"] = ""
            links.append(current)
            continue
        if current is not None and line.startswith("  출처:"):
            current["publisher"] = line.split(":", 1)[1].strip()
    return links


def check_env_and_sources(result: Validation, env_path: Path, sources_path: Path) -> None:
    env_values = parse_env_file(env_path)
    if not env_path.exists():
        result.warning(f"env file missing: {env_path}")
    active_sources = [row for row in read_csv_rows(sources_path) if row.get("is_active", "1") == "1"]
    active_naver = [row for row in active_sources if row.get("source_kind") == "naver_news_api"]
    if active_naver:
        missing = [key for key in ["NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"] if not env_values.get(key) and not os.environ.get(key)]
        if missing:
            result.error("active Naver sources exist but Naver credentials are missing")
        else:
            result.note(f"Naver credentials configured for {len(active_naver)} active Naver sources")
    if not active_sources:
        result.error("no active news sources configured")
    result.note(f"active source count: {len(active_sources)}")


def check_artifacts(result: Validation, out_dir: Path, report_date: str) -> None:
    dated = compact_date(report_date)
    paths = {
        "brief_md": out_dir / f"daily_news_brief_{dated}.md",
        "brief_html": out_dir / f"daily_news_brief_{dated}.html",
        "review_queue": out_dir / f"daily_news_review_queue_{dated}.csv",
        "review_actions": out_dir / f"daily_news_review_actions_{dated}.csv",
        "review_html": out_dir / f"daily_news_review_{dated}.html",
        "latest_md": out_dir / "daily_news_brief_latest.md",
        "latest_html": out_dir / "daily_news_brief_latest.html",
        "latest_review_actions": out_dir / "daily_news_review_actions_latest.csv",
    }
    for label, path in paths.items():
        if not path.exists():
            result.error(f"missing {label}: {path}")
        elif path.stat().st_size == 0:
            result.error(f"empty {label}: {path}")

    brief_text = read_text(paths["brief_md"])
    if not brief_text:
        return

    expected_coverage = coverage_window_label(report_date)
    if expected_coverage not in brief_text:
        result.error("brief markdown does not show the expected 24-hour coverage window")
    if "No search available" in brief_text:
        result.warning("brief markdown has no selected clips")

    links = markdown_links(brief_text)
    if not links:
        result.warning("brief markdown has no article links")
    url_keys: set[str] = set()
    title_keys: set[str] = set()
    title_rows: list[tuple[str, str]] = []
    google_redirect_count = 0
    for link in links:
        url_key = normalize_url(link["url"])
        title_key = normalize_title_key(link["title"])
        publisher_hint = link.get("publisher", "")
        if url_key in url_keys:
            result.error(f"duplicate URL in brief: {link['url']}")
        if title_key and (title_key in title_keys or is_near_duplicate_title_key(title_key, publisher_hint, title_rows)):
            result.error(f"duplicate-looking title in brief: {link['title']}")
        url_keys.add(url_key)
        title_keys.add(title_key)
        if title_key:
            title_rows.append((title_key, publisher_hint))
        if "news.google.com/" in link["url"]:
            google_redirect_count += 1
    if google_redirect_count:
        result.warning(f"Google News redirect links in brief: {google_redirect_count}")
    result.note(f"brief selected clip count: {len(links)}")

    queue_rows = read_csv_rows(paths["review_queue"])
    included_queue = [row for row in queue_rows if row.get("normalized_source_url") or row.get("source_url")]
    if len(included_queue) < len(links):
        result.warning("review queue has fewer rows than brief links")
    for row in queue_rows:
        include_flag = row.get("include_in_brief", "").upper()
        if include_flag == "Y":
            score = parse_float(row.get("quality_score", "0"))
            if score < EXPORT_MIN_QUALITY_SCORE:
                result.warning(f"included row below quality threshold: {row.get('title', '')} ({score})")

    action_rows = read_csv_rows(paths["review_actions"])
    for row in action_rows:
        category = row.get("category", "").strip()
        if category and category not in VALID_CATEGORY_LABELS:
            result.error(f"invalid review category '{category}' for title: {row.get('title', '')}")
        action = row.get("action", "").strip()
        if action and action not in {"include", "exclude"}:
            result.error(f"invalid review action '{action}' for title: {row.get('title', '')}")

    latest_text = read_text(paths["latest_md"])
    if latest_text and expected_coverage not in latest_text:
        result.warning("latest markdown is not aligned with the selected report date")

    final_latest = out_dir / "daily_news_final_latest.md"
    if final_latest.exists() and expected_coverage not in read_text(final_latest):
        result.warning("latest final file is older than the latest brief; finalization is pending")


def check_public_site(result: Validation, public_dir: Path, report_date: str) -> None:
    paths = {
        "public landing page": public_dir / "index.html",
        "public daily news page": public_dir / "daily-news.html",
        "public service stylesheet": public_dir / "assets" / "service.css",
    }
    for label, path in paths.items():
        if not path.exists():
            result.warning(f"missing {label}: {path}")
        elif path.stat().st_size == 0:
            result.warning(f"empty {label}: {path}")
    landing_text = read_text(paths["public landing page"])
    daily_text = read_text(paths["public daily news page"])
    display_report_date = report_date.replace("-", ".")
    for label, text in [("public landing page", landing_text), ("public daily news page", daily_text)]:
        if text and report_date not in text and display_report_date not in text:
            result.warning(f"{label} does not show report date {report_date}")
        for forbidden in ["KST", "최근 24시간", "선정 기사", "검수 후보", "Review Queue", "Raw HTML", "PC가 꺼져"]:
            if text and forbidden in text:
                result.warning(f"{label} exposes internal wording: {forbidden}")


def check_database(result: Validation, db_path: Path, report_date: str) -> None:
    if not db_path.exists():
        result.error(f"database missing: {db_path}")
        return
    conn = sqlite3.connect(db_path)
    try:
        existing_tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        for table in REQUIRED_TABLES:
            if table not in existing_tables:
                result.error(f"database table missing: {table}")
        row = conn.execute(
            """
            SELECT run_id, status, discovered_count, fetched_count, relevant_count, notes
            FROM news_run
            WHERE run_date = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (report_date,),
        ).fetchone()
        if not row:
            result.error(f"no news_run row for {report_date}")
            return
        run_id, status, discovered, fetched, relevant, notes = row
        if status != "completed":
            result.error(f"latest run is not completed: {run_id} status={status}")
        if int(discovered or 0) <= 0:
            result.error(f"latest run discovered no items: {run_id}")
        if int(fetched or 0) <= 0:
            result.error(f"latest run fetched no articles: {run_id}")
        if notes:
            result.warning(f"latest run has warnings: {str(notes).splitlines()[0]}")
        result.note(f"latest db run: {run_id}, discovered={discovered}, fetched={fetched}, selected={relevant}")
    finally:
        conn.close()


def check_scheduler(result: Validation) -> None:
    if os.name != "nt":
        return
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-ScheduledTask -TaskName 'Private Equity Daily News Clipping' | Select-Object -ExpandProperty State",
    ]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=30)
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        if "Access is denied" in stderr or "액세스가 거부" in stderr:
            result.note("Windows scheduled task check skipped because access was denied in this shell")
        else:
            result.warning("Windows scheduled task was not found or could not be read")
        return
    state = completed.stdout.strip()
    if state not in {"Ready", "Running"}:
        result.warning(f"Windows scheduled task state is {state}")
    else:
        result.note(f"Windows scheduled task state: {state}")


def parse_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def print_human(result: Validation) -> None:
    status = "OK" if not result.errors else "FAIL"
    print(f"Daily news validation: {status}")
    if result.errors:
        print("\nErrors")
        for message in result.errors:
            print(f"- {message}")
    if result.warnings:
        print("\nWarnings")
        for message in result.warnings:
            print(f"- {message}")
    if result.info:
        print("\nInfo")
        for message in result.info:
            print(f"- {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate daily news clipping outputs")
    parser.add_argument("--date", default=today_seoul())
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--public-dir", type=Path, default=REPO_ROOT / "public")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = Validation()
    check_env_and_sources(result, args.env, args.sources)
    check_artifacts(result, args.out_dir, args.date)
    check_public_site(result, args.public_dir, args.date)
    check_database(result, args.db, args.date)
    check_scheduler(result)

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        print_human(result)
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
