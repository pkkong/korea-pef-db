#!/usr/bin/env python
"""Build the public mobile-first Daily PEF app shell."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from daily_news_common import DEFAULT_EXPORT_DIR, REPO_ROOT, clean_news_title, normalize_url, normalize_whitespace, split_news_title_badges, today_seoul

DEFAULT_PUBLIC_DIR = REPO_ROOT / "public"
DEFAULT_SERVICE_INTEGRATION_WORKLIST = REPO_ROOT / "exports" / "service_integration_worklist_latest.csv"
DEFAULT_LP_COMMITMENT_MONITOR = REPO_ROOT / "exports" / "lp_commitment_monitor_latest.csv"
DEFAULT_ARCHIVE_LIMIT = 30
SECTION_HEADER_RE = re.compile(r"^\[(?P<section>.+?)\]\s*$")
ARTICLE_RE = re.compile(r"^- \[(?P<title>.+?)\]\((?P<url>https?://[^)]+)\)")
EDITORIAL_SECTIONS = [
    "AI & PE",
    "Deal",
    "LP",
    "GP",
    "Market",
]
AI_SHORT_RE = re.compile(r"(?<![A-Za-z])AI(?![A-Za-z])", re.IGNORECASE)
PUBLISHER_BADGES = {
    "더벨": "더",
    "인베스트조선": "인",
    "딜사이트": "딜",
    "조선비즈": "조",
    "연합인포맥스": "연",
    "블로터": "블",
    "한국경제": "한",
    "서울경제": "서",
    "매일경제": "매",
    "머니투데이": "머",
    "아시아경제": "아",
    "이데일리": "이",
    "이투데이": "투",
    "파이낸셜뉴스": "파",
    "뉴스핌": "핌",
    "뉴시스": "뉴",
    "조세일보": "세",
    "포쓰저널": "포",
    "뉴스톱": "톱",
    "뉴스토마토": "토",
}
PRIMARY_LP_SOURCE_CODES = {
    "nps_manager_selection",
    "kafi_apfs_notice",
    "pmaa_bid_notice",
    "koreapost_asset_notice",
    "cu_notice",
    "kbiz_notice",
}
BACKUP_LP_SOURCE_CODES = {
    "vcs_investment_notice",
    "kofia_notice_feed",
}
LP_EVENT_PRIORITY = {
    "new_notice": 0,
    "deadline_soon": 1,
    "final_selection": 2,
    "shortlist": 3,
    "revision": 4,
    "cancellation": 5,
    "performance_update": 6,
    "deadline_closed": 7,
}


def html_escape(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def compact_date(report_date: str) -> str:
    return report_date.replace("-", "")


def display_date(report_date: str) -> str:
    return report_date.replace("-", ".")


def short_date(report_date: str) -> str:
    parts = report_date.split("-")
    if len(parts) == 3:
        return f"{parts[1]}.{parts[2]}"
    return display_date(report_date)


def weekday_label(report_date: str) -> str:
    try:
        from datetime import date

        parsed = date.fromisoformat(report_date)
    except ValueError:
        return ""
    return ["월", "화", "수", "목", "금", "토", "일"][parsed.weekday()]


def latest_report_date(out_dir: Path, fallback: str) -> str:
    candidates: list[str] = []
    for path in out_dir.glob("daily_news_brief_*.md"):
        match = re.fullmatch(r"daily_news_brief_(\d{8})\.md", path.name)
        if match:
            raw = match.group(1)
            candidates.append(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
    return sorted(candidates, reverse=True)[0] if candidates else fallback


def report_dates(out_dir: Path) -> list[str]:
    dates: list[str] = []
    for path in out_dir.glob("daily_news_brief_*.md"):
        match = re.fullmatch(r"daily_news_brief_(\d{8})\.md", path.name)
        if not match:
            continue
        raw = match.group(1)
        dates.append(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
    return sorted(set(dates), reverse=True)


def parse_brief(markdown_path: Path) -> list[dict[str, str]]:
    if not markdown_path.exists():
        return []
    rows: list[dict[str, str]] = []
    current_section = ""
    last_row: dict[str, str] | None = None
    for raw_line in markdown_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        section_match = SECTION_HEADER_RE.match(line)
        if section_match:
            current_section = section_match.group("section")
            last_row = None
            continue
        article_match = ARTICLE_RE.match(line)
        if article_match:
            last_row = {
                "section": current_section,
                "title": clean_news_title(article_match.group("title")),
                "url": article_match.group("url"),
                "source": "",
            }
            rows.append(last_row)
            continue
        if last_row is not None and line.startswith("출처:"):
            last_row["source"] = line.replace("출처:", "", 1).strip()
            last_row["title"] = clean_news_title(last_row["title"], last_row["source"])
    return rows


def parse_brief_basis(markdown_path: Path) -> str:
    return ""


def brief_count_label(count: int) -> str:
    return f"주요 뉴스 {count}건"


def contains_any(text: str, keywords: list[str]) -> bool:
    normalized = text.lower()
    return any(keyword.lower() in normalized for keyword in keywords)


AI_THEME_KEYWORDS = [
    "A.I.",
    "인공지능",
    "생성형 AI",
    "생성 AI",
    "generative AI",
    "GenAI",
    "LLM",
    "머신러닝",
    "딥러닝",
    "AI 반도체",
    "AI반도체",
    "GPU",
    "엔비디아",
    "데이터센터",
    "data center",
    "AI 인프라",
    "컴퓨트",
    "클라우드 인프라",
]
DEAL_SIGNAL_KEYWORDS = [
    "M&A",
    "매각",
    "인수",
    "품는다",
    "사들인다",
    "지분매각",
    "회수",
    "청산",
    "경영권",
    "엑시트",
    "exit",
    "탈출",
    "매물",
    "우선협상",
    "주관사",
    "입찰",
    "상장폐지",
    "블록딜",
    "SPA",
    "본계약",
    "클로징",
    "자금 납입",
    "세컨더리",
    "컨티뉴에이션",
]
DEAL_FINANCING_KEYWORDS = [
    "리캡",
    "인수금융",
    "리파이낸싱",
    "사모대출",
    "프라이빗크레딧",
    "private credit",
    "메자닌",
    "전환사채",
    "CB",
    "대출",
    "파이낸싱",
]
DEAL_OWNERSHIP_KEYWORDS = ["포트폴리오", "밸류업", "PMI", "구조조정", "턴어라운드", "운영 개선", "체질 개선", "실적"]
DEAL_ISSUE_KEYWORDS = ["무산", "분쟁", "소송", "가격 이견", "리스크", "부실", "시끌", "장고"]
LP_FOCUS_KEYWORDS = [
    "LP",
    "출자자",
    "기관투자가",
    "연기금",
    "공제회",
    "국민연금",
    "사학연금",
    "교직원공제",
    "행정공제",
    "군인공제",
    "새마을금고",
    "모태펀드",
    "성장금융",
    "한국벤처투자",
    "국민성장펀드",
    "자산배분",
    "대체투자",
    "출자사업",
    "출자공고",
    "위탁운용",
    "운용사 선정",
    "출자확약",
    "공제사업",
    "공제회",
    "연기금",
    "중소기업중앙회",
    "노란우산공제",
    "자산운용본부",
    "자산운용본부장",
    "자산운용부서장",
    "RFP",
    "커밋먼트",
    "분배금",
    "DPI",
]
GP_FOCUS_KEYWORDS = [
    "GP",
    "운용사",
    "PE하우스",
    "대표",
    "파트너",
    "심사역",
    "인력",
    "조직",
    "복귀",
    "선임",
    "영입",
    "펀드 결성",
    "펀드레이징",
    "펀드 조성",
    "펀드 도전",
    "약정총액",
    "목표액",
    "블라인드펀드",
    "하우스 전략",
    "운용전략",
    "플랫폼",
]
MARKET_KEYWORDS = ["규제", "금감원", "금융위", "금융감독원", "내부통제", "자본시장법", "세제", "과세", "시장", "전망", "동향", "트렌드"]


def has_ai_theme(text: str) -> bool:
    return bool(AI_SHORT_RE.search(text)) or contains_any(text, AI_THEME_KEYWORDS)


def legacy_section_to_current(raw_section: str, title_text: str) -> str:
    raw_text = raw_section or ""
    if "AI & PE" in raw_text:
        return "AI & PE"
    if raw_text.strip() == "LP":
        return "LP"
    if raw_text.strip() == "GP":
        return "GP"
    if "Credit" in raw_text or "크레딧" in raw_text or "Portfolio" in raw_text or "포트폴리오" in raw_text:
        return "Deal"
    if "Deal" in raw_text or "딜" in raw_text or "엑시트" in raw_text or "거래" in raw_text:
        return "Deal"
    if "LP 출자" in raw_text or "LP / 출자자" in raw_text:
        return "LP" if contains_any(title_text, LP_FOCUS_KEYWORDS) else "Market"
    if "펀드·출자" in raw_text or "Fundraising" in raw_text or "펀드레이징" in raw_text or "펀드 결성" in raw_text:
        return "GP"
    if "GP" in raw_text or "운용사" in raw_text:
        return "GP"
    if "Regulation" in raw_text or "규제" in raw_text:
        return "Market"
    return "Market"


def editorial_section(row: dict[str, str]) -> str:
    title = row.get("title", "")
    raw_section = row.get("section", "")
    title_text = title
    combined = f"{title_text} {raw_section}"
    if has_ai_theme(combined) and contains_any(combined, DEAL_SIGNAL_KEYWORDS + DEAL_FINANCING_KEYWORDS + LP_FOCUS_KEYWORDS + GP_FOCUS_KEYWORDS):
        return "AI & PE"
    if contains_any(title_text, ["펀드 결성", "펀드레이징", "펀드 조성", "펀드 도전", "클로징", "약정총액", "목표액", "블라인드펀드"]):
        return "GP"
    if contains_any(title_text, DEAL_FINANCING_KEYWORDS + DEAL_SIGNAL_KEYWORDS + DEAL_OWNERSHIP_KEYWORDS + DEAL_ISSUE_KEYWORDS):
        return "Deal"
    if contains_any(title_text, LP_FOCUS_KEYWORDS):
        return "LP"
    if contains_any(title_text, GP_FOCUS_KEYWORDS):
        return "GP"
    if contains_any(title_text, MARKET_KEYWORDS):
        return "Market"
    return legacy_section_to_current(raw_section, title_text)


def editorial_subtype(row: dict[str, str], section: str) -> str:
    title = row.get("title", "")
    raw_section = row.get("section", "")
    text = f"{title} {raw_section}"
    if section == "AI & PE":
        if contains_any(text, ["규제", "저작권", "IP", "보안", "거버넌스", "모델 리스크"]):
            return "AI 리스크·규제"
        if contains_any(text, ["데이터센터", "data center", "GPU", "AI 반도체", "AI반도체", "인프라", "컴퓨트", "클라우드"]):
            return "AI 투자·인프라"
        return "AI 전략·운영"
    if section == "Deal":
        if contains_any(text, DEAL_FINANCING_KEYWORDS):
            return "Financing"
        if contains_any(text, ["세컨더리", "컨티뉴에이션", "continuation"]):
            return "Secondary"
        if contains_any(text, DEAL_ISSUE_KEYWORDS):
            return "Issue"
        if contains_any(text, ["밸류업", "PMI", "구조조정", "턴어라운드", "운영 개선", "실적"]):
            return "Ownership"
        if contains_any(text, ["엑시트", "회수", "매각", "IPO", "블록딜", "청산"]):
            return "Exit"
        if contains_any(text, ["SPA", "본계약", "계약 체결", "클로징", "자금 납입", "마무리", "완료"]):
            return "Signing·Closing"
        if contains_any(text, ["입찰", "우선협상", "숏리스트", "주관사", "매각주관"]):
            return "Auction"
        return "Acquisition"
    if section == "LP":
        if contains_any(text, ["출자사업", "출자공고", "위탁운용", "운용사 선정", "RFP", "출자확약", "앵커"]):
            return "Mandate"
        if contains_any(text, ["자산배분", "대체투자", "투자정책", "리밸런싱", "국민성장펀드"]):
            return "Allocation"
        if contains_any(text, ["분배금", "DPI", "수익률", "성과", "포트폴리오"]):
            return "Portfolio Review"
        if contains_any(text, ["LP 세컨더리", "유동성", "지분 매각"]):
            return "Liquidity"
        return "Governance"
    if section == "GP":
        if contains_any(text, ["펀드 결성", "펀드레이징", "펀드 조성", "펀드 도전", "클로징", "약정총액", "목표액", "블라인드펀드"]):
            return "Fundraising"
        if contains_any(text, ["대표", "파트너", "심사역", "영입", "선임", "복귀", "승진", "인력"]):
            return "People"
        if contains_any(text, ["조직", "사무소", "부문", "플랫폼", "계열", "법인"]):
            return "Organization"
        if contains_any(text, ["트랙레코드", "성과", "과거 딜", "회수 성과"]):
            return "Track Record"
        return "Strategy"
    if contains_any(text, ["규제", "금융위", "금감원", "자본시장법", "세제", "공정위", "제재", "소송"]):
        return "Regulation"
    if contains_any(text, ["금리", "환율", "유동성", "대출시장", "스프레드", "레버리지"]):
        return "Capital Market"
    if contains_any(text, ["통계", "리그테이블", "시장 규모", "설문", "리포트", "데이터"]):
        return "Data"
    if contains_any(text, ["섹터", "트렌드", "밸류업", "테마"]):
        return "Sector Theme"
    return "Market View"


def publisher_badge(source: str) -> str:
    source = (source or "").strip()
    if source in PUBLISHER_BADGES:
        return PUBLISHER_BADGES[source]
    compact = re.sub(r"[^0-9A-Za-z가-힣]", "", source)
    return compact[:1] or "뉴"


def source_domain(url: str) -> str:
    hostname = urlparse(url or "").hostname or ""
    return hostname.removeprefix("www.")


def source_icon_url(url: str) -> str:
    domain = source_domain(url)
    if not domain:
        return ""
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"


def section_sort_key(section: str) -> int:
    try:
        return EDITORIAL_SECTIONS.index(section)
    except ValueError:
        return len(EDITORIAL_SECTIONS)


def split_semicolon(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def add_unique(items: list[str], value: str) -> None:
    value = str(value or "").strip()
    if value and value not in items:
        items.append(value)


def service_action_label(action: str, context_action: str = "") -> str:
    text = f"{action} {context_action}"
    if "프로필 필수정보" in text:
        return "프로필 보강"
    if "식별자" in text:
        return "식별자 보강"
    if "People 1차" in text:
        return "인물 수집"
    if "한글명" in text:
        return "인물 검증"
    if "GP 프로필" in text or "GP/People" in text:
        return "DB 연결"
    return ""


def read_service_context(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    context: dict[str, dict[str, object]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            url = normalize_url(str(row.get("latest_url") or "").strip())
            if not url:
                continue
            entry = context.setdefault(
                url,
                {
                    "gpNames": [],
                    "searchTerms": [],
                    "peopleCount": 0,
                    "serviceActions": [],
                },
            )
            gp_names = entry["gpNames"]
            search_terms = entry["searchTerms"]
            add_unique(gp_names, row.get("standard_gp_name", ""))
            add_unique(search_terms, row.get("standard_gp_name", ""))
            for alias in split_semicolon(row.get("matched_aliases", "")):
                add_unique(search_terms, alias)
            try:
                entry["peopleCount"] = int(entry["peopleCount"]) + int(float(row.get("people_count") or 0))
            except ValueError:
                pass
            action = service_action_label(
                str(row.get("integrated_action") or ""),
                str(row.get("newsletter_context_action") or ""),
            )
            add_unique(entry["serviceActions"], action)

    for entry in context.values():
        actions = entry.pop("serviceActions", [])
        entry["serviceAction"] = actions[0] if actions else ""
    return context


def lp_display_title(title: str) -> str:
    text = re.sub(r"\s+NEW$", "", normalize_whitespace(title), flags=re.IGNORECASE)
    if "공고일:" in text:
        text = re.sub(r"^.*?공고일:\s*20\d{2}-\d{2}-\d{2}\s*", "", text)
    text = re.sub(r"신청기한:\s*20\d{2}-\d{2}-\d{2}\s*", "", text)
    text = re.sub(r"선정\(예정\)일:\s*(?:20\d{2}-\d{2}-\d{2})?\s*", "", text)
    text = re.sub(r"결성\(예정\)일:\s*(?:20\d{2}-\d{2}-\d{2})?\s*", "", text)
    text = re.sub(r"^(?:\[[^\]]+\]\s*)+", "", text)
    text = text.replace("-->", "")
    return normalize_whitespace(text) or title


def lp_dedupe_title(title: str) -> str:
    text = lp_display_title(title)
    text = re.sub(r"^20\d{2}년\s*", "", text)
    text = re.sub(r"^20\d{2}\s*", "", text)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).lower()


def lp_source_priority(item: dict[str, object]) -> int:
    source_code = str(item.get("sourceCode") or "")
    if source_code in PRIMARY_LP_SOURCE_CODES:
        return 3
    if source_code and source_code not in BACKUP_LP_SOURCE_CODES:
        return 2
    return 1


def lp_item_quality(item: dict[str, object]) -> tuple[int, int, int, str]:
    has_document = 1 if item.get("documentUrl") or item.get("attachments") else 0
    has_deadline = 1 if item.get("applicationDeadline") else 0
    return (
        lp_source_priority(item),
        has_document,
        has_deadline,
        str(item.get("eventDate") or ""),
    )


def compact_date_int(value: object) -> int:
    text = str(value or "")[:10]
    return int(text.replace("-", "")) if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text) else 0


def lp_public_sort_key(item: dict[str, object]) -> tuple[int, int, int, int]:
    today = today_seoul()
    deadline = str(item.get("applicationDeadline") or "")
    has_upcoming_deadline = bool(deadline and deadline >= today)
    date_value = deadline if has_upcoming_deadline else str(item.get("eventDate") or item.get("announcedDate") or "")
    return (
        0 if has_upcoming_deadline else 1,
        LP_EVENT_PRIORITY.get(str(item.get("eventType") or ""), 9),
        -compact_date_int(date_value),
        -lp_source_priority(item),
    )


def merge_lp_item(primary: dict[str, object], secondary: dict[str, object]) -> dict[str, object]:
    merged = dict(primary)
    for key in [
        "applicationDeadline",
        "announcedDate",
        "eventDate",
        "assetClass",
        "strategy",
        "purpose",
        "programName",
        "roundName",
    ]:
        if not merged.get(key) and secondary.get(key):
            merged[key] = secondary[key]
    if not merged.get("attachments") and secondary.get("attachments"):
        merged["attachments"] = secondary["attachments"]
    if not merged.get("documentUrl") and secondary.get("documentUrl"):
        merged["documentUrl"] = secondary["documentUrl"]
    return merged


def read_lp_monitor(path: Path, limit: int = 8) -> list[dict[str, object]]:
    if not path.exists():
        return []
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            title = str(row.get("title") or "").strip()
            notice_url = str(row.get("notice_url") or "").strip()
            if not title or not notice_url:
                continue
            if str(row.get("source_type") or "").strip() != "official":
                continue
            if str(row.get("public_visible") or "1").strip() in {"0", "false", "False"}:
                continue
            if row.get("event_type") == "candidate":
                continue
            attachment_names = split_semicolon(row.get("attachment_names", ""))
            attachment_urls = split_semicolon(row.get("attachment_urls", ""))
            attachments = [
                {"name": attachment_names[index] if index < len(attachment_names) else f"공식 첨부파일 {index + 1}", "url": url}
                for index, url in enumerate(attachment_urls)
                if url
            ]
            document_url = row.get("document_url", "")
            if document_url and not attachments:
                attachments.insert(0, {"name": "공식 첨부파일", "url": document_url})
            display_title = lp_display_title(title)
            purpose = row.get("strategy", "") or row.get("program_name", "") or row.get("round_name", "")
            item = {
                "noticeId": row.get("notice_id", ""),
                "lpName": row.get("lp_name", "") or "LP 미분류",
                "lpType": row.get("lp_type", ""),
                "defaultTeam": row.get("default_team", ""),
                "sourceCode": row.get("source_code", ""),
                "sourceType": row.get("source_type", ""),
                "eventType": row.get("event_type", ""),
                "eventDate": row.get("event_date", "") or row.get("announced_date", ""),
                "title": title,
                "displayTitle": display_title,
                "url": notice_url,
                "documentUrl": document_url,
                "programName": row.get("program_name", ""),
                "roundName": row.get("round_name", ""),
                "purpose": purpose,
                "announcedDate": row.get("announced_date", ""),
                "noticeYear": row.get("notice_year", ""),
                "applicationDeadline": row.get("application_deadline", ""),
                "stage": row.get("notice_stage", ""),
                "assetClass": row.get("asset_class", ""),
                "strategy": row.get("strategy", ""),
                "allocationAmount": row.get("allocation_amount_krw_100mn", "") or row.get("commitment_amount_krw_100mn", ""),
                "programSize": row.get("program_size_krw_100mn", ""),
                "amountConfidence": row.get("amount_confidence", ""),
                "confidence": row.get("confidence", ""),
                "selectedGpNames": split_semicolon(row.get("selected_gp_names", "")),
                "attachments": attachments,
            }
            dedupe_key = (str(item["lpName"]), lp_dedupe_title(title))
            current = grouped.get(dedupe_key)
            if current is None or lp_item_quality(item) > lp_item_quality(current):
                grouped[dedupe_key] = merge_lp_item(item, current or {})
            else:
                grouped[dedupe_key] = merge_lp_item(current, item)
    rows = list(grouped.values())
    rows.sort(key=lp_public_sort_key)
    return rows[:limit]


def article_payload_rows(
    rows: list[dict[str, str]],
    service_context: dict[str, dict[str, object]] | None = None,
    id_prefix: str = "clip",
) -> list[dict[str, object]]:
    service_context = service_context or {}
    payload: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        section = editorial_section(row)
        subtype = editorial_subtype(row, section)
        article_url = row.get("url", "")
        context = service_context.get(normalize_url(article_url), service_context.get(article_url, {}))
        display_title, title_badges = split_news_title_badges(row.get("title", ""), row.get("source", ""))
        payload.append(
            {
                "id": f"{id_prefix}-{index}",
                "rank": index,
                "section": section,
                "subCategory": subtype,
                "rawSection": row.get("section", ""),
                "title": display_title,
                "titleBadges": title_badges,
                "source": row.get("source", ""),
                "sourceBadge": publisher_badge(row.get("source", "")),
                "sourceIconUrl": source_icon_url(row.get("url", "")),
                "url": row.get("url", ""),
                "sectionOrder": section_sort_key(section),
                "gpNames": context.get("gpNames", []),
                "peopleCount": context.get("peopleCount", 0),
                "searchTerms": context.get("searchTerms", []),
            }
        )
    return payload


def article_payload(rows: list[dict[str, str]], service_context: dict[str, dict[str, object]] | None = None) -> str:
    payload = article_payload_rows(rows, service_context)
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def build_archive_payload(
    out_dir: Path,
    selected_report_date: str,
    service_context: dict[str, dict[str, object]],
    archive_limit: int,
) -> list[dict[str, object]]:
    dates = report_dates(out_dir)
    if selected_report_date and selected_report_date not in dates:
        dates.insert(0, selected_report_date)
    if archive_limit > 0:
        dates = dates[:archive_limit]
    payload: list[dict[str, object]] = []
    for report_date in dates:
        markdown_path = out_dir / f"daily_news_brief_{compact_date(report_date)}.md"
        rows = parse_brief(markdown_path)
        if not rows and report_date != selected_report_date:
            continue
        payload.append(
            {
                "reportDate": report_date,
                "visibleDate": display_date(report_date),
                "basis": "",
                "countLabel": brief_count_label(len(rows)),
                "articles": article_payload_rows(rows, service_context, f"clip-{compact_date(report_date)}"),
            }
        )
    return payload


def render_app(
    report_date: str,
    articles: list[dict[str, str]],
    basis_text: str = "",
    service_context: dict[str, dict[str, object]] | None = None,
    archive_entries: list[dict[str, object]] | None = None,
    lp_monitor: list[dict[str, object]] | None = None,
    newsletter_only: bool = False,
) -> str:
    archive_entries = archive_entries or [
        {
            "reportDate": report_date,
            "visibleDate": display_date(report_date),
            "basis": "",
            "countLabel": brief_count_label(len(articles)),
            "articles": article_payload_rows(articles, service_context),
        }
    ]
    payload = json.dumps(archive_entries, ensure_ascii=False).replace("</", "<\\/")
    lp_payload = json.dumps(lp_monitor or [], ensure_ascii=False).replace("</", "<\\/")
    visible_date = display_date(report_date)
    basis = html_escape(basis_text)
    count_label = brief_count_label(len(articles))
    date_options = "\n".join(
        f'          <option value="{html_escape(str(entry.get("reportDate", "")))}"'
        f'{" selected" if entry.get("reportDate") == report_date else ""}>'
        f'{html_escape(str(entry.get("visibleDate", entry.get("reportDate", ""))))}</option>'
        for entry in archive_entries
    )
    available_dates = [str(entry.get("reportDate", "")) for entry in archive_entries if entry.get("reportDate")]
    min_date = min(available_dates) if available_dates else report_date
    max_date = max(available_dates) if available_dates else report_date
    shell_class = "app-shell newsletter-only" if newsletter_only else "app-shell"
    header_db_link = (
        '<a class="header-action" href="lp-notices.html" aria-label="LP 공식 공고 열기">공고</a>'
        if newsletter_only
        else '<a class="header-action" href="db.html" aria-label="공개 GP·펀드 데이터베이스 열기">DB</a>'
    )
    lp_db_link = "" if newsletter_only else '<a href="db.html#lp">LP DB</a>'
    bottom_db_link = (
        """      <a href="lp-notices.html">
        <span aria-hidden="true" class="nav-dot nav-icon-db"></span>
        <strong>공고</strong>
      </a>"""
        if newsletter_only
        else """      <a href="db.html">
        <span aria-hidden="true" class="nav-dot nav-icon-db"></span>
        <strong>DB</strong>
      </a>"""
    )
    search_placeholder = "뉴스·GP 검색" if newsletter_only else "뉴스·공식공고·GP 검색"
    lp_monitor_section = (
        ""
        if newsletter_only
        else f"""      <section class="lp-monitor-panel" id="lpMonitorPanel" aria-label="공식 출자공고" hidden>
        <div class="lp-monitor-head">
          <h2>공식 출자공고</h2>
          {lp_db_link}
        </div>
        <div class="lp-monitor-list" id="lpMonitorList"></div>
      </section>

