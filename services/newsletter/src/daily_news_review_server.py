#!/usr/bin/env python
"""Local browser UI for reviewing and finalizing daily news clipping."""

from __future__ import annotations

import argparse
import csv
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from daily_news_common import DEFAULT_EXPORT_DIR, DEFAULT_OVERRIDES, load_manual_overrides, split_semicolon, today_seoul
from finalize_daily_news_review import DEFAULT_REVIEW_FILE, finalize_review
from run_daily_news_pipeline import coverage_window_label
from run_daily_news_pipeline import SECTION_LABELS, SECTION_LABEL_TO_CODE, SECTION_ORDER


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


def override_section_label(manual_tags: str) -> str:
    for tag in split_semicolon(manual_tags):
        if not tag.startswith("section_override:"):
            continue
        raw = tag.split(":", 1)[1].strip()
        code = SECTION_LABEL_TO_CODE.get(raw) or (raw if raw in SECTION_ORDER else "")
        if code:
            return SECTION_LABELS.get(code, code)
    return ""


def rows_with_manual_overrides(rows: list[dict[str, str]], overrides_file: Path = DEFAULT_OVERRIDES) -> list[dict[str, str]]:
    overrides = load_manual_overrides(overrides_file)
    if not overrides:
        return rows
    merged: list[dict[str, str]] = []
    for row in rows:
        next_row = dict(row)
        override = overrides.get(row.get("normalized_source_url", ""))
        if override:
            review_status = (override.get("review_status") or "").strip()
            if review_status == "force_exclude" or override.get("force_exclude", "").lower() in {"1", "true", "y", "yes"}:
                next_row["action"] = "exclude"
            elif review_status == "force_include" or override.get("force_include", "").lower() in {"1", "true", "y", "yes"}:
                next_row["action"] = next_row.get("action") or "include"
            section_label = override_section_label(override.get("manual_tags", ""))
            if section_label:
                next_row["category"] = section_label
        merged.append(next_row)
    return merged


