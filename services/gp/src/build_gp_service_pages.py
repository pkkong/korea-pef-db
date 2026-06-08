#!/usr/bin/env python
"""Build GP service static pages into an explicit site directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
NEWSLETTER_SRC_DIR = REPO_ROOT / "services" / "newsletter" / "src"
if str(NEWSLETTER_SRC_DIR) not in sys.path:
    sys.path.append(str(NEWSLETTER_SRC_DIR))

from daily_news_common import today_seoul  # noqa: E402
from gp_service_pages import write_gp_pages  # noqa: E402


def build_gp_service_pages(site_dir: Path, db_path: Path = DEFAULT_DB, report_date: str | None = None) -> dict[str, int]:
    """Write GP directory, market, and profile pages while preserving current public URLs."""
    return write_gp_pages(site_dir, db_path, report_date or today_seoul())


def main() -> int:
    parser = argparse.ArgumentParser(description="Build GP service pages into an explicit site directory")
    parser.add_argument("--site-dir", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--date", default=today_seoul())
    args = parser.parse_args()

    result = build_gp_service_pages(args.site_dir, args.db, args.date)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
