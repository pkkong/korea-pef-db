#!/usr/bin/env python
"""Build public GP directory pages for the newsletter static site."""

from __future__ import annotations

import html
import csv
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from services.shared.src.brand_assets import brand_logo_url, brand_style_attr, prepare_brand_asset_cache
from services.shared.src.daily_news_common import normalize_url


MARKET_REQUIRED_TABLES = ("v_period_summary", "source_document")
PROFILE_REQUIRED_TABLES = ("gp_profile", "gp_house")
NEWS_REQUIRED_TABLES = ("news_entity_link", "news_document")
TOP_GP_PAGE_LIMIT = 120
PROFILE_NEWS_LIMIT = 12
PROFILE_LP_SIGNAL_LIMIT = 8
PROFILE_DEAL_SIGNAL_LIMIT = 8
# Keep the first profile redesign isolated until its information hierarchy is
# approved. The standard name is stable across FSS ingestion runs.
PROFILE_UI_PREVIEW_STANDARD_GP_NAME = "엠비케이파트너스"
DEAL_TAG_HINTS = {
    "section:deal",
    "topic:deal",
    "topic:deal_watch",
    "section:portfolio",
    "topic:portfolio",
}
DEAL_KEYWORDS = (
    "m&a",
    "acquisition",
    "buyout",
    "exit",
    "stake",
    "인수",
    "매각",
    "엑시트",
    "우선협상",
    "블록딜",
    "경영권",
    "품으로",
    "사들",
    "지분 인수",
    "투자 유치",
    "회수",
    "딜",
)
APP_ICON_FILE = "apple-touch-icon.png"
REPO_ROOT = Path(__file__).resolve().parents[3]
FSS_SOURCE_REGISTRY = REPO_ROOT / "data" / "source_registry_fss_pef.csv"


def _app_head_meta() -> str:
    return f"""  <meta name="theme-color" content="#111827">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="KPEF Brief">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <link rel="apple-touch-icon" href="{APP_ICON_FILE}">
  <link rel="icon" type="image/png" href="{APP_ICON_FILE}">
  <link rel="manifest" href="site.webmanifest">"""


def write_gp_pages(site_dir: Path, db_path: Path, report_date: str) -> dict[str, int]:
    """Write market, GP directory, and top-GP profile pages into a static site directory."""
    site_dir.mkdir(parents=True, exist_ok=True)
    prepare_brand_asset_cache(site_dir)
    _remove_stale_gp_pages(site_dir)

    zero_counts = _zero_counts()
    if not db_path.exists():
        (site_dir / "market.html").write_text(
            _render_empty_market(report_date, "시장 통계가 준비되는 중입니다."),
            encoding="utf-8",
        )
        (site_dir / "gps.html").write_text(
            _render_empty_directory(report_date, "GP 공개 정보가 준비되는 중입니다."),
            encoding="utf-8",
        )
        return zero_counts

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        market_ready = _db_objects_exist(conn, MARKET_REQUIRED_TABLES)
        if market_ready:
            market_context = _read_market_context(conn)
            (site_dir / "market.html").write_text(
                _render_market_page(report_date, market_context),
                encoding="utf-8",
            )
        else:
            (site_dir / "market.html").write_text(
                _render_empty_market(report_date, "시장 통계가 준비되는 중입니다."),
                encoding="utf-8",
            )

        if not _db_objects_exist(conn, PROFILE_REQUIRED_TABLES):
            (site_dir / "gps.html").write_text(
                _render_empty_directory(report_date, "GP 공개 정보가 준비되는 중입니다."),
                encoding="utf-8",
            )
            return zero_counts

        gps = _read_gp_profiles(conn)
        if not gps:
            (site_dir / "gps.html").write_text(
                _render_empty_directory(report_date, "표시할 GP 프로필이 없습니다."),
                encoding="utf-8",
            )
            return zero_counts

        news_by_gp = _read_gp_news(conn) if _db_objects_exist(conn, NEWS_REQUIRED_TABLES) else {}
        funds_by_gp = _read_gp_funds(conn)
        lp_signals_by_gp = _read_lp_signals(conn)
        period_metrics_by_gp = _read_gp_period_metrics(conn)
        for gp in gps:
            gp_id = str(gp["source_gp_id"])
            gp["news"] = news_by_gp.get(gp_id, [])
            gp["news_count"] = len(gp["news"])
            gp["deal_news"] = [item for item in gp["news"] if _is_deal_news(item)]
            gp["deal_news_count"] = len(gp["deal_news"])
            gp["funds"] = funds_by_gp.get(gp_id, [])
            gp["active_fund_signal_count"] = len(gp["funds"])
            gp["lp_signals"] = lp_signals_by_gp.get(gp_id, [])
            gp["lp_signal_count"] = len(gp["lp_signals"])
            gp["period_metrics"] = period_metrics_by_gp.get(gp_id, {})

        ranked_gps = sorted(gps, key=_gp_sort_key)
        # FSS-only names can appear in the directory, but they do not receive a
        # profile page until source-backed profile facts exist.
        top_gps = [gp for gp in ranked_gps if _has_public_profile(gp)][:TOP_GP_PAGE_LIMIT]
        top_ids = {str(gp["source_gp_id"]) for gp in top_gps}
        for gp in gps:
            gp["profile_page"] = _gp_page_name(gp["source_gp_id"]) if str(gp["source_gp_id"]) in top_ids else ""

        (site_dir / "gps.html").write_text(
            _render_directory_page(report_date, ranked_gps, top_ids),
            encoding="utf-8",
        )
        for gp in top_gps:
            (site_dir / _gp_page_name(gp["source_gp_id"])).write_text(
                _render_gp_detail_page(report_date, gp, ranked_gps),
                encoding="utf-8",
            )

        return {
            "gp_count": len(gps),
            "active_gp_count": sum(1 for gp in gps if _as_bool(gp.get("active_in_latest_period"))),
            "top_gp_page_count": len(top_gps),
            "news_link_count": sum(int(gp.get("news_count") or 0) for gp in gps),
            "deal_signal_count": sum(int(gp.get("deal_news_count") or 0) for gp in gps),
            "lp_signal_count": sum(int(gp.get("lp_signal_count") or 0) for gp in gps),
        }
    finally:
        conn.close()


def _zero_counts() -> dict[str, int]:
    return {
        "gp_count": 0,
        "active_gp_count": 0,
        "top_gp_page_count": 0,
        "news_link_count": 0,
        "deal_signal_count": 0,
        "lp_signal_count": 0,
    }


def _remove_stale_gp_pages(site_dir: Path) -> None:
    for path in site_dir.glob("gp-*.html"):
        path.unlink()


def _db_object_exists(conn: sqlite3.Connection, name: str) -> bool:
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


def _db_objects_exist(conn: sqlite3.Connection, names: tuple[str, ...]) -> bool:
    return all(_db_object_exists(conn, name) for name in names)


def _has_public_profile(gp: dict[str, object]) -> bool:
    verification_level = _clean(gp.get("verification_level")).upper()
    if verification_level in {"", "FSS_NAME_ONLY"}:
        return False
    return bool(
        _clean(gp.get("primary_source_url"))
        or _clean(gp.get("homepage_url"))
        or _clean(gp.get("legal_entity_name_ko"))
    )


