#!/usr/bin/env python
"""Apply LP commitment schema."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_SCHEMA = REPO_ROOT / "schema" / "lp_commitments.sql"


def apply_schema(db_path: Path, schema_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        schema_sql = schema_path.read_text(encoding="utf-8")
        marker = "CREATE INDEX IF NOT EXISTS idx_lp_notice_lp"
        if marker in schema_sql:
            pre_index_sql, index_and_view_sql = schema_sql.split(marker, 1)
            conn.executescript(pre_index_sql)
            ensure_columns(conn)
            conn.executescript(marker + index_and_view_sql)
        else:
            conn.executescript(schema_sql)
            ensure_columns(conn)
        conn.commit()
    finally:
        conn.close()


def ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(lp_commitment_notice)").fetchall()
    }
    columns = {
        "event_type": "TEXT",
        "event_date": "TEXT",
        "program_name": "TEXT",
        "round_name": "TEXT",
        "program_size_krw_100mn": "REAL",
        "allocation_amount_krw_100mn": "REAL",
        "amount_type": "TEXT",
        "amount_confidence": "TEXT",
        "confidence": "TEXT",
        "confidence_note": "TEXT",
        "public_visible": "INTEGER NOT NULL DEFAULT 1",
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE lp_commitment_notice ADD COLUMN {name} {definition}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply LP commitment schema")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args()

    apply_schema(args.db, args.schema)
    print(f"applied_schema={args.schema}")
    print(f"db={args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
