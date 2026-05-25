from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "db" / "private_equity.db"
DEFAULT_OUT = ROOT / "exports" / "people_research_worklist_top50.csv"


def has_hangul(value: str | None) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in str(value or ""))


def object_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE name = ?
          AND type IN ('table', 'view')
        LIMIT 1
        """,
        (name,),
    ).fetchone()
    return row is not None


def people_counts(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    if not object_exists(conn, "v_person_current_gp"):
        return {}
    rows = conn.execute(
        """
        SELECT gp_id, person_name_ko
        FROM v_person_current_gp
        """
    ).fetchall()
    counts: dict[str, dict[str, int]] = {}
    for gp_id, person_name_ko in rows:
        key = str(gp_id or "")
        if key not in counts:
            counts[key] = {"people_count": 0, "korean_name_missing_count": 0}
        counts[key]["people_count"] += 1
        if not has_hangul(person_name_ko):
            counts[key]["korean_name_missing_count"] += 1
    return counts


def next_action(people_count: int, korean_name_missing_count: int, homepage_url: str, primary_source_url: str) -> str:
    if people_count and korean_name_missing_count:
        return "기존 인력 한글명 재검증"
    if people_count:
        return "기존 인력 보강 및 퇴사/현직 검증"
    if homepage_url or primary_source_url:
        return "공식 홈페이지 팀/조직 페이지 확인"
    return "공식 홈페이지, 기사, LinkedIn 등 1차 수집처 탐색"


def coverage_status(people_count: int, korean_name_missing_count: int) -> str:
    if not people_count:
        return "not_started"
    if korean_name_missing_count:
        return "needs_name_review"
    return "started"


def build_rows(conn: sqlite3.Connection, limit: int) -> list[dict[str, object]]:
    counts = people_counts(conn)
    source_rows = conn.execute(
        """
        SELECT
            latest_primary_rank,
            source_gp_id,
            standard_gp_name,
            latest_primary_aum_proxy_krw_100mn,
            latest_primary_active_fund_count,
            cumulative_primary_rank,
            cumulative_primary_commitment_proxy_krw_100mn,
            homepage_url,
            primary_source_url,
            verification_level,
            profile_status
        FROM gp_profile
        WHERE latest_primary_rank IS NOT NULL
        ORDER BY latest_primary_rank
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    rows: list[dict[str, object]] = []
    for row in source_rows:
        (
            rank,
            gp_id,
            gp_name,
            latest_aum,
            active_fund_count,
            cumulative_rank,
            cumulative_commitment,
            homepage_url,
            primary_source_url,
            verification_level,
            profile_status,
        ) = row
        count = counts.get(str(gp_id or ""), {"people_count": 0, "korean_name_missing_count": 0})
        people_count = int(count["people_count"])
        korean_name_missing_count = int(count["korean_name_missing_count"])
        rows.append(
            {
                "rank": rank,
                "gp_id": gp_id,
                "gp_name": gp_name,
                "latest_aum_억원": latest_aum,
                "active_fund_count": active_fund_count,
                "cumulative_rank": cumulative_rank,
                "cumulative_commitment_억원": cumulative_commitment,
                "people_count": people_count,
                "korean_name_missing_count": korean_name_missing_count,
                "coverage_status": coverage_status(people_count, korean_name_missing_count),
                "homepage_url": homepage_url or "",
                "primary_source_url": primary_source_url or "",
                "profile_verification_level": verification_level or "",
                "profile_status": profile_status or "",
                "next_action": next_action(
                    people_count,
                    korean_name_missing_count,
                    str(homepage_url or ""),
                    str(primary_source_url or ""),
                ),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "rank",
        "gp_id",
        "gp_name",
        "latest_aum_억원",
        "active_fund_count",
        "cumulative_rank",
        "cumulative_commitment_억원",
        "people_count",
        "korean_name_missing_count",
        "coverage_status",
        "homepage_url",
        "primary_source_url",
        "profile_verification_level",
        "profile_status",
        "next_action",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build top-GP People DB collection worklist.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    with sqlite3.connect(args.db) as conn:
        rows = build_rows(conn, args.limit)
    write_csv(args.out, rows)

    started = sum(1 for row in rows if int(row["people_count"]) > 0)
    review_needed = sum(1 for row in rows if int(row["korean_name_missing_count"]) > 0)
    print(f"wrote {args.out}")
    print(f"gp_rows={len(rows)}")
    print(f"people_started_gp_count={started}")
    print(f"korean_name_review_gp_count={review_needed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
