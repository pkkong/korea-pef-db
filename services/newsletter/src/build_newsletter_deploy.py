#!/usr/bin/env python
"""Build a deployable static bundle for the newsletter-only service."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote_plus, urlparse
from urllib.request import urlopen


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
SRC_DIR = Path(__file__).resolve().parent
DEFAULT_DEPLOY_DIR = SERVICE_ROOT / "deploy"
DEFAULT_SITE_DIR = DEFAULT_DEPLOY_DIR / "site"
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_LP_SELECTED_GP_EXCLUSIONS = REPO_ROOT / "data" / "lp_selected_gp_non_gp_exclusions.csv"
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
    "notice_history": "출자공고 이력",
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
    read_review_queue_context,
    read_service_context,
    render_app,
    render_public_product_header,
)
from daily_news_common import normalize_whitespace, today_seoul  # noqa: E402
from gp_service_pages import write_gp_pages  # noqa: E402
from pef_wiki_pages import render_pef_wiki_page  # noqa: E402
from lp_notice_view import (  # noqa: E402
    consolidate_lp_notice_display_items,
    is_generic_lp_program_name,
    korean_date_label,
    lp_amount_label,
    lp_event_label,
    lp_notice_amount_label,
    lp_notice_business_round_name,
    lp_notice_canonical_title,
    lp_notice_date,
    lp_notice_display_group_key,
    lp_notice_effective_deadline_value,
    lp_notice_platform_label,
    lp_notice_program_label,
    lp_notice_public_strategy_label,
    lp_notice_public_status,
    lp_notice_source_label,
    lp_notice_source_note,
    lp_notice_specific_program_name,
    lp_notice_stage_label,
    lp_notice_status,
    lp_notice_status_label,
    split_notice_names,
)


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
            haystack = row.get("title", "")
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


def load_selected_gp_exclusion_names(path: Path = DEFAULT_LP_SELECTED_GP_EXCLUSIONS) -> set[str]:
    if not path.exists():
        return set()
    names: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            token = normalize_whitespace(row.get("token", ""))
            if token:
                names.add(token)
    return names


SELECTED_GP_EXCLUSION_NAMES = load_selected_gp_exclusion_names()


def notice_gp_label(value: object, limit: int = 2) -> str:
    names = [name for name in split_notice_names(value) if name not in SELECTED_GP_EXCLUSION_NAMES]
    if not names:
        return "-"
    if len(names) <= limit:
        return " · ".join(names)
    return f"{' · '.join(names[:limit])} 외 {len(names) - limit}"


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
        <a class="brief-section-tab{lp_active}" href="lp-notices.html"{lp_current}>출자기관</a>
        <a class="brief-section-tab{notice_active}" href="lp-official-notices.html"{notice_current}>출자공고</a>
        <a class="brief-section-tab lp-result-tab" href="lp-official-notices.html?status=result">선정결과</a>
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
        searchArea.classList.toggle("active", open);
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
                WHERE COALESCE(display_enabled, 1) = 1
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
                coverage_tier,
                display_enabled,
                notice_tracking_enabled,
                profile_status,
                notice_count,
                allocation_amount_krw_100mn,
                latest_event_date,
                fact_count,
                source_count
            FROM v_lp_profile_summary
            WHERE COALESCE(display_enabled, 1) = 1
            ORDER BY service_priority DESC, lp_name
            """,
        )
        notice_stats = read_lp_notice_stats(conn)
        return [merge_lp_notice_stats(row, notice_stats) for row in rows]
    finally:
        conn.close()


