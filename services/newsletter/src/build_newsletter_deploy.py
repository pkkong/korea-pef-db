#!/usr/bin/env python
"""Build a deployable static bundle for the newsletter-only service."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
DEFAULT_DEPLOY_DIR = SERVICE_ROOT / "deploy"
DEFAULT_SITE_DIR = DEFAULT_DEPLOY_DIR / "site"
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_ARCHIVE_SEED_URL = os.environ.get(
    "NEWSLETTER_ARCHIVE_SEED_URL",
    "https://raw.githubusercontent.com/pkkong/kpef-newsletter/main/archive.json",
)

KTCU_CODE = "ktcu"
KTCU_FACT_SECTION_LABELS = {
    "general": "일반현황",
    "investment_status": "투자현황",
    "investment_strategy": "투자전략",
    "investment_org": "PE 관련 조직",
    "investment_governance": "투자 의사결정",
    "public_people": "공개 인물",
    "notice_history": "출자공고 히스토리",
    "data_gap": "확인 필요",
}
KTCU_FACT_SECTION_ORDER = {
    "general": 10,
    "investment_status": 20,
    "investment_strategy": 30,
    "investment_org": 40,
    "investment_governance": 50,
    "public_people": 60,
    "notice_history": 70,
    "data_gap": 90,
}

LEGACY_SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(LEGACY_SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(LEGACY_SCRIPTS_DIR))
from build_service_site import (  # noqa: E402
    DEFAULT_ARCHIVE_LIMIT,
    DEFAULT_EXPORT_DIR,
    DEFAULT_LP_COMMITMENT_MONITOR,
    DEFAULT_SERVICE_INTEGRATION_WORKLIST,
    build,
    compact_date,
    html_escape,
    parse_brief,
    parse_brief_basis,
    read_lp_monitor,
    read_service_context,
    render_app,
)
from daily_news_common import today_seoul  # noqa: E402


ARCHIVE_SCRIPT_RE = re.compile(
    r"<script>window\.KPEF_DAILY_ARCHIVE\s*=\s*(?P<payload>.*?);</script>",
    re.DOTALL,
)


def assert_newsletter_only(site_dir: Path) -> None:
    for name in ["index.html", "daily-news.html"]:
        html = (site_dir / name).read_text(encoding="utf-8")
        if 'href="db.html' in html or "db.html#" in html:
            raise RuntimeError(f"{name} still contains DB navigation")


def write_health_file(site_dir: Path, result: dict[str, str]) -> None:
    payload = {
        "service": "kpef-newsletter",
        "status": "ok",
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "report_date": result.get("report_date", ""),
        "article_count": int(result.get("article_count", "0") or 0),
        "lp_monitor_count": int(result.get("lp_monitor_count", "0") or 0),
        "ktcu_fact_count": int(result.get("ktcu_fact_count", "0") or 0),
    }
    (site_dir / "health.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_static_support_files(site_dir: Path) -> None:
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
    (site_dir / "robots.txt").write_text("User-agent: *\nDisallow:\n", encoding="utf-8")
    (site_dir / "404.html").write_text((site_dir / "index.html").read_text(encoding="utf-8"), encoding="utf-8")


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


def amount_short(value: object) -> str:
    try:
        parsed = float(str(value or "0").replace(",", ""))
    except ValueError:
        return "-"
    if parsed <= 0:
        return "-"
    if parsed >= 10000:
        return f"{parsed / 10000:,.1f}조"
    return f"{round(parsed):,}억"


def fact_value(facts: list[dict[str, object]], label: str, fallback: str = "-") -> str:
    for fact in facts:
        if str(fact.get("label") or "") == label:
            return str(fact.get("value") or fallback)
    return fallback


def read_ktcu_payload(db_path: Path = DEFAULT_DB) -> dict[str, object]:
    if not db_path.exists():
        return {"profile": {}, "facts": [], "notices": [], "yearly": []}
    conn = sqlite3.connect(db_path)
    try:
        profile = {}
        if db_object_exists(conn, "lp_institution"):
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
                (KTCU_CODE,),
            )
            profile = rows[0] if rows else {}

        facts = (
            fetch_dicts(
                conn,
                """
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
                FROM lp_profile_fact
                WHERE lp_code = ?
                  AND public_visible = 1
                ORDER BY section, sort_order, label
                """,
                (KTCU_CODE,),
            )
            if db_object_exists(conn, "lp_profile_fact")
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
                    event_date,
                    title,
                    notice_url,
                    document_url,
                    application_deadline,
                    asset_class,
                    strategy,
                    allocation_amount_krw_100mn,
                    selected_gp_names,
                    confidence
                FROM v_lp_commitment_notice_public
                WHERE lp_code = ?
                  AND public_visible = 1
                ORDER BY COALESCE(event_date, announced_date) DESC, notice_id DESC
                """,
                (KTCU_CODE,),
            )
            if db_object_exists(conn, "v_lp_commitment_notice_public")
            else []
        )

        yearly = (
            fetch_dicts(
                conn,
                """
                SELECT
                    notice_year,
                    notice_count,
                    allocation_amount_krw_100mn
                FROM v_lp_commitment_yearly_stats
                WHERE lp_code = ?
                ORDER BY notice_year DESC
                """,
                (KTCU_CODE,),
            )
            if db_object_exists(conn, "v_lp_commitment_yearly_stats")
            else []
        )
    finally:
        conn.close()
    return {"profile": profile, "facts": facts, "notices": notices, "yearly": yearly}


