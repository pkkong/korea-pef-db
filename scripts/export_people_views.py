from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "db" / "private_equity.db"
DEFAULT_OUT = ROOT / "exports"


EXPORTS = {
    "people_profile_summary.csv": """
        SELECT *
        FROM v_person_profile_summary
        ORDER BY current_primary_org_name, person_id
    """,
    "people_current_gp.csv": """
        SELECT *
        FROM v_person_current_gp
        ORDER BY gp_name, person_id
    """,
    "people_roles.csv": """
        SELECT
            p.person_name_ko,
            p.current_primary_org_name,
            pr.org_type,
            pr.org_name,
            pr.title,
            pr.team,
            pr.role_start_date,
            pr.role_end_date,
            pr.is_current,
            pr.source_url,
            pr.verification_status,
            pr.notes
        FROM person_role pr
        JOIN person p
            ON p.person_id = pr.person_id
        ORDER BY p.current_primary_org_name, p.person_id, pr.is_current DESC, pr.role_id
    """,
    "people_education.csv": """
        SELECT
            p.person_name_ko,
            p.current_primary_org_name,
            pe.school_name,
            pe.school_name_en,
            pe.degree,
            pe.major,
            pe.start_year,
            pe.graduation_year,
            pe.source_url,
            pe.verification_status,
            pe.notes
        FROM person_education pe
        JOIN person p
            ON p.person_id = pe.person_id
        ORDER BY p.current_primary_org_name, p.person_id, pe.education_id
    """,
}


def write_csv(conn: sqlite3.Connection, out_path: Path, sql: str) -> int:
    cursor = conn.execute(sql)
    rows = cursor.fetchall()
    headers = [column[0] for column in cursor.description]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export People DB review CSV files.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.db) as conn:
        for filename, sql in EXPORTS.items():
            count = write_csv(conn, args.out / filename, sql)
            print(f"{filename}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
