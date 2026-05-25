#!/usr/bin/env python
"""Build fund master and review tables from the FSS PEF database."""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from build_gp_master_candidates import write_csv, write_xlsx


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_OUT = REPO_ROOT / "exports"


@dataclass(frozen=True)
class Period:
    period_id: str
    period_label: str
    as_of_date: str
    year: int
    quarter: int
    period_index: int


@dataclass(frozen=True)
class Snapshot:
    fund_id: int
    fund_name: str
    fund_name_norm: str
    regime_first_seen: str
    fund_type: str
    established_date: str
    liquidation_date: str
    period_id: str
    period_label: str
    as_of_date: str
    period_index: int
    gp_id: int | None
    gp_name: str
    gp_name_raw: str
    canonical_gp_names: str
    raw_gp_names: str
    fund_type_raw: str
    status_raw: str
    commitment_amount_raw: str
    commitment_amount_krw_mn: float | None
    paid_in_amount_raw: str
    paid_in_amount_krw_mn: float | None
    source_id: str
    source_title: str
    source_url: str


def split_names(value: str) -> list[str]:
    names = []
    for part in (value or "").replace("\n", ";").split(";"):
        name = part.strip()
        if name and name not in {"-", "－"}:
            names.append(name)
    return names


def compact_name(value: str) -> str:
    value = (value or "").strip().lower()
    value = value.replace("㈜", "주식회사")
    value = value.replace("(주)", "주식회사")
    value = value.replace("（주）", "주식회사")
    return "".join(value.split())


def trn_krw(value_krw_mn: float | None) -> float | str:
    if value_krw_mn is None:
        return ""
    return round(float(value_krw_mn) / 1_000_000.0, 6)


def load_periods(conn: sqlite3.Connection) -> list[Period]:
    rows = conn.execute(
        """
        SELECT period_id, period_label, as_of_date, year, quarter
        FROM reporting_period
        ORDER BY as_of_date, period_id
        """
    ).fetchall()
    return [
        Period(
            period_id=row[0],
            period_label=row[1],
            as_of_date=row[2],
            year=int(row[3]),
            quarter=int(row[4]),
            period_index=int(row[3]) * 4 + int(row[4]),
        )
        for row in rows
    ]


def load_name_map(conn: sqlite3.Connection) -> dict[str, str]:
    name_map: dict[str, str] = {}
    for gp_name, in conn.execute("SELECT gp_name FROM gp_house"):
        name_map[compact_name(gp_name)] = gp_name
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'gp_house_alias'"
    ).fetchone()
    if row:
        for alias_name, canonical_name in conn.execute(
            "SELECT alias_gp_name, canonical_gp_name FROM gp_house_alias"
        ):
            name_map[compact_name(alias_name)] = canonical_name
    return name_map


def canonicalize_gp_names(raw_gp_names: str, fallback_gp_name: str, name_map: dict[str, str]) -> tuple[str, str]:
    raw_names = split_names(raw_gp_names)
    if not raw_names and fallback_gp_name:
        raw_names = [fallback_gp_name]

    canonical_names = []
    for raw_name in raw_names:
        canonical = name_map.get(compact_name(raw_name), raw_name)
        if canonical not in canonical_names:
            canonical_names.append(canonical)
    return "; ".join(canonical_names), "; ".join(raw_names)


