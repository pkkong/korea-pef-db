#!/usr/bin/env python
"""Open the public-facing dashboard with a local static server."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = REPO_ROOT / "public"
PORT = 8010
URL = f"http://127.0.0.1:{PORT}/"


def url_is_live() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=1.5) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


def start_server() -> None:
    log_dir = REPO_ROOT / "public"
    log_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "serve_dashboard.py"),
        "--root",
        str(PUBLIC_ROOT),
        "--port",
        str(PORT),
    ]

    if sys.platform.startswith("win"):
        subprocess.Popen(
            [
                "cmd",
                "/c",
                "start",
                "PEF Public Dashboard Server",
                "/min",
                "cmd",
                "/k",
                *command,
            ],
            cwd=str(REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return

    stdout = (log_dir / "server_stdout.log").open("a", encoding="utf-8")
    stderr = (log_dir / "server_stderr.log").open("a", encoding="utf-8")
    subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        close_fds=True,
    )


def wait_for_server(seconds: float = 8.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if url_is_live():
            return True
        time.sleep(0.35)
    return False


def open_browser(url: str) -> None:
    if sys.platform.startswith("win"):
        import os

        try:
            os.startfile(url)  # noqa: S606 - fixed localhost URL launcher.
        except OSError:
            subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        return

    import webbrowser

    webbrowser.open(url)


def main() -> int:
    if not url_is_live():
        print("Starting public dashboard server...", flush=True)
        start_server()
        if not wait_for_server():
            print("Public dashboard server did not start.")
            return 1

    open_browser(URL)
    print(f"Public dashboard opened: {URL}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
