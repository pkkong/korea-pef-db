#!/usr/bin/env python
"""Build a source coverage audit for the daily newsletter desk."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
from collections import Counter
from pathlib import Path

from daily_news_common import DEFAULT_DB, DEFAULT_EXPORT_DIR, DEFAULT_SOURCES, today_seoul


DEFAULT_CORE_PUBLISHERS = [
    "더벨",
    "딜사이트",
    "인베스트조선",
    "블로터",
    "이데일리",
    "뉴스토마토",
    "뉴스톱",
]


def read_csv_counts(path: Path, key: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not path.exists():
        return counts
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            value = str(row.get(key) or "").strip()
            if value:
                counts[value] += 1
    return counts


def read_brief_source_counts(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not path.exists():
        return counts
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("출처:"):
            publisher = line.replace("출처:", "", 1).strip()
            if publisher:
                counts[publisher] += 1
    return counts


def write_csv(path: Path, rows: list[dict[str, object]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})


def fetch_latest_run(conn: sqlite3.Connection, report_date: str) -> sqlite3.Row | None:
    cursor = conn.execute(
        """
        SELECT run_id, run_date, started_at, ended_at, status,
               discovered_count, fetched_count, inserted_count, relevant_count, notes
        FROM news_run
        WHERE run_date = ?
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (report_date,),
    )
    return cursor.fetchone()


def publisher_document_counts(conn: sqlite3.Connection, run_id: str) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(TRIM(publisher), ''), '출처 미확인') AS publisher,
            COUNT(*) AS fetched_docs,
            SUM(CASE WHEN is_pe_relevant = 1 THEN 1 ELSE 0 END) AS relevant_docs,
            MAX(COALESCE(published_at, discovered_at)) AS latest_at,
            GROUP_CONCAT(DISTINCT source_code) AS source_codes
        FROM news_document
        WHERE run_id = ?
        GROUP BY COALESCE(NULLIF(TRIM(publisher), ''), '출처 미확인')
        """,
        (run_id,),
    ).fetchall()
    return {
        str(row["publisher"]): {
            "fetched_docs": int(row["fetched_docs"] or 0),
            "relevant_docs": int(row["relevant_docs"] or 0),
            "latest_at": row["latest_at"] or "",
            "source_codes": row["source_codes"] or "",
        }
        for row in rows
    }


def source_document_counts(conn: sqlite3.Connection, run_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            ns.source_code,
            ns.source_name,
            ns.source_kind,
            ns.publisher,
            ns.allowed_publishers,
            ns.is_active,
            COUNT(nd.news_id) AS fetched_docs,
            SUM(CASE WHEN nd.is_pe_relevant = 1 THEN 1 ELSE 0 END) AS relevant_docs
        FROM news_source ns
        LEFT JOIN news_document nd
            ON nd.source_code = ns.source_code
           AND nd.run_id = ?
        WHERE ns.is_active = 1
        GROUP BY ns.source_code, ns.source_name, ns.source_kind, ns.publisher,
                 ns.allowed_publishers, ns.is_active
        ORDER BY ns.source_code
        """,
        (run_id,),
    ).fetchall()
    return [
        {
            "source_code": row["source_code"],
            "source_name": row["source_name"],
            "source_kind": row["source_kind"],
            "publisher": row["publisher"] or "",
            "allowed_publishers": row["allowed_publishers"] or "",
            "discovered_count": "",
            "candidate_count": "",
            "fetched_docs": int(row["fetched_docs"] or 0),
            "cached_count": "",
            "relevant_docs": int(row["relevant_docs"] or 0),
            "warning_count": "",
            "status": "ok" if int(row["fetched_docs"] or 0) else "watch",
        }
        for row in rows
    ]


