#!/usr/bin/env python
"""Newsletter-only static renderer.

This module is extracted from the legacy service-site builder so the daily
newsletter publish path does not import LP, GP, Wiki, or monolith build code.
"""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from services.newsletter.src.brand_assets import (
    brand_logo_url,
    brand_style_string,
    prepare_brand_asset_cache,
)
from services.newsletter.src.daily_news_common import (
    clean_investment_memo_summary_line,
    clean_investment_memo_summary_lines,
    clean_news_title,
    normalize_url,
    normalize_whitespace,
    split_news_title_badges,
)
from services.newsletter.src.news_taxonomy import SECTION_LABELS, TAG_TAXONOMY_VERSION, canonical_section
from services.newsletter.web.newsletter_ui import (
    app_asset_version,
    app_web_manifest,
    display_date,
    render_app,
    service_css,
    service_js,
    write_app_icon_assets,
)


SECTION_HEADER_RE = re.compile(r"^\[(?P<section>.+?)\]\s*$")

ARTICLE_RE = re.compile(r"^- \[(?P<title>.+?)\]\((?P<url>https?://[^)]+)\)")

EDITORIAL_SECTIONS = [
    "AI & PE",
    "국민성장펀드",
    "Deal",
    "LP",
    "GP",
    "Market",
]

AI_SHORT_RE = re.compile(r"(?<![A-Za-z])AI(?![A-Za-z])", re.IGNORECASE)

FUNDRAISING_FUND_CHALLENGE_RE = re.compile(r"펀드[\"'’”\)\]\s]{0,4}도전")

EQUITY_STAKE_TRANSACTION_RE = re.compile(
    r"(?:투자.*지분\s*\d+(?:\.\d+)?%|지분\s*\d+(?:\.\d+)?%.*확보)"
)

AMOUNTED_INVESTMENT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:조|억|억원)\s*(?:규모\s*)?(?:투자|베팅|투입|집행)")

NATIONAL_GROWTH_FUND_KEYWORDS = [
    "국민성장펀드",
    "국민성장 펀드",
    "150조 국민성장펀드",
    "150조원 국민성장펀드",
]

NATIONAL_GROWTH_FUND_MAIN_TOPIC_KEYWORDS = [
    "간접투자",
    "출자사업",
    "출자 사업",
    "위탁운용",
    "운용사",
    "GP 선정",
    "GP 발표",
    "최종 GP",
    "숏리스트",
    "명단",
    "낙점",
    "리그",
    "마중물",
    "국민참여형",
    "완판",
    "소진",
    "출시",
    "가입",
    "수익률",
]

MARKET_STRUCTURE_KEYWORDS = [
    "GP 스테이크",
    "GP스테이크",
    "GP stake",
    "GP stakes",
    "운용사 지분",
    "운용사 스테이크",
    "PEF협의회",
    "PEF협회",
    "PEF업계",
    "사모펀드협의회",
]

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




def compact_date(report_date: str) -> str:
    return report_date.replace("-", "")


def latest_report_date(out_dir: Path, fallback: str) -> str:
    candidates: list[str] = []
    for path in [*out_dir.glob("daily_news_final_*.md"), *out_dir.glob("daily_news_brief_*.md")]:
        match = re.fullmatch(r"daily_news_(?:final|brief)_(\d{8})\.md", path.name)
        if match:
            raw = match.group(1)
            candidates.append(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
    return sorted(candidates, reverse=True)[0] if candidates else fallback

def report_dates(out_dir: Path) -> list[str]:
    dates: list[str] = []
    for path in [*out_dir.glob("daily_news_final_*.md"), *out_dir.glob("daily_news_brief_*.md")]:
        match = re.fullmatch(r"daily_news_(?:final|brief)_(\d{8})\.md", path.name)
        if not match:
            continue
        raw = match.group(1)
        dates.append(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
    return sorted(set(dates), reverse=True)

def brief_markdown_path(out_dir: Path, report_date: str) -> Path:
    compact = compact_date(report_date)
    final_path = out_dir / f"daily_news_final_{compact}.md"
    if final_path.exists():
        return final_path
    return out_dir / f"daily_news_brief_{compact}.md"

def parse_brief(markdown_path: Path) -> list[dict[str, str]]:
    if not markdown_path.exists():
        return []
    rows: list[dict[str, str]] = []
    current_section = ""
    last_row: dict[str, str] | None = None
    is_finalized = markdown_path.name.startswith("daily_news_final_")
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
                "finalized": "1" if is_finalized else "",
            }
            rows.append(last_row)
            continue
        if last_row is not None and line.startswith("출처:"):
            last_row["source"] = line.replace("출처:", "", 1).strip()
            last_row["title"] = clean_news_title(last_row["title"], last_row["source"])
    return rows

def parse_brief_basis(markdown_path: Path) -> str:
    return ""

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
    "품는",
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
    "DIP",
    "전환사채",
    "CB",
    "대출",
    "파이낸싱",
]

