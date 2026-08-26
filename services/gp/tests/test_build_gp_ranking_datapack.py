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

            self.assertEqual(result["fund_rows"], 2369)
            self.assertEqual(result["ranked_gps"], 580)
            self.assertEqual(result["gp_change_funds"], 195)
            self.assertEqual(result["commitment_trn_krw"], 279.489082)
            self.assertGreater(result["formula_count"], 4_700)
            self.assertFalse(result["excel_normalized"])

            with zipfile.ZipFile(output) as archive:
                workbook = archive.read("xl/workbook.xml").decode("utf-8")
                ranking = archive.read("xl/worksheets/sheet6.xml").decode("utf-8")
                ledger = archive.read("xl/worksheets/sheet5.xml").decode("utf-8")
                qa = archive.read("xl/worksheets/sheet10.xml").decode("utf-8")

            self.assertIn('name="Raw 2025Q4"', workbook)
            self.assertIn('name="GP DB Snapshot"', workbook)
            self.assertIn('name="GP Change History"', workbook)
            self.assertIn("SUMIF('Fund Attribution Ledger'!$C$4:$C$2372", ranking)
            self.assertIn("J4*'Assumptions'!$B$10", ledger)
            self.assertIn("SUM('GP DB Snapshot'!$E$4:$E$583)", qa)

    def test_cumulative_analytics_counts_each_normalized_fund_once(self) -> None:
        conn = sqlite3.connect(DEFAULT_DB)
        try:
            attribution_count, total_commitment = conn.execute(
                """
                SELECT COUNT(*), ROUND(SUM(max_commitment_trn_krw), 6)
                FROM analytics_gp_cumulative_fund_attribution
                """
            ).fetchone()
            unique_fund_count, unique_fund_total = conn.execute(
                """
                SELECT COUNT(*), ROUND(SUM(max_commitment_trn_krw), 6)
                FROM fund_master
                """
            ).fetchone()
            change_count = conn.execute(
                "SELECT COUNT(*) FROM analytics_gp_cumulative_change_history"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(attribution_count, unique_fund_count)
        self.assertEqual(total_commitment, unique_fund_total)
        self.assertEqual(change_count, 195)


if __name__ == "__main__":
    unittest.main()
