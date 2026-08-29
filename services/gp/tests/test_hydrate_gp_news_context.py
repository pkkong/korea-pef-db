from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.gp.src.hydrate_gp_news_context import hydrate_archive


class GPNewsContextTests(unittest.TestCase):
    def _create_gp_db(self, path: Path) -> None:
        with sqlite3.connect(path) as conn:
            # Match the minimal pre-People restore shape to cover schema expansion.
            conn.execute("CREATE TABLE news_document (news_id INTEGER PRIMARY KEY)")
            conn.execute(
                """
                CREATE TABLE gp_house (
                    gp_id INTEGER PRIMARY KEY,
                    gp_name TEXT NOT NULL,
                    gp_name_norm TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE gp_profile (
                    source_gp_id INTEGER PRIMARY KEY,
                    standard_gp_name TEXT NOT NULL,
                    display_name_ko TEXT,
                    legal_entity_name_ko TEXT,
                    legal_entity_name_en TEXT,
                    alias_names TEXT,
                    raw_name_variants TEXT
                )
                """
            )
            rows = [
                (2, "엠비케이파트너스", "엠비케이파트너스", "MBK", ""),
                (311, "글랜우드프라이빗에쿼티", "글랜우드프라이빗에쿼티", "글랜우드", ""),
                (17467, "글랜우드크레딧", "글랜우드크레딧", "글랜우드크레딧", ""),
            ]
            for gp_id, gp_name, standard_name, aliases, variants in rows:
                conn.execute("INSERT INTO gp_house VALUES (?, ?, ?)", (gp_id, gp_name, gp_name.lower()))
                conn.execute(
                    """
                    INSERT INTO gp_profile (
                        source_gp_id, standard_gp_name, display_name_ko,
                        legal_entity_name_ko, legal_entity_name_en, alias_names, raw_name_variants
                    ) VALUES (?, ?, ?, '', '', ?, ?)
                    """,
                    (gp_id, standard_name, standard_name, aliases, variants),
                )

    def test_hydrates_news_and_prefers_specific_gp_alias(self) -> None:
        archive = [
            {
                "reportDate": "2026-08-29",
                "articles": [
                    {
                        "url": "https://example.test/glenwood-credit",
                        "title": "글랜우드크레딧, 실리콘투 지분 매각",
                        "source": "테스트뉴스",
                        "summaryText": "글랜우드크레딧이 블록딜로 지분을 처분했다.",
                        "section": "Deal",
                        "subCategory": "Exit",
                    },
                    {
                        "url": "https://example.test/mbk",
                        "title": "MBK, 신규 인수 협상 착수",
                        "source": "테스트뉴스",
                        "summaryText": "관련 거래가 진행 중이다.",
                        "section": "Deal",
                    },
                    {
                        "url": "https://example.test/declared",
                        "title": "운용사 시장 동향",
                        "source": "테스트뉴스",
                        "summaryText": "일반 시장 기사다.",
                        "section": "Market",
                        "gpNames": ["엠비케이파트너스"],
                    },
                ],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "gp.db"
            self._create_gp_db(db_path)

            result = hydrate_archive(db_path, archive)
            repeat_result = hydrate_archive(db_path, archive)

            with sqlite3.connect(db_path) as conn:
                document_columns = {row[1] for row in conn.execute("PRAGMA table_info(news_document)")}
                links = conn.execute(
                    "SELECT entity_ref, entity_name FROM news_entity_link ORDER BY entity_ref"
                ).fetchall()
                tags = conn.execute("SELECT COUNT(*) FROM news_tag").fetchone()[0]

        self.assertIn("title", document_columns)
        self.assertIn("source_url", document_columns)
        self.assertEqual(result["articles"], 3)
        self.assertEqual(result["news_entity_links"], 3)
        self.assertEqual(repeat_result, result)
        self.assertEqual(
            links,
            [
                ("gp:17467", "글랜우드크레딧"),
                ("gp:2", "엠비케이파트너스"),
                ("gp:2", "엠비케이파트너스"),
            ],
        )
        self.assertNotIn(("gp:311", "글랜우드프라이빗에쿼티"), links)
        self.assertEqual(tags, 4)


if __name__ == "__main__":
    unittest.main()
