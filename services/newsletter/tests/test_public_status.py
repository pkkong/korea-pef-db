#!/usr/bin/env python3
"""No-network tests for newsletter public status checks."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.newsletter.src.newsletter_public_status import (
    download_verified_archive,
    mirror_freshness,
    verify_public_mirror,
    verify_vercel_app,
    watchdog_freshness,
)


REPORT_DATE = "2026-06-21"
ARCHIVE = [
    {
        "reportDate": REPORT_DATE,
        "articles": [
            {"title": "A", "url": "https://example.com/a"},
            {"title": "B", "url": "https://example.com/b"},
        ],
    },
    {"reportDate": "2026-06-20", "articles": []},
]
MIRROR_HEALTH = {
    "service": "kpef-newsletter",
    "services": "newsletter",
    "status": "ok",
    "built_at": "2026-06-21T00:00:00+00:00",
    "report_date": REPORT_DATE,
    "article_count": 2,
    "lp_monitor_count": 0,
    "gp_count": 0,
    "gp_profile_page_count": 0,
}
APP_HEALTH = {
    "service": "newsletter",
    "runtime": "vercel-flask",
    "status": "ok",
    "data_source": "supabase",
    "report_date": REPORT_DATE,
    "article_count": 2,
    "issue_count": 2,
}
STALE_MIRROR_HEALTH = {
    **MIRROR_HEALTH,
    "built_at": "2026-06-20T00:00:00+00:00",
    "report_date": "2026-06-20",
    "article_count": 1,
}
STALE_ARCHIVE = [
    {"reportDate": "2026-06-20", "articles": [{"title": "Old", "url": "https://example.com/old"}]},
]


def fake_fetcher(url: str, timeout: int = 20) -> object:
    if url.startswith("https://mirror.example/health.json"):
        return dict(MIRROR_HEALTH)
    if url.startswith("https://mirror.example/archive.json"):
        return list(ARCHIVE)
    if url.startswith("https://app.example/health.json"):
        return dict(APP_HEALTH)
    if url.startswith("https://app.example/archive.json"):
        return list(ARCHIVE)
    raise AssertionError(f"unexpected URL: {url}")


def stale_app_fetcher(url: str, timeout: int = 20) -> object:
    if url.startswith("https://app.example/health.json"):
        stale = dict(APP_HEALTH)
        stale["report_date"] = "2026-06-20"
        return stale
    return fake_fetcher(url, timeout)


def github_pages_lag_fetcher(url: str, timeout: int = 20) -> object:
    if url.startswith("https://pkkong.github.io/kpef-newsletter/health.json"):
        return dict(STALE_MIRROR_HEALTH)
    if url.startswith("https://pkkong.github.io/kpef-newsletter/archive.json"):
        return list(STALE_ARCHIVE)
    if url.startswith("https://raw.githubusercontent.com/pkkong/kpef-newsletter/gh-pages/health.json"):
        return dict(MIRROR_HEALTH)
    if url.startswith("https://raw.githubusercontent.com/pkkong/kpef-newsletter/gh-pages/archive.json"):
        return list(ARCHIVE)
    return fake_fetcher(url, timeout)


def github_pages_lag_stale_app_fetcher(url: str, timeout: int = 20) -> object:
    if url.startswith("https://app.example/health.json"):
        stale = dict(APP_HEALTH)
        stale["report_date"] = "2026-06-20"
        return stale
    return github_pages_lag_fetcher(url, timeout)


def github_pages_lag_archive_fallback_app_fetcher(url: str, timeout: int = 20) -> object:
    if url.startswith("https://app.example/health.json"):
        fallback = dict(APP_HEALTH)
        fallback["data_source"] = "archive_fallback"
        return fallback
    return github_pages_lag_fetcher(url, timeout)


def test_mirror_freshness_skips_network_for_manual_runs() -> None:
    def fail_fetcher(url: str, timeout: int = 20) -> object:
        raise AssertionError("manual freshness should not fetch public URLs")

    payload = mirror_freshness(
        report_date=REPORT_DATE,
        mirror_url="https://mirror.example",
        event_name="workflow_dispatch",
        fetcher=fail_fetcher,
    )

    assert payload["should_run"] is True
    assert payload["reason"] == "manual run"


def test_mirror_freshness_detects_already_fresh_schedule() -> None:
    payload = mirror_freshness(
        report_date=REPORT_DATE,
        mirror_url="https://mirror.example",
        event_name="schedule",
        fetcher=fake_fetcher,
    )

    assert payload["should_run"] is False
    assert payload["public_article_count"] == 2
    assert payload["public_archive_count"] == 2


def test_download_verified_archive_writes_syncable_archive() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "public_archive.json"
        payload = download_verified_archive(
            requested_report_date="",
            mirror_url="https://mirror.example",
            out_path=out,
            fetcher=fake_fetcher,
        )

        assert payload["report_date"] == REPORT_DATE
        assert payload["article_count"] == 2
        assert payload["source"] == "pages_mirror"
        assert json.loads(out.read_text(encoding="utf-8")) == ARCHIVE


def test_download_verified_archive_uses_raw_github_pages_when_pages_lag() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "public_archive.json"
        payload = download_verified_archive(
            requested_report_date=REPORT_DATE,
            mirror_url="https://pkkong.github.io/kpef-newsletter",
            out_path=out,
            fetcher=github_pages_lag_fetcher,
        )

        assert payload["report_date"] == REPORT_DATE
        assert payload["article_count"] == 2
        assert payload["source"] == "raw_github_pages"
        assert json.loads(out.read_text(encoding="utf-8")) == ARCHIVE


def test_verify_public_mirror_matches_local_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        health = root / "health.json"
        archive = root / "archive.json"
        health.write_text(json.dumps(MIRROR_HEALTH), encoding="utf-8")
        archive.write_text(json.dumps(ARCHIVE), encoding="utf-8")

        payload = verify_public_mirror(
            report_date=REPORT_DATE,
            mirror_url="https://mirror.example",
            expected_health_path=health,
            expected_archive_path=archive,
            deadline_seconds=0,
            fetcher=fake_fetcher,
        )

        assert payload["health_articles"] == 2
        assert payload["archive_articles"] == 2


def test_verify_vercel_app_requires_supabase_and_mirror_count_match() -> None:
    payload = verify_vercel_app(
        report_date=REPORT_DATE,
        app_url="https://app.example",
        mirror_url="https://mirror.example",
        deadline_seconds=0,
        fetcher=fake_fetcher,
    )

    assert payload["article_count"] == 2
    assert payload["archive_count"] == 2


def test_verify_vercel_app_uses_raw_github_pages_count_when_pages_lag() -> None:
    payload = verify_vercel_app(
        report_date=REPORT_DATE,
        app_url="https://app.example",
        mirror_url="https://pkkong.github.io/kpef-newsletter",
        deadline_seconds=0,
        fetcher=github_pages_lag_fetcher,
    )

    assert payload["article_count"] == 2
    assert payload["archive_count"] == 2
    assert payload["source"] == "raw_github_pages"


def test_watchdog_freshness_dispatches_only_stale_side() -> None:
    payload = watchdog_freshness(
        report_date=REPORT_DATE,
        mirror_url="https://mirror.example",
        app_url="https://app.example",
        fetcher=stale_app_fetcher,
    )

    assert payload["stale"] is True
    assert payload["mirror_fresh"] is True
    assert payload["sync_source_fresh"] is True
    assert payload["app_fresh"] is False


def test_watchdog_uses_raw_github_pages_as_sync_source_when_pages_lag() -> None:
    payload = watchdog_freshness(
        report_date=REPORT_DATE,
        mirror_url="https://pkkong.github.io/kpef-newsletter",
        app_url="https://app.example",
        fetcher=github_pages_lag_stale_app_fetcher,
    )

    assert payload["stale"] is True
    assert payload["mirror_fresh"] is False
    assert payload["sync_source_fresh"] is True
    assert payload["app_fresh"] is False
    assert "raw_github_pages" in payload["reason"]


def test_watchdog_accepts_archive_fallback_app_when_pages_lag() -> None:
    payload = watchdog_freshness(
        report_date=REPORT_DATE,
        mirror_url="https://pkkong.github.io/kpef-newsletter",
        app_url="https://app.example",
        fetcher=github_pages_lag_archive_fallback_app_fetcher,
    )

    assert payload["stale"] is False
    assert payload["mirror_fresh"] is False
    assert payload["sync_source_fresh"] is True
    assert payload["app_fresh"] is True


def main() -> int:
    test_mirror_freshness_skips_network_for_manual_runs()
    test_mirror_freshness_detects_already_fresh_schedule()
    test_download_verified_archive_writes_syncable_archive()
    test_download_verified_archive_uses_raw_github_pages_when_pages_lag()
    test_verify_public_mirror_matches_local_artifacts()
    test_verify_vercel_app_requires_supabase_and_mirror_count_match()
    test_verify_vercel_app_uses_raw_github_pages_count_when_pages_lag()
    test_watchdog_freshness_dispatches_only_stale_side()
    test_watchdog_uses_raw_github_pages_as_sync_source_when_pages_lag()
    test_watchdog_accepts_archive_fallback_app_when_pages_lag()
    print("newsletter public status tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
