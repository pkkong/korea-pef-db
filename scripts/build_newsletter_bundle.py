#!/usr/bin/env python
"""Build the GitHub Actions newsletter-only public bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.newsletter.src.build_newsletter_service_pages import build_newsletter_service_pages  # noqa: E402
from services.newsletter.src.daily_news_common import today_seoul  # noqa: E402
from services.newsletter.src.newsletter_site_support import (  # noqa: E402
    DEFAULT_ARCHIVE_LIMIT,
    DEFAULT_ARCHIVE_SEED_URL,
    DEFAULT_DEPLOY_DIR,
    assert_newsletter_only,
    remove_legacy_public_db_files,
    write_health_file,
    write_static_support_files,
    zip_newsletter_site,
)


def build_newsletter_bundle(
    *,
    deploy_dir: Path = DEFAULT_DEPLOY_DIR,
    report_date: str | None = None,
    archive_limit: int = DEFAULT_ARCHIVE_LIMIT,
    archive_seed_url: str = DEFAULT_ARCHIVE_SEED_URL,
    use_archive_seed: bool = True,
    require_archive_seed: bool = False,
) -> dict[str, str]:
    effective_date = report_date or today_seoul()
    site_dir = deploy_dir / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    deploy_dir.mkdir(parents=True, exist_ok=True)

    result = build_newsletter_service_pages(
        site_dir,
        effective_date,
        archive_limit,
        archive_seed_url,
        use_archive_seed,
        require_archive_seed,
    )
    result["report_date"] = effective_date
    result["services"] = "newsletter"

    remove_legacy_public_db_files(site_dir)
    write_health_file(site_dir, result)
    write_static_support_files(site_dir)
    assert_newsletter_only(site_dir)
    zip_path = zip_newsletter_site(deploy_dir, site_dir)

    manifest = {
        **result,
        "deploy_dir": str(deploy_dir),
        "site_dir": str(site_dir),
        "zip_path": str(zip_path),
    }
    (deploy_dir / "deploy-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build newsletter-only public site bundle")
    parser.add_argument("--date", default=today_seoul())
    parser.add_argument("--deploy-dir", type=Path, default=DEFAULT_DEPLOY_DIR)
    parser.add_argument("--archive-limit", type=int, default=DEFAULT_ARCHIVE_LIMIT)
    parser.add_argument("--archive-seed-url", default=DEFAULT_ARCHIVE_SEED_URL)
    parser.add_argument("--no-archive-seed", action="store_true")
    parser.add_argument("--require-archive-seed", action="store_true")
    args = parser.parse_args()

    manifest = build_newsletter_bundle(
        deploy_dir=args.deploy_dir,
        report_date=args.date,
        archive_limit=args.archive_limit,
        archive_seed_url=args.archive_seed_url,
        use_archive_seed=not args.no_archive_seed,
        require_archive_seed=args.require_archive_seed,
    )
    for key, value in manifest.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
