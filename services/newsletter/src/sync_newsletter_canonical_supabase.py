#!/usr/bin/env python3
"""Synchronize the private newsletter collection database with Supabase.

The collector still uses SQLite-compatible SQL, but that database is an
ephemeral build adapter. Supabase owns the durable source, run, document,
classification, review, and raw-html records.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.shared.src.daily_news_common import (  # noqa: E402
    DEFAULT_SCHEMA,
    DEFAULT_SOURCES,
    load_sources,
    now_utc_iso,
)
from services.newsletter.src.newsletter_atomic_sync import publish_atomic  # noqa: E402


DEFAULT_PAYLOAD_OUT = REPO_ROOT / "exports" / "daily_news" / "newsletter_canonical_payload.json"
REST_PAGE_SIZE = 500
REST_BATCH_SIZE = 250
MAX_REST_BATCH_BYTES = 750_000
RAW_BUCKET = "newsletter-raw"
RAW_HTML_CACHE_DAYS = 30
RETRIABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class CanonicalNewsletterError(RuntimeError):
    pass


@dataclass(frozen=True)
class TableSpec:
    sqlite_table: str
    supabase_table: str
    columns: tuple[str, ...]
    conflict_columns: tuple[str, ...]


TABLES = (
    TableSpec(
        "news_source",
        "newsletter_canonical_sources",
        (
            "source_code", "source_name", "source_kind", "locator", "publisher",
            "homepage_url", "article_url_regex", "must_contain", "allowed_publishers",
            "default_tags", "is_active", "notes", "created_at", "updated_at",
        ),
        ("source_code",),
    ),
    TableSpec(
        "news_run",
        "newsletter_canonical_runs",
        (
            "run_id", "run_date", "started_at", "ended_at", "status", "discovered_count",
            "fetched_count", "inserted_count", "relevant_count", "notes",
        ),
        ("run_id",),
    ),
    TableSpec(
        "news_document",
        "newsletter_canonical_documents",
        (
            "news_id", "run_id", "source_code", "source_url", "normalized_source_url",
            "source_domain", "publisher", "title", "published_at", "discovered_at",
            "fetched_at", "document_type", "language_code", "raw_html_path",
            "meta_description", "excerpt_text", "body_text", "content_hash",
            "relevance_score", "relevance_label", "comment_text", "review_status",
            "is_pe_relevant", "raw_payload", "created_at", "updated_at",
        ),
        ("news_id",),
    ),
    TableSpec(
        "news_tag",
        "newsletter_canonical_tags",
        ("tag_id", "news_id", "tag_type", "tag_value", "tag_source", "confidence", "created_at"),
        ("tag_id",),
    ),
    TableSpec(
        "news_entity_link",
        "newsletter_canonical_entity_links",
        (
            "link_id", "news_id", "entity_type", "entity_ref", "entity_name",
            "matched_alias", "match_field", "link_source", "confidence", "created_at",
        ),
        ("link_id",),
    ),
)
SOURCE_SPEC, RUN_SPEC, DOCUMENT_SPEC, TAG_SPEC, ENTITY_SPEC = TABLES


def _supabase_url() -> str:
    value = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not value:
        raise CanonicalNewsletterError("SUPABASE_URL is required")
    return value


def _supabase_key() -> str:
    value = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")
    if not value:
        raise CanonicalNewsletterError("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY is required")
    return value


def _request(url: str, *, method: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> Any:
    request_headers = {
        "apikey": _supabase_key(),
        "Authorization": f"Bearer {_supabase_key()}",
        **(headers or {}),
    }
    last_error: BaseException | None = None
    for attempt in range(4):
        request = Request(url, data=body, method=method, headers=request_headers)
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code not in RETRIABLE_HTTP_STATUS_CODES or attempt == 3:
                raise CanonicalNewsletterError(f"Supabase {method} request failed: HTTP {exc.code} {detail}") from exc
            last_error = exc
        except (URLError, TimeoutError, ConnectionResetError) as exc:
            if attempt == 3:
                raise CanonicalNewsletterError(f"Supabase {method} request failed: {exc}") from exc
            last_error = exc
        time.sleep(min(8.0, 0.75 * (2**attempt)))
    raise CanonicalNewsletterError(f"Supabase {method} request failed: {last_error}")


def _rest_request(
    resource: str,
    *,
    method: str = "GET",
    query: dict[str, str] | None = None,
    payload: object | None = None,
    prefer: str | None = None,
) -> Any:
    url = f"{_supabase_url()}/rest/v1/{resource}"
    if query:
        url = f"{url}?{urlencode(query)}"
    headers = {"Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if payload is not None else None
    return _request(url, method=method, body=body, headers=headers)


def _read_all(resource: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    offset = 0
    while True:
        page = _rest_request(resource, query={"limit": str(REST_PAGE_SIZE), "offset": str(offset)})
        if not isinstance(page, list):
            raise CanonicalNewsletterError(f"Supabase {resource} returned a non-list payload")
        typed_page = [row for row in page if isinstance(row, dict)]
        rows.extend(typed_page)
        if len(typed_page) < REST_PAGE_SIZE:
            return rows
        offset += len(typed_page)


def _batched(rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    batches: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    current_bytes = 2
    for row in rows:
        row_bytes = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        if current and (len(current) >= REST_BATCH_SIZE or current_bytes + row_bytes > MAX_REST_BATCH_BYTES):
            batches.append(current)
            current = []
            current_bytes = 2
        current.append(row)
        current_bytes += row_bytes
    if current:
        batches.append(current)
    return batches


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
    ).fetchone() is not None


def _json_value(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {"raw": value}
    return value if value is not None else {}


def _sqlite_rows(conn: sqlite3.Connection, spec: TableSpec) -> list[dict[str, object]]:
    if not _table_exists(conn, spec.sqlite_table):
        return []
    source_columns = ["raw_payload_json AS raw_payload" if column == "raw_payload" else column for column in spec.columns]
    rows = conn.execute(
        f'SELECT {", ".join(source_columns)} FROM "{spec.sqlite_table}" ORDER BY rowid'
    ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        item = {column: row[column] for column in spec.columns}
        if spec is SOURCE_SPEC:
            item["is_active"] = bool(item["is_active"])
        elif spec is DOCUMENT_SPEC:
            item["is_pe_relevant"] = bool(item["is_pe_relevant"])
            item["raw_payload"] = _json_value(item["raw_payload"])
        result.append(item)
    return result


def prepare_payload(db_path: Path) -> dict[str, list[dict[str, object]]]:
    if not db_path.is_file():
        raise CanonicalNewsletterError(f"SQLite collection database does not exist: {db_path}")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return {spec.supabase_table: _sqlite_rows(conn, spec) for spec in TABLES}


def prepare_source_registry_payload(sources_path: Path) -> list[dict[str, object]]:
    applied_at = now_utc_iso()
    return [
        {
            "source_code": source.source_code,
            "source_name": source.source_name,
            "source_kind": source.source_kind,
            "locator": source.locator,
            "publisher": source.publisher or None,
            "homepage_url": source.homepage_url or None,
            "article_url_regex": source.article_url_regex or None,
            "must_contain": ";".join(source.must_contain) or None,
            "allowed_publishers": ";".join(source.allowed_publishers) or None,
            "default_tags": ";".join(f"{tag_type}:{tag_value}" for tag_type, tag_value in source.default_tags) or None,
            "is_active": bool(source.is_active),
            "notes": source.notes or None,
            "updated_at": applied_at,
        }
        for source in load_sources(sources_path)
    ]


def _storage_object_key(news_id: object) -> str:
    return f"documents/{int(news_id)}.html"


def _storage_object_key_from_path(raw_html_path: object) -> str | None:
    prefix = f"supabase://{RAW_BUCKET}/"
    value = str(raw_html_path or "")
    if not value.startswith(prefix):
        return None
    object_key = value.removeprefix(prefix)
    if not object_key.startswith("documents/") or not object_key.endswith(".html"):
        return None
    return object_key


def _upload_raw_html(document: dict[str, object]) -> str:
    current = str(document.get("raw_html_path") or "")
    if not current:
        return ""
    if current.startswith(f"supabase://{RAW_BUCKET}/"):
        return current
    source_path = Path(current)
    if not source_path.is_file():
        raise CanonicalNewsletterError(f"Raw HTML file is missing for news_id={document.get('news_id')}: {source_path}")
    object_key = _storage_object_key(document["news_id"])
    encoded_key = quote(object_key, safe="/")
    _request(
        f"{_supabase_url()}/storage/v1/object/{RAW_BUCKET}/{encoded_key}",
        method="POST",
        body=source_path.read_bytes(),
        # Supabase Storage validates against the bucket's exact MIME allow-list.
        # Keep the charset out of this transport header; HTML is already UTF-8.
        headers={"Content-Type": "text/html", "x-upsert": "true"},
    )
    return f"supabase://{RAW_BUCKET}/{object_key}"


def _parse_utc_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def purge_raw_html_cache(
    *,
    now_at: datetime | None = None,
    retention_days: int = RAW_HTML_CACHE_DAYS,
) -> dict[str, int]:
    """Expire private raw HTML without affecting article records or publishing.

    A cleanup failure is reported but never raises: raw HTML is a debugging
    cache, while the normalized article record remains the durable source.
    """
    if retention_days < 1:
        raise CanonicalNewsletterError("Raw HTML cache retention must be at least one day")
    current_time = (now_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current_time - timedelta(days=retention_days)
    result = {"raw_html_purged": 0, "raw_html_purge_failures": 0}
    try:
        rows = _read_all(DOCUMENT_SPEC.supabase_table)
    except (CanonicalNewsletterError, OSError, ValueError) as exc:
        result["raw_html_purge_failures"] = 1
        print(f"WARN raw HTML cache listing failed: {exc}", file=sys.stderr)
        return result

    for document in rows:
        object_key = _storage_object_key_from_path(document.get("raw_html_path"))
        fetched_at = _parse_utc_timestamp(document.get("fetched_at"))
        if object_key is None or fetched_at is None or fetched_at >= cutoff:
            continue

        news_id = document.get("news_id")
        if not isinstance(news_id, int):
            result["raw_html_purge_failures"] += 1
            print(f"WARN raw HTML cache purge skipped: invalid news_id={news_id!r}", file=sys.stderr)
            continue
        try:
            _request(
                f"{_supabase_url()}/storage/v1/object/{RAW_BUCKET}/{quote(object_key, safe='/')}",
                method="DELETE",
            )
            _rest_request(
                DOCUMENT_SPEC.supabase_table,
                method="PATCH",
                query={"news_id": f"eq.{news_id}"},
                payload={"raw_html_path": None},
                prefer="return=minimal",
            )
            result["raw_html_purged"] += 1
        except (CanonicalNewsletterError, OSError, ValueError) as exc:
            result["raw_html_purge_failures"] += 1
            print(f"WARN raw HTML cache purge failed for news_id={news_id}: {exc}", file=sys.stderr)
    return result


def _upsert(spec: TableSpec, rows: list[dict[str, object]]) -> None:
    for batch in _batched(rows):
        _rest_request(
            spec.supabase_table,
            method="POST",
            query={"on_conflict": ",".join(spec.conflict_columns)},
            payload=batch,
            prefer="resolution=merge-duplicates,return=minimal",
        )


def apply_payload(
    payload: dict[str, list[dict[str, object]]],
    *,
    upload_raw_html: bool = True,
    purge_raw_html_cache_after_sync: bool = True,
) -> dict[str, int]:
    for spec in TABLES:
        if not isinstance(payload.get(spec.supabase_table), list):
            raise CanonicalNewsletterError(f"Canonical payload is missing {spec.supabase_table}")

    documents = [dict(row) for row in payload[DOCUMENT_SPEC.supabase_table]]
    raw_upload_count = 0
    if upload_raw_html:
        for document in documents:
            before = str(document.get("raw_html_path") or "")
            after = _upload_raw_html(document)
            if after and after != before:
                document["raw_html_path"] = after
                raw_upload_count += 1
    payload = {**payload, DOCUMENT_SPEC.supabase_table: documents}

    publish_atomic(payload, model="canonical", request=_rest_request)
    result = {
        "sources": len(payload[SOURCE_SPEC.supabase_table]),
        "runs": len(payload[RUN_SPEC.supabase_table]),
        "documents": len(documents),
        "tags": len(payload[TAG_SPEC.supabase_table]),
        "entity_links": len(payload[ENTITY_SPEC.supabase_table]),
        "raw_html_uploaded": raw_upload_count,
    }
    if purge_raw_html_cache_after_sync:
        result.update(purge_raw_html_cache())
    return result


def _sqlite_value(spec: TableSpec, column: str, value: object) -> object:
    if spec is SOURCE_SPEC and column == "is_active":
        return 1 if value else 0
    if spec is DOCUMENT_SPEC and column == "is_pe_relevant":
        return 1 if value else 0
    if spec is DOCUMENT_SPEC and column == "raw_payload":
        return json.dumps(value or {}, ensure_ascii=False)
    return value


def _restore_rows(conn: sqlite3.Connection, spec: TableSpec, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    target_columns = ["raw_payload_json" if column == "raw_payload" else column for column in spec.columns]
    quoted_columns = ", ".join(f'"{column}"' for column in target_columns)
    placeholders = ", ".join("?" for _ in target_columns)
    values = [tuple(_sqlite_value(spec, column, row.get(column)) for column in spec.columns) for row in rows]
    conn.executemany(
        f'INSERT INTO "{spec.sqlite_table}" ({quoted_columns}) VALUES ({placeholders})',
        values,
    )


def restore_canonical_db(db_path: Path) -> dict[str, int]:
    if db_path.exists():
        raise CanonicalNewsletterError(f"Refusing to overwrite existing SQLite database: {db_path}")
    rows_by_table = {spec.supabase_table: _read_all(spec.supabase_table) for spec in TABLES}
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
        for spec in TABLES:
            _restore_rows(conn, spec, rows_by_table[spec.supabase_table])
        conn.commit()
    return {
        "sources": len(rows_by_table[SOURCE_SPEC.supabase_table]),
        "runs": len(rows_by_table[RUN_SPEC.supabase_table]),
        "documents": len(rows_by_table[DOCUMENT_SPEC.supabase_table]),
        "tags": len(rows_by_table[TAG_SPEC.supabase_table]),
        "entity_links": len(rows_by_table[ENTITY_SPEC.supabase_table]),
    }


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def prepare_archive_bootstrap_payload(archive_path: Path) -> dict[str, list[dict[str, object]]]:
    """Seed an empty collection from the already published public archive.

    The archive cannot recover old raw HTML or review notes, but it preserves
    the published URL, source, classification, and GP/LP links. New collection
    runs then retain the full private record going forward.
    """
    raw = json.loads(archive_path.read_text(encoding="utf-8"))
    issues = raw.get("issues", raw) if isinstance(raw, dict) else raw
    if not isinstance(issues, list):
        raise CanonicalNewsletterError(f"Archive is not an issue list: {archive_path}")

    sources = [{
        "source_code": "legacy_public_archive",
        "source_name": "Published newsletter archive import",
        "source_kind": "archive_import",
        "locator": str(archive_path),
        "publisher": None,
        "homepage_url": None,
        "article_url_regex": None,
        "must_contain": None,
        "allowed_publishers": None,
        "default_tags": None,
        "is_active": False,
        "notes": "Initial import from the verified public newsletter archive",
        "created_at": "2026-09-03T00:00:00+00:00",
        "updated_at": "2026-09-03T00:00:00+00:00",
    }]
    runs: list[dict[str, object]] = []
    documents: list[dict[str, object]] = []
    tags: list[dict[str, object]] = []
    links: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    news_id = 0
    tag_id = 0
    link_id = 0

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        report_date = str(issue.get("reportDate") or issue.get("issue_date") or "").strip()
        if not report_date:
            continue
        run_id = f"public_archive_{report_date.replace('-', '')}"
        timestamp = f"{report_date}T00:00:00+00:00"
        articles = issue.get("articles")
        article_rows = articles if isinstance(articles, list) else []
        runs.append({
            "run_id": run_id,
            "run_date": report_date,
            "started_at": timestamp,
            "ended_at": timestamp,
            "status": "imported_public_archive",
            "discovered_count": len(article_rows),
            "fetched_count": len(article_rows),
            "inserted_count": len(article_rows),
            "relevant_count": len(article_rows),
            "notes": "Initial canonical import from public archive",
        })
        for article in article_rows:
            if not isinstance(article, dict):
                continue
            normalized_url = str(article.get("url") or article.get("normalizedUrl") or "").strip()
            title = str(article.get("title") or "").strip()
            if not normalized_url or not title or normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            news_id += 1
            section = str(article.get("section") or "Market").strip() or "Market"
            sub_category = str(article.get("subCategory") or "").strip()
            summary_lines = _string_list(article.get("summaryLines"))
            summary_text = " ".join(summary_lines)
            published_at = str(article.get("publishedAt") or article.get("published_at") or "").strip() or None
            documents.append({
                "news_id": news_id,
                "run_id": run_id,
                "source_code": "legacy_public_archive",
                "source_url": normalized_url,
                "normalized_source_url": normalized_url,
                "source_domain": None,
                "publisher": str(article.get("source") or article.get("publisher") or "").strip() or None,
                "title": title,
                "published_at": published_at,
                "discovered_at": report_date,
                "fetched_at": None,
                "document_type": "article",
                "language_code": "ko",
                "raw_html_path": "",
                "meta_description": None,
                "excerpt_text": summary_text,
                "body_text": None,
                "content_hash": None,
                "relevance_score": 0,
                "relevance_label": "relevant",
                "comment_text": None,
                "review_status": "published_archive",
                "is_pe_relevant": True,
                "raw_payload": {"archive_issue_date": report_date},
                "created_at": timestamp,
                "updated_at": timestamp,
            })
            tag_id += 1
            tags.append({
                "tag_id": tag_id,
                "news_id": news_id,
                "tag_type": "section",
                "tag_value": section,
                "tag_source": "public_archive",
                "confidence": None,
                "created_at": timestamp,
            })
            if sub_category:
                tag_id += 1
                tags.append({
                    "tag_id": tag_id,
                    "news_id": news_id,
                    "tag_type": "topic",
                    "tag_value": sub_category,
                    "tag_source": "public_archive",
                    "confidence": None,
                    "created_at": timestamp,
                })
            for entity_type, field in (("GP", "gpNames"), ("LP", "lpNames")):
                for name in _string_list(article.get(field)):
                    link_id += 1
                    links.append({
                        "link_id": link_id,
                        "news_id": news_id,
                        "entity_type": entity_type,
                        "entity_ref": name,
                        "entity_name": name,
                        "matched_alias": "",
                        "match_field": "public_archive",
                        "link_source": "public_archive",
                        "confidence": None,
                        "created_at": timestamp,
                    })
    return {
        SOURCE_SPEC.supabase_table: sources,
        RUN_SPEC.supabase_table: runs,
        DOCUMENT_SPEC.supabase_table: documents,
        TAG_SPEC.supabase_table: tags,
        ENTITY_SPEC.supabase_table: links,
    }


def canonical_collection_is_empty() -> bool:
    rows = _rest_request(DOCUMENT_SPEC.supabase_table, query={"select": "news_id", "limit": "1"})
    if not isinstance(rows, list):
        raise CanonicalNewsletterError("Could not read canonical newsletter collection state")
    return not rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore or sync canonical newsletter collection data in Supabase")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--restore", action="store_true", help="Create a new temporary SQLite adapter from Supabase")
    mode.add_argument("--sync", action="store_true", help="Copy a completed SQLite adapter back to Supabase")
    mode.add_argument(
        "--bootstrap-archive",
        type=Path,
        help="Seed an empty canonical collection from the verified public archive once.",
    )
    mode.add_argument(
        "--sync-source-registry",
        action="store_true",
        help="Copy maintained source definitions into the canonical collection.",
    )
    parser.add_argument("--db", type=Path)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--payload-out", type=Path, default=DEFAULT_PAYLOAD_OUT)
    parser.add_argument("--apply", action="store_true", help="Apply a sync payload to Supabase")
    parser.add_argument("--skip-raw-html-upload", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.restore:
            if args.db is None:
                raise CanonicalNewsletterError("--db is required with --restore")
            result = restore_canonical_db(args.db)
            print("canonical_newsletter_restore=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0

        if args.bootstrap_archive:
            if not canonical_collection_is_empty():
                print("canonical_newsletter_bootstrap=skipped_existing_collection")
                return 0
            payload = prepare_archive_bootstrap_payload(args.bootstrap_archive)
            args.payload_out.parent.mkdir(parents=True, exist_ok=True)
            args.payload_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"payload_out={args.payload_out}")
            if args.apply:
                result = apply_payload(
                    payload,
                    upload_raw_html=False,
                    purge_raw_html_cache_after_sync=False,
                )
                print("canonical_newsletter_bootstrap=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
            else:
                print("canonical_newsletter_bootstrap=skipped --apply not set")
            return 0

        if args.sync_source_registry:
            sources = prepare_source_registry_payload(args.sources)
            if args.apply:
                _upsert(SOURCE_SPEC, sources)
                print("canonical_newsletter_source_registry=" + json.dumps({"sources": len(sources)}, ensure_ascii=False))
            else:
                print("canonical_newsletter_source_registry=skipped --apply not set")
            return 0

        if args.db is None:
            raise CanonicalNewsletterError("--db is required with --sync")
        payload = prepare_payload(args.db)
        args.payload_out.parent.mkdir(parents=True, exist_ok=True)
        args.payload_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"payload_out={args.payload_out}")
        if args.apply:
            result = apply_payload(payload, upload_raw_html=not args.skip_raw_html_upload)
            print("canonical_newsletter_sync=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            print("canonical_newsletter_sync=skipped --apply not set")
    except (OSError, ValueError, sqlite3.Error, CanonicalNewsletterError) as exc:
        print(f"FAIL canonical newsletter sync: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
