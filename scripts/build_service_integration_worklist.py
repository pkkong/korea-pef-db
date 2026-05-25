#!/usr/bin/env python
"""Build a cross-service worklist connecting Daily News and People DB work.

This worklist is the operating bridge between the newsletter surface and the
entity database. It keeps the newsletter as a user-facing service while turning
news-visible GPs into concrete profile and People DB follow-up tasks.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "db" / "private_equity.db"
DEFAULT_NEWS_WORKLIST = ROOT / "exports" / "daily_news" / "news_gp_update_worklist_latest.csv"
DEFAULT_OUT_DIR = ROOT / "exports"


def clean(value: object) -> str:
    return str(value or "").strip()


def has_hangul(value: object) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in clean(value))


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


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, object]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows([{header: row.get(header, "") for header in headers} for row in rows])


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
        key = clean(gp_id)
        if not key:
            continue
        if key not in counts:
            counts[key] = {"people_count": 0, "korean_name_missing_count": 0}
        counts[key]["people_count"] += 1
        if not has_hangul(person_name_ko):
            counts[key]["korean_name_missing_count"] += 1
    return counts


def load_profiles(conn: sqlite3.Connection, top_gp_limit: int) -> dict[str, dict[str, object]]:
    if not object_exists(conn, "gp_profile"):
        return {}
    cursor = conn.execute(
        """
        SELECT
            source_gp_id,
            standard_gp_name,
            latest_primary_rank,
            latest_primary_aum_proxy_krw_100mn,
            latest_primary_active_fund_count,
            homepage_url,
            primary_source_url,
            verification_level,
            profile_status
        FROM gp_profile
        WHERE source_gp_id IS NOT NULL
        ORDER BY COALESCE(latest_primary_rank, 999999), standard_gp_name
        """
    )
    headers = [desc[0] for desc in cursor.description]
    return {clean(row[0]): dict(zip(headers, row)) for row in cursor.fetchall()}


def people_status(people_count: int, korean_name_missing_count: int) -> str:
    if people_count <= 0:
        return "not_started"
    if korean_name_missing_count:
        return "needs_name_review"
    return "started"


def people_next_action(
    people_count: int,
    korean_name_missing_count: int,
    homepage_url: str,
    primary_source_url: str,
) -> str:
    if people_count and korean_name_missing_count:
        return "기존 인력 한글명/현직 재검증"
    if people_count:
        return "기존 인력 역할·학력·뉴스 연결 보강"
    if homepage_url or primary_source_url:
        return "공식 홈페이지 팀/조직 페이지 확인"
    return "공식 홈페이지, 기사, LinkedIn 등 1차 수집처 탐색"


def parse_int(value: object, default: int = 0) -> int:
    text = clean(value)
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def integrated_owner(news_action: str, people_count: int, korean_name_missing_count: int, row_source: str) -> str:
    if news_action == "프로필 우선 보강":
        return "GP profile"
    if news_action == "식별자 보강":
        return "GP profile"
    if people_count <= 0 or korean_name_missing_count:
        return "People DB"
    if row_source == "news":
        return "Newsletter"
    return "People DB"


def integrated_action(
    news_action: str,
    people_count: int,
    korean_name_missing_count: int,
    row_source: str,
) -> str:
    if news_action == "프로필 우선 보강":
        return "뉴스 노출 GP 프로필 필수정보 보강"
    if news_action == "식별자 보강":
        return "뉴스 노출 GP 식별자 보강"
    if people_count <= 0:
        return "뉴스/Top GP 기준 People 1차 수집"
    if korean_name_missing_count:
        return "People 한글명과 현직 여부 검증"
    if row_source == "news":
        return "뉴스레터에 GP/People 맥락 연결"
    return "People coverage 유지 점검"


def newsletter_context_action(people_count: int, service_ready: str, latest_title: str) -> str:
    if not latest_title:
        return ""
    if people_count:
        return "발행 카드에 GP 프로필 및 관련 인물 맥락 연결"
    if service_ready == "Y":
        return "발행 카드에 GP 프로필 맥락 연결"
    return "발행은 가능하되 DB 맥락은 보강 후 연결"


def priority_tuple(row: dict[str, object]) -> tuple[int, int, int, str]:
    row_source = clean(row.get("row_source"))
    owner = clean(row.get("owner"))
    action = clean(row.get("integrated_action"))
    article_count = int(row.get("article_count") or 0)
    rank = parse_int(row.get("latest_primary_rank"), 999999)
    source_priority = 0 if row_source == "news" else 1
    owner_priority = {"GP profile": 0, "People DB": 1, "Newsletter": 2}.get(owner, 9)
    action_priority = 0 if "필수정보" in action else 1 if "1차 수집" in action else 2
    return (source_priority, owner_priority, action_priority, -article_count, rank, clean(row.get("standard_gp_name")))


def merge_rows(
    conn: sqlite3.Connection,
    news_worklist_path: Path,
    top_gp_limit: int,
) -> list[dict[str, object]]:
    counts = people_counts(conn)
    profiles = load_profiles(conn, top_gp_limit)
    news_rows = read_csv(news_worklist_path)
    merged: dict[str, dict[str, object]] = {}

    for raw in news_rows:
        gp_id = clean(raw.get("source_gp_id"))
        if not gp_id:
            continue
        merged[gp_id] = {
            "row_source": "news",
            "source_gp_id": gp_id,
            "standard_gp_name": clean(raw.get("standard_gp_name")),
            "article_count": int(clean(raw.get("article_count")) or 0),
            "latest_article_at": clean(raw.get("latest_article_at")),
            "latest_publisher": clean(raw.get("latest_publisher")),
            "latest_title": clean(raw.get("latest_title")),
            "latest_url": clean(raw.get("latest_url")),
            "latest_comment": clean(raw.get("latest_comment")),
            "news_action": clean(raw.get("suggested_action")),
            "matched_aliases": clean(raw.get("matched_aliases")),
            "publishers": clean(raw.get("publishers")),
            "service_ready": "Y" if clean(raw.get("service_ready")) else "",
            "identifier_complete": "Y" if clean(raw.get("identifier_complete")) else "",
            "missing_service_fields": clean(raw.get("missing_service_fields")),
            "missing_identifier_fields": clean(raw.get("missing_identifier_fields")),
            "missing_optional_fields": clean(raw.get("missing_optional_fields")),
        }

    for gp_id, profile in profiles.items():
        rank = parse_int(profile.get("latest_primary_rank"), 999999)
        if top_gp_limit > 0 and rank > top_gp_limit:
            continue
        merged.setdefault(
            gp_id,
            {
                "row_source": "top_gp",
                "source_gp_id": gp_id,
                "standard_gp_name": clean(profile.get("standard_gp_name")),
                "article_count": 0,
                "latest_article_at": "",
                "latest_publisher": "",
                "latest_title": "",
                "latest_url": "",
                "latest_comment": "",
                "news_action": "",
                "matched_aliases": "",
                "publishers": "",
                "service_ready": "",
                "identifier_complete": "",
                "missing_service_fields": "",
                "missing_identifier_fields": "",
                "missing_optional_fields": "",
            },
        )

    rows: list[dict[str, object]] = []
    for gp_id, raw in merged.items():
        profile = profiles.get(gp_id, {})
        count = counts.get(gp_id, {"people_count": 0, "korean_name_missing_count": 0})
        people_count = int(count["people_count"])
        korean_missing = int(count["korean_name_missing_count"])
        homepage_url = clean(profile.get("homepage_url"))
        primary_source_url = clean(profile.get("primary_source_url") or raw.get("primary_source_url"))
        news_action = clean(raw.get("news_action"))
        row_source = clean(raw.get("row_source"))
        owner = integrated_owner(news_action, people_count, korean_missing, row_source)
        action = integrated_action(news_action, people_count, korean_missing, row_source)
        rows.append(
            {
                **raw,
                "standard_gp_name": raw.get("standard_gp_name") or clean(profile.get("standard_gp_name")),
                "latest_primary_rank": profile.get("latest_primary_rank", ""),
                "latest_primary_aum_억원": profile.get("latest_primary_aum_proxy_krw_100mn", ""),
                "latest_primary_active_fund_count": profile.get("latest_primary_active_fund_count", ""),
                "profile_verification_level": profile.get("verification_level", ""),
                "profile_status": profile.get("profile_status", ""),
                "homepage_url": homepage_url,
                "primary_source_url": primary_source_url,
                "people_count": people_count,
                "korean_name_missing_count": korean_missing,
                "people_coverage_status": people_status(people_count, korean_missing),
                "people_next_action": people_next_action(
                    people_count,
                    korean_missing,
                    homepage_url,
                    primary_source_url,
                ),
                "owner": owner,
                "integrated_action": action,
                "newsletter_context_action": newsletter_context_action(
                    people_count,
                    clean(raw.get("service_ready")),
                    clean(raw.get("latest_title")),
                ),
            }
        )

    rows.sort(key=priority_tuple)
    for index, row in enumerate(rows, start=1):
        row["service_rank"] = index
    return rows


def build(
    db_path: Path,
    news_worklist_path: Path,
    out_dir: Path,
    report_date: str,
    top_gp_limit: int,
    write_latest: bool = True,
) -> dict[str, object]:
    if not report_date:
        report_date = datetime.now().strftime("%Y-%m-%d")
    with sqlite3.connect(db_path) as conn:
        rows = merge_rows(conn, news_worklist_path, top_gp_limit)

    headers = [
        "service_rank",
        "row_source",
        "owner",
        "integrated_action",
        "newsletter_context_action",
        "source_gp_id",
        "standard_gp_name",
        "latest_primary_rank",
        "latest_primary_aum_억원",
        "latest_primary_active_fund_count",
        "article_count",
        "latest_article_at",
        "latest_publisher",
        "latest_title",
        "latest_url",
        "latest_comment",
        "news_action",
        "matched_aliases",
        "publishers",
        "service_ready",
        "identifier_complete",
        "profile_verification_level",
        "profile_status",
        "missing_service_fields",
        "missing_identifier_fields",
        "missing_optional_fields",
        "people_count",
        "korean_name_missing_count",
        "people_coverage_status",
        "people_next_action",
        "homepage_url",
        "primary_source_url",
    ]
    dated_path = out_dir / f"service_integration_worklist_{report_date.replace('-', '')}.csv"
    latest_path = out_dir / "service_integration_worklist_latest.csv"
    write_csv(dated_path, rows, headers)
    if write_latest:
        write_csv(latest_path, rows, headers)
    return {
        "report_date": report_date,
        "rows": len(rows),
        "dated_path": str(dated_path),
        "latest_path": str(latest_path),
        "news_rows": sum(1 for row in rows if row.get("row_source") == "news"),
        "people_db_rows": sum(1 for row in rows if row.get("owner") == "People DB"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build integrated Newsletter/People/GP operating worklist.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--news-worklist", type=Path, default=DEFAULT_NEWS_WORKLIST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--date", default="")
    parser.add_argument("--top-gp-limit", type=int, default=50)
    args = parser.parse_args()
    result = build(args.db, args.news_worklist, args.out_dir, args.date, args.top_gp_limit)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
