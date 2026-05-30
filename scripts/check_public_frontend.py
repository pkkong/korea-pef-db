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
NEWSLETTER_SITE_DIR = REPO_ROOT / "services" / "newsletter" / "deploy" / "site"
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


def gp_service_tabs(html: str) -> list[str]:
    match = re.search(r'<nav class="brief-section-tabs[^"]*"[^>]*>(.*?)</nav>', html, re.DOTALL)
    if not match:
        return []
    return [
        strip_tags(item)
        for item in re.findall(r"<(?:a|button)\b[^>]*>(.*?)</(?:a|button)>", match.group(1), re.DOTALL)
        if strip_tags(item)
    ]


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


def check_generated_gp_contract() -> list[str]:
    gps_path = NEWSLETTER_SITE_DIR / "gps.html"
    market_path = NEWSLETTER_SITE_DIR / "market.html"
    if not gps_path.exists():
        return ["generated_gp_contract=skipped"]
    if not market_path.exists():
        raise CheckFailure("market.html missing from generated newsletter site")

    gps_html = gps_path.read_text(encoding="utf-8")
    market_html = market_path.read_text(encoding="utf-8")
    labels = bottom_nav_labels(gps_html)
    if labels != BOTTOM_NAV_LABELS:
        raise CheckFailure(f"gps.html bottom nav mismatch: expected {BOTTOM_NAV_LABELS}, got {labels}")
    market_labels = bottom_nav_labels(market_html)
    if market_labels != BOTTOM_NAV_LABELS:
        raise CheckFailure(f"market.html bottom nav mismatch: expected {BOTTOM_NAV_LABELS}, got {market_labels}")

    forbidden = [
        "상위 프로필",
        "상위 120개",
        "자료 확인",
        "상세 프로필",
        "gp-card-extra",
        "kpef-service-tabs",
        "gp-top-nav",
        "source/evidence",
        "AUM proxy",
        "operator",
        "verification",
        "research",
        "자동 생성",
        "신호",
    ]
    violations = [needle for needle in forbidden if needle in gps_html]
    violations.extend(f"market.html:{needle}" for needle in forbidden if needle in market_html)

    if '<header class="kpef-product-header' in gps_html:
        violations.append("kpef-product-header")
    if '<strong class="service-title">GP</strong>' not in gps_html:
        raise CheckFailure("GP directory service title missing")
    tabs = gp_service_tabs(gps_html)
    if tabs != ["MARKET", "GP", "PEOPLE"]:
        raise CheckFailure(f"GP service tabs mismatch: expected MARKET/GP/PEOPLE, got {tabs}")
    if gp_service_tabs(market_html) != ["MARKET", "GP", "PEOPLE"]:
        raise CheckFailure("Market service tabs mismatch")
    gps_text = strip_tags(gps_html)
    if not re.search(r"\d[\d,]*개 PEF 운용사", gps_text):
        raise CheckFailure("GP directory count title missing")
    if re.search(r"\d[\d,]*개 PEF 운용사\s*\([0-9.]+ 기준\)", gps_text):
        raise CheckFailure("GP directory title should not include 기준일")
    for required_control in ['id="gpPeriod"', 'id="gpScope"', 'id="gpSort"', 'id="gpPageSize"']:
        if required_control not in gps_html:
            violations.append(f"gps.html:{required_control}")
    for combined_label in ["대표/홈페이지", "순위/약정액", "뉴스/출자"]:
        if combined_label in gps_html:
            violations.append(f"gps.html:{combined_label}")
    for row_badge_markup in ['<div class="gp-chips"', '<div class="gp-signal-strip"']:
        if row_badge_markup in gps_html:
            violations.append(f"gps.html:{row_badge_markup}")
    for required in ["Overview", "분기별 시장 추이", "상위 GP", "연도별 신규 펀드"]:
        if required not in market_html:
            raise CheckFailure(f"market.html missing required section: {required}")
    if "PEF 시장 통계" in market_html:
        violations.append("market.html:PEF 시장 통계")
    if 'font-variant-numeric: tabular-nums' not in gps_html:
        violations.append("gps.html:tabular-nums")

    detail_paths = sorted(NEWSLETTER_SITE_DIR.glob("gp-*.html"))[:3]
    for detail_path in detail_paths:
        html = detail_path.read_text(encoding="utf-8")
        detail_labels = bottom_nav_labels(html)
        if detail_labels != BOTTOM_NAV_LABELS:
            raise CheckFailure(
                f"{detail_path.name} bottom nav mismatch: expected {BOTTOM_NAV_LABELS}, got {detail_labels}"
            )
        for needle in forbidden:
            if needle in html:
                violations.append(f"{detail_path.name}:{needle}")
        if '<header class="kpef-product-header' in html:
            violations.append(f"{detail_path.name}:kpef-product-header")
        if gp_service_tabs(html) != ["MARKET", "GP", "PEOPLE"]:
            violations.append(f"{detail_path.name}:gp-service-tabs")

    if violations:
        raise CheckFailure(f"Forbidden generated GP wording/markup: {', '.join(violations)}")
    if 'data-url="gp-' not in gps_html:
        raise CheckFailure("GP directory rows are missing clickable data-url links")

    return [f"generated_gp_contract=ok detail_pages_checked={len(detail_paths)} market=ok"]