def source_stats_rows(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    stats = payload.get("source_stats", {})
    rows: list[dict[str, object]] = []
    for source_code, item in sorted(stats.items()):
        discovered = int(item.get("discovered_count") or 0)
        candidate = int(item.get("candidate_count") or 0)
        fetched = int(item.get("fetched_count") or 0)
        cached = int(item.get("cached_count") or 0)
        relevant = int(item.get("relevant_count") or 0)
        warnings = int(item.get("warning_count") or 0)
        if warnings and not fetched and not cached:
            status = "error"
        elif fetched or cached:
            status = "ok"
        elif discovered:
            status = "no_candidate"
        else:
            status = "no_matches"
        rows.append(
            {
                "source_code": source_code,
                "source_name": item.get("source_name", ""),
                "source_kind": "",
                "publisher": "",
                "allowed_publishers": "",
                "discovered_count": discovered,
                "candidate_count": candidate,
                "fetched_docs": fetched,
                "cached_count": cached,
                "relevant_docs": relevant,
                "warning_count": warnings,
                "status": status,
            }
        )
    return rows


def configured_publishers(sources_path: Path) -> set[str]:
    names: set[str] = set()
    if not sources_path.exists():
        return names
    with sources_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            for field in ["publisher", "allowed_publishers"]:
                for value in str(row.get(field) or "").split(";"):
                    value = value.strip()
                    if value and value not in {"Google News", "Naver News API"}:
                        names.add(value)
    return names


def build(args: argparse.Namespace) -> dict[str, Path]:
    report_date = args.date or today_seoul()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    dated = report_date.replace("-", "")
    review_path = out_dir / f"daily_news_review_queue_{dated}.csv"
    brief_path = out_dir / f"daily_news_brief_{dated}.md"

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        run = fetch_latest_run(conn, report_date)
        if run is None:
            raise SystemExit(f"No news_run found for {report_date}")

        doc_counts = publisher_document_counts(conn, str(run["run_id"]))
        review_counts = read_csv_counts(review_path, "publisher")
        brief_counts = read_brief_source_counts(brief_path)
        configured = configured_publishers(args.sources)
        publishers = sorted(set(doc_counts) | set(review_counts) | set(brief_counts) | set(args.core_publishers))

        publisher_rows: list[dict[str, object]] = []
        for publisher in publishers:
            docs = doc_counts.get(publisher, {})
            fetched = int(docs.get("fetched_docs", 0) or 0)
            relevant = int(docs.get("relevant_docs", 0) or 0)
            review = int(review_counts.get(publisher, 0))
            brief = int(brief_counts.get(publisher, 0))
            if brief:
                status = "briefed"
            elif review:
                status = "review_only"
            elif fetched:
                status = "fetched_only"
            elif publisher in args.core_publishers:
                status = "missing_core"
            else:
                status = "missing"
            publisher_rows.append(
                {
                    "publisher": publisher,
                    "configured": "Y" if publisher in configured else "",
                    "core": "Y" if publisher in args.core_publishers else "",
                    "fetched_docs": fetched,
                    "relevant_docs": relevant,
                    "review_queue_docs": review,
                    "brief_docs": brief,
                    "latest_at": docs.get("latest_at", ""),
                    "source_codes": docs.get("source_codes", ""),
                    "status": status,
                }
            )

        stats_path = out_dir / f"daily_news_source_stats_{dated}.json"
        source_rows = source_stats_rows(stats_path) or source_document_counts(conn, str(run["run_id"]))
    finally:
        conn.close()

    publisher_headers = [
        "publisher",
        "configured",
        "core",
        "fetched_docs",
        "relevant_docs",
        "review_queue_docs",
        "brief_docs",
        "latest_at",
        "source_codes",
        "status",
    ]
    source_headers = [
        "source_code",
        "source_name",
        "source_kind",
        "publisher",
        "allowed_publishers",
        "discovered_count",
        "candidate_count",
        "fetched_docs",
        "cached_count",
        "relevant_docs",
        "warning_count",
        "status",
    ]
    publisher_csv = out_dir / f"newsletter_source_audit_{dated}.csv"
    source_csv = out_dir / f"newsletter_source_audit_sources_{dated}.csv"
    write_csv(publisher_csv, publisher_rows, publisher_headers)
    write_csv(source_csv, source_rows, source_headers)

    core_rows = [row for row in publisher_rows if row["core"] == "Y"]
    missing_core = [str(row["publisher"]) for row in core_rows if row["status"] == "missing_core"]
    watch_sources = [row for row in source_rows if row["status"] in {"error", "no_matches", "watch"}]
    md_path = out_dir / f"newsletter_source_audit_{dated}.md"
    lines = [
        f"# 뉴스레터 소스 감사 - {report_date}",
        "",
        f"- run_id: `{run['run_id']}`",
        f"- 상태: {run['status']}",
        f"- 발견/수집/관련/브리프: {run['discovered_count']} / {run['fetched_count']} / {run['relevant_count']} / {sum(int(row['brief_docs']) for row in publisher_rows)}",
        f"- 핵심 매체 미수집: {', '.join(missing_core) if missing_core else '없음'}",
        f"- 실행 기준 수집 0건 소스: {len(watch_sources)}개",
        "",
        "## 핵심 매체",
        "",
        "| 매체 | 수집 | 리뷰큐 | 브리프 | 상태 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in core_rows:
        lines.append(
            f"| {row['publisher']} | {row['fetched_docs']} | {row['review_queue_docs']} | {row['brief_docs']} | {row['status']} |"
        )
    lines.extend(
        [
            "",
            "## 운영 메모",
            "",
            "- `missing_core`는 오늘 기준 핵심 매체 기사 후보가 DB에 한 건도 들어오지 않은 상태다.",
            "- `review_only`는 후보/리뷰에는 들어왔지만 최종 브리프에는 빠진 상태다.",
            "- `fetched_only`는 수집은 됐지만 관련도/품질 기준을 통과하지 못한 상태다.",
            "- 공개 뉴스 카드에는 운영용 태그 대신 확정 GP 1개와 추가 개수만 표시한다.",
            "",
            f"- 상세 CSV: `{publisher_csv.name}`",
            f"- 소스별 CSV: `{source_csv.name}`",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    latest_md = out_dir / "newsletter_source_audit_latest.md"
    latest_csv = out_dir / "newsletter_source_audit_latest.csv"
    latest_source_csv = out_dir / "newsletter_source_audit_sources_latest.csv"
    shutil.copyfile(md_path, latest_md)
    shutil.copyfile(publisher_csv, latest_csv)
    shutil.copyfile(source_csv, latest_source_csv)

    return {
        "markdown_path": md_path,
        "latest_markdown_path": latest_md,
        "publisher_csv_path": publisher_csv,
        "source_csv_path": source_csv,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the daily newsletter source coverage audit")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--date", default=today_seoul())
    parser.add_argument("--core-publishers", default=";".join(DEFAULT_CORE_PUBLISHERS))
    args = parser.parse_args()
    args.core_publishers = [part.strip() for part in str(args.core_publishers).split(";") if part.strip()]
    result = build(args)
    print(f"wrote {result['latest_markdown_path']}")
    print(f"publisher_csv={result['publisher_csv_path']}")
    print(f"source_csv={result['source_csv_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
