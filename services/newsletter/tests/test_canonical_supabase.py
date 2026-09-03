#!/usr/bin/env python3
"""No-network regression checks for the canonical newsletter Supabase adapter."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
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

    def fake_rest(resource: str, *, method: str = "GET", **_: object) -> object:
        calls.append((method, resource))
        return []

    original_rest = canonical._rest_request
    canonical._rest_request = fake_rest
    try:
        result = canonical.apply_payload(payload, upload_raw_html=False)
    finally:
        canonical._rest_request = original_rest

    assert result["documents"] == 1
    assert calls == [
        ("POST", "newsletter_canonical_sources"),
        ("POST", "newsletter_canonical_runs"),
        ("POST", "newsletter_canonical_documents"),
        ("DELETE", "newsletter_canonical_tags"),
        ("DELETE", "newsletter_canonical_entity_links"),
        ("POST", "newsletter_canonical_tags"),
        ("POST", "newsletter_canonical_entity_links"),
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


def main() -> int:
    test_prepare_payload_preserves_private_collection_fields()
    test_restore_rows_recreates_pipeline_compatible_sqlite()
    test_apply_payload_replaces_private_links_after_documents()
    test_archive_bootstrap_preserves_published_classification_and_entities()
    print("canonical newsletter Supabase tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
