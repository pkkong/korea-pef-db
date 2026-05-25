#!/usr/bin/env python
"""Apply externally verified GP alias merges to the FSS PEF SQLite DB.

Only rows marked MERGE_ALIAS in gp_alias_external_verification are hard-merged.
Raw FSS GP names remain in fund_period_snapshot.gp_name_raw, and removed gp_id
values are preserved in gp_house_alias for auditability.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_RULES = REPO_ROOT / "data" / "gp_alias_merge_rules.csv"


@dataclass(frozen=True)
class Period:
    period_id: str
    as_of_date: str


@dataclass(frozen=True)
class MergeGroup:
    alias_candidate_group_id: str
    standard_name: str
    relationship_type: str
    evidence_summary: str
    primary_sources: str
    candidate_gp_ids: list[int]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gp_alias_merge_rule (
            rule_id TEXT PRIMARY KEY,
            canonical_gp_name TEXT NOT NULL,
            alias_gp_name TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            verification_decision TEXT NOT NULL,
            evidence_summary TEXT NOT NULL,
            primary_sources TEXT NOT NULL,
            loaded_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gp_house_alias (
            alias_gp_id INTEGER PRIMARY KEY,
            canonical_gp_id INTEGER NOT NULL,
            alias_gp_name TEXT NOT NULL,
            alias_gp_name_norm TEXT NOT NULL,
            canonical_gp_name TEXT NOT NULL,
            alias_candidate_group_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            verification_decision TEXT NOT NULL,
            evidence_summary TEXT NOT NULL,
            primary_sources TEXT NOT NULL,
            merged_at TEXT NOT NULL,
            FOREIGN KEY (canonical_gp_id) REFERENCES gp_house(gp_id)
        )
        """
    )


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def load_periods(conn: sqlite3.Connection) -> dict[str, Period]:
    return {
        row[0]: Period(period_id=row[0], as_of_date=row[1] or "")
        for row in conn.execute("SELECT period_id, as_of_date FROM reporting_period")
    }


def min_period(left: str | None, right: str | None, periods: dict[str, Period]) -> str | None:
    if not left:
        return right
    if not right:
        return left
    return left if periods.get(left, Period(left, "")).as_of_date <= periods.get(right, Period(right, "")).as_of_date else right


def max_period(left: str | None, right: str | None, periods: dict[str, Period]) -> str | None:
    if not left:
        return right
    if not right:
        return left
    return left if periods.get(left, Period(left, "")).as_of_date >= periods.get(right, Period(right, "")).as_of_date else right


def find_gp_id_by_name(conn: sqlite3.Connection, gp_name: str) -> int | None:
    row = conn.execute("SELECT gp_id FROM gp_house WHERE gp_name = ?", (gp_name,)).fetchone()
    return int(row[0]) if row else None


