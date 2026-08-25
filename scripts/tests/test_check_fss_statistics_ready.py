from __future__ import annotations

import csv
import hashlib
import importlib.util
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("check_fss_statistics_ready", ROOT / "scripts" / "check_fss_statistics_ready.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FssStatisticsReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.raw_path = self.root / "source.xlsx"
        self.raw_path.write_bytes(b"official-fss-source")
        self.registry_path = self.root / "registry.csv"
        with self.registry_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["source_id", "period_label", "as_of_date", "local_file"])
            writer.writeheader()
            writer.writerow(
                {
                    "source_id": "FSS_PEF_2025_Q4",
                    "period_label": "2025Q4",
                    "as_of_date": "2025-12-31",
                    "local_file": str(self.raw_path.relative_to(ROOT)) if self.raw_path.is_relative_to(ROOT) else str(self.raw_path),
                }
            )
        self.db_path = self.root / "private_equity.db"
        self._create_db()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_db(self) -> None:
        digest = hashlib.sha256(self.raw_path.read_bytes()).hexdigest()
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE source_document (source_id TEXT, period_label TEXT, as_of_date TEXT, sha256 TEXT);
            CREATE TABLE reporting_period (period_id TEXT, period_label TEXT, as_of_date TEXT);
            CREATE TABLE fund_period_snapshot (period_id TEXT, fund_id TEXT, gp_id INTEGER);
            CREATE TABLE v_period_summary (period_label TEXT, as_of_date TEXT, fund_count INTEGER, primary_gp_count INTEGER, commitment_amount_krw_mn REAL);
            CREATE TABLE analytics_gp_ranking_2025Q4 (rank INTEGER);
            """
        )
        conn.execute("INSERT INTO source_document VALUES (?, ?, ?, ?)", ("FSS_PEF_2025_Q4", "2025Q4", "2025-12-31", digest))
        conn.execute("INSERT INTO reporting_period VALUES (?, ?, ?)", ("2025Q4_inst", "2025Q4", "2025-12-31"))
        conn.executemany("INSERT INTO fund_period_snapshot VALUES (?, ?, ?)", [("2025Q4_inst", "fund-1", 1), ("2025Q4_inst", "fund-2", 1)])
        conn.execute("INSERT INTO v_period_summary VALUES (?, ?, ?, ?, ?)", ("2025Q4", "2025-12-31", 2, 1, 100.0))
        conn.execute("INSERT INTO analytics_gp_ranking_2025Q4 VALUES (1)")
        conn.commit()
        conn.close()

    def test_accepts_matching_latest_source_and_statistics(self) -> None:
        original_root = MODULE.REPO_ROOT
        MODULE.REPO_ROOT = self.root
        try:
            summary = MODULE.check_fss_statistics(
                db_path=self.db_path,
                registry_path=self.registry_path,
                expected_latest_period="2025Q4",
                max_source_age_days=400,
                today=date(2026, 8, 21),
            )
        finally:
            MODULE.REPO_ROOT = original_root
        self.assertEqual(summary["fund_count"], 2)
        self.assertEqual(summary["primary_gp_count"], 1)

    def test_rejects_missing_ranking_table(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("DROP TABLE analytics_gp_ranking_2025Q4")
        conn.commit()
        conn.close()
        original_root = MODULE.REPO_ROOT
        MODULE.REPO_ROOT = self.root
        try:
            with self.assertRaises(MODULE.ReadinessError):
                MODULE.check_fss_statistics(
                    db_path=self.db_path,
                    registry_path=self.registry_path,
                    expected_latest_period="2025Q4",
                    max_source_age_days=400,
                    today=date(2026, 8, 21),
                )
        finally:
            MODULE.REPO_ROOT = original_root
