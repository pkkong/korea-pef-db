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


def public_visible_value(value: object) -> bool:
    return str(value if value is not None else "1").strip().lower() not in LP_PUBLIC_FALSE_VALUES


def is_public_lp_notice_row(row: dict[str, object], require_official: bool = False) -> bool:
    """Return True only for reviewed public LP notice rows."""
    if not public_visible_value(row.get("public_visible", 1)):
        return False
    if require_official and str(row.get("source_type") or "").strip() != "official":
        return False
    event_type = str(row.get("event_type") or "").strip().lower()
    if event_type in LP_NON_PUBLIC_EVENT_TYPES:
        return False
    confidence = str(row.get("confidence") or "").strip().lower()
    if confidence in LP_NON_PUBLIC_CONFIDENCE_VALUES:
        return False
    monitor_status = str(row.get("monitor_status") or "").strip().lower()
    if monitor_status in LP_NON_PUBLIC_MONITOR_STATUSES:
        return False
    return True