def load_snapshots(conn: sqlite3.Connection, name_map: dict[str, str]) -> list[Snapshot]:
    rows = conn.execute(
        """
        SELECT
            pf.fund_id,
            pf.fund_name,
            pf.fund_name_norm,
            COALESCE(pf.regime_first_seen, ''),
            COALESCE(pf.fund_type, ''),
            COALESCE(pf.established_date, ''),
            COALESCE(pf.liquidation_date, ''),
            rp.period_id,
            rp.period_label,
            rp.as_of_date,
            rp.year * 4 + rp.quarter AS period_index,
            fps.gp_id,
            COALESCE(gh.gp_name, ''),
            COALESCE(fps.gp_name_raw, ''),
            COALESCE(fps.fund_type_raw, ''),
            COALESCE(fps.status_raw, ''),
            COALESCE(fps.commitment_amount_raw, ''),
            fps.commitment_amount_krw_mn,
            COALESCE(fps.paid_in_amount_raw, ''),
            fps.paid_in_amount_krw_mn,
            fps.source_id,
            COALESCE(sd.title, ''),
            COALESCE(sd.source_url, '')
        FROM fund_period_snapshot fps
        JOIN pef_fund pf ON pf.fund_id = fps.fund_id
        JOIN reporting_period rp ON rp.period_id = fps.period_id
        LEFT JOIN gp_house gh ON gh.gp_id = fps.gp_id
        LEFT JOIN source_document sd ON sd.source_id = fps.source_id
        ORDER BY pf.fund_id, rp.as_of_date, rp.period_id
        """
    ).fetchall()

    snapshots = []
    for row in rows:
        canonical_names, raw_names = canonicalize_gp_names(row[13], row[12], name_map)
        snapshots.append(
            Snapshot(
                fund_id=int(row[0]),
                fund_name=row[1],
                fund_name_norm=row[2],
                regime_first_seen=row[3],
                fund_type=row[4],
                established_date=row[5],
                liquidation_date=row[6],
                period_id=row[7],
                period_label=row[8],
                as_of_date=row[9],
                period_index=int(row[10]),
                gp_id=int(row[11]) if row[11] is not None else None,
                gp_name=row[12],
                gp_name_raw=row[13],
                canonical_gp_names=canonical_names,
                raw_gp_names=raw_names,
                fund_type_raw=row[14],
                status_raw=row[15],
                commitment_amount_raw=row[16],
                commitment_amount_krw_mn=float(row[17]) if row[17] is not None else None,
                paid_in_amount_raw=row[18],
                paid_in_amount_krw_mn=float(row[19]) if row[19] is not None else None,
                source_id=row[20],
                source_title=row[21],
                source_url=row[22],
            )
        )
    return snapshots


def unique_join(values: list[str]) -> str:
    seen = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return "; ".join(seen)


def next_imported_period(last_period_id: str, periods: list[Period]) -> Period | None:
    for idx, period in enumerate(periods):
        if period.period_id == last_period_id and idx + 1 < len(periods):
            return periods[idx + 1]
    return None


def build_gp_history(grouped: dict[int, list[Snapshot]]) -> list[dict[str, object]]:
    rows = []
    for fund_id, snaps in grouped.items():
        current_key = None
        segment_start: Snapshot | None = None
        segment_end: Snapshot | None = None
        raw_variants: list[str] = []
        observation_count = 0

        def flush() -> None:
            nonlocal segment_start, segment_end, raw_variants, observation_count
            if segment_start is None or segment_end is None:
                return
            rows.append(
                {
                    "fund_id": fund_id,
                    "fund_name": segment_start.fund_name,
                    "canonical_gp_names": segment_start.canonical_gp_names,
                    "raw_gp_name_variants": unique_join(raw_variants),
                    "first_period": segment_start.period_label,
                    "first_as_of_date": segment_start.as_of_date,
                    "last_period": segment_end.period_label,
                    "last_as_of_date": segment_end.as_of_date,
                    "observation_count": observation_count,
                }
            )

        for snap in snaps:
            key = snap.canonical_gp_names
            if current_key is None:
                current_key = key
                segment_start = snap
                segment_end = snap
                raw_variants = [snap.raw_gp_names]
                observation_count = 1
                continue
            if key == current_key:
                segment_end = snap
                raw_variants.append(snap.raw_gp_names)
                observation_count += 1
                continue
            flush()
            current_key = key
            segment_start = snap
            segment_end = snap
            raw_variants = [snap.raw_gp_names]
            observation_count = 1
        flush()
    return rows


def build_commitment_history(grouped: dict[int, list[Snapshot]]) -> list[dict[str, object]]:
    rows = []
    for fund_id, snaps in grouped.items():
        previous_amount: float | None = None
        for snap in snaps:
            changed = ""
            delta = ""
            if previous_amount is not None and snap.commitment_amount_krw_mn is not None:
                changed = 1 if snap.commitment_amount_krw_mn != previous_amount else 0
                delta = trn_krw(snap.commitment_amount_krw_mn - previous_amount)
            rows.append(
                {
                    "fund_id": fund_id,
                    "fund_name": snap.fund_name,
                    "period_label": snap.period_label,
                    "as_of_date": snap.as_of_date,
                    "canonical_gp_names": snap.canonical_gp_names,
                    "raw_gp_names": snap.raw_gp_names,
                    "commitment_amount_raw": snap.commitment_amount_raw,
                    "commitment_trn_krw": trn_krw(snap.commitment_amount_krw_mn),
                    "paid_in_amount_raw": snap.paid_in_amount_raw,
                    "paid_in_trn_krw": trn_krw(snap.paid_in_amount_krw_mn),
                    "commitment_changed_from_previous": changed,
                    "commitment_delta_trn_krw": delta,
                    "source_id": snap.source_id,
                    "source_url": snap.source_url,
                }
            )
            if snap.commitment_amount_krw_mn is not None:
                previous_amount = snap.commitment_amount_krw_mn
    return rows


