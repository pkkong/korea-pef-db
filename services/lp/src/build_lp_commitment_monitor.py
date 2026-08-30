#!/usr/bin/env python
"""Build the LP commitment notice monitor from official notices and news clips."""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import ssl
import sqlite3
import struct
import sys
import zipfile
import zlib
from http.cookiejar import CookieJar
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlencode, unquote_plus, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener, urlopen
from urllib.error import HTTPError

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.shared.src.daily_news_common import (
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
from services.lp.src.lp_notice_identity import (
    GENERIC_PROGRAM_NAMES,
    _normalize_program_name_text,
    _notice_platform_name,
    _notice_program_specificity,
    _notice_specific_map_key,
    clean_program_candidate,
    infer_notice_program_name,
    infer_notice_round_name,
    infer_program_name,
    infer_round_name,
    infer_round_name_with_fallback,
    is_generic_program_name,
    normalize_round_name,
    notice_business_key,
    program_candidates,
)


DEFAULT_SCHEMA = REPO_ROOT / "schema" / "lp_commitments.sql"
DEFAULT_LP_INSTITUTIONS = REPO_ROOT / "data" / "lp_institutions.csv"
DEFAULT_LP_PROFILE_FACTS = REPO_ROOT / "data" / "lp_profile_facts.csv"
DEFAULT_LP_SOURCES = REPO_ROOT / "data" / "lp_commitment_sources.csv"
DEFAULT_LP_REVIEWED_EVENTS = REPO_ROOT / "data" / "lp_reviewed_events.csv"
DEFAULT_LP_SELECTED_GP_EXCLUSIONS = REPO_ROOT / "data" / "lp_selected_gp_non_gp_exclusions.csv"
DEFAULT_OUT_DIR = REPO_ROOT / "exports"
NEWS_FEED_SOURCE_CODE = "daily_news_lp_feed"
VCS_BACKFILL_PAGE_SIZE = 500
NOTICE_TERMS = [
    "출자사업",
    "출자 공고",
    "출자전",
    "출자 규모",
    "위탁운용",
    "위탁운용사",
    "주간운용사",
    "OCIO",
    "외부위탁운용관리",
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
    "고용보험기금",
    "산재보험기금",
    "장애인고용촉진및직업재활기금",
    "임금채권보장기금",
    "예금보험기금",
    "주택금융신용보증기금",
    "정보통신진흥기금",
    "방송통신발전기금",
    "전력산업기반기금",
    "연기금투자풀",
    "주간운용사",
    "OCIO",
]

COMBINED_AMOUNT_RE = re.compile(r"\[?(?P<jo>\d[\d,]*(?:\.\d+)?)\]?\s*조(?:\s*\[?(?P<eok>\d[\d,]*)\]?\s*억?|원)?(?![가-힣])", re.IGNORECASE)
AMOUNT_RE = re.compile(r"\[?(?P<num>\d[\d,]*(?:\.\d+)?)\]?\s*(?P<unit>조\s*원|조원|억원|억|조(?![가-힣]))", re.IGNORECASE)
DATE_RE = re.compile(r"(?P<year>20\d{2})[.\-/년]\s*(?P<month>\d{1,2})[.\-/월]\s*(?P<day>\d{1,2})")
SHORT_DATE_RE = re.compile(r"(?<!\d)[`'‘’]?(?P<year>\d{2})[.\-/년]\s*(?P<month>\d{1,2})[.\-/월]\s*(?P<day>\d{1,2})")
DATE_TOKEN_RE = r"(?:20\d{2}|[`'‘’]?\d{2})[.\-/년]\s*\d{1,2}[.\-/월]\s*\d{1,2}"
PARTIAL_DATE_TOKEN_RE = r"\d{1,2}[.\-/월]\s*\d{1,2}"
FILE_EXT_RE = re.compile(r"\.(pdf|hwp|hwpx|docx?|xlsx?|pptx?|zip)($|[?#&])", re.IGNORECASE)
MONEY_CONTEXT_WINDOW = 44
LP_NOTICE_COMPARISON_START_DATE = "2024-01-01"
OFFICIAL_DETAIL_TEXT_LIMIT = 30000
OFFICIAL_GP_MATCH_TEXT_LIMIT = 12000
ATTACHMENT_TEXT_LIMIT = 20000
ATTACHMENT_FETCH_LIMIT = 2
ATTACHMENT_MAX_BYTES = 8 * 1024 * 1024
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
    "운용규모",
    "자산규모",
    "자산 규모",
    "트랙레코드",
]
FUND_TARGET_AMOUNT_HINTS = [
    "결성목표액",
    "결성 목표액",
    "목표결성",
    "목표 결성",
    "결성규모",
    "결성 규모",
    "최소결성",
    "최소 결성",
]
NON_COMMITMENT_NOTICE_TERMS = [
    "온라인마케팅",
    "참여기업 모집",
    "회계감사인",
    "논문",
    "투자유치",
    "크라우드펀딩",
    "부킹 이벤트",
    "회원 대상",
    "공정가치 평가",
    "투자성과 모니터링",
    "회계감사",
    "평가 대행",
    "정량평가 대행",
    "실사 위탁",
    "평가기관",
    "외부 평가기관",
    "제안요청서 작성",
]
PROCUREMENT_SERVICE_TERMS = [
    "컨설팅",
    "내부통제",
    "데이터 관리",
    "생성형 ai",
    "휴양소",
    "온비드",
    "부동산",
    "유가증권 매각",
    "인수자 지정",
    "평가",
    "실사",
    "모니터링",
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


def load_selected_gp_exclusion_names(path: Path = DEFAULT_LP_SELECTED_GP_EXCLUSIONS) -> set[str]:
    if not path.exists():
        return set()
    names: set[str] = set()
    for row in read_csv_rows(path):
        token = normalize_whitespace(row.get("token", ""))
        if token:
            names.add(token)
    return names


GP_EXCLUSION_NAMES.update(load_selected_gp_exclusion_names())

GP_NAME_SUFFIXES = [
    "자산운용",
    "인베스트먼트파트너스",
    "인베스트먼트",
    "프라이빗에쿼티",
    "에쿼티파트너스",
    "투자운용",
    "그린인베스트먼트",
    "벤처투자",
    "기술투자",
    "창업투자",
    "벤처스코리아",
    "벤처스",
    "캐피탈",
    "파트너즈",
    "파트너스",
    "홀딩스",
]
RAW_GP_EXPLICIT_NAMES = [
    "에이티넘",
    "파트너스현",
    "엑스퀘어드",
    "리인베스트먼트",
    "아주IB투자",
    "아주IB",
]
RAW_GP_DISPLAY_ALIASES = {
    "아주IB투자": "아주아이비투자",
    "아주IB": "아주아이비투자",
    "KB자산운용": "케이비자산운용",
}
RAW_GP_NAME_RE = re.compile(
    r"(?P<name>[가-힣A-Za-z0-9&·]{2,34}(?:"
    + "|".join(re.escape(suffix) for suffix in GP_NAME_SUFFIXES)
    + r"))"
)


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
        ensure_lp_institution_columns(conn)
        ensure_lp_notice_columns(conn)
        ensure_lp_link_tables_are_local(conn)
        conn.executescript(marker + index_and_view_sql)
    else:
        conn.executescript(schema_sql)
    ensure_lp_institution_columns(conn)
    ensure_lp_notice_columns(conn)
    ensure_lp_link_tables_are_local(conn)
    conn.commit()


def ensure_lp_institution_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(lp_institution)").fetchall()
    }
    columns = {
        "legal_lp_category": "TEXT",
        "legal_lp_basis": "TEXT",
        "coverage_tier": "TEXT NOT NULL DEFAULT 'candidate'",
        "display_enabled": "INTEGER NOT NULL DEFAULT 1",
        "notice_tracking_enabled": "INTEGER NOT NULL DEFAULT 0",
        "profile_status": "TEXT NOT NULL DEFAULT 'candidate'",
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE lp_institution ADD COLUMN {name} {definition}")


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


def ensure_lp_link_tables_are_local(conn: sqlite3.Connection) -> None:
    """Remove legacy cross-service foreign keys from an LP-only build database."""
    migrations = (
        (
            "lp_notice_gp_link",
            "idx_lp_notice_gp_link_lp",
            """
            CREATE TABLE lp_notice_gp_link (
                notice_id INTEGER NOT NULL,
                lp_code TEXT,
                source_gp_id INTEGER NOT NULL,
                gp_name TEXT NOT NULL,
                matched_alias TEXT,
                link_source TEXT NOT NULL DEFAULT 'selected_gp_names',
                confidence TEXT NOT NULL DEFAULT 'medium',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (notice_id, source_gp_id),
                FOREIGN KEY (notice_id) REFERENCES lp_commitment_notice(notice_id) ON DELETE CASCADE,
                FOREIGN KEY (lp_code) REFERENCES lp_institution(lp_code)
            )
            """,
        ),
        (
            "lp_notice_news_link",
            "idx_lp_notice_news_link_lp",
            """
            CREATE TABLE lp_notice_news_link (
                notice_id INTEGER NOT NULL,
                news_id INTEGER NOT NULL,
                lp_code TEXT,
                link_source TEXT NOT NULL DEFAULT 'url_match',
                confidence TEXT NOT NULL DEFAULT 'high',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (notice_id, news_id),
                FOREIGN KEY (notice_id) REFERENCES lp_commitment_notice(notice_id) ON DELETE CASCADE,
                FOREIGN KEY (lp_code) REFERENCES lp_institution(lp_code)
            )
            """,
        ),
    )
    for table_name, index_name, create_sql in migrations:
        foreign_tables = {
            str(row[2])
            for row in conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
        }
        if not ({"gp_house", "news_document"} & foreign_tables):
            continue
        legacy_name = f"{table_name}_legacy_external_fk"
        conn.execute(f"DROP INDEX IF EXISTS {index_name}")
        conn.execute(f"ALTER TABLE {table_name} RENAME TO {legacy_name}")
        conn.execute(create_sql)
        columns = [
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        ]
        column_list = ", ".join(columns)
        conn.execute(
            f"INSERT INTO {table_name} ({column_list}) "
            f"SELECT {column_list} FROM {legacy_name}"
        )
        conn.execute(f"DROP TABLE {legacy_name}")


def seed_lp_institutions(conn: sqlite3.Connection, path: Path) -> list[dict[str, str]]:
    rows = read_csv_rows(path)
    source_lp_codes = sorted({str(row.get("lp_code") or "").strip() for row in rows if str(row.get("lp_code") or "").strip()})
    headers = [
        "lp_code",
        "lp_name",
        "lp_name_en",
        "lp_type",
        "legal_lp_category",
        "legal_lp_basis",
        "ownership_type",
        "homepage_url",
        "notice_url",
        "default_team",
        "focus_asset_classes",
        "service_priority",
        "coverage_tier",
        "display_enabled",
        "notice_tracking_enabled",
        "profile_status",
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
                legal_lp_category = excluded.legal_lp_category,
                legal_lp_basis = excluded.legal_lp_basis,
                ownership_type = excluded.ownership_type,
                homepage_url = excluded.homepage_url,
                notice_url = excluded.notice_url,
                default_team = excluded.default_team,
                focus_asset_classes = excluded.focus_asset_classes,
                service_priority = excluded.service_priority,
                coverage_tier = excluded.coverage_tier,
                display_enabled = excluded.display_enabled,
                notice_tracking_enabled = excluded.notice_tracking_enabled,
                profile_status = excluded.profile_status,
                aliases = excluded.aliases,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            [row.get(header, "") for header in headers] + [now_utc_iso()],
        )
    if source_lp_codes:
        placeholders = ", ".join("?" for _ in source_lp_codes)
        conn.execute(
            f"""
            DELETE FROM lp_institution
            WHERE lp_code NOT IN ({placeholders})
              AND NOT EXISTS (
                  SELECT 1 FROM lp_profile_fact f
                  WHERE f.lp_code = lp_institution.lp_code
              )
              AND NOT EXISTS (
                  SELECT 1 FROM lp_commitment_source s
                  WHERE s.lp_code = lp_institution.lp_code
              )
              AND NOT EXISTS (
                  SELECT 1 FROM lp_commitment_notice n
                  WHERE n.lp_code = lp_institution.lp_code
              )
              AND NOT EXISTS (
                  SELECT 1 FROM lp_notice_gp_link g
                  WHERE g.lp_code = lp_institution.lp_code
              )
              AND NOT EXISTS (
                  SELECT 1 FROM lp_notice_news_link nl
                  WHERE nl.lp_code = lp_institution.lp_code
              )
            """,
            source_lp_codes,
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
    if any(term in value for term in ["숏리스트", "shortlist", "1차 선정", "2라운드", "본선", "서류심사 결과", "정량평가 결과", "제안서 발표대상", "발표대상", "적격", "합격"]):
        return "shortlist"
    if (
        any(term in value for term in ["lp rader", "팀장", "겸임", "조직", "인사"])
        and not any(term in value for term in ["공고", "선정", "마감", "숏리스트"])
    ):
        return "candidate"
    if any(term in value for term in ["설명회", "사업설명회", "제안설명"]):
        return "briefing"
    if any(term in value for term in ["접수", "접수현황", "마감", "제안서", "서류제출"]):
        return "application"
    if (
        any(term in value for term in ["회수", "분배금", "dpi", "moic", "청산"])
        and not any(term in value for term in ["공고", "선정계획", "위탁운용사", "출자사업"])
    ):
        return "performance_update"
    if any(term in value for term in ["공고", "모집", "공모", "선정계획", "출자사업", "위탁운용사", "운용사 선정"]):
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


def amount_context(text: str, start: int, end: int, window: int = MONEY_CONTEXT_WINDOW) -> str:
    left = max(0, start - window)
    right = min(len(text), end + window)
    return text[left:right]


def is_non_commitment_amount_context(context: str) -> bool:
    ctx = context.lower()
    if any(hint.lower() in ctx for hint in NON_COMMITMENT_AMOUNT_HINTS):
        return True
    return ("미만" in ctx or "이상" in ctx) and any(hint in ctx for hint in ["aum", "운용", "자산", "트랙레코드"])


def is_fund_target_amount_context(context: str) -> bool:
    ctx = context.lower()
    return any(hint.lower() in ctx for hint in FUND_TARGET_AMOUNT_HINTS)


def is_law_article_amount(text: str, start: int) -> bool:
    return bool(re.search(r"제\s*$", text[max(0, start - 3) : start]))


def classify_amounts(text: str) -> dict[str, object]:
    cleaned = re.sub(r"\[[^\]]*국민성장펀드[^\]]*\]", " ", text or "")
    amount_rows: list[dict[str, object]] = []
    for match in COMBINED_AMOUNT_RE.finditer(text):
        if is_law_article_amount(text, match.start()):
            continue
        jo = parse_number(match.group("jo"))
        eok = parse_number(match.group("eok") or "0")
        if jo:
            ctx = amount_context(text, match.start(), match.end())
            near_ctx = amount_context(text, match.start(), match.end(), window=18)
            left_ctx = text[max(0, match.start() - 18) : match.start()]
            amount_rows.append({"amount": (jo * 10000) + eok, "context": ctx, "near_context": near_ctx, "left_context": left_ctx, "raw": match.group(0)})
    for match in AMOUNT_RE.finditer(cleaned):
        if is_law_article_amount(cleaned, match.start()):
            continue
        amount = parse_number(match.group("num"))
        unit = match.group("unit")
        if not amount:
            continue
        ctx = amount_context(cleaned, match.start(), match.end())
        near_ctx = amount_context(cleaned, match.start(), match.end(), window=18)
        left_ctx = cleaned[max(0, match.start() - 18) : match.start()]
        amount_rows.append({"amount": amount_to_krw_100mn(amount, unit), "context": ctx, "near_context": near_ctx, "left_context": left_ctx, "raw": match.group(0)})
    program_amounts: list[float] = []
    allocation_amounts: list[float] = []
    fallback_amounts: list[float] = []
    for row in amount_rows:
        ctx = str(row["context"]).lower()
        near_ctx = str(row.get("near_context") or row["context"]).lower()
        left_ctx = str(row.get("left_context") or "").lower()
        amount = float(row["amount"])
        if is_non_commitment_amount_context(near_ctx):
            continue
        if is_fund_target_amount_context(left_ctx):
            continue
        allocation_near = any(hint.lower() in near_ctx for hint in ALLOCATION_HINTS)
        if is_fund_target_amount_context(near_ctx) and not allocation_near:
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
    lowered = title.lower()
    if any(term.lower() in lowered for term in NON_COMMITMENT_NOTICE_TERMS):
        return True
    if any(term.lower() in lowered for term in ["용역", "대행", "사업자 선정"]):
        if not any(term.lower() in lowered for term in ["ocio", "외부위탁운용관리", "주간운용사"]):
            return any(term.lower() in lowered for term in PROCUREMENT_SERVICE_TERMS)
    return False


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
    value = value.replace("`", "'").replace("‘", "'").replace("’", "'")
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
    short_match = SHORT_DATE_RE.search(value)
    if short_match:
        short_year = int(short_match.group("year"))
        year = 2000 + short_year
        month = int(short_match.group("month"))
        day = int(short_match.group("day"))
        if 2020 <= year <= 2035:
            try:
                return datetime(year, month, day).date().isoformat()
            except ValueError:
                return ""
    return value[:10] if re.match(r"^20\d{2}-\d{2}-\d{2}", value) else ""


def normalize_partial_date(value: str, fallback_year: int | None) -> str:
    normalized = normalize_date(value)
    if normalized:
        return normalized
    if not fallback_year:
        return ""
    match = re.search(r"(?P<month>\d{1,2})[.\-/월]\s*(?P<day>\d{1,2})", str(value or ""))
    if not match:
        return ""
    try:
        return datetime(fallback_year, int(match.group("month")), int(match.group("day"))).date().isoformat()
    except ValueError:
        return ""


def infer_text_year(text: str) -> int | None:
    years = [int(year) for year in re.findall(r"20\d{2}", text or "")]
    years = [year for year in years if 2020 <= year <= 2035]
    return years[0] if years else None


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
    date_token = DATE_TOKEN_RE
    partial_date_token = PARTIAL_DATE_TOKEN_RE
    for pattern in [
        rf"(?:접수기간|접수\s*기간|신청기간|신청\s*기간|제출기간|제출\s*기간|제안서\s*접수)[^0-9`'‘’]{{0,40}}(?P<start>{date_token})[^~∼\-–—]{{0,40}}[~∼\-–—][^0-9`'‘’]{{0,30}}(?P<end>{date_token}|{partial_date_token})",
        rf"(?P<start>{date_token})[^~∼\-–—]{{0,40}}[~∼\-–—][^0-9`'‘’]{{0,30}}(?P<end>{date_token}|{partial_date_token})[^0-9]{{0,30}}(?:까지|마감|접수|제출)",
    ]:
        match = re.search(pattern, text)
        if not match:
            continue
        start_date = normalize_date(match.group("start"))
        fallback_year = int(start_date[:4]) if start_date else infer_text_year(text)
        end_date = normalize_partial_date(match.group("end"), fallback_year)
        if end_date:
            return end_date
    for pattern in [
        rf"(?:접수마감|접수기한|제출기한|신청기한|서류\s*제출|제안서\s*접수|온라인\s*신청|접수|제출|신청|마감)[^0-9`'‘’]{{0,30}}({date_token})",
        rf"({date_token})[^0-9]{{0,30}}(?:까지|마감|접수|제출)",
    ]:
        match = re.search(pattern, text)
        if match:
            return normalize_date(match.group(1))
    return ""


def extract_announcement_date(text: str) -> str:
    date_token = DATE_TOKEN_RE
    for pattern in [
        rf"(?:공고일|게시일|등록일|작성일)[^0-9`'‘’]{{0,20}}({date_token})",
        rf"({date_token})[^0-9]{{0,20}}(?:공고|게시|등록)",
        rf"({date_token})[^0-9]{{0,20}}(?:작성자|조회수)",
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
        absolute = urljoin(base_url, html.unescape(href.strip()))
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

    for item in re.findall(r"<li\b[^>]*>.*?</li>", html_text, flags=re.IGNORECASE | re.DOTALL):
        call_match = re.search(
            r"fn_egov_downFile\(\s*['\"](?P<atch>[^'\"]+)['\"]\s*,\s*['\"](?P<sn>[^'\"]+)['\"]\s*\)",
            item,
            flags=re.IGNORECASE,
        )
        if not call_match:
            continue
        label = strip_html_tags(item)
        label = re.sub(r"\[[^\]]*KByte\]", "", label, flags=re.IGNORECASE)
        label = normalize_whitespace(label.replace("다운로드", ""))
        href = "/ebz/cmm/fms/FileDown.do?" + urlencode(
            {
                "atchFileId": call_match.group("atch"),
                "fileSn": call_match.group("sn"),
            }
        )
        add_attachment(label, href)

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


def attachment_kind(name: str, url: str, content_type: str, raw_bytes: bytes = b"") -> str:
    haystack = f"{name} {url} {content_type}".lower()
    if raw_bytes.startswith(b"%PDF") or ".pdf" in haystack or "application/pdf" in haystack:
        return "pdf"
    if raw_bytes.startswith(b"PK\x03\x04") and (".hwpx" in haystack or ".docx" in haystack):
        return "hwpx"
    if raw_bytes.startswith(b"HWP Document File") or raw_bytes.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") or ".hwp" in haystack:
        return "hwp"
    return ""


def is_text_extractable_attachment(name: str, url: str) -> bool:
    haystack = f"{name} {url}".lower()
    return any(token in haystack for token in [".pdf", ".hwp", ".hwpx", "fileview", "filedown"])


def should_extract_attachment_text(stage: str, title: str, attachments: list[dict[str, str]]) -> bool:
    if not attachments:
        return False
    text = f"{title} {' '.join(str(item.get('name') or '') for item in attachments)}"
    if stage in {"selection_result", "shortlist"}:
        return any(token in text for token in ["선정", "결과", "서류심사", "숏리스트", "위탁운용사"])
    if stage in {"notice", "application", "briefing"}:
        return any(
            token in text
            for token in [
                "공고",
                "공모",
                "모집",
                "선정계획",
                "출자사업",
                "위탁운용사",
                "제안요청서",
                "제안서",
                "사업계획서",
            ]
        )
    return False


def attachment_priority(item: dict[str, str]) -> tuple[int, int, str]:
    name = str(item.get("name") or "")
    url = str(item.get("url") or "")
    haystack = f"{name} {url}"
    result_score = 0
    if any(token in haystack for token in ["선정 결과", "선정결과", "서류심사", "숏리스트", "우선협상"]):
        result_score = 3
    elif any(token in haystack for token in ["선정", "결과"]):
        result_score = 2
    elif any(token in haystack for token in ["공고", "선정계획"]):
        result_score = 1
    kind_score = 1 if is_text_extractable_attachment(name, url) else 0
    return result_score, kind_score, name


def extract_attachment_texts(attachments: list[dict[str, str]], allow_insecure_ssl: bool) -> str:
    values: list[str] = []
    seen: set[str] = set()
    candidates = sorted(attachments, key=attachment_priority, reverse=True)
    for item in candidates:
        if len(values) >= ATTACHMENT_FETCH_LIMIT:
            break
        name = str(item.get("name") or "")
        url = str(item.get("url") or "")
        if not url or url in seen or not is_text_extractable_attachment(name, url):
            continue
        seen.add(url)
        try:
            fetched = fetch_text(url, timeout=20, verify_ssl=not allow_insecure_ssl)
        except Exception as exc:
            print(f"warning: attachment_fetch_failed url={url} error={exc}")
            continue
        raw_bytes = bytes(fetched.get("raw_bytes") or b"")
        if not raw_bytes or len(raw_bytes) > ATTACHMENT_MAX_BYTES:
            continue
        kind = attachment_kind(name, str(fetched.get("final_url") or url), str(fetched.get("content_type") or ""), raw_bytes)
        text = extract_attachment_text(raw_bytes, kind)
        text = normalize_whitespace(text)
        if text:
            values.append(text[:ATTACHMENT_TEXT_LIMIT])
    return normalize_whitespace(" ".join(values))[:ATTACHMENT_TEXT_LIMIT]


def extract_attachment_text(raw_bytes: bytes, kind: str) -> str:
    if kind == "pdf":
        return extract_pdf_text(raw_bytes)
    if kind == "hwpx":
        return extract_hwpx_text(raw_bytes)
    if kind == "hwp":
        return extract_hwp_text(raw_bytes)
    return ""


def extract_pdf_text(raw_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(raw_bytes))
        text = " ".join(page.extract_text() or "" for page in reader.pages)
        if text:
            return text
    except Exception:
        pass
    return extract_pdf_text_fallback(raw_bytes)


def pdf_objects(raw_bytes: bytes) -> dict[int, bytes]:
    return {
        int(match.group(1)): match.group(2)
        for match in re.finditer(rb"(\d+)\s+0\s+obj\s*(.*?)\s*endobj", raw_bytes, flags=re.DOTALL)
    }


def pdf_stream_data(body: bytes) -> bytes:
    match = re.search(rb"stream\r?\n(.*?)\r?\nendstream", body, flags=re.DOTALL)
    if not match:
        return b""
    data = match.group(1)
    if b"/FlateDecode" in body:
        for window_bits in [15, -15]:
            try:
                return zlib.decompress(data, window_bits)
            except Exception:
                continue
    return data


def parse_pdf_cmap(stream: bytes) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if b"begincmap" not in stream:
        return mapping
    text = stream.decode("latin1", errors="ignore")
    for block in re.findall(r"beginbfchar\s*(.*?)\s*endbfchar", text, flags=re.DOTALL):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            if dst.lower() == "ffff":
                continue
            try:
                mapping[src.lower()] = "".join(chr(int(dst[index : index + 4], 16)) for index in range(0, len(dst), 4))
            except ValueError:
                continue
    for block in re.findall(r"beginbfrange\s*(.*?)\s*endbfrange", text, flags=re.DOTALL):
        for start, end, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            try:
                start_int = int(start, 16)
                end_int = int(end, 16)
                dst_int = int(dst, 16)
            except ValueError:
                continue
            width = len(start)
            for offset, code in enumerate(range(start_int, end_int + 1)):
                mapping[f"{code:0{width}x}"] = chr(dst_int + offset)
    return mapping


def decode_pdf_hex_text(hex_text: str, mapping: dict[str, str]) -> str:
    value = re.sub(r"\s+", "", hex_text).lower()
    if not value:
        return ""
    token_lengths = sorted({len(key) for key in mapping}, reverse=True) or [4, 2]
    output: list[str] = []
    index = 0
    while index < len(value):
        for token_length in token_lengths:
            token = value[index : index + token_length]
            if token in mapping:
                output.append(mapping[token])
                index += token_length
                break
        else:
            token = value[index : index + 2]
            try:
                codepoint = int(token, 16)
                if 32 <= codepoint < 127:
                    output.append(chr(codepoint))
            except ValueError:
                pass
            index += 2
    return "".join(output)


def extract_pdf_text_fallback(raw_bytes: bytes) -> str:
    objects = pdf_objects(raw_bytes)
    font_object_by_name: dict[str, int] = {}
    for body in objects.values():
        for name, object_number in re.findall(rb"/([A-Za-z][A-Za-z0-9]+)\s+(\d+)\s+0\s+R", body):
            if name.startswith((b"F", b"T")):
                font_object_by_name[name.decode("latin1")] = int(object_number)
    font_maps: dict[str, dict[str, str]] = {}
    for name, object_number in font_object_by_name.items():
        body = objects.get(object_number, b"")
        match = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", body)
        if not match:
            continue
        cmap_stream = pdf_stream_data(objects.get(int(match.group(1)), b""))
        font_maps[name] = parse_pdf_cmap(cmap_stream)

    chunks: list[str] = []
    token_re = re.compile(
        r"/([A-Za-z][A-Za-z0-9]+)\s+[0-9.]+\s+Tf|\[(.*?)\]\s*TJ|<([0-9A-Fa-f\s]+)>\s*Tj",
        flags=re.DOTALL,
    )
    for _, body in sorted(objects.items()):
        stream = pdf_stream_data(body)
        if not stream or b"BT" not in stream:
            continue
        content = stream.decode("latin1", errors="ignore")
        current_font = ""
        for match in token_re.finditer(content):
            if match.group(1):
                current_font = match.group(1)
                continue
            mapping = font_maps.get(current_font, {})
            if match.group(2) is not None:
                text = "".join(
                    decode_pdf_hex_text(hex_value, mapping)
                    for hex_value in re.findall(r"<([0-9A-Fa-f\s]+)>", match.group(2))
                )
            else:
                text = decode_pdf_hex_text(match.group(3) or "", mapping)
            if text:
                chunks.append(text)
    return normalize_whitespace(" ".join(chunks))


def extract_hwpx_text(raw_bytes: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
            texts: list[str] = []
            for name in sorted(archive.namelist()):
                lower = name.lower()
                if not lower.endswith(".xml") or not any(token in lower for token in ["section", "contents", "body"]):
                    continue
                payload = archive.read(name).decode("utf-8", errors="ignore")
                payload = re.sub(r"<[^>]+>", " ", payload)
                texts.append(html.unescape(payload))
            return normalize_whitespace(" ".join(texts))
    except Exception:
        return ""


def extract_hwp_text(raw_bytes: bytes) -> str:
    try:
        from olefile import OleFileIO  # type: ignore

        ole = OleFileIO(io.BytesIO(raw_bytes))
        try:
            header = ole.openstream("FileHeader").read()
            compressed = len(header) >= 40 and bool(struct.unpack_from("<I", header, 36)[0] & 1)
            texts: list[str] = []
            section_names = sorted("/".join(item) for item in ole.listdir() if len(item) == 2 and item[0] == "BodyText")
            for name in section_names:
                data = ole.openstream(name).read()
                if compressed:
                    data = zlib.decompress(data, -15)
                texts.append(extract_hwp_body_text(data))
            return normalize_whitespace(" ".join(texts))
        finally:
            ole.close()
    except Exception:
        pass
    try:
        reader = CompoundFileReader(raw_bytes)
        header = reader.read_stream("FileHeader")
        compressed = len(header) >= 40 and bool(struct.unpack_from("<I", header, 36)[0] & 1)
        texts = []
        for name in reader.stream_names():
            if not re.fullmatch(r"Section\d+", name):
                continue
            data = reader.read_stream(name)
            if compressed:
                data = zlib.decompress(data, -15)
            texts.append(extract_hwp_body_text(data))
        return normalize_whitespace(" ".join(texts))
    except Exception:
        return ""


def extract_hwp_body_text(data: bytes) -> str:
    position = 0
    texts: list[str] = []
    while position + 4 <= len(data):
        record_header = struct.unpack_from("<I", data, position)[0]
        position += 4
        tag = record_header & 0x3FF
        size = (record_header >> 20) & 0xFFF
        if size == 0xFFF:
            if position + 4 > len(data):
                break
            size = struct.unpack_from("<I", data, position)[0]
            position += 4
        payload = data[position : position + size]
        position += size
        if tag == 67:
            text = payload.decode("utf-16le", errors="ignore")
            text = "".join(char if char in {"\n", "\t"} or ord(char) >= 32 else " " for char in text)
            texts.append(text)
    return " ".join(texts)


class CompoundFileReader:
    END_OF_CHAIN = 0xFFFFFFFE
    FREE_SECTOR = 0xFFFFFFFF
    FAT_SECTOR = 0xFFFFFFFD
    DIFAT_SECTOR = 0xFFFFFFFC

    def __init__(self, data: bytes):
        if not data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise ValueError("not a compound file")
        self.data = data
        self.sector_size = 1 << struct.unpack_from("<H", data, 30)[0]
        self.mini_sector_size = 1 << struct.unpack_from("<H", data, 32)[0]
        self.first_dir_sector = struct.unpack_from("<I", data, 48)[0]
        self.mini_stream_cutoff = struct.unpack_from("<I", data, 56)[0]
        self.first_mini_fat_sector = struct.unpack_from("<I", data, 60)[0]
        self.num_mini_fat_sectors = struct.unpack_from("<I", data, 64)[0]
        first_difat_sector = struct.unpack_from("<I", data, 68)[0]
        num_difat_sectors = struct.unpack_from("<I", data, 72)[0]
        difat = [
            entry
            for entry in struct.unpack_from("<109I", data, 76)
            if entry not in {self.FREE_SECTOR, self.END_OF_CHAIN}
        ]
        sector = first_difat_sector
        for _ in range(num_difat_sectors):
            if sector in {self.FREE_SECTOR, self.END_OF_CHAIN}:
                break
            payload = self.read_sector(sector)
            entries = struct.unpack("<" + "I" * (self.sector_size // 4), payload)
            difat.extend(entry for entry in entries[:-1] if entry not in {self.FREE_SECTOR, self.END_OF_CHAIN})
            sector = entries[-1]
        self.fat: list[int] = []
        for sector_id in difat:
            payload = self.read_sector(sector_id)
            self.fat.extend(struct.unpack("<" + "I" * (self.sector_size // 4), payload))
        self.entries = self.read_directory()
        self.root_entry = next((entry for entry in self.entries if entry.get("type") == 5), None)
        self.mini_fat = self.read_mini_fat()
        self.mini_stream = self.read_regular_stream(int(self.root_entry.get("start", self.END_OF_CHAIN))) if self.root_entry else b""

    def read_sector(self, sector_id: int) -> bytes:
        offset = (sector_id + 1) * self.sector_size
        return self.data[offset : offset + self.sector_size]

    def sector_chain(self, start_sector: int) -> list[int]:
        chain: list[int] = []
        sector = start_sector
        seen: set[int] = set()
        while sector not in {self.END_OF_CHAIN, self.FREE_SECTOR} and sector < len(self.fat) and sector not in seen:
            seen.add(sector)
            chain.append(sector)
            sector = self.fat[sector]
        return chain

    def read_regular_stream(self, start_sector: int) -> bytes:
        return b"".join(self.read_sector(sector) for sector in self.sector_chain(start_sector))

    def read_directory(self) -> list[dict[str, object]]:
        stream = self.read_regular_stream(self.first_dir_sector)
        entries: list[dict[str, object]] = []
        for index in range(0, len(stream), 128):
            entry = stream[index : index + 128]
            if len(entry) < 128:
                continue
            name_length = struct.unpack_from("<H", entry, 64)[0]
            name = entry[: max(0, name_length - 2)].decode("utf-16le", errors="ignore")
            object_type = entry[66]
            if not name or object_type == 0:
                continue
            start_sector = struct.unpack_from("<I", entry, 116)[0]
            stream_size = struct.unpack_from("<Q", entry, 120)[0]
            entries.append({"name": name, "type": object_type, "start": start_sector, "size": stream_size})
        return entries

    def read_mini_fat(self) -> list[int]:
        if self.first_mini_fat_sector in {self.FREE_SECTOR, self.END_OF_CHAIN} or self.num_mini_fat_sectors == 0:
            return []
        stream = self.read_regular_stream(self.first_mini_fat_sector)
        return list(struct.unpack("<" + "I" * (len(stream) // 4), stream))

    def mini_sector_chain(self, start_sector: int) -> list[int]:
        chain: list[int] = []
        sector = start_sector
        seen: set[int] = set()
        while sector not in {self.END_OF_CHAIN, self.FREE_SECTOR} and sector < len(self.mini_fat) and sector not in seen:
            seen.add(sector)
            chain.append(sector)
            sector = self.mini_fat[sector]
        return chain

    def read_mini_stream(self, start_sector: int) -> bytes:
        chunks = []
        for sector in self.mini_sector_chain(start_sector):
            offset = sector * self.mini_sector_size
            chunks.append(self.mini_stream[offset : offset + self.mini_sector_size])
        return b"".join(chunks)

    def stream_names(self) -> list[str]:
        return [str(entry["name"]) for entry in self.entries if entry.get("type") == 2]

    def read_stream(self, name: str) -> bytes:
        entry = next((item for item in self.entries if item.get("name") == name and item.get("type") == 2), None)
        if entry is None:
            raise KeyError(name)
        size = int(entry.get("size") or 0)
        start = int(entry.get("start") or self.END_OF_CHAIN)
        if size < self.mini_stream_cutoff and self.mini_fat and self.mini_stream:
            return self.read_mini_stream(start)[:size]
        return self.read_regular_stream(start)[:size]


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


def fetch_kgrowth_detail(notice_url: str, referer_url: str, allow_insecure_ssl: bool) -> dict[str, object]:
    handlers: list[object] = [HTTPCookieProcessor(CookieJar())]
    if allow_insecure_ssl:
        handlers.append(HTTPSHandler(context=ssl._create_unverified_context()))
    opener = build_opener(*handlers)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
    }
    referer = referer_url or "https://www.kgrowth.or.kr/notice.asp?str_type=1&tab=1"
    opener.open(Request(referer, headers=headers), timeout=20).read()
    detail_headers = dict(headers)
    detail_headers["Referer"] = referer
    with opener.open(Request(notice_url, headers=detail_headers), timeout=20) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "euc-kr"
        html_text = raw.decode(charset, errors="replace")
        final_url = response.geturl() or notice_url
    if "비정상적인 접근" in html_text:
        return {}
    cleaned_html = re.sub(r"<script\b.*?</script>", " ", html_text, flags=re.IGNORECASE | re.DOTALL)
    return {
        "attachments": extract_official_attachments(final_url, html_text),
        "title": extract_official_detail_title(html_text),
        "text": strip_html_tags(cleaned_html),
    }


def fetch_kexim_detail(notice_url: str, allow_insecure_ssl: bool) -> dict[str, object]:
    try:
        fetched = fetch_cookie_redirect_text(
            notice_url,
            allow_insecure_ssl,
            referer="https://www.koreaexim.go.kr/HPHKBI039M01",
        )
    except Exception as exc:
        print(f"warning: kexim_detail_fetch_failed url={notice_url} error={exc}")
        return {}
    html_text = str(fetched.get("text") or "")
    final_url = str(fetched.get("final_url") or notice_url)
    cleaned_html = re.sub(r"<script\b.*?</script>", " ", html_text, flags=re.IGNORECASE | re.DOTALL)
    return {
        "attachments": extract_official_attachments(final_url, html_text),
        "title": extract_official_detail_title(html_text),
        "text": strip_html_tags(cleaned_html),
    }


def fetch_source_detail(source: dict[str, str], notice_url: str, allow_insecure_ssl: bool) -> dict[str, object]:
    if source.get("source_code") == "kgrowth_notice":
        try:
            return fetch_kgrowth_detail(notice_url, source.get("locator", ""), allow_insecure_ssl)
        except Exception as exc:
            print(f"warning: kgrowth_detail_fetch_failed url={notice_url} error={exc}")
            return {}
    if source.get("source_code") == "kexim_notice":
        return fetch_kexim_detail(notice_url, allow_insecure_ssl)
    return fetch_official_detail(notice_url, allow_insecure_ssl)


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
    if source_code == "kobc_notice":
        match = re.search(
            r"goTo\.view\(['\"]view['\"]\s*,\s*['\"](?P<bidx>\d+)['\"]\s*,\s*['\"](?P<ptidx>\d+)['\"]\s*,\s*['\"](?P<mid>[^'\"]+)['\"]\)",
            notice_url,
        )
        if match:
            return (
                "https://www.kobc.or.kr/ebz/kor/bbs/view.do"
                f"?mId={match.group('mid')}&bIdx={match.group('bidx')}&ptIdx={match.group('ptidx')}"
            )
    return notice_url


def make_html_page_link(source: dict[str, str], html_text: str, final_url: str) -> list[dict[str, str]]:
    title_match = re.search(r"<title\b[^>]*>(?P<title>.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    title = normalize_whitespace(source.get("source_name", "")) or (
        normalize_whitespace(strip_html_tags(title_match.group("title"))) if title_match else ""
    )
    return [
        {
            "title": title or source.get("source_name", "") or final_url,
            "link": final_url,
            "announced_date": "",
            "contact_team": "",
        }
    ]


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


def fetch_json_post_text(url: str, data: dict[str, object], referer: str, allow_insecure_ssl: bool) -> str:
    encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=encoded,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "ko,en-US;q=0.7,en;q=0.3",
            "Content-Type": "application/json;",
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


def fetch_cookie_redirect_text(url: str, allow_insecure_ssl: bool, referer: str = "") -> dict[str, str]:
    """Fetch pages from sites that require a same-URL cookie redirect handshake."""
    cookies: dict[str, str] = {}
    current_url = url
    headers_base = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
    }
    opener_handlers: list[object] = []
    if allow_insecure_ssl:
        opener_handlers.append(HTTPSHandler(context=ssl._create_unverified_context()))
    opener = build_opener(*opener_handlers)

    def store_cookie(set_cookie_value: str | None) -> None:
        if not set_cookie_value:
            return
        simple_cookie = SimpleCookie()
        try:
            simple_cookie.load(set_cookie_value)
        except Exception:
            return
        for key, morsel in simple_cookie.items():
            cookies[key] = morsel.value

    for _ in range(8):
        headers = dict(headers_base)
        if referer:
            headers["Referer"] = referer
        if cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
        request = Request(current_url, headers=headers)
        try:
            with opener.open(request, timeout=20) as response:
                store_cookie(response.headers.get("Set-Cookie"))
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return {
                    "text": raw.decode(charset, errors="replace"),
                    "final_url": response.geturl() or current_url,
                }
        except HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                raise
            store_cookie(exc.headers.get("Set-Cookie"))
            location = exc.headers.get("Location")
            if not location:
                raise
            referer = current_url
            current_url = urljoin(current_url, location)
            continue
    raise RuntimeError(f"too many cookie redirects: {url}")


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


def parse_vcs_investment_listing(source: dict[str, str], limit: int, allow_insecure_ssl: bool) -> list[dict[str, str]]:
    locator = source.get("locator", "")
    if not locator:
        return []
    parsed = urlparse(locator)
    query = parse_qs(parsed.query)
    query["pageSize"] = [str(max(VCS_BACKFILL_PAGE_SIZE, min(limit, 1000)))]
    list_url = parsed._replace(query=urlencode({key: values[-1] for key, values in query.items()})).geturl()
    fetched = fetch_text(list_url, verify_ssl=not allow_insecure_ssl)
    html_text = str(fetched.get("text") or "")
    final_url = str(fetched.get("final_url") or list_url)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in parse_html_listing(final_url, html_text, r"/web/portal/bbs/invtnotice/\d+"):
        raw_title = normalize_whitespace(link.get("title", ""))
        notice_url = link.get("link", "")
        if not raw_title or not notice_url or notice_url in seen:
            continue
        if "공고일:" not in raw_title:
            continue
        announced_date = extract_announcement_date(raw_title)
        deadline = extract_deadline(raw_title)
        lp_name = normalize_whitespace(raw_title.split("공고일:", 1)[0])
        seen.add(notice_url)
        rows.append(
            {
                "title": raw_title,
                "link": notice_url,
                "announced_date": announced_date,
                "application_deadline": deadline,
                "contact_team": lp_name,
                "text": raw_title,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def should_fetch_source_detail(source_kind: str, link: dict[str, str]) -> bool:
    if source_kind != "vcs_listing":
        return True
    announced = normalize_date(str(link.get("announced_date") or ""))
    if announced and announced < LP_NOTICE_COMPARISON_START_DATE:
        return False
    return True


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


def extract_kfcc_mg_attachments(final_url: str, html_text: str) -> list[dict[str, str]]:
    attachments: list[dict[str, str]] = []
    for match in re.finditer(
        r"fnDownload\(\s*['\"](?P<board>[^'\"]+)['\"]\s*,\s*['\"](?P<notice_no>[^'\"]+)['\"]\s*,\s*['\"](?P<file_no>[^'\"]+)['\"]\s*,\s*['\"](?P<file_name>[^'\"]+)['\"]\s*\)",
        html_text,
        flags=re.IGNORECASE,
    ):
        file_name = clean_attachment_name(match.group("file_name"))
        file_url = urljoin(final_url, f"/upload/neoboard/{match.group('board')}/{file_name}")
        attachments.append({"name": file_name, "url": file_url})
    return attachments


def is_kfcc_mg_commitment_notice(title: str) -> bool:
    text = normalize_whitespace(title)
    return all(term in text for term in ["위탁펀드형", "대체투자", "운용사"]) and "선정 공고" in text


def parse_kfcc_mg_notice_listing(source: dict[str, str], limit: int, allow_insecure_ssl: bool) -> list[dict[str, str]]:
    locator = source.get("locator", "")
    if not locator:
        return []
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    search_terms = split_semicolon(source.get("must_contain", "")) or ["위탁펀드형", "대체투자", "운용사"]

    def add_rows_from_html(html_text: str, final_url: str) -> None:
        for item in re.findall(r"<li\b.*?</li>", html_text, flags=re.IGNORECASE | re.DOTALL):
            action = re.search(r"fnDetail\(['\"](?P<id>\d+)['\"]\)", item, flags=re.IGNORECASE)
            title_match = re.search(r"<a\b[^>]*>\s*(?P<title>.*?)\s*</a>", item, flags=re.IGNORECASE | re.DOTALL)
            if not action or not title_match:
                continue
            title = normalize_whitespace(strip_html_tags(title_match.group("title")))
            if not title or not matches_must_contain(search_terms, title) or not is_kfcc_mg_commitment_notice(title):
                continue
            notice_id = action.group("id")
            link = urljoin(final_url, f"/mgNotice/mgNoticeDetail.do?no={notice_id}")
            if link in seen:
                continue
            date_match = re.search(
                r"<div\b[^>]*class=[\"'][^\"']*date[^\"']*[\"'][^>]*>(?P<date>.*?)</div>",
                item,
                flags=re.IGNORECASE | re.DOTALL,
            )
            announced_date = normalize_date(strip_html_tags(date_match.group("date"))) if date_match else ""
            if announced_date and announced_date < LP_NOTICE_COMPARISON_START_DATE:
                continue
            detail = fetch_official_detail(link, allow_insecure_ssl)
            attachment_items = extract_kfcc_mg_attachments(link, str(detail.get("text") or ""))
            if not attachment_items:
                # fetch_official_detail strips markup from text, so fetch the raw detail once for onclick attachments.
                try:
                    raw_detail = fetch_text(link, verify_ssl=not allow_insecure_ssl)
                    attachment_items = extract_kfcc_mg_attachments(
                        str(raw_detail.get("final_url") or link),
                        str(raw_detail.get("text") or ""),
                    )
                except Exception:
                    attachment_items = []
            seen.add(link)
            rows.append(
                {
                    "title": title,
                    "link": link,
                    "announced_date": announced_date,
                    "contact_team": "새마을금고중앙회",
                    "text": normalize_whitespace(f"{title} {detail.get('text') or ''}"),
                    "attachment_names": semicolon_join([str(item.get("name") or "") for item in attachment_items]),
                    "attachment_urls": semicolon_join([str(item.get("url") or "") for item in attachment_items]),
                }
            )
            if len(rows) >= limit:
                break

    page_count = max(1, min(12, (limit + 7) // 8 + 4))
    for page_no in range(1, page_count + 1):
        if len(rows) >= limit:
            break
        page_url = locator if page_no == 1 else urljoin(locator, "/mgNotice/mgNoticeList.do") + "?" + urlencode(
            {
                "pageRows": "8",
                "pageUnit": "10",
                "totalRows": "",
                "currentPageNo": "1",
                "boardId": "A01",
                "no": "",
                "schCategoryId": "",
                "schType": "",
                "schValue": "",
                "schGubun": "",
                "tabIndex": "",
                "pageNo": str(page_no),
            }
        )
        try:
            fetched = fetch_text(page_url, verify_ssl=not allow_insecure_ssl)
        except Exception as exc:
            print(f"warning: kfcc_mg_notice_fetch_failed page={page_no} error={exc}")
            continue
        add_rows_from_html(str(fetched.get("text") or ""), str(fetched.get("final_url") or page_url))

    list_url = urljoin(locator, "/mgNotice/mgNoticeList.do")
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
                    "schGubun": "",
                    "tabIndex": "",
                },
                locator,
                allow_insecure_ssl,
            )
        except Exception as exc:
            print(f"warning: kfcc_mg_notice_search_failed term={term} error={exc}")
            continue
        add_rows_from_html(html_text, list_url)
    return rows[:limit]


def is_kexim_commitment_notice(title: str) -> bool:
    text = normalize_whitespace(title)
    if "펀드" not in text:
        return False
    if any(term in text for term in ["컨설팅", "타당성조사", "입찰 지원", "입찰지원", "조달"]):
        return False
    return any(term in text for term in ["출자사업", "위탁운용사", "운용사", "선정계획"])


def extract_kexim_notice_rows(html_text: str, final_url: str, search_terms: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    item_pattern = (
        r"<div\b[^>]*class=[\"'][^\"']*notice-list-item[^\"']*[\"'][^>]*>"
        r"(?P<item>.*?)"
        r"(?=\s*<div\b[^>]*class=[\"'][^\"']*notice-list-item|\s*<!--\s*(?:공지사항|일반)\s+게시물\s+끝)"
    )
    for item_match in re.finditer(item_pattern, html_text, flags=re.IGNORECASE | re.DOTALL):
        item = item_match.group("item")
        title_match = re.search(
            r"<span\b[^>]*class=[\"'][^\"']*subject[^\"']*[\"'][^>]*>.*?<a\b[^>]*href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<title>.*?)</a>",
            item,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            continue
        title = normalize_whitespace(strip_html_tags(title_match.group("title")))
        if not title or not matches_must_contain(search_terms, title) or not is_kexim_commitment_notice(title):
            continue
        date_match = re.search(
            r"<span\b[^>]*title=[\"']작성일[\"'][^>]*>(?P<date>.*?)</span>",
            item,
            flags=re.IGNORECASE | re.DOTALL,
        )
        announced_date = normalize_date(strip_html_tags(date_match.group("date"))) if date_match else ""
        if announced_date and announced_date < LP_NOTICE_COMPARISON_START_DATE:
            continue
        category_match = re.search(
            r"<span\b[^>]*title=[\"']카테고리[\"'][^>]*>(?P<category>.*?)</span>",
            item,
            flags=re.IGNORECASE | re.DOTALL,
        )
        attachments: list[dict[str, str]] = []
        for link_match in re.finditer(r"<a\b[^>]*href=[\"'](?P<href>[^\"']*comm/getFile[^\"']+)[\"'][^>]*>(?P<name>.*?)</a>", item, flags=re.IGNORECASE | re.DOTALL):
            attachment_url = urljoin(final_url, html.unescape(link_match.group("href")))
            attachment_name = clean_attachment_name(strip_html_tags(link_match.group("name"))) or "첨부파일"
            attachments.append({"name": attachment_name, "url": attachment_url})
        rows.append(
            {
                "title": title,
                "link": urljoin(final_url, html.unescape(title_match.group("href"))),
                "announced_date": announced_date,
                "contact_team": normalize_whitespace(strip_html_tags(category_match.group("category"))) if category_match else "한국수출입은행",
                "text": title,
                "attachment_names": semicolon_join([item["name"] for item in attachments]),
                "attachment_urls": semicolon_join([item["url"] for item in attachments]),
            }
        )
    return rows


def parse_kexim_notice_listing(source: dict[str, str], limit: int, allow_insecure_ssl: bool) -> list[dict[str, str]]:
    locator = source.get("locator", "") or "https://www.koreaexim.go.kr/HPHKBI039M01"
    search_terms = split_semicolon(source.get("must_contain", "")) or ["펀드", "운용사", "출자"]
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    page_count = max(1, min(12, (limit + 9) // 10 + 4))
    for page_no in range(1, page_count + 1):
        if len(rows) >= limit:
            break
        page_url = locator if page_no == 1 else locator + "?" + urlencode({"curPage": str(page_no)})
        try:
            fetched = fetch_cookie_redirect_text(page_url, allow_insecure_ssl, referer=locator)
        except Exception as exc:
            print(f"warning: kexim_notice_fetch_failed page={page_no} error={exc}")
            continue
        for row in extract_kexim_notice_rows(str(fetched.get("text") or ""), str(fetched.get("final_url") or page_url), search_terms):
            if row["link"] in seen:
                continue
            seen.add(row["link"])
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows[:limit]


def parse_compact_datetime(value: str) -> str:
    text = re.sub(r"[^0-9]", "", str(value or ""))
    if len(text) >= 8:
        try:
            return datetime.strptime(text[:8], "%Y%m%d").date().isoformat()
        except ValueError:
            return ""
    return normalize_date(value)


def is_kdb_ngf_relevant_notice(title: str) -> bool:
    if "국민성장펀드" not in title:
        return False
    if any(term in title for term in ["약정서", "운영 안내", "제출서식"]):
        return False
    return any(term in title for term in ["선정공고", "선정결과", "선정계획"])


def make_kdb_ngf_detail_url(locator: str, row: dict[str, object]) -> str:
    payload = {
        "ITR_NAC_ID_MNG_SNO": str(row.get("ITR_NAC_ID_MNG_SNO") or ""),
        "ITR_BLB_ID": "PDS463",
        "NAC_SNO": str(row.get("NUM") or ""),
        "FIRST_MENU_ID": "GFIMMG01N00",
        "CTG_C": str(row.get("CTG_C") or ""),
        "DCD_SNO": str(row.get("DCD_SNO") or ""),
    }
    return urljoin(locator, "/BOUBUF02N00.act") + "?" + urlencode(
        {
            "_mnuId": "WBGFGF0007",
            "_PARAM_NAME": "NEXT_DATA",
            "_PARM_DATA": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        }
    )


def parse_kdb_ngf_listing(source: dict[str, str], limit: int, allow_insecure_ssl: bool) -> list[dict[str, str]]:
    locator = source.get("locator", "")
    if not locator:
        return []
    payload = {
        "SEARCH_CONDITION": "",
        "SEARCH_KEYWORD": "",
        "SEARCH_CATEGORY": "",
        "ORDER_TYPE": "new",
        "MODE": "",
        "ITR_BLB_ID": "PDS463",
        "HEADER_STD_WEB": {
            "REQ_PAGE_NO": 1,
            "PAGE_ROW_COUNT": str(max(10, min(limit, 50))),
            "NEXT_PAGE_YN": "S",
            "NEXTPAGDTT": "P",
            "GRID_NEXTKEY_ITR_CND": "",
        },
    }
    response_text = fetch_form_text(
        "https://ngf.kdb.co.kr/BOUBUF01R01.jct",
        {"_JSON_": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
        locator,
        allow_insecure_ssl,
    )
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        print(f"warning: kdb_ngf_json_failed source_code={source.get('source_code')} error={exc}")
        return []

    files_by_group: dict[str, list[dict[str, str]]] = {}
    for file_key in ["FILELIST_REC", "FILEGRPLIST_REC"]:
        for file_row in data.get(file_key, []) or []:
            if not isinstance(file_row, dict):
                continue
            group_id = str(file_row.get("GROUP_ID") or "")
            file_id = str(file_row.get("FILE_ID") or "")
            file_name = clean_attachment_name(str(file_row.get("FILE_NM") or ""))
            if not group_id or not file_id:
                continue
            url = "https://file.kdb.co.kr/fileView?" + urlencode({"groupId": group_id, "fileId": file_id})
            group_files = files_by_group.setdefault(group_id, [])
            if any(item["url"] == url for item in group_files):
                continue
            group_files.append({"name": file_name, "url": url})

    rows: list[dict[str, str]] = []
    for raw_row in data.get("PDSLIST_REC", []) or []:
        if not isinstance(raw_row, dict):
            continue
        title = normalize_whitespace(strip_html_tags(str(raw_row.get("NAC_CONE_TTL") or "")))
        if not title or not is_kdb_ngf_relevant_notice(title):
            continue
        body = normalize_whitespace(
            strip_html_tags(str(raw_row.get("NAC_SMRY_CONE") or raw_row.get("NAC_HTML_TXT_INF") or ""))
        )
        group_id = str(raw_row.get("FILE_ID") or "")
        attachments = files_by_group.get(group_id, [])
        rows.append(
            {
                "title": title,
                "link": make_kdb_ngf_detail_url(locator, raw_row),
                "announced_date": parse_compact_datetime(str(raw_row.get("FST_ENR_DTM") or "")),
                "contact_team": "",
                "text": body,
                "attachment_names": semicolon_join([item["name"] for item in attachments]),
                "attachment_urls": semicolon_join([item["url"] for item in attachments]),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def is_kdic_relevant_notice(title: str, contact_team: str) -> bool:
    haystack = f"{title} {contact_team}".lower()
    if is_non_commitment_notice(title):
        return False
    if "예금보험기금" not in title and "기금운용실" not in contact_team:
        return False
    return any(term in haystack for term in ["위탁운용사", "운용사", "pool", "자산운용", "국내채권자산"])


def extract_kdic_detail_payload(html_text: str) -> dict[str, str]:
    detail_block = ""
    detail_match = re.search(
        r"<div\b[^>]*class=[\"'][^\"']*detailTable[^\"']*[\"'][^>]*>(?P<block>.*?)</div>\s*<!--// detailTable -->",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if detail_match:
        detail_block = detail_match.group("block")
    title_match = re.search(r"<th\b[^>]*[^>]*>\s*<span>(?P<title>.*?)</span>", detail_block, flags=re.IGNORECASE | re.DOTALL)
    team_match = re.search(r"<b>\s*소관부서\s*</b>\s*<em\b[^>]*>(?P<team>.*?)</em>", detail_block, flags=re.IGNORECASE | re.DOTALL)
    date_match = re.search(r"<b>\s*등록일\s*</b>\s*<em\b[^>]*>(?P<date>.*?)</em>", detail_block, flags=re.IGNORECASE | re.DOTALL)
    body_match = re.search(r"<tr\b[^>]*class=[\"']detail[\"'][^>]*>\s*<td\b[^>]*>(?P<body>.*?)</td>", detail_block, flags=re.IGNORECASE | re.DOTALL)
    attachment_names = []
    for item in re.findall(r"<div\b[^>]*class=[\"'][^\"']*downFileBox[^\"']*[\"'][^>]*>.*?</div>", detail_block, flags=re.IGNORECASE | re.DOTALL):
        for name in re.findall(r"<p\b[^>]*>\s*<span>(?P<name>.*?)</span>", item, flags=re.IGNORECASE | re.DOTALL):
            attachment_names.append(clean_attachment_name(strip_html_tags(name)))
    return {
        "title": strip_html_tags(title_match.group("title")) if title_match else "",
        "contact_team": strip_html_tags(team_match.group("team")) if team_match else "",
        "announced_date": normalize_date(strip_html_tags(date_match.group("date"))) if date_match else "",
        "text": strip_html_tags(body_match.group("body")) if body_match else strip_html_tags(detail_block),
        "attachment_names": semicolon_join(attachment_names),
    }


def parse_kdic_notice_listing(source: dict[str, str], limit: int, allow_insecure_ssl: bool) -> list[dict[str, str]]:
    locator = source.get("locator", "")
    if not locator:
        return []
    fetched = fetch_text(locator, verify_ssl=not allow_insecure_ssl)
    html_text = str(fetched.get("text") or "")
    final_url = str(fetched.get("final_url") or locator)
    rows: list[dict[str, str]] = []
    for row_html in re.findall(r"<tr\b.*?</tr>", html_text, flags=re.IGNORECASE | re.DOTALL):
        action = re.search(r"detailView\((?P<pst_no>\d+)\)", row_html, flags=re.IGNORECASE)
        title_match = re.search(
            r"<td\b[^>]*class=[\"'][^\"']*tit[^\"']*[\"'][^>]*>.*?<a\b[^>]*>(?P<title>.*?)</a>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not action or not title_match:
            continue
        title = normalize_whitespace(strip_html_tags(title_match.group("title")))
        team_match = re.search(
            r"<td\b[^>]*>\s*<span\b[^>]*>\s*소관부서\s*</span>\s*<a\b[^>]*>(?P<team>.*?)</a>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        date_match = re.search(
            r"<td\b[^>]*>\s*<span\b[^>]*>\s*등록일\s*</span>(?P<date>.*?)</td>",
            row_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        contact_team = normalize_whitespace(strip_html_tags(team_match.group("team"))) if team_match else ""
        if not is_kdic_relevant_notice(title, contact_team):
            continue
        detail_url = urljoin(final_url, "/di/pbcr/selectPbcrNtcDtl.do") + "?" + urlencode(
            {"pstNo": action.group("pst_no"), "curPage": "0"}
        )
        payload: dict[str, str] = {}
        try:
            detail = fetch_text(detail_url, verify_ssl=not allow_insecure_ssl)
            payload = extract_kdic_detail_payload(str(detail.get("text") or ""))
        except Exception as exc:
            print(f"warning: kdic_detail_fetch_failed pst_no={action.group('pst_no')} error={exc}")
        rows.append(
            {
                "title": normalize_whitespace(payload.get("title") or title),
                "link": detail_url,
                "announced_date": payload.get("announced_date") or normalize_date(strip_html_tags(date_match.group("date"))) if date_match else payload.get("announced_date", ""),
                "contact_team": payload.get("contact_team") or contact_team,
                "text": normalize_whitespace(payload.get("text", "")),
                "attachment_names": payload.get("attachment_names", ""),
                "attachment_urls": "",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def is_nps_commitment_notice(title: str) -> bool:
    include_terms = [
        "사모투자",
        "PEF",
        "벤처",
        "대체투자",
        "부동산투자",
        "인프라투자",
        "인프라",
        "사모대출",
        "크레딧",
    ]
    exclude_terms = [
        "국내주식",
        "MMF",
        "외화금고",
        "수탁기관",
        "자문사",
        "투자자문",
        "채권",
        "거래증권사",
        "보관기관",
    ]
    return any(term in title for term in include_terms) and not any(term in title for term in exclude_terms)


def parse_nps_manager_selection_listing(source: dict[str, str], limit: int, allow_insecure_ssl: bool) -> list[dict[str, str]]:
    locator = source.get("locator", "")
    if not locator:
        return []
    fetched = fetch_text(locator, verify_ssl=not allow_insecure_ssl)
    first_html = str(fetched.get("text") or "")
    final_url = str(fetched.get("final_url") or locator)
    page_numbers = [
        int(value)
        for value in re.findall(r"data-pagenum=[\"'](?P<page>\d+)[\"']", first_html)
        if value.isdigit()
    ]
    max_page = max(page_numbers) if page_numbers else 1
    list_url = urljoin(final_url, "/impa/dlnginstslctnpbanclist/empty/getOHEF0017M0.do")
    detail_base = urljoin(final_url, "/impa/dlnginstslctnpbancdtl/getOHEF0018M0.do")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    def append_rows(html_text: str) -> None:
        for row_html in re.findall(r"<tr\b.*?</tr>", html_text, flags=re.IGNORECASE | re.DOTALL):
            action = re.search(
                r"fnc_goBbsDetail\(\s*['\"](?P<pst_id>[^'\"]+)['\"]\s*,\s*['\"](?P<bbs_cd>[^'\"]+)['\"]\s*\)",
                row_html,
                flags=re.IGNORECASE,
            )
            title_match = re.search(
                r"<td\b[^>]*class=[\"'][^\"']*title[^\"']*[\"'][^>]*>.*?<a\b[^>]*>(?P<title>.*?)</a>",
                row_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not action or not title_match:
                continue
            title = normalize_whitespace(strip_html_tags(title_match.group("title")))
            if not title or not is_nps_commitment_notice(title):
                continue
            date_match = re.search(
                r"<td\b[^>]*class=[\"'][^\"']*date[^\"']*[\"'][^>]*>(?P<date>.*?)</td>",
                row_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            writer_match = re.search(
                r"<td\b[^>]*class=[\"'][^\"']*writer[^\"']*[\"'][^>]*>(?P<writer>.*?)</td>",
                row_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            pst_id = action.group("pst_id")
            bbs_cd = action.group("bbs_cd")
            detail_url = detail_base + "?" + urlencode({"pstId": pst_id, "hmpgBbsCd": bbs_cd})
            if detail_url in seen:
                continue
            seen.add(detail_url)
            rows.append(
                {
                    "title": title,
                    "link": detail_url,
                    "announced_date": normalize_date(strip_html_tags(date_match.group("date"))) if date_match else "",
                    "contact_team": normalize_whitespace(strip_html_tags(writer_match.group("writer"))) if writer_match else "",
                    "text": title,
                }
            )

    append_rows(first_html)
    for page_no in range(2, max_page + 1):
        if len(rows) >= limit:
            break
        try:
            html_text = fetch_json_post_text(
                list_url,
                {"pageIndex": page_no, "searchGbu": "", "searchText": ""},
                final_url,
                allow_insecure_ssl,
            )
        except Exception as exc:
            print(f"warning: nps_page_fetch_failed page={page_no} error={exc}")
            continue
        append_rows(html_text)
    return rows[:limit]


def selected_gp_names(title: str, excerpt: str, aliases: object, existing: str = "") -> str:
    names = [part.strip() for part in re.split(r"[,;]", existing or "") if part.strip()]
    raw_names = extract_raw_selected_gp_names(f"{title} {excerpt}")
    raw_norms = {normalize_for_match(name): name for name in raw_names}
    for match in match_gp_entities(title, excerpt, "", aliases):
        name = str(match.get("entity_name") or "").strip()
        matched_alias_norm = normalize_for_match(str(match.get("matched_alias") or ""))
        entity_norm = normalize_for_match(name)
        if any(matched_alias_norm and matched_alias_norm in raw_norm and entity_norm != raw_norm for raw_norm in raw_norms):
            continue
        if name and name not in names:
            names.append(name)
    for name in raw_names:
        if name and name not in names:
            names.append(name)
    names = [name for name in names if name and name not in GP_EXCLUSION_NAMES]
    return "; ".join(names)


def clean_raw_gp_candidate(value: str) -> str:
    text = normalize_whitespace(value)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"^[0-9]+\s*", "", text)
    text = re.sub(r"^[ㅇ○●ㆍ·\-\s]+", "", text)
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    text = re.sub(r"^(?:대형|중형|소형|루키|중대형|선정결과|운용사명|운용사\s*명|구분)\s*", "", text)
    text = re.sub(r"\s*(?:대형|중형|소형|루키|중대형)\s*$", "", text)
    text = normalize_whitespace(text)
    return text


def append_raw_gp_name(names: list[str], raw_name: str) -> None:
    name = clean_raw_gp_candidate(raw_name)
    name = RAW_GP_DISPLAY_ALIASES.get(name, name)
    if not name or name in GP_EXCLUSION_NAMES:
        return
    if any(token in name for token in ["위탁운용사", "선정결과", "서류심사", "운용사명"]):
        return
    if len(normalize_for_match(name)) < 3:
        return
    name_norm = normalize_for_match(name)
    for index, existing in enumerate(names):
        existing_norm = normalize_for_match(existing)
        if name_norm == existing_norm:
            return
        if name_norm in existing_norm:
            return
        if existing_norm in name_norm:
            names[index] = name
            return
    names.append(name)


def extract_raw_selected_gp_names(text: str) -> list[str]:
    value = normalize_whitespace(text)
    if not value:
        return []
    # Keep the extraction focused on the result section; page chrome often contains unrelated menus.
    start_candidates = [
        value.find(term)
        for term in ["선정 결과", "선정결과", "서류심사 통과", "정량평가 결과", "대상 운용사"]
        if value.find(term) >= 0
    ]
    if start_candidates:
        value = value[min(start_candidates) :]
    stop_candidates = [
        value.find(term)
        for term in ["다음글", "이전글", "목록", "문의:", "Copyright"]
        if value.find(term) >= 0
    ]
    if stop_candidates:
        value = value[: min(stop_candidates)]
    names: list[str] = []
    for explicit_name in RAW_GP_EXPLICIT_NAMES:
        if explicit_name in value:
            append_raw_gp_name(names, explicit_name)
    normalized_chunks = value
    normalized_chunks = normalized_chunks.replace("/", "|")
    normalized_chunks = re.sub(r"\s*[-–—]\s*", "|", normalized_chunks)
    normalized_chunks = re.sub(r"(?:^|\s)(?:[0-9]{1,2}[.)]?|ㅇ|○|●|ㆍ|·)\s*", "|", normalized_chunks)
    normalized_chunks = re.sub(r"\s+(?:대형|중형|소형|루키|중대형)(?=\s|$)", "|", normalized_chunks)
    for chunk in re.split(r"[|,;]", normalized_chunks):
        chunk = clean_raw_gp_candidate(chunk)
        if not chunk:
            continue
        for match in RAW_GP_NAME_RE.finditer(chunk):
            append_raw_gp_name(names, match.group("name"))
    return names


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


def official_notice_value_overrides(source_code: str, title: str, text: str) -> dict[str, object]:
    if source_code != "kfcc_mg_notice":
        return {}
    combined = normalize_whitespace(f"{title} {text}")
    if "위탁펀드형 대체투자" not in combined or "운용사 선정 공고" not in combined:
        return {}
    if "2024년" in title:
        return {
            "application_deadline": "2024-09-13",
            "allocation_amount_krw_100mn": 5000.0,
        }
    if "2025년" in title:
        return {
            "application_deadline": "2025-05-14",
            "allocation_amount_krw_100mn": 5000.0,
        }
    return {}


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
    title_first_text = normalize_whitespace(f"{title}\n{cleaned_text}")
    overrides = official_notice_value_overrides(source_code, title, cleaned_text)
    announced = normalize_date(announced_date) or extract_announcement_date(cleaned_text)
    deadline = str(overrides.get("application_deadline") or "") or extract_deadline(cleaned_text)
    title_stage = infer_stage(title)
    stage = title_stage if title_stage in {"notice", "application", "briefing"} else infer_stage(cleaned_text)
    event_type = infer_event_type(title, stage, deadline, report_date)
    if event_type not in {"final_selection", "shortlist"}:
        gp_names = ""
    amount_info = classify_amounts(cleaned_text)
    if overrides.get("allocation_amount_krw_100mn") is not None:
        amount_info = dict(amount_info)
        amount_info["allocation_amount_krw_100mn"] = overrides["allocation_amount_krw_100mn"]
        amount_info["amount_type"] = "allocation"
        amount_info["amount_confidence"] = "high"
    allocation = amount_info["allocation_amount_krw_100mn"]
    confidence, confidence_note, public_visible = confidence_for(source_type, lp_code, event_type, allocation, title)
    first_document = document_url or (split_semicolon(attachment_urls)[0] if attachment_urls else "")
    event_date = announced or report_date
    if not announced and deadline and deadline < report_date:
        event_date = deadline
    program_name = infer_program_name(title) or infer_program_name(title_first_text)
    round_name = infer_round_name(title) or infer_round_name(title_first_text)
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
        "event_date": event_date,
        "program_name": program_name,
        "round_name": round_name,
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
        if not parse_bool(source.get("is_active", "1")) or source_kind not in {"html_listing", "html_page", "apfs_board", "kbiz_listing", "vcs_listing", "ktcu_notice", "cu_notice", "kfcc_tender", "kfcc_mg_notice", "kexim_notice", "kdb_jex_board", "kdic_notice"}:
            continue
        locator = source.get("locator", "")
        if not locator:
            continue
        try:
            # The caller owns collection volume. A source-specific backfill override
            # made small readiness checks unexpectedly parse hundreds of notices.
            source_limit = limit_per_source
            if source_kind == "apfs_board":
                links = parse_apfs_board_listing(source, source_limit, allow_insecure_ssl)
            elif source_kind == "kbiz_listing":
                links = parse_kbiz_listing(source, allow_insecure_ssl)
            elif source_kind == "vcs_listing":
                links = parse_vcs_investment_listing(source, source_limit, allow_insecure_ssl)
            elif source_kind == "ktcu_notice":
                links = parse_ktcu_listing(source, source_limit, allow_insecure_ssl)
            elif source_kind == "cu_notice":
                links = parse_cu_listing(source, source_limit, allow_insecure_ssl)
            elif source_kind == "kfcc_tender":
                links = parse_kfcc_tender_listing(source, source_limit, allow_insecure_ssl)
            elif source_kind == "kfcc_mg_notice":
                links = parse_kfcc_mg_notice_listing(source, source_limit, allow_insecure_ssl)
            elif source_kind == "kexim_notice":
                links = parse_kexim_notice_listing(source, source_limit, allow_insecure_ssl)
            elif source_kind == "kdb_jex_board":
                links = parse_kdb_ngf_listing(source, source_limit, allow_insecure_ssl)
            elif source_kind == "kdic_notice":
                links = parse_kdic_notice_listing(source, source_limit, allow_insecure_ssl)
            elif source.get("source_code") == "nps_manager_selection":
                links = parse_nps_manager_selection_listing(source, source_limit, allow_insecure_ssl)
            elif source_kind == "html_page":
                fetched = fetch_text(locator, verify_ssl=not allow_insecure_ssl)
                links = make_html_page_link(
                    source,
                    str(fetched.get("text") or ""),
                    str(fetched.get("final_url") or locator),
                )
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
            link_text = normalize_whitespace(str(link.get("text") or ""))
            link_attachment_names = split_semicolon(str(link.get("attachment_names") or ""))
            link_attachment_urls = split_semicolon(str(link.get("attachment_urls") or ""))
            link_attachments = [
                {"name": name, "url": url}
                for name, url in zip(link_attachment_names, link_attachment_urls)
                if url
            ]
            if should_fetch_source_detail(source_kind, link):
                detail = fetch_source_detail(source, notice_url, allow_insecure_ssl)
            else:
                detail = {}
            detail_title = normalize_whitespace(str(detail.get("title") or ""))
            detail_attachments = [item for item in detail.get("attachments", []) if isinstance(item, dict)]
            attachments = [*link_attachments, *detail_attachments]
            attachment_names = semicolon_join([*link_attachment_names, *[str(item.get("name") or "") for item in detail_attachments]])
            attachment_urls = semicolon_join([*link_attachment_urls, *[str(item.get("url") or "") for item in detail_attachments]])
            base_detail_text = normalize_whitespace(f"{link_text} {detail.get('text') or ''}")
            stage_hint = infer_stage(f"{title} {detail_title} {base_detail_text}")
            attachment_text = (
                extract_attachment_texts(attachments, allow_insecure_ssl)
                if should_extract_attachment_text(stage_hint, title, attachments)
                else ""
            )
            detail_text = normalize_whitespace(f"{attachment_text} {base_detail_text}")[:OFFICIAL_DETAIL_TEXT_LIMIT]
            contact_team = link.get("contact_team", "")
            contact_lp_code = infer_lp_code(contact_team, lp_aliases)
            preliminary_text = f"{title} {detail_title} {link_text} {detail_text} {notice_url}"
            if source_kind == "vcs_listing" and contact_lp_code:
                lp_code = contact_lp_code
            else:
                lp_code = infer_lp_code(preliminary_text, lp_aliases, source.get("lp_code", ""))
            title = choose_official_notice_title(title, detail_title, lp_names_by_code.get(lp_code, ""))
            text = f"{title} {link_text} {detail_text} {notice_url}"
            if source_kind == "vcs_listing":
                lp_code = infer_lp_code(title, lp_aliases, "") or lp_code
            else:
                lp_code = infer_lp_code(title, lp_aliases, lp_code) or infer_lp_code(text, lp_aliases, lp_code)
            announced_date = link.get("announced_date", "")
            stage_for_gp = infer_stage(f"{title} {detail_text}") or stage_hint
            gp_text = detail_text[:OFFICIAL_GP_MATCH_TEXT_LIMIT] if stage_for_gp in {"selection_result", "shortlist"} else ""
            rows.append(
                make_notice_row(
                    lp_code=lp_code,
                    source_code=source.get("source_code", ""),
                    source_type="official",
                    notice_url=notice_url,
                    title=title,
                    announced_date=announced_date or str(link.get("announced_date") or ""),
                    fallback_year=fallback_year,
                    report_date=report_date,
                    text=text,
                    gp_names=selected_gp_names(title, gp_text, gp_aliases),
                    raw_excerpt=f"{source.get('source_name', '')} 목록에서 발견",
                    contact_team=contact_team,
                    document_url=str(link.get("document_url") or "") or primary_document_url(attachments),
                    attachment_names=attachment_names,
                    attachment_urls=attachment_urls,
                )
            )
            count += 1
            if count >= source_limit:
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
                selected_gp_names = CASE
                    WHEN excluded.event_type NOT IN ('final_selection', 'shortlist') THEN ''
                    ELSE COALESCE(NULLIF(excluded.selected_gp_names, ''), lp_commitment_notice.selected_gp_names)
                END,
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
    value = re.sub(r"(?<!\d)[`'‘’](?P<year>\d{2})(?=\s*년|[.\-/])", lambda m: f"20{m.group('year')}", value)
    value = re.sub(r"(?<!\d)(?P<year>2[0-9])(?=\s*년|[.\-/])", lambda m: f"20{m.group('year')}", value)
    value = re.sub(r"[-–—]\s*(더벨|인베스트조선|매일경제|한국경제|이데일리|블로터|딜사이트)\s*$", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value).lower()

def _build_lp_notice_business_maps(rows: list[dict[str, object]]) -> tuple[
    dict[tuple[str, str, str], str],
    dict[tuple[str, str, str], set[str]],
]:
    """사업 단위 병합을 위한 특수사업명/플랫폼/라운드 인덱스를 생성한다."""
    specific_by_anchor: dict[tuple[str, str, str], tuple[tuple[int, ...], str]] = {}
    rounds_by_business: dict[tuple[str, str, str], set[str]] = {}

    def round_key(row: dict[str, object]) -> str:
        return normalize_round_name(infer_notice_round_name(row))

    for row in rows:
        lp_code = str(row.get("lp_code") or "").strip()
        if not lp_code:
            continue
        platform_key = _normalize_program_name_text(_notice_platform_name(row))
        program = infer_notice_program_name(row)
        if not program or is_generic_program_name(program):
            continue
        program_key = _normalize_program_name_text(program)
        rkey = round_key(row)
        score = stored_notice_quality(row)
        candidate: tuple[tuple[int, ...], str] = (score, program)
        for key in [
            _notice_specific_map_key(lp_code, rkey, platform_key),
            _notice_specific_map_key(lp_code, rkey, ""),
            _notice_specific_map_key(lp_code, "", platform_key),
        ]:
            existing = specific_by_anchor.get(key)
            if not existing or score > existing[0] or (score == existing[0] and len(program) > len(existing[1])):
                specific_by_anchor[key] = candidate

        if rkey:
            rounds_key = (lp_code, program_key, platform_key)
            rounds_by_business.setdefault(rounds_key, set()).add(rkey)

    resolved_specific_map: dict[tuple[str, str, str], str] = {key: value[1] for key, value in specific_by_anchor.items()}
    return resolved_specific_map, rounds_by_business


def _best_notice_program_name(rows: list[dict[str, object]]) -> str:
    ranked = sorted(rows, key=stored_notice_quality, reverse=True)
    # Prefer business-specific program names (e.g., '은행권 중견기업 밸류업펀드 3차')
    # over platform-level names (e.g., '국민성장펀드').
    for row in ranked:
        candidate = infer_notice_program_name(row)
        if candidate and not is_generic_program_name(candidate):
            return candidate
    # If no business-specific candidate is found, keep legacy fallback behavior.
    for row in ranked:
        candidate = clean_program_candidate(row.get("program_name"))
        if candidate:
            return candidate
    for row in ranked:
        candidate = infer_notice_program_name(row)
        if candidate:
            return candidate
    for row in ranked:
        inferred = infer_program_name(
            normalize_whitespace(
                " ".join(
                    str(value or "")
                    for value in [
                        row.get("title", ""),
                        row.get("raw_excerpt", ""),
                        row.get("program_name", ""),
                        row.get("round_name", ""),
                    ]
                )
            )
        )
        if inferred:
            return inferred
    return ""


def _best_notice_round_name(rows: list[dict[str, object]]) -> str:
    ranked = sorted(rows, key=stored_notice_quality, reverse=True)
    preferred: list[str] = []
    fallback: list[str] = []
    for row in ranked:
        raw_round = infer_notice_round_name(row)
        if raw_round:
            preferred.append(raw_round)
        else:
            fallback_candidate = normalize_round_name(row.get("round_name"))
            if fallback_candidate:
                fallback.append(fallback_candidate)
    for round_name in preferred:
        if round_name and round_name not in {"수시", "정시", "상반기", "하반기"}:
            return round_name
    for round_name in preferred:
        if round_name:
            return round_name
    for round_name in fallback:
        if round_name:
            return round_name
    text_round = infer_round_name_with_fallback(
        normalize_whitespace(
            " ".join(
                str(value or "")
                for value in [row.get("title") for row in rows if row.get("title")]
            )
        )
    )
    return text_round or ""


def dedupe_candidates(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[object, str, str], dict[str, object]] = {}
    for row in rows:
        business_key = notice_business_key(row)
        key = (
            row.get("lp_code") or "",
            str(row.get("event_type") or ""),
            business_key or normalize_title_key(str(row.get("title") or "")),
        )
        if not key[2]:
            continue
        current = grouped.get(key)
        if current is None or candidate_quality(row) > candidate_quality(current):
            grouped[key] = row
    return sorted(grouped.values(), key=lambda row: (EVENT_PRIORITY.get(str(row.get("event_type") or ""), 99), str(row.get("event_date") or ""), str(row.get("title") or "")))


def candidate_quality(row: dict[str, object]) -> tuple[int, ...]:
    program_specificity = _notice_program_specificity(row)
    confidence_score = {"high": 3, "medium": 2, "low": 1}.get(str(row.get("confidence") or ""), 0)
    source_score = 2 if row.get("source_type") == "official" else 1
    selected_score = 1 if row.get("selected_gp_names") else 0
    amount_score = 1 if row.get("allocation_amount_krw_100mn") else 0
    validated_score = 1 if row.get("monitor_status") == "validated" else 0
    return confidence_score, program_specificity, source_score, validated_score, selected_score, amount_score


def canonical_notice_key(row: dict[str, object]) -> tuple[str, str]:
    title_key = notice_business_key(row) or normalize_title_key(str(row.get("title") or ""))
    return (str(row.get("lp_code") or ""), title_key)


def stored_notice_quality(row: dict[str, object]) -> tuple[int, int, int, int, int, int, int]:
    program_specificity = _notice_program_specificity(row)
    confidence_score = {"high": 3, "medium": 2, "low": 1}.get(str(row.get("confidence") or ""), 0)
    source_code = str(row.get("source_code") or "")
    source_type = str(row.get("source_type") or "")
    source_score = 0
    if source_type == "official":
        source_score = 3
    if source_code == "vcs_investment_notice":
        source_score = 2
    if source_type == "news":
        source_score = 1
    field_score = sum(
        1
        for key in [
            "allocation_amount_krw_100mn",
            "application_deadline",
            "selected_gp_names",
            "document_url",
            "attachment_urls",
            "asset_class",
            "strategy",
        ]
        if row.get(key)
    )
    validated_score = 2 if row.get("monitor_status") == "validated" else 0
    visible_score = 1 if row.get("public_visible") else 0
    detail_score = len(str(row.get("raw_excerpt") or ""))
    notice_id = int(row.get("notice_id") or 0)
    return validated_score, confidence_score, program_specificity, field_score, source_score, visible_score, detail_score, -notice_id


def merged_selected_gp_names(rows: list[dict[str, object]]) -> str:
    names: list[str] = []
    for row in rows:
        if str(row.get("event_type") or "") not in {"final_selection", "shortlist"}:
            continue
        for name in split_selected_gp_names(str(row.get("selected_gp_names") or "")):
            if name not in names:
                names.append(name)
    return "; ".join(names)


def first_non_blank(rows: list[dict[str, object]], key: str) -> object:
    for row in rows:
        value = row.get(key)
        if value not in {None, ""}:
            return value
    return None


def dedupe_stored_notices(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        """
        SELECT
            notice_id,
            lp_code,
            source_code,
            source_type,
            title,
            event_type,
            event_date,
            announced_date,
            application_deadline,
            document_url,
            attachment_names,
            attachment_urls,
            program_name,
            round_name,
            notice_year,
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
            raw_excerpt
        FROM lp_commitment_notice
        WHERE public_visible = 1
          AND COALESCE(monitor_status, '') <> 'dismissed'
        """
    )
    headers = [desc[0] for desc in cursor.description]
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    rows = [dict(zip(headers, values)) for values in cursor.fetchall()]
    specific_map, rounds_by_business = _build_lp_notice_business_maps(rows)

    resolved_rows: list[dict[str, object]] = []
    for row in rows:
        lp_code = str(row.get("lp_code") or "").strip()
        if not lp_code:
            resolved_rows.append(row)
            continue

        resolved_row = dict(row)
        lp_key = lp_code
        program = infer_notice_program_name(resolved_row)
        rkey = normalize_round_name(infer_notice_round_name(resolved_row))
        platform_key = _normalize_program_name_text(_notice_platform_name(resolved_row))

        if not program or is_generic_program_name(program):
            for key in [
                _notice_specific_map_key(lp_key, rkey, platform_key),
                _notice_specific_map_key(lp_key, rkey, ""),
                _notice_specific_map_key(lp_key, "", platform_key),
            ]:
                mapped_program = specific_map.get(key)
                if mapped_program:
                    resolved_row["program_name"] = mapped_program
                    program = mapped_program
                    break

        if program and rkey == "":
            program_key = _normalize_program_name_text(program)
            fallback_round = ""
            for key in [
                (lp_key, program_key, platform_key),
                (lp_key, program_key, ""),
            ]:
                candidates = rounds_by_business.get(key, set())
                if candidates and len(candidates) == 1:
                    candidate_round = next(iter(candidates))
                    if candidate_round:
                        fallback_round = candidate_round
                        break
            if fallback_round:
                resolved_row["round_name"] = fallback_round

        resolved_rows.append(resolved_row)

    for row in resolved_rows:
        key = canonical_notice_key(row)
        if not key[0] or not key[1]:
            continue
        groups.setdefault(key, []).append(row)

    hidden = 0
    now = now_utc_iso()
    for rows in groups.values():
        if len(rows) < 2:
            continue
        ranked = sorted(rows, key=stored_notice_quality, reverse=True)
        keeper = ranked[0]
        keeper_id = int(keeper["notice_id"])
        merged: dict[str, object] = {
            "program_name": _best_notice_program_name(ranked),
            "round_name": _best_notice_round_name(ranked),
        }
        for key in [
            "document_url",
            "attachment_names",
            "attachment_urls",
            "application_deadline",
            "notice_stage",
            "asset_class",
            "strategy",
            "amount_type",
            "amount_confidence",
            "confidence",
            "confidence_note",
            "raw_excerpt",
        ]:
            merged[key] = keeper.get(key) or first_non_blank(ranked, key) or ""
        for key in [
            "program_size_krw_100mn",
            "allocation_amount_krw_100mn",
            "commitment_amount_krw_100mn",
        ]:
            merged[key] = keeper.get(key) or first_non_blank(ranked, key)
        merged["selected_gp_names"] = merged_selected_gp_names(ranked)
        conn.execute(
            """
            UPDATE lp_commitment_notice
            SET
                document_url = ?,
                attachment_names = ?,
                attachment_urls = ?,
                program_name = ?,
                round_name = ?,
                application_deadline = ?,
                notice_stage = ?,
                asset_class = ?,
                strategy = ?,
                program_size_krw_100mn = ?,
                allocation_amount_krw_100mn = ?,
                amount_type = ?,
                amount_confidence = ?,
                commitment_amount_krw_100mn = ?,
                selected_gp_names = ?,
                confidence = ?,
                confidence_note = ?,
                raw_excerpt = ?,
                public_visible = 1,
                updated_at = ?
            WHERE notice_id = ?
            """,
            (
                merged["document_url"],
                merged["attachment_names"],
                merged["attachment_urls"],
                merged["program_name"],
                merged["round_name"],
                merged["application_deadline"],
                merged["notice_stage"],
                merged["asset_class"],
                merged["strategy"],
                merged["program_size_krw_100mn"],
                merged["allocation_amount_krw_100mn"],
                merged["amount_type"],
                merged["amount_confidence"],
                merged["commitment_amount_krw_100mn"],
                merged["selected_gp_names"],
                merged["confidence"],
                merged["confidence_note"],
                merged["raw_excerpt"],
                now,
                keeper_id,
            ),
        )
        duplicate_ids = [int(row["notice_id"]) for row in ranked[1:] if row.get("monitor_status") != "validated"]
        if duplicate_ids:
            conn.executemany(
                """
                UPDATE lp_commitment_notice
                SET public_visible = 0,
                    monitor_status = 'duplicate',
                    updated_at = ?
                WHERE notice_id = ?
                """,
                [(now, notice_id) for notice_id in duplicate_ids],
            )
            hidden += len(duplicate_ids)
    conn.commit()
    return hidden


def clear_non_result_gp_names(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        """
        UPDATE lp_commitment_notice
        SET selected_gp_names = '',
            updated_at = ?
        WHERE COALESCE(selected_gp_names, '') <> ''
          AND COALESCE(event_type, '') NOT IN ('final_selection', 'shortlist')
        """,
        (now_utc_iso(),),
    )
    conn.commit()
    return int(cursor.rowcount or 0)


def clear_auto_candidates(conn: sqlite3.Connection, preserve_official: bool = False) -> int:
    where_clause = "monitor_status NOT IN ('validated', 'dismissed')"
    if preserve_official:
        where_clause += " AND source_type <> 'official'"
    cursor = conn.execute(f"DELETE FROM lp_commitment_notice WHERE {where_clause}")
    conn.commit()
    return int(cursor.rowcount or 0)


def split_selected_gp_names(value: str) -> list[str]:
    names: list[str] = []
    for part in re.split(r"[,;]", value or ""):
        token = normalize_whitespace(part)
        if not token:
            continue
        names.append(token)
        if "-" not in token:
            continue
        sub_tokens = [normalize_whitespace(piece) for piece in re.split(r"\s*-\s*", token) if normalize_whitespace(piece)]
        if len(sub_tokens) < 2:
            continue
        if all(is_gp_like_token(piece) for piece in sub_tokens):
            names.extend(piece for piece in sub_tokens if piece not in names)
    return names


def is_gp_like_token(value: str) -> bool:
    return bool(
        value
        and (
            re.search(r"(PE|GP|VC|증권|은행|투자|인베스트|파트너|자산운용|캐피탈|벤처)", value, flags=re.IGNORECASE)
            or len(value) >= 2
            and value.isascii()
        )
    )


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
            COALESCE(event_date, announced_date, discovered_at) DESC,
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
        cleared = clear_auto_candidates(conn, preserve_official=True)
        upserted = upsert_notices(conn, candidates)
        deduped = dedupe_stored_notices(conn)
        cleared_non_result_gp_names = clear_non_result_gp_names(conn)
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
        "deduped": deduped,
        "cleared_non_result_gp_names": cleared_non_result_gp_names,
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
