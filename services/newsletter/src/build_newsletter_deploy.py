#!/usr/bin/env python
"""Build a deployable static bundle for the newsletter-only service."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
DEFAULT_DEPLOY_DIR = SERVICE_ROOT / "deploy"
DEFAULT_SITE_DIR = DEFAULT_DEPLOY_DIR / "site"
DEFAULT_ARCHIVE_SEED_URL = os.environ.get(
    "NEWSLETTER_ARCHIVE_SEED_URL",
    "https://raw.githubusercontent.com/pkkong/kpef-newsletter/main/archive.json",
)

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
