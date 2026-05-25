#!/usr/bin/env python
"""Export compact JSON for the local PEF dashboard."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_OUT = REPO_ROOT / "dashboard" / "data" / "dashboard_data.json"
DEFAULT_NEWS_GP_ALIAS_OVERRIDES = REPO_ROOT / "data" / "news_gp_alias_overrides.csv"
DEFAULT_NEWS_GP_UPDATE_WORKLIST = REPO_ROOT / "exports" / "daily_news" / "news_gp_update_worklist_latest.csv"
DEFAULT_SERVICE_INTEGRATION_WORKLIST = REPO_ROOT / "exports" / "service_integration_worklist_latest.csv"


def fetch_dicts(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
    cur = conn.execute(query, params)
    headers = [desc[0] for desc in cur.description]
    return [dict(zip(headers, row)) for row in cur.fetchall()]


def object_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE name = ?
          AND type IN ('table', 'view')
        LIMIT 1
        """,
        (name,),
    ).fetchone()
    return row is not None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def split_names(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def load_news_gp_alias_overrides(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            canonical = (row.get("standard_gp_name") or "").strip()
            alias = (row.get("alias_name") or "").strip()
            if not canonical or not alias:
                continue
            rows.append(
                {
                    "canonical_gp_name": canonical,
                    "alias_gp_name": alias,
                    "relationship_type": "dashboard_search_alias",
                    "evidence_summary": row.get("notes", ""),
                }
            )
    return rows


def load_news_gp_update_worklist(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def build_gp_cumulative(funds: list[dict[str, object]]) -> list[dict[str, object]]:
    stats: dict[str, dict[str, object]] = {}
    for fund in funds:
        amount = float(fund.get("max_commitment_trn_krw") or 0)
        active_amount = float(fund.get("latest_commitment_trn_krw") or 0) if fund.get("active_in_latest_period") else 0.0
        for gp_name in split_names(str(fund.get("all_canonical_gp_names") or fund.get("latest_canonical_gp_names") or "")):
            if gp_name not in stats:
                stats[gp_name] = {
                    "gp_name": gp_name,
                    "cumulative_fund_count": 0,
                    "cumulative_commitment_trn_krw": 0.0,
                    "active_fund_count_latest": 0,
                    "active_commitment_trn_krw_latest": 0.0,
                }
            stats[gp_name]["cumulative_fund_count"] = int(stats[gp_name]["cumulative_fund_count"]) + 1
            stats[gp_name]["cumulative_commitment_trn_krw"] = round(
                float(stats[gp_name]["cumulative_commitment_trn_krw"]) + amount,
                6,
            )
            if fund.get("active_in_latest_period"):
                stats[gp_name]["active_fund_count_latest"] = int(stats[gp_name]["active_fund_count_latest"]) + 1
                stats[gp_name]["active_commitment_trn_krw_latest"] = round(
                    float(stats[gp_name]["active_commitment_trn_krw_latest"]) + active_amount,
                    6,
                )
    rows = sorted(
        stats.values(),
        key=lambda row: (-float(row["cumulative_commitment_trn_krw"]), str(row["gp_name"])),
    )
    for idx, row in enumerate(rows, start=1):
        row["cumulative_rank"] = idx
    return rows


def build_payload(
    conn: sqlite3.Connection,
    news_gp_alias_overrides: Path = DEFAULT_NEWS_GP_ALIAS_OVERRIDES,
    news_gp_update_worklist: Path = DEFAULT_NEWS_GP_UPDATE_WORKLIST,
    service_integration_worklist: Path = DEFAULT_SERVICE_INTEGRATION_WORKLIST,
) -> dict[str, object]:
    periods = fetch_dicts(
        conn,
        """
        SELECT
            period_label,
            as_of_date,
            regime,
            fund_count,
            primary_gp_count,
            ROUND(commitment_amount_krw_mn / 1000000.0, 6) AS commitment_trn_krw
        FROM v_period_summary
        ORDER BY as_of_date
        """,
    )

    gp_period_primary = fetch_dicts(
        conn,
        """
        SELECT
            period_label,
            as_of_date,
            gp_name,
            active_fund_count,
            commitment_aum_proxy_trn_krw
        FROM analytics_gp_period_aum
        ORDER BY as_of_date, commitment_aum_proxy_trn_krw DESC, gp_name
        """,
    )

    gp_period_full_credit = fetch_dicts(
        conn,
        """
        SELECT
            period_label,
            as_of_date,
            gp_name,
            active_fund_count,
            commitment_aum_proxy_trn_krw
        FROM analytics_gp_period_aum_full_credit
        ORDER BY as_of_date, commitment_aum_proxy_trn_krw DESC, gp_name
        """,
    )

    funds = fetch_dicts(
        conn,
        """
        SELECT
            fund_id,
            fund_name,
            established_date,
            lifecycle_status,
            first_seen_period,
            first_seen_date,
            last_seen_period,
            last_seen_date,
            active_in_latest_period,
            latest_canonical_gp_names,
            period_observation_count,
            first_commitment_trn_krw,
            latest_commitment_trn_krw,
            max_commitment_trn_krw,
            all_canonical_gp_names
        FROM fund_master
        ORDER BY fund_name
        """,
    )

    fund_snapshots = fetch_dicts(
        conn,
        """
        SELECT
            fund_id,
            fund_name,
            period_label,
            canonical_gp_names,
            raw_gp_names,
            commitment_trn_krw
        FROM fund_commitment_history
        ORDER BY as_of_date, fund_name
        """,
    )

    new_funds_by_year = fetch_dicts(
        conn,
        """
        SELECT
            year,
            new_fund_count,
            first_seen_commitment_trn_krw,
            latest_commitment_trn_krw,
            max_commitment_trn_krw,
            active_in_latest_count
        FROM analytics_new_funds_by_year
        ORDER BY year
        """,
    )

    new_funds_by_quarter = fetch_dicts(
        conn,
        """
        SELECT
            established_quarter,
            new_fund_count,
            first_seen_commitment_trn_krw,
            latest_commitment_trn_krw,
            max_commitment_trn_krw
        FROM analytics_new_funds_by_quarter
        ORDER BY established_quarter
        """,
    )

    gp_aliases = fetch_dicts(
        conn,
        """
        SELECT
            canonical_gp_name,
            alias_gp_name,
            relationship_type,
            evidence_summary
        FROM gp_house_alias
        ORDER BY canonical_gp_name, alias_gp_name
        """,
    )
    seen_aliases = {
        (str(row.get("canonical_gp_name") or ""), str(row.get("alias_gp_name") or ""))
        for row in gp_aliases
    }
    for row in load_news_gp_alias_overrides(news_gp_alias_overrides):
        key = (str(row.get("canonical_gp_name") or ""), str(row.get("alias_gp_name") or ""))
        if key not in seen_aliases:
            gp_aliases.append(row)
            seen_aliases.add(key)

    gp_profiles = fetch_dicts(
        conn,
        """
        SELECT
            source_gp_id,
            gp_profile_id,
            standard_gp_name AS gp_name,
            company_category,
            display_name_ko,
            legal_entity_name_ko,
            legal_entity_name_en,
            homepage_url,
            established_date,
            firm_founded_date,
            firm_founded_year,
            firm_description,
            representative_name,
            headquarters_address,
            phone_number,
            contact_email,
            business_registration_number,
            corporate_registration_number,
            profile_status,
            verification_level,
            primary_source_url,
            source_note,
            latest_primary_rank,
            latest_primary_active_fund_count,
            latest_primary_aum_proxy_krw_100mn,
            cumulative_primary_rank,
            cumulative_primary_fund_count,
            cumulative_primary_commitment_proxy_krw_100mn,
            first_seen_period,
            first_seen_date,
            last_seen_period,
            last_seen_date,
            active_in_latest_period,
            alias_names
        FROM gp_profile
        ORDER BY standard_gp_name
        """,
    )
    for profile in gp_profiles:
        required_display = [
            "company_category",
            "legal_entity_name_ko",
            "legal_entity_name_en",
            "established_date",
            "representative_name",
            "headquarters_address",
            "primary_source_url",
        ]
        profile["service_ready"] = (
            profile.get("verification_level") != "FSS_NAME_ONLY"
            and all(profile.get(field) for field in required_display)
        )

    source_documents = fetch_dicts(
        conn,
        """
        SELECT
            period_label,
            as_of_date,
            title,
            source_url
        FROM source_document
        ORDER BY as_of_date
        """,
    )
    people_current_gp: list[dict[str, object]] = []
    people_profile_summary: list[dict[str, object]] = []
    if object_exists(conn, "v_person_current_gp") and object_exists(conn, "v_person_profile_summary"):
        people_current_gp = fetch_dicts(
            conn,
            """
            SELECT
                person_id,
                person_name_ko,
                person_name_en,
                current_title,
                role_title,
                team,
                gp_id,
                gp_name,
                profile_status,
                verification_level,
                primary_source_url
            FROM v_person_current_gp
            ORDER BY gp_name, person_id
            """,
        )
        people_profile_summary = fetch_dicts(
            conn,
            """
            SELECT
                person_id,
                person_name_ko,
                person_name_en,
                current_primary_org_name,
                current_title,
                profile_status,
                verification_level,
                role_count,
                education_count,
                source_count
            FROM v_person_profile_summary
            ORDER BY current_primary_org_name, person_id
            """,
        )
    people_roles: list[dict[str, object]] = []
    people_education: list[dict[str, object]] = []
    if object_exists(conn, "person_role") and object_exists(conn, "person_education"):
        people_roles = fetch_dicts(
            conn,
            """
            SELECT
                pr.role_id,
                pr.person_id,
                pr.org_type,
                pr.org_id,
                pr.org_name,
                pr.title,
                pr.team,
                pr.role_start_date,
                pr.role_end_date,
                pr.is_current,
                pr.source_url,
                pr.verification_status,
                pr.notes
            FROM person_role pr
            ORDER BY pr.person_id, pr.is_current DESC, pr.role_id
            """,
        )
        people_education = fetch_dicts(
            conn,
            """
            SELECT
                pe.education_id,
                pe.person_id,
                pe.school_name,
                pe.school_name_en,
                pe.degree,
                pe.major,
                pe.start_year,
                pe.graduation_year,
                pe.source_url,
                pe.verification_status,
                pe.notes
            FROM person_education pe
            ORDER BY pe.person_id, pe.education_id
            """,
        )
    gp_cumulative = build_gp_cumulative(funds)
    news_gp_update_queue = load_news_gp_update_worklist(news_gp_update_worklist)
    service_integration_queue = load_news_gp_update_worklist(service_integration_worklist)
    lp_institutions: list[dict[str, object]] = []
    lp_institution_stats: list[dict[str, object]] = []
    lp_commitment_notices: list[dict[str, object]] = []
    lp_commitment_yearly_stats: list[dict[str, object]] = []
    if object_exists(conn, "lp_institution"):
        lp_institutions = fetch_dicts(
            conn,
            """
            SELECT
                lp_code,
                lp_name,
                lp_name_en,
                lp_type,
                ownership_type,
                homepage_url,
                notice_url,
                default_team,
                focus_asset_classes,
                service_priority,
                aliases,
                notes
            FROM lp_institution
            ORDER BY service_priority DESC, lp_name
            """,
        )
    if object_exists(conn, "v_lp_institution_stats"):
        lp_institution_stats = fetch_dicts(
            conn,
            """
            SELECT
                lp_code,
                lp_name,
                lp_type,
                default_team,
                focus_asset_classes,
                service_priority,
                notice_count,
                allocation_amount_krw_100mn,
                commitment_amount_krw_100mn,
                latest_event_date,
                latest_announced_date,
                latest_discovered_at
            FROM v_lp_institution_stats
            ORDER BY service_priority DESC, notice_count DESC, lp_name
            """,
        )
    if object_exists(conn, "v_lp_commitment_notice_public"):
        lp_commitment_notices = fetch_dicts(
            conn,
            """
            SELECT
                notice_id,
                lp_code,
                lp_name,
                lp_type,
                default_team,
                source_code,
                source_type,
                event_type,
                event_date,
                title,
                notice_url,
                document_url,
                program_name,
                round_name,
                announced_date,
                notice_year,
                application_deadline,
                notice_stage,
                asset_class,
                strategy,
                program_size_krw_100mn,
                allocation_amount_krw_100mn,
                amount_type,
                amount_confidence,
                commitment_amount_krw_100mn,
                selected_gp_names,
                contact_team,
                confidence,
                confidence_note,
                public_visible,
                monitor_status,
                raw_excerpt,
                discovered_at,
                updated_at
            FROM v_lp_commitment_notice_public
            ORDER BY
                CASE event_type
                    WHEN 'new_notice' THEN 0
                    WHEN 'deadline_soon' THEN 1
                    WHEN 'final_selection' THEN 2
                    WHEN 'shortlist' THEN 3
                    WHEN 'revision' THEN 4
                    WHEN 'cancellation' THEN 5
                    WHEN 'performance_update' THEN 6
                    ELSE 9
                END,
                COALESCE(event_date, announced_date, discovered_at) DESC,
                notice_id DESC
            LIMIT 500
            """,
        )
    if object_exists(conn, "v_lp_commitment_yearly_stats"):
        lp_commitment_yearly_stats = fetch_dicts(
            conn,
            """
            SELECT
                notice_year,
                lp_code,
                lp_name,
                notice_count,
                allocation_amount_krw_100mn,
                commitment_amount_krw_100mn
            FROM v_lp_commitment_yearly_stats
            ORDER BY notice_year DESC, commitment_amount_krw_100mn DESC, notice_count DESC, lp_name
            """,
        )

    return {
        "meta": {
            "generated_at": now_iso(),
            "aum_basis": "FSS commitment amount proxy, not NAV",
            "latest_period": periods[-1]["period_label"] if periods else "",
            "latest_as_of_date": periods[-1]["as_of_date"] if periods else "",
        },
        "periods": periods,
        "gp_period_primary": gp_period_primary,
        "gp_period_full_credit": gp_period_full_credit,
        "funds": funds,
        "fund_snapshots": fund_snapshots,
        "gp_cumulative": gp_cumulative,
        "new_funds_by_year": new_funds_by_year,
        "new_funds_by_quarter": new_funds_by_quarter,
        "gp_aliases": gp_aliases,
        "gp_profiles": gp_profiles,
        "people_current_gp": people_current_gp,
        "people_profile_summary": people_profile_summary,
        "people_roles": people_roles,
        "people_education": people_education,
        "lp_institutions": lp_institutions,
        "lp_institution_stats": lp_institution_stats,
        "lp_commitment_notices": lp_commitment_notices,
        "lp_commitment_yearly_stats": lp_commitment_yearly_stats,
        "news_gp_update_queue": news_gp_update_queue,
        "service_integration_queue": service_integration_queue,
        "source_documents": source_documents,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build JSON data for the PEF dashboard")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--news-gp-alias-overrides", type=Path, default=DEFAULT_NEWS_GP_ALIAS_OVERRIDES)
    parser.add_argument("--news-gp-update-worklist", type=Path, default=DEFAULT_NEWS_GP_UPDATE_WORKLIST)
    parser.add_argument("--service-integration-worklist", type=Path, default=DEFAULT_SERVICE_INTEGRATION_WORKLIST)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        payload = build_payload(
            conn,
            args.news_gp_alias_overrides,
            args.news_gp_update_worklist,
            args.service_integration_worklist,
        )
    finally:
        conn.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"periods={len(payload['periods'])}")
    print(f"funds={len(payload['funds'])}")
    print(f"fund_snapshots={len(payload['fund_snapshots'])}")
    print(f"gp_cumulative={len(payload['gp_cumulative'])}")
    print(f"gp_period_primary={len(payload['gp_period_primary'])}")
    print(f"gp_period_full_credit={len(payload['gp_period_full_credit'])}")
    print(f"people_current_gp={len(payload['people_current_gp'])}")
    print(f"people_roles={len(payload['people_roles'])}")
    print(f"people_education={len(payload['people_education'])}")
    print(f"lp_institutions={len(payload['lp_institutions'])}")
    print(f"lp_commitment_notices={len(payload['lp_commitment_notices'])}")
    print(f"service_integration_queue={len(payload['service_integration_queue'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
