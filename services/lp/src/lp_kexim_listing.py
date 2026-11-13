"""Korea Exim Bank notice-board listing parser.

Moved out of the retired legacy LP monitor (build_lp_commitment_monitor.py)
on 2026-11-13. Behavior is unchanged; collect_kexim_programs.py is the only
caller.
"""
from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote_plus, urljoin

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.shared.src.daily_news_common import (  # noqa: E402
    matches_must_contain,
    normalize_whitespace,
    strip_html_tags,
)

DATE_RE = re.compile(r"(?P<year>20\d{2})[.\-/년]\s*(?P<month>\d{1,2})[.\-/월]\s*(?P<day>\d{1,2})")
SHORT_DATE_RE = re.compile(r"(?<!\d)[`'‘’]?(?P<year>\d{2})[.\-/년]\s*(?P<month>\d{1,2})[.\-/월]\s*(?P<day>\d{1,2})")
# The legacy monitor compared notices from 2024 onward; kept as-is so the
# Exim listing filter does not change in this refactor.
LP_NOTICE_COMPARISON_START_DATE = "2024-01-01"


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
