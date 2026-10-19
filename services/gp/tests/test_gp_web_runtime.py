"""GP runtime owns its routes and continues without sibling service modules."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services.gp.web import app as web_app
from services.gp.web import gp_public_data
from services.gp.web.navigation import rewrite_gp_navigation


def sample_page(name: str = "gps.html", snapshot: str = "published-one") -> dict[str, str]:
    return {"page_html": f'<!doctype html><a href="index.html?date=2026-10-19#news">브리프</a><a href="lp-notices.html">LP</a><main>{name}</main>', "snapshot_id": snapshot, "reporting_period": "2025Q4", "as_of_date": "2025-12-31", "source_sha256": "a" * 64}


def test_gp_canonical_routes_and_home_are_owned_by_gp() -> None:
    with patch.dict(web_app._GP_PAGE_CACHE, {"snapshot_id": "", "pages": {}}, clear=True), patch.object(web_app, "fetch_active_gp_page", side_effect=sample_page):
        client = web_app.app.test_client()
        for path, name in [("/", "gps.html"), ("/index.html", "gps.html"), ("/gps", "gps.html"), ("/gps.html", "gps.html"), ("/market", "market.html"), ("/market.html", "market.html"), ("/gp-2.html", "gp-2.html"), ("/person-47.html", "person-47.html")]:
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["X-GP-Data-Source"] == "supabase-public-snapshot"
            assert response.headers["X-GP-Snapshot-Id"] == "published-one"
            assert name in response.get_data(as_text=True)
        assert client.get("/archive.json").status_code == 404
        assert client.get("/samples/lp/index.html").status_code == 404


def test_gp_navigation_preserves_queries_sources_and_internal_profiles() -> None:
    page = '''<a href='index.html?a=1&amp;b=2#date'>Brief</a><a href="./lp-notices.html?q=pe#active">LP</a><a href="https://pkkong.github.io/kpef-newsletter/gp-2.html?q=x#fund">GP</a><a href="https://source.example/index.html">Source</a><a href="#fund">Fund</a><a href="https://pkkong.github.io/unrelated/index.html">Other</a>'''
    with patch.dict(os.environ, {"NEWSLETTER_PUBLIC_URL": "https://brief.example", "LP_PUBLIC_URL": "https://lp.example", "GP_PUBLIC_URL": "https://gp.example"}):
        rewritten = rewrite_gp_navigation(page)
    assert "href='https://brief.example/?a=1&amp;b=2#date'" in rewritten
    assert 'href="https://lp.example/?q=pe#active"' in rewritten
    assert 'href="/gp-2.html?q=x#fund"' in rewritten
    assert 'href="https://source.example/index.html"' in rewritten
    assert 'href="#fund"' in rewritten
    assert 'href="https://pkkong.github.io/unrelated/index.html"' in rewritten


def test_gp_reader_verifies_stored_hash_before_navigation_changes() -> None:
    raw = sample_page()["page_html"]
    snapshot = [{"snapshot_id": "published-one", "reporting_period": "2025Q4"}]
    pages = [{"page_html": raw, "content_sha256": hashlib.sha256(raw.encode()).hexdigest()}]
    with patch.object(gp_public_data, "_supabase_config", return_value=("https://db.example", "public-key")), patch.object(gp_public_data, "_request_json", side_effect=[snapshot, pages]):
        verified = gp_public_data.fetch_active_gp_page("gps.html")
    assert verified["page_html"] == raw
    with patch.dict(web_app._GP_PAGE_CACHE, {"snapshot_id": "", "pages": {}}, clear=True), patch.object(web_app, "fetch_active_gp_page", return_value=verified):
        result = web_app.load_gp_page("gps.html")
        assert 'href="https://kpef-newsletter.vercel.app/?date=2026-10-19#news"' in result["page_html"]
    pages[0]["page_html"] += "changed"
    with patch.object(gp_public_data, "_supabase_config", return_value=("https://db.example", "public-key")), patch.object(gp_public_data, "_request_json", side_effect=[snapshot, pages]):
        try:
            gp_public_data.fetch_active_gp_page("gps.html")
        except gp_public_data.GPPublicDataError as error:
            assert "hash" in str(error)
        else:
            raise AssertionError("Corrupt GP snapshot was accepted")


def test_gp_expiry_is_per_page_and_new_snapshot_invalidates_old_pages() -> None:
    clock = [1000.0]
    calls = []
    version = ["one"]
    def fetch(name):
        calls.append(name)
        return sample_page(name, version[0])
    with patch.dict(web_app._GP_PAGE_CACHE, {"snapshot_id": "", "pages": {}}, clear=True), patch.object(web_app.time, "time", lambda: clock[0]), patch.object(web_app, "fetch_active_gp_page", side_effect=fetch):
        web_app.load_gp_page("gps.html")
        clock[0] += 100
        web_app.load_gp_page("gp-1.html")
        clock[0] += 201
        web_app.load_gp_page("gps.html")
        assert calls == ["gps.html", "gp-1.html", "gps.html"]
        version[0] = "two"
        web_app.load_gp_page("gp-2.html")
        assert web_app.load_gp_page("gps.html")["snapshot_id"] == "two"


def test_gp_outage_serves_bounded_stale_then_controlled_failure() -> None:
    clock = [1000.0]
    with patch.dict(web_app._GP_PAGE_CACHE, {"snapshot_id": "", "pages": {}}, clear=True), patch.object(web_app.time, "time", lambda: clock[0]), patch.object(web_app, "fetch_active_gp_page", return_value=sample_page()):
        client = web_app.app.test_client()
        assert client.get("/").status_code == 200
        with patch.object(web_app, "fetch_active_gp_page", side_effect=OSError("DB unavailable")):
            clock[0] = 1301
            response = client.get("/")
            assert response.status_code == 200
            assert response.headers["X-GP-Cache-Status"] == "stale"
            assert response.headers["Cache-Control"] == "no-store"
            assert client.get("/health.json").get_json()["status"] == "degraded"
            clock[0] = 5000
            assert client.get("/").status_code == 503
            health = client.get("/health.json")
            assert health.status_code == 503
            assert health.get_json() == {"service": "gp", "status": "unavailable"}
            assert client.get("/assets/service.css").status_code == 200


def test_gp_download_has_its_own_file_and_preserves_filename() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / web_app.GP_RANKING_DATAPACK_NAME
        path.write_bytes(b"PKtest-pack")
        with patch.object(web_app, "GP_RANKING_DATAPACK_PATH", path):
            response = web_app.app.test_client().get("/downloads/gp-ranking-datapack-2025ye.xlsx")
            assert response.status_code == 200
            assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            assert 'attachment; filename=gp_ranking_datapack_2025YE.xlsx' in response.headers["Content-Disposition"]
            assert response.headers["X-GP-Data-Pack-Period"] == "2025Q4"
            assert response.get_data().startswith(b"PK")
            response.close()
        with patch.object(web_app, "GP_RANKING_DATAPACK_PATH", path.with_name("missing.xlsx")):
            assert web_app.app.test_client().get("/downloads/gp-ranking-datapack-2025ye.xlsx").status_code == 404


def test_gp_import_and_assets_work_when_sibling_services_cannot_import() -> None:
    code = '''import importlib.abc, sys
class BlockSibling(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("services.newsletter", "services.lp", "newsletter_", "lp_")):
            raise RuntimeError("Sibling service must not be imported: " + fullname)
sys.meta_path.insert(0, BlockSibling())
from services.gp.web.app import app
client=app.test_client()
assert client.get("/assets/service.css").status_code == 200
assert client.get("/assets/service.js").status_code == 200
assert client.get("/site.webmanifest").get_json()["start_url"] == "/"
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[3], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_gp_public_reader_rejects_non_gp_routes_before_request() -> None:
    with patch.object(gp_public_data, "_request_json") as request:
        for name in ["../index.html", "lp-notices.html", "gps.html?x=1", "archive.json"]:
            try:
                gp_public_data.fetch_active_gp_page(name)
            except gp_public_data.GPPublicDataError:
                pass
            else:
                raise AssertionError(name)
        request.assert_not_called()


def test_gp_legacy_asset_links_are_served_by_own_runtime() -> None:
    raw = '<link href="https://kpef-newsletter.vercel.app/assets/service.css?v=3"><script src="https://pkkong.github.io/kpef-newsletter/assets/service.js?v=3"></script><link href="https://external.example/assets/service.css">'
    rewritten = rewrite_gp_navigation(raw)
    assert 'href="/assets/service.css?v=3"' in rewritten
    assert 'src="/assets/service.js?v=3"' in rewritten
    assert 'href="https://external.example/assets/service.css"' in rewritten
