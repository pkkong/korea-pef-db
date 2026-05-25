#!/usr/bin/env python
"""Backfill daily newsletter export files from completed DB runs."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from daily_news_common import DEFAULT_DB, DEFAULT_EXPORT_DIR, write_csv_rows
from run_daily_news_pipeline import build_export_rows, render_html, render_markdown


BRIEF_HEADERS = [
    "news_id",
    "report_date",
    "publisher",
    "title",
    "source_url",
    "normalized_source_url",
    "published_at",
    "section_tags",
    "section_override_tags",
    "topic_tags",
    "document_type_tags",
    "gp_names",
    "quality_score",
    "quality_reason",
    "relevance_score",
    "relevance_label",
    "summary_text",
    "comment_text",
]


def latest_completed_runs(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    limit: int,
) -> list[sqlite3.Row]:
    where = ["status = 'completed'"]
    params: list[object] = []
    if start_date:
        where.append("run_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("run_date <= ?")
        params.append(end_date)
    where_sql = " AND ".join(where)
    limit_sql = "LIMIT ?" if limit > 0 else ""
    if limit > 0:
        params.append(limit)
    return conn.execute(
        f"""
        SELECT run_date, run_id
        FROM news_run AS nr
        WHERE {where_sql}
          AND started_at = (
              SELECT MAX(started_at)
              FROM news_run AS latest
              WHERE latest.run_date = nr.run_date
                AND latest.status = 'completed'
          )
        ORDER BY run_date DESC
        {limit_sql}
        """,
        params,
    ).fetchall()


def write_exports(
    conn: sqlite3.Connection,
    run_date: str,
    run_id: str,
    out_dir: Path,
    brief_limit: int,
    force: bool,
) -> dict[str, object]:
    dated = run_date.replace("-", "")
    markdown_path = out_dir / f"daily_news_brief_{dated}.md"
    html_path = out_dir / f"daily_news_brief_{dated}.html"
    csv_path = out_dir / f"daily_news_review_queue_{dated}.csv"
    if markdown_path.exists() and not force:
        return {"run_date": run_date, "status": "skipped", "rows": 0, "path": str(markdown_path)}
    rows = build_export_rows(conn, run_id, run_date, brief_limit, out_dir)
    markdown_path.write_text(render_markdown(run_date, rows), encoding="utf-8")
    html_path.write_text(render_html(run_date, rows), encoding="utf-8")
    write_csv_rows(csv_path, rows, BRIEF_HEADERS)
    return {"run_date": run_date, "status": "written", "rows": len(rows), "path": str(markdown_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill daily newsletter exports from completed DB runs")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--brief-limit", type=int, default=12)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        runs = latest_completed_runs(conn, args.start_date, args.end_date, args.limit)
        for row in sorted(runs, key=lambda item: str(item["run_date"])):
            result = write_exports(conn, str(row["run_date"]), str(row["run_id"]), args.out_dir, args.brief_limit, args.force)
            print(" ".join(f"{key}={value}" for key, value in result.items()))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
