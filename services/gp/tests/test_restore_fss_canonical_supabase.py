#!/usr/bin/env python3
"""No-network tests for canonical FSS-to-SQLite restoration."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "restore_fss_canonical_supabase",
    ROOT / "services" / "gp" / "src" / "restore_fss_canonical_supabase.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _snapshot() -> dict[str, object]:
    return {
        "snapshot_id": "fss-core-2025q4-test",
        "reporting_period": "2025Q4",
        "as_of_date": "2025-12-31",
        "source_id": "FSS_PEF_2025_Q4",
        "source_sha256": "a" * 64,
        "fund_count": 1,
        "primary_gp_count": 1,
        "commitment_amount_krw_mn": 1000,
        "generated_at": "2026-08-28T00:00:00+00:00",
    }


def _rows(resource: str) -> list[dict[str, object]]:
    source_id = "FSS_PEF_2025_Q4"
    period_id = "FSS_PEF_2025_Q4"
    data: dict[str, list[dict[str, object]]] = {
        "fss_source_documents": [
            {
                "source_id": source_id,
                "title": "PEF 2025Q4",
                "publisher": "금융감독원",
                "document_type": "quarterly_pef_status",
                "regime": "current",
                "period_label": "2025Q4",
                "as_of_date": "2025-12-31",
                "source_url": "https://example.test/fss",
                "local_path": "raw.xlsx",
                "sha256": "a" * 64,
                "fetched_at": "2026-07-02",
                "parsed_at": "2026-07-02",
                "notes": None,
            }
        ],
        "fss_reporting_periods": [
            {
                "period_id": period_id,
                "period_label": "2025Q4",
                "as_of_date": "2025-12-31",
                "year": 2025,
                "quarter": 4,
                "regime": "current",
            }
        ],
        "fss_gp_houses": [
            {
                "gp_id": 1,
                "gp_name": "테스트GP",
                "gp_name_norm": "테스트gp",
                "first_seen_period_id": period_id,
                "last_seen_period_id": period_id,
                "created_at": "2026-07-02",
                "updated_at": "2026-07-02",
            }
        ],
        "fss_pef_funds": [
            {
                "fund_id": 1,
                "fund_name": "테스트펀드",
                "fund_name_norm": "테스트펀드",
                "regime_first_seen": "current",
                "fund_type": "PEF",
                "established_date": "2025-01-01",
                "liquidation_date": None,
                "created_at": "2026-07-02",
                "updated_at": "2026-07-02",
            }
        ],
        "fss_fund_gp_affiliations": [
            {
                "fund_id": 1,
                "gp_id": 1,
                "role": "업무집행사원",
                "first_seen_period_id": period_id,
                "last_seen_period_id": period_id,
            }
        ],
        "fss_gp_house_aliases": [],
        "fss_source_rows": [
            {
                "source_row_id": 1,
                "source_id": source_id,
                "sheet_name": "Sheet1",
                "row_number": 2,
                "raw_row_json": "{}",
                "row_hash": "row-1",
            }
        ],
        "fss_fund_period_snapshots": [
            {
                "fund_period_snapshot_id": 1,
                "fund_id": 1,
                "period_id": period_id,
                "source_id": source_id,
                "gp_id": 1,
                "sheet_name": "Sheet1",
                "row_number": 2,
                "sheet_role": "all",
                "fund_name_raw": "테스트펀드",
                "gp_name_raw": "테스트GP",
                "fund_type_raw": "PEF",
                "status_raw": "운용중",
                "established_date_raw": "2025-01-01",
                "liquidation_date_raw": None,
                "commitment_amount_raw": "1,000",
                "commitment_amount_krw_mn": 1000,
                "paid_in_amount_raw": "500",
                "paid_in_amount_krw_mn": 500,
                "raw_row_json": "{}",
                "row_hash": "row-1",
            }
        ],
        "fss_fund_events": [
            {
                "fund_event_id": 1,
                "fund_id": 1,
                "gp_id": 1,
                "event_type": "established",
                "event_date": "2025-01-01",
                "period_id": period_id,
                "source_id": source_id,
                "confidence": "A",
                "basis": "source",
                "created_at": "2026-07-02",
            }
        ],
        "people_persons": [
            {
                "person_id": 1,
                "person_name_ko": "홍길동",
                "person_name_en": None,
                "person_name_norm": "홍길동",
                "current_primary_org_type": "GP",
                "current_primary_org_id": "1",
                "current_primary_org_name": "테스트GP",
                "current_title": "대표",
                "profile_status": "published",
                "verification_level": "official",
                "primary_source_url": "https://example.test/team",
                "notes": None,
                "created_at": "2026-07-02",
                "updated_at": "2026-07-02",
            }
        ],
        "people_aliases": [],
        "people_roles": [
            {
                "role_id": 1,
                "person_id": 1,
                "org_type": "GP",
                "org_id": "1",
                "org_name": "테스트GP",
                "title": "대표",
                "team": None,
                "role_start_date": None,
                "role_end_date": None,
                "is_current": True,
                "source_url": "https://example.test/team",
                "source_title": "팀",
                "source_grade": "official",
                "verification_status": "verified",
                "notes": None,
                "created_at": "2026-07-02",
                "updated_at": "2026-07-02",
            }
        ],
        "people_educations": [],
        "people_sources": [],
    }
    return data.get(resource, [])


class CanonicalRestoreTests(unittest.TestCase):
    def test_restores_new_temporary_db_and_manifest(self) -> None:
        original_snapshot = MODULE._published_snapshot
        original_read_all = MODULE._read_all
        MODULE._published_snapshot = _snapshot
        MODULE._read_all = lambda resource, _query: _rows(resource)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                db_path = root / "restored.db"
                manifest_path = root / "manifest.json"
                result = MODULE.restore_snapshot(
                    db_path=db_path,
                    manifest_out=manifest_path,
                    include_people=True,
                )
                with sqlite3.connect(db_path) as conn:
                    self.assertEqual(conn.execute("SELECT count(*) FROM fund_period_snapshot").fetchone()[0], 1)
                    self.assertEqual(conn.execute("SELECT count(*) FROM person").fetchone()[0], 1)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        finally:
            MODULE._published_snapshot = original_snapshot
            MODULE._read_all = original_read_all

        self.assertEqual(result["snapshot_id"], "fss-core-2025q4-test")
        self.assertEqual(manifest["snapshot"]["reporting_period"], "2025Q4")

    def test_refuses_to_overwrite_existing_db(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "existing.db"
            db_path.touch()
            with self.assertRaises(MODULE.CanonicalRestoreError):
                MODULE.restore_snapshot(db_path=db_path, manifest_out=Path(temp_dir) / "manifest.json")


if __name__ == "__main__":
    unittest.main()
