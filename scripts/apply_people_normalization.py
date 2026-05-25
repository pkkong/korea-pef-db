from __future__ import annotations

import argparse
import csv
import sqlite3
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "db" / "private_equity.db"
DEFAULT_SCHEMA = ROOT / "schema" / "people.sql"
DEFAULT_PERSON_NAME_OVERRIDES = ROOT / "data" / "person_name_overrides.csv"
DEFAULT_SCHOOL_ALIASES = ROOT / "data" / "school_name_aliases.csv"


def clean(value: str | None) -> str:
    return str(value or "").strip()


def has_hangul(value: str | None) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in str(value or ""))


def norm(value: str | None) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().lower().replace(" ", "")


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle) if any(clean(value) for value in row.values())]


def column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    return any(row[1] == column_name for row in conn.execute(f"PRAGMA table_info({table_name})"))


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
    if not column_exists(conn, "person_education", "school_name_en"):
        conn.execute("ALTER TABLE person_education ADD COLUMN school_name_en TEXT")


def lookup_gp_id(conn: sqlite3.Connection, gp_name: str) -> str:
    if not clean(gp_name):
        return ""
    row = conn.execute(
        """
        SELECT gp_id
        FROM gp_house
        WHERE gp_name_norm = ?
        ORDER BY gp_id
        LIMIT 1
        """,
        (norm(gp_name),),
    ).fetchone()
    return str(row[0]) if row else ""


def find_person_for_override(
    conn: sqlite3.Connection,
    gp_name: str,
    person_name_en: str,
    person_name_ko: str,
) -> int | None:
    gp_id = lookup_gp_id(conn, gp_name)
    names = [clean(person_name_ko), clean(person_name_en)]
    normalized_names = [norm(name) for name in names if name]
    lowercase_names = [name.lower() for name in names if name]
    if not normalized_names and not lowercase_names:
        return None

    gp_filter = ""
    params: list[object] = []
    if gp_id:
        gp_filter = "AND COALESCE(p.current_primary_org_id, '') = ?"
        params.append(gp_id)

    placeholders_norm = ",".join("?" for _ in normalized_names) or "''"
    placeholders_lower = ",".join("?" for _ in lowercase_names) or "''"
    query = f"""
        SELECT p.person_id
        FROM person p
        WHERE (
                p.person_name_norm IN ({placeholders_norm})
             OR LOWER(COALESCE(p.person_name_en, '')) IN ({placeholders_lower})
        )
        {gp_filter}
        ORDER BY p.person_id
        LIMIT 1
    """
    row = conn.execute(query, [*normalized_names, *lowercase_names, *params]).fetchone()
    if row:
        return int(row[0])

    alias_query = f"""
        SELECT p.person_id
        FROM person p
        JOIN person_alias pa
            ON pa.person_id = p.person_id
        WHERE pa.alias_name_norm IN ({placeholders_norm})
        {gp_filter}
        ORDER BY p.person_id
        LIMIT 1
    """
    row = conn.execute(alias_query, [*normalized_names, *params]).fetchone()
    return int(row[0]) if row else None


