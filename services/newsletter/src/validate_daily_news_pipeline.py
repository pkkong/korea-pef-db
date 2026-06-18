#!/usr/bin/env python
"""Validate daily news clipping outputs and generated public files."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from pathlib import Path

from daily_news_common import (
    DEFAULT_DB,
    DEFAULT_ENV,
    DEFAULT_EXPORT_DIR,
    DEFAULT_SOURCES,
    REPO_ROOT,
    clean_investment_memo_summary_lines,
    is_truncated_news_title,
    normalize_url,
    read_csv_rows,
    today_seoul,
)
from run_daily_news_pipeline import (
    EXPORT_MIN_QUALITY_SCORE,
    coverage_window_label,
    has_advisory_people_signal,
    has_deal_market_commentary_signal,
    is_near_duplicate_title_key,
    normalize_title_key,
)
from news_taxonomy import (
    PRIMARY_SECTION_TOPICS,
    SECTION_LABELS,
    TAG_TAXONOMY_VERSION,
    canonical_section,
)


REQUIRED_TABLES = [
    "news_source",
    "news_run",
    "news_document",
    "news_tag",
    "news_entity_link",
]
VALID_CATEGORY_LABELS = set(SECTION_LABELS.values())
FORBIDDEN_PUBLIC_ARTICLE_FIELDS = {
    "provider",
    "confidence",
    "notes",
    "section_suggestion",
    "sectionSuggestion",
    "sectionSuggestionRaw",
    "suggestion_status",
}
MARKDOWN_LINK_RE = re.compile(r"- \[(?P<title>.+?)\]\((?P<url>https?://[^)]+)\)")
BRIEF_SECTION_RE = re.compile(r"^\[(?P<section>[^\]]+)\]\s*$")

AUCTION_TITLE_RE = re.compile(r"(?:본입찰|예비입찰|입찰|원매자|인수의향|우선협상|숏리스트|주관사|매각주관|제안)")
FINANCING_TITLE_RE = re.compile(r"(?:CB|전환사채|메자닌).*(?:투입|인수|투자|조달)|(?:투입|인수|투자|조달).*(?:CB|전환사채|메자닌)", re.IGNORECASE)
GP_FUNDRAISING_TITLE_RE = re.compile(r"(?:펀딩 목표|펀드레이징|자펀드|블라인드|GP 도전|펀드.{0,5}도전)")
OWNERSHIP_TITLE_RE = re.compile(r"(?:수익성|수익성 개선|손본다|밸류업|PMI|구조조정|운영 개선|가치 재평가|재평가)", re.IGNORECASE)


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def note(self, message: str) -> None:
        self.info.append(message)

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": not self.errors,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
        }


def compact_date(report_date: str) -> str:
    return report_date.replace("-", "")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def markdown_links(markdown_text: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in markdown_text.splitlines():
        match = MARKDOWN_LINK_RE.match(line)
        if match:
            current = match.groupdict()
            current["publisher"] = ""
            links.append(current)
            continue
        if current is not None and line.startswith("  출처:"):
            current["publisher"] = line.split(":", 1)[1].strip()
    return links


def markdown_articles(markdown_text: str) -> list[dict[str, str]]:
    articles: list[dict[str, str]] = []
    current_section = ""
    current: dict[str, str] | None = None
    for line in markdown_text.splitlines():
        section_match = BRIEF_SECTION_RE.match(line.strip())
        if section_match:
            current_section = canonical_section(section_match.group("section"))
            current = None
            continue
        link_match = MARKDOWN_LINK_RE.match(line)
        if link_match:
            current = link_match.groupdict()
            current["publisher"] = ""
            current["section"] = current_section
            articles.append(current)
            continue
        if current is not None and line.startswith("  출처:"):
            current["publisher"] = line.split(":", 1)[1].strip()
    return articles


def split_csv_values(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def article_keys(title: str, *urls: str) -> list[str]:
    keys: list[str] = []
    for url in urls:
        normalized = normalize_url(str(url or ""))
        if normalized and normalized not in keys:
            keys.append(normalized)
    title_key = normalize_title_key(title)
    if title_key:
        keys.append(f"title:{title_key}")
    return keys


def index_rows_by_article(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in rows:
        for key in article_keys(
            row.get("title", ""),
            row.get("normalized_source_url", ""),
            row.get("source_url", ""),
            row.get("url", ""),
        ):
            index.setdefault(key, row)
    return index


def first_match(index: dict[str, dict[str, str]], title: str, *urls: str) -> dict[str, str] | None:
    for key in article_keys(title, *urls):
        row = index.get(key)
        if row is not None:
            return row
    return None


def expected_subcategory(title: str, section: str) -> str:
    if section == "Deal":
        if FINANCING_TITLE_RE.search(title):
            return "Financing"
        if OWNERSHIP_TITLE_RE.search(title):
            return "Ownership"
        if AUCTION_TITLE_RE.search(title):
            return "Auction"
    if section == "GP" and GP_FUNDRAISING_TITLE_RE.search(title):
        return "Fundraising"
    if section == "Market" and "장외파생상품" in title and any(token in title for token in ["라이선스", "인가", "금감원", "금융위"]):
        return "Regulation"
    return ""


def check_review_classification_quality(result: Validation, queue_rows: list[dict[str, str]]) -> None:
    for row in queue_rows:
        title = row.get("title", "")
        section = canonical_section(row.get("current_category", ""))
        section_tags = [canonical_section(value) for value in split_csv_values(row.get("section_tags", ""))]
        topic_tags = split_csv_values(row.get("topic_tags", ""))
        if not section:
            result.error(f"missing current_category: {title}")
            continue
        if len(section_tags) != 1 or section_tags[0] != section:
            result.error(
                f"classification mismatch for '{title}': current_category={section}, section_tags={','.join(section_tags) or '-'}"
            )
        conflicts = [topic for topic in topic_tags if topic in PRIMARY_SECTION_TOPICS and topic != section]
        if conflicts:
            result.error(
                f"topic tag conflicts with category for '{title}': current_category={section}, topic_tags={','.join(conflicts)}"
            )
        tag_version = row.get("tag_version", "").strip()
        if tag_version and tag_version != TAG_TAXONOMY_VERSION:
            result.error(
                f"taxonomy version mismatch for '{title}': tag_version={tag_version}, expected={TAG_TAXONOMY_VERSION}"
            )
        if section == "GP" and GP_FUNDRAISING_TITLE_RE.search(title) and "Fundraising" not in topic_tags:
            result.error(f"missing Fundraising topic for GP fundraising article: {title}")
        if section == "Deal" and FINANCING_TITLE_RE.search(title) and "Credit" not in topic_tags:
            result.warning(f"Deal financing article has no Credit topic: {title}")
        if row.get("include_in_brief", "").upper() == "Y" and has_advisory_people_signal(title):
            result.error(f"advisory people story should not be included in brief: {title}")
        if section == "Deal" and has_deal_market_commentary_signal(title):
            result.error(f"M&A market commentary is classified as Deal: {title}")


def check_brief_review_alignment(
    result: Validation,
    brief_articles: list[dict[str, str]],
    queue_rows: list[dict[str, str]],
) -> None:
    queue_index = index_rows_by_article(queue_rows)
    for article in brief_articles:
        title = article.get("title", "")
        brief_section = canonical_section(article.get("section", ""))
        row = first_match(queue_index, title, article.get("url", ""))
        if row is None:
            result.error(f"brief article is missing from review queue: {title}")
            continue
        queue_section = canonical_section(row.get("current_category", ""))
        if brief_section and queue_section and brief_section != queue_section:
            result.error(
                f"brief section does not match review queue for '{title}': brief={brief_section}, review={queue_section}"
            )


def read_site_archive(site_dir: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    health_path = site_dir / "health.json"
    archive_path = site_dir / "archive.json"
    if not health_path.exists() or not archive_path.exists():
        return {}, []
    try:
        health = json.loads(health_path.read_text(encoding="utf-8"))
        archive = json.loads(archive_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}, []
    return (health if isinstance(health, dict) else {}, archive if isinstance(archive, list) else [])


def read_current_archive(site_dir: Path, report_date: str) -> tuple[list[dict[str, object]], str]:
    health, archive = read_site_archive(site_dir)
    if not health or not archive:
        return [], ""
    if str(health.get("report_date") or "") != report_date:
        return [], str(health.get("report_date") or "")
    entry = next((row for row in archive if row.get("reportDate") == report_date), None)
    if not isinstance(entry, dict):
        return [], report_date
    rows = entry.get("articles", [])
    if not isinstance(rows, list):
        return [], report_date
    return [row for row in rows if isinstance(row, dict)], report_date


def check_archive_previous_duplicates(
    result: Validation,
    site_dir: Path,
    report_date: str,
    current_rows: list[dict[str, object]],
) -> None:
    _health, archive = read_site_archive(site_dir)
    if not archive:
        return
    previous_urls: dict[str, str] = {}
    previous_titles: dict[str, str] = {}
    for entry in archive:
        if not isinstance(entry, dict):
            continue
        archive_date = str(entry.get("reportDate") or "").strip()
        if not archive_date or archive_date >= report_date:
            continue
        articles = entry.get("articles")
        if not isinstance(articles, list):
            continue
        for article in articles:
            if not isinstance(article, dict):
                continue
            title = str(article.get("title") or "")
            url = normalize_url(str(article.get("url") or article.get("sourceUrl") or ""))
            title_key = normalize_title_key(title)
            if url:
                previous_urls.setdefault(url, archive_date)
            if title_key:
                previous_titles.setdefault(title_key, archive_date)
    for article in current_rows:
        title = str(article.get("title") or "")
        url = normalize_url(str(article.get("url") or article.get("sourceUrl") or ""))
        title_key = normalize_title_key(title)
        if url and url in previous_urls:
            result.error(f"archive repeats previously published URL from {previous_urls[url]}: {title}")
        elif title_key and title_key in previous_titles:
            result.error(f"archive repeats previously published title from {previous_titles[title_key]}: {title}")


def check_archive_classification_quality(
    result: Validation,
    site_dir: Path,
    out_dir: Path,
    report_date: str,
    brief_articles: list[dict[str, str]],
    queue_rows: list[dict[str, str]],
) -> None:
    health, archive = read_site_archive(site_dir)
    if not health:
        result.error(f"deploy archive not available for classification check: {site_dir / 'archive.json'}")
        return
    archive_report_date = str(health.get("report_date") or "")
    if archive_report_date != report_date:
        result.error(f"deploy archive is for {archive_report_date}, not {report_date}")
        return
    entry = next((row for row in archive if isinstance(row, dict) and row.get("reportDate") == report_date), None)
    if not isinstance(entry, dict):
        result.error(f"deploy archive missing reportDate={report_date}")
        return
    entry_articles = entry.get("articles")
    if not isinstance(entry_articles, list):
        result.error(f"deploy archive reportDate={report_date} has no article list")
        return
    archive_rows = [row for row in entry_articles if isinstance(row, dict)]
    check_archive_previous_duplicates(result, site_dir, report_date, archive_rows)
    brief_index = index_rows_by_article(brief_articles)
    queue_index = index_rows_by_article(queue_rows)
    apply_ai_sections = str(os.environ.get("NEWSLETTER_AI_APPLY_SECTIONS", "0")).strip().lower() in {"1", "true", "yes", "on"}
    ai_index = index_rows_by_article(read_ai_enrichment_articles(out_dir, report_date)) if apply_ai_sections else {}
    if len(archive_rows) != len(brief_articles):
        result.error(f"archive article count {len(archive_rows)} does not match brief count {len(brief_articles)}")
    for article in archive_rows:
        title = str(article.get("title") or "")
        section = canonical_section(str(article.get("section") or ""))
        subcategory = str(article.get("subCategory") or "").strip()
        source_url = str(article.get("url") or article.get("sourceUrl") or "")
        leaked_fields = sorted(field for field in FORBIDDEN_PUBLIC_ARTICLE_FIELDS if field in article)
        if leaked_fields:
            result.error(f"archive article leaks internal AI fields for '{title}': {','.join(leaked_fields)}")
        if is_truncated_news_title(title):
            result.error(f"archive article title is truncated; use the full source headline: {title}")
        summary_lines = article.get("summaryLines") or []
        if isinstance(summary_lines, list):
            raw_summary_lines = [str(line or "").strip() for line in summary_lines if str(line or "").strip()]
        elif isinstance(summary_lines, str):
            raw_summary_lines = [line.strip() for line in re.split(r"\n+|\s*\|\s*", summary_lines) if line.strip()]
        else:
            raw_summary_lines = []
        cleaned_summary_lines = clean_investment_memo_summary_lines(raw_summary_lines, title, limit=3)
        if raw_summary_lines and len(cleaned_summary_lines) != len(raw_summary_lines):
            result.error(f"archive article has unusable public summaryLines for '{title}'")
        if not raw_summary_lines:
            result.warning(f"archive article has no summaryLines: {title}")
        ai_row = first_match(ai_index, title, source_url) if apply_ai_sections else None
        ai_section = canonical_section(str(ai_row.get("section_suggestion") or "")) if ai_row is not None else ""
        ai_section_applied = bool(apply_ai_sections and ai_section and section == ai_section)
        if not section:
            result.error(f"archive article has no section: {title}")
        if not subcategory:
            result.error(f"archive article has no subCategory: {title}")
        if has_advisory_people_signal(title):
            result.error(f"archive includes advisory people story: {title}")
        if section == "Deal" and has_deal_market_commentary_signal(title):
            result.error(f"archive classifies M&A market commentary as Deal: {title}")
        brief_row = first_match(brief_index, title, source_url)
        if brief_row is not None:
            brief_section = canonical_section(brief_row.get("section", ""))
            if section and brief_section and section != brief_section and not ai_section_applied:
                result.error(f"archive section does not match brief for '{title}': archive={section}, brief={brief_section}")
        queue_row = first_match(queue_index, title, source_url)
        if queue_row is not None:
            queue_section = canonical_section(queue_row.get("current_category", ""))
            if section and queue_section and section != queue_section and not ai_section_applied:
                result.error(f"archive section does not match review queue for '{title}': archive={section}, review={queue_section}")
        if apply_ai_sections and ai_section and section != ai_section:
            result.error(f"archive section does not match AI suggestion for '{title}': archive={section}, ai={ai_section}")
        expected = expected_subcategory(title, section)
        if expected and subcategory != expected:
            result.error(f"archive subCategory mismatch for '{title}': expected={expected}, actual={subcategory}")


def read_ai_enrichment_articles(out_dir: Path, report_date: str) -> list[dict[str, object]]:
    path = out_dir / f"daily_news_ai_enrichment_{compact_date(report_date)}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    articles = data.get("articles") if isinstance(data, dict) else []
    if not isinstance(articles, list):
        return []
    return [row for row in articles if isinstance(row, dict)]


def check_ai_enrichment_classification_quality(
    result: Validation,
    out_dir: Path,
    report_date: str,
    queue_rows: list[dict[str, str]],
) -> None:
    articles = read_ai_enrichment_articles(out_dir, report_date)
    if not articles:
        result.warning("AI enrichment output is missing; summary/category second-pass was not available")
        return
    ai_payload_path = out_dir / f"daily_news_ai_enrichment_{compact_date(report_date)}.json"
    try:
        ai_payload = json.loads(ai_payload_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        ai_payload = {}
    provider = str(ai_payload.get("provider") or "") if isinstance(ai_payload, dict) else ""
    is_external_provider = provider not in {"", "local-rule"}
    if len(articles) != len(queue_rows):
        message = f"AI enrichment article count {len(articles)} does not match review queue count {len(queue_rows)}"
        if is_external_provider:
            result.error(message)
        else:
            result.warning(message)
    queue_index = index_rows_by_article(queue_rows)
    conflict_count = 0
    invalid_count = 0
    missing_count = 0
    missing_summary_count = 0
    for article in articles:
        title = str(article.get("title") or "")
        suggestion = canonical_section(str(article.get("section_suggestion") or ""))
        raw_suggestion = str(article.get("section_suggestion_raw") or "").strip()
        suggestion_status = str(article.get("suggestion_status") or "").strip()
        if suggestion_status == "invalid" or (raw_suggestion and not suggestion):
            invalid_count += 1
            result.error(f"AI enrichment invalid category for '{title}': raw={raw_suggestion}")
            continue
        if suggestion_status == "missing":
            missing_count += 1
            if is_external_provider:
                result.error(f"AI enrichment missing category suggestion for '{title}'")
            continue
        if suggestion and suggestion not in SECTION_LABELS:
            invalid_count += 1
            result.error(f"AI enrichment suggested unknown category for '{title}': {suggestion}")
            continue
        row = first_match(
            queue_index,
            title,
            str(article.get("normalized_source_url") or ""),
            str(article.get("source_url") or ""),
        )
        current = canonical_section(row.get("current_category", "")) if row is not None else canonical_section(str(article.get("current_category") or ""))
        if suggestion and current and suggestion != current:
            conflict_count += 1
            result.warning(f"AI category conflict for '{title}': current={current}, ai={suggestion}")
        summary_lines = article.get("summary_lines") or article.get("summaryLines") or []
        cleaned_summary_lines = clean_investment_memo_summary_lines(summary_lines, title, limit=3)
        if len(cleaned_summary_lines) < 1:
            missing_summary_count += 1
            if is_external_provider:
                result.error(f"AI enrichment has no usable public summary_lines for '{title}'")
    result.note(
        f"AI enrichment checked: provider={provider or 'unknown'}, articles={len(articles)}, conflicts={conflict_count}, invalid={invalid_count}, missing={missing_count}, missing_summaries={missing_summary_count}"
    )
    if missing_summary_count:
        result.warning(f"AI enrichment has {missing_summary_count} articles without summary_lines")


def check_classification_quality(result: Validation, out_dir: Path, report_date: str, site_dir: Path | None) -> None:
    dated = compact_date(report_date)
    brief_path = out_dir / f"daily_news_brief_{dated}.md"
    queue_path = out_dir / f"daily_news_review_queue_{dated}.csv"
    if not brief_path.exists() or not queue_path.exists():
        return
    brief_articles = markdown_articles(read_text(brief_path))
    queue_rows = read_csv_rows(queue_path)
    check_review_classification_quality(result, queue_rows)
    check_brief_review_alignment(result, brief_articles, queue_rows)
    check_ai_enrichment_classification_quality(result, out_dir, report_date, queue_rows)
    if site_dir is not None:
        check_archive_classification_quality(result, site_dir, out_dir, report_date, brief_articles, queue_rows)


def check_env_and_sources(result: Validation, env_path: Path, sources_path: Path) -> None:
    env_values = parse_env_file(env_path)
    active_sources = [row for row in read_csv_rows(sources_path) if row.get("is_active", "1") == "1"]
    active_naver = [row for row in active_sources if row.get("source_kind") == "naver_news_api"]
    if active_naver:
        missing = [key for key in ["NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"] if not env_values.get(key) and not os.environ.get(key)]
        if missing:
            result.error("active Naver sources exist but Naver credentials are missing")
        else:
            result.note(f"Naver credentials configured for {len(active_naver)} active Naver sources")
    if not active_sources:
        result.error("no active news sources configured")
    result.note(f"active source count: {len(active_sources)}")


def check_artifacts(result: Validation, out_dir: Path, report_date: str) -> None:
    dated = compact_date(report_date)
    paths = {
        "brief_md": out_dir / f"daily_news_brief_{dated}.md",
        "brief_html": out_dir / f"daily_news_brief_{dated}.html",
        "review_queue": out_dir / f"daily_news_review_queue_{dated}.csv",
        "review_actions": out_dir / f"daily_news_review_actions_{dated}.csv",
        "review_html": out_dir / f"daily_news_review_{dated}.html",
        "latest_md": out_dir / "daily_news_brief_latest.md",
        "latest_html": out_dir / "daily_news_brief_latest.html",
        "latest_review_actions": out_dir / "daily_news_review_actions_latest.csv",
    }
    for label, path in paths.items():
        if not path.exists():
            result.error(f"missing {label}: {path}")
        elif path.stat().st_size == 0:
            result.error(f"empty {label}: {path}")

    brief_text = read_text(paths["brief_md"])
    if not brief_text:
        return

    expected_coverage = coverage_window_label(report_date)
    if expected_coverage not in brief_text:
        result.error("brief markdown does not show the expected 24-hour coverage window")
    if "No search available" in brief_text:
        result.warning("brief markdown has no selected clips")

    links = markdown_links(brief_text)
    if not links:
        result.warning("brief markdown has no article links")
    url_keys: set[str] = set()
    title_keys: set[str] = set()
    title_rows: list[tuple[str, str]] = []
    google_redirect_count = 0
    for link in links:
        url_key = normalize_url(link["url"])
        title_key = normalize_title_key(link["title"])
        publisher_hint = link.get("publisher", "")
        if url_key in url_keys:
            result.error(f"duplicate URL in brief: {link['url']}")
        if title_key and (title_key in title_keys or is_near_duplicate_title_key(title_key, publisher_hint, title_rows)):
            result.error(f"duplicate-looking title in brief: {link['title']}")
        url_keys.add(url_key)
        title_keys.add(title_key)
        if title_key:
            title_rows.append((title_key, publisher_hint))
        if "news.google.com/" in link["url"]:
            google_redirect_count += 1
    if google_redirect_count:
        result.warning(f"Google News redirect links in brief: {google_redirect_count}")
    result.note(f"brief selected clip count: {len(links)}")

    queue_rows = read_csv_rows(paths["review_queue"])
    included_queue = [row for row in queue_rows if row.get("normalized_source_url") or row.get("source_url")]
    if len(included_queue) < len(links):
        result.warning("review queue has fewer rows than brief links")
    for row in queue_rows:
        include_flag = row.get("include_in_brief", "").upper()
        if include_flag == "Y":
            score = parse_float(row.get("quality_score", "0"))
            if score < EXPORT_MIN_QUALITY_SCORE:
                result.warning(f"included row below quality threshold: {row.get('title', '')} ({score})")

    action_rows = read_csv_rows(paths["review_actions"])
    for row in action_rows:
        category = row.get("category", "").strip()
        if category and category not in VALID_CATEGORY_LABELS:
            result.error(f"invalid review category '{category}' for title: {row.get('title', '')}")
        action = row.get("action", "").strip()
        if action and action not in {"include", "exclude"}:
            result.error(f"invalid review action '{action}' for title: {row.get('title', '')}")

    latest_text = read_text(paths["latest_md"])
    if latest_text and expected_coverage not in latest_text:
        result.warning("latest markdown is not aligned with the selected report date")

    final_latest = out_dir / "daily_news_final_latest.md"
    if final_latest.exists() and expected_coverage not in read_text(final_latest):
        result.warning("latest final file is older than the latest brief; finalization is pending")


def check_public_site(result: Validation, public_dir: Path, report_date: str) -> None:
    paths = {
        "public landing page": public_dir / "index.html",
        "public daily news page": public_dir / "daily-news.html",
        "public service stylesheet": public_dir / "assets" / "service.css",
    }
    for label, path in paths.items():
        if not path.exists():
            result.warning(f"missing {label}: {path}")
        elif path.stat().st_size == 0:
            result.warning(f"empty {label}: {path}")
    landing_text = read_text(paths["public landing page"])
    daily_text = read_text(paths["public daily news page"])
    display_report_date = report_date.replace("-", ".")
    for label, text in [("public landing page", landing_text), ("public daily news page", daily_text)]:
        if text and report_date not in text and display_report_date not in text:
            result.warning(f"{label} does not show report date {report_date}")
        for forbidden in ["KST", "최근 24시간", "선정 기사", "검수 후보", "Review Queue", "Raw HTML", "PC가 꺼져"]:
            if text and forbidden in text:
                result.warning(f"{label} exposes internal wording: {forbidden}")


def parse_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def check_built_site_bundle(result: Validation, site_dir: Path, report_date: str) -> None:
    health, archive = read_site_archive(site_dir)
    if not health:
        result.error(f"site health/archive files are not readable: {site_dir}")
        return
    if not archive:
        result.error(f"site archive is empty or unreadable: {site_dir / 'archive.json'}")
        return

    health_date = str(health.get("report_date") or "").strip()
    if health_date != report_date:
        result.error(f"site health report_date is {health_date or '-'}, not {report_date}")

    services = str(health.get("services") or "").strip()
    if services != "newsletter":
        result.error(f"site health services is {services or '-'}, not newsletter")

    for field in ["lp_monitor_count", "gp_count", "gp_profile_page_count"]:
        if parse_int(health.get(field)) != 0:
            result.error(f"newsletter-only bundle should not publish {field}={health.get(field)}")

    health_count = parse_int(health.get("article_count"))
    if health_count <= 0:
        result.error("site health article_count is zero")

    entry = next((row for row in archive if isinstance(row, dict) and row.get("reportDate") == report_date), None)
    if not isinstance(entry, dict):
        result.error(f"site archive missing reportDate={report_date}")
        return
    articles = entry.get("articles")
    if not isinstance(articles, list):
        result.error(f"site archive reportDate={report_date} has no article list")
        return
    archive_rows = [row for row in articles if isinstance(row, dict)]
    if not archive_rows:
        result.error(f"site archive reportDate={report_date} has no articles")
    if health_count != len(archive_rows):
        result.error(f"site health article_count {health_count} does not match archive count {len(archive_rows)}")
    check_archive_previous_duplicates(result, site_dir, report_date, archive_rows)
    result.note(f"site bundle checked: report_date={report_date}, articles={len(archive_rows)}")


def check_database(result: Validation, db_path: Path, report_date: str) -> None:
    if not db_path.exists():
        result.error(f"database missing: {db_path}")
        return
    conn = sqlite3.connect(db_path)
    try:
        existing_tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        for table in REQUIRED_TABLES:
            if table not in existing_tables:
                result.error(f"database table missing: {table}")
        row = conn.execute(
            """
            SELECT run_id, status, discovered_count, fetched_count, relevant_count, notes
            FROM news_run
            WHERE run_date = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (report_date,),
        ).fetchone()
        if not row:
            result.error(f"no news_run row for {report_date}")
            return
        run_id, status, discovered, fetched, relevant, notes = row
        if status != "completed":
            result.error(f"latest run is not completed: {run_id} status={status}")
        if int(discovered or 0) <= 0:
            result.error(f"latest run discovered no items: {run_id}")
        if int(fetched or 0) <= 0:
            result.error(f"latest run fetched no articles: {run_id}")
        if notes:
            result.warning(f"latest run has warnings: {str(notes).splitlines()[0]}")
        result.note(f"latest db run: {run_id}, discovered={discovered}, fetched={fetched}, selected={relevant}")
    finally:
        conn.close()


