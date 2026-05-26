#!/usr/bin/env python
"""Build a prioritized LP profile research backlog from the local database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.newsletter.src.daily_news_common import today_seoul, write_csv_rows  # noqa: E402


DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_OUT_DIR = REPO_ROOT / "exports"
TARGET_SECTIONS = (
    "general",
    "investment_status",
    "investment_org",
    "public_people",
    "notice_history",
    "data_gap",
)
SECTION_LABELS = {
    "general": "일반현황",
    "investment_status": "투자현황",
    "investment_org": "투자 관련 조직",
    "public_people": "공개 담당자/임원",
    "notice_history": "과거 출자공고",
    "data_gap": "공개자료 한계",
}


def db_object_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def fetch_dicts(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
    cursor = conn.execute(query, params)
    headers = [desc[0] for desc in cursor.description]
    return [dict(zip(headers, row)) for row in cursor.fetchall()]


def fetch_profile_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if db_object_exists(conn, "v_lp_profile_summary"):
        return fetch_dicts(
            conn,
            """
            SELECT
                lp_code,
                lp_name,
                lp_name_en,
                lp_type,
                ownership_type,
                homepage_url,
                notice_url,
                default_team,
                focus_asset_classes,
                service_priority,
                notice_count,
                allocation_amount_krw_100mn,
                latest_event_date,
                fact_count,
                source_count
            FROM v_lp_profile_summary
            ORDER BY service_priority DESC, lp_name
            """,
        )
    if not db_object_exists(conn, "lp_institution"):
        return []
    return fetch_dicts(
        conn,
        """
        SELECT
            li.lp_code,
            li.lp_name,
            li.lp_name_en,
            li.lp_type,
            li.ownership_type,
            li.homepage_url,
            li.notice_url,
            li.default_team,
            li.focus_asset_classes,
            li.service_priority,
            0 AS notice_count,
            0 AS allocation_amount_krw_100mn,
            '' AS latest_event_date,
            COALESCE(facts.fact_count, 0) AS fact_count,
            COALESCE(facts.source_count, 0) AS source_count
        FROM lp_institution li
        LEFT JOIN (
            SELECT
                lp_code,
                COUNT(*) AS fact_count,
                COUNT(DISTINCT NULLIF(source_url, '')) AS source_count
            FROM lp_profile_fact
            WHERE public_visible = 1
            GROUP BY lp_code
        ) facts
          ON facts.lp_code = li.lp_code
        ORDER BY li.service_priority DESC, li.lp_name
        """,
    )


def fetch_section_map(conn: sqlite3.Connection) -> dict[str, set[str]]:
    if not db_object_exists(conn, "lp_profile_fact"):
        return {}
    rows = fetch_dicts(
        conn,
        """
        SELECT lp_code, section
        FROM lp_profile_fact
        WHERE public_visible = 1
        GROUP BY lp_code, section
        """,
    )
    sections: dict[str, set[str]] = {}
    for row in rows:
        lp_code = str(row.get("lp_code") or "")
        section = str(row.get("section") or "")
        if lp_code and section:
            sections.setdefault(lp_code, set()).add(section)
    return sections


def fetch_active_source_counts(conn: sqlite3.Connection) -> dict[str, int]:
    if not db_object_exists(conn, "lp_commitment_source"):
        return {}
    rows = fetch_dicts(
        conn,
        """
        SELECT COALESCE(lp_code, '') AS lp_code, COUNT(*) AS source_count
        FROM lp_commitment_source
        WHERE is_active = 1
        GROUP BY COALESCE(lp_code, '')
        """,
    )
    return {str(row.get("lp_code") or ""): int(row.get("source_count") or 0) for row in rows}


def profile_status(fact_count: int, notice_count: int, missing_sections: list[str]) -> str:
    if fact_count >= 10 and notice_count > 0 and len(missing_sections) <= 2:
        return "profile_ready"
    if fact_count > 0:
        return "profile_gap"
    if notice_count > 0:
        return "notice_only"
    return "seed_only"


def next_action(status: str, missing_sections: list[str], active_source_count: int) -> str:
    labels = [SECTION_LABELS.get(section, section) for section in missing_sections[:3]]
    if status == "seed_only":
        return "공식 홈페이지, 경영공시, 조직도, 공지사항에서 기본 프로필 팩트와 공고 소스를 확보"
    if status == "notice_only":
        return "공고 데이터는 있으므로 " + ", ".join(labels or ["일반현황"]) + " 팩트를 공식 출처로 보강"
    if active_source_count == 0:
        return "공식 공고 채널 URL과 파서 적용 가능 여부를 먼저 확인"
    if missing_sections:
        return ", ".join(labels) + " 섹션을 공식 출처로 보강"
    return "기존 팩트 최신성, 선정 GP 히스토리, 뉴스 연결 품질을 점검"


def build_research_query(row: dict[str, object], missing_sections: list[str]) -> str:
    lp_name = str(row.get("lp_name") or "")
    aliases = [lp_name, str(row.get("lp_name_en") or ""), str(row.get("default_team") or "")]
    section_terms = {
        "general": "일반현황 설립 회원 자산",
        "investment_status": "자산운용 현황 대체투자 투자자산",
        "investment_org": "조직도 대체투자 기업투자",
        "public_people": "이사장 CIO 기금운용이사 임원",
        "notice_history": "출자공고 위탁운용사 선정",
        "data_gap": "공개자료 경영공시",
    }
    terms = " ".join(section_terms.get(section, section) for section in missing_sections[:3])
    return " ".join(part for part in aliases + [terms] if part).strip()


def build_backlog(db_path: Path, out_dir: Path, report_date: str) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        profile_rows = fetch_profile_rows(conn)
        section_map = fetch_section_map(conn)
        active_source_counts = fetch_active_source_counts(conn)
    finally:
        conn.close()

    backlog_rows: list[dict[str, object]] = []
    for row in profile_rows:
        lp_code = str(row.get("lp_code") or "")
        fact_count = int(row.get("fact_count") or 0)
        notice_count = int(row.get("notice_count") or 0)
        active_source_count = active_source_counts.get(lp_code, 0)
        existing_sections = section_map.get(lp_code, set())
        missing_sections = [section for section in TARGET_SECTIONS if section not in existing_sections]
        status = profile_status(fact_count, notice_count, missing_sections)
        priority_score = (
            int(row.get("service_priority") or 0)
            + (40 if fact_count == 0 else 0)
            + (15 if notice_count == 0 else 0)
            + (12 if active_source_count == 0 else 0)
            + len(missing_sections) * 3
        )
        backlog_rows.append(
            {
                "report_date": report_date,
                "priority_score": priority_score,
                "profile_status": status,
                "lp_code": lp_code,
                "lp_name": row.get("lp_name") or "",
                "lp_type": row.get("lp_type") or "",
                "ownership_type": row.get("ownership_type") or "",
                "default_team": row.get("default_team") or "",
                "focus_asset_classes": row.get("focus_asset_classes") or "",
                "fact_count": fact_count,
                "notice_count": notice_count,
                "active_source_count": active_source_count,
                "source_count": int(row.get("source_count") or 0),
                "latest_event_date": row.get("latest_event_date") or "",
                "missing_sections": ";".join(missing_sections),
                "missing_section_labels": ";".join(SECTION_LABELS.get(section, section) for section in missing_sections),
                "next_action": next_action(status, missing_sections, active_source_count),
                "research_query_ko": build_research_query(row, missing_sections),
                "homepage_url": row.get("homepage_url") or "",
                "notice_url": row.get("notice_url") or "",
            }
        )
    backlog_rows.sort(
        key=lambda item: (
            -int(item.get("priority_score") or 0),
            str(item.get("profile_status") or ""),
            str(item.get("lp_name") or ""),
        )
    )

    headers = [
        "report_date",
        "priority_score",
        "profile_status",
        "lp_code",
        "lp_name",
        "lp_type",
        "ownership_type",
        "default_team",
        "focus_asset_classes",
        "fact_count",
        "notice_count",
        "active_source_count",
        "source_count",
        "latest_event_date",
        "missing_sections",
        "missing_section_labels",
        "next_action",
        "research_query_ko",
        "homepage_url",
        "notice_url",
    ]
    dated_csv = out_dir / f"lp_profile_backlog_{report_date.replace('-', '')}.csv"
    latest_csv = out_dir / "lp_profile_backlog_latest.csv"
    write_csv_rows(dated_csv, backlog_rows, headers)
    write_csv_rows(latest_csv, backlog_rows, headers)

    summary = {
        "report_date": report_date,
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "lp_count": len(backlog_rows),
        "ready_count": len([row for row in backlog_rows if row["profile_status"] == "profile_ready"]),
        "gap_count": len([row for row in backlog_rows if row["profile_status"] != "profile_ready"]),
        "zero_fact_count": len([row for row in backlog_rows if int(row["fact_count"]) == 0]),
        "dated_csv": str(dated_csv),
        "latest_csv": str(latest_csv),
    }
    latest_json = out_dir / "lp_profile_backlog_latest.json"
    latest_json.write_text(json.dumps({"summary": summary, "items": backlog_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["latest_json"] = str(latest_json)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LP profile research backlog")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--date", default=today_seoul())
    args = parser.parse_args()
    result = build_backlog(args.db, args.out_dir, args.date)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