DEAL_OWNERSHIP_KEYWORDS = ["포트폴리오", "밸류업", "PMI", "구조조정", "턴어라운드", "운영 개선", "체질 개선", "실적", "수익성", "수익성 개선", "손본다"]

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
    "교직원공제회",
    "행정공제",
    "군인공제",
    "새마을금고",
    "우본",
    "우정사업본부",
    "총회연금",
    "모태펀드",
    "성장금융",
    "한국벤처투자",
    "국민성장펀드",
    "자산배분",
    "대체투자",
    "펀드 출자",
    "PE 출자",
    "VC 출자",
    "출자사업",
    "출자공고",
    "위탁운용",
    "위탁사",
    "위탁사 선발",
    "위탁사 선정",
    "운용사 선정",
    "출자확약",
    "공제사업",
    "공제회",
    "연기금",
    "중소기업중앙회",
    "노란우산공제",
    "KIC",
    "한국투자공사",
    "자산운용본부",
    "자산운용본부장",
    "자산운용부서장",
    "RFP",
    "커밋먼트",
    "분배금",
    "DPI",
]

LP_GOVERNANCE_KEYWORDS = [
    "CIO",
    "CIO인선",
    "최고 운용",
    "운용 총괄",
    "운용총괄",
    "기금운용본부",
    "운용본부장",
    "자산운용본부장",
    "인선",
    "임기",
    "거취",
    "독립성",
    "의결권",
    "중기 자산배분",
]

RETIREMENT_ALLOCATOR_KEYWORDS = [
    "퇴직연금",
    "401k",
    "401K",
    "401(k)",
    "retirement plan",
    "retirement plans",
    "defined contribution",
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
    "블라인드",
    "펀딩",
    "자펀드",
    "하우스 전략",
    "운용전략",
    "플랫폼",
]

ADVISORY_PEOPLE_ORG_KEYWORDS = [
    "법무법인",
    "회계법인",
    "PwC",
    "삼일",
    "광장",
    "김앤장",
    "태평양",
    "세종",
    "율촌",
]

ADVISORY_PEOPLE_EVENT_KEYWORDS = [
    "영입",
    "고문",
    "합류",
    "리더십 재편",
    "부대표",
    "대표 선임",
    "파트너 선임",
    "승진",
]

MARKET_KEYWORDS = ["규제", "금감원", "금융위", "금융감독원", "내부통제", "자본시장법", "세제", "과세", "시장", "전망", "동향", "트렌드"]

MARKET_COMMENTARY_KEYWORDS = [
    "뉴노멀",
    "시장 공식",
    "시장 전망",
    "시장 동향",
    "시장 구조",
    "사모 시장",
    "M&A 보험",
    "보험 시장",
    "진술·보장",
    "진술 보장",
    "W&I",
    "사모대출은",
    "프라이빗크레딧 시장",
    "은행이 못 채운 공백",
    "불안하다",
    "구조와 투자자를 봐야",
    "메울 것",
    "불확실성",
    "고금리",
    "스프레드",
    "컨퍼런스",
    "콘퍼런스",
    "ASK 2026",
    "GAIC 2026",
    "딜로이트 AP PE 총괄",
    "AP PE 총괄",
    "설문",
    "리포트",
]

CREDIT_TRANSACTION_KEYWORDS = [
    "DIP",
    "대출 집행",
    "대출 실행",
    "자금 집행",
    "자금 납입",
    "확보",
    "조달",
    "제공",
    "주선",
    "투입",
    "리파이낸싱 완료",
    "리캡 완료",
    "차환",
    "약정",
    "클로징",
]

EXTERNAL_FUNDING_DEAL_KEYWORDS = [
    "투자유치",
    "신규 FI",
    "시리즈A",
    "시리즈B",
    "시리즈C",
    "프리IPO",
    "pre-IPO",
    "몸값",
]

