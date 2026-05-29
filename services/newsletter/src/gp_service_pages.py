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
PROFILE_NEWS_LIMIT = 12
PROFILE_FUND_LIMIT = 10
PROFILE_LP_SIGNAL_LIMIT = 8
PROFILE_DEAL_SIGNAL_LIMIT = 8
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
            _render_empty_directory(report_date, "GP 공개 정보가 준비되는 중입니다."),
            encoding="utf-8",
        )
        return zero_counts

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        missing_tables = [name for name in REQUIRED_TABLES if not _db_object_exists(conn, name)]
        if missing_tables:
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
  <title>Korea PEF GP 디렉토리</title>
{_app_head_meta()}
  {_base_styles()}
</head>
<body>
  <main class="gp-shell">
    {_render_top_nav(active="gps")}
    <section class="gp-empty">
      <span>GP 디렉토리</span>
      <h1>국내 PEF GP 디렉토리</h1>
      <p>{_e(message)}</p>
      <small>기준일 {_e(report_date)} · 공개 정보가 준비되면 운용사 순위, 펀드 수, 약정액 기준 지표, 관련 뉴스를 이 페이지에 표시합니다.</small>
    </section>
  </main>
  {_render_bottom_nav()}
</body>
</html>
"""


def _render_directory_page(report_date: str, gps: list[dict[str, object]], top_ids: set[str]) -> str:
    cards = "\n".join(_render_gp_card(gp, str(gp["source_gp_id"]) in top_ids) for gp in gps)

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
    {_render_top_nav(active="gps")}
    <header class="gp-hero">
      <div class="gp-hero-copy">
        <span>GP</span>
        <h1>PEF 운용사</h1>
        <p>운용 규모, 펀드 이력, 출자 연결, 관련 뉴스를 한 화면에서 봅니다.</p>
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
          <option value="aum">약정액 기준순</option>
          <option value="funds">운용 중 펀드순</option>
          <option value="cumulative">누적 펀드 수순</option>
          <option value="news">관련 뉴스 많은 순</option>
          <option value="signals">뉴스·출자 연결순</option>
        </select>
        <select id="gpPageSize" aria-label="페이지당 표시">
          <option value="30">30개씩 보기</option>
          <option value="50">50개씩 보기</option>
          <option value="100">100개씩 보기</option>
          <option value="all">전체 보기</option>
        </select>
      </div>
      <div class="gp-filter-row" aria-label="빠른 필터">
        <button class="active" type="button" data-filter="all">전체</button>
        <button type="button" data-filter="active">운용 중</button>
        <button type="button" data-filter="news">뉴스</button>
        <button type="button" data-filter="deal">딜</button>
        <button type="button" data-filter="lp">출자</button>
      </div>
      <p class="gp-control-meta">총 {len(gps):,}개 운용사 · 기준일 {_e(report_date)}</p>
    </section>

    <section class="gp-directory-table" aria-label="GP 목록">
      <div class="gp-directory-head" aria-hidden="true">
        <span></span>
        <span>운용사명</span>
        <span>대표/홈페이지</span>
        <span>순위/약정액</span>
        <span>뉴스/출자</span>
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
</body>
</html>
"""