def alias_already_merged(conn: sqlite3.Connection, alias_gp_name: str, canonical_gp_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM gp_house_alias
        WHERE alias_gp_name = ? AND canonical_gp_name = ?
        """,
        (alias_gp_name, canonical_gp_name),
    ).fetchone()
    return row is not None


def load_merge_groups(conn: sqlite3.Connection, rules_path: Path) -> list[MergeGroup]:
    if not rules_path.exists():
        raise RuntimeError(f"Missing GP alias merge rules: {rules_path}")

    groups: list[MergeGroup] = []
    with rules_path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("verification_decision") != "MERGE_ALIAS":
                continue
            canonical_name = (row.get("canonical_gp_name") or "").strip()
            alias_name = (row.get("alias_gp_name") or "").strip()
            if not canonical_name or not alias_name or canonical_name == alias_name:
                continue
            rule_id = row.get("rule_id") or f"rule_{alias_name}_to_{canonical_name}"
            relationship_type = row.get("relationship_type") or "alias"
            evidence_summary = row.get("evidence_summary") or ""
            primary_sources = row.get("primary_sources") or ""

            conn.execute(
                """
                INSERT OR REPLACE INTO gp_alias_merge_rule(
                    rule_id, canonical_gp_name, alias_gp_name, relationship_type,
                    verification_decision, evidence_summary, primary_sources, loaded_at
                )
                VALUES (?, ?, ?, ?, 'MERGE_ALIAS', ?, ?, ?)
                """,
                (
                    rule_id,
                    canonical_name,
                    alias_name,
                    relationship_type,
                    evidence_summary,
                    primary_sources,
                    now_iso(),
                ),
            )

            canonical_gp_id = find_gp_id_by_name(conn, canonical_name)
            alias_gp_id = find_gp_id_by_name(conn, alias_name)
            if canonical_gp_id is None:
                raise RuntimeError(f"Canonical GP not found for rule {row.get('rule_id')}: {canonical_name}")
            if alias_gp_id is None:
                if alias_already_merged(conn, alias_name, canonical_name):
                    continue
                continue

            groups.append(
                MergeGroup(
                    alias_candidate_group_id=rule_id,
                    standard_name=canonical_name,
                    relationship_type=relationship_type,
                    evidence_summary=evidence_summary,
                    primary_sources=primary_sources,
                    candidate_gp_ids=[canonical_gp_id, alias_gp_id],
                )
            )
    return groups


def find_canonical_gp_id(conn: sqlite3.Connection, group: MergeGroup) -> int:
    placeholders = ", ".join("?" for _ in group.candidate_gp_ids)
    rows = conn.execute(
        f"""
        SELECT gp_id, gp_name
        FROM gp_house
        WHERE gp_id IN ({placeholders})
        """,
        group.candidate_gp_ids,
    ).fetchall()
    if not rows:
        raise RuntimeError(f"No candidate gp_house rows found for {group.alias_candidate_group_id}")

    for gp_id, gp_name in rows:
        if gp_name == group.standard_name:
            return int(gp_id)
    for gp_id, gp_name in rows:
        if group.standard_name in gp_name or gp_name in group.standard_name:
            return int(gp_id)
    return int(sorted(row[0] for row in rows)[0])


def merge_affiliations(conn: sqlite3.Connection, alias_gp_id: int, canonical_gp_id: int, periods: dict[str, Period]) -> None:
    rows = conn.execute(
        """
        SELECT fund_id, role, first_seen_period_id, last_seen_period_id
        FROM fund_gp_affiliation
        WHERE gp_id = ?
        """,
        (alias_gp_id,),
    ).fetchall()
    for fund_id, role, first_seen, last_seen in rows:
        existing = conn.execute(
            """
            SELECT first_seen_period_id, last_seen_period_id
            FROM fund_gp_affiliation
            WHERE fund_id = ? AND gp_id = ? AND role = ?
            """,
            (fund_id, canonical_gp_id, role),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE fund_gp_affiliation
                SET first_seen_period_id = ?, last_seen_period_id = ?
                WHERE fund_id = ? AND gp_id = ? AND role = ?
                """,
                (
                    min_period(existing[0], first_seen, periods),
                    max_period(existing[1], last_seen, periods),
                    fund_id,
                    canonical_gp_id,
                    role,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO fund_gp_affiliation(fund_id, gp_id, role, first_seen_period_id, last_seen_period_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (fund_id, canonical_gp_id, role, first_seen, last_seen),
            )
    conn.execute("DELETE FROM fund_gp_affiliation WHERE gp_id = ?", (alias_gp_id,))


def merge_group(conn: sqlite3.Connection, group: MergeGroup, periods: dict[str, Period]) -> tuple[int, int]:
    canonical_gp_id = find_canonical_gp_id(conn, group)
    canonical = conn.execute(
        """
        SELECT gp_id, gp_name, gp_name_norm, first_seen_period_id, last_seen_period_id
        FROM gp_house
        WHERE gp_id = ?
        """,
        (canonical_gp_id,),
    ).fetchone()
    if canonical is None:
        raise RuntimeError(f"Canonical gp_id missing: {canonical_gp_id}")

    first_seen = canonical[3]
    last_seen = canonical[4]
    merged_count = 0
    merged_at = now_iso()

    for alias_gp_id in group.candidate_gp_ids:
        alias = conn.execute(
            """
            SELECT gp_id, gp_name, gp_name_norm, first_seen_period_id, last_seen_period_id
            FROM gp_house
            WHERE gp_id = ?
            """,
            (alias_gp_id,),
        ).fetchone()
        if alias is None:
            continue
        first_seen = min_period(first_seen, alias[3], periods)
        last_seen = max_period(last_seen, alias[4], periods)

        if alias_gp_id == canonical_gp_id:
            continue

        conn.execute(
            """
            INSERT OR REPLACE INTO gp_house_alias(
                alias_gp_id, canonical_gp_id, alias_gp_name, alias_gp_name_norm,
                canonical_gp_name, alias_candidate_group_id, relationship_type,
                verification_decision, evidence_summary, primary_sources, merged_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'MERGE_ALIAS', ?, ?, ?)
            """,
            (
                alias_gp_id,
                canonical_gp_id,
                alias[1],
                alias[2],
                group.standard_name,
                group.alias_candidate_group_id,
                group.relationship_type,
                group.evidence_summary,
                group.primary_sources,
                merged_at,
            ),
        )

        merge_affiliations(conn, alias_gp_id, canonical_gp_id, periods)
        conn.execute("UPDATE fund_period_snapshot SET gp_id = ? WHERE gp_id = ?", (canonical_gp_id, alias_gp_id))
        conn.execute("UPDATE fund_event SET gp_id = ? WHERE gp_id = ?", (canonical_gp_id, alias_gp_id))
        conn.execute("DELETE FROM gp_house WHERE gp_id = ?", (alias_gp_id,))
        merged_count += 1

    conn.execute(
        """
        UPDATE gp_house
        SET gp_name = ?, gp_name_norm = ?, first_seen_period_id = ?, last_seen_period_id = ?, updated_at = CURRENT_TIMESTAMP
        WHERE gp_id = ?
        """,
        (group.standard_name, canonical[2], first_seen, last_seen, canonical_gp_id),
    )
    return canonical_gp_id, merged_count


def apply_merges(db_path: Path, rules_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_tables(conn)
        periods = load_periods(conn)
        groups = load_merge_groups(conn, rules_path)
        merged_alias_rows = 0
        for group in groups:
            _canonical_gp_id, merged_count = merge_group(conn, group, periods)
            merged_alias_rows += merged_count
        conn.commit()
        return {"merge_groups": len(groups), "merged_alias_gp_rows": merged_alias_rows}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply externally verified GP alias merges")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    args = parser.parse_args()

    counts = apply_merges(args.db, args.rules)
    for key, value in counts.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