def has_ai_theme(text: str) -> bool:
    return bool(AI_SHORT_RE.search(text)) or contains_any(text, AI_THEME_KEYWORDS)

def has_national_growth_fund_theme(title_text: str, raw_section: str = "") -> bool:
    if "국민성장펀드" in raw_section or "NationalGrowthFund" in raw_section:
        return True
    if not contains_any(title_text, NATIONAL_GROWTH_FUND_KEYWORDS):
        return contains_any(raw_section, NATIONAL_GROWTH_FUND_KEYWORDS)
    stripped_title = title_text.lstrip()
    if stripped_title.startswith("["):
        return True
    return contains_any(title_text, NATIONAL_GROWTH_FUND_MAIN_TOPIC_KEYWORDS)

def has_specific_equity_transaction_signal(text: str) -> bool:
    return bool(EQUITY_STAKE_TRANSACTION_RE.search(text)) or bool(AMOUNTED_INVESTMENT_RE.search(text))

def has_external_funding_deal_signal(text: str) -> bool:
    return contains_any(text, EXTERNAL_FUNDING_DEAL_KEYWORDS) or has_specific_equity_transaction_signal(text)

def has_gp_focus_signal(text: str) -> bool:
    keywords = [keyword for keyword in GP_FOCUS_KEYWORDS if keyword != "파트너"]
    return contains_any(text, keywords) or "파트너" in text.replace("파트너스", "")

def has_advisory_people_signal(text: str) -> bool:
    return contains_any(text, ADVISORY_PEOPLE_ORG_KEYWORDS) and contains_any(text, ADVISORY_PEOPLE_EVENT_KEYWORDS)

def has_deal_market_commentary_signal(text: str) -> bool:
    if not contains_any(text, ["M&A", "인수합병"]):
        return False
    if contains_any(
        text,
        [
            "예비입찰",
            "본입찰",
            "입찰",
            "우선협상",
            "우협",
            "인수전",
            "매각전",
            "몸값",
            "주식매매계약",
            "본계약",
            "인수 추진",
            "매각 추진",
            "인수 완료",
            "경영권 인수",
        ],
    ):
        return False
    return contains_any(
        text,
        [
            "시장",
            "규모",
            "최저",
            "급증",
            "커진다",
            "얼어붙",
            "쪼그라",
            "팬데믹",
            "보험",
            "의뢰건수",
        ],
    )

def has_fundraising_signal(text: str) -> bool:
    return contains_any(
        text,
        ["펀드 결성", "펀드레이징", "펀드 조성", "펀드 도전", "펀드 시동", "펀드 출격", "펀드 증액", "펀딩", "펀딩 목표", "자펀드", "GP 도전", "클로징", "약정총액", "목표액", "블라인드펀드", "블라인드", "블라인드 도전"],
    ) or bool(FUNDRAISING_FUND_CHALLENGE_RE.search(text))

def has_retirement_allocator_signal(text: str) -> bool:
    return contains_any(text, RETIREMENT_ALLOCATOR_KEYWORDS)

def has_financial_license_market_signal(text: str) -> bool:
    return contains_any(text, ["장외파생상품"]) and contains_any(text, ["라이선스", "인가", "금감원", "금융위"])

def has_gp_lp_program_fundraise_signal(text: str) -> bool:
    return contains_any(text, ["농모태펀드", "모태펀드", "출자 사업", "출자사업"]) and contains_any(
        text,
        ["GP 도전", "블라인드", "펀딩", "펀드레이징", "펀드 결성", "자펀드"],
    )

def has_gp_national_growth_fund_strategy_signal(title_text: str, raw_section: str) -> bool:
    if has_national_growth_fund_theme(title_text, raw_section):
        return False
    if not contains_any(title_text, NATIONAL_GROWTH_FUND_KEYWORDS):
        return False
    if raw_section.strip() == "GP":
        return True
    return contains_any(title_text, ["운용사", "GP", "PEF", "PE하우스", "프라이빗에쿼티"]) and contains_any(
        title_text,
        ["노리는", "드라이 파우더", "레버리지", "전략"],
    )

