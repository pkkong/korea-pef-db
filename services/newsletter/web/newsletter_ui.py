#!/usr/bin/env python
"""Canonical newsletter UI renderer shared by Vercel and GitHub Pages.

This module owns newsletter HTML; pure presentation assets have one shared source.
Vercel imports it directly and the static Pages builder imports it through
``services.newsletter.src.newsletter_renderer``. Do not create a second
Vercel-only template or stylesheet.
"""

from __future__ import annotations

import json
import struct
import zlib
from datetime import date
from functools import lru_cache
from pathlib import Path

APP_ICON_FILE = "apple-touch-icon.png"

# The same pure asset source is bundled into each independent web app.
try:
    from services.shared.web.service_assets import (
        app_head_meta, app_web_manifest, write_app_icon_assets, app_icon_png,
        make_png, service_css, service_js, app_asset_version,
    )
except ModuleNotFoundError:
    from service_assets import (
        app_head_meta, app_web_manifest, write_app_icon_assets, app_icon_png,
        make_png, service_css, service_js, app_asset_version,
    )







def html_escape(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )

def display_date(report_date: str) -> str:
    return report_date.replace("-", ".")

def weekday_label(report_date: str) -> str:
    try:
        from datetime import date

        parsed = date.fromisoformat(report_date)
    except ValueError:
        return ""
    return ["월", "화", "수", "목", "금", "토", "일"][parsed.weekday()]

DEFAULT_PUBLIC_MIRROR_URL = "https://pkkong.github.io/kpef-newsletter"


def render_app(
    report_date: str,
    articles: list[dict[str, str]],
    basis_text: str = "",
    service_context: dict[str, dict[str, object]] | None = None,
    archive_entries: list[dict[str, object]] | None = None,
    lp_monitor: list[dict[str, object]] | None = None,
    newsletter_only: bool = False,
    service_base_url: str = DEFAULT_PUBLIC_MIRROR_URL,
    gp_url: str | None = None,
    lp_url: str | None = None,
) -> str:
    archive_entries = archive_entries or [
        {
            "reportDate": report_date,
            "visibleDate": display_date(report_date),
            "basis": "",
            "articles": list(articles),
        }
    ]
    payload = json.dumps(archive_entries, ensure_ascii=False).replace("</", "<\\/")
    lp_payload = json.dumps(lp_monitor or [], ensure_ascii=False).replace("</", "<\\/")
    visible_date = display_date(report_date)
    option_rows: list[str] = []
    for entry in archive_entries:
        entry_date = str(entry.get("reportDate", ""))
        entry_articles = entry.get("articles") if isinstance(entry.get("articles"), list) else []
        try:
            article_count = len(entry_articles) if entry_articles else int(entry.get("articleCount") or 0)
        except (TypeError, ValueError):
            article_count = len(entry_articles)
        visible_option_date = str(entry.get("visibleDate", entry_date))
        empty_suffix = " · 발행 없음" if article_count == 0 else ""
        option_rows.append(
            f'          <option value="{html_escape(entry_date)}"'
            f'{" selected" if entry_date == report_date else ""}>'
            f'{html_escape(visible_option_date + empty_suffix)}</option>'
        )
    date_options = "\n".join(option_rows)
    available_dates = [str(entry.get("reportDate", "")) for entry in archive_entries if entry.get("reportDate")]
    min_date = min(available_dates) if available_dates else report_date
    max_date = max(available_dates) if available_dates else report_date
    shell_class = "app-shell newsletter-only" if newsletter_only else "app-shell"
    body_class = ' class="newsletter-page"' if newsletter_only else ""
    product_header = ""
    base_url = str(service_base_url or "").rstrip("/")

    def service_href(path: str) -> str:
        return f"{base_url}/{path}" if base_url else path

    lp_default = "https://kpef-lp.vercel.app/" if newsletter_only else service_href("lp-notices.html")
    lp_notices_href = html_escape(lp_url if lp_url is not None else lp_default)
    gp_default = "https://kpef-gp.vercel.app/gps.html" if newsletter_only else service_href("gps.html")
    gp_href = html_escape(gp_url if gp_url is not None else gp_default)
    lp_db_link = "" if newsletter_only else f'<a href="{lp_notices_href}">LP 목록</a>'
    bottom_db_link = f"""      <a href="{lp_notices_href}">
        <span aria-hidden="true" class="nav-dot nav-icon-lp"></span>
        <strong>LP</strong>
      </a>
      <a href="{gp_href}">
        <span aria-hidden="true" class="nav-dot nav-icon-gp"></span>
        <strong>GP</strong>
      </a>"""
    search_placeholder = "뉴스·기관·운용사 검색" if newsletter_only else "뉴스·공식공고·기관·운용사 검색"
    lp_monitor_section = (
        ""
        if newsletter_only
        else f"""      <section class="lp-monitor-panel" id="lpMonitorPanel" aria-label="공식 출자공고" hidden>
        <div class="lp-monitor-head">
          <h2>공식 출자공고</h2>
          {lp_db_link}
        </div>
        <div class="lp-monitor-list" id="lpMonitorList"></div>
      </section>

"""
    )
    lp_detail_markup = (
        ""
        if newsletter_only
        else """    <div class="lp-detail-backdrop" id="lpDetailBackdrop" hidden></div>
    <section class="lp-detail-sheet" id="lpDetailSheet" aria-label="출자공고 상세" aria-modal="true" role="dialog" hidden>
      <div class="lp-detail-head">
        <span>출자공고 상세</span>
        <button type="button" id="lpDetailClose" aria-label="닫기"></button>
      </div>
      <div id="lpDetailBody"></div>
    </section>

"""
    )
    lp_monitor_script = "" if newsletter_only else f"  <script>window.KPEF_LP_MONITOR = {lp_payload};</script>\n"
    asset_version = app_asset_version()
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Korea PEF Intelligence Daily</title>
{app_head_meta()}
  <link rel="stylesheet" href="assets/service.css?v={asset_version}">
