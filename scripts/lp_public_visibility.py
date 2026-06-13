"""Shared public visibility rules for LP commitment notices."""

from __future__ import annotations

LP_PUBLIC_FALSE_VALUES = {"0", "false", "no", "n"}
LP_NON_PUBLIC_EVENT_TYPES = {"candidate"}
LP_NON_PUBLIC_CONFIDENCE_VALUES = {"low"}
LP_NON_PUBLIC_MONITOR_STATUSES = {
    "candidate",
    "review",
    "review_pending",
    "pending_review",
    "needs_review",
    "unvalidated",
    "draft",
}
LP_OFFICIAL_CANDIDATE_SOURCE_DENYLIST = {
    # The venture portal listing feed is useful as a discovery source, but its
    # scraped rows often carry portal navigation text instead of a clean
    # business title. Keep it out of public pages until rows are reviewed.
    "vcs_investment_notice",
}
LP_OFFICIAL_CANDIDATE_SOURCE_ALLOWLIST = {
    "cu_notice",
    "cwma_asset_manager_selection",
    "geps_manager_selection_result",
    "kafi_apfs_notice",
    "kbiz_notice",
    "kdb_ngf_notice",
    "kdb_notice",
    "kdic_notice",
    "kexim_notice",
    "kfcc_mg_notice",
    "kfcc_tender_notice",
    "kgrowth_notice",
    "kobc_notice",
    "koreapost_asset_notice",
    "ktcu_notice",
    "kvic_notice",
    "moel_asset_notice",
    "nps_manager_selection",
    "pmaa_bid_notice",
    "sema_bid_notice",
    "sema_kofia_notice",
    "tp_notice",
}


def public_visible_value(value: object) -> bool:
    return str(value if value is not None else "1").strip().lower() not in LP_PUBLIC_FALSE_VALUES


def is_public_lp_notice_row(
    row: dict[str, object],
    require_official: bool = False,
    allow_official_candidates: bool = False,
) -> bool:
    """Return True for public LP notice rows.

    Candidate rows stay hidden unless the caller explicitly opts into official
    candidates and the source parser is public-ready.
    """
    if not public_visible_value(row.get("public_visible", 1)):
        return False
    source_type = str(row.get("source_type") or "").strip().lower()
    if require_official and source_type != "official":
        return False
    event_type = str(row.get("event_type") or "").strip().lower()
    if not event_type or event_type in LP_NON_PUBLIC_EVENT_TYPES:
        return False
    confidence = str(row.get("confidence") or "").strip().lower()
    if confidence in LP_NON_PUBLIC_CONFIDENCE_VALUES:
        return False
    monitor_status = str(row.get("monitor_status") or "").strip().lower()
    if monitor_status in LP_NON_PUBLIC_MONITOR_STATUSES:
        source_code = str(row.get("source_code") or "").strip().lower()
        if (
            allow_official_candidates
            and source_type == "official"
            and monitor_status == "candidate"
            and source_code in LP_OFFICIAL_CANDIDATE_SOURCE_ALLOWLIST
            and source_code not in LP_OFFICIAL_CANDIDATE_SOURCE_DENYLIST
        ):
            return True
        return False
    return True