"""
    )
    lp_detail_markup = (
        ""
        if newsletter_only
        else """    <div class="lp-detail-backdrop" id="lpDetailBackdrop" hidden></div>
    <section class="lp-detail-sheet" id="lpDetailSheet" aria-label="출자공고 상세" aria-modal="true" role="dialog" hidden>
      <div class="lp-detail-head">
        <span>출자공고 상세</span>
        <button type="button" id="lpDetailClose" aria-label="닫기"></button>
      </div>
      <div id="lpDetailBody"></div>
    </section>

"""
    )
    lp_monitor_script = "" if newsletter_only else f"  <script>window.KPEF_LP_MONITOR = {lp_payload};</script>\n"
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Korea PEF Intelligence Daily</title>
  <link rel="stylesheet" href="assets/service.css">
</head>
<body>
  <div class="{shell_class}">
    <header class="app-header">
      <div class="header-topline">
        <div>
          <p>Korea PEF Intelligence</p>
          <strong>Daily Brief</strong>
        </div>
        <div class="header-actions">
          <button class="header-icon search-toggle" id="searchToggle" type="button" aria-label="검색 열기"></button>
          {header_db_link}
        </div>
      </div>
      <div class="date-control" aria-label="브리프 날짜 탐색">
        <button class="date-step date-prev" id="datePrev" type="button" aria-label="이전 날짜"></button>
        <div class="date-current">
          <span id="briefDateLabel">{html_escape(visible_date)}</span>
          <small id="briefWeekday">{html_escape(weekday_label(report_date))}</small>
          <input class="date-native" id="briefDateInput" type="date" value="{html_escape(report_date)}" min="{html_escape(min_date)}" max="{html_escape(max_date)}" aria-label="브리프 날짜 선택">
        </div>
        <button class="date-step date-next" id="dateNext" type="button" aria-label="다음 날짜"></button>
      </div>
      <label class="date-label" for="briefDateSelect">브리프 날짜</label>
      <select class="date-select" id="briefDateSelect" aria-label="브리프 날짜 선택">
{date_options}
      </select>
      <div class="brief-meta" id="briefMeta">{html_escape(count_label)}</div>
    </header>

    <section class="search-area" id="searchArea" aria-label="기사 검색">
      <label class="search-box">
        <span aria-hidden="true"></span>
        <input id="clipSearch" type="search" placeholder="{html_escape(search_placeholder)}" autocomplete="off">
      </label>
      <button class="search-close" id="searchClose" type="button" aria-label="검색 닫기"></button>
    </section>

    <main class="content-area">
{lp_monitor_section}
      <section id="todayView" class="view active" aria-label="오늘 브리프">
        <div class="skeleton-list" aria-hidden="true">
          <div></div><div></div><div></div>
        </div>
        <div id="todayList"></div>
      </section>

      <section id="savedView" class="view" aria-label="저장한 기사">
        <div class="empty-state" id="savedEmpty">
          <strong>저장한 기사가 없습니다</strong>
          <span>나중에 볼 기사는 오른쪽 버튼으로 저장합니다.</span>
        </div>
        <div id="savedList"></div>
      </section>
    </main>

{lp_detail_markup}
    <nav class="bottom-nav" aria-label="하단 메뉴">
      <button class="active" type="button" data-view="today">
        <span aria-hidden="true" class="nav-dot nav-icon-brief"></span>
        <strong>브리프</strong>
      </button>
      <button type="button" data-view="saved">
        <span aria-hidden="true" class="nav-dot nav-icon-saved"></span>
        <strong>저장</strong>
      </button>
{bottom_db_link}
    </nav>
  </div>
  <script>window.KPEF_DAILY_ARCHIVE = {payload};</script>
{lp_monitor_script}  <script src="assets/service.js"></script>
</body>
</html>
"""


