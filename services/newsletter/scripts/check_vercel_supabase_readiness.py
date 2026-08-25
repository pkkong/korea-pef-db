#!/usr/bin/env python3
"""Check whether the standalone newsletter Vercel/Supabase path is deploy-ready."""

from __future__ import annotations

import json
import os
import py_compile
import sys
import argparse
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_ROOT = REPO_ROOT / "services" / "newsletter" / "web"
MIGRATION_PATH = (
    REPO_ROOT
    / "services"
    / "newsletter"
    / "supabase"
    / "migrations"
    / "20260616090000_newsletter_read_model.sql"
)
SYNC_SCRIPT = REPO_ROOT / "services" / "newsletter" / "src" / "sync_newsletter_supabase.py"


def env_state(name: str) -> str:
    return "set" if os.environ.get(name) else "missing"


def compile_python(paths: list[Path]) -> list[str]:
    failures: list[str] = []
    for path in paths:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{path}: {exc.msg}")
    return failures


def check_import_isolation() -> list[str]:
    sys.path.insert(0, str(WEB_ROOT))
    import app  # noqa: F401

    forbidden_roots = [
        "services.lp",
        "services.gp",
        "services.wiki",
        "scripts.build_service_site",
        "services.newsletter.src.build_newsletter_deploy",
    ]
    return [
        name
        for name in sys.modules
        if any(name == root or name.startswith(f"{root}.") for root in forbidden_roots)
    ]


def check_vercel_config() -> list[str]:
    config_path = WEB_ROOT / "vercel.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"vercel.json is invalid JSON: {exc}"]

    failures: list[str] = []
    if config.get("framework") != "flask":
        failures.append("vercel.json must keep framework=flask")

    for rewrite in config.get("rewrites") or []:
        source = rewrite.get("source")
        destination = rewrite.get("destination")
        if source in {"/(.*)", "/:path*"} and destination in {"/index.py", "index.py"}:
            failures.append("vercel.json must not rewrite every request to /index.py")
    return failures


def smoke_flask_app() -> None:
    sys.path.insert(0, str(WEB_ROOT))
    from app import app  # noqa: E402

    client = app.test_client()
    for path in ["/", "/daily-news.html", "/health.json", "/archive.json"]:
        response = client.get(path)
        if response.status_code != 200:
            raise SystemExit(f"{path} returned {response.status_code}")
    health = client.get("/health.json").get_json()
    if health.get("service") != "newsletter":
        raise SystemExit(f"unexpected health payload: {health}")
    print(f"newsletter_vercel_smoke=ok report_date={health.get('report_date')} articles={health.get('article_count')}")


def print_step_summary(payload_path: Path) -> None:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    print("### Newsletter Vercel/Supabase readiness")
    print("")
    print("| Check | Status |")
    print("| --- | --- |")
    for key in ["files", "compile", "import_isolation", "vercel_config"]:
        print(f"| `{key}` | {payload.get(key)} |")
    print("")
    print("| Secret | Status |")
    print("| --- | --- |")
    for key, value in sorted((payload.get("env") or {}).items()):
        print(f"| `{key}` | {value} |")
    print("")
    if any(value == "missing" for value in (payload.get("env") or {}).values()):
        print("Missing secrets are expected before production Vercel/Supabase connection.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check standalone newsletter Vercel/Supabase readiness.")
    parser.add_argument("--smoke-app", action="store_true", help="Smoke-test the Flask app routes and exit.")
    parser.add_argument("--summary-from", type=Path, help="Write a GitHub step summary from readiness JSON and exit.")
    args = parser.parse_args()

    if args.smoke_app:
        smoke_flask_app()
        return 0
    if args.summary_from:
        print_step_summary(args.summary_from)
        return 0

    missing_files = [
        str(path)
        for path in [
            WEB_ROOT / "app.py",
            WEB_ROOT / "index.py",
            WEB_ROOT / "newsletter_data.py",
            WEB_ROOT / "newsletter_ui.py",
            WEB_ROOT / "gp_public_data.py",
            WEB_ROOT / "requirements.txt",
            WEB_ROOT / "vercel.json",
            MIGRATION_PATH,
            SYNC_SCRIPT,
        ]
        if not path.exists()
    ]
    compile_failures = compile_python(
        [
            WEB_ROOT / "app.py",
            WEB_ROOT / "index.py",
            WEB_ROOT / "newsletter_data.py",
            WEB_ROOT / "newsletter_ui.py",
            WEB_ROOT / "gp_public_data.py",
            SYNC_SCRIPT,
        ]
    )
    isolation_failures = check_import_isolation()
    vercel_config_failures = check_vercel_config()
    payload = {
        "files": "ok" if not missing_files else "missing",
        "missing_files": missing_files,
        "compile": "ok" if not compile_failures else "failed",
        "compile_failures": compile_failures,
        "import_isolation": "ok" if not isolation_failures else "failed",
        "forbidden_imports": isolation_failures,
        "vercel_config": "ok" if not vercel_config_failures else "failed",
        "vercel_config_failures": vercel_config_failures,
        "env": {
            "VERCEL_TOKEN": env_state("VERCEL_TOKEN"),
            "VERCEL_ORG_ID": env_state("VERCEL_ORG_ID"),
            "VERCEL_PROJECT_ID": env_state("VERCEL_PROJECT_ID"),
            "SUPABASE_DB_URL": env_state("SUPABASE_DB_URL"),
            "SUPABASE_URL": env_state("SUPABASE_URL"),
            "SUPABASE_PUBLISHABLE_KEY": env_state("SUPABASE_PUBLISHABLE_KEY"),
            "SUPABASE_SERVICE_ROLE_KEY": env_state("SUPABASE_SERVICE_ROLE_KEY"),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    hard_failures = missing_files or compile_failures or isolation_failures or vercel_config_failures
    return 1 if hard_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
