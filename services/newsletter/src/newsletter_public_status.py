#!/usr/bin/env python3
"""Public newsletter freshness and deployment-status checks.

GitHub Actions workflows call this module so mirror, Supabase, Vercel, and
watchdog checks share one tested implementation instead of embedding Python in
workflow YAML.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen


JsonFetcher = Callable[[str, int], Any]

NEWSLETTER_REQUIRED_FILES = {
    "index.html",
    "daily-news.html",
    "archive.json",
    "health.json",
    ".nojekyll",
    "assets/service.css",
    "assets/service.js",
    "apple-touch-icon.png",
}
NEWSLETTER_ONLY_ZERO_HEALTH_KEYS = ("lp_monitor_count", "gp_count", "gp_profile_page_count")
WATCHDOG_APP_FRESH_DATA_SOURCES = {"supabase", "archive_fallback"}


def _clean_base_url(value: str) -> str:
    return value.rstrip("/")


def _github_pages_raw_base_url(mirror_url: str) -> str:
    parsed = urlparse(_clean_base_url(mirror_url))
    host = parsed.netloc.lower()
    if not host.endswith(".github.io"):
        return ""
    owner = host[: -len(".github.io")]
    repo = parsed.path.strip("/").split("/", 1)[0]
    if not owner or not repo:
        return ""
    return f"https://raw.githubusercontent.com/{owner}/{repo}/gh-pages"


def _raw_mirror_base_urls(mirror_url: str) -> list[str]:
    bases: list[str] = []
    override = os.environ.get("NEWSLETTER_RAW_MIRROR_URL", "").strip()
    if override:
        bases.append(_clean_base_url(override))
    inferred = _github_pages_raw_base_url(mirror_url)
    if inferred:
        bases.append(inferred)
    deduped: list[str] = []
    for base in bases:
        if base not in deduped and base != _clean_base_url(mirror_url):
            deduped.append(base)
    return deduped


def _cache_busted_url(url: str, label: str, key: str) -> str:
    parsed = urlparse(url)
    sep = "&" if parsed.query else ""
    query = f"{parsed.query}{sep}{label}={int(time.time())}-{key}"
    return urlunparse(parsed._replace(query=query))


def fetch_json_url(url: str, timeout: int = 20) -> Any:
    request = Request(
        url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "kpef-newsletter-status/1.0",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_json_busted(
    url: str,
    *,
    label: str,
    key: str,
    timeout: int = 20,
    fetcher: JsonFetcher = fetch_json_url,
) -> Any:
    return fetcher(_cache_busted_url(url, label, key), timeout)


def issue_article_count(archive: Any, report_date: str) -> int:
    if not isinstance(archive, list):
        return 0
    entry = next(
        (row for row in archive if isinstance(row, dict) and row.get("reportDate") == report_date),
        None,
    )
    return len(entry.get("articles") or []) if isinstance(entry, dict) else 0


def _syncable_archive_snapshot(
    *,
    requested_report_date: str,
    base_url: str,
    source: str,
    label: str,
    fetcher: JsonFetcher,
) -> dict[str, Any]:
    cache_key = requested_report_date or str(int(time.time()))
    health = fetch_json_busted(
        f"{base_url}/health.json",
        label=label,
        key=cache_key,
        timeout=20,
        fetcher=fetcher,
    )
    archive = fetch_json_busted(
        f"{base_url}/archive.json",
        label=label,
        key=cache_key,
        timeout=20,
        fetcher=fetcher,
    )
    if not isinstance(health, dict):
        raise RuntimeError(f"{source} health.json is not an object")
    if not isinstance(archive, list):
        raise RuntimeError(f"{source} archive.json is not a list")
    source_report_date = str(health.get("report_date") or "")
    report_date = requested_report_date or source_report_date
    if not report_date:
        raise RuntimeError(f"{source} health.json does not contain report_date")
    if source_report_date != report_date:
        raise RuntimeError(f"{source} report_date={source_report_date} expected={report_date}")
    article_count = int(health.get("article_count") or 0)
    archive_count = issue_article_count(archive, report_date)
    if article_count <= 0 or archive_count != article_count:
        raise RuntimeError(f"{source} archive is not syncable: health={article_count} archive={archive_count}")
    return {
        "source": source,
        "health": health,
        "archive": archive,
        "report_date": report_date,
        "article_count": article_count,
        "archive_count": archive_count,
    }


def syncable_public_archive_snapshot(
    *,
    requested_report_date: str,
    mirror_url: str,
    label: str,
    fetcher: JsonFetcher = fetch_json_url,
) -> dict[str, Any]:
    base_url = _clean_base_url(mirror_url)
    errors: list[str] = []
    try:
        return _syncable_archive_snapshot(
            requested_report_date=requested_report_date,
            base_url=base_url,
            source="pages_mirror",
            label=label,
            fetcher=fetcher,
        )
    except Exception as exc:  # noqa: BLE001 - fallback reports all checked sources.
        errors.append(f"pages_mirror: {exc}")

    for raw_base_url in _raw_mirror_base_urls(mirror_url):
        try:
            snapshot = _syncable_archive_snapshot(
                requested_report_date=requested_report_date,
                base_url=raw_base_url,
                source="raw_github_pages",
                label=label,
                fetcher=fetcher,
            )
            snapshot["fallback_reason"] = "; ".join(errors)
            return snapshot
        except Exception as exc:  # noqa: BLE001 - continue checking configured fallbacks.
            errors.append(f"raw_github_pages: {exc}")

    raise RuntimeError("; ".join(errors))


def mirror_snapshot(
    *,
    report_date: str,
    mirror_url: str,
    label: str,
    fetcher: JsonFetcher = fetch_json_url,
) -> dict[str, Any]:
    base_url = _clean_base_url(mirror_url)
    health = fetch_json_busted(
        f"{base_url}/health.json",
        label=label,
        key=report_date,
        timeout=20,
        fetcher=fetcher,
    )
    archive = fetch_json_busted(
        f"{base_url}/archive.json",
        label=label,
        key=report_date,
        timeout=20,
        fetcher=fetcher,
    )
    mirror_date = str(health.get("report_date") or "") if isinstance(health, dict) else ""
    article_count = int(health.get("article_count") or 0) if isinstance(health, dict) else 0
    archive_count = issue_article_count(archive, report_date)
    return {
        "health": health,
        "archive": archive,
        "report_date": mirror_date,
        "article_count": article_count,
        "archive_count": archive_count,
        "fresh": mirror_date == report_date and article_count > 0 and archive_count == article_count,
    }


def mirror_freshness(
    *,
    report_date: str,
    mirror_url: str,
    event_name: str,
    fetcher: JsonFetcher = fetch_json_url,
) -> dict[str, Any]:
    if event_name != "schedule":
        return {
            "should_run": True,
            "reason": "manual run",
            "public_date": "",
            "public_article_count": 0,
            "public_archive_count": 0,
        }

    mirror_date = ""
    article_count = 0
    archive_count = 0
    mirror_error = ""
    mirror_fresh = False
    try:
        snapshot = mirror_snapshot(
            report_date=report_date,
            mirror_url=mirror_url,
            label="freshness",
            fetcher=fetcher,
        )
        mirror_date = str(snapshot["report_date"])
        article_count = int(snapshot["article_count"])
        archive_count = int(snapshot["archive_count"])
        mirror_fresh = bool(snapshot["fresh"])
    except (OSError, json.JSONDecodeError, ValueError, TimeoutError) as exc:
        mirror_error = str(exc)

    if mirror_fresh:
        should_run = False
        reason = f"mirror already fresh ({mirror_date}/{article_count})"
    else:
        should_run = True
        reason = (
            "mirror stale "
            f"(mirror={mirror_date or 'missing'}/{article_count}/{archive_count}"
            f"{' error=' + mirror_error if mirror_error else ''}, expected={report_date})"
        )

    return {
        "should_run": should_run,
        "reason": reason,
        "public_date": mirror_date,
        "public_article_count": article_count,
        "public_archive_count": archive_count,
    }


def check_local_artifacts(site_dir: Path) -> dict[str, Any]:
    health_path = site_dir / "health.json"
    archive_path = site_dir / "archive.json"
    health = json.loads(health_path.read_text(encoding="utf-8"))
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    missing = sorted(path for path in NEWSLETTER_REQUIRED_FILES if not (site_dir / path).exists())
    if missing:
        raise RuntimeError(f"Missing generated files: {', '.join(missing)}")
    article_count = int(health.get("article_count") or 0)
    if article_count <= 0:
        raise RuntimeError("article_count is 0; keeping the existing public newsletter instead of publishing an empty issue")
    if not isinstance(archive, list):
        raise RuntimeError("archive.json must be a list")
    return {
        "health": health,
        "archive_count": len(archive),
        "article_count": article_count,
    }


def download_verified_archive(
    *,
    requested_report_date: str,
    mirror_url: str,
    out_path: Path,
    fetcher: JsonFetcher = fetch_json_url,
) -> dict[str, Any]:
    snapshot = syncable_public_archive_snapshot(
        requested_report_date=requested_report_date,
        mirror_url=mirror_url,
        label="sync",
        fetcher=fetcher,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot["archive"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "source": snapshot["source"],
        "report_date": snapshot["report_date"],
        "article_count": snapshot["article_count"],
        "archive_count": snapshot["archive_count"],
        "archive_path": str(out_path),
    }


def verify_public_mirror(
    *,
    report_date: str,
    mirror_url: str,
    expected_health_path: Path,
    expected_archive_path: Path,
    deadline_seconds: int = 180,
    poll_seconds: int = 10,
    fetcher: JsonFetcher = fetch_json_url,
) -> dict[str, Any]:
    expected_health = json.loads(expected_health_path.read_text(encoding="utf-8"))
    expected_archive = json.loads(expected_archive_path.read_text(encoding="utf-8"))
    expected_built_at = str(expected_health.get("built_at") or "")
    expected_article_count = int(expected_health.get("article_count") or 0)
    expected_archive_count = issue_article_count(expected_archive, report_date)
    if expected_article_count <= 0 or expected_archive_count != expected_article_count:
        raise RuntimeError(
            "local newsletter artifact is invalid before public verification "
            f"(health={expected_article_count}, archive={expected_archive_count})"
        )

    base_url = _clean_base_url(mirror_url)
    deadline = time.time() + deadline_seconds
    last_error = ""
    while True:
        try:
            health = fetch_json_busted(
                f"{base_url}/health.json",
                label="verify",
                key=report_date,
                timeout=15,
                fetcher=fetcher,
            )
            archive = fetch_json_busted(
                f"{base_url}/archive.json",
                label="verify",
                key=report_date,
                timeout=15,
                fetcher=fetcher,
            )
            if not isinstance(health, dict):
                raise RuntimeError("health.json is not an object")
            if health.get("report_date") != report_date:
                raise RuntimeError(f"health report_date={health.get('report_date')} expected={report_date}")
            if health.get("services") != "newsletter":
                raise RuntimeError(f"health services={health.get('services')} expected=newsletter")
            if str(health.get("built_at") or "") != expected_built_at:
                raise RuntimeError(f"health built_at={health.get('built_at')} expected={expected_built_at}")
            article_count = int(health.get("article_count") or 0)
            if article_count != expected_article_count:
                raise RuntimeError(f"health article_count={article_count} expected={expected_article_count}")
            for key in NEWSLETTER_ONLY_ZERO_HEALTH_KEYS:
                if int(health.get(key) or 0) != 0:
                    raise RuntimeError(f"newsletter-only health {key}={health.get(key)} expected=0")
            archive_count = issue_article_count(archive, report_date)
            if archive_count != expected_archive_count:
                raise RuntimeError(f"archive article_count={archive_count} expected={expected_archive_count}")
            return {
                "report_date": report_date,
                "health_articles": article_count,
                "archive_articles": archive_count,
            }
        except Exception as exc:  # noqa: BLE001 - status loop reports the last failure.
            last_error = str(exc)
            print(f"public_verify_wait={last_error}")
            if time.time() > deadline:
                raise RuntimeError(f"public verification failed: {last_error}") from exc
            time.sleep(poll_seconds)


def verify_vercel_app(
    *,
    report_date: str,
    app_url: str,
    mirror_url: str,
    deadline_seconds: int = 180,
    poll_seconds: int = 10,
    fetcher: JsonFetcher = fetch_json_url,
) -> dict[str, Any]:
    sync_source = syncable_public_archive_snapshot(
        requested_report_date=report_date,
        mirror_url=mirror_url,
        label="verify",
        fetcher=fetcher,
    )
    expected_article_count = int(sync_source["article_count"])
    app_base_url = _clean_base_url(app_url)
    deadline = time.time() + deadline_seconds
    last_error = ""
    while True:
        try:
            health = fetch_json_busted(
                f"{app_base_url}/health.json?refresh=1",
                label="verify",
                key=report_date,
                timeout=20,
                fetcher=fetcher,
            )
            archive = fetch_json_busted(
                f"{app_base_url}/archive.json?refresh=1",
                label="verify",
                key=report_date,
                timeout=20,
                fetcher=fetcher,
            )
            if not isinstance(health, dict):
                raise RuntimeError("app health.json is not an object")
            if health.get("report_date") != report_date:
                raise RuntimeError(f"app report_date={health.get('report_date')} expected={report_date}")
            if health.get("data_source") != "supabase":
                raise RuntimeError(f"app data_source={health.get('data_source')} expected=supabase")
            article_count = int(health.get("article_count") or 0)
            if article_count != expected_article_count:
                raise RuntimeError(f"app article_count={article_count} expected={expected_article_count}")
            archive_count = issue_article_count(archive, report_date)
            if archive_count != expected_article_count:
                raise RuntimeError(f"app archive_count={archive_count} expected={expected_article_count}")
            return {
                "report_date": report_date,
                "article_count": article_count,
                "archive_count": archive_count,
                "source": sync_source["source"],
            }
        except Exception as exc:  # noqa: BLE001 - status loop reports the last failure.
            last_error = str(exc)
            print(f"supabase_recovery_verify_wait={last_error}")
            if time.time() > deadline:
                raise RuntimeError(f"Vercel verification failed after Supabase sync: {last_error}") from exc
            time.sleep(poll_seconds)


def watchdog_freshness(
    *,
    report_date: str,
    mirror_url: str,
    app_url: str,
    fetcher: JsonFetcher = fetch_json_url,
) -> dict[str, Any]:
    mirror_fresh = False
    sync_source_fresh = False
    app_fresh = False
    mirror_status = "missing"
    sync_source_status = "missing"
    app_status = "missing"

    try:
        mirror = mirror_snapshot(
            report_date=report_date,
            mirror_url=mirror_url,
            label="watchdog",
            fetcher=fetcher,
        )
        mirror_fresh = bool(mirror["fresh"])
        mirror_status = f"{mirror['report_date'] or 'missing'}/{mirror['article_count']}/{mirror['archive_count']}"
        if mirror_fresh:
            sync_source_fresh = True
            sync_source_status = f"pages_mirror/{mirror_status}"
    except (OSError, json.JSONDecodeError, ValueError, TimeoutError) as exc:
        mirror_status = f"error:{exc}"

    if not sync_source_fresh:
        try:
            sync_source = syncable_public_archive_snapshot(
                requested_report_date=report_date,
                mirror_url=mirror_url,
                label="watchdog",
                fetcher=fetcher,
            )
            sync_source_fresh = True
            sync_source_status = (
                f"{sync_source['source']}/{sync_source['report_date']}/"
                f"{sync_source['article_count']}/{sync_source['archive_count']}"
            )
        except (OSError, json.JSONDecodeError, ValueError, TimeoutError, RuntimeError) as exc:
            sync_source_status = f"error:{exc}"

    app_base_url = _clean_base_url(app_url)
    try:
        health = fetch_json_busted(
            f"{app_base_url}/health.json?refresh=1",
            label="watchdog",
            key=report_date,
            timeout=20,
            fetcher=fetcher,
        )
        if not isinstance(health, dict):
            raise ValueError("app health.json is not an object")
        app_date = str(health.get("report_date") or "")
        app_articles = int(health.get("article_count") or 0)
        app_source = str(health.get("data_source") or "")
        app_fresh = (
            app_date == report_date
            and app_articles > 0
            and app_source in WATCHDOG_APP_FRESH_DATA_SOURCES
        )
        app_status = f"{app_date or 'missing'}/{app_articles}/{app_source or 'missing'}"
    except (OSError, json.JSONDecodeError, ValueError, TimeoutError) as exc:
        app_status = f"error:{exc}"

    stale = not (sync_source_fresh and app_fresh)
    reason = (
        f"expected={report_date} mirror={mirror_status} sync_source={sync_source_status} "
        f"app={app_status} stale={'true' if stale else 'false'}"
    )
    return {
        "stale": stale,
        "mirror_fresh": mirror_fresh,
        "sync_source_fresh": sync_source_fresh,
        "app_fresh": app_fresh,
        "reason": reason,
    }


def github_output_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).replace("\n", " ")


def emit_github_outputs(values: dict[str, Any]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={github_output_value(value)}\n")


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check public newsletter status and deployment contracts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    mirror_parser = subparsers.add_parser("mirror-freshness")
    mirror_parser.add_argument("--report-date", required=True)
    mirror_parser.add_argument("--mirror-url", required=True)
    mirror_parser.add_argument("--event-name", required=True)

    local_parser = subparsers.add_parser("check-local-artifacts")
    local_parser.add_argument("--site-dir", type=Path, required=True)

    download_parser = subparsers.add_parser("download-verified-archive")
    download_parser.add_argument("--requested-report-date", default="")
    download_parser.add_argument("--mirror-url", required=True)
    download_parser.add_argument("--out", type=Path, required=True)

    public_parser = subparsers.add_parser("verify-public-mirror")
    public_parser.add_argument("--report-date", required=True)
    public_parser.add_argument("--mirror-url", required=True)
    public_parser.add_argument("--expected-health", type=Path, required=True)
    public_parser.add_argument("--expected-archive", type=Path, required=True)
    public_parser.add_argument("--deadline-seconds", type=int, default=180)
    public_parser.add_argument("--poll-seconds", type=int, default=10)

    vercel_parser = subparsers.add_parser("verify-vercel-app")
    vercel_parser.add_argument("--report-date", required=True)
    vercel_parser.add_argument("--app-url", required=True)
    vercel_parser.add_argument("--mirror-url", required=True)
    vercel_parser.add_argument("--deadline-seconds", type=int, default=180)
    vercel_parser.add_argument("--poll-seconds", type=int, default=10)

    watchdog_parser = subparsers.add_parser("watchdog-freshness")
    watchdog_parser.add_argument("--report-date", required=True)
    watchdog_parser.add_argument("--mirror-url", required=True)
    watchdog_parser.add_argument("--app-url", required=True)

    args = parser.parse_args()

    try:
        if args.command == "mirror-freshness":
            payload = mirror_freshness(
                report_date=args.report_date,
                mirror_url=args.mirror_url,
                event_name=args.event_name,
            )
            emit_github_outputs(payload)
            print(f"newsletter_mirror_freshness should_run={payload['should_run']} reason={payload['reason']}")
        elif args.command == "check-local-artifacts":
            payload = check_local_artifacts(args.site_dir)
            print_json(payload["health"])
            print(f"archive_count={payload['archive_count']}")
        elif args.command == "download-verified-archive":
            payload = download_verified_archive(
                requested_report_date=args.requested_report_date,
                mirror_url=args.mirror_url,
                out_path=args.out,
            )
            emit_github_outputs(
                {
                    "report_date": payload["report_date"],
                    "article_count": payload["article_count"],
                    "source": payload["source"],
                }
            )
            print(
                "public_archive=ok "
                f"source={payload['source']} "
                f"report_date={payload['report_date']} articles={payload['article_count']}"
            )
        elif args.command == "verify-public-mirror":
            payload = verify_public_mirror(
                report_date=args.report_date,
                mirror_url=args.mirror_url,
                expected_health_path=args.expected_health,
                expected_archive_path=args.expected_archive,
                deadline_seconds=args.deadline_seconds,
                poll_seconds=args.poll_seconds,
            )
            print(
                "public_verify_status=ok "
                f"report_date={payload['report_date']} "
                f"health_articles={payload['health_articles']} "
                f"archive_articles={payload['archive_articles']}"
            )
        elif args.command == "verify-vercel-app":
            payload = verify_vercel_app(
                report_date=args.report_date,
                app_url=args.app_url,
                mirror_url=args.mirror_url,
                deadline_seconds=args.deadline_seconds,
                poll_seconds=args.poll_seconds,
            )
            print(
                "supabase_recovery_verify_status=ok "
                f"source={payload['source']} "
                f"report_date={payload['report_date']} articles={payload['article_count']}"
            )
        elif args.command == "watchdog-freshness":
            payload = watchdog_freshness(
                report_date=args.report_date,
                mirror_url=args.mirror_url,
                app_url=args.app_url,
            )
            emit_github_outputs(payload)
            print(f"newsletter_watchdog {payload['reason']}")
        else:  # pragma: no cover - argparse prevents this.
            parser.error(f"unknown command: {args.command}")
    except Exception as exc:  # noqa: BLE001 - CLI should present concise operational failures.
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
