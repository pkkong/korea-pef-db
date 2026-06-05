#!/usr/bin/env python
"""Compare daily-news section/tag taxonomy before and after classifier changes."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from daily_news_common import write_csv_rows
from run_daily_news_pipeline import (
    SECTION_LABELS,
    has_aggregate_credit_market_signal,
    has_ai_signal,
    has_national_growth_fund_theme,
    has_title_transaction_signal,
    primary_section,
    refine_news_tags,
)


DEFAULT_OUT_DIR = Path("exports/daily_news")
REPORT_HEADERS = [
    "date",
    "publisher",
    "title",
    "url",
    "baseline_section",
    "new_section",
    "old_tags",
    "new_tags",
    "removed_tags",
    "added_tags",
    "change_reason",
]


def date_range(start: str, end: str) -> list[str]:
    start_date = datetime.strptime(start, "%Y-%m-%d").date()
    end_date = datetime.strptime(end, "%Y-%m-%d").date()
    days: list[str] = []
    current = start_date
    while current <= end_date:
        days.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return days


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def baseline_index(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    rows = read_csv(path)
    indexed: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row.get("date", ""), row.get("url", ""))
        if key[0] and key[1]:
            indexed[key] = row
    return indexed


def tag_dicts_from_row(row: dict[str, str]) -> list[dict[str, object]]:
    tags: list[dict[str, object]] = []
    for tag_type, field in [
        ("section", "section_tags"),
        ("section_override", "section_override_tags"),
        ("topic", "topic_tags"),
        ("document_type", "document_type_tags"),
    ]:
        for value in split_csv(row.get(field, "")):
            tags.append(
                {
                    "tag_type": tag_type,
                    "tag_value": value,
                    "tag_source": "backtest_existing",
                    "confidence": 0.8,
                }
            )
    return tags


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def split_entity_names(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;]", str(value or "")) if part.strip()]


def public_tag_set(value: str) -> list[str]:
    return [
        tag
        for tag in split_csv(value)
        if tag
        not in {
            "daily",
            "publisher_watch",
            "deal_watch",
            "gp_watch",
            "lp_watch",
            "allocator",
            "market_news",
            "private_credit",
            "portfolio",
            "fundraising",
            "people",
        }
    ]


def change_reason(row: dict[str, str], baseline_section: str, new_section: str, removed: list[str], added: list[str]) -> str:
    title = row.get("title", "")
    summary = row.get("summary_text", "")
    if baseline_section != new_section:
        if new_section == "Deal" and has_ai_signal(title) and has_title_transaction_signal(title):
            return "AI 키워드보다 실제 거래 이벤트를 우선"
        if new_section == "Market" and has_aggregate_credit_market_signal(f"{title} {summary}"):
            return "사모대출·크레딧 집계/규제 기사는 시장 섹션"
        if new_section == "NationalGrowthFund" and has_national_growth_fund_theme(title, []):
            return "국민성장펀드가 기사 주제이면 별도 섹션 우선"
        if new_section == "LP":
            return "출자·위탁운용사 선정 등 allocator 이벤트 우선"
        if new_section == "GP":
            return "운용사 펀드레이징·조직·전략 이벤트 우선"
        return "핵심 사건 기준 섹션 재판정"
    if removed:
        if "LP" in removed and new_section == "Market":
            return "시장 기사에서 LP 보조 태그 제거"
        if any(tag in removed for tag in ["daily", "publisher_watch", "deal_watch", "gp_watch", "lp_watch", "allocator"]):
            return "운영용 태그 제거"
        if "GP" in removed:
            return "운용사가 핵심 주체가 아닌 GP 태그 제거"
    if added:
        return "섹션과 일치하는 공개 태그 보강"
    return ""


def build_comparison(start: str, end: str, out_dir: Path, baseline_path: Path) -> tuple[list[dict[str, str]], dict[str, object]]:
    baseline = baseline_index(baseline_path)
    comparisons: list[dict[str, str]] = []
    missing_dates: list[str] = []
    for key in date_range(start, end):
        report_date = f"{key[:4]}-{key[4:6]}-{key[6:]}"
        path = out_dir / f"daily_news_review_queue_{key}.csv"
        rows = read_csv(path)
        if not rows:
            missing_dates.append(report_date)
            continue
        for row in rows:
            url = row.get("normalized_source_url") or row.get("source_url", "")
            base = baseline.get((report_date, url), {})
            baseline_section = base.get("baseline_section", "") or primary_section(row)
            new_section = primary_section(row)
            old_tags = public_tag_set(row.get("topic_tags", ""))
            gp_names = split_entity_names(row.get("gp_names", ""))
            refined = refine_news_tags(tag_dicts_from_row(row), row.get("title", ""), row.get("summary_text", ""), gp_names)
            new_tags = [
                str(tag.get("tag_value") or "")
                for tag in refined
                if str(tag.get("tag_type") or "") == "topic"
            ]
            removed = [tag for tag in old_tags if tag not in new_tags]
            added = [tag for tag in new_tags if tag not in old_tags]
            if baseline_section == new_section and not removed and not added:
                continue
            reason = change_reason(row, baseline_section, new_section, removed, added)
            comparisons.append(
                {
                    "date": report_date,
                    "publisher": row.get("publisher", ""),
                    "title": row.get("title", ""),
                    "url": url,
                    "baseline_section": SECTION_LABELS.get(baseline_section, baseline_section),
                    "new_section": SECTION_LABELS.get(new_section, new_section),
                    "old_tags": ", ".join(old_tags),
                    "new_tags": ", ".join(new_tags),
                    "removed_tags": ", ".join(removed),
                    "added_tags": ", ".join(added),
                    "change_reason": reason,
                }
            )
    stats = {
        "missing_dates": missing_dates,
        "changed_count": len(comparisons),
        "section_changes": sum(1 for row in comparisons if row["baseline_section"] != row["new_section"]),
        "tag_only_changes": sum(1 for row in comparisons if row["baseline_section"] == row["new_section"]),
        "by_date": Counter(row["date"] for row in comparisons),
        "by_reason": Counter(row["change_reason"] for row in comparisons if row["change_reason"]),
    }
    return comparisons, stats


def write_markdown(path: Path, rows: list[dict[str, str]], stats: dict[str, object], limit: int) -> None:
    lines: list[str] = []
    lines.append("# 뉴스레터 분류·태그 백테스트")
    lines.append("")
    lines.append(f"- 변경 기사 수: {stats['changed_count']}")
    lines.append(f"- 섹션 변경: {stats['section_changes']}")
    lines.append(f"- 태그만 변경: {stats['tag_only_changes']}")
    if stats["missing_dates"]:
        lines.append(f"- 산출물 없는 날짜: {', '.join(stats['missing_dates'])}")
    lines.append("")
    lines.append("## 날짜별 변경")
    lines.append("")
    lines.append("| 날짜 | 변경 건수 |")
    lines.append("|---|---:|")
    for date, count in sorted(stats["by_date"].items()):
        lines.append(f"| {date} | {count} |")
    lines.append("")
    lines.append("## 변경 사유")
    lines.append("")
    lines.append("| 사유 | 건수 |")
    lines.append("|---|---:|")
    for reason, count in stats["by_reason"].most_common():
        lines.append(f"| {reason} | {count} |")
    lines.append("")
    lines.append("## 비교표")
    lines.append("")
    lines.append("| 날짜 | 제목 | 기존 | 개선 후 | 기존 태그 | 개선 태그 | 사유 |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in rows[:limit]:
        title = row["title"].replace("|", " ")
        lines.append(
            "| {date} | {title} | {old} | {new} | {old_tags} | {new_tags} | {reason} |".format(
                date=row["date"],
                title=title[:70],
                old=row["baseline_section"],
                new=row["new_section"],
                old_tags=row["old_tags"].replace("|", " "),
                new_tags=row["new_tags"].replace("|", " "),
                reason=row["change_reason"].replace("|", " "),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest daily-news section/tag taxonomy.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--csv-out", type=Path, required=True)
    parser.add_argument("--md-out", type=Path, required=True)
    parser.add_argument("--md-limit", type=int, default=80)
    args = parser.parse_args()
    rows, stats = build_comparison(args.start, args.end, args.out_dir, args.baseline)
    write_csv_rows(args.csv_out, rows, REPORT_HEADERS)
    write_markdown(args.md_out, rows, stats, args.md_limit)
    print(f"comparison_rows={len(rows)}")
    print(f"section_changes={stats['section_changes']}")
    print(f"tag_only_changes={stats['tag_only_changes']}")
    print(f"csv={args.csv_out}")
    print(f"md={args.md_out}")


if __name__ == "__main__":
    main()
