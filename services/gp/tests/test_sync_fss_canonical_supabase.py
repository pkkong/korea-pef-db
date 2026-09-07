from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "sync_fss_canonical_supabase",
    ROOT / "services" / "gp" / "src" / "sync_fss_canonical_supabase.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CanonicalSupabaseSyncTests(unittest.TestCase):
    def test_reads_sqlite_rows_with_snapshot_and_column_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "source.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE local_rows (legacy_id INTEGER, value TEXT)")
            conn.execute("INSERT INTO local_rows VALUES (7, 'value')")
            conn.row_factory = sqlite3.Row
            spec = MODULE.TableSpec(
                "local_rows",
                "remote_rows",
                ("row_id", "value"),
                ("snapshot_id", "row_id"),
                (("row_id", "legacy_id"),),
            )

            rows = MODULE._read_table_rows(conn, spec, snapshot_id="fss-core-test")
            conn.close()

        self.assertEqual(rows, [{"snapshot_id": "fss-core-test", "row_id": 7, "value": "value"}])

    def test_batches_large_rows_by_serialized_payload_size(self) -> None:
        rows = [{"value": "a" * 40}, {"value": "b" * 40}, {"value": "c" * 40}]

        batches = MODULE._batched(rows, size=10, max_bytes=70)

        self.assertEqual(batches, [[rows[0]], [rows[1]], [rows[2]]])

    def test_apply_publishes_fss_after_people_replacement(self) -> None:
        calls: list[tuple[str, str]] = []
        original_request = MODULE._rest_request

        def fake_request(resource: str, *, method: str = "GET", **_kwargs: object) -> None:
            calls.append((method, resource))
            return None

        MODULE._rest_request = fake_request
        try:
            result = MODULE.apply_payload(
                {
                    "snapshot": {"snapshot_id": "fss-core-test", "content_hash": "a" * 64, "table_manifest": MODULE._fss_table_manifest({spec.supabase_table: [] for spec in MODULE.FSS_TABLES})},
                    "fss_tables": {spec.supabase_table: [] for spec in MODULE.FSS_TABLES},
                    "people_tables": {spec.supabase_table: [] for spec in MODULE.PEOPLE_TABLES},
                    "people_state": {"state_key": True, "fss_snapshot_id": "fss-core-test", "source_hash": MODULE._person_source_hash({spec.supabase_table: [] for spec in MODULE.PEOPLE_TABLES})},
                }
            )
        finally:
            MODULE._rest_request = original_request

        self.assertEqual(result["status"], "published")
        self.assertEqual(calls[0], ("GET", "fss_canonical_snapshots"))
        self.assertFalse(any(method == "DELETE" for method, _ in calls))
        self.assertEqual(calls[-1], ("POST", "rpc/replace_people_canonical"))

    def test_people_only_sync_keeps_fss_snapshot_untouched(self) -> None:
        calls: list[tuple[str, str]] = []
        original_request = MODULE._rest_request

        def fake_request(resource: str, *, method: str = "GET", **_kwargs: object) -> None:
            calls.append((method, resource))
            return None

        MODULE._rest_request = fake_request
        try:
            result = MODULE.apply_payload(
                {
                    "snapshot": {"snapshot_id": "fss-core-test", "content_hash": "a" * 64, "table_manifest": MODULE._fss_table_manifest({spec.supabase_table: [] for spec in MODULE.FSS_TABLES})},
                    "fss_tables": {},
                    "sync_fss_data": False,
                    "people_tables": {spec.supabase_table: [] for spec in MODULE.PEOPLE_TABLES},
                    "people_state": {"state_key": True, "fss_snapshot_id": "fss-core-test", "source_hash": MODULE._person_source_hash({spec.supabase_table: [] for spec in MODULE.PEOPLE_TABLES})},
                }
            )
        finally:
            MODULE._rest_request = original_request

        self.assertEqual(result["status"], "people_synced")
        self.assertNotIn(("POST", "fss_canonical_snapshots"), calls)
        self.assertNotIn(("POST", "rpc/publish_fss_canonical_snapshot"), calls)



class CanonicalPublicationSafetyTests(unittest.TestCase):
    def test_transformed_content_and_removed_rows_change_snapshot_identity(self) -> None:
        from copy import deepcopy
        snapshot = {"reporting_period": "2025Q4", "as_of_date": "2025-12-31", "source_id": "test", "source_sha256": "a" * 64, "fund_count": 1, "primary_gp_count": 1, "commitment_amount_krw_mn": 1000}
        tables = {"fss_gp_houses": [{"gp_id": 1, "gp_name": "A", "updated_at": "old"}, {"gp_id": 2, "gp_name": "B"}]}
        original = deepcopy(snapshot); MODULE._version_fss_snapshot(original, deepcopy(tables), {})
        changed = deepcopy(tables); changed["fss_gp_houses"][0]["updated_at"] = "new"
        same = deepcopy(snapshot); MODULE._version_fss_snapshot(same, changed, {})
        self.assertEqual(original["snapshot_id"], same["snapshot_id"])
        changed["fss_gp_houses"].pop()
        removed = deepcopy(snapshot); MODULE._version_fss_snapshot(removed, changed, {})
        self.assertNotEqual(original["snapshot_id"], removed["snapshot_id"])
        changed["fss_gp_houses"][0]["gp_name"] = "Corrected"
        corrected = deepcopy(snapshot); MODULE._version_fss_snapshot(corrected, changed, {})
        self.assertNotEqual(removed["snapshot_id"], corrected["snapshot_id"])

    def test_missing_people_table_is_rejected_before_remote_write(self) -> None:
        from unittest.mock import patch
        with patch.object(MODULE, "_rest_request") as request:
            with self.assertRaises(MODULE.CanonicalSyncError):
                MODULE.apply_payload({"snapshot": {"snapshot_id": "test"}, "fss_tables": {}, "sync_fss_data": False, "people_tables": {}, "people_state": {}})
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
