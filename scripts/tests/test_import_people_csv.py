from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("import_people_csv", ROOT / "scripts" / "import_people_csv.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PeopleImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "private_equity.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("CREATE TABLE gp_house (gp_id INTEGER PRIMARY KEY, gp_name_norm TEXT NOT NULL)")
        self.conn.execute("INSERT INTO gp_house (gp_id, gp_name_norm) VALUES (500, '테스트파트너스')")
        MODULE.apply_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_canonical_gp_name_overrides_a_stale_csv_id(self) -> None:
        people_rows = [
            {
                "person_name_ko": "홍길동",
                "current_gp_name": "테스트 파트너스",
                "current_gp_id": "17",
                "current_title": "파트너",
                "profile_status": "active",
                "verification_level": "source_derived",
                "primary_source_url": "https://example.com/team",
                "source_grade": "official",
            }
        ]
        MODULE.import_people(self.conn, people_rows)

        row = self.conn.execute(
            "SELECT current_primary_org_id FROM person WHERE person_name_ko = '홍길동'"
        ).fetchone()
        role = self.conn.execute(
            "SELECT org_id FROM person_role WHERE person_id = 1 AND org_type = 'GP' AND is_current = 1"
        ).fetchone()

        self.assertEqual(row[0], "500")
        self.assertEqual(role[0], "500")

    def test_current_gp_role_is_updated_instead_of_duplicated(self) -> None:
        MODULE.import_people(
            self.conn,
            [
                {
                    "person_name_ko": "홍길동",
                    "current_gp_name": "테스트 파트너스",
                    "current_gp_id": "17",
                    "current_title": "파트너",
                    "profile_status": "active",
                    "verification_level": "source_derived",
                    "primary_source_url": "https://example.com/team",
                    "source_grade": "official",
                }
            ],
        )
        MODULE.import_roles(
            self.conn,
            [
                {
                    "person_name_ko": "홍길동",
                    "org_type": "GP",
                    "org_name": "테스트 파트너스",
                    "org_id": "17",
                    "title": "매니징 파트너",
                    "role_start_date": "2020-01",
                    "is_current": "1",
                    "source_url": "https://example.com/leadership",
                    "source_grade": "official",
                    "verification_status": "source_derived",
                }
            ],
        )

        rows = self.conn.execute(
            """
            SELECT org_id, title, role_start_date
            FROM person_role
            WHERE person_id = 1 AND org_type = 'GP' AND is_current = 1
            """
        ).fetchall()

        self.assertEqual(rows, [("500", "매니징 파트너", "2020-01")])

    def test_existing_profile_source_is_refreshed_from_the_csv(self) -> None:
        base_row = {
            "person_name_ko": "홍길동",
            "current_gp_name": "테스트 파트너스",
            "current_gp_id": "17",
            "current_title": "파트너",
            "profile_status": "active",
            "verification_level": "source_derived",
            "primary_source_url": "https://example.com/team",
            "source_grade": "supporting",
        }
        MODULE.import_people(self.conn, [base_row])
        MODULE.import_people(self.conn, [{**base_row, "source_grade": "official"}])

        row = self.conn.execute(
            "SELECT source_grade FROM person_source WHERE person_id = 1 AND evidence_scope = 'profile'"
        ).fetchone()

        self.assertEqual(row[0], "official")

    def test_rejects_unquoted_csv_columns(self) -> None:
        path = Path(self.temp_dir.name) / "invalid.csv"
        path.write_text("name,title\n홍길동,파트너,추가값\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "unexpected CSV columns"):
            MODULE.read_rows(path)


if __name__ == "__main__":
    unittest.main()
