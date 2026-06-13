#!/usr/bin/env python3
"""Write a daily newsletter operations status report.

This report answers the operational question first: did collection happen, did
the site build, and is the public URL serving today's newsletter?
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from daily_news_common import DEFAULT_EXPORT_DIR, today_seoul


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
DEFAULT_SITE_DIR = SERVICE_ROOT / "deploy" / "site"
DEFAULT_PUBLIC_BASE_URL = "https://pkkong.github.io/kpef-newsletter"
DEFAULT_OUT_DIR = DEFAULT_EXPORT_DIR / "ops_status"


def compact_date(report_date: str) -> str:
    return report_date.replace("-", "")


def read_json(path: Path) -> tuple[object | None, str]:
    if not path.exists():
        return None, f"missing file: {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"invalid json: {path}: {exc}"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def archive_entry(archive: object, report_date: str) -> dict[str, object] | None:
    if not isinstance(archive, list):
        return None
    for row in archive:
        if isinstance(row, dict) and row.get("reportDate") == report_date:
            return row
    return None


def fetch_json(url: str, timeout: int) -> tuple[object | None, str]:
    request = Request(url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), ""
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, str(exc)


def section_counts_from_review(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        if row.get("include_in_brief", "").upper() != "Y":
            continue
        section = row.get("current_category") or row.get("category") or "Unknown"
        counts[section] += 1
    return dict(sorted(counts.items()))


def section_counts_from_archive(entry: dict[str, object] | None) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if not entry:
        return {}
    for article in entry.get("articles") or []:
        if isinstance(article, dict):
            counts[str(article.get("section") or "Unknown")] += 1
    return dict(sorted(counts.items()))


def detect_tag_conflicts(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for row in rows:
        if row.get("include_in_brief", "").upper() != "Y":
            continue
        current = (row.get("current_category") or row.get("category") or "").strip()
        section_tags = {part.strip() for part in row.get("section_tags", "").split(",") if part.strip()}
        if current and section_tags and current not in section_tags:
            issues.append(
                {
                    "status": "section_tag_mismatch",
                    "category": current,
                    "section_tags": ",".join(sorted(section_tags)),
                    "publisher": row.get("publisher", ""),
                    "title": row.get("title", ""),
                    "url": row.get("source_url", ""),
                }
            )
    return issues


def latest_log_tail(log_file: Path | None, limit: int = 12) -> list[str]:
    if not log_file or not log_file.exists():
        return []
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-limit:]


def build_status(args: argparse.Namespace) -> tuple[dict[str, object], int]:
    report_date = args.date
    dated = compact_date(report_date)
    out_dir = Path(args.out_dir)
    site_dir = Path(args.site_dir)
    public_base_url = str(args.public_base_url).rstrip("/")

    brief_path = DEFAULT_EXPORT_DIR / f"daily_news_brief_{dated}.md"
    final_path = DEFAULT_EXPORT_DIR / f"daily_news_final_{dated}.md"
    review_path = DEFAULT_EXPORT_DIR / f"daily_news_review_queue_{dated}.csv"
    stats_path = DEFAULT_EXPORT_DIR / f"daily_news_source_stats_{dated}.json"
    icon_json_path = DEFAULT_EXPORT_DIR / "icon_reports" / f"newsletter_icon_report_{dated}.json"
    ai_json_path = DEFAULT_EXPORT_DIR / f"daily_news_ai_enrichment_{dated}.json"
    ai_audit_path = DEFAULT_EXPORT_DIR / f"daily_news_ai_enrichment_audit_{dated}.csv"

    hard_failures: list[str] = []
    soft_warnings: list[str] = []

    stats, stats_error = read_json(stats_path)
    if stats_error:
        hard_failures.append(stats_error)
        stats = {}
    if not isinstance(stats, dict):
        hard_failures.append(f"source stats is not an object: {stats_path}")
        stats = {}

    if not brief_path.exists():
        hard_failures.append(f"missing brief: {brief_path}")
    if not review_path.exists():
        hard_failures.append(f"missing review queue: {review_path}")

    brief_count = int(stats.get("brief_count") or 0)
    if brief_count <= 0:
        hard_failures.append("source stats brief_count is 0")
    if int(stats.get("warning_count") or 0) > 0:
        soft_warnings.append(f"source warning_count={stats.get('warning_count')}")
    if not final_path.exists():
        soft_warnings.append(f"final file is missing: {final_path}")

    review_rows = read_csv_rows(review_path)
    tag_conflicts = detect_tag_conflicts(review_rows)
    if tag_conflicts:
        hard_failures.append(f"review category/section tag conflicts={len(tag_conflicts)}")

    local_health, local_health_error = read_json(site_dir / "health.json")
    if local_health_error:
        hard_failures.append(local_health_error)
        local_health = {}
    if not isinstance(local_health, dict):
        hard_failures.append("local health.json is not an object")
        local_health = {}
    if str(local_health.get("report_date") or "") != report_date:
        hard_failures.append(f"local health report_date={local_health.get('report_date')} expected={report_date}")
    if int(local_health.get("article_count") or 0) <= 0:
        hard_failures.append("local health article_count is 0")

    local_archive, local_archive_error = read_json(site_dir / "archive.json")
    if local_archive_error:
        hard_failures.append(local_archive_error)
    local_entry = archive_entry(local_archive, report_date)
    local_archive_count = len(local_entry.get("articles") or []) if local_entry else 0
    if local_archive_count <= 0:
        hard_failures.append(f"local archive missing articles for {report_date}")

    icon_payload, icon_error = read_json(icon_json_path)
    icon_issue_count = 0
    if icon_error:
        soft_warnings.append(icon_error)
        icon_payload = {}
    if isinstance(icon_payload, dict):
        icon_issue_count = int(icon_payload.get("issue_count") or 0)
        if icon_issue_count > 0:
            soft_warnings.append(f"publisher icon issues={icon_issue_count}")

    ai_payload, ai_error = read_json(ai_json_path)
    ai_provider = ""
    ai_article_count = 0
    if ai_error:
        soft_warnings.append(ai_error)
        ai_payload = {}
    if isinstance(ai_payload, dict):
        ai_provider = str(ai_payload.get("provider") or "")
        ai_article_count = int(ai_payload.get("article_count") or len(ai_payload.get("articles") or []))
    ai_audit_rows = read_csv_rows(ai_audit_path)
    ai_status_counts = dict(sorted(Counter(row.get("status") or "unknown" for row in ai_audit_rows).items()))

    public_health: object | None = None
    public_archive: object | None = None
    public_archive_count = 0
    public_errors: list[str] = []
    if not args.no_public:
        bust = f"{dated}-{int(datetime.now(timezone.utc).timestamp())}"
        public_health, error = fetch_json(f"{public_base_url}/health.json?ops_status={bust}", args.public_timeout)
        if error:
            public_errors.append(f"public health fetch failed: {error}")
        public_archive, error = fetch_json(f"{public_base_url}/archive.json?ops_status={bust}", args.public_timeout)
        if error:
            public_errors.append(f"public archive fetch failed: {error}")
        if public_errors:
            hard_failures.extend(public_errors)
        if isinstance(public_health, dict):
            if str(public_health.get("report_date") or "") != report_date:
                hard_failures.append(f"public health report_date={public_health.get('report_date')} expected={report_date}")
            if int(public_health.get("article_count") or 0) <= 0:
                hard_failures.append("public health article_count is 0")
        elif not public_errors:
            hard_failures.append("public health.json is not an object")
        public_entry = archive_entry(public_archive, report_date)
        public_archive_count = len(public_entry.get("articles") or []) if public_entry else 0
        if public_archive_count <= 0:
            hard_failures.append(f"public archive missing articles for {report_date}")

    publish_exit_code = args.publish_exit_code
    if publish_exit_code not in (None, 0):
        hard_failures.append(f"publish script exit_code={publish_exit_code}")

    status = "ok" if not hard_failures else "failed"
    payload: dict[str, object] = {
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "report_date": report_date,
        "status": status,
        "publish_exit_code": publish_exit_code,
        "hard_failures": hard_failures,
        "soft_warnings": soft_warnings,
        "collection": {
            "brief_exists": brief_path.exists(),
            "review_queue_exists": review_path.exists(),
            "final_exists": final_path.exists(),
            "run_id": stats.get("run_id"),
            "discovered_count": int(stats.get("discovered_count") or 0),
            "fetched_count": int(stats.get("fetched_count") or 0),
            "inserted_count": int(stats.get("inserted_count") or 0),
            "brief_count": brief_count,
            "warning_count": int(stats.get("warning_count") or 0),
        },
        "quality": {
            "icon_issue_count": icon_issue_count,
            "tag_conflict_count": len(tag_conflicts),
            "tag_conflicts": tag_conflicts[:20],
            "ai_provider": ai_provider,
            "ai_article_count": ai_article_count,
            "ai_status_counts": ai_status_counts,
            "ai_apply_sections": os.environ.get("NEWSLETTER_AI_APPLY_SECTIONS", "0"),
        },
        "local_site": {
            "health_report_date": local_health.get("report_date") if isinstance(local_health, dict) else None,
            "health_article_count": local_health.get("article_count") if isinstance(local_health, dict) else None,
            "built_at": local_health.get("built_at") if isinstance(local_health, dict) else None,
            "archive_article_count": local_archive_count,
            "section_counts": section_counts_from_archive(local_entry),
        },
        "public_site": {
            "checked": not args.no_public,
            "base_url": public_base_url,
            "health_report_date": public_health.get("report_date") if isinstance(public_health, dict) else None,
            "health_article_count": public_health.get("article_count") if isinstance(public_health, dict) else None,
            "built_at": public_health.get("built_at") if isinstance(public_health, dict) else None,
            "archive_article_count": public_archive_count,
        },
        "review_queue": {
            "included_section_counts": section_counts_from_review(review_rows),
        },
        "paths": {
            "brief": str(brief_path),
            "final": str(final_path),
            "review_queue": str(review_path),
            "source_stats": str(stats_path),
            "icon_report": str(icon_json_path),
            "ai_enrichment": str(ai_json_path),
            "ai_audit": str(ai_audit_path),
            "site_dir": str(site_dir),
            "log_file": str(args.log_file) if args.log_file else "",
        },
        "log_tail": latest_log_tail(Path(args.log_file) if args.log_file else None),
    }
    return payload, (0 if status == "ok" else 1)


def render_markdown(payload: dict[str, object]) -> str:
    collection = payload.get("collection", {})
    local_site = payload.get("local_site", {})
    public_site = payload.get("public_site", {})
    quality = payload.get("quality", {})
    if not isinstance(collection, dict):
        collection = {}
    if not isinstance(local_site, dict):
        local_site = {}
    if not isinstance(public_site, dict):
        public_site = {}
    if not isinstance(quality, dict):
        quality = {}

    lines = [
        f"# Newsletter Ops Status {payload.get('report_date')}",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Checked at: `{payload.get('checked_at')}`",
        f"- Publish exit code: `{payload.get('publish_exit_code')}`",
        "",
        "## Collection",
        "",
        f"- Run ID: `{collection.get('run_id')}`",
        f"- Discovered / fetched / inserted: {collection.get('discovered_count')} / {collection.get('fetched_count')} / {collection.get('inserted_count')}",
        f"- Brief count: {collection.get('brief_count')}",
        f"- Source warnings: {collection.get('warning_count')}",
        f"- Brief / review / final exists: {collection.get('brief_exists')} / {collection.get('review_queue_exists')} / {collection.get('final_exists')}",
        "",
        "## Site",
        "",
        f"- Local: date={local_site.get('health_report_date')}, articles={local_site.get('health_article_count')}, archive={local_site.get('archive_article_count')}, built_at={local_site.get('built_at')}",
        f"- Public: date={public_site.get('health_report_date')}, articles={public_site.get('health_article_count')}, archive={public_site.get('archive_article_count')}, built_at={public_site.get('built_at')}",
        "",
        "## Quality",
        "",
        f"- Icon issues: {quality.get('icon_issue_count')}",
        f"- Tag conflicts: {quality.get('tag_conflict_count')}",
        f"- AI enrichment: provider={quality.get('ai_provider')}, articles={quality.get('ai_article_count')}, statuses={quality.get('ai_status_counts')}, apply_sections={quality.get('ai_apply_sections')}",
    ]
    hard_failures = payload.get("hard_failures") or []
    soft_warnings = payload.get("soft_warnings") or []
    lines.extend(["", "## Hard Failures", ""])
    if hard_failures:
        lines.extend(f"- {item}" for item in hard_failures)
    else:
        lines.append("- None")
    lines.extend(["", "## Soft Warnings", ""])
    if soft_warnings:
        lines.extend(f"- {item}" for item in soft_warnings)
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write newsletter operations status")
    parser.add_argument("--date", default=today_seoul())
    parser.add_argument("--site-dir", type=Path, default=DEFAULT_SITE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--public-base-url", default=DEFAULT_PUBLIC_BASE_URL)
    parser.add_argument("--public-timeout", type=int, default=10)
    parser.add_argument("--no-public", action="store_true")
    parser.add_argument("--publish-exit-code", type=int)
    parser.add_argument("--log-file", type=Path)
    parser.add_argument("--fail-on-hard", action="store_true")
    args = parser.parse_args()

    payload, exit_code = build_status(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    dated = compact_date(args.date)
    json_path = args.out_dir / f"newsletter_ops_status_{dated}.json"
    markdown_path = args.out_dir / f"newsletter_ops_status_{dated}.md"
    latest_json_path = args.out_dir / "newsletter_ops_status_latest.json"
    latest_markdown_path = args.out_dir / "newsletter_ops_status_latest.md"
    json_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    markdown_text = render_markdown(payload)
    json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    latest_markdown_path.write_text(markdown_text, encoding="utf-8")
    print(f"newsletter_ops_status={payload['status']} report={markdown_path}")
    if payload["hard_failures"]:
        print("newsletter_ops_hard_failures=" + "; ".join(str(item) for item in payload["hard_failures"]))
    if payload["soft_warnings"]:
        print("newsletter_ops_soft_warnings=" + "; ".join(str(item) for item in payload["soft_warnings"]))
    return exit_code if args.fail_on_hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