def legacy_section_to_current(raw_section: str, title_text: str) -> str:
    raw_text = raw_section or ""
    if "AI & PE" in raw_text:
        return "AI & PE"
    if has_national_growth_fund_theme(title_text, raw_text):
        return "국민성장펀드"
    if raw_text.strip() == "LP":
        return "LP" if contains_any(title_text, LP_FOCUS_KEYWORDS) else "Market"
    if raw_text.strip() == "GP":
        return "GP"
    if "Portfolio" in raw_text or "포트폴리오" in raw_text:
        return "Deal"
    if "Credit" in raw_text or "크레딧" in raw_text:
        return "Market"
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
    if row.get("finalized") == "1" and raw_section in EDITORIAL_SECTIONS:
        return raw_section
    title_text = title
    combined = f"{title_text} {raw_section}"
    if has_national_growth_fund_theme(title_text, raw_section):
        return "국민성장펀드"
    if has_gp_national_growth_fund_strategy_signal(title_text, raw_section):
        return "GP"
    if has_financial_license_market_signal(title_text):
        return "Market"
    if has_advisory_people_signal(title_text):
        return "Market"
    if has_deal_market_commentary_signal(title_text):
        return "AI & PE" if has_ai_theme(combined) else "Market"
    if has_gp_lp_program_fundraise_signal(title_text):
        return "GP"
    if has_retirement_allocator_signal(title_text):
        return "LP"
    if contains_any(title_text, LP_FOCUS_KEYWORDS) and not has_ai_theme(title_text):
        return "LP"
    if raw_section == "LP" and contains_any(title_text, LP_GOVERNANCE_KEYWORDS):
        return "LP"
    if raw_section == "AI & PE":
        return "AI & PE"
    if has_fundraising_signal(title_text) and (raw_section.strip() == "GP" or has_gp_focus_signal(title_text)):
        return "GP"
    if contains_any(title_text, MARKET_STRUCTURE_KEYWORDS):
        return "Market"
    if contains_any(title_text, MARKET_COMMENTARY_KEYWORDS):
        return "Market"
    if contains_any(title_text, DEAL_FINANCING_KEYWORDS) and not contains_any(title_text, CREDIT_TRANSACTION_KEYWORDS):
        return "Market"
    if has_external_funding_deal_signal(title_text):
        return "Deal"
    if has_fundraising_signal(title_text):
        return "GP"
    if raw_section.strip() == "GP" and has_gp_focus_signal(title_text):
        return "GP"
    if has_ai_theme(combined) and contains_any(combined, DEAL_SIGNAL_KEYWORDS + DEAL_FINANCING_KEYWORDS + LP_FOCUS_KEYWORDS + GP_FOCUS_KEYWORDS):
        return "AI & PE"
    if contains_any(title_text, DEAL_SIGNAL_KEYWORDS + DEAL_OWNERSHIP_KEYWORDS + DEAL_ISSUE_KEYWORDS) or has_specific_equity_transaction_signal(title_text):
        return "Deal"
    if contains_any(title_text, DEAL_FINANCING_KEYWORDS):
        return "Deal" if contains_any(title_text, CREDIT_TRANSACTION_KEYWORDS) else "Market"
    if has_gp_focus_signal(title_text):
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
    if section == "국민성장펀드":
        if contains_any(text, ["간접투자", "간접 투자", "선정", "출자사업", "출자 공고", "출자공고", "위탁운용"]):
            return "출자·선정"
        if contains_any(text, ["운용사", "GP", "결승", "숏리스트"]):
            return "운용사 경쟁"
        if contains_any(text, ["정책", "정부", "금융위", "산업", "성장"]):
            return "정책펀드"
        return "프로그램 동향"
    if section == "Deal":
        if contains_any(text, DEAL_FINANCING_KEYWORDS):
            return "Financing"
        if contains_any(text, ["세컨더리", "컨티뉴에이션", "continuation"]):
            return "Secondary"
        if contains_any(text, DEAL_ISSUE_KEYWORDS):
            return "Issue"
        if contains_any(text, ["밸류업", "PMI", "구조조정", "턴어라운드", "운영 개선", "실적", "수익성", "수익성 개선", "손본다", "숨겨진 가치", "가치 재평가", "재평가"]):
            return "Ownership"
        if contains_any(text, ["SPA", "본계약", "계약 체결", "클로징", "자금 납입", "마무리", "완료"]):
            return "Signing·Closing"
        if contains_any(text, ["입찰", "우선협상", "숏리스트", "주관사", "매각주관", "원매자", "인수의향", "제안"]):
            return "Auction"
        if contains_any(text, ["엑시트", "회수", "매각", "IPO", "블록딜", "청산"]):
            return "Exit"
        return "Acquisition"
    if section == "LP":
        if has_retirement_allocator_signal(text):
            return "Allocation"
        if contains_any(text, ["출자사업", "출자공고", "위탁운용", "운용사 선정", "RFP", "출자확약", "앵커"]):
            return "Mandate"
        if contains_any(text, ["출자", "커밋먼트", "commitment"]):
            return "Allocation"
        if contains_any(text, ["자산배분", "대체투자", "투자정책", "리밸런싱", "국민성장펀드"]):
            return "Allocation"
        if contains_any(text, ["분배금", "DPI", "수익률", "성과", "포트폴리오"]):
            return "Portfolio Review"
        if contains_any(text, ["LP 세컨더리", "유동성", "지분 매각"]):
            return "Liquidity"
        return "Governance"
    if section == "GP":
        if has_fundraising_signal(text):
            return "Fundraising"
        if contains_any(text, ["대표", "파트너", "심사역", "영입", "선임", "복귀", "승진", "인력"]):
            return "People"
        if contains_any(text, ["조직", "사무소", "부문", "플랫폼", "계열", "법인"]):
            return "Organization"
        if contains_any(text, ["트랙레코드", "성과", "과거 딜", "회수 성과"]):
            return "Track Record"
        return "Strategy"
    if has_financial_license_market_signal(text) or contains_any(text, ["규제", "금융위", "금감원", "자본시장법", "세제", "공정위", "제재", "소송"]):
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

