#!/usr/bin/env python
"""Fetch, tag, and export the Korea PEF daily news clipping MVP."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sqlite3
import ssl
import sys
from datetime import date, datetime, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import quote, quote_plus, urlparse
from urllib.request import Request, urlopen

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
LEGACY_SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(LEGACY_SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(LEGACY_SCRIPTS_DIR))

from daily_news_common import (
    DEFAULT_DB,
    DEFAULT_ENV,
    DEFAULT_EXPORT_DIR,
    DEFAULT_GP_ALIAS_OVERRIDES,
    DEFAULT_OVERRIDES,
    DEFAULT_RAW_DIR,
    DEFAULT_RULES,
    DEFAULT_SCHEMA,
    DEFAULT_SOURCES,
    SEOUL_TZ,
    build_comment,
    build_summary,
    choose_relevance_label,
    clean_news_title,
    fetch_text,
    google_news_rss_url,
    is_generic_aggregator_text,
    load_gp_aliases,
    load_env_file,
    load_manual_overrides,
    read_csv_rows,
    load_rules,
    load_sources,
    match_gp_entities,
    matches_allowed_publishers,
    matches_must_contain,
    normalize_date_for_report,
    normalize_whitespace,
    normalize_url,
    now_utc_iso,
    parse_article_html,
    parse_feed,
    parse_html_listing,
    save_raw_html,
    score_document,
    source_domain,
    split_news_title_badges,
    split_semicolon,
    today_seoul,
    to_iso_datetime,
    write_csv_rows,
)
from build_news_gp_update_worklist import build as build_news_gp_update_worklist
from build_service_integration_worklist import build as build_service_integration_worklist


def init_db(conn: sqlite3.Connection, schema_path: Path) -> None:
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    existing_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(news_source)").fetchall()
    }
    if "allowed_publishers" not in existing_columns:
        conn.execute("ALTER TABLE news_source ADD COLUMN allowed_publishers TEXT")
    conn.commit()


def sync_sources(conn: sqlite3.Connection, sources_path: Path) -> list[object]:
    sources = load_sources(sources_path)
    applied_at = now_utc_iso()
    for source in sources:
        conn.execute(
            """
            INSERT INTO news_source (
                source_code, source_name, source_kind, locator, publisher,
                homepage_url, article_url_regex, must_contain, allowed_publishers,
                default_tags, is_active, notes, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_code) DO UPDATE SET
                source_name = excluded.source_name,
                source_kind = excluded.source_kind,
                locator = excluded.locator,
                publisher = excluded.publisher,
                homepage_url = excluded.homepage_url,
                article_url_regex = excluded.article_url_regex,
                must_contain = excluded.must_contain,
                allowed_publishers = excluded.allowed_publishers,
                default_tags = excluded.default_tags,
                is_active = excluded.is_active,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (
                source.source_code,
                source.source_name,
                source.source_kind,
                source.locator,
                source.publisher,
                source.homepage_url,
                source.article_url_regex,
                ";".join(source.must_contain),
                ";".join(source.allowed_publishers),
                ";".join(f"{tag_type}:{tag_value}" for tag_type, tag_value in source.default_tags),
                1 if source.is_active else 0,
                source.notes,
                applied_at,
                applied_at,
            ),
        )
    conn.commit()
    return [source for source in sources if source.is_active]


def filter_sources(sources: list[object], include_codes: set[str]) -> list[object]:
    if not include_codes:
        return sources
    return [source for source in sources if source.source_code in include_codes]


def start_run(conn: sqlite3.Connection, report_date: str) -> str:
    run_id = "daily_news_" + report_date.replace("-", "") + "_" + now_utc_iso().replace(":", "").replace("+00:00", "Z")
    conn.execute(
        """
        INSERT INTO news_run(run_id, run_date, started_at, status)
        VALUES (?, ?, ?, ?)
        """,
        (run_id, report_date, now_utc_iso(), "running"),
    )
    conn.commit()
    return run_id


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    discovered_count: int,
    fetched_count: int,
    inserted_count: int,
    relevant_count: int,
    notes: str = "",
) -> None:
    conn.execute(
        """
        UPDATE news_run
        SET ended_at = ?, status = ?, discovered_count = ?, fetched_count = ?,
            inserted_count = ?, relevant_count = ?, notes = ?
        WHERE run_id = ?
        """,
        (
            now_utc_iso(),
            status,
            discovered_count,
            fetched_count,
            inserted_count,
            relevant_count,
            notes,
            run_id,
        ),
    )
    conn.commit()


def fetch_source_items(
    source: object,
    limit_per_source: int,
    verify_ssl: bool,
    report_date: str = "",
    google_date_window: bool = False,
) -> list[dict[str, str]]:
    if source.source_kind == "google_news_query":
        locator = source.locator
        if google_date_window and report_date:
            locator = google_query_for_report_date(locator, report_date)
        feed = fetch_text(google_news_rss_url(locator), verify_ssl=verify_ssl)
        rows = parse_feed(str(feed["text"]))
        return rows[:limit_per_source]
    if source.source_kind == "naver_news_api":
        return fetch_naver_news_items(source.locator, limit_per_source)
    if source.source_kind == "rss":
        feed = fetch_text(source.locator, verify_ssl=verify_ssl)
        rows = parse_feed(str(feed["text"]))
        return rows[:limit_per_source]
    if source.source_kind == "html_listing":
        page = fetch_text(source.locator, verify_ssl=verify_ssl)
        rows = parse_html_listing(source.locator, str(page["text"]), source.article_url_regex)
        return rows
    raise ValueError(f"Unsupported source_kind={source.source_kind}")


def fetch_naver_news_items(query: str, limit_per_source: int) -> list[dict[str, str]]:
    client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return []
    display = max(1, min(limit_per_source, 100))
    url = (
        "https://openapi.naver.com/v1/search/news.json"
        + f"?query={quote_plus(query)}&display={display}&start=1&sort=date"
    )
    request = Request(
        url,
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
            "Accept": "application/json",
            "User-Agent": "private-equity-daily-news/1.0",
        },
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows: list[dict[str, str]] = []
    for item in payload.get("items", []):
        title = clean_naver_html(str(item.get("title", "")))
        excerpt = clean_naver_html(str(item.get("description", "")))
        link = str(item.get("originallink") or item.get("link") or "").strip()
        if not link:
            continue
        rows.append(
            {
                "title": title,
                "link": link,
                "published_at": str(item.get("pubDate", "")),
                "excerpt": excerpt,
                "publisher": infer_publisher(link),
            }
        )
    return rows[:limit_per_source]


def clean_naver_html(value: str) -> str:
    return unescape(value.replace("<b>", "").replace("</b>", "").strip())


def google_query_for_report_date(query: str, report_date: str) -> str:
    start, end = coverage_window(report_date)
    after_date = start.date()
    before_date = end.date() + timedelta(days=1)
    query_without_window = re.sub(r"\s+when:\S+", "", query or "").strip()
    query_without_window = re.sub(r"\s+after:\d{4}-\d{2}-\d{2}", "", query_without_window).strip()
    query_without_window = re.sub(r"\s+before:\d{4}-\d{2}-\d{2}", "", query_without_window).strip()
    return f"{query_without_window} after:{after_date.isoformat()} before:{before_date.isoformat()}"


def google_news_encoded_id(source_url: str) -> str:
    parsed = urlparse(source_url or "")
    host = parsed.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    if host != "news.google.com":
        return ""
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[-2] in {"articles", "read"}:
        return path_parts[-1]
    return ""


def decode_legacy_google_news_url(encoded_id: str) -> str:
    try:
        decoded = base64.urlsafe_b64decode(encoded_id + "==").decode("latin1")
    except Exception:
        return ""
    prefix = b"\x08\x13\x22".decode("latin1")
    if decoded.startswith(prefix):
        decoded = decoded[len(prefix) :]
    suffix = b"\xd2\x01\x00".decode("latin1")
    if decoded.endswith(suffix):
        decoded = decoded[: -len(suffix)]
    if not decoded:
        return ""
    length = bytearray(decoded, "latin1")[0]
    if length >= 0x80:
        decoded = decoded[2 : length + 1]
    else:
        decoded = decoded[1 : length + 1]
    return decoded if decoded.startswith("http") else ""


def extract_google_news_decode_params(html_text: str, encoded_id: str) -> tuple[str, str]:
    tag_match = re.search(
        r"<div\b[^>]*data-n-a-id=\"" + re.escape(encoded_id) + r"\"[^>]*>",
        html_text,
    )
    if not tag_match:
        tag_match = re.search(r"<div\b[^>]*data-n-a-id=\"[^\"]+\"[^>]*data-n-a-ts=\"[^\"]+\"[^>]*>", html_text)
    if not tag_match:
        return "", ""
    attrs = dict(re.findall(r"(data-n-a-(?:sg|ts))=\"([^\"]+)\"", tag_match.group(0)))
    return unescape(attrs.get("data-n-a-sg", "")), unescape(attrs.get("data-n-a-ts", ""))


