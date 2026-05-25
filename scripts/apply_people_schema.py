from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "db" / "private_equity.db"
DEFAULT_SCHEMA = ROOT / "schema" / "people.sql"


PEOPLE_OBJECTS = [
    "person",
    "person_alias",
    "person_role",
    "person_education",
    "person_source",
    "person_news_link",
]


def apply_schema(db_path: Path, schema_path: Path) -> dict[str, int]:
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")

    sql = schema_path.read_text(encoding="utf-8")
    with sqlite3.connect(db_path, timeout=60) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(sql)
        conn.commit()
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in PEOPLE_OBJECTS
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the People DB schema to the private equity SQLite DB.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args()

    counts = apply_schema(args.db, args.schema)
    print(f"Applied People DB schema to {args.db}")
    for table, count in counts.items():
        print(f"{table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
