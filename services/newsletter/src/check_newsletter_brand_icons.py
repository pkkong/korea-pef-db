#!/usr/bin/env python3
"""Report missing or weak article brand icons in the generated newsletter site."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from brand_assets import BRAND_MARKS


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
DEFAULT_SITE_DIR = SERVICE_ROOT / "deploy" / "site"
DEFAULT_OUT_DIR = REPO_ROOT / "exports" / "daily_news" / "icon_reports"


WEAK_EXTENSIONS = {".ico", ".img"}


def article_domain(url: object) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").removeprefix("www.")
    except ValueError:
        return ""


def icon_status(site_dir: Path, icon_url: str) -> tuple[str, str]:
    if not icon_url:
        return "missing_icon_url", "No curated logo URL; UI falls back to text badge."
    if icon_url.startswith("assets/"):
        asset_path = site_dir / icon_url
        if not asset_path.exists():
            return "missing_local_asset", f"Local asset not found: {icon_url}"
        if asset_path.suffix.lower() in WEAK_EXTENSIONS:
            return "weak_asset_type", f"Asset is {asset_path.suffix.lower()}, prefer official PNG/SVG logo."
    if icon_url.lower().endswith(".ico"):
        return "weak_favicon", "ICO favicon is present but should be replaced with official CI/logo when possible."
    return "ok", ""


def registry_icon_status(domain: str, icon_url: str) -> tuple[str, str]:
    if not icon_url:
        return "missing_registry_icon", f"{domain} has no curated logo URL."
    if icon_url.lower().endswith(".ico"):
        return "weak_favicon", f"{domain} uses an ICO favicon; prefer official PNG/SVG logo."
    return "ok", ""


def load_articles(site_dir: Path, report_date: str) -> list[dict[str, object]]:
    archive_path = site_dir / "archive.json"
    if not archive_path.exists():
        raise SystemExit(f"archive.json not found: {archive_path}")
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    if not isinstance(archive, list):
        raise SystemExit("archive.json must be a list")
    for brief in archive:
        if not isinstance(brief, dict):
            continue
        if report_date and brief.get("reportDate") != report_date:
            continue
        return list(brief.get("articles", []) or [])
    return []


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    headers = [
        "report_date",
        "status",
        "publisher",
        "domain",
        "title",
        "url",
        "icon_url",
        "reason",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows([{header: row.get(header, "") for header in headers} for row in rows])


def main() -> int:
    parser = argparse.ArgumentParser(description="Check newsletter article brand icons")
    parser.add_argument("--site-dir", type=Path, default=DEFAULT_SITE_DIR)
    parser.add_argument("--report-date", default="")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--fail-on-missing", action="store_true")
    parser.add_argument("--check-registry", action="store_true")
    args = parser.parse_args()

    articles = load_articles(args.site_dir, args.report_date)
    issue_rows: list[dict[str, object]] = []
    for article in articles:
        icon_url = str(article.get("sourceIconUrl", "") or "")
        status, reason = icon_status(args.site_dir, icon_url)
        if status == "ok":
            continue
        issue_rows.append(
            {
                "report_date": args.report_date or "",
                "status": status,
                "publisher": article.get("source", ""),
                "domain": article_domain(article.get("url", "")),
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "icon_url": icon_url,
                "reason": reason,
            }
        )

    if args.check_registry:
        for domain, mark in BRAND_MARKS.items():
            status, reason = registry_icon_status(domain, str(mark.get("logo_url", "") or ""))
            if status == "ok":
                continue
            issue_rows.append(
                {
                    "report_date": args.report_date or "",
                    "status": status,
                    "publisher": domain,
                    "domain": domain,
                    "title": "",
                    "url": "",
                    "icon_url": mark.get("logo_url", ""),
                    "reason": reason,
                }
            )

    dated = (args.report_date or "latest").replace("-", "")
    csv_path = args.out_dir / f"newsletter_icon_report_{dated}.csv"
    json_path = args.out_dir / f"newsletter_icon_report_{dated}.json"
    write_csv(csv_path, issue_rows)
    payload = {
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "report_date": args.report_date,
        "article_count": len(articles),
        "issue_count": len(issue_rows),
        "csv_path": str(csv_path),
        "issues": issue_rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"newsletter_icon_check article_count={len(articles)} issue_count={len(issue_rows)} report={csv_path}")
    if args.fail_on_missing and issue_rows:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