def read_lp_lifecycle_compare(db_path: Path = DEFAULT_DB) -> list[dict[str, object]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        if not db_object_exists(conn, "v_lp_commitment_lifecycle_compare"):
            return []
        return fetch_dicts(
            conn,
            """
            SELECT
                lp_code,
                lp_name,
                lp_type,
                program_name,
                round_name,
                asset_class,
                strategy,
                notice_count,
                open_count,
                shortlist_count,
                final_selection_count,
                selected_gp_count,
                allocation_amount_krw_100mn_sum,
                commitment_amount_krw_100mn_sum,
                amount_krw_100mn_sum,
                program_size_krw_100mn_max,
                latest_notice_title,
                latest_notice_url,
                latest_notice_date,
                latest_event_type,
                latest_stage,
                next_application_deadline,
                latest_application_deadline,
                deadline_status
            FROM v_lp_commitment_lifecycle_compare
            WHERE COALESCE(lp_code, '') <> ''
            ORDER BY
                CASE deadline_status
                    WHEN 'open' THEN 0
                    WHEN 'final_selection' THEN 1
                    WHEN 'shortlist' THEN 2
                    WHEN 'closed' THEN 3
                    ELSE 4
                END,
                COALESCE(latest_notice_date, '') DESC,
                selected_gp_count DESC,
                notice_count DESC,
                lp_name
            """,
        )
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
        notices = [row for row in notices if is_public_lp_notice_row(row, require_official=True)]

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
                require_official=False,
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
            <span>출자공고</span>
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
            <span data-label="출자공고">{html_escape(str(row.get("visible_notice_count", row.get("notice_count") or 0)))}건</span>
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
        return """          <p class="ktcu-empty-note">활동 내역이 없습니다.</p>"""
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
        return """          <p class="ktcu-empty-note">선정 GP 이력이 없습니다.</p>"""
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


def public_gap_text(value: object) -> str:
    text = str(value or "")
    if any(token in text for token in ["정규화", "notice_id", "중복 게시"]):
        return "동일 공고가 여러 공식 채널에 게시될 수 있습니다."
    if any(token in text for token in ["구조화", "상세 첨부파일"]):
        return "첨부 자료와 선정 결과는 공식 발표 기준으로 봅니다."
    if "선정 GP" in text:
        return "선정 GP와 개별 펀드 정보는 공식 발표 기준으로 봅니다."
    if any(token in text for token in ["잔액", "AUM", "최신"]):
        return "자산 규모와 대체투자 잔액은 최신 공식 자료를 기준으로 봅니다."
    if any(token in text for token in ["조달 공고", "투자 공고"]):
        return "입찰공고에는 조달·투자 공고가 함께 게시될 수 있습니다."
    return clean_public_lp_text(text)


def public_gap_label(value: object) -> str:
    text = str(value or "")
    if "공개자료" in text and "한계" in text:
        return "참고"
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
        """        <p class="ktcu-empty-note">공식 출자공고가 없습니다.</p>"""
    )
    max_yearly = max([float(row.get("allocation_amount_krw_100mn") or 0) for row in yearly] or [0])
    yearly_rows = "\n".join(render_ktcu_year_bar(row, max_yearly) for row in yearly) or (
        """        <p class="ktcu-empty-note">연도별 공고 규모가 없습니다.</p>"""
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
        """          <p class="ktcu-empty-note">자산군별 출자 패턴이 없습니다.</p>"""
    )
    general_rows = render_ktcu_fact_list(facts_in_section(facts, "general")) or (
        """          <div><dt>기관 개요</dt><dd>공식 자료 항목이 없습니다.</dd></div>"""
    )
    status_rows = render_ktcu_fact_list(facts_in_section(facts, "investment_status")) or (
        """          <div><dt>투자 현황</dt><dd>공식 자료 항목이 없습니다.</dd></div>"""
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
    gap_rows = render_public_gap_rows(facts_in_section(facts, "data_gap"))
    gap_details = (
        f"""      <details class="ktcu-detail" id="notes">
        <summary>참고사항</summary>
        <div class="ktcu-detail-body">
          <dl class="ktcu-facts">
{gap_rows}
          </dl>
        </div>
      </details>
"""
        if gap_rows.strip()
        else ""
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
        f"""          <p class="ktcu-empty-note">{highlight_year}년 공식 공고가 없습니다.</p>"""
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
{gap_details}
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
        if path.name not in service_pages and not path.name.startswith("lp-notice-"):
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
    coverage_tier = str(item.get("coverage_tier") or "candidate")
    tracking_enabled = "1" if safe_int(item.get("notice_tracking_enabled")) else "0"
    notice_count = safe_int(item.get("visible_notice_count", item.get("notice_count")))
    latest = str(item.get("latest_event_date") or "-") or "-"
    amount = public_amount_label(item.get("allocation_amount_krw_100mn"), fallback="-")
    amount_sort = safe_float(item.get("allocation_amount_krw_100mn"))
    homepage_url = str(item.get("homepage_url") or "")
    profile_url = f"lp-{lp_code}.html" if lp_code else "lp-notices.html"
    avatar_label = directory_avatar_label(lp_short_label(lp_code, lp_name), "LP")
    avatar_markup = directory_avatar_markup(homepage_url, avatar_label, lp_code or lp_name)
    search_blob = " ".join([lp_name, lp_type, ownership_label, default_team, focus, coverage_tier])
    title_markup = (
        f'<a href="{html_escape(profile_url)}">{html_escape(lp_name)}</a>'
        if item.get("has_public_profile", True)
        else html_escape(lp_name)
    )
    return f"""          <article class="lp-directory-card" aria-label="{html_escape(lp_name)}" data-search="{html_escape(search_blob)}" data-name="{html_escape(lp_name)}" data-lp="{html_escape(lp_code)}" data-asset="{html_escape(focus)}" data-kind="{html_escape(' '.join([lp_type, ownership_label]))}" data-tier="{html_escape(coverage_tier)}" data-tracking="{tracking_enabled}" data-notices="{notice_count}" data-amount="{amount_sort:.4f}" data-latest="{html_escape(latest)}">
            {avatar_markup}
            <div class="lp-directory-card-head">
              <strong>{title_markup}</strong>
            </div>
            <p class="lp-directory-focus">{html_escape(focus)}</p>
            <span class="lp-directory-latest">{html_escape(latest)}</span>
            <dl class="lp-directory-metrics">
              <div><dt>출자공고</dt><dd>{notice_count}건</dd></div>
              <div><dt>공고 규모</dt><dd>{html_escape(amount)}</dd></div>
            </dl>
          </article>"""


def render_lp_notices_page(
    report_date: str,
    notices: list[dict[str, object]],
    nav_items: list[dict[str, str]] | None = None,
    directory_items: list[dict[str, object]] | None = None,
    lifecycle_rows: list[dict[str, object]] | None = None,
    active_tab: str = "lp",
    notices_preconsolidated: bool = False,
) -> str:
    is_notice_view = active_tab == "notice"
    body_class = "lp-notices-page lp-official-notices-page" if is_notice_view else "lp-notices-page"
    search_input_id = "lpOfficialNoticeSearch" if is_notice_view else "lpDirectorySearch"
    search_placeholder = "공고명, LP, GP 검색" if is_notice_view else "LP명, 자산군 검색"
    if is_notice_view and not notices_preconsolidated:
        notices = prepare_lp_notice_display_items(notices, report_date)
    notice_status_counts = {
        status: len([item for item in notices if lp_notice_public_status(item, report_date) == status])
        for status in ["open", "shortlist", "result", "closed", "cancellation", "history"]
    }
    notice_groups = [
        ("open", "공고중", [item for item in notices if lp_notice_public_status(item, report_date) == "open"]),
        ("closed", "접수마감", [item for item in notices if lp_notice_public_status(item, report_date) == "closed"]),
        ("shortlist", "1차 선정", [item for item in notices if lp_notice_public_status(item, report_date) == "shortlist"]),
        ("result", "선정완료", [item for item in notices if lp_notice_public_status(item, report_date) == "result"]),
        (
            "cancellation",
            "취소",
            [
                item
                for item in notices
                if lp_notice_public_status(item, report_date) == "cancellation"
            ],
        ),
        (
            "history",
            "히스토리",
            [
                item
                for item in notices
                if lp_notice_public_status(item, report_date) == "history"
            ],
        ),
    ]
    notice_cards = "\n".join(
        f"""          <section class="lp-notice-group" data-group="{html_escape(group_key)}">
            <h2 class="section-title">{html_escape(group_title)}</h2>
            <div class="lp-page-list lp-notice-list">
{''.join(render_lp_notice_card(item, report_date) for item in group_items) or '<div class="empty-state visible"><strong>공고가 없습니다</strong></div>'}
            </div>
          </section>"""
        for group_key, group_title, group_items in notice_groups
        if group_items
    )
    if not notice_cards:
        notice_cards = """          <div class="empty-state visible">
            <strong>공식 출자공고가 없습니다</strong>
            <span>조건에 맞는 공고가 없습니다.</span>
          </div>"""
    notice_year_summary = render_lp_notice_year_summary(notices, report_date) if is_notice_view else ""
    lifecycle_summary = render_lp_lifecycle_summary(lifecycle_rows or [], report_date) if is_notice_view else ""
    directory_rows = directory_items or []
    directory_cards = "\n".join(render_lp_directory_card(item) for item in directory_rows) or (
        """          <div class="empty-state visible">
            <strong>출자기관 목록이 없습니다</strong>
            <span>조건에 맞는 기관이 없습니다.</span>
          </div>"""
    )
    tracked_count = len(directory_rows)
    tier_counts = {
        "core": len([item for item in directory_rows if str(item.get("coverage_tier") or "") == "core"]),
        "ocio": len([item for item in directory_rows if str(item.get("coverage_tier") or "") == "ocio"]),
        "policy": len([item for item in directory_rows if str(item.get("coverage_tier") or "") == "policy"]),
    }
    visible_notice_count = len(notices)
    total_amount = sum(float(item.get("allocation_amount_krw_100mn") or 0) for item in directory_rows)
    if is_notice_view:
        notice_status_tabs = f"""
        <div class="lp-notice-status-tabs" role="tablist" aria-label="출자공고 상태">
          <button class="lp-notice-status-tab" type="button" data-status="all">전체</button>
          <button class="lp-notice-status-tab" type="button" data-status="open">공고중</button>
          <button class="lp-notice-status-tab" type="button" data-status="closed">접수마감</button>
          <button class="lp-notice-status-tab" type="button" data-status="shortlist">1차 선정</button>
          <button class="lp-notice-status-tab" type="button" data-status="result">선정완료</button>
          <button class="lp-notice-status-tab" type="button" data-status="cancellation">취소</button>
          <button class="lp-notice-status-tab" type="button" data-status="history">히스토리</button>
        </div>"""
        notice_amount = sum(
            lp_notice_amount_label(item)[1]
            for item in notices
            if lp_notice_amount_label(item)[1] > 0
        )
        notice_with_gp_count = len([item for item in notices if split_notice_names(item.get("selectedGpNames"))])
        hero_title = f'<div class="lp-notice-title-row"><h1 class="lp-directory-title">출자공고</h1><p class="lp-directory-meta">{html_escape(korean_date_label(report_date))} 기준</p></div>'
        hero_meta = ""
        hero_kpis = ""
        hero_class = "lp-directory-hero lp-notice-hero"
        notice_summary_html = ""
    else:
        hero_title = f'<h1 class="lp-directory-title"><strong>{tracked_count}개</strong> 출자기관</h1>'
        hero_meta = f'<p class="lp-directory-meta">핵심 LP {tier_counts["core"]}개 · OCIO/공적기금 {tier_counts["ocio"]}개 · 정책펀드 {tier_counts["policy"]}개 · 공식 공고 {visible_notice_count}건 · {html_escape(report_date)} 기준</p>'
        hero_kpis = f"""
        <div class="lp-directory-kpis">
          <div><span>대상 기관</span><strong>{tracked_count}개</strong></div>
          <div><span>OCIO/공적기금</span><strong>{tier_counts["ocio"]}개</strong></div>
          <div><span>공고 기준 규모</span><strong>{html_escape(public_amount_label(total_amount, fallback="-"))}</strong></div>
          <div><span>출자공고</span><strong>{visible_notice_count}건</strong></div>
        </div>"""
        hero_class = "lp-directory-hero"
        notice_summary_html = ""
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
    notice_year_options = "".join(
        f'<option value="{html_escape(year)}">{html_escape(year)}년</option>'
        for year in sorted(
            {
                str(item.get("latestEventDate") or item.get("eventDate") or item.get("announcedDate") or "")[:4]
                for item in notices
                if re.match(r"^20\d{2}", str(item.get("latestEventDate") or item.get("eventDate") or item.get("announcedDate") or ""))
            },
            reverse=True,
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
              <option value="core">핵심 LP</option>
              <option value="ocio">OCIO/공적기금</option>
              <option value="policy">정책펀드</option>
              <option value="1">공고 추적</option>
            </select>
            <select id="lpSort" aria-label="정렬">
              <option value="latest">최근 공고일순</option>
              <option value="amount">공고 규모순</option>
              <option value="notices">공고 많은 순</option>
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
            <span>출자공고</span>
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
{notice_summary_html}
{notice_status_tabs}
        <div class="lp-notice-toolbar">
          <div class="lp-control-head">
            <label for="{search_input_id}">공고 필터</label>
            <span id="lpNoticeVisibleCount">{visible_notice_count}건 표시</span>
          </div>
        <div class="lp-control-line lp-notice-controls">
            <select id="lpNoticeYearFilter" aria-label="연도">
              <option value="all">전체 연도</option>
              {notice_year_options}
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
              <option value="deadline">마감임박순</option>
              <option value="amount">출자규모순</option>
              <option value="result">선정결과순</option>
            </select>
          </div>
        </div>
        <div class="lp-notice-records">
          <div class="lp-notice-groups">
{notice_cards}
          </div>
          <button class="lp-notice-load-more" id="lpNoticeLoadMore" type="button">더 보기</button>
          <div class="empty-state" id="lpNoticeEmpty"><strong>조건에 맞는 공고가 없습니다</strong></div>
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
    .lp-directory-table {{ overflow: hidden; border: 1px solid var(--separator); border-radius: 6px; background: var(--surface); }}
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
    .lp-directory-card-head,
    .lp-directory-card-head strong,
    .lp-directory-card-head a {{ text-align: left; }}
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
    .lp-notice-status-tabs {{
      position: relative;
      display: flex;
      gap: 16px;
      overflow: auto;
      padding: 0 2px 12px;
      border-bottom: 1px solid var(--separator);
      scrollbar-width: none;
      -ms-overflow-style: none;
    }}
    .lp-notice-status-tabs::-webkit-scrollbar {{
      display: none;
    }}
    .lp-notice-status-tab {{
      flex: 0 0 auto;
      appearance: none;
      border: 0;
      border-radius: 0;
      margin: 0;
      padding: 0 0 8px;
      min-height: 34px;
      background: transparent;
      color: var(--secondary);
      font-size: 12.5px;
      font-weight: 660;
      letter-spacing: 0;
      line-height: 1.2;
      font-family: inherit;
      cursor: pointer;
      transition: color 0.15s ease;
    }}
    .lp-notice-status-tab span {{
      margin-left: 6px;
      color: #9aa0a6;
      font-size: 11.5px;
      font-weight: 650;
    }}
    .lp-notice-status-tab:hover,
    .lp-notice-status-tab:focus-visible {{
      color: var(--text);
      outline: none;
    }}
    .lp-notice-status-tab.active {{
      color: var(--text);
      font-weight: 780;
      border-bottom: 2px solid #111214;
    }}
    .lp-notice-status-tab.active span {{
      color: var(--text);
    }}
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
      .lp-directory-table {{ border: 1px solid var(--separator); background: var(--surface); box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }}
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
    .lp-notice-hero {{
      max-width: 760px;
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
    .lp-directory-table {{
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
      .lp-notice-hero {{
        grid-template-columns: minmax(0, 1fr) !important;
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
        grid-template-columns: 180px 180px 220px 180px;
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
    body.lp-notices-page .lp-lifecycle-summary {{
      margin: 0 0 14px;
    }}
    body.lp-notices-page .lp-lifecycle-title {{
      display: grid;
      gap: 3px;
      margin: 0 0 8px;
    }}
    body.lp-notices-page .lp-lifecycle-title h2 {{
      margin: 0;
      color: var(--text);
      font-size: 15px;
      font-weight: 780;
      line-height: 1.35;
    }}
    body.lp-notices-page .lp-lifecycle-title p {{
      margin: 0;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 620;
      line-height: 1.42;
    }}
    body.lp-notices-page .lp-lifecycle-table {{
      overflow: hidden;
      border: 1px solid var(--separator);
      border-radius: 6px;
      background: var(--surface);
    }}
    body.lp-notices-page .lp-lifecycle-row {{
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) 34px 34px 34px 34px 34px 58px minmax(0, 1fr);
      gap: 8px;
      align-items: center;
      min-height: 48px;
      padding: 0 10px;
      border-bottom: 1px solid var(--separator);
      color: var(--text);
      font-size: 12.5px;
      font-weight: 660;
      text-decoration: none;
    }}
    body.lp-notices-page .lp-lifecycle-row:last-child {{
      border-bottom: 0;
    }}
    body.lp-notices-page a.lp-lifecycle-row:hover {{
      background: #fafafa;
    }}
    body.lp-notices-page .lp-lifecycle-row.is-head {{
      min-height: 36px;
      background: var(--surface-strong);
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 760;
    }}
    body.lp-notices-page .lp-lifecycle-row span {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    body.lp-notices-page .lp-lifecycle-row span:not(:first-child) {{
      text-align: right;
    }}
    body.lp-notices-page .lp-lifecycle-program {{
      display: grid;
      gap: 2px;
      text-align: left !important;
    }}
    body.lp-notices-page .lp-lifecycle-program strong {{
      min-width: 0;
      overflow: hidden;
      color: var(--text);
      font-size: 13px;
      font-weight: 760;
      line-height: 1.3;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    body.lp-notices-page .lp-lifecycle-program em {{
      min-width: 0;
      overflow: hidden;
      color: var(--secondary);
      font-size: 11.5px;
      font-style: normal;
      font-weight: 620;
      line-height: 1.3;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    body.lp-notices-page .lp-lifecycle-latest {{
      text-align: left !important;
    }}
    body.lp-notices-page .lp-notice-year-summary {{
      margin: 0 0 14px;
      border: 1px solid var(--separator);
      border-radius: 6px;
      background: var(--surface);
      overflow: hidden;
    }}
    body.lp-notices-page .lp-year-row {{
      display: grid;
      grid-template-columns: 58px 46px 46px 46px minmax(76px, 1fr);
      gap: 8px;
      align-items: center;
      width: 100%;
      min-height: 42px;
      padding: 0 10px;
      border: 0;
      border-bottom: 1px solid var(--separator);
      background: transparent;
      color: var(--text);
      font: inherit;
      text-align: left;
    }}
    body.lp-notices-page .lp-year-row:last-child {{
      border-bottom: 0;
    }}
    body.lp-notices-page .lp-year-row.is-head {{
      min-height: 36px;
      background: var(--surface-strong);
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 760;
    }}
    body.lp-notices-page button.lp-year-row {{
      cursor: pointer;
    }}
    body.lp-notices-page button.lp-year-row:hover {{
      background: #fafafa;
    }}
    body.lp-notices-page .lp-year-row strong {{
      font-size: 13px;
      font-weight: 760;
      letter-spacing: 0;
    }}
    body.lp-notices-page .lp-year-row span {{
      min-width: 0;
      color: inherit;
      font-size: 12px;
      font-weight: 650;
      line-height: 1.3;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    body.lp-notices-page .lp-notice-records {{
      display: grid;
      gap: 0;
      background: transparent;
    }}
    body.lp-notices-page .lp-notice-groups {{
      display: grid;
      gap: 16px;
    }}
    body.lp-notices-page .lp-notice-group {{
      border-top: 0;
    }}
    body.lp-notices-page .lp-notice-group + .lp-notice-group {{
      padding-top: 14px;
      border-top: 1px solid var(--separator);
    }}
    body.lp-notices-page .lp-notice-group .section-title {{
      margin: 0 0 8px;
      padding: 0;
      border-bottom: 0;
      color: var(--text);
      font-size: 14px;
      font-weight: 760;
      line-height: 1.35;
    }}
    body.lp-notices-page .lp-notice-list {{
      display: grid;
      gap: 8px;
    }}
    body.lp-notices-page .lp-notice-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 9px;
      align-items: stretch;
      min-height: 0;
      padding: 12px 11px;
      border: 1px solid var(--separator);
      border-radius: 7px;
      background: #ffffff;
      box-shadow: none;
    }}
    body.lp-notices-page .lp-notice-row:last-child {{
      border-bottom: 1px solid var(--separator);
    }}
    body.lp-notices-page .lp-notice-main {{
      display: grid;
      min-width: 0;
      gap: 5px;
    }}
    body.lp-notices-page .lp-notice-eyebrow,
    body.lp-notices-page .lp-notice-kicker {{
      display: flex;
      flex-wrap: wrap;
      gap: 4px 8px;
      align-items: center;
      margin: 0;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 650;
      line-height: 1.25;
    }}
    body.lp-notices-page .lp-notice-eyebrow span + span::before,
    body.lp-notices-page .lp-notice-kicker span + span::before {{
      color: var(--tertiary);
      content: "·";
      margin-right: 8px;
    }}
    body.lp-notices-page .lp-notice-status,
    body.lp-notices-page .lp-notice-stage {{
      color: #475569;
      font-size: 12px;
      font-weight: 760;
      line-height: 1.2;
    }}
    body.lp-notices-page .lp-notice-row[data-status="open"] .lp-notice-status,
    body.lp-notices-page .lp-notice-row[data-status="open"] .lp-notice-stage {{
      color: #047857;
    }}
    body.lp-notices-page .lp-notice-row[data-status="result"] .lp-notice-status,
    body.lp-notices-page .lp-notice-row[data-status="result"] .lp-notice-stage {{
      color: #1d4ed8;
    }}
    body.lp-notices-page .lp-notice-row[data-status="closed"] .lp-notice-status,
    body.lp-notices-page .lp-notice-row[data-status="history"] .lp-notice-status,
    body.lp-notices-page .lp-notice-row[data-status="closed"] .lp-notice-stage,
    body.lp-notices-page .lp-notice-row[data-status="history"] .lp-notice-stage {{
      color: #64748b;
    }}
    body.lp-notices-page .lp-notice-main h2 {{
      margin: 0;
      color: var(--text);
      font-size: 15px;
      font-weight: 760;
      line-height: 1.42;
      overflow-wrap: anywhere;
    }}
    body.lp-notices-page .lp-notice-main h2 a {{
      color: inherit;
      text-decoration: none;
    }}
    body.lp-notices-page .lp-notice-facts {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 10px;
      margin: 0;
    }}
    body.lp-notices-page .lp-notice-facts div {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 2px;
      min-width: 0;
      align-items: start;
    }}
    body.lp-notices-page .lp-notice-facts dt {{
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 650;
      line-height: 1.35;
    }}
    body.lp-notices-page .lp-notice-facts dd {{
      min-width: 0;
      margin: 0;
      color: var(--text);
      font-size: 12.5px;
      font-weight: 650;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    body.lp-notices-page .lp-notice-facts time {{
      color: inherit;
    }}
    body.lp-notices-page .lp-notice-materials {{
      grid-column: 1 / -1;
    }}
    body.lp-notices-page .lp-notice-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 4px;
    }}
    body.lp-notices-page .lp-notice-links a {{
      color: var(--secondary);
      font-size: 12px;
      font-weight: 680;
      text-decoration: none;
    }}
    body.lp-notices-page .lp-notice-links a:hover {{
      color: var(--text);
      text-decoration: underline;
      text-underline-offset: 3px;
    }}
    body.lp-notices-page .lp-notice-date-sub {{
      display: block;
      margin-top: 2px;
      color: var(--tertiary);
      font-size: 11.5px;
      font-weight: 600;
      line-height: 1.3;
    }}
    body.lp-notices-page .lp-notice-actions {{
      grid-column: 1 / -1;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      min-height: 0;
      align-items: center;
      padding-top: 0;
    }}
    body.lp-notices-page .lp-notice-actions:empty {{
      display: none;
    }}
    body.lp-notices-page .lp-notice-actions a {{
      min-height: 26px;
      padding: 2px 0;
      border-radius: 0;
      background: transparent;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 680;
      text-decoration: none;
    }}
    body.lp-notices-page .lp-notice-actions a:hover {{
      color: var(--text);
      text-decoration: underline;
      text-underline-offset: 3px;
    }}
    @media (max-width: 620px) {{
      body.lp-notices-page .lp-lifecycle-table {{
        display: none;
      }}
    }}
    @media (min-width: 960px) {{
      body.lp-notices-page .lp-notice-controls {{
        grid-template-columns: 140px 130px 160px minmax(180px, 1fr) 150px;
      }}
      body.lp-notices-page .lp-year-row {{
        grid-template-columns: 90px 80px 80px 80px minmax(180px, 1fr);
        padding: 0 14px;
      }}
      body.lp-notices-page .lp-lifecycle-row {{
        grid-template-columns: minmax(180px, 1.5fr) repeat(5, minmax(42px, 54px)) minmax(68px, 86px) minmax(180px, 1.2fr);
        gap: 10px;
        padding: 0 14px;
      }}
      body.lp-notices-page .lp-notice-groups {{
        gap: 18px;
      }}
      body.lp-notices-page .lp-notice-group + .lp-notice-group {{
        padding-top: 18px;
      }}
      body.lp-notices-page .lp-notice-group .section-title {{
        margin-bottom: 10px;
        font-size: 15px;
      }}
      body.lp-notices-page .lp-notice-list {{
        gap: 10px;
      }}
      body.lp-notices-page .lp-notice-row {{
        grid-template-columns: minmax(0, 1.1fr) minmax(330px, 0.9fr);
        gap: 9px 18px;
        padding: 13px 16px;
      }}
      body.lp-notices-page .lp-notice-main {{
        align-content: start;
      }}
      body.lp-notices-page .lp-notice-main h2 {{
        font-size: 15.5px;
      }}
      body.lp-notices-page .lp-notice-facts {{
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 8px 16px;
      }}
      body.lp-notices-page .lp-notice-facts div {{
        grid-template-columns: minmax(0, 1fr);
      }}
      body.lp-notices-page .lp-notice-materials {{
        grid-column: auto;
      }}
      body.lp-notices-page .lp-notice-actions {{
        grid-column: 2;
        justify-content: flex-start;
        padding-top: 6px;
        border-top: 1px solid #edf0f2;
      }}
    }}
    body.lp-notices-page .lp-notice-hero {{
      max-width: none;
      margin: 12px 0 12px;
    }}
    body.lp-notices-page .lp-directory-title {{
      font-size: 22px !important;
      font-weight: 820;
      line-height: 1.22;
    }}
    body.lp-notices-page .lp-directory-meta {{
      margin-top: 2px;
      color: #6f7378;
      font-size: 12px;
      font-weight: 620;
    }}
    body.lp-notices-page .lp-notice-summary {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      overflow: hidden;
      margin: 0 0 12px;
      border: 1px solid var(--separator);
      border-radius: 7px;
      background: #ffffff;
    }}
    body.lp-notices-page .lp-notice-summary div {{
      display: grid;
      gap: 2px;
      min-height: 54px;
      padding: 10px 11px;
      border-right: 1px solid var(--separator);
      border-bottom: 1px solid var(--separator);
      align-content: center;
    }}
    body.lp-notices-page .lp-notice-summary div:nth-child(3n) {{
      border-right: 0;
    }}
    body.lp-notices-page .lp-notice-summary div:nth-last-child(-n + 3) {{
      border-bottom: 0;
    }}
    body.lp-notices-page .lp-notice-summary span {{
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 650;
      line-height: 1.25;
    }}
    body.lp-notices-page .lp-notice-summary strong {{
      color: var(--text);
      font-size: 14px;
      font-weight: 780;
      line-height: 1.25;
    }}
    body.lp-notices-page .lp-notice-controls {{
      grid-template-columns: minmax(0, 1fr);
    }}
    body.lp-notices-page .lp-notice-toolbar {{
      margin-bottom: 12px;
    }}
    body.lp-notices-page .lp-control-head {{
      color: var(--secondary);
      font-size: 12px;
      font-weight: 720;
    }}
    body.lp-notices-page .lp-notice-toolbar select {{
      min-height: 40px;
      border-radius: 6px;
      background: #ffffff;
      color: var(--text);
      font-size: 13px;
      font-weight: 620;
    }}
    body.lp-notices-page .lp-notice-groups {{
      gap: 0;
    }}
    body.lp-notices-page .lp-notice-group {{
      border-top: 8px solid #f5f5f6;
    }}
    body.lp-notices-page .lp-notice-group:first-child {{
      border-top: 0;
    }}
    body.lp-notices-page .lp-notice-group + .lp-notice-group {{
      padding-top: 0;
      border-top: 8px solid #f5f5f6;
    }}
    body.lp-notices-page .lp-notice-group .section-title {{
      margin: 0;
      padding: 13px 10px 9px;
      border-bottom: 1px solid var(--separator);
      background: #ffffff;
      color: var(--text);
      font-size: 15px;
      font-weight: 800;
      line-height: 1.35;
    }}
    body.lp-notices-page .lp-notice-list {{
      display: grid;
      gap: 0;
      overflow: hidden;
      border: 0;
      border-radius: 0;
      background: #ffffff;
    }}
    body.lp-notices-page .lp-notice-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 10px;
      min-height: 0;
      padding: 14px 10px;
      border: 0;
      border-bottom: 1px solid var(--separator);
      border-radius: 0;
      background: #ffffff;
      box-shadow: none;
    }}
    body.lp-notices-page .lp-notice-row:last-child {{
      border-bottom: 0;
    }}
    body.lp-notices-page .lp-notice-main {{
      display: grid;
      gap: 5px;
      min-width: 0;
      align-content: start;
    }}
    body.lp-notices-page .lp-notice-kicker {{
      display: flex;
      flex-wrap: wrap;
      gap: 4px 8px;
      align-items: center;
      margin: 0;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 650;
      line-height: 1.3;
    }}
    body.lp-notices-page .lp-notice-kicker span + span::before {{
      color: var(--tertiary);
      content: "·";
      margin-right: 8px;
    }}
    body.lp-notices-page .lp-notice-status {{
      color: #52575c;
      font-weight: 820;
    }}
    body.lp-notices-page .lp-notice-row[data-status="open"] .lp-notice-status {{
      color: #0f766e;
    }}
    body.lp-notices-page .lp-notice-row[data-status="result"] .lp-notice-status {{
      color: #1f5fbf;
    }}
    body.lp-notices-page .lp-notice-row[data-status="closed"] .lp-notice-status,
    body.lp-notices-page .lp-notice-row[data-status="history"] .lp-notice-status {{
      color: #6f7378;
    }}
    body.lp-notices-page .lp-notice-main h2 {{
      margin: 0;
      color: var(--text);
      font-size: 15px;
      font-weight: 780;
      line-height: 1.42;
      overflow-wrap: anywhere;
    }}
    body.lp-notices-page .lp-notice-program {{
      margin: 0;
      color: var(--secondary);
      font-size: 12.5px;
      font-weight: 620;
      line-height: 1.4;
      overflow-wrap: anywhere;
    }}
    body.lp-notices-page .lp-notice-facts {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 9px 12px;
      margin: 0;
    }}
    body.lp-notices-page .lp-notice-facts div {{
      display: grid;
      gap: 2px;
      min-width: 0;
      align-content: start;
    }}
    body.lp-notices-page .lp-notice-facts dt {{
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 640;
      line-height: 1.3;
    }}
    body.lp-notices-page .lp-notice-facts dd {{
      min-width: 0;
      margin: 0;
      color: var(--text);
      font-size: 12.5px;
      font-weight: 690;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    body.lp-notices-page .lp-notice-materials {{
      grid-column: 1 / -1;
    }}
    body.lp-notices-page .lp-notice-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 0;
    }}
    body.lp-notices-page .lp-notice-links a {{
      color: var(--secondary);
      font-size: 12px;
      font-weight: 690;
      text-decoration: none;
    }}
    body.lp-notices-page .lp-notice-links a:hover {{
      color: var(--text);
      text-decoration: underline;
      text-underline-offset: 3px;
    }}
    body.lp-notices-page #lpNoticeEmpty {{
      display: none;
      padding: 28px 10px;
      border-top: 1px solid var(--separator);
      background: #ffffff;
    }}
    body.lp-notices-page #lpNoticeEmpty.visible {{
      display: block;
    }}
    @media (min-width: 760px) {{
      body.lp-notices-page .lp-directory-title {{
        font-size: 24px !important;
      }}
      body.lp-notices-page .lp-notice-summary {{
        grid-template-columns: repeat(6, minmax(0, 1fr));
      }}
      body.lp-notices-page .lp-notice-summary div,
      body.lp-notices-page .lp-notice-summary div:nth-child(3n) {{
        border-right: 1px solid var(--separator);
        border-bottom: 0;
      }}
      body.lp-notices-page .lp-notice-summary div:last-child {{
        border-right: 0;
      }}
    }}
    @media (min-width: 960px) {{
      body.lp-notices-page .lp-notice-controls {{
        grid-template-columns: 128px 128px 150px minmax(180px, 1fr) 144px;
      }}
      body.lp-notices-page .lp-notice-group .section-title {{
        padding: 14px 18px 10px;
      }}
      body.lp-notices-page .lp-notice-row {{
        grid-template-columns: minmax(300px, 1.05fr) minmax(460px, 1.35fr);
        gap: 18px;
        padding: 16px 18px;
      }}
      body.lp-notices-page .lp-notice-main h2 {{
        font-size: 15.5px;
      }}
      body.lp-notices-page .lp-notice-facts {{
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 8px 14px;
      }}
      body.lp-notices-page .lp-notice-materials {{
        grid-column: 1 / -1;
      }}
    }}
    body.lp-official-notices-page .app-shell {{
      width: min(100%, 980px);
      background: #ffffff;
    }}
    body.lp-official-notices-page .content-area,
    body.lp-official-notices-page .app-header {{
      width: min(900px, calc(100% - 28px));
      max-width: 900px;
    }}
    body.lp-official-notices-page .lp-notice-hero {{
      margin: 10px 0 14px;
      gap: 5px;
    }}
    body.lp-official-notices-page .lp-directory-title {{
      font-size: 22px !important;
      font-weight: 830;
      line-height: 1.24;
    }}
    body.lp-official-notices-page .lp-directory-meta {{
      color: #73777d;
      font-size: 12px;
      font-weight: 620;
    }}
    body.lp-official-notices-page .lp-notice-summary {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px 12px;
      margin: 0 0 12px;
      border: 0;
      border-radius: 0;
      background: transparent;
      color: #73777d;
      font-size: 12px;
      font-weight: 650;
      line-height: 1.35;
    }}
    body.lp-official-notices-page .lp-notice-summary span {{
      color: #73777d;
      font-size: 12px;
      font-weight: 650;
    }}
    body.lp-official-notices-page .lp-notice-summary strong {{
      color: #111214;
      font-size: 12px;
      font-weight: 800;
    }}
    body.lp-official-notices-page .lp-control-head {{
      font-size: 12px;
      font-weight: 700;
    }}
    body.lp-official-notices-page .lp-notice-toolbar select {{
      min-height: 39px;
      border-color: #e2e4e7;
      border-radius: 8px;
      background: #ffffff;
      color: #202124;
      font-size: 13px;
      font-weight: 620;
    }}
    body.lp-official-notices-page .lp-notice-status-legacy {{
      display: none;
    }}
    body.lp-official-notices-page .lp-notice-toolbar select {{
      background: #f8f9fa;
    }}
    body.lp-official-notices-page .lp-notice-groups {{
      gap: 12px;
    }}
    body.lp-official-notices-page .lp-notice-group,
    body.lp-official-notices-page .lp-notice-group + .lp-notice-group {{
      padding-top: 0;
      border-top: 0;
    }}
    body.lp-official-notices-page .lp-notice-group .section-title {{
      margin: 0;
      padding: 12px 2px 8px;
      border: 0;
      background: transparent;
      color: #111214;
      font-size: 15.5px;
      font-weight: 820;
      line-height: 1.35;
    }}
    body.lp-official-notices-page .lp-notice-list {{
      display: grid;
      gap: 8px;
      overflow: visible;
      background: transparent;
    }}
    body.lp-official-notices-page .lp-notice-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 9px;
      padding: 14px 12px;
      border-top: 1px solid var(--separator);
      border-right: 0;
      border-bottom: 0;
      border-left: 0;
      border-radius: 0;
      background: #ffffff;
      box-shadow: none;
    }}
    body.lp-official-notices-page .lp-notice-main {{
      display: grid;
      gap: 5px;
      min-width: 0;
    }}
    body.lp-official-notices-page .lp-notice-kicker {{
      display: flex;
      flex-wrap: wrap;
      gap: 5px 8px;
      align-items: center;
      margin: 0;
      color: #73777d;
      font-size: 12px;
      font-weight: 670;
      line-height: 1.3;
    }}
    body.lp-official-notices-page .lp-notice-kicker span + span::before {{
      color: #b8bcc2;
      content: "·";
      margin-right: 8px;
    }}
    body.lp-official-notices-page .lp-notice-status {{
      color: #111214;
      font-size: 12px;
      font-weight: 850;
    }}
    body.lp-official-notices-page .lp-notice-row[data-status="open"] .lp-notice-status {{
      color: #087f5b;
    }}
    body.lp-official-notices-page .lp-notice-row[data-status="result"] .lp-notice-status {{
      color: #1d4ed8;
    }}
    body.lp-official-notices-page .lp-notice-row[data-status="closed"] .lp-notice-status,
    body.lp-official-notices-page .lp-notice-row[data-status="history"] .lp-notice-status {{
      color: #667085;
    }}
    body.lp-official-notices-page .lp-notice-main h2 {{
      margin: 0;
      color: #111214;
      font-size: 16px;
      font-weight: 830;
      line-height: 1.38;
      overflow-wrap: anywhere;
    }}
    body.lp-official-notices-page .lp-notice-main h2 a {{
      color: inherit;
      text-decoration: none;
    }}
    body.lp-official-notices-page .lp-notice-summary-title {{
      margin: 0;
      color: #73777d;
      font-size: 12.5px;
      font-weight: 620;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }}
    body.lp-official-notices-page .lp-notice-summary-meta {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 1px 0 0;
      color: #8a8f98;
      font-size: 11.8px;
      font-weight: 640;
      line-height: 1.35;
    }}
    body.lp-official-notices-page .lp-notice-summary-meta span + span::before {{
      margin-right: 8px;
      content: "·";
      color: #b8bcc2;
    }}
    body.lp-official-notices-page .lp-notice-facts {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 9px 14px;
      margin: 0;
    }}
    body.lp-official-notices-page .lp-notice-facts div {{
      display: grid;
      gap: 2px;
      min-width: 0;
      align-content: start;
    }}
    body.lp-official-notices-page .lp-notice-facts dt {{
      color: #8a8f98;
      font-size: 11.5px;
      font-weight: 650;
      line-height: 1.3;
    }}
    body.lp-official-notices-page .lp-notice-facts dd {{
      min-width: 0;
      margin: 0;
      color: #202124;
      font-size: 13px;
      font-weight: 720;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    body.lp-official-notices-page .lp-notice-materials {{
      grid-column: 1 / -1;
    }}
    body.lp-official-notices-page .lp-notice-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 10px;
      margin: 0;
    }}
    body.lp-official-notices-page .lp-notice-links a {{
      color: #4f545b;
      font-size: 12.5px;
      font-weight: 760;
      text-decoration: none;
    }}
    body.lp-official-notices-page .lp-notice-links a:hover {{
      color: #111214;
      text-decoration: underline;
      text-underline-offset: 3px;
    }}
    body.lp-official-notices-page .lp-notice-timeline {{
      display: grid;
      gap: 0;
      margin: 2px 0 0;
      padding: 8px 0 0;
      border-top: 1px solid #edf0f2;
      list-style: none;
    }}
    body.lp-official-notices-page .lp-notice-timeline li {{
      display: grid;
      grid-template-columns: 82px 58px minmax(0, 1fr);
      gap: 8px;
      align-items: start;
      min-width: 0;
      padding: 4px 0;
      color: #73777d;
      font-size: 11.5px;
      line-height: 1.35;
    }}
    body.lp-official-notices-page .lp-notice-timeline time {{
      color: #8a8f98;
      font-weight: 620;
    }}
    body.lp-official-notices-page .lp-notice-timeline strong {{
      color: #4f545b;
      font-weight: 780;
    }}
    body.lp-official-notices-page .lp-notice-timeline span {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    @media (min-width: 760px) {{
      body.lp-official-notices-page .content-area,
      body.lp-official-notices-page .app-header {{
        width: min(900px, calc(100% - 44px));
      }}
      body.lp-official-notices-page .lp-notice-row {{
        grid-template-columns: minmax(280px, 1fr) minmax(330px, 0.95fr);
        gap: 10px 18px;
        padding: 14px 16px;
      }}
      body.lp-official-notices-page .lp-notice-facts {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px 14px;
      }}
      body.lp-official-notices-page .lp-notice-timeline {{
        grid-column: 1 / -1;
      }}
      body.lp-official-notices-page .lp-notice-controls {{
        grid-template-columns: 128px 128px 150px minmax(180px, 1fr) 144px;
      }}
    }}
    body.lp-official-notices-page {{
      background: #ffffff;
    }}
    body.lp-official-notices-page .app-shell {{
      width: min(100%, 1120px);
      background: #ffffff;
      padding-bottom: calc(132px + env(safe-area-inset-bottom));
      box-shadow: none;
    }}
    body.lp-official-notices-page .content-area,
    body.lp-official-notices-page .app-header {{
      width: min(1040px, calc(100% - 32px));
      max-width: 1040px;
      margin-right: auto;
      margin-left: auto;
    }}
    body.lp-official-notices-page .lp-notice-hero {{
      margin: 10px 0 12px;
      padding: 0;
    }}
    body.lp-official-notices-page .lp-notice-title-row {{
      display: flex;
      gap: 10px;
      align-items: baseline;
      justify-content: space-between;
      min-width: 0;
    }}
    body.lp-official-notices-page .lp-directory-title {{
      display: block;
      margin: 0;
      color: #111214;
      font-size: 23px !important;
      font-weight: 830;
      line-height: 1.22;
    }}
    body.lp-official-notices-page .lp-directory-meta {{
      flex: 0 0 auto;
      margin: 0;
      color: #73777d;
      font-size: 12.5px;
      font-weight: 680;
      line-height: 1.35;
      white-space: nowrap;
    }}
    body.lp-official-notices-page .lp-notice-summary,
    body.lp-official-notices-page .lp-notice-year-summary,
    body.lp-official-notices-page .lp-lifecycle-summary {{
      display: none;
    }}
    body.lp-official-notices-page .lp-notice-status-tabs {{
      gap: 18px;
      margin: 0 0 10px;
      padding: 0 0 10px;
      border-bottom: 1px solid #e5e7eb;
      background: transparent;
    }}
    body.lp-official-notices-page .lp-notice-status-tab {{
      min-height: 31px;
      padding: 0 0 8px;
      color: #7a7f86;
      font-size: 13px;
      font-weight: 690;
    }}
    body.lp-official-notices-page .lp-notice-status-tab.active {{
      color: #111214;
      border-bottom: 2px solid #111214;
      font-weight: 820;
    }}
    body.lp-official-notices-page .lp-notice-toolbar {{
      margin: 0 0 12px;
    }}
    body.lp-official-notices-page .lp-control-head {{
      color: #73777d;
      font-size: 12px;
      font-weight: 720;
    }}
    body.lp-official-notices-page .lp-notice-controls {{
      grid-template-columns: minmax(0, 1fr);
      gap: 8px;
    }}
    body.lp-official-notices-page .lp-notice-toolbar select {{
      min-height: 42px;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      background: #ffffff;
      color: #222426;
      font-size: 13px;
      font-weight: 660;
    }}
    body.lp-official-notices-page .lp-notice-records {{
      padding-bottom: 28px;
    }}
    body.lp-official-notices-page .lp-notice-groups {{
      display: grid;
      gap: 10px;
    }}
    body.lp-official-notices-page .lp-notice-group,
    body.lp-official-notices-page .lp-notice-group + .lp-notice-group {{
      padding-top: 0;
      border-top: 0;
    }}
    body.lp-official-notices-page .lp-notice-group .section-title {{
      margin: 0 0 8px;
      padding: 0 2px;
      border: 0;
      background: transparent;
      color: #111214;
      font-size: 15px;
      font-weight: 820;
      line-height: 1.35;
    }}
    body.lp-official-notices-page .lp-notice-list {{
      display: grid;
      gap: 10px;
      overflow: visible;
      background: transparent;
    }}
    body.lp-official-notices-page .lp-notice-row {{
      position: relative;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 12px;
      min-height: 0;
      padding: 16px;
      border: 1px solid #eceff2;
      border-radius: 8px;
      background: #ffffff;
      box-shadow: none;
    }}
    body.lp-official-notices-page .lp-notice-row:last-child {{
      border-bottom: 0;
    }}
    body.lp-official-notices-page .lp-notice-card-top {{
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: space-between;
      min-width: 0;
    }}
    body.lp-official-notices-page .lp-notice-status {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 22px;
      border-radius: 999px;
      padding: 0 9px;
      background: #f3f4f6;
      color: #4b5563;
      font-size: 11.5px;
      font-weight: 780;
      line-height: 1.25;
      white-space: nowrap;
    }}
    body.lp-official-notices-page .lp-notice-status.is-open,
    body.lp-official-notices-page .lp-notice-row[data-status="open"] .lp-notice-status {{
      background: #ecfdf3;
      color: #166534;
    }}
    body.lp-official-notices-page .lp-notice-status.is-shortlist,
    body.lp-official-notices-page .lp-notice-row[data-status="shortlist"] .lp-notice-status {{
      background: #eff6ff;
      color: #1d4ed8;
    }}
    body.lp-official-notices-page .lp-notice-status.is-result,
    body.lp-official-notices-page .lp-notice-row[data-status="result"] .lp-notice-status {{
      background: #111827;
      color: #ffffff;
    }}
    body.lp-official-notices-page .lp-notice-status.is-cancel,
    body.lp-official-notices-page .lp-notice-row[data-status="cancellation"] .lp-notice-status {{
      background: #fff2f2;
      color: #b91c1c;
    }}
    body.lp-official-notices-page .lp-notice-status.is-closed,
    body.lp-official-notices-page .lp-notice-row[data-status="closed"],
    body.lp-official-notices-page .lp-notice-row[data-status="history"] .lp-notice-status {{
      background: #f5f5f5;
      color: #6b7280;
    }}
    body.lp-official-notices-page .lp-notice-main h2 {{
      margin: 0;
      color: #111214;
      font-size: 17px;
      font-weight: 820;
      line-height: 1.38;
      overflow-wrap: anywhere;
    }}
    body.lp-official-notices-page .lp-notice-facts {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px 14px;
      margin: 0;
    }}
    body.lp-official-notices-page .lp-notice-facts div {{
      display: grid;
      gap: 3px;
      min-width: 0;
    }}
    body.lp-official-notices-page .lp-notice-facts dt {{
      color: #8a8f98;
      font-size: 11.5px;
      font-weight: 660;
      line-height: 1.3;
    }}
    body.lp-official-notices-page .lp-notice-facts dd {{
      margin: 0;
      color: #222426;
      font-size: 13.2px;
      font-weight: 720;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    body.lp-official-notices-page .lp-notice-card-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px 10px;
      align-items: center;
      color: #7a7f86;
      font-size: 12px;
      font-weight: 650;
      line-height: 1.35;
    }}
    body.lp-official-notices-page .lp-notice-preview-title {{
      margin: 2px 0 4px;
      color: #636770;
      font-size: 11.7px;
      font-weight: 740;
      letter-spacing: 0;
    }}
    body.lp-official-notices-page .lp-notice-preview-timeline {{
      display: grid;
      gap: 4px;
      margin: 0;
      padding: 0;
      list-style: none;
      border-top: 1px solid #f0f2f4;
      padding-top: 8px;
    }}
    body.lp-official-notices-page .lp-notice-preview-timeline li {{
      display: grid;
      gap: 4px;
      grid-template-columns: 80px minmax(56px, auto) minmax(0, 1fr);
      align-items: baseline;
      color: #52585f;
      font-size: 12px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    body.lp-official-notices-page .lp-notice-preview-timeline time {{
      color: #888d96;
      font-size: 11px;
      font-weight: 660;
      white-space: nowrap;
    }}
    body.lp-official-notices-page .lp-notice-preview-timeline strong {{
      color: #111214;
      font-size: 12px;
      font-weight: 740;
      white-space: nowrap;
    }}
    body.lp-official-notices-page .lp-notice-preview-timeline span {{
      min-width: 0;
      color: #5f6770;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    body.lp-official-notices-page .lp-notice-source-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: fit-content;
      min-height: 30px;
      margin-top: 2px;
      border-radius: 8px;
      padding: 0 10px;
      background: #f6f7f8;
      color: #3f4952;
      text-decoration: none;
      font-size: 12.2px;
      font-weight: 760;
    }}
    body.lp-official-notices-page .lp-notice-card-meta .lp-notice-source-link {{
      min-height: 24px;
      margin-top: 0;
      padding: 0 8px;
      background: #f4f5f6;
      font-size: 11.8px;
    }}
    body.lp-official-notices-page .lp-notice-load-more {{
      display: none;
      width: 100%;
      min-height: 46px;
      margin-top: 12px;
      border: 0;
      border-radius: 8px;
      background: #ffffff;
      color: #111214;
      border: 1px solid #eceff2;
      box-shadow: none;
      font: inherit;
      font-size: 14px;
      font-weight: 820;
      cursor: pointer;
    }}
    @media (min-width: 760px) {{
      body.lp-official-notices-page .lp-notice-controls {{
        grid-template-columns: repeat(5, minmax(0, 1fr));
      }}
      body.lp-official-notices-page .lp-notice-row {{
        grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
        gap: 14px 22px;
        padding: 18px;
      }}
      body.lp-official-notices-page .lp-notice-facts {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}
    @media (max-width: 620px) {{
      body.lp-official-notices-page .content-area,
      body.lp-official-notices-page .app-header {{
        width: 100%;
        max-width: none;
      }}
      body.lp-official-notices-page .app-shell {{
        padding-right: 14px;
        padding-left: 14px;
      }}
      body.lp-official-notices-page .lp-app-header,
      body.lp-official-notices-page #lpNotices.section-block {{
        margin-right: 0;
        margin-left: 0;
      }}
      body.lp-official-notices-page .lp-notice-title-row {{
        align-items: flex-end;
      }}
      body.lp-official-notices-page .lp-directory-title {{
        font-size: 21px !important;
      }}
      body.lp-official-notices-page .lp-directory-meta {{
        font-size: 12px;
      }}
      body.lp-official-notices-page .lp-notice-main h2 {{
        font-size: 16px;
      }}
      body.lp-official-notices-page .lp-notice-card-top {{
        align-items: flex-start;
      }}
      body.lp-official-notices-page .lp-notice-controls {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      body.lp-official-notices-page .lp-notice-facts {{
        grid-template-columns: minmax(0, 1fr);
      }}
      body.lp-official-notices-page .lp-notice-preview-title,
      body.lp-official-notices-page .lp-notice-preview-timeline {{
        display: none;
      }}
      body.lp-official-notices-page .lp-notice-records {{
        padding-bottom: 96px;
      }}
    }}
  </style>
</head>
<body class="{body_class}">
  <div class="app-shell newsletter-only">
    {render_lp_service_header(active_tab, search_input_id, search_placeholder)}
    <main class="content-area">
      <section class="{hero_class}" aria-label="LP 디렉토리 요약">
        <div>
          {hero_title}
          {hero_meta}
        </div>
{hero_kpis}
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
      const noticeYearFilter = document.getElementById("lpNoticeYearFilter");
      const noticeAssetFilter = document.getElementById("lpNoticeAssetFilter");
      const noticeLpFilter = document.getElementById("lpNoticeLpFilter");
      const noticeStatusTabs = Array.from(document.querySelectorAll(".lp-notice-status-tab"));
      const directory = document.querySelector(".lp-directory-grid");
      const noticeGroups = Array.from(document.querySelectorAll(".lp-notice-group"));
      const yearSummaryRows = Array.from(document.querySelectorAll("[data-summary-year]"));
      const visible = document.getElementById("lpVisibleCount");
      const noticeVisible = document.getElementById("lpNoticeVisibleCount");
      const noticeEmpty = document.getElementById("lpNoticeEmpty");
      const noticeLoadMore = document.getElementById("lpNoticeLoadMore");
      const directoryCards = Array.from(document.querySelectorAll(".lp-directory-card"));
      const noticeCards = Array.from(document.querySelectorAll(".lp-notice-row"));
      const params = new URLSearchParams(window.location.search);
      const requestedStatus = params.get("status");
      const noticePageSize = 10;
      let noticeVisibleLimit = noticePageSize;
      let activeNoticeStatus = (new Set(["open", "shortlist", "result", "closed", "cancellation", "history"]).has(requestedStatus) && requestedStatus) ? requestedStatus : "all";
      const setStatusTabActive = (status) => {{
        noticeStatusTabs.forEach((tab) => {{
          const active = tab.dataset.status === status;
          tab.classList.toggle("active", active);
          if (active) {{
            tab.setAttribute("aria-current", "page");
          }} else {{
            tab.removeAttribute("aria-current");
          }}
        }});
      }};
      const syncNoticeStatus = (value) => {{
        noticeVisibleLimit = noticePageSize;
        activeNoticeStatus = value;
        setStatusTabActive(value);
        applyNotices();
      }};
      setStatusTabActive(activeNoticeStatus);
      const num = (card, key) => {{
        const value = Number(card.dataset[key]);
        return Number.isFinite(value) ? value : 0;
      }};
      const fieldsMatch = (card, active) => {{
        const fields = [card.dataset.asset, card.dataset.event, card.dataset.lp, card.dataset.kind, card.dataset.tier, card.dataset.tracking, card.dataset.status, card.dataset.statusGroup].filter(Boolean);
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
          if (mode === "amount") return Number(b.dataset.amount || 0) - Number(a.dataset.amount || 0);
          if (mode === "result") {{
            const resultDelta = Number(b.dataset.hasGp || 0) - Number(a.dataset.hasGp || 0);
            return resultDelta || (b.dataset.date || "").localeCompare(a.dataset.date || "");
          }}
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
        const active = activeNoticeStatus || "all";
        const activeYear = noticeYearFilter?.value || "all";
        const activeAsset = noticeAssetFilter?.value || "all";
        const activeLp = noticeLpFilter?.value || "all";
        let matchCount = 0;
        let shownCount = 0;
        const today = "{html_escape(report_date)}";
        noticeCards.forEach((card) => {{
          const yearMatch = activeYear === "all" || card.dataset.year === activeYear;
          const assetMatch = activeAsset === "all" || card.dataset.assetValue === activeAsset;
          const lpMatch = activeLp === "all" || card.dataset.lp === activeLp;
          const deadline = card.dataset.deadline || "";
          const daysToDeadline = deadline ? Math.floor((new Date(`${{deadline}}T00:00:00+09:00`) - new Date(`${{today}}T00:00:00+09:00`)) / 86400000) : 9999;
          const statusMatch = active === "all"
            || card.dataset.status === active
            || card.dataset.statusGroup === active
            || (active === "deadline-soon" && deadline && daysToDeadline >= 0 && daysToDeadline <= 14)
            || (active === "has-gp" && card.dataset.hasGp === "1");
          const matchedCard = statusMatch && yearMatch && assetMatch && lpMatch && queryMatch(card);
          if (matchedCard) matchCount += 1;
          const visibleCard = matchedCard && matchCount <= noticeVisibleLimit;
          card.style.display = visibleCard ? "" : "none";
          if (visibleCard) shownCount += 1;
        }});
        noticeGroups.forEach((group) => {{
          const hasVisible = Array.from(group.querySelectorAll(".lp-notice-row")).some((card) => card.style.display !== "none");
          group.style.display = hasVisible ? "" : "none";
        }});
        if (noticeVisible) noticeVisible.textContent = `${{matchCount.toLocaleString("ko-KR")}}건 표시`;
        if (noticeLoadMore) {{
          noticeLoadMore.style.display = matchCount > shownCount ? "block" : "none";
        }}
        noticeEmpty?.classList.toggle("visible", matchCount === 0);
      }};
      input?.addEventListener("input", () => {{
        applyDirectory();
        noticeVisibleLimit = noticePageSize;
        applyNotices();
      }});
      sort?.addEventListener("change", () => {{
        applyDirectorySort();
        applyDirectory();
      }});
      filter?.addEventListener("change", applyDirectory);
      noticeSort?.addEventListener("change", () => {{
        noticeVisibleLimit = noticePageSize;
        applyNoticeSort();
        applyNotices();
      }});
      noticeStatusTabs.forEach((tab) => {{
        tab.addEventListener("click", () => {{
          const value = String(tab.dataset.status || "all");
          syncNoticeStatus(value);
        }});
      }});
      noticeYearFilter?.addEventListener("change", () => {{
        noticeVisibleLimit = noticePageSize;
        applyNotices();
      }});
      noticeAssetFilter?.addEventListener("change", () => {{
        noticeVisibleLimit = noticePageSize;
        applyNotices();
      }});
      noticeLpFilter?.addEventListener("change", () => {{
        noticeVisibleLimit = noticePageSize;
        applyNotices();
      }});
      noticeLoadMore?.addEventListener("click", () => {{
        noticeVisibleLimit += noticePageSize;
        applyNotices();
      }});
      yearSummaryRows.forEach((row) => {{
        row.addEventListener("click", () => {{
          if (!noticeYearFilter) return;
          noticeYearFilter.value = row.dataset.summaryYear || "all";
          noticeVisibleLimit = noticePageSize;
          applyNotices();
        }});
      }});
      applyDirectorySort();
      applyNoticeSort();
      applyDirectory();
      applyNotices();
    }})();
  </script>
