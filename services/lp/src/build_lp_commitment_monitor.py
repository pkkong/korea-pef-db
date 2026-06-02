#!/usr/bin/env python
"""Build the LP commitment notice monitor from official notices and news clips."""

from __future__ import annotations

import argparse
import csv
import re
import ssl
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, unquote_plus, urljoin, urlparse
from urllib.request import Request, urlopen

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.newsletter.src.daily_news_common import (
    DEFAULT_DB,
    DEFAULT_GP_ALIAS_OVERRIDES,
    fetch_text,
    load_gp_aliases,
    match_gp_entities,
    matches_must_contain,
    normalize_for_match,
    normalize_url,
    normalize_whitespace,
    now_utc_iso,
    parse_html_listing,
    read_csv_rows,
    split_semicolon,
    strip_html_tags,
    today_seoul,
    write_csv_rows,
)


DEFAULT_SCHEMA = REPO_ROOT / "schema" / "lp_commitments.sql"
DEFAULT_LP_INSTITUTIONS = REPO_ROOT / "data" / "lp_institutions.csv"
DEFAULT_LP_PROFILE_FACTS = REPO_ROOT / "data" / "lp_profile_facts.csv"
DEFAULT_LP_SOURCES = REPO_ROOT / "data" / "lp_commitment_sources.csv"
DEFAULT_LP_REVIEWED_EVENTS = REPO_ROOT / "data" / "lp_reviewed_events.csv"
DEFAULT_OUT_DIR = REPO_ROOT / "exports"
NEWS_FEED_SOURCE_CODE = "daily_news_lp_feed"

NOTICE_TERMS = [
    "출자사업",
    "출자 공고",
    "출자전",
    "출자 규모",
    "위탁운용",
    "위탁운용사",
    "운용사 선정",
    "선정계획",
    "숏리스트",
    "LP Radar",
]
FUNDRAISING_TERMS = [
    "블라인드펀드",
    "펀드 결성",
    "펀드레이징",
    "커밋먼트",
    "클로징",
    "컨티뉴에이션 펀드",
    "모태펀드",
    "국민성장펀드",
]
LP_CONTEXT_TERMS = [
    "국민연금",
    "공제회",
    "성장금융",
    "한국벤처투자",
    "산업은행",
    "우정사업본부",
    "새마을금고",
    "새마을금고중앙회",
    "한국수출입은행",
    "수출입은행",
    "수은",
    "공급망안정화기금",
]

COMBINED_AMOUNT_RE = re.compile(r"\[?(?P<jo>\d[\d,]*(?:\.\d+)?)\]?\s*조(?:\s*\[?(?P<eok>\d[\d,]*)\]?\s*억?|원)?(?![가-힣])", re.IGNORECASE)
AMOUNT_RE = re.compile(r"\[?(?P<num>\d[\d,]*(?:\.\d+)?)\]?\s*(?P<unit>조\s*원|조원|억원|억|조(?![가-힣]))", re.IGNORECASE)
DATE_RE = re.compile(r"(?P<year>20\d{2})[.\-/년]\s*(?P<month>\d{1,2})[.\-/월]\s*(?P<day>\d{1,2})")
FILE_EXT_RE = re.compile(r"\.(pdf|hwp|hwpx|docx?|xlsx?|pptx?|zip)($|[?#&])", re.IGNORECASE)
MONEY_CONTEXT_WINDOW = 44
EVENT_PRIORITY = {
    "new_notice": 0,
    "deadline_soon": 1,
    "final_selection": 2,
    "shortlist": 3,
    "revision": 4,
    "cancellation": 5,
    "performance_update": 6,
    "deadline_closed": 7,
    "candidate": 8,
}
GENERIC_LISTING_TITLES = {
    "본문 바로가기",
    "메뉴 바로가기",
    "주메뉴 바로가기",
    "컨텐츠 바로가기",
    "출자공고",
    "거래기관 선정공고",
    "공지사항",
    "목록",
    "next",
    "previous",
}
TITLE_METADATA_RE = re.compile(
    r"(?:^|\s)(?:공고일|게시일|등록일|작성일|신청기한|접수마감|마감일)\s*[:：]?\s*"
    r"20\d{2}[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2}(?:일)?",
    re.IGNORECASE,
)
DETAIL_TITLE_TERMS = [
    "출자",
    "위탁운용",
    "운용사",
    "선정",
    "우선협상",
    "정량평가",
    "공고",
    "모집",
]
PROGRAM_SIZE_HINTS = [
    "국민성장펀드",
    "마중물",
    "정책펀드",
    "자펀드",
    "프로그램",
    "전체",
    "총",
]
ALLOCATION_HINTS = [
    "출자사업",
    "출자 공고",
    "출자규모",
    "출자 규모",
    "출자 예정",
    "출자액",
    "출자금",
    "배정",
    "위탁운용",
    "위탁운용사",
    "이내",
    "선정",
]
NON_COMMITMENT_AMOUNT_HINTS = [
    "aum",
    "관리자산",
    "운용자산",
    "자산규모",
    "자산 규모",
    "트랙레코드",
]
NON_COMMITMENT_NOTICE_TERMS = [
    "온라인마케팅",
    "참여기업 모집",
    "회계감사인",
    "POOL",
    "논문",
    "투자유치",
    "크라우드펀딩",
    "부킹 이벤트",
    "회원 대상",
    "공정가치 평가",
    "투자성과 모니터링",
    "용역 입찰",
    "회계감사",
]
GP_EXCLUSION_NAMES = {
    "국민연금기금",
    "국민연금",
    "국민연금공단",
    "한국벤처투자",
    "한국성장금융",
    "한국산업은행",
    "산업은행",
    "KDB",
    "우정사업본부",
    "공무원연금공단",
    "사립학교교직원연금공단",
    "농업정책보험금융원",
    "농금원",
    "한국자산관리공사",
    "신한자산운용",
    "새마을금고중앙회",
    "한국수출입은행",
    "수출입은행",
}


@dataclass
class LpAlias:
    lp_code: str
    lp_name: str
    alias: str
    alias_lower: str


def parse_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "y", "yes"}


def none_if_blank(value: object) -> object:
    text = str(value or "").strip()
    return text or None


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def latest_report_date(conn: sqlite3.Connection) -> str:
    if table_exists(conn, "news_run"):
        row = conn.execute(
            """
            SELECT run_date
            FROM news_run
            ORDER BY run_date DESC, started_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    return today_seoul()


def date_window_start(report_date: str, days: int) -> str:
    parsed = datetime.strptime(report_date, "%Y-%m-%d")
    return (parsed - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")


def apply_schema(conn: sqlite3.Connection, schema_path: Path) -> None:
    schema_sql = schema_path.read_text(encoding="utf-8")
    marker = "CREATE INDEX IF NOT EXISTS idx_lp_notice_lp"
    if marker in schema_sql:
        pre_index_sql, index_and_view_sql = schema_sql.split(marker, 1)
        conn.executescript(pre_index_sql)
        ensure_lp_notice_columns(conn)
        conn.executescript(marker + index_and_view_sql)
    else:
        conn.executescript(schema_sql)
    ensure_lp_notice_columns(conn)
    conn.commit()


def ensure_lp_notice_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(lp_commitment_notice)").fetchall()
    }
    columns = {
        "event_type": "TEXT",
        "event_date": "TEXT",
        "program_name": "TEXT",
        "round_name": "TEXT",
        "attachment_names": "TEXT",
        "attachment_urls": "TEXT",
        "program_size_krw_100mn": "REAL",
        "allocation_amount_krw_100mn": "REAL",
        "amount_type": "TEXT",
        "amount_confidence": "TEXT",
        "confidence": "TEXT",
        "confidence_note": "TEXT",
        "public_visible": "INTEGER NOT NULL DEFAULT 1",
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE lp_commitment_notice ADD COLUMN {name} {definition}")


def seed_lp_institutions(conn: sqlite3.Connection, path: Path) -> list[dict[str, str]]:
    rows = read_csv_rows(path)
    headers = [
        "lp_code",
        "lp_name",
        "lp_name_en",
        "lp_type",
        "ownership_type",
        "homepage_url",
        "notice_url",
        "default_team",
        "focus_asset_classes",
        "service_priority",
        "aliases",
        "notes",
    ]
    for row in rows:
        conn.execute(
            f"""
            INSERT INTO lp_institution ({", ".join(headers)}, updated_at)
            VALUES ({", ".join("?" for _ in headers)}, ?)
            ON CONFLICT(lp_code) DO UPDATE SET
                lp_name = excluded.lp_name,
                lp_name_en = excluded.lp_name_en,
                lp_type = excluded.lp_type,
                ownership_type = excluded.ownership_type,
                homepage_url = excluded.homepage_url,
                notice_url = excluded.notice_url,
                default_team = excluded.default_team,
                focus_asset_classes = excluded.focus_asset_classes,
                service_priority = excluded.service_priority,
                aliases = excluded.aliases,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            [row.get(header, "") for header in headers] + [now_utc_iso()],
        )
    conn.commit()
    return rows


