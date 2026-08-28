#!/usr/bin/env python3
"""No-network tests for the GP Supabase public read-model publisher."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "sync_gp_public_read_model",
    ROOT / "services" / "gp" / "src" / "sync_gp_public_read_model.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SyncGPPublicReadModelTests(unittest.TestCase):
    def test_prepare_payload_keeps_source_metadata_and_profile_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            site_dir = root / "site"
            site_dir.mkdir()
            for page_name in MODULE.CORE_PAGE_PATHS:
                (site_dir / page_name).write_text(f"<!doctype html><main>2025Q4 {page_name}</main>", encoding="utf-8")
            (site_dir / "gp-2.html").write_text(
                '<!doctype html><meta name="kpef-fss-reporting-period" content="2025Q4"><main>GP profile</main>',
                encoding="utf-8",
            )

            originals = {
                "repo_root": MODULE.REPO_ROOT,
                "check": MODULE.check_fss_statistics,
                "read_registry": MODULE.read_registry,
                "latest": MODULE.latest_registry_row,
                "sha": MODULE.sha256_file,
            }
            MODULE.REPO_ROOT = root
            MODULE.check_fss_statistics = lambda **_: {
                "latest_period": "2025Q4",
                "as_of_date": "2025-12-31",
                "source_id": "FSS_PEF_2025_Q4",
                "fund_count": 1195,
                "primary_gp_count": 397,
                "commitment_amount_krw_mn": 167502408.727255,
            }
            MODULE.read_registry = lambda _: [{"local_file": "source.xlsx"}]
            MODULE.latest_registry_row = lambda *_: {"local_file": "source.xlsx"}
            MODULE.sha256_file = lambda _: "a" * 64
            try:
                payload = MODULE.prepare_payload(
                    site_dir=site_dir,
                    db_path=root / "private_equity.db",
                    registry_path=root / "registry.csv",
                    expected_latest_period="2025Q4",
                )
            finally:
                MODULE.REPO_ROOT = originals["repo_root"]
                MODULE.check_fss_statistics = originals["check"]
                MODULE.read_registry = originals["read_registry"]
                MODULE.latest_registry_row = originals["latest"]
                MODULE.sha256_file = originals["sha"]

        snapshot = payload["snapshot"]
        page_hashes = [
            (page["page_path"], page["content_sha256"])
            for page in payload["pages"]
        ]
        expected_content_hash = MODULE._snapshot_content_sha256(page_hashes)[:12]
        self.assertEqual(
            snapshot["snapshot_id"],
            f"fss-2025q4-{'a' * 12}-{expected_content_hash}",
        )
        self.assertEqual(snapshot["primary_gp_count"], 397)
        self.assertEqual(
            [page["page_path"] for page in payload["pages"]],
            ["market.html", "gps.html", "gp-2.html"],
        )

    def test_period_metadata_allows_localized_profile_copy(self) -> None:
        html = '<meta name="kpef-fss-reporting-period" content="2025Q4"><main>2025년 4분기</main>'
        self.assertTrue(MODULE._page_declares_reporting_period(html, "2025Q4"))
        self.assertFalse(MODULE._page_declares_reporting_period(html, "2025Q3"))

    def test_snapshot_id_changes_when_public_page_content_changes(self) -> None:
        first = MODULE._snapshot_content_sha256(
            [("market.html", "a" * 64), ("gps.html", "b" * 64)]
        )
        changed = MODULE._snapshot_content_sha256(
            [("market.html", "a" * 64), ("gps.html", "c" * 64)]
        )
        self.assertNotEqual(first, changed)

    def test_apply_payload_upserts_pages_before_atomic_publish(self) -> None:
        calls: list[tuple[str, str]] = []
        original_request = MODULE._rest_request
        MODULE._rest_request = lambda resource, method="GET", **_: calls.append((resource, method))
        try:
            result = MODULE.apply_payload(
                {
                    "snapshot": {"snapshot_id": "fss-2025q4-test"},
                    "pages": [
                        {"snapshot_id": "fss-2025q4-test", "page_path": "market.html"},
                        {"snapshot_id": "fss-2025q4-test", "page_path": "gps.html"},
                    ],
                }
            )
        finally:
            MODULE._rest_request = original_request

        self.assertEqual(
            calls,
            [
                ("gp_public_snapshots", "POST"),
                ("gp_public_pages", "POST"),
                ("rpc/publish_gp_public_snapshot", "POST"),
            ],
        )
        self.assertEqual(result["status"], "published")


if __name__ == "__main__":
    unittest.main()