def render_ktcu_fact_section(section: str, rows: list[dict[str, object]]) -> str:
    items = "\n".join(
        f"""          <div>
            <dt>{html_escape(str(row.get("label") or "-"))}</dt>
            <dd>
              <span>{html_escape(str(row.get("value") or "-"))}</span>
              {f'<a href="{html_escape(str(row.get("source_url") or ""))}" target="_blank" rel="noreferrer">{html_escape(str(row.get("source_name") or "출처"))}</a>' if row.get("source_url") else ""}
            </dd>
          </div>"""
        for row in rows
    )
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
            str(row.get("asset_class") or ""),
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
          <strong>{html_escape(amount_short(row.get("allocation_amount_krw_100mn")))}</strong>
        </article>"""


def render_ktcu_year_bar(row: dict[str, object], max_amount: float) -> str:
    amount = float(row.get("allocation_amount_krw_100mn") or 0)
    width = 0 if max_amount <= 0 else max(4, min(100, amount / max_amount * 100))
    return f"""        <div class="ktcu-year-row">
          <span>{html_escape(str(row.get("notice_year") or "-"))}</span>
          <div><i style="width: {width:.1f}%"></i></div>
          <strong>{html_escape(amount_short(amount))}</strong>
        </div>"""


def render_ktcu_page(report_date: str, payload: dict[str, object]) -> str:
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    facts = payload.get("facts") if isinstance(payload.get("facts"), list) else []
    notices = payload.get("notices") if isinstance(payload.get("notices"), list) else []
    yearly = payload.get("yearly") if isinstance(payload.get("yearly"), list) else []

    facts_by_section: dict[str, list[dict[str, object]]] = {}
    for fact in facts:
        section = str(fact.get("section") or "other")
        facts_by_section.setdefault(section, []).append(fact)
    fact_sections = "\n".join(
        render_ktcu_fact_section(section, rows)
        for section, rows in sorted(
            facts_by_section.items(),
            key=lambda item: KTCU_FACT_SECTION_ORDER.get(item[0], 99),
        )
    )
    notice_rows = "\n".join(render_ktcu_notice_row(row) for row in notices)
    max_yearly = max([float(row.get("allocation_amount_krw_100mn") or 0) for row in yearly] or [0])
    yearly_rows = "\n".join(render_ktcu_year_bar(row, max_yearly) for row in yearly)

    asset = fact_value(facts, "2025년말 보유자산", fact_value(facts, "보유 자산"))
    members = fact_value(facts, "회원 수")
    notice_count = str(profile.get("notice_count") or len(notices))
    total_amount = amount_short(profile.get("allocation_amount_krw_100mn"))
    latest = str(profile.get("latest_event_date") or "")

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>한국교직원공제회 LP Intelligence</title>
  <link rel="stylesheet" href="assets/service.css">
  <style>
    body {{ background: #f6f7f9; }}
    .ktcu-shell {{ width: min(1160px, calc(100% - 28px)); margin: 0 auto; padding: 18px 0 42px; }}
    .ktcu-top {{ display: grid; gap: 14px; padding: 18px 0 12px; }}
    .ktcu-nav {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; }}
    .ktcu-nav a {{ min-height: 34px; display: inline-flex; align-items: center; border: 1px solid var(--separator); border-radius: 999px; padding: 7px 11px; background: #fff; color: var(--text); text-decoration: none; font-size: 12px; font-weight: 700; }}
    .ktcu-hero {{ display: grid; gap: 16px; border: 1px solid var(--separator); border-radius: 18px; padding: 18px; background: #fff; }}
    .ktcu-title {{ display: grid; gap: 8px; }}
    .ktcu-title span {{ width: fit-content; border-radius: 999px; padding: 5px 9px; background: #e7f0ff; color: #15407d; font-size: 12px; font-weight: 800; }}
    .ktcu-title h1 {{ margin: 0; color: var(--text); font-size: clamp(30px, 5vw, 56px); line-height: 1.03; letter-spacing: 0; }}
    .ktcu-title p {{ max-width: 760px; margin: 0; color: var(--secondary); font-size: 14px; line-height: 1.65; }}
    .ktcu-kpis {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
    .ktcu-kpi {{ min-width: 0; border: 1px solid var(--separator); border-radius: 12px; padding: 12px; background: #fbfcfd; }}
    .ktcu-kpi span {{ display: block; color: var(--secondary); font-size: 11.5px; font-weight: 700; }}
    .ktcu-kpi strong {{ display: block; margin-top: 5px; color: var(--text); font-size: 22px; line-height: 1.15; overflow-wrap: anywhere; }}
    .ktcu-grid {{ display: grid; gap: 10px; margin-top: 10px; }}
    .ktcu-fact, .ktcu-panel {{ border: 1px solid var(--separator); border-radius: 14px; padding: 14px; background: #fff; }}
    .ktcu-fact h2, .ktcu-panel h2 {{ margin: 0 0 11px; color: var(--text); font-size: 16px; line-height: 1.35; }}
    .ktcu-fact dl {{ display: grid; gap: 9px; margin: 0; }}
    .ktcu-fact dl div {{ min-width: 0; border-top: 1px solid var(--separator); padding-top: 9px; }}
    .ktcu-fact dl div:first-child {{ border-top: 0; padding-top: 0; }}
    .ktcu-fact dt {{ color: var(--secondary); font-size: 11.5px; font-weight: 800; }}
    .ktcu-fact dd {{ display: grid; gap: 4px; margin: 4px 0 0; color: var(--text); font-size: 13px; font-weight: 750; line-height: 1.45; overflow-wrap: anywhere; }}
    .ktcu-fact dd a {{ width: fit-content; color: var(--secondary); font-size: 11.5px; text-decoration: none; }}
    .ktcu-lower {{ display: grid; gap: 10px; margin-top: 10px; }}
    .ktcu-notices {{ display: grid; gap: 8px; }}
    .ktcu-notice {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: start; border-top: 1px solid var(--separator); padding-top: 10px; }}
    .ktcu-notice:first-child {{ border-top: 0; padding-top: 0; }}
    .ktcu-notice time {{ color: var(--secondary); font-size: 11.5px; font-weight: 800; }}
    .ktcu-notice h3 {{ margin: 4px 0; font-size: 14px; line-height: 1.42; }}
    .ktcu-notice h3 a {{ color: var(--text); text-decoration: none; }}
    .ktcu-notice p {{ margin: 0; color: var(--secondary); font-size: 12px; line-height: 1.4; }}
    .ktcu-notice strong {{ white-space: nowrap; color: #15407d; font-size: 14px; }}
    .ktcu-years {{ display: grid; gap: 8px; }}
    .ktcu-year-row {{ display: grid; grid-template-columns: 44px minmax(0, 1fr) 68px; gap: 8px; align-items: center; font-size: 12px; }}
    .ktcu-year-row span {{ color: var(--secondary); font-weight: 800; }}
    .ktcu-year-row div {{ height: 9px; border-radius: 999px; background: #edf0f4; overflow: hidden; }}
    .ktcu-year-row i {{ display: block; height: 100%; border-radius: inherit; background: #2f6fbc; }}
    .ktcu-year-row strong {{ text-align: right; font-size: 12px; }}
    .ktcu-footer {{ margin-top: 14px; color: var(--secondary); font-size: 11.5px; line-height: 1.45; }}
    @media (min-width: 760px) {{
      .ktcu-shell {{ padding-top: 24px; }}
      .ktcu-hero {{ grid-template-columns: minmax(0, 1.3fr) minmax(360px, 0.7fr); padding: 24px; }}
      .ktcu-kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); align-content: start; }}
      .ktcu-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .ktcu-lower {{ grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr); }}
    }}
  </style>
</head>
<body>
  <main class="ktcu-shell">
    <header class="ktcu-top">
      <nav class="ktcu-nav" aria-label="페이지 이동">
        <a href="index.html">Daily Brief</a>
        <a href="lp-notices.html">LP 공고</a>
      </nav>
      <section class="ktcu-hero" aria-label="한국교직원공제회 요약">
        <div class="ktcu-title">
          <span>LP Intelligence Sample</span>
          <h1>한국교직원공제회</h1>
          <p>공개자료 기준으로 기관 일반현황, 기금운용 조직, 투자현황, 출자공고 히스토리를 한 페이지에 모은 샘플입니다.</p>
        </div>
        <div class="ktcu-kpis">
          <div class="ktcu-kpi"><span>보유 자산</span><strong>{html_escape(asset)}</strong></div>
          <div class="ktcu-kpi"><span>회원 수</span><strong>{html_escape(members)}</strong></div>
          <div class="ktcu-kpi"><span>포착 공고</span><strong>{html_escape(notice_count)}건</strong></div>
          <div class="ktcu-kpi"><span>포착 출자규모</span><strong>{html_escape(total_amount)}</strong></div>
        </div>
      </section>
    </header>

    <section class="ktcu-grid" aria-label="프로필 팩트">
{fact_sections}
    </section>

    <section class="ktcu-lower" aria-label="출자공고 히스토리">
      <section class="ktcu-panel">
        <h2>과거 출자공고</h2>
        <div class="ktcu-notices">
{notice_rows}
        </div>
      </section>
      <section class="ktcu-panel">
        <h2>연도별 포착 규모</h2>
        <div class="ktcu-years">
{yearly_rows}
        </div>
      </section>
    </section>

    <p class="ktcu-footer">기준일 {html_escape(report_date)} · 최신 공고일 {html_escape(latest or "-")} · 공개자료로 확인되지 않는 실무자명과 최종 선정 GP 히스토리는 추정하지 않습니다.</p>
  </main>
</body>
</html>
"""


