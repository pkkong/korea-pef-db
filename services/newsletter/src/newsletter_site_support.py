#!/usr/bin/env python
"""Newsletter-only static site support helpers.

This module is intentionally independent from LP, GP, Wiki, and the legacy
``build_newsletter_deploy`` monolith so the daily newsletter publish path stays
import-isolated.
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from services.newsletter.src.daily_news_common import normalize_url


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
DEFAULT_DEPLOY_DIR = SERVICE_ROOT / "deploy"
DEFAULT_SITE_DIR = DEFAULT_DEPLOY_DIR / "site"
DEFAULT_ARCHIVE_LIMIT = 30
DEFAULT_ARCHIVE_SEED_URL = os.environ.get(
    "NEWSLETTER_ARCHIVE_SEED_URL",
    "https://raw.githubusercontent.com/pkkong/kpef-newsletter/gh-pages/archive.json",
)
ARCHIVE_SCRIPT_RE = re.compile(
    r"<script>window\.KPEF_DAILY_ARCHIVE\s*=\s*(?P<payload>.*?);</script>",
    re.DOTALL,
)


def assert_newsletter_only(site_dir: Path) -> None:
    for name in ["index.html", "daily-news.html"]:
        html_path = site_dir / name
        if not html_path.exists():
            raise RuntimeError(f"{name} was not generated")
        html = html_path.read_text(encoding="utf-8")
        if 'href="db.html#lp"' in html or 'href="db.html#profile"' in html:
            raise RuntimeError(f"{name} still contains obsolete DB-anchor navigation")
        if "window.KPEF_LP_MONITOR" in html:
            raise RuntimeError(f"{name} still embeds LP monitor data")
    if (site_dir / "admin.html").exists():
        raise RuntimeError("admin.html must not be included in the public deploy site")


def write_health_file(site_dir: Path, result: dict[str, str]) -> None:
    def int_result(*keys: str) -> int:
        for key in keys:
            value = result.get(key)
            if value is not None and str(value).strip() != "":
                return int(value or 0)
        return 0

    payload = {
        "service": "kpef-newsletter",
        "services": result.get("services", "newsletter"),
        "status": "ok",
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "report_date": result.get("report_date", ""),
        "article_count": int_result("article_count"),
        "lp_monitor_count": int_result("lp_monitor_count"),
        "ktcu_fact_count": int_result("ktcu_fact_count"),
        "lp_profile_fact_count": int_result("lp_profile_fact_count", "ktcu_fact_count"),
        "lp_profile_page_count": int_result("lp_profile_page_count"),
        "gp_count": int_result("gp_count"),
        "gp_active_count": int_result("active_gp_count", "gp_active_count"),
        "gp_profile_page_count": int_result("top_gp_page_count", "gp_profile_page_count"),
        "gp_news_link_count": int_result("news_link_count", "gp_news_link_count"),
    }
    (site_dir / "health.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_static_support_files(site_dir: Path) -> None:
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
    (site_dir / "robots.txt").write_text("User-agent: *\nDisallow:\n", encoding="utf-8")
    index_path = site_dir / "index.html"
    if index_path.exists():
        (site_dir / "404.html").write_text(index_path.read_text(encoding="utf-8"), encoding="utf-8")


def remove_legacy_public_db_files(site_dir: Path) -> None:
    for relative_path in [
        "db.html",
        "assets/app.css",
        "assets/app.js",
        "data/service_data.json",
        "admin.html",
    ]:
        (site_dir / relative_path).unlink(missing_ok=True)


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


def read_archive_seed(seed_url: str, required: bool = False) -> list[dict[str, object]]:
    if not seed_url:
        if required:
            raise RuntimeError("archive seed URL is required for newsletter publish")
        return []
    try:
        with urlopen(seed_url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        if required:
            raise RuntimeError(f"archive seed unavailable url={seed_url}: {exc}") from exc
        return []
    if not isinstance(payload, list):
        if required:
            raise RuntimeError(f"archive seed is not a list: {seed_url}")
        return []
    if required and not payload:
        raise RuntimeError(f"archive seed has no entries: {seed_url}")
    return payload


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
    remove_cross_date_duplicate_articles(by_date)
    merged = [by_date[date] for date in sorted(by_date, reverse=True)]
    if archive_limit > 0:
        merged = merged[:archive_limit]
    return merged


def remove_cross_date_duplicate_articles(by_date: dict[str, dict[str, object]]) -> None:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for report_date in sorted(by_date):
        articles = by_date[report_date].get("articles")
        if not isinstance(articles, list):
            continue
        deduped: list[object] = []
        for article in articles:
            if not isinstance(article, dict):
                deduped.append(article)
                continue
            normalized = normalize_url(str(article.get("url") or article.get("sourceUrl") or ""))
            title_key = normalize_archive_title_key(str(article.get("title") or ""))
            if normalized and normalized in seen_urls:
                continue
            if title_key and title_key in seen_titles:
                continue
            if normalized:
                seen_urls.add(normalized)
            if title_key:
                seen_titles.add(title_key)
            deduped.append(article)
        by_date[report_date]["articles"] = deduped


def normalize_archive_title_key(title: str) -> str:
    value = re.sub(r"\s+-\s+[^-]+$", "", title or "")
    value = re.sub(r"\s*\[[^\]]*(?:\]|$)", "", value)
    value = re.sub(r"\.{2,}|…+", "", value)
    value = re.sub(r"[\[\]\"'‘’“”<>(){}|·:：,\s]+", "", value)
    return value.lower()[:42]


def archive_article_count(archive_entries: list[dict[str, object]], report_date: str, fallback: int) -> int:
    for entry in archive_entries:
        if str(entry.get("reportDate") or "") != report_date:
            continue
        articles = entry.get("articles")
        if isinstance(articles, list):
            return len(articles)
    return fallback


def zip_newsletter_site(deploy_dir: Path, site_dir: Path) -> Path:
    zip_path = deploy_dir / "kpef-newsletter-site.zip"
    if zip_path.exists():
        zip_path.unlink()
    include_paths = [
        site_dir / "index.html",
        site_dir / "daily-news.html",
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


def zip_site_tree(deploy_dir: Path, site_dir: Path) -> Path:
    zip_path = deploy_dir / "kpef-newsletter-site.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(site_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(site_dir))
    return zip_path
