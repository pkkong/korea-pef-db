#!/usr/bin/env python3
"""Attach public LP selection context to a temporary GP build database."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.shared.src.daily_news_common import GpAlias, load_gp_aliases, normalize_for_match  # noqa: E402


DEFAULT_LP_CONTEXT_URL = "https://pkkong.github.io/kpef-newsletter/lp-notices.json"
CONTEXT_SOURCE = "gp_public_lp_context"
CONTEXT_VERSION = "lp-public-notice-context-v1"
NOTICE_ID_MODULUS = 8_000_000_000_000_000_000


class GPLPContextError(RuntimeError):
    pass


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _stable_notice_id(row: dict[str, object]) -> int:
    parts = [
        _clean(row.get("lpCode")),
        _clean(row.get("noticeId")),
        _clean(row.get("title")),
        _clean(row.get("eventDate")),
    ]
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % NOTICE_ID_MODULUS


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def ensure_lp_context_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lp_institution (
            lp_code TEXT PRIMARY KEY,
            lp_name TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lp_commitment_notice (
            notice_id INTEGER PRIMARY KEY,
            lp_code TEXT,
            source_type TEXT,
            event_type TEXT,
            event_date TEXT,
            announced_date TEXT,
            title TEXT,
            notice_url TEXT,
            asset_class TEXT,
            strategy TEXT,
            program_name TEXT,
            allocation_amount_krw_100mn REAL,
            commitment_amount_krw_100mn REAL,
            amount_confidence TEXT,
            public_visible INTEGER NOT NULL DEFAULT 1,
            discovered_at TEXT,
            context_source TEXT
        )
        """
    )
    required_columns = {
        "context_source": "TEXT",
        "discovered_at": "TEXT",
    }
    existing_columns = _table_columns(conn, "lp_commitment_notice")
    for column, column_type in required_columns.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE lp_commitment_notice ADD COLUMN {column} {column_type}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lp_notice_gp_link (
            notice_id INTEGER NOT NULL,
            lp_code TEXT,
            source_gp_id INTEGER NOT NULL,
            gp_name TEXT,
            matched_alias TEXT,
            link_source TEXT NOT NULL,
            confidence TEXT NOT NULL DEFAULT 'high',
            PRIMARY KEY (notice_id, source_gp_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_gp_lp_context_link ON lp_notice_gp_link(source_gp_id, notice_id)"
    )


def fetch_context(context_url: str) -> dict[str, object]:
    request = Request(context_url, headers={"User-Agent": "kpef-gp-lp-context/1.0"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise GPLPContextError("LP public context is not an object")
    if _clean(payload.get("schemaVersion")) != CONTEXT_VERSION:
        raise GPLPContextError("LP public context schema version is unsupported")
    if not isinstance(payload.get("notices"), list):
        raise GPLPContextError("LP public context notices must be a list")
    return payload


def _aliases_by_normalized_name(aliases: list[GpAlias]) -> dict[str, list[GpAlias]]:
    by_name: dict[str, list[GpAlias]] = {}
    for alias in aliases:
        by_name.setdefault(alias.alias_norm, []).append(alias)
    return by_name


def _selected_gp_matches(value: object, aliases_by_name: dict[str, list[GpAlias]]) -> list[GpAlias]:
    raw_names = value if isinstance(value, list) else []
    matches: list[GpAlias] = []
    seen_gp_ids: set[int] = set()
    for raw_name in raw_names:
        normalized_name = normalize_for_match(_clean(raw_name))
        candidates = aliases_by_name.get(normalized_name, [])
        candidate_gp_ids = {candidate.gp_id for candidate in candidates}
        if len(candidate_gp_ids) != 1 or not candidates:
            continue
        candidate = sorted(candidates, key=lambda item: (-len(item.alias_norm), item.alias_name))[0]
        if candidate.gp_id not in seen_gp_ids:
            seen_gp_ids.add(candidate.gp_id)
            matches.append(candidate)
    return matches


def _number(value: object) -> float | None:
    try:
        parsed = float(str(value or "").replace(",", ""))
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def hydrate_context(db_path: Path, payload: dict[str, object]) -> dict[str, int]:
    if not db_path.is_file():
        raise GPLPContextError(f"GP build database is missing: {db_path}")
    aliases = load_gp_aliases(db_path)
    if not aliases:
        raise GPLPContextError("GP alias set is empty; build GP profiles before hydrating LP context")
    aliases_by_name = _aliases_by_normalized_name(aliases)
    rows = [row for row in payload.get("notices", []) if isinstance(row, dict)]
    linked_notice_count = 0
    linked_gp_ids: set[int] = set()
    link_count = 0
    with sqlite3.connect(db_path) as conn:
        ensure_lp_context_schema(conn)
        conn.execute("DELETE FROM lp_notice_gp_link WHERE link_source = ?", (CONTEXT_SOURCE,))
        conn.execute("DELETE FROM lp_commitment_notice WHERE context_source = ?", (CONTEXT_SOURCE,))
        for row in rows:
            gp_matches = _selected_gp_matches(row.get("selectedGpNames"), aliases_by_name)
            if not gp_matches:
                continue
            notice_id = _stable_notice_id(row)
            lp_code = _clean(row.get("lpCode"))
            lp_name = _clean(row.get("lpName")) or lp_code
            if lp_code and lp_name:
                conn.execute(
                    "INSERT OR REPLACE INTO lp_institution (lp_code, lp_name) VALUES (?, ?)",
                    (lp_code, lp_name),
                )
            conn.execute(
                """
                INSERT INTO lp_commitment_notice (
                    notice_id, lp_code, source_type, event_type, event_date,
                    announced_date, title, notice_url, asset_class, strategy,
                    program_name, allocation_amount_krw_100mn,
                    commitment_amount_krw_100mn, amount_confidence, public_visible,
                    discovered_at, context_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    notice_id,
                    lp_code,
                    "public_context",
                    _clean(row.get("eventType")),
                    _clean(row.get("eventDate")),
                    _clean(row.get("announcedDate")),
                    _clean(row.get("title")) or "LP 출자 이력",
                    _clean(row.get("noticeUrl")),
                    _clean(row.get("assetClass")),
                    _clean(row.get("strategy")),
                    _clean(row.get("programName")),
                    _number(row.get("allocationAmount")),
                    None,
                    "public_context",
                    _clean(payload.get("reportDate")),
                    CONTEXT_SOURCE,
                ),
            )
            linked_notice_count += 1
            for alias in gp_matches:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO lp_notice_gp_link (
                        notice_id, lp_code, source_gp_id, gp_name, matched_alias,
                        link_source, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        notice_id,
                        lp_code,
                        alias.gp_id,
                        alias.canonical_name,
                        alias.alias_name,
                        CONTEXT_SOURCE,
                        "high",
                    ),
                )
                link_count += 1
                linked_gp_ids.add(alias.gp_id)
    return {
        "public_notices": len(rows),
        "linked_notices": linked_notice_count,
        "lp_gp_links": link_count,
        "linked_gp_count": len(linked_gp_ids),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hydrate a temporary GP build DB from public LP notice context")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--context-url", default=DEFAULT_LP_CONTEXT_URL)
    args = parser.parse_args(argv)
    try:
        payload = fetch_context(args.context_url)
        result = hydrate_context(args.db, payload)
    except (OSError, ValueError, sqlite3.Error, GPLPContextError) as exc:
        print(f"FAIL GP LP context: {exc}", file=sys.stderr)
        return 1
    print("gp_lp_context=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
