#!/usr/bin/env python
"""Export and apply CSV review actions for LP commitment notices."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.newsletter.src.daily_news_common import (  # noqa: E402
    DEFAULT_DB,
    normalize_url,
    now_utc_iso,
    read_csv_rows,
    today_seoul,
    write_csv_rows,
)


DEFAULT_OUT_DIR = REPO_ROOT / "exports"
DEFAULT_QUEUE_BASENAME = "lp_commitment_notice_review_queue"
VALID_MONITOR_STATUSES = {"candidate", "validated", "dismissed"}
SKIP_ACTIONS = {"", "skip", "keep", "no_change", "unchanged", "hold", "-"}
ACTION_ALIASES = {
    "candidate": "candidate",
    "reset": "candidate",
    "requeue": "candidate",
    "대기": "candidate",
    "후보": "candidate",
    "validated": "validated",
    "validate": "validated",
    "approved": "validated",
    "approve": "validated",
    "valid": "validated",
    "확인": "validated",
    "승인": "validated",
    "dismissed": "dismissed",
    "dismiss": "dismissed",
    "rejected": "dismissed",
    "reject": "dismissed",
    "invalid": "dismissed",
    "drop": "dismissed",
    "제외": "dismissed",
    "반려": "dismissed",
}

QUEUE_HEADERS = [
    "review_action",
    "review_note",
    "review_public_visible",
    "notice_id",
    "normalized_notice_url",
    "monitor_status",
    "public_visible",
    "lp_code",
    "lp_name",
    "lp_type",
    "default_team",
    "source_code",
    "source_type",
    "event_type",
    "event_date",
    "title",
    "notice_url",
    "document_url",
    "attachment_names",
    "attachment_urls",
    "program_name",
    "round_name",
    "announced_date",
    "notice_year",
    "application_deadline",
    "notice_stage",
    "asset_class",
    "strategy",
    "program_size_krw_100mn",
    "allocation_amount_krw_100mn",
    "amount_type",
    "amount_confidence",
    "commitment_amount_krw_100mn",
    "selected_gp_names",
    "confidence",
    "confidence_note",
    "raw_excerpt",
    "discovered_at",
    "updated_at",
]


@dataclass(frozen=True)
class PendingReviewAction:
    row_number: int
    monitor_status: str
    public_visible: int | None
    normalized_notice_url: str
    notice_id: int | None


def parse_status_filter(value: str) -> list[str]:
    raw_items = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not raw_items or raw_items == ["all"]:
        return sorted(VALID_MONITOR_STATUSES)
    invalid = sorted(set(raw_items) - VALID_MONITOR_STATUSES)
    if invalid:
        raise ValueError(f"invalid status filter: {', '.join(invalid)}")
    return raw_items


def normalize_review_action(value: object) -> str | None:
    action = str(value or "").strip().lower()
    if action in SKIP_ACTIONS:
        return None
    if action not in ACTION_ALIASES:
        raise ValueError(f"invalid review_action={value!r}")
    return ACTION_ALIASES[action]


def parse_optional_bool(value: object) -> int | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "t", "yes", "y", "visible", "public", "공개"}:
        return 1
    if text in {"0", "false", "f", "no", "n", "hidden", "private", "비공개"}:
        return 0
    raise ValueError(f"invalid boolean value: {value}")


def candidate_identifier(row: dict[str, str]) -> tuple[str, int | str] | None:
    normalized_notice_url = str(row.get("normalized_notice_url") or "").strip()
    if not normalized_notice_url:
        notice_url = str(row.get("notice_url") or "").strip()
        normalized_notice_url = normalize_url(notice_url) if notice_url else ""
    if normalized_notice_url:
        return "normalized_notice_url", normalized_notice_url
    raw_notice_id = str(row.get("notice_id") or "").strip()
    if raw_notice_id:
        return "notice_id", int(raw_notice_id)
    return None


def review_action_from_row(row_number: int, row: dict[str, str]) -> PendingReviewAction | None:
    raw_action = (
        row.get("review_action")
        or row.get("action")
        or row.get("new_monitor_status")
        or row.get("target_monitor_status")
        or row.get("monitor_status_action")
    )
    action = normalize_review_action(raw_action)
    if action is None:
        return None
    identifier = candidate_identifier(row)
    if identifier is None:
        raise ValueError("missing notice_id or normalized_notice_url")
    key, value = identifier
    notice_id = int(value) if key == "notice_id" else None
    normalized_notice_url = str(value) if key == "normalized_notice_url" else ""

    return PendingReviewAction(
        row_number=row_number,
        monitor_status=action,
        public_visible=parse_optional_bool(row.get("review_public_visible")),
        normalized_notice_url=normalized_notice_url,
        notice_id=notice_id,
    )


def export_review_queue(
    db_path: Path,
    out_dir: Path,
    report_date: str,
    statuses: list[str],
    limit: int,
    out_path: Path | None = None,
) -> dict[str, object]:
    placeholders = ", ".join("?" for _ in statuses)
    query = f"""
        SELECT
            '' AS review_action,
            '' AS review_note,
            '' AS review_public_visible,
            lcn.notice_id,
            lcn.normalized_notice_url,
            lcn.monitor_status,
            lcn.public_visible,
            lcn.lp_code,
            COALESCE(li.lp_name, '') AS lp_name,
            COALESCE(li.lp_type, '') AS lp_type,
            COALESCE(li.default_team, lcn.contact_team, '') AS default_team,
            lcn.source_code,
            lcn.source_type,
            lcn.event_type,
            lcn.event_date,
            lcn.title,
            lcn.notice_url,
            lcn.document_url,
            lcn.attachment_names,
            lcn.attachment_urls,
            lcn.program_name,
            lcn.round_name,
            lcn.announced_date,
            lcn.notice_year,
            lcn.application_deadline,
            lcn.notice_stage,
            lcn.asset_class,
            lcn.strategy,
            lcn.program_size_krw_100mn,
            lcn.allocation_amount_krw_100mn,
            lcn.amount_type,
            lcn.amount_confidence,
            lcn.commitment_amount_krw_100mn,
            lcn.selected_gp_names,
            lcn.confidence,
            lcn.confidence_note,
            lcn.raw_excerpt,
            lcn.discovered_at,
            lcn.updated_at
        FROM lp_commitment_notice lcn
        LEFT JOIN lp_institution li
            ON li.lp_code = lcn.lp_code
        WHERE lcn.monitor_status IN ({placeholders})
        ORDER BY
            CASE lcn.monitor_status
                WHEN 'candidate' THEN 0
                WHEN 'validated' THEN 1
                WHEN 'dismissed' THEN 2
                ELSE 9
            END,
            CASE lcn.event_type
                WHEN 'new_notice' THEN 0
                WHEN 'deadline_soon' THEN 1
                WHEN 'final_selection' THEN 2
                WHEN 'shortlist' THEN 3
                WHEN 'revision' THEN 4
                WHEN 'cancellation' THEN 5
                WHEN 'performance_update' THEN 6
                ELSE 9
            END,
            COALESCE(lcn.event_date, lcn.announced_date, lcn.discovered_at) DESC,
            lcn.notice_id DESC
        LIMIT ?
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(query, [*statuses, limit])
        rows = [dict(zip([desc[0] for desc in cursor.description], row)) for row in cursor.fetchall()]
    finally:
        conn.close()

    if out_path is not None:
        write_csv_rows(out_path, rows, QUEUE_HEADERS)
        return {"exported": len(rows), "export": str(out_path)}

    dated_path = out_dir / f"{DEFAULT_QUEUE_BASENAME}_{report_date.replace('-', '')}.csv"
    latest_path = out_dir / f"{DEFAULT_QUEUE_BASENAME}_latest.csv"
    write_csv_rows(dated_path, rows, QUEUE_HEADERS)
    write_csv_rows(latest_path, rows, QUEUE_HEADERS)
    return {
        "exported": len(rows),
        "dated_export": str(dated_path),
        "latest_export": str(latest_path),
    }