</body>
</html>
"""


def lp_notice_year_value(item: dict[str, object]) -> str:
    value = str(item.get("eventDate") or item.get("announcedDate") or "")[:4]
    return value if re.fullmatch(r"20\d{2}", value) else ""


def render_lp_notice_year_summary(notices: list[dict[str, object]], report_date: str) -> str:
    grouped: dict[str, list[dict[str, object]]] = {}
    for item in notices:
        year = lp_notice_year_value(item)
        if not year:
            continue
        grouped.setdefault(year, []).append(item)
    if not grouped:
        return ""
    rows: list[str] = []
    for year in sorted(grouped.keys(), reverse=True):
        items = grouped[year]
        open_count = len([item for item in items if lp_notice_status(item, report_date) == "open"])
        result_count = len([item for item in items if lp_notice_status(item, report_date) == "result"])
        lp_counts: dict[str, int] = {}
        for item in items:
            name = clean_public_lp_text(item.get("lpName") or "LP 미분류") or "LP 미분류"
            lp_counts[name] = lp_counts.get(name, 0) + 1
        top_lps = sorted(lp_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:2]
        lp_label = ", ".join(name for name, _count in top_lps)
        if len(lp_counts) > len(top_lps):
            lp_label += f" 외 {len(lp_counts) - len(top_lps)}"
        rows.append(
            f"""          <button class="lp-year-row" type="button" data-summary-year="{html_escape(year)}" aria-label="{html_escape(year)}년 공고 보기">
            <strong>{html_escape(year)}</strong>
            <span>{len(items):,}건</span>
            <span>{open_count:,}건</span>
            <span>{result_count:,}건</span>
            <span>{html_escape(lp_label or "-")}</span>
          </button>"""
        )
    return f"""        <div class="lp-notice-year-summary" aria-label="연도별 출자공고 요약">
          <div class="lp-year-row is-head" aria-hidden="true">
            <span>연도</span>
            <span>공고</span>
            <span>진행</span>
            <span>선정</span>
            <span>주요 LP</span>
          </div>
{chr(10).join(rows)}
        </div>"""


def lp_lifecycle_status_label(value: object) -> str:
    return {
        "open": "공고중",
        "final_selection": "선정완료",
        "shortlist": "1차 선정",
        "closed": "접수마감",
        "no_deadline": "일정 없음",
    }.get(str(value or ""), "공고")


def lp_lifecycle_amount(row: dict[str, object]) -> float:
    for key in [
        "allocation_amount_krw_100mn_sum",
        "commitment_amount_krw_100mn_sum",
        "amount_krw_100mn_sum",
        "program_size_krw_100mn_max",
    ]:
        amount = safe_float(row.get(key))
        if amount > 0:
            return amount
    return 0.0


def render_lp_lifecycle_summary(rows: list[dict[str, object]], report_date: str, limit: int = 8) -> str:
    rows = [
        row
        for row in rows
        if "2024-01-01" <= str(row.get("latest_notice_date") or "")[:10] <= report_date
    ]
    if not rows:
        return ""
    total_programs = len(rows)
    total_notices = sum(safe_int(row.get("notice_count")) for row in rows)
    open_count = sum(safe_int(row.get("open_count")) for row in rows)
    shortlist_count = sum(safe_int(row.get("shortlist_count")) for row in rows)
    final_count = sum(safe_int(row.get("final_selection_count")) for row in rows)
    selected_gp_count = sum(safe_int(row.get("selected_gp_count")) for row in rows)
    total_amount = sum(lp_lifecycle_amount(row) for row in rows)
    summary = (
        f"프로그램 {total_programs:,}개 · 단계 기록 {total_notices:,}건 · 공고중 {open_count:,}건 · "
        f"서류 {shortlist_count:,}건 · 최종 {final_count:,}건 · GP 연결 {selected_gp_count:,}건 · "
        f"{public_amount_label(total_amount, fallback='규모 미표기')}"
    )
    rendered_rows: list[str] = []
    for row in rows[:limit]:
        lp_name = clean_public_lp_text(row.get("lp_name") or "LP 미분류") or "LP 미분류"
        program_name = clean_public_lp_text(row.get("program_name") or "") or "프로그램 미분류"
        round_name = clean_public_lp_text(row.get("round_name") or "")
        program_label = f"{program_name} {round_name}".strip()
        asset_label = public_asset_class(row.get("asset_class")) if row.get("asset_class") else ""
        strategy = clean_public_lp_text(row.get("strategy") or "")
        status_label = lp_lifecycle_status_label(row.get("deadline_status"))
        detail = " · ".join(value for value in [lp_name, asset_label, strategy, status_label] if value)
        latest_title = clean_public_lp_text(row.get("latest_notice_title") or "") or "-"
        latest_date = str(row.get("latest_notice_date") or "")
        latest_label = " · ".join(value for value in [latest_date, latest_title] if value) or "-"
        amount_label = public_amount_label(lp_lifecycle_amount(row), fallback="-")
        href = str(row.get("latest_notice_url") or "")
        tag = "a" if href else "div"
        href_attr = f' href="{html_escape(href)}" target="_blank" rel="noreferrer"' if href else ""
        rendered_rows.append(
            f"""          <{tag} class="lp-lifecycle-row" {href_attr}>
            <span class="lp-lifecycle-program">
              <strong>{html_escape(program_label)}</strong>
              <em>{html_escape(detail)}</em>
            </span>
            <span>{safe_int(row.get("notice_count")):,}</span>
            <span>{safe_int(row.get("open_count")):,}</span>
            <span>{safe_int(row.get("shortlist_count")):,}</span>
            <span>{safe_int(row.get("final_selection_count")):,}</span>
            <span>{safe_int(row.get("selected_gp_count")):,}</span>
            <span>{html_escape(amount_label)}</span>
            <span class="lp-lifecycle-latest">{html_escape(latest_label)}</span>
          </{tag}>"""
        )
    return f"""        <section class="lp-lifecycle-summary" aria-label="출자 진행 현황">
          <div class="lp-lifecycle-title">
            <h2>출자 진행 현황</h2>
            <p>{html_escape(summary)}</p>
          </div>
          <div class="lp-lifecycle-table" role="table" aria-label="프로그램별 출자 진행 현황">
            <div class="lp-lifecycle-row is-head" role="row">
              <span>프로그램</span>
              <span>기록</span>
              <span>진행</span>
              <span>서류</span>
              <span>최종</span>
              <span>GP</span>
              <span>규모</span>
              <span>최근 공고</span>
            </div>
{chr(10).join(rendered_rows)}
          </div>
        </section>"""


def lp_notice_detail_slug(item: dict[str, object]) -> str:
    lp_code = re.sub(r"[^0-9a-zA-Z-]", "", str(item.get("lpCode") or "lp").lower()) or "lp"
    title_key = lp_notice_display_group_key(item)[1] or lp_notice_canonical_title(item) or str(item.get("noticeId") or "")
    digest = hashlib.sha1(f"{lp_code}|{title_key}".encode("utf-8")).hexdigest()[:12]
    return f"lp-notice-{lp_code}-{digest}.html"


def lp_notice_source_entries(item: dict[str, object]) -> list[dict[str, object]]:
    source_links = item.get("sourceLinks") if isinstance(item.get("sourceLinks"), list) else []
    if source_links:
        return [link for link in source_links if isinstance(link, dict)]
    return [
        {
            "sourceType": item.get("sourceType"),
            "url": item.get("url"),
            "documentUrl": item.get("documentUrl"),
            "attachments": item.get("attachments") or [],
        }
    ]


def lp_notice_primary_source_url(item: dict[str, object]) -> str:
    entries = lp_notice_source_entries(item)
    for preferred_type in ["official", "news", ""]:
        for entry in entries:
            source_type = str(entry.get("sourceType") or "").strip().lower()
            if preferred_type and source_type != preferred_type:
                continue
            url = str(entry.get("url") or entry.get("documentUrl") or "")
            if url:
                return url
    return str(item.get("url") or item.get("documentUrl") or "")


def lp_notice_preview_events(item: dict[str, object], limit: int = 3) -> str:
    events = [event for event in item.get("events") if isinstance(event, dict)] if isinstance(item.get("events"), list) else []
    if not events:
        return ""
    sorted_events = sorted(
        events,
        key=lambda event: str(event.get("eventDate") or event.get("latestEventDate") or ""),
        reverse=True,
    )
    items: list[str] = []
    for event in sorted_events[:limit]:
        event_title = clean_public_lp_text(event.get("title") or "")
        if not event_title:
            continue
        event_date = str(event.get("eventDate") or "")[:10]
        event_status = clean_public_lp_text(event.get("stageLabel") or lp_event_label(event.get("eventType")) or "공지")
        items.append(
            f"""            <li>
              <time>{html_escape(event_date)}</time>
              <strong>{html_escape(event_status)}</strong>
              <span>{html_escape(event_title)}</span>
            </li>"""
        )
    if not items:
        return ""
    return f"""
            <ol class="lp-notice-preview-timeline">
{chr(10).join(items)}
            </ol>"""


def render_lp_notice_card(item: dict[str, object], report_date: str) -> str:
    raw_title = clean_public_lp_text(item.get("title") or "공식 공고") or "공식 공고"
    display_title = clean_public_lp_text(item.get("displayTitle") or "") or raw_title
    source_url = lp_notice_primary_source_url(item)
    detail_url = str(item.get("detailUrl") or lp_notice_detail_slug(item))
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
    stage_badge_class = "lp-notice-status"
    if status == "result":
        stage_badge_class += " is-result"
    elif status == "shortlist":
        stage_badge_class += " is-shortlist"
    elif status == "open":
        stage_badge_class += " is-open"
    elif status == "cancellation":
        stage_badge_class += " is-cancel"
    else:
        stage_badge_class += " is-closed"
    amount, amount_numeric = lp_notice_amount_label(item)
    program_label = lp_notice_program_label(item)
    business_title = title if program_label == "-" else program_label
    platform_label = clean_public_lp_text(item.get("programPlatform") or "")
    asset_class = public_asset_class(item.get("assetClass")) if item.get("assetClass") else ""
    strategy = lp_notice_public_strategy_label(item)
    if platform_label and platform_label == strategy:
        platform_label = ""
    type_label = " · ".join(value for value in [asset_class, strategy] if value) or "-"
    selected_label = notice_gp_label(item.get("selectedGpNames"))
    has_gp = "1" if selected_label != "-" else "0"
    notice_year = str(event_date or item.get("eventDate") or item.get("announcedDate") or "")[:4]
    source_label = lp_notice_source_label(item)
    deadline_value = deadline or "-"
    deadline_detail = (
        f'<time datetime="{html_escape(deadline_value)}">{html_escape(deadline_value)}</time>'
        if deadline_value != "-"
        else "-"
    )
    event_date_label = event_date[:10] if event_date else ""
    fact_rows: list[str] = []
    for label, value in [
        ("마감일", deadline_detail if deadline_value != "-" else ""),
        ("출자규모", html_escape(amount) if amount != "-" else ""),
        ("자산/전략", html_escape(type_label) if type_label != "-" else ""),
        ("플랫폼", html_escape(platform_label) if platform_label else ""),
        ("선정 GP", html_escape(selected_label) if selected_label != "-" else ""),
    ]:
        if not value:
            continue
        fact_rows.append(
            f"""              <div>
                <dt>{html_escape(label)}</dt>
                <dd>{value}</dd>
              </div>"""
    )
    facts_html = "\n".join(fact_rows)
    events = [event for event in item.get("events", []) if isinstance(event, dict)] if isinstance(item.get("events"), list) else []
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
    stage = " ".join(
        str(event.get("title") or "")
        for event in events
        if isinstance(event, dict)
    )
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
{facts_html}
            </dl>
            {timeline_html}
          </article>"""


