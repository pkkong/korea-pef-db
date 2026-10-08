#!/usr/bin/env python3
"""No-network regression checks for the canonical newsletter Supabase adapter."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.newsletter.src import sync_newsletter_canonical_supabase as canonical  # noqa: E402


def seed_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(canonical.DEFAULT_SCHEMA.read_text(encoding="utf-8"))
        conn.execute(
            """
            INSERT INTO news_source(
                source_code, source_name, source_kind, locator, is_active, created_at, updated_at
            ) VALUES ('sample', 'Sample', 'rss', 'https://example.com/rss', 1, '2026-09-03T00:00:00+00:00', '2026-09-03T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO news_run(run_id, run_date, started_at, status)
            VALUES ('run-1', '2026-09-03', '2026-09-03T00:00:00+00:00', 'completed')
            """
        )
        conn.execute(
            """
            INSERT INTO news_document(
                news_id, run_id, source_code, source_url, normalized_source_url, title,
                discovered_at, is_pe_relevant, raw_payload_json
            ) VALUES (
                41, 'run-1', 'sample', 'https://example.com/a?utm_source=test',
                'https://example.com/a', '테스트 기사', '2026-09-03', 1,
                '{"feed_item":{"title":"테스트"}}'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO news_tag(tag_id, news_id, tag_type, tag_value, tag_source)
            VALUES (7, 41, 'section', 'GP', 'taxonomy')
            """
        )
        conn.execute(
            """
            INSERT INTO news_entity_link(
                link_id, news_id, entity_type, entity_ref, entity_name, link_source
            ) VALUES (9, 41, 'GP', 'gp-1', '테스트GP', 'matcher')
            """
        )


def test_prepare_payload_preserves_private_collection_fields() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "daily_news.sqlite"
        seed_database(db_path)
        payload = canonical.prepare_payload(db_path)

    document = payload[canonical.DOCUMENT_SPEC.supabase_table][0]
    assert document["news_id"] == 41
    assert document["is_pe_relevant"] is True
    assert document["raw_payload"] == {"feed_item": {"title": "테스트"}}
    assert payload[canonical.SOURCE_SPEC.supabase_table][0]["is_active"] is True
    assert payload[canonical.TAG_SPEC.supabase_table][0]["tag_id"] == 7
    assert payload[canonical.ENTITY_SPEC.supabase_table][0]["link_id"] == 9


def test_restore_rows_recreates_pipeline_compatible_sqlite() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "daily_news.sqlite"
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(canonical.DEFAULT_SCHEMA.read_text(encoding="utf-8"))
            canonical._restore_rows(
                conn,
                canonical.SOURCE_SPEC,
                [{
                    "source_code": "sample", "source_name": "Sample", "source_kind": "rss",
                    "locator": "https://example.com/rss", "publisher": None, "homepage_url": None,
                    "article_url_regex": None, "must_contain": None, "allowed_publishers": None,
                    "default_tags": None, "is_active": True, "notes": None,
                    "created_at": "2026-09-03T00:00:00+00:00", "updated_at": "2026-09-03T00:00:00+00:00",
                }],
            )
            canonical._restore_rows(
                conn,
                canonical.RUN_SPEC,
                [{
                    "run_id": "run-1", "run_date": "2026-09-03", "started_at": "2026-09-03T00:00:00+00:00",
                    "ended_at": None, "status": "completed", "discovered_count": 1, "fetched_count": 1,
                    "inserted_count": 1, "relevant_count": 1, "notes": None,
                }],
            )
            canonical._restore_rows(
                conn,
                canonical.DOCUMENT_SPEC,
                [{
                    "news_id": 41, "run_id": "run-1", "source_code": "sample",
                    "source_url": "https://example.com/a", "normalized_source_url": "https://example.com/a",
                    "source_domain": None, "publisher": None, "title": "테스트 기사", "published_at": None,
                    "discovered_at": "2026-09-03", "fetched_at": None, "document_type": "article",
                    "language_code": "ko", "raw_html_path": "supabase://newsletter-raw/documents/41.html",
                    "meta_description": None, "excerpt_text": None, "body_text": None, "content_hash": None,
                    "relevance_score": 3.0, "relevance_label": "relevant", "comment_text": None,
                    "review_status": "auto", "is_pe_relevant": True,
                    "raw_payload": {"feed_item": {"title": "테스트"}},
                    "created_at": "2026-09-03T00:00:00+00:00", "updated_at": "2026-09-03T00:00:00+00:00",
                }],
            )
            row = conn.execute(
                "SELECT news_id, is_pe_relevant, raw_payload_json, raw_html_path FROM news_document"
            ).fetchone()

    assert row == (41, 1, json.dumps({"feed_item": {"title": "테스트"}}, ensure_ascii=False), "supabase://newsletter-raw/documents/41.html")


def test_apply_payload_replaces_private_links_after_documents() -> None:
    payload = {
        canonical.SOURCE_SPEC.supabase_table: [{"source_code": "sample"}],
        canonical.RUN_SPEC.supabase_table: [{"run_id": "run-1"}],
        canonical.DOCUMENT_SPEC.supabase_table: [{"news_id": 41, "raw_html_path": ""}],
        canonical.TAG_SPEC.supabase_table: [{"tag_id": 7}],
        canonical.ENTITY_SPEC.supabase_table: [{"link_id": 9}],
    }
    calls: list[tuple[str, str]] = []

    def fake_rest(resource: str, *, method: str = "GET", **kwargs: object) -> object:
        calls.append((method, resource))
        return kwargs["payload"]["expected_counts"] if resource.startswith("rpc/") else []

    original_rest = canonical._rest_request
    canonical._rest_request = fake_rest
    try:
        result = canonical.apply_payload(
            payload,
            upload_raw_html=False,
            purge_raw_html_cache_after_sync=False,
        )
    finally:
        canonical._rest_request = original_rest

    assert result["documents"] == 1
    assert calls == [("POST", "newsletter_sync_parts")] * 5 + [("POST", "rpc/publish_newsletter_sync")]



def test_raw_html_upload_uses_bucket_allowed_mime_type() -> None:
    with tempfile.TemporaryDirectory() as directory:
        raw_path = Path(directory) / "article.html"
        raw_path.write_text("<html><body>test</body></html>", encoding="utf-8")
        calls: list[dict[str, object]] = []

        def fake_request(url: str, *, method: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> object:
            calls.append({"url": url, "method": method, "body": body, "headers": headers or {}})
            return None

        original_request = canonical._request
        original_url = canonical._supabase_url
        canonical._request = fake_request
        canonical._supabase_url = lambda: "https://example.supabase.co"
        try:
            stored_path = canonical._upload_raw_html({"news_id": 41, "raw_html_path": str(raw_path)})
        finally:
            canonical._request = original_request
            canonical._supabase_url = original_url

    assert stored_path == "supabase://newsletter-raw/documents/41.html"
    assert calls == [{
        "url": "https://example.supabase.co/storage/v1/object/newsletter-raw/documents/41.html",
        "method": "POST",
        "body": b"<html><body>test</body></html>",
        "headers": {"Content-Type": "text/html", "x-upsert": "true"},
    }]


def test_raw_html_cache_purges_expired_files_without_touching_article_records() -> None:
    documents = [
        {
            "news_id": 41,
            "raw_html_path": "supabase://newsletter-raw/documents/41.html",
            "fetched_at": "2026-07-01T00:00:00+00:00",
        },
        {
            "news_id": 42,
            "raw_html_path": "supabase://newsletter-raw/documents/42.html",
            "fetched_at": "2026-07-15T00:00:00+00:00",
        },
    ]
    storage_calls: list[tuple[str, str]] = []
    record_calls: list[tuple[str, str, dict[str, str] | None, object | None]] = []

    def fake_request(url: str, *, method: str, **_: object) -> object:
        storage_calls.append((method, url))
        return None

    def fake_read_all(resource: str) -> list[dict[str, object]]:
        assert resource == canonical.DOCUMENT_SPEC.supabase_table
        return documents

    def fake_rest(
        resource: str,
        *,
        method: str = "GET",
        query: dict[str, str] | None = None,
        payload: object | None = None,
        **_: object,
    ) -> object:
        record_calls.append((method, resource, query, payload))
        return None

    original_request = canonical._request
    original_read_all = canonical._read_all
    original_rest = canonical._rest_request
    original_url = canonical._supabase_url
    canonical._request = fake_request
    canonical._read_all = fake_read_all
    canonical._rest_request = fake_rest
    canonical._supabase_url = lambda: "https://example.supabase.co"
    try:
        result = canonical.purge_raw_html_cache(
            now_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            retention_days=30,
        )
    finally:
        canonical._request = original_request
        canonical._read_all = original_read_all
        canonical._rest_request = original_rest
        canonical._supabase_url = original_url

    assert result == {"raw_html_purged": 1, "raw_html_purge_failures": 0}
    assert storage_calls == [
        ("DELETE", "https://example.supabase.co/storage/v1/object/newsletter-raw/documents/41.html")
    ]
    assert record_calls == [
        ("PATCH", canonical.DOCUMENT_SPEC.supabase_table, {"news_id": "eq.41"}, {"raw_html_path": None})
    ]


def test_archive_bootstrap_preserves_published_classification_and_entities() -> None:
    archive = [
        {
            "reportDate": "2026-09-03",
            "articles": [
                {
                    "title": "테스트 GP 펀드 결성",
                    "source": "테스트신문",
                    "url": "https://example.com/a",
                    "section": "GP",
                    "subCategory": "Fundraising",
                    "summaryLines": ["첫 줄", "둘째 줄"],
                    "gpNames": ["테스트GP"],
                    "lpNames": ["테스트LP"],
                }
            ],
        }
    ]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "archive.json"
        path.write_text(json.dumps(archive, ensure_ascii=False), encoding="utf-8")
        payload = canonical.prepare_archive_bootstrap_payload(path)

    document = payload[canonical.DOCUMENT_SPEC.supabase_table][0]
    assert document["review_status"] == "published_archive"
    assert document["excerpt_text"] == "첫 줄 둘째 줄"
    assert [tag["tag_value"] for tag in payload[canonical.TAG_SPEC.supabase_table]] == ["GP", "Fundraising"]
    assert [(link["entity_type"], link["entity_name"]) for link in payload[canonical.ENTITY_SPEC.supabase_table]] == [
        ("GP", "테스트GP"),
        ("LP", "테스트LP"),
    ]


def test_source_registry_payload_keeps_collection_fields() -> None:
    rows = canonical.prepare_source_registry_payload(canonical.DEFAULT_SOURCES)

    assert rows
    assert all(row["source_code"] and row["locator"] for row in rows)
    assert any(row["source_kind"] == "naver_news_api" and row["is_active"] for row in rows)



def test_failed_staging_never_deletes_or_publishes_canonical_data() -> None:
    from unittest.mock import patch
    calls = []
    payload = {spec.supabase_table: [{"sample": True}] for spec in canonical.TABLES}
    def request(resource, **kwargs):
        calls.append(resource)
        if len(calls) == 2:
            raise canonical.CanonicalNewsletterError("interrupted upload")
    with patch.object(canonical, "_rest_request", request):
        try:
            canonical.apply_payload(payload, upload_raw_html=False, purge_raw_html_cache_after_sync=False)
        except canonical.CanonicalNewsletterError:
            pass
        else:
            raise AssertionError("Incomplete upload must fail")
    assert calls == ["newsletter_sync_parts", "newsletter_sync_parts"]


def test_cache_listing_failure_does_not_fail_successful_canonical_sync() -> None:
    from unittest.mock import patch
    payload = {spec.supabase_table: [] for spec in canonical.TABLES}
    def request(resource, **kwargs):
        assert resource == "rpc/publish_newsletter_sync"
        return kwargs["payload"]["expected_counts"]
    with patch.object(canonical, "_rest_request", request), patch.object(canonical, "_read_all", side_effect=canonical.CanonicalNewsletterError("listing failed")):
        result = canonical.apply_payload(payload, upload_raw_html=False)
    assert result["raw_html_purge_failures"] == 1
    assert result["documents"] == 0


def _seed_restored_database(path: Path) -> None:
    seed_database(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        canonical._save_baseline(conn)


def test_restored_history_without_changes_does_not_get_uploaded() -> None:
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as directory:
        original = Path(directory) / "original.sqlite"
        seed_database(original)
        rows = canonical.prepare_payload(original)
        restored = Path(directory) / "restored.sqlite"
        with patch.object(canonical, "_read_all", side_effect=lambda table: rows[table]):
            canonical.restore_canonical_db(restored)
        assert all(not value for value in canonical.prepare_payload(restored).values())


def test_changed_document_sends_all_its_links_and_preserves_other_history() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sample.sqlite"
        _seed_restored_database(path)
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE news_document SET title = '수정된 기사' WHERE news_id = 41")
            conn.execute("INSERT INTO news_document (news_id,run_id,source_code,source_url,normalized_source_url,title,discovered_at) VALUES (42,'run-1','sample','https://example.com/b','https://example.com/b','신규 기사','2026-10-08')")
        payload = canonical.prepare_payload(path)
        assert [row["news_id"] for row in payload[canonical.DOCUMENT_SPEC.supabase_table]] == [41, 42]
        assert [row["news_id"] for row in payload[canonical.TAG_SPEC.supabase_table]] == [41]
        assert [row["news_id"] for row in payload[canonical.ENTITY_SPEC.supabase_table]] == [41]
        assert not payload[canonical.RUN_SPEC.supabase_table]
        assert not payload[canonical.SOURCE_SPEC.supabase_table]


def test_tag_only_change_and_link_removal_include_owning_document() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sample.sqlite"
        _seed_restored_database(path)
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE news_tag SET tag_value = 'LP' WHERE news_id = 41")
            conn.execute("DELETE FROM news_entity_link WHERE news_id = 41")
        payload = canonical.prepare_payload(path)
        assert [row["news_id"] for row in payload[canonical.DOCUMENT_SPEC.supabase_table]] == [41]
        assert payload[canonical.TAG_SPEC.supabase_table][0]["tag_value"] == "LP"
        assert not payload[canonical.ENTITY_SPEC.supabase_table]


def test_removed_all_links_is_still_a_change() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sample.sqlite"
        _seed_restored_database(path)
        with sqlite3.connect(path) as conn:
            conn.execute("DELETE FROM news_tag WHERE news_id = 41")
            conn.execute("DELETE FROM news_entity_link WHERE news_id = 41")
        payload = canonical.prepare_payload(path)
        assert len(payload[canonical.DOCUMENT_SPEC.supabase_table]) == 1
        assert not payload[canonical.TAG_SPEC.supabase_table]
        assert not payload[canonical.ENTITY_SPEC.supabase_table]


def test_delta_sync_scales_with_changes_instead_of_history() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sample.sqlite"
        seed_database(path)
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            conn.executemany("INSERT INTO news_document (news_id,run_id,source_code,source_url,normalized_source_url,title,discovered_at) VALUES (?,'run-1','sample',?,?,?,'2026-09-03')", [
                (news_id, f'https://example.com/{news_id}', f'https://example.com/{news_id}', f'기사 {news_id}')
                for news_id in range(100, 5100)
            ])
            canonical._save_baseline(conn)
            conn.execute("UPDATE news_document SET title = '새 제목' WHERE news_id = 5000")
        payload = canonical.prepare_payload(path)
        assert [row["news_id"] for row in payload[canonical.DOCUMENT_SPEC.supabase_table]] == [5000]
        assert not payload[canonical.TAG_SPEC.supabase_table]
        # Preparing or unsuccessfully uploading a delta never advances its baseline.
        assert canonical.prepare_payload(path) == payload


def test_failed_request_identifies_the_sync_stage() -> None:
    from unittest.mock import patch
    with patch.object(canonical, "_supabase_url", return_value="https://example.com"), patch.object(
        canonical, "_request", side_effect=canonical.CanonicalNewsletterError("HTTP 500 statement timeout")
    ):
        try:
            canonical._rest_request("rpc/publish_newsletter_sync", method="POST")
        except canonical.CanonicalNewsletterError as exc:
            assert "rpc/publish_newsletter_sync" in str(exc)
        else:
            raise AssertionError("Failed commit must remain an error")


def main() -> int:
    from scripts.run_regression_tests import run_module_tests
    return run_module_tests(sys.modules[__name__])


if __name__ == "__main__":
    raise SystemExit(main())