def service_css() -> str:
    return """@charset "utf-8";
:root {
  --bg: #f5f5f7;
  --surface: #ffffff;
  --surface-muted: #f2f2f7;
  --text: #111111;
  --secondary: #6e6e73;
  --tertiary: #9a9aa0;
  --separator: #e5e5ea;
  --accent: #111111;
  --blue: #007aff;
  --radius: 18px;
  --shell: 520px;
}
* { box-sizing: border-box; }
html { min-height: 100%; background: var(--bg); }
body {
  margin: 0;
  min-height: 100%;
  color: var(--text);
  background: var(--bg);
  font-family: Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
}
a { color: inherit; text-decoration: none; }
button, input { font: inherit; }
.app-shell {
  width: min(100%, var(--shell));
  min-height: 100vh;
  margin: 0 auto;
  background: var(--bg);
  padding: max(14px, env(safe-area-inset-top)) 14px calc(88px + env(safe-area-inset-bottom));
}
.app-header {
  display: grid;
  gap: 10px;
  padding: 4px 2px 10px;
}
.header-topline {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 40px;
  padding-right: 48px;
}
.header-topline > div { min-width: 0; }
.app-header p {
  margin: 0 0 2px;
  color: var(--secondary);
  font-size: 13px;
  line-height: 1.2;
}
.app-header strong {
  display: block;
  margin: 0;
  font-size: 20px;
  line-height: 1.2;
  font-weight: 700;
  letter-spacing: 0;
}
.date-control {
  display: flex;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 2px;
}
.date-control::before,
.date-control::after {
  content: "";
  flex: 1 1 24px;
  height: 1px;
  background: var(--separator);
}
.date-step {
  display: inline-flex;
  width: 40px;
  height: 40px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--separator);
  border-radius: 50%;
  background: var(--surface);
  color: var(--secondary);
  cursor: pointer;
}
.date-step::before {
  content: "";
  width: 16px;
  height: 16px;
  background: currentColor;
  -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='m15 5-7 7 7 7' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
  mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='m15 5-7 7 7 7' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
}
.date-next::before { transform: rotate(180deg); }
.date-step:disabled {
  opacity: 0.32;
  cursor: default;
}
.date-current {
  position: relative;
  display: grid;
  min-width: 164px;
  height: 44px;
  align-content: center;
  justify-items: center;
  gap: 1px;
  border-radius: 999px;
  background: var(--surface);
  color: var(--text);
  box-shadow: inset 0 0 0 1px rgba(0,0,0,0.06);
}
.date-current span {
  font-size: 16px;
  line-height: 1.1;
  font-weight: 650;
}
.date-current small {
  color: var(--secondary);
  font-size: 11px;
  line-height: 1.1;
  font-weight: 500;
}
.date-native {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}
.date-label {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}
.date-select {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}
.date-select:focus {
  box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.16);
}
.brief-meta {
  max-width: 390px;
  margin-top: -1px;
  color: var(--secondary);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.header-actions {
  display: flex;
  position: absolute;
  top: 0;
  right: 0;
  z-index: 2;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
}
.header-icon,
.header-action {
  display: inline-flex;
  position: relative;
  width: 40px;
  height: 40px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(0,0,0,0.06);
  border-radius: 50%;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  box-shadow: 0 1px 8px rgba(0,0,0,0.03);
}
.header-icon::before {
  content: "";
  width: 18px;
  height: 18px;
  background: currentColor;
}
.search-toggle::before {
  width: 14px;
  height: 14px;
  border: 2px solid currentColor;
  border-radius: 50%;
  background: transparent;
}
.search-toggle::after {
  content: "";
  position: absolute;
  width: 7px;
  height: 2px;
  right: 11px;
  bottom: 11px;
  border-radius: 2px;
  background: currentColor;
  transform: rotate(45deg);
}
.header-action {
  display: none;
  flex: 0 0 56px;
  width: 56px;
  height: 34px;
  white-space: nowrap;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 650;
}
.search-area {
  display: none;
  position: sticky;
  top: 0;
  z-index: 5;
  gap: 8px;
  padding: 4px 0 10px;
  background: rgba(245,245,247,0.92);
  backdrop-filter: blur(18px);
}
.search-area.active { display: flex; }
.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 42px;
  padding: 0 13px;
  border-radius: 14px;
  background: #e9e9ee;
}
.search-box span {
  width: 13px;
  height: 13px;
  border: 2px solid var(--tertiary);
  border-radius: 50%;
  position: relative;
  flex: 0 0 auto;
}
.search-box span::after {
  content: "";
  position: absolute;
  width: 6px;
  height: 2px;
  right: -5px;
  bottom: -3px;
  border-radius: 2px;
  background: var(--tertiary);
  transform: rotate(45deg);
}
.search-box input {
  width: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text);
  font-size: 16px;
}
.search-box input::placeholder { color: #8e8e93; }
.search-close {
  display: inline-flex;
  position: relative;
  flex: 0 0 42px;
  width: 42px;
  height: 42px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 50%;
  background: var(--surface);
  color: var(--secondary);
  cursor: pointer;
}
.search-close::before,
.search-close::after {
  content: "";
  position: absolute;
  width: 16px;
  height: 2px;
  border-radius: 2px;
  background: currentColor;
}
.search-close::before { transform: rotate(45deg); }
.search-close::after { transform: rotate(-45deg); }
.content-area { display: grid; gap: 14px; }
.lp-monitor-panel {
  display: grid;
  gap: 8px;
  margin: 0 0 2px;
}
.lp-monitor-panel[hidden] { display: none; }
.lp-monitor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 4px;
}
.lp-monitor-head h2 {
  margin: 0;
  color: var(--text);
  font-size: 13px;
  line-height: 1.3;
  font-weight: 650;
}
.lp-monitor-head a {
  color: var(--secondary);
  font-size: 12px;
  font-weight: 650;
}
.lp-monitor-list {
  display: flex;
  gap: 8px;
  margin: 0 -14px;
  padding: 0 14px 4px;
  overflow-x: auto;
  scroll-snap-type: x proximity;
  scrollbar-width: none;
  touch-action: pan-x;
  -webkit-overflow-scrolling: touch;
}
.lp-monitor-list::-webkit-scrollbar { display: none; }
.lp-monitor-list::after {
  content: "";
  flex: 0 0 6px;
}
.lp-monitor-item {
  display: grid;
  flex: 0 0 min(78vw, 342px);
  gap: 6px;
  width: min(78vw, 342px);
  min-height: 92px;
  padding: 11px 12px;
  border: 1px solid var(--separator);
  border-radius: 14px;
  background: var(--surface);
  color: inherit;
  text-align: left;
  cursor: pointer;
  scroll-snap-align: start;
}
.lp-monitor-item:active { background: var(--surface-muted); }
.lp-monitor-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.lp-badge {
  display: inline-flex;
  min-height: 22px;
  align-items: center;
  border-radius: 999px;
  padding: 3px 7px;
  background: var(--surface-muted);
  color: var(--secondary);
  font-size: 11px;
  line-height: 1.2;
  font-weight: 650;
}
.lp-badge.urgent {
  background: #fff2e8;
  color: #a23b00;
}
.lp-badge.official {
  background: #eaf7ee;
  color: #176c35;
}
.lp-monitor-item strong {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  font-size: 14px;
  line-height: 1.34;
  font-weight: 650;
}
.lp-monitor-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 7px;
  color: var(--secondary);
  font-size: 12px;
  line-height: 1.3;
}
.lp-monitor-meta span + span::before {
  content: "·";
  margin-right: 7px;
  color: var(--tertiary);
}
.lp-detail-backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: rgba(0,0,0,0.28);
}
.lp-detail-backdrop[hidden],
.lp-detail-sheet[hidden] { display: none; }
.lp-detail-sheet {
  position: fixed;
  left: 50%;
  bottom: 0;
  z-index: 41;
  display: grid;
  gap: 16px;
  width: min(100%, var(--shell));
  max-height: min(82vh, 720px);
  overflow: auto;
  transform: translateX(-50%);
  padding: 14px 16px calc(18px + env(safe-area-inset-bottom));
  border-radius: 22px 22px 0 0;
  background: var(--surface);
  box-shadow: 0 -18px 60px rgba(0,0,0,0.18);
}
.lp-detail-head {
  position: sticky;
  top: -14px;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 0 8px;
  background: var(--surface);
  color: var(--secondary);
  font-size: 12px;
  font-weight: 650;
}
.lp-detail-head button {
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 50%;
  background: var(--surface-muted);
  color: var(--secondary);
  cursor: pointer;
}
.lp-detail-head button::before {
  content: "×";
  font-size: 22px;
  line-height: 1;
}
.lp-detail-title {
  margin: 0 0 8px;
  color: var(--text);
  font-size: 19px;
  line-height: 1.32;
  font-weight: 700;
}
.lp-detail-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}
.lp-detail-summary span {
  min-height: 24px;
  border-radius: 999px;
  padding: 4px 8px;
  background: var(--surface-muted);
  color: var(--secondary);
  font-size: 12px;
  line-height: 1.3;
  font-weight: 650;
}
.lp-detail-grid {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 10px 12px;
  margin: 0;
  padding: 14px 0;
  border-top: 1px solid var(--separator);
  border-bottom: 1px solid var(--separator);
}
.lp-detail-grid dt {
  color: var(--secondary);
  font-size: 12px;
  line-height: 1.35;
  font-weight: 650;
}
.lp-detail-grid dd {
  margin: 0;
  min-width: 0;
  color: var(--text);
  font-size: 14px;
  line-height: 1.42;
  overflow-wrap: anywhere;
}
.lp-detail-actions,
.lp-attachment-list {
  display: grid;
  gap: 8px;
  margin-top: 14px;
}
.lp-detail-actions a,
.lp-attachment-list a {
  display: flex;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: var(--surface-muted);
  color: var(--text);
  font-size: 13px;
  line-height: 1.3;
  font-weight: 650;
}
.lp-detail-actions a::after,
.lp-attachment-list a::after {
  content: "↗";
  color: var(--tertiary);
  font-size: 14px;
  flex: 0 0 auto;
}
.lp-attachment-title {
  margin: 16px 0 0;
  color: var(--secondary);
  font-size: 12px;
  line-height: 1.3;
  font-weight: 650;
}
.view { display: none; }
.view.active { display: block; }
.section-block { margin: 8px 0 18px; }
.section-title {
  margin: 0;
  padding: 0 4px 9px;
  color: var(--text);
  font-size: 13px;
  line-height: 1.3;
  font-weight: 650;
}
.cell-list {
  margin: 0;
  padding: 0;
  list-style: none;
  overflow: hidden;
  border-radius: var(--radius);
  background: var(--surface);
}
.clip-cell {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) 44px;
  gap: 10px;
  min-height: 72px;
  align-items: center;
  padding: 10px 10px 10px 12px;
  border-bottom: 1px solid var(--separator);
}
.clip-cell:last-child { border-bottom: 0; }
.publisher-icon {
  display: inline-flex;
  position: relative;
  width: 34px;
  height: 34px;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 1px solid rgba(0,0,0,0.06);
  border-radius: 10px;
  background: var(--surface-muted);
  color: var(--secondary);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0;
}
.publisher-icon img {
  width: 20px;
  height: 20px;
  object-fit: contain;
}
.publisher-fallback { display: none; }
.publisher-icon.fallback img { display: none; }
.publisher-icon.fallback .publisher-fallback,
.publisher-icon.fallback-only .publisher-fallback { display: inline; }
.cell-main-wrap { min-width: 0; display: grid; gap: 0; }
.cell-main { min-width: 0; display: block; }
.cell-title {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  color: var(--text);
  font-size: 15px;
  line-height: 1.38;
  font-weight: 560;
  letter-spacing: 0;
}
.title-badge {
  display: inline-flex;
  min-height: 18px;
  align-items: center;
  margin-right: 5px;
  transform: translateY(-1px);
  border-radius: 5px;
  padding: 2px 5px;
  background: #fff4d6;
  color: #7a4b00;
  font-size: 10px;
  line-height: 1.1;
  font-weight: 650;
}
.cell-meta {
  display: flex;
  min-width: 0;
  gap: 6px;
  align-items: center;
  margin-top: 4px;
  color: var(--secondary);
  font-size: 13px;
  line-height: 1.2;
}
.cell-meta span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.taxonomy-meta {
  color: var(--text);
  font-weight: 650;
}
.cell-meta span + span::before {
  content: "·";
  margin-right: 6px;
  color: var(--tertiary);
}
.cell-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 7px;
}
.context-chip {
  display: inline-flex;
  max-width: 100%;
  min-height: 22px;
  align-items: center;
  border: 0;
  border-radius: 999px;
  padding: 3px 7px;
  background: var(--surface-muted);
  color: var(--secondary);
  font-size: 11px;
  line-height: 1.2;
  font-weight: 560;
  cursor: pointer;
}
.taxonomy-chip {
  background: #eef5ff;
  color: #0f5fb8;
}
.context-chip:active { background: #e0e0e6; }
.save-button {
  display: inline-flex;
  width: 44px;
  height: 44px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--tertiary);
  cursor: pointer;
}
.save-button::before {
  content: "";
  width: 18px;
  height: 22px;
  background: currentColor;
  -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M6 3.75h12v17l-6-3.6-6 3.6v-17Z' fill='none' stroke='black' stroke-width='2.2' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
  mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M6 3.75h12v17l-6-3.6-6 3.6v-17Z' fill='none' stroke='black' stroke-width='2.2' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
}
.save-button.saved { color: var(--blue); background: rgba(0, 122, 255, 0.09); }
.save-button.saved::before {
  content: "";
  -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M6 3.75h12v17l-6-3.6-6 3.6v-17Z' fill='black'/%3E%3C/svg%3E") center / contain no-repeat;
  mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M6 3.75h12v17l-6-3.6-6 3.6v-17Z' fill='black'/%3E%3C/svg%3E") center / contain no-repeat;
}
.empty-state {
  display: none;
  margin-top: 10px;
  padding: 34px 18px;
  border-radius: var(--radius);
  background: var(--surface);
  text-align: center;
}
.empty-state.visible { display: block; }
.empty-state strong {
  display: block;
  font-size: 16px;
  margin-bottom: 6px;
}
.empty-state span {
  display: block;
  color: var(--secondary);
  font-size: 14px;
  line-height: 1.45;
}
.bottom-nav {
  position: fixed;
  left: 50%;
  bottom: 0;
  z-index: 20;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  width: min(100%, var(--shell));
  transform: translateX(-50%);
  padding: 8px 12px calc(8px + env(safe-area-inset-bottom));
  border-top: 1px solid rgba(0,0,0,0.08);
  background: rgba(249,249,249,0.88);
  backdrop-filter: blur(22px);
}
.newsletter-only .bottom-nav { grid-template-columns: repeat(3, 1fr); }
.bottom-nav button,
.bottom-nav a {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  border: 0;
  background: transparent;
  color: var(--secondary);
  font-size: 11px;
  line-height: 1.1;
  cursor: pointer;
}
.bottom-nav strong { font-weight: 600; }
.bottom-nav .active { color: var(--text); }
.nav-dot {
  display: inline-flex;
  width: 24px;
  height: 24px;
  align-items: center;
  justify-content: center;
  opacity: 0.72;
}
.nav-dot::before {
  content: "";
  width: 22px;
  height: 22px;
  background: currentColor;
}
.nav-icon-brief::before {
  -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M4 5.5h16v13H4v-13Zm3 4h10M7 13h10M7 16h6' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
  mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M4 5.5h16v13H4v-13Zm3 4h10M7 13h10M7 16h6' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
}
.nav-icon-saved::before {
  -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M6 3.75h12v17l-6-3.6-6 3.6v-17Z' fill='none' stroke='black' stroke-width='2.2' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
  mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M6 3.75h12v17l-6-3.6-6 3.6v-17Z' fill='none' stroke='black' stroke-width='2.2' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
}
.nav-icon-db::before {
  -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M5 6c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3Zm0 0v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6' fill='none' stroke='black' stroke-width='2' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
  mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M5 6c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3Zm0 0v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6' fill='none' stroke='black' stroke-width='2' stroke-linejoin='round'/%3E%3C/svg%3E") center / contain no-repeat;
}
.bottom-nav .active .nav-dot { opacity: 1; }
.skeleton-list { display: grid; gap: 1px; overflow: hidden; border-radius: var(--radius); background: var(--surface); }
.skeleton-list div {
  height: 72px;
  background: linear-gradient(90deg, #fff, #f1f1f4, #fff);
  background-size: 220% 100%;
  animation: skeleton 1.4s ease-in-out infinite;
}
.skeleton-list.hidden { display: none; }
@keyframes skeleton {
  0% { background-position: 120% 0; }
  100% { background-position: -120% 0; }
}
@media (min-width: 760px) {
  body { background: #ececf1; }
  .app-shell {
    margin-top: 18px;
    margin-bottom: 18px;
    min-height: calc(100vh - 36px);
    border-radius: 30px;
    box-shadow: 0 24px 80px rgba(0,0,0,0.08);
    overflow: hidden;
  }
  .header-topline { padding-right: 112px; }
  .header-action { display: inline-flex; }
  .bottom-nav { border-radius: 0 0 30px 30px; }
  .lp-detail-sheet {
    top: 50%;
    bottom: auto;
    max-width: 620px;
    border-radius: 22px;
    transform: translate(-50%, -50%);
    padding-bottom: 18px;
  }
}
@media (min-width: 960px) {
  :root { --shell: 1060px; }
  .app-shell {
    padding-right: 22px;
    padding-left: 22px;
  }
  .content-area {
    grid-template-columns: minmax(0, 1fr) 340px;
    gap: 18px;
    align-items: start;
  }
  #todayView,
  #savedView {
    grid-column: 1;
    grid-row: 1;
  }
  .lp-monitor-panel {
    grid-column: 2;
    grid-row: 1 / span 2;
    position: sticky;
    top: 18px;
    margin: 8px 0 0;
    max-height: calc(100vh - 126px);
    overflow: auto;
    padding-right: 2px;
  }
  .lp-monitor-head { padding: 0; }
  .lp-monitor-list {
    display: grid;
    gap: 10px;
    margin: 0;
    padding: 0 0 4px;
    overflow: visible;
    scroll-snap-type: none;
  }
  .lp-monitor-list::after { display: none; }
  .lp-monitor-item {
    width: 100%;
    min-height: 0;
    flex: initial;
    scroll-snap-align: none;
  }
}
"""