def parse_google_news_batch_response(response_text: str) -> str:
    if "\n\n" not in response_text:
        return ""
    try:
        payload = json.loads(response_text.split("\n\n", 1)[1])
    except json.JSONDecodeError:
        return ""
    for item in payload:
        if not isinstance(item, list) or len(item) < 3 or item[1] != "Fbv4je" or not item[2]:
            continue
        try:
            decoded = json.loads(str(item[2]))
        except json.JSONDecodeError:
            continue
        if len(decoded) >= 2 and decoded[0] == "garturlres" and str(decoded[1]).startswith("http"):
            return str(decoded[1])
    return ""


def decode_google_news_url_with_params(encoded_id: str, signature: str, timestamp: str, verify_ssl: bool) -> str:
    payload = [
        "Fbv4je",
        (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,'
            f'null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{encoded_id}",{timestamp},"{signature}"]'
        ),
    ]
    request = Request(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        data=f"f.req={quote(json.dumps([[payload]]))}".encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
            ),
        },
    )
    context = None
    if not verify_ssl:
        context = ssl._create_unverified_context()
    with urlopen(request, timeout=10, context=context) as response:
        text = response.read().decode("utf-8", errors="replace")
    return parse_google_news_batch_response(text)


def resolve_google_news_url(source_url: str, verify_ssl: bool = True) -> str:
    encoded_id = google_news_encoded_id(source_url)
    if not encoded_id:
        return source_url
    legacy_url = decode_legacy_google_news_url(encoded_id)
    if legacy_url:
        return legacy_url
    try:
        page = fetch_text(f"https://news.google.com/articles/{encoded_id}", timeout=10, verify_ssl=verify_ssl)
        signature, timestamp = extract_google_news_decode_params(str(page["text"]), encoded_id)
        if not signature or not timestamp:
            page = fetch_text(source_url, timeout=10, verify_ssl=verify_ssl)
            signature, timestamp = extract_google_news_decode_params(str(page["text"]), encoded_id)
        if not signature or not timestamp:
            return source_url
        decoded_url = decode_google_news_url_with_params(encoded_id, signature, timestamp, verify_ssl)
        return decoded_url or source_url
    except Exception:
        return source_url


PUBLISHER_BY_DOMAIN = {
    "dealsite.co.kr": "딜사이트",
    "thebell.co.kr": "더벨",
    "bloter.net": "블로터",
    "newstomato.com": "뉴스토마토",
    "news.tomato.co.kr": "뉴스토마토",
    "newstof.com": "뉴스톱",
    "newstopkorea.com": "뉴스톱",
    "hankyung.com": "한국경제",
    "mk.co.kr": "매일경제",
    "sedaily.com": "서울경제",
    "edaily.co.kr": "이데일리",
    "newsis.com": "뉴시스",
    "biz.chosun.com": "조선비즈",
    "asiae.co.kr": "아시아경제",
    "fnnews.com": "파이낸셜뉴스",
    "wowtv.co.kr": "한국경제TV",
    "news.einfomax.co.kr": "연합인포맥스",
    "mt.co.kr": "머니투데이",
    "news.mt.co.kr": "머니투데이",
    "newspim.com": "뉴스핌",
    "investchosun.com": "인베스트조선",
    "kgnews.co.kr": "경기신문",
    "4th.kr": "포쓰저널",
    "newstof.com": "뉴스톱",
    "etoday.co.kr": "이투데이",
    "joseilbo.com": "조세일보",
    "dealsitetv.com": "DealSite경제TV",
    "greened.kr": "녹색경제신문",
    "joongangenews.com": "중앙이코노미뉴스",
    "dailypop.kr": "데일리팝",
    "dailybrief.co.kr": "데일리브리프",
    "businesspost.co.kr": "비즈니스포스트",
    "fieldnews.kr": "필드뉴스",
    "livebiz.today": "생생비즈플러스",
    "skyedaily.com": "스카이데일리",
    "biztribune.co.kr": "비즈트리뷴",
    "ebn.co.kr": "EBN",
    "busan.com": "부산일보",
    "heraldcorp.com": "헤럴드경제",
    "ttlnews.com": "퍼블릭뉴스통신",
    "financialpost.co.kr": "파이낸셜포스트",
    "cfnews.kr": "CF뉴스",
    "ekn.kr": "에너지경제",
    "ezyeconomy.com": "이지경제",
    "sidae.com": "동행미디어 시대",
    "zdnet.co.kr": "ZDNet Korea",
    "wikileaks-kr.org": "위키리크스한국",
    "daily.hankooki.com": "데일리한국",
    "dt.co.kr": "디지털타임스",
    "news.mtn.co.kr": "머니투데이방송",
    "inews24.com": "아이뉴스24",
    "donga.com": "동아일보",
    "pointdaily.co.kr": "포인트데일리",
    "it.chosun.com": "IT조선",
}


def infer_publisher(url: str, fallback: str = "") -> str:
    host = urlparse(url or "").netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    for domain, publisher in PUBLISHER_BY_DOMAIN.items():
        if host == domain or host.endswith("." + domain):
            return publisher
    if fallback and fallback != "Naver News API":
        return fallback
    return host or fallback


def upsert_document(
    conn: sqlite3.Connection,
    run_id: str,
    source: object,
    report_date: str,
    candidate: dict[str, object],
    min_score: float,
) -> tuple[int, bool]:
    existing = conn.execute(
        """
        SELECT news_id
        FROM news_document
        WHERE normalized_source_url = ?
        """,
        (str(candidate["normalized_source_url"]),),
    ).fetchone()
    force_include = bool(candidate.get("force_include"))
    force_exclude = bool(candidate.get("force_exclude"))
    is_pe_relevant, relevance_label = choose_relevance_label(float(candidate["relevance_score"]), min_score, force_include, force_exclude)
    payload_json = json.dumps(candidate.get("raw_payload", {}), ensure_ascii=False)
    applied_at = now_utc_iso()
    conn.execute(
        """
        INSERT INTO news_document (
            run_id, source_code, source_url, normalized_source_url, source_domain,
            publisher, title, published_at, discovered_at, fetched_at, document_type,
            language_code, raw_html_path, meta_description, excerpt_text, body_text,
            content_hash, relevance_score, relevance_label, comment_text, review_status,
            is_pe_relevant, raw_payload_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(normalized_source_url) DO UPDATE SET
            run_id = excluded.run_id,
            source_code = excluded.source_code,
            source_url = excluded.source_url,
            source_domain = excluded.source_domain,
            publisher = excluded.publisher,
            title = excluded.title,
            published_at = COALESCE(excluded.published_at, news_document.published_at),
            discovered_at = excluded.discovered_at,
            fetched_at = excluded.fetched_at,
            document_type = excluded.document_type,
            raw_html_path = excluded.raw_html_path,
            meta_description = excluded.meta_description,
            excerpt_text = excluded.excerpt_text,
            body_text = excluded.body_text,
            content_hash = excluded.content_hash,
            relevance_score = excluded.relevance_score,
            relevance_label = excluded.relevance_label,
            comment_text = excluded.comment_text,
            review_status = excluded.review_status,
            is_pe_relevant = excluded.is_pe_relevant,
            raw_payload_json = excluded.raw_payload_json,
            updated_at = excluded.updated_at
        """,
        (
            run_id,
            source.source_code,
            str(candidate["source_url"]),
            str(candidate["normalized_source_url"]),
            str(candidate["source_domain"]),
            str(candidate["publisher"]),
            str(candidate["title"]),
            str(candidate["published_at"]),
            report_date,
            str(candidate["fetched_at"]),
            str(candidate["document_type"]),
            "ko",
            str(candidate["raw_html_path"]),
            str(candidate["meta_description"]),
            str(candidate["summary_text"]),
            str(candidate["body_text"]),
            str(candidate["content_hash"]),
            float(candidate["relevance_score"]),
            relevance_label,
            str(candidate["comment_text"]),
            str(candidate["review_status"]),
            is_pe_relevant,
            payload_json,
            applied_at,
            applied_at,
        ),
    )
    row = conn.execute(
        """
        SELECT news_id
        FROM news_document
        WHERE normalized_source_url = ?
        """,
        (str(candidate["normalized_source_url"]),),
    ).fetchone()
    if row is None:
        raise RuntimeError("Failed to read back upserted news_document row")
    return int(row[0]), existing is None


def reuse_cached_document_for_run(
    conn: sqlite3.Connection,
    run_id: str,
    report_date: str,
    source_url: str,
) -> bool:
    normalized = normalize_url(source_url)
    row = conn.execute(
        """
        SELECT news_id
        FROM news_document
        WHERE normalized_source_url = ?
           OR source_url = ?
           OR normalized_source_url = (
                SELECT normalized_source_url
                FROM news_document
                WHERE source_url = ?
                LIMIT 1
           )
        LIMIT 1
        """,
        (normalized, source_url, source_url),
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        """
        UPDATE news_document
        SET run_id = ?,
            discovered_at = ?,
            updated_at = ?
        WHERE news_id = ?
        """,
        (run_id, report_date, now_utc_iso(), int(row[0])),
    )
    return True


