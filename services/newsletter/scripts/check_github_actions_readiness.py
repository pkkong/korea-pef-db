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


WORKFLOW_PATH = Path(".github/workflows/deploy-newsletter-pages.yml")
EXPECTED_CRON = "37 23 * * *"
EXPECTED_SECRETS = (
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "NEWSLETTER_PUBLIC_REPO_TOKEN",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
)


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
    workflow_file = repo_root / WORKFLOW_PATH

    print("Newsletter GitHub Actions readiness")
    print(f"Repository: {repo_name}")
    print(f"Workflow: {WORKFLOW_PATH}")

    failures: list[str] = []
    unknowns: list[str] = []

    if not workflow_file.exists():
        failures.append(f"missing workflow file: {WORKFLOW_PATH}")
    else:
        workflow_text = workflow_file.read_text(encoding="utf-8")
        checks = (
            ("schedule trigger present", re.search(r"(?m)^  schedule:\s*$", workflow_text)),
            (
                "manual workflow_dispatch trigger present",
                re.search(r"(?m)^  workflow_dispatch:\s*$", workflow_text),
            ),
            (f"daily 08:37 KST cron present ({EXPECTED_CRON})", EXPECTED_CRON in workflow_text),
        )
        for message, ok in checks:
            if ok:
                status("OK", message)
            else:
                failures.append(message)

        for name in EXPECTED_SECRETS:
            if f"secrets.{name}" in workflow_text:
                status("OK", f"workflow references secret {name}")
            else:
                failures.append(f"workflow does not reference secret {name}")

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
    if unknowns:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
