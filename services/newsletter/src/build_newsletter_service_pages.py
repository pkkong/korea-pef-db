#!/usr/bin/env python
"""Build Newsletter service static pages into an explicit site directory."""

from __future__ import annotations

import argparse
from pathlib import Path

from services.newsletter.src.build_newsletter_deploy import (
    DEFAULT_ARCHIVE_LIMIT,
    DEFAULT_ARCHIVE_SEED_URL,
    DEFAULT_DEPLOY_DIR,
    DEFAULT_EXPORT_DIR,
    archive_article_count,
    merge_archives,
    read_archive_seed,
    read_embedded_archive,
    rewrite_site_archive,
)
from services.newsletter.src.daily_news_common import today_seoul

try:
    from build_service_site import build
except ModuleNotFoundError:  # pragma: no cover - package import path fallback
    from scripts.build_service_site import build  # type: ignore


def build_newsletter_service_pages(
    site_dir: Path,
    report_date: str | None = None,
    archive_limit: int = DEFAULT_ARCHIVE_LIMIT,
    archive_seed_url: str = DEFAULT_ARCHIVE_SEED_URL,
    use_archive_seed: bool = True,
) -> dict[str, str]:
    """Write Newsletter pages while preserving the current public URLs."""
    site_dir.mkdir(parents=True, exist_ok=True)
    effective_date = report_date or today_seoul()
    result = build(
        public_dir=site_dir,
        out_dir=DEFAULT_EXPORT_DIR,
        report_date=effective_date,
        archive_limit=archive_limit,
        newsletter_only=True,
        include_wiki=False,
    )
    local_archive = read_embedded_archive(site_dir / "index.html")
    seed_archive = read_archive_seed(archive_seed_url) if use_archive_seed else []
    archive_entries = merge_archives(local_archive, seed_archive, archive_limit)
    if archive_entries:
        rewrite_site_archive(site_dir, effective_date, archive_entries)
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
    args = parser.parse_args()

    result = build_newsletter_service_pages(
        args.site_dir,
        args.date,
        args.archive_limit,
        args.archive_seed_url,
        not args.no_archive_seed,
    )
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