def _render_gp_card(gp: dict[str, object], has_profile_page: bool) -> str:
    gp_id = str(gp["source_gp_id"])
    name = _gp_name(gp)
    avatar_label = _avatar_label(name)
    latest_rank = _format_rank(gp.get("latest_primary_rank"))
    active_funds = _format_int(gp.get("latest_primary_active_fund_count"))
    aum = _format_krw_100mn(gp.get("latest_primary_aum_proxy_krw_100mn"))
    cumulative_funds = _format_int(gp.get("cumulative_primary_fund_count"))
    news_count = int(gp.get("news_count") or 0)
    deal_count = int(gp.get("deal_news_count") or 0)
    lp_count = int(gp.get("lp_signal_count") or 0)
    representative = _clean(gp.get("representative_name"))
    representative_html = f"<span>대표 {_e(representative)}</span>" if representative else ""
    homepage = _safe_url(gp.get("homepage_url"))
    avatar_markup = _avatar_markup(homepage, avatar_label, name)
    category = _category_label(gp.get("company_category"))
    active_label = "운용 중" if _as_bool(gp.get("active_in_latest_period")) else ""
    profile_url = _gp_page_name(gp_id) if has_profile_page else ""
    title = (
        f'<a href="{_e(profile_url)}">{_e(name)}</a>'
        if profile_url
        else _e(name)
    )
    homepage_link = (
        f'<a href="{_e(homepage)}" target="_blank" rel="noreferrer">홈페이지</a>'
        if homepage
        else ""
    )
    meta_line_html = (
        f"""        <div class="gp-meta-line">
          {representative_html}
          {homepage_link}
        </div>"""
        if representative_html or homepage_link
        else ""
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
    cumulative_sort = _sort_number(gp.get("cumulative_primary_fund_count"), default=0)
    news_sort = news_count
    signal_sort = news_count + deal_count + lp_count
    metric_rows = "\n".join(
        f"          <div><dt>{_e(label)}</dt><dd>{_e(value)}</dd></div>"
        for label, value in [
            ("순위", latest_rank),
            ("운용 중 펀드", active_funds),
            ("약정액 기준", aum),
            ("누적 펀드", cumulative_funds),
        ]
        if value and value != "-"
    )
    metrics_html = (
        f"""        <dl class="gp-metrics">
{metric_rows}
        </dl>"""
        if metric_rows
        else ""
    )
    status_label = _card_status_label(latest_rank, has_profile_page)
    status_html = f"<span>{_e(status_label)}</span>" if status_label else ""
    signal_items = [
        ("뉴스", news_count),
        ("딜", deal_count),
        ("출자", lp_count),
    ]
    signal_strip_html = ""
    if any(count for _, count in signal_items):
        signal_rows = "\n".join(
            f"          <span>{_e(label)} <strong>{count:,}</strong></span>"
            for label, count in signal_items
            if count
        )
        signal_strip_html = f"""        <div class="gp-signal-strip" aria-label="뉴스·출자 연결">
{signal_rows}
        </div>"""

    return f"""      <article class="gp-card"
        data-url="{_e(profile_url)}"
        data-search="{_e(search_blob)}"
        data-active="{1 if _as_bool(gp.get("active_in_latest_period")) else 0}"
        data-news="{1 if news_sort else 0}"
        data-deal="{1 if deal_count else 0}"
        data-lp="{1 if lp_count else 0}"
        data-rank="{rank_sort}"
        data-aum="{aum_sort}"
        data-funds="{active_sort}"
        data-cumulative="{cumulative_sort}"
        data-news-count="{news_sort}"
        data-signals="{signal_sort}">
        {avatar_markup}
        <div class="gp-card-main">
          <div class="gp-card-title">
            {status_html}
            <h2>{title}</h2>
          </div>
          <div class="gp-chips">
            {_render_chip(active_label)}
            {_render_chip(category)}
          </div>
        </div>
{metrics_html}
{signal_strip_html}
{meta_line_html}
      </article>"""


def _render_gp_detail_page(report_date: str, gp: dict[str, object], ranked_gps: list[dict[str, object]]) -> str:
    name = _gp_name(gp)
    homepage = _safe_url(gp.get("homepage_url"))
    logo_url = _favicon_url(homepage)
    avatar_label = _avatar_label(name)
    avatar_tone = _identity_tone(name)
    avatar_class = "gp-detail-logo has-logo" if logo_url else "gp-detail-logo"
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
    fund_rows = _render_fund_rows(gp.get("funds", [])[:PROFILE_FUND_LIMIT])
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
    {_render_top_nav(active="gps")}
    <nav class="gp-breadcrumb" aria-label="경로">
      <a href="gps.html">GP</a>
      <span>{_e(name)}</span>
    </nav>

    <header class="gp-detail-hero">
      <div class="gp-detail-title-head">
        <span class="{avatar_class}" data-tone="{avatar_tone}" aria-hidden="true">{avatar_logo}<span>{_e(avatar_label)}</span></span>
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
      <div><span>운용 중 펀드</span><strong>{_e(_format_int(gp.get("latest_primary_active_fund_count")))}</strong></div>
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
        <h2>펀드 이력</h2>
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
</body>
</html>
"""


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
        ("누적 순위", _format_rank(gp.get("cumulative_primary_rank"))),
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
        return '<p class="gp-empty-note">최신 기준 운용 중 펀드가 공개 자료에서 확인되지 않았습니다.</p>'
    rows = []
    for fund in fund_rows:
        name = _clean(fund.get("fund_name")) or "펀드"
        url = _safe_url(fund.get("latest_source_url"))
        title = f'<a href="{_e(url)}" target="_blank" rel="noreferrer">{_e(name)}</a>' if url else _e(name)
        amount = _format_trn_krw_as_100mn(fund.get("latest_commitment_trn_krw") or fund.get("max_commitment_trn_krw"))
        meta = _join_values(
            [
                _public_code_label(fund.get("fund_type_master")),
                _fund_status_label(fund.get("lifecycle_status")),
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
    safe = _safe_url(url)
    if not safe:
        return ""
    domain = urlparse(safe).netloc.removeprefix("www.")
    return f"https://www.google.com/s2/favicons?domain={_e(domain)}&sz=64"


def _avatar_markup(homepage_url: object, label: str, seed: object) -> str:
    tone = _identity_tone(seed or label)
    logo_url = _favicon_url(homepage_url)
    if logo_url:
        return (
            f'<span class="gp-avatar has-logo" data-tone="{tone}" aria-hidden="true">'
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


def _render_top_nav(active: str = "") -> str:
    return """    <header class="kpef-product-header" aria-label="Korea PEF Intelligence">
      <a class="kpef-product-brand" href="index.html">
        <span class="kpef-brand-mark" aria-hidden="true">K</span>
        <strong>Korea PEF Intelligence</strong>
      </a>
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
    <a href="pef-wiki.html">
      <span aria-hidden="true" class="nav-dot nav-icon-wiki"></span>
      <strong>Wiki</strong>
    </a>
  </nav>"""


def _directory_script() -> str:
    return """  <script>
    (() => {
      const input = document.getElementById("gpSearch");
      const sort = document.getElementById("gpSort");
      const pageSizeSelect = document.getElementById("gpPageSize");
      const list = document.getElementById("gpDirectory");
      const visible = document.getElementById("gpVisibleCount");
      const pagination = document.getElementById("gpPagination");
      const prevPage = document.getElementById("gpPrevPage");
      const nextPage = document.getElementById("gpNextPage");
      const pageState = document.getElementById("gpPageState");
      const buttons = Array.from(document.querySelectorAll("[data-filter]"));
      const cards = Array.from(document.querySelectorAll(".gp-card"));
      let activeFilter = "all";
      let currentPage = 1;
      let orderedCards = [...cards];

      const num = (card, key, fallback = 0) => {
        const value = Number(card.dataset[key]);
        return Number.isFinite(value) ? value : fallback;
      };

      const applySort = () => {
        const mode = sort?.value || "rank";
        orderedCards = [...cards].sort((a, b) => {
          if (mode === "aum") return num(b, "aum") - num(a, "aum");
          if (mode === "funds") return num(b, "funds") - num(a, "funds");
          if (mode === "cumulative") return num(b, "cumulative") - num(a, "cumulative");
          if (mode === "news") return num(b, "newsCount") - num(a, "newsCount");
          if (mode === "signals") return num(b, "signals") - num(a, "signals");
          return num(a, "rank", 999999) - num(b, "rank", 999999);
        });
        orderedCards.forEach((card) => list?.appendChild(card));
      };

      const filterHit = (card) => {
        if (activeFilter === "all") return true;
        return card.dataset[activeFilter] === "1";
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
          const show = filterHit(card) && (!query || haystack.includes(query));
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
      sort?.addEventListener("change", () => {
        applySort();
        apply({ resetPage: true });
      });
      pageSizeSelect?.addEventListener("change", () => apply({ resetPage: true }));
      buttons.forEach((button) => {
        button.addEventListener("click", () => {
          activeFilter = button.dataset.filter || "all";
          buttons.forEach((item) => item.classList.toggle("active", item === button));
          apply({ resetPage: true });
        });
      });
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
    .kpef-product-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      min-height: 54px;
      margin: 0 calc(50% - 50vw);
      padding: calc(max(10px, env(safe-area-inset-top)) + 7px) max(16px, calc((100vw - 1180px) / 2 + 16px)) 11px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,0.96);
      color: var(--text);
      backdrop-filter: blur(18px);
    }
    .kpef-product-brand {
      display: inline-flex;
      min-width: 0;
      align-items: center;
      gap: 9px;
      color: inherit;
      text-decoration: none;
    }
    .kpef-product-brand strong {
      overflow: hidden;
      color: inherit;
      font-size: 16px;
      font-weight: 850;
      line-height: 1.2;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .kpef-brand-mark {
      display: inline-grid;
      width: 28px;
      height: 28px;
      flex: 0 0 28px;
      place-items: center;
      border: 1px solid var(--line);
      border-radius: 50%;
      background: var(--surface-muted);
      color: var(--text);
      font-size: 13px;
      font-weight: 900;
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
      grid-template-columns: repeat(4, minmax(0, 1fr));
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
    .nav-icon-wiki::before {
      -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M5 4.5h10.5A3.5 3.5 0 0 1 19 8v11.5H8.5A3.5 3.5 0 0 1 5 16V4.5Zm4 4h6M9 12h6' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
      mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M5 4.5h10.5A3.5 3.5 0 0 1 19 8v11.5H8.5A3.5 3.5 0 0 1 5 16V4.5Zm4 4h6M9 12h6' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
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
      place-items: center;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 50%;
      background: #fff;
      color: var(--text);
      font-size: 12px;
      font-weight: 900;
      box-shadow: inset 0 0 0 4px #fff;
    }
    .gp-detail-logo::after {
      position: absolute;
      inset: 9px;
      border: 1px solid currentColor;
      border-radius: 50%;
      opacity: 0.16;
      content: "";
    }
    .gp-detail-logo > span {
      position: relative;
      z-index: 1;
    }
    .gp-detail-logo img {
      position: relative;
      z-index: 2;
      max-width: 38px;
      max-height: 38px;
      object-fit: contain;
    }
    .gp-detail-logo.has-logo > span { display: none; }
    .gp-detail-logo.fallback-only > span { display: inline; }
    .gp-detail-logo[data-tone] { border-color: var(--line); background: var(--surface-muted); color: var(--text); }
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
      width: 38px;
      height: 38px;
      grid-column: 1;
      grid-row: 1;
      place-items: center;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 50%;
      background: #fff;
      color: var(--text);
      font-size: 10px;
      font-weight: 900;
      letter-spacing: 0;
      box-shadow: inset 0 0 0 3px #fff;
    }
    .gp-avatar::after {
      position: absolute;
      inset: 7px;
      border: 1px solid currentColor;
      border-radius: 50%;
      opacity: 0.16;
      content: "";
    }
    .gp-avatar > span {
      position: relative;
      z-index: 1;
    }
    .gp-avatar img {
      position: relative;
      z-index: 2;
      max-width: 27px;
      max-height: 27px;
      object-fit: contain;
    }
    .gp-avatar.has-logo > span { display: none; }
    .gp-avatar.fallback-only > span { display: inline; }
    .gp-avatar[data-tone] { border-color: var(--line); background: var(--surface-muted); color: var(--text); }
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
      .kpef-product-header {
        margin: -12px -10px 0;
        padding-right: 16px;
        padding-left: 16px;
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
    a { text-decoration: none; }
    .gp-shell {
      width: min(calc(100% - 28px), var(--shell));
      max-width: 100%;
      padding: max(14px, env(safe-area-inset-top)) 0 calc(88px + env(safe-area-inset-bottom));
    }
    .kpef-product-header {
      min-height: 58px;
      margin: calc(-1 * max(14px, env(safe-area-inset-top))) -14px 0;
      padding: calc(max(14px, env(safe-area-inset-top)) + 8px) 16px 12px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.96);
      color: var(--text);
      box-shadow: none;
      backdrop-filter: blur(18px);
    }
    .kpef-product-brand strong {
      font-size: 16px;
      font-weight: 850;
    }
    .kpef-brand-mark {
      border-color: var(--line);
      border-radius: 50%;
      background: var(--surface-muted);
      color: var(--text);
    }
    .gp-hero,
    .gp-detail-hero {
      display: block;
      margin: 18px 0 14px;
    }
    .gp-hero-copy,
    .gp-detail-hero > div {
      gap: 7px;
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
    .gp-hero-copy p,
    .gp-detail-hero p {
      max-width: 720px;
      color: var(--secondary);
      font-size: 14px;
      line-height: 1.58;
    }
    .gp-control-panel {
      margin: 10px 0 12px;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      padding: 12px 0;
    }
    .gp-control-head {
      font-size: 12px;
      font-weight: 700;
    }
    .gp-controls {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
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
      width: 32px;
      height: 32px;
      margin-top: 2px;
      border-color: var(--line);
      font-size: 10px;
      box-shadow: inset 0 0 0 3px #fff;
    }
    .gp-avatar img {
      max-width: 23px;
      max-height: 23px;
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
      border-color: var(--line);
      box-shadow: inset 0 0 0 4px #fff;
    }
    .gp-detail-logo img {
      max-width: 35px;
      max-height: 35px;
    }
    .gp-detail-card {
      margin-top: 10px;
      color: var(--secondary);
      font-size: 13px;
      font-weight: 650;
    }
    .gp-detail-kpis,
    .gp-signal-bar {
      gap: 0;
      margin: 12px 0;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }
    .gp-detail-kpis div,
    .gp-signal-bar div {
      padding: 12px 0;
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
      font-size: 19px;
      font-weight: 780;
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
      padding: 17px 0;
    }
    .gp-panel h2,
    .gp-disclaimer h2 {
      margin-bottom: 10px;
      font-size: 16px;
      font-weight: 780;
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
      grid-template-columns: repeat(4, minmax(0, 1fr));
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
      .kpef-product-header {
        margin-right: calc((100vw - min(var(--shell), calc(100vw - 48px))) / -2);
        margin-left: calc((100vw - min(var(--shell), calc(100vw - 48px))) / -2);
        padding-right: max(22px, calc((100vw - var(--shell)) / 2 + 22px));
        padding-left: max(22px, calc((100vw - var(--shell)) / 2 + 22px));
      }
      h1 {
        font-size: 32px;
      }
      .gp-hero {
        margin-top: 22px;
        margin-bottom: 16px;
      }
      .gp-controls {
        grid-template-columns: minmax(0, 1fr) 190px 140px;
      }
      .gp-controls input {
        grid-column: auto;
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
        width: 38px;
        height: 38px;
      }
      .gp-avatar img {
        max-width: 27px;
        max-height: 27px;
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
      .kpef-product-header {
        margin-top: calc(-1 * max(14px, env(safe-area-inset-top)));
        margin-right: -14px;
        margin-left: -14px;
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
        return ""
    return text[:10]


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
        facts.append(f"운용 중 펀드 {active_funds}개")
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
        "active": "운용 중",
        "liquidated": "청산",
        "closed": "청산",
        "dissolved": "청산",
    }
    key = _clean(value)
    normalized_key = re.sub(r"[\s-]+", "_", key).lower()
    if normalized_key in {"active_in_latest_" + "fss", "active_in_latest_period"}:
        return "최신 기준 운용 중"
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
