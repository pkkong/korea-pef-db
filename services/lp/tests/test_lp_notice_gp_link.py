#!/usr/bin/env python
"""Focused checks for LP notice to GP master linking."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.lp.src.build_lp_commitment_monitor import apply_schema, refresh_notice_links
from services.shared.src.daily_news_common import GpAlias


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
    test_refresh_notice_links_matches_comma_and_normalized_gp_aliases()
    test_refresh_notice_links_splits_joint_gp_tokens()
    print("lp_notice_gp_link test passed")
