#!/usr/bin/env python3
"""Check public frontend contract before publishing."""

from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = REPO_ROOT / "public"
REQUIRED_PUBLIC_FILES = [
    "index.html",
    "daily-news.html",
    "db.html",
    "pef-wiki.html",
    "site.webmanifest",
    "apple-touch-icon.png",
    "assets/app.css",
    "assets/app.js",
    "assets/service.css",
    "assets/service.js",
    "data/service_data.json",
]
BOTTOM_NAV_LABELS = ["브리프", "LP", "GP", "Wiki"]
PUBLIC_HTML_FILES = ["index.html", "daily-news.html", "db.html", "pef-wiki.html"]
FORBIDDEN_VISIBLE_TEXT = [
    "NPL_RESTRUCTURING_AND_PE_MANAGER",
    "commitment_aum_proxy_trn_krw",
    "build_service_site.py",
    "services/newsletter",
    "localhost",
    "TODO",
    "운영자",
    "내부용",
    "FSS 출자약정액",
    "GP 원문",
    "관측",
]
FORBIDDEN_PUBLIC_SOURCE_TERMS = [
    "작업 큐",
    "검토 대기",
    "보강 필요",
    "프로필 팩트",
    "자동 매칭",
    "데이터 수집",
    "관리자",
    "operator",
    "AUM proxy",
    "open_public_dashboard",
    "admin.html",
]


class CheckFailure(Exception):
    pass


def strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def read_public_text(relative_path: str) -> str:
    return (PUBLIC_DIR / relative_path).read_text(encoding="utf-8")


def check_required_files() -> list[str]:
    missing = [path for path in REQUIRED_PUBLIC_FILES if not (PUBLIC_DIR / path).exists()]
    if missing:
        raise CheckFailure(f"Missing public files: {', '.join(missing)}")
    return [f"required_files={len(REQUIRED_PUBLIC_FILES)}"]


def bottom_nav_labels(html: str) -> list[str]:
    match = re.search(r'<nav class="bottom-nav[^"]*"[^>]*>(.*?)</nav>', html, re.DOTALL)
    if not match:
        return []
    nav = match.group(1)
    labels = [strip_tags(label) for label in re.findall(r"<strong[^>]*>(.*?)</strong>", nav, re.DOTALL)]
    if labels:
        return labels
    items = re.findall(r"<(?:a|button)\b[^>]*>(.*?)</(?:a|button)>", nav, re.DOTALL)
    return [strip_tags(item) for item in items if strip_tags(item)]


def check_bottom_nav() -> list[str]:
    checked: list[str] = []
    for relative_path in PUBLIC_HTML_FILES:
        html = read_public_text(relative_path)
        labels = bottom_nav_labels(html)
        if labels != BOTTOM_NAV_LABELS:
            raise CheckFailure(
                f"{relative_path} bottom nav mismatch: expected {BOTTOM_NAV_LABELS}, got {labels}"
            )
        checked.append(relative_path)
    return [f"bottom_nav_pages={len(checked)}"]


def check_visible_text() -> list[str]:
    violations: list[str] = []
    for relative_path in PUBLIC_HTML_FILES:
        text = read_public_text(relative_path)
        for needle in FORBIDDEN_VISIBLE_TEXT:
            if needle in text:
                violations.append(f"{relative_path}:{needle}")
    if violations:
        raise CheckFailure(f"Forbidden public wording: {', '.join(violations)}")
    return [f"visible_text_pages={len(PUBLIC_HTML_FILES)}"]


def check_public_source_terms() -> list[str]:
    paths = PUBLIC_HTML_FILES + ["assets/app.js", "assets/service.js"]
    violations: list[str] = []
    for relative_path in paths:
        text = read_public_text(relative_path)
        for needle in FORBIDDEN_PUBLIC_SOURCE_TERMS:
            if needle in text:
                violations.append(f"{relative_path}:{needle}")
    if violations:
        raise CheckFailure(f"Forbidden public source wording: {', '.join(violations)}")
    return [f"source_text_files={len(paths)}"]


def check_public_db_amount_contract() -> list[str]:
    payload = json.loads((PUBLIC_DIR / "data" / "service_data.json").read_text(encoding="utf-8"))
    latest_period = payload.get("meta", {}).get("latest_period")
    rows = [
        row
        for row in payload.get("gp_period_primary", [])
        if row.get("period_label") == latest_period
    ]
    if not rows:
        raise CheckFailure(f"No GP rows for latest period {latest_period!r}")
    top = max(rows, key=lambda row: float(row.get("commitment_trn_krw") or 0))
    amount = float(top.get("commitment_trn_krw") or 0)
    if amount <= 0:
        raise CheckFailure(f"Top GP amount is not positive for {latest_period}: {top}")

    app_js = read_public_text("assets/app.js")
    legacy_refs = [line.strip() for line in app_js.splitlines() if "commitment_aum_proxy_trn_krw" in line]
    if legacy_refs != ["return num(row?.commitment_trn_krw ?? row?.commitment_aum_proxy_trn_krw);"]:
        raise CheckFailure(f"Unexpected legacy amount-field references: {legacy_refs}")
    return [f"top_gp={top.get('gp_name')} amount_trn={amount:g}"]


def check_brief_initial_date_guard() -> list[str]:
    service_js = read_public_text("assets/service.js")
    expected = 'const initialDate = queryDate || (dateSelect && dateSelect.value) || (dateInput && dateInput.value) || "";'
    if expected not in service_js:
        raise CheckFailure("Brief initial date guard missing")
    return ["brief_initial_date_guard=ok"]


def check_remote(base_url: str) -> list[str]:
    if not base_url:
        return []
    base = base_url.rstrip("/") + "/"
    checked: list[str] = []
    for relative_path in ["", "db.html", "pef-wiki.html"]:
        url = base + relative_path
        request = Request(url, headers={"User-Agent": "kpef-public-frontend-check/1.0"})
        try:
            with urlopen(request, timeout=15) as response:
                status = getattr(response, "status", 200)
                if status >= 400:
                    raise CheckFailure(f"{url} returned HTTP {status}")
                checked.append(relative_path or "index.html")
        except URLError as exc:
            raise CheckFailure(f"{url} failed: {exc}") from exc
    return [f"remote_pages={len(checked)}"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check public frontend publishing contract")
    parser.add_argument("--base-url", default="", help="Optional deployed site URL to smoke-check")
    args = parser.parse_args()

    checks = [
        check_required_files,
        check_bottom_nav,
        check_visible_text,
        check_public_source_terms,
        check_public_db_amount_contract,
        check_brief_initial_date_guard,
    ]
    output: list[str] = []
    try:
        for check in checks:
            output.extend(check())
        output.extend(check_remote(args.base_url))
    except CheckFailure as exc:
        print(f"FAIL public frontend check: {exc}", file=sys.stderr)
        return 1

    print("OK public frontend check")
    for line in output:
        print(f"- {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
