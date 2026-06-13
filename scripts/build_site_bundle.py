#!/usr/bin/env python
"""Build the integrated public site bundle from service-specific builders."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.gp.src.build_gp_service_pages import build_gp_service_pages  # noqa: E402
from services.lp.src.build_lp_service_pages import build_lp_service_pages  # noqa: E402
from services.newsletter.src.build_newsletter_deploy import (  # noqa: E402
    DEFAULT_ARCHIVE_LIMIT,
    DEFAULT_ARCHIVE_SEED_URL,
    DEFAULT_DB,
    DEFAULT_DEPLOY_DIR,
    assert_newsletter_only,
    remove_legacy_public_db_files,
    write_health_file,
    write_static_support_files,
    zip_site,
)
from services.newsletter.src.build_newsletter_service_pages import build_newsletter_service_pages  # noqa: E402
from services.newsletter.src.daily_news_common import today_seoul  # noqa: E402
from services.wiki.src.build_wiki_service_pages import build_wiki_service_pages  # noqa: E402


DEFAULT_SERVICE_ORDER = ("newsletter", "lp", "gp")
ALL_SERVICE_ORDER = ("newsletter", "lp", "gp", "wiki")
SERVICE_ALIASES = {
    "brief": "newsletter",
    "news": "newsletter",
    "newsletter": "newsletter",
    "lp": "lp",
    "gp": "gp",
    "wiki": "wiki",
}
HEALTH_KEYS = {
    "report_date",
    "article_count",
    "lp_monitor_count",
    "ktcu_fact_count",
    "lp_profile_fact_count",
    "lp_profile_page_count",
    "gp_count",
    "active_gp_count",
    "gp_active_count",
    "top_gp_page_count",
    "gp_profile_page_count",
    "news_link_count",
    "gp_news_link_count",
}
HEALTH_RESULT_KEY_ALIASES = {
    "gp_active_count": "active_gp_count",
    "gp_profile_page_count": "top_gp_page_count",
    "gp_news_link_count": "news_link_count",
}


def parse_services(value: str) -> list[str]:
    raw_parts = [part.strip().lower() for chunk in value.split(",") for part in chunk.split() if part.strip()]
    if not raw_parts or "all" in raw_parts:
        return list(DEFAULT_SERVICE_ORDER)
    services: list[str] = []
    for part in raw_parts:
        service = SERVICE_ALIASES.get(part)
        if service is None:
            raise ValueError(f"Unknown service: {part}")
        if service not in services:
            services.append(service)
    return services


def existing_health_result(site_dir: Path, report_date: str) -> dict[str, str]:
    health_path = site_dir / "health.json"
    result: dict[str, str] = {"report_date": report_date}
    if not health_path.exists():
        return result
    try:
        payload = json.loads(health_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return result
    if not isinstance(payload, dict):
        return result
    for key in HEALTH_KEYS:
        if key in payload and payload[key] is not None:
            result[HEALTH_RESULT_KEY_ALIASES.get(key, key)] = str(payload[key])
    result["report_date"] = report_date
    return result


def write_shared_support(site_dir: Path, result: dict[str, str], requested_services: list[str]) -> None:
    remove_legacy_public_db_files(site_dir)
    (site_dir / "admin.html").unlink(missing_ok=True)
    write_health_file(site_dir, result)
    if (site_dir / "index.html").exists():
        write_static_support_files(site_dir)
    else:
        (site_dir / ".nojekyll").write_text("", encoding="utf-8")
        (site_dir / "robots.txt").write_text("User-agent: *\nDisallow:\n", encoding="utf-8")
    if "newsletter" in requested_services and (site_dir / "index.html").exists() and (site_dir / "daily-news.html").exists():
        assert_newsletter_only(site_dir)


def build_site_bundle(
    *,
    deploy_dir: Path = DEFAULT_DEPLOY_DIR,
    report_date: str | None = None,
    services: list[str] | None = None,
    archive_limit: int = DEFAULT_ARCHIVE_LIMIT,
    archive_seed_url: str = DEFAULT_ARCHIVE_SEED_URL,
    use_archive_seed: bool = True,
    db_path: Path = DEFAULT_DB,
) -> dict[str, str]:
    effective_date = report_date or today_seoul()
    requested_services = services or list(DEFAULT_SERVICE_ORDER)
    site_dir = deploy_dir / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    deploy_dir.mkdir(parents=True, exist_ok=True)

    result = existing_health_result(site_dir, effective_date)
    for service in ALL_SERVICE_ORDER:
        if service not in requested_services:
            continue
        if service == "newsletter":
            result.update(
                build_newsletter_service_pages(
                    site_dir,
                    effective_date,
                    archive_limit,
                    archive_seed_url,
                    use_archive_seed,
                )
            )
        elif service == "lp":
            result.update({key: str(value) for key, value in build_lp_service_pages(site_dir, effective_date).items()})
        elif service == "gp":
            result.update({key: str(value) for key, value in build_gp_service_pages(site_dir, db_path, effective_date).items()})
        elif service == "wiki":
            result.update({key: str(value) for key, value in build_wiki_service_pages(site_dir, effective_date).items()})
    result["report_date"] = effective_date
    result["services"] = ",".join(requested_services)

    write_shared_support(site_dir, result, requested_services)
    zip_path = zip_site(deploy_dir, site_dir)

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
    parser = argparse.ArgumentParser(description="Build integrated public site bundle from service builders")
    parser.add_argument("--date", default=today_seoul())
    parser.add_argument("--deploy-dir", type=Path, default=DEFAULT_DEPLOY_DIR)
    parser.add_argument("--services", default=",".join(DEFAULT_SERVICE_ORDER))
    parser.add_argument("--archive-limit", type=int, default=DEFAULT_ARCHIVE_LIMIT)
    parser.add_argument("--archive-seed-url", default=DEFAULT_ARCHIVE_SEED_URL)
    parser.add_argument("--no-archive-seed", action="store_true")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    try:
        services = parse_services(args.services)
    except ValueError as exc:
        parser.error(str(exc))
    manifest = build_site_bundle(
        deploy_dir=args.deploy_dir,
        report_date=args.date,
        services=services,
        archive_limit=args.archive_limit,
        archive_seed_url=args.archive_seed_url,
        use_archive_seed=not args.no_archive_seed,
        db_path=args.db,
    )
    for key, value in manifest.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
