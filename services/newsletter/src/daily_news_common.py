#!/usr/bin/env python
"""Common helpers for the daily news clipping pipeline."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, quote, quote_plus, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_SCHEMA = SERVICE_ROOT / "schema" / "daily_news.sql"
DEFAULT_SOURCES = SERVICE_ROOT / "data" / "news_sources.csv"
DEFAULT_RULES = SERVICE_ROOT / "data" / "news_keyword_rules.csv"
DEFAULT_OVERRIDES = SERVICE_ROOT / "data" / "news_manual_overrides.csv"
DEFAULT_GP_ALIAS_OVERRIDES = SERVICE_ROOT / "data" / "news_gp_alias_overrides.csv"
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw" / "daily_news"
DEFAULT_EXPORT_DIR = REPO_ROOT / "exports" / "daily_news"
SERVICE_ENV = SERVICE_ROOT / "config" / "daily_news.env"
LEGACY_ENV = REPO_ROOT / "config" / "daily_news.env"
DEFAULT_ENV = SERVICE_ENV if SERVICE_ENV.exists() else LEGACY_ENV
SEOUL_TZ = ZoneInfo("Asia/Seoul")
MEDIA_TITLE_PREFIXES = {
    "더벨",
    "thebell",
    "invest",
    "인베스트조선",
}
SERIES_TITLE_PREFIX_PATTERNS = [
    re.compile(r"^thebell\s+note$", re.IGNORECASE),
    re.compile(r"^red\s*&\s*blue$", re.IGNORECASE),
    re.compile(r"^\d{4}\s*K-LP\s+출자지도$", re.IGNORECASE),
    re.compile(r"^공시집단\s+규제\s+리뷰$"),
    re.compile(r"^인사이드\s+헤지펀드$"),
    re.compile(r"^VC\s+경영분석$", re.IGNORECASE),
    re.compile(r"^상장\s+\d+년\s+"),
]
KEEP_TITLE_PREFIXES = {"단독", "인터뷰", "속보"}
VALUE_TITLE_BADGES = {"단독"}
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "_ga",
    "_gl",
    "ref",
    "ref_src",
}


@dataclass
class SourceConfig:
    source_code: str
    source_name: str
    source_kind: str
    locator: str
    publisher: str
    homepage_url: str
    article_url_regex: str
    must_contain: list[str]
    allowed_publishers: list[str]
    default_tags: list[tuple[str, str]]
    is_active: bool
    notes: str


@dataclass
class KeywordRule:
    rule_id: str
    match_target: str
    match_mode: str
    pattern: str
    score_delta: float
    tag_type: str
    tag_value: str
    comment_hint: str
    is_active: bool
    notes: str


@dataclass
class GpAlias:
    gp_id: int
    canonical_name: str
    alias_name: str
    alias_norm: str


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._current_href = ""
        self._text_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "a":
            href = attrs_dict.get("href", "").strip()
            onclick = attrs_dict.get("onclick", "").strip()
            if onclick and (not href or href == "#" or href.lower().startswith("javascript:")):
                href = f"javascript:{onclick}"
            self._current_href = href
            self._text_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "a" and self._current_href:
            text = normalize_whitespace(" ".join(self._text_parts))
            self.links.append({"href": self._current_href, "text": text})
            self._current_href = ""
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._current_href:
            self._text_parts.append(data)


class ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.paragraphs: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical_url = ""
        self.time_values: list[str] = []
        self._in_title = False
        self._in_paragraph = False
        self._paragraph_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        elif tag == "p":
            self._in_paragraph = True
            self._paragraph_parts = []
        elif tag == "meta":
            key = attrs_dict.get("property") or attrs_dict.get("name") or attrs_dict.get("itemprop")
            value = attrs_dict.get("content", "").strip()
            if key and value:
                self.meta[key.lower()] = value
        elif tag == "link":
            rel = attrs_dict.get("rel", "").lower()
            if "canonical" in rel and attrs_dict.get("href"):
                self.canonical_url = attrs_dict["href"].strip()
        elif tag == "time":
            value = attrs_dict.get("datetime", "").strip()
            if value:
                self.time_values.append(value)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag == "p" and self._in_paragraph:
            text = normalize_whitespace(" ".join(self._paragraph_parts))
            if len(text) >= 25:
                self.paragraphs.append(text)
            self._in_paragraph = False
            self._paragraph_parts = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        if self._in_paragraph:
            self._paragraph_parts.append(data)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_seoul() -> str:
    return datetime.now(SEOUL_TZ).strftime("%Y-%m-%d")


def parse_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "y", "yes"}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def write_csv_rows(path: Path, rows: list[dict[str, object]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows([{header: row.get(header, "") for header in headers} for row in rows])


def load_env_file(path: Path = DEFAULT_ENV) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_sources(path: Path) -> list[SourceConfig]:
    rows = read_csv_rows(path)
    sources: list[SourceConfig] = []
    for row in rows:
        sources.append(
            SourceConfig(
                source_code=row.get("source_code", ""),
                source_name=row.get("source_name", ""),
                source_kind=row.get("source_kind", ""),
                locator=row.get("locator", ""),
                publisher=row.get("publisher", ""),
                homepage_url=row.get("homepage_url", ""),
                article_url_regex=row.get("article_url_regex", ""),
                must_contain=split_semicolon(row.get("must_contain", "")),
                allowed_publishers=split_semicolon(row.get("allowed_publishers", "")),
                default_tags=parse_default_tags(row.get("default_tags", "")),
                is_active=parse_bool(row.get("is_active", "1")),
                notes=row.get("notes", ""),
            )
        )
    return [source for source in sources if source.source_code]


def load_rules(path: Path) -> list[KeywordRule]:
    rows = read_csv_rows(path)
    rules: list[KeywordRule] = []
    for row in rows:
        rules.append(
            KeywordRule(
                rule_id=row.get("rule_id", ""),
                match_target=row.get("match_target", "any_text"),
                match_mode=row.get("match_mode", "contains"),
                pattern=row.get("pattern", ""),
                score_delta=float(row.get("score_delta", "0") or 0),
                tag_type=row.get("tag_type", ""),
                tag_value=row.get("tag_value", ""),
                comment_hint=row.get("comment_hint", ""),
                is_active=parse_bool(row.get("is_active", "1")),
                notes=row.get("notes", ""),
            )
        )
    return [rule for rule in rules if rule.rule_id and rule.is_active]


def load_manual_overrides(path: Path) -> dict[str, dict[str, str]]:
    rows = read_csv_rows(path)
    overrides: dict[str, dict[str, str]] = {}
    for row in rows:
        key = row.get("normalized_source_url", "")
        if key:
            overrides[key] = row
    return overrides


def split_semicolon(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(";") if item.strip()]


def parse_default_tags(value: str) -> list[tuple[str, str]]:
    tags: list[tuple[str, str]] = []
    for item in split_semicolon(value):
        if ":" in item:
            tag_type, tag_value = item.split(":", 1)
            tags.append((tag_type.strip(), tag_value.strip()))
        else:
            tags.append(("topic", item))
    return tags


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def strip_html_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return normalize_whitespace(text)


def clean_news_title(title: str, publisher: str = "") -> str:
    value = normalize_whitespace(title or "")
    if not value:
        return ""
    value = re.sub(r"\s+-\s+Google 뉴스$", "", value)
    if publisher:
        escaped = re.escape(publisher)
        value = re.sub(rf"\s+-\s+{escaped}(\s+-\s+{escaped})?$", "", value)
        value = re.sub(rf"\s*\|\s*{escaped}$", "", value)
    for _ in range(4):
        match = re.match(r"^\[([^\]]{1,60})\]\s*", value)
        if not match:
            break
        label = normalize_whitespace(match.group(1))
        if not should_remove_title_prefix(label, publisher):
            break
        value = value[match.end():].lstrip()
    return normalize_whitespace(value)


def split_news_title_badges(title: str, publisher: str = "") -> tuple[str, list[str]]:
    value = clean_news_title(title, publisher)
    badges: list[str] = []
    for _ in range(3):
        match = re.match(r"^\[([^\]]{1,20})\]\s*", value)
        if not match:
            break
        label = normalize_whitespace(match.group(1))
        if label not in VALUE_TITLE_BADGES:
            break
        badges.append(label)
        value = value[match.end():].lstrip()
    return normalize_whitespace(value), badges


def should_remove_title_prefix(label: str, publisher: str = "") -> bool:
    normalized = normalize_whitespace(label)
    if not normalized or normalized in KEEP_TITLE_PREFIXES:
        return False
    lowered = normalized.lower()
    if lowered in MEDIA_TITLE_PREFIXES:
        return True
    if publisher and normalized == publisher:
        return True
    if publisher == "더벨":
        return True
    return any(pattern.search(normalized) for pattern in SERIES_TITLE_PREFIX_PATTERNS)


def normalize_for_match(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value or "").lower()


def normalize_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value.strip())
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if netloc in {"dealsite.co.kr", "www.dealsite.co.kr"}:
        match = re.match(r"^/articles/(\d+)(?:/\d+)?$", path)
        if match:
            netloc = "dealsite.co.kr"
            path = f"/articles/{match.group(1)}"
    if netloc in {"m.sedaily.com", "www.sedaily.com", "sedaily.com"}:
        match = re.match(r"^/(?:amp)?article/([0-9A-Za-z]+)$", path, flags=re.IGNORECASE)
        if match:
            article_id = match.group(1)
            if len(article_id) % 2 == 0 and article_id[: len(article_id) // 2] == article_id[len(article_id) // 2 :]:
                article_id = article_id[: len(article_id) // 2]
            netloc = "www.sedaily.com"
            path = f"/article/{article_id}"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query_pairs = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in TRACKING_PARAMS]
    query = "&".join(
        f"{quote_plus(key)}={quote_plus(val)}" if val else quote_plus(key)
        for key, val in sorted(query_pairs)
    )
    cleaned = parsed._replace(scheme=scheme, netloc=netloc, path=path, query=query, fragment="")
    return urlunparse(cleaned)


def prepare_request_url(value: str) -> str:
    parsed = urlparse(value.strip())
    path = quote(parsed.path or "/", safe="/:@%+-._~")
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if query_pairs:
        query = "&".join(
            f"{quote_plus(key)}={quote_plus(val)}" if val else quote_plus(key)
            for key, val in query_pairs
        )
    else:
        query = quote(parsed.query, safe="=&%+-._~")
    return urlunparse(parsed._replace(path=path, query=query))


def source_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


def sha1_text(value: str) -> str:
    return hashlib.sha1((value or "").encode("utf-8")).hexdigest()


def google_news_rss_url(query: str) -> str:
    return "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=ko&gl=KR&ceid=KR:ko"


def fetch_text(url: str, timeout: float = 20.0, verify_ssl: bool = True) -> dict[str, object]:
    request_url = prepare_request_url(url)
    request = Request(
        request_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko,en-US;q=0.7,en;q=0.3",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
        },
    )
    context = None
    if not verify_ssl and url.lower().startswith("https://"):
        context = ssl._create_unverified_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        raw_bytes = response.read()
        content_type = response.headers.get("Content-Type", "")
        charset = response.headers.get_content_charset() or detect_charset(raw_bytes) or "utf-8"
        text = raw_bytes.decode(charset, errors="replace")
        return {
            "request_url": request_url,
            "final_url": response.geturl(),
            "status": getattr(response, "status", 200),
            "content_type": content_type,
            "charset": charset,
            "text": text,
            "raw_bytes": raw_bytes,
        }


def detect_charset(raw_bytes: bytes) -> str:
    head = raw_bytes[:4096].decode("ascii", errors="ignore")
    match = re.search(r'charset=["\']?([A-Za-z0-9._-]+)', head, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def parse_feed(xml_text: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    items: list[dict[str, str]] = []
    for element in root.iter():
        if local_name(element.tag) not in {"item", "entry"}:
            continue
        payload = {
            "title": "",
            "link": "",
            "published_at": "",
            "excerpt": "",
            "publisher": "",
        }
        for child in list(element):
            name = local_name(child.tag)
            text = normalize_whitespace(child.text or "")
            if name == "title" and text:
                payload["title"] = text
            elif name == "link":
                href = child.attrib.get("href", "").strip()
                payload["link"] = href or text
            elif name in {"pubdate", "published", "updated"} and text and not payload["published_at"]:
                payload["published_at"] = to_iso_datetime(text)
            elif name in {"description", "summary"} and text and not payload["excerpt"]:
                payload["excerpt"] = strip_html_tags(text)
            elif name == "source" and text and not payload["publisher"]:
                payload["publisher"] = text
        if payload["title"] or payload["link"]:
            payload["raw_payload_json"] = json.dumps(payload, ensure_ascii=False)
            items.append(payload)
    return items


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1].lower()


def to_iso_datetime(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    dot_match = re.fullmatch(r"(\d{4})\.(\d{2})\.(\d{2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?", value)
    if dot_match:
        year, month, day, hour, minute, second = dot_match.groups()
        second = second or "00"
        return f"{year}-{month}-{day}T{int(hour):02d}:{minute}:{second}+09:00"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return value


def parse_html_listing(base_url: str, html_text: str, article_url_regex: str = "") -> list[dict[str, str]]:
    parser = LinkExtractor()
    parser.feed(html_text)
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    pattern = re.compile(article_url_regex) if article_url_regex else None
    for item in parser.links:
        href = item.get("href", "")
        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        if pattern and not pattern.search(absolute):
            continue
        seen.add(absolute)
        rows.append({"link": absolute, "title": item.get("text", "")})
    return rows


def parse_article_html(html_text: str) -> dict[str, str]:
    parser = ArticleParser()
    parser.feed(html_text)
    meta = {key.lower(): normalize_whitespace(value) for key, value in parser.meta.items()}
    paragraphs = [normalize_whitespace(text) for text in parser.paragraphs if text]
    body_text = "\n".join(paragraphs[:40])
    published_at = first_non_empty(
        meta.get("article:published_time", ""),
        meta.get("og:published_time", ""),
        meta.get("pubdate", ""),
        meta.get("date", ""),
        meta.get("dc.date", ""),
        parser.time_values[0] if parser.time_values else "",
        extract_dot_datetime(html_text),
    )
    return {
        "title": first_non_empty(
            meta.get("og:title", ""),
            meta.get("twitter:title", ""),
            normalize_whitespace(" ".join(parser.title_parts)),
        ),
        "meta_description": first_non_empty(
            meta.get("description", ""),
            meta.get("og:description", ""),
            meta.get("twitter:description", ""),
        ),
        "canonical_url": parser.canonical_url,
        "published_at": to_iso_datetime(published_at),
        "body_text": body_text,
    }


def extract_dot_datetime(html_text: str) -> str:
    match = re.search(r"\b(20\d{2}\.\d{2}\.\d{2}\s+\d{1,2}:\d{2}(?::\d{2})?)\b", html_text or "")
    return match.group(1) if match else ""


def first_non_empty(*values: str) -> str:
    for value in values:
        if str(value or "").strip():
            return str(value).strip()
    return ""


def matches_must_contain(must_contain: Iterable[str], *values: str) -> bool:
    keywords = [keyword.lower() for keyword in must_contain if keyword]
    if not keywords:
        return True
    haystack = " ".join(values).lower()
    return any(keyword in haystack for keyword in keywords)


def matches_allowed_publishers(allowed_publishers: Iterable[str], publisher: str) -> bool:
    publishers = [value.lower() for value in allowed_publishers if value]
    if not publishers:
        return True
    publisher_norm = str(publisher or "").strip().lower()
    if not publisher_norm:
        return False
    return any(value in publisher_norm for value in publishers)


def sentence_candidates(text: str) -> list[str]:
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return []
    pieces = re.split(r"(?<=[.!?])\s+|(?<=다)\s+|(?<=요)\s+", cleaned)
    return [piece.strip() for piece in pieces if piece.strip()]


def is_boilerplate_sentence(value: str) -> bool:
    sentence = normalize_whitespace(value)
    lower = sentence.lower()
    patterns = [
        "김·장 법률사무소는 1973년 설립 이래",
        "국내 최대규모의 종합 법률사무소",
        "법률서비스의 선진화",
        "all rights reserved",
        "contact us",
        "subscribe",
        "more press releases",
    ]
    return any(pattern.lower() in lower for pattern in patterns)


def build_summary(meta_description: str, excerpt_text: str, body_text: str, limit: int = 2) -> str:
    for source in (meta_description, excerpt_text, body_text):
        sentences = [
            sentence
            for sentence in sentence_candidates(source)
            if len(sentence) >= 20 and not is_boilerplate_sentence(sentence)
        ]
        if sentences:
            return " ".join(sentences[:limit])
    fallback = normalize_whitespace(body_text or excerpt_text or meta_description)
    return fallback[:240]


def score_document(
    title: str,
    excerpt_text: str,
    body_text: str,
    rules: list[KeywordRule],
    default_tags: list[tuple[str, str]],
) -> dict[str, object]:
    score = 0.0
    tags: list[dict[str, object]] = []
    hints: list[str] = []
    targets = {
        "title": title,
        "excerpt": excerpt_text,
        "body": body_text,
        "title_or_excerpt": " ".join(part for part in [title, excerpt_text] if part),
        "any_text": " ".join(part for part in [title, excerpt_text, body_text] if part),
    }
    for tag_type, tag_value in default_tags:
        tags.append({"tag_type": tag_type, "tag_value": tag_value, "tag_source": "source_default", "confidence": 0.85})
    for rule in rules:
        haystack = targets.get(rule.match_target, targets["any_text"])
        if not haystack:
            continue
        matched = False
        if rule.match_mode == "contains":
            matched = rule.pattern.lower() in haystack.lower()
        elif rule.match_mode == "regex":
            matched = re.search(rule.pattern, haystack, flags=re.IGNORECASE) is not None
        if not matched:
            continue
        score += rule.score_delta
        if rule.tag_type and rule.tag_value:
            tags.append(
                {
                    "tag_type": rule.tag_type,
                    "tag_value": rule.tag_value,
                    "tag_source": "keyword_rule",
                    "confidence": min(0.99, 0.55 + abs(rule.score_delta) * 0.08),
                }
            )
        if rule.comment_hint:
            hints.append(rule.comment_hint)
    return {"score": round(score, 2), "tags": dedupe_tags(tags), "comment_hints": unique_preserve_order(hints)}


def dedupe_tags(tags: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[str, str, str]] = set()
    rows: list[dict[str, object]] = []
    for tag in tags:
        key = (str(tag.get("tag_type", "")), str(tag.get("tag_value", "")), str(tag.get("tag_source", "")))
        if key in seen or not key[0] or not key[1]:
            continue
        seen.add(key)
        rows.append(tag)
    return rows


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        if value in seen or not value:
            continue
        seen.add(value)
        rows.append(value)
    return rows


def choose_relevance_label(score: float, min_score: float, force_include: bool, force_exclude: bool) -> tuple[int, str]:
    if force_exclude:
        return 0, "excluded"
    if force_include:
        return 1, "forced"
    if score >= max(8.0, min_score + 3):
        return 1, "high"
    if score >= max(5.0, min_score + 1):
        return 1, "medium"
    if score >= min_score:
        return 1, "low"
    return 0, "review"


def build_comment(
    topic_tags: Iterable[str],
    document_type_tags: Iterable[str],
    gp_names: Iterable[str],
    comment_hints: Iterable[str],
    manual_comment: str,
) -> str:
    if manual_comment:
        return manual_comment.strip()
    topics = set(topic_tags)
    doc_types = set(document_type_tags)
    gps = list(gp_names)
    if "Market" in topics or "Regulation" in topics:
        return "규제·준법 이슈와 연결돼 운용사 실무 체크 가치가 있습니다."
    if "LP" in topics:
        return "LP 출자사업 또는 기관 자금 흐름과 연결돼 자금조달 관점에서 볼 만합니다."
    if "Advisory" in topics or "newsletter" in doc_types or "report" in doc_types:
        return "자문사 해설 또는 리포트 성격이라 실무 참고자료로 보관 가치가 있습니다."
    if "Deal" in topics and gps:
        return f"{gps[0]} 등 기존 GP DB와 연결 가능한 딜 관련 기사입니다."
    if gps:
        return "기존 GP DB와 연결 가능한 기사라 하우스별 트래킹에 바로 활용할 수 있습니다."
    hints = list(comment_hints)
    if hints:
        return hints[0]
    return "국내 PEF 시장 키워드와 직접 연결된 기사입니다."


def normalize_date_for_report(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:10]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SEOUL_TZ).strftime("%Y-%m-%d")


def is_generic_aggregator_text(value: str) -> bool:
    text = normalize_whitespace(value).lower()
    if not text:
        return False
    generic_values = {
        "google 뉴스",
        "google news",
        "google 뉴스가 전세계 매체로부터 종합한 최신 뉴스",
        "google news brings you the latest news from around the world",
    }
    return text in generic_values


def alias_is_short_ascii(value: str) -> bool:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value or "")
    return bool(cleaned) and cleaned.isascii() and len(cleaned) <= 4


def add_gp_alias(
    aliases: dict[tuple[int, str], GpAlias],
    gp_id: int,
    canonical_name: str,
    alias_name: str,
) -> None:
    alias_name = normalize_whitespace(alias_name)
    alias_norm = normalize_for_match(alias_name)
    if len(alias_norm) < 3:
        return
    aliases[(int(gp_id), alias_name)] = GpAlias(int(gp_id), canonical_name, alias_name, alias_norm)


def load_gp_aliases(db_path: Path, overrides_path: Path = DEFAULT_GP_ALIAS_OVERRIDES) -> list[GpAlias]:
    aliases: dict[tuple[int, str], GpAlias] = {}
    conn = sqlite3.connect(db_path)
    try:
        if not table_exists(conn, "gp_house"):
            return []
        gp_name_to_id: dict[str, tuple[int, str]] = {}
        for gp_id, gp_name in conn.execute("SELECT gp_id, gp_name FROM gp_house"):
            canonical_name = str(gp_name)
            gp_name_to_id[canonical_name] = (int(gp_id), canonical_name)
            add_gp_alias(aliases, int(gp_id), canonical_name, canonical_name)
        if table_exists(conn, "gp_house_alias"):
            for gp_id, canonical_name, alias_name in conn.execute(
                """
                SELECT canonical_gp_id, canonical_gp_name, alias_gp_name
                FROM gp_house_alias
                """
            ):
                add_gp_alias(aliases, int(gp_id), str(canonical_name), str(alias_name))
        if table_exists(conn, "gp_profile"):
            for row in conn.execute(
                """
                SELECT
                    source_gp_id,
                    standard_gp_name,
                    display_name_ko,
                    legal_entity_name_ko,
                    legal_entity_name_en,
                    alias_names,
                    raw_name_variants
                FROM gp_profile
                """
            ):
                gp_id = int(row[0])
                canonical_name = str(row[1] or "")
                if not canonical_name:
                    continue
                gp_name_to_id[canonical_name] = (gp_id, canonical_name)
                for alias_name in [
                    canonical_name,
                    str(row[2] or ""),
                    str(row[3] or ""),
                    str(row[4] or ""),
                ]:
                    if alias_name:
                        add_gp_alias(aliases, gp_id, canonical_name, alias_name)
                for field_value in [str(row[5] or ""), str(row[6] or "")]:
                    for alias_name in split_semicolon(field_value):
                        add_gp_alias(aliases, gp_id, canonical_name, alias_name)
    finally:
        conn.close()
    for row in read_csv_rows(overrides_path):
        standard_gp_name = row.get("standard_gp_name", "")
        alias_name = row.get("alias_name", "")
        if not standard_gp_name or not alias_name:
            continue
        gp_row = gp_name_to_id.get(standard_gp_name)
        if gp_row is None:
            continue
        add_gp_alias(aliases, gp_row[0], gp_row[1], alias_name)
    return sorted(aliases.values(), key=lambda row: (-len(row.alias_norm), row.alias_name))


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type IN ('table', 'view') AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def match_gp_entities(title: str, excerpt_text: str, body_text: str, aliases: list[GpAlias]) -> list[dict[str, object]]:
    raw_fields = {
        "title": title or "",
        "excerpt": excerpt_text or "",
        "body": body_text or "",
    }
    normalized_fields = {
        "title": normalize_for_match(title),
        "excerpt": normalize_for_match(excerpt_text),
        "body": normalize_for_match(body_text),
    }
    matches: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    for alias in aliases:
        match_field = ""
        confidence = 0.0
        if alias_is_short_ascii(alias.alias_name):
            alias_pattern = r"(?<![A-Za-z0-9])" + re.escape(alias.alias_name.lower()) + r"(?![A-Za-z0-9])"
            if re.search(alias_pattern, raw_fields["title"].lower()):
                match_field = "title"
                confidence = 0.97
            elif re.search(alias_pattern, raw_fields["excerpt"].lower()):
                match_field = "excerpt"
                confidence = 0.84
            elif re.search(alias_pattern, raw_fields["body"].lower()):
                match_field = "body"
                confidence = 0.76
        else:
            if alias.alias_norm and alias.alias_norm in normalized_fields["title"]:
                match_field = "title"
                confidence = 0.96
            elif alias.alias_norm and alias.alias_norm in normalized_fields["excerpt"]:
                match_field = "excerpt"
                confidence = 0.82
            elif alias.alias_norm and alias.alias_norm in normalized_fields["body"]:
                match_field = "body"
                confidence = 0.74
        if not match_field:
            continue
        key = (alias.gp_id, alias.canonical_name)
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            {
                "entity_type": "GP",
                "entity_ref": f"gp:{alias.gp_id}",
                "entity_name": alias.canonical_name,
                "matched_alias": alias.alias_name,
                "match_field": match_field,
                "link_source": "gp_alias_match",
                "confidence": confidence,
            }
        )
        if len(matches) >= 8:
            break
    return matches


def save_raw_html(raw_dir: Path, report_date: str, normalized_source_url: str, raw_bytes: bytes) -> str:
    if not raw_bytes:
        return ""
    folder = raw_dir / report_date
    folder.mkdir(parents=True, exist_ok=True)
    file_name = sha1_text(normalized_source_url)[:16] + ".html"
    path = folder / file_name
    path.write_bytes(raw_bytes)
    return str(path)
