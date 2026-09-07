#!/usr/bin/env python
"""Canonical newsletter UI renderer shared by Vercel and GitHub Pages.

This module must remain the single source for newsletter HTML/CSS/JS chrome.
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

def app_head_meta() -> str:
    return f"""  <meta name="theme-color" content="#eaf7ff">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="KPEF Brief">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <link rel="apple-touch-icon" href="{APP_ICON_FILE}">
  <link rel="icon" type="image/png" href="{APP_ICON_FILE}">
  <link rel="manifest" href="site.webmanifest">"""

def app_web_manifest() -> str:
    payload = {
        "name": "Korea PEF Intelligence",
        "short_name": "KPEF Brief",
        "start_url": "./index.html",
        "scope": "./",
        "display": "standalone",
        "background_color": "#eaf7ff",
        "theme_color": "#eaf7ff",
        "icons": [
            {
                "src": APP_ICON_FILE,
                "sizes": "180x180",
                "type": "image/png",
                "purpose": "any",
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

def write_app_icon_assets(public_dir: Path) -> Path:
    icon_path = public_dir / APP_ICON_FILE
    icon_path.write_bytes(app_icon_png())
    return icon_path

@lru_cache(maxsize=4)
def app_icon_png(size: int = 180) -> bytes:
    scale = 4
    canvas_size = size * scale
    background_top = (236, 249, 255)
    background_mid = (117, 196, 255)
    background_bottom = (25, 103, 220)
    pixels: list[list[tuple[int, int, int, int]]] = []
    for y in range(canvas_size):
        ty = y / max(1, canvas_size - 1)
        row = []
        for x in range(canvas_size):
            tx = x / max(1, canvas_size - 1)
            if ty < 0.58:
                t = ty / 0.58
                base = tuple(round(background_top[i] * (1 - t) + background_mid[i] * t) for i in range(3))
            else:
                t = (ty - 0.58) / 0.42
                base = tuple(round(background_mid[i] * (1 - t) + background_bottom[i] * t) for i in range(3))
            corner_shade = max(0.0, (tx + ty - 1.08)) * 38
            base = tuple(max(0, round(channel - corner_shade)) for channel in base)
            row.append((base[0], base[1], base[2], 255))
        pixels.append(row)

    def mix_pixel(x: int, y: int, color: tuple[int, int, int], alpha: float) -> None:
        if not (0 <= x < canvas_size and 0 <= y < canvas_size):
            return
        alpha = max(0.0, min(1.0, alpha))
        old = pixels[y][x]
        pixels[y][x] = (
            round(old[0] * (1 - alpha) + color[0] * alpha),
            round(old[1] * (1 - alpha) + color[1] * alpha),
            round(old[2] * (1 - alpha) + color[2] * alpha),
            255,
        )

    def radial_glow(
        center: tuple[int, int],
        radius: int,
        color: tuple[int, int, int],
        alpha: float,
    ) -> None:
        cx, cy = (value * scale for value in center)
        scaled_radius = radius * scale
        for y in range(max(0, cy - scaled_radius), min(canvas_size, cy + scaled_radius)):
            for x in range(max(0, cx - scaled_radius), min(canvas_size, cx + scaled_radius)):
                distance = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                if distance >= scaled_radius:
                    continue
                strength = (1 - distance / scaled_radius) ** 2
                mix_pixel(x, y, color, alpha * strength)

    def rounded_rect(
        rect: tuple[int, int, int, int],
        radius: int,
        color: tuple[int, int, int],
        alpha: float = 1.0,
    ) -> None:
        x0, y0, x1, y1 = (value * scale for value in rect)
        scaled_radius = radius * scale
        pad = 3 * scale
        for y in range(max(0, y0 - pad), min(canvas_size, y1 + pad)):
            for x in range(max(0, x0 - pad), min(canvas_size, x1 + pad)):
                nearest_x = min(max(x, x0 + scaled_radius), x1 - scaled_radius)
                nearest_y = min(max(y, y0 + scaled_radius), y1 - scaled_radius)
                distance = ((x - nearest_x) ** 2 + (y - nearest_y) ** 2) ** 0.5 - scaled_radius
                edge_alpha = 1.0 - max(0.0, distance + 1.5 * scale) / (3 * scale)
                if edge_alpha > 0:
                    mix_pixel(x, y, color, alpha * min(1.0, edge_alpha))

    def ellipse(
        center: tuple[int, int],
        radii: tuple[int, int],
        color: tuple[int, int, int],
        alpha: float = 1.0,
    ) -> None:
        cx, cy = (value * scale for value in center)
        rx, ry = (max(1, value * scale) for value in radii)
        pad = 3 * scale
        for y in range(max(0, cy - ry - pad), min(canvas_size, cy + ry + pad)):
            for x in range(max(0, cx - rx - pad), min(canvas_size, cx + rx + pad)):
                normalized = (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2) ** 0.5
                distance = (normalized - 1.0) * min(rx, ry)
                edge_alpha = 1.0 - max(0.0, distance + 1.5 * scale) / (3 * scale)
                if edge_alpha > 0:
                    mix_pixel(x, y, color, alpha * min(1.0, edge_alpha))

    # Cute penguin app icon: soft mobile gradient, simple rounded shapes, and
    # no lettering so it stays readable at iPhone home-screen sizes.
    radial_glow((38, 18), 118, (255, 255, 255), 0.38)
    radial_glow((142, 34), 82, (255, 255, 255), 0.14)
    radial_glow((130, 152), 92, (0, 36, 130), 0.18)
    rounded_rect((15, 15, 165, 165), 41, (255, 255, 255), 0.12)
    rounded_rect((24, 27, 156, 159), 38, (255, 255, 255), 0.10)

    shadow = (0, 45, 139)
    penguin = (16, 31, 58)
    penguin_soft = (30, 48, 82)
    belly = (255, 255, 255)
    belly_soft = (244, 250, 255)
    orange = (255, 173, 50)
    orange_deep = (246, 136, 28)
    blush = (255, 143, 165)

    ellipse((90, 150), (40, 10), shadow, 0.20)
    ellipse((54, 108), (13, 35), penguin_soft, 0.92)
    ellipse((126, 108), (13, 35), penguin_soft, 0.92)
    ellipse((90, 96), (47, 59), penguin, 0.98)
    ellipse((90, 74), (40, 36), penguin, 1.0)
    ellipse((90, 107), (32, 39), belly, 0.98)
    ellipse((90, 76), (29, 27), belly, 0.98)
    ellipse((75, 82), (16, 22), belly_soft, 0.98)
    ellipse((105, 82), (16, 22), belly_soft, 0.98)
    ellipse((75, 76), (4, 5), (10, 22, 42), 1.0)
    ellipse((105, 76), (4, 5), (10, 22, 42), 1.0)
    ellipse((77, 74), (1, 2), (255, 255, 255), 0.92)
    ellipse((107, 74), (1, 2), (255, 255, 255), 0.92)
    ellipse((90, 88), (11, 7), orange, 0.98)
    rounded_rect((82, 88, 98, 94), 5, orange_deep, 0.72)
    ellipse((69, 93), (7, 4), blush, 0.34)
    ellipse((111, 93), (7, 4), blush, 0.34)
    ellipse((73, 145), (18, 7), orange, 0.96)
    ellipse((107, 145), (18, 7), orange, 0.96)
    ellipse((72, 44), (10, 5), (255, 255, 255), 0.22)

    downsampled: list[list[tuple[int, int, int, int]]] = []
    for y in range(size):
        row = []
        for x in range(size):
            total = [0, 0, 0, 0]
            for yy in range(y * scale, (y + 1) * scale):
                for xx in range(x * scale, (x + 1) * scale):
                    pixel = pixels[yy][xx]
                    total[0] += pixel[0]
                    total[1] += pixel[1]
                    total[2] += pixel[2]
                    total[3] += pixel[3]
            area = scale * scale
            row.append(tuple(round(channel / area) for channel in total))  # type: ignore[arg-type]
        downsampled.append(row)

    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in downsampled)
    return make_png(size, size, raw)

def make_png(width: int, height: int, raw_scanlines: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw_scanlines, 9)) + chunk(b"IEND", b"")

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

    lp_notices_href = html_escape(lp_url if lp_url is not None else service_href("lp-notices.html"))
    gp_href = html_escape(gp_url if gp_url is not None else service_href("gps.html"))
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

def service_css() -> str:
    return """@charset "utf-8";