</head>
<body{body_class}>
  <div class="{shell_class}">
{product_header}
    <header class="app-header">
      <div class="service-bar">
        <strong class="service-title">Daily Brief</strong>
        <section class="search-area" id="searchArea" aria-label="기사 검색">
          <label class="search-box">
            <span aria-hidden="true"></span>
            <input id="clipSearch" type="search" placeholder="{html_escape(search_placeholder)}" autocomplete="off">
          </label>
          <button class="search-close" id="searchClose" type="button" aria-label="검색 닫기"></button>
        </section>
        <div class="service-actions" aria-label="브리프 도구">
          <button class="header-icon search-toggle" id="searchToggle" type="button" aria-label="검색 열기" aria-expanded="false"></button>
        </div>
      </div>
      <nav class="brief-section-tabs" aria-label="뉴스레터 메뉴">
        <button class="brief-section-tab active" type="button" aria-current="page">Daily</button>
        <button class="brief-section-tab" type="button" disabled>Weekly</button>
        <button class="brief-section-tab" type="button" disabled>출자공고</button>
      </nav>
      <div class="date-control" aria-label="브리프 날짜 탐색">
        <button class="date-step date-prev" id="datePrev" type="button" aria-label="이전 날짜"></button>
        <div class="date-current">
          <span id="briefDateLabel">{html_escape(visible_date)}</span>
          <small id="briefWeekday">{html_escape(weekday_label(report_date))}</small>
          <input class="date-native" id="briefDateInput" type="date" value="{html_escape(report_date)}" min="{html_escape(min_date)}" max="{html_escape(max_date)}" aria-label="브리프 날짜 선택">
        </div>
        <button class="date-step date-next" id="dateNext" type="button" aria-label="다음 날짜"></button>
      </div>
      <label class="date-label" for="briefDateSelect">브리프 날짜</label>
      <select class="date-select" id="briefDateSelect" aria-label="브리프 날짜 선택">
{date_options}
      </select>
    </header>

    <main class="content-area">
{lp_monitor_section}
      <section id="todayView" class="view active" aria-label="오늘 브리프">
        <div class="skeleton-list" aria-hidden="true">
          <div></div><div></div><div></div>
        </div>
        <p class="result-summary" id="resultSummary" aria-live="polite"></p>
        <div id="todayList"></div>
      </section>

    </main>

{lp_detail_markup}
    <nav class="bottom-nav{' newsletter-only' if newsletter_only else ''}" aria-label="하단 메뉴">
      <button class="active" type="button" data-view="today">
        <span aria-hidden="true" class="nav-dot nav-icon-brief"></span>
        <strong>브리프</strong>
      </button>
{bottom_db_link}
    </nav>
  </div>
  <script>window.KPEF_DAILY_ARCHIVE = {payload};</script>
{lp_monitor_script}  <script src="assets/service.js?v={asset_version}"></script>
</body>
</html>
"""
