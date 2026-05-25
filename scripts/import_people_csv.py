from __future__ import annotations

import argparse
import csv
import sqlite3
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "db" / "private_equity.db"
DEFAULT_SCHEMA = ROOT / "schema" / "people.sql"
DEFAULT_PEOPLE = ROOT / "data" / "people_input.csv"
DEFAULT_ROLES = ROOT / "data" / "person_role_input.csv"
DEFAULT_EDUCATION = ROOT / "data" / "person_education_input.csv"
DEFAULT_SCHOOL_ALIASES = ROOT / "data" / "school_name_aliases.csv"


def norm(value: str | None) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().lower().replace(" ", "")


def clean(value: str | None) -> str:
    return str(value or "").strip()


def clean_int(value: str | None) -> int | None:
    text = clean(value)
    if not text:
        return None
    return int(text)


def clean_bool(value: str | None) -> int:
    return 1 if clean(value).lower() in {"1", "y", "yes", "true", "현재", "current"} else 0


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f) if any(clean(value) for value in row.values())]


def column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    return any(row[1] == column_name for row in conn.execute(f"PRAGMA table_info({table_name})"))


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
    if not column_exists(conn, "person_education", "school_name_en"):
        conn.execute("ALTER TABLE person_education ADD COLUMN school_name_en TEXT")


def load_school_aliases(path: Path) -> dict[str, tuple[str, str | None]]:
    aliases: dict[str, tuple[str, str | None]] = {}
    for row in read_rows(path):
        raw_name = clean(row.get("school_name_raw"))
        school_name_ko = clean(row.get("school_name_ko"))
        school_name_en = clean(row.get("school_name_en")) or raw_name
        if raw_name and school_name_ko:
            aliases[raw_name] = (school_name_ko, school_name_en)
    return aliases


def lookup_gp_id(conn: sqlite3.Connection, gp_name: str, gp_id: str = "") -> str:
    if clean(gp_id):
        return clean(gp_id)
    if not clean(gp_name):
        return ""
    row = conn.execute(
        """
        SELECT gp_id
        FROM gp_house
        WHERE gp_name_norm = ?
        """,
        (norm(gp_name),),
    ).fetchone()
    return str(row[0]) if row else ""


def find_person(
    conn: sqlite3.Connection,
    person_name_ko: str,
    current_gp_id: str = "",
    person_name_en: str = "",
) -> int | None:
    name_norm = norm(person_name_ko)
    name_en_lower = clean(person_name_en).lower()
    if current_gp_id:
        row = conn.execute(
            """
            SELECT person_id
            FROM person
            WHERE (person_name_norm = ?
                   OR (? <> '' AND LOWER(COALESCE(person_name_en, '')) = ?))
              AND COALESCE(current_primary_org_id, '') = ?
            ORDER BY person_id
            LIMIT 1
            """,
            (name_norm, name_en_lower, name_en_lower, current_gp_id),
        ).fetchone()
        if row:
            return int(row[0])
        row = conn.execute(
            """
            SELECT p.person_id
            FROM person p
            JOIN person_alias pa
                ON pa.person_id = p.person_id
            WHERE pa.alias_name_norm = ?
              AND COALESCE(p.current_primary_org_id, '') = ?
            ORDER BY p.person_id
            LIMIT 1
            """,
            (name_norm, current_gp_id),
        ).fetchone()
        if row:
            return int(row[0])
    row = conn.execute(
        """
        SELECT person_id
        FROM person
        WHERE person_name_norm = ?
           OR LOWER(COALESCE(person_name_en, '')) = ?
           OR (? <> '' AND LOWER(COALESCE(person_name_en, '')) = ?)
        ORDER BY person_id
        LIMIT 1
        """,
        (name_norm, clean(person_name_ko).lower(), name_en_lower, name_en_lower),
    ).fetchone()
    if row:
        return int(row[0])
    row = conn.execute(
        """
        SELECT person_id
        FROM person_alias
        WHERE alias_name_norm = ?
        ORDER BY person_id
        LIMIT 1
        """,
        (name_norm,),
    ).fetchone()
    return int(row[0]) if row else None


