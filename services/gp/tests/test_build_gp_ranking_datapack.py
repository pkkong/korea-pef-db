#!/usr/bin/env python3
"""Regression tests for the audit-ready GP ranking data pack."""

from __future__ import annotations

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
    def test_2025q4_data_pack_reconciles_to_the_fss_fund_ledger(self) -> None:
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

            self.assertEqual(result["fund_rows"], 1195)
            self.assertEqual(result["ranked_gps"], 397)
            self.assertEqual(result["commitment_trn_krw"], 167.502409)
            self.assertGreater(result["formula_count"], 5_500)

            with zipfile.ZipFile(output) as archive:
                workbook = archive.read("xl/workbook.xml").decode("utf-8")
                ranking = archive.read("xl/worksheets/sheet6.xml").decode("utf-8")
                ledger = archive.read("xl/worksheets/sheet5.xml").decode("utf-8")
                qa = archive.read("xl/worksheets/sheet7.xml").decode("utf-8")

            self.assertIn('name="Raw 2025Q4"', workbook)
            self.assertIn("SUMIFS('Calculation Ledger'!$Q$4:$Q$1198", ranking)
            self.assertIn("O4*P4", ledger)
            self.assertIn("SUM('GP Ranking'!$E$4:$E$400)", qa)


if __name__ == "__main__":
    unittest.main()
