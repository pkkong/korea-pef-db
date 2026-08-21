"""Standalone newsletter web app for Vercel.

Vercel and the GitHub Pages mirror must render the newsletter through the same
UI source. The Flask app only provides runtime data access and thin HTTP routes.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, Response, jsonify, request

WEB_ROOT = Path(__file__).resolve().parent
try:  # Package import path used by repo-root tests.
    from .newsletter_data import load_archive, select_issue  # type: ignore
    from .newsletter_ui import app_icon_png, app_web_manifest, render_app, service_css, service_js  # type: ignore
except ImportError:  # Flat import path used by Vercel root and local Flask runs.
    from newsletter_data import load_archive, select_issue  # type: ignore  # noqa: E402
    from newsletter_ui import app_icon_png, app_web_manifest, render_app, service_css, service_js  # type: ignore  # noqa: E402

app = Flask(__name__, static_folder=None)

DEFAULT_GP_PAGE_BASE_URL = "https://pkkong.github.io/kpef-newsletter"
DEFAULT_GP_PAGE_CACHE_SECONDS = 300
GP_PAGE_NAMES = {"market.html", "gps.html"}
_GP_PAGE_CACHE: dict[str, object] = {"expires_at": 0.0, "pages": {}}


def today_seoul() -> str:
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def _cache_headers(content_type: str) -> dict[str, str]:
    return {
        "Content-Type": content_type,
        "Cache-Control": "public, max-age=300, stale-while-revalidate=3600",
    }


def gp_page_base_url() -> str:
    return os.environ.get("GP_PAGE_BASE_URL", DEFAULT_GP_PAGE_BASE_URL).rstrip("/")


def fetch_gp_page_html(page_name: str) -> str:
    if page_name not in GP_PAGE_NAMES:
        raise ValueError(f"Unsupported GP page: {page_name}")
    request = Request(
        f"{gp_page_base_url()}/{page_name}",
        headers={"User-Agent": "kpef-newsletter-vercel/1.0", "Accept": "text/html"},
    )
    with urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8")


def _rewrite_gp_navigation(page_html: str) -> str:
    """Keep GP pages on Vercel while directing the currently static LP page to its public source."""
    return page_html.replace(
        'href="lp-notices.html"',
        f'href="{gp_page_base_url()}/lp-notices.html"',
    )


def load_gp_page(page_name: str, force_refresh: bool = False) -> str:
    now = time.time()
    pages = _GP_PAGE_CACHE.get("pages")
    cached_pages = pages if isinstance(pages, dict) else {}
    cached = cached_pages.get(page_name)
    if not force_refresh and isinstance(cached, str) and now < float(_GP_PAGE_CACHE.get("expires_at") or 0):
        return cached

    try:
        page_html = _rewrite_gp_navigation(fetch_gp_page_html(page_name))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, ValueError):
        if isinstance(cached, str):
            return cached
        raise

    cached_pages[page_name] = page_html
    cache_seconds = int(os.environ.get("GP_PAGE_CACHE_SECONDS", str(DEFAULT_GP_PAGE_CACHE_SECONDS)))
    _GP_PAGE_CACHE["pages"] = cached_pages
    _GP_PAGE_CACHE["expires_at"] = now + max(cache_seconds, 30)
    return page_html


def gp_public_page(page_name: str):
    try:
        page_html = load_gp_page(page_name, force_refresh=request.args.get("refresh") == "1")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, ValueError):
        return Response("GP market data is temporarily unavailable.", status=503, mimetype="text/plain")
    headers = _cache_headers("text/html; charset=utf-8")
    headers["X-GP-Data-Source"] = "verified-static-source"
    return Response(page_html, headers=headers)


@app.get("/")
@app.get("/index.html")
@app.get("/daily-news")
@app.get("/daily-news.html")
def daily_news():
    archive, data_source = load_archive(force_refresh=request.args.get("refresh") == "1")
    active_issue = select_issue(archive, request.args.get("date", ""))
    report_date = str(active_issue.get("reportDate") or today_seoul())
    html = render_app(
        report_date,
        [],
        "",
        {},
        archive if archive else None,
        [],
        newsletter_only=True,
    )
    response = Response(html, mimetype="text/html")
    response.headers["X-Newsletter-Data-Source"] = data_source
    response.headers["X-Generated-At"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return response


@app.get("/market")
@app.get("/market.html")
def gp_market():
    return gp_public_page("market.html")


@app.get("/gps")
@app.get("/gps.html")
def gp_directory():
    return gp_public_page("gps.html")


@app.get("/assets/service.css")
def service_css_asset():
    return Response(service_css(), headers=_cache_headers("text/css; charset=utf-8"))


@app.get("/assets/service.js")
def service_js_asset():
    return Response(service_js(), headers=_cache_headers("text/javascript; charset=utf-8"))


@app.get("/static/service.css")
def legacy_static_css_asset():
    return service_css_asset()


@app.get("/site.webmanifest")
def manifest_asset():
    return Response(app_web_manifest(), headers=_cache_headers("application/manifest+json; charset=utf-8"))


@app.get("/apple-touch-icon.png")
@app.get("/favicon.ico")
def icon_asset():
    return Response(app_icon_png(), headers=_cache_headers("image/png"))


@app.get("/archive.json")
def archive_json():
    archive, data_source = load_archive(force_refresh=request.args.get("refresh") == "1")
    response = jsonify(archive)
    response.headers["X-Newsletter-Data-Source"] = data_source
    return response


@app.get("/health.json")
def health_json():
    archive, data_source = load_archive(force_refresh=request.args.get("refresh") == "1")
    active_issue = select_issue(archive)
    articles = active_issue.get("articles") or []
    return jsonify(
        {
            "status": "ok" if active_issue.get("reportDate") and articles else "empty",
            "service": "newsletter",
            "runtime": "vercel-flask",
            "data_source": data_source,
            "report_date": active_issue.get("reportDate", ""),
            "article_count": len(articles),
            "issue_count": len(archive),
        }
    )


@app.get("/api/newsletter/archive")
def api_archive():
    return archive_json()