def write_ktcu_page(site_dir: Path, report_date: str) -> int:
    payload = read_ktcu_payload()
    html = render_ktcu_page(report_date, payload)
    (site_dir / "ktcu.html").write_text(html, encoding="utf-8")
    (site_dir / "lp-ktcu.html").write_text(html, encoding="utf-8")
    facts = payload.get("facts") if isinstance(payload.get("facts"), list) else []
    return len(facts)


def render_lp_notices_page(report_date: str, notices: list[dict[str, object]]) -> str:
    if notices:
        notice_cards = "\n".join(render_lp_notice_card(item) for item in notices)
    else:
        notice_cards = """        <div class="empty-state visible">
          <strong>표시할 공식 공고가 없습니다</strong>
          <span>LP 공고 모니터는 별도 서비스로 분리해 운영합니다.</span>
        </div>"""
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Korea PEF Intelligence LP Notices</title>
  <link rel="stylesheet" href="assets/service.css">
  <style>
    .lp-page-list {{ display: grid; gap: 10px; }}
    .lp-page-card {{ display: grid; gap: 8px; padding: 14px; border: 1px solid var(--separator); border-radius: 14px; background: var(--surface); }}
    .lp-page-card h2 {{ margin: 0; font-size: 15px; line-height: 1.38; }}
    .lp-page-card h2 a {{ color: inherit; text-decoration: none; }}
    .lp-page-meta {{ display: flex; flex-wrap: wrap; gap: 6px; color: var(--secondary); font-size: 12px; line-height: 1.35; }}
    .lp-page-meta span + span::before {{ content: "·"; margin-right: 6px; color: var(--tertiary); }}
    .lp-page-actions {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .lp-page-actions a {{ display: inline-flex; min-height: 32px; align-items: center; border-radius: 999px; padding: 6px 10px; background: var(--surface-muted); color: var(--text); font-size: 12px; font-weight: 650; text-decoration: none; }}
    @media (min-width: 960px) {{ .lp-page-list {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
  </style>
</head>
<body>
  <div class="app-shell newsletter-only">
    <header class="app-header">
      <div class="header-topline">
        <div>
          <p>Korea PEF Intelligence</p>
          <strong>LP 공고</strong>
        </div>
        <div class="header-actions">
          <a class="header-action" href="index.html" aria-label="뉴스 브리프 열기">브리프</a>
        </div>
      </div>
      <div class="brief-meta">공식 공고 {len(notices)}건 · 기준일 {html_escape(report_date)}</div>
    </header>

    <main class="content-area">
      <section class="section-block" aria-label="LP 공식 공고">
        <div class="lp-page-list">
{notice_cards}
        </div>
      </section>
    </main>

    <nav class="bottom-nav" aria-label="하단 메뉴">
      <a href="index.html">
        <span aria-hidden="true" class="nav-dot nav-icon-brief"></span>
        <strong>브리프</strong>
      </a>
      <a class="active" href="lp-notices.html">
        <span aria-hidden="true" class="nav-dot nav-icon-db"></span>
        <strong>공고</strong>
      </a>
      <a href="index.html#saved">
        <span aria-hidden="true" class="nav-dot nav-icon-saved"></span>
        <strong>저장</strong>
      </a>
    </nav>
  </div>
</body>
</html>
"""


def render_lp_notice_card(item: dict[str, object]) -> str:
    title = str(item.get("displayTitle") or item.get("title") or "공식 공고")
    url = str(item.get("url") or "")
    document_url = str(item.get("documentUrl") or "")
    amount = lp_amount_label(item.get("allocationAmount"))
    meta_values = [
        str(item.get("lpName") or "LP 미분류"),
        lp_event_label(item.get("eventType")),
        str(item.get("assetClass") or ""),
        f"마감 {item.get('applicationDeadline')}" if item.get("applicationDeadline") else "",
        amount,
    ]
    meta = "".join(f"<span>{html_escape(value)}</span>" for value in meta_values if value)
    official_link = (
        f'<a href="{html_escape(url)}" target="_blank" rel="noreferrer">공식 공고 보기</a>'
        if url
        else ""
    )
    document_link = (
        f'<a href="{html_escape(document_url)}" target="_blank" rel="noreferrer">첨부파일</a>'
        if document_url and document_url != url
        else ""
    )
    linked_title = (
        f'<a href="{html_escape(url)}" target="_blank" rel="noreferrer">{html_escape(title)}</a>'
        if url
        else html_escape(title)
    )
    return f"""          <article class="lp-page-card">
            <h2>{linked_title}</h2>
            <div class="lp-page-meta">{meta}</div>
            <div class="lp-page-actions">{official_link}{document_link}</div>
          </article>"""


def write_lp_notices_page(site_dir: Path, report_date: str) -> int:
    notices = read_lp_monitor(DEFAULT_LP_COMMITMENT_MONITOR)
    (site_dir / "lp-notices.html").write_text(render_lp_notices_page(report_date, notices), encoding="utf-8")
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
    markdown_path = DEFAULT_EXPORT_DIR / f"daily_news_brief_{compact_date(report_date)}.md"
    articles = parse_brief(markdown_path)
    basis_text = parse_brief_basis(markdown_path)
    service_context = read_service_context(DEFAULT_SERVICE_INTEGRATION_WORKLIST)
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
    include_paths = [
        site_dir / "index.html",
        site_dir / "daily-news.html",
        site_dir / "lp-notices.html",
        site_dir / "ktcu.html",
        site_dir / "lp-ktcu.html",
        site_dir / "health.json",
        site_dir / "archive.json",
        site_dir / ".nojekyll",
        site_dir / "robots.txt",
        site_dir / "404.html",
        site_dir / "assets" / "service.css",
        site_dir / "assets" / "service.js",
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
    result["ktcu_fact_count"] = str(write_ktcu_page(site_dir, args.date))
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