def section_code(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    return SECTION_LABEL_TO_CODE.get(raw) or (raw if raw in SECTION_ORDER else "")


def card_lane(row: dict[str, str]) -> str:
    if row.get("action", "").strip().lower() == "exclude":
        return "Exclude"
    return section_code(row.get("category") or row.get("current_category")) or "Market"


def render_review_card(row: dict[str, str], index: int) -> str:
    title = row.get("title", "")
    source_url = row.get("source_url", "")
    summary = row.get("summary_text", "")[:220]
    current_category = row.get("current_category", "")
    gp_names = row.get("gp_names", "")
    normalized_url = row.get("normalized_source_url", "")
    include = row.get("include_in_brief", "")
    action = row.get("action", "")
    category = row.get("category", "")
    notes = row.get("notes", "")
    return """
      <article class="review-card{excluded}" draggable="true" data-card data-index="{index}">
        <input type="hidden" name="url_{index}" value="{normalized_url}">
        <input type="hidden" name="category_{index}" value="{category}" data-category-field>
        <div class="card-top">
          <span>{publisher}</span>
          <span>{include_label}</span>
        </div>
        <a class="card-title" href="{source_url}" target="_blank" rel="noreferrer">{title}</a>
        <p>{summary}</p>
        {gp_html}
        <div class="card-controls">
          <label>
            처리
            <select name="action_{index}" data-action-field>{action_options}</select>
          </label>
          <label>
            메모
            <input name="notes_{index}" value="{notes}" placeholder="분류 사유">
          </label>
        </div>
        <small>현재 {current_category} · 점수 {quality_score}</small>
      </article>
    """.strip().format(
        excluded=" excluded" if action == "exclude" else "",
        index=index,
        normalized_url=html_escape(normalized_url),
        category=html_escape(category),
        publisher=html_escape(row.get("publisher", "")),
        include_label="발행대상" if include.upper() == "Y" else "후보",
        source_url=html_escape(source_url),
        title=html_escape(title),
        summary=html_escape(summary),
        gp_html=f"<div class=\"gp-names\">{html_escape(gp_names)}</div>" if gp_names else "",
        action_options=render_action_options(action),
        notes=html_escape(notes),
        current_category=html_escape(current_category or "-"),
        quality_score=html_escape(row.get("quality_score", "")),
    )


def render_lane(code: str, rows: list[str]) -> str:
    is_exclude = code == "Exclude"
    label = "제외" if is_exclude else SECTION_LABELS.get(code, code)
    action = "exclude" if is_exclude else ""
    return """
      <section class="review-lane{exclude_class}" data-lane data-category="{category}" data-label="{label}" data-action="{action}">
        <header>
          <h2>{label}</h2>
          <span data-count>{count}</span>
        </header>
        <div class="lane-body" data-lane-body>
          {cards}
        </div>
      </section>
    """.strip().format(
        exclude_class=" is-exclude" if is_exclude else "",
        category="" if is_exclude else html_escape(code),
        label=html_escape(label),
        action=action,
        count=len(rows),
        cards="\n".join(rows),
    )


def render_page(out_dir: Path, report_date: str, final_message: str = "") -> str:
    review_file = review_file_for_date(out_dir, report_date)
    rows = rows_with_manual_overrides(read_csv(review_file))
    included = sum(1 for row in rows if row.get("include_in_brief", "").upper() == "Y")
    dates = available_dates(out_dir)
    coverage = coverage_window_label(report_date).replace("기준 : ", "")
    cards_by_lane: dict[str, list[str]] = {section: [] for section in SECTION_ORDER}
    cards_by_lane["Exclude"] = []
    for index, row in enumerate(rows):
        lane = card_lane(row)
        cards_by_lane.setdefault(lane, []).append(render_review_card(row, index))
    lanes = "\n".join(render_lane(section, cards_by_lane.get(section, [])) for section in [*SECTION_ORDER, "Exclude"])
    message_html = f"<p class=\"message\">{html_escape(final_message)}</p>" if final_message else ""
    return (
        "<!doctype html>\n"
        "<html lang=\"ko\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "  <title>뉴스레터 운영자</title>\n"
        "  <style>\n"
        "    :root { color-scheme: light; --line: #e5e7eb; --muted: #667085; --ink: #101828; --bg: #f6f7f9; }\n"
        "    * { box-sizing: border-box; }\n"
        "    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Pretendard', 'Noto Sans KR', sans-serif; background: var(--bg); color: var(--ink); }\n"
        "    main { width: min(1480px, calc(100vw - 28px)); margin: 0 auto; padding: 22px 0 56px; }\n"
        "    h1 { margin: 0 0 6px; font-size: 25px; letter-spacing: 0; }\n"
        "    .sub, .help { color: var(--muted); line-height: 1.55; margin: 0; }\n"
        "    .message { border: 1px solid #111827; padding: 10px 12px; color: #111827; background: #fff; }\n"
        "    .bar, .datebar { display: flex; gap: 8px; align-items: center; margin: 16px 0; flex-wrap: wrap; }\n"
        "    button { border: 1px solid #111827; background: #111827; color: #fff; border-radius: 8px; padding: 9px 13px; cursor: pointer; font-weight: 650; }\n"
        "    button.secondary { background: #fff; color: #111827; }\n"
        "    a { color: inherit; text-decoration: none; }\n"
        "    a:hover { text-decoration: underline; text-underline-offset: 3px; }\n"
        "    select, input { border: 1px solid #d0d5dd; border-radius: 7px; background: #fff; padding: 7px 8px; font: inherit; min-width: 0; }\n"
        "    .board { display: grid; grid-template-columns: repeat(7, minmax(220px, 1fr)); gap: 10px; align-items: start; overflow-x: auto; padding: 4px 0 10px; }\n"
        "    .review-lane { min-height: 62vh; border: 1px solid var(--line); border-radius: 10px; background: #fff; }\n"
        "    .review-lane.drag-over { outline: 2px solid #111827; outline-offset: 2px; }\n"
        "    .review-lane header { position: sticky; top: 0; z-index: 1; display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 10px 10px 9px; border-bottom: 1px solid var(--line); background: rgba(255,255,255,.96); }\n"
        "    .review-lane h2 { margin: 0; font-size: 14px; letter-spacing: 0; }\n"
        "    .review-lane header span { color: var(--muted); font-size: 12px; }\n"
        "    .lane-body { min-height: 54vh; padding: 8px; display: grid; gap: 8px; align-content: start; }\n"
        "    .review-card { border: 1px solid var(--line); border-radius: 8px; background: #fff; padding: 10px; cursor: grab; box-shadow: 0 1px 2px rgba(16,24,40,.04); }\n"
        "    .review-card.dragging { opacity: .48; }\n"
        "    .review-card.excluded { opacity: .72; background: #f9fafb; }\n"
        "    .card-top { display: flex; justify-content: space-between; gap: 8px; color: var(--muted); font-size: 12px; margin-bottom: 6px; }\n"
        "    .card-title { display: block; font-weight: 720; line-height: 1.35; font-size: 14px; }\n"
        "    .review-card p { margin: 7px 0 0; color: #475467; font-size: 12px; line-height: 1.45; }\n"
        "    .gp-names { margin-top: 7px; color: #344054; font-size: 12px; font-weight: 650; }\n"
        "    .card-controls { display: grid; gap: 6px; margin-top: 9px; }\n"
        "    .card-controls label { display: grid; gap: 4px; color: var(--muted); font-size: 11px; }\n"
        "    .card-controls select, .card-controls input { width: 100%; font-size: 12px; padding: 6px 7px; }\n"
        "    .review-card small { display: block; color: var(--muted); margin-top: 7px; font-size: 11px; }\n"
        "    @media (max-width: 760px) { main { width: calc(100vw - 18px); padding-top: 14px; } .board { grid-template-columns: repeat(7, 82vw); } .review-lane { min-height: 65vh; } }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        "    <h1>뉴스레터 운영자</h1>\n"
        f"    <p class=\"sub\">{html_escape(report_date)} · {html_escape(coverage)} · 후보 {len(rows)}건 · 현재 포함 {included}건</p>\n"
        "    <form class=\"datebar\" method=\"get\" action=\"/\">\n"
        "      <label for=\"date\">날짜</label>\n"
        f"      <select id=\"date\" name=\"date\" onchange=\"this.form.submit()\">{render_date_options(dates, report_date)}</select>\n"
        "      <button class=\"secondary\" type=\"submit\">이동</button>\n"
        "    </form>\n"
        f"    {message_html}\n"
        "    <p class=\"help\">기사를 원하는 분류 칸으로 끌어놓고 저장하세요. 제외 칸으로 옮기면 다음 실행부터 빠집니다.</p>\n"
        "    <form method=\"post\" action=\"/save\">\n"
        f"      <input type=\"hidden\" name=\"row_count\" value=\"{len(rows)}\">\n"
        f"      <input type=\"hidden\" name=\"report_date\" value=\"{html_escape(report_date)}\">\n"
        "      <div class=\"bar\">\n"
        "        <button type=\"submit\">저장</button>\n"
        "        <button class=\"secondary\" formaction=\"/finalize\" type=\"submit\">최종본 확정</button>\n"
        f"        <a href=\"/final?date={html_escape(report_date)}\" target=\"_blank\">최종본 보기</a>\n"
        "      </div>\n"
        f"      <div class=\"board\" data-board>{lanes}</div>\n"
        "    </form>\n"
        "  </main>\n"
        "  <script>\n"
        "    const cards = [...document.querySelectorAll('[data-card]')];\n"
        "    const lanes = [...document.querySelectorAll('[data-lane]')];\n"
        "    const updateCounts = () => lanes.forEach((lane) => { const count = lane.querySelectorAll('[data-card]').length; const node = lane.querySelector('[data-count]'); if (node) node.textContent = count; });\n"
        "    const updateCard = (card, lane) => {\n"
        "      const categoryField = card.querySelector('[data-category-field]');\n"
        "      const actionField = card.querySelector('[data-action-field]');\n"
        "      const action = lane.dataset.action || '';\n"
        "      const label = lane.dataset.label || '';\n"
        "      if (categoryField) categoryField.value = action === 'exclude' ? '' : label;\n"
        "      if (actionField && action === 'exclude') actionField.value = 'exclude';\n"
        "      if (actionField && action !== 'exclude' && actionField.value === 'exclude') actionField.value = '';\n"
        "      card.classList.toggle('excluded', action === 'exclude');\n"
        "    };\n"
        "    cards.forEach((card) => {\n"
        "      card.addEventListener('dragstart', (event) => { card.classList.add('dragging'); event.dataTransfer.setData('text/plain', card.dataset.index || ''); });\n"
        "      card.addEventListener('dragend', () => card.classList.remove('dragging'));\n"
        "    });\n"
        "    lanes.forEach((lane) => {\n"
        "      lane.addEventListener('dragover', (event) => { event.preventDefault(); lane.classList.add('drag-over'); });\n"
        "      lane.addEventListener('dragleave', () => lane.classList.remove('drag-over'));\n"
        "      lane.addEventListener('drop', (event) => {\n"
        "        event.preventDefault(); lane.classList.remove('drag-over');\n"
        "        const card = document.querySelector('.review-card.dragging');\n"
        "        const body = lane.querySelector('[data-lane-body]');\n"
        "        if (!card || !body) return;\n"
        "        body.appendChild(card); updateCard(card, lane); updateCounts();\n"
        "      });\n"
        "    });\n"
        "    updateCounts();\n"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
    )


def save_review_form(form: dict[str, list[str]], review_file: Path) -> None:
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
        save_review_form(form, review_file)
        rows = read_csv(review_file)
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
