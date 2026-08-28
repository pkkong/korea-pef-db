#!/usr/bin/env python3
"""Regression coverage for FSS fund lists in public GP profile pages."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.gp.src.gp_service_pages import (
    _read_gp_funds,
    _read_gp_profiles,
    _render_fund_rows,
    _render_gp_detail_page,
    _uses_profile_ui_preview,
)


class GpFundProfilePageTests(unittest.TestCase):
    def test_mbk_profile_includes_all_fss_linked_funds(self) -> None:
        conn = sqlite3.connect(ROOT / "db" / "private_equity.db")
        conn.row_factory = sqlite3.Row
        try:
            funds_by_gp = _read_gp_funds(conn)
            gp_id = str(
                conn.execute(
                    "SELECT source_gp_id FROM gp_profile WHERE standard_gp_name = '엠비케이파트너스'"
                ).fetchone()[0]
            )
            expected_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM fund_master
                WHERE INSTR(
                    ';' || REPLACE(REPLACE(COALESCE(all_canonical_gp_names, ''), '; ', ';'), ' ;', ';') || ';',
                    ';엠비케이파트너스;'
                ) > 0
                """
            ).fetchone()[0]
        finally:
            conn.close()

        funds = funds_by_gp[gp_id]
        html = _render_fund_rows(funds)
        self.assertEqual(len(funds), expected_count)
        self.assertEqual(html.count('<article class="gp-fund-row">'), expected_count)
        self.assertIn("엠비케이파트너스오호사모투자합자회사", html)
        self.assertIn("엠비케이파트너스2015의1호", html)
        self.assertIn("운용중", html)
        self.assertIn("청산완료", html)

    def test_mbk_uses_the_isolated_profile_preview(self) -> None:
        conn = sqlite3.connect(ROOT / "db" / "private_equity.db")
        conn.row_factory = sqlite3.Row
        try:
            profiles = _read_gp_profiles(conn)
            profile = next(item for item in profiles if item["standard_gp_name"] == "엠비케이파트너스")
            profile["funds"] = _read_gp_funds(conn)[str(profile["source_gp_id"])]
        finally:
            conn.close()

        html = _render_gp_detail_page("2026-08-28", profile, [])

        self.assertTrue(_uses_profile_ui_preview(profile))
        self.assertFalse(_uses_profile_ui_preview({"standard_gp_name": "테스트파트너스"}))
        self.assertIn('class="gp-shell gp-profile-preview"', html)
        self.assertIn('data-fund-filter="active"', html)
        self.assertIn('name="kpef-fss-reporting-period" content="2025Q4"', html)
        self.assertIn("공동 운용 펀드는 각 GP에 함께 표시합니다.", html)
        self.assertEqual(html.count('class="gp-profile-preview-fund-row"'), len(profile["funds"]))


if __name__ == "__main__":
    unittest.main()
