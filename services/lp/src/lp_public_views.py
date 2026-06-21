#!/usr/bin/env python
"""LP public view helpers split out of the legacy newsletter deploy module.

The newsletter service must not import the old monolithic
``services.newsletter.src.build_newsletter_deploy`` module just to validate LP
notice labels or LP directory formatting. Keep these LP-facing helpers here so
newsletter tests and LP pages can depend on LP-owned code instead.
"""

from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
from html import escape as html_escape
from pathlib import Path
from urllib.parse import parse_qs, unquote_plus, urlparse


REPO_ROOT = Path(__file__).resolve().parents[3]

from services.lp.src.lp_notice_view import (
    clean_public_lp_text,
    consolidate_lp_notice_display_items,
    lp_event_label,
    lp_notice_amount_label,
    lp_notice_business_round_name,
    lp_notice_display_group_key,
    lp_notice_effective_deadline_value,
    lp_notice_program_label,
    lp_notice_public_status,
    lp_notice_public_strategy_label,
    lp_notice_source_label,
    lp_notice_specific_program_name,
    lp_notice_stage_label,
    lp_notice_status_label,
)
from services.shared.src.daily_news_common import normalize_whitespace  # noqa: E402


DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_LP_INSTITUTIONS = REPO_ROOT / "data" / "lp_institutions.csv"

LP_PROFILE_FALLBACK_CODES = ("ktcu", "pmaa", "cu", "kfcc", "kexim")
LP_CONTEXT_SEED_INSTITUTIONS = {
    "kic": {
        "lp_name": "한국투자공사",
        "aliases": ("한국투자공사", "KIC", "Korea Investment Corporation"),
    },
}

LP_PROFILE_SHORT_LABELS = {
    "nps": "국민연금",
    "kvic": "벤처투자",
    "kgrowth": "성장금융",
    "kafi": "농금원",
    "kdb": "산은",
    "koreapost": "우본",
    "poba": "지방행공",
    "ktcu": "교공",
    "pmaa": "경공",
    "cu": "신협",
    "kfcc": "새마을금고",
    "kexim": "수은",
    "kbiz": "중기중앙",
    "ibk": "IBK",
}

LP_TYPE_LABELS = {
    "Public Pension": "공적연기금",
    "Fund of Funds": "모태펀드",
    "Policy Fund of Funds": "정책성 모태펀드",
    "Policy Bank": "정책금융기관",
    "Public Fund": "공공기금",
    "Mutual Aid Association": "공제회",
    "Mutual Finance": "상호금융",
    "Mutual Aid/Industry Association": "공제/경제단체",
}

ASSET_CLASS_LABELS = {
    "PEF": "PEF",
    "VC": "VC",
    "Private Credit": "사모대출",
    "Real Estate": "부동산",
    "Infrastructure": "인프라",
    "Mother Fund": "모태펀드",
    "Policy Fund": "정책펀드",
    "Supply Chain": "공급망",
}


def db_object_exists(conn: sqlite3.Connection, name: str) -> bool:
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