:root {
  --bg: #f7f7f8;
  --surface: #ffffff;
  --surface-muted: #f7f7f8;
  --text: #171717;
  --secondary: #737373;
  --tertiary: #a3a3a3;
  --separator: #e5e5e5;
  --accent: #171717;
  --radius: 18px;
  --shell: 520px;
}
* { box-sizing: border-box; }
html { min-height: 100%; overflow-x: hidden; background: var(--bg); }
body {
  margin: 0;
  min-height: 100%;
  overflow-x: hidden;
  color: var(--text);
  background: var(--bg);
  font-family: Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
}
body.newsletter-page {
  background: var(--surface);
}
a { color: inherit; text-decoration: none; }
button, input { font: inherit; }
.kpef-product-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-height: 58px;
  margin: calc(-1 * max(14px, env(safe-area-inset-top))) -14px 0;
  padding: calc(max(14px, env(safe-area-inset-top)) + 8px) 16px 12px;
  border-bottom: 1px solid var(--separator);
  background: rgba(255, 255, 255, 0.96);
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
  border: 1px solid var(--separator);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  font-weight: 900;
}
.kpef-product-actions {
  display: flex;
  flex: 0 0 auto;
  gap: 10px;
  align-items: center;
}
.kpef-icon-link {
  position: relative;
  display: inline-grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
}
.kpef-icon-search::before {
  content: "";
  width: 16px;
  height: 16px;
  border: 2px solid currentColor;
  border-radius: 50%;
}
.kpef-icon-search::after {
  position: absolute;
  right: 8px;
  bottom: 8px;
  width: 8px;
  height: 2px;
  border-radius: 2px;
  background: currentColor;
  content: "";
  transform: rotate(45deg);
}
.kpef-icon-menu::before,
.kpef-icon-menu::after {
  position: absolute;
  left: 8px;
  width: 18px;
  height: 2px;
  border-radius: 2px;
  background: currentColor;
  content: "";
}
.kpef-icon-menu::before { top: 11px; box-shadow: 0 6px 0 currentColor; }
.kpef-icon-menu::after { top: 23px; }
.kpef-service-tabs {
  display: none;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0 -14px 14px;
  border-bottom: 1px solid var(--separator);
  background: var(--surface);
}
.kpef-service-tabs a {
  display: grid;
  min-height: 46px;
  place-items: center;
  border-bottom: 3px solid transparent;
  color: var(--tertiary);
  font-size: 13px;
  font-weight: 850;
  text-decoration: none;
}
.kpef-service-tabs a.active {
  border-bottom-color: var(--accent);
  color: var(--text);
}
.app-shell {
  width: min(100vw, var(--shell));
  max-width: 100vw;
  min-height: 100vh;
  margin: 0 auto;
  overflow-x: hidden;
  background: var(--bg);
  padding: max(14px, env(safe-area-inset-top)) 14px calc(88px + env(safe-area-inset-bottom));
}
.newsletter-page .app-shell {
  background: var(--surface);
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
.brief-section-tabs {
  display: flex;
  min-height: 36px;
  align-items: center;
  gap: 18px;
  margin: 0 -14px;
  padding: 0 14px;
  border-bottom: 1px solid var(--separator);
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
.date-control {
  display: flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
}
.date-step {
  display: inline-flex;
  width: 36px;
  height: 36px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 50%;
  background: var(--surface);
  color: var(--secondary);
  cursor: pointer;
}
.date-step::before {
  content: "";
  width: 16px;
  height: 16px;
  background: currentColor;
  -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='m15 5-7 7 7 7' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
  mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='m15 5-7 7 7 7' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
}
.date-next::before { transform: rotate(180deg); }
.date-step:disabled {
  opacity: 0.32;
  cursor: default;
}
.date-current {
  position: relative;
  display: grid;
  min-width: 156px;
  height: 40px;
  align-content: center;
  justify-items: center;
  gap: 1px;
  border-radius: 999px;
  background: var(--text);
  color: var(--surface);
  box-shadow: none;
}
.date-current span {
  font-size: 15px;
  line-height: 1.1;
  font-weight: 700;
}
.date-current small {
  color: rgba(255,255,255,0.66);
  font-size: 11px;
  line-height: 1.1;
  font-weight: 500;
}
.date-native {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}
.date-label {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}
.date-select {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}
.date-select:focus {
  box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.16);
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
.header-icon::before {
  content: "";
  width: 18px;
  height: 18px;
  background: currentColor;
}
.service-actions {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.search-toggle::before {
  width: 14px;
  height: 14px;
  border: 2px solid currentColor;
  border-radius: 50%;
  background: transparent;
}
.search-toggle::after {
  content: "";
  position: absolute;
  width: 7px;
  height: 2px;
  right: 10px;
  bottom: 10px;
  border-radius: 2px;
  background: currentColor;
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
.search-area.active { display: flex; }
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
  width: 13px;
  height: 13px;
  border: 2px solid var(--tertiary);
  border-radius: 50%;
  position: relative;
  flex: 0 0 auto;
}
.search-box span::after {
  content: "";
  position: absolute;
  width: 6px;
  height: 2px;
  right: -5px;
  bottom: -3px;
  border-radius: 2px;
  background: var(--tertiary);
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
.search-box input::placeholder { color: #8e8e93; }
.search-close {
  display: inline-flex;
  position: relative;
  flex: 0 0 38px;
  width: 38px;
  height: 38px;
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
  content: "";
  position: absolute;
  width: 16px;
  height: 2px;
  border-radius: 2px;
  background: currentColor;
}
.search-close::before { transform: rotate(45deg); }
.search-close::after { transform: rotate(-45deg); }
.content-area { display: grid; gap: 14px; }
.result-summary {
  min-height: 18px;
  margin: 0 0 8px;
  color: var(--secondary);
  font-size: 12px;
  line-height: 1.45;
  font-weight: 600;
}
.newsletter-only .result-summary {
  margin: 0 0 6px;
}
.lp-monitor-panel {
  display: grid;
  gap: 8px;
  margin: 0 0 2px;
}
.lp-monitor-panel[hidden] { display: none; }
.lp-monitor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 4px;
}
.lp-monitor-head h2 {
  margin: 0;
  color: var(--text);
  font-size: 13px;
  line-height: 1.3;
  font-weight: 650;
}
.lp-monitor-head a {
  color: var(--secondary);
  font-size: 12px;
  font-weight: 650;
}
.lp-monitor-list {
  display: flex;
  gap: 8px;
  margin: 0 -14px;
  padding: 0 14px 4px;
  overflow-x: auto;
  scroll-snap-type: x proximity;
  scrollbar-width: none;
  touch-action: pan-x;
  -webkit-overflow-scrolling: touch;
}
.lp-monitor-list::-webkit-scrollbar { display: none; }
.lp-monitor-list::after {
  content: "";
  flex: 0 0 6px;
}
.lp-monitor-item {
  display: grid;
  flex: 0 0 min(78vw, 342px);
  gap: 6px;
  width: min(78vw, 342px);
  min-height: 92px;
  padding: 11px 12px;
  border: 1px solid var(--separator);
  border-radius: 14px;
  background: var(--surface);
  color: inherit;
  text-align: left;
  cursor: pointer;
  scroll-snap-align: start;
}
.lp-monitor-item:active { background: var(--surface-muted); }
.lp-monitor-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.lp-badge {
  display: inline-flex;
  min-height: 22px;
  align-items: center;
  border-radius: 999px;
  padding: 3px 7px;
  background: var(--surface-muted);
  color: var(--secondary);
  font-size: 11px;
  line-height: 1.2;
  font-weight: 650;
}
.lp-badge.urgent {
  background: #fff2e8;
  color: #a23b00;
}
.lp-badge.official {
  background: #eaf7ee;
  color: #176c35;
}
.lp-monitor-item strong {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  font-size: 14px;
  line-height: 1.34;
  font-weight: 650;
}
.lp-monitor-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 7px;
  color: var(--secondary);
  font-size: 12px;
  line-height: 1.3;
}
.lp-monitor-meta span + span::before {
  content: "·";
  margin-right: 7px;
  color: var(--tertiary);
}
.lp-detail-backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: rgba(0,0,0,0.28);
}
.lp-detail-backdrop[hidden],
.lp-detail-sheet[hidden] { display: none; }
.lp-detail-sheet {
  position: fixed;
  left: 50%;
  bottom: 0;
  z-index: 41;
  display: grid;
  gap: 16px;
  width: min(100%, var(--shell));
  max-height: min(82vh, 720px);
  overflow: auto;
  transform: translateX(-50%);
  padding: 14px 16px calc(18px + env(safe-area-inset-bottom));
  border-radius: 22px 22px 0 0;
  background: var(--surface);
  box-shadow: 0 -18px 60px rgba(0,0,0,0.18);
}
.lp-detail-head {
  position: sticky;
  top: -14px;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 0 8px;
  background: var(--surface);
  color: var(--secondary);
  font-size: 12px;
  font-weight: 650;
}
.lp-detail-head button {
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 50%;
  background: var(--surface-muted);
  color: var(--secondary);
  cursor: pointer;
}
.lp-detail-head button::before {
  content: "×";
  font-size: 22px;
  line-height: 1;
}
.lp-detail-title {
  margin: 0 0 8px;
  color: var(--text);
  font-size: 19px;
  line-height: 1.32;
  font-weight: 700;
}
.lp-detail-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}
.lp-detail-summary span {
  min-height: 24px;
  border-radius: 999px;
  padding: 4px 8px;
  background: var(--surface-muted);
  color: var(--secondary);
  font-size: 12px;
  line-height: 1.3;
  font-weight: 650;
}
.lp-detail-grid {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 10px 12px;
  margin: 0;
  padding: 14px 0;
  border-top: 1px solid var(--separator);
  border-bottom: 1px solid var(--separator);
}
.lp-detail-grid dt {
  color: var(--secondary);
  font-size: 12px;
  line-height: 1.35;
  font-weight: 650;
}
.lp-detail-grid dd {
  margin: 0;
  min-width: 0;
  color: var(--text);
  font-size: 14px;
  line-height: 1.42;
  overflow-wrap: anywhere;
}
.lp-detail-actions,
.lp-attachment-list {
  display: grid;
  gap: 8px;
  margin-top: 14px;
}
.lp-detail-actions a,
.lp-attachment-list a {
  display: flex;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: var(--surface-muted);
  color: var(--text);
  font-size: 13px;
  line-height: 1.3;
  font-weight: 650;
}
.lp-detail-actions a::after,
.lp-attachment-list a::after {
  content: "↗";
  color: var(--tertiary);
  font-size: 14px;
  flex: 0 0 auto;
}
.lp-attachment-title {
  margin: 16px 0 0;
  color: var(--secondary);
  font-size: 12px;
  line-height: 1.3;
  font-weight: 650;
}
.view { display: none; }
.view.active { display: block; }
.section-block { margin: 8px 0 18px; }
.newsletter-only .section-block {
  margin: 0 0 22px;
}
.newsletter-only .section-block + .section-block {
  position: relative;
  margin-top: 18px;
  padding-top: 20px;
}
.newsletter-only .section-block + .section-block::before {
  content: "";
  position: absolute;
  top: 0;
  left: 50%;
  width: 100vw;
  height: 8px;
  transform: translateX(-50%);
  background: #f7f7f8;
}
.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 0;
  padding: 0 0 7px;
  color: var(--text);
  font-size: 13px;
  line-height: 1.3;
  font-weight: 700;
}
.newsletter-only .section-title {
  padding-bottom: 10px;
  font-size: 14.5px;
  font-weight: 700;
}
.cell-list {
  margin: 0;
  padding: 0;
  list-style: none;
  overflow: hidden;
  border-radius: var(--radius);
  background: var(--surface);
}
.newsletter-only .cell-list {
  overflow: visible;
  border-top: 0;
  border-radius: 0;
  background: transparent;
}
.clip-cell {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 12px;
  min-height: 72px;
  align-items: start;
  padding: 10px 10px 10px 10px;
  border-bottom: 1px solid rgba(0,0,0,0.055);
}
.clip-cell:last-child { border-bottom: 0; }
.newsletter-only .clip-cell {
  min-height: 74px;
  padding: 11px 0;
}
.newsletter-only .clip-cell:last-child {
  border-bottom: 0;
}
.publisher-icon {
  display: inline-flex;
  position: relative;
  width: 40px;
  height: 40px;
  align-items: center;
  align-self: start;
  justify-content: center;
  overflow: hidden;
  box-sizing: border-box;
  border: 1px solid var(--logo-border, rgba(216, 223, 234, 0.96));
  border-radius: 50%;
  background: var(--logo-bg, radial-gradient(circle at 32% 18%, #ffffff 0%, #f8fafc 54%, #eef2f7 100%));
  color: var(--text);
  font-size: 11px;
  font-weight: 760;
  letter-spacing: 0;
  margin-top: 1px;
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.96),
    0 1px 2px rgba(15,23,42,0.08);
}
.publisher-icon::before {
  content: "";
  position: absolute;
  inset: 1px;
  z-index: 0;
  border-radius: inherit;
  background:
    radial-gradient(circle at 32% 18%, rgba(255,255,255,0.82), rgba(255,255,255,0) 54%),
    linear-gradient(180deg, rgba(255,255,255,0.34), rgba(255,255,255,0));
  pointer-events: none;
}
.publisher-icon img {
  position: relative;
  z-index: 1;
  width: var(--logo-img-width, 27px);
  height: var(--logo-img-height, 27px);
  border: 0;
  border-radius: 0;
  background: transparent;
  mix-blend-mode: normal;
  object-fit: contain;
}
.publisher-icon.has-logo {
  background: var(--logo-bg, radial-gradient(circle at 32% 18%, #ffffff 0%, #fafbfc 58%, #f0f3f8 100%));
}
.publisher-icon.fallback {
  border-color: #d8e0ea;
  background: radial-gradient(circle at 32% 18%, #ffffff 0%, #f8fafc 52%, #eef2f7 100%);
  color: #263142;
}
.publisher-icon.fallback-only {
  border-color: rgba(8, 77, 196, 0.28);
  background:
    radial-gradient(circle at 28% 18%, rgba(255,255,255,0.48), rgba(255,255,255,0) 44%),
    linear-gradient(145deg, #1688ff 0%, #0a62df 52%, #092f96 100%);
  color: #ffffff;
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.38),
    0 2px 6px rgba(8,77,196,0.22);
}
.publisher-fallback {
  position: relative;
  z-index: 1;
  display: none;
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: currentColor;
  font-size: 10.5px;
  font-weight: 800;
  line-height: 1;
  text-shadow: 0 1px 2px rgba(0,0,0,0.12);
}
.publisher-icon.fallback img { display: none; }
.publisher-icon.fallback .publisher-fallback,
.publisher-icon.fallback-only .publisher-fallback { display: inline-flex; }
.cell-main-wrap { min-width: 0; display: grid; gap: 0; }
.cell-main { min-width: 0; display: block; }
.cell-title {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  color: var(--text);
  font-size: 15px;
  line-height: 1.38;
  font-weight: 600;
  letter-spacing: 0;
}
.cell-summary {
  display: grid;
  overflow: hidden;
  gap: 2px;
  margin: 5px 0 0;
  color: #4f4f52;
  font-size: 12.5px;
  line-height: 1.48;
  font-weight: 400;
  letter-spacing: 0;
}
.cell-summary-line {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.title-badge {
  display: inline-flex;
  min-height: 18px;
  align-items: center;
  margin-right: 5px;
  transform: translateY(-1px);
  border-radius: 5px;
  padding: 2px 5px;
  background: var(--surface-muted);
  color: #525252;
  font-size: 10px;
  line-height: 1.1;
  font-weight: 600;
}
.cell-meta {
  display: flex;
  min-width: 0;
  gap: 6px;
  align-items: center;
  margin-top: 3px;
  color: var(--secondary);
  font-size: 12px;
  line-height: 1.2;
}
.cell-meta span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cell-meta span + span::before {
  content: "·";
  margin-right: 6px;
  color: var(--tertiary);
}
.cell-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  position: relative;
  align-items: center;
  margin-top: 6px;
}
.cell-tags.collapsible {
  padding-right: 44px;
}
.cell-tags.collapsed {
  max-height: 24px;
  overflow: hidden;
}
.cell-tags.expanded {
  max-height: none;
  overflow: visible;
  padding-right: 0;
}
.context-chip {
  display: inline-flex;
  max-width: 100%;
  min-height: 20px;
  align-items: center;
  border: 0;
  border-radius: 999px;
  padding: 2px 7px;
  background: #f5f5f5;
  color: #6f6f73;
  font-size: 11px;
  line-height: 1.2;
  font-weight: 500;
  cursor: pointer;
  text-decoration: none;
}
.lp-chip {
  background: var(--surface-muted);
  color: #5f5f63;
}
.gp-chip {
  background: #f2f5f4;
  color: #4f625e;
}
.context-chip:active { background: #e0e0e6; }
.tag-toggle {
  display: inline-flex;
  min-width: 38px;
  min-height: 20px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 999px;
  padding: 2px 8px;
  background: #f7f7f8;
  color: #5f6368;
  font-size: 11px;
  line-height: 1.2;
  font-weight: 600;
  cursor: pointer;
}
.tag-toggle[hidden] {
  display: none;
}
.cell-tags.collapsed .tag-toggle {
  position: absolute;
  top: 0;
  right: 0;
  box-shadow: -10px 0 12px rgba(255,255,255,0.94);
}
.cell-tags.expanded .tag-toggle {
  background: #f7f7f8;
  color: #5f6368;
}
.empty-state {
  display: none;
  margin-top: 10px;
  padding: 34px 18px;
  border-radius: var(--radius);
  background: var(--surface);
  text-align: center;
}
.empty-state.visible { display: block; }
.newsletter-only .empty-state {
  border-radius: 0;
  background: transparent;
}
.empty-state strong {
  display: block;
  font-size: 16px;
  margin-bottom: 6px;
}
.empty-state span {
  display: block;
  color: var(--secondary);
  font-size: 14px;
  line-height: 1.45;
}
.bottom-nav {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 20;
  display: grid;
  box-sizing: border-box;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  width: 100%;
  max-width: none;
  transform: none;
  padding: 7px 10px calc(7px + env(safe-area-inset-bottom));
  border-top: 1px solid rgba(0,0,0,0.08);
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(18px);
}
.newsletter-only .bottom-nav,
.bottom-nav.newsletter-only { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.bottom-nav button,
.bottom-nav a {
  display: flex;
  min-width: 0;
  overflow: hidden;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  border: 0;
  background: transparent;
  color: var(--secondary);
  font-size: 11px;
  line-height: 1.1;
  cursor: pointer;
}
.bottom-nav strong {
  max-width: 100%;
  overflow: hidden;
  font-weight: 620;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bottom-nav .active { color: var(--text); }
.nav-dot {
  display: inline-flex;
  width: 23px;
  height: 23px;
  align-items: center;
  justify-content: center;
  opacity: 0.68;
}
.nav-dot::before {
  content: "";
  width: 21px;
  height: 21px;
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
.skeleton-list { display: grid; gap: 1px; overflow: hidden; border-radius: var(--radius); background: var(--surface); }
.newsletter-only .skeleton-list {
  border-top: 0;
  border-radius: 0;
  background: transparent;
}
.skeleton-list div {
  height: 72px;
  background: linear-gradient(90deg, #fff, #f5f5f5, #fff);
  background-size: 220% 100%;
  animation: skeleton 1.4s ease-in-out infinite;
}
.newsletter-only .skeleton-list div {
  border-bottom: 1px solid rgba(0,0,0,0.055);
}
.skeleton-list.hidden { display: none; }
@keyframes skeleton {
  0% { background-position: 120% 0; }
  100% { background-position: -120% 0; }
}
@media (max-width: 430px) {
  .date-control { gap: 6px; }
  .date-step {
    width: 36px;
    height: 36px;
  }
  .date-current {
    min-width: min(150px, 42vw);
    height: 40px;
  }
  .bottom-nav {
    padding-right: 8px;
    padding-left: 8px;
  }
}
@media (min-width: 760px) {
  body { background: var(--bg); }
  .app-shell {
    margin-top: 0;
    margin-bottom: 0;
    min-height: calc(100vh - 36px);
    border-radius: 0;
    padding-bottom: calc(106px + env(safe-area-inset-bottom));
    box-shadow: none;
    overflow: visible;
  }
  .kpef-service-tabs {
    display: none;
  }
  .bottom-nav {
    left: 50%;
    right: auto;
    bottom: 18px;
    display: grid;
    width: min(640px, calc(100vw - 96px));
    transform: translateX(-50%);
    border: 1px solid rgba(0,0,0,0.07);
    border-radius: 999px;
    padding: 5px;
    background: rgba(255,255,255,0.96);
    box-shadow: 0 8px 28px rgba(15,23,42,0.08);
  }
  .bottom-nav button,
  .bottom-nav a {
    min-height: 36px;
    flex-direction: row;
    justify-content: center;
    gap: 6px;
    border-radius: 999px;
    font-size: 12px;
  }
  .bottom-nav .active {
    background: #f7f7f8;
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
  .lp-detail-sheet {
    top: 50%;
    bottom: auto;
    max-width: 620px;
    border-radius: 22px;
    transform: translate(-50%, -50%);
    padding-bottom: 18px;
  }
}
@media (min-width: 960px) {
  :root { --shell: 1060px; }
  .app-shell {
    padding-right: 22px;
    padding-left: 22px;
  }
  .app-shell.newsletter-only {
    width: min(calc(100vw - 48px), 1280px);
  }
  .newsletter-only .kpef-service-tabs {
    display: none;
  }
  .newsletter-only .app-header {
    max-width: 900px;
    margin-right: auto;
    margin-left: auto;
  }
  .content-area {
    grid-template-columns: minmax(0, 1fr) 340px;
    gap: 18px;
    align-items: start;
  }
  #todayView {
    grid-column: 1;
    grid-row: 1;
  }
  .lp-monitor-panel {
    grid-column: 2;
    grid-row: 1 / span 2;
    position: sticky;
    top: 18px;
    margin: 8px 0 0;
    max-height: calc(100vh - 126px);
    overflow: auto;
    padding-right: 2px;
  }
  .lp-monitor-head { padding: 0; }
  .lp-monitor-list {
    display: grid;
    gap: 10px;
    margin: 0;
    padding: 0 0 4px;
    overflow: visible;
    scroll-snap-type: none;
  }
  .lp-monitor-list::after { display: none; }
  .lp-monitor-item {
    width: 100%;
    min-height: 0;
    flex: initial;
    scroll-snap-align: none;
    border-width: 0 0 1px;
    border-radius: 0;
    background: transparent;
    padding: 12px 0;
  }
  .newsletter-only .content-area {
    display: block;
    max-width: 900px;
    margin-right: auto;
    margin-left: auto;
  }
  .newsletter-only #todayView {
    grid-column: auto;
    grid-row: auto;
  }
  .newsletter-only #todayList {
    display: block;
  }
  .newsletter-only .section-block {
    margin: 0 0 24px;
  }
  .newsletter-only .bottom-nav,
  .bottom-nav.newsletter-only {
    display: grid;
  }
}
"""

def service_js() -> str:
    return """(() => {
  const archive = Array.isArray(window.KPEF_DAILY_ARCHIVE) ? window.KPEF_DAILY_ARCHIVE : [];
  const lpMonitor = Array.isArray(window.KPEF_LP_MONITOR) ? window.KPEF_LP_MONITOR : [];
  const searchInput = document.getElementById("clipSearch");
  const searchArea = document.getElementById("searchArea");
  const searchToggle = document.getElementById("searchToggle");
  const searchClose = document.getElementById("searchClose");
  const serviceBar = document.querySelector(".service-bar");
  const dateSelect = document.getElementById("briefDateSelect");
  const dateInput = document.getElementById("briefDateInput");
  const dateLabel = document.getElementById("briefDateLabel");
  const weekdayLabel = document.getElementById("briefWeekday");
  const datePrev = document.getElementById("datePrev");
  const dateNext = document.getElementById("dateNext");
  const todayList = document.getElementById("todayList");
  const todayView = document.getElementById("todayView");
  const lpMonitorPanel = document.getElementById("lpMonitorPanel");
  const lpMonitorList = document.getElementById("lpMonitorList");
  const lpDetailBackdrop = document.getElementById("lpDetailBackdrop");
  const lpDetailSheet = document.getElementById("lpDetailSheet");
  const lpDetailBody = document.getElementById("lpDetailBody");
  const lpDetailClose = document.getElementById("lpDetailClose");
  const skeleton = document.querySelector(".skeleton-list");
  const resultSummary = document.getElementById("resultSummary");
  const navItems = [...document.querySelectorAll("[data-view]")];
  const showLpMonitor = lpMonitor.length > 0 && Boolean(lpMonitorPanel);

  const initialParams = new URLSearchParams(window.location.search);
  const queryDate = initialParams.get("date");
  const initialQuery = initialParams.get("q") || "";
  if (searchInput && initialQuery) searchInput.value = initialQuery;
  const initialDate = queryDate || (dateSelect && dateSelect.value) || (dateInput && dateInput.value) || "";
  let activeBrief = archive.find((brief) => brief.reportDate === initialDate) || archive[0] || {
    reportDate: "",
    visibleDate: "",
    basis: "",
    articles: []
  };
  let articles = Array.isArray(activeBrief.articles) ? activeBrief.articles : [];

  const setSearchOpen = (open) => {
    if (!searchArea) return;
    const shouldOpen = Boolean(open || queryText());
    searchArea.classList.toggle("active", shouldOpen);
    if (serviceBar) serviceBar.classList.toggle("search-open", shouldOpen);
    if (searchToggle) searchToggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
    if (shouldOpen) window.requestAnimationFrame(() => searchInput && searchInput.focus());
  };

  const queryText = () => (searchInput ? searchInput.value.trim().toLowerCase() : "");

  const formatCount = (value) => Number(value || 0).toLocaleString("ko-KR");

  const issueArticleCount = (brief) => {
    const rows = Array.isArray(brief?.articles) ? brief.articles : [];
    if (rows.length) return rows.length;
    const count = Number(brief?.articleCount);
    return Number.isFinite(count) && count > 0 ? count : 0;
  };

  const syncSearchUrl = () => {
    const url = new URL(window.location.href);
    const value = searchInput ? searchInput.value.trim() : "";
    if (value) url.searchParams.set("q", value);
    else url.searchParams.delete("q");
    if (activeBrief.reportDate) url.searchParams.set("date", activeBrief.reportDate);
    window.history.replaceState({}, "", url);
  };

  const textMatches = (values, query) => {
    if (!query) return true;
    return values
      .filter((value) => value !== null && value !== undefined)
      .join(" ")
      .toLowerCase()
      .includes(query);
  };

  const allArchiveArticles = () => {
    const byUrl = new Map();
    const briefs = archive.length ? archive : [{
      reportDate: activeBrief.reportDate,
      visibleDate: activeBrief.visibleDate,
      articles: []
    }];
    briefs.forEach((brief) => {
      const rows = Array.isArray(brief.articles) ? brief.articles : [];
      rows.forEach((article) => {
        if (!article.url || byUrl.has(article.url)) return;
        byUrl.set(article.url, {
          ...article,
          reportDate: brief.reportDate,
          visibleDate: brief.visibleDate
        });
      });
    });
    return [...byUrl.values()];
  };

  const weekdayName = (dateText) => {
    const date = new Date(`${dateText}T00:00:00+09:00`);
    if (Number.isNaN(date.getTime())) return "";
    return ["일", "월", "화", "수", "목", "금", "토"][date.getDay()];
  };

  const activeBriefIndex = () => archive.findIndex((brief) => brief.reportDate === activeBrief.reportDate);

  const setBriefByOffset = (offset) => {
    const index = activeBriefIndex();
    if (index < 0) return;
    const next = archive[index + offset];
    if (next) setActiveBrief(next.reportDate);
  };

  const updateDateControl = () => {
    const index = activeBriefIndex();
    const activeCount = issueArticleCount(activeBrief);
    if (dateInput) dateInput.value = activeBrief.reportDate || "";
    if (dateLabel) dateLabel.textContent = activeBrief.visibleDate || activeBrief.reportDate || "";
    if (weekdayLabel) weekdayLabel.textContent = activeBrief.reportDate ? (activeCount > 0 ? weekdayName(activeBrief.reportDate) : "발행 없음") : "";
    if (datePrev) datePrev.disabled = index < 0 || index >= archive.length - 1;
    if (dateNext) dateNext.disabled = index <= 0;
  };

  const updateBriefChrome = () => {
    articles = Array.isArray(activeBrief.articles) ? activeBrief.articles : [];
    if (dateSelect) dateSelect.value = activeBrief.reportDate || "";
    updateDateControl();
  };

  const setActiveBrief = (reportDate, options = {}) => {
    const next = archive.find((brief) => brief.reportDate === reportDate);
    if (!next) return;
    activeBrief = next;
    updateBriefChrome();
    render();
    if (options.updateUrl !== false && activeBrief.reportDate) {
      const url = new URL(window.location.href);
      url.searchParams.set("date", activeBrief.reportDate);
      window.history.replaceState({}, "", url);
    }
  };

  const articleSearchValues = (article) => [
    article.title,
    article.summaryText,
    article.source,
    article.section,
    article.subCategory,
    article.rawSection,
    article.visibleDate,
    article.reportDate,
    Array.isArray(article.gpNames) ? article.gpNames.join(" ") : "",
    Array.isArray(article.lpNames) ? article.lpNames.join(" ") : "",
    Array.isArray(article.searchTerms) ? article.searchTerms.join(" ") : ""
  ];

  const articleMatches = (article, query) => textMatches(articleSearchValues(article), query);

  const filtered = () => {
    const query = queryText();
    const sourceRows = query ? allArchiveArticles() : articles;
    if (!query) return sourceRows;
    return sourceRows.filter((article) => articleMatches(article, query));
  };

  const updateResultSummary = (items) => {
    if (!resultSummary) return;
    const query = queryText();
    const visibleDate = activeBrief.visibleDate || activeBrief.reportDate || "";
    if (query) {
      resultSummary.textContent = `전체 아카이브 검색 · ${formatCount(items.length)}건`;
      return;
    }
    const activeCount = issueArticleCount(activeBrief);
    if (activeCount > 0) {
      resultSummary.textContent = `${visibleDate} · 기사 ${formatCount(activeCount)}건`;
      return;
    }
    resultSummary.textContent = visibleDate ? `${visibleDate} · 발행 없음` : "브리프 준비 중";
  };

  const filteredLpMonitor = () => {
    if (!showLpMonitor) return [];
    const query = queryText();
    if (!query) return lpMonitor;
    return lpMonitor.filter((item) => textMatches([
      item.title,
      item.displayTitle,
      item.lpName,
      item.programName,
      item.roundName,
      item.purpose,
      item.strategy,
      item.defaultTeam,
      eventLabel(item.eventType),
      assetClassLabel(item.assetClass),
      amountLabel(item.allocationAmount),
      item.announcedDate,
      item.applicationDeadline,
      Array.isArray(item.selectedGpNames) ? item.selectedGpNames.join(" ") : ""
    ], query));
  };

  const issueStopwords = new Set([
    "단독", "인터뷰", "인수", "매각", "매물", "품는다", "사들인다", "추진", "마무리", "엑시트",
    "리캡", "인수금융", "우선협상", "입찰", "지분", "지분매각", "회수", "전망", "기대감", "언급",
    "신규", "최종", "공식", "전략", "전문", "국내", "해외", "업계"
  ]);

  const issueTokens = (article) => {
    const text = [
      article.title,
      Array.isArray(article.gpNames) ? article.gpNames.join(" ") : "",
      Array.isArray(article.lpNames) ? article.lpNames.join(" ") : ""
    ].join(" ");
    return new Set(
      text
        .toLowerCase()
        .replace(/[()[\\]'"“”‘’….,·:：]/g, " ")
        .split(/\\s+/)
        .map((token) => token.trim())
        .filter((token) => token.length >= 2 && !issueStopwords.has(token))
    );
  };

  const issueOverlap = (left, right) => {
    if (left.section !== right.section) return 0;
    const a = issueTokens(left);
    const b = issueTokens(right);
    let score = 0;
    a.forEach((token) => {
      if (b.has(token)) score += 1;
    });
    return score;
  };

  const clusterOrder = (items) => {
    const remaining = items.slice().sort((a, b) => (a.sectionOrder - b.sectionOrder) || ((a.rank || 0) - (b.rank || 0)));
    const ordered = [];
    while (remaining.length) {
      const seed = remaining.shift();
      ordered.push(seed);
      for (let index = 0; index < remaining.length; index += 1) {
        if (issueOverlap(seed, remaining[index]) >= 2) {
          ordered.push(remaining.splice(index, 1)[0]);
          index -= 1;
        }
      }
    }
    return ordered;
  };

  const groupBySection = (items) => {
    const groups = new Map();
    clusterOrder(items).forEach((article) => {
      if (!groups.has(article.section)) groups.set(article.section, []);
      groups.get(article.section).push(article);
    });
    return groups;
  };

  const eventLabel = (value) => ({
    new_notice: "신규 공고",
    deadline_soon: "마감 임박",
    deadline_closed: "마감",
    shortlist: "숏리스트",
    final_selection: "최종 선정",
    revision: "정정",
    cancellation: "취소",
    performance_update: "성과"
  }[value] || "공고");

  const amountLabel = (value) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return "";
    if (parsed >= 10000) return `${(parsed / 10000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}조`;
    return `${Math.round(parsed).toLocaleString("ko-KR")}억`;
  };

  const assetClassLabel = (value) => {
    const text = String(value || "");
    if (/private credit|credit|크레딧/i.test(text)) return "Credit";
    if (/vc|벤처/i.test(text)) return "VC";
    if (/pe|buyout|private equity|사모/i.test(text)) return "PE";
    return text;
  };

  const daysUntil = (dateText) => {
    if (!dateText) return null;
    const today = new Date();
    const target = new Date(`${dateText}T23:59:59+09:00`);
    if (Number.isNaN(target.getTime())) return null;
    return Math.ceil((target.getTime() - today.getTime()) / 86400000);
  };

  const deadlineBadge = (dateText) => {
    if (!dateText) return null;
    const remaining = daysUntil(dateText);
    if (remaining === null) return { label: "마감일 확인", urgent: false };
    if (remaining > 0) return { label: `D-${remaining}`, urgent: remaining <= 7 };
    if (remaining === 0) return { label: "오늘 마감", urgent: true };
    return { label: "마감", urgent: false };
  };

  const lpMonitorBadges = (item) => {
    const badges = [];
    const deadline = deadlineBadge(item.applicationDeadline);
    if (deadline) badges.push({ ...deadline, type: "deadline" });
    const amount = amountLabel(item.allocationAmount);
    if (amount) badges.push({ label: amount, type: "amount", urgent: false });
    const assetClass = assetClassLabel(item.assetClass);
    if (assetClass) badges.push({ label: assetClass, type: "asset", urgent: false });
    badges.push({ label: "공식", type: "official", urgent: false });
    return badges;
  };

  const scheduleLabel = (item) => {
    if (item.applicationDeadline) {
      const remaining = daysUntil(item.applicationDeadline);
      if (remaining === null) return `신청 마감 ${item.applicationDeadline}`;
      if (remaining > 0) return `신청 마감 ${item.applicationDeadline} · D-${remaining}`;
      if (remaining === 0) return `신청 마감 ${item.applicationDeadline} · 오늘 마감`;
      return `신청 마감 ${item.applicationDeadline} · 마감`;
    }
    if (item.eventDate) return `공고 확인 ${item.eventDate}`;
    return "공식 공고 확인";
  };

  const detailValue = (value, fallback = "-") => {
    if (Array.isArray(value)) return value.filter(Boolean).join(", ") || fallback;
    const text = String(value || "").trim();
    return text || fallback;
  };

  const appendDetailRow = (list, label, value) => {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = detailValue(value);
    list.append(dt, dd);
  };

  const openLpDetail = (item) => {
    if (!lpDetailSheet || !lpDetailBody || !lpDetailBackdrop) return;
    lpDetailBody.replaceChildren();

    const title = document.createElement("h3");
    title.className = "lp-detail-title";
    title.textContent = item.displayTitle || item.title;

    const summary = document.createElement("div");
    summary.className = "lp-detail-summary";
    [item.lpName, eventLabel(item.eventType), assetClassLabel(item.assetClass), amountLabel(item.allocationAmount)]
      .filter(Boolean)
      .forEach((label) => {
        const chip = document.createElement("span");
        chip.textContent = label;
        summary.append(chip);
      });

    const details = document.createElement("dl");
    details.className = "lp-detail-grid";
    appendDetailRow(details, "사업명", item.programName || item.displayTitle || item.title);
    appendDetailRow(details, "기관", item.lpName);
    appendDetailRow(details, "주목적", item.purpose || item.strategy || item.programName);
    appendDetailRow(details, "PE/VC 분류", assetClassLabel(item.assetClass));
    appendDetailRow(details, "담당자/팀", item.defaultTeam);
    appendDetailRow(details, "공고일", item.announcedDate || item.eventDate);
    appendDetailRow(details, "마감일", item.applicationDeadline);
    appendDetailRow(details, "향후 일정", scheduleLabel(item));

    const actions = document.createElement("div");
    actions.className = "lp-detail-actions";
    const official = document.createElement("a");
    official.href = item.url;
    official.target = "_blank";
    official.rel = "noreferrer";
    official.textContent = "공식 공고 보기";
    actions.append(official);

    lpDetailBody.append(title, summary, details, actions);

    const attachments = Array.isArray(item.attachments) ? item.attachments.filter((file) => file && file.url) : [];
    if (attachments.length) {
      const attachmentTitle = document.createElement("h4");
      attachmentTitle.className = "lp-attachment-title";
      attachmentTitle.textContent = "공식 첨부파일";
      const list = document.createElement("div");
      list.className = "lp-attachment-list";
      attachments.forEach((file, index) => {
        const link = document.createElement("a");
        link.href = file.url;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = file.name || `공식 첨부파일 ${index + 1}`;
        list.append(link);
      });
      lpDetailBody.append(attachmentTitle, list);
    }

    lpDetailBackdrop.hidden = false;
    lpDetailSheet.hidden = false;
    document.body.style.overflow = "hidden";
  };

  const closeLpDetail = () => {
    if (!lpDetailSheet || !lpDetailBackdrop) return;
    lpDetailSheet.hidden = true;
    lpDetailBackdrop.hidden = true;
    document.body.style.overflow = "";
  };

  const renderLpMonitor = (items = lpMonitor) => {
    if (!lpMonitorPanel || !lpMonitorList) return;
    const visibleItems = items;
    lpMonitorPanel.hidden = !visibleItems.length;
    lpMonitorList.replaceChildren();
    const headTitle = lpMonitorPanel.querySelector(".lp-monitor-head h2");
    if (headTitle) headTitle.textContent = `공식 공고 ${items.length}건`;
    visibleItems.forEach((item) => {
      const link = document.createElement("button");
      link.type = "button";
      link.className = "lp-monitor-item";
      link.addEventListener("click", () => openLpDetail(item));

      const badges = document.createElement("span");
      badges.className = "lp-monitor-badges";
      lpMonitorBadges(item).forEach((badge) => {
        const pill = document.createElement("span");
        pill.className = `lp-badge ${badge.type || ""} ${badge.urgent ? "urgent" : ""}`.trim();
        pill.textContent = badge.label;
        badges.append(pill);
      });

      const title = document.createElement("strong");
      title.textContent = item.displayTitle || item.title;

      const meta = document.createElement("span");
      meta.className = "lp-monitor-meta";
      [item.lpName, eventLabel(item.eventType), item.applicationDeadline && `마감 ${item.applicationDeadline}`]
        .filter(Boolean)
        .forEach((label) => {
          const part = document.createElement("span");
          part.textContent = label;
          meta.append(part);
        });
      link.append(badges, title, meta);
      lpMonitorList.append(link);
    });
  };

  const makeCell = (article) => {
    const item = document.createElement("li");
    item.className = "clip-cell";

    const mark = document.createElement("span");
    mark.className = "publisher-icon";
    mark.setAttribute("aria-label", article.source || "언론사");
    if (article.sourceIconStyle) mark.setAttribute("style", article.sourceIconStyle);
    const fallback = document.createElement("span");
    fallback.className = "publisher-fallback";
    fallback.textContent = article.sourceBadge || "뉴";
    if (article.sourceIconUrl) {
      mark.classList.add("has-logo");
      const icon = document.createElement("img");
      icon.src = article.sourceIconUrl;
      icon.alt = "";
      icon.loading = "lazy";
      icon.addEventListener("error", () => mark.classList.add("fallback"));
      mark.append(icon, fallback);
    } else {
      mark.classList.add("fallback-only");
      mark.append(fallback);
    }

    const main = document.createElement("div");
    main.className = "cell-main-wrap";

    const link = document.createElement("a");
    link.className = "cell-main";
    link.href = article.url;
    link.target = "_blank";
    link.rel = "noreferrer";

    const title = document.createElement("span");
    title.className = "cell-title";
    const titleBadges = Array.isArray(article.titleBadges) ? article.titleBadges.filter(Boolean) : [];
    titleBadges.forEach((label) => {
      const badge = document.createElement("span");
      badge.className = "title-badge";
      badge.textContent = label;
      title.append(badge);
    });
    const titleText = document.createElement("span");
    titleText.textContent = article.title;
    title.append(titleText);

    const summaryLines = Array.isArray(article.summaryLines)
      ? article.summaryLines.map((line) => String(line || "").trim()).filter(Boolean).slice(0, 3)
      : [];
    const summaryText = summaryLines.length ? "" : String(article.summaryText || "").trim();
    let summary = null;
    if (summaryLines.length || summaryText) {
      summary = document.createElement("span");
      summary.className = "cell-summary";
      if (summaryLines.length) {
        summaryLines.forEach((line) => {
          const item = document.createElement("span");
          item.className = "cell-summary-line";
          item.textContent = line;
          summary.append(item);
        });
      } else {
        summary.textContent = summaryText;
      }
    }

    const meta = document.createElement("span");
    meta.className = "cell-meta";
    const source = document.createElement("span");
    source.textContent = article.source || "출처 미확인";
    const articleDate = article.visibleDate || article.reportDate || "";
    if (articleDate && (queryText() || article.reportDate !== activeBrief.reportDate)) {
      const date = document.createElement("span");
      date.className = "article-date-meta";
      date.textContent = articleDate;
      meta.append(date);
    }
    meta.append(source);
    link.append(title);
    if (summary) link.append(summary);
    link.append(meta);
    main.append(link);

    const chips = document.createElement("span");
    chips.className = "cell-tags";
    const appendChip = (label, extraClass = "") => {
      if (!label) return;
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `context-chip ${extraClass}`.trim();
      chip.dataset.filter = label;
      chip.textContent = label;
      chips.append(chip);
    };
    const appendLinkChip = (label, href, extraClass = "") => {
      if (!label || !href) return;
      const chip = document.createElement("a");
      chip.className = `context-chip ${extraClass}`.trim();
      chip.href = href;
      chip.textContent = label;
      chips.append(chip);
    };
    const lpLinks = Array.isArray(article.lpProfileLinks) ? article.lpProfileLinks.filter((item) => item && item.name && item.url) : [];
    const lpLinkedNames = new Set(lpLinks.map((item) => item.name));
    lpLinks.forEach((item) => appendLinkChip(item.name, item.url, "lp-chip"));
    const lpNames = Array.isArray(article.lpNames) ? article.lpNames.filter(Boolean) : [];
    lpNames.filter((name) => !lpLinkedNames.has(name)).forEach((name) => appendChip(name, "lp-chip"));
    const gpLinks = Array.isArray(article.gpProfileLinks) ? article.gpProfileLinks.filter((item) => item && item.name && item.url) : [];
    const gpLinkedNames = new Set(gpLinks.map((item) => item.name));
    gpLinks.forEach((item) => appendLinkChip(item.name, item.url, "gp-chip"));
    const gpNames = Array.isArray(article.gpNames) ? article.gpNames.filter(Boolean) : [];
    gpNames.filter((name) => !gpLinkedNames.has(name)).forEach((name) => appendChip(name, "gp-chip"));
    if (chips.childElementCount) {
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "tag-toggle";
      toggle.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      chips.append(toggle);
      main.append(chips);
    }

    item.append(mark, main);
    return item;
  };

  const updateTagGroup = (group) => {
    const toggle = group.querySelector(".tag-toggle");
    if (!toggle) return;
    const chips = [...group.children].filter((child) => !child.classList.contains("tag-toggle"));
    group.classList.remove("collapsible", "collapsed", "expanded");
    group.style.maxHeight = "";
    toggle.hidden = true;
    if (chips.length < 2) {
      group.dataset.expanded = "0";
      return;
    }
    const firstTop = chips[0]?.offsetTop ?? 0;
    const hiddenCount = chips.filter((chip) => chip.offsetTop > firstTop + 2).length;
    if (hiddenCount <= 0) {
      group.dataset.expanded = "0";
      return;
    }
    const expanded = group.dataset.expanded === "1";
    group.classList.add("collapsible", expanded ? "expanded" : "collapsed");
    toggle.hidden = false;
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    toggle.textContent = expanded ? "접기" : `더보기 ${hiddenCount}`;
    toggle.setAttribute("aria-label", expanded ? "태그 접기" : `숨긴 태그 ${hiddenCount}개 더 보기`);
  };

  const updateTagGroups = () => {
    document.querySelectorAll(".cell-tags").forEach(updateTagGroup);
  };

  const renderGrouped = (target, items) => {
    target.replaceChildren();
    const groups = groupBySection(items);
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state visible";
      const visibleDate = activeBrief.visibleDate || activeBrief.reportDate || "선택한 날짜";
      empty.innerHTML = queryText()
        ? "<strong>검색 결과가 없습니다</strong><span>다른 기관명, 운용사명, 기사 키워드로 확인합니다.</span>"
        : `<strong>발행 없음</strong><span>${visibleDate}에는 공개된 브리프가 없습니다.</span>`;
      target.append(empty);
      return;
    }
    groups.forEach((groupItems, section) => {
      const block = document.createElement("section");
      block.className = "section-block";
      block.dataset.sectionName = section || "뉴스";
      const title = document.createElement("h2");
      title.className = "section-title";
      title.textContent = section || "뉴스";
      const list = document.createElement("ul");
      list.className = "cell-list";
      groupItems.forEach((article) => list.append(makeCell(article)));
      block.append(title, list);
      target.append(block);
    });
    requestAnimationFrame(updateTagGroups);
  };

  const render = () => {
    if (skeleton) skeleton.classList.add("hidden");
    const newsItems = filtered();
    const noticeItems = filteredLpMonitor();
    updateBriefChrome();
    updateResultSummary(newsItems);
    renderLpMonitor(noticeItems);
    renderGrouped(todayList, newsItems);
  };

  const setView = (view) => {
    todayView.classList.toggle("active", true);
    navItems.forEach((item) => {
      item.classList.toggle("active", item.dataset.view === "today");
    });
  };

  const setViewFromHash = () => {
    setView("today");
  };

  document.addEventListener("click", (event) => {
    const tagToggle = event.target.closest(".tag-toggle");
    if (tagToggle) {
      const group = tagToggle.closest(".cell-tags");
      if (group) {
        group.dataset.expanded = group.dataset.expanded === "1" ? "0" : "1";
        updateTagGroup(group);
      }
      return;
    }

    const filterChip = event.target.closest(".context-chip[data-filter]");
    if (filterChip) {
      searchInput.value = filterChip.dataset.filter || "";
      setSearchOpen(true);
      setView("today");
      syncSearchUrl();
      render();
      searchInput.focus();
      return;
    }

    const navButton = event.target.closest("[data-view]");
    if (navButton) setView(navButton.dataset.view);
  });

  if (lpDetailClose) lpDetailClose.addEventListener("click", closeLpDetail);
  if (lpDetailBackdrop) lpDetailBackdrop.addEventListener("click", closeLpDetail);
  if (searchToggle) searchToggle.addEventListener("click", () => setSearchOpen(true));
  if (searchClose) {
    searchClose.addEventListener("click", () => {
      if (searchInput && searchInput.value) {
        searchInput.value = "";
        syncSearchUrl();
        render();
      }
      setSearchOpen(false);
    });
  }
  if (datePrev) datePrev.addEventListener("click", () => setBriefByOffset(1));
  if (dateNext) dateNext.addEventListener("click", () => setBriefByOffset(-1));
  if (dateInput) {
    dateInput.addEventListener("change", () => {
      const next = archive.find((brief) => brief.reportDate === dateInput.value);
      if (next) {
        setActiveBrief(next.reportDate);
        return;
      }
      updateDateControl();
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeLpDetail();
      if (searchInput && !searchInput.value) setSearchOpen(false);
    }
  });

  if (searchInput) searchInput.addEventListener("input", () => {
    setSearchOpen(true);
    syncSearchUrl();
    render();
  });
  if (dateSelect) {
    dateSelect.addEventListener("change", () => setActiveBrief(dateSelect.value));
  }
  let tagResizeTimer = 0;
  window.addEventListener("resize", () => {
    window.clearTimeout(tagResizeTimer);
    tagResizeTimer = window.setTimeout(updateTagGroups, 90);
  });
  window.addEventListener("hashchange", setViewFromHash);
  render();
  setViewFromHash();
})(); 
"""

def app_asset_version() -> str:
    asset_payload = f"{service_css()}\n{service_js()}".encode("utf-8")
    return f"{zlib.crc32(asset_payload) & 0xFFFFFFFF:08x}"
