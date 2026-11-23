#!/usr/bin/env python
"""Add late-distributed stories to briefs already published (one-off backfill).

Until 2026-11-23 a story whose page date was earlier than the brief window was
dropped even when the news portal distributed it, and we first saw it, inside the
window (e.g. 서울경제 [시그널] posted on its premium page days before Naver). The
daily run now keeps such stories (run_daily_news_pipeline.is_late_distribution).
This tool applies the same rule to past briefs in the published archive:

- for each brief date, take relevant stories of any run that only the
  late-distribution rule places in that window;
- pass them through the daily editorial filters (quality, export rule, brief
  selection) and skip any story already in the archive (URL or title, any date);
- append them to that date's brief and rewrite archive.json and the archive
  embedded in index.html / daily-news.html.

Without --apply it only reports. User decision 2026-11-23: missing a story is worse
than repeating an event another outlet already covered.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import run_daily_news_pipeline as pipeline  # noqa: E402
from services.newsletter.src.newsletter_entity_tags import apply_display_tags  # noqa: E402
from services.newsletter.src.newsletter_renderer import (  # noqa: E402
    article_payload_rows,
    context_entry,
    parse_brief,
    service_context_keys,
    split_context_names,
)
from services.newsletter.src.newsletter_site_support import ARCHIVE_SCRIPT_RE  # noqa: E402

BRIEF_LIMIT = 30
ARCHIVE_HTML_FILES = ("index.html", "daily-news.html")


def archive_keys(archive: list[dict[str, object]]) -> dict[str, set[str]]:
    urls: set[str] = set()
    titles: set[str] = set()
    for entry in archive:
        for article in entry.get("articles") or []:
            if isinstance(article, dict):
                pipeline.add_previous_key(
                    str(article.get("url") or article.get("sourceUrl") or ""),
                    str(article.get("title") or ""),
                    urls,
                    titles,
                )
    return {"urls": urls, "titles": titles}


def previous_events(archive: list[dict[str, object]], report_date: str) -> set[str]:
    """Curated event keys of earlier briefs, as the daily run skips them."""
    events: set[str] = set()
    for entry in archive:
        if str(entry.get("reportDate") or "") >= report_date:
            continue
        for article in entry.get("articles") or []:
            if not isinstance(article, dict):
                continue
            key = pipeline.event_dedupe_key(
                {
                    "title": str(article.get("title") or ""),
                    "summary_text": str(article.get("summaryText") or ""),
                    "section_tags": str(article.get("rawSection") or article.get("section") or ""),
                }
            )
            if key:
                events.add(key)
    return events


def select_late_rows(
    conn: sqlite3.Connection,
    report_date: str,
    keys: dict[str, set[str]],
    events: set[str],
    limit: int,
) -> list[dict[str, object]]:
    eligible: list[dict[str, object]] = []
    previous = {"urls": keys["urls"], "titles": keys["titles"], "events": events}
    for row in pipeline.load_late_distribution_rows(conn, report_date):
        row["quality_score"], row["quality_reason"] = pipeline.editorial_quality(row)
        if pipeline.is_previous_export(row, previous):
            continue
        if pipeline.should_export_row(row):
            eligible.append(row)
    eligible.sort(key=pipeline.quality_sort_key)
    return pipeline.select_brief_rows(eligible, limit) if limit > 0 else []


def article_entries(report_date: str, rows: list[dict[str, object]], first_index: int) -> list[dict[str, object]]:
    """Archive article dicts built the way the daily site build makes them."""
    context: dict[str, dict[str, object]] = {}
    for row in rows:
        names = split_context_names(row.get("gp_names", ""))
        summary = pipeline.normalize_whitespace(str(row.get("summary_text") or ""))
        for key in service_context_keys(row.get("source_url", ""), row.get("normalized_source_url", "")):
            entry = context.setdefault(key, context_entry())
            if summary:
                entry["summaryText"] = summary
            for name in names:
                if name not in entry["gpNames"]:
                    entry["gpNames"].append(name)
                    entry["searchTerms"].append(name)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"daily_news_brief_{report_date.replace('-', '')}.md"
        path.write_text(pipeline.render_markdown(report_date, rows), encoding="utf-8")
        parsed = parse_brief(path)
    articles = article_payload_rows(parsed, context, f"clip-{report_date.replace('-', '')}")
    for offset, article in enumerate(articles):
        article["id"] = f"clip-{report_date.replace('-', '')}-{first_index + offset}"
    return articles


def merge_into_entry(entry: dict[str, object], additions: list[dict[str, object]]) -> dict[str, object]:
    """Insert each addition after the last article of its section (or an earlier one).

    Existing articles keep their order; only ranks are renumbered.
    """
    articles = [dict(article) for article in entry.get("articles") or [] if isinstance(article, dict)]
    for addition in additions:
        order = int(addition.get("sectionOrder", 99) or 0)
        position = 0
        for index, article in enumerate(articles):
            if int(article.get("sectionOrder", 99) or 0) <= order:
                position = index + 1
        articles.insert(position, dict(addition))
    for rank, article in enumerate(articles):
        article["rank"] = rank
    return {**entry, "articles": articles, "articleCount": len(articles)}


def backfill(
    conn: sqlite3.Connection,
    archive: list[dict[str, object]],
    start: str,
    end: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    keys = archive_keys(archive)
    report: list[dict[str, object]] = []
    updated: list[dict[str, object]] = []
    for entry in archive:
        report_date = str(entry.get("reportDate") or "")
        if not (start <= report_date <= end):
            updated.append(entry)
            continue
        existing = [article for article in entry.get("articles") or [] if isinstance(article, dict)]
        rows = select_late_rows(
            conn, report_date, keys, previous_events(archive, report_date), BRIEF_LIMIT - len(existing)
        )
        additions = article_entries(report_date, rows, len(existing)) if rows else []
        for row in rows:
            pipeline.add_previous_key(
                str(row.get("normalized_source_url") or row.get("source_url") or ""),
                str(row.get("title") or ""),
                keys["urls"],
                keys["titles"],
            )
        updated.append(merge_into_entry(entry, additions) if additions else entry)
        report.append(
            {
                "report_date": report_date,
                "before": len(existing),
                "added": [
                    {"publisher": a.get("source"), "title": a.get("title"), "url": a.get("url"), "section": a.get("section")}
                    for a in additions
                ],
            }
        )
    return updated, report


def write_site(site_dir: Path, archive: list[dict[str, object]], previous: list[dict[str, object]]) -> None:
    archive = apply_display_tags(archive, previous)
    (site_dir / "archive.json").write_text(json.dumps(archive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload = json.dumps(archive, ensure_ascii=False).replace("</", "<\\/")
    for name in ARCHIVE_HTML_FILES:
        path = site_dir / name
        html = path.read_text(encoding="utf-8")
        matches = list(ARCHIVE_SCRIPT_RE.finditer(html))
        if len(matches) != 1:
            raise RuntimeError(f"{name}: expected one embedded archive, found {len(matches)}")
        match = matches[0]
        replaced = f"<script>window.KPEF_DAILY_ARCHIVE = {payload};</script>"
        path.write_text(html[: match.start()] + replaced + html[match.end():], encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--site-dir", type=Path, required=True, help="checked-out public mirror (gh-pages)")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--report-out", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    for value in (args.start, args.end):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise SystemExit(f"invalid date: {value}")
    archive = json.loads((args.site_dir / "archive.json").read_text(encoding="utf-8"))
    with sqlite3.connect(args.db) as conn:
        updated, report = backfill(conn, archive, args.start, args.end)
    added = sum(len(item["added"]) for item in report)
    summary = {"applied": bool(args.apply and added), "added": added, "dates": report}
    if args.report_out:
        args.report_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for item in report:
        for article in item["added"]:
            print(f"{item['report_date']} +[{article['section']}] {article['publisher']} | {article['title']}")
    print(f"late_distribution_backfill added={added} apply={args.apply}")
    if args.apply and added:
        write_site(args.site_dir, updated, archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
