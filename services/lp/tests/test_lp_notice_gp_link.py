#!/usr/bin/env python
"""Focused checks for LP notice to GP master linking."""

from __future__ import annotations

import sqlite3
import sys
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.lp.src.build_lp_commitment_monitor import (
    apply_schema,
    load_official_candidates,
    refresh_notice_links,
)
from services.shared.src.daily_news_common import GpAlias


def test_lp_schema_has_no_gp_or_news_database_dependency() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        apply_schema(conn, REPO_ROOT / "schema" / "lp_commitments.sql")
        linked_tables = {
            str(row[2])
            for table_name in ("lp_notice_gp_link", "lp_notice_news_link")
            for row in conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
        }
        conn.execute("INSERT INTO lp_institution(lp_code, lp_name) VALUES ('TEST_LP', '테스트 LP')")
        conn.execute(
            """
            INSERT INTO lp_commitment_notice(
                notice_id, lp_code, notice_url, normalized_notice_url, title, monitor_status
            ) VALUES (1, 'TEST_LP', 'https://example.test/notice', 'https://example.test/notice',
                      '출자사업 공고', 'validated')
            """
        )
        conn.execute(
            "INSERT INTO lp_notice_gp_link(notice_id, lp_code, source_gp_id, gp_name) "
            "VALUES (1, 'TEST_LP', 999, '테스트 GP')"
        )
        conn.execute(
            "INSERT INTO lp_notice_news_link(notice_id, news_id, lp_code) "
            "VALUES (1, 999, 'TEST_LP')"
        )
        conn.execute("DELETE FROM lp_commitment_notice WHERE notice_id = 1")
        conn.commit()
    finally:
        conn.close()

    assert "gp_house" not in linked_tables
    assert "news_document" not in linked_tables


def test_apply_schema_removes_legacy_cross_service_foreign_keys() -> None:
    schema_path = REPO_ROOT / "schema" / "lp_commitments.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")
    legacy_schema_sql = schema_sql.replace(
        "FOREIGN KEY (lp_code) REFERENCES lp_institution(lp_code)\n);\n\nCREATE INDEX IF NOT EXISTS idx_lp_notice_gp_link_lp",
        "FOREIGN KEY (lp_code) REFERENCES lp_institution(lp_code),\n"
        "    FOREIGN KEY (source_gp_id) REFERENCES gp_house(gp_id)\n);\n\n"
        "CREATE INDEX IF NOT EXISTS idx_lp_notice_gp_link_lp",
    ).replace(
        "FOREIGN KEY (notice_id) REFERENCES lp_commitment_notice(notice_id) ON DELETE CASCADE,\n"
        "    FOREIGN KEY (lp_code) REFERENCES lp_institution(lp_code)\n);\n\n"
        "CREATE INDEX IF NOT EXISTS idx_lp_notice_news_link_lp",
        "FOREIGN KEY (notice_id) REFERENCES lp_commitment_notice(notice_id) ON DELETE CASCADE,\n"
        "    FOREIGN KEY (news_id) REFERENCES news_document(news_id),\n"
        "    FOREIGN KEY (lp_code) REFERENCES lp_institution(lp_code)\n);\n\n"
        "CREATE INDEX IF NOT EXISTS idx_lp_notice_news_link_lp",
    )
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            "CREATE TABLE gp_house(gp_id INTEGER PRIMARY KEY);"
            "CREATE TABLE news_document(news_id INTEGER PRIMARY KEY);"
        )
        conn.executescript(legacy_schema_sql)
        conn.execute("INSERT INTO gp_house(gp_id) VALUES (1)")
        conn.execute("INSERT INTO news_document(news_id) VALUES (1)")
        conn.execute("INSERT INTO lp_institution(lp_code, lp_name) VALUES ('TEST_LP', '테스트 LP')")
        conn.execute(
            """
            INSERT INTO lp_commitment_notice(
                notice_id, lp_code, notice_url, normalized_notice_url, title, monitor_status
            ) VALUES (1, 'TEST_LP', 'https://example.test/notice', 'https://example.test/notice',
                      '출자사업 공고', 'validated')
            """
        )
        conn.execute(
            "INSERT INTO lp_notice_gp_link(notice_id, lp_code, source_gp_id, gp_name) "
            "VALUES (1, 'TEST_LP', 1, '테스트 GP')"
        )
        conn.execute(
            "INSERT INTO lp_notice_news_link(notice_id, news_id, lp_code) "
            "VALUES (1, 1, 'TEST_LP')"
        )

        apply_schema(conn, schema_path)
        linked_tables = {
            str(row[2])
            for table_name in ("lp_notice_gp_link", "lp_notice_news_link")
            for row in conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
        }
        conn.execute("DROP TABLE gp_house")
        conn.execute("DROP TABLE news_document")
        conn.execute("DELETE FROM lp_commitment_notice WHERE notice_id = 1")
        remaining_links = conn.execute(
            "SELECT (SELECT COUNT(*) FROM lp_notice_gp_link) + "
            "(SELECT COUNT(*) FROM lp_notice_news_link)"
        ).fetchone()[0]
    finally:
        conn.close()

    assert "gp_house" not in linked_tables
    assert "news_document" not in linked_tables
    assert remaining_links == 0


def test_vcs_source_honors_requested_collection_limit() -> None:
    source = {
        "source_code": "vcs_investment_notice",
        "source_kind": "vcs_listing",
        "locator": "https://example.test/vcs",
        "is_active": "1",
    }
    with patch(
        "services.lp.src.build_lp_commitment_monitor.parse_vcs_investment_listing",
        return_value=[],
    ) as parser:
        rows = load_official_candidates(
            [source],
            lp_aliases=[],
            fallback_year=2026,
            report_date="2026-08-29",
            limit_per_source=1,
            allow_insecure_ssl=False,
            gp_aliases=[],
        )

    assert rows == []
    parser.assert_called_once_with(source, 1, False)


