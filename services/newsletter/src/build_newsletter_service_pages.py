#!/usr/bin/env python
"""Build Newsletter service static pages into an explicit site directory."""

from __future__ import annotations

import argparse
from pathlib import Path

from services.newsletter.src.daily_news_common import DEFAULT_EXPORT_DIR, today_seoul
from services.newsletter.src.newsletter_renderer import build_newsletter_site, rewrite_newsletter_archive
from services.newsletter.src.newsletter_site_support import (
    DEFAULT_ARCHIVE_LIMIT,
    DEFAULT_ARCHIVE_SEED_URL,
    DEFAULT_DEPLOY_DIR,
    archive_article_count,
    merge_archives,
    read_archive_seed,
    read_embedded_archive,
)


def build_newsletter_service_pages(
    site_dir: Path,
    report_date: str | None = None,
    archive_limit: int = DEFAULT_ARCHIVE_LIMIT,
    archive_seed_url: str = DEFAULT_ARCHIVE_SEED_URL,
    use_archive_seed: bool = True,
    require_archive_seed: bool = False,
) -> dict[str, str]:
    """Write Newsletter pages while preserving the current public URLs."""
    site_dir.mkdir(parents=True, exist_ok=True)
    effective_date = report_date or today_seoul()
    result = build_newsletter_site(
        site_dir,
        out_dir=DEFAULT_EXPORT_DIR,
        report_date=effective_date,
        archive_limit=archive_limit,
    )
    local_archive = read_embedded_archive(site_dir / "index.html")
    seed_archive = read_archive_seed(archive_seed_url, required=require_archive_seed) if use_archive_seed else []
    archive_entries = merge_archives(local_archive, seed_archive, archive_limit)
    if archive_entries:
        rewrite_newsletter_archive(site_dir, DEFAULT_EXPORT_DIR, effective_date, archive_entries)
        result["article_count"] = str(
            archive_article_count(
                archive_entries,
                effective_date,
                int(result.get("article_count", "0") or 0),
            )
        )
    result["report_date"] = effective_date
    return {key: str(value) for key, value in result.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Newsletter service pages into an explicit site directory")
    parser.add_argument("--site-dir", type=Path, default=DEFAULT_DEPLOY_DIR / "site")
    parser.add_argument("--date", default=today_seoul())
    parser.add_argument("--archive-limit", type=int, default=DEFAULT_ARCHIVE_LIMIT)
    parser.add_argument("--archive-seed-url", default=DEFAULT_ARCHIVE_SEED_URL)
    parser.add_argument("--no-archive-seed", action="store_true")
    parser.add_argument("--require-archive-seed", action="store_true")
    args = parser.parse_args()

    result = build_newsletter_service_pages(
        args.site_dir,
        args.date,
        args.archive_limit,
        args.archive_seed_url,
        not args.no_archive_seed,
        args.require_archive_seed,
    )
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