def add_alias(
    conn: sqlite3.Connection,
    person_id: int,
    alias_name: str,
    alias_type: str,
    source_url: str | None,
    verification_status: str,
    notes: str | None,
) -> int:
    alias = clean(alias_name)
    if not alias:
        return 0
    exists = conn.execute(
        """
        SELECT 1
        FROM person_alias
        WHERE person_id = ?
          AND alias_name_norm = ?
          AND alias_type = ?
        LIMIT 1
        """,
        (person_id, norm(alias), alias_type),
    ).fetchone()
    if exists:
        return 0
    conn.execute(
        """
        INSERT INTO person_alias (
            person_id, alias_name, alias_name_norm, alias_type,
            source_url, verification_status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (person_id, alias, norm(alias), alias_type, source_url, verification_status, notes),
    )
    return 1


def add_person_source(
    conn: sqlite3.Connection,
    person_id: int,
    row: dict[str, str],
    evidence_scope: str,
    evidence_value: str,
) -> int:
    source_url = clean(row.get("source_url"))
    if not source_url:
        return 0
    exists = conn.execute(
        """
        SELECT 1
        FROM person_source
        WHERE person_id = ?
          AND source_url = ?
          AND evidence_scope = ?
          AND COALESCE(evidence_value, '') = ?
        LIMIT 1
        """,
        (person_id, source_url, evidence_scope, clean(evidence_value)),
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
            "name_verification",
            clean(row.get("source_title")) or None,
            source_url,
            clean(row.get("source_grade")) or "supporting",
            evidence_scope,
            clean(evidence_value) or None,
            clean(row.get("verification_status")) or "source_derived",
            clean(row.get("notes")) or None,
        ),
    )
    return 1


def apply_person_name_overrides(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> dict[str, int]:
    stats = {"rows": 0, "people_updated": 0, "aliases_added": 0, "sources_added": 0, "not_found": 0}
    for row in rows:
        gp_name = clean(row.get("current_gp_name"))
        person_name_en = clean(row.get("person_name_en"))
        person_name_ko = clean(row.get("person_name_ko"))
        if not person_name_ko:
            continue
        stats["rows"] += 1
        person_id = find_person_for_override(conn, gp_name, person_name_en, person_name_ko)
        if not person_id:
            stats["not_found"] += 1
            continue

        current = conn.execute(
            """
            SELECT person_name_ko, person_name_en
            FROM person
            WHERE person_id = ?
            """,
            (person_id,),
        ).fetchone()
        old_name_ko = clean(current[0]) if current else ""
        old_name_en = clean(current[1]) if current else ""
        updates: dict[str, object] = {
            "person_id": person_id,
            "person_name_ko": person_name_ko,
            "person_name_en": person_name_en or old_name_en or (old_name_ko if old_name_ko != person_name_ko else ""),
            "person_name_norm": norm(person_name_ko),
        }
        conn.execute(
            """
            UPDATE person
            SET person_name_ko = :person_name_ko,
                person_name_en = COALESCE(NULLIF(:person_name_en, ''), person_name_en),
                person_name_norm = :person_name_norm,
                updated_at = CURRENT_TIMESTAMP
            WHERE person_id = :person_id
            """,
            updates,
        )
        if old_name_ko != person_name_ko or (person_name_en and old_name_en != person_name_en):
            stats["people_updated"] += 1

        source_url = clean(row.get("source_url")) or None
        verification_status = clean(row.get("verification_status")) or "source_derived"
        notes = clean(row.get("notes")) or None
        if old_name_ko and old_name_ko != person_name_ko:
            stats["aliases_added"] += add_alias(
                conn,
                person_id,
                old_name_ko,
                "previous_display_name",
                source_url,
                verification_status,
                notes,
            )
        if person_name_en:
            stats["aliases_added"] += add_alias(
                conn,
                person_id,
                person_name_en,
                "english_name",
                source_url,
                verification_status,
                notes,
            )
        stats["sources_added"] += add_person_source(conn, person_id, row, "person_name_ko", person_name_ko)
    return stats


def apply_school_aliases(conn: sqlite3.Connection, rows: list[dict[str, str]]) -> dict[str, int]:
    stats = {"rows": 0, "education_rows_updated": 0}
    for row in rows:
        raw_name = clean(row.get("school_name_raw"))
        school_name_ko = clean(row.get("school_name_ko"))
        school_name_en = clean(row.get("school_name_en")) or raw_name
        if not raw_name or not school_name_ko:
            continue
        stats["rows"] += 1
        cursor = conn.execute(
            """
            UPDATE person_education
            SET school_name = ?,
                school_name_en = COALESCE(NULLIF(school_name_en, ''), ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE school_name = ?
            """,
            (school_name_ko, school_name_en, raw_name),
        )
        stats["education_rows_updated"] += int(cursor.rowcount or 0)
    return stats


def dedupe_education(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        """
        DELETE FROM person_education
        WHERE education_id NOT IN (
            SELECT MIN(education_id)
            FROM person_education
            GROUP BY
                person_id,
                school_name,
                COALESCE(degree, ''),
                COALESCE(major, ''),
                COALESCE(start_year, 0),
                COALESCE(graduation_year, 0)
        )
        """
    )
    return int(cursor.rowcount or 0)


def backfill_latin_display_names(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT person_id, person_name_ko
        FROM person
        WHERE COALESCE(person_name_en, '') = ''
        """
    ).fetchall()
    stats = {"english_names_backfilled": 0, "aliases_added": 0}
    for person_id, person_name_ko in rows:
        if not clean(person_name_ko) or has_hangul(person_name_ko):
            continue
        conn.execute(
            """
            UPDATE person
            SET person_name_en = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE person_id = ?
            """,
            (person_name_ko, person_id),
        )
        stats["english_names_backfilled"] += 1
        stats["aliases_added"] += add_alias(
            conn,
            int(person_id),
            clean(person_name_ko),
            "english_name",
            None,
            "source_derived",
            "원문 공식 프로필의 영문명을 영문명 필드에 보존",
        )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply source-backed Korean display normalization to People DB.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--person-name-overrides", type=Path, default=DEFAULT_PERSON_NAME_OVERRIDES)
    parser.add_argument("--school-aliases", type=Path, default=DEFAULT_SCHOOL_ALIASES)
    args = parser.parse_args()

    with sqlite3.connect(args.db, timeout=60) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        name_stats = apply_person_name_overrides(conn, read_rows(args.person_name_overrides))
        school_stats = apply_school_aliases(conn, read_rows(args.school_aliases))
        education_duplicates_removed = dedupe_education(conn)
        latin_name_stats = backfill_latin_display_names(conn)
        conn.commit()

    print("person_name_normalization:", name_stats)
    print("school_name_normalization:", school_stats)
    print("education_duplicates_removed:", education_duplicates_removed)
    print("latin_name_backfill:", latin_name_stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