def replace_tags_and_links(conn: sqlite3.Connection, news_id: int, tags: list[dict[str, object]], links: list[dict[str, object]]) -> None:
    conn.execute("DELETE FROM news_tag WHERE news_id = ?", (news_id,))
    conn.execute("DELETE FROM news_entity_link WHERE news_id = ?", (news_id,))
    created_at = now_utc_iso()
    for tag in tags:
        conn.execute(
            """
            INSERT OR IGNORE INTO news_tag(news_id, tag_type, tag_value, tag_source, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                news_id,
                str(tag.get("tag_type", "")),
                str(tag.get("tag_value", "")),
                str(tag.get("tag_source", "")),
                float(tag.get("confidence", 0) or 0),
                created_at,
            ),
        )
    for link in links:
        conn.execute(
            """
            INSERT OR IGNORE INTO news_entity_link(
                news_id, entity_type, entity_ref, entity_name, matched_alias,
                match_field, link_source, confidence, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                news_id,
                str(link.get("entity_type", "")),
                str(link.get("entity_ref", "")),
                str(link.get("entity_name", "")),
                str(link.get("matched_alias", "")),
                str(link.get("match_field", "")),
                str(link.get("link_source", "")),
                float(link.get("confidence", 0) or 0),
                created_at,
            ),
        )


def load_run_candidate_rows(conn: sqlite3.Connection, run_id: str, report_date: str) -> list[dict[str, object]]:
    cursor = conn.execute(
        """
        SELECT
            vr.news_id,
            vr.publisher,
            vr.title,
            vr.source_url,
            vr.normalized_source_url,
            vr.published_at,
            vr.discovered_at,
            vr.meta_description,
            vr.excerpt_text,
            vr.relevance_score,
            vr.relevance_label,
            vr.comment_text,
            vr.review_status,
            COALESCE(vr.section_tags, '') AS section_tags,
            COALESCE(vr.section_override_tags, '') AS section_override_tags,
            COALESCE(vr.topic_tags, '') AS topic_tags,
            COALESCE(vr.document_type_tags, '') AS document_type_tags,
            COALESCE(vr.gp_names, '') AS gp_names
        FROM v_news_relevant vr
        WHERE vr.run_id = ?
          AND vr.is_pe_relevant = 1
        ORDER BY vr.relevance_score DESC, COALESCE(vr.published_at, vr.discovered_at) DESC, vr.news_id DESC
        """,
        (run_id,),
    )
    rows: list[dict[str, object]] = []
    for row in cursor.fetchall():
        if is_generic_aggregator_text(str(row[2] or "")) and is_generic_aggregator_text(str(row[8] or row[7] or "")):
            continue
        published_at = str(row[5] or "")
        discovered_at = str(row[6] or "")
        if not is_in_coverage_window(published_at, discovered_at, report_date):
            continue
        rows.append(
            {
                "news_id": int(row[0]),
                "publisher": str(row[1] or ""),
                "title": str(row[2] or ""),
                "source_url": str(row[3] or ""),
                "normalized_source_url": str(row[4] or ""),
                "published_at": published_at,
                "report_date": report_date,
                "summary_text": str(row[8] or row[7] or ""),
                "relevance_score": float(row[9] or 0),
                "relevance_label": str(row[10] or ""),
                "comment_text": str(row[11] or ""),
                "review_status": str(row[12] or ""),
                "section_tags": str(row[13] or ""),
                "section_override_tags": str(row[14] or ""),
                "topic_tags": str(row[15] or ""),
                "document_type_tags": str(row[16] or ""),
                "gp_names": str(row[17] or ""),
            }
        )
    return rows


def build_export_rows(
    conn: sqlite3.Connection,
    run_id: str,
    report_date: str,
    brief_limit: int,
    out_dir: Path,
) -> list[dict[str, object]]:
    candidates = load_run_candidate_rows(conn, run_id, report_date)
    previous_keys = load_previous_export_keys(out_dir, report_date)
    eligible: list[dict[str, object]] = []
    for row in candidates:
        quality_score, quality_reason = editorial_quality(row)
        row["quality_score"] = quality_score
        row["quality_reason"] = quality_reason
        if is_previous_export(row, previous_keys) and str(row.get("review_status", "")) != "force_include":
            continue
        if should_export_row(row):
            eligible.append(row)
    eligible.sort(key=quality_sort_key)
    return select_brief_rows(eligible, brief_limit)


def load_previous_export_keys(out_dir: Path, report_date: str) -> dict[str, set[str]]:
    report_key = report_date.replace("-", "")
    url_keys: set[str] = set()
    title_keys: set[str] = set()
    patterns = [
        "daily_news_brief_*.md",
        "daily_news_final_*.md",
    ]
    for pattern in patterns:
        for path in out_dir.glob(pattern):
            match = re.fullmatch(r"daily_news_(?:brief|final)_(\d{8})\.md", path.name)
            if not match:
                continue
            file_date = match.group(1)
            if file_date >= report_key:
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                match_line = re.match(r"- \[(.+?)\]\((.+?)\)", line.strip())
                if match_line:
                    add_previous_key(match_line.group(2), match_line.group(1), url_keys, title_keys)
    return {"urls": url_keys, "titles": title_keys}


def add_previous_key(url: str, title: str, url_keys: set[str], title_keys: set[str]) -> None:
    normalized = normalize_url(url) if url else ""
    if normalized:
        url_keys.add(normalized)
    title_key = normalize_title_key(title)
    if title_key:
        title_keys.add(title_key)


def is_previous_export(row: dict[str, object], previous_keys: dict[str, set[str]]) -> bool:
    url = str(row.get("normalized_source_url") or row.get("source_url") or "")
    normalized_url = normalize_url(url) if url else ""
    title_key = normalize_title_key(str(row.get("title", "")))
    if normalized_url and normalized_url in previous_keys["urls"]:
        return True
    return bool(title_key and title_key in previous_keys["titles"])


SECTION_ORDER = ["AI_PE", "Deal", "LP", "GP", "Market"]
SECTION_DISPLAY_LIMIT = 12
SECTION_MIN_SELECTION = {"AI_PE": 1, "LP": 2, "GP": 2}
BRIEFING_CUTOFF_HOUR = 8
BRIEFING_CUTOFF_MINUTE = 30
SECTION_LABELS = {
    "AI_PE": "AI & PE",
    "Deal": "Deal",
    "LP": "LP",
    "GP": "GP",
    "Market": "Market",
}
SECTION_LABEL_TO_CODE = {label: code for code, label in SECTION_LABELS.items()}
SECTION_LABEL_TO_CODE.update(
    {
        "오늘의 핵심": "Market",
        "시장·전략": "Market",
        "LP / 출자자": "LP",
        "LP 출자": "LP",
        "펀드·출자": "GP",
        "펀드레이징": "GP",
        "펀드레이징 / 펀드 결성": "GP",
        "딜 / 엑시트": "Deal",
        "거래·엑시트": "Deal",
        "크레딧 / 레버리지": "Deal",
        "크레딧·레버리지": "Deal",
        "크레딧·파이낸싱": "Deal",
        "포트폴리오 / 밸류업": "Deal",
        "포트폴리오·밸류업": "Deal",
        "규제 / 리스크": "Market",
        "규제·리스크": "Market",
        "규제·정책": "Market",
        "GP / 운용사": "GP",
        "GP·운용사": "GP",
        "운용사": "GP",
        "AI & PE": "AI_PE",
        "AI_PE": "AI_PE",
        "AI": "AI_PE",
        "Fundraising": "GP",
        "Credit": "Deal",
        "Portfolio": "Deal",
        "Regulation": "Market",
    }
)
EXPORT_MIN_QUALITY_SCORE = 8.0

PUBLISHER_QUALITY_WEIGHT = {
    "인베스트조선": 3.0,
    "더벨": 3.0,
    "딜사이트": 2.5,
    "뉴스토마토": 2.0,
    "뉴스톱": 1.5,
    "이데일리": 2.0,
    "한국경제": 2.0,
    "서울경제": 2.0,
    "연합인포맥스": 2.0,
    "머니투데이": 1.5,
    "블로터": 1.5,
    "뉴스톱": 1.5,
    "조선비즈": 1.2,
    "매일경제": 1.2,
    "아시아경제": 1.0,
    "파이낸셜뉴스": 1.0,
    "한국경제TV": 0.8,
    "뉴스핌": 0.8,
    "이투데이": 0.6,
    "경기신문": 0.5,
    "뉴시스": 0.4,
}
PUBLISHER_SAFETY_NET = {"뉴스톱", "뉴스토마토", "딜사이트", "블로터"}

