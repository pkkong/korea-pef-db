from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.gp.src.gp_service_pages import _read_lp_signals
from services.gp.src.hydrate_gp_lp_context import hydrate_context


class GPLPContextTests(unittest.TestCase):
    def _create_gp_db(self, path: Path) -> None:
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE gp_house (gp_id INTEGER PRIMARY KEY, gp_name TEXT NOT NULL, gp_name_norm TEXT NOT NULL)"
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
            conn.execute("INSERT INTO gp_house VALUES (2, '엠비케이파트너스', '엠비케이파트너스')")
            conn.execute(
                "INSERT INTO gp_profile VALUES (2, '엠비케이파트너스', '엠비케이파트너스', '', '', 'MBK', '')"
            )

    def test_hydrates_only_explicit_selected_gp_names(self) -> None:
        payload = {
            "schemaVersion": "lp-public-notice-context-v1",
            "reportDate": "2026-08-29",
            "notices": [
                {
                    "noticeId": "17",
                    "lpCode": "nps",
                    "lpName": "국민연금기금",
                    "title": "2026년 PEF 출자사업",
                    "eventType": "final_selection",
                    "eventDate": "2026-08-28",
                    "announcedDate": "2026-08-20",
                    "assetClass": "PEF",
                    "strategy": "Buyout",
                    "programName": "2026년 PEF 출자사업",
                    "allocationAmount": "2500",
                    "selectedGpNames": ["MBK"],
                    "noticeUrl": "https://example.test/notices/17",
                },
                {
                    "noticeId": "18",
                    "lpCode": "nps",
                    "lpName": "국민연금기금",
                    "title": "선정 결과 미확인 공고",
                    "selectedGpNames": ["알 수 없는 운용사"],
                    "noticeUrl": "https://example.test/notices/18",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "gp.db"
            self._create_gp_db(db_path)
            result = hydrate_context(db_path, payload)
            repeat_result = hydrate_context(db_path, payload)

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                signal_rows = _read_lp_signals(conn)
                notice_count = conn.execute("SELECT COUNT(*) FROM lp_commitment_notice").fetchone()[0]

        self.assertEqual(result, repeat_result)
        self.assertEqual(result["public_notices"], 2)
        self.assertEqual(result["linked_notices"], 1)
        self.assertEqual(result["lp_gp_links"], 1)
        self.assertEqual(result["linked_gp_count"], 1)
        self.assertEqual(notice_count, 1)
        self.assertEqual(list(signal_rows), ["2"])
        signal = signal_rows["2"][0]
        self.assertEqual(signal["lp_name"], "국민연금기금")
        self.assertEqual(signal["event_type"], "final_selection")
        self.assertEqual(signal["notice_url"], "https://example.test/notices/17")


if __name__ == "__main__":
    unittest.main()
