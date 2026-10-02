#!/usr/bin/env python3
"""Collect reviewed PE programs from Korea Post, KTCU, and KEXIM."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from collect_ktcu_program import collect as collect_ktcu
from collect_koreapost_program import collect as collect_post
from collect_kexim_programs import collect as collect_kexim

ROOT = Path(__file__).resolve().parents[3]


def collect(seed=None, checked_at=None, collectors=None):
    seed = seed or json.loads((ROOT / "data/lp_programs_pilot.json").read_text())
    by_id = {p["id"]: p for p in seed["programs"]}
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    collectors = collectors or {
        "ktcu": lambda: collect_ktcu(by_id["ktcu-2026-blind-pef"], checked_at),
        "koreapost": lambda: collect_post(by_id["koreapost-2026-domestic-pe"], checked_at),
        "kexim": lambda: collect_kexim(checked_at),
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
    args = parser.parse_args()
    report = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.output)
    print(json.dumps({key: {"notices": len(value["notices"]), "programs": len(value["programs"]),
                            "holds": len(value["holds"])} for key, value in report["sources"].items()}))


if __name__ == "__main__":
    main()