def source_icon_url(url: str, source: str = "") -> str:
    return brand_logo_url(url, source)

def section_sort_key(section: str) -> int:
    try:
        return EDITORIAL_SECTIONS.index(section)
    except ValueError:
        return len(EDITORIAL_SECTIONS)

def add_unique(items: list[str], value: str) -> None:
    value = str(value or "").strip()
    if value and value not in items:
        items.append(value)

def context_entry() -> dict[str, object]:
    return {
        "gpNames": [],
        "gpProfileLinks": [],
        "lpNames": [],
        "lpProfileLinks": [],
        "summaryText": "",
        "summaryLines": [],
        "searchTerms": [],
        "peopleCount": 0,
        "serviceActions": [],
        "sectionSuggestion": "",
    }

def service_context_keys(source_url: object = "", normalized_source_url: object = "") -> list[str]:
    keys: list[str] = []
    for value in [normalized_source_url, source_url]:
        text = str(value or "").strip()
        if not text:
            continue
        for key in [normalize_url(text), text]:
            if key and key not in keys:
                keys.append(key)
    return keys

def is_google_news_redirect_url(value: object) -> bool:
    try:
        return urlparse(str(value or "")).hostname == "news.google.com"
    except ValueError:
        return False

def split_context_names(value: object) -> list[str]:
    return [part.strip() for part in re.split(r"[,;]", str(value or "")) if part.strip()]

def entity_name_key(value: object) -> str:
    return re.sub(r"[\s·ㆍ.,()\\[\\]{}'\"`]+", "", str(value or "").strip()).lower()

def article_public_gp_names(context: dict[str, object]) -> list[str]:
    lp_names = {entity_name_key(name) for name in context.get("lpNames", []) if entity_name_key(name)}
    for item in context.get("lpProfileLinks", []):
        if isinstance(item, dict):
            key = entity_name_key(item.get("name", ""))
            if key:
                lp_names.add(key)
    public_names: list[str] = []
    for name in context.get("gpNames", []):
        key = entity_name_key(name)
        if key and key not in lp_names:
            add_unique(public_names, str(name))
    return public_names

def public_article_summary(value: object, title: object = "") -> str:
    text = normalize_whitespace(str(value or ""))
    title_text = normalize_whitespace(str(title or ""))
    if not text or len(text) < 18:
        return ""
    if title_text and entity_name_key(text) == entity_name_key(title_text):
        return ""
    return text[:360]

