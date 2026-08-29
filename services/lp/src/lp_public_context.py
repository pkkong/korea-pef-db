"""Public LP notice context shared with other service read models."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from services.lp.src.lp_notice_view import (
    clean_public_lp_text,
    lp_notice_program_label,
    split_notice_names,
)


PUBLIC_CONTEXT_FILENAME = "lp-notices.json"
PUBLIC_CONTEXT_VERSION = "lp-public-notice-context-v1"


def _safe_url(value: object) -> str:
    url = clean_public_lp_text(value)
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _primary_source_url(item: dict[str, object]) -> str:
    entries = item.get("sourceLinks")
    if isinstance(entries, list):
        for source_type in ("official", "news", ""):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                current_type = clean_public_lp_text(entry.get("sourceType")).lower()
                if source_type and current_type != source_type:
                    continue
                url = _safe_url(entry.get("url")) or _safe_url(entry.get("documentUrl"))
                if url:
                    return url
    return _safe_url(item.get("url")) or _safe_url(item.get("documentUrl"))


def _public_notice_row(item: dict[str, object]) -> dict[str, object]:
    program_name = clean_public_lp_text(lp_notice_program_label(item))
    title = program_name if program_name and program_name != "-" else clean_public_lp_text(
        item.get("displayTitle") or item.get("title") or "출자사업"
    )
    event_date = clean_public_lp_text(
        item.get("latestEventDate") or item.get("eventDate") or item.get("announcedDate")
    )[:10]
    return {
        "noticeId": clean_public_lp_text(item.get("noticeId")),
        "lpCode": clean_public_lp_text(item.get("lpCode")),
        "lpName": clean_public_lp_text(item.get("lpName")) or "LP 미분류",
        "title": title,
        "eventType": clean_public_lp_text(item.get("latestEventType") or item.get("eventType")),
        "eventDate": event_date,
        "announcedDate": clean_public_lp_text(item.get("announcedDate"))[:10],
        "assetClass": clean_public_lp_text(item.get("assetClass")),
        "strategy": clean_public_lp_text(item.get("strategy")),
        "programName": program_name if program_name != "-" else "",
        "allocationAmount": item.get("allocationAmount") or item.get("programSize") or "",
        "selectedGpNames": split_notice_names(item.get("selectedGpNames")),
        "noticeUrl": _primary_source_url(item),
    }


def build_public_notice_context(report_date: str, notices: list[dict[str, object]]) -> dict[str, object]:
    rows = [_public_notice_row(item) for item in notices]
    rows = [row for row in rows if str(row.get("title") or "").strip()]
    return {
        "schemaVersion": PUBLIC_CONTEXT_VERSION,
        "reportDate": report_date,
        "notices": rows,
    }


def write_public_notice_context(site_dir: Path, report_date: str, notices: list[dict[str, object]]) -> int:
    payload = build_public_notice_context(report_date, notices)
    (site_dir / PUBLIC_CONTEXT_FILENAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(payload["notices"])
