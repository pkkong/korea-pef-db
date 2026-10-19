"""Independent GP directory, profiles and market-data HTTP runtime."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from flask import Flask, Response, jsonify, request, send_file

if __package__:
    from .gp_public_data import GPPublicDataError, fetch_active_gp_page
    from .navigation import rewrite_gp_navigation
else:
    from gp_public_data import GPPublicDataError, fetch_active_gp_page
    from navigation import rewrite_gp_navigation

try:
    from services.shared.web.service_assets import service_css, service_js, app_icon_png
except ModuleNotFoundError as error:
    if error.name not in {"services", "services.shared", "services.shared.web", "services.shared.web.service_assets"}:
        raise
    from service_assets import service_css, service_js, app_icon_png

WEB_ROOT = Path(__file__).resolve().parent
DOWNLOADS_ROOT = WEB_ROOT / "downloads"
GP_RANKING_DATAPACK_NAME = "gp_ranking_datapack_2025YE.xlsx"
GP_RANKING_DATAPACK_PATH = DOWNLOADS_ROOT / GP_RANKING_DATAPACK_NAME
app = Flask(__name__, static_folder=None)

DEFAULT_GP_PAGE_CACHE_SECONDS = 300
DEFAULT_GP_STALE_IF_ERROR_SECONDS = 3600
_GP_PAGE_CACHE: dict[str, object] = {"snapshot_id": "", "pages": {}}
_GP_CACHE_LOCK = RLock()


def _cache_headers(content_type: str) -> dict[str, str]:
    return {
        "Content-Type": content_type,
        "Cache-Control": "public, max-age=300, stale-while-revalidate=3600",
    }


def load_gp_page(page_name: str, force_refresh: bool = False) -> dict[str, str]:
    # Serialize refreshes so an older in-flight response cannot restore a
    # snapshot after another request has observed its replacement.
    with _GP_CACHE_LOCK:
        return _load_gp_page(page_name, force_refresh)


def _load_gp_page(page_name: str, force_refresh: bool) -> dict[str, str]:
    now = time.time()
    pages = _GP_PAGE_CACHE.get("pages")
    cached_pages = pages if isinstance(pages, dict) else {}
    entry = cached_pages.get(page_name) or {}
    cached = entry.get("page")
    if not force_refresh and isinstance(cached, dict) and now < float(entry.get("expires_at") or 0):
        return dict(cached)

    try:
        page = dict(fetch_active_gp_page(page_name))
        page["page_html"] = rewrite_gp_navigation(page["page_html"])
    except (GPPublicDataError, OSError, TimeoutError, UnicodeDecodeError, ValueError):
        stale_seconds = max(0, int(os.environ.get("GP_PAGE_STALE_IF_ERROR_SECONDS", str(DEFAULT_GP_STALE_IF_ERROR_SECONDS))))
        if isinstance(cached, dict) and time.time() < float(entry.get("expires_at") or 0) + stale_seconds:
            return {**cached, "cache_status": "stale"}
        raise

    if page.get("snapshot_id") != _GP_PAGE_CACHE.get("snapshot_id"):
        cached_pages = {}
    _GP_PAGE_CACHE["snapshot_id"] = page.get("snapshot_id", "")
    now = time.time()
    page["cache_status"] = "fresh"
    page["last_success_at"] = datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds")
    cache_seconds = int(os.environ.get("GP_PAGE_CACHE_SECONDS", str(DEFAULT_GP_PAGE_CACHE_SECONDS)))
    cached_pages[page_name] = {"page": page, "expires_at": now + max(cache_seconds, 30)}
    _GP_PAGE_CACHE["pages"] = cached_pages
    return dict(page)


def gp_public_page(page_name: str):
    try:
        page = load_gp_page(page_name, force_refresh=request.args.get("refresh") == "1")
    except (GPPublicDataError, OSError, TimeoutError, UnicodeDecodeError, ValueError):
        return Response("GP 정보를 잠시 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.", status=503, content_type="text/plain; charset=utf-8", headers={"Retry-After": "60", "Cache-Control": "no-store"})
    headers = _cache_headers("text/html; charset=utf-8")
    headers["X-GP-Data-Source"] = "supabase-public-snapshot"
    headers["X-GP-Snapshot-Id"] = page.get("snapshot_id", "")
    headers["X-GP-Reporting-Period"] = page.get("reporting_period", "")
    headers["X-GP-Cache-Status"] = page.get("cache_status", "fresh")
    headers["X-GP-Last-Success-At"] = page.get("last_success_at", "")
    if page.get("cache_status") == "stale":
        headers["Cache-Control"] = "no-store"
    return Response(page["page_html"], headers=headers)


@app.get("/market")
@app.get("/market.html")
def gp_market():
    return gp_public_page("market.html")


@app.get("/")
@app.get("/index.html")
@app.get("/gps")
@app.get("/gps.html")
def gp_directory():
    return gp_public_page("gps.html")


@app.get("/gp-<int:gp_id>.html")
def gp_profile(gp_id: int):
    return gp_public_page(f"gp-{gp_id}.html")


@app.get("/person-<int:person_id>.html")
def person_profile(person_id: int):
    return gp_public_page(f"person-{person_id}.html")


@app.get("/downloads/gp-ranking-datapack-2025ye.xlsx")
def gp_ranking_datapack_download():
    if not GP_RANKING_DATAPACK_PATH.is_file():
        return Response("The requested data pack is unavailable.", status=404, mimetype="text/plain")
    response = send_file(
        GP_RANKING_DATAPACK_PATH,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=GP_RANKING_DATAPACK_NAME,
        max_age=3600,
    )
    response.headers["X-GP-Data-Pack-Period"] = "2025Q4"
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
    payload = {"name": "Korea PEF GP", "short_name": "KPEF GP", "start_url": "/", "scope": "/", "display": "standalone", "theme_color": "#eaf7ff", "background_color": "#eaf7ff", "icons": [{"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"}]}
    return Response(json.dumps(payload), headers=_cache_headers("application/manifest+json; charset=utf-8"))


@app.get("/apple-touch-icon.png")
@app.get("/favicon.ico")
def icon_asset():
    return Response(app_icon_png(), headers=_cache_headers("image/png"))


@app.get("/health.json")
def health_json():
    try:
        page = load_gp_page("gps.html", force_refresh=request.args.get("refresh") == "1")
    except (GPPublicDataError, OSError, TimeoutError, UnicodeDecodeError, ValueError):
        return jsonify({"status": "unavailable", "service": "gp"}), 503, {"Retry-After": "60", "Cache-Control": "no-store"}
    return jsonify({"status": "degraded" if page.get("cache_status") == "stale" else "ok", "service": "gp", "release": os.environ.get("SERVICE_RELEASE", "local"), "snapshot_id": page.get("snapshot_id", ""), "reporting_period": page.get("reporting_period", ""), "cache_status": page.get("cache_status", "fresh"), "last_success_at": page.get("last_success_at", "")}), 200, {"Cache-Control": "no-store"}