def public_article_summary_lines(value: object, title: object = "") -> list[str]:
    text = public_article_summary(value, title)
    if not text:
        return []
    text = re.sub(r"\[[^\]]*본 기사는[^\]]*\]", " ", text)
    text = re.sub(r"이 기사는\s*20\d{2}년\s*\d{1,2}월\s*\d{1,2}일[^.。]*", " ", text)
    text = re.sub(r"▲[^.。]{0,80}", " ", text)
    text = re.sub(r"\s*[-–]\s*(?:인베스트조선|한국경제|매일경제|딜사이트|더벨|뉴스톱)\s*$", "", text)
    text = normalize_whitespace(text)
    raw_parts = [
        normalize_whitespace(part)
        for part in re.split(
            r"(?<=[!?。])(?=\s*[가-힣A-Z0-9\"“‘<])\s*|(?<=\.)(?=\s*[가-힣A-Z\"“‘<])\s*|(?<=\.)\s+(?=[0-9])|…\s*|\s{2,}",
            text,
        )
        if normalize_whitespace(part)
    ]
    if len(raw_parts) <= 1:
        raw_parts = [
            normalize_whitespace(part)
            for part in re.split(r"\s*[;；]\s*|\s*,\s*(?=[가-힣A-Za-z0-9]{2,})", text)
            if normalize_whitespace(part)
        ]
    lines: list[str] = []
    for part in raw_parts:
        line = part.strip(" \t\r\n-–—·,.;:。")
        line = re.sub(r"^\[[^\]]+\]\s*", "", line)
        line = re.sub(r"\s+", " ", line)
        line = clean_investment_memo_summary_line(line, title, max_length=62)
        if not line or len(line) < 8:
            continue
        if line not in lines:
            lines.append(line)
        if len(lines) >= 3:
            break
    if not lines:
        fallback = text.strip(" \t\r\n-–—·,.;:。")
        if len(fallback) > 62:
            fallback = fallback[:61].rstrip(" ,.;:·") + "…"
        fallback = clean_investment_memo_summary_line(fallback, title, max_length=62)
        return [fallback] if fallback else []
    return lines