VISIBLE_PE_KEYWORDS = [
    "인공지능",
    "생성형 AI",
    "사모펀드",
    "PEF",
    "PE",
    "M&A",
    "private equity",
    "프라이빗에쿼티",
    "운용사",
    "GP",
    "LP",
    "출자자",
    "기관투자가",
    "인수",
    "매각",
    "엑시트",
    "출자",
    "출자사업",
    "위탁운용",
    "커밋먼트",
    "공제사업",
    "공제회",
    "연기금",
    "자금배분",
    "자산배분",
    "대체투자",
    "자산운용본부",
    "자산운용본부장",
    "노란우산공제",
    "분배금",
    "DPI",
    "펀드",
    "펀드레이징",
    "펀드 결성",
    "클로징",
    "블라인드",
    "프라이빗크레딧",
    "private credit",
    "인수금융",
    "밸류업",
    "바이아웃",
    "MBK",
    "IMM",
    "VIG",
    "글랜우드",
    "스틱",
    "큐캐피탈",
    "유암코",
    "KCGI",
    "한앤컴퍼니",
    "KKR",
    "EQT",
    "CVC",
    "TPG",
    "칼라일",
    "블랙스톤",
]

LOW_VALUE_TITLE_KEYWORDS = [
    "로비",
    "광산",
    "우주정거장",
    "대통령",
    "정치",
    "갑질",
    "폭로",
]
WEAK_CONTEXT_TITLE_KEYWORDS = [
    "감사보고서",
    "외감",
    "장외파생",
    "종합 IB",
    "e종목",
    "임상",
    "주가",
    "실적",
]
TITLE_RISK_KEYWORDS = [
    "유탄",
    "리스크",
    "위법",
    "금감원",
    "금융감독원",
    "제재",
    "소송",
]
HIGH_VALUE_TITLE_KEYWORDS = [
    "인공지능",
    "생성형 AI",
    "데이터센터",
    "AI 인프라",
    "성장금융",
    "출자사업",
    "위탁운용",
    "운용사 선정",
    "출자자",
    "기관투자가",
    "대체투자",
    "자산운용본부",
    "공제사업",
    "커밋먼트",
    "분배금",
    "DPI",
    "펀드 결성",
    "펀드레이징",
    "클로징",
    "최종 결성",
    "파이널 클로징",
    "공동투자 펀드",
    "블라인드펀드",
    "프라이빗크레딧",
    "인수금융",
    "리캡",
    "리캡탈라이제이션",
    "컨티뉴에이션 펀드",
    "그로쓰캡",
    "PEF",
    "사모펀드",
    "GP",
    "LP",
]

SECTION_KEYWORDS = {
    "Regulation": [
        "규제",
        "상법",
        "자본시장법",
        "법 개정",
        "법안",
        "금융위",
        "금융위원회",
        "금감원",
        "금융감독원",
        "금투협",
        "공정위",
        "제재",
        "내부통제",
        "위법",
        "소송",
        "과세",
        "세제",
        "리스크",
        "유탄",
    ],
    "Deal": [
        "M&A",
        "인수",
        "매각",
        "매물",
        "딜",
        "엑시트",
        "회수",
        "청산",
        "상장폐지",
        "블록딜",
        "우선협상",
        "예비입찰",
        "본입찰",
        "매각주관",
        "주관사",
        "바이아웃",
        "세컨더리",
        "컨티뉴에이션",
        "continuation",
        "IPO",
        "구주",
        "지분",
    ],
    "LP": [
        "LP",
        "Limited Partner",
        "allocator",
        "allocators",
        "출자자",
        "기관투자가",
        "출자",
        "출자사업",
        "출자확약",
        "commitment",
        "commitments",
        "위탁운용",
        "운용사 선정",
        "mandate",
        "mandates",
        "RFP",
        "active fund search",
        "investment plan",
        "investment plans",
        "자금배분",
        "자산배분",
        "대체투자",
        "공제사업",
        "자산운용본부",
        "자산운용본부장",
        "자산운용부서장",
        "투자심의",
        "투자심의위원회",
        "리업",
        "재출자",
        "캐피털콜",
        "capital call",
        "분배금",
        "DPI",
        "TVPI",
        "net-to-LP",
        "연기금",
        "공제회",
        "중소기업중앙회",
        "노란우산공제",
        "경찰공제회",
        "신협중앙회",
        "국민연금",
        "사학연금",
        "교직원공제",
        "행정공제",
        "군인공제",
        "새마을금고",
        "모태펀드",
        "성장금융",
        "한국벤처투자",
        "앵커",
        "앵커 LP",
        "LP 세컨더리",
        "LP 지분",
    ],
    "Fundraising": [
        "블라인드펀드",
        "펀드 결성",
        "결성",
        "펀드레이징",
        "fundraising",
        "fundraise",
        "펀드 조성",
        "펀드 도전",
        "약정총액",
        "목표액",
        "1차 클로징",
        "첫 클로징",
        "최종 결성",
        "최종 클로징",
        "파이널 클로징",
        "first close",
        "final close",
        "fund close",
        "close fund",
        "앵커 출자",
        "공동투자",
        "co-investment",
        "co-invest",
        "세컨더리 펀드",
        "컨티뉴에이션 펀드",
        "Continuation fund",
        "Continuation vehicle",
    ],
    "Credit": [
        "프라이빗크레딧",
        "private credit",
        "사모대출",
        "대출펀드",
        "인수금융",
        "리캡",
        "리캡탈라이제이션",
        "리파이낸싱",
        "refinancing",
        "레버리지",
        "leveraged loan",
        "unitranche",
        "CLO",
        "하이일드",
        "메자닌",
        "CB",
        "BW",
        "EB",
        "전환사채",
        "교환사채",
        "신주인수권부사채",
        "대주단",
    ],
    "Portfolio": [
        "포트폴리오",
        "밸류업",
        "value-up",
        "구조조정",
        "턴어라운드",
        "PMI",
        "인수 후 통합",
        "실적",
        "주주환원",
        "배당",
        "리파이낸싱",
        "차입금",
        "운영 개선",
    ],
    "GP": [
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
    ],
}

STRONG_DEAL_KEYWORDS = [
    "M&A",
    "인수",
    "매각",
    "품는다",
    "사들인다",
    "지분매각",
    "회수",
    "청산",
    "매물",
    "딜",
    "엑시트",
    "상장폐지",
    "블록딜",
    "우선협상",
    "예비입찰",
    "본입찰",
    "매각주관",
    "바이아웃",
    "세컨더리",
    "컨티뉴에이션",
    "continuation",
    "지분투자",
    "투자유치",
    "투자 집행",
]
CONTENT_DEAL_KEYWORDS = [keyword for keyword in STRONG_DEAL_KEYWORDS if keyword not in {"딜"}]

LP_COMMITMENT_EVENT_KEYWORDS = [
    "출자사업",
    "출자공고",
    "출자 공고",
    "위탁운용",
    "운용사 선정",
    "출자확약",
    "앵커 출자",
    "민간모펀드",
    "국민성장펀드",
    "모태펀드",
    "PEF 출자",
    "커밋먼트",
    "commitment",
    "RFP",
    "mandate",
]

GP_STRATEGY_EVENT_KEYWORDS = [
    "대표",
    "파트너",
    "심사역",
    "인력",
    "조직",
    "복귀",
    "선임",
    "영입",
    "하우스 전략",
    "운용전략",
    "플랫폼",
]

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

AI_SHORT_RE = re.compile(r"(?<![A-Za-z])AI(?![A-Za-z])", re.IGNORECASE)


def contains_any_keyword(text: str, keywords: list[str]) -> bool:
    lower_text = text.lower()
    return any(keyword.lower() in lower_text for keyword in keywords)