def parse_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def print_human(result: Validation) -> None:
    status = "OK" if not result.errors else "FAIL"
    print(f"Daily news validation: {status}")
    if result.errors:
        print("\nErrors")
        for message in result.errors:
            print(f"- {message}")
    if result.warnings:
        print("\nWarnings")
        for message in result.warnings:
            print(f"- {message}")
    if result.info:
        print("\nInfo")
        for message in result.info:
            print(f"- {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate daily news clipping outputs")
    parser.add_argument("--date", default=today_seoul())
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--public-dir", type=Path, default=REPO_ROOT / "services" / "newsletter" / "deploy" / "site")
    parser.add_argument("--site-dir", type=Path, default=None, help="Optional built deploy site directory for archive.json classification checks")
    parser.add_argument("--site-only", action="store_true", help="Validate only the generated public site bundle")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = Validation()
    if args.site_only:
        site_dir = args.site_dir or args.public_dir
        check_public_site(result, site_dir, args.date)
        check_built_site_bundle(result, site_dir, args.date)
    else:
        check_env_and_sources(result, args.env, args.sources)
        check_artifacts(result, args.out_dir, args.date)
        check_classification_quality(result, args.out_dir, args.date, args.site_dir)
        check_public_site(result, args.public_dir, args.date)
        check_database(result, args.db, args.date)

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        print_human(result)
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