def upsert_person(conn: sqlite3.Connection, row: dict[str, str]) -> int:
    person_name_ko = clean(row.get("person_name_ko"))
    if not person_name_ko:
        raise ValueError("person_name_ko is required")
    current_gp_name = clean(row.get("current_gp_name"))
    current_gp_id = lookup_gp_id(conn, current_gp_name, clean(row.get("current_gp_id")))
    person_id = find_person(conn, person_name_ko, current_gp_id, clean(row.get("person_name_en")))
    values = {
        "person_name_ko": person_name_ko,
        "person_name_en": clean(row.get("person_name_en")) or None,
        "person_name_norm": norm(person_name_ko),
        "current_primary_org_type": "GP" if current_gp_name or current_gp_id else None,
        "current_primary_org_id": current_gp_id or None,
        "current_primary_org_name": current_gp_name or None,
        "current_title": clean(row.get("current_title")) or None,
        "profile_status": clean(row.get("profile_status")) or "draft",
        "verification_level": clean(row.get("verification_level")) or "source_derived",
        "primary_source_url": clean(row.get("primary_source_url")) or None,
        "notes": clean(row.get("notes")) or None,
    }
    if person_id:
        conn.execute(
            """
            UPDATE person
            SET person_name_ko = :person_name_ko,
                person_name_en = COALESCE(:person_name_en, person_name_en),
                person_name_norm = :person_name_norm,
                current_primary_org_type = COALESCE(:current_primary_org_type, current_primary_org_type),
                current_primary_org_id = COALESCE(:current_primary_org_id, current_primary_org_id),
                current_primary_org_name = COALESCE(:current_primary_org_name, current_primary_org_name),
                current_title = COALESCE(:current_title, current_title),
                profile_status = :profile_status,
                verification_level = :verification_level,
                primary_source_url = COALESCE(:primary_source_url, primary_source_url),
                notes = COALESCE(:notes, notes),
                updated_at = CURRENT_TIMESTAMP
            WHERE person_id = :person_id
            """,
            {**values, "person_id": person_id},
        )
        return person_id
    cursor = conn.execute(
        """
        INSERT INTO person (
            person_name_ko, person_name_en, person_name_norm,
            current_primary_org_type, current_primary_org_id, current_primary_org_name,
            current_title, profile_status, verification_level, primary_source_url, notes
        )
        VALUES (
            :person_name_ko, :person_name_en, :person_name_norm,
            :current_primary_org_type, :current_primary_org_id, :current_primary_org_name,
            :current_title, :profile_status, :verification_level, :primary_source_url, :notes
        )
        """,
        values,
    )
    return int(cursor.lastrowid)


def add_source_from_person_row(conn: sqlite3.Connection, person_id: int, row: dict[str, str]) -> int:
    source_url = clean(row.get("primary_source_url"))
    if not source_url:
        return 0
    exists = conn.execute(
        """
        SELECT 1
        FROM person_source
        WHERE person_id = ?
          AND source_url = ?
          AND evidence_scope = 'profile'
        LIMIT 1
        """,
        (person_id, source_url),
    ).fetchone()
    if exists:
        return 0
    conn.execute(
        """
        INSERT INTO person_source (
            person_id, source_type, source_title, source_url, source_grade,
            evidence_scope, evidence_value, verification_status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            person_id,
            "profile",
            clean(row.get("source_title")) or None,
            source_url,
            clean(row.get("source_grade")) or "supporting",
            "profile",
            clean(row.get("current_title")) or clean(row.get("current_gp_name")) or None,
            clean(row.get("verification_level")) or "source_derived",
            clean(row.get("notes")) or None,
        ),
    )
    return 1


def add_role(
    conn: sqlite3.Connection,
    person_id: int,
    org_type: str,
    org_id: str | None,
    org_name: str,
    title: str | None,
    team: str | None,
    role_start_date: str | None,
    role_end_date: str | None,
    is_current: int,
    source_url: str | None,
    source_title: str | None,
    source_grade: str,
    verification_status: str,
    notes: str | None,
) -> int:
    exists = conn.execute(
        """
        SELECT 1
        FROM person_role
        WHERE person_id = ?
          AND org_type = ?
          AND COALESCE(org_id, '') = COALESCE(?, '')
          AND org_name = ?
          AND COALESCE(title, '') = COALESCE(?, '')
          AND COALESCE(team, '') = COALESCE(?, '')
          AND COALESCE(role_start_date, '') = COALESCE(?, '')
          AND COALESCE(role_end_date, '') = COALESCE(?, '')
          AND is_current = ?
        LIMIT 1
        """,
        (person_id, org_type, org_id, org_name, title, team, role_start_date, role_end_date, is_current),
    ).fetchone()
    if exists:
        return 0
    conn.execute(
        """
        INSERT INTO person_role (
            person_id, org_type, org_id, org_name, title, team,
            role_start_date, role_end_date, is_current, source_url,
            source_title, source_grade, verification_status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            person_id,
            org_type,
            org_id,
            org_name,
            title,
            team,
            role_start_date,
            role_end_date,
            is_current,
            source_url,
            source_title,
            source_grade,
            verification_status,
            notes,
        ),
    )
    return 1


