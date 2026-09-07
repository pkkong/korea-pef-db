#!/usr/bin/env python
"""No-network checks for the Vercel newsletter data adapter."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from newsletter_data import (  # noqa: E402
    _filter_article_rows_to_issues,
    archive_from_supabase_rows,
    filter_articles,
    grouped_sections,
    select_issue,
)
import newsletter_data  # noqa: E402
from newsletter_ui import render_app, service_js  # noqa: E402
import app as web_app  # noqa: E402


def sample_archive() -> list[dict[str, object]]:
    return [
        {
            "reportDate": "2026-06-16",
            "visibleDate": "2026.06.16",
            "basis": "",
            "articles": [
                {
                    "id": "a",
                    "rank": 0,
                    "title": "국민성장펀드 기사",
                    "source": "테스트신문",
                    "url": "https://example.com/a",
                    "section": "LP",
                    "summaryLines": ["요약"],
                    "lpNames": ["한국성장금융"],
                    "gpNames": [],
                },
                {
                    "id": "b",
                    "rank": 1,
                    "title": "바이아웃 기사",
                    "source": "테스트신문",
                    "url": "https://example.com/b",
                    "section": "Deal",
                    "summaryLines": ["요약"],
                    "gpNames": ["테스트PE"],
                    "lpNames": [],
                },
            ],
        }
    ]


def test_archive_from_supabase_rows_keeps_issue_skeletons_and_zero_section_order() -> None:
    issue_rows = [
        {
            "issue_date": "2026-06-17",
            "visible_date": "2026년 6월 17일",
            "basis": "전일",
            "article_count": 0,
        },
        {
            "issue_date": "2026-06-16",
            "visible_date": "2026년 6월 16일",
            "basis": "전일",
            "article_count": 2,
        },
    ]
    rows = [
        {
            "issue_date": "2026-06-16",
            "visible_date": "2026년 6월 16일",
            "rank": 1,
            "article_id": "b",
            "title": "둘째 기사",
            "publisher": "테스트신문",
            "source_url": "https://example.com/b",
            "section": "LP",
            "summary_lines": ["요약"],
            "gp_names": [],
            "lp_names": ["한국성장금융"],
        },
        {
            "issue_date": "2026-06-16",
            "visible_date": "2026년 6월 16일",
            "rank": 0,
            "section_order": 0,
            "article_id": "a",
            "title": "첫 기사",
            "publisher": "테스트신문",
            "source_url": "https://example.com/a",
            "section": "GP",
            "summary_lines": ["요약"],
            "gp_names": ["테스트인베스트먼트"],
            "lp_names": [],
        },
    ]

    archive = archive_from_supabase_rows(rows, issue_rows)

    assert len(archive) == 2
    assert archive[0]["reportDate"] == "2026-06-17"
    assert archive[0]["articleCount"] == 0
    assert archive[0]["articles"] == []
    assert archive[1]["reportDate"] == "2026-06-16"
    assert archive[1]["articleCount"] == 2
    assert [row["title"] for row in archive[1]["articles"]] == ["첫 기사", "둘째 기사"]
    assert archive[1]["articles"][0]["sectionOrder"] == 0


def test_supabase_archive_filters_articles_to_selected_issue_window() -> None:
    issue_rows = [{"issue_date": "2026-06-17"}, {"issue_date": "2026-06-16"}]
    rows = [
        {
            "issue_date": "2026-06-17",
            "rank": 0,
            "article_id": "new",
            "title": "최근 기사",
            "publisher": "테스트신문",
            "source_url": "https://example.com/new",
        },
        {
            "issue_date": "2026-06-15",
            "rank": 0,
            "article_id": "old",
            "title": "범위 밖 기사",
            "publisher": "테스트신문",
            "source_url": "https://example.com/old",
        },
    ]
    filtered_rows = _filter_article_rows_to_issues(rows, issue_rows)
    archive = archive_from_supabase_rows(
        filtered_rows,
        issue_rows,
    )

    assert [row["title"] for row in filtered_rows] == ["최근 기사"]
    assert [issue["reportDate"] for issue in archive] == ["2026-06-17", "2026-06-16"]
    assert [row["title"] for row in archive[0]["articles"]] == ["최근 기사"]
    assert archive[1]["articles"] == []


def test_filter_and_group_articles() -> None:
    issue = {
        "reportDate": "2026-06-16",
        "articles": [
            {"title": "국민성장펀드 기사", "section": "LP", "source": "A", "lpNames": ["한국성장금융"]},
            {"title": "바이아웃 기사", "section": "Deal", "source": "B", "gpNames": ["테스트PE"]},
        ],
    }

    active = select_issue([issue], "2026-06-16")
    filtered = filter_articles(active, "성장금융")
    grouped = grouped_sections(filtered)

    assert len(filtered) == 1
    assert grouped[0][0] == "LP"


def test_load_archive_prefers_newer_raw_archive_when_supabase_lags() -> None:
    supabase_archive = sample_archive()
    raw_archive = [
        {
            "reportDate": "2026-06-17",
            "visibleDate": "2026.06.17",
            "articles": [
                {
                    "id": "fresh",
                    "rank": 0,
                    "title": "최신 기사",
                    "source": "테스트신문",
                    "url": "https://example.com/fresh",
                    "section": "Market",
                }
            ],
        },
        *supabase_archive,
    ]
    old_cache = dict(newsletter_data._CACHE)
    old_supabase = newsletter_data.fetch_supabase_archive
    old_urls = newsletter_data.archive_fallback_urls
    old_archive_fetch = newsletter_data.fetch_archive_url_from
    newsletter_data._CACHE.update({"expires_at": 0.0, "archive": [], "source": "empty"})
    newsletter_data.fetch_supabase_archive = lambda: supabase_archive
    newsletter_data.archive_fallback_urls = lambda: ["pages", "raw"]
    newsletter_data.fetch_archive_url_from = lambda url, **kwargs: raw_archive if url == "raw" else supabase_archive
    try:
        archive, source = newsletter_data.load_archive(force_refresh=True)

        assert source == "archive_fallback"
        assert archive[0]["reportDate"] == "2026-06-17"
        assert archive[0]["articles"][0]["title"] == "최신 기사"
    finally:
        newsletter_data.fetch_supabase_archive = old_supabase
        newsletter_data.archive_fallback_urls = old_urls
        newsletter_data.fetch_archive_url_from = old_archive_fetch
        newsletter_data._CACHE.update(old_cache)


def test_load_archive_keeps_supabase_when_archive_fallback_is_not_newer() -> None:
    supabase_archive = sample_archive()
    older_archive = [
        {
            "reportDate": "2026-06-15",
            "visibleDate": "2026.06.15",
            "articles": [
                {
                    "id": "old",
                    "rank": 0,
                    "title": "이전 기사",
                    "source": "테스트신문",
                    "url": "https://example.com/old",
                    "section": "Market",
                }
            ],
        }
    ]
    old_cache = dict(newsletter_data._CACHE)
    old_supabase = newsletter_data.fetch_supabase_archive
    old_urls = newsletter_data.archive_fallback_urls
    old_archive_fetch = newsletter_data.fetch_archive_url_from
    newsletter_data._CACHE.update({"expires_at": 0.0, "archive": [], "source": "empty"})
    newsletter_data.fetch_supabase_archive = lambda: supabase_archive
    newsletter_data.archive_fallback_urls = lambda: ["raw"]
    newsletter_data.fetch_archive_url_from = lambda url, **kwargs: older_archive
    try:
        archive, source = newsletter_data.load_archive(force_refresh=True)

        assert source == "supabase"
        assert archive[0]["reportDate"] == "2026-06-16"
    finally:
        newsletter_data.fetch_supabase_archive = old_supabase
        newsletter_data.archive_fallback_urls = old_urls
        newsletter_data.fetch_archive_url_from = old_archive_fetch
        newsletter_data._CACHE.update(old_cache)


def test_vercel_app_uses_common_newsletter_ui() -> None:
    old_loader = web_app.load_archive
    web_app.load_archive = lambda force_refresh=False: (sample_archive(), "test")
    try:
        client = web_app.app.test_client()
        response = client.get("/")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert response.headers["X-Newsletter-Data-Source"] == "test"
        assert "window.KPEF_DAILY_ARCHIVE" in html
        assert "brief-section-tabs" in html
        assert "bottom-nav newsletter-only" in html
        assert 'href="assets/service.css' in html
        assert 'src="assets/service.js' in html
        assert 'href="https://pkkong.github.io/kpef-newsletter/lp-notices.html"' in html
        assert 'href="/gps.html"' in html
        assert 'href="lp-notices.html"' not in html
        assert 'href="gps.html"' not in html
        assert "/static/service.css" not in html
        assert 'id="resultSummary"' in html

        css = client.get("/assets/service.css")
        legacy_css = client.get("/static/service.css")
        js = client.get("/assets/service.js")
        assert css.status_code == 200
        assert legacy_css.status_code == 200
        assert legacy_css.get_data() == css.get_data()
        assert ".brief-section-tabs" in css.get_data(as_text=True)
        assert "window.KPEF_DAILY_ARCHIVE" in js.get_data(as_text=True)
    finally:
        web_app.load_archive = old_loader


def test_vercel_app_serves_gp_pages_at_canonical_routes() -> None:
    old_fetch = web_app.fetch_active_gp_page
    old_cache = {
        "expires_at": web_app._GP_PAGE_CACHE.get("expires_at", 0.0),
        "pages": dict(web_app._GP_PAGE_CACHE.get("pages") or {}),
    }

    def fake_fetch(page_name: str) -> dict[str, str]:
        return {
            "page_html": f'<!doctype html><a href="lp-notices.html">LP</a><main>{page_name} 2025Q4</main>',
            "snapshot_id": "fss-2025q4-test",
            "reporting_period": "2025Q4",
            "as_of_date": "2025-12-31",
            "source_sha256": "a" * 64,
        }

    web_app.fetch_active_gp_page = fake_fetch
    web_app._GP_PAGE_CACHE.update({"expires_at": 0.0, "pages": {}})
    try:
        client = web_app.app.test_client()
        market = client.get("/market.html?refresh=1")
        directory = client.get("/gps.html?refresh=1")
        profile = client.get("/gp-2.html?refresh=1")
        person = client.get("/person-47.html?refresh=1")

        assert market.status_code == 200
        assert directory.status_code == 200
        assert profile.status_code == 200
        assert person.status_code == 200
        assert market.headers["X-GP-Data-Source"] == "supabase-public-snapshot"
        assert market.headers["X-GP-Snapshot-Id"] == "fss-2025q4-test"
        assert "market.html 2025Q4" in market.get_data(as_text=True)
        assert "gps.html 2025Q4" in directory.get_data(as_text=True)
        assert "gp-2.html 2025Q4" in profile.get_data(as_text=True)
        assert "person-47.html 2025Q4" in person.get_data(as_text=True)
        assert 'href="https://pkkong.github.io/kpef-newsletter/lp-notices.html"' in market.get_data(as_text=True)
    finally:
        web_app.fetch_active_gp_page = old_fetch
        web_app._GP_PAGE_CACHE.update(old_cache)


def test_vercel_app_serves_gp_ranking_data_pack_as_a_download() -> None:
    client = web_app.app.test_client()
    response = client.get("/downloads/gp-ranking-datapack-2025ye.xlsx")

    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert 'attachment; filename=gp_ranking_datapack_2025YE.xlsx' in response.headers["Content-Disposition"]
    assert response.headers["X-GP-Data-Pack-Period"] == "2025Q4"
    assert response.get_data().startswith(b"PK")


def test_common_ui_marks_empty_issue_dates_for_public_users() -> None:
    html = render_app(
        "2026-06-17",
        [],
        "",
        {},
        [
            {
                "reportDate": "2026-06-17",
                "visibleDate": "2026.06.17",
                "articleCount": 0,
                "articles": [],
            },
            {
                "reportDate": "2026-06-16",
                "visibleDate": "2026.06.16",
                "articleCount": 1,
                "articles": [
                    {
                        "title": "테스트 기사",
                        "source": "테스트신문",
                        "url": "https://example.com/a",
                        "section": "Market",
                    }
                ],
            },
        ],
        [],
        newsletter_only=True,
    )

    assert "2026.06.17 · 발행 없음" in html
    assert 'id="resultSummary"' in html
    assert "전체 아카이브 검색" in service_js()
    assert "발행 없음" in service_js()


def test_vercel_app_imports_from_repo_root_package_path() -> None:
    module = importlib.import_module("services.newsletter.web.app")
    assert module.app.name == "services.newsletter.web.app"


def test_vercel_runtime_has_no_standalone_ui_or_legacy_service_imports() -> None:
    assert not (WEB_ROOT / "templates" / "daily_news.html").exists()
    assert not (WEB_ROOT / "static" / "service.css").exists()

    forbidden = [
        "build_service_site",
        "build_newsletter_deploy",
        "services.lp",
        "services.gp",
        "services.wiki",
        "pef_wiki",
    ]
    for path in [WEB_ROOT / "app.py", WEB_ROOT / "index.py", WEB_ROOT / "newsletter_data.py", WEB_ROOT / "gp_public_data.py"]:
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path.name} must not import or mention {token}"


def test_vercel_config_uses_flask_framework_without_catchall_index_rewrite() -> None:
    config = json.loads((WEB_ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert config.get("framework") == "flask"

    for rewrite in config.get("rewrites") or []:
        assert not (
            rewrite.get("source") in {"/(.*)", "/:path*"}
            and rewrite.get("destination") in {"/index.py", "index.py"}
        ), "Vercel must not rewrite every request to /index.py; it makes public routes 404."



def test_gp_page_expiry_is_independent_of_other_page_refresh() -> None:
    from unittest.mock import patch
    clock = [1000.0]
    calls = []
    def fetch(name):
        calls.append(name)
        return {"snapshot_id": "one", "page_html": name}
    with patch.dict(web_app._GP_PAGE_CACHE, {"snapshot_id": "", "pages": {}}, clear=True), patch.object(web_app.time, "time", lambda: clock[0]), patch.object(web_app, "fetch_active_gp_page", fetch):
        web_app.load_gp_page("gps.html")
        clock[0] += 100
        web_app.load_gp_page("gp-1.html")
        clock[0] += 201
        web_app.load_gp_page("gps.html")
    assert calls == ["gps.html", "gp-1.html", "gps.html"]


def test_new_gp_snapshot_invalidates_old_directory() -> None:
    from unittest.mock import patch
    version = ["old"]
    def fetch(name):
        return {"snapshot_id": version[0], "page_html": name}
    with patch.dict(web_app._GP_PAGE_CACHE, {"snapshot_id": "", "pages": {}}, clear=True), patch.object(web_app, "fetch_active_gp_page", fetch):
        web_app.load_gp_page("gps.html")
        version[0] = "new"
        web_app.load_gp_page("gp-1.html")
        assert web_app.load_gp_page("gps.html")["snapshot_id"] == "new"


def test_gp_outage_cache_has_time_limit() -> None:
    from unittest.mock import patch
    clock = [1000.0]
    with patch.dict(web_app._GP_PAGE_CACHE, {"snapshot_id": "", "pages": {}}, clear=True), patch.object(web_app.time, "time", lambda: clock[0]), patch.object(web_app, "fetch_active_gp_page", return_value={"snapshot_id": "old", "page_html": "ok"}):
        web_app.load_gp_page("gps.html")
        with patch.object(web_app, "fetch_active_gp_page", side_effect=OSError("outage")):
            clock[0] = 1301
            assert web_app.load_gp_page("gps.html")["cache_status"] == "stale"
            clock[0] = 5000
            response = web_app.app.test_client().get("/gps.html")
            assert response.status_code == 503


def test_news_outage_serves_last_good_archive_then_returns_controlled_503() -> None:
    from unittest.mock import patch
    clock = [1000.0]
    cache = {"expires_at": 0, "archive": [], "source": "empty", "last_success_at": None}
    with patch.dict(newsletter_data._CACHE, cache, clear=True), patch.object(newsletter_data.time, "time", lambda: clock[0]), patch.object(newsletter_data, "fetch_supabase_archive", return_value=sample_archive()), patch.object(newsletter_data, "fetch_best_archive_fallback", return_value=([], "")):
        archive, source = newsletter_data.load_archive()
        assert source == "supabase"
        with patch.object(newsletter_data, "fetch_supabase_archive", side_effect=OSError("outage")):
            clock[0] = 1301
            assert newsletter_data.load_archive() == (archive, "stale_cache")
            health = web_app.app.test_client().get("/health.json")
            assert health.status_code == 200
            assert health.get_json()["status"] == "degraded"
            assert health.get_json()["last_success_at"]
            clock[0] = 5000
            for route in ["/", "/health.json", "/archive.json"]:
                assert web_app.app.test_client().get(route).status_code == 503


def test_news_cold_start_outage_does_not_raise_http_500() -> None:
    from unittest.mock import patch
    cache = {"expires_at": 0, "archive": [], "source": "empty", "last_success_at": None}
    with patch.dict(newsletter_data._CACHE, cache, clear=True), patch.object(newsletter_data, "fetch_supabase_archive", side_effect=OSError("outage")), patch.object(newsletter_data, "fetch_archive_url_from", side_effect=OSError("outage")):
        client = web_app.app.test_client()
        assert client.get("/").status_code == 503
        assert client.get("/health.json").get_json()["status"] == "unavailable"


def test_archive_fallback_fetches_share_a_bounded_timeout_budget() -> None:
    from unittest.mock import patch
    timeouts = []
    def fetch(url, timeout):
        timeouts.append(timeout)
        raise OSError("timeout")
    with patch.object(newsletter_data, "fetch_archive_url_from", fetch):
        assert newsletter_data.fetch_best_archive_fallback([]) == ([], "")
    assert len(timeouts) == 2
    assert 0 < sum(timeouts) <= newsletter_data.DEFAULT_FALLBACK_BUDGET_SECONDS


def main() -> int:
    from scripts.run_regression_tests import run_module_tests
    return run_module_tests(sys.modules[__name__])


if __name__ == "__main__":
    raise SystemExit(main())
