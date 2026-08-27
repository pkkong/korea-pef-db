#!/usr/bin/env python
"""Block GP publishing when canonical profile evidence is missing or stale."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from apply_gp_profile_evidence import (
    DEFAULT_EVIDENCE,
    DEFAULT_DB,
    read_evidence,
    resolve_gp,
    source_hash,
    validate_row,
)


def active_rows(evidence_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in read_evidence(evidence_path):
        if row.get("skip", "").upper() in {"1", "Y", "YES", "TRUE"}:
            continue
        validate_row(row)
        rows.append(row)
    return rows


def check(db_path: Path, evidence_path: Path) -> dict[str, int]:
    rows = active_rows(evidence_path)
    conn = sqlite3.connect(db_path)
    try:
        expected_sources: dict[str, tuple[int, str, dict[str, str]]] = {}
        expected_gp_ids: set[int] = set()
        for row in rows:
            gp_id, gp_profile_id, _standard_gp_name = resolve_gp(conn, row)
            evidence_id = "manual_" + source_hash(
                gp_id,
                row["field_name"],
                row["field_value"],
                row["source_url"],
            )
            if evidence_id in expected_sources:
                raise ValueError(f"Duplicate active GP evidence row: {row}")
            expected_sources[evidence_id] = (gp_id, gp_profile_id, row)
            expected_gp_ids.add(gp_id)

        actual_sources = {
            row[0]: (int(row[1]), str(row[2]))
            for row in conn.execute(
                """
                SELECT source_evidence_id, source_gp_id, gp_profile_id
                FROM gp_profile_source
                WHERE source_evidence_id LIKE 'manual_%'
                """
            ).fetchall()
        }

        expected_ids = set(expected_sources)
        actual_ids = set(actual_sources)
        missing_ids = sorted(expected_ids - actual_ids)
        stale_ids = sorted(actual_ids - expected_ids)
        mismatched_ids = sorted(
            evidence_id
            for evidence_id in expected_ids & actual_ids
            if actual_sources[evidence_id]
            != expected_sources[evidence_id][:2]
        )
        if missing_ids or stale_ids or mismatched_ids:
            raise ValueError(
                "GP profile evidence is not synchronized with the canonical CSV. "
                f"missing={len(missing_ids)} stale={len(stale_ids)} "
                f"mismatched={len(mismatched_ids)}"
            )

        placeholders = ", ".join("?" for _ in expected_gp_ids)
        profile_rows = conn.execute(
            f"""
            SELECT source_gp_id, verification_level
            FROM gp_profile
            WHERE source_gp_id IN ({placeholders})
            """,
            tuple(sorted(expected_gp_ids)),
        ).fetchall()
        verification_by_gp_id = {int(row[0]): str(row[1]) for row in profile_rows}
        unverified = sorted(
            gp_id
            for gp_id in expected_gp_ids
            if verification_by_gp_id.get(gp_id) in {None, "", "FSS_NAME_ONLY"}
        )
        if unverified:
            raise ValueError(
                "Source-backed GP profiles remain unverified: "
                + ", ".join(str(gp_id) for gp_id in unverified)
            )

        return {
            "active_evidence_rows": len(rows),
            "source_backed_gp_profiles": len(expected_gp_ids),
            "manual_evidence_rows": len(actual_sources),
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check GP profile evidence readiness")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()

    counts = check(args.db, args.evidence)
    for key, value in counts.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
