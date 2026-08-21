#!/usr/bin/env python3
"""Fail when the FSS PEF statistical dataset is not reproducible or publishable."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_REGISTRY = REPO_ROOT / "data" / "source_registry_fss_pef.csv"
DEFAULT_MAX_SOURCE_AGE_DAYS = 400


class ReadinessError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_registry(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ReadinessError(f"FSS source registry is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [{key: str(value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]
    if not rows:
        raise ReadinessError("FSS source registry is empty")
    for row in rows:
        if not row.get("source_id") or not row.get("period_label") or not row.get("as_of_date") or not row.get("local_file"):
            raise ReadinessError(f"FSS source registry has an incomplete row: {row}")
        raw_path = REPO_ROOT / row["local_file"]
        if not raw_path.is_file() or raw_path.stat().st_size <= 0:
            raise ReadinessError(f"FSS raw source is missing or empty: {row['source_id']} {raw_path}")
    return rows


def latest_registry_row(rows: list[dict[str, str]], expected_period: str | None) -> dict[str, str]:
    if expected_period:
        matches = [row for row in rows if row["period_label"] == expected_period]
        if len(matches) != 1:
            raise ReadinessError(f"Expected exactly one registry row for {expected_period}; found {len(matches)}")
        return matches[0]
    return max(rows, key=lambda row: (row["as_of_date"], row["period_label"], row["source_id"]))


def object_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'view') LIMIT 1",
        (name,),
    ).fetchone() is not None


def safe_table_suffix(period_label: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]+", "", period_label)


def scalar(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> object:
    row = conn.execute(query, params).fetchone()
    return row[0] if row is not None else None


def check_fss_statistics(
    *,
    db_path: Path,
    registry_path: Path,
    expected_latest_period: str | None = None,
    max_source_age_days: int = DEFAULT_MAX_SOURCE_AGE_DAYS,
    today: date | None = None,
) -> dict[str, object]:
    rows = read_registry(registry_path)
    latest = latest_registry_row(rows, expected_latest_period)
    as_of_date = date.fromisoformat(latest["as_of_date"])
    current_day = today or date.today()
    age_days = (current_day - as_of_date).days
    if age_days > max_source_age_days:
        raise ReadinessError(
            f"Latest FSS period is stale: {latest['period_label']} as of {latest['as_of_date']} ({age_days} days old)"
        )
    if not db_path.is_file() or db_path.stat().st_size <= 0:
        raise ReadinessError(f"FSS statistics DB is missing or empty: {db_path}")

    raw_path = REPO_ROOT / latest["local_file"]
    raw_sha256 = sha256_file(raw_path)
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        required_objects = ("source_document", "reporting_period", "fund_period_snapshot", "v_period_summary")
        missing = [name for name in required_objects if not object_exists(conn, name)]
        if missing:
            raise ReadinessError(f"FSS statistics DB is missing required object(s): {', '.join(missing)}")

        source = conn.execute(
            "SELECT period_label, as_of_date, sha256 FROM source_document WHERE source_id = ?",
            (latest["source_id"],),
        ).fetchone()
        if source is None:
            raise ReadinessError(f"Latest FSS source is not imported: {latest['source_id']}")
        if source[0] != latest["period_label"] or source[1] != latest["as_of_date"]:
            raise ReadinessError(f"Latest FSS source metadata differs from registry: {latest['source_id']}")
        if str(source[2] or "").lower() != raw_sha256.lower():
            raise ReadinessError(f"Latest FSS source hash differs from raw file: {latest['source_id']}")

        period = conn.execute(
            "SELECT period_id, period_label, as_of_date FROM reporting_period ORDER BY as_of_date DESC, period_id DESC LIMIT 1"
        ).fetchone()
        if period is None or period[1] != latest["period_label"] or period[2] != latest["as_of_date"]:
            raise ReadinessError("DB latest reporting period does not match the latest FSS source")

        summary = conn.execute(
            """
            SELECT fund_count, primary_gp_count, commitment_amount_krw_mn
            FROM v_period_summary
            WHERE period_label = ? AND as_of_date = ?
            """,
            (latest["period_label"], latest["as_of_date"]),
        ).fetchone()
        if summary is None:
            raise ReadinessError("Latest FSS period has no market summary")
        fund_count, gp_count, commitment = (int(summary[0] or 0), int(summary[1] or 0), float(summary[2] or 0))
        if fund_count <= 0 or gp_count <= 0 or commitment <= 0:
            raise ReadinessError("Latest FSS market summary has empty fund, GP, or commitment data")

        snapshot_fund_count = int(
            scalar(conn, "SELECT COUNT(DISTINCT fund_id) FROM fund_period_snapshot WHERE period_id = ?", (period[0],)) or 0
        )
        snapshot_gp_count = int(
            scalar(conn, "SELECT COUNT(DISTINCT gp_id) FROM fund_period_snapshot WHERE period_id = ?", (period[0],)) or 0
        )
        if snapshot_fund_count != fund_count or snapshot_gp_count != gp_count:
            raise ReadinessError(
                "Latest FSS market summary disagrees with snapshots: "
                f"summary=({fund_count} funds, {gp_count} GPs), "
                f"snapshots=({snapshot_fund_count} funds, {snapshot_gp_count} GPs)"
            )

        ranking_table = f"analytics_gp_ranking_{safe_table_suffix(latest['period_label'])}"
        if not object_exists(conn, ranking_table):
            raise ReadinessError(f"Latest FSS GP ranking table is missing: {ranking_table}")
        ranking_count = int(scalar(conn, f"SELECT COUNT(*) FROM {ranking_table}") or 0)
        if ranking_count != gp_count:
            raise ReadinessError(f"Latest FSS GP ranking is incomplete: expected {gp_count}, found {ranking_count}")
        top_rank = scalar(conn, f"SELECT MIN(rank) FROM {ranking_table}")
        if int(top_rank or 0) != 1:
            raise ReadinessError("Latest FSS GP ranking does not start at rank 1")
    finally:
        conn.close()

    return {
        "latest_period": latest["period_label"],
        "as_of_date": latest["as_of_date"],
        "source_id": latest["source_id"],
        "source_age_days": age_days,
        "registry_rows": len(rows),
        "fund_count": fund_count,
        "primary_gp_count": gp_count,
        "commitment_amount_krw_mn": commitment,
        "ranking_count": ranking_count,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate FSS PEF statistical readiness")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--expected-latest-period")
    parser.add_argument("--max-source-age-days", type=int, default=DEFAULT_MAX_SOURCE_AGE_DAYS)
    args = parser.parse_args(argv)
    try:
        summary = check_fss_statistics(
            db_path=args.db,
            registry_path=args.registry,
            expected_latest_period=args.expected_latest_period,
            max_source_age_days=args.max_source_age_days,
        )
    except (OSError, sqlite3.Error, ValueError, ReadinessError) as exc:
        print(f"FAIL FSS statistics readiness: {exc}")
        return 1
    print("PASS FSS statistics readiness")
    for key, value in summary.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
