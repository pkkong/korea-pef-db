#!/usr/bin/env python
"""Run the maintainable refresh pipeline for the Private Equity DB."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_EXPORTS = REPO_ROOT / "exports"
DEFAULT_DASHBOARD_JSON = REPO_ROOT / "dashboard" / "data" / "dashboard_data.json"
DEFAULT_DASHBOARD_INDEX = REPO_ROOT / "dashboard" / "index.html"
DEFAULT_PUBLIC_SERVICE_JSON = REPO_ROOT / "services" / "newsletter" / "deploy" / "site" / "data" / "service_data.json"
DEFAULT_EVIDENCE = REPO_ROOT / "data" / "gp_profile_evidence.csv"
DEFAULT_QUALITY_XLSX = REPO_ROOT / "exports" / "db_quality_report.xlsx"
DEFAULT_QUALITY_CSV_PREFIX = REPO_ROOT / "exports" / "db_quality"
DEFAULT_LOG_DIR = REPO_ROOT / "logs"
DEFAULT_OPERATIONAL_STATUS = REPO_ROOT / "exports" / "operational_status_latest.md"
DEFAULT_DAILY_NEWS_EXPORTS = REPO_ROOT / "exports" / "daily_news"
DEFAULT_PEOPLE_INPUT = REPO_ROOT / "data" / "people_input.csv"
DEFAULT_PERSON_ROLE_INPUT = REPO_ROOT / "data" / "person_role_input.csv"
DEFAULT_PERSON_EDUCATION_INPUT = REPO_ROOT / "data" / "person_education_input.csv"
DEFAULT_PERSON_NAME_OVERRIDES = REPO_ROOT / "data" / "person_name_overrides.csv"
DEFAULT_SCHOOL_NAME_ALIASES = REPO_ROOT / "data" / "school_name_aliases.csv"
DEFAULT_PEOPLE_RESEARCH_WORKLIST = REPO_ROOT / "exports" / "people_research_worklist_top50.csv"
DEFAULT_SERVICE_INTEGRATION_OUT = REPO_ROOT / "exports"
DEFAULT_LP_INSTITUTIONS = REPO_ROOT / "data" / "lp_institutions.csv"
DEFAULT_LP_COMMITMENT_SOURCES = REPO_ROOT / "data" / "lp_commitment_sources.csv"


@dataclass
class PipelineStep:
    name: str
    description: str
    command_factory: callable
    enabled: bool = True
    skip_reason: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def latest_period_label(db_path: Path) -> str:
    if not db_path.exists():
        raise RuntimeError(f"Cannot detect latest reporting period because {db_path} does not exist.")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT period_label
            FROM reporting_period
            ORDER BY as_of_date DESC, period_id DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if row is None or not row[0]:
        raise RuntimeError("Could not detect the latest reporting period from reporting_period.")
    return str(row[0])


def build_steps(args: argparse.Namespace) -> list[PipelineStep]:
    steps: list[PipelineStep] = []

    if args.with_fetch_sources:
        steps.append(
            PipelineStep(
                name="fetch_fss_sources",
                description="Fetch and register FSS source files",
                command_factory=lambda: [sys.executable, str(SCRIPTS_DIR / "fetch_fss_pef_sources.py")],
            )
        )

    if args.with_rebuild_db:
        steps.append(
            PipelineStep(
                name="rebuild_fss_db",
                description="Rebuild the SQLite DB from registered raw FSS files",
                command_factory=lambda: [
                    sys.executable,
                    str(SCRIPTS_DIR / "ingest_fss_pef.py"),
                    "--db",
                    str(args.db),
                    "rebuild",
                ],
            )
        )

    steps.extend(
        [
            PipelineStep(
                name="import_people_csv",
                description="Apply People DB schema and import maintained people CSV inputs",
                command_factory=lambda: [
                    sys.executable,
                    str(SCRIPTS_DIR / "import_people_csv.py"),
                    "--db",
                    str(args.db),
                    "--people",
                    str(args.people_input),
                    "--roles",
                    str(args.person_role_input),
                    "--education",
                    str(args.person_education_input),
                    "--school-aliases",
                    str(args.school_name_aliases),
                ],
                enabled=not args.skip_people_import,
                skip_reason="--skip-people-import was supplied",
            ),
            PipelineStep(
                name="apply_people_normalization",
                description="Apply Korean-first person and school display normalization",
                command_factory=lambda: [
                    sys.executable,
                    str(SCRIPTS_DIR / "apply_people_normalization.py"),
                    "--db",
                    str(args.db),
                    "--person-name-overrides",
                    str(args.person_name_overrides),
                    "--school-aliases",
                    str(args.school_name_aliases),
                ],
                enabled=not args.skip_people_import,
                skip_reason="--skip-people-import was supplied",
            ),
            PipelineStep(
                name="export_people_views",
                description="Export People DB review views to CSV",
                command_factory=lambda: [
                    sys.executable,
                    str(SCRIPTS_DIR / "export_people_views.py"),
                    "--db",
                    str(args.db),
                    "--out",
                    str(args.exports),
                ],
                enabled=not args.skip_people_import,
                skip_reason="--skip-people-import was supplied",
            ),
            PipelineStep(
                name="export_fss_views",
                description="Export FSS review views to CSV",
                command_factory=lambda: [
                    sys.executable,
                    str(SCRIPTS_DIR / "export_fss_pef_views.py"),
                    "--db",
                    str(args.db),
                    "--out",
                    str(args.exports),
                ],
            ),
            PipelineStep(
                name="build_gp_master_candidates_pre_merge",
                description="Refresh GP master candidates before alias merge application",
                command_factory=lambda: [
                    sys.executable,
                    str(SCRIPTS_DIR / "build_gp_master_candidates.py"),
                    "--db",
                    str(args.db),
                    "--out",
                    str(args.exports),
                ],
            ),
            PipelineStep(
                name="apply_gp_alias_merges",
                description="Apply externally verified GP alias merges",
                command_factory=lambda: [
                    sys.executable,
                    str(SCRIPTS_DIR / "apply_gp_alias_merges.py"),
                    "--db",
                    str(args.db),
                ],
            ),
            PipelineStep(
                name="build_gp_master_candidates_post_merge",
                description="Refresh GP master candidates after alias merge application",
                command_factory=lambda: [
                    sys.executable,
                    str(SCRIPTS_DIR / "build_gp_master_candidates.py"),
                    "--db",
                    str(args.db),
                    "--out",
                    str(args.exports),
                ],
            ),
            PipelineStep(
                name="build_fund_master",
                description="Build fund master tables and exports",
                command_factory=lambda: [
                    sys.executable,
                    str(SCRIPTS_DIR / "build_fund_master.py"),
                    "--db",
                    str(args.db),
                    "--out",
                    str(args.exports),
                ],
            ),
            PipelineStep(
                name="build_aum_analytics",
                description="Build GP AUM-style analytics using the latest detected period",
                command_factory=lambda: [
                    sys.executable,
                    str(SCRIPTS_DIR / "build_aum_analytics.py"),
                    "--db",
                    str(args.db),
                    "--out",
                    str(args.exports),
                    "--ranking-period",
                    latest_period_label(args.db),
                ],
            ),
            PipelineStep(
                name="build_gp_profile_master_pre_evidence",
                description="Build GP profile master shell and research worklist",
                command_factory=lambda: [
                    sys.executable,
                    str(SCRIPTS_DIR / "build_gp_profile_master.py"),
                    "--db",
                    str(args.db),
                    "--out",
                    str(args.exports),
                    "--limit",
                    str(args.gp_profile_limit),
                ],
            ),
        ]
    )

    evidence_enabled = (not args.skip_profile_evidence) and args.evidence.exists()
    steps.append(
        PipelineStep(
            name="apply_gp_profile_evidence",
            description="Apply manual GP profile evidence to DB",
            command_factory=lambda: [
                sys.executable,
                str(SCRIPTS_DIR / "apply_gp_profile_evidence.py"),
                "--db",
                str(args.db),
                "--evidence",
                str(args.evidence),
            ],
            enabled=evidence_enabled,
            skip_reason="evidence file missing or --skip-profile-evidence was supplied",
        )
    )

    steps.append(
        PipelineStep(
            name="build_gp_profile_master_post_evidence",
            description="Rebuild GP profile exports after evidence application",
            command_factory=lambda: [
                sys.executable,
                str(SCRIPTS_DIR / "build_gp_profile_master.py"),
                "--db",
                str(args.db),
                "--out",
                str(args.exports),
                "--limit",
                str(args.gp_profile_limit),
            ],
            enabled=evidence_enabled,
            skip_reason="evidence file missing or --skip-profile-evidence was supplied",
        )
    )

    steps.append(
        PipelineStep(
            name="build_people_research_worklist",
            description="Build top-GP People DB collection worklist",
            command_factory=lambda: [
                sys.executable,
                str(SCRIPTS_DIR / "build_people_research_worklist.py"),
                "--db",
                str(args.db),
                "--out",
                str(args.people_research_worklist_out),
                "--limit",
                str(args.people_research_limit),
            ],
            enabled=not args.skip_people_worklist,
            skip_reason="--skip-people-worklist was supplied",
        )
    )

    steps.append(
        PipelineStep(
            name="build_news_gp_update_worklist",
            description="Refresh news-driven GP profile update queue",
            command_factory=lambda: [
                sys.executable,
                str(SCRIPTS_DIR / "build_news_gp_update_worklist.py"),
                "--db",
                str(args.db),
                "--out-dir",
                str(args.daily_news_out),
                "--days",
                str(args.news_gp_worklist_days),
            ],
            enabled=not args.skip_news_gp_worklist,
            skip_reason="--skip-news-gp-worklist was supplied",
        )
    )

    steps.append(
        PipelineStep(
            name="build_service_integration_worklist",
            description="Build integrated Newsletter/People/GP operating worklist",
            command_factory=lambda: [
                sys.executable,
                str(SCRIPTS_DIR / "build_service_integration_worklist.py"),
                "--db",
                str(args.db),
                "--news-worklist",
                str(args.daily_news_out / "news_gp_update_worklist_latest.csv"),
                "--out-dir",
                str(args.service_integration_out),
                "--top-gp-limit",
                str(args.service_integration_top_gp_limit),
            ],
            enabled=not args.skip_service_integration_worklist,
            skip_reason="--skip-service-integration-worklist was supplied",
        )
    )

    steps.append(
        PipelineStep(
            name="build_lp_commitment_monitor",
            description="Build LP commitment notice monitor from official sources and news clips",
            command_factory=lambda: [
                sys.executable,
                str(SCRIPTS_DIR / "build_lp_commitment_monitor.py"),
                "--db",
                str(args.db),
                "--lp-institutions",
                str(args.lp_institutions),
                "--lp-sources",
                str(args.lp_commitment_sources),
                "--out-dir",
                str(args.exports),
                "--days",
                str(args.lp_monitor_days),
                "--limit-per-source",
                str(args.lp_monitor_limit_per_source),
            ],
            enabled=not args.skip_lp_monitor,
            skip_reason="--skip-lp-monitor was supplied",
        )
    )

    dashboard_enabled = not args.skip_dashboard
    steps.append(
        PipelineStep(
            name="build_dashboard_data",
            description="Build dashboard JSON payload",
            command_factory=lambda: [
                sys.executable,
                str(SCRIPTS_DIR / "build_dashboard_data.py"),
                "--db",
                str(args.db),
                "--out",
                str(args.dashboard_out),
                "--news-gp-update-worklist",
                str(args.daily_news_out / "news_gp_update_worklist_latest.csv"),
                "--service-integration-worklist",
                str(args.service_integration_out / "service_integration_worklist_latest.csv"),
            ],
            enabled=dashboard_enabled,
            skip_reason="--skip-dashboard was supplied",
        )
    )
    steps.append(
        PipelineStep(
            name="build_public_service_data",
            description="Build public-safe service JSON without operator queues",
            command_factory=lambda: [
                sys.executable,
                str(SCRIPTS_DIR / "build_public_service_data.py"),
                "--input",
                str(args.dashboard_out),
                "--out",
                str(args.public_service_out),
            ],
            enabled=dashboard_enabled,
            skip_reason="--skip-dashboard was supplied",
        )
    )
    steps.append(
        PipelineStep(
            name="build_dashboard_app",
            description="Build service dashboard HTML shell",
            command_factory=lambda: [
                sys.executable,
                str(SCRIPTS_DIR / "build_standalone_dashboard.py"),
                "--data",
                str(args.dashboard_out),
                "--out",
                str(args.dashboard_index_out),
            ],
            enabled=dashboard_enabled,
            skip_reason="--skip-dashboard was supplied",
        )
    )

    steps.append(
        PipelineStep(
            name="build_db_quality_report",
            description="Build DB quality and coverage reports",
            command_factory=lambda: [
                sys.executable,
                str(SCRIPTS_DIR / "build_db_quality_report.py"),
                "--db",
                str(args.db),
                "--out",
                str(args.quality_out),
                "--csv-prefix",
                str(args.quality_csv_prefix),
                "--top-n",
                str(args.quality_top_n),
            ],
            enabled=not args.skip_quality_report,
            skip_reason="--skip-quality-report was supplied",
        )
    )

    steps.append(
        PipelineStep(
            name="build_operational_status_report",
            description="Build user-facing operational status summary",
            command_factory=lambda: [
                sys.executable,
                str(SCRIPTS_DIR / "build_operational_status_report.py"),
                "--db",
                str(args.db),
                "--exports",
                str(args.exports),
                "--dashboard-json",
                str(args.dashboard_out),
                "--news-worklist",
                str(args.daily_news_out / "news_gp_update_worklist_latest.csv"),
                "--log-dir",
                str(args.log_dir),
                "--out",
                str(args.operational_status_out),
            ],
            enabled=not args.skip_operational_status,
            skip_reason="--skip-operational-status was supplied",
        )
    )

    return steps


def run_step(step: PipelineStep, log_fh, dry_run: bool) -> dict[str, object]:
    started_at = now_iso()
    start_monotonic = time.perf_counter()
    command = step.command_factory()

    log_fh.write(f"\n=== STEP {step.name} ===\n")
    log_fh.write(f"description: {step.description}\n")
    log_fh.write(f"started_at: {started_at}\n")
    log_fh.write(f"command: {json.dumps(command, ensure_ascii=False)}\n")
    log_fh.flush()

    print(f"[RUN ] {step.name}: {step.description}")
    if dry_run:
        print(f"       dry-run command: {' '.join(command)}")
        ended_at = now_iso()
        duration_seconds = round(time.perf_counter() - start_monotonic, 3)
        return {
            "name": step.name,
            "description": step.description,
            "command": command,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
            "returncode": 0,
            "status": "dry_run",
        }

    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    ended_at = now_iso()
    duration_seconds = round(time.perf_counter() - start_monotonic, 3)

    if completed.stdout:
        print(completed.stdout.rstrip())
        log_fh.write("--- stdout ---\n")
        log_fh.write(completed.stdout)
        if not completed.stdout.endswith("\n"):
            log_fh.write("\n")
    if completed.stderr:
        print(completed.stderr.rstrip())
        log_fh.write("--- stderr ---\n")
        log_fh.write(completed.stderr)
        if not completed.stderr.endswith("\n"):
            log_fh.write("\n")

    log_fh.write(f"returncode: {completed.returncode}\n")
    log_fh.write(f"ended_at: {ended_at}\n")
    log_fh.write(f"duration_seconds: {duration_seconds}\n")
    log_fh.flush()

    status = "success" if completed.returncode == 0 else "failed"
    result = {
        "name": step.name,
        "description": step.description,
        "command": command,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration_seconds,
        "returncode": completed.returncode,
        "status": status,
    }
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, command)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the maintainable Private Equity DB refresh pipeline")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--exports", type=Path, default=DEFAULT_EXPORTS)
    parser.add_argument("--dashboard-out", type=Path, default=DEFAULT_DASHBOARD_JSON)
    parser.add_argument("--dashboard-index-out", type=Path, default=DEFAULT_DASHBOARD_INDEX)
    parser.add_argument("--public-service-out", type=Path, default=DEFAULT_PUBLIC_SERVICE_JSON)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--quality-out", type=Path, default=DEFAULT_QUALITY_XLSX)
    parser.add_argument("--quality-csv-prefix", type=Path, default=DEFAULT_QUALITY_CSV_PREFIX)
    parser.add_argument("--quality-top-n", type=int, default=100)
    parser.add_argument("--operational-status-out", type=Path, default=DEFAULT_OPERATIONAL_STATUS)
    parser.add_argument("--daily-news-out", type=Path, default=DEFAULT_DAILY_NEWS_EXPORTS)
    parser.add_argument("--people-input", type=Path, default=DEFAULT_PEOPLE_INPUT)
    parser.add_argument("--person-role-input", type=Path, default=DEFAULT_PERSON_ROLE_INPUT)
    parser.add_argument("--person-education-input", type=Path, default=DEFAULT_PERSON_EDUCATION_INPUT)
    parser.add_argument("--person-name-overrides", type=Path, default=DEFAULT_PERSON_NAME_OVERRIDES)
    parser.add_argument("--school-name-aliases", type=Path, default=DEFAULT_SCHOOL_NAME_ALIASES)
    parser.add_argument("--people-research-worklist-out", type=Path, default=DEFAULT_PEOPLE_RESEARCH_WORKLIST)
    parser.add_argument("--people-research-limit", type=int, default=50)
    parser.add_argument("--news-gp-worklist-days", type=int, default=7)
    parser.add_argument("--service-integration-out", type=Path, default=DEFAULT_SERVICE_INTEGRATION_OUT)
    parser.add_argument("--service-integration-top-gp-limit", type=int, default=50)
    parser.add_argument("--lp-institutions", type=Path, default=DEFAULT_LP_INSTITUTIONS)
    parser.add_argument("--lp-commitment-sources", type=Path, default=DEFAULT_LP_COMMITMENT_SOURCES)
    parser.add_argument("--lp-monitor-days", type=int, default=180)
    parser.add_argument("--lp-monitor-limit-per-source", type=int, default=50)
    parser.add_argument("--gp-profile-limit", type=int, default=50)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--with-fetch-sources", action="store_true")
    parser.add_argument("--with-rebuild-db", action="store_true")
    parser.add_argument("--skip-profile-evidence", action="store_true")
    parser.add_argument("--skip-dashboard", action="store_true")
    parser.add_argument("--skip-people-import", action="store_true")
    parser.add_argument("--skip-quality-report", action="store_true")
    parser.add_argument("--skip-news-gp-worklist", action="store_true")
    parser.add_argument("--skip-people-worklist", action="store_true")
    parser.add_argument("--skip-service-integration-worklist", action="store_true")
    parser.add_argument("--skip-lp-monitor", action="store_true")
    parser.add_argument("--skip-operational-status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.db.exists() and not args.with_rebuild_db and not args.dry_run:
        raise RuntimeError(
            f"DB file {args.db} does not exist. Use --with-rebuild-db to create it from registered raw files."
        )

    args.log_dir.mkdir(parents=True, exist_ok=True)
    run_id = now_stamp()
    log_path = args.log_dir / f"pipeline_{run_id}.log"
    manifest_path = args.log_dir / f"pipeline_{run_id}.json"

    manifest: dict[str, object] = {
        "started_at": now_iso(),
        "db": str(args.db),
        "exports": str(args.exports),
        "dashboard_out": str(args.dashboard_out),
        "dashboard_index_out": str(args.dashboard_index_out),
        "quality_out": str(args.quality_out),
        "quality_csv_prefix": str(args.quality_csv_prefix),
        "operational_status_out": str(args.operational_status_out),
        "daily_news_out": str(args.daily_news_out),
        "people_input": str(args.people_input),
        "person_role_input": str(args.person_role_input),
        "person_education_input": str(args.person_education_input),
        "person_name_overrides": str(args.person_name_overrides),
        "school_name_aliases": str(args.school_name_aliases),
        "people_research_worklist_out": str(args.people_research_worklist_out),
        "people_research_limit": args.people_research_limit,
        "news_gp_worklist_days": args.news_gp_worklist_days,
        "service_integration_out": str(args.service_integration_out),
        "service_integration_top_gp_limit": args.service_integration_top_gp_limit,
        "lp_institutions": str(args.lp_institutions),
        "lp_commitment_sources": str(args.lp_commitment_sources),
        "lp_monitor_days": args.lp_monitor_days,
        "steps": [],
    }

    steps = build_steps(args)
    with log_path.open("w", encoding="utf-8") as log_fh:
        log_fh.write("Private Equity DB pipeline log\n")
        log_fh.write(json.dumps({k: v for k, v in manifest.items() if k != "steps"}, ensure_ascii=False, indent=2))
        log_fh.write("\n")

        try:
            for step in steps:
                if not step.enabled:
                    print(f"[SKIP] {step.name}: {step.skip_reason}")
                    manifest["steps"].append(
                        {
                            "name": step.name,
                            "description": step.description,
                            "status": "skipped",
                            "reason": step.skip_reason,
                        }
                    )
                    manifest["status"] = "running"
                    manifest["ended_at"] = now_iso()
                    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                    continue
                if step.name == "build_operational_status_report":
                    # The status report reads the latest manifest, so write the
                    # current successful pipeline state before generating it.
                    manifest["status"] = "success"
                    manifest["ended_at"] = now_iso()
                    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                manifest["steps"].append(run_step(step, log_fh, args.dry_run))
                manifest["status"] = "running"
                manifest["ended_at"] = now_iso()
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest["status"] = "success"
            return_code = 0
        except Exception as exc:
            manifest["status"] = "failed"
            manifest["error"] = str(exc)
            return_code = 1
            print(f"[FAIL] {exc}")
        finally:
            manifest["ended_at"] = now_iso()
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"log={log_path}")
    print(f"manifest={manifest_path}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