def seed_lp_profile_facts(conn: sqlite3.Connection, path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows = read_csv_rows(path)
    managed_lp_codes = sorted({row.get("lp_code", "").strip() for row in rows if row.get("lp_code", "").strip()})
    for lp_code in managed_lp_codes:
        conn.execute("DELETE FROM lp_profile_fact WHERE lp_code = ?", (lp_code,))
    headers = [
        "lp_code",
        "section",
        "label",
        "value",
        "as_of_date",
        "source_name",
        "source_url",
        "confidence",
        "notes",
        "sort_order",
        "public_visible",
    ]
    for row in rows:
        values = [row.get(header, "") for header in headers]
        conn.execute(
            f"""
            INSERT INTO lp_profile_fact ({", ".join(headers)}, updated_at)
            VALUES ({", ".join("?" for _ in headers)}, ?)
            ON CONFLICT(lp_code, section, label, source_url) DO UPDATE SET
                value = excluded.value,
                as_of_date = excluded.as_of_date,
                source_name = excluded.source_name,
                confidence = excluded.confidence,
                notes = excluded.notes,
                sort_order = excluded.sort_order,
                public_visible = excluded.public_visible,
                updated_at = excluded.updated_at
            """,
            values + [now_utc_iso()],
        )
    conn.commit()
    return rows


def seed_lp_sources(conn: sqlite3.Connection, path: Path) -> list[dict[str, str]]:
    rows = read_csv_rows(path)
    headers = [
        "source_code",
        "lp_code",
        "source_name",
        "source_kind",
        "locator",
        "homepage_url",
        "article_url_regex",
        "must_contain",
        "is_active",
        "notes",
    ]
    for row in rows:
        values = [row.get(header, "") for header in headers]
        values[1] = none_if_blank(values[1])
        conn.execute(
            f"""
            INSERT INTO lp_commitment_source ({", ".join(headers)}, updated_at)
            VALUES ({", ".join("?" for _ in headers)}, ?)
            ON CONFLICT(source_code) DO UPDATE SET
                lp_code = excluded.lp_code,
                source_name = excluded.source_name,
                source_kind = excluded.source_kind,
                locator = excluded.locator,
                homepage_url = excluded.homepage_url,
                article_url_regex = excluded.article_url_regex,
                must_contain = excluded.must_contain,
                is_active = excluded.is_active,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            values + [now_utc_iso()],
        )
    conn.execute(
        """
        INSERT INTO lp_commitment_source (
            source_code, lp_code, source_name, source_kind, locator, homepage_url,
            article_url_regex, must_contain, is_active, notes, updated_at
        )
        VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(source_code) DO UPDATE SET
            source_name = excluded.source_name,
            source_kind = excluded.source_kind,
            locator = excluded.locator,
            is_active = 1,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """,
        (
            NEWS_FEED_SOURCE_CODE,
            "Daily 뉴스 LP/출자사업 후보",
            "news_view",
            "v_news_relevant",
            "",
            "",
            "",
            "뉴스레터 클리핑에서 LP/출자사업 관련 후보를 연결",
            now_utc_iso(),
        ),
    )
    conn.commit()
    return rows


def load_lp_aliases(rows: list[dict[str, str]]) -> list[LpAlias]:
    aliases: list[LpAlias] = []
    for row in rows:
        lp_code = row.get("lp_code", "")
        lp_name = row.get("lp_name", "")
        raw_aliases = [lp_name, row.get("lp_name_en", ""), *split_semicolon(row.get("aliases", ""))]
        for alias in raw_aliases:
            alias = normalize_whitespace(alias)
            if not lp_code or not alias:
                continue
            aliases.append(LpAlias(lp_code, lp_name, alias, alias.lower()))
    return sorted(aliases, key=lambda item: (-len(item.alias), item.alias))


def infer_lp_code(text: str, aliases: list[LpAlias], fallback: str = "") -> str:
    haystack = text.lower()
    for item in aliases:
        alias = item.alias_lower
        compact = re.sub(r"[^A-Za-z0-9]", "", alias)
        if compact and compact.isascii() and len(compact) <= 4:
            pattern = r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])"
            if re.search(pattern, haystack, flags=re.IGNORECASE):
                return item.lp_code
        elif alias in haystack:
            return item.lp_code
    return fallback


def infer_stage(text: str) -> str:
    value = text.lower()
    if any(term in value for term in ["선정결과", "선정 결과", "최종 선정", "선정 완료", "선정했다", "선정됐다", "선정된", "결과 발표", "우선협상대상자"]):
        return "selection_result"
    if "선정" in value and any(term in value for term in ["gp에", "gp로", "운용사로"]):
        return "selection_result"
    if any(term in value for term in ["숏리스트", "shortlist", "1차 선정", "2라운드", "본선"]):
        return "shortlist"
    if (
        any(term in value for term in ["lp rader", "팀장", "겸임", "조직", "인사"])
        and not any(term in value for term in ["공고", "선정", "마감", "숏리스트"])
    ):
        return "candidate"
    if any(term in value for term in ["설명회", "사업설명회", "제안설명"]):
        return "briefing"
    if any(term in value for term in ["접수", "마감", "제안서", "서류제출"]):
        return "application"
    if (
        any(term in value for term in ["회수", "분배금", "dpi", "moic", "청산"])
        and not any(term in value for term in ["공고", "선정계획", "위탁운용사", "출자사업"])
    ):
        return "performance_update"
    if any(term in value for term in ["공고", "모집", "선정계획", "출자사업", "위탁운용사", "운용사 선정"]):
        return "notice"
    return "candidate"


def infer_event_type(text: str, stage: str, deadline: str, report_date: str) -> str:
    value = text.lower()
    if any(term in value for term in ["취소", "철회", "유찰"]):
        return "cancellation"
    if any(term in value for term in ["정정공고", "수정공고", "재공고", "변경공고", "조건 변경"]):
        return "revision"
    if stage == "selection_result":
        return "final_selection"
    if stage == "shortlist":
        return "shortlist"
    if stage == "performance_update":
        return "performance_update"
    if deadline:
        try:
            gap = (datetime.strptime(deadline, "%Y-%m-%d") - datetime.strptime(report_date, "%Y-%m-%d")).days
        except ValueError:
            gap = 999
        if 0 <= gap <= 14:
            return "deadline_soon"
        if gap < 0:
            return "deadline_closed"
    if stage in {"notice", "application", "briefing"}:
        return "new_notice"
    return "candidate"


def infer_asset_class(text: str) -> str:
    value = text.lower()
    if ("pe" in value or "pef" in value or "사모펀드" in value) and ("vc" in value or "벤처" in value):
        return "PEF/VC"
    if any(term in value for term in ["프라이빗크레딧", "private credit", "사모대출", "인수금융", "메자닌", "pc펀드"]):
        return "Private Credit"
    if any(term in value for term in ["벤처", "vc", "모태펀드", "한국벤처투자"]):
        return "VC"
    if any(term in value for term in ["인프라", "infrastructure"]):
        return "Infrastructure"
    if any(term in value for term in ["부동산", "리츠", "real estate"]):
        return "Real Estate"
    if any(term in value for term in ["pef", "사모펀드", "블라인드", "바이아웃", "private equity"]):
        return "PEF"
    return ""


def infer_strategy(text: str) -> str:
    value = text.lower()
    if "공급망안정화기금" in text:
        return "공급망안정화기금"
    if "국민성장펀드" in text:
        return "국민성장펀드"
    if "모태펀드" in text:
        return "모태펀드"
    if any(term in value for term in ["블라인드", "blind"]):
        return "블라인드"
    if any(term in value for term in ["세컨더리", "secondary"]):
        return "세컨더리"
    if any(term in value for term in ["프로젝트", "project"]):
        return "프로젝트"
    if any(term in value for term in ["재간접", "fund of funds"]):
        return "재간접"
    return ""


def parse_number(value: str) -> float:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return 0.0


def amount_to_krw_100mn(amount: float, unit: str) -> float:
    return amount * 10000 if unit.strip().startswith("조") else amount


def amount_context(text: str, start: int, end: int) -> str:
    left = max(0, start - MONEY_CONTEXT_WINDOW)
    right = min(len(text), end + MONEY_CONTEXT_WINDOW)
    return text[left:right]


def is_non_commitment_amount_context(context: str) -> bool:
    ctx = context.lower()
    if any(hint.lower() in ctx for hint in NON_COMMITMENT_AMOUNT_HINTS):
        return True
    return ("미만" in ctx or "이상" in ctx) and any(hint in ctx for hint in ["aum", "운용", "자산", "트랙레코드"])


def classify_amounts(text: str) -> dict[str, object]:
    cleaned = re.sub(r"\[[^\]]*국민성장펀드[^\]]*\]", " ", text or "")
    amount_rows: list[dict[str, object]] = []
    for match in COMBINED_AMOUNT_RE.finditer(text):
        jo = parse_number(match.group("jo"))
        eok = parse_number(match.group("eok") or "0")
        if jo:
            ctx = amount_context(text, match.start(), match.end())
            amount_rows.append({"amount": (jo * 10000) + eok, "context": ctx, "raw": match.group(0)})
    for match in AMOUNT_RE.finditer(cleaned):
        amount = parse_number(match.group("num"))
        unit = match.group("unit")
        if not amount:
            continue
        ctx = amount_context(cleaned, match.start(), match.end())
        amount_rows.append({"amount": amount_to_krw_100mn(amount, unit), "context": ctx, "raw": match.group(0)})
    program_amounts: list[float] = []
    allocation_amounts: list[float] = []
    fallback_amounts: list[float] = []
    for row in amount_rows:
        ctx = str(row["context"]).lower()
        amount = float(row["amount"])
        if is_non_commitment_amount_context(ctx):
            continue
        is_program = (
            amount >= 50000
            and any(hint.lower() in ctx for hint in PROGRAM_SIZE_HINTS)
            and not any(hint.lower() in ctx for hint in ["이번 출자", "출자 공고", "위탁운용사 선정"])
        )
        if is_program:
            program_amounts.append(amount)
            continue
        if any(hint.lower() in ctx for hint in ALLOCATION_HINTS):
            allocation_amounts.append(amount)
        if amount < 50000:
            fallback_amounts.append(amount)
    allocation = max(allocation_amounts) if allocation_amounts else None
    program = max(program_amounts) if program_amounts else None
    if allocation is None and fallback_amounts:
        allocation = max(fallback_amounts)
    return {
        "allocation_amount_krw_100mn": allocation,
        "program_size_krw_100mn": program,
        "amount_type": "allocation" if allocation else ("program_size" if program else ""),
        "amount_confidence": "medium" if allocation else ("low" if program else ""),
    }


def infer_program_name(text: str) -> str:
    if "공급망안정화기금" in text:
        return "공급망안정화기금"
    if "국민성장펀드" in text:
        return "국민성장펀드"
    if "농식품모태펀드" in text or "농림수산식품모태펀드" in text:
        return "농식품모태펀드"
    if "모태펀드" in text:
        return "모태펀드"
    match = re.search(r"([가-힣A-Za-z0-9·\-\s]{2,40}(?:펀드|출자사업))", text)
    return normalize_whitespace(match.group(1)) if match else ""


def infer_round_name(text: str) -> str:
    patterns = [
        r"(\d+차\s*(?:출자|공고|선정|간접투자)?)",
        r"(상반기|하반기|정시|수시)\s*(?:출자|공고|선정)?",
        r"(대형|중형|루키|도전|코스닥|M&A|세컨더리)\s*(?:리그|분야)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return normalize_whitespace(match.group(1))
    return ""


def confidence_for(source_type: str, lp_code: str, event_type: str, allocation: object, title: str) -> tuple[str, str, int]:
    notes: list[str] = []
    score = 0
    if source_type == "official":
        score += 3
    else:
        notes.append("news_source")
        score += 1
    if lp_code:
        score += 1
    else:
        notes.append("lp_unmatched")
    if event_type in {"new_notice", "deadline_soon", "final_selection", "shortlist"}:
        score += 1
    if allocation:
        score += 1
    else:
        notes.append("allocation_unverified")
    if "국민성장펀드" in title and not lp_code:
        notes.append("program_strategy_only")
    confidence = "high" if score >= 5 else "medium" if score >= 3 else "low"
    title_noise = any(term in title for term in ["LP Rader", "팀장", "겸임", "조직", "인사"])
    direct_news_notice = (
        any(term in title for term in ["출자", "공고", "국민성장펀드", "모태펀드", "농금원", "국민연금", "산은", "산업은행", "성장금융"])
        and not title_noise
    )
    public_news_event = (
        (event_type == "new_notice" and bool(allocation) and direct_news_notice)
        or event_type in {"deadline_soon", "shortlist", "final_selection", "revision", "cancellation"}
    )
    public_visible = 1 if (
        lp_code
        and confidence in {"high", "medium"}
        and event_type != "candidate"
        and (source_type == "official" or public_news_event)
    ) else 0
    return confidence, "; ".join(notes), public_visible


def is_menu_link(title: str, url: str) -> bool:
    compact_title = normalize_whitespace(title)
    lowered_url = (url or "").strip().lower()
    if compact_title in GENERIC_LISTING_TITLES:
        return True
    if lowered_url.startswith("javascript:") or lowered_url.endswith("#") or lowered_url.startswith("#"):
        return True
    if len(compact_title) <= 3:
        return True
    return False


def is_non_commitment_notice(title: str) -> bool:
    return any(term.lower() in title.lower() for term in NON_COMMITMENT_NOTICE_TERMS)


def clean_official_notice_title(title: str, lp_name: str = "") -> str:
    text = normalize_whitespace(strip_html_tags(unquote_plus(str(title or ""))))
    if not text:
        return ""
    if "|" in text:
        parts = [
            normalize_whitespace(part)
            for part in text.split("|")
            if normalize_whitespace(part)
        ]
        substantive_parts = [
            part
            for part in parts
            if len(part) >= 12
            and any(term in part for term in DETAIL_TITLE_TERMS)
            and part not in GENERIC_LISTING_TITLES
        ]
        if substantive_parts:
            text = max(substantive_parts, key=len)
    text = re.sub(r"\s*\bNEW\b\s*$", "", text, flags=re.IGNORECASE)
    text = TITLE_METADATA_RE.sub(" ", text)
    text = re.sub(r"\s*(?:을|를)?\s*표시합니다\.?\s*$", "", text)
    text = normalize_whitespace(text)
    if lp_name:
        escaped_lp = re.escape(normalize_whitespace(lp_name))
        text = re.sub(rf"^(?:\[{escaped_lp}\]|{escaped_lp})\s*", "", text)
    return normalize_whitespace(text)


def title_noise_score(title: str) -> int:
    text = normalize_whitespace(title)
    score = 0
    if TITLE_METADATA_RE.search(text):
        score += 4
    if re.search(r"\bNEW\b\s*$", text, flags=re.IGNORECASE):
        score += 1
    if ".." in text or "…" in text:
        score += 3
    if any(token in text for token in ["상세보기", "목록으로", "작성자", "조회수", "상세내용"]):
        score += 5
    if len(text) < 12:
        score += 2
    return score


def choose_official_notice_title(listing_title: str, detail_title: str, lp_name: str = "") -> str:
    listing = clean_official_notice_title(listing_title, lp_name)
    detail = clean_official_notice_title(detail_title, lp_name)
    if not is_useful_official_detail_title(detail):
        return listing
    listing_noise = title_noise_score(listing_title)
    detail_noise = title_noise_score(detail)
    if not listing:
        return detail
    if detail_noise < listing_noise:
        return detail
    if (".." in listing or "…" in listing) and len(detail) >= len(listing.rstrip(".…")):
        return detail
    if len(detail) > len(listing) + 8:
        return detail
    return listing


def normalize_date(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    match = DATE_RE.search(value)
    if match:
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return ""
    return value[:10] if re.match(r"^20\d{2}-\d{2}-\d{2}", value) else ""


def extract_year(date_value: str, text: str, fallback_year: int) -> int | None:
    normalized = normalize_date(date_value)
    if normalized:
        return int(normalized[:4])
    years = [
        year
        for year in [int(match) for match in re.findall(r"20\d{2}", text)]
        if 2000 <= year <= fallback_year + 1
    ]
    if years:
        return max(years)
    return fallback_year


def extract_deadline(text: str) -> str:
    for pattern in [
        r"(?:접수|제출|신청|마감)[^0-9]{0,20}(20\d{2}[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2})",
        r"(20\d{2}[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2})[^0-9]{0,20}(?:까지|마감)",
    ]:
        match = re.search(pattern, text)
        if match:
            return normalize_date(match.group(1))
    return ""


def extract_announcement_date(text: str) -> str:
    for pattern in [
        r"(?:공고일|게시일|등록일|작성일)[^0-9]{0,20}(20\d{2}[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2})",
        r"(20\d{2}[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2})[^0-9]{0,20}(?:공고|게시|등록)",
        r"(20\d{2}[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2})[^0-9]{0,20}(?:작성자|조회수)",
    ]:
        match = re.search(pattern, text)
        if match:
            return normalize_date(match.group(1))
    return ""


def clean_attachment_name(value: str) -> str:
    name = unquote_plus(str(value or "").strip())
    name = normalize_whitespace(name.replace("+", " "))
    return name or "공식 첨부파일"


def semicolon_join(values: list[str]) -> str:
    cleaned: list[str] = []
    for value in values:
        text = normalize_whitespace(str(value or "").replace(";", ","))
        if text and text not in cleaned:
            cleaned.append(text)
    return "; ".join(cleaned)


def extract_official_attachments(base_url: str, html_text: str) -> list[dict[str, str]]:
    attachments: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_attachment(name: str, href: str) -> None:
        absolute = urljoin(base_url, href.strip())
        if not absolute or absolute in seen:
            return
        clean_name = clean_attachment_name(name)
        haystack = f"{absolute} {clean_name}".lower()
        if clean_name in {"다운로드", "바로보기"}:
            return
        if any(term in haystack for term in ["inspectexample", "검사사례", "정보통신접근성", "품질인증"]):
            return
        absolute_lower = absolute.lower()
        if not (
            FILE_EXT_RE.search(absolute)
            or (FILE_EXT_RE.search(name) and any(term in absolute_lower for term in ["download", "file", "atch", "attach"]))
        ):
            return
        seen.add(absolute)
        attachments.append({"name": clean_name, "url": absolute})

    for call in re.findall(r"RAONKUPLOAD\.AddUploadedFile\((.*?)\);", html_text, flags=re.IGNORECASE | re.DOTALL):
        parts = re.findall(r'"([^"]*)"', call)
        if len(parts) >= 3:
            add_attachment(parts[1], parts[2])

    for match in re.finditer(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html_text, flags=re.IGNORECASE | re.DOTALL):
        href = match.group(1)
        label = strip_html_tags(match.group(2))
        add_attachment(label, href)

    for item in re.findall(r"<li\b[^>]*>.*?</li>", html_text, flags=re.IGNORECASE | re.DOTALL):
        if "download.do" not in item:
            continue
        name_match = re.search(r"<em\b[^>]*>(?P<name>.*?)</em>", item, flags=re.IGNORECASE | re.DOTALL)
        href_match = re.search(r"<a\b[^>]*href=[\"'](?P<href>[^\"']*download\.do[^\"']*)[\"']", item, flags=re.IGNORECASE | re.DOTALL)
        if not name_match or not href_match:
            continue
        label = re.sub(r"\([^)]*KB\)", "", strip_html_tags(name_match.group("name")), flags=re.IGNORECASE)
        label = normalize_whitespace(label.replace("첨부파일", ""))
        add_attachment(label, href_match.group("href"))

    return attachments


def primary_document_url(attachments: list[dict[str, str]]) -> str:
    for item in attachments:
        name = str(item.get("name") or "")
        url = str(item.get("url") or "")
        if url and ("공고" in name or "선정계획" in name):
            return url
    for item in attachments:
        url = str(item.get("url") or "")
        if url and re.search(r"\.pdf($|[?#&])", url, flags=re.IGNORECASE):
            return url
    return str(attachments[0].get("url") or "") if attachments else ""


def extract_official_detail_title(html_text: str) -> str:
    summary_match = re.search(r"<table\b[^>]*summary=[\"'](?P<summary>[^\"']+)[\"']", html_text, flags=re.IGNORECASE)
    if summary_match:
        title = clean_official_notice_title(summary_match.group("summary"))
        title = re.sub(r"\s*에 대한\s+작성자.*$", "", title)
        title = re.sub(r"\s*에 대한\s*$", "", title)
        if is_useful_official_detail_title(title):
            return title
    for pattern in [
        r"<meta\b[^>]*(?:property|name)=[\"'](?:og:title|title)[\"'][^>]*content=[\"'](?P<title>[^\"']+)[\"']",
        r"<meta\b[^>]*content=[\"'](?P<title>[^\"']+)[\"'][^>]*(?:property|name)=[\"'](?:og:title|title)[\"']",
        r"<h1\b[^>]*>(?P<title>.*?)</h1>",
        r"<h2\b[^>]*>(?P<title>.*?)</h2>",
    ]:
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        title = clean_official_notice_title(match.group("title"))
        if is_useful_official_detail_title(title) and not re.fullmatch(r"거래기관선정공고.*", title):
            return title
    return ""


def is_useful_official_detail_title(title: str) -> bool:
    if not title:
        return False
    if any(token in title for token in ["상세보기", "목록으로", "작성자", "조회수", "상세내용", "Agricultural Policy"]):
        return False
    return any(token in title for token in DETAIL_TITLE_TERMS)


def fetch_official_detail(notice_url: str, allow_insecure_ssl: bool) -> dict[str, object]:
    try:
        fetched = fetch_text(notice_url, verify_ssl=not allow_insecure_ssl)
    except Exception as exc:
        print(f"warning: notice_detail_fetch_failed url={notice_url} error={exc}")
        return {}
    html_text = str(fetched.get("text") or "")
    final_url = str(fetched.get("final_url") or notice_url)
    return {
        "attachments": extract_official_attachments(final_url, html_text),
        "title": extract_official_detail_title(html_text),
        "text": strip_html_tags(re.sub(r"<script\b.*?</script>", " ", html_text, flags=re.IGNORECASE | re.DOTALL)),
    }


def normalize_official_notice_url(source: dict[str, str], notice_url: str) -> str:
    source_code = source.get("source_code", "")
    if source_code == "pmaa_bid_notice":
        match = re.search(r"fn_view\(['\"](?P<id>\d+)['\"]\)", notice_url)
        if match:
            return f"https://www.pmaa.or.kr/www/1461128463820/bbs.do?bbs_idx={match.group('id')}&recruitCd=&type=view"
    if source_code == "koreapost_asset_notice":
        match = re.search(
            r"introBoardView\(['\"](?P<mid>[^'\"]+)['\"]\s*,\s*['\"](?P<no>\d+)['\"]\s*,\s*['\"](?P<bid>[^'\"]*)['\"]\)",
            notice_url,
        )
        if match:
            bid = match.group("bid") or "0041"
            return (
                "https://www.kpasset.go.kr/board.es"
                f"?mid={match.group('mid')}&bid={bid}&list_no={match.group('no')}&act=view&intro_yn=Y"
            )
    return notice_url


def fetch_form_text(url: str, data: dict[str, str], referer: str, allow_insecure_ssl: bool) -> str:
    encoded = urlencode(data).encode("utf-8")
    request = Request(
        url,
        data=encoded,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko,en-US;q=0.7,en;q=0.3",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": referer,
        },
    )
    context = None
    if allow_insecure_ssl and url.lower().startswith("https://"):
        context = ssl._create_unverified_context()
    with urlopen(request, timeout=20, context=context) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def apfs_board_params(locator: str, page_size: int) -> dict[str, str]:
    parsed = urlparse(locator)
    query = parse_qs(parsed.query)
    return {
        "miv_pageNo": "1",
        "miv_pageSize": str(max(10, min(page_size, 50))),
        "total_cnt": "",
        "LISTOP": "",
        "mode": "W",
        "contId": "",
        "delYn": "N",
        "menuId": query.get("menuId", ["5386"])[0],
        "boardId": query.get("boardId", ["10026"])[0],
        "selTab": query.get("selTab", ["1"])[0],
        "requestUrl": "",
        "searchKey": "A",
        "searchTxt": "",
    }


def parse_apfs_board_listing(source: dict[str, str], limit: int, allow_insecure_ssl: bool) -> list[dict[str, str]]:
    locator = source.get("locator", "")
    params = apfs_board_params(locator, limit)
    list_url = urljoin(locator, "/front/board/boardContentsList.do")
    html_text = fetch_form_text(list_url, params, locator, allow_insecure_ssl)
    rows: list[dict[str, str]] = []
    for row_html in re.findall(r"<tr\b.*?</tr>", html_text, flags=re.IGNORECASE | re.DOTALL):
        anchor = re.search(
            r"<a\b(?P<attrs>[^>]*\bclass=[\"'][^\"']*detail_view[^\"']*[\"'][^>]*)>(?P<title>.*?)</a>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not anchor:
            continue
        view_id = re.search(r"\bviewId=[\"'](?P<id>\d+)[\"']", anchor.group("attrs"), flags=re.IGNORECASE)
        if not view_id:
            continue
        date_match = re.search(
            r"<td\b[^>]*class=[\"'][^\"']*c_reg_dt[^\"']*[\"'][^>]*>(?P<date>.*?)</td>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        team_match = re.search(
            r"<td\b[^>]*class=[\"'][^\"']*c_reg_mem_nm[^\"']*[\"'][^>]*>(?P<team>.*?)</td>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        view_params = dict(params)
        view_params["contId"] = view_id.group("id")
        view_url = urljoin(locator, "/front/board/boardContentsView.do") + "?" + urlencode(view_params)
        rows.append(
            {
                "title": strip_html_tags(anchor.group("title")),
                "link": view_url,
                "announced_date": strip_html_tags(date_match.group("date")) if date_match else "",
                "contact_team": strip_html_tags(team_match.group("team")) if team_match else "",
            }
        )
    return rows


def parse_kbiz_listing(source: dict[str, str], allow_insecure_ssl: bool) -> list[dict[str, str]]:
    locator = source.get("locator", "")
    parsed = urlparse(locator)
    query = parse_qs(parsed.query)
    mn_seq = query.get("mnSeq", ["211"])[0]
    fetched = fetch_text(locator, verify_ssl=not allow_insecure_ssl)
    html_text = str(fetched.get("text") or "")
    final_url = str(fetched.get("final_url") or locator)
    rows: list[dict[str, str]] = []
    for row_html in re.findall(r"<tr\b.*?</tr>", html_text, flags=re.IGNORECASE | re.DOTALL):
        action = re.search(
            r"goView\(\s*(?P<seq>\d+)\s*,\s*&#39;(?P<top>[^&]+)&#39;\s*\)",
            row_html,
            flags=re.IGNORECASE,
        ) or re.search(
            r"goView\(\s*(?P<seq>\d+)\s*,\s*['\"](?P<top>[^'\"]+)['\"]\s*\)",
            row_html,
            flags=re.IGNORECASE,
        )
        if not action:
            continue
        title_match = re.search(
            r"<td\b[^>]*class=[\"'][^\"']*subject[^\"']*[\"'][^>]*>.*?<span\b[^>]*>(?P<title>.*?)</span>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        date_match = re.search(
            r"<td\b[^>]*class=[\"'][^\"']*date[^\"']*[\"'][^>]*>\s*<span>(?P<date>.*?)</span>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            continue
        seq = action.group("seq")
        top = action.group("top")
        view_url = urljoin(final_url, f"./view.do?seq={seq}&topFixYn={top}&mnSeq={mn_seq}")
        rows.append(
            {
                "title": strip_html_tags(title_match.group("title")),
                "link": view_url,
                "announced_date": normalize_date(strip_html_tags(date_match.group("date"))) if date_match else "",
                "contact_team": "",
            }
        )
    return rows


def parse_ktcu_listing(source: dict[str, str], limit: int, allow_insecure_ssl: bool) -> list[dict[str, str]]:
    locator = source.get("locator", "")
    if not locator:
        return []
    search_terms = split_semicolon(source.get("must_contain", ""))
    if not search_terms:
        search_terms = ["위탁운용", "블라인드", "PEF", "VC", "골프장"]
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_rows_from_html(html_text: str) -> None:
        for item in re.findall(r"<li\b.*?</li>", html_text, flags=re.IGNORECASE | re.DOTALL):
            action = re.search(r"fn_view\(['\"](?P<id>\d+)['\"]\)", item, flags=re.IGNORECASE)
            title_match = re.search(
                r"<span\b[^>]*class=[\"'][^\"']*tit[^\"']*[\"'][^>]*>.*?<a\b[^>]*>(?P<title>.*?)</a>",
                item,
                flags=re.IGNORECASE | re.DOTALL,
            )
            date_matches = re.findall(
                r"<span\b[^>]*class=[\"']date[\"'][^>]*>(?P<value>.*?)</span>",
                item,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not action or not title_match:
                continue
            title = strip_html_tags(title_match.group("title"))
            if not any(term.lower() in title.lower() for term in search_terms):
                continue
            notice_id = action.group("id")
            link = urljoin(locator, f"/PPW-CSB-000101/{notice_id}")
            if link in seen:
                continue
            seen.add(link)
            rows.append(
                {
                    "title": title,
                    "link": link,
                    "announced_date": normalize_date(strip_html_tags(date_matches[0])) if date_matches else "",
                    "contact_team": "",
                }
            )

    try:
        fetched = fetch_text(locator, verify_ssl=not allow_insecure_ssl)
        add_rows_from_html(str(fetched.get("text") or ""))
    except Exception as exc:
        print(f"warning: ktcu_listing_fetch_failed url={locator} error={exc}")

    for term in search_terms:
        if len(rows) >= limit:
            break
        try:
            html_text = fetch_form_text(
                locator,
                {
                    "srchCtgry": "",
                    "curPage": "1",
                    "srchKey": "all",
                    "srchText": term,
                },
                locator,
                allow_insecure_ssl,
            )
        except Exception as exc:
            print(f"warning: ktcu_listing_search_failed term={term} error={exc}")
            continue
        add_rows_from_html(html_text)

    return rows[:limit]


def parse_cu_listing(source: dict[str, str], limit: int, allow_insecure_ssl: bool) -> list[dict[str, str]]:
    locator = source.get("locator", "")
    if not locator:
        return []
    parsed = urlparse(locator)
    query = parse_qs(parsed.query)
    mi = query.get("mi", ["100007"])[0]
    bbs_id = query.get("bbsId", ["1020"])[0]
    list_url = urljoin(locator, "/cu/na/ntt/selectNttList.do")
    search_terms = split_semicolon(source.get("must_contain", ""))
    if not search_terms:
        search_terms = ["블라인드", "위탁운용", "PE", "VC"]

    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_rows_from_html(html_text: str) -> None:
        for row_html in re.findall(r"<tr\b.*?</tr>", html_text, flags=re.IGNORECASE | re.DOTALL):
            anchor = re.search(
                r"<a\b[^>]*href=[\"'](?P<href>[^\"']*selectNttInfo\.do[^\"']*)[\"'][^>]*>(?P<title>.*?)</a>",
                row_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not anchor:
                continue
            title = normalize_whitespace(strip_html_tags(anchor.group("title")))
            if not title:
                continue
            link = urljoin(locator, anchor.group("href").replace("&amp;", "&"))
            if link in seen:
                continue
            date_match = re.search(
                r"<td\b[^>]*data-table=[\"']date[\"'][^>]*>(?P<date>.*?)</td>",
                row_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            seen.add(link)
            rows.append(
                {
                    "title": title,
                    "link": link,
                    "announced_date": normalize_date(strip_html_tags(date_match.group("date"))) if date_match else "",
                    "contact_team": "",
                }
            )

    for term in search_terms:
        if len(rows) >= limit:
            break
        try:
            html_text = fetch_form_text(
                list_url,
                {
                    "mi": mi,
                    "bbsId": bbs_id,
                    "nttSn": "",
                    "currPage": "1",
                    "listCo": str(max(10, min(limit, 50))),
                    "searchType": "all",
                    "searchValue": term,
                },
                locator,
                allow_insecure_ssl,
            )
        except Exception as exc:
            print(f"warning: cu_listing_search_failed term={term} error={exc}")
            continue
        add_rows_from_html(html_text)

    return rows[:limit]


def parse_kfcc_tender_listing(source: dict[str, str], limit: int, allow_insecure_ssl: bool) -> list[dict[str, str]]:
    locator = source.get("locator", "")
    if not locator:
        return []
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    search_terms = split_semicolon(source.get("must_contain", ""))

    def add_rows_from_html(html_text: str, final_url: str) -> None:
        for item in re.findall(r"<li\b.*?</li>", html_text, flags=re.IGNORECASE | re.DOTALL):
            action = re.search(r"fnDetail\(['\"](?P<id>\d+)['\"]\)", item, flags=re.IGNORECASE)
            title_match = re.search(r"<a\b[^>]*>\s*(?P<title>.*?)\s*</a>", item, flags=re.IGNORECASE | re.DOTALL)
            if not action or not title_match:
                continue
            title = normalize_whitespace(strip_html_tags(title_match.group("title")))
            if not title or not matches_must_contain(search_terms, title):
                continue
            notice_id = action.group("id")
            link = urljoin(final_url, f"/noticeofTender/noticeofTenderDetail.do?no={notice_id}")
            if link in seen:
                continue
            date_match = re.search(
                r"<div\b[^>]*class=[\"'][^\"']*date[^\"']*[\"'][^>]*>(?P<date>.*?)</div>",
                item,
                flags=re.IGNORECASE | re.DOTALL,
            )
            seen.add(link)
            rows.append(
                {
                    "title": title,
                    "link": link,
                    "announced_date": normalize_date(strip_html_tags(date_match.group("date"))) if date_match else "",
                    "contact_team": "",
                }
            )
            if len(rows) >= limit:
                break

    page_count = max(1, min(12, (limit + 7) // 8 + 4))
    for page_no in range(1, page_count + 1):
        if len(rows) >= limit:
            break
        try:
            if page_no == 1:
                page_url = locator
            else:
                page_url = urljoin(locator, "/noticeofTender/noticeofTenderList.do") + "?" + urlencode(
                    {
                        "pageRows": "8",
                        "pageUnit": "10",
                        "totalRows": "",
                        "currentPageNo": "1",
                        "boardId": "A02",
                        "no": "",
                        "schCategoryId": "",
                        "schType": "",
                        "schValue": "",
                        "status": "",
                        "pageNo": str(page_no),
                    }
                )
            fetched = fetch_text(page_url, verify_ssl=not allow_insecure_ssl)
        except Exception as exc:
            print(f"warning: kfcc_tender_fetch_failed page={page_no} error={exc}")
            continue
        add_rows_from_html(str(fetched.get("text") or ""), str(fetched.get("final_url") or page_url))

    list_url = urljoin(locator, "/noticeofTender/noticeofTenderList.do")
    for term in search_terms:
        if len(rows) >= limit:
            break
        if len(term) < 2:
            continue
        try:
            html_text = fetch_form_text(
                list_url,
                {
                    "pageNo": "1",
                    "no": "",
                    "schCategoryId": "",
                    "schType": "all",
                    "schValue": term,
                },
                locator,
                allow_insecure_ssl,
            )
        except Exception as exc:
            print(f"warning: kfcc_tender_search_failed term={term} error={exc}")
            continue
        add_rows_from_html(html_text, list_url)
    return rows[:limit]


def selected_gp_names(title: str, excerpt: str, aliases: object, existing: str = "") -> str:
    names = [part.strip() for part in re.split(r"[,;]", existing or "") if part.strip()]
    for match in match_gp_entities(title, excerpt, "", aliases):
        name = str(match.get("entity_name") or "").strip()
        if name and name not in names:
            names.append(name)
    names = [name for name in names if name and name not in GP_EXCLUSION_NAMES]
    return "; ".join(names)


def is_lp_related_news(row: dict[str, object], text: str, lp_code: str) -> bool:
    tag_text = " ".join(
        str(row.get(key) or "")
        for key in ["section_tags", "section_override_tags", "topic_tags"]
    )
    text = " ".join(
        [
            text,
            tag_text,
        ]
    )
    lowered = text.lower()
    notice = any(term.lower() in lowered for term in NOTICE_TERMS)
    fundraising = any(term.lower() in lowered for term in FUNDRAISING_TERMS)
    context = any(term.lower() in lowered for term in LP_CONTEXT_TERMS)
    if notice:
        return True
    if fundraising and (lp_code or context):
        return True
    return False


def make_notice_row(
    *,
    lp_code: str,
    source_code: str,
    source_type: str,
    notice_url: str,
    title: str,
    announced_date: str,
    fallback_year: int,
    report_date: str,
    text: str,
    gp_names: str,
    raw_excerpt: str,
    contact_team: str = "",
    document_url: str = "",
    attachment_names: str = "",
    attachment_urls: str = "",
) -> dict[str, object]:
    cleaned_text = normalize_whitespace(text)
    title = normalize_whitespace(title)
    announced = normalize_date(announced_date) or extract_announcement_date(cleaned_text)
    deadline = extract_deadline(cleaned_text)
    title_stage = infer_stage(title)
    stage = title_stage if title_stage in {"notice", "application", "briefing"} else infer_stage(cleaned_text)
    event_type = infer_event_type(title, stage, deadline, report_date)
    amount_info = classify_amounts(cleaned_text)
    allocation = amount_info["allocation_amount_krw_100mn"]
    confidence, confidence_note, public_visible = confidence_for(source_type, lp_code, event_type, allocation, title)
    first_document = document_url or (split_semicolon(attachment_urls)[0] if attachment_urls else "")
    return {
        "lp_code": lp_code or None,
        "source_code": source_code,
        "source_type": source_type,
        "notice_url": notice_url,
        "normalized_notice_url": normalize_url(notice_url),
        "document_url": first_document or (notice_url if FILE_EXT_RE.search(notice_url) else ""),
        "attachment_names": attachment_names,
        "attachment_urls": attachment_urls,
        "title": title,
        "event_type": event_type,
        "event_date": announced or report_date,
        "program_name": infer_program_name(cleaned_text),
        "round_name": infer_round_name(cleaned_text),
        "announced_date": announced,
        "notice_year": extract_year(announced, cleaned_text, fallback_year),
        "application_deadline": deadline,
        "notice_stage": stage,
        "asset_class": infer_asset_class(cleaned_text),
        "strategy": infer_strategy(cleaned_text),
        "program_size_krw_100mn": amount_info["program_size_krw_100mn"],
        "allocation_amount_krw_100mn": allocation,
        "amount_type": amount_info["amount_type"],
        "amount_confidence": amount_info["amount_confidence"],
        "commitment_amount_krw_100mn": allocation,
        "selected_gp_names": gp_names,
        "contact_team": contact_team,
        "confidence": confidence,
        "confidence_note": confidence_note,
        "public_visible": public_visible,
        "monitor_status": "candidate",
        "raw_excerpt": raw_excerpt,
        "discovered_at": now_utc_iso(),
        "updated_at": now_utc_iso(),
    }


def load_official_candidates(
    sources: list[dict[str, str]],
    lp_aliases: list[LpAlias],
    fallback_year: int,
    report_date: str,
    limit_per_source: int,
    allow_insecure_ssl: bool,
    gp_aliases: object,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    lp_names_by_code = {alias.lp_code: alias.lp_name for alias in lp_aliases}
    for source in sources:
        source_kind = source.get("source_kind", "")
        if not parse_bool(source.get("is_active", "1")) or source_kind not in {"html_listing", "apfs_board", "kbiz_listing", "ktcu_notice", "cu_notice", "kfcc_tender"}:
            continue
        locator = source.get("locator", "")
        if not locator:
            continue
        try:
            if source_kind == "apfs_board":
                links = parse_apfs_board_listing(source, limit_per_source, allow_insecure_ssl)
            elif source_kind == "kbiz_listing":
                links = parse_kbiz_listing(source, allow_insecure_ssl)
            elif source_kind == "ktcu_notice":
                links = parse_ktcu_listing(source, limit_per_source, allow_insecure_ssl)
            elif source_kind == "cu_notice":
                links = parse_cu_listing(source, limit_per_source, allow_insecure_ssl)
            elif source_kind == "kfcc_tender":
                links = parse_kfcc_tender_listing(source, limit_per_source, allow_insecure_ssl)
            else:
                fetched = fetch_text(locator, verify_ssl=not allow_insecure_ssl)
                links = parse_html_listing(
                    str(fetched.get("final_url") or locator),
                    str(fetched.get("text") or ""),
                    source.get("article_url_regex", ""),
                )
        except Exception as exc:
            print(f"warning: source_fetch_failed source_code={source.get('source_code')} error={exc}")
            continue
        count = 0
        for link in links:
            title = normalize_whitespace(link.get("title", ""))
            notice_url = normalize_official_notice_url(source, link.get("link", ""))
            if len(title) < 4 or not notice_url:
                continue
            if is_menu_link(title, notice_url):
                continue
            if is_non_commitment_notice(title):
                continue
            if not matches_must_contain(split_semicolon(source.get("must_contain", "")), title, notice_url):
                continue
            detail = fetch_official_detail(notice_url, allow_insecure_ssl)
            detail_title = normalize_whitespace(str(detail.get("title") or ""))
            detail_text = normalize_whitespace(str(detail.get("text") or ""))[:6000]
            attachments = [item for item in detail.get("attachments", []) if isinstance(item, dict)]
            attachment_names = semicolon_join([str(item.get("name") or "") for item in attachments])
            attachment_urls = semicolon_join([str(item.get("url") or "") for item in attachments])
            preliminary_text = f"{title} {detail_title} {detail_text} {notice_url}"
            lp_code = infer_lp_code(preliminary_text, lp_aliases, source.get("lp_code", ""))
            title = choose_official_notice_title(title, detail_title, lp_names_by_code.get(lp_code, ""))
            text = f"{title} {notice_url}" if source.get("source_code") == "vcs_investment_notice" else f"{title} {detail_text} {notice_url}"
            lp_code = infer_lp_code(title, lp_aliases, lp_code) or infer_lp_code(text, lp_aliases, lp_code)
            announced_date = link.get("announced_date", "")
            contact_team = link.get("contact_team", "")
            stage_for_gp = infer_stage(f"{title} {detail_text}")
            gp_text = detail_text[:3000] if stage_for_gp in {"selection_result", "shortlist"} else ""
            rows.append(
                make_notice_row(
                    lp_code=lp_code,
                    source_code=source.get("source_code", ""),
                    source_type="official",
                    notice_url=notice_url,
                    title=title,
                    announced_date=announced_date,
                    fallback_year=fallback_year,
                    report_date=report_date,
                    text=text,
                    gp_names=selected_gp_names(title, gp_text, gp_aliases),
                    raw_excerpt=f"{source.get('source_name', '')} 목록에서 발견",
                    contact_team=contact_team,
                    document_url=primary_document_url(attachments),
                    attachment_names=attachment_names,
                    attachment_urls=attachment_urls,
                )
            )
            count += 1
            if count >= limit_per_source:
                break
    return rows


def load_news_candidates(
    conn: sqlite3.Connection,
    lp_aliases: list[LpAlias],
    fallback_year: int,
    report_date: str,
    days: int,
    gp_aliases: object,
) -> list[dict[str, object]]:
    if not table_exists(conn, "v_news_relevant"):
        return []
    start_date = date_window_start(report_date, days)
    cursor = conn.execute(
        """
        SELECT
            news_id,
            source_code,
            source_url,
            normalized_source_url,
            publisher,
            title,
            published_at,
            discovered_at,
            meta_description,
            excerpt_text,
            section_tags,
            section_override_tags,
            topic_tags,
            gp_names
        FROM v_news_relevant
        WHERE is_pe_relevant = 1
          AND date(substr(COALESCE(NULLIF(published_at, ''), discovered_at), 1, 10)) >= date(?)
        ORDER BY COALESCE(NULLIF(published_at, ''), discovered_at) DESC, news_id DESC
        LIMIT 1200
        """,
        (start_date,),
    )
    headers = [desc[0] for desc in cursor.description]
    rows: list[dict[str, object]] = []
    for raw in [dict(zip(headers, row)) for row in cursor.fetchall()]:
        title = str(raw.get("title") or "")
        excerpt = str(raw.get("excerpt_text") or raw.get("meta_description") or "")
        text = " ".join(
            [
                title,
                excerpt,
                str(raw.get("publisher") or ""),
                str(raw.get("section_tags") or ""),
                str(raw.get("topic_tags") or ""),
            ]
        )
        lp_code = infer_lp_code(text, lp_aliases)
        if not is_lp_related_news(raw, text, lp_code):
            continue
        names = selected_gp_names(title, excerpt, gp_aliases, str(raw.get("gp_names") or ""))
        rows.append(
            make_notice_row(
                lp_code=lp_code,
                source_code=NEWS_FEED_SOURCE_CODE,
                source_type="news",
                notice_url=str(raw.get("source_url") or raw.get("normalized_source_url") or ""),
                title=title,
                announced_date=str(raw.get("published_at") or raw.get("discovered_at") or ""),
                fallback_year=fallback_year,
                report_date=report_date,
                text=text,
                gp_names=names,
                raw_excerpt=excerpt[:500],
            )
        )
    return rows


def csv_float(value: object) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_reviewed_candidates(
    path: Path,
    fallback_year: int,
    report_date: str,
) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for item in read_csv_rows(path):
        lp_code = item.get("lp_code", "")
        notice_url = item.get("notice_url", "")
        title = item.get("title", "")
        if not lp_code or not notice_url or not title:
            continue
        selected_gp_names = item.get("selected_gp_names", "")
        raw_excerpt = item.get("raw_excerpt", "")
        text = " ".join(
            part
            for part in [
                title,
                item.get("program_name", ""),
                item.get("asset_class", ""),
                item.get("strategy", ""),
                item.get("text", ""),
                raw_excerpt,
                selected_gp_names,
                item.get("allocation_amount_krw_100mn", ""),
            ]
            if part
        )
        row = make_notice_row(
            lp_code=lp_code,
            source_code=item.get("source_code", "") or NEWS_FEED_SOURCE_CODE,
            source_type=item.get("source_type", "") or "news",
            notice_url=notice_url,
            title=title,
            announced_date=item.get("announced_date", ""),
            fallback_year=fallback_year,
            report_date=report_date,
            text=text,
            gp_names=selected_gp_names,
            raw_excerpt=raw_excerpt,
            document_url=item.get("document_url", ""),
            attachment_names=item.get("attachment_names", ""),
            attachment_urls=item.get("attachment_urls", ""),
        )
        for key in [
            "event_type",
            "event_date",
            "program_name",
            "round_name",
            "notice_stage",
            "asset_class",
            "strategy",
            "amount_type",
            "amount_confidence",
            "contact_team",
            "confidence",
            "confidence_note",
            "monitor_status",
        ]:
            if item.get(key, ""):
                row[key] = item[key]
        for key in ["program_size_krw_100mn", "allocation_amount_krw_100mn", "commitment_amount_krw_100mn"]:
            parsed = csv_float(item.get(key, ""))
            if parsed is not None:
                row[key] = parsed
        if item.get("public_visible", "") != "":
            row["public_visible"] = 1 if parse_bool(item.get("public_visible", "1")) else 0
        if item.get("selected_gp_names", ""):
            row["selected_gp_names"] = item["selected_gp_names"]
        rows.append(row)
    return rows


def upsert_notices(conn: sqlite3.Connection, rows: list[dict[str, object]]) -> int:
    headers = [
        "lp_code",
        "source_code",
        "source_type",
        "notice_url",
        "normalized_notice_url",
        "document_url",
        "attachment_names",
        "attachment_urls",
        "title",
        "event_type",
        "event_date",
        "program_name",
        "round_name",
        "announced_date",
        "notice_year",
        "application_deadline",
        "notice_stage",
        "asset_class",
        "strategy",
        "program_size_krw_100mn",
        "allocation_amount_krw_100mn",
        "amount_type",
        "amount_confidence",
        "commitment_amount_krw_100mn",
        "selected_gp_names",
        "contact_team",
        "confidence",
        "confidence_note",
        "public_visible",
        "monitor_status",
        "raw_excerpt",
        "discovered_at",
        "updated_at",
    ]
    inserted = 0
    for row in rows:
        if not row.get("normalized_notice_url") or not row.get("title"):
            continue
        conn.execute(
            f"""
            INSERT INTO lp_commitment_notice ({", ".join(headers)})
            VALUES ({", ".join("?" for _ in headers)})
            ON CONFLICT(normalized_notice_url) DO UPDATE SET
                lp_code = COALESCE(excluded.lp_code, lp_commitment_notice.lp_code),
                source_code = excluded.source_code,
                source_type = excluded.source_type,
                notice_url = excluded.notice_url,
                document_url = COALESCE(NULLIF(excluded.document_url, ''), lp_commitment_notice.document_url),
                attachment_names = COALESCE(NULLIF(excluded.attachment_names, ''), lp_commitment_notice.attachment_names),
                attachment_urls = COALESCE(NULLIF(excluded.attachment_urls, ''), lp_commitment_notice.attachment_urls),
                title = excluded.title,
                event_type = COALESCE(NULLIF(excluded.event_type, ''), lp_commitment_notice.event_type),
                event_date = COALESCE(NULLIF(excluded.event_date, ''), lp_commitment_notice.event_date),
                program_name = COALESCE(NULLIF(excluded.program_name, ''), lp_commitment_notice.program_name),
                round_name = COALESCE(NULLIF(excluded.round_name, ''), lp_commitment_notice.round_name),
                announced_date = COALESCE(NULLIF(excluded.announced_date, ''), lp_commitment_notice.announced_date),
                notice_year = COALESCE(excluded.notice_year, lp_commitment_notice.notice_year),
                application_deadline = COALESCE(NULLIF(excluded.application_deadline, ''), lp_commitment_notice.application_deadline),
                notice_stage = COALESCE(NULLIF(excluded.notice_stage, ''), lp_commitment_notice.notice_stage),
                asset_class = COALESCE(NULLIF(excluded.asset_class, ''), lp_commitment_notice.asset_class),
                strategy = COALESCE(NULLIF(excluded.strategy, ''), lp_commitment_notice.strategy),
                program_size_krw_100mn = COALESCE(excluded.program_size_krw_100mn, lp_commitment_notice.program_size_krw_100mn),
                allocation_amount_krw_100mn = COALESCE(excluded.allocation_amount_krw_100mn, lp_commitment_notice.allocation_amount_krw_100mn),
                amount_type = COALESCE(NULLIF(excluded.amount_type, ''), lp_commitment_notice.amount_type),
                amount_confidence = COALESCE(NULLIF(excluded.amount_confidence, ''), lp_commitment_notice.amount_confidence),
                commitment_amount_krw_100mn = COALESCE(excluded.commitment_amount_krw_100mn, lp_commitment_notice.commitment_amount_krw_100mn),
                selected_gp_names = COALESCE(NULLIF(excluded.selected_gp_names, ''), lp_commitment_notice.selected_gp_names),
                contact_team = COALESCE(NULLIF(excluded.contact_team, ''), lp_commitment_notice.contact_team),
                confidence = COALESCE(NULLIF(excluded.confidence, ''), lp_commitment_notice.confidence),
                confidence_note = COALESCE(NULLIF(excluded.confidence_note, ''), lp_commitment_notice.confidence_note),
                public_visible = excluded.public_visible,
                monitor_status = CASE
                    WHEN lp_commitment_notice.monitor_status IN ('validated', 'dismissed')
                    THEN lp_commitment_notice.monitor_status
                    ELSE excluded.monitor_status
                END,
                raw_excerpt = COALESCE(NULLIF(excluded.raw_excerpt, ''), lp_commitment_notice.raw_excerpt),
                updated_at = excluded.updated_at
            """,
            [row.get(header) for header in headers],
        )
        inserted += 1
    conn.commit()
    return inserted


def normalize_title_key(title: str) -> str:
    value = re.sub(r"\[[^\]]+\]", " ", title or "")
    value = re.sub(r"[-–—]\s*(더벨|인베스트조선|매일경제|한국경제|이데일리|블로터|딜사이트)\s*$", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value).lower()


def dedupe_candidates(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[object, str, str, str], dict[str, object]] = {}
    for row in rows:
        key = (
            row.get("lp_code") or "",
            str(row.get("event_type") or ""),
            normalize_title_key(str(row.get("title") or "")),
            str(row.get("event_date") or row.get("announced_date") or "")[:10],
        )
        if not key[2]:
            continue
        current = grouped.get(key)
        if current is None or candidate_quality(row) > candidate_quality(current):
            grouped[key] = row
    return sorted(grouped.values(), key=lambda row: (EVENT_PRIORITY.get(str(row.get("event_type") or ""), 99), str(row.get("event_date") or ""), str(row.get("title") or "")))


def candidate_quality(row: dict[str, object]) -> tuple[int, int, int]:
    confidence_score = {"high": 3, "medium": 2, "low": 1}.get(str(row.get("confidence") or ""), 0)
    source_score = 2 if row.get("source_type") == "official" else 1
    amount_score = 1 if row.get("allocation_amount_krw_100mn") else 0
    return confidence_score, source_score, amount_score


def clear_auto_candidates(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        """
        DELETE FROM lp_commitment_notice
        WHERE monitor_status NOT IN ('validated', 'dismissed')
        """,
    )
    conn.commit()
    return int(cursor.rowcount or 0)


def split_selected_gp_names(value: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"[,;]", value or "")
        if part.strip()
    ]


def notice_gp_alias_indexes(gp_aliases: object) -> tuple[dict[str, object], dict[str, object]]:
    exact_candidates: dict[str, object | None] = {}
    normalized_candidates: dict[str, object | None] = {}
    for alias in gp_aliases:
        values = [
            getattr(alias, "alias_name", ""),
            getattr(alias, "canonical_name", ""),
        ]
        for value in values:
            exact_key = normalize_whitespace(str(value or "")).lower()
            if exact_key:
                current_exact = exact_candidates.get(exact_key)
                if current_exact is None and exact_key in exact_candidates:
                    continue
                if (
                    current_exact is not None
                    and getattr(current_exact, "gp_id", None) != getattr(alias, "gp_id", None)
                ):
                    exact_candidates[exact_key] = None
                else:
                    exact_candidates[exact_key] = alias

            normalized_key = normalize_for_match(str(value or ""))
            if not normalized_key:
                continue
            current = normalized_candidates.get(normalized_key)
            if current is None and normalized_key in normalized_candidates:
                continue
            if (
                current is not None
                and getattr(current, "gp_id", None) != getattr(alias, "gp_id", None)
            ):
                normalized_candidates[normalized_key] = None
            else:
                normalized_candidates[normalized_key] = alias

    exact_by_name = {
        key: alias
        for key, alias in exact_candidates.items()
        if alias is not None
    }
    normalized_by_name = {
        key: alias
        for key, alias in normalized_candidates.items()
        if alias is not None
    }
    return exact_by_name, normalized_by_name


def resolve_notice_gp_alias(
    name: str,
    exact_by_name: dict[str, object],
    normalized_by_name: dict[str, object],
) -> object | None:
    cleaned = normalize_whitespace(name)
    if not cleaned or cleaned in GP_EXCLUSION_NAMES:
        return None
    exact_key = cleaned.lower()
    alias = exact_by_name.get(exact_key)
    if alias is not None:
        return alias
    return normalized_by_name.get(normalize_for_match(cleaned))


def refresh_notice_links(conn: sqlite3.Connection, gp_aliases: object) -> tuple[int, int]:
    conn.execute("DELETE FROM lp_notice_gp_link")
    conn.execute("DELETE FROM lp_notice_news_link")

    exact_by_name, normalized_by_name = notice_gp_alias_indexes(gp_aliases)

    gp_links = 0
    for notice_id, lp_code, selected_names, source_type, event_type in conn.execute(
        """
        SELECT notice_id, lp_code, selected_gp_names, source_type, event_type
        FROM lp_commitment_notice
        WHERE public_visible = 1
          AND COALESCE(selected_gp_names, '') <> ''
        """
    ):
        for name in split_selected_gp_names(str(selected_names or "")):
            alias = resolve_notice_gp_alias(name, exact_by_name, normalized_by_name)
            if alias is None:
                continue
            link_confidence = "high" if source_type == "official" and event_type in {"final_selection", "shortlist"} else "medium" if event_type in {"final_selection", "shortlist"} else "low"
            conn.execute(
                """
                INSERT OR IGNORE INTO lp_notice_gp_link (
                    notice_id, lp_code, source_gp_id, gp_name, matched_alias, link_source, confidence
                )
                VALUES (?, ?, ?, ?, ?, 'selected_gp_names', ?)
                """,
                (
                    notice_id,
                    lp_code,
                    getattr(alias, "gp_id"),
                    getattr(alias, "canonical_name"),
                    getattr(alias, "alias_name"),
                    link_confidence,
                ),
            )
            gp_links += 1

    news_links = 0
    if table_exists(conn, "news_document"):
        cursor = conn.execute(
            """
            SELECT lcn.notice_id, nd.news_id, lcn.lp_code
            FROM lp_commitment_notice lcn
            JOIN news_document nd
              ON nd.normalized_source_url = lcn.normalized_notice_url
            WHERE lcn.source_type = 'news'
              AND lcn.public_visible = 1
            """
        )
        for notice_id, news_id, lp_code in cursor.fetchall():
            conn.execute(
                """
                INSERT OR IGNORE INTO lp_notice_news_link (
                    notice_id, news_id, lp_code, link_source, confidence
                )
                VALUES (?, ?, ?, 'url_match', 'high')
                """,
                (notice_id, news_id, lp_code),
            )
            news_links += 1

    conn.commit()
    return gp_links, news_links


def export_monitor(conn: sqlite3.Connection, out_dir: Path, report_date: str) -> tuple[Path, Path, int]:
    cursor = conn.execute(
        """
        SELECT
            notice_id,
            lp_code,
            lp_name,
            lp_type,
            default_team,
            source_code,
            source_type,
            event_type,
            event_date,
            title,
            notice_url,
            document_url,
            attachment_names,
            attachment_urls,
            program_name,
            round_name,
            announced_date,
            notice_year,
            application_deadline,
            notice_stage,
            asset_class,
            strategy,
            program_size_krw_100mn,
            allocation_amount_krw_100mn,
            amount_type,
            amount_confidence,
            commitment_amount_krw_100mn,
            selected_gp_names,
            confidence,
            confidence_note,
            public_visible,
            monitor_status,
            raw_excerpt,
            discovered_at,
            updated_at
        FROM v_lp_commitment_notice_public
        ORDER BY
            CASE event_type
                WHEN 'new_notice' THEN 0
                WHEN 'deadline_soon' THEN 1
                WHEN 'final_selection' THEN 2
                WHEN 'shortlist' THEN 3
                WHEN 'revision' THEN 4
                WHEN 'cancellation' THEN 5
                WHEN 'performance_update' THEN 6
                ELSE 9
            END,
            COALESCE(event_date, announced_date, discovered_at) DESC,
            notice_id DESC
        LIMIT 500
        """
    )
    headers = [desc[0] for desc in cursor.description]
    rows = [dict(zip(headers, row)) for row in cursor.fetchall()]
    dated_path = out_dir / f"lp_commitment_monitor_{report_date.replace('-', '')}.csv"
    latest_path = out_dir / "lp_commitment_monitor_latest.csv"
    write_csv_rows(dated_path, rows, headers)
    write_csv_rows(latest_path, rows, headers)
    return dated_path, latest_path, len(rows)


def build(
    db_path: Path,
    schema_path: Path,
    institutions_path: Path,
    profile_facts_path: Path,
    sources_path: Path,
    reviewed_events_path: Path,
    out_dir: Path,
    report_date: str,
    days: int,
    limit_per_source: int,
    allow_insecure_ssl: bool,
    skip_source_fetch: bool,
    gp_alias_overrides: Path,
) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    try:
        apply_schema(conn, schema_path)
        lp_rows = seed_lp_institutions(conn, institutions_path)
        profile_fact_rows = seed_lp_profile_facts(conn, profile_facts_path)
        source_rows = seed_lp_sources(conn, sources_path)
        report_date = report_date or latest_report_date(conn)
        fallback_year = int(report_date[:4])
        lp_aliases = load_lp_aliases(lp_rows)
        gp_aliases = load_gp_aliases(db_path, gp_alias_overrides)
        official_rows = [] if skip_source_fetch else load_official_candidates(
            source_rows,
            lp_aliases,
            fallback_year,
            report_date,
            limit_per_source,
            allow_insecure_ssl,
            gp_aliases,
        )
        news_rows = load_news_candidates(conn, lp_aliases, fallback_year, report_date, days, gp_aliases)
        reviewed_rows = load_reviewed_candidates(reviewed_events_path, fallback_year, report_date)
        candidates = dedupe_candidates(official_rows + news_rows + reviewed_rows)
        cleared = clear_auto_candidates(conn)
        upserted = upsert_notices(conn, candidates)
        gp_links, news_links = refresh_notice_links(conn, gp_aliases)
        dated_path, latest_path, exported = export_monitor(conn, out_dir, report_date)
    finally:
        conn.close()
    return {
        "report_date": report_date,
        "lp_institutions": len(lp_rows),
        "lp_profile_facts": len(profile_fact_rows),
        "lp_sources": len(source_rows) + 1,
        "official_candidates": len(official_rows),
        "news_candidates": len(news_rows),
        "reviewed_candidates": len(reviewed_rows),
        "cleared_auto_candidates": cleared,
        "upserted": upserted,
        "gp_links": gp_links,
        "news_links": news_links,
        "exported": exported,
        "dated_export": str(dated_path),
        "latest_export": str(latest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LP commitment notice monitor")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--lp-institutions", type=Path, default=DEFAULT_LP_INSTITUTIONS)
    parser.add_argument("--lp-profile-facts", type=Path, default=DEFAULT_LP_PROFILE_FACTS)
    parser.add_argument("--lp-sources", type=Path, default=DEFAULT_LP_SOURCES)
    parser.add_argument("--lp-reviewed-events", type=Path, default=DEFAULT_LP_REVIEWED_EVENTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--date", default="")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--limit-per-source", type=int, default=50)
    parser.add_argument("--allow-insecure-ssl", action="store_true")
    parser.add_argument("--skip-source-fetch", action="store_true")
    parser.add_argument("--gp-alias-overrides", type=Path, default=DEFAULT_GP_ALIAS_OVERRIDES)
    args = parser.parse_args()

    result = build(
        args.db,
        args.schema,
        args.lp_institutions,
        args.lp_profile_facts,
        args.lp_sources,
        args.lp_reviewed_events,
        args.out_dir,
        args.date,
        args.days,
        args.limit_per_source,
        args.allow_insecure_ssl,
        args.skip_source_fetch,
        args.gp_alias_overrides,
    )
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
