#!/usr/bin/env python
"""Create final daily news clipping files from the reviewed action CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from apply_daily_news_review import apply_review, normalize_action, normalize_category
from daily_news_common import DEFAULT_EXPORT_DIR, DEFAULT_OVERRIDES, split_news_title_badges, today_seoul
from run_daily_news_pipeline import SECTION_LABELS, SECTION_LABEL_TO_CODE, SECTION_ORDER, coverage_window_label


DEFAULT_REVIEW_FILE = DEFAULT_EXPORT_DIR / "daily_news_review_actions_latest.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def html_escape(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def canonical_section(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "Market"
    section = normalize_category(raw)
    if section:
        return section
    return SECTION_LABEL_TO_CODE.get(raw, "Market")


def include_row(row: dict[str, str]) -> bool:
    action = normalize_action(row.get("action", ""))
    if action == "exclude":
        return False
    if action == "include":
        return True
    return row.get("include_in_brief", "").strip().upper() == "Y"


def final_rows(review_file: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for row in read_csv(review_file):
        if not include_row(row):
            continue
        url = row.get("normalized_source_url") or row.get("source_url") or ""
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        section = canonical_section(row.get("category") or row.get("current_category"))
        output = dict(row)
        output["final_section"] = section
        output["title"], _badges = split_news_title_badges(output.get("title", ""), output.get("publisher", ""))
        rows.append(output)
    return rows


def grouped_rows(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped = {section: [] for section in SECTION_ORDER}
    for row in rows:
        grouped.setdefault(row.get("final_section", "Market"), []).append(row)
    return grouped


def render_markdown(report_date: str, rows: list[dict[str, str]]) -> str:
    grouped = grouped_rows(rows)
    lines = [f"일자 : {report_date}", coverage_window_label(report_date), ""]
    if not rows:
        lines.append("No confirmed clips")
        return "\n".join(lines) + "\n"
    for section in SECTION_ORDER:
        section_rows = grouped.get(section, [])
        if not section_rows:
            continue
        lines.append(f"[{SECTION_LABELS.get(section, section)}]")
        for row in section_rows:
            title = row.get("title", "")
            url = row.get("source_url", "")
            publisher = row.get("publisher", "")
            lines.append(f"- [{title}]({url})")
            if publisher:
                lines.append(f"  출처: {publisher}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(report_date: str, rows: list[dict[str, str]]) -> str:
    grouped = grouped_rows(rows)
    coverage = coverage_window_label(report_date).replace("기준 : ", "")
    sections: list[str] = []
    for section in SECTION_ORDER:
        section_rows = grouped.get(section, [])
        if not section_rows:
            continue
        clips: list[str] = []
        for row in section_rows:
            publisher = row.get("publisher", "")
            clips.append(
                """
                <li class="clip">
                  <a href="{url}" target="_blank" rel="noreferrer">{title}</a>
                  {source}
                </li>
                """.strip().format(
                    url=html_escape(row.get("source_url", "")),
                    title=html_escape(row.get("title", "")),
                    source=f"<span class=\"source\">출처: {html_escape(publisher)}</span>" if publisher else "",
                )
            )
        sections.append(
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
    body = "\n".join(sections) if sections else "<p>확정된 클립이 없습니다.</p>"
    return (
        "<!doctype html>\n"
        "<html lang=\"ko\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"  <title>Final Daily PEF Clipping {html_escape(report_date)}</title>\n"
        "  <style>\n"
        "    body { margin: 0; font-family: 'Pretendard', 'Noto Sans KR', sans-serif; background: #fff; color: #111; }\n"
        "    main { width: min(880px, calc(100vw - 32px)); margin: 0 auto; padding: 28px 0 52px; }\n"
        "    h1 { margin: 0 0 6px; font-size: 26px; letter-spacing: -0.02em; }\n"
        "    .sub { color: #555; margin: 0 0 28px; }\n"
        "    section { margin: 30px 0 34px; }\n"
        "    h2 { margin: 0 0 12px; font-size: 17px; border-bottom: 1px solid #111; padding-bottom: 7px; }\n"
        "    ul { list-style: none; margin: 0; padding: 0; }\n"
        "    .clip { border-bottom: 1px solid #e6e6e6; padding: 11px 0 10px; line-height: 1.45; }\n"
        "    a { color: inherit; text-decoration: none; font-weight: 650; }\n"
        "    a:hover { text-decoration: underline; text-underline-offset: 3px; }\n"
        "    .source { display: block; color: #555; font-size: 12px; margin-top: 4px; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        "    <h1>Daily PEF Clipping</h1>\n"
        f"    <p class=\"sub\">{html_escape(report_date)} · {html_escape(coverage)} · Final</p>\n"
        f"{body}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def finalize_review(
    review_file: Path,
    out_dir: Path,
    report_date: str,
    apply_to_overrides: bool = False,
    overrides_file: Path = DEFAULT_OVERRIDES,
    write_latest: bool = True,
) -> dict[str, object]:
    rows = final_rows(review_file)
    out_dir.mkdir(parents=True, exist_ok=True)
    dated = report_date.replace("-", "")
    markdown_path = out_dir / f"daily_news_final_{dated}.md"
    html_path = out_dir / f"daily_news_final_{dated}.html"
    latest_markdown_path = out_dir / "daily_news_final_latest.md"
    latest_html_path = out_dir / "daily_news_final_latest.html"
    markdown_text = render_markdown(report_date, rows)
    html_text = render_html(report_date, rows)
    markdown_path.write_text(markdown_text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    if write_latest:
        latest_markdown_path.write_text(markdown_text, encoding="utf-8")
        latest_html_path.write_text(html_text, encoding="utf-8")
    override_result = {"changed": 0, "skipped": 0, "total_overrides": 0}
    if apply_to_overrides:
        override_result = apply_review(review_file, overrides_file)
    return {
        "report_date": report_date,
        "final_count": len(rows),
        "markdown_path": str(markdown_path),
        "html_path": str(html_path),
        "latest_markdown_path": str(latest_markdown_path),
        "latest_html_path": str(latest_html_path),
        "overrides": override_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize reviewed daily PEF clipping")
    parser.add_argument("--review-file", type=Path, default=DEFAULT_REVIEW_FILE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--date", default=today_seoul())
    parser.add_argument("--apply-overrides", action="store_true")
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--no-latest", action="store_true")
    args = parser.parse_args()

    result = finalize_review(args.review_file, args.out_dir, args.date, args.apply_overrides, args.overrides, write_latest=not args.no_latest)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
