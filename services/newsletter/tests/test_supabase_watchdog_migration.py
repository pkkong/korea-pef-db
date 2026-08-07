#!/usr/bin/env python3
"""No-network checks for the Supabase external newsletter watchdog migration."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPO_ROOT
    / "services"
    / "newsletter"
    / "supabase"
    / "migrations"
    / "20260807093000_newsletter_external_watchdog_cron.sql"
)


def read_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_installs_required_supabase_extensions() -> None:
    sql = read_sql()

    assert "CREATE EXTENSION IF NOT EXISTS pg_net" in sql
    assert "CREATE EXTENSION IF NOT EXISTS pg_cron" in sql
    assert "CREATE EXTENSION IF NOT EXISTS supabase_vault" in sql


def test_migration_dispatches_existing_github_watchdog() -> None:
    sql = read_sql()

    assert "newsletter_ops.dispatch_newsletter_watchdog" in sql
    assert "newsletter-watchdog.yml/dispatches" in sql
    assert "'ref', 'main'" in sql
    assert "'report_date', resolved_report_date::TEXT" in sql
    assert "'dry_run', 'false'" in sql


def test_migration_uses_supabase_vault_secret_without_plaintext_token() -> None:
    sql = read_sql()

    assert "vault.decrypted_secrets" in sql
    assert "newsletter_github_actions_dispatch_token" in sql
    assert "github_pat_" not in sql
    assert "ghp_" not in sql


def test_migration_schedules_four_external_retry_windows() -> None:
    sql = read_sql()

    expected_jobs = {
        "newsletter-external-watchdog-0905-kst": "5 0 * * *",
        "newsletter-external-watchdog-0935-kst": "35 0 * * *",
        "newsletter-external-watchdog-1005-kst": "5 1 * * *",
        "newsletter-external-watchdog-1035-kst": "35 1 * * *",
    }
    for job_name, schedule in expected_jobs.items():
        assert job_name in sql
        assert schedule in sql


def test_migration_logs_and_does_not_error_when_token_missing() -> None:
    sql = read_sql()

    assert "newsletter_external_watchdog_runs" in sql
    assert "skipped_missing_token" in sql
    assert "failed_to_queue" in sql
    assert "RETURN NULL" in sql


def main() -> int:
    test_migration_installs_required_supabase_extensions()
    test_migration_dispatches_existing_github_watchdog()
    test_migration_uses_supabase_vault_secret_without_plaintext_token()
    test_migration_schedules_four_external_retry_windows()
    test_migration_logs_and_does_not_error_when_token_missing()
    print("supabase watchdog migration tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