def prepare_lp_notice_display_items(notices: list[dict[str, object]], report_date: str | None = None) -> list[dict[str, object]]:
    items = consolidate_lp_notice_display_items(notices, report_date)
    prepared: list[dict[str, object]] = []
    for item in items:
        row = dict(item)
        row["detailUrl"] = lp_notice_detail_slug(row)
        prepared.append(row)
    return prepared


def render_lp_notice_detail_page(report_date: str, item: dict[str, object]) -> str:
    title = lp_notice_program_label(item)
    if title == "-":
        title = clean_public_lp_text(item.get("displayTitle") or item.get("title") or "출자사업")
    lp_name = clean_public_lp_text(item.get("lpName") or "LP 미분류") or "LP 미분류"
    status = lp_notice_public_status(item, report_date)
    status_label = clean_public_lp_text(item.get("businessStageLabel") or "") or lp_notice_status_label(status)
    deadline = lp_notice_effective_deadline_value(item)
    amount, _amount_numeric = lp_notice_amount_label(item)
    asset_class = public_asset_class(item.get("assetClass")) if item.get("assetClass") else ""
    strategy = lp_notice_public_strategy_label(item)
    platform = clean_public_lp_text(item.get("programPlatform") or "")
    selected_gp = notice_gp_label(item.get("selectedGpNames"))
    source_url = lp_notice_primary_source_url(item)
    fact_rows = [
        ("상태", status_label),
        ("출자기관", lp_name),
        ("마감일", korean_date_label(deadline) if deadline else "-"),
        ("출자규모", amount),
        ("자산/전략", " · ".join(value for value in [asset_class, strategy] if value) or "-"),
        ("플랫폼", platform or "-"),
        ("선정 GP", selected_gp),
    ]
    fact_html = "\n".join(
        f"""          <div>
            <dt>{html_escape(label)}</dt>
            <dd>{html_escape(value)}</dd>
          </div>"""
        for label, value in fact_rows
        if value and value != "-"
    )
    events = [event for event in item.get("events", []) if isinstance(event, dict)] if isinstance(item.get("events"), list) else []
    timeline_html = ""
    if events:
        timeline_items = []
        for event in events:
            event_title = clean_public_lp_text(event.get("title") or "")
            event_date_label = korean_date_label(str(event.get("eventDate") or "")[:10]) or "-"
            event_stage = clean_public_lp_text(event.get("stageLabel") or "") or lp_event_label(event.get("eventType"))
            timeline_items.append(
                f"""          <li>
            <time>{html_escape(event_date_label)}</time>
            <strong>{html_escape(event_stage)}</strong>
            <span>{html_escape(event_title)}</span>
          </li>"""
            )
        timeline_html = f"""
        <section class="lp-notice-detail-section">
          <h2>진행 이력</h2>
          <ol class="lp-notice-detail-timeline">
{chr(10).join(timeline_items)}
          </ol>
        </section>"""
    source_rows: list[str] = []
    used_urls: set[str] = set()
    for entry in lp_notice_source_entries(item):
        source_type = "기사" if str(entry.get("sourceType") or "").strip().lower() == "news" else "공식"
        for label, url in [("원문", entry.get("url")), ("첨부", entry.get("documentUrl"))]:
            link = str(url or "")
            if not link or link in used_urls:
                continue
            used_urls.add(link)
            source_rows.append(
                f"""          <a href="{html_escape(link)}" target="_blank" rel="noreferrer">
            <span>{html_escape(source_type)}</span>
            <strong>{html_escape(label)}</strong>
          </a>"""
            )
        for attachment in entry.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            link = str(attachment.get("url") or "")
            name = clean_public_lp_text(attachment.get("name") or "첨부")
            if not link or link in used_urls:
                continue
            used_urls.add(link)
            source_rows.append(
                f"""          <a href="{html_escape(link)}" target="_blank" rel="noreferrer">
            <span>{html_escape(source_type)}</span>
            <strong>{html_escape(name)}</strong>
          </a>"""
            )
    source_html = ""
    if source_rows:
        source_html = f"""
        <section class="lp-notice-detail-section">
          <h2>원문과 첨부</h2>
          <div class="lp-notice-detail-sources">
{chr(10).join(source_rows)}
          </div>
        </section>"""
    source_action = (
        f'<a class="lp-notice-detail-source-action" href="{html_escape(source_url)}" target="_blank" rel="noreferrer">원문 보기</a>'
        if source_url
        else ""
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{html_escape(title)} - LP 출자공고</title>
{app_head_meta()}
  <link rel="stylesheet" href="assets/service.css?v={app_asset_version()}">
  <style>
    body.lp-notice-detail-page {{ background: #ffffff; }}
    body.lp-notice-detail-page .app-shell {{ width: min(100%, 1120px); min-height: 100dvh; background: #ffffff; box-shadow: none; }}
    body.lp-notice-detail-page .content-area,
    body.lp-notice-detail-page .app-header {{ width: min(900px, calc(100% - 32px)); max-width: 900px; margin: 0 auto; }}
    body.lp-notice-detail-page .content-area {{ padding-bottom: calc(112px + env(safe-area-inset-bottom)); }}
    .lp-notice-detail-back {{ display: inline-flex; margin: 14px 0 18px; color: #4f555c; font-size: 13px; font-weight: 760; text-decoration: none; }}
    .lp-notice-detail-hero {{ display: grid; gap: 12px; margin: 0; padding: 0 0 20px; border-bottom: 1px solid #e5e5e5; }}
    .lp-notice-detail-hero h1 {{ margin: 0; color: #111214; font-size: 22px; font-weight: 820; line-height: 1.32; letter-spacing: 0; }}
    .lp-notice-detail-meta {{ display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; color: #70757d; font-size: 13px; font-weight: 650; line-height: 1.35; }}
    .lp-notice-detail-status {{ color: #111214; font-weight: 820; }}
    .lp-notice-detail-source-action {{ display: inline-flex; justify-self: start; min-height: 34px; align-items: center; border-radius: 8px; padding: 0 12px; background: #111214; color: #ffffff; font-size: 13px; font-weight: 780; text-decoration: none; }}
    .lp-notice-detail-section {{ margin: 0; border-bottom: 1px solid #e9eaec; background: #ffffff; padding: 20px 0; box-shadow: none; }}
    .lp-notice-detail-section:last-of-type {{ margin-bottom: calc(88px + env(safe-area-inset-bottom)); }}
    .lp-notice-detail-section h2 {{ margin: 0 0 14px; color: #111214; font-size: 16px; font-weight: 820; line-height: 1.35; }}
    .lp-notice-detail-facts {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 18px; margin: 0; }}
    .lp-notice-detail-facts div {{ display: grid; gap: 4px; min-width: 0; }}
    .lp-notice-detail-facts dt {{ color: #7a7f86; font-size: 12px; font-weight: 650; }}
    .lp-notice-detail-facts dd {{ margin: 0; color: #111214; font-size: 14px; font-weight: 760; line-height: 1.35; overflow-wrap: anywhere; }}
    .lp-notice-detail-timeline {{ display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }}
    .lp-notice-detail-timeline li {{ display: grid; grid-template-columns: 112px 78px minmax(0, 1fr); gap: 10px; padding: 11px 0; border-top: 1px solid #eceff2; color: #52575c; font-size: 13px; line-height: 1.42; }}
    .lp-notice-detail-timeline li:first-child {{ border-top: 0; }}
    .lp-notice-detail-timeline time {{ color: #7a7f86; font-weight: 650; }}
    .lp-notice-detail-timeline strong {{ color: #111214; font-weight: 780; }}
    .lp-notice-detail-timeline span {{ min-width: 0; overflow-wrap: anywhere; }}
    .lp-notice-detail-sources {{ display: grid; gap: 8px; }}
    .lp-notice-detail-sources a {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; min-height: 42px; border-radius: 8px; padding: 0 12px; background: #f7f8fa; color: #111214; text-decoration: none; }}
    .lp-notice-detail-sources span {{ color: #7a7f86; font-size: 12px; font-weight: 650; }}
    .lp-notice-detail-sources strong {{ flex: 1 1 auto; min-width: 0; color: #111214; font-size: 13px; font-weight: 760; overflow-wrap: anywhere; text-align: right; }}
    @media (max-width: 620px) {{
      body.lp-notice-detail-page .content-area,
      body.lp-notice-detail-page .app-header {{ width: 100%; max-width: none; }}
      .lp-notice-detail-back {{ margin: 12px 0 18px; }}
      .lp-notice-detail-hero {{ padding-bottom: 18px; }}
      .lp-notice-detail-hero h1 {{ font-size: 21px; line-height: 1.3; }}
      .lp-notice-detail-section {{ padding: 18px 0; }}
      .lp-notice-detail-facts {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 16px; }}
      .lp-notice-detail-timeline li {{ grid-template-columns: 82px 56px minmax(0, 1fr); gap: 7px; }}
      .lp-notice-detail-timeline time,
      .lp-notice-detail-timeline strong,
      .lp-notice-detail-timeline span {{ font-size: 12.5px; }}
      .lp-notice-detail-sources a {{ min-height: 40px; align-items: flex-start; padding-top: 10px; padding-bottom: 10px; }}
      .lp-notice-detail-sources span {{ flex: 0 0 auto; }}
    }}
  </style>
</head>
<body class="lp-notice-detail-page">
  <div class="app-shell newsletter-only">
    {render_lp_service_header("notice", "lpNoticeDetailSearch", "공고명, LP, GP 검색")}
    <main class="content-area">
      <a class="lp-notice-detail-back" href="lp-official-notices.html">출자공고로 돌아가기</a>
      <section class="lp-notice-detail-hero" aria-label="출자사업 요약">
        <div>
          <h1>{html_escape(title)}</h1>
          <div class="lp-notice-detail-meta">
            <span class="lp-notice-detail-status">{html_escape(status_label)}</span>
            <span>{html_escape(lp_name)}</span>
            <span>{html_escape(korean_date_label(report_date))} 기준</span>
          </div>
        </div>
        {source_action}
      </section>
      <section class="lp-notice-detail-section">
        <h2>기본 정보</h2>
        <dl class="lp-notice-detail-facts">
{fact_html}
        </dl>
      </section>
{timeline_html}
{source_html}
    </main>
    {render_service_bottom_nav("lp")}
  </div>
  <script>{lp_header_script()}</script>
</body>
</html>
"""


def write_lp_notice_detail_pages(site_dir: Path, report_date: str, notices: list[dict[str, object]]) -> None:
    for stale_path in site_dir.glob("lp-notice-*.html"):
        stale_path.unlink()
    for item in notices:
        detail_url = str(item.get("detailUrl") or lp_notice_detail_slug(item))
        (site_dir / detail_url).write_text(render_lp_notice_detail_page(report_date, item), encoding="utf-8")


def write_lp_notices_page(site_dir: Path, report_date: str) -> int:
    notices = read_lp_monitor(DEFAULT_LP_COMMITMENT_MONITOR, limit=None)
    nav_items = read_lp_profile_nav()
    directory_items = read_lp_directory_items()
    lifecycle_rows = read_lp_lifecycle_compare()
    notice_items = prepare_lp_notice_display_items(notices, report_date)
    (site_dir / "lp-notices.html").write_text(
        render_lp_notices_page(report_date, notices, nav_items, directory_items, active_tab="lp"),
        encoding="utf-8",
    )
    (site_dir / "lp-official-notices.html").write_text(
        render_lp_notices_page(
            report_date,
            notice_items,
            nav_items,
            directory_items,
            lifecycle_rows=lifecycle_rows,
            active_tab="notice",
            notices_preconsolidated=True,
        ),
        encoding="utf-8",
    )
    return len(notice_items)


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
    service_context = merge_service_context(service_context, read_review_queue_context(DEFAULT_EXPORT_DIR))
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
        if path.name not in lp_service_pages and not path.name.startswith("lp-notice-")
    )
    lp_notice_detail_paths = sorted(site_dir.glob("lp-notice-*.html"))
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
        *lp_notice_detail_paths,
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
    write_lp_notice_detail_pages(
        site_dir,
        args.date,
        prepare_lp_notice_display_items(read_lp_monitor(DEFAULT_LP_COMMITMENT_MONITOR, limit=None), args.date),
    )
    lp_service_pages = {"lp-notices.html", "lp-official-notices.html"}
    result["lp_profile_page_count"] = str(
        len(
            [
                path
                for path in site_dir.glob("lp-*.html")
                if path.name not in lp_service_pages and not path.name.startswith("lp-notice-")
            ]
        )
    )
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
