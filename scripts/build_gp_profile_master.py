#!/usr/bin/env python
"""Build GP profile master tables and a top-priority research worklist.

This script creates the structure needed to enrich FSS GP names with legal
entity identifiers. It deliberately leaves legal fields blank unless they were
already entered and verified from an external source.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from build_gp_master_candidates import write_xlsx


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_OUT = REPO_ROOT / "exports"
DEFAULT_LIMIT = 50


PROFILE_COLUMNS = [
    "gp_profile_id",
    "source_gp_id",
    "standard_gp_name",
    "gp_name_norm",
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
    "profile_status",
    "verification_level",
    "primary_source_url",
    "source_note",
    "latest_period_label",
    "latest_as_of_date",
    "latest_primary_rank",
    "latest_primary_active_fund_count",
    "latest_primary_aum_proxy_krw_100mn",
    "latest_primary_market_share_pct",
    "cumulative_primary_rank",
    "cumulative_primary_fund_count",
    "cumulative_primary_commitment_proxy_krw_100mn",
    "cumulative_primary_active_fund_count_latest",
    "first_seen_period",
    "first_seen_date",
    "last_seen_period",
    "last_seen_date",
    "active_in_latest_period",
    "alias_names",
    "raw_name_variants",
    "research_priority",
    "research_priority_reason",
    "research_note",
    "source_basis",
    "created_at",
    "updated_at",
]

MANUAL_PROFILE_COLUMNS = {
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
    "profile_status",
    "verification_level",
    "primary_source_url",
    "source_note",
    "research_note",
}

IDENTIFIER_COLUMNS = [
    "identifier_id",
    "source_gp_id",
    "gp_profile_id",
    "identifier_type",
    "identifier_value",
    "normalized_identifier_value",
    "issuer",
    "source_url",
    "source_title",
    "source_grade",
    "verification_status",
    "verified_at",
    "notes",
    "created_at",
    "updated_at",
]

SOURCE_COLUMNS = [
    "source_evidence_id",
    "source_gp_id",
    "gp_profile_id",
    "source_type",
    "source_title",
    "source_url",
    "source_grade",
    "evidence_scope",
    "evidence_value",
    "evidence_date",
    "verification_status",
    "captured_at",
    "notes",
]

WORKLIST_COLUMNS = [
    "worklist_rank",
    "source_gp_id",
    "gp_profile_id",
    "standard_gp_name",
    "latest_period_label",
    "latest_primary_rank",
    "latest_primary_aum_proxy_krw_100mn",
    "cumulative_primary_rank",
    "cumulative_primary_commitment_proxy_krw_100mn",
    "active_in_latest_period",
    "profile_status",
    "verification_level",
    "research_priority_reason",
    "fields_to_fill",
    "recommended_sources",
    "do_not_fill_without_source",
    "alias_names",
    "raw_name_variants",
    "research_note",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch_dicts(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
    cur = conn.execute(query, params)
    headers = [desc[0] for desc in cur.description]
    return [dict(zip(headers, row)) for row in cur.fetchall()]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def safe_table_suffix(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", value or "")
    if not cleaned:
        raise ValueError("Cannot build analytics table name without a period label")
    return cleaned


def eok_from_trn(value: object) -> float:
    return round(float(value or 0) * 10_000.0, 2)


def blank_row(columns: list[str]) -> dict[str, object]:
    return {column: "" for column in columns}


def write_csv_with_headers(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows([{column: row.get(column, "") for column in columns} for row in rows])


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS gp_profile (
            gp_profile_id TEXT NOT NULL UNIQUE,
            source_gp_id INTEGER PRIMARY KEY,
            standard_gp_name TEXT NOT NULL,
            gp_name_norm TEXT,
            company_category TEXT,
            display_name_ko TEXT,
            legal_entity_name_ko TEXT,
            legal_entity_name_en TEXT,
            homepage_url TEXT,
            established_date TEXT,
            firm_founded_date TEXT,
            firm_founded_year INTEGER,
            firm_description TEXT,
            representative_name TEXT,
            headquarters_address TEXT,
            phone_number TEXT,
            contact_email TEXT,
            business_registration_number TEXT,
            corporate_registration_number TEXT,
            financial_registration_number TEXT,
            license_type TEXT,
            license_status TEXT,
            profile_status TEXT NOT NULL,
            verification_level TEXT NOT NULL,
            primary_source_url TEXT,
            source_note TEXT,
            latest_period_label TEXT,
            latest_as_of_date TEXT,
            latest_primary_rank INTEGER,
            latest_primary_active_fund_count INTEGER,
            latest_primary_aum_proxy_krw_100mn REAL,
            latest_primary_market_share_pct REAL,
            cumulative_primary_rank INTEGER,
            cumulative_primary_fund_count INTEGER,
            cumulative_primary_commitment_proxy_krw_100mn REAL,
            cumulative_primary_active_fund_count_latest INTEGER,
            first_seen_period TEXT,
            first_seen_date TEXT,
            last_seen_period TEXT,
            last_seen_date TEXT,
            active_in_latest_period INTEGER NOT NULL,
            alias_names TEXT,
            raw_name_variants TEXT,
            research_priority INTEGER,
            research_priority_reason TEXT,
            research_note TEXT,
            source_basis TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gp_identifier (
            identifier_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_gp_id INTEGER NOT NULL,
            gp_profile_id TEXT NOT NULL,
            identifier_type TEXT NOT NULL,
            identifier_value TEXT NOT NULL,
            normalized_identifier_value TEXT,
            issuer TEXT,
            source_url TEXT,
            source_title TEXT,
            source_grade TEXT,
            verification_status TEXT NOT NULL,
            verified_at TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_gp_id, identifier_type, identifier_value)
        );

        CREATE TABLE IF NOT EXISTS gp_profile_source (
            source_evidence_id TEXT PRIMARY KEY,
            source_gp_id INTEGER NOT NULL,
            gp_profile_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_title TEXT,
            source_url TEXT,
            source_grade TEXT NOT NULL,
            evidence_scope TEXT NOT NULL,
            evidence_value TEXT,
            evidence_date TEXT,
            verification_status TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS gp_profile_research_worklist (
            worklist_rank INTEGER PRIMARY KEY,
            source_gp_id INTEGER NOT NULL,
            gp_profile_id TEXT NOT NULL,
            standard_gp_name TEXT NOT NULL,
            latest_period_label TEXT,
            latest_primary_rank INTEGER,
            latest_primary_aum_proxy_krw_100mn REAL,
            cumulative_primary_rank INTEGER,
            cumulative_primary_commitment_proxy_krw_100mn REAL,
            active_in_latest_period INTEGER NOT NULL,
            profile_status TEXT NOT NULL,
            verification_level TEXT NOT NULL,
            research_priority_reason TEXT,
            fields_to_fill TEXT NOT NULL,
            recommended_sources TEXT NOT NULL,
            do_not_fill_without_source TEXT NOT NULL,
            alias_names TEXT,
            raw_name_variants TEXT,
            research_note TEXT
        );
        """
    )

    existing_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(gp_profile)").fetchall()
    }
    column_defs = {
        "company_category": "TEXT",
        "firm_founded_date": "TEXT",
        "firm_founded_year": "INTEGER",
        "firm_description": "TEXT",
        "phone_number": "TEXT",
        "contact_email": "TEXT",
    }
    for column, column_type in column_defs.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE gp_profile ADD COLUMN {column} {column_type}")