def build_lifecycle_events(
    grouped: dict[int, list[Snapshot]],
    periods: list[Period],
    latest_period_id: str,
) -> list[dict[str, object]]:
    rows = []
    for fund_id, snaps in grouped.items():
        first = snaps[0]
        last = snaps[-1]
        if first.established_date:
            rows.append(
                {
                    "fund_id": fund_id,
                    "fund_name": first.fund_name,
                    "event_type": "established",
                    "event_date": first.established_date,
                    "event_period": "",
                    "confidence": "A",
                    "basis": "FSS established/register date field",
                }
            )
        rows.append(
            {
                "fund_id": fund_id,
                "fund_name": first.fund_name,
                "event_type": "first_seen_in_imported_fss",
                "event_date": first.as_of_date,
                "event_period": first.period_label,
                "confidence": "A",
                "basis": "First appearance in imported FSS quarterly status files",
            }
        )
        if first.liquidation_date:
            rows.append(
                {
                    "fund_id": fund_id,
                    "fund_name": first.fund_name,
                    "event_type": "liquidation_reported",
                    "event_date": first.liquidation_date,
                    "event_period": "",
                    "confidence": "A",
                    "basis": "FSS liquidation date field",
                }
            )
        if last.period_id != latest_period_id:
            next_period = next_imported_period(last.period_id, periods)
            if next_period is not None:
                consecutive = next_period.period_index == last.period_index + 1
                rows.append(
                    {
                        "fund_id": fund_id,
                        "fund_name": first.fund_name,
                        "event_type": "disappeared_from_fss",
                        "event_date": next_period.as_of_date,
                        "event_period": next_period.period_label,
                        "confidence": "B" if consecutive else "C_GAP",
                        "basis": (
                            "Absent from next consecutive imported FSS status; not a confirmed liquidation"
                            if consecutive
                            else "Absent from later imported FSS status after an import gap; not a confirmed liquidation"
                        ),
                    }
                )
    return rows


def latest_amount(snaps: list[Snapshot]) -> float | None:
    for snap in reversed(snaps):
        if snap.commitment_amount_krw_mn is not None:
            return snap.commitment_amount_krw_mn
    return None


def first_amount(snaps: list[Snapshot]) -> float | None:
    for snap in snaps:
        if snap.commitment_amount_krw_mn is not None:
            return snap.commitment_amount_krw_mn
    return None