def test_listing_fetch_retries_truncated_response() -> None:
    source = {
        "source_code": "kofia_notice_feed",
        "source_kind": "html_listing",
        "locator": "https://example.test/kofia",
        "is_active": "1",
    }
    with (
        patch(
            "services.lp.src.build_lp_commitment_monitor.fetch_text",
            side_effect=[
                IncompleteRead(b"partial", 10),
                {"text": "<html></html>", "final_url": source["locator"]},
            ],
        ) as fetch,
        patch("services.lp.src.build_lp_commitment_monitor.parse_html_listing", return_value=[]) as parser,
        patch("services.lp.src.build_lp_commitment_monitor.time.sleep") as sleep,
    ):
        rows = load_official_candidates(
            [source],
            lp_aliases=[],
            fallback_year=2026,
            report_date="2026-08-29",
            limit_per_source=1,
            allow_insecure_ssl=False,
            gp_aliases=[],
        )

    assert rows == []
    assert fetch.call_count == 2
    parser.assert_called_once_with(source["locator"], "<html></html>", "")
    sleep.assert_called_once()


def test_refresh_notice_links_matches_comma_and_normalized_gp_aliases() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE gp_house(gp_id INTEGER PRIMARY KEY, gp_name TEXT)")
        conn.execute("CREATE TABLE news_document(news_id INTEGER PRIMARY KEY, normalized_source_url TEXT)")
        apply_schema(conn, REPO_ROOT / "schema" / "lp_commitments.sql")
        conn.executemany(
            "INSERT INTO gp_house(gp_id, gp_name) VALUES (?, ?)",
            [
                (1, "아이엠엠인베스트먼트"),
                (2, "스톤브릿지벤처스"),
            ],
        )
        conn.execute(
            "INSERT INTO lp_institution(lp_code, lp_name) VALUES (?, ?)",
            ("TEST_LP", "테스트 LP"),
        )
        conn.execute(
            """
            INSERT INTO lp_commitment_notice(
                notice_id,
                lp_code,
                source_type,
                notice_url,
                normalized_notice_url,
                title,
                event_type,
                selected_gp_names,
                public_visible
            )
            VALUES (1, 'TEST_LP', 'official', 'https://example.test/notice', 'https://example.test/notice',
                    '위탁운용사 선정 결과', 'final_selection', 'I.M.M. PE, 스톤브릿지벤처스', 1)
            """,
        )
        conn.commit()

        gp_links, news_links = refresh_notice_links(
            conn,
            [
                GpAlias(1, "아이엠엠인베스트먼트", "IMM PE", "immpe"),
                GpAlias(2, "스톤브릿지벤처스", "스톤브릿지 벤처스", "스톤브릿지벤처스"),
            ],
        )

        rows = conn.execute(
            """
            SELECT source_gp_id, gp_name, matched_alias, confidence
            FROM lp_notice_gp_link
            ORDER BY source_gp_id
            """
        ).fetchall()
    finally:
        conn.close()

    assert gp_links == 2
    assert news_links == 0
    assert rows == [
        (1, "아이엠엠인베스트먼트", "IMM PE", "high"),
        (2, "스톤브릿지벤처스", "스톤브릿지 벤처스", "high"),
    ]


def test_refresh_notice_links_splits_joint_gp_tokens() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE gp_house(gp_id INTEGER PRIMARY KEY, gp_name TEXT)")
        conn.execute("CREATE TABLE news_document(news_id INTEGER PRIMARY KEY, normalized_source_url TEXT)")
        apply_schema(conn, REPO_ROOT / "schema" / "lp_commitments.sql")
        conn.executemany(
            "INSERT INTO gp_house(gp_id, gp_name) VALUES (?, ?)",
            [
                (1, "NH투자증권"),
                (2, "우리프라이빗에퀴티자산운용"),
            ],
        )
        conn.execute(
            "INSERT INTO lp_institution(lp_code, lp_name) VALUES (?, ?)",
            ("TEST_LP", "테스트 LP"),
        )
        conn.execute(
            """
            INSERT INTO lp_commitment_notice(
                notice_id,
                lp_code,
                source_type,
                notice_url,
                normalized_notice_url,
                title,
                event_type,
                selected_gp_names,
                public_visible
            )
            VALUES (1, 'TEST_LP', 'official', 'https://example.test/notice', 'https://example.test/notice',
                    '위탁운용사 선정 결과', 'final_selection', 'NH투자증권-우리PE', 1)
            """,
        )
        conn.commit()

        gp_links, news_links = refresh_notice_links(
            conn,
            [
                GpAlias(1, "NH투자증권", "NH투자증권", "nh투자증권"),
                GpAlias(2, "우리프라이빗에퀴티자산운용", "우리PE", "우리pe"),
            ],
        )

        rows = conn.execute(
            """
            SELECT source_gp_id, gp_name, matched_alias, confidence
            FROM lp_notice_gp_link
            ORDER BY source_gp_id
            """
        ).fetchall()
    finally:
        conn.close()

    assert gp_links == 2
    assert news_links == 0
    assert rows == [
        (1, "NH투자증권", "NH투자증권", "high"),
        (2, "우리프라이빗에퀴티자산운용", "우리PE", "high"),
    ]


if __name__ == "__main__":
    from scripts.run_regression_tests import run_module_tests
    raise SystemExit(run_module_tests(sys.modules[__name__]))
