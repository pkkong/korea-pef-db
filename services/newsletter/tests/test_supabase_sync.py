#!/usr/bin/env python
"""No-network checks for newsletter Supabase payload generation."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.newsletter.src.sync_newsletter_supabase import prepare_payload  # noqa: E402


def test_prepare_payload_dedupes_issue_urls() -> None:
    archive = [
        {
            "reportDate": "2026-06-16",
            "visibleDate": "2026년 6월 16일",
            "basis": "KST",
            "articles": [
                {
                    "rank": 0,
                    "section": "GP",
                    "subCategory": "Fundraising",
                    "rawSection": "GP",
                    "title": "테스트 GP 펀드 결성",
                    "source": "테스트신문",
                    "url": "https://example.com/article?a=1&utm_source=naver",
                    "summaryLines": ["첫 줄", "둘째 줄"],
                    "gpNames": ["테스트인베스트먼트"],
                    "lpNames": ["한국성장금융"],
                    "sectionOrder": 2,
                },
                {
                    "rank": 1,
                    "section": "GP",
                    "title": "중복 URL",
                    "source": "테스트신문",
                    "url": "https://example.com/article?a=1",
                },
            ],
        }
    ]

    payload = prepare_payload(archive, "2026-06-16")

    assert len(payload["issues"]) == 1
    assert payload["issues"][0]["article_count"] == 1
    assert len(payload["articles"]) == 1
    assert len(payload["issue_articles"]) == 1
    assert payload["articles"][0]["section"] == "GP"
    assert payload["articles"][0]["gp_names"] == ["테스트인베스트먼트"]
    assert payload["articles"][0]["lp_names"] == ["한국성장금융"]
    assert any(row["tag_type"] == "section" and row["tag_value"] == "GP" for row in payload["tags"])
    assert any(row["entity_type"] == "GP" for row in payload["entities"])


def test_prepare_payload_filters_selected_date() -> None:
    archive = [
        {"reportDate": "2026-06-15", "articles": []},
        {
            "reportDate": "2026-06-16",
            "articles": [
                {
                    "title": "선택 날짜 기사",
                    "source": "테스트신문",
                    "url": "https://example.com/selected",
                    "section": "Market",
                }
            ],
        },
    ]

    payload = prepare_payload(archive, "2026-06-16")

    assert [row["issue_date"] for row in payload["issues"]] == ["2026-06-16"]
    assert payload["articles"][0]["title"] == "선택 날짜 기사"


def main() -> int:
    test_prepare_payload_dedupes_issue_urls()
    test_prepare_payload_filters_selected_date()
    print("supabase sync tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
