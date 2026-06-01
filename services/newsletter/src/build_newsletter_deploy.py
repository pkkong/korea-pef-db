#!/usr/bin/env python
"""Build a deployable static bundle for the newsletter-only service."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
SRC_DIR = Path(__file__).resolve().parent
DEFAULT_DEPLOY_DIR = SERVICE_ROOT / "deploy"
DEFAULT_SITE_DIR = DEFAULT_DEPLOY_DIR / "site"
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_ARCHIVE_SEED_URL = os.environ.get(
    "NEWSLETTER_ARCHIVE_SEED_URL",
    "https://raw.githubusercontent.com/pkkong/kpef-newsletter/gh-pages/archive.json",
)

KTCU_CODE = "ktcu"
LP_PROFILE_FALLBACK_CODES = ("ktcu", "pmaa", "cu", "kfcc", "kexim")
LP_PROFILE_CODES = LP_PROFILE_FALLBACK_CODES
LP_PROFILE_ALIASES = {
    "ktcu": ("ktcu.html",),
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
LP_PROFILE_DISPLAY_LABELS = {
    "nps": "국민연금기금",
    "kvic": "한국벤처투자",
    "kgrowth": "한국성장금융",
    "kafi": "농업정책보험금융원",
    "kdb": "한국산업은행",
    "koreapost": "우정사업본부",
    "poba": "대한지방행정공제회",
    "ktcu": "한국교직원공제회",
    "pmaa": "경찰공제회",
    "cu": "신협중앙회",
    "kfcc": "새마을금고중앙회",
    "kexim": "한국수출입은행",
    "kbiz": "중소기업중앙회",
    "ibk": "IBK기업은행",
}
LP_CONTEXT_SEED_INSTITUTIONS = {
    "kic": {
        "lp_name": "한국투자공사",
        "aliases": ("한국투자공사", "KIC", "Korea Investment Corporation"),
    },
}
KTCU_FACT_SECTION_LABELS = {
    "general": "일반현황",
    "investment_status": "투자현황",
    "investment_strategy": "투자전략",
    "investment_org": "담당 조직",
    "investment_governance": "투자 의사결정",
    "public_people": "핵심 의사결정자",
    "notice_history": "출자공고 히스토리",
    "recent_news": "최근 동향",
    "data_gap": "참고사항",
}
KTCU_FACT_SECTION_ORDER = {
    "general": 10,
    "investment_status": 20,
    "investment_strategy": 30,
    "investment_org": 40,
    "investment_governance": 50,
    "public_people": 60,
    "notice_history": 70,
    "recent_news": 80,
    "data_gap": 90,
}

LEGACY_SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))
if str(LEGACY_SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(LEGACY_SCRIPTS_DIR))
from brand_assets import brand_logo_url, brand_style_attr  # noqa: E402
from build_service_site import (  # noqa: E402
    DEFAULT_ARCHIVE_LIMIT,
    DEFAULT_EXPORT_DIR,
    DEFAULT_LP_COMMITMENT_MONITOR,
    DEFAULT_SERVICE_INTEGRATION_WORKLIST,
    article_payload_rows,
    app_asset_version,
    app_head_meta,
    brief_markdown_path,
    build,
    compact_date,
    display_date,
    html_escape,
    is_public_lp_notice_row,
    merge_service_context,
    normalize_url,
    parse_brief,
    parse_brief_basis,
    read_lp_monitor,
    read_service_context,
    render_app,
    render_public_product_header,
)
from daily_news_common import today_seoul  # noqa: E402
from gp_service_pages import write_gp_pages  # noqa: E402
from pef_wiki_pages import render_pef_wiki_page  # noqa: E402


ARCHIVE_SCRIPT_RE = re.compile(
    r"<script>window\.KPEF_DAILY_ARCHIVE\s*=\s*(?P<payload>.*?);</script>",
    re.DOTALL,
)


def assert_newsletter_only(site_dir: Path) -> None:
    for name in ["index.html", "daily-news.html"]:
        html = (site_dir / name).read_text(encoding="utf-8")
        if 'href="db.html#lp"' in html or 'href="db.html#profile"' in html:
            raise RuntimeError(f"{name} still contains obsolete DB-anchor navigation")
    if (site_dir / "admin.html").exists():
        raise RuntimeError("admin.html must not be included in the public deploy site")


def write_health_file(site_dir: Path, result: dict[str, str]) -> None:
    payload = {
        "service": "kpef-newsletter",
        "status": "ok",
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "report_date": result.get("report_date", ""),
        "article_count": int(result.get("article_count", "0") or 0),
        "lp_monitor_count": int(result.get("lp_monitor_count", "0") or 0),
        "ktcu_fact_count": int(result.get("ktcu_fact_count", "0") or 0),
        "lp_profile_fact_count": int(result.get("lp_profile_fact_count", result.get("ktcu_fact_count", "0")) or 0),
        "lp_profile_page_count": int(result.get("lp_profile_page_count", "0") or 0),
        "gp_count": int(result.get("gp_count", "0") or 0),
        "gp_active_count": int(result.get("active_gp_count", "0") or 0),
        "gp_profile_page_count": int(result.get("top_gp_page_count", "0") or 0),
        "gp_news_link_count": int(result.get("news_link_count", "0") or 0),
        "public_db_page": (site_dir / "db.html").exists(),
    }
    (site_dir / "health.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_lp_article_context(
    context: dict[str, dict[str, object]],
    source_url: object,
    normalized_source_url: object,
    lp_code: object,
    lp_name: object,
    aliases: object = "",
) -> None:
    name = str(lp_name or lp_code or "").strip()
    code = str(lp_code or "").strip()
    if not name or not code:
        return
    keys = []
    for value in [normalized_source_url, source_url]:
        text = str(value or "").strip()
        if not text:
            continue
        for key in [normalize_url(text), text]:
            if key and key not in keys:
                keys.append(key)
    for key in keys:
        entry = context.setdefault(key, {"lpNames": [], "lpProfileLinks": [], "searchTerms": []})
        lp_names = entry.setdefault("lpNames", [])
        if name not in lp_names:
            lp_names.append(name)
        search_terms = entry.setdefault("searchTerms", [])
        for term in [name, code, *[part.strip() for part in str(aliases or "").split(";") if part.strip()]]:
            if term and term not in search_terms:
                search_terms.append(term)
        links = entry.setdefault("lpProfileLinks", [])
        link = {"code": code, "name": name, "url": f"lp-{code}.html"}
        if not any(isinstance(item, dict) and item.get("code") == code for item in links):
            links.append(link)


def read_lp_article_context(db_path: Path = DEFAULT_DB) -> dict[str, dict[str, object]]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    context: dict[str, dict[str, object]] = {}
    try:
        if db_object_exists(conn, "lp_notice_news_link") and db_object_exists(conn, "news_document"):
            rows = fetch_dicts(
                conn,
                """
                SELECT
                    nd.source_url,
                    nd.normalized_source_url,
                    lnnl.lp_code,
                    COALESCE(li.lp_name, lnnl.lp_code) AS lp_name,
                    COALESCE(li.aliases, '') AS aliases
                FROM lp_notice_news_link lnnl
                JOIN news_document nd
                  ON nd.news_id = lnnl.news_id
                LEFT JOIN lp_institution li
                  ON li.lp_code = lnnl.lp_code
                """,
            )
            for row in rows:
                add_lp_article_context(
                    context,
                    row.get("source_url"),
                    row.get("normalized_source_url"),
                    row.get("lp_code"),
                    row.get("lp_name"),
                    row.get("aliases"),
                )
        if db_object_exists(conn, "lp_commitment_notice"):
            rows = fetch_dicts(
                conn,
                """
                SELECT
                    lcn.notice_url AS source_url,
                    lcn.normalized_notice_url AS normalized_source_url,
                    lcn.lp_code,
                    COALESCE(li.lp_name, lcn.lp_code) AS lp_name,
                    COALESCE(li.aliases, '') AS aliases
                FROM lp_commitment_notice lcn
                LEFT JOIN lp_institution li
                  ON li.lp_code = lcn.lp_code
                WHERE lcn.source_type = 'news'
                  AND COALESCE(lcn.public_visible, 1) = 1
                """,
            )
            for row in rows:
                add_lp_article_context(
                    context,
                    row.get("source_url"),
                    row.get("normalized_source_url"),
                    row.get("lp_code"),
                    row.get("lp_name"),
                    row.get("aliases"),
                )
    finally:
        conn.close()
    return context


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


def read_lp_alias_patterns(db_path: Path = DEFAULT_DB) -> list[dict[str, object]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        if not db_object_exists(conn, "lp_institution"):
            return []
        rows = fetch_dicts(
            conn,
            """
            SELECT lp_code, lp_name, aliases
            FROM lp_institution
            ORDER BY service_priority DESC, lp_name
            """,
        )
    finally:
        conn.close()
    extras = {
        "kdb": ["국민성장펀드", "국민참여형 국민성장펀드"],
        "kvic": ["모태펀드", "한국모태펀드"],
        "kgrowth": ["성장금융"],
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


def add_title_matched_lp_article_context(
    context: dict[str, dict[str, object]],
    archive_entries: list[dict[str, object]],
    db_path: Path = DEFAULT_DB,
) -> None:
    patterns = read_lp_alias_patterns(db_path)
    if not patterns:
        return
    seen_dates = {str(entry.get("reportDate") or "") for entry in archive_entries if entry.get("reportDate")}
    for report_date in seen_dates:
        markdown_path = brief_markdown_path(DEFAULT_EXPORT_DIR, report_date)
        if not markdown_path.exists():
            continue
        for row in parse_brief(markdown_path):
            url = row.get("url", "")
            haystack = " ".join([row.get("title", ""), row.get("section", ""), row.get("source", "")])
            matched = 0
            for pattern in patterns:
                aliases = pattern.get("aliases") if isinstance(pattern.get("aliases"), list) else []
                if any(str(alias) and str(alias) in haystack for alias in aliases):
                    add_lp_article_context(
                        context,
                        url,
                        normalize_url(url),
                        pattern.get("lp_code"),
                        pattern.get("lp_name"),
                        ";".join(str(alias) for alias in aliases),
                    )
                    matched += 1
                if matched >= 3:
                    break


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


def refresh_archive_entries_with_context(
    archive_entries: list[dict[str, object]],
    service_context: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    refreshed: list[dict[str, object]] = []
    for entry in archive_entries:
        report_date = str(entry.get("reportDate") or "")
        markdown_path = brief_markdown_path(DEFAULT_EXPORT_DIR, report_date)
        if not report_date or not markdown_path.exists():
            refreshed.append(entry)
            continue
        rows = parse_brief(markdown_path)
        next_entry = dict(entry)
        next_entry["visibleDate"] = str(next_entry.get("visibleDate") or display_date(report_date))
        next_entry["articles"] = article_payload_rows(rows, service_context, f"clip-{compact_date(report_date)}")
        refreshed.append(next_entry)
    return refreshed


def write_static_support_files(site_dir: Path) -> None:
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
    (site_dir / "robots.txt").write_text("User-agent: *\nDisallow:\n", encoding="utf-8")
    (site_dir / "404.html").write_text((site_dir / "index.html").read_text(encoding="utf-8"), encoding="utf-8")


def write_pef_wiki_page(site_dir: Path, report_date: str) -> None:
    (site_dir / "pef-wiki.html").write_text(
        render_pef_wiki_page(report_date, app_asset_version()),
        encoding="utf-8",
    )


def write_public_db_page(site_dir: Path) -> None:
    public_dir = REPO_ROOT / "public"
    required = [
        public_dir / "db.html",
        public_dir / "assets" / "app.css",
        public_dir / "assets" / "app.js",
        public_dir / "data" / "service_data.json",
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing public DB files: {', '.join(missing)}")

    (site_dir / "assets").mkdir(parents=True, exist_ok=True)
    (site_dir / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy2(public_dir / "db.html", site_dir / "db.html")
    shutil.copy2(public_dir / "assets" / "app.css", site_dir / "assets" / "app.css")
    shutil.copy2(public_dir / "assets" / "app.js", site_dir / "assets" / "app.js")
    shutil.copy2(public_dir / "data" / "service_data.json", site_dir / "data" / "service_data.json")


def lp_event_label(value: object) -> str:
    return {
        "new_notice": "신규 공고",
        "deadline_soon": "마감 임박",
        "deadline_closed": "마감",
        "shortlist": "숏리스트",
        "final_selection": "최종 선정",
        "revision": "정정",
        "cancellation": "취소",
        "performance_update": "성과",
    }.get(str(value or ""), "공고")


def lp_amount_label(value: object) -> str:
    try:
        parsed = float(str(value or "0").replace(",", ""))
    except ValueError:
        return ""
    if parsed <= 0:
        return ""
    if parsed >= 10000:
        return f"{parsed / 10000:,.1f}조"
    return f"{round(parsed):,}억"


def split_notice_names(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw_parts = [str(item or "") for item in value]
    else:
        raw_parts = re.split(r"[;,]", str(value or ""))
    names: list[str] = []
    seen: set[str] = set()
    for raw_part in raw_parts:
        for part in re.split(r"[;,]", raw_part):
            name = clean_public_lp_text(part)
            if not name or name in seen:
                continue
            names.append(name)
            seen.add(name)
    return names


def notice_gp_label(value: object, limit: int = 2) -> str:
    names = split_notice_names(value)
    if not names:
        return "-"
    if len(names) <= limit:
        return " · ".join(names)
    return f"{' · '.join(names[:limit])} 외 {len(names) - limit}"


def lp_notice_date(value: object):
    text = str(value or "").strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def lp_notice_status(item: dict[str, object], report_date: str) -> str:
    event_type = str(item.get("eventType") or "")
    if event_type in {"final_selection", "shortlist", "performance_update"}:
        return "result"
    if event_type in {"cancellation", "deadline_closed"}:
        return "closed"
    today = lp_notice_date(report_date)
    deadline = lp_notice_date(item.get("applicationDeadline"))
    event_date = lp_notice_date(item.get("eventDate") or item.get("announcedDate"))
    if today and deadline:
        return "open" if deadline >= today else "closed"
    if event_type == "deadline_soon":
        return "open"
    if event_type == "new_notice" and today and event_date:
        return "open" if today - event_date <= timedelta(days=45) else "history"
    return "history"


def lp_notice_status_label(status: str) -> str:
    return {
        "open": "진행중",
        "result": "선정결과",
        "closed": "마감",
        "history": "히스토리",
    }.get(status, "공고")


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


def lp_notice_stats(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    stats: dict[str, dict[str, object]] = {}
    for row in rows:
        if not is_public_lp_notice_row(row, require_official=True):
            continue
        lp_code = str(row.get("lp_code") or "").strip()
        if not lp_code:
            continue
        entry = stats.setdefault(
            lp_code,
            {"notice_count": 0, "allocation_amount_krw_100mn": 0.0, "latest_event_date": ""},
        )
        entry["notice_count"] = int(entry["notice_count"]) + 1
        entry["allocation_amount_krw_100mn"] = float(entry["allocation_amount_krw_100mn"]) + safe_float(
            row.get("allocation_amount_krw_100mn")
        )
        event_date = str(row.get("event_date") or row.get("announced_date") or "")
        if event_date > str(entry.get("latest_event_date") or ""):
            entry["latest_event_date"] = event_date
    return stats


def read_lp_notice_stats(conn: sqlite3.Connection) -> dict[str, dict[str, object]]:
    if not db_object_exists(conn, "v_lp_commitment_notice_public"):
        return {}
    return lp_notice_stats(fetch_dicts(conn, "SELECT * FROM v_lp_commitment_notice_public WHERE public_visible = 1"))


def merge_lp_notice_stats(row: dict[str, object], stats: dict[str, dict[str, object]]) -> dict[str, object]:
    merged = dict(row)
    lp_code = str(merged.get("lp_code") or "")
    public_stats = stats.get(lp_code, {})
    visible_notice_count = safe_int(public_stats.get("notice_count"))
    merged["profile_notice_count"] = safe_int(merged.get("notice_count"))
    merged["visible_notice_count"] = visible_notice_count
    merged["notice_count"] = visible_notice_count
    merged["allocation_amount_krw_100mn"] = safe_float(public_stats.get("allocation_amount_krw_100mn"))
    merged["latest_event_date"] = str(public_stats.get("latest_event_date") or "")
    merged["has_public_profile"] = bool(safe_int(merged.get("fact_count")) > 0 or visible_notice_count > 0)
    return merged


def yearly_stats_from_notices(notices: list[dict[str, object]]) -> list[dict[str, object]]:
    by_year: dict[str, dict[str, object]] = {}
    for notice in notices:
        if str(notice.get("source_type") or "") != "official":
            continue
        year = str(notice.get("notice_year") or (str(notice.get("event_date") or "")[:4]))
        if not re.fullmatch(r"20\d{2}", year):
            continue
        row = by_year.setdefault(year, {"notice_year": year, "notice_count": 0, "allocation_amount_krw_100mn": 0.0})
        row["notice_count"] = int(row["notice_count"]) + 1
        row["allocation_amount_krw_100mn"] = float(row["allocation_amount_krw_100mn"]) + safe_float(
            notice.get("allocation_amount_krw_100mn")
        )
    return [by_year[year] for year in sorted(by_year, reverse=True)]


def amount_short(value: object) -> str:
    try:
        parsed = float(str(value or "0").replace(",", ""))
    except ValueError:
        return "-"
    if parsed <= 0:
        return "-"
    if parsed >= 10000:
        return f"{parsed / 10000:,.2f}조"
    return f"{round(parsed):,}억"


def public_amount_label(value: object, fallback: str = "-") -> str:
    label = amount_short(value)
    return fallback if label == "-" else label


def fact_value(facts: list[dict[str, object]], label: str, fallback: str = "-") -> str:
    for fact in facts:
        if str(fact.get("label") or "") == label:
            return str(fact.get("value") or fallback)
    return fallback


def first_fact_pair(facts: list[dict[str, object]], labels: list[str], fallback: str = "-") -> tuple[str, str]:
    for label in labels:
        value = fact_value(facts, label, "")
        if value:
            return label, value
    return "", fallback


def compact_alternative_amount(value: str, fallback: str) -> str:
    match = re.search(r"대체투자\s+([0-9,]+)억원", value)
    if match:
        return amount_short(match.group(1))
    if "45조 4,724억원" in value:
        return "45.5조"
    return fallback or "-"


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


def public_lp_type(value: object) -> str:
    text = str(value or "").strip()
    return LP_TYPE_LABELS.get(text, text or "LP")


def public_asset_class(value: object) -> str:
    text = str(value or "").strip()
    return ASSET_CLASS_LABELS.get(text, text or "기타")


def display_asset_classes(value: object) -> str:
    parts = split_asset_classes(value)
    return " · ".join(parts) if parts else "-"


def clean_public_lp_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    simple_labels = {
        "public": "공공",
        "private": "민간",
        "policy": "정책",
    }
    if text.lower() in simple_labels:
        return simple_labels[text.lower()]
    regex_replacements = [
        (r"작업\s*큐", ""),
        (r"검토\s*대기", ""),
        (r"자료\s*정리\s*중", ""),
        (r"공개\s*신호\s*관측", ""),
        (r"출자\s+신호", "출자 동향"),
        (r"뉴스\s+기반\s+출자\s+신호", "뉴스 기반 출자 동향"),
        (r"보강\s*필요", ""),
        (r"검증\s*필요", ""),
        (r"프로필\s*팩트", "프로필 항목"),
        (r"자동\s*매칭", "연결"),
        (r"데이터\s*수집", "자료"),
        (r"관리\s*자", "서비스"),
        (r"source\s*/\s*[e]vidence", "자료"),
        (r"\bAUM\s+proxy\b", "운용자산 기준"),
        (r"근거\s*자료", "자료"),
        (r"자료\s*없음", ""),
    ]
    for pattern, replacement in regex_replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = text.replace("canonical notice_id", "공식 공고")
    text = re.sub(r"(보강|검증|구조화|정규화)\s*필요", "", text)
    text = re.sub(r"\b보강\b", "확인", text)
    text = re.sub(r"\b검증\b", "확인", text)
    text = re.sub(r"\b관측\b", "확인", text)
    text = text.replace("신호", "동향")
    text = re.sub(r"\bAUM\b", "운용자산", text)
    text = text.replace("실무자명", "담당자")
    return re.sub(r"\s+", " ", text).strip()


def public_fact_label(value: object) -> str:
    return clean_public_lp_text(value)


def public_fact_value(value: object) -> str:
    return clean_public_lp_text(value)


def lp_short_label(lp_code: str, lp_name: str) -> str:
    return LP_PROFILE_SHORT_LABELS.get(lp_code, lp_name)


def lp_display_label(lp_code: str, lp_name: str) -> str:
    return LP_PROFILE_DISPLAY_LABELS.get(lp_code, lp_name)


def directory_avatar_label(value: object, fallback: str = "K") -> str:
    text = re.sub(r"\s+", "", str(value or "").strip())
    if not text:
        return fallback
    korean = "".join(re.findall(r"[가-힣]", text))
    if korean:
        return korean[:2]
    letters = re.findall(r"[A-Za-z0-9]", text)
    return "".join(letters[:2]).upper() or fallback


def directory_avatar_tone(value: object) -> int:
    text = str(value or "").strip()
    if not text:
        return 1
    return (sum(ord(char) for char in text) % 6) + 1


def directory_logo_url(url: object) -> str:
    return brand_logo_url(url)


def directory_logo_style(url: object) -> str:
    return brand_style_attr(url)


def directory_avatar_markup(homepage_url: object, label: str, seed: object = "") -> str:
    logo_url = directory_logo_url(homepage_url)
    tone = directory_avatar_tone(seed or label)
    style_attr = directory_logo_style(homepage_url)
    if logo_url:
        return (
            f'<span class="lp-directory-avatar has-logo" data-tone="{tone}" aria-hidden="true"{style_attr}>'
            f'<img src="{logo_url}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.classList.add(\'fallback-only\'); this.remove()">'
            f'<span>{html_escape(label)}</span></span>'
        )
    return f'<span class="lp-directory-avatar" data-tone="{tone}" aria-hidden="true"><span>{html_escape(label)}</span></span>'


def render_service_bottom_nav(active: str) -> str:
    items = [
        ("brief", "index.html", "브리프", "nav-icon-brief"),
        ("lp", "lp-notices.html", "LP", "nav-icon-lp"),
        ("gp", "gps.html", "GP", "nav-icon-gp"),
        ("wiki", "pef-wiki.html", "Wiki", "nav-icon-wiki"),
    ]
    links = "\n".join(
        f"""    <a class="{'active' if key == active else ''}" href="{href}">
      <span aria-hidden="true" class="nav-dot {icon}"></span>
      <strong>{label}</strong>
    </a>"""
        for key, href, label, icon in items
    )
    return f"""  <nav class="bottom-nav newsletter-only" aria-label="하단 메뉴">
{links}
  </nav>"""


def render_lp_service_header(active_tab: str, search_input_id: str, placeholder: str) -> str:
    lp_active = " active" if active_tab == "lp" else ""
    lp_current = ' aria-current="page"' if active_tab == "lp" else ""
    notice_active = " active" if active_tab == "notice" else ""
    notice_current = ' aria-current="page"' if active_tab == "notice" else ""
    return f"""    <header class="app-header lp-app-header">
      <div class="service-bar">
        <strong class="service-title">LP</strong>
        <section class="search-area" id="searchArea" aria-label="LP 검색">
          <label class="search-box">
            <span aria-hidden="true"></span>
            <input id="{html_escape(search_input_id)}" type="search" placeholder="{html_escape(placeholder)}" autocomplete="off">
          </label>
          <button class="search-close" id="searchClose" type="button" aria-label="검색 닫기"></button>
        </section>
        <div class="service-actions" aria-label="LP 도구">
          <button class="header-icon search-toggle" id="searchToggle" type="button" aria-label="검색 열기" aria-expanded="false"></button>
        </div>
      </div>
      <nav class="brief-section-tabs lp-section-tabs" aria-label="LP 메뉴">
        <a class="brief-section-tab{lp_active}" href="lp-notices.html"{lp_current}>LP</a>
        <a class="brief-section-tab{notice_active}" href="lp-official-notices.html"{notice_current}>NOTICE</a>
        <button class="brief-section-tab" type="button" disabled>PEOPLE</button>
      </nav>
    </header>"""


def lp_header_script() -> str:
    return """      const serviceBar = document.querySelector(".service-bar");
      const searchArea = document.getElementById("searchArea");
      const searchInput = searchArea?.querySelector("input");
      const searchToggle = document.getElementById("searchToggle");
      const searchClose = document.getElementById("searchClose");
      const setSearchOpen = (open) => {
        if (!serviceBar || !searchArea || !searchToggle) return;
        serviceBar.classList.toggle("search-open", open);
        searchArea.classList.toggle("visible", open);
        searchToggle.setAttribute("aria-expanded", String(open));
        if (open) searchInput?.focus();
      };
      searchToggle?.addEventListener("click", () => setSearchOpen(true));
      searchClose?.addEventListener("click", () => {
        if (searchInput) {
          searchInput.value = "";
          searchInput.dispatchEvent(new Event("input", { bubbles: true }));
        }
        setSearchOpen(false);
      });"""


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
                ORDER BY service_priority DESC, lp_name
                """,
            )
            notice_stats = read_lp_notice_stats(conn)
        else:
            rows = []
    except sqlite3.OperationalError:
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


