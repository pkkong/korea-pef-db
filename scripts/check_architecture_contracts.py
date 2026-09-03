#!/usr/bin/env python3
"""Check cross-service architecture and workflow responsibility contracts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_BOUNDARY_DIRS = [
    REPO_ROOT / "services" / "lp",
    REPO_ROOT / "services" / "gp",
    REPO_ROOT / "services" / "wiki",
]
NEWSLETTER_WORKFLOWS = [
    REPO_ROOT / ".github" / "workflows" / "deploy-newsletter-pages.yml",
    REPO_ROOT / ".github" / "workflows" / "sync-newsletter-supabase.yml",
    REPO_ROOT / ".github" / "workflows" / "newsletter-watchdog.yml",
    REPO_ROOT / ".github" / "workflows" / "deploy-newsletter-vercel.yml",
    REPO_ROOT / ".github" / "workflows" / "check-newsletter-vercel-readiness.yml",
    REPO_ROOT / ".github" / "workflows" / "apply-newsletter-supabase-migration.yml",
]
DIRECT_NEWSLETTER_SRC_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+services\.newsletter\.src(?:\.|\s|$)"
)
GENERATED_TRACKED_PATTERNS = (
    "services/newsletter/deploy/site/",
    "exports/",
    "public/",
)
LP_SCHEMA_PATH = REPO_ROOT / "schema" / "lp_commitments.sql"
LP_CROSS_SERVICE_FOREIGN_KEY_REFS = (
    "REFERENCES gp_house",
    "REFERENCES news_document",
)


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def check_no_cross_service_newsletter_src_imports() -> list[str]:
    violations: list[str] = []
    for directory in SERVICE_BOUNDARY_DIRS:
        for path in sorted(directory.rglob("*.py")):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if DIRECT_NEWSLETTER_SRC_IMPORT_RE.search(line):
                    violations.append(f"{rel(path)}:{line_number}:{line.strip()}")
    return violations


def check_lp_schema_is_service_local() -> list[str]:
    schema_text = LP_SCHEMA_PATH.read_text(encoding="utf-8")
    return [
        f"{rel(LP_SCHEMA_PATH)}:{reference}"
        for reference in LP_CROSS_SERVICE_FOREIGN_KEY_REFS
        if reference in schema_text
    ]


def run_python(code: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def check_import_isolation() -> list[str]:
    checks = {
        "newsletter_bundle": """
import importlib, json, sys
importlib.import_module("scripts.build_newsletter_bundle")
bad = sorted(
    name for name in sys.modules
    if name == "services.lp" or name.startswith("services.lp.")
    or name == "services.gp" or name.startswith("services.gp.")
    or name == "services.wiki" or name.startswith("services.wiki.")
    or name in {"build_service_site", "scripts.build_service_site"}
    or name == "services.lp.src.lp_legacy_service_pages"
)
print(json.dumps(bad, ensure_ascii=False))
raise SystemExit(1 if bad else 0)
""",
        "lp_builder_import": """
import importlib, json, sys
importlib.import_module("services.lp.src.build_lp_service_pages")
bad = sorted(
    name for name in sys.modules
    if name == "services.gp" or name.startswith("services.gp.")
    or name == "services.wiki" or name.startswith("services.wiki.")
    or name in {"build_service_site", "scripts.build_service_site"}
    or name == "services.lp.src.lp_legacy_service_pages"
)
print(json.dumps(bad, ensure_ascii=False))
raise SystemExit(1 if bad else 0)
""",
        "lp_legacy_import": """
import importlib, json, sys
importlib.import_module("services.lp.src.lp_legacy_service_pages")
bad = sorted(
    name for name in sys.modules
    if name == "services.gp" or name.startswith("services.gp.")
    or name == "services.wiki" or name.startswith("services.wiki.")
)
print(json.dumps(bad, ensure_ascii=False))
raise SystemExit(1 if bad else 0)
""",
        "vercel_app": """
