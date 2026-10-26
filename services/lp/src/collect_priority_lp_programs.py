#!/usr/bin/env python3
"""Collect reviewed PE programs from Korea Post, KTCU, and KEXIM."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .collect_ktcu_program import collect as collect_ktcu, project as project_ktcu, link_suggestions as suggest_ktcu, discovery_candidates as discover_ktcu
    from .collect_koreapost_program import collect as collect_post, project as project_post, _suggestions as suggest_post, discovery_candidates as discover_post
    from .collect_kexim_programs import collect as collect_kexim, project as project_kexim, link_suggestions as suggest_kexim, discovery_candidates as discover_kexim
except ImportError:
    from collect_ktcu_program import collect as collect_ktcu, project as project_ktcu, link_suggestions as suggest_ktcu, discovery_candidates as discover_ktcu
    from collect_koreapost_program import collect as collect_post, project as project_post, _suggestions as suggest_post, discovery_candidates as discover_post
    from collect_kexim_programs import collect as collect_kexim, project as project_kexim, link_suggestions as suggest_kexim, discovery_candidates as discover_kexim

ROOT = Path(__file__).resolve().parents[3]


def _current_artifact(path: Path, checked_at: str, institution: str) -> dict:
    report = json.loads(path.read_text())
    collected_at = datetime.fromisoformat(report["checked_at"])
    now = datetime.fromisoformat(checked_at)
    if collected_at.tzinfo is None or now.tzinfo is None or not (-timedelta(minutes=5) <= now - collected_at <= timedelta(hours=2)):
        raise ValueError(f"{institution} collection is not from the current run")
    if not report["notices"]:
        raise ValueError(f"{institution} official collection is empty")
    return report


def load_ktcu_collection(path: Path, checked_at: str, seed_program: dict) -> dict:
    report = _current_artifact(path, checked_at, 'KTCU')
    notices = report['notices']
    programs, holds = project_ktcu(notices, checked_at, seed_program)
    return {'checked_at': report['checked_at'], 'notices': notices,
            'programs': programs, 'holds': holds,
            'link_suggestions': suggest_ktcu(notices, seed_program['title']),
            'discovery_candidates': discover_ktcu(notices)}


def load_kexim_collection(path: Path, checked_at: str) -> dict:
    """Read this workflow run's macOS artifact and verify its official evidence."""
    report = _current_artifact(path, checked_at, "KEXIM")
    notices = report["notices"]
    programs, holds = project_kexim(notices, checked_at)
    return {"checked_at": report["checked_at"], "notices": notices,
            "programs": programs, "holds": holds,
            "supporting_notices": report.get("supporting_notices", []), "supporting_holds": report.get("supporting_holds", []),
            "link_suggestions": suggest_kexim(notices),
            "discovery_candidates": discover_kexim(notices)}


def load_post_collection(path: Path, checked_at: str) -> dict:
    report = _current_artifact(path, checked_at, "Korea Post")
    notices = report["notices"]
    programs, holds = project_post(notices, checked_at)
    return {"checked_at": report["checked_at"], "notices": notices,
            "programs": programs, "holds": holds,
            "link_suggestions": suggest_post(notices),
            "collection_coverage": report.get("collection_coverage", {}),
            "discovery_candidates": discover_post(notices)}


def collect(seed=None, checked_at=None, collectors=None, kexim_input: Path | None = None,
            koreapost_input: Path | None = None, ktcu_input: Path | None = None):
    seed = seed or json.loads((ROOT / "data/lp_programs_pilot.json").read_text())
    by_id = {p["id"]: p for p in seed["programs"]}
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    collectors = collectors or {
        "ktcu": (lambda: load_ktcu_collection(ktcu_input, checked_at, by_id["ktcu-2026-blind-pef"])) if ktcu_input else
                (lambda: collect_ktcu(by_id["ktcu-2026-blind-pef"], checked_at)),
        "koreapost": (lambda: load_post_collection(koreapost_input, checked_at)) if koreapost_input else
                     (lambda: collect_post(by_id["koreapost-2026-domestic-pe"], checked_at)),
        "kexim": (lambda: load_kexim_collection(kexim_input, checked_at)) if kexim_input else
                 (lambda: collect_kexim(checked_at)),
    }
    sources = {}
    for institution, run in collectors.items():
        try:
            sources[institution] = run()
        except Exception as error:
            # A source outage must not erase previously published programs or
            # stop independent institutions from updating on this run.
            sources[institution] = {"notices": [], "programs": [], "holds": [
                {"program_id": institution, "reason": f"공식 자료 수집 실패: {type(error).__name__}"}],
                "link_suggestions": [], "error": f"{type(error).__name__}: {error}"}
    return {"checked_at": checked_at, "sources": sources}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ktcu-input", type=Path, help="official KTCU artifact from this run’s macOS runner")
    parser.add_argument("--kexim-input", type=Path,
                        help="official collection artifact from this run's macOS runner")
    parser.add_argument("--koreapost-input", type=Path,
                        help="official collection artifact from this run's macOS runner")
    args = parser.parse_args()
    report = collect(kexim_input=args.kexim_input, koreapost_input=args.koreapost_input, ktcu_input=args.ktcu_input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.output)
    print(json.dumps({key: {"notices": len(value["notices"]), "programs": len(value["programs"]),
                            "holds": len(value["holds"])} for key, value in report["sources"].items()}))


if __name__ == "__main__":
    main()