def add_education(
    conn: sqlite3.Connection,
    person_id: int,
    school_name: str,
    school_name_en: str | None,
    degree: str | None,
    major: str | None,
    start_year: int | None,
    graduation_year: int | None,
    source_url: str | None,
    source_title: str | None,
    source_grade: str,
    verification_status: str,
    notes: str | None,
) -> int:
    exists = conn.execute(
        """
        SELECT 1
        FROM person_education
        WHERE person_id = ?
          AND school_name = ?
          AND COALESCE(degree, '') = COALESCE(?, '')
          AND COALESCE(major, '') = COALESCE(?, '')
          AND COALESCE(start_year, 0) = COALESCE(?, 0)
          AND COALESCE(graduation_year, 0) = COALESCE(?, 0)
        LIMIT 1
        """,
        (person_id, school_name, degree, major, start_year, graduation_year),
    ).fetchone()
    if exists:
        return 0
    conn.execute(
        """
        INSERT INTO person_education (
            person_id, school_name, school_name_en, degree, major, start_year, graduation_year,
            source_url, source_title, source_grade, verification_status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            person_id,
            school_name,
            school_name_en,
            degree,
            major,
            start_year,
            graduation_year,
            source_url,
            source_title,
            source_grade,
            verification_status,
            notes,
        ),
    )
    return 1


def import_people(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> tuple[int, int]:
    people_count = 0
    source_count = 0
    for row in rows:
        person_id = upsert_person(conn, row)
        people_count += 1
        source_count += add_source_from_person_row(conn, person_id, row)
        current_gp_name = clean(row.get("current_gp_name"))
        current_title = clean(row.get("current_title"))
        if current_gp_name or current_title:
            gp_id = lookup_gp_id(conn, current_gp_name, clean(row.get("current_gp_id")))
            add_role(
                conn,
                person_id,
                "GP",
                gp_id or None,
                current_gp_name or "-",
                current_title or None,
                clean(row.get("team")) or None,
                None,
                None,
                1,
                clean(row.get("primary_source_url")) or None,
                clean(row.get("source_title")) or None,
                clean(row.get("source_grade")) or "supporting",
                clean(row.get("verification_level")) or "source_derived",
                clean(row.get("notes")) or None,
            )
    return people_count, source_count


def import_roles(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> int:
    count = 0
    for row in rows:
        person_name_ko = clean(row.get("person_name_ko"))
        if not person_name_ko:
            continue
        org_type = clean(row.get("org_type")) or "Organization"
        org_name = clean(row.get("org_name"))
        org_id = lookup_gp_id(conn, org_name, clean(row.get("org_id"))) if org_type == "GP" else clean(row.get("org_id"))
        person_id = find_person(conn, person_name_ko, org_id if org_type == "GP" else "")
        if not person_id:
            person_id = upsert_person(conn, {"person_name_ko": person_name_ko})
        count += add_role(
            conn,
            person_id,
            org_type,
            org_id or None,
            org_name or "-",
            clean(row.get("title")) or None,
            clean(row.get("team")) or None,
            clean(row.get("role_start_date")) or None,
            clean(row.get("role_end_date")) or None,
            clean_bool(row.get("is_current")),
            clean(row.get("source_url")) or None,
            clean(row.get("source_title")) or None,
            clean(row.get("source_grade")) or "supporting",
            clean(row.get("verification_status")) or "source_derived",
            clean(row.get("notes")) or None,
        )
    return count


def import_education(
    conn: sqlite3.Connection,
    rows: list[dict[str, str]],
    school_aliases: dict[str, tuple[str, str | None]],
) -> int:
    count = 0
    for row in rows:
        person_name_ko = clean(row.get("person_name_ko"))
        raw_school_name = clean(row.get("school_name"))
        school_name, school_name_en = school_aliases.get(raw_school_name, (raw_school_name, None))
        if not person_name_ko or not school_name:
            continue
        person_id = find_person(conn, person_name_ko)
        if not person_id:
            person_id = upsert_person(conn, {"person_name_ko": person_name_ko})
        count += add_education(
            conn,
            person_id,
            school_name,
            school_name_en,
            clean(row.get("degree")) or None,
            clean(row.get("major")) or None,
            clean_int(row.get("start_year")),
            clean_int(row.get("graduation_year")),
            clean(row.get("source_url")) or None,
            clean(row.get("source_title")) or None,
            clean(row.get("source_grade")) or "supporting",
            clean(row.get("verification_status")) or "source_derived",
            clean(row.get("notes")) or None,
        )
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Import People DB CSV inputs into the private equity SQLite DB.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--people", type=Path, default=DEFAULT_PEOPLE)
    parser.add_argument("--roles", type=Path, default=DEFAULT_ROLES)
    parser.add_argument("--education", type=Path, default=DEFAULT_EDUCATION)
    parser.add_argument("--school-aliases", type=Path, default=DEFAULT_SCHOOL_ALIASES)
    args = parser.parse_args()

    with sqlite3.connect(args.db, timeout=60) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        apply_schema(conn)
        school_aliases = load_school_aliases(args.school_aliases)
        people_count, source_count = import_people(conn, read_rows(args.people))
        role_count = import_roles(conn, read_rows(args.roles))
        education_count = import_education(conn, read_rows(args.education), school_aliases)
        conn.commit()

    print(f"people_rows_processed: {people_count}")
    print(f"person_sources_added: {source_count}")
    print(f"roles_added: {role_count}")
    print(f"education_rows_added: {education_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
