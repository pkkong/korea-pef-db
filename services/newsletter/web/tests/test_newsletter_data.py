#!/usr/bin/env python
"""No-network checks for the Vercel newsletter data adapter."""

from __future__ import annotations

import sys
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from newsletter_data import archive_from_supabase_rows, filter_articles, grouped_sections, select_issue  # noqa: E402


def test_archive_from_supabase_rows_groups_issues() -> None:
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

    archive = archive_from_supabase_rows(rows)

    assert len(archive) == 1
    assert archive[0]["reportDate"] == "2026-06-16"
    assert [row["title"] for row in archive[0]["articles"]] == ["첫 기사", "둘째 기사"]


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


def main() -> int:
    test_archive_from_supabase_rows_groups_issues()
    test_filter_and_group_articles()
    print("newsletter web data tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
