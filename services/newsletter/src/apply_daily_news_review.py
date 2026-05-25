#!/usr/bin/env python
"""Apply manual daily-news review decisions to news_manual_overrides.csv."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from daily_news_common import DEFAULT_EXPORT_DIR, DEFAULT_OVERRIDES
from run_daily_news_pipeline import SECTION_LABELS


DEFAULT_REVIEW_FILE = DEFAULT_EXPORT_DIR / "daily_news_review_actions_latest.csv"
OVERRIDE_HEADERS = [
    "normalized_source_url",
    "review_status",
    "force_include",
    "force_exclude",
    "manual_tags",
    "manual_comment",
    "notes",
]

SECTION_BY_INPUT = {value: key for key, value in SECTION_LABELS.items()}
SECTION_BY_INPUT.update(
    {
        "오늘의핵심": "Market",
        "핵심": "Market",
        "시장": "Market",
        "시장전략": "Market",
        "LP": "LP",
        "출자": "LP",
        "출자자": "LP",
        "LP출자": "LP",
        "LPCommitment": "LP",
        "기관투자가": "LP",
        "Allocator": "LP",
        "Allocators": "LP",
        "펀드레이징": "GP",
        "펀드결성": "GP",
        "결성": "GP",
        "클로징": "GP",
        "딜": "Deal",
        "딜/엑시트": "Deal",
        "거래": "Deal",
        "거래엑시트": "Deal",
        "엑시트": "Deal",
        "GP": "GP",
        "운용사": "GP",
        "하우스전략": "GP",
        "포트폴리오": "Deal",
        "밸류업": "Deal",
        "크레딧": "Deal",
        "파이낸싱": "Deal",
        "레버리지": "Deal",
        "인수금융": "Deal",
        "규제": "Market",
        "리스크": "Market",
        "AI": "AI_PE",
        "AI&PE": "AI_PE",
        "AI_PE": "AI_PE",
    }
)
INCLUDE_ACTIONS = {"include", "keep", "y", "yes", "o", "포함", "유지"}
EXCLUDE_ACTIONS = {"exclude", "drop", "n", "no", "x", "제외", "삭제"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OVERRIDE_HEADERS)
        writer.writeheader()
        writer.writerows([{header: row.get(header, "") for header in OVERRIDE_HEADERS} for row in rows])


def normalize_action(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw in INCLUDE_ACTIONS:
        return "include"
    if raw in EXCLUDE_ACTIONS:
        return "exclude"
    return ""


def normalize_category(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    compact = raw.replace(" ", "")
    if raw in SECTION_LABELS:
        return raw
    return SECTION_BY_INPUT.get(raw) or SECTION_BY_INPUT.get(compact) or ""


def replace_section_override(manual_tags: str, section_code: str) -> str:
    tags = [tag.strip() for tag in (manual_tags or "").split(";") if tag.strip()]
    tags = [tag for tag in tags if not tag.startswith("section_override:")]
    if section_code:
        tags.append(f"section_override:{section_code}")
    return ";".join(tags)


def append_note(existing: str, note: str) -> str:
    note = (note or "").strip()
    if not note:
        return existing or ""
    if existing and note in existing:
        return existing
    return f"{existing}; {note}" if existing else note


def apply_review(review_file: Path, overrides_file: Path) -> dict[str, int]:
    review_rows = read_csv(review_file)
    override_rows = read_csv(overrides_file)
    by_url = {row.get("normalized_source_url", ""): row for row in override_rows if row.get("normalized_source_url")}
    changed = 0
    skipped = 0

    for review in review_rows:
        url = review.get("normalized_source_url", "").strip()
        if not url:
            skipped += 1
            continue
        action = normalize_action(review.get("action", ""))
        section_code = normalize_category(review.get("category", ""))
        if not action and not section_code:
            skipped += 1
            continue

        row = by_url.setdefault(
            url,
            {
                "normalized_source_url": url,
                "review_status": "auto",
                "force_include": "",
                "force_exclude": "",
                "manual_tags": "",
                "manual_comment": "",
                "notes": "",
            },
        )
        if action == "include":
            row["review_status"] = "force_include"
            row["force_include"] = "1"
            row["force_exclude"] = ""
        elif action == "exclude":
            row["review_status"] = "force_exclude"
            row["force_include"] = ""
            row["force_exclude"] = "1"
        if section_code:
            row["manual_tags"] = replace_section_override(row.get("manual_tags", ""), section_code)
        row["notes"] = append_note(row.get("notes", ""), review.get("notes", ""))
        changed += 1

    output = sorted(by_url.values(), key=lambda row: row.get("normalized_source_url", ""))
    write_csv(overrides_file, output)
    return {"changed": changed, "skipped": skipped, "total_overrides": len(output)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply daily news review actions to manual overrides")
    parser.add_argument("--review-file", type=Path, default=DEFAULT_REVIEW_FILE)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    args = parser.parse_args()

    result = apply_review(args.review_file, args.overrides)
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