def build_fund_master(
    grouped: dict[int, list[Snapshot]],
    periods: list[Period],
    latest_period_id: str,
) -> list[dict[str, object]]:
    rows = []
    for fund_id, snaps in grouped.items():
        first = snaps[0]
        last = snaps[-1]
        all_canonical_names = []
        all_raw_names = []
        all_gp_sets = []
        fund_type_values = []
        for snap in snaps:
            all_canonical_names.extend(split_names(snap.canonical_gp_names))
            all_raw_names.extend(split_names(snap.raw_gp_names))
            if snap.canonical_gp_names and snap.canonical_gp_names not in all_gp_sets:
                all_gp_sets.append(snap.canonical_gp_names)
            if snap.fund_type_raw and snap.fund_type_raw not in fund_type_values:
                fund_type_values.append(snap.fund_type_raw)

        amounts = [snap.commitment_amount_krw_mn for snap in snaps if snap.commitment_amount_krw_mn is not None]
        first_commitment = first_amount(snaps)
        latest_commitment = latest_amount(snaps)
        max_commitment = max(amounts) if amounts else None
        active_in_latest = 1 if last.period_id == latest_period_id else 0
        next_period = None if active_in_latest else next_imported_period(last.period_id, periods)
        if first.liquidation_date:
            lifecycle_status = "liquidation_reported"
        elif active_in_latest:
            lifecycle_status = "active_in_latest_fss"
        else:
            lifecycle_status = "absent_from_later_fss_not_confirmed"

        rows.append(
            {
                "fund_id": fund_id,
                "fund_name": first.fund_name,
                "fund_name_norm": first.fund_name_norm,
                "regime_first_seen": first.regime_first_seen,
                "fund_type_master": first.fund_type,
                "fund_type_raw_values": unique_join(fund_type_values),
                "established_date": first.established_date,
                "liquidation_date": first.liquidation_date,
                "lifecycle_status": lifecycle_status,
                "first_seen_period": first.period_label,
                "first_seen_date": first.as_of_date,
                "last_seen_period": last.period_label,
                "last_seen_date": last.as_of_date,
                "active_in_latest_period": active_in_latest,
                "first_absent_period_after_last_seen": "" if next_period is None else next_period.period_label,
                "first_absent_date_after_last_seen": "" if next_period is None else next_period.as_of_date,
                "disappearance_basis": ""
                if active_in_latest
                else "Absent from later imported FSS status; not a confirmed liquidation",
                "latest_canonical_gp_names": last.canonical_gp_names,
                "all_canonical_gp_names": unique_join(all_canonical_names),
                "raw_gp_name_variants": unique_join(all_raw_names),
                "gp_history_segment_count": len(all_gp_sets),
                "gp_changed_by_canonical_name": 1 if len(all_gp_sets) > 1 else 0,
                "period_observation_count": len(snaps),
                "first_commitment_trn_krw": trn_krw(first_commitment),
                "latest_commitment_trn_krw": trn_krw(latest_commitment),
                "max_commitment_trn_krw": trn_krw(max_commitment),
                "commitment_delta_first_to_latest_trn_krw": ""
                if first_commitment is None or latest_commitment is None
                else trn_krw(latest_commitment - first_commitment),
                "latest_paid_in_trn_krw": trn_krw(last.paid_in_amount_krw_mn),
                "latest_source_id": last.source_id,
                "latest_source_url": last.source_url,
            }
        )
    return rows


def sql_type(column: str) -> str:
    integer_columns = {
        "fund_id",
        "active_in_latest_period",
        "gp_history_segment_count",
        "gp_changed_by_canonical_name",
        "period_observation_count",
        "observation_count",
        "commitment_changed_from_previous",
    }
    if column in integer_columns:
        return "INTEGER"
    if column.endswith("_trn_krw") or column.endswith("_delta_trn_krw"):
        return "REAL"
    return "TEXT"


def replace_table(conn: sqlite3.Connection, table_name: str, rows: list[dict[str, object]]) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    if not rows:
        return
    columns = list(rows[0].keys())
    column_sql = ", ".join(f"{column} {sql_type(column)}" for column in columns)
    conn.execute(f"CREATE TABLE {table_name} ({column_sql})")
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})",
        [[row.get(column, "") for column in columns] for row in rows],
    )


def build(db_path: Path, out_dir: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        periods = load_periods(conn)
        latest_period_id = periods[-1].period_id
        name_map = load_name_map(conn)
        snapshots = load_snapshots(conn, name_map)
        grouped: dict[int, list[Snapshot]] = defaultdict(list)
        for snap in snapshots:
            grouped[snap.fund_id].append(snap)

        fund_master = build_fund_master(grouped, periods, latest_period_id)
        gp_history = build_gp_history(grouped)
        commitment_history = build_commitment_history(grouped)
        lifecycle_events = build_lifecycle_events(grouped, periods, latest_period_id)

        out_dir.mkdir(parents=True, exist_ok=True)
        write_csv(out_dir / "fund_master.csv", fund_master)
        write_csv(out_dir / "fund_gp_history.csv", gp_history)
        write_csv(out_dir / "fund_commitment_history.csv", commitment_history)
        write_csv(out_dir / "fund_lifecycle_events.csv", lifecycle_events)
        write_xlsx(
            out_dir / "fund_master.xlsx",
            [
                ("fund_master", fund_master),
                ("gp_history", gp_history),
                ("commitment_history", commitment_history),
                ("lifecycle_events", lifecycle_events),
            ],
        )

        replace_table(conn, "fund_master", fund_master)
        replace_table(conn, "fund_gp_history", gp_history)
        replace_table(conn, "fund_commitment_history", commitment_history)
        replace_table(conn, "fund_lifecycle_event", lifecycle_events)
        conn.commit()

        return {
            "fund_master": len(fund_master),
            "fund_gp_history": len(gp_history),
            "fund_commitment_history": len(commitment_history),
            "fund_lifecycle_event": len(lifecycle_events),
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build fund master exports and DB tables")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    counts = build(args.db, args.out)
    for key, value in counts.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