def service_js() -> str:
    return """(() => {
  const archive = Array.isArray(window.KPEF_DAILY_ARCHIVE) ? window.KPEF_DAILY_ARCHIVE : [];
  const lpMonitor = Array.isArray(window.KPEF_LP_MONITOR) ? window.KPEF_LP_MONITOR : [];
  const legacyArticles = Array.isArray(window.KPEF_ARTICLES) ? window.KPEF_ARTICLES : [];
  const storageKey = "kpef.saved.urls";
  const searchInput = document.getElementById("clipSearch");
  const searchArea = document.getElementById("searchArea");
  const searchToggle = document.getElementById("searchToggle");
  const searchClose = document.getElementById("searchClose");
  const dateSelect = document.getElementById("briefDateSelect");
  const dateInput = document.getElementById("briefDateInput");
  const dateLabel = document.getElementById("briefDateLabel");
  const weekdayLabel = document.getElementById("briefWeekday");
  const datePrev = document.getElementById("datePrev");
  const dateNext = document.getElementById("dateNext");
  const dateRail = document.getElementById("briefDateRail");
  const briefMeta = document.getElementById("briefMeta");
  const todayList = document.getElementById("todayList");
  const savedList = document.getElementById("savedList");
  const savedEmpty = document.getElementById("savedEmpty");
  const todayView = document.getElementById("todayView");
  const savedView = document.getElementById("savedView");
  const lpMonitorPanel = document.getElementById("lpMonitorPanel");
  const lpMonitorList = document.getElementById("lpMonitorList");
  const lpDetailBackdrop = document.getElementById("lpDetailBackdrop");
  const lpDetailSheet = document.getElementById("lpDetailSheet");
  const lpDetailBody = document.getElementById("lpDetailBody");
  const lpDetailClose = document.getElementById("lpDetailClose");
  const skeleton = document.querySelector(".skeleton-list");
  const navItems = [...document.querySelectorAll(".bottom-nav [data-view]")];
  const showLpMonitor = lpMonitor.length > 0 && Boolean(lpMonitorPanel);

  const loadSaved = () => {
    try {
      return new Set(JSON.parse(localStorage.getItem(storageKey) || "[]"));
    } catch {
      return new Set();
    }
  };

  const queryDate = new URLSearchParams(window.location.search).get("date");
  let activeBrief = archive.find((brief) => brief.reportDate === queryDate) || archive[0] || {
    reportDate: "",
    visibleDate: "",
    basis: "",
    countLabel: `주요 뉴스 ${legacyArticles.length}건`,
    articles: legacyArticles
  };
  let articles = Array.isArray(activeBrief.articles) ? activeBrief.articles : [];
  let saved = loadSaved();
  let currentView = "today";

  const persistSaved = () => {
    localStorage.setItem(storageKey, JSON.stringify([...saved]));
  };

  const setSearchOpen = (open) => {
    if (!searchArea) return;
    const shouldOpen = Boolean(open || queryText());
    searchArea.classList.toggle("active", shouldOpen);
    if (searchToggle) searchToggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
    if (shouldOpen) window.requestAnimationFrame(() => searchInput && searchInput.focus());
  };

  const queryText = () => (searchInput ? searchInput.value.trim().toLowerCase() : "");

  const textMatches = (values, query) => {
    if (!query) return true;
    return values
      .filter((value) => value !== null && value !== undefined)
      .join(" ")
      .toLowerCase()
      .includes(query);
  };

  const allArchiveArticles = () => {
    const byUrl = new Map();
    const briefs = archive.length ? archive : [{
      reportDate: activeBrief.reportDate,
      visibleDate: activeBrief.visibleDate,
      articles: legacyArticles
    }];
    briefs.forEach((brief) => {
      const rows = Array.isArray(brief.articles) ? brief.articles : [];
      rows.forEach((article) => {
        if (!article.url || byUrl.has(article.url)) return;
        byUrl.set(article.url, {
          ...article,
          reportDate: brief.reportDate,
          visibleDate: brief.visibleDate
        });
      });
    });
    return [...byUrl.values()];
  };

  const weekdayName = (dateText) => {
    const date = new Date(`${dateText}T00:00:00+09:00`);
    if (Number.isNaN(date.getTime())) return "";
    return ["일", "월", "화", "수", "목", "금", "토"][date.getDay()];
  };

  const activeBriefIndex = () => archive.findIndex((brief) => brief.reportDate === activeBrief.reportDate);

  const setBriefByOffset = (offset) => {
    const index = activeBriefIndex();
    if (index < 0) return;
    const next = archive[index + offset];
    if (next) setActiveBrief(next.reportDate);
  };

  const updateDateControl = () => {
    const index = activeBriefIndex();
    if (dateInput) dateInput.value = activeBrief.reportDate || "";
    if (dateLabel) dateLabel.textContent = activeBrief.visibleDate || activeBrief.reportDate || "";
    if (weekdayLabel) weekdayLabel.textContent = activeBrief.reportDate ? weekdayName(activeBrief.reportDate) : "";
    if (datePrev) datePrev.disabled = index < 0 || index >= archive.length - 1;
    if (dateNext) dateNext.disabled = index <= 0;
  };

  const updateBriefChrome = (counts = {}) => {
    articles = Array.isArray(activeBrief.articles) ? activeBrief.articles : [];
    if (dateSelect) dateSelect.value = activeBrief.reportDate || "";
    updateDateControl();
    if (dateRail) {
      dateRail.querySelectorAll(".date-pill").forEach((button) => {
        const active = button.dataset.date === activeBrief.reportDate;
        button.classList.toggle("active", active);
        if (active) button.scrollIntoView({ block: "nearest", inline: "center" });
      });
    }
    if (briefMeta) {
      const query = queryText();
      if (query) {
        const newsCount = Number.isFinite(counts.newsCount) ? counts.newsCount : filtered().length;
        if (showLpMonitor) {
          const noticeCount = Number.isFinite(counts.noticeCount) ? counts.noticeCount : filteredLpMonitor().length;
          briefMeta.textContent = `전체 아카이브 검색 결과 뉴스 ${newsCount}건 · 공식공고 ${noticeCount}건`;
        } else {
          briefMeta.textContent = `전체 아카이브 검색 결과 뉴스 ${newsCount}건`;
        }
        return;
      }
      const countLabel = activeBrief.countLabel || `주요 뉴스 ${articles.length}건`;
      briefMeta.textContent = countLabel;
    }
  };

  const setActiveBrief = (reportDate, options = {}) => {
    const next = archive.find((brief) => brief.reportDate === reportDate);
    if (!next) return;
    activeBrief = next;
    updateBriefChrome();
    render();
    if (options.updateUrl !== false && activeBrief.reportDate) {
      const url = new URL(window.location.href);
      url.searchParams.set("date", activeBrief.reportDate);
      window.history.replaceState({}, "", url);
    }
  };

  const articleSearchValues = (article) => [
    article.title,
    article.source,
    article.section,
    article.subCategory,
    article.rawSection,
    article.visibleDate,
    article.reportDate,
    Array.isArray(article.gpNames) ? article.gpNames.join(" ") : "",
    Array.isArray(article.searchTerms) ? article.searchTerms.join(" ") : ""
  ];

  const articleMatches = (article, query) => textMatches(articleSearchValues(article), query);

  const filtered = () => {
    const query = queryText();
    const sourceRows = query ? allArchiveArticles() : articles;
    if (!query) return sourceRows;
    return sourceRows.filter((article) => articleMatches(article, query));
  };

  const filteredLpMonitor = () => {
    if (!showLpMonitor) return [];
    const query = queryText();
    if (!query) return lpMonitor;
    return lpMonitor.filter((item) => textMatches([
      item.title,
      item.displayTitle,
      item.lpName,
      item.programName,
      item.roundName,
      item.purpose,
      item.strategy,
      item.defaultTeam,
      eventLabel(item.eventType),
      assetClassLabel(item.assetClass),
      amountLabel(item.allocationAmount),
      item.announcedDate,
      item.applicationDeadline,
      Array.isArray(item.selectedGpNames) ? item.selectedGpNames.join(" ") : ""
    ], query));
  };

  const issueStopwords = new Set([
    "단독", "인터뷰", "인수", "매각", "매물", "품는다", "사들인다", "추진", "마무리", "엑시트",
    "리캡", "인수금융", "우선협상", "입찰", "지분", "지분매각", "회수", "전망", "기대감", "언급",
    "신규", "최종", "공식", "전략", "전문", "국내", "해외", "업계"
  ]);

  const issueTokens = (article) => {
    const text = [
      article.title,
      Array.isArray(article.gpNames) ? article.gpNames.join(" ") : ""
    ].join(" ");
    return new Set(
      text
        .toLowerCase()
        .replace(/[()[\]'"“”‘’….,·:：]/g, " ")
        .split(/\s+/)
        .map((token) => token.trim())
        .filter((token) => token.length >= 2 && !issueStopwords.has(token))
    );
  };

  const issueOverlap = (left, right) => {
    if (left.section !== right.section) return 0;
    const a = issueTokens(left);
    const b = issueTokens(right);
    let score = 0;
    a.forEach((token) => {
      if (b.has(token)) score += 1;
    });
    return score;
  };

  const clusterOrder = (items) => {
    const remaining = items.slice().sort((a, b) => (a.sectionOrder - b.sectionOrder) || ((a.rank || 0) - (b.rank || 0)));
    const ordered = [];
    while (remaining.length) {
      const seed = remaining.shift();
      ordered.push(seed);
      for (let index = 0; index < remaining.length; index += 1) {
        if (issueOverlap(seed, remaining[index]) >= 2) {
          ordered.push(remaining.splice(index, 1)[0]);
          index -= 1;
        }
      }
    }
    return ordered;
  };

  const groupBySection = (items) => {
    const groups = new Map();
    clusterOrder(items).forEach((article) => {
      if (!groups.has(article.section)) groups.set(article.section, []);
      groups.get(article.section).push(article);
    });
    return groups;
  };

  const eventLabel = (value) => ({
    new_notice: "신규 공고",
    deadline_soon: "마감 임박",
    deadline_closed: "마감",
    shortlist: "숏리스트",
    final_selection: "최종 선정",
    revision: "정정",
    cancellation: "취소",
    performance_update: "성과"
  }[value] || "후보");

  const amountLabel = (value) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return "";
    if (parsed >= 10000) return `${(parsed / 10000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}조`;
    return `${Math.round(parsed).toLocaleString("ko-KR")}억`;
  };

  const assetClassLabel = (value) => {
    const text = String(value || "");
    if (/private credit|credit|크레딧/i.test(text)) return "Credit";
    if (/vc|벤처/i.test(text)) return "VC";
    if (/pe|buyout|private equity|사모/i.test(text)) return "PE";
    return text;
  };

  const daysUntil = (dateText) => {
    if (!dateText) return null;
    const today = new Date();
    const target = new Date(`${dateText}T23:59:59+09:00`);
    if (Number.isNaN(target.getTime())) return null;
    return Math.ceil((target.getTime() - today.getTime()) / 86400000);
  };

  const deadlineBadge = (dateText) => {
    if (!dateText) return null;
    const remaining = daysUntil(dateText);
    if (remaining === null) return { label: "마감일 확인", urgent: false };
    if (remaining > 0) return { label: `D-${remaining}`, urgent: remaining <= 7 };
    if (remaining === 0) return { label: "오늘 마감", urgent: true };
    return { label: "마감", urgent: false };
  };

  const lpMonitorBadges = (item) => {
    const badges = [];
    const deadline = deadlineBadge(item.applicationDeadline);
    if (deadline) badges.push({ ...deadline, type: "deadline" });
    const amount = amountLabel(item.allocationAmount);
    if (amount) badges.push({ label: amount, type: "amount", urgent: false });
    const assetClass = assetClassLabel(item.assetClass);
    if (assetClass) badges.push({ label: assetClass, type: "asset", urgent: false });
    badges.push({ label: "공식", type: "official", urgent: false });
    return badges;
  };

  const scheduleLabel = (item) => {
    if (item.applicationDeadline) {
      const remaining = daysUntil(item.applicationDeadline);
      if (remaining === null) return `신청 마감 ${item.applicationDeadline}`;
      if (remaining > 0) return `신청 마감 ${item.applicationDeadline} · D-${remaining}`;
      if (remaining === 0) return `신청 마감 ${item.applicationDeadline} · 오늘 마감`;
      return `신청 마감 ${item.applicationDeadline} · 마감`;
    }
    if (item.eventDate) return `공고 확인 ${item.eventDate}`;
    return "공식 공고 확인";
  };

  const detailValue = (value, fallback = "-") => {
    if (Array.isArray(value)) return value.filter(Boolean).join(", ") || fallback;
    const text = String(value || "").trim();
    return text || fallback;
  };

  const appendDetailRow = (list, label, value) => {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = detailValue(value);
    list.append(dt, dd);
  };

  const openLpDetail = (item) => {
    if (!lpDetailSheet || !lpDetailBody || !lpDetailBackdrop) return;
    lpDetailBody.replaceChildren();

    const title = document.createElement("h3");
    title.className = "lp-detail-title";
    title.textContent = item.displayTitle || item.title;

    const summary = document.createElement("div");
    summary.className = "lp-detail-summary";
    [item.lpName, eventLabel(item.eventType), assetClassLabel(item.assetClass), amountLabel(item.allocationAmount)]
      .filter(Boolean)
      .forEach((label) => {
        const chip = document.createElement("span");
        chip.textContent = label;
        summary.append(chip);
      });

    const details = document.createElement("dl");
    details.className = "lp-detail-grid";
    appendDetailRow(details, "사업명", item.programName || item.displayTitle || item.title);
    appendDetailRow(details, "기관", item.lpName);
    appendDetailRow(details, "주목적", item.purpose || item.strategy || item.programName);
    appendDetailRow(details, "PE/VC 분류", assetClassLabel(item.assetClass));
    appendDetailRow(details, "담당자/팀", item.defaultTeam);
    appendDetailRow(details, "공고일", item.announcedDate || item.eventDate);
    appendDetailRow(details, "마감일", item.applicationDeadline);
    appendDetailRow(details, "향후 일정", scheduleLabel(item));

    const actions = document.createElement("div");
    actions.className = "lp-detail-actions";
    const official = document.createElement("a");
    official.href = item.url;
    official.target = "_blank";
    official.rel = "noreferrer";
    official.textContent = "공식 공고 보기";
    actions.append(official);

    lpDetailBody.append(title, summary, details, actions);

    const attachments = Array.isArray(item.attachments) ? item.attachments.filter((file) => file && file.url) : [];
    if (attachments.length) {
      const attachmentTitle = document.createElement("h4");
      attachmentTitle.className = "lp-attachment-title";
      attachmentTitle.textContent = "공식 첨부파일";
      const list = document.createElement("div");
      list.className = "lp-attachment-list";
      attachments.forEach((file, index) => {
        const link = document.createElement("a");
        link.href = file.url;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = file.name || `공식 첨부파일 ${index + 1}`;
        list.append(link);
      });
      lpDetailBody.append(attachmentTitle, list);
    }

    lpDetailBackdrop.hidden = false;
    lpDetailSheet.hidden = false;
    document.body.style.overflow = "hidden";
  };

  const closeLpDetail = () => {
    if (!lpDetailSheet || !lpDetailBackdrop) return;
    lpDetailSheet.hidden = true;
    lpDetailBackdrop.hidden = true;
    document.body.style.overflow = "";
  };

  const renderLpMonitor = (items = lpMonitor) => {
    if (!lpMonitorPanel || !lpMonitorList) return;
    const visibleItems = items;
    lpMonitorPanel.hidden = !visibleItems.length;
    lpMonitorList.replaceChildren();
    const headTitle = lpMonitorPanel.querySelector(".lp-monitor-head h2");
    if (headTitle) headTitle.textContent = `공식 공고 ${items.length}건`;
    visibleItems.forEach((item) => {
      const link = document.createElement("button");
      link.type = "button";
      link.className = "lp-monitor-item";
      link.addEventListener("click", () => openLpDetail(item));

      const badges = document.createElement("span");
      badges.className = "lp-monitor-badges";
      lpMonitorBadges(item).forEach((badge) => {
        const pill = document.createElement("span");
        pill.className = `lp-badge ${badge.type || ""} ${badge.urgent ? "urgent" : ""}`.trim();
        pill.textContent = badge.label;
        badges.append(pill);
      });

      const title = document.createElement("strong");
      title.textContent = item.displayTitle || item.title;

      const meta = document.createElement("span");
      meta.className = "lp-monitor-meta";
      [item.lpName, eventLabel(item.eventType), item.applicationDeadline && `마감 ${item.applicationDeadline}`]
        .filter(Boolean)
        .forEach((label) => {
          const part = document.createElement("span");
          part.textContent = label;
          meta.append(part);
        });
      link.append(badges, title, meta);
      lpMonitorList.append(link);
    });
  };

  const makeCell = (article) => {
    const item = document.createElement("li");
    item.className = "clip-cell";

    const mark = document.createElement("span");
    mark.className = "publisher-icon";
    mark.setAttribute("aria-label", article.source || "언론사");
    const fallback = document.createElement("span");
    fallback.className = "publisher-fallback";
    fallback.textContent = article.sourceBadge || "뉴";
    if (article.sourceIconUrl) {
      const icon = document.createElement("img");
      icon.src = article.sourceIconUrl;
      icon.alt = "";
      icon.loading = "lazy";
      icon.addEventListener("error", () => mark.classList.add("fallback"));
      mark.append(icon, fallback);
    } else {
      mark.classList.add("fallback-only");
      mark.append(fallback);
    }

    const main = document.createElement("div");
    main.className = "cell-main-wrap";

    const link = document.createElement("a");
    link.className = "cell-main";
    link.href = article.url;
    link.target = "_blank";
    link.rel = "noreferrer";

    const title = document.createElement("span");
    title.className = "cell-title";
    const titleBadges = Array.isArray(article.titleBadges) ? article.titleBadges.filter(Boolean) : [];
    titleBadges.forEach((label) => {
      const badge = document.createElement("span");
      badge.className = "title-badge";
      badge.textContent = label;
      title.append(badge);
    });
    const titleText = document.createElement("span");
    titleText.textContent = article.title;
    title.append(titleText);

    const meta = document.createElement("span");
    meta.className = "cell-meta";
    const taxonomy = document.createElement("span");
    taxonomy.className = "taxonomy-meta";
    taxonomy.textContent = article.subCategory ? `${article.section} · ${article.subCategory}` : (article.section || "");
    const source = document.createElement("span");
    source.textContent = article.source || "출처 미확인";
    const articleDate = article.visibleDate || article.reportDate || "";
    if (articleDate && (queryText() || article.reportDate !== activeBrief.reportDate)) {
      const date = document.createElement("span");
      date.className = "article-date-meta";
      date.textContent = articleDate;
      meta.append(date);
    }
    if (taxonomy.textContent) meta.append(taxonomy);
    meta.append(source);
    link.append(title, meta);
    main.append(link);

    const chips = document.createElement("span");
    chips.className = "cell-tags";
    const appendChip = (label, extraClass = "") => {
      if (!label) return;
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `context-chip ${extraClass}`.trim();
      chip.dataset.filter = label;
      chip.textContent = label;
      chips.append(chip);
    };
    const gpNames = Array.isArray(article.gpNames) ? article.gpNames.filter(Boolean) : [];
    gpNames.forEach((name) => appendChip(name));
    if (chips.childElementCount) main.append(chips);

    const save = document.createElement("button");
    save.className = "save-button";
    save.type = "button";
    save.dataset.url = article.url;
    const updateSaveState = () => {
      const isSaved = saved.has(article.url);
      save.classList.toggle("saved", isSaved);
      save.setAttribute("aria-label", isSaved ? "저장 해제" : "저장");
      save.title = isSaved ? "저장 해제" : "저장";
    };
    updateSaveState();

    item.append(mark, main, save);
    return item;
  };

  const renderGrouped = (target, items) => {
    target.replaceChildren();
    const groups = groupBySection(items);
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state visible";
      empty.innerHTML = "<strong>결과가 없습니다</strong><span>검색어를 줄여 다시 확인합니다.</span>";
      target.append(empty);
      return;
    }
    groups.forEach((groupItems, section) => {
      const block = document.createElement("section");
      block.className = "section-block";
      const title = document.createElement("h2");
      title.className = "section-title";
      title.textContent = section || "뉴스";
      const list = document.createElement("ul");
      list.className = "cell-list";
      groupItems.forEach((article) => list.append(makeCell(article)));
      block.append(title, list);
      target.append(block);
    });
  };

  const renderSaved = () => {
    const query = queryText();
    const savedItems = allArchiveArticles().filter((article) => saved.has(article.url));
    const items = query ? savedItems.filter((article) => articleMatches(article, query)) : savedItems;
    savedList.replaceChildren();
    savedEmpty.classList.toggle("visible", !items.length);
    if (!items.length) {
      const title = savedEmpty.querySelector("strong");
      const body = savedEmpty.querySelector("span");
      if (title) title.textContent = query && savedItems.length ? "저장한 기사 중 검색 결과가 없습니다" : "저장한 기사가 없습니다";
      if (body) body.textContent = query && savedItems.length ? "검색어를 줄여 다시 확인합니다." : "나중에 볼 기사는 오른쪽 버튼으로 저장합니다.";
    }
    if (items.length) renderGrouped(savedList, items);
  };

  const render = () => {
    if (skeleton) skeleton.classList.add("hidden");
    const newsItems = filtered();
    const noticeItems = filteredLpMonitor();
    updateBriefChrome({ newsCount: newsItems.length, noticeCount: noticeItems.length });
    renderLpMonitor(noticeItems);
    renderGrouped(todayList, newsItems);
    renderSaved();
  };

  const setView = (view) => {
    currentView = view;
    todayView.classList.toggle("active", view === "today");
    savedView.classList.toggle("active", view === "saved");
    navItems.forEach((item) => item.classList.toggle("active", item.dataset.view === view));
    if (view === "saved") renderSaved();
  };

  document.addEventListener("click", (event) => {
    const dateButton = event.target.closest(".date-pill[data-date]");
    if (dateButton) {
      setActiveBrief(dateButton.dataset.date);
      return;
    }

    const filterChip = event.target.closest(".context-chip[data-filter]");
    if (filterChip) {
      searchInput.value = filterChip.dataset.filter || "";
      setSearchOpen(true);
      setView("today");
      render();
      searchInput.focus();
      return;
    }

    const saveButton = event.target.closest(".save-button");
    if (saveButton) {
      const url = saveButton.dataset.url;
      if (saved.has(url)) saved.delete(url);
      else saved.add(url);
      persistSaved();
      document.querySelectorAll(`.save-button[data-url="${CSS.escape(url)}"]`).forEach((button) => {
        button.classList.toggle("saved", saved.has(url));
        button.setAttribute("aria-label", saved.has(url) ? "저장 해제" : "저장");
        button.title = saved.has(url) ? "저장 해제" : "저장";
      });
      if (currentView === "saved") renderSaved();
      return;
    }

    const navButton = event.target.closest("[data-view]");
    if (navButton) setView(navButton.dataset.view);
  });

  if (lpDetailClose) lpDetailClose.addEventListener("click", closeLpDetail);
  if (lpDetailBackdrop) lpDetailBackdrop.addEventListener("click", closeLpDetail);
  if (searchToggle) searchToggle.addEventListener("click", () => setSearchOpen(true));
  if (searchClose) {
    searchClose.addEventListener("click", () => {
      if (searchInput && searchInput.value) {
        searchInput.value = "";
        render();
      }
      setSearchOpen(false);
    });
  }
  if (datePrev) datePrev.addEventListener("click", () => setBriefByOffset(1));
  if (dateNext) dateNext.addEventListener("click", () => setBriefByOffset(-1));
  if (dateInput) {
    dateInput.addEventListener("change", () => {
      const next = archive.find((brief) => brief.reportDate === dateInput.value);
      if (next) {
        setActiveBrief(next.reportDate);
        return;
      }
      const missing = dateInput.value;
      updateDateControl();
      if (briefMeta && missing) briefMeta.textContent = `${missing.replaceAll("-", ".")} 브리프가 아직 없습니다`;
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeLpDetail();
      if (searchInput && !searchInput.value) setSearchOpen(false);
    }
  });

  if (searchInput) searchInput.addEventListener("input", () => {
    setSearchOpen(true);
    render();
  });
  if (dateSelect) {
    dateSelect.addEventListener("change", () => setActiveBrief(dateSelect.value));
  }
  render();
})(); 
"""


