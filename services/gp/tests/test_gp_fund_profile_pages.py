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
    _is_public_person_profile_candidate,
    _read_gp_funds,
    _read_gp_people,
    _read_gp_profiles,
    _read_public_person_profiles,
    _render_fund_rows,
    _render_gp_detail_page,
    _render_person_profile_page,
)


class GpFundProfilePageTests(unittest.TestCase):
    @unittest.skipUnless((ROOT / "db" / "private_equity.db").is_file(), "Full FSS fixture DB is not available; run the data audit after rebuilding it")
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

    @unittest.skipUnless((ROOT / "db" / "private_equity.db").is_file(), "Full FSS fixture DB is not available; run the data audit after rebuilding it")
    def test_gp_profile_uses_the_shared_profile_layout(self) -> None:
        conn = sqlite3.connect(ROOT / "db" / "private_equity.db")
        conn.row_factory = sqlite3.Row
        try:
            profiles = _read_gp_profiles(conn)
            profile = next(item for item in profiles if item["standard_gp_name"] == "엠비케이파트너스")
            profile["funds"] = _read_gp_funds(conn)[str(profile["source_gp_id"])]
            profile["people"] = _read_gp_people(conn)[str(profile["source_gp_id"])]
            person_profiles = _read_public_person_profiles(
                conn,
                {
                    int(person["person_id"])
                    for person in profile["people"]
                    if _is_public_person_profile_candidate(person)
                },
            )
            for person in profile["people"]:
                person_id = int(person["person_id"])
                if person_id in person_profiles:
                    person["profile_page"] = f"person-{person_id}.html"
        finally:
            conn.close()

        html = _render_gp_detail_page("2026-08-28", profile, [])

        self.assertIn('class="gp-shell gp-profile-preview"', html)
        self.assertIn('data-fund-filter="active"', html)
        self.assertIn('name="kpef-fss-reporting-period" content="2025Q4"', html)
        self.assertIn("공동 운용 펀드는 각 GP에 함께 표시합니다.", html)
        self.assertEqual(html.count('class="gp-profile-preview-fund-row"'), len(profile["funds"]))
        self.assertEqual(html.count('class="gp-profile-preview-person-row"'), 13)
        self.assertIn("김병주", html)
        self.assertIn('href="person-', html)
        self.assertRegex(
            html,
            r'<a class="gp-profile-preview-person-link" href="person-\d+\.html"><div>',
        )
        self.assertIn("공식 팀 페이지", html)

    def test_non_mbk_profile_uses_the_same_profile_layout(self) -> None:
        html = _render_gp_detail_page(
            "2026-08-28",
            {
                "source_gp_id": "sample-gp",
                "display_name": "테스트파트너스",
                "latest_period_label": "2025Q4",
                "latest_primary_aum_proxy_krw_100mn": 1200,
                "cumulative_primary_commitment_proxy_krw_100mn": 1800,
                "latest_primary_active_fund_count": 2,
                "latest_primary_rank": 12,
                "funds": [],
                "people": [],
                "lp_signals": [],
                "deal_news": [],
                "news": [],
            },
            [],
        )

        self.assertIn('class="gp-shell gp-profile-preview"', html)
        self.assertIn("테스트파트너스", html)
        self.assertIn("금감원 확인 펀드", html)
        self.assertNotIn('class="gp-detail-grid"', html)

    @unittest.skipUnless((ROOT / "db" / "private_equity.db").is_file(), "Full FSS fixture DB is not available; run the data audit after rebuilding it")
    def test_senior_person_profile_includes_source_backed_career_and_education(self) -> None:
        conn = sqlite3.connect(ROOT / "db" / "private_equity.db")
        conn.row_factory = sqlite3.Row
        try:
            people_by_gp = _read_gp_people(conn)
            mbk_people = next(
                people
                for gp_id, people in people_by_gp.items()
                if gp_id
                == str(
                    conn.execute(
                        "SELECT source_gp_id FROM gp_profile WHERE standard_gp_name = '엠비케이파트너스'"
                    ).fetchone()[0]
                )
            )
            people = _read_public_person_profiles(
                conn,
                {
                    int(person["person_id"])
                    for person in mbk_people
                    if _is_public_person_profile_candidate(person)
                },
            )
        finally:
            conn.close()

        person = next(item for item in people.values() if item["person_name_ko"] == "김병주")
        person["gp_profile_page"] = "gp-2.html"
        person["reporting_period"] = "2025Q4"
        html = _render_person_profile_page("2026-08-28", person)

        self.assertIn('name="kpef-fss-reporting-period" content="2025Q4"', html)
        self.assertIn('href="gp-2.html"', html)
        self.assertIn("Carlyle Asia Partners", html)
        self.assertIn("학력", html)
        self.assertIn("공식 출처", html)


if __name__ == "__main__":
    unittest.main()
