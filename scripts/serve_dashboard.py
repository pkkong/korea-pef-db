#!/usr/bin/env python
"""Serve the local static PEF dashboard."""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "dashboard"


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the local PEF dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(args.root))
    with socketserver.TCPServer((args.host, args.port), handler) as httpd:
        print(f"Serving {args.root} at http://{args.host}:{args.port}/")
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