def load_existing_profiles(conn: sqlite3.Connection) -> dict[int, dict[str, object]]:
    if not table_exists(conn, "gp_profile"):
        return {}
    rows = fetch_dicts(conn, "SELECT * FROM gp_profile")
    return {int(row["source_gp_id"]): row for row in rows}


def latest_period(conn: sqlite3.Connection) -> dict[str, object]:
    row = fetch_dicts(
        conn,
        """
        SELECT period_id, period_label, as_of_date
        FROM reporting_period
        ORDER BY as_of_date DESC, period_id DESC
        LIMIT 1
        """,
    )
    if not row:
        raise RuntimeError("No reporting_period rows found")
    return row[0]


def load_source_documents(conn: sqlite3.Connection) -> dict[str, dict[str, object]]:
    if not table_exists(conn, "source_document"):
        return {}
    rows = fetch_dicts(
        conn,
        """
        SELECT period_label, as_of_date, title, source_url
        FROM source_document
        ORDER BY as_of_date
        """,
    )
    return {str(row["period_label"]): row for row in rows}


def load_gp_base(conn: sqlite3.Connection, latest_period_id: str) -> list[dict[str, object]]:
    return fetch_dicts(
        conn,
        """
        SELECT
            gh.gp_id AS source_gp_id,
            gh.gp_name AS standard_gp_name,
            gh.gp_name_norm,
            first_rp.period_label AS first_seen_period,
            first_rp.as_of_date AS first_seen_date,
            last_rp.period_label AS last_seen_period,
            last_rp.as_of_date AS last_seen_date,
            CASE WHEN gh.last_seen_period_id = ? THEN 1 ELSE 0 END AS active_in_latest_period
        FROM gp_house gh
        LEFT JOIN reporting_period first_rp ON first_rp.period_id = gh.first_seen_period_id
        LEFT JOIN reporting_period last_rp ON last_rp.period_id = gh.last_seen_period_id
        ORDER BY gh.gp_id
        """,
        (latest_period_id,),
    )


