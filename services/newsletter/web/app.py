"""Standalone newsletter web app for Vercel.

Vercel and the GitHub Pages mirror must render the newsletter through the same
UI source. The Flask app only provides runtime data access and thin HTTP routes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, request

WEB_ROOT = Path(__file__).resolve().parent
try:  # Package import path used by repo-root tests.
    from .newsletter_data import load_archive, select_issue  # type: ignore
    from .newsletter_ui import app_icon_png, app_web_manifest, render_app, service_css, service_js  # type: ignore
except ImportError:  # Flat import path used by Vercel root and local Flask runs.
    from newsletter_data import load_archive, select_issue  # type: ignore  # noqa: E402
    from newsletter_ui import app_icon_png, app_web_manifest, render_app, service_css, service_js  # type: ignore  # noqa: E402

app = Flask(__name__, static_folder=None)


def today_seoul() -> str:
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def _cache_headers(content_type: str) -> dict[str, str]:
    return {
        "Content-Type": content_type,
        "Cache-Control": "public, max-age=300, stale-while-revalidate=3600",
    }


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
