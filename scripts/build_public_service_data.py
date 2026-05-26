#!/usr/bin/env python
"""Build a public-safe service data payload.

The operator dashboard JSON contains work queues and coverage gaps. This script
keeps only the product data needed by the public GP/Fund/People views.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "dashboard" / "data" / "dashboard_data.json"
DEFAULT_OUT = ROOT / "public" / "data" / "service_data.json"

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
    "lp_commitment_notices",
    "lp_commitment_yearly_stats",
]

PROFILE_KEYS = [
    "source_gp_id",
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
    "verification_level",
    "primary_source_url",
    "latest_primary_rank",
    "latest_primary_active_fund_count",
    "latest_primary_aum_proxy_krw_100mn",
    "cumulative_primary_rank",
    "cumulative_primary_fund_count",
    "cumulative_primary_commitment_proxy_krw_100mn",
    "first_seen_period",
    "first_seen_date",
    "last_seen_period",
    "last_seen_date",
    "active_in_latest_period",
    "alias_names",
    "service_ready",
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
    "notes",
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
]

LP_NOTICE_KEYS = [
    "notice_id",
    "lp_code",
    "lp_name",
    "lp_type",
    "default_team",
    "source_code",
    "source_type",
    "event_type",
    "event_date",
    "title",
    "notice_url",
    "document_url",
    "program_name",
    "round_name",
    "announced_date",
    "notice_year",
    "application_deadline",
    "notice_stage",
    "asset_class",
    "strategy",
    "allocation_amount_krw_100mn",
    "amount_confidence",
    "selected_gp_names",
    "confidence",
    "public_visible",
]


def project(row: dict[str, object], keys: list[str]) -> dict[str, object]:
    return {key: row.get(key, "") for key in keys}


def build_payload(data: dict[str, object]) -> dict[str, object]:
    payload = {key: data.get(key, []) for key in PUBLIC_KEYS}
    payload["meta"] = {
        "generated_at": data.get("meta", {}).get("generated_at", ""),
        "aum_basis": "FSS 출자약정액 기준 AUM 프록시",
        "latest_period": data.get("meta", {}).get("latest_period", ""),
        "latest_as_of_date": data.get("meta", {}).get("latest_as_of_date", ""),
    }
    payload["gp_profiles"] = [
        project(row, PROFILE_KEYS)
        for row in data.get("gp_profiles", [])
        if isinstance(row, dict)
    ]
    payload["lp_profiles"] = [
        project(row, LP_PROFILE_KEYS)
        for row in data.get("lp_profiles", [])
        if isinstance(row, dict)
    ]
    payload["lp_commitment_notices"] = [
        project(row, LP_NOTICE_KEYS)
        for row in data.get("lp_commitment_notices", [])
        if isinstance(row, dict) and str(row.get("public_visible", "1")).strip().lower() not in {"0", "false", "no"}
    ]
    return payload


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
