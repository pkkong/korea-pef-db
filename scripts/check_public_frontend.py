#!/usr/bin/env python3
"""Check public frontend contract before publishing."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from html import unescape
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from lp_public_visibility import is_public_lp_notice_row


REPO_ROOT = Path(__file__).resolve().parents[1]
NEWSLETTER_SITE_DIR = REPO_ROOT / "services" / "newsletter" / "deploy" / "site"
PUBLIC_DIR = NEWSLETTER_SITE_DIR
FSS_SOURCE_REGISTRY = REPO_ROOT / "data" / "source_registry_fss_pef.csv"
REQUIRED_PUBLIC_FILES = [
    "index.html",
    "daily-news.html",
    "lp-notices.html",
    "lp-official-notices.html",
    "gps.html",
    "market.html",
    "site.webmanifest",
    "apple-touch-icon.png",
    "assets/service.css",
    "assets/service.js",
]
BOTTOM_NAV_LABELS = ["브리프", "LP", "GP"]
PUBLIC_CORE_HTML_FILES = ["index.html", "daily-news.html"]
PUBLIC_SERVICE_HTML_FILES = ["lp-notices.html", "lp-official-notices.html", "gps.html", "market.html"]
PUBLIC_HTML_FILES = PUBLIC_CORE_HTML_FILES + PUBLIC_SERVICE_HTML_FILES
FORBIDDEN_VISIBLE_TEXT = [
    "NPL_RESTRUCTURING_AND_PE_MANAGER",
    "commitment_aum_proxy_trn_krw",
    "build_service_site.py",
    "services/newsletter",
    "localhost",
    "TODO",
    "내부용",
    "FSS 출자약정액",
    "GP 원문",
    "OCIO",
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
LP_NOTICE_FORBIDDEN_TEXT = [
    "벤처투자포털",
    "벤처투자종합포털",
    "벤처투자마트",
    "신청 정보 확인",
    "주식유통정보",
    "비상장주식거래플랫폼",
    "동의하지 않은 경우",
    "가치형이나 고배당형",
    "목록에서 발견",
    "source/evidence",
    "monitor_status",
    "candidate",
    "confidence",
    "OCIO",
]
LP_PUBLIC_JSON_FORBIDDEN_KEYS = {
    "raw_excerpt",
    "confidence",
    "confidence_note",
    "public_visible",
    "monitor_status",
    "source_code",
    "discovered_at",
    "updated_at",
}
GOOGLE_NEWS_HOST_RE = re.compile(r"https?://news\.google\.com/")


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
    paths = PUBLIC_HTML_FILES + ["assets/service.js"]
    violations: list[str] = []
    for relative_path in paths:
        text = read_public_text(relative_path)
        for needle in FORBIDDEN_PUBLIC_SOURCE_TERMS:
            if needle in text:
                violations.append(f"{relative_path}:{needle}")
    if violations:
        raise CheckFailure(f"Forbidden public source wording: {', '.join(violations)}")
    return [f"source_text_files={len(paths)}"]


def check_brief_initial_date_guard() -> list[str]:
    service_js = read_public_text("assets/service.js")
    expected = 'const initialDate = queryDate || (dateSelect && dateSelect.value) || (dateInput && dateInput.value) || "";'
    if expected not in service_js:
        raise CheckFailure("Brief initial date guard missing")
    return ["brief_initial_date_guard=ok"]


def check_newsletter_frontend_contract() -> list[str]:
    archive_path = PUBLIC_DIR / "archive.json"
    if not archive_path.exists():
        archive_path = NEWSLETTER_SITE_DIR / "archive.json"
    if not archive_path.exists():
        raise CheckFailure("archive.json missing for newsletter contract check")
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    if not isinstance(archive, list):
        raise CheckFailure("archive.json is not a list")
    article_count = 0
    violations: list[str] = []
    for entry in archive:
        if not isinstance(entry, dict):
            continue
        for article in entry.get("articles") or []:
            if not isinstance(article, dict):
                continue
            article_count += 1
            title = str(article.get("title") or "")
            if GOOGLE_NEWS_HOST_RE.search(str(article.get("url") or "")):
                violations.append(f"google_news_redirect:{title}")
            if not str(article.get("sourceIconUrl") or "").strip():
                violations.append(f"missing_source_icon:{title}")
            if str(article.get("tagVersion") or "") != "news-taxonomy-v1":
                violations.append(f"taxonomy_version:{title}")
    service_js_path = PUBLIC_DIR / "assets" / "service.js"
    if not service_js_path.exists():
        service_js_path = NEWSLETTER_SITE_DIR / "assets" / "service.js"
    service_js = service_js_path.read_text(encoding="utf-8") if service_js_path.exists() else ""
    for required in ["article.gpProfileLinks", 'appendLinkChip(item.name, item.url, "gp-chip")', 'appendLinkChip(item.name, item.url, "lp-chip")']:
        if required not in service_js:
            violations.append(f"service.js missing {required}")
    if violations:
        raise CheckFailure(f"Newsletter contract violations: {', '.join(violations[:20])}")
    return [f"newsletter_contract=ok articles_checked={article_count}"]


def check_public_lp_json_contract() -> list[str]:
    data_path = PUBLIC_DIR / "data" / "service_data.json"
    if not data_path.exists():
        data_path = NEWSLETTER_SITE_DIR / "data" / "service_data.json"
    if not data_path.exists():
        return ["lp_public_json_contract=skipped"]
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CheckFailure("service_data.json is not an object")
    violations: list[str] = []
    notices = payload.get("lp_commitment_notices") or []
    if not isinstance(notices, list):
        raise CheckFailure("lp_commitment_notices is not a list")
    for index, row in enumerate(notices, start=1):
        if not isinstance(row, dict):
            violations.append(f"lp_commitment_notices[{index}]:not_object")
            continue
        leaked = sorted(key for key in LP_PUBLIC_JSON_FORBIDDEN_KEYS if key in row)
        if leaked:
            violations.append(f"lp_commitment_notices[{index}]:internal_keys={','.join(leaked)}")
        if not is_public_lp_notice_row(row, require_official=True, allow_official_candidates=True):
            violations.append(f"lp_commitment_notices[{index}]:visibility")
        event_type = str(row.get("event_type") or "")
        event_date = str(row.get("event_date") or row.get("announced_date") or "")[:10]
        deadline = str(row.get("application_deadline") or "")[:10]
        if event_type in {"new_notice", "deadline_soon"} and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", event_date) and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", deadline) and deadline < event_date:
            violations.append(f"lp_commitment_notices[{index}]:stale_deadline")
        title = " ".join(str(row.get(key) or "") for key in ["title", "program_name", "raw_excerpt"])
        for needle in LP_NOTICE_FORBIDDEN_TEXT:
            if needle in title:
                violations.append(f"lp_commitment_notices[{index}]:{needle}")
    profiles = payload.get("lp_profiles") or []
    for index, row in enumerate(profiles, start=1):
        if not isinstance(row, dict):
            violations.append(f"lp_profiles[{index}]:not_object")
            continue
        status_text = " ".join(str(row.get(key) or "") for key in ["profile_status", "notes"])
        if "candidate" in status_text.lower() or "후보" in status_text:
            violations.append(f"lp_profiles[{index}]:candidate_profile")
        row_text = json.dumps(row, ensure_ascii=False)
        if "OCIO" in row_text or "placeholder" in row_text.lower():
            violations.append(f"lp_profiles[{index}]:weak_public_profile_text")
    for index, row in enumerate(payload.get("lp_institution_stats") or [], start=1):
        if isinstance(row, dict):
            row_text = json.dumps(row, ensure_ascii=False)
            if "OCIO" in row_text or "placeholder" in row_text.lower():
                violations.append(f"lp_institution_stats[{index}]:weak_public_profile_text")
    if violations:
        raise CheckFailure(f"LP public JSON violations: {', '.join(violations[:20])}")
    return [f"lp_public_json_contract=ok notices_checked={len(notices)} profiles_checked={len(profiles)}"]


def latest_fss_registry_period() -> str:
    if not FSS_SOURCE_REGISTRY.exists():
        return ""
    latest = ""
    with FSS_SOURCE_REGISTRY.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            period = str(row.get("period_label") or row.get("period") or "").strip()
            if period > latest:
                latest = period
    return latest


def check_generated_gp_contract() -> list[str]:
    gps_path = NEWSLETTER_SITE_DIR / "gps.html"
    market_path = NEWSLETTER_SITE_DIR / "market.html"
    if not gps_path.exists():
        return ["generated_gp_contract=skipped"]
    if not market_path.exists():
        raise CheckFailure("market.html missing from generated newsletter site")

    gps_html = gps_path.read_text(encoding="utf-8")
    market_html = market_path.read_text(encoding="utf-8")
    latest_registry_period = latest_fss_registry_period()
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
    ]
    violations = [needle for needle in forbidden if needle in gps_html]
    violations.extend(f"market.html:{needle}" for needle in forbidden if needle in market_html)

    if '<header class="kpef-product-header' in gps_html:
        violations.append("kpef-product-header")
    if '<strong class="service-title">GP</strong>' not in gps_html:
        raise CheckFailure("GP directory service title missing")
    tabs = gp_service_tabs(gps_html)
    if tabs != ["MARKET", "GP"]:
        raise CheckFailure(f"GP service tabs mismatch: expected MARKET/GP, got {tabs}")
    if gp_service_tabs(market_html) != ["MARKET", "GP"]:
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
    for required in ["market-trend-chart", "market-rank-chart", "대표 운용사 집계", "프로필/제휴 기준"]:
        if required not in market_html:
            raise CheckFailure(f"market.html missing GP market contract text/markup: {required}")
    if latest_registry_period and latest_registry_period not in market_html:
        raise CheckFailure(f"market.html does not show latest FSS period {latest_registry_period}")
    if "PEOPLE" in tabs or ">PEOPLE<" in gps_html or ">PEOPLE<" in market_html:
        raise CheckFailure("People tab must stay hidden until the public coverage gate is met")
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
        if gp_service_tabs(html) != ["MARKET", "GP"]:
            violations.append(f"{detail_path.name}:gp-service-tabs")

    if violations:
        raise CheckFailure(f"Forbidden generated GP wording/markup: {', '.join(violations)}")
    if 'data-url="gp-' not in gps_html:
        raise CheckFailure("GP directory rows are missing clickable data-url links")

    return [f"generated_gp_contract=ok detail_pages_checked={len(detail_paths)} market=ok"]


def check_generated_lp_wiki_contract() -> list[str]:
    lp_path = NEWSLETTER_SITE_DIR / "lp-notices.html"
    lp_notice_path = NEWSLETTER_SITE_DIR / "lp-official-notices.html"
    if not lp_path.exists() or not lp_notice_path.exists():
        return ["generated_lp_contract=skipped"]

    violations: list[str] = []
    lp_html = lp_path.read_text(encoding="utf-8")
    lp_notice_html = lp_notice_path.read_text(encoding="utf-8")

    for name, html in [("lp-notices.html", lp_html), ("lp-official-notices.html", lp_notice_html)]:
        labels = bottom_nav_labels(html)
        if labels != BOTTOM_NAV_LABELS:
            raise CheckFailure(f"{name} bottom nav mismatch: expected {BOTTOM_NAV_LABELS}, got {labels}")
        if '<header class="kpef-product-header' in html:
            violations.append(f"{name}:kpef-product-header")
        if 'font-variant-numeric: tabular-nums' not in html:
            violations.append(f"{name}:tabular-nums")

    if '<strong class="service-title">LP</strong>' not in lp_html:
        raise CheckFailure("LP service title missing")
    expected_lp_tabs = ["출자기관", "출자공고", "선정결과"]
    if gp_service_tabs(lp_html) != expected_lp_tabs:
        raise CheckFailure(f"LP service tabs mismatch: got {gp_service_tabs(lp_html)}")
    if gp_service_tabs(lp_notice_html) != expected_lp_tabs:
        raise CheckFailure(f"LP notice service tabs mismatch: got {gp_service_tabs(lp_notice_html)}")
    if 'aria-current="page">출자공고</a>' not in lp_notice_html:
        violations.append("lp-official-notices.html:notice tab not current")
    if "lp-notice-row" not in lp_notice_html:
        violations.append("lp-official-notices.html:notice rows missing")
    for needle in LP_NOTICE_FORBIDDEN_TEXT:
        if needle in lp_notice_html:
            violations.append(f"lp-official-notices.html:{needle}")
    notice_articles = re.findall(r'<article class="lp-notice-row"[^>]*>.*?</article>', lp_notice_html, re.DOTALL)
    for index, article in enumerate(notice_articles[:80], start=1):
        article_text = strip_tags(article)
        if "2026년 국민연금기금 벤처펀드" in article_text and any(term in article_text for term in ["부동산", "국내사모투자"]):
            violations.append(f"lp-official-notices.html:nps_overmerged_card_{index}")
        if re.search(r"\([^)]*$", article_text):
            violations.append(f"lp-official-notices.html:unclosed_parenthesis_{index}")
    if re.search(r'data-kind="[^"]*\b(public|private|mutual_aid)\b', lp_html):
        violations.append("lp-notices.html:raw ownership token")
    if "출자기관 프로필" in lp_html:
        violations.append("lp-notices.html:profile label in directory")

    detail_paths = sorted(NEWSLETTER_SITE_DIR.glob("lp-notice-*.html"))[:8]
    for detail_path in detail_paths:
        html = detail_path.read_text(encoding="utf-8")
        labels = bottom_nav_labels(html)
        if labels != BOTTOM_NAV_LABELS:
            raise CheckFailure(
                f"{detail_path.name} bottom nav mismatch: expected {BOTTOM_NAV_LABELS}, got {labels}"
            )
        for needle in LP_NOTICE_FORBIDDEN_TEXT:
            if needle in html:
                violations.append(f"{detail_path.name}:{needle}")

    profile_paths = sorted(
        path
        for path in NEWSLETTER_SITE_DIR.glob("lp-*.html")
        if path.name not in {"lp-notices.html", "lp-official-notices.html"} and not path.name.startswith("lp-notice-")
    )[:3]
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

    if violations:
        raise CheckFailure(f"Forbidden generated LP wording/markup: {', '.join(violations)}")
    return [f"generated_lp_contract=ok lp_profiles_checked={len(profile_paths)} lp_notice_details_checked={len(detail_paths)}"]


def check_remote(base_url: str) -> list[str]:
    if not base_url:
        return []
    base = base_url.rstrip("/") + "/"
    checked: list[str] = []
    for relative_path in ["", "market.html", "gps.html", "lp-official-notices.html"]:
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
    parser.add_argument(
        "--public-dir",
        type=Path,
        default=NEWSLETTER_SITE_DIR,
        help="Local static site directory to check. Defaults to services/newsletter/deploy/site.",
    )
    args = parser.parse_args()
    global PUBLIC_DIR
    PUBLIC_DIR = args.public_dir

    checks = [
        check_required_files,
        check_bottom_nav,
        check_visible_text,
        check_public_source_terms,
        check_newsletter_frontend_contract,
        check_public_lp_json_contract,
        check_generated_gp_contract,
        check_generated_lp_wiki_contract,
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
