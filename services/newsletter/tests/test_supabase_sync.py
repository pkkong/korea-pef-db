#!/usr/bin/env python
"""No-network checks for newsletter Supabase payload generation."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.error import URLError


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.newsletter.src import sync_newsletter_supabase as supabase_sync  # noqa: E402
from services.newsletter.src.sync_newsletter_supabase import prepare_payload, select_sync_archive  # noqa: E402


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


def test_select_sync_archive_keeps_rolling_range_by_default() -> None:
    archive = [
        {"reportDate": "2026-06-17", "articles": []},
        {"reportDate": "2026-06-16", "articles": []},
        {"reportDate": "2026-06-15", "articles": []},
    ]

    selected = select_sync_archive(archive, issue_limit=2)

    assert [row["reportDate"] for row in selected] == ["2026-06-17", "2026-06-16"]


def test_select_sync_archive_allows_single_issue_debug_sync() -> None:
    archive = [
        {"reportDate": "2026-06-17", "articles": []},
        {"reportDate": "2026-06-16", "articles": []},
    ]

    selected = select_sync_archive(archive, issue_date="2026-06-16")

    assert [row["reportDate"] for row in selected] == ["2026-06-16"]


def test_apply_payload_resets_issue_links_and_article_metadata() -> None:
    calls: list[tuple[str, str, dict[str, str] | None]] = []

    def fake_rest_request(
        table: str,
        *,
        method: str = "GET",
        query: dict[str, str] | None = None,
        payload: object | None = None,
        prefer: str | None = None,
    ) -> object:
        calls.append((method, table, query))
        if table == "rpc/publish_newsletter_sync":
            return payload["expected_counts"]
        return []

    original_rest_request = supabase_sync._rest_request
    supabase_sync._rest_request = fake_rest_request
    try:
        result = supabase_sync.apply_payload(
            {
                "issues": [
                    {
                        "issue_date": "2026-06-17",
                        "visible_date": "2026년 6월 17일",
                        "basis": "KST",
                        "status": "published",
                        "article_count": 1,
                    }
                ],
                "articles": [
                    {
                        "normalized_url": "https://example.com/a",
                        "source_url": "https://example.com/a",
                        "title": "신규 기사",
                        "section": "Market",
                    }
                ],
                "issue_articles": [
                    {
                        "issue_date": "2026-06-17",
                        "normalized_url": "https://example.com/a",
                        "rank": 0,
                        "section_order": 1,
                    }
                ],
                "tags": [
                    {
                        "normalized_url": "https://example.com/a",
                        "tag_type": "section",
                        "tag_value": "Market",
                        "tag_source": "archive",
                    }
                ],
                "entities": [],
            }
        )
    finally:
        supabase_sync._rest_request = original_rest_request

    assert result["issue_articles"] == 1
    assert not any(method == "DELETE" for method, _, _ in calls)
    assert [table for _, table, _ in calls] == ["newsletter_sync_parts"] * 4 + ["rpc/publish_newsletter_sync"]


def test_delete_many_batches_unique_values() -> None:
    calls: list[tuple[str, str, dict[str, str] | None]] = []

    def fake_rest_request(
        table: str,
        *,
        method: str = "GET",
        query: dict[str, str] | None = None,
        payload: object | None = None,
        prefer: str | None = None,
    ) -> object:
        calls.append((method, table, query))
        return []

    original_rest_request = supabase_sync._rest_request
    supabase_sync._rest_request = fake_rest_request
    try:
        supabase_sync._delete_many(
            "newsletter_article_tags",
            "article_id",
            ["a1", "a2", "a1", "", "a3"],
            batch_size=2,
        )
    finally:
        supabase_sync._rest_request = original_rest_request

    assert calls == [
        ("DELETE", "newsletter_article_tags", {"article_id": "in.(a1,a2)"}),
        ("DELETE", "newsletter_article_tags", {"article_id": "in.(a3)"}),
    ]


def test_rest_request_retries_transient_url_errors() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        calls.append(timeout)
        if len(calls) == 1:
            raise URLError(ConnectionResetError("reset by peer"))
        return FakeResponse()

    original_urlopen = supabase_sync.urlopen
    original_sleep = supabase_sync.time.sleep
    original_env = {
        key: os.environ.get(key)
        for key in [
            "SUPABASE_URL",
            "SUPABASE_SERVICE_ROLE_KEY",
            "NEWSLETTER_SUPABASE_REST_RETRIES",
            "NEWSLETTER_SUPABASE_REST_TIMEOUT_SECONDS",
        ]
    }
    supabase_sync.urlopen = fake_urlopen
    supabase_sync.time.sleep = lambda delay: sleeps.append(delay)
    os.environ["SUPABASE_URL"] = "https://example.supabase.co"
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "secret"
    os.environ["NEWSLETTER_SUPABASE_REST_RETRIES"] = "2"
    os.environ["NEWSLETTER_SUPABASE_REST_TIMEOUT_SECONDS"] = "7"
    try:
        result = supabase_sync._rest_request(
            "newsletter_article_entities",
            method="DELETE",
            query={"article_id": "eq.test"},
            prefer="return=minimal",
        )
    finally:
        supabase_sync.urlopen = original_urlopen
        supabase_sync.time.sleep = original_sleep
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    assert result == {"ok": True}
    assert calls == [7, 7]
    assert sleeps == [0.75]



def test_same_article_across_dates_uses_latest_metadata_without_duplicate_keys() -> None:
    old = {"title": "Old", "url": "https://example.com/a", "section": "Market", "gpNames": ["Old GP"]}
    new = {**old, "title": "Corrected", "section": "GP", "gpNames": ["New GP"]}
    for archive in [
        [{"reportDate": "2026-09-05", "articles": [new]}, {"reportDate": "2026-09-04", "articles": [old]}],
        [{"reportDate": "2026-09-04", "articles": [old]}, {"reportDate": "2026-09-05", "articles": [new]}],
    ]:
        payload = prepare_payload(archive)
        assert len(payload["issue_articles"]) == 2
        assert len(payload["articles"]) == 1
        assert payload["articles"][0]["title"] == "Corrected"
        assert [row["tag_value"] for row in payload["tags"]] == ["GP"]
        assert [row["entity_name"] for row in payload["entities"]] == ["New GP"]


def test_atomic_upload_failure_leaves_public_model_untouched() -> None:
    from unittest.mock import patch
    calls = []
    def request(resource, **kwargs):
        calls.append(resource)
        raise RuntimeError("staging unavailable")
    with patch.object(supabase_sync, "_rest_request", request):
        try:
            supabase_sync.apply_payload(prepare_payload([{"reportDate": "2026-09-05", "articles": []}]))
        except RuntimeError:
            pass
        else:
            raise AssertionError("Upload must fail")
    assert calls == ["newsletter_sync_parts"]


def main() -> int:
    from scripts.run_regression_tests import run_module_tests
    return run_module_tests(sys.modules[__name__])


if __name__ == "__main__":
    raise SystemExit(main())