def load_latest_primary_ranking(conn: sqlite3.Connection, period_label: str) -> dict[int, dict[str, object]]:
    table_name = f"analytics_gp_ranking_{safe_table_suffix(period_label)}"
    if not table_exists(conn, table_name):
        rows = fetch_dicts(
            conn,
            """
            WITH gp_amount AS (
                SELECT
                    gh.gp_id,
                    gh.gp_name,
                    COUNT(DISTINCT fps.fund_id) AS active_fund_count,
                    SUM(fps.commitment_amount_krw_mn) AS commitment_amount_krw_mn
                FROM fund_period_snapshot fps
                JOIN reporting_period rp ON rp.period_id = fps.period_id
                JOIN gp_house gh ON gh.gp_id = fps.gp_id
                WHERE rp.period_label = ?
                GROUP BY gh.gp_id
            ),
            total_amount AS (
                SELECT SUM(commitment_amount_krw_mn) AS total_commitment_amount_krw_mn
                FROM gp_amount
            )
            SELECT
                ROW_NUMBER() OVER (ORDER BY commitment_amount_krw_mn DESC, gp_name) AS rank,
                gp_id,
                active_fund_count,
                ROUND(commitment_amount_krw_mn / 1000000.0, 6) AS commitment_aum_proxy_trn_krw,
                ROUND(commitment_amount_krw_mn / total_commitment_amount_krw_mn * 100.0, 4) AS market_share_pct
            FROM gp_amount
            CROSS JOIN total_amount
            ORDER BY rank
            """,
            (period_label,),
        )
    else:
        rows = fetch_dicts(
            conn,
            f"""
            SELECT
                rank,
                gp_id,
                active_fund_count,
                commitment_aum_proxy_trn_krw,
                market_share_pct
            FROM {table_name}
            ORDER BY rank
            """,
        )
    return {int(row["gp_id"]): row for row in rows if str(row.get("gp_id") or "").isdigit()}


def load_cumulative_full_credit_stats(conn: sqlite3.Connection) -> dict[int, dict[str, object]]:
    table_name = "analytics_gp_cumulative_ranking"
    if not table_exists(conn, table_name):
        raise RuntimeError(
            f"Missing {table_name}. Run scripts/build_aum_analytics.py after build_fund_master.py before building GP profiles."
        )
    rows = fetch_dicts(
        conn,
        f"""
        SELECT
            rank AS cumulative_primary_rank,
            gp_id,
            cumulative_fund_count AS cumulative_primary_fund_count,
            cumulative_commitment_proxy_trn_krw AS cumulative_primary_commitment_trn_krw,
            active_fund_count_latest AS cumulative_primary_active_fund_count_latest
        FROM {table_name}
        ORDER BY cumulative_primary_rank
        """,
    )
    return {int(row["gp_id"]): row for row in rows}


def load_alias_names(conn: sqlite3.Connection) -> dict[int, str]:
    if not table_exists(conn, "gp_house_alias"):
        return {}
    grouped: dict[int, list[str]] = {}
    for row in fetch_dicts(
        conn,
        """
        SELECT canonical_gp_id, alias_gp_name
        FROM gp_house_alias
        ORDER BY canonical_gp_name, alias_gp_name
        """,
    ):
        grouped.setdefault(int(row["canonical_gp_id"]), []).append(str(row["alias_gp_name"]))
    return {gp_id: "; ".join(sorted(set(names))) for gp_id, names in grouped.items()}


