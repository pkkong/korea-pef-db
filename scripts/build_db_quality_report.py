#!/usr/bin/env python
"""Build DB quality and coverage reports for the Private Equity DB."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from build_gp_master_candidates import write_xlsx


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_OUT = REPO_ROOT / "exports" / "db_quality_report.xlsx"
DEFAULT_CSV_PREFIX = REPO_ROOT / "exports" / "db_quality"
DEFAULT_TOP_N = 100


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch_dicts(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
    cur = conn.execute(query, params)
    headers = [desc[0] for desc in cur.description]
    return [dict(zip(headers, row)) for row in cur.fetchall()]


def scalar(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = (), default: object = "") -> object:
    row = conn.execute(query, params).fetchone()
    if row is None:
        return default
    return row[0]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def write_csv_with_headers(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows([{column: row.get(column, "") for column in columns} for row in rows])


def rows_for_xlsx(rows: list[dict[str, object]], columns: list[str]) -> list[dict[str, object]]:
    if rows:
        return rows
    return [{column: "" for column in columns}]


def is_filled(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.lower() != "unknown"


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, "", 0, "0"):
        return False
    return True


def pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((part / total) * 100.0, 2)


def int_or_large(value: object) -> int:
    if value in (None, ""):
        return 999999
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 999999
    if parsed <= 0:
        return 999999
    return parsed


def assert_required_tables(conn: sqlite3.Connection) -> None:
    required = [
        "reporting_period",
        "source_document",
        "fund_master",
        "gp_profile",
        "gp_profile_source",
        "gp_identifier",
        "gp_profile_research_worklist",
    ]
    missing = [table for table in required if not table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "Missing required tables for quality report: "
            + ", ".join(missing)
            + ". Run the upstream build scripts first."
        )


def load_profiles(conn: sqlite3.Connection) -> list[dict[str, object]]:
    return fetch_dicts(
        conn,
        """
        SELECT
            p.*,
            COALESCE(w.worklist_rank, 0) AS worklist_rank,
            COALESCE(w.fields_to_fill, '') AS fields_to_fill,
            COALESCE(w.research_priority_reason, '') AS research_priority_reason,
            COALESCE(src.manual_evidence_count, 0) AS manual_evidence_count,
            COALESCE(src.total_evidence_count, 0) AS total_evidence_count,
            COALESCE(idf.identifier_row_count, 0) AS identifier_row_count
        FROM gp_profile p
        LEFT JOIN gp_profile_research_worklist w
            ON w.source_gp_id = p.source_gp_id
        LEFT JOIN (
            SELECT
                source_gp_id,
                SUM(CASE WHEN source_evidence_id LIKE 'manual_%' THEN 1 ELSE 0 END) AS manual_evidence_count,
                COUNT(*) AS total_evidence_count
            FROM gp_profile_source
            GROUP BY source_gp_id
        ) src
            ON src.source_gp_id = p.source_gp_id
        LEFT JOIN (
            SELECT source_gp_id, COUNT(*) AS identifier_row_count
            FROM gp_identifier
            GROUP BY source_gp_id
        ) idf
            ON idf.source_gp_id = p.source_gp_id
        ORDER BY
            CASE
                WHEN COALESCE(w.worklist_rank, 0) > 0 THEN w.worklist_rank
                ELSE 999999
            END,
            CASE
                WHEN COALESCE(p.latest_primary_rank, 0) > 0 THEN p.latest_primary_rank
                ELSE 999999
            END,
            CASE
                WHEN COALESCE(p.cumulative_primary_rank, 0) > 0 THEN p.cumulative_primary_rank
                ELSE 999999
            END,
            p.standard_gp_name
        """,
    )


def build_overview_rows(conn: sqlite3.Connection, profiles: list[dict[str, object]], generated_at: str) -> list[dict[str, object]]:
    latest_period = conn.execute(
        """
        SELECT period_label, as_of_date
        FROM reporting_period
        ORDER BY as_of_date DESC, period_id DESC
        LIMIT 1
        """
    ).fetchone()
    latest_source = conn.execute(
        """
        SELECT period_label, as_of_date, title, source_url
        FROM source_document
        ORDER BY as_of_date DESC, rowid DESC
        LIMIT 1
        """
    ).fetchone()

    verified_profiles = sum(1 for profile in profiles if str(profile.get("verification_level") or "") != "FSS_NAME_ONLY")
    identifier_gp_count = sum(1 for profile in profiles if int(profile.get("identifier_row_count") or 0) > 0)
    manual_evidence_gp_count = sum(1 for profile in profiles if int(profile.get("manual_evidence_count") or 0) > 0)
    latest_active_gp_count = sum(1 for profile in profiles if truthy(profile.get("active_in_latest_period")))

    return [
        {
            "metric": "generated_at",
            "value": generated_at,
            "notes": "UTC timestamp for this quality report build.",
        },
        {
            "metric": "latest_period_label",
            "value": latest_period[0] if latest_period else "",
            "notes": "Latest reporting period available in the DB.",
        },
        {
            "metric": "latest_period_as_of_date",
            "value": latest_period[1] if latest_period else "",
            "notes": "As-of date for the latest reporting period.",
        },
        {
            "metric": "gp_profile_count",
            "value": len(profiles),
            "notes": "Rows currently present in gp_profile.",
        },
        {
            "metric": "gp_verified_profile_count",
            "value": verified_profiles,
            "notes": "Profiles whose verification level is above raw FSS name only.",
        },
        {
            "metric": "gp_with_identifier_count",
            "value": identifier_gp_count,
            "notes": "Distinct GP profiles with at least one identifier row.",
        },
        {
            "metric": "gp_with_manual_evidence_count",
            "value": manual_evidence_gp_count,
            "notes": "Distinct GP profiles with at least one manual source-backed evidence row.",
        },
        {
            "metric": "gp_active_latest_period_count",
            "value": latest_active_gp_count,
            "notes": "GP profiles marked active in the latest period.",
        },
        {
            "metric": "fund_master_count",
            "value": scalar(conn, "SELECT COUNT(*) FROM fund_master", default=0),
            "notes": "Rows currently present in fund_master.",
        },
        {
            "metric": "fund_active_latest_period_count",
            "value": scalar(conn, "SELECT COUNT(*) FROM fund_master WHERE active_in_latest_period = 1", default=0),
            "notes": "Funds active in the latest observed period.",
        },
        {
            "metric": "gp_identifier_row_count",
            "value": scalar(conn, "SELECT COUNT(*) FROM gp_identifier", default=0),
            "notes": "Total identifier rows across all GP profiles.",
        },
        {
            "metric": "gp_profile_source_row_count",
            "value": scalar(conn, "SELECT COUNT(*) FROM gp_profile_source", default=0),
            "notes": "Total evidence rows across automatic FSS and manual sources.",
        },
        {
            "metric": "gp_profile_manual_source_row_count",
            "value": scalar(
                conn,
                "SELECT COUNT(*) FROM gp_profile_source WHERE source_evidence_id LIKE 'manual_%'",
                default=0,
            ),
            "notes": "Manual source-backed evidence rows only.",
        },
        {
            "metric": "source_document_count",
            "value": scalar(conn, "SELECT COUNT(*) FROM source_document", default=0),
            "notes": "Registered raw source documents in the DB.",
        },
        {
            "metric": "latest_source_document_title",
            "value": latest_source[2] if latest_source else "",
            "notes": latest_source[3] if latest_source else "",
        },
        {
            "metric": "latest_source_document_period",
            "value": latest_source[0] if latest_source else "",
            "notes": latest_source[1] if latest_source else "",
        },
    ]


def build_coverage_rows(profiles: list[dict[str, object]]) -> list[dict[str, object]]:
    metrics = [
        (
            "profile_verified",
            "Verification above raw FSS",
            lambda profile: str(profile.get("verification_level") or "") != "FSS_NAME_ONLY",
            "verification_level is not FSS_NAME_ONLY",
        ),
        (
            "manual_evidence",
            "Any manual evidence",
            lambda profile: int(profile.get("manual_evidence_count") or 0) > 0,
            "At least one manual source-backed evidence row exists",
        ),
        (
            "any_identifier",
            "Any identifier",
            lambda profile: int(profile.get("identifier_row_count") or 0) > 0,
            "At least one gp_identifier row exists",
        ),
        (
            "company_category",
            "Company category",
            lambda profile: is_filled(profile.get("company_category")),
            "company_category is filled and not unknown",
        ),
        (
            "homepage_url",
            "Homepage URL",
            lambda profile: is_filled(profile.get("homepage_url")),
            "homepage_url is filled",
        ),
        (
            "legal_entity_name_ko",
            "Legal entity name KO",
            lambda profile: is_filled(profile.get("legal_entity_name_ko")),
            "legal_entity_name_ko is filled",
        ),
        (
            "legal_entity_name_en",
            "Legal entity name EN",
            lambda profile: is_filled(profile.get("legal_entity_name_en")),
            "legal_entity_name_en is filled",
        ),
        (
            "established_date",
            "Established date",
            lambda profile: is_filled(profile.get("established_date")),
            "established_date is filled",
        ),
        (
            "firm_founded_year",
            "Firm founded year",
            lambda profile: is_filled(profile.get("firm_founded_year")),
            "firm_founded_year is filled",
        ),
        (
            "representative_name",
            "Representative name",
            lambda profile: is_filled(profile.get("representative_name")),
            "representative_name is filled",
        ),
        (
            "headquarters_address",
            "Headquarters address",
            lambda profile: is_filled(profile.get("headquarters_address")),
            "headquarters_address is filled",
        ),
        (
            "phone_number",
            "Phone number",
            lambda profile: is_filled(profile.get("phone_number")),
            "phone_number is filled",
        ),
        (
            "contact_email",
            "Contact email",
            lambda profile: is_filled(profile.get("contact_email")),
            "contact_email is filled",
        ),
        (
            "business_registration_number",
            "Business registration number",
            lambda profile: is_filled(profile.get("business_registration_number")),
            "business_registration_number is filled",
        ),
        (
            "corporate_registration_number",
            "Corporate registration number",
            lambda profile: is_filled(profile.get("corporate_registration_number")),
            "corporate_registration_number is filled",
        ),
        (
            "financial_registration_number",
            "Financial registration number",
            lambda profile: is_filled(profile.get("financial_registration_number")),
            "financial_registration_number is filled",
        ),
        (
            "primary_source_url",
            "Primary source URL",
            lambda profile: is_filled(profile.get("primary_source_url")),
            "primary_source_url is filled",
        ),
    ]

    populations = [
        (
            "all_gp",
            "All GP profiles",
            lambda profile: True,
        ),
        (
            "active_latest_gp",
            "Active GP in latest period",
            lambda profile: truthy(profile.get("active_in_latest_period")),
        ),
        (
            "top50_latest_rank",
            "Top 50 by latest primary rank",
            lambda profile: int_or_large(profile.get("latest_primary_rank")) <= 50,
        ),
        (
            "top50_cumulative_rank",
            "Top 50 by cumulative primary rank",
            lambda profile: int_or_large(profile.get("cumulative_primary_rank")) <= 50,
        ),
        (
            "worklist_top50",
            "Top 50 GP profile research worklist",
            lambda profile: int_or_large(profile.get("worklist_rank")) <= 50,
        ),
    ]

    rows: list[dict[str, object]] = []
    for population_key, population_label, population_filter in populations:
        members = [profile for profile in profiles if population_filter(profile)]
        total_count = len(members)
        for metric_key, metric_label, metric_filter, definition in metrics:
            filled_count = sum(1 for profile in members if metric_filter(profile))
            rows.append(
                {
                    "population_key": population_key,
                    "population_label": population_label,
                    "population_size": total_count,
                    "metric_key": metric_key,
                    "metric_label": metric_label,
                    "filled_count": filled_count,
                    "missing_count": total_count - filled_count,
                    "coverage_pct": pct(filled_count, total_count),
                    "definition": definition,
                }
            )
    return rows


def build_verification_rows(conn: sqlite3.Connection, total_gp_count: int) -> list[dict[str, object]]:
    rows = fetch_dicts(
        conn,
        """
        SELECT
            verification_level,
            profile_status,
            COUNT(*) AS gp_count
        FROM gp_profile
        GROUP BY verification_level, profile_status
        ORDER BY gp_count DESC, verification_level, profile_status
        """,
    )
    for row in rows:
        row["share_pct"] = pct(int(row["gp_count"] or 0), total_gp_count)
    return rows


def build_source_grade_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
    return fetch_dicts(
        conn,
        """
        SELECT
            CASE
                WHEN source_evidence_id LIKE 'manual_%' THEN 'manual'
                ELSE 'auto'
            END AS evidence_origin,
            source_grade,
            COUNT(*) AS evidence_count,
            COUNT(DISTINCT source_gp_id) AS gp_count
        FROM gp_profile_source
        GROUP BY evidence_origin, source_grade
        ORDER BY evidence_origin, evidence_count DESC, source_grade
        """,
    )


def build_top_gap_rows(profiles: list[dict[str, object]], top_n: int) -> list[dict[str, object]]:
    critical_fields = [
        ("company_category", "company_category"),
        ("homepage_url", "homepage_url"),
        ("legal_entity_name_ko", "legal_entity_name_ko"),
        ("legal_entity_name_en", "legal_entity_name_en"),
        ("established_date", "established_date"),
        ("business_registration_number", "business_registration_number"),
        ("corporate_registration_number", "corporate_registration_number"),
        ("representative_name", "representative_name"),
        ("headquarters_address", "headquarters_address"),
        ("phone_number", "phone_number"),
        ("primary_source_url", "primary_source_url"),
    ]

    candidates = [profile for profile in profiles if int_or_large(profile.get("worklist_rank")) <= 999998]
    if not candidates:
        candidates = profiles

    candidates = sorted(
        candidates,
        key=lambda profile: (
            int_or_large(profile.get("worklist_rank")),
            int_or_large(profile.get("latest_primary_rank")),
            int_or_large(profile.get("cumulative_primary_rank")),
            str(profile.get("standard_gp_name") or ""),
        ),
    )

    rows: list[dict[str, object]] = []
    for profile in candidates:
        missing_fields = [label for field_name, label in critical_fields if not is_filled(profile.get(field_name))]
        if not missing_fields:
            continue
        rows.append(
            {
                "worklist_rank": profile.get("worklist_rank", ""),
                "source_gp_id": profile.get("source_gp_id", ""),
                "standard_gp_name": profile.get("standard_gp_name", ""),
                "latest_primary_rank": profile.get("latest_primary_rank", ""),
                "cumulative_primary_rank": profile.get("cumulative_primary_rank", ""),
                "latest_primary_aum_proxy_krw_100mn": profile.get("latest_primary_aum_proxy_krw_100mn", ""),
                "cumulative_primary_commitment_proxy_krw_100mn": profile.get(
                    "cumulative_primary_commitment_proxy_krw_100mn",
                    "",
                ),
                "verification_level": profile.get("verification_level", ""),
                "manual_evidence_count": profile.get("manual_evidence_count", 0),
                "identifier_row_count": profile.get("identifier_row_count", 0),
                "missing_critical_field_count": len(missing_fields),
                "missing_critical_fields": "; ".join(missing_fields),
                "company_category_filled": "Y" if is_filled(profile.get("company_category")) else "",
                "homepage_url_filled": "Y" if is_filled(profile.get("homepage_url")) else "",
                "legal_entity_name_ko_filled": "Y" if is_filled(profile.get("legal_entity_name_ko")) else "",
                "legal_entity_name_en_filled": "Y" if is_filled(profile.get("legal_entity_name_en")) else "",
                "established_date_filled": "Y" if is_filled(profile.get("established_date")) else "",
                "business_registration_number_filled": "Y"
                if is_filled(profile.get("business_registration_number"))
                else "",
                "corporate_registration_number_filled": "Y"
                if is_filled(profile.get("corporate_registration_number"))
                else "",
                "representative_name_filled": "Y" if is_filled(profile.get("representative_name")) else "",
                "headquarters_address_filled": "Y" if is_filled(profile.get("headquarters_address")) else "",
                "phone_number_filled": "Y" if is_filled(profile.get("phone_number")) else "",
                "primary_source_url_filled": "Y" if is_filled(profile.get("primary_source_url")) else "",
                "fields_to_fill": profile.get("fields_to_fill", ""),
                "research_priority_reason": profile.get("research_priority_reason", ""),
            }
        )
        if len(rows) >= top_n:
            break
    return rows


def build_service_ready_rows(profiles: list[dict[str, object]], top_n: int = 50) -> list[dict[str, object]]:
    service_fields = [
        ("company_category", "company_category"),
        ("legal_entity_name_ko", "legal_entity_name_ko"),
        ("legal_entity_name_en", "legal_entity_name_en"),
        ("established_date", "established_date"),
        ("representative_name", "representative_name"),
        ("headquarters_address", "headquarters_address"),
        ("primary_source_url", "primary_source_url"),
    ]
    optional_display_fields = [
        ("homepage_url", "homepage_url"),
        ("phone_number", "phone_number"),
        ("contact_email", "contact_email"),
    ]
    identifier_fields = [
        ("business_registration_number", "business_registration_number"),
        ("corporate_registration_number", "corporate_registration_number"),
    ]

    ranked = [
        profile
        for profile in profiles
        if int_or_large(profile.get("worklist_rank")) <= top_n
    ]
    ranked = sorted(
        ranked,
        key=lambda profile: (
            int_or_large(profile.get("worklist_rank")),
            int_or_large(profile.get("latest_primary_rank")),
            int_or_large(profile.get("cumulative_primary_rank")),
            str(profile.get("standard_gp_name") or ""),
        ),
    )

    rows: list[dict[str, object]] = []
    for profile in ranked:
        missing_service_fields = [
            label for field_name, label in service_fields if not is_filled(profile.get(field_name))
        ]
        missing_identifier_fields = [
            label for field_name, label in identifier_fields if not is_filled(profile.get(field_name))
        ]
        missing_optional_fields = [
            label for field_name, label in optional_display_fields if not is_filled(profile.get(field_name))
        ]
        is_verified = str(profile.get("verification_level") or "") != "FSS_NAME_ONLY"
        service_ready = is_verified and not missing_service_fields
        rows.append(
            {
                "worklist_rank": profile.get("worklist_rank", ""),
                "source_gp_id": profile.get("source_gp_id", ""),
                "standard_gp_name": profile.get("standard_gp_name", ""),
                "latest_primary_rank": profile.get("latest_primary_rank", ""),
                "cumulative_primary_rank": profile.get("cumulative_primary_rank", ""),
                "verification_level": profile.get("verification_level", ""),
                "service_ready": "Y" if service_ready else "",
                "identifier_complete": "Y" if not missing_identifier_fields else "",
                "missing_service_field_count": len(missing_service_fields),
                "missing_service_fields": "; ".join(missing_service_fields),
                "missing_identifier_field_count": len(missing_identifier_fields),
                "missing_identifier_fields": "; ".join(missing_identifier_fields),
                "missing_optional_field_count": len(missing_optional_fields),
                "missing_optional_fields": "; ".join(missing_optional_fields),
                "manual_evidence_count": profile.get("manual_evidence_count", 0),
                "primary_source_url": profile.get("primary_source_url", ""),
                "research_priority_reason": profile.get("research_priority_reason", ""),
            }
        )
    return rows


def build_identifier_duplicate_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
    return fetch_dicts(
        conn,
        """
        SELECT
            i.identifier_type,
            i.normalized_identifier_value,
            COUNT(*) AS identifier_row_count,
            COUNT(DISTINCT i.source_gp_id) AS gp_count,
            GROUP_CONCAT(i.source_gp_id, '; ') AS source_gp_ids,
            GROUP_CONCAT(p.standard_gp_name, '; ') AS gp_names
        FROM gp_identifier i
        JOIN gp_profile p
            ON p.source_gp_id = i.source_gp_id
        WHERE COALESCE(i.normalized_identifier_value, '') <> ''
        GROUP BY i.identifier_type, i.normalized_identifier_value
        HAVING COUNT(DISTINCT i.source_gp_id) > 1
        ORDER BY i.identifier_type, i.normalized_identifier_value
        """,
    )


def build(db_path: Path, out_path: Path, csv_prefix: Path, top_n: int) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        assert_required_tables(conn)
        generated_at = now_iso()
        profiles = load_profiles(conn)

        overview_rows = build_overview_rows(conn, profiles, generated_at)
        coverage_rows = build_coverage_rows(profiles)
        verification_rows = build_verification_rows(conn, len(profiles))
        source_grade_rows = build_source_grade_rows(conn)
        top_gap_rows = build_top_gap_rows(profiles, top_n)
        service_ready_rows = build_service_ready_rows(profiles, 50)
        identifier_duplicate_rows = build_identifier_duplicate_rows(conn)
    finally:
        conn.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    csv_prefix.parent.mkdir(parents=True, exist_ok=True)

    overview_columns = ["metric", "value", "notes"]
    coverage_columns = [
        "population_key",
        "population_label",
        "population_size",
        "metric_key",
        "metric_label",
        "filled_count",
        "missing_count",
        "coverage_pct",
        "definition",
    ]
    verification_columns = ["verification_level", "profile_status", "gp_count", "share_pct"]
    source_grade_columns = ["evidence_origin", "source_grade", "evidence_count", "gp_count"]
    top_gap_columns = [
        "worklist_rank",
        "source_gp_id",
        "standard_gp_name",
        "latest_primary_rank",
        "cumulative_primary_rank",
        "latest_primary_aum_proxy_krw_100mn",
        "cumulative_primary_commitment_proxy_krw_100mn",
        "verification_level",
        "manual_evidence_count",
        "identifier_row_count",
        "missing_critical_field_count",
        "missing_critical_fields",
        "company_category_filled",
        "homepage_url_filled",
        "legal_entity_name_ko_filled",
        "legal_entity_name_en_filled",
        "established_date_filled",
        "business_registration_number_filled",
        "corporate_registration_number_filled",
        "representative_name_filled",
        "headquarters_address_filled",
        "phone_number_filled",
        "primary_source_url_filled",
        "fields_to_fill",
        "research_priority_reason",
    ]
    identifier_duplicate_columns = [
        "identifier_type",
        "normalized_identifier_value",
        "identifier_row_count",
        "gp_count",
        "source_gp_ids",
        "gp_names",
    ]
    service_ready_columns = [
        "worklist_rank",
        "source_gp_id",
        "standard_gp_name",
        "latest_primary_rank",
        "cumulative_primary_rank",
        "verification_level",
        "service_ready",
        "identifier_complete",
        "missing_service_field_count",
        "missing_service_fields",
        "missing_identifier_field_count",
        "missing_identifier_fields",
        "missing_optional_field_count",
        "missing_optional_fields",
        "manual_evidence_count",
        "primary_source_url",
        "research_priority_reason",
    ]

    write_csv_with_headers(csv_prefix.with_name(csv_prefix.name + "_overview.csv"), overview_rows, overview_columns)
    write_csv_with_headers(
        csv_prefix.with_name(csv_prefix.name + "_gp_profile_coverage.csv"),
        coverage_rows,
        coverage_columns,
    )
    write_csv_with_headers(
        csv_prefix.with_name(csv_prefix.name + "_verification_summary.csv"),
        verification_rows,
        verification_columns,
    )
    write_csv_with_headers(
        csv_prefix.with_name(csv_prefix.name + "_source_grade_summary.csv"),
        source_grade_rows,
        source_grade_columns,
    )
    write_csv_with_headers(
        csv_prefix.with_name(csv_prefix.name + "_top_gp_gaps.csv"),
        top_gap_rows,
        top_gap_columns,
    )
    write_csv_with_headers(
        csv_prefix.with_name(csv_prefix.name + "_service_ready_top50.csv"),
        service_ready_rows,
        service_ready_columns,
    )
    write_csv_with_headers(
        csv_prefix.with_name(csv_prefix.name + "_identifier_duplicates.csv"),
        identifier_duplicate_rows,
        identifier_duplicate_columns,
    )

    write_xlsx(
        out_path,
        [
            ("overview", rows_for_xlsx(overview_rows, overview_columns)),
            ("gp_profile_coverage", rows_for_xlsx(coverage_rows, coverage_columns)),
            ("verification_summary", rows_for_xlsx(verification_rows, verification_columns)),
            ("source_grade_summary", rows_for_xlsx(source_grade_rows, source_grade_columns)),
            ("top_gp_gaps", rows_for_xlsx(top_gap_rows, top_gap_columns)),
            ("service_ready_top50", rows_for_xlsx(service_ready_rows, service_ready_columns)),
            ("identifier_duplicates", rows_for_xlsx(identifier_duplicate_rows, identifier_duplicate_columns)),
        ],
    )

    return {
        "profiles": len(profiles),
        "overview": len(overview_rows),
        "coverage_rows": len(coverage_rows),
        "verification_rows": len(verification_rows),
        "source_grade_rows": len(source_grade_rows),
        "top_gap_rows": len(top_gap_rows),
        "service_ready_top50_rows": len(service_ready_rows),
        "identifier_duplicate_rows": len(identifier_duplicate_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build DB quality and coverage reports")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--csv-prefix", type=Path, default=DEFAULT_CSV_PREFIX)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    args = parser.parse_args()

    counts = build(args.db, args.out, args.csv_prefix, args.top_n)
    print(f"wrote {args.out}")
    for key, value in counts.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
