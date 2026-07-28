#!/usr/bin/env python3
"""Check newsletter GitHub Actions readiness without printing secret values."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


MIRROR_WORKFLOW_PATH = Path(".github/workflows/deploy-newsletter-pages.yml")
SYNC_WORKFLOW_PATH = Path(".github/workflows/sync-newsletter-supabase.yml")
EXPECTED_CRON = "37 23 * * *"
MIRROR_EXPECTED_SECRETS = (
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "NEWSLETTER_PUBLIC_REPO_TOKEN",
)
SYNC_EXPECTED_SECRETS = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
)
EXPECTED_SECRETS = MIRROR_EXPECTED_SECRETS + SYNC_EXPECTED_SECRETS


def run(args: list[str], cwd: Path, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def find_repo_root() -> Path:
    proc = run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if proc.returncode == 0:
        return Path(proc.stdout.strip())
    return Path(__file__).resolve().parents[3]


def infer_repo_name(repo_root: Path) -> str:
    proc = run(["git", "config", "--get", "remote.origin.url"], repo_root)
    if proc.returncode != 0:
        return "pkkong/korea-pef-db"

    remote = proc.stdout.strip()
    if remote.endswith(".git"):
        remote = remote[:-4]
    match = re.search(r"github\.com[:/](?P<path>[^/]+/[^/]+)$", remote)
    if match:
        return match.group("path")
    return "pkkong/korea-pef-db"


def first_error_line(proc: subprocess.CompletedProcess[str]) -> str:
    output = (proc.stderr or proc.stdout).strip()
    if not output:
        return f"exit code {proc.returncode}"
    return output.splitlines()[0]


def load_gh_secret_names(repo_root: Path, repo_name: str) -> tuple[set[str] | None, str | None]:
    gh_path = shutil.which("gh")
    if not gh_path:
        return None, "gh CLI not found"

    proc = run([gh_path, "secret", "list", "--repo", repo_name, "--json", "name"], repo_root)
    if proc.returncode == 0:
        try:
            return {item["name"] for item in json.loads(proc.stdout)}, None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return None, f"could not parse gh JSON output: {exc}"

    fallback = run([gh_path, "secret", "list", "--repo", repo_name], repo_root)
    if fallback.returncode != 0:
        return None, f"gh secret list failed: {first_error_line(fallback)}"

    names: set[str] = set()
    for line in fallback.stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper().startswith("NAME"):
            continue
        names.add(stripped.split()[0])
    return names, None


def status(label: str, message: str) -> None:
    print(f"[{label}] {message}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check newsletter GitHub Actions triggers and repository secret names."
    )
    parser.add_argument(
        "--repo",
        help="GitHub repository in owner/name form. Defaults to remote.origin.url.",
    )
    parser.add_argument(
        "--skip-secrets",
        action="store_true",
        help="Only check workflow structure; do not call gh secret list.",
    )
    args = parser.parse_args()

    repo_root = find_repo_root()
    repo_name = args.repo or infer_repo_name(repo_root)
    mirror_workflow_file = repo_root / MIRROR_WORKFLOW_PATH
    sync_workflow_file = repo_root / SYNC_WORKFLOW_PATH

    print("Newsletter GitHub Actions readiness")
    print(f"Repository: {repo_name}")
    print(f"Mirror workflow: {MIRROR_WORKFLOW_PATH}")
    print(f"Supabase sync workflow: {SYNC_WORKFLOW_PATH}")

    failures: list[str] = []
    unknowns: list[str] = []

    if not mirror_workflow_file.exists():
        failures.append(f"missing workflow file: {MIRROR_WORKFLOW_PATH}")
    else:
        workflow_text = mirror_workflow_file.read_text(encoding="utf-8")
        checks = (
            ("mirror workflow named Build newsletter mirror", "name: Build newsletter mirror" in workflow_text),
            ("schedule trigger present", re.search(r"(?m)^  schedule:\s*$", workflow_text)),
            (
                "manual workflow_dispatch trigger present",
                re.search(r"(?m)^  workflow_dispatch:\s*$", workflow_text),
            ),
            (f"daily 08:37 KST cron present ({EXPECTED_CRON})", EXPECTED_CRON in workflow_text),
            ("mirror workflow does not sync Supabase", "sync_newsletter_supabase.py" not in workflow_text),
            ("mirror workflow does not verify Vercel app", "NEWSLETTER_APP_URL" not in workflow_text),
            (
                "mirror workflow dispatches separate Supabase sync",
                'gh workflow run "Sync newsletter Supabase read model"' in workflow_text,
            ),
            ("mirror workflow defaults to stable source profile", "NEWSLETTER_SOURCE_PROFILE: stable" in workflow_text),
            ("mirror workflow exposes manual source profile input", "source_profile:" in workflow_text),
        )
        for message, ok in checks:
            if ok:
                status("OK", message)
            else:
                failures.append(message)

        for name in MIRROR_EXPECTED_SECRETS:
            if f"secrets.{name}" in workflow_text:
                status("OK", f"mirror workflow references secret {name}")
            else:
                failures.append(f"mirror workflow does not reference secret {name}")

        for name in SYNC_EXPECTED_SECRETS:
            if f"secrets.{name}" in workflow_text:
                failures.append(f"mirror workflow should not reference sync secret {name}")

    if not sync_workflow_file.exists():
        failures.append(f"missing workflow file: {SYNC_WORKFLOW_PATH}")
    else:
        sync_text = sync_workflow_file.read_text(encoding="utf-8")
        checks = (
            ("sync workflow named Sync newsletter Supabase read model", "name: Sync newsletter Supabase read model" in sync_text),
            ("sync workflow has manual dispatch", re.search(r"(?m)^  workflow_dispatch:\s*$", sync_text)),
            ("sync workflow calls sync_newsletter_supabase.py", "sync_newsletter_supabase.py" in sync_text),
            ("sync workflow verifies Vercel app", "NEWSLETTER_APP_URL" in sync_text),
            ("sync workflow has no schedule", re.search(r"(?m)^  schedule:\s*$", sync_text) is None),
        )
        for message, ok in checks:
            if ok:
                status("OK", message)
            else:
                failures.append(message)

        for name in SYNC_EXPECTED_SECRETS:
            if f"secrets.{name}" in sync_text:
                status("OK", f"sync workflow references secret {name}")
            else:
                failures.append(f"sync workflow does not reference secret {name}")

    if args.skip_secrets:
        unknowns.append("GitHub secret list skipped by --skip-secrets")
    else:
        names, error = load_gh_secret_names(repo_root, repo_name)
        if names is None:
            unknowns.append(f"GitHub secret names not checked: {error}")
        else:
            for name in EXPECTED_SECRETS:
                if name in names:
                    status("OK", f"GitHub secret exists: {name}")
                else:
                    failures.append(f"GitHub secret missing: {name}")

    for failure in failures:
        status("FAIL", failure)
    for unknown in unknowns:
        status("UNKNOWN", unknown)

    if failures:
        return 1
    if unknowns and not args.skip_secrets:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
