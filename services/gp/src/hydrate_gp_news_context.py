#!/usr/bin/env python3
"""Attach published newsletter context to a temporary GP build database.

The GP publisher never opens the newsletter operating database.  It reads the
already-public archive contract, resolves names only against the restored GP
profile and alias set, and writes the small compatibility tables used by the
existing GP renderer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.shared.src.daily_news_common import (  # noqa: E402
    GpAlias,
    load_gp_aliases,
    match_gp_entities,
    normalize_for_match,
    normalize_url,
)


DEFAULT_ARCHIVE_URL = "https://pkkong.github.io/kpef-newsletter/archive.json"
CONTEXT_SOURCE = "gp_public_archive"
ARTICLE_ID_MODULUS = 8_000_000_000_000_000_000


class GPNewsContextError(RuntimeError):
    pass


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _clean_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        name = _clean(item)
        if name and name not in names:
            names.append(name)
    return names


def _stable_article_id(source_url: str) -> int:
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % ARTICLE_ID_MODULUS


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def ensure_news_context_schema(conn: sqlite3.Connection) -> None:
    """Create the renderer-compatible newsletter subset without touching its DB."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_document (
            news_id INTEGER PRIMARY KEY,
            source_url TEXT,
            source_domain TEXT,
            publisher TEXT,
            title TEXT,
            published_at TEXT,
            discovered_at TEXT,
            excerpt_text TEXT,
            relevance_score REAL,
            relevance_label TEXT,
            review_status TEXT,
            is_pe_relevant INTEGER
        )
        """
    )
    required_columns = {
        "source_url": "TEXT",
        "source_domain": "TEXT",
        "publisher": "TEXT",
        "title": "TEXT",
        "published_at": "TEXT",
        "discovered_at": "TEXT",
        "excerpt_text": "TEXT",
        "relevance_score": "REAL",
        "relevance_label": "TEXT",
        "review_status": "TEXT",
        "is_pe_relevant": "INTEGER",
    }
    existing_columns = _table_columns(conn, "news_document")
    for column, column_type in required_columns.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE news_document ADD COLUMN {column} {column_type}")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_tag (
            news_id INTEGER NOT NULL,
            tag_type TEXT NOT NULL,
            tag_value TEXT NOT NULL,
            tag_source TEXT NOT NULL,
            PRIMARY KEY (news_id, tag_type, tag_value, tag_source)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_entity_link (
            news_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            entity_ref TEXT NOT NULL,
            entity_name TEXT NOT NULL,
            matched_alias TEXT NOT NULL,
            match_field TEXT NOT NULL,
            link_source TEXT NOT NULL,
            confidence REAL,
            PRIMARY KEY (news_id, entity_type, entity_ref, matched_alias, match_field, link_source)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_gp_news_context_entity ON news_entity_link(entity_type, entity_ref)"
    )


def fetch_archive(archive_url: str) -> list[dict[str, object]]:
    request = Request(archive_url, headers={"User-Agent": "kpef-gp-news-context/1.0"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise GPNewsContextError("Published newsletter archive is not a list")
    return [row for row in payload if isinstance(row, dict)]


def _declared_matches(names: list[str], aliases: list[GpAlias]) -> list[dict[str, object]]:
    aliases_by_normalized_name: dict[str, list[GpAlias]] = {}
    for alias in aliases:
        aliases_by_normalized_name.setdefault(alias.alias_norm, []).append(alias)

    matches: list[dict[str, object]] = []
    for name in names:
        normalized_name = normalize_for_match(name)
        candidates = aliases_by_normalized_name.get(normalized_name, [])
        gp_ids = {candidate.gp_id for candidate in candidates}
        if len(gp_ids) != 1 or not candidates:
            continue
        candidate = sorted(candidates, key=lambda item: (-len(item.alias_norm), item.alias_name))[0]
        matches.append(
            {
                "entity_type": "GP",
                "entity_ref": f"gp:{candidate.gp_id}",
                "entity_name": candidate.canonical_name,
                "matched_alias": name,
                "match_field": "declared_entity",
                "link_source": CONTEXT_SOURCE,
                "confidence": 1.0,
            }
        )
    return matches


def _prefer_specific_matches(matches: list[dict[str, object]]) -> list[dict[str, object]]:
    """Drop an alias when a longer matched alias names a different GP.

    For example, an article mentioning ``글랜우드크레딧`` must not also be
    attributed to ``글랜우드프라이빗에쿼티`` solely through the short
    ``글랜우드`` alias.
    """
    filtered: list[dict[str, object]] = []
    for candidate in matches:
        alias_norm = normalize_for_match(_clean(candidate.get("matched_alias")))
        if not alias_norm:
            continue
        candidate_ref = _clean(candidate.get("entity_ref"))
        candidate_field = _clean(candidate.get("match_field"))
        shadowed = any(
            candidate_ref != _clean(other.get("entity_ref"))
            and candidate_field == _clean(other.get("match_field"))
            and len(alias_norm) < len(other_alias_norm := normalize_for_match(_clean(other.get("matched_alias"))))
            and alias_norm in other_alias_norm
            for other in matches
        )
        if not shadowed:
            filtered.append(candidate)

    deduped: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in sorted(
        filtered,
        key=lambda item: (
            -float(item.get("confidence") or 0),
            -len(normalize_for_match(_clean(item.get("matched_alias")))),
            _clean(item.get("entity_ref")),
        ),
    ):
        entity_ref = _clean(row.get("entity_ref"))
        if entity_ref and entity_ref not in seen:
            seen.add(entity_ref)
            deduped.append(row)
    return deduped


def _article_matches(article: dict[str, object], aliases: list[GpAlias]) -> list[dict[str, object]]:
    declared = _declared_matches(_clean_names(article.get("gpNames")), aliases)
    derived = match_gp_entities(
        _clean(article.get("title")),
        _clean(article.get("summaryText")),
        "",
        aliases,
    )
    for row in derived:
        row["link_source"] = CONTEXT_SOURCE
    return _prefer_specific_matches([*declared, *derived])


def hydrate_archive(db_path: Path, archive: list[dict[str, object]], max_issues: int = 30) -> dict[str, int]:
    if not db_path.is_file():
        raise GPNewsContextError(f"GP build database is missing: {db_path}")
    aliases = load_gp_aliases(db_path)
    if not aliases:
        raise GPNewsContextError("GP alias set is empty; build GP profiles before hydrating news context")

    article_count = 0
    entity_count = 0
    linked_gp_ids: set[str] = set()
    with sqlite3.connect(db_path) as conn:
        ensure_news_context_schema(conn)
        conn.execute("DELETE FROM news_entity_link WHERE link_source = ?", (CONTEXT_SOURCE,))
        conn.execute("DELETE FROM news_tag WHERE tag_source = ?", (CONTEXT_SOURCE,))
        for issue in archive[:max_issues]:
            report_date = _clean(issue.get("reportDate"))
            articles = issue.get("articles")
            if not report_date or not isinstance(articles, list):
                continue
            for article in articles:
                if not isinstance(article, dict):
                    continue
                source_url = _clean(article.get("url") or article.get("sourceUrl"))
                normalized_url = normalize_url(source_url)
                title = _clean(article.get("title"))
                if not normalized_url or not title:
                    continue
                news_id = _stable_article_id(normalized_url)
                existing = conn.execute(
                    "SELECT source_url FROM news_document WHERE news_id = ?",
                    (news_id,),
                ).fetchone()
                if existing and normalize_url(str(existing[0] or "")) not in {"", normalized_url}:
                    raise GPNewsContextError(f"Stable news ID collision for {normalized_url}")
                source_domain = urlparse(source_url).netloc.lower()
                section = _clean(article.get("section")) or "Market"
                sub_category = _clean(article.get("subCategory"))
                conn.execute(
                    """
                    INSERT INTO news_document (
                        news_id, source_url, source_domain, publisher, title,
                        published_at, discovered_at, excerpt_text, relevance_score,
                        relevance_label, review_status, is_pe_relevant
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(news_id) DO UPDATE SET
                        source_url = excluded.source_url,
                        source_domain = excluded.source_domain,
                        publisher = excluded.publisher,
                        title = excluded.title,
                        published_at = excluded.published_at,
                        discovered_at = excluded.discovered_at,
                        excerpt_text = excluded.excerpt_text,
                        relevance_score = excluded.relevance_score,
                        relevance_label = excluded.relevance_label,
                        review_status = excluded.review_status,
                        is_pe_relevant = excluded.is_pe_relevant
                    """,
                    (
                        news_id,
                        source_url,
                        source_domain,
                        _clean(article.get("source") or article.get("publisher")),
                        title,
                        report_date,
                        report_date,
                        _clean(article.get("summaryText")),
                        1.0,
                        section,
                        "published",
                        1,
                    ),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO news_tag (news_id, tag_type, tag_value, tag_source) VALUES (?, ?, ?, ?)",
                    (news_id, "section", section, CONTEXT_SOURCE),
                )
                if sub_category:
                    conn.execute(
                        "INSERT OR IGNORE INTO news_tag (news_id, tag_type, tag_value, tag_source) VALUES (?, ?, ?, ?)",
                        (news_id, "sub_category", sub_category, CONTEXT_SOURCE),
                    )
                article_count += 1
                for match in _article_matches(article, aliases):
                    entity_ref = _clean(match.get("entity_ref"))
                    if not entity_ref:
                        continue
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO news_entity_link (
                            news_id, entity_type, entity_ref, entity_name, matched_alias,
                            match_field, link_source, confidence
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            news_id,
                            "GP",
                            entity_ref,
                            _clean(match.get("entity_name")),
                            _clean(match.get("matched_alias")),
                            _clean(match.get("match_field")),
                            CONTEXT_SOURCE,
                            float(match.get("confidence") or 0),
                        ),
                    )
                    entity_count += 1
                    linked_gp_ids.add(entity_ref)

    return {
        "archive_issues": min(len(archive), max_issues),
        "articles": article_count,
        "news_entity_links": entity_count,
        "linked_gp_count": len(linked_gp_ids),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hydrate a temporary GP build DB from the published newsletter archive")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--archive-url", default=DEFAULT_ARCHIVE_URL)
    parser.add_argument("--max-issues", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        archive = fetch_archive(args.archive_url)
        result = hydrate_archive(args.db, archive, max_issues=max(args.max_issues, 1))
    except (OSError, ValueError, sqlite3.Error, GPNewsContextError) as exc:
        print(f"FAIL GP news context: {exc}", file=sys.stderr)
        return 1
    print("gp_news_context=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