def load_raw_variants(conn: sqlite3.Connection) -> dict[int, str]:
    if not table_exists(conn, "gp_name_variant"):
        return {}
    grouped: dict[int, list[str]] = {}
    for row in fetch_dicts(
        conn,
        """
        SELECT source_gp_id, raw_name_variant
        FROM gp_name_variant
        ORDER BY source_gp_id, raw_name_variant
        """,
    ):
        grouped.setdefault(int(row["source_gp_id"]), []).append(str(row["raw_name_variant"]))
    return {gp_id: "; ".join(sorted(set(names))) for gp_id, names in grouped.items()}


def ranking_reason(latest_rank: object, cumulative_rank: object, limit: int) -> str:
    latest = int(latest_rank) if latest_rank not in {"", None} else None
    cumulative = int(cumulative_rank) if cumulative_rank not in {"", None} else None
    if latest is not None and latest <= limit and cumulative is not None and cumulative <= limit:
        return f"latest_{latest}_and_cumulative_{cumulative}"
    if latest is not None and latest <= limit:
        return f"latest_rank_{latest}"
    if cumulative is not None and cumulative <= limit:
        return f"cumulative_rank_{cumulative}"
    return ""


def priority_key(row: dict[str, object]) -> int:
    values = []
    for column in ("latest_primary_rank", "cumulative_primary_rank"):
        value = row.get(column)
        if value not in {"", None}:
            values.append(int(value))
    return min(values) if values else 999999


