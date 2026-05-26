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
    "investment_org": "담당 조직",
    "investment_governance": "투자 의사결정",
    "public_people": "핵심 의사결정자",
    "notice_history": "출자공고 히스토리",
    "data_gap": "공개자료 한계",
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
        return f"{parsed / 10000:,.2f}조"
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
                    notice_year,
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


def facts_in_section(facts: list[dict[str, object]], section: str) -> list[dict[str, object]]:
    return [fact for fact in facts if str(fact.get("section") or "") == section]


def render_ktcu_fact_list(rows: list[dict[str, object]]) -> str:
    return "\n".join(
        f"""          <div>
            <dt>{html_escape(str(row.get("label") or "-"))}</dt>
            <dd>{html_escape(str(row.get("value") or "-"))}</dd>
          </div>"""
        for row in rows
    )


def render_ktcu_source_links(facts: list[dict[str, object]]) -> str:
    seen: set[str] = set()
    links: list[str] = []
    for fact in facts:
        url = str(fact.get("source_url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        name = str(fact.get("source_name") or "공개 출처")
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
        asset_class = str(notice.get("asset_class") or "기타")
        totals[asset_class] = totals.get(asset_class, 0.0) + float(notice.get("allocation_amount_krw_100mn") or 0)
        counts[asset_class] = counts.get(asset_class, 0) + 1
    rows = sorted(totals, key=lambda key: (-totals[key], key))
    return "\n".join(
        f"""          <div class="ktcu-mix-row">
            <span>{html_escape(asset_class)}</span>
            <strong>{html_escape(amount_short(totals[asset_class]))}</strong>
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
            <span>{html_escape(str(row.get("asset_class") or "출자"))}</span>
            <strong>{html_escape(amount_short(row.get("allocation_amount_krw_100mn")))}</strong>
            <em>{html_escape(str(row.get("title") or ""))}</em>
          </div>"""
        for row in rows
    )


def ktcu_year_amount(notices: list[dict[str, object]], year: int) -> float:
    return sum(
        float(row.get("allocation_amount_krw_100mn") or 0)
        for row in notices
        if str(row.get("event_date") or "").startswith(str(year))
    )


def render_ktcu_page(report_date: str, payload: dict[str, object]) -> str:
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    facts = payload.get("facts") if isinstance(payload.get("facts"), list) else []
    notices = payload.get("notices") if isinstance(payload.get("notices"), list) else []
    yearly = payload.get("yearly") if isinstance(payload.get("yearly"), list) else []

    notice_rows = "\n".join(render_ktcu_notice_row(row) for row in notices)
    max_yearly = max([float(row.get("allocation_amount_krw_100mn") or 0) for row in yearly] or [0])
    yearly_rows = "\n".join(render_ktcu_year_bar(row, max_yearly) for row in yearly)
    source_rows = render_ktcu_source_links(facts)
    asset_mix_rows = render_ktcu_asset_mix(notices)
    general_rows = render_ktcu_fact_list(facts_in_section(facts, "general"))
    status_rows = render_ktcu_fact_list(facts_in_section(facts, "investment_status"))
    strategy_rows = render_ktcu_fact_list(facts_in_section(facts, "investment_strategy"))
    governance_rows = render_ktcu_fact_list(facts_in_section(facts, "investment_governance"))

    asset = fact_value(facts, "2025년말 보유자산", fact_value(facts, "보유 자산"))
    alternatives = fact_value(facts, "2025년 투자자산")
    alternative_amount = "45.5조" if "45조 4,724억원" in alternatives else alternatives
    target = fact_value(facts, "2026년 자산운용 목표")
    chairman = fact_value(facts, "이사장")
    cio = fact_value(facts, "기금운용이사/CIO")
    team_one = fact_value(facts, "기업투자1팀")
    team_two = fact_value(facts, "기업투자2팀")
    pe_notice = fact_value(facts, "2025년 PEF 블라인드 공고")
    gp_gap_public = "최종 선정 GP 히스토리는 공식 공고와 별도 자료를 대조해 추가 검증해야 합니다."
    people_gap_public = "공개 조직도에서는 부서와 팀 역할까지 확인되며, 실무 담당자명은 확정하지 않습니다."
    notice_count = str(profile.get("notice_count") or len(notices))
    total_amount = amount_short(profile.get("allocation_amount_krw_100mn"))
    latest = str(profile.get("latest_event_date") or "")
    notices_2025 = [notice for notice in notices if str(notice.get("event_date") or "").startswith("2025")]
    count_2025 = len(notices_2025)
    amount_2025 = amount_short(ktcu_year_amount(notices, 2025))
    highlight_rows_2025 = render_ktcu_annual_highlights(notices, 2025) or (
        """          <p class="ktcu-empty-note">2025년 공식 공고가 아직 정리되지 않았습니다.</p>"""
    )

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>한국교직원공제회 LP 프로필</title>
  <link rel="stylesheet" href="assets/service.css">
  <style>
    body {{ background: #f7f8fa; }}
    .ktcu-shell {{ width: min(1180px, calc(100% - 28px)); margin: 0 auto; padding: 16px 0 44px; }}
    .ktcu-top {{ display: grid; gap: 14px; padding: 14px 0 12px; }}
    .ktcu-nav {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; }}
    .ktcu-nav strong {{ color: var(--text); font-size: 13px; }}
    .ktcu-nav a {{ min-height: 34px; display: inline-flex; align-items: center; border: 1px solid var(--separator); border-radius: 8px; padding: 7px 11px; background: #fff; color: var(--text); text-decoration: none; font-size: 12px; font-weight: 700; }}
    .ktcu-hero {{ display: grid; gap: 18px; padding: 18px 0 8px; }}
    .ktcu-title {{ display: grid; gap: 10px; }}
    .ktcu-title span {{ width: fit-content; border-left: 3px solid #2f6fbc; padding-left: 8px; color: #24598d; font-size: 12px; font-weight: 800; }}
    .ktcu-title h1 {{ margin: 0; color: var(--text); font-size: clamp(32px, 5vw, 62px); line-height: 1.02; letter-spacing: 0; }}
    .ktcu-title p {{ max-width: 760px; margin: 0; color: var(--secondary); font-size: 15px; line-height: 1.68; }}
    .ktcu-quick {{ display: grid; gap: 8px; }}
    .ktcu-quick-item {{ border-left: 3px solid #d0a33c; padding-left: 10px; color: var(--text); font-size: 13px; line-height: 1.5; }}
    .ktcu-quick-item strong {{ display: block; margin-bottom: 2px; font-size: 13px; }}
    .ktcu-kpis {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 6px; }}
    .ktcu-kpi {{ min-width: 0; border: 1px solid var(--separator); border-radius: 8px; padding: 12px; background: #fff; }}
    .ktcu-kpi span {{ display: block; color: var(--secondary); font-size: 11.5px; font-weight: 700; }}
    .ktcu-kpi strong {{ display: block; margin-top: 5px; color: var(--text); font-size: 22px; line-height: 1.15; overflow-wrap: anywhere; }}
    .ktcu-highlight-panel {{ margin-top: 10px; }}
    .ktcu-panel-head {{ display: flex; gap: 10px; align-items: start; justify-content: space-between; margin-bottom: 12px; }}
    .ktcu-panel-head h2 {{ margin-bottom: 4px; }}
    .ktcu-panel-head p {{ margin: 0; color: var(--secondary); font-size: 13px; line-height: 1.5; }}
    .ktcu-panel-head > strong {{ flex: 0 0 auto; color: #15407d; font-size: 18px; line-height: 1.25; text-align: right; }}
    .ktcu-highlight-list {{ display: grid; gap: 8px; }}
    .ktcu-highlight-row {{ display: grid; grid-template-columns: minmax(86px, 0.28fr) minmax(74px, auto) minmax(0, 1fr); gap: 9px; align-items: center; border-top: 1px solid var(--separator); padding-top: 9px; font-size: 13px; }}
    .ktcu-highlight-row:first-child {{ border-top: 0; padding-top: 0; }}
    .ktcu-highlight-row span {{ color: var(--secondary); font-weight: 800; }}
    .ktcu-highlight-row strong {{ color: #15407d; white-space: nowrap; }}
    .ktcu-highlight-row em {{ color: var(--text); font-style: normal; font-weight: 700; line-height: 1.4; }}
    .ktcu-empty-note {{ margin: 0; color: var(--secondary); font-size: 13px; }}
    .ktcu-section-grid {{ display: grid; gap: 10px; margin-top: 12px; }}
    .ktcu-panel {{ border: 1px solid var(--separator); border-radius: 8px; padding: 15px; background: #fff; }}
    .ktcu-panel h2 {{ margin: 0 0 11px; color: var(--text); font-size: 17px; line-height: 1.35; }}
    .ktcu-panel > p {{ margin: 0 0 12px; color: var(--secondary); font-size: 13px; line-height: 1.58; }}
    .ktcu-facts {{ display: grid; gap: 9px; margin: 0; }}
    .ktcu-facts div {{ min-width: 0; border-top: 1px solid var(--separator); padding-top: 9px; }}
    .ktcu-facts div:first-child {{ border-top: 0; padding-top: 0; }}
    .ktcu-facts dt {{ color: var(--secondary); font-size: 11.5px; font-weight: 800; }}
    .ktcu-facts dd {{ margin: 4px 0 0; color: var(--text); font-size: 13px; font-weight: 750; line-height: 1.48; overflow-wrap: anywhere; }}
    .ktcu-org {{ display: grid; gap: 8px; }}
    .ktcu-org-node {{ border: 1px solid var(--separator); border-radius: 8px; padding: 10px; background: #fbfcfd; }}
    .ktcu-org-node span {{ display: block; color: var(--secondary); font-size: 11.5px; font-weight: 800; }}
    .ktcu-org-node strong {{ display: block; margin-top: 4px; color: var(--text); font-size: 14px; line-height: 1.35; }}
    .ktcu-org-split {{ display: grid; gap: 8px; }}
    .ktcu-mix {{ display: grid; gap: 8px; }}
    .ktcu-mix-row {{ display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 8px; align-items: center; border-top: 1px solid var(--separator); padding-top: 8px; font-size: 13px; }}
    .ktcu-mix-row:first-child {{ border-top: 0; padding-top: 0; }}
    .ktcu-mix-row span {{ font-weight: 800; }}
    .ktcu-mix-row strong {{ color: #24598d; }}
    .ktcu-mix-row em {{ color: var(--secondary); font-style: normal; }}
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
    .ktcu-evidence {{ margin-top: 10px; border: 1px solid var(--separator); border-radius: 8px; background: #fff; }}
    .ktcu-evidence summary {{ cursor: pointer; padding: 12px 14px; color: var(--text); font-size: 13px; font-weight: 800; }}
    .ktcu-evidence-body {{ padding: 0 14px 14px; }}
    .ktcu-evidence-body p {{ margin: 0 0 10px; color: var(--secondary); font-size: 13px; line-height: 1.55; }}
    .ktcu-evidence ul {{ display: grid; gap: 8px; margin: 0; padding: 0 14px 14px 28px; }}
    .ktcu-evidence a {{ color: var(--secondary); font-size: 12px; text-decoration: none; }}
    .ktcu-footer {{ margin-top: 14px; color: var(--secondary); font-size: 11.5px; line-height: 1.45; }}
    @media (min-width: 760px) {{
      .ktcu-shell {{ padding-top: 22px; }}
      .ktcu-hero {{ grid-template-columns: minmax(0, 1.12fr) minmax(340px, 0.88fr); align-items: end; }}
      .ktcu-section-grid {{ grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }}
      .ktcu-org-split {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .ktcu-lower {{ grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr); }}
    }}
  </style>
</head>
<body>
  <main class="ktcu-shell">
    <header class="ktcu-top">
      <nav class="ktcu-nav" aria-label="페이지 이동">
        <strong>Korea PEF Intelligence</strong>
        <span>
          <a href="index.html">Daily Brief</a>
          <a href="lp-notices.html">LP 공고</a>
        </span>
      </nav>
      <section class="ktcu-hero" aria-label="한국교직원공제회 요약">
        <div class="ktcu-title">
          <span>LP Profile</span>
          <h1>한국교직원공제회</h1>
          <p>대형 공제회 LP의 투자 성향, 담당 조직, 출자공고 흐름을 한 화면에서 볼 수 있게 정리했습니다. PE 관점에서는 기금운용이사 산하 기업투자부의 블라인드 PEF·VC 출자 패턴과 대체투자 비중을 먼저 봅니다.</p>
          <div class="ktcu-quick">
            <div class="ktcu-quick-item"><strong>핵심 창구</strong>기업투자부가 PE·기업금융·벤처 투자를 담당합니다.</div>
            <div class="ktcu-quick-item"><strong>2025년 활동</strong>공식 공고 {html_escape(str(count_2025))}건, 공고 기준 출자규모 {html_escape(amount_2025)}입니다.</div>
            <div class="ktcu-quick-item"><strong>검증 범위</strong>공고와 공식 조직은 확인됐고, 최종 선정 GP는 별도 검증 대상입니다.</div>
          </div>
        </div>
        <div class="ktcu-kpis">
          <div class="ktcu-kpi"><span>보유자산</span><strong>{html_escape(asset)}</strong></div>
          <div class="ktcu-kpi"><span>대체투자</span><strong>{html_escape(alternative_amount)}</strong></div>
          <div class="ktcu-kpi"><span>공식 공고</span><strong>{html_escape(notice_count)}건</strong></div>
          <div class="ktcu-kpi"><span>공고 기준 출자규모</span><strong>{html_escape(total_amount)}</strong></div>
        </div>
      </section>
    </header>

    <section class="ktcu-panel ktcu-highlight-panel" aria-label="2025년 출자 하이라이트">
      <div class="ktcu-panel-head">
        <div>
          <h2>2025년 출자 하이라이트</h2>
          <p>공식 공고에 적힌 출자 예정·배정 규모입니다. 최종 선정 또는 실제 집행 금액과는 다를 수 있습니다.</p>
        </div>
        <strong>{html_escape(str(count_2025))}건<br>{html_escape(amount_2025)}</strong>
      </div>
      <div class="ktcu-highlight-list">
{highlight_rows_2025}
      </div>
    </section>

    <section class="ktcu-section-grid" aria-label="사용자용 LP 요약">
      <section class="ktcu-panel">
        <h2>투자 현황</h2>
        <p>{html_escape(alternatives)} · {html_escape(target)}</p>
        <dl class="ktcu-facts">
{status_rows}
        </dl>
      </section>

      <section class="ktcu-panel">
        <h2>담당 조직</h2>
        <p>공식 조직도 기준으로 PE와 기업금융을 담당하는 축만 정리했습니다.</p>
        <div class="ktcu-org">
          <div class="ktcu-org-node"><span>이사장</span><strong>{html_escape(chairman)}</strong></div>
          <div class="ktcu-org-node"><span>기금운용이사/CIO</span><strong>{html_escape(cio)}</strong></div>
          <div class="ktcu-org-node"><span>핵심 부서</span><strong>기업투자부</strong></div>
          <div class="ktcu-org-split">
            <div class="ktcu-org-node"><span>기업투자1팀</span><strong>{html_escape(team_one)}</strong></div>
            <div class="ktcu-org-node"><span>기업투자2팀</span><strong>{html_escape(team_two)}</strong></div>
          </div>
        </div>
      </section>

      <section class="ktcu-panel">
        <h2>투자전략과 의사결정</h2>
        <p>운용 원칙과 투자 의사결정 기구를 분리해서 봅니다.</p>
        <dl class="ktcu-facts">
{strategy_rows}
{governance_rows}
        </dl>
      </section>

      <section class="ktcu-panel">
        <h2>출자 패턴</h2>
        <p>공개된 공식 공고의 자산군과 공고상 출자 규모를 기준으로 본 패턴입니다.</p>
        <div class="ktcu-mix">
{asset_mix_rows}
        </div>
      </section>

      <section class="ktcu-panel">
        <h2>기관 개요</h2>
        <p>공식 기관소개와 경영공시에서 확인되는 기본 정보입니다.</p>
        <dl class="ktcu-facts">
{general_rows}
        </dl>
      </section>
    </section>

    <section class="ktcu-lower" aria-label="출자공고 히스토리">
      <section class="ktcu-panel">
        <h2>과거 출자공고</h2>
        <div class="ktcu-notices">
{notice_rows}
        </div>
      </section>
      <section class="ktcu-panel">
        <h2>연도별 공식 공고 규모</h2>
        <div class="ktcu-years">
{yearly_rows}
        </div>
      </section>
    </section>

    <details class="ktcu-evidence">
      <summary>공개자료 한계</summary>
      <div class="ktcu-evidence-body">
        <p>공개 공고와 공식 조직도 기준의 프로필입니다. 최종 선정 GP, 실제 약정·집행액, 기업투자부 실무 담당자명은 공개자료만으로 확정하지 않습니다.</p>
        <dl class="ktcu-facts">
          <div><dt>선정 GP 히스토리</dt><dd>{html_escape(gp_gap_public)}</dd></div>
          <div><dt>2025년 대표 공고</dt><dd>{html_escape(pe_notice)}</dd></div>
          <div><dt>실무자명</dt><dd>{html_escape(people_gap_public)}</dd></div>
        </dl>
      </div>
    </details>

    <details class="ktcu-evidence">
      <summary>공개 출처 보기</summary>
      <ul>
{source_rows}
      </ul>
    </details>

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
