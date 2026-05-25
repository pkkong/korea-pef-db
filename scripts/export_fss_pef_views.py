#!/usr/bin/env python
"""Export FSS PEF SQLite views to UTF-8-SIG CSV files for spreadsheet review."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_OUT = REPO_ROOT / "exports"


EXPORTS = {
    "fss_pef_period_summary.csv": """
        SELECT
            period_label,
            as_of_date,
            regime,
            fund_count,
            primary_gp_count,
            ROUND(commitment_amount_krw_mn / 1000000.0, 6) AS commitment_trn_krw,
            ROUND(paid_in_amount_krw_mn / 1000000.0, 6) AS paid_in_trn_krw
        FROM v_period_summary
        ORDER BY as_of_date
    """,
    "fss_pef_gp_period_commitment.csv": """
        SELECT
            period_label,
            as_of_date,
            gp_id,
            gp_name,
            fund_count,
            ROUND(commitment_amount_krw_mn / 1000000.0, 6) AS commitment_trn_krw,
            ROUND(paid_in_amount_krw_mn / 1000000.0, 6) AS paid_in_trn_krw
        FROM v_gp_period_commitment
        WHERE gp_name IS NOT NULL
        ORDER BY as_of_date, commitment_amount_krw_mn DESC, gp_name
    """,
    "fss_pef_fund_timeline.csv": """
        SELECT
            fund_id,
            fund_name,
            gp_name,
            period_label,
            as_of_date,
            fund_type_raw,
            ROUND(commitment_amount_krw_mn / 1000000.0, 6) AS commitment_trn_krw,
            established_date_raw,
            source_title,
            source_url
        FROM v_fund_timeline
        ORDER BY fund_name, as_of_date
    """,
    "fss_pef_fund_events.csv": """
        SELECT
            fe.event_type,
            fe.event_date,
            rp.period_label,
            pf.fund_id,
            pf.fund_name,
            gh.gp_name,
            fe.confidence,
            fe.basis
        FROM fund_event fe
        JOIN pef_fund pf ON pf.fund_id = fe.fund_id
        LEFT JOIN gp_house gh ON gh.gp_id = fe.gp_id
        JOIN reporting_period rp ON rp.period_id = fe.period_id
        ORDER BY event_date, event_type, fund_name
    """,
    "fss_pef_established_by_quarter.csv": """
        SELECT
            established_quarter,
            established_date,
            fund_id,
            fund_name,
            gp_name,
            confidence,
            basis
        FROM v_fund_established_by_calendar_quarter
        ORDER BY established_date, fund_name
    """,
    "fss_pef_disappeared_next_period.csv": """
        SELECT
            last_seen_period,
            absent_period,
            fund_id,
            fund_name,
            gp_name,
            ROUND(commitment_amount_krw_mn / 1000000.0, 6) AS commitment_trn_krw,
            basis
        FROM v_fund_disappeared_next_period
        ORDER BY last_seen_period, fund_name
    """,
}


def export_query(conn: sqlite3.Connection, out_path: Path, query: str) -> int:
    cur = conn.execute(query)
    rows = cur.fetchall()
    headers = [desc[0] for desc in cur.description]
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export FSS PEF DB views to CSV")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    try:
        for filename, query in EXPORTS.items():
            out_path = args.out / filename
            count = export_query(conn, out_path, query)
            print(f"exported {filename}: rows={count}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
