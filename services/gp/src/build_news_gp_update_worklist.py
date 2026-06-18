#!/usr/bin/env python
"""Build a GP update worklist from recently clipped news.

The goal is operational: when a GP appears in daily or weekly news, surface it
with its current profile quality so the next research pass focuses on visible
market activity instead of long-tail completion.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.newsletter.src.daily_news_common import DEFAULT_DB, DEFAULT_EXPORT_DIR, today_seoul


DEFAULT_OUT_DIR = DEFAULT_EXPORT_DIR
SERVICE_FIELDS = [
    "company_category",
    "legal_entity_name_ko",
    "legal_entity_name_en",
    "established_date",
    "representative_name",
    "headquarters_address",
    "primary_source_url",
]
IDENTIFIER_FIELDS = [
    "business_registration_number",
    "corporate_registration_number",
]
OPTIONAL_FIELDS = [
    "homepage_url",
    "phone_number",
    "contact_email",
]


def is_filled(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.lower() != "unknown"


def write_csv(path: Path, rows: list[dict[str, object]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows([{header: row.get(header, "") for header in headers} for row in rows])


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def latest_report_date(conn: sqlite3.Connection) -> str:
    if not table_exists(conn, "news_run"):
        return today_seoul()
    row = conn.execute(
        """
        SELECT run_date
        FROM news_run
        ORDER BY run_date DESC, started_at DESC
        LIMIT 1
        """
    ).fetchone()
    return str(row[0]) if row else today_seoul()


def news_window_start(report_date: str, days: int) -> str:
    parsed = datetime.strptime(report_date, "%Y-%m-%d")
    return (parsed - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")


def load_recent_news_links(conn: sqlite3.Connection, report_date: str, days: int) -> list[dict[str, object]]:
    if not table_exists(conn, "news_entity_link") or not table_exists(conn, "news_document"):
        return []
    start_date = news_window_start(report_date, days)
    cursor = conn.execute(
        """
        SELECT
            nel.entity_ref,
            nel.entity_name,
            nel.matched_alias,
            nd.news_id,
            nd.publisher,
            nd.title,
            nd.source_url,
            nd.normalized_source_url,
            nd.published_at,
            nd.discovered_at,
            nd.relevance_score,
            nd.relevance_label,
            nd.comment_text
        FROM news_entity_link nel
        JOIN news_document nd
            ON nd.news_id = nel.news_id
        WHERE nel.entity_type = 'GP'
          AND nd.is_pe_relevant = 1
          AND date(COALESCE(NULLIF(nd.published_at, ''), nd.discovered_at)) BETWEEN date(?) AND date(?)
        ORDER BY nel.entity_name, COALESCE(nd.published_at, nd.discovered_at) DESC, nd.news_id DESC
        """,
        (start_date, report_date),
    )
    headers = [desc[0] for desc in cursor.description]
    return [dict(zip(headers, row)) for row in cursor.fetchall()]


def load_profiles(conn: sqlite3.Connection) -> dict[int, dict[str, object]]:
    if not table_exists(conn, "gp_profile"):
        return {}
    cursor = conn.execute("SELECT * FROM gp_profile")
    headers = [desc[0] for desc in cursor.description]
    return {int(row[headers.index("source_gp_id")]): dict(zip(headers, row)) for row in cursor.fetchall()}


def gp_id_from_ref(entity_ref: str) -> int:
    if not entity_ref.startswith("gp:"):
        return 0
    try:
        return int(entity_ref.split(":", 1)[1])
    except ValueError:
        return 0


def build_rows(conn: sqlite3.Connection, report_date: str, days: int) -> list[dict[str, object]]:
    links = load_recent_news_links(conn, report_date, days)
    profiles = load_profiles(conn)
    grouped: dict[int, dict[str, object]] = {}

    for link in links:
        gp_id = gp_id_from_ref(str(link.get("entity_ref") or ""))
        if not gp_id:
            continue
        profile = profiles.get(gp_id, {})
        row = grouped.setdefault(
            gp_id,
            {
                "source_gp_id": gp_id,
                "standard_gp_name": profile.get("standard_gp_name") or link.get("entity_name") or "",
                "article_count": 0,
                "matched_aliases": set(),
                "publishers": set(),
                "latest_article_at": "",
                "latest_title": "",
                "latest_publisher": "",
                "latest_url": "",
                "latest_comment": "",
                "profile": profile,
            },
        )
        row["article_count"] = int(row["article_count"]) + 1
        if link.get("matched_alias"):
            row["matched_aliases"].add(str(link["matched_alias"]))
        if link.get("publisher"):
            row["publishers"].add(str(link["publisher"]))
        article_at = str(link.get("published_at") or link.get("discovered_at") or "")
        if article_at >= str(row["latest_article_at"] or ""):
            row["latest_article_at"] = article_at
            row["latest_title"] = link.get("title") or ""
            row["latest_publisher"] = link.get("publisher") or ""
            row["latest_url"] = link.get("source_url") or ""
            row["latest_comment"] = link.get("comment_text") or ""

    output: list[dict[str, object]] = []
    for raw in grouped.values():
        profile = dict(raw.pop("profile") or {})
        missing_service = [field for field in SERVICE_FIELDS if not is_filled(profile.get(field))]
        missing_identifier = [field for field in IDENTIFIER_FIELDS if not is_filled(profile.get(field))]
        missing_optional = [field for field in OPTIONAL_FIELDS if not is_filled(profile.get(field))]
        is_verified = str(profile.get("verification_level") or "") != "FSS_NAME_ONLY"
        service_ready = is_verified and not missing_service
        identifier_complete = not missing_identifier
        if not service_ready:
            suggested_action = "프로필 우선 보강"
        elif not identifier_complete:
            suggested_action = "식별자 보강"
        elif missing_optional:
            suggested_action = "선택정보 보강"
        else:
            suggested_action = "유지"

        output.append(
            {
                "source_gp_id": raw["source_gp_id"],
                "standard_gp_name": raw["standard_gp_name"],
                "article_count": raw["article_count"],
                "latest_article_at": raw["latest_article_at"],
                "latest_publisher": raw["latest_publisher"],
                "latest_title": raw["latest_title"],
                "latest_url": raw["latest_url"],
                "latest_comment": raw["latest_comment"],
                "matched_aliases": "; ".join(sorted(raw["matched_aliases"])),
                "publishers": "; ".join(sorted(raw["publishers"])),
                "verification_level": profile.get("verification_level", ""),
                "service_ready": "Y" if service_ready else "",
                "identifier_complete": "Y" if identifier_complete else "",
                "missing_service_fields": "; ".join(missing_service),
                "missing_identifier_fields": "; ".join(missing_identifier),
                "missing_optional_fields": "; ".join(missing_optional),
                "suggested_action": suggested_action,
                "primary_source_url": profile.get("primary_source_url", ""),
            }
        )

    priority = {
        "프로필 우선 보강": 0,
        "식별자 보강": 1,
        "선택정보 보강": 2,
        "유지": 3,
    }
    output.sort(
        key=lambda row: (
            priority.get(str(row["suggested_action"]), 9),
            -int(row["article_count"]),
            str(row["standard_gp_name"]),
        )
    )
    for index, row in enumerate(output, start=1):
        row["worklist_rank"] = index
    return output


def build(db_path: Path, out_dir: Path, report_date: str, days: int, write_latest: bool = True) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    try:
        if not report_date:
            report_date = latest_report_date(conn)
        rows = build_rows(conn, report_date, days)
    finally:
        conn.close()

    headers = [
        "worklist_rank",
        "source_gp_id",
        "standard_gp_name",
        "article_count",
        "latest_article_at",
        "latest_publisher",
        "latest_title",
        "latest_url",
        "latest_comment",
        "matched_aliases",
        "publishers",
        "verification_level",
        "service_ready",
        "identifier_complete",
        "missing_service_fields",
        "missing_identifier_fields",
        "missing_optional_fields",
        "suggested_action",
        "primary_source_url",
    ]
    dated_path = out_dir / f"news_gp_update_worklist_{report_date.replace('-', '')}.csv"
    latest_path = out_dir / "news_gp_update_worklist_latest.csv"
    write_csv(dated_path, rows, headers)
    if write_latest:
        write_csv(latest_path, rows, headers)
    return {
        "report_date": report_date,
        "days": days,
        "rows": len(rows),
        "dated_path": str(dated_path),
        "latest_path": str(latest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build GP update worklist from daily/weekly news links")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--date", default="")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    result = build(args.db, args.out_dir, args.date, args.days)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