def build(
    public_dir: Path,
    out_dir: Path,
    report_date: str,
    service_integration_worklist: Path = DEFAULT_SERVICE_INTEGRATION_WORKLIST,
    lp_commitment_monitor: Path = DEFAULT_LP_COMMITMENT_MONITOR,
    archive_limit: int = DEFAULT_ARCHIVE_LIMIT,
    newsletter_only: bool = False,
) -> dict[str, str]:
    if not report_date:
        report_date = latest_report_date(out_dir, today_seoul())
    markdown_path = out_dir / f"daily_news_brief_{compact_date(report_date)}.md"
    articles = parse_brief(markdown_path)
    basis_text = parse_brief_basis(markdown_path)
    service_context = read_service_context(service_integration_worklist)
    lp_monitor = read_lp_monitor(lp_commitment_monitor)
    archive_entries = build_archive_payload(out_dir, report_date, service_context, archive_limit)
    assets_dir = public_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    home_path = public_dir / "index.html"
    daily_path = public_dir / "daily-news.html"
    css_path = assets_dir / "service.css"
    js_path = assets_dir / "service.js"
    html = render_app(report_date, articles, basis_text, service_context, archive_entries, lp_monitor, newsletter_only)
    home_path.write_text(html, encoding="utf-8")
    daily_path.write_text(html, encoding="utf-8")
    css_path.write_text(service_css(), encoding="utf-8")
    js_path.write_text(service_js(), encoding="utf-8")
    return {
        "report_date": report_date,
        "home_path": str(home_path),
        "daily_path": str(daily_path),
        "css_path": str(css_path),
        "js_path": str(js_path),
        "article_count": str(len(articles)),
        "lp_monitor_count": str(len(lp_monitor)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build public service pages")
    parser.add_argument("--date", default="")
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--service-integration-worklist", type=Path, default=DEFAULT_SERVICE_INTEGRATION_WORKLIST)
    parser.add_argument("--lp-commitment-monitor", type=Path, default=DEFAULT_LP_COMMITMENT_MONITOR)
    parser.add_argument("--archive-limit", type=int, default=DEFAULT_ARCHIVE_LIMIT)
    parser.add_argument("--newsletter-only", action="store_true", help="Build the Daily Brief without DB navigation")
    args = parser.parse_args()
    result = build(
        args.public_dir,
        args.out_dir,
        args.date,
        args.service_integration_worklist,
        args.lp_commitment_monitor,
        args.archive_limit,
        args.newsletter_only,
    )
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
