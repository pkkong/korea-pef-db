#!/usr/bin/env python3
"""Evaluate newsletter classification logic and AI output against golden cases."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
LEGACY_SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(LEGACY_SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(LEGACY_SCRIPTS_DIR))

from news_taxonomy import SECTION_LABELS, canonical_section
from run_daily_news_pipeline import primary_section


DEFAULT_GOLDENS = SERVICE_ROOT / "data" / "news_classification_golden.csv"
DEFAULT_OUT_DIR = REPO_ROOT / "exports" / "daily_news" / "ai_backtests"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def read_ai_articles(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    articles = payload.get("articles") if isinstance(payload, dict) else []
    return [row for row in articles if isinstance(row, dict)]


def article_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for value in [row.get("case_id"), row.get("news_id"), row.get("source_url"), row.get("normalized_source_url"), row.get("title")]:
        text = str(value or "").strip()
        if text and text not in keys:
            keys.append(text)
    return keys


def build_ai_index(articles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in articles:
        for key in article_keys(row):
            index.setdefault(key, row)
    return index


def local_section(row: dict[str, str]) -> str:
    working = {
        "publisher": row.get("publisher", ""),
        "title": row.get("title", ""),
        "summary_text": row.get("summary_text", ""),
        "section_tags": row.get("section_tags", ""),
        "topic_tags": row.get("topic_tags", ""),
        "gp_names": row.get("gp_names", ""),
        "lp_names": row.get("lp_names", ""),
        "source_url": row.get("source_url", ""),
        "review_status": "auto",
    }
    return primary_section(working)


def evaluate(goldens: list[dict[str, str]], ai_articles: list[dict[str, Any]]) -> list[dict[str, str]]:
    ai_index = build_ai_index(ai_articles)
    rows: list[dict[str, str]] = []
    for row in goldens:
        expected = canonical_section(row.get("expected_section"))
        local = canonical_section(local_section(row))
        ai_row = None
        for key in article_keys(row):
            ai_row = ai_index.get(key)
            if ai_row is not None:
                break
        ai_section = canonical_section(str(ai_row.get("section_suggestion") or "")) if ai_row else ""
        rows.append(
            {
                "case_id": row.get("case_id", ""),
                "publisher": row.get("publisher", ""),
                "title": row.get("title", ""),
                "expected_section": expected,
                "expected_label": SECTION_LABELS.get(expected, expected),
                "local_section": local,
                "local_label": SECTION_LABELS.get(local, local),
                "local_status": "pass" if local == expected else "fail",
                "ai_section": ai_section,
                "ai_label": SECTION_LABELS.get(ai_section, ai_section),
                "ai_status": "not_run" if not ai_articles else ("pass" if ai_section == expected else "fail"),
                "reason": row.get("reason", ""),
            }
        )
    return rows


def write_outputs(rows: list[dict[str, str]], out_dir: Path, ai_file: Path | None) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = "news_classification_golden_eval"
    csv_path = out_dir / f"{stem}.csv"
    md_path = out_dir / f"{stem}.md"
    headers = [
        "case_id",
        "publisher",
        "title",
        "expected_section",
        "local_section",
        "local_status",
        "ai_section",
        "ai_status",
        "reason",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows([{key: row.get(key, "") for key in headers} for row in rows])
    local_fail = [row for row in rows if row["local_status"] != "pass"]
    ai_fail = [row for row in rows if row["ai_status"] == "fail"]
    lines = [
        "# News Classification Golden Evaluation",
        "",
        f"- generated_at: `{datetime.now(timezone.utc).replace(microsecond=0).isoformat()}`",
        f"- cases: {len(rows)}",
        f"- local pass: {len(rows) - len(local_fail)} / {len(rows)}",
        f"- ai file: `{ai_file or ''}`",
        f"- ai pass: {len(rows) - len(ai_fail)} / {len(rows)}" if ai_file else "- ai pass: not_run",
        "",
        "| case | expected | local | local status | ai | ai status |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case_id']} | {row['expected_section']} | {row['local_section']} | {row['local_status']} | {row['ai_section']} | {row['ai_status']} |"
        )
    if local_fail or ai_fail:
        lines.extend(["", "## Failures", ""])
        for row in local_fail:
            lines.append(f"- local `{row['case_id']}` expected {row['expected_section']} got {row['local_section']}: {row['title']}")
        for row in ai_fail:
            lines.append(f"- ai `{row['case_id']}` expected {row['expected_section']} got {row['ai_section']}: {row['title']}")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    (out_dir / "news_classification_golden_eval_latest.csv").write_text(csv_path.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    (out_dir / "news_classification_golden_eval_latest.md").write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    return csv_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate newsletter category golden cases")
    parser.add_argument("--goldens", type=Path, default=DEFAULT_GOLDENS)
    parser.add_argument("--ai-file", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--fail-on-mismatch", action="store_true")
    args = parser.parse_args()

    rows = evaluate(read_csv_rows(args.goldens), read_ai_articles(args.ai_file))
    csv_path, md_path = write_outputs(rows, args.out_dir, args.ai_file)
    local_fail = [row for row in rows if row["local_status"] != "pass"]
    ai_fail = [row for row in rows if row["ai_status"] == "fail"]
    print(
        f"golden_eval_status={'failed' if local_fail or ai_fail else 'ok'} cases={len(rows)} local_fail={len(local_fail)} ai_fail={len(ai_fail)} csv={csv_path} md={md_path}"
    )
    return 1 if args.fail_on_mismatch and (local_fail or ai_fail) else 0


if __name__ == "__main__":
    raise SystemExit(main())