import importlib, json, sys
importlib.import_module("services.newsletter.web.app")
bad = sorted(
    name for name in sys.modules
    if name == "services.lp" or name.startswith("services.lp.")
    or name == "services.gp" or name.startswith("services.gp.")
    or name == "services.wiki" or name.startswith("services.wiki.")
    or name in {"build_service_site", "scripts.build_service_site"}
    or name == "services.newsletter.src.build_newsletter_deploy"
)
print(json.dumps(bad, ensure_ascii=False))
raise SystemExit(1 if bad else 0)
""",
    }
    violations: list[str] = []
    for name, code in checks.items():
        returncode, stdout, stderr = run_python(code)
        if returncode != 0:
            details = (stdout or stderr).strip()
            violations.append(f"{name}:{details}")
    return violations


def check_workflow_contracts() -> list[str]:
    violations: list[str] = []
    workflow_text = {path.name: path.read_text(encoding="utf-8") for path in NEWSLETTER_WORKFLOWS}
    for name, text in workflow_text.items():
        if "<<'PY'" in text or 'python3 - <<' in text or 'python3 - "' in text:
            violations.append(f"{name}:inline_python")

    mirror = workflow_text["deploy-newsletter-pages.yml"]
    if "sync_newsletter_supabase.py" in mirror:
        violations.append("deploy-newsletter-pages.yml:must_not_sync_supabase")
    if "NEWSLETTER_APP_URL" in mirror:
        violations.append("deploy-newsletter-pages.yml:must_not_verify_vercel")
    for required in [
        "newsletter_public_status.py mirror-freshness",
        "newsletter_public_status.py check-local-artifacts",
        "newsletter_public_status.py verify-public-mirror",
        'gh workflow run "Sync newsletter Supabase read model"',
    ]:
        if required not in mirror:
            violations.append(f"deploy-newsletter-pages.yml:missing:{required}")

    sync = workflow_text["sync-newsletter-supabase.yml"]
    if re.search(r"(?m)^  schedule:\s*$", sync):
        violations.append("sync-newsletter-supabase.yml:must_not_have_schedule")
    for forbidden in ["run_daily_news_pipeline.py", "build_newsletter_bundle.py", "vercel deploy"]:
        if forbidden in sync:
            violations.append(f"sync-newsletter-supabase.yml:forbidden:{forbidden}")
    for required in [
        "sync_newsletter_supabase.py",
        "newsletter_public_status.py download-verified-archive",
        "newsletter_public_status.py verify-vercel-app",
        "NEWSLETTER_APP_URL",
    ]:
        if required not in sync:
            violations.append(f"sync-newsletter-supabase.yml:missing:{required}")

    vercel = workflow_text["deploy-newsletter-vercel.yml"]
    for forbidden in ["run_daily_news_pipeline.py", "build_newsletter_bundle.py", "sync_newsletter_supabase.py", "SUPABASE_SERVICE_ROLE_KEY"]:
        if forbidden in vercel:
            violations.append(f"deploy-newsletter-vercel.yml:forbidden:{forbidden}")
    if "vercel deploy --prod" not in vercel:
        violations.append("deploy-newsletter-vercel.yml:missing:vercel deploy --prod")

    migration = workflow_text["apply-newsletter-supabase-migration.yml"]
    if "SUPABASE_DB_URL" not in migration or "psql" not in migration:
        violations.append("apply-newsletter-supabase-migration.yml:must_apply_db_url_with_psql")
    if "services/newsletter/supabase/migrations/*.sql" not in migration:
        violations.append("apply-newsletter-supabase-migration.yml:must_apply_all_newsletter_migrations")
    if "NEWSLETTER_WATCHDOG_DISPATCH_TOKEN" not in migration:
        violations.append("apply-newsletter-supabase-migration.yml:missing:NEWSLETTER_WATCHDOG_DISPATCH_TOKEN")
    if "newsletter_github_actions_dispatch_token" not in migration:
        violations.append("apply-newsletter-supabase-migration.yml:missing:vault_watchdog_token")
    for forbidden in ["vercel deploy", "run_daily_news_pipeline.py", "build_newsletter_bundle.py"]:
        if forbidden in migration:
            violations.append(f"apply-newsletter-supabase-migration.yml:forbidden:{forbidden}")

    watchdog = workflow_text["newsletter-watchdog.yml"]
    if "newsletter_public_status.py watchdog-freshness" not in watchdog:
        violations.append("newsletter-watchdog.yml:missing:watchdog-freshness")
    if "gh_with_retry()" not in watchdog:
        violations.append("newsletter-watchdog.yml:missing:github_api_retry_wrapper")
    if "later watchdog windows will retry" not in watchdog:
        violations.append("newsletter-watchdog.yml:missing:soft_fail_for_transient_github_api_errors")
    return violations


def check_generated_outputs_untracked() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return [f"git_ls_files:{proc.stderr.strip() or proc.returncode}"]
    violations: list[str] = []
    for path in proc.stdout.splitlines():
        if path.startswith(GENERATED_TRACKED_PATTERNS) or re.fullmatch(r"db/.*\.(?:db|sqlite|sqlite3)", path):
            violations.append(path)
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Check repository architecture contracts")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable result JSON")
    args = parser.parse_args()

    sections = {
        "cross_service_newsletter_src_imports": check_no_cross_service_newsletter_src_imports(),
        "lp_schema_service_local": check_lp_schema_is_service_local(),
        "import_isolation": check_import_isolation(),
        "workflow_contracts": check_workflow_contracts(),
        "generated_outputs_untracked": check_generated_outputs_untracked(),
    }
    failures = {name: values for name, values in sections.items() if values}
    if args.json:
        print(json.dumps({"status": "fail" if failures else "ok", "failures": failures}, ensure_ascii=False, indent=2))
    else:
        if failures:
            print("FAIL architecture contracts")
            for name, values in failures.items():
                print(f"- {name}:")
                for value in values:
                    print(f"  - {value}")
        else:
            print("OK architecture contracts")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