def read_lp_profile_nav(db_path: Path = DEFAULT_DB, profile_codes: list[str] | None = None) -> list[dict[str, str]]:
    codes = profile_codes or read_lp_profile_codes(db_path)
    if not codes:
        return []
    fallback = [
        {
            "lp_code": code,
            "lp_name": LP_PROFILE_DISPLAY_LABELS.get(code, code),
            "label": LP_PROFILE_DISPLAY_LABELS.get(code, code),
        }
        for code in codes
    ]
    if not db_path.exists():
        return fallback
    conn = sqlite3.connect(db_path)
    try:
        if not db_object_exists(conn, "lp_institution"):
            return fallback
        placeholders = ", ".join("?" for _ in codes)
        rows = fetch_dicts(
            conn,
            f"""
            SELECT lp_code, lp_name
            FROM lp_institution
            WHERE lp_code IN ({placeholders})
            """,
            tuple(codes),
        )
    finally:
        conn.close()
    by_code = {str(row.get("lp_code") or ""): row for row in rows}
    nav_items: list[dict[str, str]] = []
    for code in codes:
        row = by_code.get(code, {})
        lp_name = str(row.get("lp_name") or LP_PROFILE_DISPLAY_LABELS.get(code, code))
        nav_items.append({"lp_code": code, "lp_name": lp_name, "label": lp_display_label(code, lp_name)})
    return nav_items


