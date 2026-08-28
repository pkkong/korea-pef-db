#!/usr/bin/env python3
"""Copy the normalized FSS and People operating data from SQLite to Supabase.

SQLite remains compatible with the existing FSS parser, but Supabase is the
durable operating database. The public GP HTML snapshot is a separate read
model and is published only after this canonical snapshot is complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_fss_statistics_ready import (  # noqa: E402
    DEFAULT_DB,
    DEFAULT_REGISTRY,
    check_fss_statistics,
    latest_registry_row,
    read_registry,
    sha256_file,
)


DEFAULT_PAYLOAD_OUT = REPO_ROOT / "exports" / "gp" / "fss_canonical_supabase_payload.json"
REST_BATCH_SIZE = 500
MAX_REST_BATCH_BYTES = 750_000
RETRIABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class CanonicalSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class TableSpec:
    sqlite_table: str
    supabase_table: str
    columns: tuple[str, ...]
    conflict_columns: tuple[str, ...]
    column_sources: tuple[tuple[str, str], ...] = ()
    is_fss_data: bool = True

    def source_column(self, output_column: str) -> str:
        return dict(self.column_sources).get(output_column, output_column)


FSS_TABLES = (
    TableSpec(
        "source_document",
        "fss_source_documents",
        (
            "source_id", "title", "publisher", "document_type", "regime", "period_label", "as_of_date",
            "source_url", "local_path", "sha256", "fetched_at", "parsed_at", "notes",
        ),
        ("snapshot_id", "source_id"),
    ),
    TableSpec(
        "reporting_period",
        "fss_reporting_periods",
        ("period_id", "period_label", "as_of_date", "year", "quarter", "regime"),
        ("snapshot_id", "period_id"),
    ),
    TableSpec(
        "gp_house",
        "fss_gp_houses",
        ("gp_id", "gp_name", "gp_name_norm", "first_seen_period_id", "last_seen_period_id", "created_at", "updated_at"),
        ("snapshot_id", "gp_id"),
    ),
    TableSpec(
        "pef_fund",
        "fss_pef_funds",
        (
            "fund_id", "fund_name", "fund_name_norm", "regime_first_seen", "fund_type", "established_date",
            "liquidation_date", "created_at", "updated_at",
        ),
        ("snapshot_id", "fund_id"),
    ),
    TableSpec(
        "fund_gp_affiliation",
        "fss_fund_gp_affiliations",
        ("fund_id", "gp_id", "role", "first_seen_period_id", "last_seen_period_id"),
        ("snapshot_id", "fund_id", "gp_id", "role"),
    ),
    TableSpec(
        "gp_house_alias",
        "fss_gp_house_aliases",
        (
            "alias_gp_id", "canonical_gp_id", "alias_gp_name", "alias_gp_name_norm",
            "canonical_gp_name", "alias_candidate_group_id", "relationship_type",
            "verification_decision", "evidence_summary", "primary_sources", "merged_at",
        ),
        ("snapshot_id", "alias_gp_id"),
    ),
    TableSpec(
        "source_row",
        "fss_source_rows",
        ("source_row_id", "source_id", "sheet_name", "row_number", "raw_row_json", "row_hash"),
        ("snapshot_id", "source_row_id"),
    ),
    TableSpec(
        "fund_period_snapshot",
        "fss_fund_period_snapshots",
        (
            "fund_period_snapshot_id", "fund_id", "period_id", "source_id", "gp_id", "sheet_name", "row_number",
            "sheet_role", "fund_name_raw", "gp_name_raw", "fund_type_raw", "status_raw", "established_date_raw",
            "liquidation_date_raw", "commitment_amount_raw", "commitment_amount_krw_mn", "paid_in_amount_raw",
            "paid_in_amount_krw_mn", "raw_row_json", "row_hash",
        ),
        ("snapshot_id", "fund_period_snapshot_id"),
        (("fund_period_snapshot_id", "snapshot_id"),),
    ),
    TableSpec(
        "fund_event",
        "fss_fund_events",
        (
            "fund_event_id", "fund_id", "gp_id", "event_type", "event_date", "period_id", "source_id",
            "confidence", "basis", "created_at",
        ),
        ("snapshot_id", "fund_event_id"),
        (("fund_event_id", "event_id"),),
    ),
)

PEOPLE_TABLES = (
    TableSpec(
        "person",
        "people_persons",
        (
            "person_id", "person_name_ko", "person_name_en", "person_name_norm", "current_primary_org_type",
            "current_primary_org_id", "current_primary_org_name", "current_title", "profile_status",
            "verification_level", "primary_source_url", "notes", "created_at", "updated_at",
        ),
        ("person_id",),
        is_fss_data=False,
    ),
    TableSpec(
        "person_alias",
        "people_aliases",
        (
            "alias_id", "person_id", "alias_name", "alias_name_norm", "alias_type", "source_url",
            "verification_status", "notes", "created_at",
        ),
        ("alias_id",),
        is_fss_data=False,
    ),
    TableSpec(
        "person_role",
        "people_roles",
        (
            "role_id", "person_id", "org_type", "org_id", "org_name", "title", "team", "role_start_date",
            "role_end_date", "is_current", "source_url", "source_title", "source_grade", "verification_status",
            "notes", "created_at", "updated_at",
        ),
        ("role_id",),
        is_fss_data=False,
    ),
    TableSpec(
        "person_education",
        "people_educations",
        (
            "education_id", "person_id", "school_name", "school_name_en", "degree", "major", "start_year",
            "graduation_year", "source_url", "source_title", "source_grade", "verification_status", "notes",
            "created_at", "updated_at",
        ),
        ("education_id",),
        is_fss_data=False,
    ),
    TableSpec(
        "person_source",
        "people_sources",
        (
            "source_evidence_id", "person_id", "source_type", "source_title", "source_url", "source_grade",
            "evidence_scope", "evidence_value", "evidence_date", "verification_status", "captured_at", "notes",
        ),
        ("source_evidence_id",),
        is_fss_data=False,
    ),
    TableSpec(
        "person_news_link",
        "people_news_links",
        ("person_id", "news_id", "matched_name", "link_source", "confidence", "notes", "created_at"),
        ("person_id", "news_id", "link_source"),
        is_fss_data=False,
    ),
)


def _supabase_url() -> str:
    value = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not value:
        raise CanonicalSyncError("SUPABASE_URL is required for --apply")
    return value


def _supabase_key() -> str:
    value = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")
    if not value:
        raise CanonicalSyncError("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY is required for --apply")
    return value


def _rest_request(
    resource: str,
    *,
    method: str = "GET",
    query: dict[str, str] | None = None,
    payload: object | None = None,
    prefer: str | None = None,
) -> Any:
    url = f"{_supabase_url()}/rest/v1/{resource}"
    if query:
        url = f"{url}?{urlencode(query)}"
    key = _supabase_key()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if payload is not None else None

    last_error: BaseException | None = None
    for attempt in range(4):
        request = Request(url, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code not in RETRIABLE_HTTP_STATUS_CODES or attempt == 3:
                raise CanonicalSyncError(f"Supabase {method} {resource} failed: HTTP {exc.code} {detail}") from exc
            last_error = exc
        except (URLError, TimeoutError, ConnectionResetError) as exc:
            if attempt == 3:
                raise CanonicalSyncError(f"Supabase {method} {resource} failed: {exc}") from exc
            last_error = exc
        time.sleep(min(8.0, 0.75 * (2**attempt)))
    raise CanonicalSyncError(f"Supabase {method} {resource} failed: {last_error}")


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
    ).fetchone() is not None


def _read_table_rows(conn: sqlite3.Connection, spec: TableSpec, *, snapshot_id: str | None = None) -> list[dict[str, object]]:
    if not _table_exists(conn, spec.sqlite_table):
        return []
    select_columns = [f'"{spec.source_column(column)}" AS "{column}"' for column in spec.columns]
    rows = conn.execute(f'SELECT {", ".join(select_columns)} FROM "{spec.sqlite_table}"').fetchall()
    output: list[dict[str, object]] = []
    for row in rows:
        item = {column: row[column] for column in spec.columns}
        if spec.supabase_table == "people_roles":
            item["is_current"] = bool(item["is_current"])
        if snapshot_id and spec.is_fss_data:
            item = {"snapshot_id": snapshot_id, **item}
        output.append(item)
    return output


def _person_source_hash(people_tables: dict[str, list[dict[str, object]]]) -> str:
    encoded = json.dumps(people_tables, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_from_manifest(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    snapshot = data.get("snapshot", data)
    if not isinstance(snapshot, dict):
        raise CanonicalSyncError(f"Canonical snapshot manifest is invalid: {path}")
    required = (
        "snapshot_id",
        "reporting_period",
        "as_of_date",
        "source_id",
        "source_sha256",
        "fund_count",
        "primary_gp_count",
        "commitment_amount_krw_mn",
    )
    missing = [field for field in required if snapshot.get(field) in (None, "")]
    if missing:
        raise CanonicalSyncError(f"Canonical snapshot manifest is missing: {', '.join(missing)}")
    return {
        **{field: snapshot[field] for field in required},
        "status": "staged",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def prepare_payload(
    *,
    db_path: Path,
    registry_path: Path,
    expected_latest_period: str | None = None,
    canonical_manifest: Path | None = None,
    include_fss_data: bool = True,
) -> dict[str, object]:
    if canonical_manifest:
        snapshot = _snapshot_from_manifest(canonical_manifest)
        canonical_snapshot_id = str(snapshot["snapshot_id"])
    else:
        readiness = check_fss_statistics(
            db_path=db_path,
            registry_path=registry_path,
            expected_latest_period=expected_latest_period,
        )
        registry_rows = read_registry(registry_path)
        latest = latest_registry_row(registry_rows, str(readiness["latest_period"]))
        raw_path = REPO_ROOT / latest["local_file"]
        source_sha256 = sha256_file(raw_path)
        canonical_snapshot_id = f"fss-core-{str(readiness['latest_period']).lower()}-{source_sha256[:12]}"
        snapshot = {
            "snapshot_id": canonical_snapshot_id,
            "reporting_period": readiness["latest_period"],
            "as_of_date": readiness["as_of_date"],
            "source_id": readiness["source_id"],
            "source_sha256": source_sha256,
            "fund_count": readiness["fund_count"],
            "primary_gp_count": readiness["primary_gp_count"],
            "commitment_amount_krw_mn": readiness["commitment_amount_krw_mn"],
            "status": "staged",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        fss_tables = (
            {
                spec.supabase_table: _read_table_rows(conn, spec, snapshot_id=canonical_snapshot_id)
                for spec in FSS_TABLES
            }
            if include_fss_data
            else {}
        )
        people_tables = {
            spec.supabase_table: _read_table_rows(conn, spec)
            for spec in PEOPLE_TABLES
        }

    return {
        "snapshot": snapshot,
        "fss_tables": fss_tables,
        "sync_fss_data": include_fss_data,
        "people_tables": people_tables,
        "people_state": {
            "state_key": True,
            "fss_snapshot_id": canonical_snapshot_id,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "source_hash": _person_source_hash(people_tables),
        },
    }


def _batched(
    rows: list[dict[str, object]],
    size: int = REST_BATCH_SIZE,
    max_bytes: int = MAX_REST_BATCH_BYTES,
) -> list[list[dict[str, object]]]:
    """Keep PostgREST requests small even when a raw FSS row is large."""
    batches: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    current_bytes = 2
    for row in rows:
        row_bytes = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        if current and (len(current) >= size or current_bytes + row_bytes > max_bytes):
            batches.append(current)
            current = []
            current_bytes = 2
        current.append(row)
        current_bytes += row_bytes
    if current:
        batches.append(current)
    return batches


def _upsert_table(spec: TableSpec, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    for batch in _batched(rows):
        _rest_request(
            spec.supabase_table,
            method="POST",
            query={"on_conflict": ",".join(spec.conflict_columns)},
            payload=batch,
            prefer="resolution=merge-duplicates,return=minimal",
        )


def apply_payload(payload: dict[str, object]) -> dict[str, object]:
    snapshot = payload.get("snapshot")
    fss_tables = payload.get("fss_tables")
    people_tables = payload.get("people_tables")
    people_state = payload.get("people_state")
    sync_fss_data = payload.get("sync_fss_data", True)
    if not isinstance(snapshot, dict) or not isinstance(fss_tables, dict) or not isinstance(people_tables, dict):
        raise CanonicalSyncError("Invalid canonical Supabase payload")
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    if not snapshot_id:
        raise CanonicalSyncError("Canonical FSS snapshot id is missing")

    if not isinstance(sync_fss_data, bool):
        raise CanonicalSyncError("sync_fss_data must be a boolean")
    if sync_fss_data:
        _rest_request(
            "fss_canonical_snapshots",
            method="POST",
            query={"on_conflict": "snapshot_id"},
            payload=snapshot,
            prefer="resolution=ignore-duplicates,return=minimal",
        )
        for spec in FSS_TABLES:
            rows = fss_tables.get(spec.supabase_table, [])
            if not isinstance(rows, list):
                raise CanonicalSyncError(f"Invalid rows for {spec.supabase_table}")
            _upsert_table(spec, rows)

    # People is current operational data, not an immutable quarterly FSS snapshot.
    _rest_request("people_persons", method="DELETE", query={"person_id": "gte.0"}, prefer="return=minimal")
    for spec in PEOPLE_TABLES:
        rows = people_tables.get(spec.supabase_table, [])
        if not isinstance(rows, list):
            raise CanonicalSyncError(f"Invalid rows for {spec.supabase_table}")
        _upsert_table(spec, rows)
    if not isinstance(people_state, dict):
        raise CanonicalSyncError("People state is missing")
    _rest_request(
        "people_data_state",
        method="POST",
        query={"on_conflict": "state_key"},
        payload=people_state,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    if sync_fss_data:
        _rest_request(
            "rpc/publish_fss_canonical_snapshot",
            method="POST",
            payload={"target_snapshot_id": snapshot_id},
            prefer="return=minimal",
        )
    return {
        "snapshot_id": snapshot_id,
        "fss_rows": sum(len(rows) for rows in fss_tables.values() if isinstance(rows, list)),
        "people_rows": sum(len(rows) for rows in people_tables.values() if isinstance(rows, list)),
        "status": "published" if sync_fss_data else "people_synced",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync normalized FSS and People data to canonical Supabase tables")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--expected-latest-period")
    parser.add_argument(
        "--canonical-manifest",
        type=Path,
        help="Use existing Supabase FSS snapshot metadata instead of checking local raw Excel files.",
    )
    parser.add_argument(
        "--people-only",
        action="store_true",
        help="Update People tables only; retain the published FSS snapshot unchanged.",
    )
    parser.add_argument("--payload-out", type=Path, default=DEFAULT_PAYLOAD_OUT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = prepare_payload(
            db_path=args.db,
            registry_path=args.registry,
            expected_latest_period=args.expected_latest_period or None,
            canonical_manifest=args.canonical_manifest,
            include_fss_data=not args.people_only,
        )
        args.payload_out.parent.mkdir(parents=True, exist_ok=True)
        args.payload_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        snapshot = payload["snapshot"]
        assert isinstance(snapshot, dict)
        print(f"payload_out={args.payload_out}")
        print(f"snapshot_id={snapshot['snapshot_id']}")
        print(f"reporting_period={snapshot['reporting_period']}")
        if args.apply:
            print("supabase_fss_canonical_sync=" + json.dumps(apply_payload(payload), ensure_ascii=False, sort_keys=True))
        else:
            print("supabase_fss_canonical_sync=skipped --apply not set")
    except (OSError, ValueError, sqlite3.Error, CanonicalSyncError) as exc:
        print(f"FAIL canonical FSS Supabase sync: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