def _read_gp_profiles(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            p.source_gp_id,
            COALESCE(NULLIF(p.display_name_ko, ''), NULLIF(p.standard_gp_name, ''), h.gp_name) AS display_name,
            p.standard_gp_name,
            h.gp_name AS house_name,
            p.legal_entity_name_ko,
            p.legal_entity_name_en,
            p.homepage_url,
            p.established_date,
            p.representative_name,
            p.headquarters_address,
            p.license_type,
            p.license_status,
            p.profile_status,
            p.verification_level,
            p.primary_source_url,
            p.source_note,
            p.latest_period_label,
            p.latest_as_of_date,
            p.latest_primary_rank,
            p.latest_primary_active_fund_count,
            p.latest_primary_aum_proxy_krw_100mn,
            p.latest_primary_market_share_pct,
            p.cumulative_primary_rank,
            p.cumulative_primary_fund_count,
            p.cumulative_primary_commitment_proxy_krw_100mn,
            p.cumulative_primary_active_fund_count_latest,
            p.first_seen_period,
            p.first_seen_date,
            p.last_seen_period,
            p.last_seen_date,
            p.active_in_latest_period,
            p.alias_names,
            p.raw_name_variants,
            p.research_priority,
            p.research_priority_reason,
            p.research_note,
            p.source_basis,
            p.company_category,
            p.firm_founded_date,
            p.firm_founded_year,
            p.firm_description,
            p.phone_number,
            p.contact_email,
            h.first_seen_period_id AS house_first_seen_period,
            h.last_seen_period_id AS house_last_seen_period
        FROM gp_profile p
        LEFT JOIN gp_house h
          ON h.gp_id = p.source_gp_id
        WHERE p.source_gp_id IS NOT NULL
        ORDER BY
            CASE WHEN p.latest_primary_rank IS NULL THEN 1 ELSE 0 END,
            p.latest_primary_rank,
            CASE WHEN p.cumulative_primary_rank IS NULL THEN 1 ELSE 0 END,
            p.cumulative_primary_rank,
            display_name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _read_gp_news(conn: sqlite3.Connection) -> dict[str, list[dict[str, object]]]:
    tag_select = ", tags.tag_values" if _db_object_exists(conn, "news_tag") else ", '' AS tag_values"
    tag_join = (
        """
        LEFT JOIN (
            SELECT
                news_id,
                GROUP_CONCAT(tag_type || ':' || tag_value, ';') AS tag_values
            FROM news_tag
            GROUP BY news_id
        ) tags
          ON tags.news_id = nd.news_id
        """
        if _db_object_exists(conn, "news_tag")
        else ""
    )
    rows = conn.execute(
        f"""
        SELECT
            nel.entity_ref,
            nel.entity_name,
            nel.matched_alias,
            nel.link_source,
            nel.confidence,
            nd.news_id,
            nd.source_url,
            nd.source_domain,
            nd.publisher,
            nd.title,
            nd.published_at,
            nd.discovered_at,
            nd.excerpt_text,
            nd.relevance_score,
            nd.relevance_label,
            nd.review_status,
            nd.is_pe_relevant
            {tag_select}
        FROM news_entity_link nel
        JOIN news_document nd
          ON nd.news_id = nel.news_id
        {tag_join}
        WHERE nel.entity_type = 'GP'
          AND nel.entity_ref LIKE 'gp:%'
        ORDER BY
            COALESCE(nd.published_at, nd.discovered_at, '') DESC,
            nd.relevance_score DESC,
            nd.news_id DESC
        """
    ).fetchall()

    news_by_gp: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen_by_gp: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        gp_id = str(row["entity_ref"] or "").removeprefix("gp:")
        if not gp_id:
            continue
        dedupe_keys = _news_dedupe_keys(row)
        if any(key in seen_by_gp[gp_id] for key in dedupe_keys):
            continue
        seen_by_gp[gp_id].update(dedupe_keys)
        news_by_gp[gp_id].append(dict(row))
    return dict(news_by_gp)


def _read_gp_funds(conn: sqlite3.Connection) -> dict[str, list[dict[str, object]]]:
    if not _db_object_exists(conn, "fund_master"):
        return {}
    rows = conn.execute(
        """
        SELECT
            p.source_gp_id,
            fm.fund_id,
            fm.fund_name,
            fm.fund_type_master,
            fm.established_date,
            fm.lifecycle_status,
            fm.active_in_latest_period,
            fm.first_seen_period,
            fm.last_seen_period,
            fm.latest_commitment_trn_krw,
            fm.max_commitment_trn_krw,
            fm.latest_source_url,
            fm.latest_canonical_gp_names,
            fm.all_canonical_gp_names
        FROM gp_profile p
        JOIN fund_master fm
          ON (
            INSTR(
                ';' || REPLACE(REPLACE(COALESCE(fm.latest_canonical_gp_names, ''), '; ', ';'), ' ;', ';') || ';',
                ';' || p.standard_gp_name || ';'
            ) > 0
            OR INSTR(
                ';' || REPLACE(REPLACE(COALESCE(fm.all_canonical_gp_names, ''), '; ', ';'), ' ;', ';') || ';',
                ';' || p.standard_gp_name || ';'
            ) > 0
          )
        WHERE p.source_gp_id IS NOT NULL
        ORDER BY
            p.source_gp_id,
            COALESCE(fm.max_commitment_trn_krw, fm.latest_commitment_trn_krw, 0) DESC,
            fm.fund_name
        """
    ).fetchall()
    funds_by_gp: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen_by_gp: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        gp_id = str(row["source_gp_id"])
        fund_id = str(row["fund_id"])
        if fund_id in seen_by_gp[gp_id]:
            continue
        seen_by_gp[gp_id].add(fund_id)
        funds_by_gp[gp_id].append(dict(row))
    return dict(funds_by_gp)


def _read_lp_signals(conn: sqlite3.Connection) -> dict[str, list[dict[str, object]]]:
    required = ("lp_notice_gp_link", "lp_commitment_notice")
    if any(not _db_object_exists(conn, name) for name in required):
        return {}
    lp_name_select = "COALESCE(li.lp_name, l.lp_code, '') AS lp_name" if _db_object_exists(conn, "lp_institution") else "COALESCE(l.lp_code, '') AS lp_name"
    lp_join = "LEFT JOIN lp_institution li ON li.lp_code = n.lp_code" if _db_object_exists(conn, "lp_institution") else ""
    rows = conn.execute(
        f"""
        SELECT
            l.source_gp_id,
            l.gp_name,
            l.matched_alias,
            l.link_source,
            l.confidence AS link_confidence,
            n.notice_id,
            n.lp_code,
            {lp_name_select},
            n.source_type,
            n.event_type,
            n.event_date,
            n.announced_date,
            n.title,
            n.notice_url,
            n.asset_class,
            n.strategy,
            n.program_name,
            n.allocation_amount_krw_100mn,
            n.commitment_amount_krw_100mn,
            n.amount_confidence
        FROM lp_notice_gp_link l
        JOIN lp_commitment_notice n
          ON n.notice_id = l.notice_id
        {lp_join}
        WHERE COALESCE(n.public_visible, 1) = 1
        ORDER BY
            l.source_gp_id,
            COALESCE(n.event_date, n.announced_date, n.discovered_at, '') DESC,
            n.notice_id DESC
        """
    ).fetchall()
    signals_by_gp: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen_by_gp: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        gp_id = str(row["source_gp_id"])
        notice_id = str(row["notice_id"])
        if notice_id in seen_by_gp[gp_id]:
            continue
        seen_by_gp[gp_id].add(notice_id)
        signals_by_gp[gp_id].append(dict(row))
    return dict(signals_by_gp)


def _read_gp_period_metrics(conn: sqlite3.Connection) -> dict[str, dict[str, dict[str, object]]]:
    if not _db_object_exists(conn, "v_gp_period_commitment"):
        return {}
    rows = conn.execute(
        """
        SELECT
            gp_id,
            period_label,
            as_of_date,
            fund_count,
            ROUND(commitment_amount_krw_mn / 100.0, 2) AS commitment_krw_100mn
        FROM v_gp_period_commitment
        WHERE gp_id IS NOT NULL
          AND period_label IS NOT NULL
        ORDER BY as_of_date
        """
    ).fetchall()
    metrics: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        gp_id = str(row["gp_id"])
        period = _clean(row["period_label"])
        if not gp_id or not period:
            continue
        metrics[gp_id][period] = {
            "asOf": _short_date(row["as_of_date"]),
            "funds": int(_as_float(row["fund_count"])),
            "aum100mn": round(_as_float(row["commitment_krw_100mn"]), 2),
        }
    return dict(metrics)


def _read_market_context(conn: sqlite3.Connection) -> dict[str, object]:
    periods = [
        dict(row)
        for row in conn.execute(
            """
            SELECT
                period_label,
                as_of_date,
                regime,
                fund_count,
                primary_gp_count,
                commitment_amount_krw_mn,
                paid_in_amount_krw_mn
            FROM v_period_summary
            ORDER BY as_of_date
            """
        ).fetchall()
    ] if _db_object_exists(conn, "v_period_summary") else []
    latest = periods[-1] if periods else {}
    latest_period = _clean(latest.get("period_label")) if latest else ""
    safe_latest_period = re.sub(r"[^0-9A-Za-z_]+", "", latest_period)
    ranking_table = f"analytics_gp_ranking_{safe_latest_period}" if safe_latest_period else ""
    top_gps: list[dict[str, object]] = []
    if ranking_table and _db_object_exists(conn, ranking_table):
        top_gps = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT
                    rank,
                    gp_name,
                    active_fund_count,
                    commitment_aum_proxy_trn_krw,
                    market_share_pct
                FROM {ranking_table}
                ORDER BY rank
                LIMIT 20
                """
            ).fetchall()
        ]
    elif latest_period and _db_object_exists(conn, "v_gp_period_commitment"):
        rows = [
            dict(row)
            for row in conn.execute(
                """
                WITH gp_amount AS (
                    SELECT
                        gp_name,
                        fund_count AS active_fund_count,
                        commitment_amount_krw_mn,
                        SUM(commitment_amount_krw_mn) OVER () AS total_commitment
                    FROM v_gp_period_commitment
                    WHERE period_label = ?
                      AND gp_name IS NOT NULL
                )
                SELECT
                    ROW_NUMBER() OVER (ORDER BY commitment_amount_krw_mn DESC, gp_name) AS rank,
                    gp_name,
                    active_fund_count,
                    ROUND(commitment_amount_krw_mn / 1000000.0, 6) AS commitment_aum_proxy_trn_krw,
                    ROUND(commitment_amount_krw_mn / total_commitment * 100.0, 4) AS market_share_pct
                FROM gp_amount
                ORDER BY rank
                LIMIT 20
                """,
                (latest_period,),
            ).fetchall()
        ]
        top_gps = rows

    new_by_year = [
        dict(row)
        for row in conn.execute(
            """
            SELECT year, new_fund_count, first_seen_commitment_trn_krw
            FROM analytics_new_funds_by_year
            ORDER BY year DESC
            LIMIT 8
            """
        ).fetchall()
    ] if _db_object_exists(conn, "analytics_new_funds_by_year") else []
    new_by_quarter = [
        dict(row)
        for row in conn.execute(
            """
            SELECT established_quarter, new_fund_count, first_seen_commitment_trn_krw
            FROM analytics_new_funds_by_quarter
            ORDER BY established_quarter DESC
            LIMIT 8
            """
        ).fetchall()
    ] if _db_object_exists(conn, "analytics_new_funds_by_quarter") else []
    disappeared = [
        dict(row)
        for row in conn.execute(
            """
            SELECT
                absent_period,
                COUNT(*) AS fund_count,
                ROUND(SUM(commitment_amount_krw_mn) / 1000000.0, 6) AS commitment_trn_krw
            FROM v_fund_disappeared_next_period
            GROUP BY absent_period
            ORDER BY absent_period DESC
            LIMIT 6
            """
        ).fetchall()
    ] if _db_object_exists(conn, "v_fund_disappeared_next_period") else []
    sources = [
        dict(row)
        for row in conn.execute(
            """
            SELECT period_label, as_of_date, title, source_url
            FROM source_document
            WHERE document_type = 'quarterly_pef_status'
            ORDER BY as_of_date DESC
            LIMIT 6
            """
        ).fetchall()
    ] if _db_object_exists(conn, "source_document") else []

    prior_year = {}
    if latest:
        year = int(_as_float(str(latest_period)[:4])) if re.match(r"^\d{4}Q[1-4]$", latest_period) else 0
        quarter = latest_period[-2:] if re.match(r"^\d{4}Q[1-4]$", latest_period) else ""
        prior_label = f"{year - 1}{quarter}" if year and quarter else ""
        prior_year = next((row for row in periods if row.get("period_label") == prior_label), {})

    return {
        "periods": periods,
        "latest": latest,
        "prior_year": prior_year,
        "top_gps": top_gps,
        "new_by_year": new_by_year,
        "new_by_quarter": new_by_quarter,
        "disappeared": disappeared,
        "sources": sources,
        "top10_share": sum(_as_float(row.get("market_share_pct")) for row in top_gps[:10]),
        "top20_share": sum(_as_float(row.get("market_share_pct")) for row in top_gps[:20]),
    }


def _news_dedupe_keys(row: sqlite3.Row) -> list[str]:
    url = normalize_url(str(row["source_url"] or ""))
    title = re.sub(r"\s*\[[^\]]*(?:\]|$)", "", _clean(row["title"]))
    title = re.sub(r"\.{2,}|…+", "", title)
    title_key = re.sub(r"[^0-9A-Za-z가-힣]", "", title).lower()[:42]
    keys: list[str] = []
    if title_key:
        keys.append(f"title:{title_key}")
    if url and "news.google.com" not in url:
        keys.append(f"url:{url}")
    if not keys:
        keys.append(f"news:{row['news_id']}")
    return keys


def _is_deal_news(row: dict[str, object]) -> bool:
    tag_values = {tag.strip().lower() for tag in _clean(row.get("tag_values")).split(";") if tag.strip()}
    if tag_values & DEAL_TAG_HINTS:
        return True
    title = _clean(row.get("title")).lower()
    excerpt = _clean(row.get("excerpt_text")).lower()
    haystack = f"{title} {excerpt}"
    return any(keyword in haystack for keyword in DEAL_KEYWORDS)


def _render_empty_directory(report_date: str, message: str) -> str:
    empty_card = f"""      <article class="gp-card">
        <span class="gp-avatar gp-avatar-fallback" aria-hidden="true">GP</span>
        <div class="gp-card-main">
          <div class="gp-card-title">
            <h2>표시할 운용사가 없습니다</h2>
          </div>
          <p class="gp-empty-row-copy">기준일 {_e(report_date)}</p>
        </div>
        <dl class="gp-metrics">
          <div><dt>약정액</dt><dd>-</dd></div>
          <div><dt>펀드수</dt><dd>-</dd></div>
        </dl>
      </article>"""
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Korea PEF GP 디렉토리</title>
{_app_head_meta()}
  {_base_styles()}
</head>
<body>
  <main class="gp-shell">
    {_render_service_header("gp")}
    <header class="gp-hero">
      <div class="gp-hero-copy">
        <h1 class="gp-directory-title"><strong>0개</strong> <span>PEF 운용사</span></h1>
      </div>
    </header>

    <section class="gp-control-panel" aria-label="GP 필터">
      <div class="gp-controls">
        <label>
          <span>기준일</span>
          <select id="gpPeriod" aria-label="기준일">
            <option value="{_e(report_date)}" selected>{_e(_format_date_dot(report_date) or report_date)}</option>
          </select>
        </label>
        <label>
          <span>누적/운용중</span>
          <select id="gpScope" aria-label="복수 GP 반영 누적 또는 운용중">
            <option value="active" selected>운용중</option>
            <option value="cumulative">누적 (복수 GP 반영)</option>
          </select>
        </label>
        <label>
          <span>정렬기준</span>
          <select id="gpSort" aria-label="정렬기준">
            <option value="aum" selected>약정액 높은순</option>
            <option value="funds">펀드수 많은순</option>
            <option value="name">운용사명순</option>
          </select>
        </label>
        <label>
          <span>보기</span>
          <select id="gpPageSize" aria-label="페이지당 표시">
            <option value="30" selected>30개씩 보기</option>
            <option value="50">50개씩 보기</option>
            <option value="100">100개씩 보기</option>
            <option value="all">전체 보기</option>
          </select>
        </label>
      </div>
      <div class="gp-control-head">
        <span id="gpVisibleCount">0개 중 0</span>
      </div>
    </section>

    <section class="gp-directory-table" aria-label="GP 목록">
      <div class="gp-directory-head" aria-hidden="true">
        <span></span>
        <span>운용사명</span>
        <span>약정액</span>
        <span>펀드수</span>
      </div>
      <div class="gp-directory" id="gpDirectory">
{empty_card}
      </div>
    </section>
  </main>
  {_render_bottom_nav()}
  {_service_header_script(redirect_search=True)}
</body>
</html>
"""


def _render_empty_market(report_date: str, message: str) -> str:
    source = _latest_registry_source()
    latest = {
        "period_label": source.get("period_label") or "-",
        "as_of_date": source.get("as_of_date") or report_date,
    }
    context = {
        "latest": latest,
        "sources": [source] if source else [],
        "empty_message": message,
    }
    return _render_market_page(report_date, context)


def _latest_registry_source() -> dict[str, str]:
    if not FSS_SOURCE_REGISTRY.exists():
        return {}
    latest: dict[str, str] = {}
    with FSS_SOURCE_REGISTRY.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            period = _clean(row.get("period_label") or row.get("period"))
            if period and period >= _clean(latest.get("period_label")):
                latest = {key: _clean(value) for key, value in row.items()}
    return latest


def _bar_width(value: object, maximum: float) -> str:
    if maximum <= 0:
        return "0%"
    width = max(3.0, min(100.0, _as_float(value) / maximum * 100.0))
    return f"{width:.1f}%"


def _render_market_trend_chart(periods: list[dict[str, object]]) -> str:
    rows = periods[-8:]
    if not rows:
        return """      <div class="market-chart market-trend-chart" aria-label="출자약정액 추이">
        <div class="market-chart-empty">표시할 시장 추이가 없습니다.</div>
      </div>"""
    max_commitment = max(_as_float(row.get("commitment_amount_krw_mn")) for row in rows)
    bars = "\n".join(
        f"""          <div class="market-chart-bar">
            <span>{_e(row.get("period_label"))}</span>
            <i style="height:{_bar_width(row.get("commitment_amount_krw_mn"), max_commitment)}"></i>
            <strong>{_e(_format_trn_krw_as_100mn(_as_float(row.get("commitment_amount_krw_mn")) / 1000000))}</strong>
          </div>"""
        for row in rows
    )
    return f"""      <div class="market-chart market-trend-chart" aria-label="출자약정액 추이">
{bars}
      </div>"""


def _render_market_top_gp_bars(top_gps: list[dict[str, object]]) -> str:
    rows = top_gps[:8]
    if not rows:
        return """      <div class="market-chart market-rank-chart" aria-label="상위 GP 약정액">
        <div class="market-chart-empty">표시할 GP 순위가 없습니다.</div>
      </div>"""
    max_commitment = max(_as_float(row.get("commitment_aum_proxy_trn_krw")) for row in rows)
    bars = "\n".join(
        f"""          <div class="market-rank-bar">
            <span>{_e(row.get("gp_name"))}</span>
            <i><b style="width:{_bar_width(row.get("commitment_aum_proxy_trn_krw"), max_commitment)}"></b></i>
            <strong>{_e(_format_trn_krw_as_100mn(row.get("commitment_aum_proxy_trn_krw")))}</strong>
          </div>"""
        for row in rows
    )
    return f"""      <div class="market-chart market-rank-chart" aria-label="상위 GP 약정액">
{bars}
      </div>"""


def _render_market_page(report_date: str, context: dict[str, object]) -> str:
    latest = context.get("latest") if isinstance(context.get("latest"), dict) else {}
    prior_year = context.get("prior_year") if isinstance(context.get("prior_year"), dict) else {}
    periods = list(context.get("periods") or [])
    top_gps = list(context.get("top_gps") or [])
    new_by_year = list(context.get("new_by_year") or [])
    new_by_quarter = list(context.get("new_by_quarter") or [])
    disappeared = list(context.get("disappeared") or [])
    sources = list(context.get("sources") or [])
    latest_period = _clean(latest.get("period_label")) or "-"
    latest_date = _format_date_dot(latest.get("as_of_date")) or _e(report_date)
    period_rows = list(reversed(periods[-10:]))
    trend_chart_html = _render_market_trend_chart(periods)
    top_gp_chart_html = _render_market_top_gp_bars(top_gps)
    top10_share = _format_pct(context.get("top10_share"))
    top20_share = _format_pct(context.get("top20_share"))

    kpis = [
        ("펀드 수", _format_int(latest.get("fund_count")), _format_delta(latest.get("fund_count"), prior_year.get("fund_count"), "개")),
        ("운용 GP", _format_int(latest.get("primary_gp_count")), _format_delta(latest.get("primary_gp_count"), prior_year.get("primary_gp_count"), "개")),
        ("출자약정액", _format_trn_krw_as_100mn(_as_float(latest.get("commitment_amount_krw_mn")) / 1000000), _format_delta_trn(latest.get("commitment_amount_krw_mn"), prior_year.get("commitment_amount_krw_mn"))),
        ("상위 10개 비중", top10_share, f"상위 20개 {top20_share}" if top20_share != "-" else ""),
    ]
    kpi_html = "\n".join(
        f"""        <div>
          <span>{_e(label)}</span>
          <strong>{_e(value)}</strong>
          {f'<em>{_e(delta)}</em>' if delta else ''}
        </div>"""
        for label, value, delta in kpis
    )
    period_html = "\n".join(
        f"""          <div class="market-row market-period-row">
            <span>{_e(row.get("period_label"))}</span>
            <span>{_e(_format_int(row.get("fund_count")))}</span>
            <span>{_e(_format_int(row.get("primary_gp_count")))}</span>
            <span>{_e(_format_trn_krw_as_100mn(_as_float(row.get("commitment_amount_krw_mn")) / 1000000))}</span>
          </div>"""
        for row in period_rows
    ) or _empty_table_row("표시할 시장 추이가 없습니다.")
    top_gp_html = "\n".join(
        f"""          <div class="market-row market-gp-row">
            <span>{_e(row.get("rank"))}</span>
            <strong>{_e(row.get("gp_name"))}</strong>
            <span>{_e(_format_trn_krw_as_100mn(row.get("commitment_aum_proxy_trn_krw")))}</span>
            <span>{_e(_format_int(row.get("active_fund_count")))}</span>
          </div>"""
        for row in top_gps[:10]
    ) or _empty_table_row("표시할 GP 순위가 없습니다.")
    new_year_html = "\n".join(
        f"""          <div class="market-row market-new-row">
            <span>{_e(row.get("year"))}</span>
            <span>{_e(_format_int(row.get("new_fund_count")))}</span>
            <span>{_e(_format_trn_krw_as_100mn(row.get("first_seen_commitment_trn_krw")))}</span>
          </div>"""
        for row in new_by_year
    ) or _empty_table_row("표시할 신규 결성 이력이 없습니다.")
    new_quarter_html = "\n".join(
        f"""          <div class="market-row market-new-row">
            <span>{_e(row.get("established_quarter"))}</span>
            <span>{_e(_format_int(row.get("new_fund_count")))}</span>
            <span>{_e(_format_trn_krw_as_100mn(row.get("first_seen_commitment_trn_krw")))}</span>
          </div>"""
        for row in new_by_quarter
    ) or _empty_table_row("표시할 분기별 결성 이력이 없습니다.")
    disappeared_html = "\n".join(
        f"""          <div class="market-row market-new-row">
            <span>{_e(row.get("absent_period"))}</span>
            <span>{_e(_format_int(row.get("fund_count")))}</span>
            <span>{_e(_format_trn_krw_as_100mn(row.get("commitment_trn_krw")))}</span>
          </div>"""
        for row in disappeared
    ) or _empty_table_row("표시할 이탈 추정 이력이 없습니다.")
    source_html = "\n".join(
        f"""          <li>
            <a href="{_e(row.get("source_url"))}" target="_blank" rel="noreferrer">{_e(row.get("period_label"))}</a>
            <span>{_e(_format_date_dot(row.get("as_of_date")))}</span>
          </li>"""
        for row in sources
    ) or "          <li><span>기준 자료 없음</span></li>"
    metric_note_html = f"""      <p class="market-metric-note">
        운용 GP는 {_e(latest_period)} 기준 각 펀드의 대표 운용사 집계입니다.
        프로필/제휴 기준의 전체 GP 수와 다를 수 있습니다.
      </p>"""

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Korea PEF Market</title>
{_app_head_meta()}
  {_base_styles()}
</head>
<body>
  <main class="gp-shell">
    {_render_service_header("market")}
    <header class="gp-hero market-hero">
      <div class="gp-hero-copy">
        <h1>Overview</h1>
        <p>{_e(latest_period)} · {latest_date} 기준</p>
      </div>
    </header>

    <section class="market-section market-overview-section" aria-label="Overview">
      <div class="market-kpis">
{kpi_html}
      </div>
{metric_note_html}
    </section>

    <section class="market-section" aria-label="분기별 시장 추이">
      <div class="market-section-head">
        <h2>분기별 시장 추이</h2>
      </div>
{trend_chart_html}
      <div class="market-table">
        <div class="market-head market-period-row"><span>기준</span><span>펀드</span><span>GP</span><span>약정액</span></div>
{period_html}
      </div>
    </section>

    <section class="market-section" aria-label="상위 GP">
      <div class="market-section-head">
        <h2>상위 GP</h2>
      </div>
{top_gp_chart_html}
      <div class="market-table">
        <div class="market-head market-gp-row"><span>순위</span><span>운용사</span><span>약정액</span><span>펀드</span></div>
{top_gp_html}
      </div>
    </section>

    <section class="market-section" aria-label="연도별 신규 펀드">
        <div class="market-section-head">
          <h2>연도별 신규 펀드</h2>
        </div>
        <div class="market-table">
          <div class="market-head market-new-row"><span>연도</span><span>펀드</span><span>약정액</span></div>
{new_year_html}
        </div>
    </section>
    <section class="market-section" aria-label="분기별 신규 펀드">
        <div class="market-section-head">
          <h2>분기별 신규 펀드</h2>
        </div>
        <div class="market-table">
          <div class="market-head market-new-row"><span>분기</span><span>펀드</span><span>약정액</span></div>
{new_quarter_html}
        </div>
    </section>

    <section class="market-section" aria-label="펀드 이탈 추정">
      <div class="market-section-head">
        <h2>다음 분기 미등장 펀드</h2>
        <p>분기 자료 비교 기준이며 청산 확정을 의미하지 않습니다.</p>
      </div>
      <div class="market-table">
        <div class="market-head market-new-row"><span>미등장 분기</span><span>펀드</span><span>약정액</span></div>
{disappeared_html}
      </div>
    </section>

    <section class="market-section market-source-note" aria-label="기준 자료">
      <strong>기준 자료</strong>
      <ul>
{source_html}
      </ul>
    </section>
  </main>
  {_render_bottom_nav()}
  {_service_header_script(redirect_search=True)}
</body>
</html>
"""


def _render_directory_page(report_date: str, gps: list[dict[str, object]], top_ids: set[str]) -> str:
    cards = "\n".join(_render_gp_card(gp, str(gp["source_gp_id"]) in top_ids) for gp in gps)
    latest_date = _latest_gp_as_of_date(gps) or report_date
    period_options = _gp_period_options(gps)
    period_options_html = "\n".join(
        f'            <option value="{_e(period)}"{ " selected" if index == 0 else ""}>{_e(period)} · {_e(_format_date_dot(as_of))}</option>'
        for index, (period, as_of) in enumerate(period_options)
    ) or f'            <option value="{_e(_clean(gps[0].get("latest_period_label")) if gps else "")}" selected>{_e(_format_date_dot(latest_date) or latest_date)}</option>'

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Korea PEF GP 디렉토리</title>
{_app_head_meta()}
  {_base_styles()}
</head>
<body>
  <main class="gp-shell">
    {_render_service_header("gp")}
    <header class="gp-hero">
      <div class="gp-hero-copy">
        <h1 class="gp-directory-title"><strong>{len(gps):,}개</strong> <span>PEF 운용사</span></h1>
      </div>
    </header>

    <section class="gp-control-panel" aria-label="GP 필터">
      <div class="gp-controls">
        <label>
          <span>기준일</span>
          <select id="gpPeriod" aria-label="기준일">
{period_options_html}
          </select>
        </label>
        <label>
          <span>누적/운용중</span>
          <select id="gpScope" aria-label="복수 GP 반영 누적 또는 운용중">
            <option value="active" selected>운용중</option>
            <option value="cumulative">누적 (복수 GP 반영)</option>
          </select>
        </label>
        <label>
          <span>정렬기준</span>
          <select id="gpSort" aria-label="정렬기준">
            <option value="aum" selected>약정액 높은순</option>
            <option value="funds">펀드수 많은순</option>
            <option value="name">운용사명순</option>
          </select>
        </label>
        <label>
          <span>보기</span>
          <select id="gpPageSize" aria-label="페이지당 표시">
            <option value="30" selected>30개씩 보기</option>
            <option value="50">50개씩 보기</option>
            <option value="100">100개씩 보기</option>
            <option value="all">전체 보기</option>
          </select>
        </label>
      </div>
      <div class="gp-control-head">
        <span id="gpVisibleCount">{len(gps):,}개 중 1-30</span>
      </div>
    </section>

    <section class="gp-directory-table" aria-label="GP 목록">
      <div class="gp-directory-head" aria-hidden="true">
        <span></span>
        <span>운용사명</span>
        <span>약정액</span>
        <span>펀드수</span>
      </div>
      <div class="gp-directory" id="gpDirectory">
{cards}
      </div>
    </section>
    <div class="gp-pagination" id="gpPagination" aria-label="GP 목록 페이지 이동">
      <button type="button" id="gpPrevPage">이전</button>
      <span id="gpPageState">1 / 1</span>
      <button type="button" id="gpNextPage">다음</button>
    </div>
  </main>
  {_render_bottom_nav()}
  {_directory_script()}
  {_service_header_script()}
</body>
</html>
"""


def _render_gp_card(gp: dict[str, object], has_profile_page: bool) -> str:
    gp_id = str(gp["source_gp_id"])
    name = _gp_name(gp)
    avatar_label = _avatar_label(name)
    active_funds = _format_int(gp.get("latest_primary_active_fund_count"))
    aum = _format_krw_100mn(gp.get("latest_primary_aum_proxy_krw_100mn"))
    representative = _clean(gp.get("representative_name"))
    homepage = _safe_url(gp.get("homepage_url"))
    avatar_markup = _avatar_markup(homepage, avatar_label, name, name)
    profile_url = _gp_page_name(gp_id) if has_profile_page else ""
    title = (
        f'<a href="{_e(profile_url)}">{_e(name)}</a>'
        if profile_url
        else _e(name)
    )
    search_blob = " ".join(
        [
            name,
            _clean(gp.get("standard_gp_name")),
            _clean(gp.get("house_name")),
            _clean(gp.get("legal_entity_name_ko")),
            representative,
            _clean(gp.get("alias_names")),
            " ".join(_clean(item.get("lp_name")) for item in gp.get("lp_signals", [])[:3]),
            " ".join(_clean(item.get("fund_name")) for item in gp.get("funds", [])[:5]),
        ]
    )
    rank_sort = _sort_number(gp.get("latest_primary_rank"), default=999999)
    aum_sort = _sort_number(gp.get("latest_primary_aum_proxy_krw_100mn"), default=0)
    active_sort = _sort_number(gp.get("latest_primary_active_fund_count"), default=0)
    cumulative_aum = _format_krw_100mn(gp.get("cumulative_primary_commitment_proxy_krw_100mn"))
    cumulative_funds = _format_int(gp.get("cumulative_primary_fund_count"))
    cumulative_aum_sort = _sort_number(gp.get("cumulative_primary_commitment_proxy_krw_100mn"), default=0)
    cumulative_fund_sort = _sort_number(gp.get("cumulative_primary_fund_count"), default=0)
    period_metrics = gp.get("period_metrics") if isinstance(gp.get("period_metrics"), dict) else {}
    period_metrics_json = html.escape(
        json.dumps(period_metrics, ensure_ascii=False, separators=(",", ":")),
        quote=True,
    )

    return f"""      <article class="gp-card"
        data-url="{_e(profile_url)}"
        data-profile="{'detail' if profile_url else 'fss-name-only'}"
        data-search="{_e(search_blob)}"
        data-active="{1 if _as_bool(gp.get("active_in_latest_period")) else 0}"
        data-rank="{rank_sort}"
        data-aum="{aum_sort}"
        data-funds="{active_sort}"
        data-cumulative-aum="{cumulative_aum_sort}"
        data-cumulative-funds="{cumulative_fund_sort}"
        data-cumulative-aum-label="{_e(cumulative_aum)}"
        data-cumulative-funds-label="{_e(cumulative_funds)}"
        data-period-metrics="{period_metrics_json}"
        data-name="{_e(name)}">
        {avatar_markup}
        <div class="gp-card-main">
          <div class="gp-card-title">
            <h2>{title}</h2>
          </div>
        </div>
        <dl class="gp-metrics">
          <div><dt>약정액</dt><dd data-gp-aum>{_e(aum)}</dd></div>
          <div><dt>펀드수</dt><dd data-gp-funds>{_e(active_funds)}</dd></div>
        </dl>
      </article>"""


def _render_gp_detail_page(report_date: str, gp: dict[str, object], ranked_gps: list[dict[str, object]]) -> str:
    if _uses_profile_ui_preview(gp):
        return _render_gp_profile_preview_page(report_date, gp)

    name = _gp_name(gp)
    homepage = _safe_url(gp.get("homepage_url"))
    logo_url = _brand_logo_url(homepage, name)
    avatar_label = _avatar_label(name)
    avatar_tone = _identity_tone(name)
    avatar_class = "gp-detail-logo has-logo" if logo_url else "gp-detail-logo"
    avatar_style = _brand_logo_style_attr(homepage, name) if logo_url else ""
    avatar_logo = (
        f'<img src="{logo_url}" alt="" loading="lazy" onerror="this.parentElement.classList.add(\'fallback-only\'); this.remove()">'
        if logo_url
        else ""
    )
    homepage_link = (
        f'<a href="{_e(homepage)}" target="_blank" rel="noreferrer">{_e(_homepage_label(homepage))}</a>'
        if homepage
        else ""
    )
    representative = _clean(gp.get("representative_name"))
    representative_html = f"<span>대표 {_e(representative)}</span>" if representative else ""
    category = _category_label(gp.get("company_category"))
    category_html = f"<span>{_e(category)}</span>" if category else ""
    description = _profile_summary(gp)
    description_html = f"        <p>{_e(description)}</p>" if description else ""
    deal_items = list(gp.get("deal_news", [])[:PROFILE_DEAL_SIGNAL_LIMIT])
    deal_urls = {_safe_url(item.get("source_url")) for item in deal_items if _safe_url(item.get("source_url"))}
    news_items = [
        item
        for item in gp.get("news", [])
        if not _safe_url(item.get("source_url")) or _safe_url(item.get("source_url")) not in deal_urls
    ][:PROFILE_NEWS_LIMIT]
    news_rows = _render_news_timeline(news_items)
    deal_rows = _render_news_timeline(deal_items, empty_label="딜 관련 뉴스가 없습니다.")
    fund_rows = _render_fund_rows(list(gp.get("funds", [])))
    fund_count = len(gp.get("funds", []))
    lp_signal_rows = _render_lp_signal_rows(gp.get("lp_signals", [])[:PROFILE_LP_SIGNAL_LIMIT])
    peer_rows = _render_peer_links(gp, ranked_gps)
    profile_rows = _render_profile_facts(gp, homepage_link)
    coverage_rows = _render_coverage_facts(gp)
    signal_bar = _render_signal_bar(gp)
    alias_list = _render_aliases(gp.get("alias_names") or gp.get("raw_name_variants"))

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{_e(name)} - PEF 운용사</title>
{_app_head_meta()}
  {_base_styles()}
</head>
<body>
  <main class="gp-shell">
    {_render_service_header("gp")}
    <nav class="gp-breadcrumb" aria-label="경로">
      <a href="gps.html">GP</a>
      <span>{_e(name)}</span>
    </nav>

    <header class="gp-detail-hero">
      <div class="gp-detail-title-head">
        <span class="{avatar_class}" data-tone="{avatar_tone}" aria-hidden="true"{avatar_style}>{avatar_logo}<span>{_e(avatar_label)}</span></span>
        <div>
          <span>운용사</span>
          <h1>{_e(name)}</h1>
        </div>
{description_html}
      </div>
      <aside class="gp-detail-card" aria-label="핵심 정보">
        {category_html}
        {representative_html}
        {homepage_link}
      </aside>
    </header>

    <section class="gp-detail-kpis" aria-label="운용 현황">
      <div><span>최신 순위</span><strong>{_e(_format_rank(gp.get("latest_primary_rank")))}</strong></div>
      <div><span>운용중 펀드</span><strong>{_e(_format_int(gp.get("latest_primary_active_fund_count")))}</strong></div>
      <div><span>약정액 기준</span><strong>{_e(_format_krw_100mn(gp.get("latest_primary_aum_proxy_krw_100mn")))}</strong></div>
      <div><span>약정액 점유율</span><strong>{_e(_format_pct(gp.get("latest_primary_market_share_pct")))}</strong></div>
    </section>

    {signal_bar}

    <section class="gp-detail-grid">
      <article class="gp-panel">
        <h2>회사 개요</h2>
        <dl class="gp-fact-list">
{profile_rows}
        </dl>
      </article>
      <article class="gp-panel">
        <h2>운용 정보</h2>
        <dl class="gp-fact-list">
{coverage_rows}
        </dl>
      </article>
    </section>

    <section class="gp-detail-grid gp-detail-lower">
      <article class="gp-panel">
        <div class="gp-panel-heading">
          <h2>금감원 확인 펀드</h2>
          <span>{fund_count:,}개</span>
        </div>
        {fund_rows}
      </article>
      <article class="gp-panel">
        <h2>출자 연결</h2>
        {lp_signal_rows}
      </article>
    </section>

    <section class="gp-detail-grid gp-detail-lower">
      <article class="gp-panel">
        <h2>관련 딜</h2>
        {deal_rows}
      </article>
      <article class="gp-panel">
        <h2>관련 뉴스</h2>
        {news_rows}
      </article>
    </section>

    <section class="gp-detail-grid gp-detail-lower">
      <article class="gp-panel">
        <h2>비교 GP</h2>
        {peer_rows}
      </article>
      <article class="gp-panel">
        <h2>명칭 정보</h2>
        <div class="gp-alias-box">
          <strong>함께 쓰이는 명칭</strong>
          {alias_list}
        </div>
      </article>
    </section>

    <section class="gp-disclaimer" aria-label="참고사항">
      <h2>참고사항</h2>
      <p>{_e(_detail_limit_note(gp))}</p>
    </section>
  </main>
  {_render_bottom_nav()}
  {_service_header_script(redirect_search=True)}
</body>
</html>
"""


def _uses_profile_ui_preview(gp: dict[str, object]) -> bool:
    return _clean(gp.get("standard_gp_name")) == PROFILE_UI_PREVIEW_STANDARD_GP_NAME


def _render_gp_profile_preview_page(report_date: str, gp: dict[str, object]) -> str:
    """Render the approved-candidate profile layout for one GP only."""
    name = _gp_name(gp)
    homepage = _safe_url(gp.get("homepage_url"))
    logo_url = _brand_logo_url(homepage, name)
    avatar_label = _avatar_label(name)
    avatar_style = _brand_logo_style_attr(homepage, name) if logo_url else ""
    avatar_logo = (
        f'<img src="{logo_url}" alt="" loading="lazy" onerror="this.parentElement.classList.add(\'fallback-only\'); this.remove()">'
        if logo_url
        else ""
    )
    funds = list(gp.get("funds", []))
    active_fund_count = sum(1 for fund in funds if _as_bool(fund.get("active_in_latest_period")))
    historical_fund_count = len(funds) - active_fund_count
    reporting_period = _clean(gp.get("latest_period_label") or gp.get("last_seen_period") or report_date)
    period_label = _format_period_label(reporting_period)
    company_rows = _render_profile_preview_company_rows(gp, homepage)
    fund_rows = _render_profile_preview_fund_rows(funds)
    source_note = f"금감원 PEF 운용현황 {period_label} 기준"

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{_e(name)} - PEF 운용사</title>
{_app_head_meta()}
  {_reporting_period_meta(reporting_period)}
  {_base_styles()}
</head>
<body>
  <main class="gp-shell gp-profile-preview">
    {_render_service_header("gp")}
    <nav class="gp-profile-preview-back" aria-label="경로">
      <a href="gps.html">GP 목록</a>
    </nav>

    <header class="gp-profile-preview-hero">
      <span class="gp-detail-logo gp-profile-preview-logo{' has-logo' if logo_url else ''}" aria-hidden="true"{avatar_style}>{avatar_logo}<span>{_e(avatar_label)}</span></span>
      <div>
        <span class="gp-profile-preview-kicker">PEF 운용사</span>
        <h1>{_e(name)}</h1>
        <p>{_e(period_label)} 운용 현황</p>
      </div>
    </header>

    <section class="gp-profile-preview-metrics" aria-label="핵심 통계">
      <dl>
        <div>
          <dt>최신 약정액</dt>
          <dd>{_e(_format_krw_100mn(gp.get("latest_primary_aum_proxy_krw_100mn")))}</dd>
          <span>{_e(period_label)}</span>
        </div>
        <div>
          <dt>누적 약정액</dt>
          <dd>{_e(_format_krw_100mn(gp.get("cumulative_primary_commitment_proxy_krw_100mn")))}</dd>
          <span>펀드 이력 기준</span>
        </div>
        <div>
          <dt>연결 펀드</dt>
          <dd>{len(funds):,}개</dd>
          <span>금감원 확인 이력</span>
        </div>
        <div>
          <dt>최신 순위</dt>
          <dd>{_e(_format_rank(gp.get("latest_primary_rank")))}</dd>
          <span>{_e(period_label)} 약정액 기준</span>
        </div>
      </dl>
    </section>

    <section class="gp-profile-preview-section" aria-labelledby="gpCompanyInfo">
      <div class="gp-profile-preview-section-head">
        <h2 id="gpCompanyInfo">회사 정보</h2>
      </div>
      <dl class="gp-profile-preview-info-list">
{company_rows}
      </dl>
    </section>

    <section class="gp-profile-preview-section gp-profile-preview-funds" aria-labelledby="gpFundHistory">
      <div class="gp-profile-preview-section-head gp-profile-preview-fund-head">
        <div>
          <h2 id="gpFundHistory">금감원 확인 펀드</h2>
          <p>공동 운용 펀드는 각 GP에 함께 표시합니다.</p>
        </div>
        <strong>{len(funds):,}개</strong>
      </div>
      <div class="gp-profile-preview-filter" role="group" aria-label="펀드 상태">
        <button class="active" type="button" data-fund-filter="all" aria-pressed="true">전체 {len(funds):,}</button>
        <button type="button" data-fund-filter="active" aria-pressed="false">운용중 {active_fund_count:,}</button>
        <button type="button" data-fund-filter="historical" aria-pressed="false">청산완료 {historical_fund_count:,}</button>
      </div>
      <div class="gp-profile-preview-fund-list">
{fund_rows}
      </div>
      <p class="gp-profile-preview-empty" id="gpFundEmpty" hidden>해당 상태의 펀드가 없습니다.</p>
    </section>

    <footer class="gp-profile-preview-source">
      <p>{source_note}</p>
    </footer>
  </main>
  {_render_bottom_nav()}
  {_service_header_script(redirect_search=True)}
  {_profile_preview_script()}
</body>
</html>
"""


def _render_profile_preview_company_rows(gp: dict[str, object], homepage: str) -> str:
    homepage_link = (
        f'<a href="{_e(homepage)}" target="_blank" rel="noreferrer">{_e(_homepage_label(homepage))}</a>'
        if homepage
        else ""
    )
    facts = [
        ("법인명", _clean(gp.get("legal_entity_name_ko")) or _clean(gp.get("legal_entity_name_en"))),
        ("대표", _clean(gp.get("representative_name"))),
        ("설립", _clean(gp.get("firm_founded_year")) or _clean(gp.get("firm_founded_date")) or _clean(gp.get("established_date"))),
        ("홈페이지", homepage_link, True),
    ]
    rows = []
    for label, value, *raw_value in facts:
        if not _clean(value):
            continue
        raw = bool(raw_value and raw_value[0])
        body = str(value) if raw else _e(str(value))
        rows.append(
            f"""        <div class="gp-profile-preview-info-row">
          <dt>{_e(label)}</dt>
          <dd>{body}</dd>
        </div>"""
        )
    return "\n".join(rows) or "        <div class=\"gp-profile-preview-info-row\"><dt>회사 정보</dt><dd>-</dd></div>"


def _render_profile_preview_fund_rows(fund_rows: list[dict[str, object]]) -> str:
    if not fund_rows:
        return '<p class="gp-empty-note">금감원 공개 자료에서 연결된 펀드가 확인되지 않았습니다.</p>'
    rows = []
    for fund in fund_rows:
        name = _clean(fund.get("fund_name")) or "펀드"
        url = _safe_url(fund.get("latest_source_url"))
        title = f'<a href="{_e(url)}" target="_blank" rel="noreferrer">{_e(name)}</a>' if url else _e(name)
        active = _as_bool(fund.get("active_in_latest_period"))
        state = "active" if active else "historical"
        state_label = "운용중" if active else "청산완료"
        amount = _format_trn_krw_as_100mn(
            fund.get("max_commitment_trn_krw") or fund.get("latest_commitment_trn_krw")
        )
        established = _short_date(fund.get("established_date"))
        last_seen = _format_period_label(fund.get("last_seen_period"))
        meta = _join_values(
            [
                f"설정 {established}" if established else "설정일 미확인",
                f"최근 확인 {last_seen}" if last_seen else "",
            ]
        )
        rows.append(
            f"""        <article class="gp-profile-preview-fund-row" data-fund-state="{state}">
          <div class="gp-profile-preview-fund-copy">
            <h3>{title}</h3>
            <p>{_e(meta or "금감원 공개 운용 현황 기준")}</p>
          </div>
          <div class="gp-profile-preview-fund-amount">
            <span class="gp-profile-preview-fund-state {state}">{state_label}</span>
            <strong>{_e(amount)}</strong>
          </div>
        </article>"""
        )
    return "\n".join(rows)


def _profile_preview_script() -> str:
    return """  <script>
    (() => {
      const buttons = Array.from(document.querySelectorAll("[data-fund-filter]"));
      const rows = Array.from(document.querySelectorAll("[data-fund-state]"));
      const empty = document.getElementById("gpFundEmpty");
      const apply = (filter) => {
        let visible = 0;
        rows.forEach((row) => {
          const show = filter === "all" || row.dataset.fundState === filter;
          row.hidden = !show;
          if (show) visible += 1;
        });
        buttons.forEach((button) => {
          const active = button.dataset.fundFilter === filter;
          button.classList.toggle("active", active);
          button.setAttribute("aria-pressed", String(active));
        });
        if (empty) empty.hidden = visible > 0;
      };
      buttons.forEach((button) => button.addEventListener("click", () => apply(button.dataset.fundFilter || "all")));
    })();
  </script>"""


def _render_profile_facts(gp: dict[str, object], homepage_link: str) -> str:
    facts = [
        ("운용사명", _gp_name(gp)),
        ("법인명", _clean(gp.get("legal_entity_name_ko")) or _clean(gp.get("legal_entity_name_en"))),
        ("대표", _clean(gp.get("representative_name"))),
        ("홈페이지", homepage_link, True),
        ("설립", _clean(gp.get("firm_founded_year")) or _clean(gp.get("firm_founded_date")) or _clean(gp.get("established_date"))),
        ("본점/주소", _clean(gp.get("headquarters_address"))),
        ("인허가", _join_values([_public_code_label(gp.get("license_type")), _public_code_label(gp.get("license_status"))])),
        ("최근 기준 기간", _clean(gp.get("latest_period_label")) or _clean(gp.get("house_last_seen_period"))),
    ]
    rows = []
    for item in facts:
        label, value = item[:2]
        raw = bool(item[2]) if len(item) > 2 else False
        if not _clean(value):
            continue
        rows.append(_fact_row(label, value, raw=raw))
    return "\n".join(rows)


def _render_coverage_facts(gp: dict[str, object]) -> str:
    market_share = _format_pct(gp.get("latest_primary_market_share_pct"))
    facts = [
        ("최신 순위", _format_rank(gp.get("latest_primary_rank"))),
        ("누적 순위 (복수 GP 반영)", _format_rank(gp.get("cumulative_primary_rank"))),
        ("약정액 점유율", market_share),
        ("최초 확인 기간", _clean(gp.get("first_seen_period")) or _clean(gp.get("house_first_seen_period"))),
        ("최근 확인 기간", _clean(gp.get("last_seen_period")) or _clean(gp.get("house_last_seen_period"))),
        ("자료 범위", _material_basis_note(gp)),
    ]
    return "\n".join(_fact_row(label, value) for label, value in facts if _clean(value) and _clean(value) != "-")


def _render_signal_bar(gp: dict[str, object]) -> str:
    news_count = int(gp.get("news_count") or 0)
    deal_count = int(gp.get("deal_news_count") or 0)
    lp_count = int(gp.get("lp_signal_count") or 0)
    return f"""    <section class="gp-signal-bar" aria-label="관련 정보 요약">
      <div><span>출자 연결</span><strong>{lp_count:,}</strong><em>공고·선정 이력</em></div>
      <div><span>딜 관련</span><strong>{deal_count:,}</strong><em>딜 관련 기사</em></div>
      <div><span>관련 뉴스</span><strong>{news_count:,}</strong><em>관련 기사</em></div>
    </section>"""


def _render_fund_rows(fund_rows: list[dict[str, object]]) -> str:
    if not fund_rows:
        return '<p class="gp-empty-note">금감원 공개 자료에서 연결된 펀드가 확인되지 않았습니다.</p>'
    rows = []
    for fund in fund_rows:
        name = _clean(fund.get("fund_name")) or "펀드"
        url = _safe_url(fund.get("latest_source_url"))
        title = f'<a href="{_e(url)}" target="_blank" rel="noreferrer">{_e(name)}</a>' if url else _e(name)
        amount = _format_trn_krw_as_100mn(fund.get("max_commitment_trn_krw") or fund.get("latest_commitment_trn_krw"))
        active_label = "운용중" if _as_bool(fund.get("active_in_latest_period")) else "청산완료"
        period_label = _clean(fund.get("last_seen_period"))
        meta = _join_values(
            [
                active_label,
                _short_date(fund.get("established_date")) if fund.get("established_date") else "설정일 미확인",
                f"최근 확인 {period_label}" if period_label else "",
            ]
        )
        rows.append(
            f"""          <article class="gp-fund-row">
            <h3>{title}</h3>
            <span><small>최대 총약정액</small>{_e(amount)}</span>
            <p>{_e(meta or "공개 운용 현황 기준")}</p>
          </article>"""
        )
    return '<div class="gp-fund-list">\n' + "\n".join(rows) + "\n        </div>"


def _render_lp_signal_rows(signal_rows: list[dict[str, object]]) -> str:
    if not signal_rows:
        return '<p class="gp-empty-note">이 GP와 직접 연결된 공개 LP 공고·선정 이력이 없습니다.</p>'
    rows = []
    for signal in signal_rows:
        title = _clean(signal.get("title")) or "LP 출자 이력"
        url = _safe_url(signal.get("notice_url"))
        linked_title = f'<a href="{_e(url)}" target="_blank" rel="noreferrer">{_e(title)}</a>' if url else _e(title)
        lp_name = _clean(signal.get("lp_name")) or _clean(signal.get("lp_code")) or "LP"
        date = _short_date(signal.get("event_date") or signal.get("announced_date"))
        amount = _format_krw_100mn(signal.get("allocation_amount_krw_100mn") or signal.get("commitment_amount_krw_100mn"))
        meta = _join_values(
            [
                lp_name,
                _lp_event_label(signal.get("event_type")),
                signal.get("asset_class"),
                signal.get("strategy"),
                amount if amount != "-" else "",
            ]
        )
        meta_line = _join_values([date, meta])
        meta_html = f"<span>{_e(meta_line)}</span>" if meta_line else ""
        rows.append(
            f"""          <article class="gp-lp-row">
            {meta_html}
            <h3>{linked_title}</h3>
          </article>"""
        )
    return '<div class="gp-lp-list">\n' + "\n".join(rows) + "\n        </div>"


def _render_news_timeline(news_rows: list[dict[str, object]], empty_label: str = "최근 공개 뉴스가 없습니다.") -> str:
    if not news_rows:
        return f'<p class="gp-empty-note">{_e(empty_label)}</p>'
    rows = []
    for item in news_rows:
        title = _clean(item.get("title")) or "뉴스"
        url = _safe_url(item.get("source_url"))
        publisher = _clean(item.get("publisher")) or _clean(item.get("source_domain")) or "언론"
        date = _short_date(item.get("published_at") or item.get("discovered_at"))
        excerpt = _clean(item.get("excerpt_text"))
        linked_title = (
            f'<a href="{_e(url)}" target="_blank" rel="noreferrer">{_e(title)}</a>'
            if url
            else _e(title)
        )
        excerpt_html = f"<p>{_e(excerpt[:180])}</p>" if excerpt else ""
        meta = _join_values([publisher, date])
        rows.append(
            f"""          <article class="gp-news-row">
            <span>{_e(meta)}</span>
            <h3>{linked_title}</h3>
            {excerpt_html}
          </article>"""
        )
    return '<div class="gp-news-list">\n' + "\n".join(rows) + "\n        </div>"


def _render_peer_links(current_gp: dict[str, object], ranked_gps: list[dict[str, object]]) -> str:
    current_id = str(current_gp["source_gp_id"])
    peers = [gp for gp in ranked_gps if str(gp["source_gp_id"]) != current_id and gp.get("profile_page")][:6]
    if not peers:
        return '<p class="gp-empty-note">표시할 비교 GP가 없습니다.</p>'
    rows = []
    for gp in peers:
        rows.append(
            f"""          <a class="gp-peer-row" href="{_e(str(gp.get("profile_page")))}">
            <strong>{_e(_gp_name(gp))}</strong>
            <span>{_e(_format_rank(gp.get("latest_primary_rank")))}</span>
            <span>{_e(_format_krw_100mn(gp.get("latest_primary_aum_proxy_krw_100mn")))}</span>
          </a>"""
        )
    return '<div class="gp-peer-list">\n' + "\n".join(rows) + "\n        </div>"


def _render_aliases(value: object) -> str:
    items = [item.strip() for item in re.split(r"[;,|]", _clean(value)) if item.strip()]
    if not items:
        return "<p>함께 쓰이는 별칭이 없습니다.</p>"
    return "<p>" + " ".join(f"<span>{_e(item)}</span>" for item in items[:12]) + "</p>"


def _render_chip(label: str, extra_class: str = "") -> str:
    if not label:
        return ""
    class_attr = f' class="{_e(extra_class)}"' if extra_class else ""
    return f"<span{class_attr}>{_e(label)}</span>"


def _avatar_label(value: object, fallback: str = "GP") -> str:
    text = re.sub(r"\s+", "", _clean(value))
    if not text:
        return fallback
    korean = "".join(re.findall(r"[가-힣]", text))
    if korean:
        return korean[:2]
    letters = re.findall(r"[A-Za-z0-9]", text)
    return "".join(letters[:2]).upper() or fallback


def _identity_tone(value: object) -> int:
    text = _clean(value)
    if not text:
        return 1
    return (sum(ord(char) for char in text) % 6) + 1


def _favicon_url(url: object) -> str:
    return brand_logo_url(_safe_url(url))


def _logo_style_attr(url: object) -> str:
    return brand_style_attr(_safe_url(url))


def _brand_logo_url(homepage_url: object, label: object) -> str:
    return brand_logo_url(_safe_url(homepage_url), label)


def _brand_logo_style_attr(homepage_url: object, label: object) -> str:
    return brand_style_attr(_safe_url(homepage_url), label)


def _avatar_markup(homepage_url: object, label: str, seed: object, brand_label: object = "") -> str:
    tone = _identity_tone(seed or label)
    logo_url = _brand_logo_url(homepage_url, brand_label)
    style_attr = _brand_logo_style_attr(homepage_url, brand_label)
    if logo_url:
        return (
            f'<span class="gp-avatar has-logo" data-tone="{tone}" aria-hidden="true"{style_attr}>'
            f'<img src="{logo_url}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.classList.add(\'fallback-only\'); this.remove()">'
            f'<span>{_e(label)}</span></span>'
        )
    return f'<span class="gp-avatar" data-tone="{tone}" aria-hidden="true"><span>{_e(label)}</span></span>'


def _card_status_label(latest_rank: str, has_profile_page: bool) -> str:
    return ""


def _fact_row(label: str, value: object, raw: bool = False) -> str:
    body = str(value) if raw else _e(str(value))
    return f"""          <div>
            <dt>{_e(label)}</dt>
            <dd>{body}</dd>
          </div>"""


def _render_service_header(active_tab: str = "gp") -> str:
    market_active = " active" if active_tab == "market" else ""
    market_current = ' aria-current="page"' if active_tab == "market" else ""
    gp_active = " active" if active_tab == "gp" else ""
    gp_current = ' aria-current="page"' if active_tab == "gp" else ""
    return f"""    <header class="app-header gp-app-header">
      <div class="service-bar">
        <strong class="service-title">GP</strong>
        <section class="search-area" id="searchArea" aria-label="GP 검색">
          <label class="search-box">
            <span aria-hidden="true"></span>
            <input id="gpSearch" type="search" placeholder="운용사명, 대표, 별칭, 펀드명 검색" autocomplete="off">
          </label>
          <button class="search-close" id="searchClose" type="button" aria-label="검색 닫기"></button>
        </section>
        <div class="service-actions" aria-label="GP 도구">
          <button class="header-icon search-toggle" id="searchToggle" type="button" aria-label="검색 열기" aria-expanded="false"></button>
        </div>
      </div>
      <nav class="brief-section-tabs gp-section-tabs" aria-label="GP 메뉴">
        <a class="brief-section-tab{market_active}" href="market.html"{market_current}>MARKET</a>
        <a class="brief-section-tab{gp_active}" href="gps.html"{gp_current}>GP</a>
      </nav>
    </header>"""


def _render_bottom_nav() -> str:
    return """  <nav class="bottom-nav newsletter-only" aria-label="하단 메뉴">
    <a href="index.html">
      <span aria-hidden="true" class="nav-dot nav-icon-brief"></span>
      <strong>브리프</strong>
    </a>
    <a href="lp-notices.html">
      <span aria-hidden="true" class="nav-dot nav-icon-lp"></span>
      <strong>LP</strong>
    </a>
    <a class="active" href="gps.html">
      <span aria-hidden="true" class="nav-dot nav-icon-gp"></span>
      <strong>GP</strong>
    </a>
  </nav>"""


def _service_header_script(redirect_search: bool = False) -> str:
    redirect = "true" if redirect_search else "false"
    return f"""  <script>
    (() => {{
      const serviceBar = document.querySelector(".service-bar");
      const searchArea = document.getElementById("searchArea");
      const searchInput = document.getElementById("gpSearch");
      const searchToggle = document.getElementById("searchToggle");
      const searchClose = document.getElementById("searchClose");
      const redirectSearch = {redirect};

      const openSearch = () => {{
        serviceBar?.classList.add("search-open");
        searchArea?.classList.add("active");
        searchToggle?.setAttribute("aria-expanded", "true");
        window.requestAnimationFrame(() => searchInput?.focus());
      }};

      const closeSearch = () => {{
        if (searchInput) searchInput.value = "";
        serviceBar?.classList.remove("search-open");
        searchArea?.classList.remove("active");
        searchToggle?.setAttribute("aria-expanded", "false");
        if (!redirectSearch) searchInput?.dispatchEvent(new Event("input", {{ bubbles: true }}));
      }};

      searchToggle?.addEventListener("click", openSearch);
      searchClose?.addEventListener("click", closeSearch);

      if (searchInput && !redirectSearch) {{
        const params = new URLSearchParams(window.location.search);
        const query = params.get("q") || "";
        if (query) {{
          openSearch();
          searchInput.value = query;
          searchInput.dispatchEvent(new Event("input", {{ bubbles: true }}));
        }}
      }}

      if (searchInput && redirectSearch) {{
        searchInput.addEventListener("keydown", (event) => {{
          if (event.key !== "Enter") return;
          event.preventDefault();
          const query = searchInput.value.trim();
          window.location.href = query ? `gps.html?q=${{encodeURIComponent(query)}}` : "gps.html";
        }});
      }}
    }})();
  </script>"""


def _directory_script() -> str:
    return """  <script>
    (() => {
      const input = document.getElementById("gpSearch");
      const periodSelect = document.getElementById("gpPeriod");
      const scopeSelect = document.getElementById("gpScope");
      const sort = document.getElementById("gpSort");
      const pageSizeSelect = document.getElementById("gpPageSize");
      const list = document.getElementById("gpDirectory");
      const visible = document.getElementById("gpVisibleCount");
      const pagination = document.getElementById("gpPagination");
      const prevPage = document.getElementById("gpPrevPage");
      const nextPage = document.getElementById("gpNextPage");
      const pageState = document.getElementById("gpPageState");
      const cards = Array.from(document.querySelectorAll(".gp-card"));
      let currentPage = 1;
      let orderedCards = [...cards];

      const num = (card, key, fallback = 0) => {
        const value = Number(card.dataset[key]);
        return Number.isFinite(value) ? value : fallback;
      };

      const formatAum100mn = (value) => {
        const parsed = Number(value);
        if (!Number.isFinite(parsed) || parsed <= 0) return "-";
        if (parsed >= 10000) return `${(parsed / 10000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}조`;
        return `${Math.round(parsed).toLocaleString("ko-KR")}억`;
      };

      const syncMetrics = () => {
        const period = periodSelect?.value || "";
        const scope = scopeSelect?.value || "active";
        cards.forEach((card) => {
          let aum = 0;
          let funds = 0;
          let aumLabel = "-";
          let fundsLabel = "-";
          let periodHit = true;
          if (scope === "cumulative") {
            aum = num(card, "cumulativeAum");
            funds = num(card, "cumulativeFunds");
            aumLabel = card.dataset.cumulativeAumLabel || formatAum100mn(aum);
            fundsLabel = card.dataset.cumulativeFundsLabel || (funds ? Math.round(funds).toLocaleString("ko-KR") : "-");
          } else {
            let metrics = {};
            try {
              metrics = JSON.parse(card.dataset.periodMetrics || "{}");
            } catch {
              metrics = {};
            }
            const row = metrics[period];
            periodHit = Boolean(row);
            if (row) {
              aum = Number(row.aum100mn) || 0;
              funds = Number(row.funds) || 0;
              aumLabel = formatAum100mn(aum);
              fundsLabel = funds ? Math.round(funds).toLocaleString("ko-KR") : "-";
            }
          }
          card.dataset.currentAum = String(aum);
          card.dataset.currentFunds = String(funds);
          card.dataset.periodHit = periodHit ? "1" : "0";
          const aumNode = card.querySelector("[data-gp-aum]");
          const fundsNode = card.querySelector("[data-gp-funds]");
          if (aumNode) aumNode.textContent = aumLabel;
          if (fundsNode) fundsNode.textContent = fundsLabel;
        });
      };

      const applySort = () => {
        const mode = sort?.value || "aum";
        orderedCards = [...cards].sort((a, b) => {
          if (mode === "aum") return num(b, "currentAum") - num(a, "currentAum");
          if (mode === "funds") return num(b, "currentFunds") - num(a, "currentFunds");
          if (mode === "name") return (a.dataset.name || "").localeCompare(b.dataset.name || "", "ko");
          return num(a, "rank", 999999) - num(b, "rank", 999999);
        });
        orderedCards.forEach((card) => list?.appendChild(card));
      };

      const getPageSize = (matchCount) => {
        const value = pageSizeSelect?.value || "30";
        if (value === "all") return Math.max(matchCount, 1);
        const parsed = Number(value);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : 30;
      };

      const apply = (options = {}) => {
        if (options.resetPage) currentPage = 1;
        const query = (input?.value || "").trim().toLowerCase();
        const matches = [];
        orderedCards.forEach((card) => {
          const haystack = (card.dataset.search || card.innerText || "").toLowerCase();
          const show = card.dataset.periodHit !== "0" && (!query || haystack.includes(query));
          if (show) matches.push(card);
          card.hidden = true;
        });
        const pageSize = getPageSize(matches.length);
        const totalPages = Math.max(1, Math.ceil(matches.length / pageSize));
        currentPage = Math.min(Math.max(currentPage, 1), totalPages);
        const start = (currentPage - 1) * pageSize;
        const end = Math.min(start + pageSize, matches.length);
        matches.slice(start, end).forEach((card) => {
          card.hidden = false;
        });
        if (visible) {
          const range = matches.length ? `${(start + 1).toLocaleString("ko-KR")}-${end.toLocaleString("ko-KR")}` : "0";
          visible.textContent = `${matches.length.toLocaleString("ko-KR")}개 중 ${range}`;
        }
        if (pagination) pagination.hidden = matches.length <= pageSize;
        if (pageState) pageState.textContent = `${currentPage.toLocaleString("ko-KR")} / ${totalPages.toLocaleString("ko-KR")}`;
        if (prevPage) prevPage.disabled = currentPage <= 1;
        if (nextPage) nextPage.disabled = currentPage >= totalPages;
      };

      input?.addEventListener("input", () => apply({ resetPage: true }));
      periodSelect?.addEventListener("change", () => {
        syncMetrics();
        applySort();
        apply({ resetPage: true });
      });
      scopeSelect?.addEventListener("change", () => {
        syncMetrics();
        applySort();
        apply({ resetPage: true });
      });
      sort?.addEventListener("change", () => {
        applySort();
        apply({ resetPage: true });
      });
      pageSizeSelect?.addEventListener("change", () => apply({ resetPage: true }));
      cards.forEach((card) => {
        const url = card.dataset.url || "";
        if (!url) return;
        card.tabIndex = 0;
        card.setAttribute("role", "link");
        card.addEventListener("click", (event) => {
          if (event.target.closest("a, button, input, select")) return;
          window.location.href = url;
        });
        card.addEventListener("keydown", (event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          window.location.href = url;
        });
      });
      prevPage?.addEventListener("click", () => {
        currentPage -= 1;
        apply();
        list?.scrollIntoView({ block: "start", behavior: "smooth" });
      });
      nextPage?.addEventListener("click", () => {
        currentPage += 1;
        apply();
        list?.scrollIntoView({ block: "start", behavior: "smooth" });
      });
      syncMetrics();
      applySort();
      apply();
    })();
  </script>"""


def _base_styles() -> str:
    return """  <style>
    :root {
      --bg: #ffffff;
      --surface: #ffffff;
      --surface-muted: #f7f7f8;
      --text: #171717;
      --secondary: #737373;
      --tertiary: #a3a3a3;
      --line: #e5e5e5;
      --line-strong: #d4d4d4;
      --accent: #171717;
      --accent-soft: #f5f5f5;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      overflow-x: hidden;
      background: var(--bg);
      color: var(--text);
      font-family: Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif;
      letter-spacing: 0;
    }
    a { color: inherit; }
    button,
    input {
      font: inherit;
    }
    .app-header {
      display: grid;
      gap: 0;
      padding: 2px 0 10px;
    }
    .service-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 40px;
    }
    .service-bar.search-open {
      gap: 8px;
    }
    .service-bar.search-open .service-title,
    .service-bar.search-open .service-actions {
      display: none;
    }
    .service-title {
      display: block;
      min-width: 0;
      margin: 0;
      color: var(--text);
      font-size: 21px;
      line-height: 1.1;
      font-weight: 800;
      letter-spacing: 0;
    }
    .service-actions {
      display: inline-flex;
      align-items: center;
      gap: 2px;
    }
    .header-icon {
      display: inline-flex;
      position: relative;
      width: 38px;
      height: 38px;
      flex: 0 0 38px;
      align-items: center;
      justify-content: center;
      border: 0;
      border-radius: 0;
      background: transparent;
      color: var(--text);
      cursor: pointer;
    }
    .search-toggle::before {
      width: 14px;
      height: 14px;
      border: 2px solid currentColor;
      border-radius: 50%;
      background: transparent;
      content: "";
    }
    .search-toggle::after {
      position: absolute;
      right: 10px;
      bottom: 10px;
      width: 7px;
      height: 2px;
      border-radius: 2px;
      background: currentColor;
      content: "";
      transform: rotate(45deg);
    }
    .search-area {
      display: none;
      min-width: 0;
      flex: 1 1 auto;
      gap: 8px;
      padding: 0;
      background: transparent;
    }
    .search-area.active {
      display: flex;
    }
    .search-box {
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      height: 38px;
      padding: 0 13px;
      border-radius: 12px;
      background: var(--surface-muted);
    }
    .search-box span {
      position: relative;
      width: 13px;
      height: 13px;
      flex: 0 0 auto;
      border: 2px solid var(--tertiary);
      border-radius: 50%;
    }
    .search-box span::after {
      position: absolute;
      right: -5px;
      bottom: -3px;
      width: 6px;
      height: 2px;
      border-radius: 2px;
      background: var(--tertiary);
      content: "";
      transform: rotate(45deg);
    }
    .search-box input {
      width: 100%;
      border: 0;
      outline: 0;
      background: transparent;
      color: var(--text);
      font-size: 16px;
    }
    .search-box input::placeholder {
      color: #8e8e93;
    }
    .search-close {
      display: inline-flex;
      position: relative;
      width: 38px;
      height: 38px;
      flex: 0 0 38px;
      align-items: center;
      justify-content: center;
      border: 0;
      border-radius: 50%;
      background: var(--surface);
      color: var(--secondary);
      cursor: pointer;
    }
    .search-close::before,
    .search-close::after {
      position: absolute;
      width: 16px;
      height: 2px;
      border-radius: 2px;
      background: currentColor;
      content: "";
    }
    .search-close::before {
      transform: rotate(45deg);
    }
    .search-close::after {
      transform: rotate(-45deg);
    }
    .brief-section-tabs {
      display: flex;
      min-height: 36px;
      align-items: center;
      gap: 18px;
      margin: 0 -14px;
      padding: 0 14px;
      border-bottom: 1px solid var(--line);
    }
    .brief-section-tabs::after {
      content: "";
      flex: 1 1 auto;
    }
    .brief-section-tab {
      display: inline-flex;
      position: relative;
      height: 36px;
      align-items: center;
      align-self: stretch;
      border: 0;
      border-bottom: 2px solid transparent;
      background: transparent;
      color: var(--secondary);
      font-size: 13px;
      line-height: 1;
      font-weight: 600;
      letter-spacing: 0;
      white-space: nowrap;
      cursor: default;
      -webkit-text-fill-color: currentColor;
    }
    .brief-section-tab.active {
      border-bottom-color: var(--text);
      color: var(--text);
      font-weight: 800;
    }
    .brief-section-tab:disabled {
      opacity: 1;
      color: #b8b8bd;
      -webkit-text-fill-color: currentColor;
    }
    .gp-shell {
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 0 0 calc(94px + env(safe-area-inset-bottom));
    }
    .bottom-nav {
      position: fixed;
      left: 50%;
      bottom: 0;
      z-index: 30;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      width: min(100vw, 1180px);
      max-width: 100vw;
      transform: translateX(-50%);
      border-top: 1px solid var(--line);
      padding: 8px 10px calc(8px + env(safe-area-inset-bottom));
      background: rgba(255,255,255,0.94);
      backdrop-filter: blur(22px);
      box-shadow: 0 -8px 24px rgba(15, 23, 42, 0.04);
    }
    .bottom-nav a {
      display: flex;
      min-width: 0;
      min-height: 48px;
      overflow: hidden;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 4px;
      border: 0;
      background: transparent;
      color: var(--secondary);
      font-size: 11px;
      line-height: 1.1;
      text-decoration: none;
    }
    .bottom-nav strong {
      max-width: 100%;
      overflow: hidden;
      font-weight: 700;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .bottom-nav .active { color: var(--text); }
    .nav-dot {
      display: inline-flex;
      width: 24px;
      height: 24px;
      flex: 0 0 24px;
      align-items: center;
      justify-content: center;
      opacity: 0.72;
    }
    .nav-dot::before {
      content: "";
      width: 22px;
      height: 22px;
      background: currentColor;
    }
    .nav-icon-brief::before {
      -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M4 5.5h16v13H4v-13Zm3 4h10M7 13h10M7 16h6' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
      mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M4 5.5h16v13H4v-13Zm3 4h10M7 13h10M7 16h6' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
    }
    .nav-icon-lp::before {
      -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M5 6.5h14M5 12h14M5 17.5h14M7 4.5v15M17 4.5v15' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'/%3E%3C/svg%3E") center / contain no-repeat;
      mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M5 6.5h14M5 12h14M5 17.5h14M7 4.5v15M17 4.5v15' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'/%3E%3C/svg%3E") center / contain no-repeat;
    }
    .nav-icon-gp::before {
      -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M4 18.5 9.5 13l3 3L20 7.5M14 7.5h6v6' fill='none' stroke='black' stroke-width='2.1' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
      mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M4 18.5 9.5 13l3 3L20 7.5M14 7.5h6v6' fill='none' stroke='black' stroke-width='2.1' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
    }
    .bottom-nav .active .nav-dot { opacity: 1; }
    .gp-hero {
      display: grid;
      gap: 8px;
      align-items: end;
      margin: 18px 0 12px;
    }
    .gp-hero-copy, .gp-detail-hero > div { display: grid; gap: 10px; }
    .gp-detail-title-head {
      display: grid;
      grid-template-columns: 54px minmax(0, 1fr);
      gap: 14px;
      align-items: center;
    }
    .gp-detail-title-head p { grid-column: 1 / -1; }
    .gp-detail-logo {
      position: relative;
      display: inline-grid;
      width: 54px;
      height: 54px;
      box-sizing: border-box;
      place-items: center;
      overflow: hidden;
      border: 1px solid #dde3ea;
      border-radius: 50%;
      background: #f4f6f8;
      color: var(--text);
      font-size: 12px;
      font-weight: 900;
      box-shadow: none;
    }
    .gp-detail-logo.has-logo {
      border-color: var(--logo-border, #e2e5ea);
      background: var(--logo-bg, #fff);
    }
    .gp-detail-logo.has-logo.fallback-only {
      border-color: #dde3ea;
      background: #f4f6f8;
    }
    .gp-detail-logo > span {
      position: relative;
      z-index: 1;
    }
    .gp-detail-logo img {
      position: relative;
      z-index: 2;
      width: var(--logo-detail-img-width, var(--logo-img-width, 38px));
      height: var(--logo-detail-img-height, var(--logo-img-height, 38px));
      mix-blend-mode: normal;
      object-fit: contain;
    }
    .gp-detail-logo.has-logo > span { display: none; }
    .gp-detail-logo.fallback-only > span { display: inline; }
    .gp-detail-logo[data-tone] { color: var(--text); }
    .gp-hero-copy > span,
    .gp-detail-title-head div > span,
    .gp-empty > span {
      width: fit-content;
      color: var(--secondary);
      font-size: 12.5px;
      font-weight: 850;
    }
    h1 {
      margin: 0;
      color: var(--text);
      font-size: 24px;
      font-weight: 860;
      line-height: 1.16;
      letter-spacing: 0;
    }
    .gp-hero-copy p,
    .gp-detail-hero p {
      max-width: 780px;
      margin: 0;
      color: var(--secondary);
      font-size: 14px;
      line-height: 1.55;
    }
    .gp-detail-kpis {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .gp-detail-kpis div,
    .gp-detail-card,
    .gp-control-panel,
    .gp-card,
    .gp-panel,
    .gp-disclaimer,
    .gp-empty {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: none;
    }
    .gp-detail-kpis div {
      min-width: 0;
      padding: 12px;
    }
    .gp-detail-kpis {
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }
    .gp-detail-kpis div {
      border: 0;
      border-radius: 0;
      background: transparent;
      box-shadow: none;
      padding: 13px 0;
    }
    .gp-detail-kpis span,
    .gp-fact-list dt {
      display: block;
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 850;
    }
    .gp-detail-kpis strong {
      display: block;
      margin-top: 5px;
      color: var(--text);
      font-size: 22px;
      line-height: 1.15;
      overflow-wrap: anywhere;
    }
    .gp-control-panel {
      display: grid;
      gap: 10px;
      margin: 12px 0 14px;
      border: 0;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      border-radius: 0;
      padding: 14px 0;
      background: transparent;
      box-shadow: none;
    }
    .gp-control-head {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 800;
    }
    .gp-controls {
      display: grid;
      gap: 8px;
    }
    .gp-controls input,
    .gp-controls select {
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 11px;
      background: var(--surface);
      color: var(--text);
      font: inherit;
      font-size: 14px;
    }
    .gp-filter-row {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
    }
    .gp-filter-row button {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 6px 10px;
      background: var(--surface);
      color: var(--secondary);
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
    }
    .gp-filter-row button.active {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    .gp-control-panel p {
      margin: 0;
      color: var(--secondary);
      font-size: 12px;
      line-height: 1.45;
    }
    .gp-directory-table {
      overflow: hidden;
      border: 1px solid var(--line-strong);
      border-radius: 6px;
      background: var(--surface);
      box-shadow: none;
    }
    .gp-directory-head {
      display: grid;
      grid-template-columns: 44px minmax(0, 1fr) 132px;
      gap: 10px;
      align-items: start;
      min-height: 44px;
      padding: 0 10px;
      border-bottom: 1px solid var(--line-strong);
      background: var(--surface-muted);
      color: var(--secondary);
      font-size: 12px;
      font-weight: 850;
      text-align: right;
      letter-spacing: 0;
    }
    .gp-directory-head span:first-child { text-align: center; }
    .gp-directory-head span:nth-child(3),
    .gp-directory-head span:nth-child(5) {
      display: none;
    }
    .gp-directory-head span:nth-child(4) {
      font-size: 0;
    }
    .gp-directory-head span:nth-child(4)::after {
      content: "순위 / 약정액";
      font-size: 12px;
    }
    .gp-directory {
      display: grid;
      gap: 0;
    }
    .gp-card {
      display: grid;
      grid-template-columns: 44px minmax(0, 1fr) 132px;
      gap: 10px;
      align-items: center;
      min-height: 76px;
      border: 0;
      border-bottom: 1px solid var(--line);
      border-radius: 0;
      padding: 10px;
      box-shadow: none;
    }
    .gp-avatar {
      position: relative;
      display: inline-grid;
      width: 40px;
      height: 40px;
      grid-column: 1;
      grid-row: 1;
      box-sizing: border-box;
      place-items: center;
      overflow: hidden;
      border: 1px solid #dde3ea;
      border-radius: 50%;
      background: #f4f6f8;
      color: var(--text);
      font-size: 10px;
      font-weight: 900;
      letter-spacing: 0;
      box-shadow: none;
    }
    .gp-avatar.has-logo {
      border-color: var(--logo-border, #e2e5ea);
      background: var(--logo-bg, #fff);
    }
    .gp-avatar.has-logo.fallback-only {
      border-color: #dde3ea;
      background: #f4f6f8;
    }
    .gp-avatar > span {
      position: relative;
      z-index: 1;
    }
    .gp-avatar img {
      position: relative;
      z-index: 2;
      width: var(--logo-img-width, 27px);
      height: var(--logo-img-height, 27px);
      mix-blend-mode: normal;
      object-fit: contain;
    }
    .gp-avatar.has-logo > span { display: none; }
    .gp-avatar.fallback-only > span { display: inline; }
    .gp-avatar[data-tone] { color: var(--text); }
    .gp-card:last-child { border-bottom: 0; }
    .gp-card[hidden] { display: none; }
    .gp-card-main {
      display: grid;
      grid-column: 2;
      grid-row: 1;
      gap: 6px;
    }
    .gp-card-title {
      display: grid;
      gap: 4px;
      min-width: 0;
    }
    .gp-card-title > span {
      color: var(--tertiary);
      font-size: 11px;
      font-weight: 850;
    }
    .gp-card h2 {
      margin: 0;
      color: var(--text);
      font-size: 15px;
      line-height: 1.34;
      overflow-wrap: break-word;
      word-break: keep-all;
    }
    .gp-card h2 a { text-decoration: none; }
    .gp-card h2 a:hover { color: var(--accent); }
    .gp-empty-row-copy {
      margin: 4px 0 0;
      color: var(--secondary);
      font-size: 12px;
      line-height: 1.4;
    }
    .gp-chips {
      display: none;
      flex-wrap: wrap;
      gap: 6px;
    }
    .gp-chips span {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 7px;
      background: var(--surface-muted);
      color: var(--text);
      font-size: 11px;
      font-weight: 850;
    }
    .gp-chips span.strong {
      border-color: var(--line-strong);
      background: var(--surface-muted);
      color: var(--text);
    }
    .gp-metrics {
      display: grid;
      grid-column: 3;
      grid-row: 1;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 7px;
      margin: 0;
      text-align: right;
    }
    .gp-metrics div {
      min-width: 0;
      border: 0;
      border-radius: 0;
      padding: 0;
      background: transparent;
    }
    .gp-metrics div:nth-child(2),
    .gp-metrics div:nth-child(4) { display: none; }
    .gp-metrics dt {
      color: var(--secondary);
      font-size: 10.5px;
      font-weight: 850;
      white-space: nowrap;
    }
    .gp-metrics dd {
      margin: 4px 0 0;
      color: var(--text);
      font-size: 14px;
      font-weight: 850;
      line-height: 1.2;
      overflow-wrap: anywhere;
    }
    .gp-signal-strip {
      display: none;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 6px;
    }
    .gp-signal-strip span {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 6px 7px;
      background: var(--surface-muted);
      color: var(--secondary);
      font-size: 11px;
      font-weight: 850;
      line-height: 1.25;
      white-space: nowrap;
    }
    .gp-signal-strip strong {
      color: var(--text);
      font-size: 12px;
    }
    .gp-meta-line {
      display: none;
      flex-wrap: wrap;
      gap: 7px;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 750;
      line-height: 1.4;
    }
    .gp-meta-line a,
    .gp-detail-card a {
      color: var(--accent);
      text-decoration: none;
      font-weight: 850;
    }
    .gp-pagination {
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: center;
      margin: 12px 0 4px;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 800;
    }
    .gp-pagination[hidden] {
      display: none;
    }
    .gp-pagination button {
      min-width: 70px;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--text);
      font: inherit;
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
    }
    .gp-pagination button:disabled {
      color: var(--tertiary);
      background: var(--surface-muted);
      cursor: default;
    }
    .gp-pagination span {
      min-width: 72px;
      text-align: center;
    }
    .gp-empty-note {
      margin: 0;
      color: var(--secondary);
      font-size: 12px;
      line-height: 1.45;
    }
    .gp-news-row a {
      color: var(--text);
      text-decoration: none;
      font-weight: 800;
    }
    .gp-disclaimer {
      margin-top: 12px;
      padding: 14px;
    }
    .gp-disclaimer h2,
    .gp-panel h2 {
      margin: 0 0 10px;
      font-size: 17px;
      line-height: 1.35;
    }
    .gp-panel-heading {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 10px;
    }
    .gp-panel-heading h2 { margin-bottom: 0; }
    .gp-panel-heading > span {
      flex: 0 0 auto;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 760;
    }
    .gp-disclaimer p {
      margin: 0;
      color: var(--secondary);
      font-size: 13px;
      line-height: 1.58;
    }
    .gp-disclaimer p + p { margin-top: 8px; }
    .gp-breadcrumb {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      margin-bottom: 12px;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 800;
    }
    .gp-breadcrumb a { color: var(--accent); text-decoration: none; }
    .gp-breadcrumb span::before { content: "/"; margin-right: 7px; color: var(--tertiary); }
    .gp-detail-hero {
      display: grid;
      gap: 14px;
      align-items: end;
      margin: 10px 0 12px;
    }
    .gp-detail-card {
      display: grid;
      gap: 7px;
      padding: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      box-shadow: none;
      color: var(--secondary);
      font-size: 13px;
      line-height: 1.45;
    }
    .gp-detail-card strong {
      color: var(--accent);
      font-size: 17px;
    }
    .gp-signal-bar {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin: 10px 0;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }
    .gp-signal-bar div {
      min-width: 0;
      border: 0;
      border-radius: 0;
      padding: 13px 0;
      background: transparent;
      box-shadow: none;
    }
    .gp-signal-bar span,
    .gp-signal-bar em {
      display: block;
      color: var(--secondary);
      font-size: 11.5px;
      font-style: normal;
      font-weight: 850;
      line-height: 1.35;
    }
    .gp-signal-bar strong {
      display: block;
      margin: 4px 0;
      color: var(--text);
      font-size: 22px;
      line-height: 1.1;
    }
    .gp-detail-grid {
      display: grid;
      gap: 10px;
      margin-top: 10px;
    }
    .gp-panel {
      min-width: 0;
      border: 0;
      border-top: 1px solid var(--line);
      border-radius: 0;
      padding: 18px 0;
      background: transparent;
      box-shadow: none;
    }
    .gp-fact-list {
      display: grid;
      gap: 9px;
      margin: 0;
    }
    .gp-fact-list div {
      min-width: 0;
      border-top: 1px solid var(--line);
      padding-top: 9px;
    }
    .gp-fact-list div:first-child {
      border-top: 0;
      padding-top: 0;
    }
    .gp-fact-list dd {
      margin: 4px 0 0;
      color: var(--text);
      font-size: 13px;
      font-weight: 750;
      line-height: 1.48;
      overflow-wrap: anywhere;
    }
    .gp-news-list {
      display: grid;
      gap: 10px;
    }
    .gp-fund-list,
    .gp-lp-list {
      display: grid;
      gap: 8px;
    }
    .gp-fund-row,
    .gp-lp-row {
      border-top: 1px solid var(--line);
      padding-top: 9px;
    }
    .gp-fund-row:first-child,
    .gp-lp-row:first-child {
      border-top: 0;
      padding-top: 0;
    }
    .gp-fund-row h3,
    .gp-lp-row h3 {
      margin: 0 0 4px;
      font-size: 14px;
      line-height: 1.42;
      overflow-wrap: anywhere;
    }
    .gp-fund-row a,
    .gp-lp-row a {
      color: var(--text);
      text-decoration: none;
      font-weight: 850;
    }
    .gp-fund-row span,
    .gp-lp-row span {
      display: block;
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 850;
      line-height: 1.4;
    }
    .gp-fund-row span small {
      display: block;
      margin-bottom: 1px;
      color: var(--tertiary);
      font-size: 10.5px;
      font-weight: 650;
    }
    .gp-fund-row p {
      margin: 0;
      color: var(--secondary);
      font-size: 12px;
      line-height: 1.45;
    }
    .gp-news-row {
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }
    .gp-news-row:first-child {
      border-top: 0;
      padding-top: 0;
    }
    .gp-news-row span {
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 850;
    }
    .gp-news-row h3 {
      margin: 4px 0;
      font-size: 14px;
      line-height: 1.42;
    }
    .gp-news-row p {
      margin: 0;
      color: var(--secondary);
      font-size: 12px;
      line-height: 1.48;
    }
    .gp-peer-list {
      display: grid;
      gap: 7px;
    }
    .gp-peer-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 64px 86px;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px;
      background: var(--surface-muted);
      color: var(--text);
      text-decoration: none;
      font-size: 12px;
    }
    .gp-peer-row strong {
      min-width: 0;
      overflow-wrap: anywhere;
      font-size: 13px;
    }
    .gp-peer-row span {
      color: var(--secondary);
      text-align: right;
      font-weight: 850;
    }
    .gp-alias-box {
      margin-top: 12px;
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }
    .gp-alias-box strong {
      display: block;
      margin-bottom: 7px;
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 850;
    }
    .gp-alias-box p {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 0;
      color: var(--secondary);
      font-size: 12px;
      line-height: 1.45;
    }
    .gp-alias-box span {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 7px;
      background: var(--surface-muted);
      color: var(--text);
      font-weight: 800;
    }
    .gp-empty {
      display: grid;
      gap: 10px;
      margin-top: 20px;
      padding: 24px;
    }
    .gp-empty p {
      margin: 0;
      color: var(--secondary);
      font-size: 15px;
      line-height: 1.55;
    }
    .gp-empty small {
      color: var(--secondary);
      font-size: 12px;
      line-height: 1.45;
    }
    @media (min-width: 720px) {
      .gp-hero { grid-template-columns: minmax(0, 1.2fr) minmax(360px, 0.8fr); }
      .gp-controls { grid-template-columns: minmax(0, 1fr) 210px 150px; }
      .gp-card-main { grid-template-columns: minmax(0, 1fr); align-items: start; }
      .gp-detail-hero { grid-template-columns: minmax(0, 1.2fr) minmax(300px, 0.8fr); }
      .gp-detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .gp-detail-lower { grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.75fr); }
      .gp-fact-list div {
        display: grid;
        grid-template-columns: 132px minmax(0, 1fr);
        gap: 14px;
        align-items: start;
      }
      .gp-fact-list dd { margin-top: 0; }
    }
    @media (min-width: 760px) {
      .gp-shell { padding-bottom: calc(106px + env(safe-area-inset-bottom)); }
      .bottom-nav {
        bottom: 18px;
        display: grid;
        width: min(720px, calc(100vw - 96px));
        border: 1px solid rgba(21, 32, 43, 0.10);
        border-radius: 999px;
        padding: 5px;
        background: rgba(255,255,255,0.94);
        box-shadow: 0 18px 60px rgba(15,23,42,0.15);
      }
      .bottom-nav a {
        min-height: 36px;
        flex-direction: row;
        gap: 6px;
        border-radius: 999px;
        font-size: 12px;
      }
      .bottom-nav .active {
        background: var(--surface-muted);
      }
      .nav-dot {
        width: 18px;
        height: 18px;
        flex-basis: 18px;
      }
      .nav-dot::before {
        width: 17px;
        height: 17px;
      }
    }
    @media (min-width: 960px) {
      .gp-shell {
        width: min(1460px, calc(100% - 56px));
      }
      h1 {
        font-size: 38px;
      }
      .bottom-nav {
        display: grid;
      }
      .gp-detail-kpis {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
      .gp-control-panel {
        margin: 16px 0;
      }
      .gp-directory-head {
        display: grid;
        grid-template-columns: 48px minmax(230px, 1.18fr) minmax(128px, 0.56fr) minmax(320px, 1.36fr) minmax(184px, 0.78fr) minmax(126px, 0.5fr);
        gap: 16px;
        align-items: center;
        min-height: 42px;
        padding: 0 16px;
        border-bottom: 1px solid var(--line-strong);
        background: #f0f1f2;
        color: var(--secondary);
        font-size: 12px;
        font-weight: 850;
        text-align: left;
      }
      .gp-directory-head span {
        display: block;
        font-size: 12px;
      }
      .gp-directory-head span:nth-child(2) {
        text-align: left;
      }
      .gp-directory-head span:nth-child(4)::after {
        content: none;
      }
      .gp-directory {
        gap: 0;
      }
      .gp-directory-table {
        border: 1px solid var(--line-strong);
        background: var(--surface);
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
      }
      .gp-card {
        grid-template-columns: 48px minmax(230px, 1.18fr) minmax(128px, 0.56fr) minmax(320px, 1.36fr) minmax(184px, 0.78fr) minmax(126px, 0.5fr);
        gap: 16px;
        align-items: center;
        border: 0;
        border-radius: 0;
        border-bottom: 1px solid var(--line);
        min-height: 72px;
        padding: 12px 16px;
        box-shadow: none;
      }
      .gp-card:last-child {
        border-bottom: 0;
      }
      .gp-card-main {
        grid-column: 2;
        grid-row: 1;
      }
      .gp-avatar {
        width: 40px;
        height: 40px;
      }
      .gp-meta-line {
        grid-column: 3;
        grid-row: 1;
        display: grid;
        gap: 4px;
      }
      .gp-metrics {
        grid-column: 4;
        grid-row: 1;
      }
      .gp-signal-strip {
        grid-column: 5;
        grid-row: 1;
      }
      .gp-card h2 {
        font-size: 15px;
      }
      .gp-card-title > span {
        font-size: 10.5px;
      }
      .gp-chips span {
        background: #f5f5f5;
        border-color: #e3e3e3;
        color: var(--secondary);
      }
      .gp-chips {
        display: flex;
      }
      .gp-metrics {
        grid-template-columns: repeat(4, minmax(0, 1fr));
        text-align: left;
      }
      .gp-metrics div:nth-child(2),
      .gp-metrics div:nth-child(4) {
        display: block;
      }
      .gp-signal-strip {
        display: grid;
      }
      .gp-metrics div,
      .gp-signal-strip span {
        border: 0;
        border-radius: 0;
        padding: 0;
        background: transparent;
      }
      .gp-metrics dt,
      .gp-signal-strip span {
        font-size: 10.5px;
      }
      .gp-metrics dd {
        font-size: 12.5px;
      }
    }
    @media (max-width: 620px) {
      .gp-shell {
        width: min(100% - 20px, 1240px);
        padding-top: 12px;
        padding-bottom: calc(52px + env(safe-area-inset-bottom));
      }
      h1 { font-size: 28px; line-height: 1.12; }
      .gp-hero-copy p,
      .gp-detail-hero p { font-size: 14px; line-height: 1.58; }
      .gp-filter-row {
        width: 100%;
        flex-wrap: wrap;
        overflow-x: visible;
        padding-bottom: 0;
      }
      .gp-filter-row button { flex: 0 0 auto; }
      .gp-detail-kpis,
      .gp-metrics,
      .gp-signal-strip,
      .gp-signal-bar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .gp-peer-row { grid-template-columns: minmax(0, 1fr) 56px; }
      .gp-peer-row span:last-child { display: none; }
      .bottom-nav {
        padding-right: 6px;
        padding-left: 6px;
      }
      .bottom-nav a {
        min-height: 50px;
        font-size: 10.5px;
      }
      .nav-dot {
        width: 22px;
        height: 22px;
        flex-basis: 22px;
      }
      .nav-dot::before {
        width: 20px;
        height: 20px;
      }
    }

    /* Newsletter-aligned GP public UI contract. Keep this block as the final
       override so GP follows the shared public visual language. */
    :root {
      --bg: #ffffff;
      --surface: #ffffff;
      --surface-muted: #f7f7f8;
      --text: #171717;
      --secondary: #737373;
      --tertiary: #a3a3a3;
      --line: #e5e5e5;
      --line-strong: #d4d4d4;
      --accent: #171717;
      --accent-soft: #f7f7f8;
      --shell: 1080px;
    }
    html {
      overflow-x: hidden;
      background: var(--surface);
    }
    body {
      background: var(--surface);
      color: var(--text);
      -webkit-font-smoothing: antialiased;
    }
    body,
    button,
    input,
    select {
      font-variant-numeric: tabular-nums;
      font-feature-settings: "tnum" 1, "lnum" 1;
    }
    a { text-decoration: none; }
    .gp-shell {
      width: min(calc(100% - 28px), var(--shell));
      max-width: 100%;
      padding: max(14px, env(safe-area-inset-top)) 0 calc(88px + env(safe-area-inset-bottom));
    }
    .gp-app-header {
      max-width: 900px;
      margin: 0 auto 2px;
    }
    .gp-hero {
      display: block;
      margin: 9px 0 7px;
    }
    .gp-detail-hero {
      display: block;
      margin: 12px 0 10px;
    }
    .gp-hero-copy,
    .gp-detail-hero > div {
      gap: 6px;
    }
    .gp-hero-copy > span,
    .gp-detail-title-head div > span,
    .gp-empty > span {
      border: 0;
      padding-left: 0;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 650;
    }
    h1 {
      font-size: 26px;
      font-weight: 820;
      line-height: 1.14;
    }
    .gp-hero h1 {
      font-size: 16px;
      font-weight: 800;
      line-height: 1.35;
    }
    .gp-detail-title-head h1 {
      font-size: 23px;
      font-weight: 820;
      line-height: 1.18;
    }
    .gp-hero-copy p,
    .gp-detail-hero p {
      max-width: 720px;
      color: var(--secondary);
      font-size: 14px;
      line-height: 1.58;
    }
    .gp-control-panel {
      margin: 0 0 10px;
      border-top: 0;
      border-bottom: 1px solid var(--line);
      padding: 0 0 10px;
    }
    .gp-control-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 650;
      line-height: 1.35;
    }
    .gp-controls {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 8px;
    }
    .gp-controls input {
      grid-column: 1 / -1;
    }
    .gp-controls input,
    .gp-controls select {
      min-height: 40px;
      border-color: var(--line);
      border-radius: 6px;
      color: var(--text);
      font-size: 13.5px;
      box-shadow: none;
      outline-color: var(--accent);
    }
    .gp-filter-row {
      gap: 5px;
      margin-top: 0;
    }
    .gp-filter-row button {
      border-color: var(--line);
      border-radius: 999px;
      padding: 5px 9px;
      background: var(--surface);
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 700;
      box-shadow: none;
    }
    .gp-filter-row button.active {
      border-color: var(--text);
      background: var(--text);
      color: #fff;
    }
    .gp-control-meta,
    .gp-control-panel p {
      color: var(--secondary);
      font-size: 12px;
      line-height: 1.45;
    }
    .gp-directory-table {
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      box-shadow: none;
    }
    .gp-directory-head {
      grid-template-columns: 40px minmax(0, 1fr) 90px;
      min-height: 38px;
      padding: 0 8px;
      border-bottom: 1px solid var(--line);
      background: var(--surface-muted);
      color: var(--secondary);
      font-size: 12px;
      font-weight: 700;
      text-align: right;
    }
    .gp-directory-head span:first-child {
      grid-column: 1;
    }
    .gp-directory-head span:nth-child(2) {
      grid-column: 2;
      text-align: left;
    }
    .gp-directory-head span:nth-child(3),
    .gp-directory-head span:nth-child(5) {
      display: none;
    }
    .gp-directory-head span:nth-child(4) {
      grid-column: 3;
      display: block;
      font-size: 12px;
      text-align: right;
    }
    .gp-directory-head span:nth-child(4)::after {
      content: none;
    }
    .gp-card {
      grid-template-columns: 40px minmax(0, 1fr) 90px;
      align-items: start;
      min-height: 68px;
      border-bottom: 1px solid var(--line);
      padding: 9px 8px;
      background: var(--surface);
    }
    .gp-card:last-child { border-bottom: 0; }
    .gp-avatar {
      width: 40px;
      height: 40px;
      margin-top: 2px;
      border-color: #dde3ea;
      font-size: 10px;
      box-shadow: none;
    }
    .gp-avatar img {
      width: var(--logo-img-width, 27px);
      height: var(--logo-img-height, 27px);
    }
    .gp-card-title {
      gap: 2px;
    }
    .gp-card-main {
      grid-column: 2;
      grid-row: 1;
    }
    .gp-card-title > span,
    .gp-chips {
      display: none !important;
    }
    .gp-card h2 {
      font-size: 14.5px;
      font-weight: 700;
      line-height: 1.36;
      letter-spacing: 0;
    }
    .gp-metrics {
      grid-column: 3;
      grid-row: 1;
      gap: 5px;
      grid-template-columns: 1fr;
      text-align: right;
    }
    .gp-metrics dt {
      color: var(--secondary);
      font-size: 10.5px;
      font-weight: 650;
    }
    .gp-metrics dd {
      color: var(--text);
      font-size: 12.5px;
      font-weight: 740;
    }
    .gp-signal-strip {
      display: none !important;
    }
    .gp-meta-line {
      color: var(--secondary);
      font-size: 12px;
      font-weight: 650;
    }
    .gp-pagination {
      margin: 12px 0 2px;
      font-size: 12px;
      font-weight: 700;
    }
    .gp-pagination button {
      min-height: 34px;
      border-color: var(--line);
      border-radius: 8px;
      background: var(--surface);
      font-size: 12px;
      font-weight: 700;
    }
    .gp-breadcrumb {
      margin: 14px 0 12px;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 650;
    }
    .gp-detail-title-head {
      grid-template-columns: 50px minmax(0, 1fr);
      gap: 12px;
    }
    .gp-detail-logo {
      width: 50px;
      height: 50px;
      border-color: #dde3ea;
      box-shadow: none;
    }
    .gp-detail-logo img {
      width: var(--logo-detail-img-width, var(--logo-img-width, 35px));
      height: var(--logo-detail-img-height, var(--logo-img-height, 35px));
    }
    .gp-detail-card {
      margin-top: 8px;
      color: var(--secondary);
      font-size: 12.5px;
      font-weight: 650;
    }
    .gp-detail-kpis,
    .gp-signal-bar {
      gap: 0;
      margin: 10px 0;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }
    .gp-detail-kpis div,
    .gp-signal-bar div {
      padding: 10px 0;
    }
    .gp-detail-kpis span,
    .gp-signal-bar span,
    .gp-signal-bar em,
    .gp-fact-list dt {
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 650;
    }
    .gp-detail-kpis strong,
    .gp-signal-bar strong {
      margin-top: 4px;
      color: var(--text);
      font-size: 17px;
      font-weight: 760;
    }
    .gp-panel,
    .gp-disclaimer {
      border: 0;
      border-top: 1px solid var(--line);
      border-radius: 0;
      background: transparent;
      box-shadow: none;
    }
    .gp-panel {
      padding: 15px 0;
    }
    .gp-panel h2,
    .gp-disclaimer h2 {
      margin-bottom: 10px;
      font-size: 15px;
      font-weight: 760;
      line-height: 1.35;
    }
    .gp-fact-list div,
    .gp-fund-row,
    .gp-lp-row,
    .gp-news-row {
      border-top-color: var(--line);
    }
    .gp-fact-list dd {
      color: var(--text);
      font-size: 13px;
      font-weight: 620;
      line-height: 1.5;
    }
    .gp-fund-row h3,
    .gp-lp-row h3,
    .gp-news-row h3 {
      font-size: 14px;
      font-weight: 720;
      line-height: 1.45;
    }
    .gp-fund-row span,
    .gp-lp-row span,
    .gp-news-row span,
    .gp-news-row p,
    .gp-empty-note {
      color: var(--secondary);
      font-size: 12px;
      font-weight: 600;
    }
    .gp-peer-row {
      border-color: var(--line);
      border-radius: 6px;
      background: var(--surface);
      box-shadow: none;
    }
    .gp-alias-box span {
      border-color: var(--line);
      background: var(--surface-muted);
      font-weight: 650;
    }
    .gp-disclaimer {
      margin-top: 6px;
      padding: 16px 0 0;
    }
    .gp-disclaimer p {
      color: var(--secondary);
      font-size: 12.5px;
      line-height: 1.58;
    }
    .bottom-nav {
      grid-template-columns: repeat(3, minmax(0, 1fr));
      width: min(100vw, 520px);
      padding: 7px 10px calc(7px + env(safe-area-inset-bottom));
      border-top: 1px solid rgba(0,0,0,0.08);
      background: rgba(255,255,255,0.92);
      box-shadow: none;
      backdrop-filter: blur(18px);
    }
    .bottom-nav a {
      min-height: auto;
      gap: 3px;
      color: var(--secondary);
      font-size: 11px;
      line-height: 1.1;
    }
    .bottom-nav strong {
      font-weight: 620;
    }
    .bottom-nav .active {
      color: var(--text);
    }
    .nav-dot {
      width: 23px;
      height: 23px;
      flex-basis: 23px;
      opacity: 0.68;
    }
    .nav-dot::before {
      width: 21px;
      height: 21px;
    }
    .bottom-nav .active .nav-dot { opacity: 1; }
    @media (min-width: 760px) {
      .gp-shell {
        padding-bottom: calc(106px + env(safe-area-inset-bottom));
      }
      .bottom-nav {
        bottom: 18px;
        width: min(640px, calc(100vw - 96px));
        border: 1px solid rgba(0,0,0,0.07);
        border-radius: 999px;
        padding: 5px;
        background: rgba(255,255,255,0.96);
        box-shadow: 0 8px 28px rgba(15,23,42,0.08);
      }
      .bottom-nav a {
        min-height: 36px;
        flex-direction: row;
        justify-content: center;
        gap: 6px;
        border-radius: 999px;
        font-size: 12px;
      }
      .bottom-nav .active {
        background: var(--surface-muted);
      }
      .nav-dot {
        width: 18px;
        height: 18px;
        flex-basis: 18px;
      }
      .nav-dot::before {
        width: 17px;
        height: 17px;
      }
    }
    @media (min-width: 960px) {
      .gp-shell {
        width: min(calc(100% - 48px), var(--shell));
      }
      h1 {
        font-size: 32px;
      }
      .gp-hero {
        margin-top: 22px;
        margin-bottom: 16px;
      }
      .gp-controls {
        grid-template-columns: 190px 140px;
        justify-content: start;
      }
      .gp-directory-head {
        grid-template-columns: 48px minmax(230px, 1.15fr) minmax(130px, 0.56fr) minmax(300px, 1.34fr) minmax(170px, 0.74fr);
        gap: 16px;
        min-height: 42px;
        padding: 0 16px;
        text-align: left;
      }
      .gp-directory-head span:nth-child(3),
      .gp-directory-head span:nth-child(5) {
        display: block;
      }
      .gp-card {
        grid-template-columns: 48px minmax(230px, 1.15fr) minmax(130px, 0.56fr) minmax(300px, 1.34fr) minmax(170px, 0.74fr);
        gap: 16px;
        min-height: 72px;
        padding: 12px 16px;
      }
      .gp-avatar {
        width: 40px;
        height: 40px;
      }
      .gp-avatar img {
        width: var(--logo-img-width, 27px);
        height: var(--logo-img-height, 27px);
      }
      .gp-meta-line {
        display: grid;
        grid-column: 3;
        grid-row: 1;
        gap: 4px;
      }
      .gp-metrics {
        grid-column: 4;
        grid-row: 1;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        text-align: left;
      }
      .gp-metrics div:nth-child(2),
      .gp-metrics div:nth-child(4) {
        display: block;
      }
      .gp-signal-strip {
        display: grid !important;
        grid-column: 5;
        grid-row: 1;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 4px 8px;
      }
      .gp-signal-strip span {
        border: 0;
        border-radius: 0;
        padding: 0;
        background: transparent;
        color: var(--secondary);
        font-size: 11px;
        font-weight: 650;
      }
      .gp-signal-strip strong {
        color: var(--text);
        font-size: 12px;
        font-weight: 740;
      }
      .gp-detail-hero {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(220px, 0.32fr);
        gap: 22px;
        align-items: end;
      }
      .gp-detail-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .gp-detail-lower {
        grid-template-columns: minmax(0, 1.18fr) minmax(320px, 0.82fr);
      }
      .gp-detail-kpis {
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }
      .gp-signal-bar {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }
    @media (max-width: 620px) {
      .gp-shell {
        width: calc(100% - 28px);
        padding-top: max(14px, env(safe-area-inset-top));
      }
      h1 {
        font-size: 26px;
      }
      .gp-detail-kpis,
      .gp-signal-bar {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .gp-card h2 {
        font-size: 15px;
      }
    }
    .brief-section-tab {
      text-decoration: none;
    }
    .market-hero .gp-hero-copy p {
      margin-top: 3px;
      color: var(--secondary);
      font-size: 12.5px;
      font-weight: 650;
    }
    .market-kpis {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0;
      margin: 0;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }
    .market-kpis div {
      min-width: 0;
      padding: 12px 0;
    }
    .market-kpis span,
    .market-kpis em {
      display: block;
      color: var(--secondary);
      font-size: 11.5px;
      font-style: normal;
      font-weight: 650;
      line-height: 1.35;
    }
    .market-kpis strong {
      display: block;
      margin: 4px 0 3px;
      color: var(--text);
      font-size: 18px;
      font-weight: 780;
      line-height: 1.15;
    }
    .market-metric-note {
      margin: 10px 0 0;
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 620;
      line-height: 1.5;
    }
    .market-chart {
      margin: 0 0 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
    }
    .market-trend-chart {
      display: grid;
      grid-template-columns: repeat(8, minmax(0, 1fr));
      align-items: end;
      gap: 8px;
      min-height: 164px;
      padding: 12px;
    }
    .market-chart-bar {
      display: grid;
      grid-template-rows: 18px minmax(48px, 1fr) 18px;
      gap: 6px;
      align-items: end;
      min-width: 0;
      height: 136px;
      color: var(--secondary);
      font-size: 10.5px;
      font-weight: 650;
      text-align: center;
    }
    .market-chart-bar i {
      display: block;
      width: 100%;
      min-height: 8px;
      border-radius: 4px 4px 0 0;
      background: #2f6f66;
    }
    .market-chart-bar strong {
      overflow: hidden;
      color: var(--text);
      font-size: 10.5px;
      font-weight: 720;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .market-chart-empty {
      display: grid;
      grid-column: 1 / -1;
      min-height: 120px;
      place-items: center;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 650;
      text-align: center;
    }
    .market-rank-chart {
      display: grid;
      gap: 8px;
      padding: 12px;
    }
    .market-rank-bar {
      display: grid;
      grid-template-columns: minmax(90px, 1fr) minmax(90px, 2fr) 70px;
      gap: 8px;
      align-items: center;
      min-height: 24px;
      font-size: 11.5px;
      font-weight: 650;
    }
    .market-rank-bar span {
      overflow: hidden;
      color: var(--text);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .market-rank-bar i {
      display: block;
      overflow: hidden;
      height: 8px;
      border-radius: 999px;
      background: var(--surface-muted);
    }
    .market-rank-bar b {
      display: block;
      height: 100%;
      border-radius: inherit;
      background: #2f6f66;
    }
    .market-rank-bar strong {
      color: var(--secondary);
      font-size: 11px;
      font-weight: 720;
      text-align: right;
    }
    .market-section {
      position: relative;
      margin: 0 0 18px;
      border-top: 0;
      padding-top: 0;
    }
    .market-section + .market-section {
      margin-top: 18px;
      padding-top: 20px;
    }
    .market-section + .market-section::before {
      position: absolute;
      top: 0;
      left: 50%;
      width: 100vw;
      height: 8px;
      transform: translateX(-50%);
      background: #f7f7f8;
      content: "";
    }
    .market-overview-section {
      margin-top: 6px;
    }
    .market-section-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }
    .market-section h2 {
      margin: 0;
      color: var(--text);
      font-size: 15px;
      font-weight: 780;
      line-height: 1.35;
    }
    .market-section-head p {
      margin: 0;
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 620;
      line-height: 1.4;
      text-align: right;
    }
    .market-table {
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
    }
    .market-head,
    .market-row {
      display: grid;
      gap: 10px;
      align-items: center;
      min-height: 40px;
      padding: 0 10px;
      border-bottom: 1px solid var(--line);
      font-size: 12.5px;
      line-height: 1.35;
    }
    .market-head {
      background: var(--surface-muted);
      color: var(--secondary);
      font-weight: 720;
    }
    .market-row {
      color: var(--text);
      font-weight: 650;
    }
    .market-row:last-child {
      border-bottom: 0;
    }
    .market-period-row {
      grid-template-columns: minmax(62px, 0.85fr) minmax(48px, 0.7fr) minmax(42px, 0.6fr) minmax(72px, 0.9fr);
      text-align: right;
    }
    .market-period-row span:first-child {
      text-align: left;
    }
    .market-gp-row {
      grid-template-columns: 36px minmax(0, 1fr) minmax(72px, 0.72fr) minmax(44px, 0.52fr);
      text-align: right;
    }
    .market-gp-row strong {
      min-width: 0;
      color: var(--text);
      font-size: 13px;
      font-weight: 760;
      text-align: left;
      word-break: keep-all;
      overflow-wrap: anywhere;
    }
    .market-gp-row span:nth-child(1) {
      text-align: center;
    }
    .market-new-row {
      grid-template-columns: minmax(72px, 1fr) minmax(48px, 0.7fr) minmax(86px, 0.9fr);
      text-align: right;
    }
    .market-new-row span:first-child {
      text-align: left;
    }
    .market-empty-row {
      display: block;
      padding: 12px;
      color: var(--secondary);
    }
    .market-grid {
      display: grid;
      gap: 0;
    }
    .market-source-note {
      margin-bottom: 0;
      color: var(--secondary);
      font-size: 12px;
      line-height: 1.5;
    }
    .market-source-note strong {
      display: block;
      margin-bottom: 6px;
      color: var(--text);
      font-size: 13px;
      font-weight: 760;
    }
    .market-source-note ul {
      display: grid;
      gap: 5px;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .market-source-note li {
      display: flex;
      justify-content: space-between;
      gap: 12px;
    }
    .market-source-note a {
      color: var(--text);
      font-weight: 650;
    }
    .gp-directory-title {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 4px 6px;
      font-size: 16px !important;
      line-height: 1.35;
    }
    .gp-directory-title strong {
      color: #8a6a56;
      font-size: 17px;
      font-weight: 820;
    }
    .gp-directory-title span {
      color: var(--text);
      font-weight: 760;
    }
    .gp-directory-title em {
      color: var(--secondary);
      font-size: 12px;
      font-style: normal;
      font-weight: 620;
    }
    .gp-controls {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      align-items: end;
      margin: 0;
    }
    .gp-controls label {
      display: grid;
      gap: 5px;
      min-width: 0;
    }
    .gp-controls label > span {
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 650;
    }
    .gp-control-head {
      margin: 8px 0 0;
      font-size: 11.5px;
      font-weight: 620;
    }
    .gp-directory-head,
    .gp-card {
      grid-template-columns: 40px minmax(0, 1fr) minmax(78px, 0.7fr) minmax(48px, 0.46fr) !important;
      gap: 9px;
      align-items: center;
    }
    .gp-directory-head {
      min-height: 38px;
      text-align: right;
    }
    .gp-directory-head span {
      display: block !important;
      grid-column: auto !important;
      font-size: 12px !important;
    }
    .gp-directory-head span:nth-child(2) {
      text-align: left;
    }
    .gp-directory-head span:nth-child(3),
    .gp-directory-head span:nth-child(4) {
      text-align: right;
    }
    .gp-card {
      min-height: 64px;
      align-items: center;
    }
    .gp-card-main {
      grid-column: 2;
    }
    .gp-card h2 {
      font-size: 14.5px;
      font-weight: 720;
      line-height: 1.36;
    }
    .gp-metrics {
      display: contents;
    }
    .gp-metrics div {
      display: block !important;
      min-width: 0;
      text-align: right;
    }
    .gp-metrics div:first-child {
      grid-column: 3;
    }
    .gp-metrics div:last-child {
      grid-column: 4;
    }
    .gp-metrics dt {
      display: none;
    }
    .gp-metrics dd {
      margin: 0;
      color: var(--text);
      font-size: 12.5px;
      font-weight: 740;
      line-height: 1.25;
    }
    .gp-filter-row,
    .gp-chips,
    .gp-signal-strip,
    .gp-meta-line {
      display: none !important;
    }
    @media (max-width: 620px) {
      .market-trend-chart {
        grid-template-columns: repeat(4, minmax(0, 1fr));
        min-height: 220px;
      }
      .market-chart-bar {
        height: 96px;
      }
      .market-rank-bar {
        grid-template-columns: minmax(80px, 1fr) minmax(80px, 1.4fr) 60px;
      }
    }
    @media (min-width: 760px) {
      .market-kpis {
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }
      .market-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 18px;
      }
      .market-section h2 {
        font-size: 16px;
      }
      .market-head,
      .market-row {
        min-height: 44px;
        padding: 0 14px;
        font-size: 13px;
      }
      .gp-controls {
        grid-template-columns: minmax(150px, 1fr) minmax(120px, 0.7fr) minmax(150px, 0.9fr) minmax(130px, 0.7fr) !important;
        justify-content: stretch;
      }
      .gp-directory-head,
      .gp-card {
        grid-template-columns: 48px minmax(260px, 1fr) minmax(112px, 0.42fr) minmax(76px, 0.28fr) !important;
        gap: 16px;
        padding-right: 16px;
        padding-left: 16px;
      }
      .gp-card {
        min-height: 70px;
      }
      .gp-card h2 {
        font-size: 15px;
      }
      .gp-metrics dd {
        font-size: 13px;
      }
    }

    /* Isolated profile preview: applies only to the approved MBK profile. */
    .gp-profile-preview {
      width: min(calc(100% - 32px), 760px);
      padding-bottom: calc(100px + env(safe-area-inset-bottom));
    }
    .gp-profile-preview .gp-app-header {
      margin-bottom: 10px;
    }
    .gp-profile-preview-back {
      margin: 12px 0 22px;
      font-size: 13px;
      font-weight: 700;
    }
    .gp-profile-preview-back a {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      color: #4e5968;
    }
    .gp-profile-preview-back a::before {
      width: 8px;
      height: 8px;
      margin-right: 8px;
      border-bottom: 1.5px solid currentColor;
      border-left: 1.5px solid currentColor;
      content: "";
      transform: rotate(45deg);
    }
    .gp-profile-preview-hero {
      display: grid;
      grid-template-columns: 64px minmax(0, 1fr);
      gap: 15px;
      align-items: center;
      padding: 0 0 26px;
    }
    .gp-profile-preview-logo {
      width: 64px;
      height: 64px;
      border-color: #e5e8eb;
      background: #fff;
      border-radius: 18px;
    }
    .gp-profile-preview-logo img {
      width: var(--logo-detail-img-width, var(--logo-img-width, 45px));
      height: var(--logo-detail-img-height, var(--logo-img-height, 45px));
    }
    .gp-profile-preview-kicker {
      display: block;
      margin-bottom: 4px;
      color: #6b7684;
      font-size: 13px;
      font-weight: 650;
      line-height: 1.3;
    }
    .gp-profile-preview-hero h1 {
      color: #191f28;
      font-size: 25px;
      font-weight: 780;
      line-height: 1.22;
    }
    .gp-profile-preview-hero p {
      margin: 6px 0 0;
      color: #6b7684;
      font-size: 13px;
      font-weight: 600;
      line-height: 1.4;
    }
    .gp-profile-preview-metrics {
      border-top: 1px solid #e5e8eb;
      border-bottom: 1px solid #e5e8eb;
      padding: 0;
    }
    .gp-profile-preview-metrics dl {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0;
      margin: 0;
    }
    .gp-profile-preview-metrics div {
      min-width: 0;
      padding: 18px 12px 16px 0;
    }
    .gp-profile-preview-metrics div:nth-child(even) {
      padding-right: 0;
      padding-left: 12px;
    }
    .gp-profile-preview-metrics div:nth-child(n + 3) {
      border-top: 1px solid #f2f4f6;
    }
    .gp-profile-preview-metrics dt {
      color: #6b7684;
      font-size: 12px;
      font-weight: 650;
      line-height: 1.35;
    }
    .gp-profile-preview-metrics dd {
      margin: 7px 0 3px;
      color: #191f28;
      font-size: 22px;
      font-weight: 780;
      line-height: 1.18;
      letter-spacing: 0;
      overflow-wrap: anywhere;
    }
    .gp-profile-preview-metrics span {
      display: block;
      color: #8b95a1;
      font-size: 11px;
      font-weight: 600;
      line-height: 1.35;
    }
    .gp-profile-preview-section {
      margin: 0 -16px;
      border-top: 8px solid #f2f4f6;
      padding: 24px 16px 0;
    }
    .gp-profile-preview-section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 14px;
    }
    .gp-profile-preview-section-head h2 {
      margin: 0;
      color: #191f28;
      font-size: 18px;
      font-weight: 760;
      line-height: 1.35;
    }
    .gp-profile-preview-info-list {
      margin: 0;
    }
    .gp-profile-preview-info-row {
      display: grid;
      grid-template-columns: minmax(80px, 0.42fr) minmax(0, 1fr);
      gap: 16px;
      min-height: 53px;
      align-items: center;
      border-top: 1px solid #f2f4f6;
    }
    .gp-profile-preview-info-row dt {
      color: #6b7684;
      font-size: 14px;
      font-weight: 650;
    }
    .gp-profile-preview-info-row dd {
      margin: 0;
      color: #333d4b;
      font-size: 14px;
      font-weight: 650;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .gp-profile-preview-info-row a {
      color: #3182f6;
    }
    .gp-profile-preview-funds {
      padding-bottom: 4px;
    }
    .gp-profile-preview-fund-head {
      align-items: flex-start;
      margin-bottom: 16px;
    }
    .gp-profile-preview-fund-head p {
      margin: 5px 0 0;
      color: #6b7684;
      font-size: 12px;
      font-weight: 600;
      line-height: 1.45;
    }
    .gp-profile-preview-fund-head > strong {
      padding-top: 2px;
      color: #4e5968;
      font-size: 14px;
      font-weight: 700;
      white-space: nowrap;
    }
    .gp-profile-preview-filter {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      margin: 0 -2px 10px;
      padding: 0 2px 4px;
      scrollbar-width: none;
    }
    .gp-profile-preview-filter::-webkit-scrollbar { display: none; }
    .gp-profile-preview-filter button {
      flex: 0 0 auto;
      min-height: 34px;
      border: 0;
      border-radius: 8px;
      padding: 0 11px;
      background: #f2f4f6;
      color: #6b7684;
      font-size: 12px;
      font-weight: 700;
    }
    .gp-profile-preview-filter button.active {
      background: #191f28;
      color: #fff;
    }
    .gp-profile-preview-fund-list {
      display: grid;
    }
    .gp-profile-preview-fund-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 16px;
      align-items: center;
      min-height: 84px;
      border-top: 1px solid #f2f4f6;
      padding: 14px 0;
    }
    .gp-profile-preview-fund-row[hidden] { display: none; }
    .gp-profile-preview-fund-copy { min-width: 0; }
    .gp-profile-preview-fund-copy h3 {
      margin: 0;
      color: #333d4b;
      font-size: 14px;
      font-weight: 700;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .gp-profile-preview-fund-copy a { color: inherit; }
    .gp-profile-preview-fund-copy p {
      margin: 5px 0 0;
      color: #8b95a1;
      font-size: 12px;
      font-weight: 600;
      line-height: 1.4;
    }
    .gp-profile-preview-fund-amount {
      display: grid;
      justify-items: end;
      gap: 6px;
      min-width: 72px;
    }
    .gp-profile-preview-fund-state {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      border-radius: 6px;
      padding: 0 7px;
      background: #e8f3ff;
      color: #3182f6;
      font-size: 11px;
      font-weight: 700;
      white-space: nowrap;
    }
    .gp-profile-preview-fund-state.historical {
      background: #f2f4f6;
      color: #6b7684;
    }
    .gp-profile-preview-fund-amount strong {
      color: #333d4b;
      font-size: 13px;
      font-weight: 750;
      line-height: 1.3;
      text-align: right;
      white-space: nowrap;
    }
    .gp-profile-preview-empty {
      margin: 16px 0;
      color: #6b7684;
      font-size: 13px;
      font-weight: 600;
    }
    .gp-profile-preview-source {
      margin: 0 -16px;
      border-top: 8px solid #f2f4f6;
      padding: 18px 16px 0;
    }
    .gp-profile-preview-source p {
      margin: 0;
      color: #8b95a1;
      font-size: 12px;
      font-weight: 600;
      line-height: 1.5;
    }
    .gp-profile-preview-source a {
      margin-left: 2px;
      color: #6b7684;
      text-decoration: underline;
      text-underline-offset: 2px;
    }
    @media (min-width: 700px) {
      .gp-profile-preview { width: min(calc(100% - 48px), 760px); }
      .gp-profile-preview-hero { grid-template-columns: 72px minmax(0, 1fr); padding-bottom: 30px; }
      .gp-profile-preview-logo { width: 72px; height: 72px; }
      .gp-profile-preview-hero h1 { font-size: 28px; }
      .gp-profile-preview-metrics dl { grid-template-columns: repeat(4, minmax(0, 1fr)); }
      .gp-profile-preview-metrics div,
      .gp-profile-preview-metrics div:nth-child(even) { padding: 21px 14px 19px; }
      .gp-profile-preview-metrics div:first-child { padding-left: 0; }
      .gp-profile-preview-metrics div:last-child { padding-right: 0; }
      .gp-profile-preview-metrics div:nth-child(n + 3) { border-top: 0; }
      .gp-profile-preview-metrics div + div { border-left: 1px solid #f2f4f6; }
      .gp-profile-preview-section,
      .gp-profile-preview-source { margin-right: 0; margin-left: 0; padding-right: 0; padding-left: 0; }
      .gp-profile-preview-section { padding-top: 28px; }
      .gp-profile-preview-source { padding-top: 20px; }
    }
  </style>"""


def _gp_sort_key(gp: dict[str, object]) -> tuple[float | int | str, ...]:
    latest_rank = _as_float(gp.get("latest_primary_rank"))
    cumulative_rank = _as_float(gp.get("cumulative_primary_rank"))
    rank_bucket = 0 if latest_rank > 0 else 1 if cumulative_rank > 0 else 2
    rank_value = latest_rank if latest_rank > 0 else cumulative_rank if cumulative_rank > 0 else 999999
    active_funds = _as_float(gp.get("latest_primary_active_fund_count"))
    aum = _as_float(gp.get("latest_primary_aum_proxy_krw_100mn"))
    news_count = _as_float(gp.get("news_count"))
    return (rank_bucket, rank_value, -active_funds, -aum, -news_count, _gp_name(gp))


def _gp_name(gp: dict[str, object]) -> str:
    return (
        _clean(gp.get("display_name"))
        or _clean(gp.get("standard_gp_name"))
        or _clean(gp.get("house_name"))
        or f"GP {gp.get('source_gp_id')}"
    )


def _gp_page_name(source_gp_id: object) -> str:
    safe_id = re.sub(r"[^0-9A-Za-z_-]+", "-", str(source_gp_id)).strip("-")
    return f"gp-{safe_id or 'unknown'}.html"


def _format_rank(value: object) -> str:
    parsed = _as_float(value)
    return f"{int(parsed):,}위" if parsed > 0 else "-"


def _format_int(value: object) -> str:
    parsed = _as_float(value)
    return f"{int(round(parsed)):,}" if parsed > 0 else "-"


def _format_krw_100mn(value: object) -> str:
    parsed = _as_float(value)
    if parsed <= 0:
        return "-"
    if parsed >= 10000:
        return f"{parsed / 10000:,.1f}조"
    return f"{round(parsed):,}억"


def _format_trn_krw_as_100mn(value: object) -> str:
    parsed = _as_float(value)
    return _format_krw_100mn(parsed * 10000) if parsed > 0 else "-"


def _format_pct(value: object) -> str:
    parsed = _as_float(value)
    return f"{parsed:.2f}%" if parsed > 0 else "-"


def _format_date_dot(value: object) -> str:
    text = _short_date(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text.replace("-", ".")
    return text


def _format_period_label(value: object) -> str:
    text = _clean(value)
    matched = re.fullmatch(r"(\d{4})Q([1-4])", text, re.IGNORECASE)
    if matched:
        return f"{matched.group(1)}년 {matched.group(2)}분기"
    return text


def _reporting_period_meta(value: object) -> str:
    period = _clean(value)
    return f'<meta name="kpef-fss-reporting-period" content="{_e(period)}">' if period else ""


def _format_delta(current: object, previous: object, suffix: str = "") -> str:
    current_value = _as_float(current)
    previous_value = _as_float(previous)
    if not current_value or not previous_value:
        return ""
    delta = current_value - previous_value
    if abs(delta) < 0.000001:
        return "전년 동일"
    sign = "+" if delta > 0 else "-"
    return f"전년 대비 {sign}{abs(int(round(delta))):,}{suffix}"


def _format_delta_trn(current_krw_mn: object, previous_krw_mn: object) -> str:
    current_value = _as_float(current_krw_mn)
    previous_value = _as_float(previous_krw_mn)
    if not current_value or not previous_value:
        return ""
    delta_trn = (current_value - previous_value) / 1000000
    if abs(delta_trn) < 0.05:
        return "전년 동일"
    sign = "+" if delta_trn > 0 else "-"
    return f"전년 대비 {sign}{abs(delta_trn):,.1f}조"


def _short_date(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    return text[:10]


def _latest_gp_as_of_date(gps: list[dict[str, object]]) -> str:
    dates = sorted({_short_date(gp.get("latest_as_of_date")) for gp in gps if _short_date(gp.get("latest_as_of_date"))})
    return dates[-1] if dates else ""


def _gp_period_options(gps: list[dict[str, object]]) -> list[tuple[str, str]]:
    periods: dict[str, str] = {}
    for gp in gps:
        metrics = gp.get("period_metrics")
        if isinstance(metrics, dict):
            for period, values in metrics.items():
                if not isinstance(values, dict):
                    continue
                as_of = _short_date(values.get("asOf"))
                if period and as_of:
                    periods[str(period)] = as_of
        latest_period = _clean(gp.get("latest_period_label"))
        latest_as_of = _short_date(gp.get("latest_as_of_date"))
        if latest_period and latest_as_of:
            periods[latest_period] = latest_as_of
    return sorted(periods.items(), key=lambda item: (item[1], item[0]), reverse=True)


def _empty_table_row(message: str) -> str:
    return f"""          <div class="market-row market-empty-row">
            <span>{_e(message)}</span>
          </div>"""


def _profile_summary(gp: dict[str, object]) -> str:
    public_description = _public_firm_description(gp.get("firm_description"))
    if public_description:
        return public_description

    period = _clean(gp.get("latest_period_label")) or _clean(gp.get("last_seen_period"))
    period_prefix = f"{period} 기준 " if period else ""
    facts = []
    latest_rank = _format_rank(gp.get("latest_primary_rank"))
    active_funds = _format_int(gp.get("latest_primary_active_fund_count"))
    aum = _format_krw_100mn(gp.get("latest_primary_aum_proxy_krw_100mn"))
    if latest_rank != "-":
        facts.append(f"최신 순위 {latest_rank}")
    if active_funds != "-":
        facts.append(f"운용중 펀드 {active_funds}개")
    if aum != "-":
        facts.append(f"약정액 기준 {aum}")
    if facts:
        return f"금감원 PEF 운용 현황에서 {period_prefix}{', '.join(facts)}으로 확인됩니다."

    news_count = int(gp.get("news_count") or 0)
    lp_count = int(gp.get("lp_signal_count") or 0)
    if news_count or lp_count:
        parts = []
        if news_count:
            parts.append(f"관련 뉴스 {news_count:,}건")
        if lp_count:
            parts.append(f"출자 연결 {lp_count:,}건")
        return f"공개자료에서 {_join_values(parts)}이 확인됩니다."
    return ""


def _public_firm_description(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    if not re.search(r"[가-힣]", text):
        return ""
    blocked = (
        "작업 큐",
        "검토 대기",
        "보완 필요",
        "프로필 팩트",
        "자동 매칭",
        "데이터 수집",
        "관리자",
        "oper" + "ator",
        "source",
        "evidence",
        "aum proxy",
        "fss_name_only",
    )
    lower = text.lower()
    if any(term in lower for term in blocked):
        return ""
    return text[:220]


def _verification_label(value: object) -> str:
    key = _clean(value)
    normalized_key = re.sub(r"[\s-]+", "_", key).upper()
    if normalized_key == "OFFICIAL_SOURCE_VERIFIED":
        return "공식 자료"
    if normalized_key == "IDENTIFIER_VERIFIED":
        return "법인정보 확인"
    if normalized_key == "MANUAL_VERIFIED":
        return "공개자료 확인"
    if normalized_key == "SUPPORTING_SOURCE_ONLY":
        return "공개자료"
    if normalized_key == "FSS" + "_NAME_ONLY":
        return "운용 현황"
    return ""


def _category_label(value: object) -> str:
    labels = {
        "PE_HOUSE": "PE 운용사",
        "PE_HOUSE_PUBLIC": "상장 PE 운용사",
        "ASSET_MANAGER": "자산운용",
        "SECURITIES": "증권",
        "FINANCIAL_GROUP": "금융그룹",
        "PE_HOUSE_FINANCIAL_GROUP_AFFILIATE": "금융계열 PE",
        "VC": "벤처캐피탈",
        "VC_AND_PE_HOUSE": "PE·VC 운용사",
        "PUBLIC_FINANCIAL_INSTITUTION": "정책금융기관",
        "MULTI_ASSET_ALTERNATIVE_MANAGER": "대체투자 운용사",
        "PRIVATE_CREDIT_MANAGER": "사모대출 운용사",
        "BANK_PUBLIC": "은행",
        "NPL_RESTRUCTURING_AND_PE_MANAGER": "구조조정·PE 운용사",
        "unknown": "",
    }
    key = _clean(value)
    normalized_key = re.sub(r"[\s-]+", "_", key).upper()
    return labels.get(key) or labels.get(normalized_key) or ""


def _lp_event_label(value: object) -> str:
    labels = {
        "candidate": "후보",
        "new_notice": "신규 공고",
        "deadline_soon": "마감 임박",
        "deadline_closed": "접수 마감",
        "shortlist": "숏리스트",
        "final_selection": "최종 선정",
        "revision": "정정",
        "cancellation": "취소",
        "performance_update": "성과 업데이트",
    }
    key = _clean(value)
    return labels.get(key, key.replace("_", " ").title() if key else "공고")


def _fund_status_label(value: object) -> str:
    labels = {
        "active": "운용중",
        "liquidated": "청산완료",
        "closed": "청산완료",
        "dissolved": "청산완료",
    }
    key = _clean(value)
    normalized_key = re.sub(r"[\s-]+", "_", key).lower()
    if normalized_key in {"active_in_latest_" + "fss", "active_in_latest_period"}:
        return "최신 기준 운용중"
    if normalized_key in labels:
        return labels[normalized_key]
    return _public_code_label(value)


def _public_code_label(value: object) -> str:
    text = _clean(value)
    if not text or text == "-":
        return ""
    lower = text.lower()
    if re.search(r"\b(source|evidence|profile|proxy|fss_name_only|unverified)\b", lower):
        return ""
    if "_" in text or re.fullmatch(r"[A-Z0-9_-]+", text):
        return ""
    return text


def _public_source_basis(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    lower = text.lower()
    if "fss quarterly pef status" in lower:
        return "금감원 PEF 운용 현황에서 운용사명, 펀드 연결, 약정액 기준 지표가 확인됩니다. 회사 정보는 별도 공개자료가 있는 경우에만 표시합니다."
    if re.search(r"\b(source|evidence|gp_profile|legal identifiers)\b", text, re.IGNORECASE):
        return "공개자료에서 확인되는 항목만 표시합니다."
    return "공개자료에서 확인되는 항목만 표시합니다."


def _material_basis_note(gp: dict[str, object]) -> str:
    source_basis = _public_source_basis(gp.get("source_basis"))
    if source_basis:
        return source_basis
    sources = []
    if any(
        _format != "-"
        for _format in (
            _format_rank(gp.get("latest_primary_rank")),
            _format_int(gp.get("latest_primary_active_fund_count")),
            _format_krw_100mn(gp.get("latest_primary_aum_proxy_krw_100mn")),
        )
    ):
        sources.append("금감원 PEF 운용 현황")
    if int(gp.get("news_count") or 0):
        sources.append("공개 뉴스")
    if int(gp.get("lp_signal_count") or 0):
        sources.append("LP 공고")
    if any(_clean(gp.get(key)) for key in ("homepage_url", "legal_entity_name_ko", "legal_entity_name_en", "representative_name")):
        sources.append("공개 회사 자료")
    if not sources:
        return ""
    return f"{_join_values(sources)}에서 확인되는 항목 기준입니다."


def _detail_limit_note(gp: dict[str, object]) -> str:
    return (
        "순위와 약정액은 공개 운용 현황 기준이며 실제 순자산이나 미실현 가치를 의미하지 않습니다. "
        "관련 뉴스는 운용사명 기준으로 연결됩니다."
    )


def _is_verified(value: object) -> bool:
    return _clean(value) in {"OFFICIAL_SOURCE_VERIFIED", "IDENTIFIER_VERIFIED", "MANUAL_VERIFIED"}


def _homepage_label(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "") or "홈페이지"


def _safe_url(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return text
    return ""


def _join_values(values: list[object]) -> str:
    parts = [_clean(value) for value in values if _clean(value)]
    return " · ".join(parts)


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _e(value: object) -> str:
    return html.escape(_clean(value), quote=True)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _as_float(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _sort_number(value: object, default: float) -> str:
    parsed = _as_float(value)
    if parsed <= 0:
        parsed = default
    if parsed == int(parsed):
        return str(int(parsed))
    return str(parsed)