def check_generated_lp_wiki_contract() -> list[str]:
    lp_path = NEWSLETTER_SITE_DIR / "lp-notices.html"
    wiki_path = NEWSLETTER_SITE_DIR / "pef-wiki.html"
    if not lp_path.exists() or not wiki_path.exists():
        return ["generated_lp_wiki_contract=skipped"]

    violations: list[str] = []
    lp_html = lp_path.read_text(encoding="utf-8")
    wiki_html = wiki_path.read_text(encoding="utf-8")

    for name, html in [("lp-notices.html", lp_html), ("pef-wiki.html", wiki_html)]:
        labels = bottom_nav_labels(html)
        if labels != BOTTOM_NAV_LABELS:
            raise CheckFailure(f"{name} bottom nav mismatch: expected {BOTTOM_NAV_LABELS}, got {labels}")
        if '<header class="kpef-product-header' in html:
            violations.append(f"{name}:kpef-product-header")
        if 'font-variant-numeric: tabular-nums' not in html:
            violations.append(f"{name}:tabular-nums")

    if '<strong class="service-title">LP</strong>' not in lp_html:
        raise CheckFailure("LP service title missing")
    if gp_service_tabs(lp_html) != ["LP", "NOTICE", "PEOPLE"]:
        raise CheckFailure(f"LP service tabs mismatch: got {gp_service_tabs(lp_html)}")
    if re.search(r'data-kind="[^"]*\b(public|private|mutual_aid)\b', lp_html):
        violations.append("lp-notices.html:raw ownership token")
    if "출자기관 프로필" in lp_html:
        violations.append("lp-notices.html:profile label in directory")

    profile_paths = sorted(path for path in NEWSLETTER_SITE_DIR.glob("lp-*.html") if path.name != "lp-notices.html")[:3]
    for profile_path in profile_paths:
        html = profile_path.read_text(encoding="utf-8")
        labels = bottom_nav_labels(html)
        if labels != BOTTOM_NAV_LABELS:
            raise CheckFailure(
                f"{profile_path.name} bottom nav mismatch: expected {BOTTOM_NAV_LABELS}, got {labels}"
            )
        if '<header class="kpef-product-header' in html:
            violations.append(f"{profile_path.name}:kpef-product-header")
        if '<strong class="service-title">LP</strong>' not in html:
            violations.append(f"{profile_path.name}:LP service title")
        if 'font-variant-numeric: tabular-nums' not in html:
            violations.append(f"{profile_path.name}:tabular-nums")

    if '<strong class="service-title">Wiki</strong>' not in wiki_html:
        raise CheckFailure("Wiki service title missing")
    if gp_service_tabs(wiki_html) != ["개요", "법령", "보고", "세무", "체크리스트"]:
        raise CheckFailure(f"Wiki topic tabs mismatch: got {gp_service_tabs(wiki_html)}")
    if wiki_html.count('id="wikiSearch"') != 1:
        violations.append("pef-wiki.html:duplicate wikiSearch")

    if violations:
        raise CheckFailure(f"Forbidden generated LP/Wiki wording/markup: {', '.join(violations)}")
    return [f"generated_lp_wiki_contract=ok lp_profiles_checked={len(profile_paths)} wiki=ok"]


def check_remote(base_url: str) -> list[str]:
    if not base_url:
        return []
    base = base_url.rstrip("/") + "/"
    checked: list[str] = []
    for relative_path in ["", "market.html", "gps.html", "db.html", "pef-wiki.html"]:
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
        check_generated_gp_contract,
        check_generated_lp_wiki_contract,
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
