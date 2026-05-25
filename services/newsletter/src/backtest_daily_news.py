#!/usr/bin/env python
"""Run daily news clipping backtests over a date range."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from shutil import copy2

from daily_news_common import DEFAULT_DB
from run_daily_news_pipeline import SECTION_LABELS, SECTION_ORDER, primary_section


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "exports" / "daily_news"
DEFAULT_BACKTEST_ROOT = DEFAULT_OUT_DIR / "backtests"
BACKTEST_SOURCE_CODES = [
    "google_pef_market",
    "google_pef_deal",
    "google_pef_gp",
    "google_pef_lp",
    "google_pef_portfolio",
    "google_pef_regulation",
]
DISPLAY_SECTION_ORDER = [SECTION_LABELS[section] for section in SECTION_ORDER]


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest daily PEF news clipping")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--limit-per-source", type=int, default=10)
    parser.add_argument("--brief-limit", type=int, default=60)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_BACKTEST_ROOT)
    parser.add_argument("--db-source", type=Path, default=DEFAULT_DB)
    parser.add_argument("--allow-insecure-ssl", action="store_true")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    if end_date < start_date:
        raise SystemExit("--end must be on or after --start")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    range_slug = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}_{timestamp}"
    backtest_dir = args.out_root / range_slug
    export_dir = backtest_dir / "exports"
    raw_dir = backtest_dir / "raw"
    db_path = backtest_dir / "backtest.db"
    export_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    if args.db_source.exists():
        copy2(args.db_source, db_path)

    results: list[dict[str, object]] = []
    current = start_date
    while current <= end_date:
        report_date = current.isoformat()
        command = [
            sys.executable,
            str(SERVICE_ROOT / "src" / "run_daily_news_pipeline.py"),
            "--date",
            report_date,
            "--limit-per-source",
            str(args.limit_per_source),
            "--brief-limit",
            str(args.brief_limit),
            "--db",
            str(db_path),
            "--raw-dir",
            str(raw_dir),
            "--out-dir",
            str(export_dir),
            "--google-date-window",
            "--no-latest",
            "--source-code",
            ",".join(BACKTEST_SOURCE_CODES),
        ]
        if args.allow_insecure_ssl:
            command.append("--allow-insecure-ssl")
        completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
        if completed.returncode != 0:
            print(completed.stdout)
            print(completed.stderr, file=sys.stderr)
            raise SystemExit(completed.returncode)
        payload = json.loads(completed.stdout)
        if (
            int(payload.get("warning_count", 0) or 0) > 0
            and int(payload.get("discovered_count", 0) or 0) == 0
            and int(payload.get("fetched_count", 0) or 0) == 0
        ):
            print(completed.stderr, file=sys.stderr)
            raise SystemExit(
                "Backtest discovered no items and only produced source warnings. "
                "Network access or source availability is likely broken."
            )
        sections = section_counts(export_dir / f"daily_news_review_queue_{report_date.replace('-', '')}.csv")
        results.append(
            {
                "date": report_date,
                "discovered_count": payload.get("discovered_count", 0),
                "fetched_count": payload.get("fetched_count", 0),
                "brief_count": payload.get("brief_count", 0),
                "warning_count": payload.get("warning_count", 0),
                "sections": sections,
                "markdown_path": payload.get("markdown_path", ""),
            }
        )
        current += timedelta(days=1)

    summary_path = backtest_dir / f"backtest_summary_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.md"
    summary_text = render_summary(results, backtest_dir)
    summary_path.write_text(summary_text, encoding="utf-8")
    latest_summary_path = args.out_root / "backtest_latest.md"
    latest_summary_path.write_text(summary_text, encoding="utf-8")
    print(
        json.dumps(
            {
                "backtest_dir": str(backtest_dir),
                "summary_path": str(summary_path),
                "latest_summary_path": str(latest_summary_path),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def section_counts(csv_path: Path) -> dict[str, int]:
    counts = {label: 0 for label in DISPLAY_SECTION_ORDER}
    if not csv_path.exists():
        return counts
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            section = classify_section(row)
            if section in counts:
                counts[section] += 1
    return {key: value for key, value in counts.items() if value}


def classify_section(row: dict[str, str]) -> str:
    section = primary_section(row)
    return SECTION_LABELS.get(section, section)


def render_summary(results: list[dict[str, object]], backtest_dir: Path) -> str:
    lines = [
        "# Daily PEF Clipping Backtest",
        "",
        f"- Backtest directory: `{backtest_dir}`",
        "- Output is isolated from the live daily clipping files.",
        "",
        "| Date | Discovered | Fetched | Selected | Warnings | Sections |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in results:
        sections = row.get("sections", {})
        section_text = ", ".join(f"{key} {value}" for key, value in sections.items()) if isinstance(sections, dict) else ""
        lines.append(
            "| {date} | {discovered_count} | {fetched_count} | {brief_count} | {warning_count} | {sections} |".format(
                date=row.get("date", ""),
                discovered_count=row.get("discovered_count", 0),
                fetched_count=row.get("fetched_count", 0),
                brief_count=row.get("brief_count", 0),
                warning_count=row.get("warning_count", 0),
                sections=section_text,
            )
        )
    total_selected = sum(int(row.get("brief_count", 0) or 0) for row in results)
    avg_selected = total_selected / len(results) if results else 0
    lines.extend(
        [
            "",
            f"- Total selected clips: {total_selected}",
            f"- Average selected clips per day: {avg_selected:.1f}",
            "",
            "## Files",
        ]
    )
    for row in results:
        lines.append(f"- {row.get('date')}: {row.get('markdown_path')}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
