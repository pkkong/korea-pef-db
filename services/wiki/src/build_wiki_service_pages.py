#!/usr/bin/env python
"""Build Wiki service static pages into an explicit site directory."""

from __future__ import annotations

import argparse
from pathlib import Path

from services.newsletter.src.build_newsletter_deploy import app_asset_version
from services.newsletter.src.daily_news_common import today_seoul
from services.newsletter.src.pef_wiki_pages import render_pef_wiki_page


def build_wiki_service_pages(site_dir: Path, report_date: str | None = None, asset_version: str | None = None) -> dict[str, int]:
    """Write the PEF Wiki page while preserving the current pef-wiki.html URL."""
    site_dir.mkdir(parents=True, exist_ok=True)
    version = app_asset_version() if asset_version is None else asset_version
    (site_dir / "pef-wiki.html").write_text(
        render_pef_wiki_page(report_date or today_seoul(), version),
        encoding="utf-8",
    )
    return {"wiki_page_count": 1}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Wiki service pages into an explicit site directory")
    parser.add_argument("--site-dir", type=Path, required=True)
    parser.add_argument("--date", default=today_seoul())
    parser.add_argument("--asset-version", default=None)
    args = parser.parse_args()

    result = build_wiki_service_pages(args.site_dir, args.date, args.asset_version)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
