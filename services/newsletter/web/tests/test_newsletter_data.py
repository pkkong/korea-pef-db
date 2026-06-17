#!/usr/bin/env python
"""No-network checks for the Vercel newsletter data adapter."""

from __future__ import annotations

import sys
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from newsletter_data import archive_from_supabase_rows, filter_articles, grouped_sections, select_issue  # noqa: E402
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


def test_archive_from_supabase_rows_groups_issues() -> None:
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
    assert archive[0]["articles"] == []
    assert archive[1]["reportDate"] == "2026-06-16"
    assert [row["title"] for row in archive[1]["articles"]] == ["첫 기사", "둘째 기사"]


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
        assert 'href="https://pkkong.github.io/kpef-newsletter/gps.html"' in html
        assert 'href="lp-notices.html"' not in html
        assert 'href="gps.html"' not in html
        assert "/static/service.css" not in html

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


def main() -> int:
    test_archive_from_supabase_rows_groups_issues()
    test_filter_and_group_articles()
    test_vercel_app_uses_common_newsletter_ui()
    print("newsletter web data tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
