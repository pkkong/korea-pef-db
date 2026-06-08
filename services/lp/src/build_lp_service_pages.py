#!/usr/bin/env python
"""Build LP service static pages into an explicit site directory."""

from __future__ import annotations

import argparse
from pathlib import Path

from services.newsletter.src.build_newsletter_deploy import (
    DEFAULT_LP_COMMITMENT_MONITOR,
    prepare_lp_notice_display_items,
    read_lp_monitor,
    write_lp_notice_detail_pages,
    write_lp_notices_page,
    write_lp_profile_pages,
)
from services.newsletter.src.daily_news_common import today_seoul


def build_lp_service_pages(
    site_dir: Path,
    report_date: str | None = None,
    monitor_path: Path = DEFAULT_LP_COMMITMENT_MONITOR,
) -> dict[str, int]:
    """Write LP directory, notice, profile, and notice detail pages while preserving current public URLs."""
    site_dir.mkdir(parents=True, exist_ok=True)
    effective_date = report_date or today_seoul()
    notice_count = write_lp_notices_page(site_dir, effective_date)
    profile_fact_count = write_lp_profile_pages(site_dir, effective_date)
    notices = prepare_lp_notice_display_items(read_lp_monitor(monitor_path, limit=None), effective_date)
    write_lp_notice_detail_pages(site_dir, effective_date, notices)
    lp_service_pages = {"lp-notices.html", "lp-official-notices.html"}
    profile_page_count = len(
        [
            path
            for path in site_dir.glob("lp-*.html")
            if path.name not in lp_service_pages and not path.name.startswith("lp-notice-")
        ]
    )
    return {
        "lp_monitor_count": notice_count,
        "lp_profile_fact_count": profile_fact_count,
        "lp_profile_page_count": profile_page_count,
        "lp_notice_detail_page_count": len(list(site_dir.glob("lp-notice-*.html"))),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LP service pages into an explicit site directory")
    parser.add_argument("--site-dir", type=Path, required=True)
    parser.add_argument("--date", default=today_seoul())
    parser.add_argument("--monitor", type=Path, default=DEFAULT_LP_COMMITMENT_MONITOR)
    args = parser.parse_args()

    result = build_lp_service_pages(args.site_dir, args.date, args.monitor)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