def build_profile_rows(conn: sqlite3.Connection, limit: int, created_at: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    latest = latest_period(conn)
    latest_period_id = str(latest["period_id"])
    latest_label = str(latest["period_label"])
    latest_date = str(latest["as_of_date"])

    existing_profiles = load_existing_profiles(conn)
    gp_base = load_gp_base(conn, latest_period_id)
    latest_ranking = load_latest_primary_ranking(conn, latest_label)
    cumulative_stats = load_cumulative_full_credit_stats(conn)
    alias_names = load_alias_names(conn)
    raw_variants = load_raw_variants(conn)

    rows = []
    for base in gp_base:
        gp_id = int(base["source_gp_id"])
        existing = existing_profiles.get(gp_id, {})
        latest_rank_row = latest_ranking.get(gp_id, {})
        cumulative_row = cumulative_stats.get(gp_id, {})

        row = blank_row(PROFILE_COLUMNS)
        row.update(
            {
                "gp_profile_id": f"fss_gp_{gp_id:05d}",
                "source_gp_id": gp_id,
                "standard_gp_name": base["standard_gp_name"],
                "gp_name_norm": base["gp_name_norm"],
                "company_category": "unknown",
                "display_name_ko": base["standard_gp_name"],
                "profile_status": "research_needed",
                "verification_level": "FSS_NAME_ONLY",
                "latest_period_label": latest_label,
                "latest_as_of_date": latest_date,
                "latest_primary_rank": latest_rank_row.get("rank", ""),
                "latest_primary_active_fund_count": latest_rank_row.get("active_fund_count", ""),
                "latest_primary_aum_proxy_krw_100mn": eok_from_trn(
                    latest_rank_row.get("commitment_aum_proxy_trn_krw", 0)
                )
                if latest_rank_row
                else "",
                "latest_primary_market_share_pct": latest_rank_row.get("market_share_pct", ""),
                "cumulative_primary_rank": cumulative_row.get("cumulative_primary_rank", ""),
                "cumulative_primary_fund_count": cumulative_row.get("cumulative_primary_fund_count", ""),
                "cumulative_primary_commitment_proxy_krw_100mn": eok_from_trn(
                    cumulative_row.get("cumulative_primary_commitment_trn_krw", 0)
                )
                if cumulative_row
                else "",
                "cumulative_primary_active_fund_count_latest": cumulative_row.get(
                    "cumulative_primary_active_fund_count_latest",
                    "",
                ),
                "first_seen_period": base["first_seen_period"],
                "first_seen_date": base["first_seen_date"],
                "last_seen_period": base["last_seen_period"],
                "last_seen_date": base["last_seen_date"],
                "active_in_latest_period": int(base["active_in_latest_period"] or 0),
                "alias_names": alias_names.get(gp_id, ""),
                "raw_name_variants": raw_variants.get(gp_id, ""),
                "source_basis": (
                    "금감원 PEF 운용 현황에서 확인되는 운용사명, 펀드 연결, 약정액 기준 지표를 반영합니다. "
                    "법인 식별정보는 별도 공개자료가 확인된 경우에만 표시합니다."
                ),
                "created_at": existing.get("created_at") or created_at,
                "updated_at": created_at,
            }
        )
        for column in MANUAL_PROFILE_COLUMNS:
            existing_value = existing.get(column)
            if existing_value not in {"", None}:
                row[column] = existing_value
        reason = ranking_reason(row["latest_primary_rank"], row["cumulative_primary_rank"], limit)
        row["research_priority"] = priority_key(row) if reason else ""
        row["research_priority_reason"] = reason
        rows.append(row)

    rows.sort(key=lambda row: int(row["source_gp_id"]))
    worklist_candidates = [row for row in rows if row["research_priority_reason"]]
    worklist_candidates.sort(
        key=lambda row: (
            priority_key(row),
            -float(row.get("latest_primary_aum_proxy_krw_100mn") or 0),
            str(row["standard_gp_name"]),
        )
    )

    worklist_rows = []
    fields_to_fill = (
        "legal_entity_name_ko; business_registration_number; corporate_registration_number; "
        "established_date; representative_name; headquarters_address; homepage_url; official_source_url"
    )
    recommended_sources = (
        "Official company website/disclosure; FSS/KOFIA/DART; corporate/business registry source; "
        "credible news only as supporting evidence."
    )
    for worklist_rank, row in enumerate(worklist_candidates[:limit], start=1):
        worklist = {column: row.get(column, "") for column in WORKLIST_COLUMNS if column in row}
        worklist.update(
            {
                "worklist_rank": worklist_rank,
                "fields_to_fill": fields_to_fill,
                "recommended_sources": recommended_sources,
                "do_not_fill_without_source": "Do not infer. Leave blank unless the source explicitly confirms the field.",
            }
        )
        worklist_rows.append(worklist)

    return rows, worklist_rows


def build_source_rows(
    conn: sqlite3.Connection,
    profile_rows: list[dict[str, object]],
    captured_at: str,
) -> list[dict[str, object]]:
    source_documents = load_source_documents(conn)
    rows = []
    for profile in profile_rows:
        gp_id = int(profile["source_gp_id"])
        last_period = str(profile.get("last_seen_period") or "")
        source_doc = source_documents.get(last_period, {})
        rows.append(
            {
                "source_evidence_id": f"auto_fss_pef_status_{gp_id:05d}",
                "source_gp_id": gp_id,
                "gp_profile_id": profile["gp_profile_id"],
                "source_type": "FSS_PEF_STATUS_AUTO",
                "source_title": source_doc.get("title", ""),
                "source_url": source_doc.get("source_url", ""),
                "source_grade": "OFFICIAL_REGULATORY_SOURCE",
                "evidence_scope": "운용사명, 펀드 연결, 최초/최근 반영 기간, 약정액 기준 지표",
                "evidence_value": str(profile["standard_gp_name"]),
                "evidence_date": profile.get("last_seen_date", ""),
                "verification_status": "auto_extracted_from_fss",
                "captured_at": captured_at,
                "notes": "Does not verify legal entity identifiers, establishment date, address, or representative.",
            }
        )
    return rows


def load_identifiers(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not table_exists(conn, "gp_identifier"):
        return []
    return fetch_dicts(
        conn,
        """
        SELECT
            identifier_id,
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
        FROM gp_identifier
        ORDER BY source_gp_id, identifier_type, identifier_value
        """,
    )


def load_sources(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not table_exists(conn, "gp_profile_source"):
        return []
    return fetch_dicts(
        conn,
        """
        SELECT
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
        FROM gp_profile_source
        ORDER BY source_gp_id, source_type, source_evidence_id
        """,
    )


def field_dictionary_rows() -> list[dict[str, object]]:
    return [
        {
            "field_name": "standard_gp_name",
            "meaning": "FSS GP name after confirmed alias merges",
            "fill_rule": "Auto from FSS data",
        },
        {
            "field_name": "company_category",
            "meaning": "Working classification such as PE_HOUSE, BANK, SECURITIES, ASSET_MANAGER, PUBLIC_FINANCIAL_INSTITUTION",
            "fill_rule": "Use official profile/business description where possible; otherwise leave unknown.",
        },
        {
            "field_name": "legal_entity_name_ko",
            "meaning": "Verified Korean legal entity name",
            "fill_rule": "Only from official company/regulatory/registry source",
        },
        {
            "field_name": "business_registration_number",
            "meaning": "Korean business registration number",
            "fill_rule": "Do not infer from name. Fill only with explicit source evidence.",
        },
        {
            "field_name": "corporate_registration_number",
            "meaning": "Corporate registration number",
            "fill_rule": "Do not infer from name. Fill only with explicit source evidence.",
        },
        {
            "field_name": "established_date",
            "meaning": "Legal entity establishment date",
            "fill_rule": "Do not use fund establishment date. Use legal entity source only.",
        },
        {
            "field_name": "firm_founded_date",
            "meaning": "Firm-level founded date when different from legal entity establishment date",
            "fill_rule": "Use official company source or regulatory profile; keep separate from legal entity establishment date.",
        },
        {
            "field_name": "latest_primary_aum_proxy_krw_100mn",
            "meaning": "Latest-period active commitment amount proxy in KRW 100mn",
            "fill_rule": "Auto from FSS PEF status. This is commitment amount, not NAV.",
        },
        {
            "field_name": "cumulative_primary_commitment_proxy_krw_100mn",
            "meaning": "Sum of each normalized fund's maximum commitment amount for every GP listed in FSS history, KRW 100mn",
            "fill_rule": "Auto from normalized FSS PEF history. A joint-GP fund is credited in full to every listed GP, so the cumulative total can exceed the economic fund total.",
        },
        {
            "field_name": "verification_level",
            "meaning": "Evidence strength for legal profile fields",
            "fill_rule": "FSS_NAME_ONLY / OFFICIAL_SOURCE_VERIFIED / IDENTIFIER_VERIFIED",
        },
    ]


def insert_rows(conn: sqlite3.Connection, table_name: str, rows: list[dict[str, object]], columns: list[str]) -> None:
    if not rows:
        return
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    conn.executemany(
        f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})",
        [[row.get(column, "") for column in columns] for row in rows],
    )


def build(db_path: Path, out_dir: Path, limit: int) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        ensure_tables(conn)
        created_at = now_iso()
        profile_rows, worklist_rows = build_profile_rows(conn, limit, created_at)
        source_rows = build_source_rows(conn, profile_rows, created_at)

        conn.execute("DELETE FROM gp_profile")
        insert_rows(conn, "gp_profile", profile_rows, PROFILE_COLUMNS)
        conn.execute("DELETE FROM gp_profile_source WHERE source_type = 'FSS_PEF_STATUS_AUTO'")
        insert_rows(conn, "gp_profile_source", source_rows, SOURCE_COLUMNS)
        conn.execute("DELETE FROM gp_profile_research_worklist")
        insert_rows(conn, "gp_profile_research_worklist", worklist_rows, WORKLIST_COLUMNS)
        conn.commit()

        identifier_rows = load_identifiers(conn)
        all_source_rows = load_sources(conn)
        field_rows = field_dictionary_rows()

        write_csv_with_headers(out_dir / "gp_profile_master.csv", profile_rows, PROFILE_COLUMNS)
        write_csv_with_headers(out_dir / "gp_identifier.csv", identifier_rows, IDENTIFIER_COLUMNS)
        write_csv_with_headers(out_dir / "gp_profile_sources.csv", all_source_rows, SOURCE_COLUMNS)
        write_csv_with_headers(out_dir / "gp_profile_research_worklist_top50.csv", worklist_rows, WORKLIST_COLUMNS)
        write_xlsx(
            out_dir / "gp_profile_master.xlsx",
            [
                ("top50_worklist", worklist_rows or [blank_row(WORKLIST_COLUMNS)]),
                ("gp_profile", profile_rows),
                ("identifiers", identifier_rows or [blank_row(IDENTIFIER_COLUMNS)]),
                ("source_evidence", all_source_rows),
                ("field_dictionary", field_rows),
            ],
        )

        return {
            "gp_profile": len(profile_rows),
            "gp_profile_research_worklist": len(worklist_rows),
            "gp_identifier": len(identifier_rows),
            "gp_profile_source": len(all_source_rows),
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build GP profile master tables and research worklist")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()

    counts = build(args.db, args.out, args.limit)
    for key, value in counts.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
