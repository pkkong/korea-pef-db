#!/usr/bin/env python
"""Build public GP directory pages for the newsletter static site."""

from __future__ import annotations

import html
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from daily_news_common import normalize_url


REQUIRED_TABLES = ("gp_profile", "gp_house", "news_entity_link", "news_document")
TOP_GP_PAGE_LIMIT = 120
DIRECTORY_NEWS_LIMIT = 2
DETAIL_NEWS_LIMIT = 12
DETAIL_FUND_LIMIT = 10
DETAIL_LP_SIGNAL_LIMIT = 8
DETAIL_DEAL_SIGNAL_LIMIT = 8
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


def _app_head_meta() -> str:
    return f"""  <meta name="theme-color" content="#111827">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="KPEF Brief">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <link rel="apple-touch-icon" href="{APP_ICON_FILE}">
  <link rel="icon" type="image/png" href="{APP_ICON_FILE}">
  <link rel="manifest" href="site.webmanifest">"""


def write_gp_pages(site_dir: Path, db_path: Path, report_date: str) -> dict[str, int]:
    """Write gps.html and top-GP profile pages into a static site directory."""
    site_dir.mkdir(parents=True, exist_ok=True)
    _remove_stale_gp_pages(site_dir)

    zero_counts = _zero_counts()
    if not db_path.exists():
        (site_dir / "gps.html").write_text(
            _render_empty_directory(report_date, "GP 데이터베이스를 찾을 수 없습니다."),
            encoding="utf-8",
        )
        return zero_counts

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        missing_tables = [name for name in REQUIRED_TABLES if not _db_object_exists(conn, name)]
        if missing_tables:
            (site_dir / "gps.html").write_text(
                _render_empty_directory(
                    report_date,
                    "GP 서비스에 필요한 테이블이 아직 준비되지 않았습니다: "
                    + ", ".join(missing_tables),
                ),
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

        news_by_gp = _read_gp_news(conn)
        funds_by_gp = _read_gp_funds(conn)
        lp_signals_by_gp = _read_lp_signals(conn)
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

        ranked_gps = sorted(gps, key=_gp_sort_key)
        top_gps = ranked_gps[:TOP_GP_PAGE_LIMIT]
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
        WHERE fm.active_in_latest_period = 1
          AND p.source_gp_id IS NOT NULL
        ORDER BY
            p.source_gp_id,
            COALESCE(fm.latest_commitment_trn_krw, fm.max_commitment_trn_krw, 0) DESC,
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
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Korea PEF GP Directory</title>
{_app_head_meta()}
  {_base_styles()}
</head>
<body>
  <main class="gp-shell">
    {_render_top_nav()}
    <section class="gp-empty">
      <span>GP Directory</span>
      <h1>국내 PEF GP 디렉토리</h1>
      <p>{_e(message)}</p>
      <small>기준일 {_e(report_date)} · 데이터가 준비되면 운용사 순위, 펀드 수, AUM proxy, 뉴스 링크를 이 페이지에 표시합니다.</small>
    </section>
  </main>
</body>
</html>
"""


def _render_directory_page(report_date: str, gps: list[dict[str, object]], top_ids: set[str]) -> str:
    active_count = sum(1 for gp in gps if _as_bool(gp.get("active_in_latest_period")))
    verified_count = sum(1 for gp in gps if _is_verified(gp.get("verification_level")))
    news_link_count = sum(int(gp.get("news_count") or 0) for gp in gps)
    deal_signal_count = sum(int(gp.get("deal_news_count") or 0) for gp in gps)
    lp_signal_count = sum(int(gp.get("lp_signal_count") or 0) for gp in gps)
    total_aum = sum(_as_float(gp.get("latest_primary_aum_proxy_krw_100mn")) for gp in gps)
    top20 = [gp for gp in gps if 0 < _as_float(gp.get("latest_primary_rank")) <= 20]
    top20_aum = sum(_as_float(gp.get("latest_primary_aum_proxy_krw_100mn")) for gp in top20)
    cards = "\n".join(_render_gp_card(gp, str(gp["source_gp_id"]) in top_ids) for gp in gps)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Korea PEF GP Directory</title>
{_app_head_meta()}
  {_base_styles()}
</head>
<body>
  <main class="gp-shell">
    {_render_top_nav(active="gps")}
    <header class="gp-hero">
      <div class="gp-hero-copy">
        <span>GP Directory</span>
        <h1>국내 PEF GP 디렉토리</h1>
        <p>금감원 PEF 운용 현황과 공개 뉴스·LP 출자 신호를 기준으로 상위 GP의 규모, 펀드, 관계 신호, 검증수준을 한 화면에서 탐색합니다.</p>
      </div>
      <div class="gp-kpis" aria-label="GP 디렉토리 요약">
        <div><span>전체 GP</span><strong>{len(gps):,}</strong></div>
        <div><span>최신 활동 GP</span><strong>{active_count:,}</strong></div>
        <div><span>상위 20 약정액 proxy</span><strong>{_format_krw_100mn(top20_aum)}</strong></div>
        <div><span>전체 약정액 proxy</span><strong>{_format_krw_100mn(total_aum)}</strong></div>
        <div><span>뉴스/딜 신호</span><strong>{news_link_count:,}/{deal_signal_count:,}</strong></div>
        <div><span>LP 출자 신호</span><strong>{lp_signal_count:,}</strong></div>
      </div>
    </header>

    <section class="gp-control-panel" aria-label="GP 검색 및 필터">
      <div class="gp-control-head">
        <label for="gpSearch">운용사 검색</label>
        <span id="gpVisibleCount">{len(gps):,}개 표시</span>
      </div>
      <div class="gp-controls">
        <input id="gpSearch" type="search" placeholder="운용사명, 대표, 별칭, 뉴스 제목 검색">
        <select id="gpSort" aria-label="정렬">
          <option value="rank">최신 순위순</option>
          <option value="aum">AUM proxy순</option>
          <option value="funds">Active fund count순</option>
          <option value="cumulative">누적 펀드 수순</option>
          <option value="news">최신 뉴스 많은 순</option>
          <option value="signals">관계 신호 많은 순</option>
        </select>
      </div>
      <div class="gp-filter-row" aria-label="빠른 필터">
        <button class="active" type="button" data-filter="all">전체</button>
        <button type="button" data-filter="active">최신 활동</button>
        <button type="button" data-filter="top">상위 프로필</button>
        <button type="button" data-filter="verified">검증 강화</button>
        <button type="button" data-filter="news">뉴스 있음</button>
        <button type="button" data-filter="deal">딜 신호</button>
        <button type="button" data-filter="lp">LP 신호</button>
        <button type="button" data-filter="homepage">홈페이지 있음</button>
      </div>
      <p>상위 20 GP {len(top20):,}개 · 개별 프로필 {len(top_ids):,}개 · 검증 강화 {verified_count:,}개 · 기준일 {_e(report_date)}</p>
    </section>

    <section class="gp-directory" id="gpDirectory" aria-label="GP 목록">
{cards}
    </section>

    <section class="gp-disclaimer" aria-label="데이터 한계">
      <h2>데이터 한계</h2>
      <p>AUM proxy는 금감원 PEF 공시/운용 현황의 약정액 기반 대용치이며 실제 순자산, 미실현 가치, co-GP 지분율을 의미하지 않습니다. 뉴스 링크는 자동 엔티티 매칭 결과라 동명이인·동명 법인 가능성이 있고, 회사 식별정보는 검증수준에 따라 신뢰도가 다릅니다.</p>
    </section>
  </main>
  {_directory_script()}
</body>
</html>
"""


def _render_gp_card(gp: dict[str, object], has_profile_page: bool) -> str:
    gp_id = str(gp["source_gp_id"])
    name = _gp_name(gp)
    latest_rank = _format_rank(gp.get("latest_primary_rank"))
    active_funds = _format_int(gp.get("latest_primary_active_fund_count"))
    aum = _format_krw_100mn(gp.get("latest_primary_aum_proxy_krw_100mn"))
    cumulative_funds = _format_int(gp.get("cumulative_primary_fund_count"))
    news_count = int(gp.get("news_count") or 0)
    deal_count = int(gp.get("deal_news_count") or 0)
    lp_count = int(gp.get("lp_signal_count") or 0)
    fund_signal_count = int(gp.get("active_fund_signal_count") or 0)
    representative = _clean(gp.get("representative_name")) or "대표 미확인"
    homepage = _safe_url(gp.get("homepage_url"))
    verification = _verification_label(gp.get("verification_level"))
    category = _category_label(gp.get("company_category"))
    active_label = "최신 활동" if _as_bool(gp.get("active_in_latest_period")) else "과거 관측"
    top20_label = "상위 20" if 0 < _as_float(gp.get("latest_primary_rank")) <= 20 else ""
    profile_url = _gp_page_name(gp_id) if has_profile_page else ""
    title = (
        f'<a href="{_e(profile_url)}">{_e(name)}</a>'
        if profile_url
        else _e(name)
    )
    homepage_link = (
        f'<a href="{_e(homepage)}" target="_blank" rel="noreferrer">홈페이지</a>'
        if homepage
        else "<span>홈페이지 미확인</span>"
    )
    news_html = _render_compact_news(gp.get("news", [])[:DIRECTORY_NEWS_LIMIT])
    if not news_html:
        news_html = '<p class="gp-no-news">최근 연결 뉴스 없음</p>'
    data_note = _short_limit_note(gp)
    search_blob = " ".join(
        [
            name,
            _clean(gp.get("standard_gp_name")),
            _clean(gp.get("house_name")),
            _clean(gp.get("legal_entity_name_ko")),
            representative,
            _clean(gp.get("alias_names")),
            " ".join(_clean(item.get("title")) for item in gp.get("news", [])),
            " ".join(_clean(item.get("title")) for item in gp.get("lp_signals", [])),
            " ".join(_clean(item.get("lp_name")) for item in gp.get("lp_signals", [])),
            " ".join(_clean(item.get("fund_name")) for item in gp.get("funds", [])),
        ]
    )
    rank_sort = _sort_number(gp.get("latest_primary_rank"), default=999999)
    aum_sort = _sort_number(gp.get("latest_primary_aum_proxy_krw_100mn"), default=0)
    active_sort = _sort_number(gp.get("latest_primary_active_fund_count"), default=0)
    cumulative_sort = _sort_number(gp.get("cumulative_primary_fund_count"), default=0)
    news_sort = news_count
    signal_sort = news_count + deal_count + lp_count

    return f"""      <article class="gp-card"
        data-search="{_e(search_blob)}"
        data-active="{1 if _as_bool(gp.get("active_in_latest_period")) else 0}"
        data-top="{1 if has_profile_page else 0}"
        data-verified="{1 if _is_verified(gp.get("verification_level")) else 0}"
        data-news="{1 if news_sort else 0}"
        data-deal="{1 if deal_count else 0}"
        data-lp="{1 if lp_count else 0}"
        data-homepage="{1 if homepage else 0}"
        data-rank="{rank_sort}"
        data-aum="{aum_sort}"
        data-funds="{active_sort}"
        data-cumulative="{cumulative_sort}"
        data-news-count="{news_sort}"
        data-signals="{signal_sort}">
        <div class="gp-card-main">
          <div class="gp-card-title">
            <span>{_e(latest_rank)} · source {_e(str(gp_id))}</span>
            <h2>{title}</h2>
          </div>
          <div class="gp-chips">
            {_render_chip(top20_label, "strong")}
            <span>{_e(active_label)}</span>
            <span>{_e(verification)}</span>
            <span>{_e(category)}</span>
          </div>
        </div>
        <dl class="gp-metrics">
          <div><dt>순위</dt><dd>{_e(latest_rank)}</dd></div>
          <div><dt>운용중 펀드</dt><dd>{_e(active_funds)}</dd></div>
          <div><dt>약정액 proxy</dt><dd>{_e(aum)}</dd></div>
          <div><dt>누적 펀드</dt><dd>{_e(cumulative_funds)}</dd></div>
        </dl>
        <div class="gp-signal-strip" aria-label="관계 신호">
          <span>뉴스 <strong>{news_count:,}</strong></span>
          <span>딜 <strong>{deal_count:,}</strong></span>
          <span>LP <strong>{lp_count:,}</strong></span>
          <span>펀드 <strong>{fund_signal_count:,}</strong></span>
        </div>
        <div class="gp-meta-line">
          <span>대표 {_e(representative)}</span>
          {homepage_link}
        </div>
        <details class="gp-card-extra">
          <summary>뉴스·데이터 한계</summary>
          <div class="gp-news-mini">
            <strong>최신 뉴스</strong>
            {news_html}
          </div>
          <p class="gp-limit-note">{_e(data_note)}</p>
        </details>
      </article>"""


def _render_gp_detail_page(report_date: str, gp: dict[str, object], ranked_gps: list[dict[str, object]]) -> str:
    gp_id = str(gp["source_gp_id"])
    name = _gp_name(gp)
    homepage = _safe_url(gp.get("homepage_url"))
    homepage_link = (
        f'<a href="{_e(homepage)}" target="_blank" rel="noreferrer">{_e(_homepage_label(homepage))}</a>'
        if homepage
        else "<span>홈페이지 미확인</span>"
    )
    representative = _clean(gp.get("representative_name")) or "대표 미확인"
    description = _clean(gp.get("firm_description")) or (
        "금감원 PEF 운용 현황과 공개 뉴스 매칭을 기준으로 구성한 GP 공개 프로필입니다."
    )
    news_rows = _render_news_timeline(gp.get("news", [])[:DETAIL_NEWS_LIMIT])
    deal_rows = _render_news_timeline(gp.get("deal_news", [])[:DETAIL_DEAL_SIGNAL_LIMIT], empty_label="딜로 분류된 연결 뉴스가 없습니다.")
    fund_rows = _render_fund_rows(gp.get("funds", [])[:DETAIL_FUND_LIMIT])
    lp_signal_rows = _render_lp_signal_rows(gp.get("lp_signals", [])[:DETAIL_LP_SIGNAL_LIMIT])
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
  <title>{_e(name)} GP Profile</title>
{_app_head_meta()}
  {_base_styles()}
</head>
<body>
  <main class="gp-shell">
    {_render_top_nav(active="gps")}
    <nav class="gp-breadcrumb" aria-label="경로">
      <a href="gps.html">GP Directory</a>
      <span>{_e(name)}</span>
    </nav>

    <header class="gp-detail-hero">
      <div>
        <span>GP Profile</span>
        <h1>{_e(name)}</h1>
        <p>{_e(description)}</p>
      </div>
      <aside class="gp-detail-card" aria-label="핵심 정보">
        <strong>{_e(_verification_label(gp.get("verification_level")))}</strong>
        <span>{_e(_category_label(gp.get("company_category")))}</span>
        <span>대표 {_e(representative)}</span>
        {homepage_link}
      </aside>
    </header>

    <section class="gp-detail-kpis" aria-label="운용 지표">
      <div><span>최신 순위</span><strong>{_e(_format_rank(gp.get("latest_primary_rank")))}</strong></div>
      <div><span>운용중 펀드</span><strong>{_e(_format_int(gp.get("latest_primary_active_fund_count")))}</strong></div>
      <div><span>약정액 proxy</span><strong>{_e(_format_krw_100mn(gp.get("latest_primary_aum_proxy_krw_100mn")))}</strong></div>
      <div><span>시장점유율 proxy</span><strong>{_e(_format_pct(gp.get("latest_primary_market_share_pct")))}</strong></div>
      <div><span>누적 펀드</span><strong>{_e(_format_int(gp.get("cumulative_primary_fund_count")))}</strong></div>
      <div><span>누적 약정액 proxy</span><strong>{_e(_format_krw_100mn(gp.get("cumulative_primary_commitment_proxy_krw_100mn")))}</strong></div>
    </section>

    {signal_bar}

    <section class="gp-detail-grid">
      <article class="gp-panel">
        <h2>회사 프로필</h2>
        <dl class="gp-fact-list">
{profile_rows}
        </dl>
      </article>
      <article class="gp-panel">
        <h2>검증수준과 커버리지</h2>
        <dl class="gp-fact-list">
{coverage_rows}
        </dl>
      </article>
    </section>

    <section class="gp-detail-grid gp-detail-lower">
      <article class="gp-panel">
        <h2>운용중 펀드</h2>
        {fund_rows}
      </article>
      <article class="gp-panel">
        <h2>LP 출자·선정 신호</h2>
        {lp_signal_rows}
      </article>
    </section>

    <section class="gp-detail-grid gp-detail-lower">
      <article class="gp-panel">
        <h2>딜 뉴스 신호</h2>
        {deal_rows}
      </article>
      <article class="gp-panel">
        <h2>최신 뉴스 링크</h2>
        {news_rows}
      </article>
    </section>

    <section class="gp-detail-grid gp-detail-lower">
      <article class="gp-panel">
        <h2>같이 볼 상위 GP</h2>
        {peer_rows}
      </article>
      <article class="gp-panel">
        <h2>식별 보조 정보</h2>
        <div class="gp-alias-box">
          <strong>관측 별칭</strong>
          {alias_list}
        </div>
      </article>
    </section>

    <section class="gp-disclaimer" aria-label="데이터 한계">
      <h2>데이터 한계</h2>
      <p>{_e(_detail_limit_note(gp))}</p>
      <p>기준일 {_e(report_date)} · source_gp_id {_e(gp_id)} · 개별 페이지는 최신 순위/AUM/뉴스 기준 상위 {TOP_GP_PAGE_LIMIT:,}개 GP에 한해 생성됩니다.</p>
    </section>
  </main>
</body>
</html>
"""


def _render_profile_facts(gp: dict[str, object], homepage_link: str) -> str:
    facts = [
        ("표준 운용사명", _gp_name(gp)),
        ("법인명", _clean(gp.get("legal_entity_name_ko")) or _clean(gp.get("legal_entity_name_en")) or "-"),
        ("대표", _clean(gp.get("representative_name")) or "-"),
        ("홈페이지", homepage_link, True),
        ("설립", _clean(gp.get("firm_founded_year")) or _clean(gp.get("firm_founded_date")) or _clean(gp.get("established_date")) or "-"),
        ("본점/주소", _clean(gp.get("headquarters_address")) or "-"),
        ("라이선스", _join_values([gp.get("license_type"), gp.get("license_status")]) or "-"),
        ("최신 관측 기간", _clean(gp.get("latest_period_label")) or _clean(gp.get("house_last_seen_period")) or "-"),
    ]
    rows = []
    for item in facts:
        label, value = item[:2]
        raw = bool(item[2]) if len(item) > 2 else False
        rows.append(_fact_row(label, value, raw=raw))
    return "\n".join(rows)


def _render_coverage_facts(gp: dict[str, object]) -> str:
    market_share = _format_pct(gp.get("latest_primary_market_share_pct"))
    facts = [
        ("검증수준", _verification_label(gp.get("verification_level"))),
        ("프로필 상태", _clean(gp.get("profile_status")) or "-"),
        ("최신 랭킹", _format_rank(gp.get("latest_primary_rank"))),
        ("누적 랭킹", _format_rank(gp.get("cumulative_primary_rank"))),
        ("시장점유율 proxy", market_share),
        ("첫 관측", _clean(gp.get("first_seen_period")) or _clean(gp.get("house_first_seen_period")) or "-"),
        ("마지막 관측", _clean(gp.get("last_seen_period")) or _clean(gp.get("house_last_seen_period")) or "-"),
        ("출처 기준", _clean(gp.get("source_basis")) or "-"),
        ("리서치 메모", _join_values([gp.get("research_priority_reason"), gp.get("source_note")]) or "-"),
    ]
    return "\n".join(_fact_row(label, value) for label, value in facts)


def _render_signal_bar(gp: dict[str, object]) -> str:
    news_count = int(gp.get("news_count") or 0)
    deal_count = int(gp.get("deal_news_count") or 0)
    lp_count = int(gp.get("lp_signal_count") or 0)
    fund_count = int(gp.get("active_fund_signal_count") or 0)
    return f"""    <section class="gp-signal-bar" aria-label="관계 신호 요약">
      <div><span>운용 펀드</span><strong>{fund_count:,}</strong><em>최신 활동 기준</em></div>
      <div><span>LP 신호</span><strong>{lp_count:,}</strong><em>공고·선정 링크</em></div>
      <div><span>딜 신호</span><strong>{deal_count:,}</strong><em>뉴스 태그 기준</em></div>
      <div><span>뉴스 링크</span><strong>{news_count:,}</strong><em>자동 GP 매칭</em></div>
    </section>"""


def _render_fund_rows(fund_rows: list[dict[str, object]]) -> str:
    if not fund_rows:
        return '<p class="gp-empty-note">최신 기준 운용중 펀드가 공개 데이터에서 확인되지 않았습니다.</p>'
    rows = []
    for fund in fund_rows:
        name = _clean(fund.get("fund_name")) or "펀드명 미확인"
        url = _safe_url(fund.get("latest_source_url"))
        title = f'<a href="{_e(url)}" target="_blank" rel="noreferrer">{_e(name)}</a>' if url else _e(name)
        amount = _format_trn_krw_as_100mn(fund.get("latest_commitment_trn_krw") or fund.get("max_commitment_trn_krw"))
        meta = _join_values(
            [
                fund.get("fund_type_master"),
                fund.get("lifecycle_status"),
                _short_date(fund.get("established_date")) if fund.get("established_date") else "",
            ]
        )
        rows.append(
            f"""          <article class="gp-fund-row">
            <h3>{title}</h3>
            <span>{_e(amount)}</span>
            <p>{_e(meta or "공개 운용 현황 기준")}</p>
          </article>"""
        )
    return '<div class="gp-fund-list">\n' + "\n".join(rows) + "\n        </div>"


def _render_lp_signal_rows(signal_rows: list[dict[str, object]]) -> str:
    if not signal_rows:
        return '<p class="gp-empty-note">이 GP와 직접 연결된 공개 LP 공고·선정 신호는 아직 없습니다.</p>'
    rows = []
    for signal in signal_rows:
        title = _clean(signal.get("title")) or "LP 출자 신호"
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
        rows.append(
            f"""          <article class="gp-lp-row">
            <span>{_e(date)} · {_e(meta)}</span>
            <h3>{linked_title}</h3>
          </article>"""
        )
    return '<div class="gp-lp-list">\n' + "\n".join(rows) + "\n        </div>"


def _render_compact_news(news_rows: list[dict[str, object]]) -> str:
    if not news_rows:
        return ""
    items = []
    for item in news_rows:
        title = _clean(item.get("title")) or "뉴스"
        url = _safe_url(item.get("source_url"))
        publisher = _clean(item.get("publisher")) or _clean(item.get("source_domain")) or "언론"
        date = _short_date(item.get("published_at") or item.get("discovered_at"))
        linked_title = (
            f'<a href="{_e(url)}" target="_blank" rel="noreferrer">{_e(title)}</a>'
            if url
            else _e(title)
        )
        items.append(f"<p><span>{_e(publisher)} · {_e(date)}</span>{linked_title}</p>")
    return "\n".join(items)


def _render_news_timeline(news_rows: list[dict[str, object]], empty_label: str = "연결된 최신 뉴스가 없습니다.") -> str:
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
        rows.append(
            f"""          <article class="gp-news-row">
            <span>{_e(publisher)} · {_e(date)}</span>
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
        return "<p>별칭 데이터 없음</p>"
    return "<p>" + " ".join(f"<span>{_e(item)}</span>" for item in items[:12]) + "</p>"


def _render_chip(label: str, extra_class: str = "") -> str:
    if not label:
        return ""
    class_attr = f' class="{_e(extra_class)}"' if extra_class else ""
    return f"<span{class_attr}>{_e(label)}</span>"


def _fact_row(label: str, value: object, raw: bool = False) -> str:
    body = str(value) if raw else _e(str(value))
    return f"""          <div>
            <dt>{_e(label)}</dt>
            <dd>{body}</dd>
          </div>"""


def _render_top_nav(active: str = "") -> str:
    gps_class = "active" if active == "gps" else ""
    return f"""    <nav class="gp-top-nav" aria-label="서비스 이동">
      <strong>Korea PEF Intelligence</strong>
      <span>
        <a href="index.html">Daily Brief</a>
        <a href="lp-notices.html">LP 공고</a>
        <a class="{gps_class}" href="gps.html">GP Directory</a>
      </span>
    </nav>"""


def _directory_script() -> str:
    return """  <script>
    (() => {
      const input = document.getElementById("gpSearch");
      const sort = document.getElementById("gpSort");
      const list = document.getElementById("gpDirectory");
      const visible = document.getElementById("gpVisibleCount");
      const buttons = Array.from(document.querySelectorAll("[data-filter]"));
      const cards = Array.from(document.querySelectorAll(".gp-card"));
      let activeFilter = "all";

      const num = (card, key, fallback = 0) => {
        const value = Number(card.dataset[key]);
        return Number.isFinite(value) ? value : fallback;
      };

      const applySort = () => {
        const mode = sort?.value || "rank";
        const sorted = [...cards].sort((a, b) => {
          if (mode === "aum") return num(b, "aum") - num(a, "aum");
          if (mode === "funds") return num(b, "funds") - num(a, "funds");
          if (mode === "cumulative") return num(b, "cumulative") - num(a, "cumulative");
          if (mode === "news") return num(b, "newsCount") - num(a, "newsCount");
          if (mode === "signals") return num(b, "signals") - num(a, "signals");
          return num(a, "rank", 999999) - num(b, "rank", 999999);
        });
        sorted.forEach((card) => list?.appendChild(card));
      };

      const filterHit = (card) => {
        if (activeFilter === "all") return true;
        return card.dataset[activeFilter] === "1";
      };

      const apply = () => {
        const query = (input?.value || "").trim().toLowerCase();
        let count = 0;
        cards.forEach((card) => {
          const haystack = (card.dataset.search || card.innerText || "").toLowerCase();
          const show = filterHit(card) && (!query || haystack.includes(query));
          card.hidden = !show;
          if (show) count += 1;
        });
        if (visible) visible.textContent = `${count.toLocaleString("ko-KR")}개 표시`;
      };

      input?.addEventListener("input", apply);
      sort?.addEventListener("change", () => {
        applySort();
        apply();
      });
      buttons.forEach((button) => {
        button.addEventListener("click", () => {
          activeFilter = button.dataset.filter || "all";
          buttons.forEach((item) => item.classList.toggle("active", item === button));
          apply();
        });
      });
      applySort();
      apply();
    })();
  </script>"""


def _base_styles() -> str:
    return """  <style>
    :root {
      --bg: #f4f6f8;
      --surface: #ffffff;
      --surface-muted: #f8fafb;
      --text: #15202b;
      --secondary: #52616f;
      --tertiary: #7c8792;
      --line: #dce3e8;
      --accent: #1f6b63;
      --accent-soft: #e7f4f1;
      --gold: #aa7b26;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    a { color: inherit; }
    .gp-shell {
      width: min(1240px, calc(100% - 28px));
      margin: 0 auto;
      padding: 18px 0 52px;
    }
    .gp-top-nav {
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 14px;
      padding: 8px 0;
      background: rgba(244, 246, 248, 0.92);
      backdrop-filter: blur(14px);
    }
    .gp-top-nav strong { font-size: 13px; }
    .gp-top-nav span { display: flex; flex-wrap: wrap; gap: 7px; }
    .gp-top-nav a {
      display: inline-flex;
      min-height: 34px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 7px 11px;
      background: var(--surface);
      color: var(--text);
      font-size: 12px;
      font-weight: 750;
      text-decoration: none;
    }
    .gp-top-nav a.active {
      border-color: var(--accent);
      background: var(--accent-soft);
      color: #164c46;
    }
    .gp-hero {
      display: grid;
      gap: 18px;
      align-items: end;
      margin: 10px 0 12px;
    }
    .gp-hero-copy, .gp-detail-hero > div { display: grid; gap: 10px; }
    .gp-hero-copy > span,
    .gp-detail-hero > div > span,
    .gp-empty > span {
      width: fit-content;
      border-left: 3px solid var(--accent);
      padding-left: 8px;
      color: #164c46;
      font-size: 12px;
      font-weight: 850;
    }
    h1 {
      margin: 0;
      color: var(--text);
      font-size: clamp(34px, 5vw, 62px);
      line-height: 1.04;
      letter-spacing: 0;
    }
    .gp-hero-copy p,
    .gp-detail-hero p {
      max-width: 780px;
      margin: 0;
      color: var(--secondary);
      font-size: 15px;
      line-height: 1.65;
    }
    .gp-kpis,
    .gp-detail-kpis {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .gp-kpis div,
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
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }
    .gp-kpis div,
    .gp-detail-kpis div {
      min-width: 0;
      padding: 12px;
    }
    .gp-kpis span,
    .gp-detail-kpis span,
    .gp-fact-list dt {
      display: block;
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 850;
    }
    .gp-kpis strong,
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
      margin: 12px 0;
      padding: 14px;
    }
    .gp-control-head {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      color: var(--secondary);
      font-size: 12px;
      font-weight: 850;
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
      border-radius: 8px;
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
      padding: 7px 10px;
      background: var(--surface);
      color: var(--secondary);
      font-size: 12px;
      font-weight: 850;
      cursor: pointer;
    }
    .gp-filter-row button.active {
      border-color: var(--accent);
      background: var(--accent-soft);
      color: #164c46;
    }
    .gp-control-panel p {
      margin: 0;
      color: var(--secondary);
      font-size: 12px;
      line-height: 1.45;
    }
    .gp-directory {
      display: grid;
      gap: 10px;
    }
    .gp-card {
      display: grid;
      gap: 9px;
      padding: 12px;
    }
    .gp-card[hidden] { display: none; }
    .gp-card-main {
      display: grid;
      gap: 8px;
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
      font-size: 18px;
      line-height: 1.34;
      overflow-wrap: break-word;
      word-break: keep-all;
    }
    .gp-card h2 a { text-decoration: none; }
    .gp-card h2 a:hover { color: var(--accent); }
    .gp-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .gp-chips span {
      border: 1px solid #d7e6e3;
      border-radius: 999px;
      padding: 4px 7px;
      background: #f2faf8;
      color: #164c46;
      font-size: 11px;
      font-weight: 850;
    }
    .gp-chips span.strong {
      border-color: #d7bd78;
      background: #fff7dd;
      color: #725313;
    }
    .gp-metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 7px;
      margin: 0;
    }
    .gp-metrics div {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 7px 8px;
      background: var(--surface-muted);
    }
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
      display: grid;
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
      display: flex;
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
    .gp-news-mini {
      display: grid;
      gap: 6px;
    }
    .gp-card-extra {
      border-top: 1px solid var(--line);
      padding-top: 8px;
    }
    .gp-card-extra summary {
      display: flex;
      min-height: 28px;
      align-items: center;
      justify-content: space-between;
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 850;
      cursor: pointer;
    }
    .gp-card-extra summary::-webkit-details-marker { display: none; }
    .gp-card-extra summary::after {
      content: "";
      width: 8px;
      height: 8px;
      border-right: 1.5px solid currentColor;
      border-bottom: 1.5px solid currentColor;
      transform: rotate(45deg) translateY(-2px);
    }
    .gp-card-extra[open] summary { margin-bottom: 8px; }
    .gp-card-extra[open] summary::after { transform: rotate(225deg) translateY(-2px); }
    .gp-news-mini > strong {
      color: var(--secondary);
      font-size: 11.5px;
      font-weight: 850;
    }
    .gp-news-mini p,
    .gp-no-news,
    .gp-limit-note,
    .gp-empty-note {
      margin: 0;
      color: var(--secondary);
      font-size: 12px;
      line-height: 1.45;
    }
    .gp-news-mini p span {
      display: block;
      margin-bottom: 2px;
      color: var(--tertiary);
      font-size: 11px;
      font-weight: 800;
    }
    .gp-news-mini a,
    .gp-news-row a {
      color: var(--text);
      text-decoration: none;
      font-weight: 800;
    }
    .gp-limit-note {
      border-left: 3px solid #e4c88a;
      padding-left: 8px;
      margin-top: 8px;
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
      padding: 14px;
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
    }
    .gp-signal-bar div {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 11px;
      background: var(--surface);
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
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
      padding: 15px;
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
      .gp-controls { grid-template-columns: minmax(0, 1fr) 210px; }
      .gp-directory { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .gp-card-main { grid-template-columns: minmax(0, 1fr); align-items: start; }
      .gp-detail-hero { grid-template-columns: minmax(0, 1.2fr) minmax(300px, 0.8fr); }
      .gp-detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .gp-detail-lower { grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.75fr); }
    }
    @media (min-width: 1120px) {
      .gp-directory { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 620px) {
      .gp-shell { width: min(100% - 20px, 1240px); padding-top: 12px; }
      .gp-top-nav { align-items: start; flex-direction: column; }
      h1 { font-size: 30px; line-height: 1.08; }
      .gp-hero-copy p,
      .gp-detail-hero p { font-size: 14px; line-height: 1.58; }
      .gp-top-nav span,
      .gp-filter-row {
        width: 100%;
        flex-wrap: nowrap;
        overflow-x: auto;
        padding-bottom: 3px;
      }
      .gp-top-nav a,
      .gp-filter-row button { flex: 0 0 auto; }
      .gp-kpis,
      .gp-detail-kpis,
      .gp-metrics,
      .gp-signal-strip,
      .gp-signal-bar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .gp-peer-row { grid-template-columns: minmax(0, 1fr) 56px; }
      .gp-peer-row span:last-child { display: none; }
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


def _short_date(value: object) -> str:
    text = _clean(value)
    if not text:
        return "날짜 미확인"
    return text[:10]


def _verification_label(value: object) -> str:
    labels = {
        "OFFICIAL_SOURCE_VERIFIED": "공식 출처 검증",
        "IDENTIFIER_VERIFIED": "식별정보 검증",
        "FSS_NAME_ONLY": "이름 기준 매칭",
        "MANUAL_VERIFIED": "수동 검증",
        "UNVERIFIED": "미검증",
    }
    key = _clean(value)
    return labels.get(key, key.replace("_", " ").title() if key else "검증수준 미확인")


def _category_label(value: object) -> str:
    labels = {
        "PE_HOUSE": "PE House",
        "ASSET_MANAGER": "자산운용",
        "SECURITIES": "증권",
        "FINANCIAL_GROUP": "금융그룹",
        "PE_HOUSE_FINANCIAL_GROUP_AFFILIATE": "금융계열 PE",
        "VC": "VC",
        "unknown": "분류 미확인",
    }
    key = _clean(value)
    return labels.get(key, key.replace("_", " ").title() if key else "분류 미확인")


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


def _short_limit_note(gp: dict[str, object]) -> str:
    if _clean(gp.get("source_basis")):
        return "AUM은 약정액 기반 proxy이며, 법인 식별정보는 검증수준을 함께 확인해야 합니다."
    return "공개 공시와 뉴스 매칭 기반 프로필입니다. 실제 운용자산/회사정보는 추가 검증이 필요합니다."


def _detail_limit_note(gp: dict[str, object]) -> str:
    source_basis = _clean(gp.get("source_basis"))
    if source_basis:
        return (
            f"{source_basis} AUM proxy는 실제 NAV/AUM이 아니라 공개 운용 현황 기반 대용치입니다. "
            "뉴스 링크는 자동 매칭 결과라 동일·유사 명칭의 다른 법인이 포함될 수 있습니다."
        )
    return (
        "AUM proxy는 공개 운용 현황 기반 대용치이며 실제 NAV/AUM이 아닙니다. "
        "대표자, 홈페이지, 법인 식별정보와 뉴스 링크는 검증수준에 따라 추가 확인이 필요합니다."
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
