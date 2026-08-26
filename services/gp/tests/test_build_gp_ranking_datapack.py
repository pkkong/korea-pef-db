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
from scripts.build_gp_ranking_datapack import DEFAULT_ALIAS_RULES, DEFAULT_DB, DEFAULT_REGISTRY, build_datapack


class GpRankingDataPackTests(unittest.TestCase):
    def test_2025q4_data_pack_reconciles_to_the_public_gp_database(self) -> None:
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

            self.assertEqual(result["fund_rows"], 3133)
            self.assertEqual(result["ranked_gps"], 725)
            self.assertEqual(result["multi_gp_rows"], 1407)
            self.assertEqual(result["commitment_trn_krw"], 364.157751)
            self.assertGreater(result["formula_count"], 6_000)
            self.assertFalse(result["excel_normalized"])

            with zipfile.ZipFile(output) as archive:
                workbook = archive.read("xl/workbook.xml").decode("utf-8")
                ranking = archive.read("xl/worksheets/sheet6.xml").decode("utf-8")
                ledger = archive.read("xl/worksheets/sheet5.xml").decode("utf-8")
                qa = archive.read("xl/worksheets/sheet10.xml").decode("utf-8")

            self.assertIn('name="Raw 2025Q4"', workbook)
            self.assertIn('name="누적 순위"', workbook)
            self.assertIn('name="복수 GP 내역"', workbook)
            self.assertIn("SUMIF('펀드별 반영'!$C$4:$C$3136", ranking)
            self.assertIn("J4*'집계 기준'!$B$10", ledger)
            self.assertIn("SUM('누적 순위'!$E$4:$E$728)", qa)

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
        self.assertEqual(multi_gp_rows, 1407)


if __name__ == "__main__":
    unittest.main()
