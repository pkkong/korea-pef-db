#!/usr/bin/env python
"""Build a public-safe service data payload.

The operator dashboard JSON contains work queues and coverage gaps. This script
keeps only the product data needed by the public GP/Fund/People views.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from lp_public_visibility import is_public_lp_notice_row, public_visible_value


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "dashboard" / "data" / "dashboard_data.json"
DEFAULT_OUT = ROOT / "services" / "newsletter" / "deploy" / "site" / "data" / "service_data.json"

PUBLIC_KEYS = [
    "meta",
    "periods",
    "gp_period_primary",
    "gp_period_full_credit",
    "funds",
    "fund_snapshots",
    "gp_cumulative",
    "new_funds_by_year",
    "new_funds_by_quarter",
    "gp_aliases",
    "gp_profiles",
    "people_current_gp",
    "people_profile_summary",
    "people_roles",
    "people_education",
    "lp_profiles",
    "lp_institutions",
    "lp_institution_stats",
    "lp_profile_facts",
    "lp_notice_gp_links",
    "lp_notice_news_links",
    "lp_commitment_notices",
    "lp_commitment_yearly_stats",
    "lp_commitment_selected_gp_compare",
    "lp_commitment_lifecycle_compare",
]

PROFILE_KEY_MAP = [
    ("gp_id", "source_gp_id"),
    ("profile_id", "gp_profile_id"),
    "gp_name",
    "company_category",
    "display_name_ko",
    "legal_entity_name_ko",
    "legal_entity_name_en",
    "homepage_url",
    "established_date",
    "firm_founded_date",
    "firm_founded_year",
    "representative_name",
    "headquarters_address",
    "business_registration_number",
    ("source_url", "primary_source_url"),
    "latest_primary_rank",
    "latest_primary_active_fund_count",
    ("latest_primary_commitment_krw_100mn", "latest_primary_aum_proxy_krw_100mn"),
    "cumulative_primary_rank",
    "cumulative_primary_fund_count",
    ("cumulative_commitment_krw_100mn", "cumulative_primary_commitment_proxy_krw_100mn"),
    "first_seen_period",
    "first_seen_date",
    "last_seen_period",
    "last_seen_date",
    "active_in_latest_period",
    "alias_names",
]

LP_PROFILE_KEYS = [
    "lp_code",
    "lp_name",
    "lp_name_en",
    "lp_type",
    "ownership_type",
    "homepage_url",
    "notice_url",
    "default_team",
    "focus_asset_classes",
    "service_priority",
    "aliases",
    "notice_count",
    "official_notice_count",
    "news_notice_count",
    "new_notice_count",
    "deadline_soon_count",
    "selection_event_count",
    "allocation_amount_krw_100mn",
    "commitment_amount_krw_100mn",
    "latest_event_date",
    "latest_announced_date",
    "latest_notice_title",
    "latest_notice_url",
    "latest_notice_event_type",
]
LP_PUBLIC_ASSET_CLASS_BLOCKLIST = {"OCIO"}

LP_NOTICE_NOISE_TERMS = [
    "제출서식",
    "제출서류",
    "FAQ",
    "담당팀 연락처",
    "동의하지 않은 경우",
    "가치형이나 고배당형",
    "벤처투자마트",
    "벤처투자종합포털",
    "주식유통정보",
    "비상장주식거래플랫폼",
    "신청 정보 확인",
]

LP_NOTICE_KEYS = [
    "notice_id",
    "lp_code",
    "lp_name",
    "lp_type",
    "default_team",
    "source_type",
    "event_type",
    "event_date",
    "title",
    "notice_url",
    "document_url",
    "attachment_names",
    "attachment_urls",
    "program_name",
    "round_name",
    "announced_date",
    "notice_year",
    "application_deadline",
    "notice_stage",
    "asset_class",
    "strategy",
    "program_size_krw_100mn",
    "allocation_amount_krw_100mn",
    "amount_type",
    "commitment_amount_krw_100mn",
    "selected_gp_names",
    "contact_team",
]

LP_FACT_KEYS = [
    "fact_id",
    "lp_code",
    "section",
    "label",
    "value",
    "as_of_date",
    "source_name",
    "source_url",
    "notes",
    "sort_order",
]

LP_NOTICE_GP_LINK_KEYS = [
    "notice_id",
    "lp_code",
    "source_gp_id",
    "gp_name",
    "matched_alias",
    "link_source",
]

LP_NOTICE_NEWS_LINK_KEYS = [
    "notice_id",
    "news_id",
    "lp_code",
    "publisher",
    "news_title",
    "published_at",
    "source_url",
    "link_source",
    "confidence",
    "created_at",
]

LP_SELECTED_GP_COMPARE_KEYS = [
    "notice_id",
    "lp_code",
    "lp_name",
    "lp_type",
    "program_name",
    "round_name",
    "notice_year",
    "event_type",
    "event_date",
    "announced_date",
    "application_deadline",
    "stage",
    "notice_stage",
    "asset_class",
    "strategy",
    "program_size_krw_100mn",
    "allocation_amount_krw_100mn",
    "commitment_amount_krw_100mn",
    "amount_krw_100mn",
    "amount_type",
    "source_gp_id",
    "gp_name",
    "matched_alias",
    "source_type",
    "notice_title",
    "source_url",
    "document_url",
]

LP_LIFECYCLE_COMPARE_KEYS = [
    "lp_code",
    "lp_name",
    "lp_type",
    "program_name",
    "round_name",
    "program_key",
    "round_key",
    "asset_class",
    "strategy",
    "notice_count",
    "open_count",
    "shortlist_count",
    "final_selection_count",
    "selected_gp_count",
    "allocation_amount_krw_100mn_sum",
    "commitment_amount_krw_100mn_sum",
    "amount_krw_100mn_sum",
    "program_size_krw_100mn_max",
    "latest_notice_id",
    "latest_notice_title",
    "latest_notice_url",
    "latest_document_url",
    "latest_notice_date",
    "latest_event_type",
    "latest_stage",
    "next_application_deadline",
    "latest_application_deadline",
    "deadline_status",
]

PUBLIC_KEY_RENAMES = {
    "source_gp_id": "gp_id",
    "verification_level": "source_confidence",
    "commitment_aum_proxy_trn_krw": "commitment_trn_krw",
    "latest_primary_aum_proxy_krw_100mn": "latest_primary_commitment_krw_100mn",
    "cumulative_primary_commitment_proxy_krw_100mn": "cumulative_commitment_krw_100mn",
}


def project(row: dict[str, object], keys: list[str]) -> dict[str, object]:
    return {key: row.get(key, "") for key in keys}


def sanitize_public_keys(value: object) -> object:
    if isinstance(value, list):
        return [sanitize_public_keys(item) for item in value]
    if isinstance(value, dict):
        return {
            PUBLIC_KEY_RENAMES.get(key, key): sanitize_public_keys(item)
            for key, item in value.items()
        }
    return value


def project_mapped(row: dict[str, object], keys: list[str | tuple[str, str]]) -> dict[str, object]:
    projected: dict[str, object] = {}
    for item in keys:
        if isinstance(item, tuple):
            public_key, source_key = item
            projected[public_key] = row.get(source_key, "")
        else:
            projected[item] = row.get(item, "")
    return projected


def numeric(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def notice_sort_value(row: dict[str, object]) -> str:
    return str(row.get("event_date") or row.get("announced_date") or row.get("discovered_at") or "")


def notice_year(row: dict[str, object]) -> int | None:
    value = row.get("notice_year")
    if value not in {None, ""}:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    for key in ("event_date", "announced_date", "discovered_at"):
        value = str(row.get(key) or "")
        if len(value) >= 4 and value[:4].isdigit():
            return int(value[:4])
    return None


def is_public_lp_profile(row: dict[str, object]) -> bool:
    if str(row.get("display_enabled") or "1").strip().lower() in {"0", "false", "no", "n"}:
        return False
    if str(row.get("profile_status") or "").strip().lower() in {"candidate", "draft", "internal"}:
        return False
    notes = str(row.get("notes") or "").lower()
    note_marks_candidate = "candidate" in notes or "후보" in notes or "ocio" in notes
    if note_marks_candidate and int(numeric(row.get("notice_count"))) <= 0:
        return False
    return True


def public_lp_asset_classes(value: object) -> str:
    parts = [
        part.strip()
        for part in str(value or "").split(";")
        if part.strip() and part.strip().upper() not in LP_PUBLIC_ASSET_CLASS_BLOCKLIST
    ]
    return ";".join(parts)


def is_stale_public_notice_deadline(row: dict[str, object]) -> bool:
    event_type = str(row.get("event_type") or "")
    if event_type not in {"new_notice", "deadline_soon"}:
        return False
    event_date = str(row.get("event_date") or row.get("announced_date") or "")[:10]
    deadline = str(row.get("application_deadline") or "")[:10]
    return bool(
        re.fullmatch(r"20\d{2}-\d{2}-\d{2}", event_date)
        and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", deadline)
        and deadline < event_date
    )


def is_clean_public_lp_notice(row: dict[str, object]) -> bool:
    if is_stale_public_notice_deadline(row):
        return False
    text = " ".join(str(row.get(key) or "") for key in ["title", "program_name", "raw_excerpt"])
    return not any(term in text for term in LP_NOTICE_NOISE_TERMS)


def build_lp_notice_stats(notices: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    notices_by_code: dict[str, list[dict[str, object]]] = {}
    for row in notices:
        lp_code = str(row.get("lp_code") or "").strip()
        if lp_code:
            notices_by_code.setdefault(lp_code, []).append(row)

    stats_by_code: dict[str, dict[str, object]] = {}
    for lp_code, lp_notices in notices_by_code.items():
        sorted_notices = sorted(lp_notices, key=notice_sort_value, reverse=True)
        source_counts: dict[str, int] = {}
        event_counts: dict[str, int] = {}
        for notice in sorted_notices:
            source_type = str(notice.get("source_type") or "")
            event_type = str(notice.get("event_type") or "")
            source_counts[source_type] = source_counts.get(source_type, 0) + 1
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        latest_notice = sorted_notices[0] if sorted_notices else {}
        stats_by_code[lp_code] = {
            "notice_count": len(sorted_notices),
            "official_notice_count": source_counts.get("official", 0),
            "news_notice_count": source_counts.get("news", 0),
            "new_notice_count": event_counts.get("new_notice", 0),
            "deadline_soon_count": event_counts.get("deadline_soon", 0),
            "selection_event_count": event_counts.get("shortlist", 0) + event_counts.get("final_selection", 0),
            "allocation_amount_krw_100mn": round(
                sum(numeric(row.get("allocation_amount_krw_100mn")) for row in sorted_notices),
                4,
            ),
            "commitment_amount_krw_100mn": round(
                sum(numeric(row.get("commitment_amount_krw_100mn")) for row in sorted_notices),
                4,
            ),
            "latest_event_date": latest_notice.get("event_date") or "",
            "latest_announced_date": latest_notice.get("announced_date") or "",
            "latest_discovered_at": latest_notice.get("discovered_at") or "",
            "latest_notice_title": latest_notice.get("title") or "",
            "latest_notice_url": latest_notice.get("notice_url") or "",
            "latest_notice_event_type": latest_notice.get("event_type") or "",
        }
    return stats_by_code


def with_lp_notice_stats(row: dict[str, object], stats_by_code: dict[str, dict[str, object]]) -> dict[str, object]:
    stats = stats_by_code.get(str(row.get("lp_code") or "").strip(), {})
    merged = dict(row)
    for key in (
        "notice_count",
        "official_notice_count",
        "news_notice_count",
        "new_notice_count",
        "deadline_soon_count",
        "selection_event_count",
        "allocation_amount_krw_100mn",
        "commitment_amount_krw_100mn",
        "latest_event_date",
        "latest_announced_date",
        "latest_discovered_at",
        "latest_notice_title",
        "latest_notice_url",
        "latest_notice_event_type",
    ):
        if key in merged or key in LP_PROFILE_KEYS:
            merged[key] = stats.get(key, 0 if key.endswith("_count") else "")
    return merged


def build_lp_institution_stats(
    institutions: list[dict[str, object]],
    stats_by_code: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for institution in institutions:
        lp_code = str(institution.get("lp_code") or "").strip()
        stats = stats_by_code.get(lp_code)
        if not stats:
            continue
        rows.append(
            {
                "lp_code": lp_code,
                "lp_name": institution.get("lp_name") or "",
                "lp_type": institution.get("lp_type") or "",
                "default_team": institution.get("default_team") or "",
                "focus_asset_classes": public_lp_asset_classes(institution.get("focus_asset_classes")),
                "service_priority": institution.get("service_priority") or "",
                "notice_count": stats.get("notice_count", 0),
                "allocation_amount_krw_100mn": stats.get("allocation_amount_krw_100mn", 0),
                "commitment_amount_krw_100mn": stats.get("commitment_amount_krw_100mn", 0),
                "latest_event_date": stats.get("latest_event_date", ""),
                "latest_announced_date": stats.get("latest_announced_date", ""),
                "latest_discovered_at": stats.get("latest_discovered_at", ""),
            }
        )
    return sorted(
        rows,
        key=lambda row: (-int(row.get("service_priority") or 0), -int(row.get("notice_count") or 0), str(row.get("lp_name") or "")),
    )


def build_lp_yearly_stats(notices: list[dict[str, object]]) -> list[dict[str, object]]:
    rows_by_key: dict[tuple[int, str], dict[str, object]] = {}
    for notice in notices:
        year = notice_year(notice)
        lp_code = str(notice.get("lp_code") or "").strip()
        if year is None or not lp_code:
            continue
        row = rows_by_key.setdefault(
            (year, lp_code),
            {
                "notice_year": year,
                "lp_code": lp_code,
                "lp_name": notice.get("lp_name") or "",
                "notice_count": 0,
                "allocation_amount_krw_100mn": 0.0,
                "commitment_amount_krw_100mn": 0.0,
            },
        )
        row["notice_count"] = int(row["notice_count"]) + 1
        row["allocation_amount_krw_100mn"] = round(
            numeric(row["allocation_amount_krw_100mn"]) + numeric(notice.get("allocation_amount_krw_100mn")),
            4,
        )
        row["commitment_amount_krw_100mn"] = round(
            numeric(row["commitment_amount_krw_100mn"]) + numeric(notice.get("commitment_amount_krw_100mn")),
            4,
        )
    return sorted(
        rows_by_key.values(),
        key=lambda row: (-int(row.get("notice_year") or 0), -numeric(row.get("commitment_amount_krw_100mn")), -int(row.get("notice_count") or 0), str(row.get("lp_name") or "")),
    )


def build_payload(data: dict[str, object]) -> dict[str, object]:
    payload = {key: data.get(key, []) for key in PUBLIC_KEYS}
    public_lp_notice_rows = [
        row
        for row in data.get("lp_commitment_notices", [])
        if isinstance(row, dict)
        and is_public_lp_notice_row(row, require_official=True)
        and is_clean_public_lp_notice(row)
    ]
    public_lp_notice_ids = {str(row.get("notice_id") or "") for row in public_lp_notice_rows if row.get("notice_id") not in {None, ""}}
    lp_notice_stats = build_lp_notice_stats(public_lp_notice_rows)
    lp_institutions = [row for row in data.get("lp_institutions", []) if isinstance(row, dict)]
    payload["meta"] = {
        "generated_at": data.get("meta", {}).get("generated_at", ""),
        "aum_basis": "금감원 PEF 운용 현황의 출자약정액 기준 지표",
        "latest_period": data.get("meta", {}).get("latest_period", ""),
        "latest_as_of_date": data.get("meta", {}).get("latest_as_of_date", ""),
    }
    payload["gp_profiles"] = [
        project_mapped(row, PROFILE_KEY_MAP)
        for row in data.get("gp_profiles", [])
        if isinstance(row, dict)
    ]
    payload["lp_profiles"] = [
        project(merged_row, LP_PROFILE_KEYS)
        for row in data.get("lp_profiles", [])
        if isinstance(row, dict)
        for merged_row in [with_lp_notice_stats(row, lp_notice_stats)]
        for merged_row in [{**merged_row, "focus_asset_classes": public_lp_asset_classes(merged_row.get("focus_asset_classes"))}]
        if is_public_lp_profile(merged_row)
    ]
    payload["lp_institution_stats"] = build_lp_institution_stats(lp_institutions, lp_notice_stats)
    payload["lp_commitment_yearly_stats"] = build_lp_yearly_stats(public_lp_notice_rows)
    payload["lp_commitment_notices"] = [
        project(row, LP_NOTICE_KEYS)
        for row in public_lp_notice_rows
    ]
    payload["lp_profile_facts"] = [
        project(row, LP_FACT_KEYS)
        for row in data.get("lp_profile_facts", [])
        if isinstance(row, dict) and public_visible_value(row.get("public_visible", "1"))
    ]
    payload["lp_notice_gp_links"] = [
        project(row, LP_NOTICE_GP_LINK_KEYS)
        for row in data.get("lp_notice_gp_links", [])
        if isinstance(row, dict) and str(row.get("notice_id") or "") in public_lp_notice_ids
    ]
    payload["lp_notice_news_links"] = [
        project(row, LP_NOTICE_NEWS_LINK_KEYS)
        for row in data.get("lp_notice_news_links", [])
        if isinstance(row, dict) and str(row.get("notice_id") or "") in public_lp_notice_ids
    ]
    payload["lp_commitment_selected_gp_compare"] = [
        project(row, LP_SELECTED_GP_COMPARE_KEYS)
        for row in data.get("lp_commitment_selected_gp_compare", [])
        if isinstance(row, dict) and str(row.get("notice_id") or "") in public_lp_notice_ids
    ]
    payload["lp_commitment_lifecycle_compare"] = [
        project(row, LP_LIFECYCLE_COMPARE_KEYS)
        for row in data.get("lp_commitment_lifecycle_compare", [])
        if isinstance(row, dict)
    ]
    return sanitize_public_keys(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build public service JSON without operator queues")
    parser.add_argument("--input", type=Path, default=DEFAULT_IN)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    payload = build_payload(data)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"keys={len(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