def fetch_notice_for_action(conn: sqlite3.Connection, action: PendingReviewAction) -> sqlite3.Row | None:
    if action.normalized_notice_url:
        return conn.execute(
            """
            SELECT notice_id, monitor_status, public_visible
            FROM lp_commitment_notice
            WHERE normalized_notice_url = ?
            """,
            (action.normalized_notice_url,),
        ).fetchone()
    if action.notice_id is not None:
        return conn.execute(
            """
            SELECT notice_id, monitor_status, public_visible
            FROM lp_commitment_notice
            WHERE notice_id = ?
            """,
            (action.notice_id,),
        ).fetchone()
    return None


def apply_review_actions(
    db_path: Path,
    actions_csv: Path,
    dry_run: bool,
    allow_missing: bool,
    require_current_status_match: bool,
) -> dict[str, object]:
    rows = read_csv_rows(actions_csv)
    pending: list[PendingReviewAction] = []
    invalid: list[str] = []
    for index, row in enumerate(rows, start=2):
        try:
            action = review_action_from_row(index, row)
        except (TypeError, ValueError) as exc:
            invalid.append(f"row {index}: {exc}")
            continue
        if action is not None:
            pending.append(action)
    if invalid:
        raise RuntimeError("invalid review rows: " + "; ".join(invalid[:5]))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    missing: list[str] = []
    status_mismatches: list[str] = []
    applied = 0
    try:
        for action in pending:
            notice = fetch_notice_for_action(conn, action)
            if notice is None:
                missing.append(f"row {action.row_number}")
                continue
            if require_current_status_match:
                source_row = rows[action.row_number - 2]
                expected_status = str(source_row.get("monitor_status") or "").strip().lower()
                if expected_status and expected_status != str(notice["monitor_status"]):
                    status_mismatches.append(
                        f"row {action.row_number}: expected {expected_status}, found {notice['monitor_status']}"
                    )
                    continue
            if dry_run:
                continue

            public_visible = action.public_visible
            if public_visible is None:
                if action.monitor_status == "validated":
                    public_visible = 1
                elif action.monitor_status == "dismissed":
                    public_visible = 0
                else:
                    public_visible = int(notice["public_visible"])
            conn.execute(
                """
                UPDATE lp_commitment_notice
                SET monitor_status = ?,
                    public_visible = ?,
                    updated_at = ?
                WHERE notice_id = ?
                """,
                (action.monitor_status, public_visible, now_utc_iso(), int(notice["notice_id"])),
            )
            applied += 1

        if missing and not allow_missing:
            raise RuntimeError("missing notices for review rows: " + ", ".join(missing[:10]))
        if status_mismatches:
            raise RuntimeError("current status mismatches: " + "; ".join(status_mismatches[:10]))
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "input_rows": len(rows),
        "action_rows": len(pending),
        "applied": 0 if dry_run else applied,
        "dry_run": dry_run,
        "missing": len(missing),
        "status_mismatches": len(status_mismatches),
    }