def read_lp_directory_items(db_path: Path = DEFAULT_DB) -> list[dict[str, object]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        if not db_object_exists(conn, "v_lp_profile_summary"):
            return []
        rows = fetch_dicts(
            conn,
            """
            SELECT
                lp_code,
                lp_name,
                lp_type,
                ownership_type,
                homepage_url,
                notice_url,
                default_team,
                focus_asset_classes,
                service_priority,
                notice_count,
                allocation_amount_krw_100mn,
                latest_event_date,
                fact_count,
                source_count
            FROM v_lp_profile_summary
            ORDER BY service_priority DESC, lp_name
            """,
        )
        notice_stats = read_lp_notice_stats(conn)
        return [merge_lp_notice_stats(row, notice_stats) for row in rows]
    finally:
        conn.close()


def render_lp_profile_nav(nav_items: list[dict[str, str]], active_code: str = "") -> str:
    rows = nav_items or [
        {
            "lp_code": code,
            "lp_name": LP_PROFILE_DISPLAY_LABELS.get(code, code),
            "label": LP_PROFILE_DISPLAY_LABELS.get(code, code),
        }
        for code in LP_PROFILE_FALLBACK_CODES
    ]
    links = []
    for item in rows:
        code = str(item.get("lp_code") or "")
        label = str(item.get("label") or item.get("lp_name") or code)
        active_class = " active" if code == active_code else ""
        links.append(
            f'<a class="ktcu-profile-link{active_class}" href="lp-{html_escape(code)}.html">{html_escape(label)}</a>'
        )
    return "\n          ".join(links)


def read_ktcu_payload(db_path: Path = DEFAULT_DB, lp_code: str = KTCU_CODE, profile_codes: list[str] | None = None) -> dict[str, object]:
    if not db_path.exists():
        return {"profile": {}, "facts": [], "notices": [], "yearly": []}
    conn = sqlite3.connect(db_path)
    try:
        profile = {}
        notice_stats = read_lp_notice_stats(conn)
        if db_object_exists(conn, "v_lp_profile_summary"):
            rows = fetch_dicts(
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
                    notes,
                    notice_count,
                    allocation_amount_krw_100mn,
                    latest_event_date,
                    latest_announced_date,
                    fact_count,
                    source_count
                FROM v_lp_profile_summary
                WHERE lp_code = ?
                LIMIT 1
                """,
                (lp_code,),
            )
            profile = rows[0] if rows else {}
        elif db_object_exists(conn, "lp_institution"):
            stats_join = (
                """
                LEFT JOIN v_lp_institution_stats stats
                  ON stats.lp_code = li.lp_code
                """
                if db_object_exists(conn, "v_lp_institution_stats")
                else ""
            )
            stats_columns = (
                """
                COALESCE(stats.notice_count, 0) AS notice_count,
                COALESCE(stats.allocation_amount_krw_100mn, 0) AS allocation_amount_krw_100mn,
                COALESCE(stats.latest_event_date, '') AS latest_event_date
                """
                if stats_join
                else """
                0 AS notice_count,
                0 AS allocation_amount_krw_100mn,
                '' AS latest_event_date
                """
            )
            rows = fetch_dicts(
                conn,
                f"""
                SELECT
                    li.lp_code,
                    li.lp_name,
                    li.lp_name_en,
                    li.lp_type,
                    li.ownership_type,
                    li.homepage_url,
                    li.notice_url,
                    li.default_team,
                    li.focus_asset_classes,
                    li.notes,
                    {stats_columns}
                FROM lp_institution li
                {stats_join}
                WHERE li.lp_code = ?
                LIMIT 1
                """,
                (lp_code,),
            )
            profile = rows[0] if rows else {}
        if profile:
            profile = merge_lp_notice_stats(profile, notice_stats)

        fact_source = "v_lp_profile_fact_public" if db_object_exists(conn, "v_lp_profile_fact_public") else "lp_profile_fact"
        facts = (
            fetch_dicts(
                conn,
                f"""
                SELECT
                    section,
                    label,
                    value,
                    as_of_date,
                    source_name,
                    source_url,
                    confidence,
                    notes,
                    sort_order
                FROM {fact_source}
                WHERE lp_code = ?
                  {"AND public_visible = 1" if fact_source == "lp_profile_fact" else ""}
                ORDER BY section, sort_order, label
                """,
                (lp_code,),
            )
            if db_object_exists(conn, fact_source)
            else []
        )
        facts.sort(
            key=lambda row: (
                KTCU_FACT_SECTION_ORDER.get(str(row.get("section") or ""), 99),
                int(row.get("sort_order") or 0),
                str(row.get("label") or ""),
            )
        )

        notices = (
            fetch_dicts(
                conn,
                """
                SELECT
                    notice_id,
                    source_type,
                    source_code,
                    event_date,
                    title,
                    notice_url,
                    document_url,
                    announced_date,
                    application_deadline,
                    notice_year,
                    event_type,
                    asset_class,
                    strategy,
                    allocation_amount_krw_100mn,
                    amount_confidence,
                    selected_gp_names,
                    confidence,
                    confidence_note,
                    monitor_status,
                    raw_excerpt
                FROM v_lp_commitment_notice_public
                WHERE lp_code = ?
                  AND public_visible = 1
                ORDER BY COALESCE(event_date, announced_date) DESC, notice_id DESC
                """,
                (lp_code,),
            )
            if db_object_exists(conn, "v_lp_commitment_notice_public")
            else []
        )
        notices = [row for row in notices if is_public_lp_notice_row(row)]

        yearly = yearly_stats_from_notices(notices)

        peer_source = "v_lp_profile_peer_compare" if db_object_exists(conn, "v_lp_profile_peer_compare") else "v_lp_profile_summary"
        peer_codes = profile_codes or read_lp_profile_codes(db_path)
        peers = (
            fetch_dicts(
                conn,
                f"""
                SELECT
                    lp_code,
                    lp_name,
                    lp_type,
                    ownership_type,
                    default_team,
                    focus_asset_classes,
                    service_priority,
                    notice_count,
                    allocation_amount_krw_100mn,
                    latest_event_date,
                    fact_count,
                    source_count
                FROM {peer_source}
                WHERE lp_code IN ({", ".join("?" for _ in peer_codes)})
                ORDER BY service_priority DESC, lp_name
                """,
                tuple(peer_codes),
            )
            if db_object_exists(conn, peer_source)
            else []
        )
        peers = [merge_lp_notice_stats(row, notice_stats) for row in peers]

        gp_links = (
            fetch_dicts(
                conn,
                """
                SELECT
                    lgl.notice_id,
                    lgl.lp_code,
                    lgl.source_gp_id,
                    lgl.gp_name,
                    lgl.matched_alias,
                    lgl.confidence,
                    lcn.confidence AS notice_confidence,
                    lcn.public_visible,
                    lcn.monitor_status,
                    lcn.event_type,
                    lcn.source_type,
                    lcn.event_date,
                    lcn.title AS notice_title
                FROM lp_notice_gp_link lgl
                LEFT JOIN lp_commitment_notice lcn
                  ON lcn.notice_id = lgl.notice_id
                WHERE lgl.lp_code = ?
                  AND COALESCE(lcn.public_visible, 1) = 1
                ORDER BY
                    CASE lgl.confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    COALESCE(lcn.event_date, lcn.announced_date, lcn.discovered_at) DESC,
                    lgl.gp_name
                LIMIT 16
                """,
                (lp_code,),
            )
            if db_object_exists(conn, "lp_notice_gp_link") and db_object_exists(conn, "lp_commitment_notice")
            else []
        )
        gp_links = [
            row
            for row in gp_links
            if is_public_lp_notice_row(
                {
                    "source_type": row.get("source_type"),
                    "event_type": row.get("event_type"),
                    "monitor_status": row.get("monitor_status"),
                    "confidence": row.get("notice_confidence"),
                    "public_visible": row.get("public_visible"),
                },
                require_official=True,
            )
        ]

        related_news = (
            fetch_dicts(
                conn,
                """
                SELECT
                    lnnl.notice_id,
                    nd.news_id,
                    nd.publisher,
                    nd.title AS news_title,
                    nd.source_url,
                    nd.published_at,
                    nd.discovered_at,
                    lnnl.link_source,
                    lnnl.confidence,
                    lcn.source_type,
                    lcn.event_type,
                    lcn.confidence AS notice_confidence,
                    lcn.public_visible,
                    lcn.monitor_status
                FROM lp_notice_news_link lnnl
                JOIN news_document nd
                  ON nd.news_id = lnnl.news_id
                JOIN lp_commitment_notice lcn
                  ON lcn.notice_id = lnnl.notice_id
                WHERE lnnl.lp_code = ?
                  AND lcn.public_visible = 1
                ORDER BY COALESCE(nd.published_at, nd.discovered_at) DESC, nd.news_id DESC
                LIMIT 12
                """,
                (lp_code,),
            )
            if db_object_exists(conn, "lp_notice_news_link") and db_object_exists(conn, "news_document")
            else []
        )
        related_news = [
            row
            for row in related_news
            if is_public_lp_notice_row(
                {
                    "source_type": row.get("source_type"),
                    "event_type": row.get("event_type"),
                    "monitor_status": row.get("monitor_status"),
                    "confidence": row.get("notice_confidence"),
                    "public_visible": row.get("public_visible"),
                },
                require_official=True,
            )
        ]
    finally:
        conn.close()
    return {"profile": profile, "facts": facts, "notices": notices, "yearly": yearly, "peers": peers, "gp_links": gp_links, "news": related_news}


def render_ktcu_fact_section(section: str, rows: list[dict[str, object]]) -> str:
    rendered: list[str] = []
    for row in rows:
        label = public_fact_label(row.get("label"))
        value = public_fact_value(row.get("value"))
        if not label or not value:
            continue
        source_name = clean_public_lp_text(row.get("source_name")) or "자료 보기"
        rendered.append(
            f"""          <div>
            <dt>{html_escape(label)}</dt>
            <dd>
              <span>{html_escape(value)}</span>
              {f'<a href="{html_escape(str(row.get("source_url") or ""))}" target="_blank" rel="noreferrer">{html_escape(source_name)}</a>' if row.get("source_url") else ""}
            </dd>
          </div>"""
        )
    if not rendered:
        return ""
    items = "\n".join(rendered)
    return f"""      <section class="ktcu-fact">
        <h2>{html_escape(KTCU_FACT_SECTION_LABELS.get(section, section))}</h2>
        <dl>
{items}
        </dl>
      </section>"""


def render_ktcu_notice_row(row: dict[str, object]) -> str:
    title = str(row.get("title") or "공고")
    url = str(row.get("notice_url") or "")
    title_html = (
        f'<a href="{html_escape(url)}" target="_blank" rel="noreferrer">{html_escape(title)}</a>'
        if url
        else html_escape(title)
    )
    meta = " · ".join(
        value
        for value in [
            public_asset_class(row.get("asset_class")) if row.get("asset_class") else "",
            str(row.get("strategy") or ""),
            f"마감 {row.get('application_deadline')}" if row.get("application_deadline") else "",
        ]
        if value
    )
    return f"""        <article class="ktcu-notice">
          <div>
            <time>{html_escape(str(row.get("event_date") or "-"))}</time>
            <h3>{title_html}</h3>
            <p>{html_escape(meta or "공식 공고")}</p>
          </div>
          <strong>{html_escape(public_amount_label(row.get("allocation_amount_krw_100mn")))}</strong>
        </article>"""


def render_ktcu_year_bar(row: dict[str, object], max_amount: float) -> str:
    amount = float(row.get("allocation_amount_krw_100mn") or 0)
    width = 0 if max_amount <= 0 else max(4, min(100, amount / max_amount * 100))
    return f"""        <div class="ktcu-year-row">
          <span>{html_escape(str(row.get("notice_year") or "-"))}</span>
          <div><i style="width: {width:.1f}%"></i></div>
          <strong>{html_escape(amount_short(amount))}</strong>
        </div>"""


def facts_in_section(facts: list[dict[str, object]], section: str) -> list[dict[str, object]]:
    return [fact for fact in facts if str(fact.get("section") or "") == section]


def lp_source_icon(source_url: object, source_name: object) -> tuple[str, str]:
    url = str(source_url or "")
    name = str(source_name or "")
    parsed = urlparse(url)
    domain = parsed.netloc.lower().removeprefix("www.")
    haystack = f"{domain} {name} {url}".lower()
    if "linkedin.com" in haystack:
        return "linkedin", "LinkedIn"
    if (
        urlparse(url).path.lower().endswith(".pdf")
        or "getfile" in haystack
        or "filety=attach" in haystack
        or re.search(r"보고서|공시|공고|정관|규정|pdf", name, re.I)
    ):
        return "document", "자료"
    if re.search(
        r"뉴스|기사|신문|경제|일보|투데이|타임즈|데일리|thebell|dealsite|hankyung|mk\.co\.kr|sedaily|chosun|news",
        haystack,
        re.I,
    ):
        return "article", "기사"
    return "home", "홈페이지"


def render_lp_source_icon(source_url: object, source_name: object) -> str:
    url = str(source_url or "")
    if not url:
        return ""
    kind, label = lp_source_icon(url, source_name)
    icon = {
        "home": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10.5 12 4l8 6.5"/><path d="M6.5 10v9h11v-9"/><path d="M10 19v-5h4v5"/></svg>',
        "document": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4h7l3 3v13H7z"/><path d="M14 4v4h4"/><path d="M9.5 12h5"/><path d="M9.5 15.5h5"/></svg>',
        "article": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5h14v14H5z"/><path d="M8 9h8"/><path d="M8 12h8"/><path d="M8 15h5"/></svg>',
        "linkedin": '<span aria-hidden="true">in</span>',
    }.get(kind, '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7"/><path d="M9 7h8v8"/></svg>')
    return (
        f'<a class="ktcu-source-icon ktcu-source-{html_escape(kind)}" '
        f'href="{html_escape(url)}" target="_blank" rel="noreferrer" '
        f'aria-label="출처: {html_escape(label)}" title="{html_escape(label)}">'
        f'{icon}</a>'
    )


def render_ktcu_fact_list(rows: list[dict[str, object]]) -> str:
    rendered: list[str] = []
    for row in rows:
        source_url = str(row.get("source_url") or "")
        source_name = clean_public_lp_text(row.get("source_name"))
        source_html = render_lp_source_icon(source_url, source_name)
        label = public_fact_label(row.get("label"))
        value = public_fact_value(row.get("value"))
        if not label or not value:
            continue
        rendered.append(
            f"""          <div>
            <dt>{html_escape(label)}</dt>
            <dd><span>{html_escape(value)}</span>{source_html}</dd>
          </div>"""
        )
    return "\n".join(rendered)


def confidence_label(value: object) -> str:
    return {
        "high": "공식 확인",
        "medium": "참고 자료",
        "low": "참고 자료",
    }.get(str(value or ""), "")


def render_ktcu_source_links(facts: list[dict[str, object]]) -> str:
    seen: set[str] = set()
    links: list[str] = []
    for fact in facts:
        url = str(fact.get("source_url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        name = clean_public_lp_text(fact.get("source_name")) or "자료 보기"
        links.append(
            f'<a href="{html_escape(url)}" target="_blank" rel="noreferrer">{html_escape(name)}</a>'
        )
        if len(links) >= 9:
            break
    return "\n".join(f"          <li>{link}</li>" for link in links)


def render_ktcu_asset_mix(notices: list[dict[str, object]]) -> str:
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for notice in notices:
        asset_class = public_asset_class(notice.get("asset_class") or "기타")
        totals[asset_class] = totals.get(asset_class, 0.0) + float(notice.get("allocation_amount_krw_100mn") or 0)
        counts[asset_class] = counts.get(asset_class, 0) + 1
    rows = sorted(totals, key=lambda key: (-totals[key], key))
    return "\n".join(
        f"""          <div class="ktcu-mix-row">
            <span>{html_escape(asset_class)}</span>
            <strong>{html_escape(public_amount_label(totals[asset_class]))}</strong>
            <em>{counts[asset_class]}건</em>
          </div>"""
        for asset_class in rows
    )


def render_ktcu_annual_highlights(notices: list[dict[str, object]], year: int) -> str:
    rows = [
        notice
        for notice in notices
        if str(notice.get("event_date") or "").startswith(str(year))
    ]
    rows.sort(key=lambda row: float(row.get("allocation_amount_krw_100mn") or 0), reverse=True)
    return "\n".join(
        f"""          <div class="ktcu-highlight-row">
            <span>{html_escape(public_asset_class(row.get("asset_class") or "출자"))}</span>
            <strong>{html_escape(public_amount_label(row.get("allocation_amount_krw_100mn")))}</strong>
            <em>{html_escape(str(row.get("title") or ""))}</em>
          </div>"""
        for row in rows
    )


def split_asset_classes(value: object) -> list[str]:
    parts = [public_asset_class(part) for part in str(value or "").split(";") if part.strip()]
    deduped = list(dict.fromkeys(parts))
    return deduped or ["자산군 미표시"]


def render_asset_chips(value: object) -> str:
    return "\n".join(f"            <span>{html_escape(part)}</span>" for part in split_asset_classes(value))


def render_lp_peer_rows(peers: list[dict[str, object]], active_code: str) -> str:
    if not peers:
        return """          <p class="ktcu-empty-note">비교할 LP 프로필이 아직 없습니다.</p>"""
    rows: list[str] = [
        """          <div class="ktcu-peer-row ktcu-peer-head">
            <strong>LP</strong>
            <span>유형</span>
            <span>표시 공고</span>
            <span>규모</span>
          </div>"""
    ]
    ordered_peers = sorted(
        peers,
        key=lambda row: (
            0 if str(row.get("lp_code") or "") == active_code else 1,
            -int(row.get("service_priority") or 0),
            str(row.get("lp_name") or ""),
        ),
    )
    for row in ordered_peers:
        lp_code = str(row.get("lp_code") or "")
        active_class = " active" if lp_code == active_code else ""
        latest = str(row.get("latest_event_date") or "-")
        amount = public_amount_label(row.get("allocation_amount_krw_100mn"), fallback="-")
        rows.append(
            f"""          <a class="ktcu-peer-row{active_class}" href="lp-{html_escape(lp_code)}.html">
            <strong>{html_escape(str(row.get("lp_name") or lp_code))}</strong>
            <span data-label="유형">{html_escape(public_lp_type(row.get("lp_type") or "LP"))}</span>
            <span data-label="표시 공고">{html_escape(str(row.get("visible_notice_count", row.get("notice_count") or 0)))}건</span>
            <span data-label="규모" title="최신 공고일 {html_escape(latest)}">{html_escape(amount)}</span>
          </a>"""
        )
    return "\n".join(rows)


def render_profile_timeline(facts: list[dict[str, object]], notices: list[dict[str, object]], limit: int = 12) -> str:
    events: list[dict[str, str]] = []
    for notice in notices:
        amount = public_amount_label(notice.get("allocation_amount_krw_100mn"), fallback="")
        detail = " · ".join(
            part
            for part in [
                public_asset_class(notice.get("asset_class")) if notice.get("asset_class") else "",
                str(notice.get("strategy") or ""),
                amount,
            ]
            if part
        )
        events.append(
            {
                "date": str(notice.get("event_date") or ""),
                "tag": "관련 뉴스" if str(notice.get("source_type") or "") == "news" else "공식 공고",
                "kind": str(notice.get("source_type") or "official"),
                "asset": public_asset_class(notice.get("asset_class")) if notice.get("asset_class") else "",
                "title": clean_public_lp_text(notice.get("title")) or "공고",
                "detail": clean_public_lp_text(detail) or "공식 공고",
                "url": str(notice.get("notice_url") or ""),
            }
        )
    for fact in facts:
        section = str(fact.get("section") or "")
        if section not in {"notice_history", "recent_news"}:
            continue
        title = public_fact_label(fact.get("label"))
        detail = public_fact_value(fact.get("value"))
        if not title and not detail:
            continue
        events.append(
            {
                "date": str(fact.get("as_of_date") or ""),
                "tag": KTCU_FACT_SECTION_LABELS.get(section, "이벤트"),
                "kind": section,
                "asset": "",
                "title": title or "이벤트",
                "detail": detail,
                "url": str(fact.get("source_url") or ""),
            }
        )
    events.sort(key=lambda row: (row.get("date") or "0000-00-00", row.get("title") or ""), reverse=True)
    if not events:
        return """          <p class="ktcu-empty-note">공식 공고와 최근 뉴스가 확인되면 활동 타임라인으로 표시됩니다.</p>"""
    rows: list[str] = []
    for event in events[:limit]:
        title = html_escape(event.get("title") or "-")
        url = event.get("url") or ""
        title_html = f'<a href="{html_escape(url)}" target="_blank" rel="noreferrer">{title}</a>' if url else title
        year = (event.get("date") or "")[:4]
        rows.append(
            f"""          <article class="ktcu-timeline-item" data-kind="{html_escape(event.get("kind") or "")}" data-year="{html_escape(year)}" data-asset="{html_escape(event.get("asset") or "")}">
            <div>
              <time>{html_escape(event.get("date") or "-")}</time>
              <span>{html_escape(event.get("tag") or "이벤트")}</span>
            </div>
            <h3>{title_html}</h3>
            <p>{html_escape(event.get("detail") or "")}</p>
          </article>"""
        )
    return "\n".join(rows)


def render_related_gp_signals(notices: list[dict[str, object]], gp_links: list[dict[str, object]] | None = None) -> str:
    names: list[str] = []
    for link in gp_links or []:
        name = str(link.get("gp_name") or "").strip()
        if name and name not in names:
            names.append(name)
    for notice in notices:
        for name in re.split(r"[,;]", str(notice.get("selected_gp_names") or "")):
            clean_name = name.strip()
            if clean_name and clean_name not in names:
                names.append(clean_name)
    if not names:
        return """          <p class="ktcu-empty-note">공개 공고에서 확인된 선정 GP가 아직 없습니다.</p>"""
    return "\n".join(f"          <span>{html_escape(name)}</span>" for name in names[:10])


def render_related_news_rows(news_rows: list[dict[str, object]]) -> str:
    if not news_rows:
        return """          <p class="ktcu-empty-note">직접 관련된 뉴스는 아직 없습니다.</p>"""
    rows: list[str] = []
    for row in news_rows:
        title = html_escape(str(row.get("news_title") or "관련 뉴스"))
        url = str(row.get("source_url") or "")
        title_html = f'<a href="{html_escape(url)}" target="_blank" rel="noreferrer">{title}</a>' if url else title
        rows.append(
            f"""          <article class="ktcu-news-row">
            <span>{html_escape(str(row.get("publisher") or "뉴스"))} · {html_escape(str(row.get("published_at") or row.get("discovered_at") or "")[:10])}</span>
            <h3>{title_html}</h3>
          </article>"""
        )
    return "\n".join(rows)


def public_gap_text(value: object) -> str:
    text = str(value or "")
    if any(token in text for token in ["정규화", "notice_id", "중복 게시"]):
        return "같은 공고가 여러 공식 채널에 게시될 수 있어 중복 여부를 구분해 봐야 합니다."
    if any(token in text for token in ["구조화", "상세 첨부파일"]):
        return "첨부 자료와 최종 선정 결과는 공식 발표가 확인된 건만 반영합니다."
    if "선정 GP" in text:
        return "선정 GP와 개별 펀드 정보는 공식 발표가 확인된 건만 반영합니다."
    if any(token in text for token in ["잔액", "AUM", "최신"]):
        return "자산 규모와 대체투자 잔액은 최신 공식 자료가 확인된 항목만 반영합니다."
    if any(token in text for token in ["조달 공고", "투자 공고"]):
        return "입찰공고에는 조달·투자 공고가 함께 게시되므로 PE/VC 관련 공고만 표시합니다."
    return clean_public_lp_text(text)


def public_gap_label(value: object) -> str:
    text = str(value or "")
    if "공개자료" in text and "한계" in text:
        return "자료 범위"
    if any(token in text for token in ["정규화", "구조화", "수집"]) or re.search(r"보강|검증", text):
        return "참고사항"
    return clean_public_lp_text(text) or "참고사항"


def render_public_gap_rows(rows: list[dict[str, object]]) -> str:
    public_rows: list[dict[str, object]] = []
    for row in rows:
        public_row = dict(row)
        public_row["label"] = public_gap_label(row.get("label"))
        public_row["value"] = public_gap_text(row.get("value"))
        public_row["confidence"] = ""
        public_rows.append(public_row)
    return render_ktcu_fact_list(public_rows)


def public_coverage_label(fact_count: object, source_count: object) -> str:
    facts = int(fact_count or 0)
    if facts <= 0:
        return "0개"
    return f"{facts}개"


def ktcu_year_amount(notices: list[dict[str, object]], year: int) -> float:
    return sum(
        float(row.get("allocation_amount_krw_100mn") or 0)
        for row in notices
        if str(row.get("event_date") or "").startswith(str(year))
    )


def render_ktcu_page(report_date: str, payload: dict[str, object], nav_items: list[dict[str, str]] | None = None) -> str:
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    facts = payload.get("facts") if isinstance(payload.get("facts"), list) else []
    notices = payload.get("notices") if isinstance(payload.get("notices"), list) else []
    yearly = payload.get("yearly") if isinstance(payload.get("yearly"), list) else []
    peers = payload.get("peers") if isinstance(payload.get("peers"), list) else []
    gp_links = payload.get("gp_links") if isinstance(payload.get("gp_links"), list) else []
    related_news = payload.get("news") if isinstance(payload.get("news"), list) else []
    official_notices = [notice for notice in notices if str(notice.get("source_type") or "official") == "official"]

    notice_rows = "\n".join(render_ktcu_notice_row(row) for row in official_notices) or (
        """        <p class="ktcu-empty-note">아직 공개 페이지에 표시할 공식 출자공고가 없습니다.</p>"""
    )
    max_yearly = max([float(row.get("allocation_amount_krw_100mn") or 0) for row in yearly] or [0])
    yearly_rows = "\n".join(render_ktcu_year_bar(row, max_yearly) for row in yearly) or (
        """        <p class="ktcu-empty-note">연도별 공고 규모는 공식 공고가 확인되면 표시됩니다.</p>"""
    )
    source_rows = render_ktcu_source_links(facts)
    source_tab = '<a href="#resources">자료</a>'
    source_details = (
        f"""    <details class="ktcu-detail" id="sourceLinks">
      <summary>자료 링크</summary>
      <ul>
{source_rows}
      </ul>
    </details>
"""
        if source_rows.strip()
        else ""
    )
    asset_mix_rows = render_ktcu_asset_mix(official_notices) or (
        """          <p class="ktcu-empty-note">자산군별 출자 패턴은 공식 공고가 추가되면 표시됩니다.</p>"""
    )
    general_rows = render_ktcu_fact_list(facts_in_section(facts, "general")) or (
        """          <div><dt>기관 개요</dt><dd>현재 공개자료에서 확인된 항목이 없습니다.</dd></div>"""
    )
    status_rows = render_ktcu_fact_list(facts_in_section(facts, "investment_status")) or (
        """          <div><dt>투자 현황</dt><dd>현재 공개자료에서 확인된 항목이 없습니다.</dd></div>"""
    )
    org_rows = render_ktcu_fact_list(facts_in_section(facts, "investment_org") + facts_in_section(facts, "public_people")) or (
        """          <div><dt>담당 조직</dt><dd>공식 조직도에서 확인된 조직 정보가 없습니다.</dd></div>"""
    )
    news_rows = render_ktcu_fact_list(facts_in_section(facts, "recent_news"))
    news_panel = (
        f"""      <section class="ktcu-panel">
        <h2>최근 동향</h2>
        <dl class="ktcu-facts">
{news_rows}
        </dl>
      </section>
"""
        if news_rows.strip()
        else ""
    )
    gap_rows = render_public_gap_rows(facts_in_section(facts, "data_gap")) or (
        """          <div><dt>선정 GP 히스토리</dt><dd>공식 발표가 확인된 건만 반영합니다.</dd></div>"""
    )

    lp_code = str(profile.get("lp_code") or "")
    lp_name = str(profile.get("lp_name") or "LP")
    lp_type = public_lp_type(profile.get("lp_type") or "LP")
    lp_logo_url = directory_logo_url(profile.get("homepage_url"))
    lp_avatar_label = directory_avatar_label(lp_short_label(lp_code, lp_name), "LP")
    lp_avatar_tone = directory_avatar_tone(lp_code or lp_name)
    lp_avatar_class = "ktcu-logo has-logo" if lp_logo_url else "ktcu-logo"
    lp_avatar_style = directory_logo_style(profile.get("homepage_url")) if lp_logo_url else ""
    lp_avatar_logo = (
        f'<img src="{lp_logo_url}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.classList.add(\'fallback-only\'); this.remove()">'
        if lp_logo_url
        else ""
    )
    default_team = str(profile.get("default_team") or "투자 담당")
    focus_label = display_asset_classes(profile.get("focus_asset_classes"))
    asset_label, asset = first_fact_pair(
        facts,
        ["2025년말 보유자산", "2025년말 총자산", "총자산", "보유 자산", "회원조합"],
    )
    asset = public_fact_value(asset) or "-"
    asset_kpi_label = "기관 규모" if asset_label == "회원조합" else "총자산"
    _, investment_status = first_fact_pair(
        facts,
        ["2025년 투자자산", "2026년 자산운용 목표", "2026년 자산운용 계획", "자금운용 역할"],
        focus_label,
    )
    investment_status = public_fact_value(investment_status) or focus_label
    investment_kpi = compact_alternative_amount(investment_status, focus_label)
    notice_count = str(len(official_notices))
    total_amount_value = sum(safe_float(notice.get("allocation_amount_krw_100mn")) for notice in official_notices)
    total_amount = public_amount_label(total_amount_value)
    latest = max([str(notice.get("event_date") or notice.get("announced_date") or "") for notice in official_notices] or [""])
    highlight_year = int((latest or report_date)[:4])
    highlight_count = len([notice for notice in official_notices if str(notice.get("event_date") or "").startswith(str(highlight_year))])
    highlight_amount = public_amount_label(ktcu_year_amount(official_notices, highlight_year))
    highlight_rows = render_ktcu_annual_highlights(official_notices, highlight_year) or (
        f"""          <p class="ktcu-empty-note">{highlight_year}년 표시할 공식 공고가 없습니다.</p>"""
    )
    timeline_rows = render_profile_timeline(facts, notices)
    peer_rows = render_lp_peer_rows(peers, lp_code)
    gp_signal_rows = render_related_gp_signals(notices, gp_links)
    related_news_rows = render_related_news_rows(related_news)
    asset_chips = render_asset_chips(profile.get("focus_asset_classes"))
    latest_label = latest or "-"

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{html_escape(lp_name)} LP 프로필</title>
{app_head_meta()}
  <link rel="stylesheet" href="assets/service.css?v={app_asset_version()}">
  <style>
    body {{ background: #ffffff; }}
    body,
    button,
    input,
    select {{
      font-variant-numeric: tabular-nums;
      font-feature-settings: "tnum" 1, "lnum" 1;
    }}
    .ktcu-shell {{ width: min(1200px, calc(100% - 28px)); margin: 0 auto; padding: 16px 0 calc(112px + env(safe-area-inset-bottom)); }}
    .ktcu-shell .kpef-product-header {{ margin: -16px calc((100vw - min(1200px, calc(100vw - 28px))) / -2) 0; padding-left: max(16px, calc((100vw - 1200px) / 2 + 16px)); padding-right: max(16px, calc((100vw - 1200px) / 2 + 16px)); }}
    .ktcu-shell .kpef-service-tabs {{ margin: 0 calc((100vw - min(1200px, calc(100vw - 28px))) / -2) 14px; padding-left: max(0px, calc((100vw - 1200px) / 2)); padding-right: max(0px, calc((100vw - 1200px) / 2)); }}
    .ktcu-top {{ display: grid; gap: 14px; padding: 8px 0 12px; }}
    .ktcu-profile-nav .ktcu-profile-link.active {{ border-color: var(--accent); background: var(--surface-muted); color: var(--text); }}
    .ktcu-profile-nav {{ display: flex; flex-wrap: wrap; gap: 7px; }}
    .ktcu-profile-nav a {{ min-height: 32px; display: inline-flex; align-items: center; border: 1px solid var(--separator); border-radius: 999px; padding: 6px 10px; background: #fff; color: var(--secondary); text-decoration: none; font-size: 12px; font-weight: 800; }}
    .ktcu-hero {{ display: grid; gap: 18px; padding: 8px 0 8px; }}
    .ktcu-title {{ display: grid; gap: 10px; }}
    .ktcu-title-head {{ display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 12px; align-items: center; }}
    .ktcu-logo {{ position: relative; display: inline-grid; width: 40px; height: 40px; box-sizing: border-box; place-items: center; overflow: hidden; border: 1px solid #dde3ea; border-radius: 50%; background: #f4f6f8; color: var(--text); font-size: 10px; font-weight: 900; box-shadow: none; }}
    .ktcu-logo.has-logo {{ border-color: var(--logo-border, #e2e5ea); background: var(--logo-bg, #fff); }}
    .ktcu-logo.has-logo.fallback-only {{ border-color: #dde3ea; background: #f4f6f8; }}
    .ktcu-logo > span {{ position: relative; z-index: 1; }}
    .ktcu-logo img {{ position: relative; z-index: 2; width: var(--logo-detail-img-width, var(--logo-img-width, 27px)); height: var(--logo-detail-img-height, var(--logo-img-height, 27px)); object-fit: contain; mix-blend-mode: normal; }}
    .ktcu-logo.has-logo > span {{ display: none; }}
    .ktcu-logo.fallback-only > span {{ display: inline; }}
    .ktcu-logo[data-tone] {{ color: var(--text); }}
    .ktcu-title-head div > span {{ width: fit-content; border-left: 3px solid var(--accent); padding-left: 8px; color: var(--text); font-size: 12px; font-weight: 800; }}
    .ktcu-title h1 {{ margin: 0; color: var(--text); font-size: 28px; font-weight: 850; line-height: 1.12; letter-spacing: 0; }}
    .ktcu-title p {{ max-width: 760px; margin: 0; color: var(--secondary); font-size: 15px; line-height: 1.68; }}
    .ktcu-hero-facts {{ display: grid; border-top: 1px solid var(--separator); border-bottom: 1px solid var(--separator); }}
    .ktcu-hero-fact {{ display: grid; grid-template-columns: 88px minmax(0, 1fr); gap: 10px; align-items: start; border-top: 1px solid var(--separator); padding: 9px 0; }}
    .ktcu-hero-fact:first-child {{ border-top: 0; }}
    .ktcu-hero-fact span {{ color: var(--secondary); font-size: 11.5px; font-weight: 850; line-height: 1.35; }}
    .ktcu-hero-fact strong {{ min-width: 0; color: var(--text); font-size: 13px; font-weight: 760; line-height: 1.42; overflow-wrap: anywhere; }}
    .ktcu-quick {{ display: grid; gap: 8px; }}
    .ktcu-quick-item {{ border-left: 3px solid var(--separator); padding-left: 10px; color: var(--text); font-size: 13px; line-height: 1.5; }}
    .ktcu-quick-item strong {{ display: block; margin-bottom: 2px; font-size: 13px; }}
    .ktcu-kpis {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 6px; }}
    .ktcu-kpis {{ border-top: 1px solid var(--separator); border-bottom: 1px solid var(--separator); }}
    .ktcu-kpi {{ min-width: 0; border: 0; border-radius: 0; padding: 13px 0; background: transparent; box-shadow: none; }}
    .ktcu-kpi span {{ display: block; color: var(--secondary); font-size: 11.5px; font-weight: 700; }}
    .ktcu-kpi strong {{ display: block; margin-top: 5px; color: var(--text); font-size: 22px; line-height: 1.15; overflow-wrap: anywhere; }}
    .ktcu-tabbar {{ display: flex; flex-wrap: wrap; gap: 18px; margin-top: 12px; border-bottom: 1px solid var(--separator); }}
    .ktcu-tabbar a {{ min-height: 34px; border: 0; border-bottom: 2px solid transparent; border-radius: 0; padding: 0 0 9px; background: transparent; color: var(--secondary); text-decoration: none; font-size: 13px; font-weight: 700; }}
    .ktcu-tabbar a:first-child {{ border-bottom-color: var(--text); color: var(--text); font-weight: 850; }}
    .ktcu-profile-toolbar {{ display: grid; gap: 8px; margin-top: 10px; }}
    .ktcu-profile-toolbar input {{ width: 100%; min-height: 40px; border: 1px solid var(--separator); border-radius: 8px; padding: 8px 11px; background: #fff; color: var(--text); font-size: 13px; }}
    .ktcu-profile-toolbar p {{ margin: 0; color: var(--secondary); font-size: 12px; line-height: 1.45; }}
    .ktcu-intel-grid {{ display: grid; gap: 10px; margin-top: 10px; }}
    .ktcu-coverage {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
    .ktcu-coverage div {{ min-width: 0; border: 1px solid var(--separator); border-radius: 8px; padding: 10px; background: #fbfcfd; }}
    .ktcu-coverage span {{ display: block; color: var(--secondary); font-size: 11.5px; font-weight: 800; }}
    .ktcu-coverage strong {{ display: block; margin-top: 4px; color: var(--text); font-size: 18px; line-height: 1.2; }}
    .ktcu-source-coverage {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .ktcu-chips {{ display: flex; flex-wrap: wrap; gap: 7px; }}
    .ktcu-chips span {{ border: 1px solid var(--separator); border-radius: 999px; padding: 6px 9px; background: #fbfcfd; color: var(--text); font-size: 12px; font-weight: 800; }}
    .ktcu-highlight-panel {{ margin-top: 10px; }}
    .ktcu-panel-head {{ display: flex; gap: 10px; align-items: start; justify-content: space-between; margin-bottom: 12px; }}
    .ktcu-panel-head h2 {{ margin-bottom: 4px; }}
    .ktcu-panel-head p {{ margin: 0; color: var(--secondary); font-size: 13px; line-height: 1.5; }}
    .ktcu-panel-head > strong {{ flex: 0 0 auto; color: var(--text); font-size: 18px; line-height: 1.25; text-align: right; }}
    .ktcu-highlight-list {{ display: grid; gap: 8px; }}
    .ktcu-highlight-row {{ display: grid; grid-template-columns: minmax(86px, 0.28fr) minmax(74px, auto) minmax(0, 1fr); gap: 9px; align-items: center; border-top: 1px solid var(--separator); padding-top: 9px; font-size: 13px; }}
    .ktcu-highlight-row:first-child {{ border-top: 0; padding-top: 0; }}
    .ktcu-highlight-row span {{ color: var(--secondary); font-weight: 800; }}
    .ktcu-highlight-row strong {{ color: var(--text); white-space: nowrap; }}
    .ktcu-highlight-row em {{ color: var(--text); font-style: normal; font-weight: 700; line-height: 1.4; }}
    .ktcu-empty-note {{ margin: 0; color: var(--secondary); font-size: 13px; }}
    .ktcu-section-grid {{ display: grid; gap: 10px; margin-top: 12px; }}
    .ktcu-panel {{ border: 0; border-top: 1px solid var(--separator); border-radius: 0; padding: 18px 0; background: transparent; box-shadow: none; }}
    .ktcu-panel h2 {{ margin: 0 0 11px; color: var(--text); font-size: 17px; line-height: 1.35; }}
    .ktcu-panel > p {{ margin: 0 0 12px; color: var(--secondary); font-size: 13px; line-height: 1.58; }}
    .ktcu-facts {{ display: grid; gap: 9px; margin: 0; }}
    .ktcu-facts div {{ min-width: 0; border-top: 1px solid var(--separator); padding-top: 9px; }}
    .ktcu-facts div:first-child {{ border-top: 0; padding-top: 0; }}
    .ktcu-facts dt {{ color: var(--secondary); font-size: 11.5px; font-weight: 800; }}
    .ktcu-facts dd {{ display: flex; min-width: 0; flex-wrap: wrap; gap: 6px; align-items: center; margin: 4px 0 0; color: var(--text); font-size: 13px; font-weight: 750; line-height: 1.48; overflow-wrap: anywhere; }}
    .ktcu-facts dd > span {{ min-width: 0; overflow-wrap: anywhere; }}
    .ktcu-source-icon {{ display: inline-flex; width: 17px; height: 17px; flex: 0 0 auto; align-items: center; justify-content: center; border: 1px solid var(--separator); border-radius: 50%; color: var(--secondary); text-decoration: none; transform: translateY(1px); }}
    .ktcu-source-icon svg {{ width: 11px; height: 11px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }}
    .ktcu-source-icon > span {{ font-size: 8.5px; font-weight: 900; line-height: 1; letter-spacing: 0; }}
    .ktcu-source-icon:hover {{ border-color: var(--text); color: var(--text); }}
    .ktcu-org {{ display: grid; gap: 8px; }}
    .ktcu-org-node {{ border: 1px solid var(--separator); border-radius: 8px; padding: 10px; background: #fbfcfd; }}
    .ktcu-org-node span {{ display: block; color: var(--secondary); font-size: 11.5px; font-weight: 800; }}
    .ktcu-org-node strong {{ display: block; margin-top: 4px; color: var(--text); font-size: 14px; line-height: 1.35; }}
    .ktcu-org-split {{ display: grid; gap: 8px; }}
    .ktcu-mix {{ display: grid; gap: 8px; }}
    .ktcu-mix-row {{ display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 8px; align-items: center; border-top: 1px solid var(--separator); padding-top: 8px; font-size: 13px; }}
    .ktcu-mix-row:first-child {{ border-top: 0; padding-top: 0; }}
    .ktcu-mix-row span {{ font-weight: 800; }}
    .ktcu-mix-row strong {{ color: var(--text); }}
    .ktcu-mix-row em {{ color: var(--secondary); font-style: normal; }}
    .ktcu-lower {{ display: grid; gap: 10px; margin-top: 10px; }}
    .ktcu-timeline {{ display: grid; gap: 9px; }}
    .ktcu-timeline-item {{ display: grid; gap: 5px; border-top: 1px solid var(--separator); padding-top: 10px; }}
    .ktcu-timeline-item:first-child {{ border-top: 0; padding-top: 0; }}
    .ktcu-timeline-item div {{ display: flex; flex-wrap: wrap; gap: 7px; align-items: center; }}
    .ktcu-timeline-item time {{ color: var(--secondary); font-size: 11.5px; font-weight: 800; }}
    .ktcu-timeline-item span {{ border-radius: 999px; padding: 3px 7px; background: var(--surface-muted); color: var(--text); font-size: 11px; font-weight: 800; }}
    .ktcu-timeline-item h3 {{ margin: 0; font-size: 14px; line-height: 1.4; }}
    .ktcu-timeline-item h3 a {{ color: var(--text); text-decoration: none; }}
    .ktcu-timeline-item p {{ margin: 0; color: var(--secondary); font-size: 12.5px; line-height: 1.45; }}
    .ktcu-news-list {{ display: grid; gap: 9px; }}
    .ktcu-news-row {{ border-top: 1px solid var(--separator); padding-top: 9px; }}
    .ktcu-news-row:first-child {{ border-top: 0; padding-top: 0; }}
    .ktcu-news-row span {{ color: var(--secondary); font-size: 11.5px; font-weight: 800; }}
    .ktcu-news-row h3 {{ margin: 4px 0 0; color: var(--text); font-size: 13.5px; line-height: 1.4; }}
    .ktcu-news-row a {{ color: inherit; text-decoration: none; }}
    .ktcu-notices {{ display: grid; gap: 8px; }}
    .ktcu-notice {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: start; border-top: 1px solid var(--separator); padding-top: 10px; }}
    .ktcu-notice:first-child {{ border-top: 0; padding-top: 0; }}
    .ktcu-notice time {{ color: var(--secondary); font-size: 11.5px; font-weight: 800; }}
    .ktcu-notice h3 {{ margin: 4px 0; font-size: 14px; line-height: 1.42; }}
    .ktcu-notice h3 a {{ color: var(--text); text-decoration: none; }}
    .ktcu-notice p {{ margin: 0; color: var(--secondary); font-size: 12px; line-height: 1.4; }}
    .ktcu-notice strong {{ white-space: nowrap; color: var(--text); font-size: 14px; }}
    .ktcu-years {{ display: grid; gap: 8px; }}
    .ktcu-year-row {{ display: grid; grid-template-columns: 44px minmax(0, 1fr) 68px; gap: 8px; align-items: center; font-size: 12px; }}
    .ktcu-year-row span {{ color: var(--secondary); font-weight: 800; }}
    .ktcu-year-row div {{ height: 9px; border-radius: 999px; background: #edf0f4; overflow: hidden; }}
    .ktcu-year-row i {{ display: block; height: 100%; border-radius: inherit; background: var(--accent); }}
    .ktcu-year-row strong {{ text-align: right; font-size: 12px; }}
    .ktcu-detail {{ margin-top: 10px; border: 1px solid var(--separator); border-radius: 8px; background: #fff; }}
    .ktcu-detail summary {{ cursor: pointer; padding: 12px 14px; color: var(--text); font-size: 13px; font-weight: 800; }}
    .ktcu-detail-body {{ padding: 0 14px 14px; }}
    .ktcu-detail-body p {{ margin: 0 0 10px; color: var(--secondary); font-size: 13px; line-height: 1.55; }}
    .ktcu-detail-body .ktcu-coverage {{ margin-top: 2px; }}
    .ktcu-detail ul {{ display: grid; gap: 8px; margin: 0; padding: 0 14px 14px 28px; }}
    .ktcu-detail a {{ color: var(--secondary); font-size: 12px; text-decoration: none; }}
    .ktcu-peer-table {{ display: grid; gap: 7px; }}
    .ktcu-peer-row {{ display: grid; grid-template-columns: minmax(128px, 1.25fr) minmax(82px, 0.8fr) 64px 86px; gap: 8px; align-items: center; border: 1px solid var(--separator); border-radius: 8px; padding: 9px; background: #fff; color: var(--text); text-decoration: none; font-size: 12px; }}
    .ktcu-peer-head {{ background: #f7fafb; color: var(--secondary); font-weight: 800; }}
    .ktcu-peer-row.active {{ border-color: var(--accent); background: var(--surface-muted); }}
    .ktcu-peer-row strong {{ min-width: 0; overflow-wrap: anywhere; font-size: 13px; }}
    .ktcu-peer-row span {{ min-width: 0; color: var(--secondary); overflow-wrap: anywhere; }}
    .ktcu-gp-tags {{ display: flex; flex-wrap: wrap; gap: 7px; }}
    .ktcu-gp-tags span {{ border: 1px solid var(--separator); border-radius: 999px; padding: 6px 9px; background: #fbfcfd; color: var(--text); font-size: 12px; font-weight: 800; }}
    .ktcu-footer {{ margin-top: 14px; color: var(--secondary); font-size: 11.5px; line-height: 1.45; }}
    @media (min-width: 760px) {{
      .ktcu-shell {{ padding-top: 22px; padding-bottom: calc(106px + env(safe-area-inset-bottom)); }}
      .ktcu-shell .kpef-product-header {{ margin-top: -22px; }}
      .ktcu-title h1 {{ font-size: 38px; }}
      .ktcu-hero {{ grid-template-columns: minmax(0, 1.12fr) minmax(340px, 0.88fr); align-items: start; }}
      .ktcu-intel-grid {{ grid-template-columns: minmax(0, 0.7fr) minmax(0, 1.3fr); }}
      .ktcu-section-grid {{ grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }}
      .ktcu-org-split {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .ktcu-lower {{ grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr); }}
      .ktcu-facts div {{
        display: grid;
        grid-template-columns: 132px minmax(0, 1fr);
        gap: 14px;
        align-items: start;
      }}
      .ktcu-facts dd {{ margin-top: 0; }}
    }}
    @media (max-width: 620px) {{
      .ktcu-profile-nav, .ktcu-tabbar {{ flex-wrap: nowrap; overflow-x: auto; padding-bottom: 3px; }}
      .ktcu-profile-nav a, .ktcu-tabbar a {{ flex: 0 0 auto; }}
      .ktcu-peer-row {{ grid-template-columns: minmax(0, 1fr) 52px 76px; }}
      .ktcu-peer-row span:nth-of-type(1) {{ display: none; }}
      .ktcu-peer-head {{ display: none; }}
      .ktcu-source-coverage {{ grid-template-columns: 1fr; }}
    }}
    .ktcu-title-head div > span {{
      border-left: 0;
      padding-left: 0;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 650;
    }}
    .ktcu-title h1 {{
      font-size: 23px;
      font-weight: 820;
      line-height: 1.18;
    }}
    .ktcu-title p {{
      font-size: 12.5px;
      font-weight: 650;
      line-height: 1.58;
    }}
    .ktcu-hero-fact strong {{
      font-size: 13px;
      font-weight: 760;
    }}
    .ktcu-quick-item {{
      font-size: 12.5px;
      line-height: 1.48;
    }}
    .ktcu-quick-item strong {{
      font-size: 12.5px;
      font-weight: 760;
    }}
    .ktcu-kpi span,
    .ktcu-coverage span,
    .ktcu-facts dt,
    .ktcu-timeline-item time,
    .ktcu-news-row span,
    .ktcu-notice time {{
      font-size: 11.5px;
      font-weight: 850;
    }}
    .ktcu-kpi strong {{
      font-size: 22px;
      font-weight: 780;
    }}
    .ktcu-tabbar a {{
      font-size: 13px;
      font-weight: 650;
    }}
    .ktcu-tabbar a:first-child {{
      font-weight: 800;
    }}
    .ktcu-profile-toolbar p,
    .ktcu-footer {{
      font-size: 11.5px;
      font-weight: 620;
      line-height: 1.45;
    }}
    .ktcu-panel h2 {{
      font-size: 17px;
      font-weight: 760;
      line-height: 1.35;
    }}
    .ktcu-panel > p,
    .ktcu-panel-head p {{
      font-size: 13px;
      font-weight: 500;
      line-height: 1.58;
    }}
    .ktcu-facts dd {{
      font-size: 13px;
      font-weight: 750;
      line-height: 1.48;
    }}
    .ktcu-highlight-row,
    .ktcu-mix-row {{
      font-size: 13px;
      line-height: 1.42;
    }}
    .ktcu-timeline-item h3,
    .ktcu-notice h3 {{
      font-size: 14px;
      font-weight: 760;
      line-height: 1.42;
    }}
    .ktcu-news-row h3 {{
      font-size: 14px;
      font-weight: 760;
      line-height: 1.42;
    }}
    @media (min-width: 760px) {{
      .ktcu-title h1 {{
        font-size: 28px;
      }}
    }}
  </style>
</head>
<body>
  <main class="ktcu-shell">
    {render_lp_service_header("lp", "lpProfileSearch", f"{lp_name} 페이지 검색")}
    <header class="ktcu-top">
      <section class="ktcu-hero" aria-label="{html_escape(lp_name)} 요약">
        <div class="ktcu-title">
          <div class="ktcu-title-head">
            <span class="{lp_avatar_class}" data-tone="{lp_avatar_tone}" aria-hidden="true"{lp_avatar_style}>{lp_avatar_logo}<span>{html_escape(lp_avatar_label)}</span></span>
            <div>
              <span>출자기관</span>
              <h1>{html_escape(lp_name)}</h1>
            </div>
          </div>
          <div class="ktcu-hero-facts" aria-label="핵심 정보">
            <div class="ktcu-hero-fact"><span>유형</span><strong>{html_escape(lp_type)}</strong></div>
            <div class="ktcu-hero-fact"><span>담당 조직</span><strong>{html_escape(default_team)}</strong></div>
            <div class="ktcu-hero-fact"><span>최신 공고</span><strong>{html_escape(latest_label)}</strong></div>
          </div>
          <nav class="ktcu-tabbar" aria-label="프로필 섹션">
            <a href="#overview">개요</a>
            <a href="#investment">배분</a>
            <a href="#notices">출자</a>
            <a href="#relationships">GP</a>
            <a href="#news">뉴스</a>
            <a href="#peers">비교</a>
            {source_tab}
          </nav>
        </div>
        <div class="ktcu-kpis">
          <div class="ktcu-kpi"><span>{html_escape(asset_kpi_label)}</span><strong>{html_escape(asset)}</strong></div>
          <div class="ktcu-kpi"><span>관심 자산군</span><strong>{html_escape(investment_kpi)}</strong></div>
          <div class="ktcu-kpi"><span>출자공고</span><strong>{html_escape(notice_count)}건</strong></div>
          <div class="ktcu-kpi"><span>공고 규모</span><strong>{html_escape(total_amount)}</strong></div>
        </div>
      </section>
    </header>

    <section class="ktcu-section-grid" id="overview" aria-label="기본 정보">
      <section class="ktcu-panel">
        <h2>기본 정보</h2>
        <dl class="ktcu-facts">
{general_rows}
        </dl>
      </section>

      <section class="ktcu-panel">
        <h2>담당 조직</h2>
        <dl class="ktcu-facts">
{org_rows}
        </dl>
      </section>
    </section>

    <section class="ktcu-section-grid" id="investment" aria-label="투자 현황">
      <section class="ktcu-panel">
        <h2>운용·배분</h2>
        <dl class="ktcu-facts">
{status_rows}
        </dl>
      </section>

      <section class="ktcu-panel">
        <h2>관심 자산군</h2>
        <div class="ktcu-chips">
{asset_chips}
        </div>
      </section>

      <section class="ktcu-panel">
        <h2>출자 패턴</h2>
        <div class="ktcu-mix">
{asset_mix_rows}
        </div>
      </section>

      <section class="ktcu-panel">
        <h2>연도별 공고 규모</h2>
        <div class="ktcu-years">
{yearly_rows}
        </div>
      </section>
    </section>

    <section class="ktcu-panel ktcu-highlight-panel" aria-label="{html_escape(str(highlight_year))}년 출자 하이라이트">
      <div class="ktcu-panel-head">
        <div>
          <h2>{html_escape(str(highlight_year))}년 출자공고</h2>
        </div>
        <strong>{html_escape(str(highlight_count))}건<br>{html_escape(highlight_amount)}</strong>
      </div>
      <div class="ktcu-highlight-list">
{highlight_rows}
      </div>
    </section>

    <section class="ktcu-lower" id="notices" aria-label="출자공고">
      <section class="ktcu-panel">
        <h2>타임라인</h2>
        <div class="ktcu-timeline">
{timeline_rows}
        </div>
      </section>
      <section class="ktcu-panel">
        <h2>과거 출자공고</h2>
        <div class="ktcu-notices">
{notice_rows}
        </div>
      </section>
    </section>

    <section class="ktcu-section-grid" id="relationships" aria-label="관련 GP">
      <section class="ktcu-panel">
        <h2>선정 GP</h2>
        <div class="ktcu-gp-tags">
{gp_signal_rows}
        </div>
      </section>
    </section>

    <section class="ktcu-section-grid" id="news" aria-label="관련 뉴스">
{news_panel}
      <section class="ktcu-panel">
        <h2>관련 뉴스</h2>
        <div class="ktcu-news-list">
{related_news_rows}
        </div>
      </section>
    </section>

    <section class="ktcu-panel ktcu-highlight-panel" id="peers" aria-label="LP 피어 비교">
      <div class="ktcu-panel-head">
        <div>
          <h2>기관 비교</h2>
        </div>
      </div>
      <div class="ktcu-peer-table">
{peer_rows}
      </div>
    </section>

    <section class="ktcu-section-grid ktcu-resources" id="resources" aria-label="자료">
{source_details}
      <details class="ktcu-detail" id="notes">
        <summary>참고사항</summary>
        <div class="ktcu-detail-body">
          <dl class="ktcu-facts">
{gap_rows}
          </dl>
        </div>
      </details>
    </section>

    <p class="ktcu-footer">기준일 {html_escape(report_date)} · 최신 공고일 {html_escape(latest_label)}</p>
  </main>
  {render_service_bottom_nav("lp")}
  <script>
    (() => {{
{lp_header_script()}
      const input = document.getElementById("lpProfileSearch");
      if (!input) return;
      const targets = Array.from(document.querySelectorAll(".ktcu-panel, .ktcu-timeline-item, .ktcu-notice, .ktcu-peer-row:not(.ktcu-peer-head), .ktcu-news-row, .ktcu-gp-tags span"));
      input.addEventListener("input", () => {{
        const query = input.value.trim().toLowerCase();
        targets.forEach((node) => {{
          const visible = !query || node.innerText.toLowerCase().includes(query);
          node.style.display = visible ? "" : "none";
        }});
      }});
    }})();
  </script>
</body>
</html>
"""


def write_lp_profile_pages(site_dir: Path, report_date: str) -> int:
    fact_count = 0
    profile_codes = read_lp_profile_codes()
    nav_items = read_lp_profile_nav(profile_codes=profile_codes)
    service_pages = {"lp-notices.html", "lp-official-notices.html"}
    for path in site_dir.glob("lp-*.html"):
        if path.name not in service_pages:
            path.unlink()
    for alias in [site_dir / alias for aliases in LP_PROFILE_ALIASES.values() for alias in aliases]:
        if alias.exists():
            alias.unlink()
    for lp_code in profile_codes:
        payload = read_ktcu_payload(lp_code=lp_code, profile_codes=profile_codes)
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        facts = payload.get("facts") if isinstance(payload.get("facts"), list) else []
        if not profile and not facts:
            continue
        html = render_ktcu_page(report_date, payload, nav_items)
        (site_dir / f"lp-{lp_code}.html").write_text(html, encoding="utf-8")
        for alias in LP_PROFILE_ALIASES.get(lp_code, ()):
            (site_dir / alias).write_text(html, encoding="utf-8")
        fact_count += len(facts)
    return fact_count


def render_lp_directory_card(item: dict[str, object]) -> str:
    lp_code = str(item.get("lp_code") or "")
    lp_name = str(item.get("lp_name") or lp_code or "LP")
    lp_type = public_lp_type(item.get("lp_type") or "LP")
    ownership = str(item.get("ownership_type") or "")
    ownership_label = {
        "public": "공공",
        "private": "민간",
        "mutual_aid": "공제",
    }.get(ownership.lower(), clean_public_lp_text(ownership))
    default_team = str(item.get("default_team") or "투자 담당")
    focus = display_asset_classes(item.get("focus_asset_classes"))
    notice_count = safe_int(item.get("visible_notice_count", item.get("notice_count")))
    latest = str(item.get("latest_event_date") or "-") or "-"
    amount = public_amount_label(item.get("allocation_amount_krw_100mn"), fallback="-")
    amount_sort = safe_float(item.get("allocation_amount_krw_100mn"))
    homepage_url = str(item.get("homepage_url") or "")
    profile_url = f"lp-{lp_code}.html" if lp_code else "lp-notices.html"
    avatar_label = directory_avatar_label(lp_short_label(lp_code, lp_name), "LP")
    avatar_markup = directory_avatar_markup(homepage_url, avatar_label, lp_code or lp_name)
    search_blob = " ".join([lp_name, lp_type, ownership_label, default_team, focus])
    title_markup = (
        f'<a href="{html_escape(profile_url)}">{html_escape(lp_name)}</a>'
        if item.get("has_public_profile", True)
        else html_escape(lp_name)
    )
    return f"""          <article class="lp-directory-card" aria-label="{html_escape(lp_name)}" data-search="{html_escape(search_blob)}" data-name="{html_escape(lp_name)}" data-lp="{html_escape(lp_code)}" data-asset="{html_escape(focus)}" data-kind="{html_escape(' '.join([lp_type, ownership_label]))}" data-notices="{notice_count}" data-amount="{amount_sort:.4f}" data-latest="{html_escape(latest)}">
            {avatar_markup}
            <div class="lp-directory-card-head">
              <strong>{title_markup}</strong>
            </div>
            <p class="lp-directory-focus">{html_escape(focus)}</p>
            <span class="lp-directory-latest">{html_escape(latest)}</span>
            <dl class="lp-directory-metrics">
              <div><dt>표시 공고</dt><dd>{notice_count}건</dd></div>
              <div><dt>공고 규모</dt><dd>{html_escape(amount)}</dd></div>
            </dl>
          </article>"""


def render_lp_notices_page(
    report_date: str,
    notices: list[dict[str, object]],
    nav_items: list[dict[str, str]] | None = None,
    directory_items: list[dict[str, object]] | None = None,
    active_tab: str = "lp",
) -> str:
    is_notice_view = active_tab == "notice"
    search_input_id = "lpOfficialNoticeSearch" if is_notice_view else "lpDirectorySearch"
    search_placeholder = "공고명, LP, GP 검색" if is_notice_view else "LP명, 자산군 검색"
    notice_groups = [
        ("open", "진행중 공고", [item for item in notices if lp_notice_status(item, report_date) == "open"]),
        ("result", "선정 결과", [item for item in notices if lp_notice_status(item, report_date) == "result"]),
        (
            "history",
            "공고 히스토리",
            [
                item
                for item in notices
                if lp_notice_status(item, report_date) in {"closed", "history"}
            ],
        ),
    ]
    notice_cards = "\n".join(
        f"""          <section class="lp-notice-group" data-group="{html_escape(group_key)}">
            <h2 class="section-title">{html_escape(group_title)}</h2>
            <div class="lp-page-list">
{''.join(render_lp_notice_card(item, report_date) for item in group_items) or '<div class="empty-state visible"><strong>표시할 공고가 없습니다</strong></div>'}
            </div>
          </section>"""
        for group_key, group_title, group_items in notice_groups
        if group_items
    )
    if not notice_cards:
        notice_cards = """          <div class="empty-state visible">
            <strong>표시할 공식 공고가 없습니다</strong>
            <span>공식 공고가 확인되면 여기에 표시됩니다.</span>
          </div>"""
    directory_rows = directory_items or []
    directory_cards = "\n".join(render_lp_directory_card(item) for item in directory_rows) or (
        """          <div class="empty-state visible">
            <strong>표시할 LP 프로필이 없습니다</strong>
            <span>공개자료가 확인되면 여기에 표시됩니다.</span>
          </div>"""
    )
    tracked_count = len(directory_rows)
    profile_count = len([item for item in directory_rows if item.get("has_public_profile")])
    visible_notice_count = len(notices)
    total_amount = sum(float(item.get("allocation_amount_krw_100mn") or 0) for item in directory_rows)
    if is_notice_view:
        hero_title = '<h1 class="lp-directory-title">출자공고</h1>'
        hero_meta = f'<p class="lp-directory-meta">공식 공고 {visible_notice_count}건 · 출자기관 {tracked_count}개 · {html_escape(report_date)} 기준</p>'
    else:
        hero_title = f'<h1 class="lp-directory-title"><strong>{tracked_count}개</strong> 출자기관</h1>'
        hero_meta = f'<p class="lp-directory-meta">기관 프로필 {profile_count}개 · 공식 공고 {visible_notice_count}건 · {html_escape(report_date)} 기준</p>'
    notice_asset_options = "".join(
        f'<option value="{html_escape(asset)}">{html_escape(asset)}</option>'
        for asset in sorted(
            {
                public_asset_class(item.get("assetClass"))
                for item in notices
                if str(item.get("assetClass") or "").strip()
            }
        )
    )
    notice_lp_options = "".join(
        f'<option value="{html_escape(code)}">{html_escape(name)}</option>'
        for code, name in sorted(
            {
                (str(item.get("lpCode") or ""), str(item.get("lpName") or "LP 미분류"))
                for item in notices
                if str(item.get("lpCode") or "").strip()
            },
            key=lambda pair: pair[1],
        )
    )
    directory_section = ""
    if not is_notice_view:
        directory_section = f"""
      <section class="section-block" id="lpDirectory" aria-label="출자기관 목록">
        <div class="lp-notice-toolbar">
          <div class="lp-control-head">
            <label for="{search_input_id}">출자기관 검색</label>
            <span id="lpVisibleCount">{tracked_count}개 표시</span>
          </div>
          <div class="lp-control-line lp-directory-controls">
            <select id="lpFilter" aria-label="필터">
              <option value="all">전체</option>
              <option value="공공">공공 LP</option>
              <option value="공제">공제회</option>
              <option value="PEF">PEF</option>
              <option value="VC">VC</option>
            </select>
            <select id="lpSort" aria-label="정렬">
              <option value="latest">최근 공고일순</option>
              <option value="amount">공고 규모순</option>
              <option value="notices">표시 공고 많은 순</option>
              <option value="name">기관명순</option>
            </select>
          </div>
        </div>
        <div class="lp-directory-table">
          <div class="lp-directory-head" aria-hidden="true">
            <span></span>
            <span>출자기관명</span>
            <span>주요 자산군</span>
            <span>최근 공고</span>
            <span>표시 공고</span>
            <span>공고 규모</span>
          </div>
          <div class="lp-directory-grid">
{directory_cards}
          </div>
        </div>
      </section>"""
    notice_section = ""
    if is_notice_view:
        notice_section = f"""
      <section class="section-block" id="lpNotices" aria-label="LP 공식 공고">
        <div class="lp-notice-toolbar">
          <div class="lp-control-head">
            <label for="{search_input_id}">공고 검색</label>
            <span id="lpNoticeVisibleCount">{visible_notice_count}건 표시</span>
          </div>
          <div class="lp-control-line lp-notice-controls">
            <select id="lpNoticeFilter" aria-label="필터">
              <option value="all">전체 상태</option>
              <option value="open">진행중</option>
              <option value="result">선정결과</option>
              <option value="history">히스토리</option>
              <option value="closed">마감</option>
            </select>
            <select id="lpNoticeAssetFilter" aria-label="자산군">
              <option value="all">전체 자산군</option>
              {notice_asset_options}
            </select>
            <select id="lpNoticeLpFilter" aria-label="출자기관">
              <option value="all">전체 기관</option>
              {notice_lp_options}
            </select>
            <select id="lpNoticeSort" aria-label="정렬">
              <option value="latest">최근 공고일순</option>
              <option value="deadline">마감일순</option>
              <option value="lp">기관명순</option>
            </select>
          </div>
        </div>
        <div class="lp-notice-table">
          <div class="lp-notice-head" aria-hidden="true">
            <span>공고명</span>
            <span>출자기관</span>
            <span>유형</span>
            <span>일정</span>
            <span>규모</span>
            <span>선정 GP</span>
            <span>자료</span>
          </div>
          <div class="lp-notice-groups">
{notice_cards}
          </div>
        </div>
      </section>"""
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Korea PEF Intelligence LP Notices</title>
{app_head_meta()}
  <link rel="stylesheet" href="assets/service.css?v={app_asset_version()}">
  <style>
    body.lp-notices-page {{ background: #f7f7f8; }}
    body.lp-notices-page .app-shell {{ width: min(100%, 1460px); background: #f7f7f8; }}
    body.lp-notices-page .content-area {{ display: block; width: min(1400px, 100%); margin: 0 auto; }}
    body.lp-notices-page .app-header {{ width: min(1400px, 100%); margin: 0 auto; }}
    .lp-profile-nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }}
    .lp-profile-nav a {{ display: inline-flex; min-height: 32px; align-items: center; border-radius: 999px; padding: 6px 10px; background: var(--surface-muted); color: var(--text); font-size: 12px; font-weight: 750; text-decoration: none; }}
    .lp-directory-hero {{ display: grid; gap: 18px; margin: 18px 0 16px; padding: 4px 0 2px; }}
    .lp-directory-meta {{ margin: 0 0 8px; color: var(--secondary); font-size: 13px; font-weight: 750; line-height: 1.45; }}
    .lp-directory-hero h1 {{ margin: 0; color: var(--text); font-size: 28px; font-weight: 850; line-height: 1.12; letter-spacing: 0; }}
    .lp-directory-hero p {{ max-width: 760px; margin: 0; color: var(--secondary); font-size: 14px; line-height: 1.62; }}
    .lp-directory-kpis {{ display: none; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
    .lp-directory-kpis div {{ border: 1px solid var(--separator); border-radius: 8px; padding: 11px; background: var(--surface); }}
    .lp-directory-kpis span {{ display: block; color: var(--secondary); font-size: 11.5px; font-weight: 800; }}
    .lp-directory-kpis strong {{ display: block; margin-top: 4px; color: var(--text); font-size: 20px; line-height: 1.2; }}
    .lp-directory-table,
    .lp-notice-table {{ overflow: hidden; border: 1px solid var(--separator); border-radius: 6px; background: var(--surface); }}
    .lp-directory-head {{
      display: grid;
      grid-template-columns: 40px minmax(0, 1fr) 76px 64px;
      gap: 8px;
      align-items: center;
      min-height: 44px;
      padding: 0 10px;
      border-bottom: 1px solid var(--separator);
      background: #f4f5f6;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 850;
      text-align: right;
    }}
    .lp-directory-head span:first-child {{ text-align: center; }}
    .lp-directory-head span:nth-child(2) {{ text-align: left; }}
    .lp-directory-head span:nth-child(3),
    .lp-directory-head span:nth-child(6) {{ display: none; }}
    .lp-directory-head span:nth-child(4) {{ font-size: 0; }}
    .lp-directory-head span:nth-child(4)::after {{ content: "최근"; font-size: 12px; }}
    .lp-directory-head span:nth-child(5) {{ font-size: 0; }}
    .lp-directory-head span:nth-child(5)::after {{ content: "공고"; font-size: 12px; }}
    .lp-notice-head {{ display: none; }}
    .lp-directory-grid {{ display: grid; gap: 0; margin-bottom: 16px; }}
    .lp-directory-card {{ display: grid; grid-template-columns: 40px minmax(0, 1fr) 76px 64px; gap: 8px; align-items: center; min-height: 68px; border-bottom: 1px solid var(--separator); padding: 9px 10px; background: var(--surface); }}
    .lp-directory-card:hover {{ background: #fbfcfd; }}
    .lp-directory-card:last-child {{ border-bottom: 0; }}
    .lp-directory-avatar {{ position: relative; display: inline-grid; width: 40px; height: 40px; box-sizing: border-box; place-items: center; overflow: hidden; border: 1px solid #dde3ea; border-radius: 50%; background: #f4f6f8; color: var(--text); font-size: 10px; font-weight: 900; letter-spacing: 0; box-shadow: none; }}
    .lp-directory-avatar.has-logo {{ border-color: var(--logo-border, #e2e5ea); background: var(--logo-bg, #fff); }}
    .lp-directory-avatar.has-logo.fallback-only {{ border-color: #dde3ea; background: #f4f6f8; }}
    .lp-directory-avatar > span {{ position: relative; z-index: 1; }}
    .lp-directory-avatar img {{ position: relative; z-index: 2; width: var(--logo-img-width, 27px); height: var(--logo-img-height, 27px); object-fit: contain; mix-blend-mode: normal; }}
    .lp-directory-avatar.has-logo > span {{ display: none; }}
    .lp-directory-avatar.fallback-only > span {{ display: inline; }}
    .lp-directory-avatar[data-tone] {{ color: var(--text); }}
    .lp-directory-card-head {{ display: grid; gap: 4px; }}
    .lp-directory-card-head strong {{ color: var(--text); font-size: 15px; line-height: 1.28; overflow-wrap: anywhere; }}
    .lp-directory-latest {{ color: var(--secondary); font-size: 13px; font-weight: 750; line-height: 1.45; }}
    .lp-directory-focus,
    .lp-directory-card > .lp-page-actions {{ display: none; }}
    .lp-directory-latest {{ text-align: right; }}
    .lp-directory-card p,
    .lp-directory-focus {{ margin: 0; color: var(--secondary); font-size: 13px; line-height: 1.5; }}
    .lp-directory-metrics {{ display: block; margin: 0; text-align: right; }}
    .lp-directory-metrics div:not(:first-child) {{ display: none; }}
    .lp-directory-metrics dt {{ display: none; }}
    .lp-directory-metrics dd {{ margin: 0; color: var(--text); font-size: 13px; font-weight: 800; overflow-wrap: anywhere; }}
    .lp-notice-toolbar {{ display: grid; gap: 9px; margin-bottom: 12px; }}
    .lp-control-head {{ display: flex; gap: 10px; align-items: center; justify-content: space-between; color: var(--secondary); font-size: 12px; font-weight: 850; }}
    .lp-control-line {{ display: grid; gap: 8px; }}
    .lp-notice-toolbar input {{ width: 100%; min-height: 42px; border: 1px solid var(--separator); border-radius: 8px; padding: 8px 11px; background: var(--surface); color: var(--text); font-size: 14px; }}
    .lp-notice-toolbar select {{ width: 100%; min-height: 42px; border: 1px solid var(--separator); border-radius: 8px; padding: 8px 11px; background: var(--surface); color: var(--text); font-size: 14px; }}
    .lp-page-list {{ display: grid; gap: 10px; }}
    .lp-page-card {{ display: grid; gap: 8px; padding: 14px; border: 1px solid var(--separator); border-radius: 8px; background: var(--surface); }}
    .lp-page-card h2 {{ margin: 0; font-size: 15px; line-height: 1.38; }}
    .lp-page-card h2 a {{ color: inherit; text-decoration: none; }}
    .lp-page-meta {{ display: flex; flex-wrap: wrap; gap: 6px; color: var(--secondary); font-size: 12px; line-height: 1.35; }}
    .lp-page-meta span + span::before {{ content: "·"; margin-right: 6px; color: var(--tertiary); }}
    .lp-page-actions {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .lp-page-actions a {{ display: inline-flex; min-height: 28px; align-items: center; border-radius: 4px; padding: 4px 6px; background: transparent; color: var(--secondary); font-size: 12px; font-weight: 650; text-decoration: none; }}
    .lp-page-actions a:hover {{ color: var(--text); text-decoration: underline; text-underline-offset: 3px; }}
    @media (min-width: 760px) {{
      body.lp-notices-page .app-shell {{ margin-top: 0; margin-bottom: 0; min-height: 100vh; border-radius: 0; box-shadow: none; }}
      .lp-directory-hero h1 {{ font-size: 38px; }}
      .lp-directory-hero {{ grid-template-columns: minmax(0, 1fr) minmax(320px, 0.7fr); align-items: end; }}
      .lp-directory-grid {{ grid-template-columns: minmax(0, 1fr); }}
      .lp-control-line {{ grid-template-columns: minmax(0, 1fr) 210px; }}
    }}
    @media (min-width: 960px) {{
      body.lp-notices-page .kpef-service-tabs {{
        display: none;
      }}
      body.lp-notices-page .bottom-nav {{
        display: grid;
      }}
      .lp-directory-table,
      .lp-notice-table {{ border: 1px solid var(--separator); background: var(--surface); box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }}
      .lp-directory-head {{
        display: grid;
        grid-template-columns: 44px minmax(170px, 1.2fr) minmax(140px, 0.9fr) minmax(92px, 0.45fr) minmax(88px, 0.4fr) minmax(108px, 0.5fr);
        gap: 12px;
        align-items: center;
        min-height: 48px;
        padding: 0 14px;
        border-bottom: 1px solid var(--separator);
        background: #f4f5f6;
        color: var(--secondary);
        font-size: 12px;
        font-weight: 850;
        text-align: left;
      }}
      .lp-directory-head span {{
        display: block;
      }}
      .lp-directory-head span:nth-child(2) {{
        text-align: left;
      }}
      .lp-directory-head span:nth-child(5) {{ font-size: 12px; }}
      .lp-directory-head span:nth-child(5)::after {{ content: none; }}
      .lp-directory-grid {{ grid-template-columns: minmax(0, 1fr); gap: 0; margin-bottom: 0; }}
      .lp-directory-card {{
        grid-template-columns: 44px minmax(170px, 1.2fr) minmax(140px, 0.9fr) minmax(92px, 0.45fr) minmax(88px, 0.4fr) minmax(108px, 0.5fr);
        gap: 12px;
        align-items: center;
        border: 0;
        border-bottom: 1px solid var(--separator);
        border-radius: 0;
        padding: 15px 14px;
        box-shadow: none;
      }}
      .lp-directory-card:last-child {{ border-bottom: 0; }}
      .lp-directory-card-head strong {{ font-size: 15px; }}
      .lp-directory-avatar {{ width: 40px; height: 40px; }}
      .lp-directory-focus {{ color: var(--text); }}
      .lp-directory-focus {{ display: block; }}
      .lp-directory-metrics {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
        text-align: left;
      }}
      .lp-directory-metrics div:not(:first-child) {{ display: block; }}
      .lp-directory-metrics div {{ border-top: 0; padding-top: 0; }}
      .lp-directory-metrics dt {{ display: block; }}
      .lp-directory-card > .lp-page-actions {{ display: flex; }}
      .lp-notice-head {{
        display: grid;
        grid-template-columns: minmax(360px, 1.4fr) minmax(320px, 1fr) minmax(160px, 0.42fr);
        gap: 18px;
        align-items: center;
        min-height: 48px;
        padding: 0 18px;
        border-bottom: 1px solid var(--separator);
        background: #f4f5f6;
        color: var(--secondary);
        font-size: 12px;
        font-weight: 850;
      }}
      .lp-page-list {{ grid-template-columns: minmax(0, 1fr); gap: 0; }}
      .lp-page-card {{
        grid-template-columns: minmax(360px, 1.4fr) minmax(320px, 1fr) minmax(160px, 0.42fr);
        gap: 18px;
        align-items: center;
        border: 0;
        border-bottom: 1px solid var(--separator);
        border-radius: 0;
        padding: 15px 18px;
      }}
      .lp-page-card:last-child {{ border-bottom: 0; }}
      .lp-page-card h2 {{ font-size: 14px; }}
    }}
    @media (max-width: 620px) {{
      .lp-directory-hero {{ margin: 10px 0 14px; }}
      .lp-directory-kpis {{ display: none; }}
      .lp-profile-nav {{ flex-wrap: nowrap; overflow-x: auto; padding-bottom: 3px; }}
      .lp-profile-nav a {{ flex: 0 0 auto; }}
      .lp-page-card h2 {{ overflow-wrap: anywhere; }}
      .lp-directory-metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    body.lp-notices-page {{ background: #ffffff; }}
    body.lp-notices-page,
    body.lp-notices-page button,
    body.lp-notices-page input,
    body.lp-notices-page select {{
      font-variant-numeric: tabular-nums;
      font-feature-settings: "tnum" 1, "lnum" 1;
    }}
    body.lp-notices-page .app-shell {{
      width: min(100%, 1120px);
      background: #ffffff;
      border-radius: 0;
      box-shadow: none;
    }}
    body.lp-notices-page .content-area,
    body.lp-notices-page .app-header {{
      width: min(100%, 1040px);
      max-width: 1040px;
      margin: 0 auto;
    }}
    .lp-app-header {{
      padding: 2px 0 10px;
      background: #ffffff;
    }}
    .lp-section-tabs {{
      margin-top: 0;
    }}
    .lp-directory-hero {{
      display: grid;
      gap: 8px;
      margin: 12px 0 16px;
      padding: 0;
    }}
    .lp-directory-meta {{
      order: 2;
      margin: 0;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 600;
    }}
    .lp-directory-title {{
      margin: 0;
      color: var(--text);
      font-size: 23px;
      font-weight: 800;
      line-height: 1.2;
    }}
    .lp-directory-title strong {{
      color: #8a6a56;
      font-weight: 850;
    }}
    .lp-directory-kpis,
    .lp-profile-nav {{
      display: none !important;
    }}
    .section-block {{
      position: relative;
      margin: 0 0 18px;
    }}
    .section-block + .section-block {{
      margin-top: 18px;
      padding-top: 20px;
    }}
    .section-block + .section-block::before {{
      position: absolute;
      top: 0;
      left: 50%;
      width: 100vw;
      height: 8px;
      transform: translateX(-50%);
      background: #f7f7f8;
      content: "";
    }}
    .lp-notice-toolbar {{
      gap: 8px;
      margin-bottom: 10px;
    }}
    .lp-control-head {{
      font-size: 12px;
      font-weight: 760;
    }}
    .lp-control-line {{
      grid-template-columns: minmax(0, 1fr);
    }}
    .lp-directory-controls,
    .lp-notice-controls {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .lp-notice-toolbar input {{
      display: none;
    }}
    .lp-notice-toolbar select {{
      min-height: 38px;
      border-radius: 7px;
      font-size: 13px;
    }}
    .lp-directory-table,
    .lp-notice-table {{
      border: 1px solid var(--separator);
      border-radius: 7px;
      box-shadow: none;
      background: #ffffff;
    }}
    .lp-directory-head {{
      grid-template-columns: 40px minmax(0, 1fr) 76px 64px;
      min-height: 42px;
      background: #f7f7f8;
      color: var(--secondary);
      text-align: right;
    }}
    .lp-directory-head span:nth-child(3),
    .lp-directory-head span:nth-child(6) {{
      display: none !important;
    }}
    .lp-directory-head span:nth-child(5) {{
      font-size: 0;
    }}
    .lp-directory-head span:nth-child(5)::after {{
      content: "공고";
      font-size: 12px;
    }}
    .lp-directory-card {{
      grid-template-columns: 40px minmax(0, 1fr) 76px 64px;
      min-height: 68px;
      padding: 9px 10px;
      box-shadow: none;
    }}
    .lp-directory-card-head strong,
    .lp-directory-card-head a {{
      color: var(--text);
      font-size: 15px;
      line-height: 1.3;
      text-decoration: none;
    }}
    .lp-directory-focus {{
      display: none;
    }}
    .lp-directory-card > .lp-page-actions {{
      display: none !important;
    }}
    .lp-directory-metrics {{
      text-align: right;
    }}
    .lp-directory-metrics div:nth-child(2),
    .lp-directory-metrics div:nth-child(3) {{
      display: none !important;
    }}
    .lp-directory-metrics dd,
    .lp-directory-latest {{
      font-size: 13px;
    }}
    .section-title {{
      margin: 0 0 10px;
      color: var(--text);
      font-size: 14.5px;
      font-weight: 800;
    }}
    .lp-page-list {{
      gap: 0;
    }}
    .lp-notice-groups {{
      display: grid;
      gap: 0;
    }}
    .lp-notice-group {{
      border-top: 8px solid #f7f7f8;
    }}
    .lp-notice-group:first-child {{
      border-top: 0;
    }}
    .lp-notice-group .section-title {{
      margin: 0;
      padding: 12px 10px 8px;
      border-bottom: 1px solid var(--separator);
    }}
    .lp-page-card {{
      border: 0;
      border-bottom: 1px solid var(--separator);
      border-radius: 0;
      padding: 13px 10px;
      box-shadow: none;
    }}
    .lp-page-card:last-child {{
      border-bottom: 0;
    }}
    .lp-page-card h2 {{
      font-size: 14.5px;
      font-weight: 650;
    }}
    .lp-page-actions a {{
      background: transparent;
      color: var(--secondary);
      font-weight: 620;
    }}
    @media (min-width: 760px) {{
      body.lp-notices-page .app-shell {{
        min-height: 100vh;
      }}
      .lp-directory-hero h1,
      .lp-directory-title {{
        font-size: 28px;
      }}
    }}
    @media (min-width: 960px) {{
      body.lp-notices-page .content-area,
      body.lp-notices-page .app-header {{
        width: min(1040px, calc(100% - 40px));
        max-width: 1040px;
      }}
      .lp-control-line {{
        grid-template-columns: 220px;
      }}
      .lp-directory-controls,
      .lp-notice-controls {{
        grid-template-columns: 180px 180px;
      }}
      .lp-directory-head {{
        grid-template-columns: 44px minmax(170px, 1.2fr) minmax(140px, 0.9fr) minmax(92px, 0.45fr) minmax(88px, 0.4fr) minmax(108px, 0.5fr);
        gap: 12px;
        text-align: left;
      }}
      .lp-directory-head span:nth-child(3),
      .lp-directory-head span:nth-child(4),
      .lp-directory-head span:nth-child(5),
      .lp-directory-head span:nth-child(6) {{
        display: block !important;
      }}
      .lp-directory-head span:nth-child(3) {{
        font-size: inherit;
      }}
      .lp-directory-head span:nth-child(3)::after {{
        content: none;
      }}
      .lp-directory-head span:nth-child(4) {{
        font-size: inherit;
      }}
      .lp-directory-head span:nth-child(4)::after {{
        content: none;
      }}
      .lp-directory-head span:nth-child(5) {{
        font-size: inherit;
      }}
      .lp-directory-head span:nth-child(5)::after {{
        content: none;
      }}
      .lp-directory-card {{
        grid-template-columns: 44px minmax(170px, 1.2fr) minmax(140px, 0.9fr) minmax(92px, 0.45fr) minmax(88px, 0.4fr) minmax(108px, 0.5fr);
        gap: 12px;
        padding: 15px 14px;
      }}
      .lp-directory-focus {{
        display: block;
        color: var(--secondary);
      }}
      .lp-directory-latest {{
        text-align: left;
      }}
      .lp-directory-metrics {{
        display: contents;
        text-align: left;
      }}
      .lp-directory-metrics div {{
        display: block !important;
      }}
      .lp-directory-metrics div:nth-child(2) {{
        display: block !important;
      }}
      .lp-directory-metrics div:nth-child(3) {{
        display: none !important;
      }}
      .lp-directory-metrics dt {{
        display: none;
      }}
      .lp-directory-metrics dd {{
        font-size: 13px;
      }}
      .lp-notice-group .section-title {{
        padding: 13px 18px 9px;
      }}
    }}
    .lp-directory-title {{
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 4px 6px;
      font-size: 16px !important;
      font-weight: 760;
      line-height: 1.35;
    }}
    .lp-directory-title strong {{
      font-size: 17px;
      font-weight: 820;
    }}
    .lp-directory-meta {{
      font-size: 12px;
      font-weight: 620;
      line-height: 1.42;
    }}
    .lp-control-head,
    .lp-controls label > span {{
      font-size: 11.5px;
      font-weight: 650;
    }}
    .lp-directory-head {{
      font-size: 12px;
      font-weight: 720;
    }}
    .lp-directory-card-head strong,
    .lp-directory-card-head a {{
      font-size: 14.5px;
      font-weight: 720;
      line-height: 1.36;
    }}
    .lp-directory-latest,
    .lp-directory-focus {{
      font-size: 12.5px;
      font-weight: 620;
      line-height: 1.4;
    }}
    .lp-directory-metrics dd {{
      font-size: 12.5px;
      font-weight: 740;
      line-height: 1.25;
    }}
    .section-title {{
      font-size: 15px;
      font-weight: 780;
      line-height: 1.35;
    }}
    .lp-page-card h2 {{
      font-size: 14px;
      font-weight: 760;
      line-height: 1.42;
    }}
    .lp-page-meta {{
      font-size: 11.5px;
      font-weight: 620;
      line-height: 1.4;
    }}
    .lp-page-actions a {{
      font-size: 12px;
      font-weight: 650;
    }}
    @media (min-width: 760px) {{
      .lp-directory-card-head strong,
      .lp-directory-card-head a {{
        font-size: 15px;
      }}
      .lp-directory-metrics dd {{
        font-size: 13px;
      }}
    }}
    body.lp-notices-page .lp-notice-controls {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    body.lp-notices-page .lp-notice-head {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 82px 66px;
      gap: 8px;
      align-items: center;
      min-height: 42px;
      padding: 0 10px;
      border-bottom: 1px solid var(--separator);
      background: #f7f7f8;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 720;
    }}
    body.lp-notices-page .lp-notice-head span:nth-child(2),
    body.lp-notices-page .lp-notice-head span:nth-child(3),
    body.lp-notices-page .lp-notice-head span:nth-child(6),
    body.lp-notices-page .lp-notice-head span:nth-child(7) {{
      display: none;
    }}
    body.lp-notices-page .lp-notice-head span:nth-child(4)::before {{
      content: "일정";
    }}
    body.lp-notices-page .lp-notice-head span:nth-child(4) {{
      font-size: 0;
      text-align: right;
    }}
    body.lp-notices-page .lp-notice-head span:nth-child(4)::before {{
      font-size: 12px;
    }}
    body.lp-notices-page .lp-notice-head span:nth-child(5) {{
      text-align: right;
    }}
    body.lp-notices-page .lp-notice-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 82px 66px;
      gap: 8px;
      align-items: center;
      min-height: 76px;
      padding: 11px 10px;
      border-bottom: 1px solid var(--separator);
      background: #ffffff;
    }}
    body.lp-notices-page .lp-notice-row:last-child {{
      border-bottom: 0;
    }}
    body.lp-notices-page .lp-notice-main {{
      min-width: 0;
      display: grid;
      gap: 4px;
    }}
    body.lp-notices-page .lp-notice-main > span {{
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 680;
      line-height: 1.2;
    }}
    body.lp-notices-page .lp-notice-main h2 {{
      margin: 0;
      color: var(--text);
      font-size: 14px;
      font-weight: 760;
      line-height: 1.4;
      overflow-wrap: anywhere;
    }}
    body.lp-notices-page .lp-notice-main h2 a {{
      color: inherit;
      text-decoration: none;
    }}
    body.lp-notices-page .lp-notice-main p {{
      display: flex;
      min-width: 0;
      flex-wrap: wrap;
      gap: 2px 8px;
      margin: 0;
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 620;
      line-height: 1.35;
    }}
    body.lp-notices-page .lp-notice-main p span + span::before {{
      content: "·";
      margin-right: 8px;
      color: var(--tertiary);
    }}
    body.lp-notices-page .lp-notice-lp,
    body.lp-notices-page .lp-notice-type,
    body.lp-notices-page .lp-notice-gp {{
      display: none;
    }}
    body.lp-notices-page .lp-notice-actions {{
      grid-column: 1 / -1;
      display: flex;
      gap: 10px;
      min-height: 0;
      align-items: center;
      padding-top: 2px;
    }}
    body.lp-notices-page .lp-notice-schedule {{
      display: grid;
      gap: 2px;
      justify-items: end;
      color: var(--secondary);
      font-style: normal;
      text-align: right;
    }}
    body.lp-notices-page .lp-notice-schedule span {{
      font-size: 10.5px;
      font-weight: 650;
    }}
    body.lp-notices-page .lp-notice-schedule strong,
    body.lp-notices-page .lp-notice-amount {{
      color: var(--text);
      font-size: 12.5px;
      font-weight: 760;
      line-height: 1.25;
      text-align: right;
    }}
    body.lp-notices-page .lp-notice-schedule em {{
      color: var(--tertiary);
      font-size: 10.5px;
      font-style: normal;
      font-weight: 600;
      line-height: 1.2;
    }}
    @media (min-width: 760px) {{
      body.lp-notices-page .lp-notice-controls {{
        grid-template-columns: 150px 160px minmax(180px, 1fr) 160px;
      }}
      body.lp-notices-page .lp-notice-head {{
        grid-template-columns: minmax(280px, 1.45fr) minmax(120px, 0.55fr) minmax(125px, 0.55fr) minmax(105px, 0.46fr) minmax(82px, 0.34fr) minmax(150px, 0.7fr) minmax(96px, 0.34fr);
        gap: 14px;
        padding: 0 16px;
      }}
      body.lp-notices-page .lp-notice-head span,
      body.lp-notices-page .lp-notice-head span:nth-child(2),
      body.lp-notices-page .lp-notice-head span:nth-child(3),
      body.lp-notices-page .lp-notice-head span:nth-child(6),
      body.lp-notices-page .lp-notice-head span:nth-child(7) {{
        display: block;
      }}
      body.lp-notices-page .lp-notice-head span:nth-child(4) {{
        font-size: 12px;
        text-align: left;
      }}
      body.lp-notices-page .lp-notice-head span:nth-child(4)::before {{
        content: none;
      }}
      body.lp-notices-page .lp-notice-row {{
        grid-template-columns: minmax(280px, 1.45fr) minmax(120px, 0.55fr) minmax(125px, 0.55fr) minmax(105px, 0.46fr) minmax(82px, 0.34fr) minmax(150px, 0.7fr) minmax(96px, 0.34fr);
        gap: 14px;
        min-height: 70px;
        padding: 13px 16px;
      }}
      body.lp-notices-page .lp-notice-main p {{
        display: none;
      }}
      body.lp-notices-page .lp-notice-lp,
      body.lp-notices-page .lp-notice-type,
      body.lp-notices-page .lp-notice-gp {{
        display: block;
        min-width: 0;
        color: var(--text);
        font-size: 12.5px;
        font-weight: 650;
        line-height: 1.35;
        overflow-wrap: anywhere;
      }}
      body.lp-notices-page .lp-notice-type,
      body.lp-notices-page .lp-notice-gp {{
        color: var(--secondary);
      }}
      body.lp-notices-page .lp-notice-schedule {{
        justify-items: start;
        text-align: left;
      }}
      body.lp-notices-page .lp-notice-amount {{
        text-align: left;
      }}
      body.lp-notices-page .lp-notice-actions {{
        grid-column: auto;
        display: flex;
        justify-content: flex-start;
      }}
    }}
  </style>
</head>
<body class="lp-notices-page">
  <div class="app-shell newsletter-only">
    {render_lp_service_header(active_tab, search_input_id, search_placeholder)}
    <main class="content-area">
      <section class="lp-directory-hero" aria-label="LP 디렉토리 요약">
        <div>
          {hero_title}
          {hero_meta}
        </div>
        <div class="lp-directory-kpis">
          <div><span>대상 기관</span><strong>{tracked_count}개</strong></div>
          <div><span>기관 프로필</span><strong>{profile_count}개</strong></div>
          <div><span>공고 기준 규모</span><strong>{html_escape(public_amount_label(total_amount, fallback="-"))}</strong></div>
          <div><span>표시 공고</span><strong>{visible_notice_count}건</strong></div>
        </div>
      </section>
{directory_section}
{notice_section}
    </main>

    {render_service_bottom_nav("lp")}
  </div>
  <script>
    (() => {{
{lp_header_script()}
      const input = document.getElementById("{search_input_id}");
      const sort = document.getElementById("lpSort");
      const filter = document.getElementById("lpFilter");
      const noticeSort = document.getElementById("lpNoticeSort");
      const noticeFilter = document.getElementById("lpNoticeFilter");
      const noticeAssetFilter = document.getElementById("lpNoticeAssetFilter");
      const noticeLpFilter = document.getElementById("lpNoticeLpFilter");
      const directory = document.querySelector(".lp-directory-grid");
      const noticeGroups = Array.from(document.querySelectorAll(".lp-notice-group"));
      const visible = document.getElementById("lpVisibleCount");
      const noticeVisible = document.getElementById("lpNoticeVisibleCount");
      const directoryCards = Array.from(document.querySelectorAll(".lp-directory-card"));
      const noticeCards = Array.from(document.querySelectorAll(".lp-notice-row"));
      const num = (card, key) => {{
        const value = Number(card.dataset[key]);
        return Number.isFinite(value) ? value : 0;
      }};
      const fieldsMatch = (card, active) => {{
        const fields = [card.dataset.asset, card.dataset.event, card.dataset.lp, card.dataset.kind, card.dataset.status, card.dataset.statusGroup].filter(Boolean);
        return active === "all" || fields.includes(active) || fields.some((field) => field.includes(active));
      }};
      const queryMatch = (card) => {{
        const query = (input?.value || "").trim().toLowerCase();
        const haystack = (card.dataset.search || card.innerText).toLowerCase();
        return !query || haystack.includes(query);
      }};
      const applyDirectorySort = () => {{
        const mode = sort?.value || "latest";
        const sorted = [...directoryCards].sort((a, b) => {{
          if (mode === "amount") return num(b, "amount") - num(a, "amount");
          if (mode === "notices") return num(b, "notices") - num(a, "notices");
          if (mode === "name") return (a.dataset.name || "").localeCompare(b.dataset.name || "", "ko");
          return (b.dataset.latest || "").localeCompare(a.dataset.latest || "");
        }});
        sorted.forEach((card) => directory?.appendChild(card));
      }};
      const applyDirectory = () => {{
        const active = filter?.value || "all";
        let count = 0;
        directoryCards.forEach((card) => {{
          const visibleCard = fieldsMatch(card, active) && queryMatch(card);
          card.style.display = visibleCard ? "" : "none";
          if (visibleCard) count += 1;
        }});
        if (visible) visible.textContent = `${{count.toLocaleString("ko-KR")}}개 표시`;
      }};
      const applyNoticeSort = () => {{
        const mode = noticeSort?.value || "latest";
        const sorted = [...noticeCards].sort((a, b) => {{
          if (mode === "deadline") return (a.dataset.deadline || "9999-99-99").localeCompare(b.dataset.deadline || "9999-99-99");
          if (mode === "lp") return (a.dataset.lpName || "").localeCompare(b.dataset.lpName || "", "ko");
          return (b.dataset.date || "").localeCompare(a.dataset.date || "");
        }});
        noticeGroups.forEach((group) => {{
          const list = group.querySelector(".lp-page-list");
          sorted
            .filter((card) => card.dataset.statusGroup === group.dataset.group)
            .forEach((card) => list?.appendChild(card));
        }});
      }};
      const applyNotices = () => {{
        const active = noticeFilter?.value || "all";
        const activeAsset = noticeAssetFilter?.value || "all";
        const activeLp = noticeLpFilter?.value || "all";
        let count = 0;
        noticeCards.forEach((card) => {{
          const visibleCard = fieldsMatch(card, active) && fieldsMatch(card, activeAsset) && fieldsMatch(card, activeLp) && queryMatch(card);
          card.style.display = visibleCard ? "" : "none";
          if (visibleCard) count += 1;
        }});
        noticeGroups.forEach((group) => {{
          const hasVisible = Array.from(group.querySelectorAll(".lp-notice-row")).some((card) => card.style.display !== "none");
          group.style.display = hasVisible ? "" : "none";
        }});
        if (noticeVisible) noticeVisible.textContent = `${{count.toLocaleString("ko-KR")}}건 표시`;
      }};
      input?.addEventListener("input", () => {{
        applyDirectory();
        applyNotices();
      }});
      sort?.addEventListener("change", () => {{
        applyDirectorySort();
        applyDirectory();
      }});
      filter?.addEventListener("change", applyDirectory);
      noticeSort?.addEventListener("change", () => {{
        applyNoticeSort();
        applyNotices();
      }});
      noticeFilter?.addEventListener("change", applyNotices);
      noticeAssetFilter?.addEventListener("change", applyNotices);
      noticeLpFilter?.addEventListener("change", applyNotices);
      applyDirectorySort();
      applyNoticeSort();
      applyDirectory();
      applyNotices();
    }})();
  </script>
</body>
</html>
"""


def render_lp_notice_card(item: dict[str, object], report_date: str) -> str:
    title = str(item.get("displayTitle") or item.get("title") or "공식 공고")
    url = str(item.get("url") or "")
    document_url = str(item.get("documentUrl") or "")
    lp_code = str(item.get("lpCode") or "")
    lp_name = str(item.get("lpName") or "LP 미분류")
    event_type = str(item.get("eventType") or "")
    event_date = str(item.get("eventDate") or item.get("announcedDate") or "")
    deadline = str(item.get("applicationDeadline") or "")
    status = lp_notice_status(item, report_date)
    status_group = "history" if status in {"closed", "history"} else status
    status_label = lp_notice_status_label(status)
    amount = lp_amount_label(item.get("allocationAmount"))
    amount_label = amount or "-"
    asset_class = public_asset_class(item.get("assetClass")) if item.get("assetClass") else ""
    strategy = clean_public_lp_text(item.get("strategy") or item.get("purpose") or "")
    type_label = " · ".join(value for value in [asset_class, strategy] if value) or "-"
    selected_label = notice_gp_label(item.get("selectedGpNames"))
    if status == "result":
        schedule_label = "선정일"
        schedule_value = event_date or "-"
        schedule_sub = ""
    elif deadline:
        schedule_label = "마감"
        schedule_value = deadline
        schedule_sub = f"공고 {event_date}" if event_date else ""
    else:
        schedule_label = "공고일"
        schedule_value = event_date or "-"
        schedule_sub = ""
    official_link = (
        f'<a href="{html_escape(url)}" target="_blank" rel="noreferrer">원문</a>'
        if url
        else ""
    )
    document_link = (
        f'<a href="{html_escape(document_url)}" target="_blank" rel="noreferrer">첨부</a>'
        if document_url and document_url != url
        else ""
    )
    linked_title = (
        f'<a href="{html_escape(url)}" target="_blank" rel="noreferrer">{html_escape(title)}</a>'
        if url
        else html_escape(title)
    )
    search_blob = " ".join(
        str(value or "")
        for value in [
            title,
            lp_name,
            asset_class,
            event_type,
            status_label,
            deadline,
            strategy,
            item.get("selectedGpNames"),
        ]
    )
    return f"""              <article class="lp-notice-row" data-search="{html_escape(search_blob)}" data-lp="{html_escape(lp_code)}" data-lp-name="{html_escape(lp_name)}" data-asset="{html_escape(asset_class)}" data-event="{html_escape(event_type)}" data-status="{html_escape(status)}" data-status-group="{html_escape(status_group)}" data-date="{html_escape(event_date)}" data-deadline="{html_escape(deadline)}">
            <div class="lp-notice-main">
              <span>{html_escape(status_label)}</span>
              <h2>{linked_title}</h2>
              <p><span>{html_escape(lp_name)}</span><span>{html_escape(type_label)}</span></p>
            </div>
            <strong class="lp-notice-lp">{html_escape(lp_name)}</strong>
            <span class="lp-notice-type">{html_escape(type_label)}</span>
            <time class="lp-notice-schedule" datetime="{html_escape(schedule_value if schedule_value != '-' else '')}">
              <span>{html_escape(schedule_label)}</span>
              <strong>{html_escape(schedule_value)}</strong>
              {f'<em>{html_escape(schedule_sub)}</em>' if schedule_sub else ''}
            </time>
            <strong class="lp-notice-amount">{html_escape(amount_label)}</strong>
            <span class="lp-notice-gp">{html_escape(selected_label)}</span>
            <div class="lp-page-actions lp-notice-actions">{official_link}{document_link}</div>
          </article>"""


def write_lp_notices_page(site_dir: Path, report_date: str) -> int:
    notices = read_lp_monitor(DEFAULT_LP_COMMITMENT_MONITOR, limit=None)
    nav_items = read_lp_profile_nav()
    directory_items = read_lp_directory_items()
    (site_dir / "lp-notices.html").write_text(
        render_lp_notices_page(report_date, notices, nav_items, directory_items, active_tab="lp"),
        encoding="utf-8",
    )
    (site_dir / "lp-official-notices.html").write_text(
        render_lp_notices_page(report_date, notices, nav_items, directory_items, active_tab="notice"),
        encoding="utf-8",
    )
    return len(notices)


def read_embedded_archive(html_path: Path) -> list[dict[str, object]]:
    if not html_path.exists():
        return []
    match = ARCHIVE_SCRIPT_RE.search(html_path.read_text(encoding="utf-8"))
    if not match:
        return []
    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def read_archive_seed(seed_url: str) -> list[dict[str, object]]:
    if not seed_url:
        return []
    try:
        with urlopen(seed_url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def merge_archives(
    local_entries: list[dict[str, object]],
    seed_entries: list[dict[str, object]],
    archive_limit: int,
) -> list[dict[str, object]]:
    by_date: dict[str, dict[str, object]] = {}
    for entry in seed_entries + local_entries:
        report_date = str(entry.get("reportDate") or "").strip()
        articles = entry.get("articles")
        if not report_date or not isinstance(articles, list):
            continue
        existing = by_date.get(report_date)
        existing_articles = existing.get("articles") if existing else []
        if existing and isinstance(existing_articles, list) and existing_articles and not articles:
            continue
        by_date[report_date] = entry
    merged = [by_date[date] for date in sorted(by_date, reverse=True)]
    if archive_limit > 0:
        merged = merged[:archive_limit]
    return merged


def archive_article_count(archive_entries: list[dict[str, object]], report_date: str, fallback: int) -> int:
    for entry in archive_entries:
        if str(entry.get("reportDate") or "") != report_date:
            continue
        articles = entry.get("articles")
        if isinstance(articles, list):
            return len(articles)
    return fallback


def rewrite_site_archive(site_dir: Path, report_date: str, archive_entries: list[dict[str, object]]) -> None:
    markdown_path = brief_markdown_path(DEFAULT_EXPORT_DIR, report_date)
    articles = parse_brief(markdown_path)
    basis_text = parse_brief_basis(markdown_path)
    service_context = read_service_context(DEFAULT_SERVICE_INTEGRATION_WORKLIST)
    service_context = merge_service_context(service_context, read_lp_article_context())
    add_title_matched_lp_article_context(service_context, archive_entries)
    filter_service_context_profile_links(service_context)
    archive_entries = refresh_archive_entries_with_context(archive_entries, service_context)
    lp_monitor = read_lp_monitor(DEFAULT_LP_COMMITMENT_MONITOR)
    html = render_app(
        report_date,
        articles,
        basis_text,
        service_context,
        archive_entries,
        lp_monitor,
        newsletter_only=True,
    )
    (site_dir / "index.html").write_text(html, encoding="utf-8")
    (site_dir / "daily-news.html").write_text(html, encoding="utf-8")
    (site_dir / "archive.json").write_text(
        json.dumps(archive_entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def zip_site(deploy_dir: Path, site_dir: Path) -> Path:
    zip_path = deploy_dir / "kpef-newsletter-site.zip"
    if zip_path.exists():
        zip_path.unlink()
    lp_service_pages = {"lp-notices.html", "lp-official-notices.html"}
    profile_paths = sorted(
        path
        for path in site_dir.glob("lp-*.html")
        if path.name not in lp_service_pages
    )
    gp_profile_paths = sorted(site_dir.glob("gp-*.html"))
    alias_paths = [site_dir / alias for aliases in LP_PROFILE_ALIASES.values() for alias in aliases]
    include_paths = [
        site_dir / "index.html",
        site_dir / "daily-news.html",
        site_dir / "lp-notices.html",
        site_dir / "lp-official-notices.html",
        site_dir / "market.html",
        site_dir / "gps.html",
        site_dir / "pef-wiki.html",
        *alias_paths,
        *profile_paths,
        *gp_profile_paths,
        site_dir / "health.json",
        site_dir / "archive.json",
        site_dir / "site.webmanifest",
        site_dir / "apple-touch-icon.png",
        site_dir / ".nojekyll",
        site_dir / "robots.txt",
        site_dir / "404.html",
        site_dir / "assets" / "service.css",
        site_dir / "assets" / "service.js",
        *sorted((site_dir / "assets" / "brand-marks").glob("*")),
    ]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in include_paths:
            if path.is_file():
                archive.write(path, path.relative_to(site_dir))
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build newsletter-only deployment artifacts")
    parser.add_argument("--date", default=today_seoul())
    parser.add_argument("--deploy-dir", type=Path, default=DEFAULT_DEPLOY_DIR)
    parser.add_argument("--archive-limit", type=int, default=DEFAULT_ARCHIVE_LIMIT)
    parser.add_argument("--archive-seed-url", default=DEFAULT_ARCHIVE_SEED_URL)
    parser.add_argument("--no-archive-seed", action="store_true")
    args = parser.parse_args()

    deploy_dir = args.deploy_dir
    site_dir = deploy_dir / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    deploy_dir.mkdir(parents=True, exist_ok=True)

    result = build(
        public_dir=site_dir,
        out_dir=DEFAULT_EXPORT_DIR,
        report_date=args.date,
        archive_limit=args.archive_limit,
        newsletter_only=True,
    )
    local_archive = read_embedded_archive(site_dir / "index.html")
    seed_archive = [] if args.no_archive_seed else read_archive_seed(args.archive_seed_url)
    archive_entries = merge_archives(local_archive, seed_archive, args.archive_limit)
    if archive_entries:
        rewrite_site_archive(site_dir, args.date, archive_entries)
        result["article_count"] = str(
            archive_article_count(
                archive_entries,
                args.date,
                int(result.get("article_count", "0") or 0),
            )
        )
    result["lp_monitor_count"] = str(write_lp_notices_page(site_dir, args.date))
    result["lp_profile_fact_count"] = str(write_lp_profile_pages(site_dir, args.date))
    lp_service_pages = {"lp-notices.html", "lp-official-notices.html"}
    result["lp_profile_page_count"] = str(len([path for path in site_dir.glob("lp-*.html") if path.name not in lp_service_pages]))
    result["ktcu_fact_count"] = str(len(read_ktcu_payload(lp_code=KTCU_CODE, profile_codes=read_lp_profile_codes()).get("facts") or []))
    result.update({key: str(value) for key, value in write_gp_pages(site_dir, DEFAULT_DB, args.date).items()})
    write_pef_wiki_page(site_dir, args.date)
    write_public_db_page(site_dir)
    (site_dir / "admin.html").unlink(missing_ok=True)
    write_health_file(site_dir, result)
    write_static_support_files(site_dir)
    assert_newsletter_only(site_dir)
    zip_path = zip_site(deploy_dir, site_dir)

    manifest = {
        **result,
        "deploy_dir": str(deploy_dir),
        "site_dir": str(site_dir),
        "zip_path": str(zip_path),
    }
    (deploy_dir / "deploy-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for key, value in manifest.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
