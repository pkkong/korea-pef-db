#!/usr/bin/env python3
"""Restore the published canonical FSS snapshot from Supabase into temporary SQLite.

This is only a compatibility bridge for the existing FSS analytics/page
builders. It lets GP and People publication start from Supabase without
contacting the FSS website or treating a developer machine's SQLite file as
the source of truth.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.gp.src.sync_fss_canonical_supabase import FSS_TABLES, PEOPLE_TABLES, TableSpec
from scripts.apply_gp_alias_merges import ensure_tables as ensure_gp_alias_tables


FSS_SCHEMA = REPO_ROOT / "schema" / "fss_pef.sql"
PEOPLE_SCHEMA = REPO_ROOT / "schema" / "people.sql"
DEFAULT_MANIFEST_OUT = REPO_ROOT / "exports" / "gp" / "fss_canonical_snapshot_manifest.json"
REST_PAGE_SIZE = 500
RETRIABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
# ``person_news_link`` references newsletter's ``news_document`` in the legacy
# SQLite schema. The temporary GP builder needs only its IDs, so it receives a
# minimal FK table and preserves the links when the People rows are synced back.
RESTORABLE_PEOPLE_TABLES = PEOPLE_TABLES


class CanonicalRestoreError(RuntimeError):
    pass


def _supabase_url() -> str:
    value = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not value:
        raise CanonicalRestoreError("SUPABASE_URL is required")
    return value


def _supabase_key() -> str:
    value = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")
    if not value:
        raise CanonicalRestoreError("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY is required")
    return value


def _rest_get(resource: str, query: dict[str, str]) -> list[dict[str, object]]:
    url = f"{_supabase_url()}/rest/v1/{resource}?{urlencode(query)}"
    key = _supabase_key()
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    last_error: BaseException | None = None
    for attempt in range(4):
        request = Request(url, method="GET", headers=headers)
        try:
            with urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, list):
                    raise CanonicalRestoreError(f"Supabase {resource} returned a non-list payload")
                return [row for row in payload if isinstance(row, dict)]
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code not in RETRIABLE_HTTP_STATUS_CODES or attempt == 3:
                raise CanonicalRestoreError(f"Supabase GET {resource} failed: HTTP {exc.code} {detail}") from exc
            last_error = exc
        except (URLError, TimeoutError, ConnectionResetError) as exc:
            if attempt == 3:
                raise CanonicalRestoreError(f"Supabase GET {resource} failed: {exc}") from exc
            last_error = exc
        time.sleep(min(8.0, 0.75 * (2**attempt)))
    raise CanonicalRestoreError(f"Supabase GET {resource} failed: {last_error}")


def _read_all(resource: str, query: dict[str, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    offset = 0
    while True:
        page = _rest_get(resource, {**query, "limit": str(REST_PAGE_SIZE), "offset": str(offset)})
        rows.extend(page)
        if len(page) < REST_PAGE_SIZE:
            return rows
        offset += len(page)


def _published_snapshot() -> dict[str, object]:
    rows = _rest_get(
        "fss_canonical_snapshots",
        {
            "select": "snapshot_id,reporting_period,as_of_date,source_id,source_sha256,fund_count,primary_gp_count,commitment_amount_krw_mn,generated_at",
            "status": "eq.published",
            "order": "published_at.desc",
            "limit": "1",
        },
    )
    if not rows:
        raise CanonicalRestoreError("No published canonical FSS snapshot exists in Supabase")
    return rows[0]


def _insert_rows(conn: sqlite3.Connection, spec: TableSpec, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    target_columns = tuple(spec.source_column(column) for column in spec.columns)
    placeholders = ", ".join("?" for _ in target_columns)
    quoted_columns = ", ".join(f'"{column}"' for column in target_columns)
    values = []
    for row in rows:
        values.append(tuple(row.get(column) for column in spec.columns))
    conn.executemany(
        f'INSERT INTO "{spec.sqlite_table}" ({quoted_columns}) VALUES ({placeholders})',
        values,
    )


def restore_snapshot(*, db_path: Path, manifest_out: Path, include_people: bool = True) -> dict[str, object]:
    if db_path.exists():
        raise CanonicalRestoreError(f"Refusing to overwrite existing SQLite database: {db_path}")
    snapshot = _published_snapshot()
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    if not snapshot_id:
        raise CanonicalRestoreError("Published canonical FSS snapshot has no id")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(FSS_SCHEMA.read_text(encoding="utf-8"))
        ensure_gp_alias_tables(conn)
        if include_people:
            conn.execute("CREATE TABLE IF NOT EXISTS news_document (news_id INTEGER PRIMARY KEY)")
            conn.executescript(PEOPLE_SCHEMA.read_text(encoding="utf-8"))
        for spec in FSS_TABLES:
            rows = _read_all(spec.supabase_table, {"snapshot_id": f"eq.{snapshot_id}"})
            _insert_rows(conn, spec, rows)
        if include_people:
            for spec in RESTORABLE_PEOPLE_TABLES:
                rows = _read_all(spec.supabase_table, {})
                if spec.sqlite_table == "person_news_link":
                    conn.executemany(
                        "INSERT OR IGNORE INTO news_document (news_id) VALUES (?)",
                        [(row["news_id"],) for row in rows if row.get("news_id") is not None],
                    )
                _insert_rows(conn, spec, rows)

    manifest = {"snapshot": snapshot}
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "snapshot_id": snapshot_id,
        "fss_rows": sum(
            _table_row_count(db_path, spec.sqlite_table)
            for spec in FSS_TABLES
        ),
        "people_rows": sum(
            _table_row_count(db_path, spec.sqlite_table)
            for spec in RESTORABLE_PEOPLE_TABLES
        ) if include_people else 0,
    }


def _table_row_count(db_path: Path, table_name: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore published canonical FSS data from Supabase")
    parser.add_argument("--db", type=Path, required=True, help="New temporary SQLite path to create")
    parser.add_argument("--manifest-out", type=Path, default=DEFAULT_MANIFEST_OUT)
    parser.add_argument("--no-people", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = restore_snapshot(
            db_path=args.db,
            manifest_out=args.manifest_out,
            include_people=not args.no_people,
        )
        print("canonical_fss_restore=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, sqlite3.Error, CanonicalRestoreError) as exc:
        print(f"FAIL canonical FSS restore: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
