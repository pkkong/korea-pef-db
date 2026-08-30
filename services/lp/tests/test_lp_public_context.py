from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

from scripts.lp_public_visibility import is_public_lp_notice_row
from services.lp.src.build_lp_service_pages import build_lp_service_pages
from services.lp.src.lp_public_context import build_public_notice_context


class LPPublicContextTests(unittest.TestCase):
    def test_candidate_notice_is_not_public_even_when_source_is_official(self) -> None:
        candidate = {
            "source_type": "official",
            "source_code": "kgrowth_notice",
            "event_type": "new_notice",
            "monitor_status": "candidate",
            "confidence": "medium",
            "public_visible": "1",
        }
        validated = {**candidate, "monitor_status": "validated"}

        self.assertFalse(is_public_lp_notice_row(candidate, require_official=True))
        self.assertTrue(is_public_lp_notice_row(validated, require_official=True))

    def test_exports_only_public_notice_context_fields(self) -> None:
        payload = build_public_notice_context(
            "2026-08-29",
            [
                {
                    "noticeId": "17",
                    "lpCode": "nps",
                    "lpName": "국민연금기금",
                    "displayTitle": "2026년 PEF 출자사업",
                    "eventType": "final_selection",
                    "latestEventDate": "2026-08-28",
                    "announcedDate": "2026-08-20",
                    "assetClass": "PEF",
                    "strategy": "Buyout",
                    "allocationAmount": "2500",
                    "selectedGpNames": ["엠비케이파트너스", "글랜우드크레딧"],
                    "sourceLinks": [
                        {
                            "sourceType": "official",
                            "url": "https://example.test/notices/17",
                        }
                    ],
                    "rawExcerpt": "internal source text",
                    "monitorStatus": "candidate",
                    "confidence": "medium",
                }
            ],
        )

        self.assertEqual(payload["schemaVersion"], "lp-public-notice-context-v1")
        self.assertEqual(payload["reportDate"], "2026-08-29")
        self.assertEqual(
            payload["notices"],
            [
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
                    "selectedGpNames": ["엠비케이파트너스", "글랜우드크레딧"],
                    "noticeUrl": "https://example.test/notices/17",
                }
            ],
        )

    def test_missing_monitor_does_not_replace_existing_public_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            site_dir = Path(temp_dir) / "site"
            site_dir.mkdir()
            context_path = site_dir / "lp-notices.json"
            context_path.write_text('{"preserve": true}\n', encoding="utf-8")
            missing_monitor = Path(temp_dir) / "missing-monitor.csv"
            with (
                patch("services.lp.src.lp_legacy_service_pages.read_lp_monitor", return_value=[]),
                patch("services.lp.src.lp_legacy_service_pages.prepare_lp_notice_display_items", return_value=[]),
                patch("services.lp.src.lp_legacy_service_pages.write_lp_notices_page", return_value=0),
                patch("services.lp.src.lp_legacy_service_pages.write_lp_profile_pages", return_value=0),
                patch("services.lp.src.lp_legacy_service_pages.write_lp_notice_detail_pages"),
            ):
                result = build_lp_service_pages(site_dir, "2026-08-29", monitor_path=missing_monitor)

            self.assertEqual(context_path.read_text(encoding="utf-8"), '{"preserve": true}\n')
            self.assertEqual(result["lp_public_notice_context_count"], 0)


if __name__ == "__main__":
    unittest.main()
