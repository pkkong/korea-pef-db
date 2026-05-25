#!/usr/bin/env python
"""Open the dashboard with a local static server.

This is the user-facing launcher behind open_dashboard.bat. It starts the
dashboard server only when the local URL is not already reachable, then opens
the default browser.
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8000/"


def url_is_live() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=1.5) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


def start_server() -> None:
    log_dir = REPO_ROOT / "dashboard"
    log_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        subprocess.Popen(
            [
                "cmd",
                "/c",
                "start",
                "PEF Dashboard Server",
                "/min",
                "cmd",
                "/k",
                str(REPO_ROOT / "scripts" / "run_dashboard_server.bat"),
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
        [sys.executable, str(REPO_ROOT / "scripts" / "serve_dashboard.py")],
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
            os.startfile(url)  # noqa: S606 - local launcher opens a fixed localhost URL.
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
        print("Starting dashboard server...", flush=True)
        start_server()
        if not wait_for_server():
            print("Dashboard server did not start. Check dashboard/server_stderr.log.")
            return 1

    open_browser(URL)
    print(f"Dashboard opened: {URL}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
