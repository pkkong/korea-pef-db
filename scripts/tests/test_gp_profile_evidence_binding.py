from __future__ import annotations

import csv
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from apply_gp_profile_evidence import apply, resolve_gp
from build_gp_profile_master import ensure_tables, load_existing_profiles
from check_gp_profile_evidence_ready import check
from ingest_fss_pef import normalize_name


class GpProfileEvidenceBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "private_equity.db"
        self.evidence_path = root / "gp_profile_evidence.csv"
        self._create_profiles()
        self._write_evidence()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_profiles(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            ensure_tables(conn)
            created_at = "2026-08-27T00:00:00+00:00"
            rows = [
                ("fss_gp_00002", 2, "테스트캐피탈", normalize_name("테스트캐피탈")),
                ("fss_gp_00060", 60, "다른운용사", normalize_name("다른운용사")),
            ]
            conn.executemany(
                """
                INSERT INTO gp_profile (
                    gp_profile_id, source_gp_id, standard_gp_name, gp_name_norm,
                    profile_status, verification_level, active_in_latest_period,
                    source_basis, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'raw_fss_name_only', 'FSS_NAME_ONLY', 0, 'test', ?, ?)
                """,
                [(*row, created_at, created_at) for row in rows],
            )
            conn.commit()
        finally:
            conn.close()

    def _write_evidence(self) -> None:
        with self.evidence_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "source_gp_id",
                    "standard_gp_name",
                    "field_name",
                    "field_value",
                    "source_type",
                    "source_title",
                    "source_url",
                    "source_grade",
                    "verification_status",
                    "evidence_date",
                    "issuer",
                    "notes",
                    "skip",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "source_gp_id": "60",
                    "standard_gp_name": "테스트캐피탈",
                    "field_name": "homepage_url",
                    "field_value": "https://example.com",
                    "source_type": "official_company_website",
                    "source_title": "Test Capital",
                    "source_url": "https://example.com",
                    "source_grade": "OFFICIAL_COMPANY_WEBSITE",
                    "verification_status": "verified",
                }
            )

    def test_standard_name_wins_over_stale_ingestion_id(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            row = {
                "source_gp_id": "60",
                "standard_gp_name": "테스트캐피탈",
            }
            gp_id, _profile_id, standard_name = resolve_gp(conn, row)
        finally:
            conn.close()

        self.assertEqual(gp_id, 2)
        self.assertEqual(standard_name, "테스트캐피탈")

    def test_apply_does_not_write_evidence_to_stale_id_match(self) -> None:
        result = apply(self.db_path, self.evidence_path)
        self.assertEqual(result["updated_gp_profiles"], 1)
        readiness = check(self.db_path, self.evidence_path)
        self.assertEqual(readiness["manual_evidence_rows"], 1)

        conn = sqlite3.connect(self.db_path)
        try:
            profiles = load_existing_profiles(conn)
            target = profiles[normalize_name("테스트캐피탈")]
            other = profiles[normalize_name("다른운용사")]
        finally:
            conn.close()

        self.assertEqual(target["homepage_url"], "https://example.com")
        self.assertEqual(target["verification_level"], "OFFICIAL_SOURCE_VERIFIED")
        self.assertIn(other["homepage_url"], {None, ""})
        self.assertEqual(other["verification_level"], "FSS_NAME_ONLY")

    def test_duplicate_standard_name_blocks_evidence_binding(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            created_at = "2026-08-27T00:00:00+00:00"
            conn.execute(
                """
                INSERT INTO gp_profile (
                    gp_profile_id, source_gp_id, standard_gp_name, gp_name_norm,
                    profile_status, verification_level, active_in_latest_period,
                    source_basis, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'raw_fss_name_only', 'FSS_NAME_ONLY', 0, 'test', ?, ?)
                """,
                (
                    "fss_gp_00003",
                    3,
                    "테스트캐피탈",
                    normalize_name("테스트캐피탈"),
                    created_at,
                    created_at,
                ),
            )
            with self.assertRaisesRegex(ValueError, "Ambiguous GP evidence binding"):
                resolve_gp(
                    conn,
                    {"source_gp_id": "60", "standard_gp_name": "테스트캐피탈"},
                )
        finally:
            conn.close()

    def test_readiness_blocks_stale_manual_evidence(self) -> None:
        apply(self.db_path, self.evidence_path)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE gp_profile_source
                SET source_gp_id = 60, gp_profile_id = 'fss_gp_00060'
                WHERE source_evidence_id LIKE 'manual_%'
                """
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaisesRegex(ValueError, "GP profile evidence is not synchronized"):
            check(self.db_path, self.evidence_path)


if __name__ == "__main__":
    unittest.main()
