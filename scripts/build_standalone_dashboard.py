#!/usr/bin/env python
"""Build the dashboard HTML shell.

The service dashboard keeps application HTML separate from
dashboard/data/dashboard_data.json. A standalone embedded file is still
available with --embed-data for ad-hoc offline review.
"""

from __future__ import annotations

import argparse
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = REPO_ROOT / "dashboard" / "index_app_template.html"
DEFAULT_DATA = REPO_ROOT / "dashboard" / "data" / "dashboard_data.json"
DEFAULT_CSS = REPO_ROOT / "dashboard" / "assets" / "app.css"
DEFAULT_JS = REPO_ROOT / "dashboard" / "assets" / "app.js"
DEFAULT_OUT = REPO_ROOT / "dashboard" / "index.html"
DEFAULT_LEGACY_COPY = REPO_ROOT / "dashboard" / "pef_dashboard_standalone.html"


FETCH_BLOCK = """      const response = await fetch("data/dashboard_data.json");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.data = await response.json();"""

INLINE_BLOCK = """      state.data = JSON.parse(document.getElementById("dashboardData").textContent);"""
STYLE_TAG = '  <link rel="stylesheet" href="assets/app.css">'
SCRIPT_TAG = '  <script src="assets/app.js"></script>'


def escape_script_json(raw_json: str) -> str:
    return (
        raw_json
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def build(
    index_path: Path,
    data_path: Path,
    out_path: Path,
    css_path: Path = DEFAULT_CSS,
    js_path: Path = DEFAULT_JS,
    embed_data: bool = False,
) -> None:
    html = index_path.read_text(encoding="utf-8")

    if embed_data:
        data = escape_script_json(data_path.read_text(encoding="utf-8"))
        css = css_path.read_text(encoding="utf-8")
        js = js_path.read_text(encoding="utf-8")
        if FETCH_BLOCK not in js:
            raise RuntimeError("Could not find dashboard fetch block in dashboard JS")
        if STYLE_TAG not in html:
            raise RuntimeError("Could not find dashboard stylesheet tag in index template")
        if SCRIPT_TAG not in html:
            raise RuntimeError("Could not find dashboard script tag in index template")

        js = js.replace(FETCH_BLOCK, INLINE_BLOCK)
        html = html.replace(STYLE_TAG, f"  <style>\n{css.rstrip()}\n  </style>", 1)
        html = html.replace(
            SCRIPT_TAG,
            f'  <script id="dashboardData" type="application/json">{data}</script>\n'
            f"  <script>\n{js.rstrip()}\n  </script>",
            1,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build standalone PEF dashboard HTML")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--css", type=Path, default=DEFAULT_CSS)
    parser.add_argument("--js", type=Path, default=DEFAULT_JS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--embed-data", action="store_true")
    parser.add_argument("--legacy-copy", type=Path, default=DEFAULT_LEGACY_COPY)
    args = parser.parse_args()

    build(args.index, args.data, args.out, css_path=args.css, js_path=args.js, embed_data=args.embed_data)
    print(f"wrote {args.out}")
    print(f"bytes={args.out.stat().st_size}")
    if not args.embed_data and args.legacy_copy and args.legacy_copy != args.out:
        args.legacy_copy.write_text(args.out.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"copied service shell {args.legacy_copy}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
