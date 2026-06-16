#!/usr/bin/env python3
"""Check whether the standalone newsletter Vercel/Supabase path is deploy-ready."""

from __future__ import annotations

import json
import os
import py_compile
import sys
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


def main() -> int:
    missing_files = [
        str(path)
        for path in [
            WEB_ROOT / "app.py",
            WEB_ROOT / "index.py",
            WEB_ROOT / "newsletter_data.py",
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
            SYNC_SCRIPT,
        ]
    )
    isolation_failures = check_import_isolation()
    payload = {
        "files": "ok" if not missing_files else "missing",
        "missing_files": missing_files,
        "compile": "ok" if not compile_failures else "failed",
        "compile_failures": compile_failures,
        "import_isolation": "ok" if not isolation_failures else "failed",
        "forbidden_imports": isolation_failures,
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
    hard_failures = missing_files or compile_failures or isolation_failures
    return 1 if hard_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
