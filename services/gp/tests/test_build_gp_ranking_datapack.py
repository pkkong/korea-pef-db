#!/usr/bin/env python3
"""Regression tests for the audit-ready GP ranking data pack."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.build_gp_ranking_datapack import (
    DEFAULT_ALIAS_RULES,
    DEFAULT_DB,
    DEFAULT_REGISTRY,
    build_datapack,
    to_krw_100mn,
)


class GpRankingDataPackTests(unittest.TestCase):
    @unittest.skipUnless((DEFAULT_DB).is_file(), "Full FSS fixture DB is not available; run the data audit after rebuilding it")
    def test_2025q4_data_pack_reconciles_to_the_public_gp_database(self) -> None:
        conn = sqlite3.connect(DEFAULT_DB)
        try:
            expected_fund_rows, expected_commitment = conn.execute(
                """
                SELECT COUNT(*), ROUND(SUM(max_commitment_trn_krw), 6)
                FROM analytics_gp_cumulative_fund_credit
                """
            ).fetchone()
            expected_ranked_gps = conn.execute(
                "SELECT COUNT(*) FROM analytics_gp_cumulative_ranking"
            ).fetchone()[0]
            expected_multi_gp_rows = conn.execute(
                "SELECT COUNT(*) FROM analytics_gp_cumulative_multi_gp_detail"
            ).fetchone()[0]
        finally:
            conn.close()

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "gp_ranking_datapack_2025Q4.xlsx"
            result = build_datapack(
                db_path=DEFAULT_DB,
                registry_path=DEFAULT_REGISTRY,
                alias_rules_path=DEFAULT_ALIAS_RULES,
                output_path=output,
                period_label="2025Q4",
                raw_history="latest",
            )

            self.assertEqual(result["fund_rows"], expected_fund_rows)
            self.assertEqual(result["ranked_gps"], expected_ranked_gps)
            self.assertEqual(result["multi_gp_rows"], expected_multi_gp_rows)
            self.assertEqual(result["commitment_trn_krw"], expected_commitment)
            self.assertGreater(result["formula_count"], expected_ranked_gps)
            self.assertFalse(result["excel_normalized"])

            with zipfile.ZipFile(output) as archive:
                workbook = archive.read("xl/workbook.xml").decode("utf-8")
                ranking = archive.read("xl/worksheets/sheet6.xml").decode("utf-8")
                ledger = archive.read("xl/worksheets/sheet5.xml").decode("utf-8")
                qa = archive.read("xl/worksheets/sheet10.xml").decode("utf-8")

            self.assertIn('name="Raw 2025Q4"', workbook)
            self.assertIn('name="누적 순위"', workbook)
            self.assertIn('name="복수 GP 내역"', workbook)
            data_end_row = expected_fund_rows + 3
            ranking_end_row = expected_ranked_gps + 3
            self.assertIn(f"SUMIF('펀드별 반영'!$C$4:$C${data_end_row}", ranking)
            self.assertIn("최대 총약정액 (억원)", ledger)
            self.assertNotIn("집계 기준", ledger)
            self.assertIn("펀드별 반영 합계 (억원)", qa)
            self.assertIn(f"$O$4:$O${data_end_row}", qa)
            self.assertIn(f"$M$4:$M${data_end_row}", qa)
            self.assertIn(f"SUM('누적 순위'!$E$4:$E${ranking_end_row})", qa)

    def test_amounts_are_converted_to_hundred_million_won(self) -> None:
        self.assertEqual(to_krw_100mn(25.635147), 256351.47)

    @unittest.skipUnless((DEFAULT_DB).is_file(), "Full FSS fixture DB is not available; run the data audit after rebuilding it")
    def test_cumulative_analytics_credits_each_listed_gp(self) -> None:
        conn = sqlite3.connect(DEFAULT_DB)
        try:
            credit_count, total_commitment = conn.execute(
                """
                SELECT COUNT(*), ROUND(SUM(max_commitment_trn_krw), 6)
                FROM analytics_gp_cumulative_fund_credit
                """
            ).fetchone()
            fund_gp_count, fund_gp_total = conn.execute(
                """
                SELECT COUNT(*), ROUND(SUM(fm.max_commitment_trn_krw), 6)
                FROM fund_gp_affiliation fga
                JOIN fund_master fm ON fm.fund_id = fga.fund_id
                WHERE fm.max_commitment_trn_krw IS NOT NULL
                """
            ).fetchone()
            multi_gp_rows = conn.execute(
                "SELECT COUNT(*) FROM analytics_gp_cumulative_multi_gp_detail"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(credit_count, fund_gp_count)
        self.assertEqual(total_commitment, fund_gp_total)
        self.assertGreater(credit_count, 2369)
        self.assertGreater(multi_gp_rows, 0)


if __name__ == "__main__":
    unittest.main()
