#!/usr/bin/env python
"""Local browser UI for reviewing and finalizing daily news clipping."""

from __future__ import annotations

import argparse
import csv
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from daily_news_common import DEFAULT_EXPORT_DIR, today_seoul
from finalize_daily_news_review import DEFAULT_REVIEW_FILE, finalize_review
from run_daily_news_pipeline import coverage_window_label
from run_daily_news_pipeline import SECTION_LABELS, SECTION_ORDER


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


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_HEADERS)
        writer.writeheader()
        writer.writerows([{header: row.get(header, "") for header in REVIEW_HEADERS} for row in rows])


def available_dates(out_dir: Path) -> list[str]:
    dates: list[str] = []
    for path in out_dir.glob("daily_news_review_actions_*.csv"):
        match = re.fullmatch(r"daily_news_review_actions_(\d{8})\.csv", path.name)
        if not match:
            continue
        raw = match.group(1)
        dates.append(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
    return sorted(set(dates), reverse=True)


def latest_available_date(out_dir: Path, fallback: str) -> str:
    dates = available_dates(out_dir)
    return dates[0] if dates else fallback


def review_file_for_date(out_dir: Path, report_date: str) -> Path:
    return out_dir / f"daily_news_review_actions_{report_date.replace('-', '')}.csv"


def final_file_for_date(out_dir: Path, report_date: str) -> Path:
    return out_dir / f"daily_news_final_{report_date.replace('-', '')}.html"


def should_write_latest(out_dir: Path, report_date: str) -> bool:
    return report_date == latest_available_date(out_dir, report_date)


def html_escape(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def selected(value: str, expected: str) -> str:
    return " selected" if (value or "") == expected else ""


def render_date_options(dates: list[str], current: str) -> str:
    if current not in dates:
        dates = [current] + dates
    return "\n".join(
        "<option value=\"{date}\"{selected}>{date}</option>".format(
            date=html_escape(date),
            selected=selected(current, date),
        )
        for date in dates
    )


def render_category_options(current: str) -> str:
    options = ["<option value=\"\">자동</option>"]
    for section in SECTION_ORDER:
        label = SECTION_LABELS[section]
        options.append(
            "<option value=\"{label}\"{selected}>{label}</option>".format(
                label=html_escape(label),
                selected=selected(current, label),
            )
        )
    return "\n".join(options)


def render_action_options(current: str) -> str:
    labels = [
        ("", "자동"),
        ("include", "포함"),
        ("exclude", "제외"),
    ]
    return "\n".join(
        "<option value=\"{value}\"{selected}>{label}</option>".format(
            value=value,
            selected=selected(current, value),
            label=label,
        )
        for value, label in labels
    )


def render_page(out_dir: Path, report_date: str, final_message: str = "") -> str:
    review_file = review_file_for_date(out_dir, report_date)
    rows = read_csv(review_file)
    included = sum(1 for row in rows if row.get("include_in_brief", "").upper() == "Y")
    dates = available_dates(out_dir)
    coverage = coverage_window_label(report_date).replace("기준 : ", "")
    body_rows: list[str] = []
    for index, row in enumerate(rows):
        title = row.get("title", "")
        source_url = row.get("source_url", "")
        summary = row.get("summary_text", "")[:260]
        current_category = row.get("current_category", "")
        category_value = row.get("category", "")
        body_rows.append(
            """
            <tr>
              <td class="controls">
                <input type="hidden" name="url_{index}" value="{normalized_url}">
                <select name="action_{index}">{action_options}</select>
                <select name="category_{index}">{category_options}</select>
                <input name="notes_{index}" value="{notes}" placeholder="메모">
              </td>
              <td class="include">{include}</td>
              <td>{current_category}</td>
              <td>{publisher}</td>
              <td class="article">
                <a href="{source_url}" target="_blank" rel="noreferrer">{title}</a>
                <div>{summary}</div>
                <small>{gp_names}</small>
              </td>
              <td>{quality_score}</td>
            </tr>
            """.strip().format(
                index=index,
                normalized_url=html_escape(row.get("normalized_source_url", "")),
                action_options=render_action_options(row.get("action", "")),
                category_options=render_category_options(category_value),
                notes=html_escape(row.get("notes", "")),
                include=html_escape(row.get("include_in_brief", "")),
                current_category=html_escape(current_category),
                publisher=html_escape(row.get("publisher", "")),
                source_url=html_escape(source_url),
                title=html_escape(title),
                summary=html_escape(summary),
                gp_names=html_escape(row.get("gp_names", "")),
                quality_score=html_escape(row.get("quality_score", "")),
            )
        )
    message_html = f"<p class=\"message\">{html_escape(final_message)}</p>" if final_message else ""
    return (
        "<!doctype html>\n"
        "<html lang=\"ko\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "  <title>Daily PEF Review</title>\n"
        "  <style>\n"
        "    body { margin: 0; font-family: 'Pretendard', 'Noto Sans KR', sans-serif; background: #fff; color: #111; }\n"
        "    main { width: min(1240px, calc(100vw - 28px)); margin: 0 auto; padding: 24px 0 56px; }\n"
        "    h1 { margin: 0 0 6px; font-size: 25px; letter-spacing: -0.02em; }\n"
        "    .sub, .help { color: #555; line-height: 1.55; }\n"
        "    .message { border: 1px solid #111; padding: 10px 12px; color: #111; }\n"
        "    .bar { display: flex; gap: 8px; align-items: center; margin: 18px 0; flex-wrap: wrap; }\n"
        "    .datebar { display: flex; gap: 8px; align-items: center; margin: 16px 0; }\n"
        "    button { border: 1px solid #111; background: #111; color: #fff; padding: 9px 13px; cursor: pointer; }\n"
        "    button.secondary { background: #fff; color: #111; }\n"
        "    table { width: 100%; border-collapse: collapse; font-size: 13px; }\n"
        "    th { text-align: left; border-bottom: 1px solid #111; padding: 8px 6px; white-space: nowrap; }\n"
        "    td { vertical-align: top; border-bottom: 1px solid #e6e6e6; padding: 8px 6px; line-height: 1.45; }\n"
        "    select, input { max-width: 150px; border: 1px solid #cfcfcf; padding: 5px; margin: 0 0 5px; }\n"
        "    .controls { width: 180px; }\n"
        "    .include { text-align: center; width: 42px; }\n"
        "    .article a { color: inherit; font-weight: 650; text-decoration: none; }\n"
        "    .article a:hover { text-decoration: underline; text-underline-offset: 3px; }\n"
        "    .article div { color: #555; margin-top: 4px; }\n"
        "    .article small { display: block; color: #777; margin-top: 4px; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        "    <h1>Daily PEF Review</h1>\n"
        f"    <p class=\"sub\">{html_escape(report_date)} · {html_escape(coverage)} · 후보 {len(rows)}건 · 현재 포함 {included}건</p>\n"
        "    <form class=\"datebar\" method=\"get\" action=\"/\">\n"
        "      <label for=\"date\">날짜</label>\n"
        f"      <select id=\"date\" name=\"date\" onchange=\"this.form.submit()\">{render_date_options(dates, report_date)}</select>\n"
        "      <button class=\"secondary\" type=\"submit\">이동</button>\n"
        "    </form>\n"
        f"    {message_html}\n"
        "    <p class=\"help\">각 기사에서 액션을 고른 뒤 저장하세요. 확정 버튼은 저장된 상태로 최종본 파일을 생성하고, 변경사항을 다음 실행에도 반영합니다.</p>\n"
        "    <form method=\"post\" action=\"/save\">\n"
        f"      <input type=\"hidden\" name=\"row_count\" value=\"{len(rows)}\">\n"
        f"      <input type=\"hidden\" name=\"report_date\" value=\"{html_escape(report_date)}\">\n"
        "      <div class=\"bar\">\n"
        "        <button type=\"submit\">저장</button>\n"
        "        <button class=\"secondary\" formaction=\"/finalize\" type=\"submit\">최종본 확정</button>\n"
        f"        <a href=\"/final?date={html_escape(report_date)}\" target=\"_blank\">최종본 보기</a>\n"
        "      </div>\n"
        "      <table>\n"
        "        <thead><tr><th>검수</th><th>포함</th><th>현재분류</th><th>출처</th><th>기사</th><th>점수</th></tr></thead>\n"
        f"        <tbody>{''.join(body_rows)}</tbody>\n"
        "      </table>\n"
        "    </form>\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


class ReviewHandler(BaseHTTPRequestHandler):
    out_dir: Path = DEFAULT_EXPORT_DIR
    report_date: str = today_seoul()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        report_date = self.requested_date(parsed.query)
        if parsed.path == "/final":
            final_path = final_file_for_date(self.out_dir, report_date)
            if final_path.exists():
                self.respond(final_path.read_text(encoding="utf-8"), "text/html")
            else:
                self.respond(render_page(self.out_dir, report_date, "이 날짜의 확정본이 아직 없습니다."), "text/html")
            return
        self.respond(render_page(self.out_dir, report_date), "text/html")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        payload = self.rfile.read(length).decode("utf-8")
        form = parse_qs(payload, keep_blank_values=True)
        report_date = first(form.get("report_date"), self.report_date)
        review_file = review_file_for_date(self.out_dir, report_date)
        self.save_form(form, review_file, report_date)
        parsed = urlparse(self.path)
        if parsed.path == "/finalize":
            result = finalize_review(
                review_file,
                self.out_dir,
                report_date,
                apply_to_overrides=True,
                write_latest=should_write_latest(self.out_dir, report_date),
            )
            message = f"최종본 확정 완료: {result['final_count']}건"
            self.respond(render_page(self.out_dir, report_date, message), "text/html")
            return
        self.respond(render_page(self.out_dir, report_date, "저장 완료"), "text/html")

    def requested_date(self, query: str) -> str:
        params = parse_qs(query, keep_blank_values=True)
        requested = first(params.get("date"), "")
        if requested and re.fullmatch(r"\d{4}-\d{2}-\d{2}", requested):
            return requested
        return latest_available_date(self.out_dir, self.report_date)

    def save_form(self, form: dict[str, list[str]], review_file: Path, report_date: str) -> None:
        rows = read_csv(review_file)
        row_count = int(first(form.get("row_count"), "0") or 0)
        by_url = {row.get("normalized_source_url", ""): row for row in rows}
        for index in range(row_count):
            url = first(form.get(f"url_{index}"), "")
            if not url or url not in by_url:
                continue
            row = by_url[url]
            row["action"] = first(form.get(f"action_{index}"), "")
            row["category"] = first(form.get(f"category_{index}"), "")
            row["notes"] = first(form.get(f"notes_{index}"), "")
        write_csv(review_file, rows)
        if should_write_latest(self.out_dir, report_date):
            write_csv(self.out_dir / "daily_news_review_actions_latest.csv", rows)

    def respond(self, body: str, content_type: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


def first(values: list[str] | None, default: str) -> str:
    if not values:
        return default
    return values[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local daily news review UI")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--date", default="")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    ReviewHandler.out_dir = args.out_dir
    ReviewHandler.report_date = args.date or latest_available_date(args.out_dir, today_seoul())
    server = ThreadingHTTPServer((args.host, args.port), ReviewHandler)
    print(f"Review UI: http://{args.host}:{args.port}/")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
