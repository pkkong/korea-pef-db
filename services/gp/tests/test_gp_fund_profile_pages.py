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

from services.gp.src.gp_service_pages import _read_gp_funds, _render_fund_rows


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
        self.assertIn("운용 중", html)
        self.assertIn("과거 확인", html)


if __name__ == "__main__":
    unittest.main()