def split_csv_values(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def has_fundraising_title_signal(title: str) -> bool:
    return contains_any_keyword(title, SECTION_KEYWORDS["Fundraising"]) or (
        "펀드" in title and contains_any_keyword(title, ["결성", "모집", "소진", "펀딩"])
    )


def has_ai_pe_theme(text: str) -> bool:
    has_ai_signal = bool(AI_SHORT_RE.search(text)) or contains_any_keyword(text, AI_THEME_KEYWORDS)
    if not has_ai_signal:
        return False
    return contains_any_keyword(
        text,
        VISIBLE_PE_KEYWORDS
        + STRONG_DEAL_KEYWORDS
        + SECTION_KEYWORDS["LP"]
        + SECTION_KEYWORDS["Fundraising"]
        + SECTION_KEYWORDS["GP"],
    )


def has_lp_focus_signal(text: str) -> bool:
    return contains_any_keyword(text, SECTION_KEYWORDS["LP"] + LP_COMMITMENT_EVENT_KEYWORDS)


def has_gp_focus_signal(text: str) -> bool:
    return (
        has_fundraising_title_signal(text)
        or contains_any_keyword(text, GP_STRATEGY_EVENT_KEYWORDS)
        or contains_any_keyword(text, SECTION_KEYWORDS["GP"])
    )


def section_override(row: dict[str, object]) -> str:
    for section in split_csv_values(str(row.get("section_override_tags", ""))):
        mapped = SECTION_LABEL_TO_CODE.get(section)
        if mapped:
            return mapped
        if section in SECTION_ORDER:
            return section
    return ""


def primary_section(row: dict[str, object]) -> str:
    override = section_override(row)
    if override:
        return override
    raw_sections = []
    for value in split_csv_values(str(row.get("section_tags", ""))):
        raw_sections.append(SECTION_LABEL_TO_CODE.get(value, value))
    topics = {value.strip() for value in str(row.get("topic_tags", "")).split(",") if value.strip()}
    title = str(row.get("title", ""))
    content = " ".join(
        [
            title,
            str(row.get("summary_text", "")),
            str(row.get("gp_names", "")),
        ]
    )
    if has_ai_pe_theme(content):
        return "AI_PE"
    if contains_any_keyword(title, SECTION_KEYWORDS["Credit"]) and has_fundraising_title_signal(title):
        return "GP"
    if contains_any_keyword(title, SECTION_KEYWORDS["Credit"]):
        return "Deal"
    if has_fundraising_title_signal(title):
        return "GP"
    if contains_any_keyword(title, STRONG_DEAL_KEYWORDS):
        return "Deal"
    if contains_any_keyword(title, SECTION_KEYWORDS["Portfolio"]):
        return "Deal"
    if has_lp_focus_signal(title):
        return "LP"
    if has_gp_focus_signal(title):
        return "GP"
    if contains_any_keyword(title, TITLE_RISK_KEYWORDS):
        return "Market"
    if contains_any_keyword(title, SECTION_KEYWORDS["Regulation"]):
        return "Market"
    if contains_any_keyword(content, SECTION_KEYWORDS["Credit"]) and has_fundraising_title_signal(title):
        return "GP"
    if contains_any_keyword(content, SECTION_KEYWORDS["Credit"]):
        return "Deal"
    if contains_any_keyword(content, CONTENT_DEAL_KEYWORDS):
        return "Deal"
    if contains_any_keyword(content, SECTION_KEYWORDS["Portfolio"]):
        return "Deal"
    if has_lp_focus_signal(content):
        return "LP"
    if has_gp_focus_signal(content):
        return "GP"
    if "Fundraising" in topics:
        return "GP"
    if "Credit" in topics:
        return "Deal"
    if "Portfolio" in topics:
        return "Deal"
    if "Deal" in topics:
        return "Deal"
    if "LP Commitment" in topics or "LP" in topics:
        return "LP"
    if contains_any_keyword(content, SECTION_KEYWORDS["Regulation"]):
        return "Market"
    if "Regulation" in topics:
        return "Market"
    if "GP" in topics or "PEF" in topics and contains_any_keyword(content, SECTION_KEYWORDS["GP"]):
        return "GP"
    for section in SECTION_ORDER:
        if section in raw_sections:
            if section == "LP" and not has_lp_focus_signal(content):
                continue
            return section
    return "Market"


def quality_sort_key(row: dict[str, object]) -> tuple[float, float, int]:
    return (
        -float(row.get("quality_score", 0) or 0),
        -float(row.get("relevance_score", 0) or 0),
        -int(row.get("news_id", 0) or 0),
    )


def visible_quality_text(row: dict[str, object]) -> str:
    return " ".join(
        [
            str(row.get("title", "")),
            str(row.get("summary_text", "")),
            str(row.get("gp_names", "")),
        ]
    )


def editorial_quality(row: dict[str, object]) -> tuple[float, str]:
    score = float(row.get("relevance_score", 0) or 0)
    reasons: list[str] = [f"base {score:.1f}"]
    publisher = str(row.get("publisher", "")).strip()
    publisher_weight = PUBLISHER_QUALITY_WEIGHT.get(publisher, 0.0)
    if publisher_weight:
        score += publisher_weight
        reasons.append(f"source +{publisher_weight:g}")

    title = str(row.get("title", ""))
    text = visible_quality_text(row)
    signal_strength = "weak"
    title_has_direct_signal = contains_any_keyword(title, VISIBLE_PE_KEYWORDS)
    text_has_direct_signal = contains_any_keyword(text, VISIBLE_PE_KEYWORDS)
    if contains_any_keyword(title, VISIBLE_PE_KEYWORDS):
        signal_strength = "title"
        score += 2.0
        reasons.append("title PE signal")
    elif text_has_direct_signal:
        signal_strength = "body"
        score += 0.8
        reasons.append("body PE signal")
    else:
        score -= 6.0
        reasons.append("weak PE signal")
    high_value_headline = contains_any_keyword(title, HIGH_VALUE_TITLE_KEYWORDS)
    if high_value_headline:
        score += 2.5
        reasons.append("high-value headline")
    if contains_any_keyword(title, STRONG_DEAL_KEYWORDS):
        score += 1.2
        reasons.append("deal headline")
    elif has_fundraising_title_signal(title):
        score += 0.8
        reasons.append("fundraising headline")

    section = primary_section(row)
    if section == "AI_PE" and signal_strength != "weak":
        score += 1.5
        reasons.append("AI & PE priority")
    elif section == "Deal" and signal_strength != "weak":
        score += 1.0
        reasons.append("deal priority")
    elif section == "LP" and signal_strength != "weak":
        score += 1.2
        reasons.append("LP priority")
    elif section == "GP" and signal_strength != "weak":
        score += 1.0
        reasons.append("GP priority")

    if publisher in PUBLISHER_SAFETY_NET and signal_strength == "title" and section in {"AI_PE", "Deal", "LP", "GP"}:
        score += 1.5
        reasons.append("publisher safety net")

    if str(row.get("source_url", "")).startswith("https://news.google.com/"):
        score -= 2.5
        reasons.append("google redirect")
    if contains_any_keyword(title, LOW_VALUE_TITLE_KEYWORDS) and not title_has_direct_signal:
        score -= 2.0
        reasons.append("weak headline")
    if signal_strength == "body" and not high_value_headline:
        if contains_any_keyword(title, WEAK_CONTEXT_TITLE_KEYWORDS):
            score -= 8.0
            reasons.append("weak context headline")
        elif not contains_any_keyword(
            title,
            STRONG_DEAL_KEYWORDS
            + SECTION_KEYWORDS["LP"]
            + SECTION_KEYWORDS["Fundraising"]
            + SECTION_KEYWORDS["Credit"],
        ):
            score -= 3.0
            reasons.append("PE only in body")
    if "press_release" in split_csv_values(str(row.get("document_type_tags", ""))):
        score -= 0.5
        reasons.append("press release")
    if section_override(row):
        score += 10.0
        reasons.append("manual category")
    if str(row.get("review_status", "")) == "force_include":
        score += 20.0
        reasons.append("manual include")
    return round(score, 2), "; ".join(reasons)


def should_export_row(row: dict[str, object]) -> bool:
    review_status = str(row.get("review_status", ""))
    if review_status == "force_exclude":
        return False
    if review_status == "force_include":
        return True
    if str(row.get("source_url", "")).startswith("https://news.google.com/"):
        return False
    return float(row.get("quality_score", 0) or 0) >= EXPORT_MIN_QUALITY_SCORE


def select_brief_rows(rows: list[dict[str, object]], brief_limit: int) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    section_counts = {section: 0 for section in SECTION_ORDER}
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    def add_row(row: dict[str, object]) -> bool:
        url_key = str(row.get("normalized_source_url") or row.get("source_url") or "")
        title_key = normalize_title_key(str(row.get("title", "")))
        if url_key and url_key in seen_urls:
            return False
        if title_key and title_key in seen_titles:
            return False
        section = primary_section(row)
        if section_counts.get(section, 0) >= SECTION_DISPLAY_LIMIT:
            return False
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        section_counts[section] = section_counts.get(section, 0) + 1
        selected.append(row)
        return True

    minimum_selection = SECTION_MIN_SELECTION if brief_limit >= 8 else {"AI_PE": 1}
    for reserve_section, reserve_count in minimum_selection.items():
        for row in rows:
            if len(selected) >= brief_limit:
                break
            if section_counts.get(reserve_section, 0) >= reserve_count:
                break
            if primary_section(row) != reserve_section:
                continue
            add_row(row)

    for row in rows:
        if len(selected) >= brief_limit:
            break
        add_row(row)
        if len(selected) >= brief_limit:
            break
    return selected


def group_export_rows(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped = {section: [] for section in SECTION_ORDER}
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for row in rows:
        url_key = str(row.get("normalized_source_url") or row.get("source_url") or "")
        title_key = normalize_title_key(str(row.get("title", "")))
        if url_key and url_key in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        section = primary_section(row)
        if len(grouped.setdefault(section, [])) >= SECTION_DISPLAY_LIMIT:
            continue
        grouped[section].append(row)
    return grouped


def normalize_title_key(title: str) -> str:
    value = clean_news_title(title)
    value = re.sub(r"\s+-\s+[^-]+$", "", value)
    value = re.sub(r"\.{2,}|…+", "", value)
    value = re.sub(r"[\[\]\"'‘’“”<>(){}|·:：,\s]+", "", value)
    return value.lower()[:42]


def clean_display_title(title: str, publisher: str = "") -> str:
    display_title, _badges = split_news_title_badges(title, publisher)
    return display_title


def display_source(row: dict[str, object]) -> str:
    return str(row.get("publisher", "")).strip()


def coverage_window(report_date: str) -> tuple[datetime, datetime]:
    parsed = date.fromisoformat(report_date)
    end = datetime(
        parsed.year,
        parsed.month,
        parsed.day,
        BRIEFING_CUTOFF_HOUR,
        BRIEFING_CUTOFF_MINUTE,
        tzinfo=SEOUL_TZ,
    )
    lookback_days = 3 if parsed.weekday() == 0 else 1
    return end - timedelta(days=lookback_days), end


def coverage_window_label(report_date: str) -> str:
    try:
        start, end = coverage_window(report_date)
    except ValueError:
        return "기준 : 최근 24시간 브리핑"
    label = "주말 포함 최근 72시간 브리핑" if end - start >= timedelta(days=3) else "최근 24시간 브리핑"
    return (
        f"기준 : {label} "
        f"({start.strftime('%Y-%m-%d %H:%M')} ~ {end.strftime('%Y-%m-%d %H:%M')}, KST)"
    )


def parse_coverage_datetime(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SEOUL_TZ)
    return parsed.astimezone(SEOUL_TZ)


def is_in_coverage_window(published_at: str, discovered_at: str, report_date: str) -> bool:
    try:
        start, end = coverage_window(report_date)
    except ValueError:
        return True
    published_dt = parse_coverage_datetime(published_at)
    if published_dt:
        return start <= published_dt < end
    return normalize_date_for_report(discovered_at) == report_date


def render_markdown(report_date: str, rows: list[dict[str, object]]) -> str:
    grouped = group_export_rows(rows)
    total_count = sum(len(items) for items in grouped.values())
    lines = [
        f"일자 : {report_date}",
        coverage_window_label(report_date),
        "",
    ]
    if not total_count:
        lines.append("No search available")
        return "\n".join(lines) + "\n"
    for section in SECTION_ORDER:
        section_rows = grouped.get(section, [])
        if not section_rows:
            continue
        lines.append(f"[{SECTION_LABELS.get(section, section)}]")
        for row in section_rows:
            title = clean_display_title(str(row.get("title", "")), str(row.get("publisher", "")))
            source = display_source(row)
            lines.append(f"- [{title}]({row['source_url']})")
            if source:
                lines.append(f"  출처: {source}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(report_date: str, rows: list[dict[str, object]]) -> str:
    grouped = group_export_rows(rows)
    coverage = coverage_window_label(report_date).replace("기준 : ", "")
    items = []
    for section in SECTION_ORDER:
        section_rows = grouped.get(section, [])
        if not section_rows:
            continue
        clips = []
        for row in section_rows:
            source = display_source(row)
            clips.append(
                """
                <li class="clip">
                  <a href="{url}" target="_blank" rel="noreferrer">{title}</a>
                  {meta}
                </li>
                """.strip().format(
                    url=html_escape(str(row.get("source_url", ""))),
                    title=html_escape(clean_display_title(str(row.get("title", "")), str(row.get("publisher", "")))),
                    meta=f"<span class=\"source\">출처: {html_escape(source)}</span>" if source else "",
                )
            )
        if not clips:
            clips.append("<li class=\"empty\">No search available</li>")
        items.append(
            """
            <section>
              <h2>{section}</h2>
              <ul>{clips}</ul>
            </section>
            """.strip().format(
                section=html_escape(SECTION_LABELS.get(section, section)),
                clips="\n".join(clips),
            )
        )
    return (
        "<!doctype html>\n"
        "<html lang=\"ko\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"  <title>Daily PEF Clipping {html_escape(report_date)}</title>\n"
        "  <style>\n"
        "    :root { --bg: #ffffff; --paper: #ffffff; --ink: #171717; --muted: #737373; --line: #e5e5e5; --line-strong: #d4d4d4; }\n"
        "    body { margin: 0; font-family: Pretendard, 'Pretendard Variable', 'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', system-ui, sans-serif; background: var(--bg); color: var(--ink); }\n"
        "    main { width: min(820px, calc(100vw - 24px)); margin: 0 auto; padding: 26px 0 52px; }\n"
        "    h1 { margin: 0 0 6px; font-size: 28px; line-height: 1.08; letter-spacing: -0.045em; }\n"
        "    .sub { color: var(--muted); margin: 0 0 22px; font-size: 13px; }\n"
        "    section { margin: 14px 0; border: 1px solid var(--line); border-radius: 16px; background: var(--paper); padding: 16px; }\n"
        "    h2 { margin: 0 0 10px; font-size: 20px; line-height: 1.12; letter-spacing: -0.035em; border-bottom: 1px solid var(--ink); padding-bottom: 8px; }\n"
        "    ul { list-style: none; margin: 0; padding: 0; }\n"
        "    .clip { border-bottom: 1px solid var(--line); padding: 11px 0 10px; line-height: 1.48; }\n"
        "    .clip:last-child { border-bottom: 0; padding-bottom: 0; }\n"
        "    a { color: inherit; text-decoration: none; font-weight: 700; }\n"
        "    a:hover { text-decoration: underline; text-underline-offset: 3px; }\n"
        "    .source { display: block; color: var(--muted); font-size: 12px; margin-top: 4px; }\n"
        "    .empty { color: var(--muted); }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        f"    <h1>Daily PEF Clipping</h1>\n"
        f"    <p class=\"sub\">{html_escape(report_date)} · {html_escape(coverage)}</p>\n"
        + ("\n".join(items) if items else "    <p>오늘 기준으로 선택된 PEF 관련 클립이 없습니다.</p>\n")
        + "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


REVIEW_HEADERS = [
    "action",
    "category",
    "include_in_brief",
    "current_category",
    "publisher",
    "title",
    "quality_score",
    "quality_reason",
    "relevance_score",
    "gp_names",
    "summary_text",
    "source_url",
    "normalized_source_url",
    "notes",
]


def build_review_rows(
    conn: sqlite3.Connection,
    run_id: str,
    report_date: str,
    review_limit: int,
    brief_rows: list[dict[str, object]],
    out_dir: Path,
) -> list[dict[str, object]]:
    brief_urls = {str(row.get("normalized_source_url") or "") for row in brief_rows}
    previous_keys = load_previous_export_keys(out_dir, report_date)
    rows = load_run_candidate_rows(conn, run_id, report_date)
    for row in rows:
        quality_score, quality_reason = editorial_quality(row)
        row["quality_score"] = quality_score
        row["quality_reason"] = quality_reason
    rows = [
        row
        for row in rows
        if not is_previous_export(row, previous_keys) or str(row.get("review_status", "")) == "force_include"
    ]
    rows.sort(key=quality_sort_key)
    review_rows: list[dict[str, object]] = []
    for row in select_review_rows(rows, review_limit):
        current_section = primary_section(row)
        review_rows.append(
            {
                "action": "",
                "category": "",
                "include_in_brief": "Y" if str(row.get("normalized_source_url") or "") in brief_urls else "",
                "current_category": SECTION_LABELS.get(current_section, current_section),
                "publisher": str(row.get("publisher", "")),
                "title": clean_display_title(str(row.get("title", "")), str(row.get("publisher", ""))),
                "quality_score": row.get("quality_score", ""),
                "quality_reason": row.get("quality_reason", ""),
                "relevance_score": row.get("relevance_score", ""),
                "gp_names": row.get("gp_names", ""),
                "summary_text": row.get("summary_text", ""),
                "source_url": row.get("source_url", ""),
                "normalized_source_url": row.get("normalized_source_url", ""),
                "notes": "",
            }
        )
    return review_rows


def select_review_rows(rows: list[dict[str, object]], review_limit: int) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for row in rows:
        if str(row.get("review_status", "")) == "force_exclude":
            continue
        url_key = str(row.get("normalized_source_url") or row.get("source_url") or "")
        title_key = normalize_title_key(str(row.get("title", "")))
        if url_key and url_key in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        selected.append(row)
        if len(selected) >= review_limit:
            break
    return selected


def render_review_html(report_date: str, review_rows: list[dict[str, object]]) -> str:
    category_choices = ", ".join(SECTION_LABELS[section] for section in SECTION_ORDER)
    row_html = []
    for row in review_rows:
        row_html.append(
            """
            <tr>
              <td>{include_in_brief}</td>
              <td>{current_category}</td>
              <td>{publisher}</td>
              <td><a href="{url}" target="_blank" rel="noreferrer">{title}</a><div>{summary}</div></td>
              <td>{quality_score}</td>
              <td>{quality_reason}</td>
            </tr>
            """.strip().format(
                include_in_brief=html_escape(str(row.get("include_in_brief", ""))),
                current_category=html_escape(str(row.get("current_category", ""))),
                publisher=html_escape(str(row.get("publisher", ""))),
                url=html_escape(str(row.get("source_url", ""))),
                title=html_escape(str(row.get("title", ""))),
                summary=html_escape(str(row.get("summary_text", ""))[:220]),
                quality_score=html_escape(str(row.get("quality_score", ""))),
                quality_reason=html_escape(str(row.get("quality_reason", ""))),
            )
        )
    return (
        "<!doctype html>\n"
        "<html lang=\"ko\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"  <title>Daily PEF Review {html_escape(report_date)}</title>\n"
        "  <style>\n"
        "    :root { --bg: #ffffff; --paper: #ffffff; --ink: #171717; --muted: #737373; --line: #e5e5e5; --line-strong: #d4d4d4; }\n"
        "    body { margin: 0; font-family: Pretendard, 'Pretendard Variable', 'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', system-ui, sans-serif; color: var(--ink); background: var(--bg); }\n"
        "    main { width: min(1180px, calc(100vw - 24px)); margin: 0 auto; padding: 26px 0 56px; }\n"
        "    h1 { margin: 0 0 6px; font-size: 28px; line-height: 1.08; letter-spacing: -0.045em; }\n"
        "    p { color: var(--muted); line-height: 1.55; font-size: 13px; }\n"
        "    code { background: var(--paper); border: 1px solid var(--line); padding: 2px 5px; border-radius: 4px; }\n"
        "    table { width: 100%; border-collapse: collapse; margin-top: 18px; font-size: 13px; background: var(--paper); border: 1px solid var(--line); }\n"
        "    th { text-align: left; border-bottom: 1px solid var(--ink); padding: 9px 8px; white-space: nowrap; }\n"
        "    td { vertical-align: top; border-bottom: 1px solid var(--line); padding: 10px 8px; line-height: 1.48; }\n"
        "    a { color: inherit; font-weight: 700; text-decoration: none; }\n"
        "    a:hover { text-decoration: underline; text-underline-offset: 3px; }\n"
        "    td div { color: var(--muted); margin-top: 4px; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        "    <h1>Daily PEF Review</h1>\n"
        f"    <p>{html_escape(report_date)}</p>\n"
        "    <p>CSV에서 <code>action</code>에 <code>exclude</code> 또는 <code>include</code>를 적고, "
        f"<code>category</code>에는 필요할 때만 다음 중 하나를 적으면 됩니다: {html_escape(category_choices)}.</p>\n"
        "    <table>\n"
        "      <thead><tr><th>최종포함</th><th>현재분류</th><th>출처</th><th>기사</th><th>품질점수</th><th>점수이유</th></tr></thead>\n"
        f"      <tbody>{''.join(row_html)}</tbody>\n"
        "    </table>\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Korea PEF daily news clipping MVP pipeline")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--gp-alias-overrides", type=Path, default=DEFAULT_GP_ALIAS_OVERRIDES)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--date", default=today_seoul(), help="Report date in YYYY-MM-DD format")
    parser.add_argument("--limit-per-source", type=int, default=30)
    parser.add_argument("--brief-limit", type=int, default=12)
    parser.add_argument("--review-limit", type=int, default=80)
    parser.add_argument("--min-score", type=float, default=2.0)
    parser.add_argument("--allow-insecure-ssl", action="store_true", help="Disable TLS certificate verification for public source fetching")
    parser.add_argument("--source-code", default="", help="Comma-separated source_code filter for targeted testing")
    parser.add_argument("--google-date-window", action="store_true", help="Use Google News after/before operators based on --date")
    parser.add_argument("--no-latest", action="store_true", help="Do not update daily_news_*_latest export files")
    parser.add_argument("--gp-worklist-days", type=int, default=7)
    parser.add_argument("--service-integration-out-dir", type=Path, default=DEFAULT_EXPORT_DIR.parent)
    parser.add_argument("--service-integration-top-gp-limit", type=int, default=50)
    args = parser.parse_args()
    load_env_file(args.env)

    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    discovered_count = 0
    fetched_count = 0
    inserted_count = 0
    relevant_count = 0
    run_id = ""
    warnings: list[str] = []
    source_stats: dict[str, dict[str, object]] = {}
    try:
        init_db(conn, args.schema)
        sources = sync_sources(conn, args.sources)
        selected_source_codes = {code.strip() for code in args.source_code.split(",") if code.strip()}
        sources = filter_sources(sources, selected_source_codes)
        rules = load_rules(args.rules)
        overrides = load_manual_overrides(args.overrides)
        gp_aliases = load_gp_aliases(args.db, args.gp_alias_overrides)
        run_id = start_run(conn, args.date)

        for source in sources:
            source_stats[source.source_code] = {
                "source_name": source.source_name,
                "discovered_count": 0,
                "candidate_count": 0,
                "fetched_count": 0,
                "cached_count": 0,
                "relevant_count": 0,
                "warning_count": 0,
            }
            candidate_budget = 0
            try:
                items = fetch_source_items(
                    source,
                    args.limit_per_source,
                    verify_ssl=not args.allow_insecure_ssl,
                    report_date=args.date,
                    google_date_window=args.google_date_window,
                )
            except Exception as exc:
                warning = f"source={source.source_code} stage=listing error={exc}"
                warnings.append(warning)
                source_stats[source.source_code]["warning_count"] = int(source_stats[source.source_code]["warning_count"]) + 1
                print(f"WARNING: {warning}", file=sys.stderr)
                continue
            discovered_count += len(items)
            source_stats[source.source_code]["discovered_count"] = len(items)
            for item in items:
                source_url = str(item.get("link", "") or item.get("source_url", "")).strip()
                feed_publisher = str(item.get("publisher", "")).strip()
                if not source_url:
                    continue
                preview_text = " ".join([str(item.get("title", "")), str(item.get("excerpt", "")), source_url])
                if not matches_must_contain(source.must_contain, preview_text):
                    continue
                publisher_for_filter = feed_publisher or source.publisher
                if not matches_allowed_publishers(source.allowed_publishers, publisher_for_filter):
                    continue
                candidate_budget += 1
                if candidate_budget > args.limit_per_source:
                    break
                source_stats[source.source_code]["candidate_count"] = int(source_stats[source.source_code]["candidate_count"]) + 1

                article_url = resolve_google_news_url(source_url, verify_ssl=not args.allow_insecure_ssl)
                try:
                    article_response = fetch_text(article_url, verify_ssl=not args.allow_insecure_ssl)
                except Exception as exc:
                    if reuse_cached_document_for_run(conn, run_id, args.date, article_url):
                        source_stats[source.source_code]["cached_count"] = int(source_stats[source.source_code]["cached_count"]) + 1
                        continue
                    warning = f"source={source.source_code} stage=article url={article_url} error={exc}"
                    warnings.append(warning)
                    source_stats[source.source_code]["warning_count"] = int(source_stats[source.source_code]["warning_count"]) + 1
                    print(f"WARNING: {warning}", file=sys.stderr)
                    continue
                fetched_count += 1
                source_stats[source.source_code]["fetched_count"] = int(source_stats[source.source_code]["fetched_count"]) + 1
                final_url = str(article_response["final_url"])
                publisher_name = infer_publisher(final_url, str(item.get("publisher", "") or source.publisher))
                normalized_source_url = normalize_url(final_url)
                article_meta = parse_article_html(str(article_response["text"]))
                canonical_url = normalize_url(article_meta.get("canonical_url", ""))
                if canonical_url:
                    normalized_source_url = canonical_url
                raw_html_path = save_raw_html(args.raw_dir, args.date, normalized_source_url, bytes(article_response["raw_bytes"]))

                feed_title = str(item.get("title", "")).strip()
                article_title = article_meta.get("title", "")
                if feed_title and len(feed_title) > 180 and article_title and not is_generic_aggregator_text(article_title):
                    title = article_title
                elif feed_title and not is_generic_aggregator_text(feed_title):
                    title = feed_title
                elif article_title and not is_generic_aggregator_text(article_title):
                    title = article_title
                else:
                    title = feed_title or article_title or normalized_source_url
                title = clean_news_title(title, publisher_name) or title

                meta_description = article_meta.get("meta_description", "")
                if is_generic_aggregator_text(meta_description):
                    meta_description = ""
                body_text = article_meta.get("body_text", "")
                excerpt_text = str(item.get("excerpt", "")).strip()
                summary_text = build_summary(meta_description, excerpt_text, body_text)
                if (
                    source.source_kind == "google_news_query"
                    and is_generic_aggregator_text(title)
                    and is_generic_aggregator_text(summary_text)
                ):
                    continue
                score_result = score_document(title, excerpt_text, body_text, rules, source.default_tags)
                entity_links = match_gp_entities(title, summary_text, body_text, gp_aliases)

                override = overrides.get(normalized_source_url, {})
                manual_tags = []
                for tag in split_semicolon(override.get("manual_tags", "")):
                    if ":" in tag:
                        tag_type, tag_value = tag.split(":", 1)
                    else:
                        tag_type, tag_value = "topic", tag
                    manual_tags.append(
                        {
                            "tag_type": tag_type.strip(),
                            "tag_value": tag_value.strip(),
                            "tag_source": "manual_override",
                            "confidence": 1.0,
                        }
                    )
                tags = score_result["tags"] + manual_tags
                topic_tags = [str(tag["tag_value"]) for tag in tags if str(tag["tag_type"]) == "topic"]
                document_type_tags = [str(tag["tag_value"]) for tag in tags if str(tag["tag_type"]) == "document_type"]
                gp_names = [str(link["entity_name"]) for link in entity_links]
                comment_text = build_comment(
                    topic_tags,
                    document_type_tags,
                    gp_names,
                    score_result["comment_hints"],
                    override.get("manual_comment", ""),
                )
                review_status = override.get("review_status", "") or "auto"
                force_include = review_status == "force_include" or override.get("force_include", "").lower() in {"1", "true", "y", "yes"}
                force_exclude = review_status == "force_exclude" or override.get("force_exclude", "").lower() in {"1", "true", "y", "yes"}

                candidate = {
                    "source_url": final_url,
                    "normalized_source_url": normalized_source_url,
                    "source_domain": source_domain(normalized_source_url),
                    "publisher": publisher_name,
                    "title": title,
                    "published_at": article_meta.get("published_at", "") or to_iso_datetime(str(item.get("published_at", ""))),
                    "fetched_at": now_utc_iso(),
                    "document_type": document_type_tags[0] if document_type_tags else "article",
                    "raw_html_path": raw_html_path,
                    "meta_description": meta_description,
                    "summary_text": summary_text,
                    "body_text": body_text,
                    "content_hash": body_hash(title, summary_text, body_text),
                    "relevance_score": float(score_result["score"]),
                    "comment_text": comment_text,
                    "review_status": review_status,
                    "raw_payload": {
                        "feed_item": item,
                        "feed_source_url": source_url,
                        "resolved_source_url": article_url if article_url != source_url else "",
                        "article_meta": article_meta,
                        "source_code": source.source_code,
                    },
                    "force_include": force_include,
                    "force_exclude": force_exclude,
                }

                news_id, created_now = upsert_document(conn, run_id, source, args.date, candidate, args.min_score)
                replace_tags_and_links(conn, news_id, tags, entity_links)
                inserted_count += 1 if created_now else 0
                is_relevant_now = choose_relevance_label(candidate["relevance_score"], args.min_score, force_include, force_exclude)[0]
                relevant_count += 1 if is_relevant_now else 0
                source_stats[source.source_code]["relevant_count"] = int(source_stats[source.source_code]["relevant_count"]) + (1 if is_relevant_now else 0)

        conn.commit()
        rows = build_export_rows(conn, run_id, args.date, args.brief_limit, args.out_dir)
        review_rows = build_review_rows(conn, run_id, args.date, args.review_limit, rows, args.out_dir)
        markdown_path = args.out_dir / f"daily_news_brief_{args.date.replace('-', '')}.md"
        html_path = args.out_dir / f"daily_news_brief_{args.date.replace('-', '')}.html"
        csv_path = args.out_dir / f"daily_news_review_queue_{args.date.replace('-', '')}.csv"
        review_actions_path = args.out_dir / f"daily_news_review_actions_{args.date.replace('-', '')}.csv"
        review_html_path = args.out_dir / f"daily_news_review_{args.date.replace('-', '')}.html"
        latest_markdown_path = args.out_dir / "daily_news_brief_latest.md"
        latest_html_path = args.out_dir / "daily_news_brief_latest.html"
        latest_csv_path = args.out_dir / "daily_news_review_queue_latest.csv"
        latest_review_actions_path = args.out_dir / "daily_news_review_actions_latest.csv"
        latest_review_html_path = args.out_dir / "daily_news_review_latest.html"
        markdown_text = render_markdown(args.date, rows)
        html_text = render_html(args.date, rows)
        review_html_text = render_review_html(args.date, review_rows)
        markdown_path.write_text(markdown_text, encoding="utf-8")
        html_path.write_text(html_text, encoding="utf-8")
        review_html_path.write_text(review_html_text, encoding="utf-8")
        if not args.no_latest:
            latest_markdown_path.write_text(markdown_text, encoding="utf-8")
            latest_html_path.write_text(html_text, encoding="utf-8")
            latest_review_html_path.write_text(review_html_text, encoding="utf-8")
        write_csv_rows(
            csv_path,
            rows,
            [
                "news_id",
                "report_date",
                "publisher",
                "title",
                "source_url",
                "normalized_source_url",
                "published_at",
                "section_tags",
                "section_override_tags",
                "topic_tags",
                "document_type_tags",
                "gp_names",
                "quality_score",
                "quality_reason",
                "relevance_score",
                "relevance_label",
                "summary_text",
                "comment_text",
            ],
        )
        write_csv_rows(review_actions_path, review_rows, REVIEW_HEADERS)
        if not args.no_latest:
            write_csv_rows(
                latest_csv_path,
                rows,
                [
                    "news_id",
                    "report_date",
                    "publisher",
                    "title",
                    "source_url",
                    "normalized_source_url",
                    "published_at",
                    "section_tags",
                    "section_override_tags",
                    "topic_tags",
                    "document_type_tags",
                    "gp_names",
                    "quality_score",
                    "quality_reason",
                    "relevance_score",
                    "relevance_label",
                    "summary_text",
                    "comment_text",
                ],
            )
            write_csv_rows(latest_review_actions_path, review_rows, REVIEW_HEADERS)
        gp_worklist = build_news_gp_update_worklist(
            args.db,
            args.out_dir,
            args.date,
            args.gp_worklist_days,
            write_latest=not args.no_latest,
        )
        gp_worklist_path = Path(str(gp_worklist["dated_path"] if args.no_latest else gp_worklist["latest_path"]))
        service_worklist = build_service_integration_worklist(
            args.db,
            gp_worklist_path,
            args.service_integration_out_dir,
            args.date,
            args.service_integration_top_gp_limit,
            write_latest=not args.no_latest,
        )
        finish_run(
            conn,
            run_id,
            "completed",
            discovered_count,
            fetched_count,
            inserted_count,
            len(rows),
            notes="\n".join(warnings[:20]),
        )
        source_stats_path = args.out_dir / f"daily_news_source_stats_{args.date.replace('-', '')}.json"
        latest_source_stats_path = args.out_dir / "daily_news_source_stats_latest.json"
        result_payload = {
            "run_id": run_id,
            "report_date": args.date,
            "discovered_count": discovered_count,
            "fetched_count": fetched_count,
            "inserted_count": inserted_count,
            "brief_count": len(rows),
            "warning_count": len(warnings),
            "source_stats": source_stats,
            "markdown_path": str(markdown_path),
            "html_path": str(html_path),
            "csv_path": str(csv_path),
            "review_actions_path": str(review_actions_path),
            "review_html_path": str(review_html_path),
            "latest_markdown_path": str(latest_markdown_path),
            "latest_html_path": str(latest_html_path),
            "latest_csv_path": str(latest_csv_path),
            "latest_review_actions_path": str(latest_review_actions_path),
            "latest_review_html_path": str(latest_review_html_path),
            "source_stats_path": str(source_stats_path),
            "latest_source_stats_path": str(latest_source_stats_path),
            "gp_update_worklist_path": gp_worklist["dated_path"],
            "latest_gp_update_worklist_path": gp_worklist["latest_path"],
            "service_integration_worklist_path": service_worklist["dated_path"],
            "latest_service_integration_worklist_path": service_worklist["latest_path"],
        }
        source_stats_json = json.dumps(result_payload, ensure_ascii=False, indent=2)
        source_stats_path.write_text(source_stats_json, encoding="utf-8")
        latest_source_stats_path.write_text(source_stats_json, encoding="utf-8")
        print(source_stats_json)
        return 0
    except Exception as exc:
        if run_id:
            finish_run(
                conn,
                run_id,
                "failed",
                discovered_count,
                fetched_count,
                inserted_count,
                relevant_count,
                notes="\n".join(warnings[:20] + [str(exc)]),
            )
        raise
    finally:
        conn.close()


def body_hash(title: str, summary_text: str, body_text: str) -> str:
    raw = "\n".join([title, summary_text, body_text[:4000]])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    sys.exit(main())