def add_common_db_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)


def main() -> int:
    parser = argparse.ArgumentParser(description="Review LP commitment notice monitor candidates")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="export a CSV review queue")
    add_common_db_arg(export_parser)
    export_parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    export_parser.add_argument("--out", type=Path)
    export_parser.add_argument("--date", default="")
    export_parser.add_argument("--status", default="candidate")
    export_parser.add_argument("--limit", type=int, default=500)

    apply_parser = subparsers.add_parser("apply", help="apply review_action values from a CSV")
    add_common_db_arg(apply_parser)
    apply_parser.add_argument("actions_csv", type=Path)
    apply_parser.add_argument("--dry-run", action="store_true")
    apply_parser.add_argument("--allow-missing", action="store_true")
    apply_parser.add_argument("--require-current-status-match", action="store_true")

    args = parser.parse_args()
    if args.command == "export":
        result = export_review_queue(
            db_path=args.db,
            out_dir=args.out_dir,
            report_date=args.date or today_seoul(),
            statuses=parse_status_filter(args.status),
            limit=args.limit,
            out_path=args.out,
        )
    else:
        result = apply_review_actions(
            db_path=args.db,
            actions_csv=args.actions_csv,
            dry_run=args.dry_run,
            allow_missing=args.allow_missing,
            require_current_status_match=args.require_current_status_match,
        )

    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
