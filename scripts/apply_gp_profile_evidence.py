#!/usr/bin/env python
"""Apply source-backed GP profile evidence to the GP profile master.

Input is a field-level CSV. The script updates only fields that have explicit
source evidence and records every applied value in gp_profile_source. Identifier
fields are also mirrored into gp_identifier for matching and future automation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from build_gp_profile_master import (
    DEFAULT_DB,
    ensure_tables,
)
from ingest_fss_pef import normalize_name


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = REPO_ROOT / "data" / "gp_profile_evidence.csv"

ALLOWED_PROFILE_FIELDS = {
    "company_category",
    "display_name_ko",
    "legal_entity_name_ko",
    "legal_entity_name_en",
    "homepage_url",
    "established_date",
    "firm_founded_date",
    "firm_founded_year",
    "firm_description",
    "representative_name",
    "headquarters_address",
    "phone_number",
    "contact_email",
    "business_registration_number",
    "corporate_registration_number",
    "financial_registration_number",
    "license_type",
    "license_status",
    "primary_source_url",
    "source_note",
    "research_note",
}

IDENTIFIER_FIELDS = {
    "business_registration_number": "business_registration_number",
    "corporate_registration_number": "corporate_registration_number",
    "financial_registration_number": "financial_registration_number",
}

OFFICIAL_SOURCE_GRADES = {
    "OFFICIAL_COMPANY_WEBSITE",
    "OFFICIAL_REGULATORY_SOURCE",
    "OFFICIAL_PUBLIC_INSTITUTION",
    "OFFICIAL_EXCHANGE_DISCLOSURE",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", value or "")


def source_hash(*parts: object) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def read_evidence(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [{key: (value or "").strip() for key, value in row.items()} for row in rows]


def resolve_gp(conn: sqlite3.Connection, row: dict[str, str]) -> tuple[int, str, str]:
    standard_name = row.get("standard_gp_name", "")
    standard_name_norm = normalize_name(standard_name)
    gp_rows = conn.execute(
        """
        SELECT source_gp_id, gp_profile_id, standard_gp_name
        FROM gp_profile
        WHERE gp_name_norm = ?
        """,
        (standard_name_norm,),
    ).fetchall()
    if not gp_rows:
        raise ValueError(
            "Cannot resolve GP evidence by standard_gp_name. "
            "source_gp_id is an ingestion-local value and must not be used as a stable key: "
            f"{row}"
        )
    if len(gp_rows) != 1:
        candidates = ", ".join(
            f"{candidate[0]}:{candidate[2]}" for candidate in gp_rows
        )
        raise ValueError(
            "Ambiguous GP evidence binding by standard_gp_name. "
            f"standard_gp_name={standard_name!r} candidates={candidates}"
        )
    gp_row = gp_rows[0]
    return int(gp_row[0]), str(gp_row[1]), str(gp_row[2])


def validate_row(row: dict[str, str]) -> None:
    standard_gp_name = row.get("standard_gp_name", "")
    field_name = row.get("field_name", "")
    field_value = row.get("field_value", "")
    source_url = row.get("source_url", "")
    source_grade = row.get("source_grade", "")
    if not field_name:
        raise ValueError(f"Missing field_name: {row}")
    if not standard_gp_name:
        raise ValueError(f"Missing standard_gp_name: {row}")
    if field_name not in ALLOWED_PROFILE_FIELDS:
        raise ValueError(f"Unsupported field_name={field_name}: {row}")
    if not field_value:
        raise ValueError(f"Missing field_value for {field_name}: {row}")
    if not source_url:
        raise ValueError(f"Missing source_url for {field_name}: {row}")
    if not source_grade:
        raise ValueError(f"Missing source_grade for {field_name}: {row}")


def validate_no_conflicting_values(
    resolved_rows: list[tuple[int, str, str, dict[str, str]]],
) -> None:
    values_by_field: dict[tuple[int, str], dict[str, set[str]]] = {}
    names_by_gp_id: dict[int, str] = {}
    for gp_id, _gp_profile_id, standard_gp_name, row in resolved_rows:
        field_name = row["field_name"]
        field_value = row["field_value"]
        names_by_gp_id[gp_id] = standard_gp_name
        source_titles = values_by_field.setdefault((gp_id, field_name), {}).setdefault(
            field_value,
            set(),
        )
        source_titles.add(row.get("source_title", ""))

    conflicts: list[str] = []
    for (gp_id, field_name), values in sorted(values_by_field.items()):
        if len(values) <= 1:
            continue
        value_list = "; ".join(
            f"{value} [{', '.join(sorted(title for title in titles if title))}]"
            for value, titles in sorted(values.items())
        )
        conflicts.append(
            f"source_gp_id={gp_id} standard_gp_name={names_by_gp_id.get(gp_id, '')} "
            f"field_name={field_name}: {value_list}"
        )
    if conflicts:
        raise ValueError(
            "Conflicting active GP profile evidence rows found. "
            "Mark superseded rows with skip=1 or move imprecise firm facts "
            "to firm_founded_* fields:\n"
            + "\n".join(conflicts)
        )


def value_for_db(field_name: str, field_value: str) -> object:
    if field_name == "firm_founded_year":
        return int(field_value)
    return field_value


def upsert_identifier(
    conn: sqlite3.Connection,
    gp_id: int,
    gp_profile_id: str,
    row: dict[str, str],
    applied_at: str,
) -> None:
    field_name = row["field_name"]
    identifier_type = IDENTIFIER_FIELDS[field_name]
    identifier_value = row["field_value"]
    normalized = normalize_identifier(identifier_value)
    conn.execute(
        """
        INSERT INTO gp_identifier (
            source_gp_id,
            gp_profile_id,
            identifier_type,
            identifier_value,
            normalized_identifier_value,
            issuer,
            source_url,
            source_title,
            source_grade,
            verification_status,
            verified_at,
            notes,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_gp_id, identifier_type, identifier_value) DO UPDATE SET
            normalized_identifier_value = excluded.normalized_identifier_value,
            issuer = excluded.issuer,
            source_url = excluded.source_url,
            source_title = excluded.source_title,
            source_grade = excluded.source_grade,
            verification_status = excluded.verification_status,
            verified_at = excluded.verified_at,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """,
        (
            gp_id,
            gp_profile_id,
            identifier_type,
            identifier_value,
            normalized,
            row.get("issuer", ""),
            row.get("source_url", ""),
            row.get("source_title", ""),
            row.get("source_grade", ""),
            row.get("verification_status", "verified"),
            row.get("verified_at", "") or applied_at,
            row.get("notes", ""),
            applied_at,
            applied_at,
        ),
    )


def upsert_source(
    conn: sqlite3.Connection,
    gp_id: int,
    gp_profile_id: str,
    standard_gp_name: str,
    row: dict[str, str],
    applied_at: str,
) -> None:
    evidence_id = "manual_" + source_hash(
        gp_id,
        row.get("field_name", ""),
        row.get("field_value", ""),
        row.get("source_url", ""),
    )
    evidence_scope = row.get("evidence_scope", "") or row["field_name"]
    notes = row.get("notes", "")
    if standard_gp_name and standard_gp_name not in notes:
        notes = (notes + " " if notes else "") + f"GP={standard_gp_name}"
    conn.execute(
        """
        INSERT INTO gp_profile_source (
            source_evidence_id,
            source_gp_id,
            gp_profile_id,
            source_type,
            source_title,
            source_url,
            source_grade,
            evidence_scope,
            evidence_value,
            evidence_date,
            verification_status,
            captured_at,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_evidence_id) DO UPDATE SET
            source_type = excluded.source_type,
            source_title = excluded.source_title,
            source_url = excluded.source_url,
            source_grade = excluded.source_grade,
            evidence_scope = excluded.evidence_scope,
            evidence_value = excluded.evidence_value,
            evidence_date = excluded.evidence_date,
            verification_status = excluded.verification_status,
            captured_at = excluded.captured_at,
            notes = excluded.notes
        """,
        (
            evidence_id,
            gp_id,
            gp_profile_id,
            row.get("source_type", "manual_profile_evidence"),
            row.get("source_title", ""),
            row.get("source_url", ""),
            row.get("source_grade", ""),
            evidence_scope,
            row.get("field_value", ""),
            row.get("evidence_date", ""),
            row.get("verification_status", "verified"),
            applied_at,
            notes,
        ),
    )


def status_for_gp(rows: list[dict[str, str]]) -> tuple[str, str]:
    fields = {row["field_name"] for row in rows}
    grades = {row.get("source_grade", "") for row in rows}
    identifier_rows = [row for row in rows if row["field_name"] in IDENTIFIER_FIELDS]
    if identifier_rows and any(
        row.get("source_grade", "") in OFFICIAL_SOURCE_GRADES for row in identifier_rows
    ):
        return "identifier_verified", "IDENTIFIER_VERIFIED"
    if grades & OFFICIAL_SOURCE_GRADES:
        return "official_source_partial", "OFFICIAL_SOURCE_VERIFIED"
    return "supporting_source_partial", "SUPPORTING_SOURCE_ONLY"


def clear_existing_manual_data(
    conn: sqlite3.Connection,
    applied_at: str,
) -> None:
    reset_fields = ", ".join(f"{field} = NULL" for field in sorted(ALLOWED_PROFILE_FIELDS))
    conn.execute(
        """
        DELETE FROM gp_profile_source
        WHERE source_evidence_id LIKE 'manual_%'
        """
    )
    conn.execute("DELETE FROM gp_identifier")
    conn.execute(
        f"""
        UPDATE gp_profile
        SET
            {reset_fields},
            profile_status = 'raw_fss_name_only',
            verification_level = 'FSS_NAME_ONLY',
            primary_source_url = NULL,
            source_note = NULL,
            updated_at = ?
        """,
        (applied_at,),
    )


def apply(db_path: Path, evidence_path: Path) -> dict[str, int]:
    rows = read_evidence(evidence_path)
    conn = sqlite3.connect(db_path)
    try:
        ensure_tables(conn)
        applied_at = now_iso()
        grouped: dict[int, list[dict[str, str]]] = {}
        applied_count = 0
        identifier_count = 0
        resolved_rows: list[tuple[int, str, str, dict[str, str]]] = []

        for row in rows:
            if row.get("skip", "").upper() in {"1", "Y", "YES", "TRUE"}:
                continue
            validate_row(row)
            gp_id, gp_profile_id, standard_gp_name = resolve_gp(conn, row)
            resolved_rows.append((gp_id, gp_profile_id, standard_gp_name, row))

        validate_no_conflicting_values(resolved_rows)
        clear_existing_manual_data(conn, applied_at)

        for gp_id, gp_profile_id, standard_gp_name, row in resolved_rows:
            if row.get("skip", "").upper() in {"1", "Y", "YES", "TRUE"}:
                continue
            field_name = row["field_name"]
            conn.execute(
                f"UPDATE gp_profile SET {field_name} = ?, updated_at = ? WHERE source_gp_id = ?",
                (value_for_db(field_name, row["field_value"]), applied_at, gp_id),
            )
            upsert_source(conn, gp_id, gp_profile_id, standard_gp_name, row, applied_at)
            if field_name in IDENTIFIER_FIELDS:
                upsert_identifier(conn, gp_id, gp_profile_id, row, applied_at)
                identifier_count += 1
            grouped.setdefault(gp_id, []).append(row)
            applied_count += 1

        for gp_id, gp_rows in grouped.items():
            profile_status, verification_level = status_for_gp(gp_rows)
            primary_source = next(
                (row["source_url"] for row in gp_rows if row.get("source_url")),
                "",
            )
            conn.execute(
                """
                UPDATE gp_profile
                SET
                    profile_status = ?,
                    verification_level = ?,
                    primary_source_url = COALESCE(NULLIF(primary_source_url, ''), ?),
                    source_note = COALESCE(NULLIF(source_note, ''), ?),
                    updated_at = ?
                WHERE source_gp_id = ?
                """,
                (
                    profile_status,
                    verification_level,
                    primary_source,
                    "Updated from source-backed gp_profile_evidence.csv",
                    applied_at,
                    gp_id,
                ),
            )

        conn.commit()
        return {
            "evidence_rows": len(rows),
            "applied_rows": applied_count,
            "updated_gp_profiles": len(grouped),
            "identifier_rows_applied": identifier_count,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply source-backed GP profile evidence")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()

    counts = apply(args.db, args.evidence)
    for key, value in counts.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