def db_object_columns(conn: sqlite3.Connection, name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({name})").fetchall()}


def select_column(columns: set[str], name: str, fallback: str = "''") -> str:
    return name if name in columns else f"{fallback} AS {name}"


def fetch_dicts(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
    cursor = conn.execute(query, params)
    headers = [desc[0] for desc in cursor.description]
    return [dict(zip(headers, row)) for row in cursor.fetchall()]


def safe_int(value: object) -> int:
    try:
        return int(float(str(value or "0").replace(",", "")))
    except ValueError:
        return 0


def safe_float(value: object) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except ValueError:
        return 0.0


def split_aliases(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def useful_lp_alias(alias: str) -> bool:
    if not alias:
        return False
    if alias.upper() == "KIC":
        return True
    if alias.upper() in {"LP", "CU"}:
        return False
    if re.fullmatch(r"[A-Za-z0-9&.-]+", alias) and len(alias) < 4:
        return False
    return len(alias) >= 2


def lp_short_label(lp_code: str, lp_name: str) -> str:
    return LP_PROFILE_SHORT_LABELS.get(lp_code, lp_name)


def read_lp_institution_seed_rows(path: Path = DEFAULT_LP_INSTITUTIONS) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_lp_alias_patterns(db_path: Path = DEFAULT_DB) -> list[dict[str, object]]:
    if not db_path.exists():
        rows = read_lp_institution_seed_rows()
    else:
        conn = sqlite3.connect(db_path)
        try:
            if db_object_exists(conn, "lp_institution"):
                rows = fetch_dicts(
                    conn,
                    """
                    SELECT lp_code, lp_name, aliases
                    FROM lp_institution
                    ORDER BY service_priority DESC, lp_name
                    """,
                )
            else:
                rows = read_lp_institution_seed_rows()
        finally:
            conn.close()

    extras = {
        "kvic": ["모태펀드", "한국모태펀드"],
        "kgrowth": ["성장금융"],
        "moel_iaci": ["산재기금"],
        "nps": ["국민연금"],
        "poba": ["행정공제회"],
    }
    rows_by_code = {str(row.get("lp_code") or ""): row for row in rows if row.get("lp_code")}
    for code, seed in LP_CONTEXT_SEED_INSTITUTIONS.items():
        if code not in rows_by_code:
            rows.append(
                {
                    "lp_code": code,
                    "lp_name": seed["lp_name"],
                    "aliases": ";".join(seed["aliases"]),
                }
            )

    patterns: list[dict[str, object]] = []
    for row in rows:
        code = str(row.get("lp_code") or "")
        name = str(row.get("lp_name") or code)
        aliases = [name, lp_short_label(code, name), *split_aliases(row.get("aliases")), *extras.get(code, [])]
        clean_aliases = sorted({alias for alias in aliases if useful_lp_alias(alias)}, key=len, reverse=True)
        patterns.append({"lp_code": code, "lp_name": name, "aliases": clean_aliases})
    return patterns


def filter_service_context_profile_links(
    service_context: dict[str, dict[str, object]],
    profile_codes: set[str] | None = None,
) -> dict[str, dict[str, object]]:
    allowed_codes = profile_codes if profile_codes is not None else set(read_lp_profile_codes())
    for entry in service_context.values():
        links = entry.get("lpProfileLinks")
        if not isinstance(links, list):
            continue
        entry["lpProfileLinks"] = [
            link
            for link in links
            if isinstance(link, dict) and str(link.get("code") or "") in allowed_codes
        ]
    return service_context


def public_lp_type(value: object) -> str:
    text = str(value or "").strip()
    return LP_TYPE_LABELS.get(text, text or "LP")


def public_asset_class(value: object) -> str:
    text = str(value or "").strip()
    return ASSET_CLASS_LABELS.get(text, text or "기타")


def split_asset_classes(value: object) -> list[str]:
    classes = []
    seen: set[str] = set()
    for part in re.split(r"[;,/]", str(value or "")):
        label = public_asset_class(part.strip())
        if not label or label == "기타" or label in seen:
            continue
        classes.append(label)
        seen.add(label)
    return classes


def display_asset_classes(value: object) -> str:
    parts = split_asset_classes(value)
    return " · ".join(parts) if parts else "-"


def read_lp_notice_stats(conn: sqlite3.Connection) -> dict[str, dict[str, object]]:
    if not db_object_exists(conn, "v_lp_commitment_notice_public"):
        return {}
    rows = fetch_dicts(conn, "SELECT * FROM v_lp_commitment_notice_public WHERE COALESCE(public_visible, 1) = 1")
    stats: dict[str, dict[str, object]] = {}
    for row in rows:
        lp_code = str(row.get("lp_code") or "").strip()
        if not lp_code:
            continue
        entry = stats.setdefault(lp_code, {"notice_count": 0, "allocation_amount_krw_100mn": 0.0, "latest_event_date": ""})
        entry["notice_count"] = safe_int(entry["notice_count"]) + 1
        entry["allocation_amount_krw_100mn"] = safe_float(entry["allocation_amount_krw_100mn"]) + safe_float(
            row.get("allocation_amount_krw_100mn")
        )
        event_date = str(row.get("event_date") or row.get("announced_date") or "")
        if event_date > str(entry.get("latest_event_date") or ""):
            entry["latest_event_date"] = event_date
    return stats


def merge_lp_notice_stats(row: dict[str, object], stats: dict[str, dict[str, object]]) -> dict[str, object]:
    merged = dict(row)
    public_stats = stats.get(str(merged.get("lp_code") or ""), {})
    visible_notice_count = safe_int(public_stats.get("notice_count"))
    merged["profile_notice_count"] = safe_int(merged.get("notice_count"))
    merged["visible_notice_count"] = visible_notice_count
    merged["notice_count"] = visible_notice_count
    merged["allocation_amount_krw_100mn"] = safe_float(public_stats.get("allocation_amount_krw_100mn"))
    merged["latest_event_date"] = str(public_stats.get("latest_event_date") or "")
    merged["has_public_profile"] = bool(safe_int(merged.get("fact_count")) > 0 or visible_notice_count > 0)
    return merged


def read_lp_profile_codes(db_path: Path = DEFAULT_DB) -> list[str]:
    fallback = list(LP_PROFILE_FALLBACK_CODES)
    if not db_path.exists():
        return fallback
    conn = sqlite3.connect(db_path)
    notice_stats: dict[str, dict[str, object]] = {}
    has_summary = False
    try:
        if db_object_exists(conn, "v_lp_profile_summary"):
            has_summary = True
            rows = fetch_dicts(
                conn,
                """
                SELECT lp_code, fact_count
                FROM v_lp_profile_summary
                WHERE COALESCE(display_enabled, 1) = 1
                ORDER BY service_priority DESC, lp_name
                """,
            )
            notice_stats = read_lp_notice_stats(conn)
        else:
            rows = []
    finally:
        conn.close()

    codes = [
        str(row.get("lp_code") or "")
        for row in rows
        if row.get("lp_code")
        and (safe_int(row.get("fact_count")) > 0 or safe_int(notice_stats.get(str(row.get("lp_code") or ""), {}).get("notice_count")) > 0)
    ]
    return codes if has_summary else fallback


def read_lp_directory_items(db_path: Path = DEFAULT_DB) -> list[dict[str, object]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        if not db_object_exists(conn, "v_lp_profile_summary"):
            return []
        columns = db_object_columns(conn, "v_lp_profile_summary")
        selected_columns = ",\n                ".join(
            [
                select_column(columns, "lp_code"),
                select_column(columns, "lp_name"),
                select_column(columns, "lp_type"),
                select_column(columns, "legal_lp_category"),
                select_column(columns, "legal_lp_basis"),
                select_column(columns, "ownership_type"),
                select_column(columns, "homepage_url"),
                select_column(columns, "notice_url"),
                select_column(columns, "default_team"),
                select_column(columns, "focus_asset_classes"),
                select_column(columns, "service_priority", "0"),
                select_column(columns, "coverage_tier"),
                select_column(columns, "display_enabled", "1"),
                select_column(columns, "notice_tracking_enabled", "1"),
                select_column(columns, "profile_status"),
                select_column(columns, "notice_count", "0"),
                select_column(columns, "allocation_amount_krw_100mn", "0"),
                select_column(columns, "latest_event_date"),
                select_column(columns, "fact_count", "0"),
                select_column(columns, "source_count", "0"),
            ]
        )
        rows = fetch_dicts(
            conn,
            f"""
            SELECT
                {selected_columns}
            FROM v_lp_profile_summary
            WHERE COALESCE(display_enabled, 1) = 1
            ORDER BY service_priority DESC, lp_name
            """,
        )
        notice_stats = read_lp_notice_stats(conn)
        return [merge_lp_notice_stats(row, notice_stats) for row in rows]
    finally:
        conn.close()


def public_coverage_label(fact_count: object, source_count: object) -> str:
    return f"{safe_int(fact_count) + safe_int(source_count)}개"


def notice_gp_label(value: object, limit: int = 2) -> str:
    names = [name for name in split_notice_names(value)]
    if not names:
        return "-"
    if len(names) <= limit:
        return " · ".join(names)
    return f"{' · '.join(names[:limit])} 외 {len(names) - limit}"


def split_notice_names(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw_parts = [str(item or "") for item in value]
    else:
        raw_parts = re.split(r"[;,]", str(value or ""))
    names: list[str] = []
    seen: set[str] = set()
    for raw_part in raw_parts:
        for part in re.split(r"[;,]", raw_part):
            name = normalize_whitespace(part)
            if not name or name in seen:
                continue
            names.append(name)
            seen.add(name)
    return names


def lp_notice_detail_slug(item: dict[str, object]) -> str:
    lp_code = re.sub(r"[^0-9a-zA-Z-]", "", str(item.get("lpCode") or "lp").lower()) or "lp"
    title_key = lp_notice_display_group_key(item)[1] or lp_notice_program_label(item) or str(item.get("noticeId") or "")
    digest = hashlib.sha1(f"{lp_code}|{title_key}".encode("utf-8")).hexdigest()[:12]
    return f"lp-notice-{lp_code}-{digest}.html"


def lp_notice_primary_source_url(item: dict[str, object]) -> str:
    source_links = item.get("sourceLinks") if isinstance(item.get("sourceLinks"), list) else []
    entries = [link for link in source_links if isinstance(link, dict)] or [
        {
            "sourceType": item.get("sourceType"),
            "url": item.get("url"),
            "documentUrl": item.get("documentUrl"),
        }
    ]
    for preferred_type in ["official", "news", ""]:
        for entry in entries:
            source_type = str(entry.get("sourceType") or "").strip().lower()
            if preferred_type and source_type != preferred_type:
                continue
            url = str(entry.get("url") or entry.get("documentUrl") or "")
            if url:
                return url
    return str(item.get("url") or item.get("documentUrl") or "")


def lp_notice_document_title(document_url: object, attachment_names: object = "") -> str:
    candidates: list[str] = []
    raw_url = str(document_url or "")
    if raw_url:
        query = parse_qs(urlparse(raw_url.replace("&amp;", "&")).query)
        candidates.extend(query.get("filenameOrg", []))
        candidates.extend(query.get("name", []))
    candidates.extend(part.strip() for part in str(attachment_names or "").split(";") if part.strip())
    for candidate in candidates:
        title = clean_public_lp_text(unquote_plus(candidate))
        title = re.sub(r"^\s*[-\d.)_\s]+", "", title)
        title = re.sub(r"\.(?:hwp|hwpx|pdf|docx?|xlsx?)$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*(?:공고문|공고)\s*(?:\(국문\)|\(English\))?$", " 공고", title)
        title = normalize_whitespace(title)
        if len(title) >= 12 and any(token in title for token in ["공고", "선정", "위탁운용", "출자"]):
            return title
    return ""


def is_truncated_lp_notice_title(value: str) -> bool:
    return bool(re.search(r"\.{2,}|…", value or ""))


def lp_notice_public_event_title(event: dict[str, object]) -> str:
    title = clean_public_lp_text(event.get("title") or "")
    if not title:
        return ""
    if any(
        term in title
        for term in [
            "벤처투자포털",
            "벤처투자종합포털",
            "벤처투자마트",
            "주식유통정보",
            "비상장주식거래플랫폼",
            "출자공고 |",
            "| 출자사업 |",
            "목록에서 발견",
        ]
    ):
        return ""
    return re.sub(r"\s*\|\s*(?:벤처투자포털|벤처투자종합포털|출자사업).*$", "", title).strip()


def lp_notice_preview_events(item: dict[str, object], limit: int = 3) -> str:
    events = [event for event in item.get("events", []) if isinstance(event, dict)] if isinstance(item.get("events"), list) else []
    if not events:
        return ""
    rows: list[str] = []
    for event in sorted(events, key=lambda event: str(event.get("eventDate") or event.get("latestEventDate") or ""), reverse=True)[:limit]:
        event_title = lp_notice_public_event_title(event)
        if not event_title:
            continue
        event_date = str(event.get("eventDate") or "")[:10]
        event_status = clean_public_lp_text(event.get("stageLabel") or lp_event_label(event.get("eventType")) or "공지")
        rows.append(
            f"""            <li>
              <time>{html_escape(event_date)}</time>
              <strong>{html_escape(event_status)}</strong>
              <span>{html_escape(event_title)}</span>
            </li>"""
        )
    if not rows:
        return ""
    return f"""
            <ol class="lp-notice-preview-timeline">
{chr(10).join(rows)}
            </ol>"""


def render_lp_notice_card(item: dict[str, object], report_date: str) -> str:
    raw_title = clean_public_lp_text(item.get("title") or "공식 공고") or "공식 공고"
    display_title = clean_public_lp_text(item.get("displayTitle") or "") or raw_title
    document_url = str(item.get("documentUrl") or "")
    attachments = item.get("attachments") if isinstance(item.get("attachments"), list) else []
    attachment_names = "; ".join(str(attachment.get("name") or "") for attachment in attachments if isinstance(attachment, dict))
    document_title = lp_notice_document_title(document_url, attachment_names)
    title = display_title if not is_truncated_lp_notice_title(display_title) else raw_title
    if document_title and (is_truncated_lp_notice_title(title) or len(document_title) > len(title) + 8):
        title = document_title

    lp_code = str(item.get("lpCode") or "")
    lp_name = clean_public_lp_text(item.get("lpName") or "LP 미분류") or "LP 미분류"
    event_date = str(item.get("latestEventDate") or item.get("eventDate") or item.get("announcedDate") or "")
    deadline = lp_notice_effective_deadline_value(item)
    status = lp_notice_public_status(item, report_date)
    status_group = "history" if status in {"closed", "history"} else status
    status_label = lp_notice_status_label(status)
    stage_label = clean_public_lp_text(item.get("businessStageLabel") or "") or lp_notice_stage_label(item, status)
    stage_badge_class = f"lp-notice-status is-{status if status in {'open', 'shortlist', 'result'} else 'closed'}"

    amount, amount_numeric = lp_notice_amount_label(item)
    program_label = lp_notice_program_label(item)
    business_title = title if program_label == "-" else program_label
    asset_class = public_asset_class(item.get("assetClass")) if item.get("assetClass") else ""
    strategy = lp_notice_public_strategy_label(item)
    type_label = " · ".join(value for value in [asset_class, strategy] if value) or "-"
    selected_label = notice_gp_label(item.get("selectedGpNames"))
    source_label = lp_notice_source_label(item)
    source_url = lp_notice_primary_source_url(item)
    detail_url = str(item.get("detailUrl") or lp_notice_detail_slug(item))
    notice_year = str(event_date or item.get("eventDate") or item.get("announcedDate") or "")[:4]

    fact_rows: list[str] = []
    for label, value in [
        ("마감일", deadline),
        ("출자규모", amount if amount != "-" else ""),
        ("자산/전략", type_label if type_label != "-" else ""),
        ("선정 GP", selected_label if selected_label != "-" else ""),
    ]:
        if not value:
            continue
        fact_rows.append(
            f"""              <div>
                <dt>{html_escape(label)}</dt>
                <dd>{html_escape(value)}</dd>
              </div>"""
        )

    timeline_html = lp_notice_preview_events(item)
    if timeline_html:
        timeline_html = f"""
            <h3 class="lp-notice-preview-title">진행 이력</h3>
{timeline_html}"""
    source_link_html = (
        f'<a class="lp-notice-source-link" href="{html_escape(source_url)}" target="_blank" rel="noreferrer">원문</a>'
        if source_url
        else ""
    )
    events = [event for event in item.get("events", []) if isinstance(event, dict)] if isinstance(item.get("events"), list) else []
    stage = " ".join(str(event.get("title") or "") for event in events)
    search_blob = " ".join(
        str(value or "")
        for value in [
            title,
            business_title,
            lp_name,
            program_label,
            asset_class,
            status_label,
            stage_label,
            deadline,
            strategy,
            selected_label,
            source_label,
            stage,
        ]
    )
    has_gp = "1" if selected_label != "-" else "0"
    event_date_label = event_date[:10] if event_date else ""
    return f"""              <article class="lp-notice-row" data-search="{html_escape(search_blob)}" data-lp="{html_escape(lp_code)}" data-lp-name="{html_escape(lp_name)}" data-program="{html_escape(program_label)}" data-asset="{html_escape(asset_class)}" data-asset-value="{html_escape(asset_class)}" data-source="{html_escape(source_label)}" data-status="{html_escape(status)}" data-status-group="{html_escape(status_group)}" data-year="{html_escape(notice_year)}" data-date="{html_escape(event_date)}" data-deadline="{html_escape(deadline)}" data-amount="{amount_numeric:.0f}" data-has-gp="{has_gp}">
            <div class="lp-notice-main">
              <div class="lp-notice-card-top">
                <span class="{stage_badge_class}">{html_escape(stage_label or status_label)}</span>
                <span class="lp-notice-kicker">{html_escape(source_label)} · {html_escape(lp_name)}</span>
              </div>
              <h2><a href="{html_escape(detail_url)}">{html_escape(business_title)}</a></h2>
              <div class="lp-notice-card-meta">
                {f'<span>최근 {html_escape(event_date_label)}</span>' if event_date_label else ''}
                {source_link_html}
              </div>
            </div>
            <dl class="lp-notice-facts">
{chr(10).join(fact_rows)}
            </dl>
            {timeline_html}
          </article>"""