def read_review_queue_context(out_dir: Path) -> dict[str, dict[str, object]]:
    context: dict[str, dict[str, object]] = {}
    for path in sorted(out_dir.glob("daily_news_review_queue_*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                names = split_context_names(row.get("gp_names", ""))
                summary_text = normalize_whitespace(str(row.get("summary_text") or ""))
                if not names and not summary_text:
                    continue
                for key in service_context_keys(row.get("source_url", ""), row.get("normalized_source_url", "")):
                    entry = context.setdefault(key, context_entry())
                    if summary_text:
                        entry["summaryText"] = summary_text
                    gp_names = entry["gpNames"]
                    search_terms = entry["searchTerms"]
                    for name in names:
                        add_unique(gp_names, name)
                        add_unique(search_terms, name)
    return merge_service_context(context, read_ai_enrichment_context(out_dir))

def clean_summary_line_values(value: object, title: object = "") -> list[str]:
    return clean_investment_memo_summary_lines(value, title, limit=3)

def public_section_from_ai_suggestion(value: object) -> str:
    section_code = canonical_section(value)
    return SECTION_LABELS.get(section_code, "")

def should_apply_ai_section_suggestions() -> bool:
    return str(os.environ.get("NEWSLETTER_AI_APPLY_SECTIONS", "0")).strip().lower() in {"1", "true", "yes", "on"}

def read_ai_enrichment_context(out_dir: Path) -> dict[str, dict[str, object]]:
    context: dict[str, dict[str, object]] = {}
    for path in sorted(out_dir.glob("daily_news_ai_enrichment_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        articles = data.get("articles") if isinstance(data, dict) else data
        if not isinstance(articles, list):
            continue
        for row in articles:
            if not isinstance(row, dict):
                continue
            summary_lines = clean_summary_line_values(row.get("summary_lines") or row.get("summaryLines"), row.get("title", ""))
            summary_text = normalize_whitespace(str(row.get("summary_text") or row.get("summaryText") or ""))
            section_suggestion = public_section_from_ai_suggestion(row.get("section_suggestion") or row.get("section"))
            if not summary_lines and not summary_text and not section_suggestion:
                continue
            keys = service_context_keys(row.get("source_url", ""), row.get("normalized_source_url", ""))
            if not keys:
                keys = service_context_keys(row.get("url", ""), "")
            for key in keys:
                entry = context.setdefault(key, context_entry())
                if summary_text:
                    entry["summaryText"] = summary_text
                if summary_lines:
                    entry["summaryLines"] = summary_lines
                if section_suggestion:
                    entry["sectionSuggestion"] = section_suggestion
    return context

def merge_service_context(
    base: dict[str, dict[str, object]],
    extra: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    for key, row in extra.items():
        entry = base.setdefault(key, context_entry())
        for name in row.get("gpNames", []):
            add_unique(entry["gpNames"], str(name))
        gp_links = entry.setdefault("gpProfileLinks", [])
        seen_gp_links = {
            (
                str(item.get("id") or ""),
                str(item.get("url") or ""),
                str(item.get("name") or ""),
            )
            for item in gp_links
            if isinstance(item, dict)
        }
        for item in row.get("gpProfileLinks", []):
            if not isinstance(item, dict):
                continue
            link = {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "url": str(item.get("url") or ""),
            }
            key_tuple = (link["id"], link["url"], link["name"])
            if link["name"] and link["url"] and key_tuple not in seen_gp_links:
                gp_links.append(link)
                seen_gp_links.add(key_tuple)
        for name in row.get("lpNames", []):
            add_unique(entry["lpNames"], str(name))
        summary_text = normalize_whitespace(str(row.get("summaryText") or ""))
        if summary_text:
            entry["summaryText"] = summary_text
        summary_lines = clean_summary_line_values(row.get("summaryLines") or row.get("summary_lines"))
        if summary_lines:
            entry["summaryLines"] = summary_lines
        section_suggestion = public_section_from_ai_suggestion(row.get("sectionSuggestion") or row.get("section_suggestion"))
        if section_suggestion:
            entry["sectionSuggestion"] = section_suggestion
        for term in row.get("searchTerms", []):
            add_unique(entry["searchTerms"], str(term))
        links = entry.setdefault("lpProfileLinks", [])
        seen_links = {
            (
                str(item.get("code") or ""),
                str(item.get("url") or ""),
                str(item.get("name") or ""),
            )
            for item in links
            if isinstance(item, dict)
        }
        for item in row.get("lpProfileLinks", []):
            if not isinstance(item, dict):
                continue
            link = {
                "code": str(item.get("code") or ""),
                "name": str(item.get("name") or ""),
                "url": str(item.get("url") or ""),
            }
            key_tuple = (link["code"], link["url"], link["name"])
            if link["name"] and link["url"] and key_tuple not in seen_links:
                links.append(link)
                seen_links.add(key_tuple)
    return base

def article_payload_rows(
    rows: list[dict[str, str]],
    service_context: dict[str, dict[str, object]] | None = None,
    id_prefix: str = "clip",
) -> list[dict[str, object]]:
    service_context = service_context or {}
    payload: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        raw_section = row.get("section", "")
        section = raw_section if raw_section in EDITORIAL_SECTIONS else editorial_section(row)
        article_url = row.get("url", "")
        if is_google_news_redirect_url(article_url):
            continue
        context = service_context.get(normalize_url(article_url), service_context.get(article_url, {}))
        if should_apply_ai_section_suggestions():
            ai_section = str(context.get("sectionSuggestion") or "")
            if ai_section in EDITORIAL_SECTIONS:
                section = ai_section
        subtype = editorial_subtype(row, section)
        display_title, title_badges = split_news_title_badges(row.get("title", ""), row.get("source", ""))
        gp_names = article_public_gp_names(context)
        summary_text = public_article_summary(context.get("summaryText", ""), display_title)
        summary_lines = clean_summary_line_values(context.get("summaryLines"), display_title) or public_article_summary_lines(summary_text, display_title)
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
                "sourceIconUrl": source_icon_url(row.get("url", ""), row.get("source", "")),
                "sourceIconStyle": brand_style_string(row.get("url", ""), row.get("source", "")),
                "url": row.get("url", ""),
                "summaryText": summary_text,
                "summaryLines": summary_lines,
                "tagVersion": TAG_TAXONOMY_VERSION,
                "sectionOrder": section_sort_key(section),
                "gpNames": gp_names,
                "gpProfileLinks": context.get("gpProfileLinks", []),
                "lpNames": context.get("lpNames", []),
                "lpProfileLinks": context.get("lpProfileLinks", []),
                "peopleCount": context.get("peopleCount", 0),
                "searchTerms": context.get("searchTerms", []),
            }
        )
    return payload

def refresh_archive_article_assets(articles: object) -> list[dict[str, object]]:
    if not isinstance(articles, list):
        return []
    refreshed: list[dict[str, object]] = []
    for item in articles:
        if not isinstance(item, dict):
            continue
        article = dict(item)
        url = str(article.get("url") or article.get("sourceUrl") or "")
        source = str(article.get("source") or article.get("publisher") or "")
        icon_url = source_icon_url(url, source)
        icon_style = brand_style_string(url, source)
        if icon_url:
            article["sourceIconUrl"] = icon_url
        if icon_style:
            article["sourceIconStyle"] = icon_style
        refreshed.append(article)
    return refreshed

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
        markdown_path = brief_markdown_path(out_dir, report_date)
        rows = parse_brief(markdown_path)
        articles = article_payload_rows(rows, service_context, f"clip-{compact_date(report_date)}")
        payload.append(
            {
                "reportDate": report_date,
                "visibleDate": display_date(report_date),
                "basis": "",
                "articleCount": len(articles),
                "articles": articles,
            }
        )
    return payload

def refresh_archive_entries_with_context(
    out_dir: Path,
    archive_entries: list[dict[str, object]],
    service_context: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    refreshed: list[dict[str, object]] = []
    for entry in archive_entries:
        report_date = str(entry.get("reportDate") or "")
        markdown_path = brief_markdown_path(out_dir, report_date)
        if not report_date or not markdown_path.exists():
            next_entry = dict(entry)
            articles = refresh_archive_article_assets(next_entry.get("articles"))
            next_entry["articles"] = articles
            next_entry["articleCount"] = len(articles)
            refreshed.append(next_entry)
            continue
        rows = parse_brief(markdown_path)
        articles = article_payload_rows(rows, service_context, f"clip-{compact_date(report_date)}")
        next_entry = dict(entry)
        next_entry["visibleDate"] = str(next_entry.get("visibleDate") or display_date(report_date))
        next_entry["articleCount"] = len(articles)
        next_entry["articles"] = articles
        refreshed.append(next_entry)
    return refreshed

def rewrite_newsletter_archive(
    public_dir: Path,
    out_dir: Path,
    report_date: str,
    archive_entries: list[dict[str, object]],
) -> None:
    markdown_path = brief_markdown_path(out_dir, report_date)
    articles = parse_brief(markdown_path)
    basis_text = parse_brief_basis(markdown_path)
    service_context = read_review_queue_context(out_dir)
    archive_entries = refresh_archive_entries_with_context(out_dir, archive_entries, service_context)
    html = render_app(
        report_date,
        articles,
        basis_text,
        service_context,
        archive_entries,
        [],
        newsletter_only=True,
    )
    (public_dir / "index.html").write_text(html, encoding="utf-8")
    (public_dir / "daily-news.html").write_text(html, encoding="utf-8")
    (public_dir / "archive.json").write_text(
        json.dumps(archive_entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_newsletter_site(
    public_dir: Path,
    out_dir: Path,
    report_date: str,
    archive_limit: int,
) -> dict[str, str]:
    if not report_date:
        raise ValueError("report_date is required for newsletter-only site builds")
    markdown_path = brief_markdown_path(out_dir, report_date)
    articles = parse_brief(markdown_path)
    basis_text = parse_brief_basis(markdown_path)
    service_context = read_review_queue_context(out_dir)
    archive_entries = build_archive_payload(out_dir, report_date, service_context, archive_limit)

    assets_dir = public_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    prepare_brand_asset_cache(public_dir)

    home_path = public_dir / "index.html"
    daily_path = public_dir / "daily-news.html"
    archive_path = public_dir / "archive.json"
    css_path = assets_dir / "service.css"
    js_path = assets_dir / "service.js"
    manifest_path = public_dir / "site.webmanifest"
    icon_path = write_app_icon_assets(public_dir)

    html = render_app(report_date, articles, basis_text, service_context, archive_entries, [], newsletter_only=True)
    home_path.write_text(html, encoding="utf-8")
    daily_path.write_text(html, encoding="utf-8")
    archive_path.write_text(json.dumps(archive_entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    css_path.write_text(service_css(), encoding="utf-8")
    js_path.write_text(service_js(), encoding="utf-8")
    manifest_path.write_text(app_web_manifest(), encoding="utf-8")

    return {
        "report_date": report_date,
        "home_path": str(home_path),
        "daily_path": str(daily_path),
        "archive_path": str(archive_path),
        "css_path": str(css_path),
        "js_path": str(js_path),
        "manifest_path": str(manifest_path),
        "icon_path": str(icon_path),
        "article_count": str(len(articles)),
        "lp_monitor_count": "0",
    }
