#!/usr/bin/env python
"""Build a user-facing operational status report for the PE DB workspace."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_EXPORTS = REPO_ROOT / "exports"
DEFAULT_DASHBOARD_JSON = REPO_ROOT / "dashboard" / "data" / "dashboard_data.json"
DEFAULT_NEWS_WORKLIST = REPO_ROOT / "exports" / "daily_news" / "news_gp_update_worklist_latest.csv"
DEFAULT_LOG_DIR = REPO_ROOT / "logs"
DEFAULT_OUT = REPO_ROOT / "exports" / "operational_status_latest.md"


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def scalar(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = (), default: object = "") -> object:
    row = conn.execute(query, params).fetchone()
    if row is None:
        return default
    return row[0]


def fetch_dicts(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
    cur = conn.execute(query, params)
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def latest_pipeline_manifest(log_dir: Path) -> dict[str, object]:
    if not log_dir.exists():
        return {}
    candidates = sorted(log_dir.glob("pipeline_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return {}
    try:
        payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(candidates[0]), "status": "unreadable"}
    payload["path"] = str(candidates[0])
    return payload


def dashboard_summary(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"exists": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"exists": True, "error": str(exc), "bytes": path.stat().st_size}
    return {
        "exists": True,
        "bytes": path.stat().st_size,
        "periods": len(payload.get("periods", [])),
        "funds": len(payload.get("funds", [])),
        "gp_rows": len(payload.get("gp_cumulative", [])),
        "aliases": len(payload.get("gp_aliases", {})),
    }


def format_count(value: object) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def format_krw_100mn(value: object) -> str:
    try:
        return f"{float(value):,.0f}억원"
    except (TypeError, ValueError):
        return str(value)


def format_file_size(bytes_value: object) -> str:
    try:
        size = float(bytes_value)
    except (TypeError, ValueError):
        return ""
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.1f}KB"
    return f"{int(size)}B"


def service_ready_expr() -> str:
    required = [
        "homepage_url",
        "legal_entity_name_ko",
        "representative_name",
        "headquarters_address",
        "established_date",
    ]
    return " AND ".join(f"NULLIF(TRIM(COALESCE({field}, '')), '') IS NOT NULL" for field in required)


def build_db_summary(conn: sqlite3.Connection) -> dict[str, object]:
    latest_period = conn.execute(
        """
        SELECT period_label, as_of_date, regime
        FROM reporting_period
        ORDER BY as_of_date DESC, period_id DESC
        LIMIT 1
        """
    ).fetchone()

    latest_period_label = latest_period[0] if latest_period else ""
    latest_period_date = latest_period[1] if latest_period else ""
    latest_regime = latest_period[2] if latest_period else ""

    summary: dict[str, object] = {
        "latest_period_label": latest_period_label,
        "latest_period_date": latest_period_date,
        "latest_regime": latest_regime,
        "period_count": scalar(conn, "SELECT COUNT(*) FROM reporting_period", default=0),
        "source_document_count": scalar(conn, "SELECT COUNT(*) FROM source_document", default=0),
        "fund_count": scalar(conn, "SELECT COUNT(*) FROM fund_master", default=0),
        "active_fund_count": scalar(conn, "SELECT COUNT(*) FROM fund_master WHERE active_in_latest_period = 1", default=0),
        "gp_profile_count": scalar(conn, "SELECT COUNT(*) FROM gp_profile", default=0),
        "active_gp_count": scalar(conn, "SELECT COUNT(*) FROM gp_profile WHERE active_in_latest_period = 1", default=0),
        "verified_gp_count": scalar(
            conn,
            "SELECT COUNT(*) FROM gp_profile WHERE COALESCE(verification_level, '') <> 'FSS_NAME_ONLY'",
            default=0,
        ),
        "identifier_gp_count": scalar(conn, "SELECT COUNT(DISTINCT source_gp_id) FROM gp_identifier", default=0),
        "evidence_count": scalar(conn, "SELECT COUNT(*) FROM gp_profile_source", default=0),
    }

    if table_exists(conn, "analytics_gp_period_aum") and latest_period_label:
        summary["latest_aum_proxy_krw_100mn"] = scalar(
            conn,
            """
            SELECT SUM(commitment_aum_proxy_trn_krw) * 10000.0
            FROM analytics_gp_period_aum
            WHERE period_label = ?
            """,
            (latest_period_label,),
            default=0,
        )
    else:
        summary["latest_aum_proxy_krw_100mn"] = 0

    if table_exists(conn, "analytics_new_funds_by_year"):
        latest_year = scalar(conn, "SELECT MAX(year) FROM analytics_new_funds_by_year", default="")
        summary["latest_new_fund_year"] = latest_year
        if latest_year != "":
            latest_year_rows = conn.execute(
                """
                SELECT new_fund_count, first_seen_commitment_trn_krw * 10000.0
                FROM analytics_new_funds_by_year
                WHERE year = ?
                """,
                (latest_year,),
            ).fetchone()
            if latest_year_rows:
                summary["latest_year_new_fund_count"] = latest_year_rows[0]
                summary["latest_year_new_commitment_krw_100mn"] = latest_year_rows[1]

    summary["service_ready_top50_count"] = scalar(
        conn,
        f"""
        SELECT COUNT(*)
        FROM gp_profile
        WHERE COALESCE(latest_primary_rank, 999999) BETWEEN 1 AND 50
          AND {service_ready_expr()}
        """,
        default=0,
    )
    return summary


def top_gp_rows(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, object]]:
    if not table_exists(conn, "analytics_gp_period_aum"):
        return []
    latest_period = scalar(
        conn,
        "SELECT period_label FROM reporting_period ORDER BY as_of_date DESC, period_id DESC LIMIT 1",
        default="",
    )
    if latest_period == "":
        return []
    return fetch_dicts(
        conn,
        """
        SELECT
            gp_name,
            active_fund_count,
            commitment_aum_proxy_trn_krw * 10000.0 AS aum_krw_100mn
        FROM analytics_gp_period_aum
        WHERE period_label = ?
        ORDER BY commitment_aum_proxy_trn_krw DESC, active_fund_count DESC, gp_name
        LIMIT ?
        """,
        (latest_period, limit),
    )


def build_report(args: argparse.Namespace) -> tuple[Path, Path]:
    generated_at = now_utc()
    conn = sqlite3.connect(args.db)
    try:
        db_summary = build_db_summary(conn)
        top_gps = top_gp_rows(conn, limit=10)
    finally:
        conn.close()

    dashboard = dashboard_summary(args.dashboard_json)
    news_rows = read_csv_rows(args.news_worklist)
    quality_gap_rows = read_csv_rows(args.exports / "db_quality_top_gp_gaps.csv")
    service_ready_rows = read_csv_rows(args.exports / "db_quality_service_ready_top50.csv")
    if service_ready_rows:
        db_summary["service_ready_top50_count"] = sum(1 for row in service_ready_rows if row.get("service_ready") == "Y")
        db_summary["service_ready_top50_total"] = len(service_ready_rows)
    else:
        db_summary["service_ready_top50_total"] = 50
    latest_manifest = latest_pipeline_manifest(args.log_dir)

    lines: list[str] = []
    lines.append("# Private Equity DB 운영 현황")
    lines.append("")
    lines.append(f"- 생성시각: {generated_at.isoformat()}")
    lines.append(f"- 최신 FSS 기준시점: {db_summary.get('latest_period_label', '')} / {db_summary.get('latest_period_date', '')}")
    lines.append(f"- 최신 파이프라인 상태: {latest_manifest.get('status', 'unknown')}")
    if latest_manifest.get("path"):
        lines.append(f"- 최신 파이프라인 로그: {latest_manifest.get('path')}")
    lines.append("")

    lines.append("## 지금 확보된 DB")
    lines.append("")
    lines.append("| 항목 | 값 |")
    lines.append("| --- | ---: |")
    lines.append(f"| FSS 기준시점 수 | {format_count(db_summary.get('period_count'))} |")
    lines.append(f"| FSS 원천문서 수 | {format_count(db_summary.get('source_document_count'))} |")
    lines.append(f"| 펀드 마스터 | {format_count(db_summary.get('fund_count'))} |")
    lines.append(f"| 최신시점 운용중 펀드 | {format_count(db_summary.get('active_fund_count'))} |")
    lines.append(f"| GP 프로필 | {format_count(db_summary.get('gp_profile_count'))} |")
    lines.append(f"| 최신시점 활동 GP | {format_count(db_summary.get('active_gp_count'))} |")
    lines.append(f"| 외부근거 보강 GP | {format_count(db_summary.get('verified_gp_count'))} |")
    lines.append(f"| 식별자 확보 GP | {format_count(db_summary.get('identifier_gp_count'))} |")
    lines.append(f"| GP 프로필 근거 레코드 | {format_count(db_summary.get('evidence_count'))} |")
    lines.append(f"| 최신시점 약정액 합계 프록시 | {format_krw_100mn(db_summary.get('latest_aum_proxy_krw_100mn'))} |")
    lines.append(
        f"| Top 50 서비스 가능 프로필 | "
        f"{format_count(db_summary.get('service_ready_top50_count'))} / "
        f"{format_count(db_summary.get('service_ready_top50_total'))} |"
    )
    lines.append("")

    lines.append("## 대시보드 상태")
    lines.append("")
    if dashboard.get("exists"):
        lines.append(f"- 데이터 파일: {args.dashboard_json}")
        lines.append(f"- 파일 크기: {format_file_size(dashboard.get('bytes'))}")
        if dashboard.get("error"):
            lines.append(f"- 상태: JSON 오류 - {dashboard.get('error')}")
        else:
            lines.append(
                "- 적재 데이터: "
                f"기준시점 {format_count(dashboard.get('periods'))}, "
                f"펀드 {format_count(dashboard.get('funds'))}, "
                f"GP {format_count(dashboard.get('gp_rows'))}, "
                f"검색 별칭 {format_count(dashboard.get('aliases'))}"
            )
            lines.append("- 실행: `open_dashboard.bat` 더블클릭")
    else:
        lines.append("- 상태: 대시보드 데이터 파일 없음")
    lines.append("")

    lines.append("## 최신시점 GP 약정액 상위 10")
    lines.append("")
    lines.append("| 순위 | GP | 운용중 펀드 | 약정액 프록시 |")
    lines.append("| ---: | --- | ---: | ---: |")
    for idx, row in enumerate(top_gps, start=1):
        lines.append(
            f"| {idx} | {row.get('gp_name', '')} | "
            f"{format_count(row.get('active_fund_count'))} | "
            f"{format_krw_100mn(row.get('aum_krw_100mn'))} |"
        )
    if not top_gps:
        lines.append("|  | 데이터 없음 |  |  |")
    lines.append("")

    lines.append("## 뉴스 기반 GP 업데이트 큐")
    lines.append("")
    lines.append(f"- 파일: {args.news_worklist}")
    lines.append(f"- 최근 뉴스로 업데이트 검토가 필요한 GP: {format_count(len(news_rows))}곳")
    if news_rows:
        lines.append("")
        lines.append("| 순위 | GP | 기사수 | 최근 매체 | 조치 |")
        lines.append("| ---: | --- | ---: | --- | --- |")
        for row in news_rows[:10]:
            lines.append(
                f"| {row.get('worklist_rank', '')} | {row.get('standard_gp_name', '')} | "
                f"{row.get('article_count', '')} | {row.get('latest_publisher', '')} | "
                f"{row.get('suggested_action', '')} |"
            )
    lines.append("")

    lines.append("## 남은 품질 이슈")
    lines.append("")
    lines.append(f"- Top GP 갭 행: {format_count(len(quality_gap_rows))}")
    lines.append(f"- Top 50 서비스 가능 점검 행: {format_count(len(service_ready_rows))}")
    lines.append("- 원칙: 비어 있는 값은 추정하지 않고, 공식/준공식 근거가 생길 때 `data/gp_profile_evidence.csv`에 추가")
    lines.append("")

    lines.append("## 다음 운영 방식")
    lines.append("")
    lines.append("1. FSS 새 분기 자료가 나오면 `python scripts/run_pipeline.py --with-fetch-sources --with-rebuild-db` 실행")
    lines.append("2. 평소에는 `python scripts/run_pipeline.py`로 파생 테이블, 대시보드, 품질표 갱신")
    lines.append("3. 뉴스 작업 후에는 `exports/daily_news/news_gp_update_worklist_latest.csv`를 보고 해당 GP만 보강")
    lines.append("4. 대시보드는 `open_dashboard.bat`로 열고, 화면 개선은 DB 구조를 유지한 채 별도 진행")
    lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines)
    args.out.write_text(content, encoding="utf-8")

    dated_out = args.out.with_name(f"operational_status_{generated_at.strftime('%Y%m%d_%H%M%S')}.md")
    dated_out.write_text(content, encoding="utf-8")
    return args.out, dated_out


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a user-facing operational status report")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--exports", type=Path, default=DEFAULT_EXPORTS)
    parser.add_argument("--dashboard-json", type=Path, default=DEFAULT_DASHBOARD_JSON)
    parser.add_argument("--news-worklist", type=Path, default=DEFAULT_NEWS_WORKLIST)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.db.exists():
        raise RuntimeError(f"DB file does not exist: {args.db}")

    latest_path, dated_path = build_report(args)
    print(f"latest_path={latest_path}")
    print(f"dated_path={dated_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
