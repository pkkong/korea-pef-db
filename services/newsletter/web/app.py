"""Independent newsletter runtime; LP/GP are optional outbound links only."""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from flask import Flask, Response, jsonify, request, redirect

try:
    from .newsletter_data import NewsletterDataError, archive_cache_status, load_archive, select_issue
    from .newsletter_ui import app_icon_png, app_web_manifest, render_app, service_css, service_js
except ImportError:
    from newsletter_data import NewsletterDataError, archive_cache_status, load_archive, select_issue
    from newsletter_ui import app_icon_png, app_web_manifest, render_app, service_css, service_js

app = Flask(__name__, static_folder=None)


def service_url(service: str, path: str = "") -> str:
    base = os.environ.get(f"{service.upper()}_PUBLIC_URL", f"https://kpef-{service}.vercel.app").rstrip("/")
    return base + "/" + path.lstrip("/")


def service_redirect(service: str, path: str = ""):
    target = service_url(service, path)
    if request.query_string:
        target += "?" + request.query_string.decode("ascii", errors="replace")
    # A link requires no import, data query or health check of the other service.
    return redirect(target, code=307)


@app.get("/samples/lp/<filename>")
def old_lp_sample(filename: str):
    return service_redirect("lp", quote(filename, safe="-_."))


@app.get("/admin/lp")
def old_lp_review():
    return service_redirect("lp", "review.html")


@app.get("/lp-notices.html")
def old_lp_directory():
    return service_redirect("lp")


@app.get("/gps")
@app.get("/gps.html")
def old_gp_directory():
    return service_redirect("gp", "gps.html")


@app.get("/market")
@app.get("/market.html")
def old_gp_market():
    return service_redirect("gp", "market.html")


@app.get("/gp-<int:gp_id>.html")
def old_gp_profile(gp_id: int):
    return service_redirect("gp", f"gp-{gp_id}.html")


@app.get("/person-<int:person_id>.html")
def old_gp_person(person_id: int):
    return service_redirect("gp", f"person-{person_id}.html")


@app.get("/downloads/gp-ranking-datapack-2025ye.xlsx")
def old_gp_download():
    return service_redirect("gp", "downloads/gp-ranking-datapack-2025ye.xlsx")


def today_seoul() -> str:
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def _cache_headers(content_type: str) -> dict[str, str]:
    return {
        "Content-Type": content_type,
        "Cache-Control": "public, max-age=300, stale-while-revalidate=3600",
    }


@app.errorhandler(NewsletterDataError)
def newsletter_unavailable(error: NewsletterDataError):
    if request.path in {"/health.json", "/archive.json", "/api/newsletter/archive"}:
        response = jsonify({
            "status": "unavailable",
            "service": "newsletter",
            "release": os.environ.get("SERVICE_RELEASE", "local"),
            "runtime": "vercel-flask",
            "data_source": "unavailable",
            "report_date": "",
            "article_count": 0,
            "issue_count": 0,
            **archive_cache_status(),
        })
    else:
        response = Response("브리프를 잠시 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.", mimetype="text/plain")
    response.status_code = 503
    response.headers["Retry-After"] = "60"
    response.headers["Cache-Control"] = "no-store"
    return response


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
        gp_url=service_url("gp", "gps.html"),
        lp_url=service_url("lp"),
    )
    response = Response(html, mimetype="text/html")
    response.headers["X-Newsletter-Data-Source"] = data_source
    response.headers["X-Generated-At"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if data_source == "stale_cache":
        response.headers["Cache-Control"] = "no-store"
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
    if data_source == "stale_cache":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health.json")
def health_json():
    archive, data_source = load_archive(force_refresh=request.args.get("refresh") == "1")
    active_issue = select_issue(archive)
    articles = active_issue.get("articles") or []
    return jsonify(
        {
            "status": "degraded" if data_source == "stale_cache" else ("ok" if active_issue.get("reportDate") and articles else "empty"),
            "service": "newsletter",
            "release": os.environ.get("SERVICE_RELEASE", "local"),
            "runtime": "vercel-flask",
            "data_source": data_source,
            "report_date": active_issue.get("reportDate", ""),
            "article_count": len(articles),
            "issue_count": len(archive),
            "stale": data_source == "stale_cache",
            **archive_cache_status(),
        }
    )


@app.get("/api/newsletter/archive")
def api_archive():
    return archive_json()
