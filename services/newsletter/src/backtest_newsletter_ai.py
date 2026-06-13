#!/usr/bin/env python3
"""Backtest newsletter AI enrichment over existing daily review queues."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from daily_news_common import DEFAULT_EXPORT_DIR, clean_investment_memo_summary_lines, today_seoul


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3]
ENRICH_SCRIPT = SCRIPT_PATH.with_name("enrich_daily_news_ai.py")
BACKTEST_DIRNAME = "ai_backtests"
EXTERNAL_PROVIDERS = {"notebooklm", "notebooklm-cli", "nlm", "command", "custom"}
NOTEBOOKLM_PROVIDERS = {"notebooklm", "notebooklm-cli", "nlm"}
PROJECT_NLM_BIN = REPO_ROOT / ".venv" / "bin" / "nlm"


def compact_date(value: str) -> str:
    return str(value or "").replace("-", "")


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_span(start_date: str, end_date: str) -> list[str]:
    start = parse_date(start_date)
    end = parse_date(end_date)
    if end < start:
        raise SystemExit(f"--end-date {end_date} is before --start-date {start_date}")
    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def default_date_span(days: int) -> list[str]:
    end = parse_date(today_seoul())
    start = end - timedelta(days=max(1, days) - 1)
    return date_span(start.isoformat(), end.isoformat())


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def provider_key(value: str) -> str:
    return str(value or "local").strip().lower()


def default_nlm_bin_for_project(provider: str, current: str = "") -> str:
    if current or provider_key(provider) not in NOTEBOOKLM_PROVIDERS:
        return current
    return str(PROJECT_NLM_BIN) if PROJECT_NLM_BIN.exists() and os.access(PROJECT_NLM_BIN, os.X_OK) else ""


def run_provider_check(args: argparse.Namespace) -> tuple[bool, str]:
    provider = provider_key(args.provider)
    if provider not in EXTERNAL_PROVIDERS:
        return True, "local provider does not require external preflight"
    command = [
        sys.executable,
        str(ENRICH_SCRIPT),
        "--provider",
        args.provider,
        "--check-only",
        "--timeout",
        str(args.timeout),
    ]
    if args.notebook_id:
        command.extend(["--notebook-id", args.notebook_id])
    if args.nlm_bin:
        command.extend(["--nlm-bin", args.nlm_bin])
    if args.nlm_profile:
        command.extend(["--nlm-profile", args.nlm_profile])
    if args.command:
        command.extend(["--command", args.command])
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    output = (completed.stdout + "\n" + completed.stderr).strip()
    return completed.returncode == 0, output


def run_enrichment_for_date(report_date: str, args: argparse.Namespace) -> tuple[bool, str]:
    command = [
        sys.executable,
        str(ENRICH_SCRIPT),
        "--date",
        report_date,
        "--provider",
        args.provider,
        "--out-dir",
        str(args.out_dir),
        "--timeout",
        str(args.timeout),
        "--no-latest",
    ]
    if args.notebook_id:
        command.extend(["--notebook-id", args.notebook_id])
    if args.nlm_bin:
        command.extend(["--nlm-bin", args.nlm_bin])
    if args.nlm_profile:
        command.extend(["--nlm-profile", args.nlm_profile])
    if args.command:
        command.extend(["--command", args.command])
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    output = (completed.stdout + "\n" + completed.stderr).strip()
    return completed.returncode == 0, output


def summarize_date(report_date: str, out_dir: Path, run_ok: bool = True, run_message: str = "") -> dict[str, Any]:
    dated = compact_date(report_date)
    review_rows = read_csv_rows(out_dir / f"daily_news_review_queue_{dated}.csv")
    payload = read_json(out_dir / f"daily_news_ai_enrichment_{dated}.json")
    articles = payload.get("articles") if isinstance(payload.get("articles"), list) else []
    audit_rows = read_csv_rows(out_dir / f"daily_news_ai_enrichment_audit_{dated}.csv")
    status_counts = Counter(row.get("status") or "unknown" for row in audit_rows)
    summary_missing = 0
    for article in articles:
        if not isinstance(article, dict):
            continue
        lines = clean_investment_memo_summary_lines(article.get("summary_lines") or article.get("summaryLines"), article.get("title", ""))
        if len(lines) < 1:
            summary_missing += 1
    conflicts = [
        {
            "report_date": report_date,
            "title": row.get("title", ""),
            "current_section": row.get("current_section", ""),
            "section_suggestion": row.get("section_suggestion", ""),
            "status": row.get("status", ""),
            "source_url": row.get("source_url", ""),
        }
        for row in audit_rows
        if row.get("status") in {"conflict", "invalid", "missing"}
    ]
    return {
        "report_date": report_date,
        "provider": payload.get("provider") or "",
        "run_ok": run_ok,
        "run_message": run_message,
        "review_count": len(review_rows),
        "article_count": len(articles),
        "status_ok": status_counts.get("ok", 0),
        "status_conflict": status_counts.get("conflict", 0),
        "status_invalid": status_counts.get("invalid", 0),
        "status_missing": status_counts.get("missing", 0),
        "summary_missing": summary_missing,
        "conflicts": conflicts,
    }


def write_report(
    rows: list[dict[str, Any]],
    out_dir: Path,
    start_date: str,
    end_date: str,
    provider: str,
    metadata: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    metadata = metadata or {}
    report_dir = out_dir / BACKTEST_DIRNAME
    report_dir.mkdir(parents=True, exist_ok=True)
    name = f"daily_news_ai_backtest_{compact_date(start_date)}_{compact_date(end_date)}_{provider_key(provider)}"
    csv_path = report_dir / f"{name}.csv"
    md_path = report_dir / f"{name}.md"
    headers = [
        "report_date",
        "provider",
        "run_ok",
        "review_count",
        "article_count",
        "status_ok",
        "status_conflict",
        "status_invalid",
        "status_missing",
        "summary_missing",
        "run_message",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})

    totals = Counter()
    all_conflicts: list[dict[str, str]] = []
    for row in rows:
        for key in ["review_count", "article_count", "status_ok", "status_conflict", "status_invalid", "status_missing", "summary_missing"]:
            totals[key] += int(row.get(key) or 0)
        all_conflicts.extend(row.get("conflicts") or [])

    lines = [
        f"# Daily News AI Backtest {start_date} ~ {end_date}",
        "",
        f"- provider: `{provider}`",
        f"- generated_at: `{datetime.utcnow().replace(microsecond=0).isoformat()}Z`",
        f"- preflight: `{metadata.get('preflight_status', 'not_run')}`",
        f"- preflight_message: `{metadata.get('preflight_message', '')}`",
        f"- nlm_bin: `{metadata.get('nlm_bin', '')}`",
        f"- nlm_profile: `{metadata.get('nlm_profile', '')}`",
        f"- notebook_id_set: `{metadata.get('notebook_id_set', 'false')}`",
        f"- ai_apply_sections: `{metadata.get('ai_apply_sections', '0')}`",
        f"- dates: {len(rows)}",
        f"- review rows: {totals['review_count']}",
        f"- AI articles: {totals['article_count']}",
        f"- ok / conflict / invalid / missing: {totals['status_ok']} / {totals['status_conflict']} / {totals['status_invalid']} / {totals['status_missing']}",
        f"- missing public summaries: {totals['summary_missing']}",
        "",
        "## Daily Summary",
        "",
        "| date | provider | review | articles | ok | conflict | invalid | missing | summary missing |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('report_date')} | {row.get('provider') or provider} | {row.get('review_count')} | {row.get('article_count')} | {row.get('status_ok')} | {row.get('status_conflict')} | {row.get('status_invalid')} | {row.get('status_missing')} | {row.get('summary_missing')} |"
        )
    lines.extend(["", "## Conflicts / Invalid / Missing", ""])
    if not all_conflicts:
        lines.append("- None")
    else:
        for item in all_conflicts[:100]:
            lines.append(
                f"- {item['report_date']} `{item['status']}` {item['current_section']} -> {item['section_suggestion']}: {item['title']}"
            )
        if len(all_conflicts) > 100:
            lines.append(f"- ... {len(all_conflicts) - 100} more")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    (report_dir / "daily_news_ai_backtest_latest.csv").write_text(csv_path.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    (report_dir / "daily_news_ai_backtest_latest.md").write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    return csv_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest newsletter AI enrichment over recent review queues")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--provider", default=os.environ.get("NEWSLETTER_AI_PROVIDER", "local"))
    parser.add_argument("--command", default=os.environ.get("NEWSLETTER_AI_COMMAND", ""))
    parser.add_argument("--notebook-id", default=os.environ.get("NEWSLETTER_NOTEBOOKLM_NOTEBOOK_ID", ""))
    parser.add_argument("--nlm-bin", default=os.environ.get("NEWSLETTER_NLM_BIN", ""))
    parser.add_argument("--nlm-profile", default=os.environ.get("NEWSLETTER_NLM_PROFILE", ""))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("NEWSLETTER_AI_TIMEOUT_SECONDS", "180")))
    parser.add_argument("--no-run", action="store_true", help="Only summarize existing enrichment files")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue dates even when enrichment fails")
    args = parser.parse_args()
    args.nlm_bin = default_nlm_bin_for_project(args.provider, args.nlm_bin)

    if args.start_date or args.end_date:
        if not args.start_date or not args.end_date:
            raise SystemExit("--start-date and --end-date must be provided together")
        dates = date_span(args.start_date, args.end_date)
    else:
        dates = default_date_span(args.days)
    available_dates = [
        report_date
        for report_date in dates
        if (args.out_dir / f"daily_news_review_queue_{compact_date(report_date)}.csv").exists()
    ]
    if not available_dates:
        raise SystemExit("No daily_news_review_queue files found for requested dates")

    if not args.no_run:
        ok, message = run_provider_check(args)
        print(f"ai_backtest_preflight={'ok' if ok else 'fail'} provider={args.provider} message={message}")
        if not ok:
            return 1
    else:
        ok, message = True, "not_run"

    rows: list[dict[str, Any]] = []
    had_failure = False
    for report_date in available_dates:
        run_ok = True
        run_message = ""
        if not args.no_run:
            run_ok, run_message = run_enrichment_for_date(report_date, args)
            print(f"ai_backtest_enrichment={'ok' if run_ok else 'fail'} date={report_date} message={run_message}")
            if not run_ok:
                had_failure = True
                if not args.continue_on_error:
                    rows.append(summarize_date(report_date, args.out_dir, run_ok=False, run_message=run_message))
                    break
        rows.append(summarize_date(report_date, args.out_dir, run_ok=run_ok, run_message=run_message))

    csv_path, md_path = write_report(
        rows,
        args.out_dir,
        available_dates[0],
        available_dates[-1],
        args.provider,
        {
            "preflight_status": "ok" if ok else "fail",
            "preflight_message": message,
            "nlm_bin": args.nlm_bin,
            "nlm_profile": args.nlm_profile,
            "notebook_id_set": "true" if bool(args.notebook_id) else "false",
            "ai_apply_sections": os.environ.get("NEWSLETTER_AI_APPLY_SECTIONS", "0"),
        },
    )
    print(f"ai_backtest_status={'failed' if had_failure else 'ok'} dates={len(rows)} csv={csv_path} md={md_path}")
    return 1 if had_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
