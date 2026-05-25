#!/usr/bin/env python
"""Build reviewable GP master candidate tables from the FSS PEF database.

This script does not merge similar GP names. It creates one master candidate
per FSS gp_house row and writes separate alias review candidates for names that
look similar enough to require a human or external identifier check.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from xml.sax.saxutils import escape


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_OUT = REPO_ROOT / "exports"


LEGAL_TERMS = [
    "주식회사",
    "유한회사",
    "유한책임회사",
    "합자회사",
    "합명회사",
    "inc",
    "ltd",
    "llc",
    "co",
    "corp",
    "corporation",
]

GENERIC_GP_TERMS = [
    "프라이빗에쿼티",
    "프라이빗에쿼티스",
    "피이에프",
    "피이",
    "pef",
    "pe",
    "privateequity",
    "파트너스",
    "partners",
    "인베스트먼트",
    "인베스트먼츠",
    "investment",
    "investments",
    "자산운용",
    "assetmanagement",
    "캐피탈",
    "capital",
    "벤처스",
    "ventures",
    "운용",
    "투자자문",
    "투자증권",
    "창업투자",
    "신기술투자",
]


@dataclass
class PeriodInfo:
    period_label: str = ""
    as_of_date: str = ""


@dataclass
class VariantStat:
    raw_name: str
    norm: str
    first_seen_date: str = ""
    first_seen_period: str = ""
    last_seen_date: str = ""
    last_seen_period: str = ""
    observation_count: int = 0


@dataclass
class GpCandidate:
    gp_id: int
    gp_name: str
    gp_name_norm: str
    first_seen_period_id: str
    last_seen_period_id: str
    first_seen_period: str = ""
    first_seen_date: str = ""
    last_seen_period: str = ""
    last_seen_date: str = ""
    active_in_latest_period: int = 0
    affiliated_fund_count: int = 0
    primary_fund_count: int = 0
    primary_observed_period_count: int = 0
    latest_primary_fund_count: int = 0
    latest_primary_commitment_krw_mn: float = 0.0
    max_primary_commitment_krw_mn: float = 0.0
    max_primary_commitment_period: str = ""
    variants: dict[str, VariantStat] = field(default_factory=dict)
    alias_candidate_count: int = 0
    needs_review: int = 0
    review_reasons: set[str] = field(default_factory=set)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compact_name(value: str) -> str:
    value = (value or "").strip().lower()
    value = value.replace("㈜", "주식회사")
    value = value.replace("(주)", "주식회사")
    value = value.replace("（주）", "주식회사")
    value = re.sub(r"[\s\-_.,()/\\·ㆍ&+]", "", value)
    return value


def normalize_name(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"\s+", "", value)
    value = value.replace("㈜", "주식회사")
    value = value.replace("(주)", "주식회사")
    value = value.replace("（주）", "주식회사")
    return value.lower()


def legal_key(value: str) -> str:
    key = compact_name(value)
    changed = True
    while changed:
        changed = False
        for term in LEGAL_TERMS:
            if key.startswith(term) and len(key) > len(term):
                key = key[len(term) :]
                changed = True
            if key.endswith(term) and len(key) > len(term):
                key = key[: -len(term)]
                changed = True
    return key


def core_key(value: str) -> str:
    key = legal_key(value)
    for term in GENERIC_GP_TERMS:
        key = key.replace(term, "")
    return key


def split_gp_names(raw_value: str) -> list[str]:
    names = []
    for part in re.split(r"[;\n]+", raw_value or ""):
        name = part.strip()
        if name and name not in {"-", "－"}:
            names.append(name)
    return names


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def fetch_periods(conn: sqlite3.Connection) -> dict[str, PeriodInfo]:
    periods = {}
    for row in conn.execute(
        """
        SELECT period_id, period_label, as_of_date
        FROM reporting_period
        """
    ):
        periods[row[0]] = PeriodInfo(period_label=row[1] or "", as_of_date=row[2] or "")
    return periods


def fetch_latest_period(conn: sqlite3.Connection) -> tuple[str, str, str]:
    row = conn.execute(
        """
        SELECT period_id, period_label, as_of_date
        FROM reporting_period
        ORDER BY as_of_date DESC, period_id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return "", "", ""
    return row[0], row[1] or "", row[2] or ""


def load_candidates(conn: sqlite3.Connection, periods: dict[str, PeriodInfo], latest_period_id: str) -> dict[int, GpCandidate]:
    candidates: dict[int, GpCandidate] = {}
    for row in conn.execute(
        """
        SELECT gp_id, gp_name, gp_name_norm, first_seen_period_id, last_seen_period_id
        FROM gp_house
        ORDER BY gp_id
        """
    ):
        gp = GpCandidate(
            gp_id=int(row[0]),
            gp_name=row[1] or "",
            gp_name_norm=row[2] or "",
            first_seen_period_id=row[3] or "",
            last_seen_period_id=row[4] or "",
        )
        first_period = periods.get(gp.first_seen_period_id, PeriodInfo())
        last_period = periods.get(gp.last_seen_period_id, PeriodInfo())
        gp.first_seen_period = first_period.period_label
        gp.first_seen_date = first_period.as_of_date
        gp.last_seen_period = last_period.period_label
        gp.last_seen_date = last_period.as_of_date
        gp.active_in_latest_period = 1 if gp.last_seen_period_id == latest_period_id else 0
        candidates[gp.gp_id] = gp
    return candidates


def add_count_stats(conn: sqlite3.Connection, candidates: dict[int, GpCandidate], latest_period_id: str) -> None:
    for gp_id, count in conn.execute(
        """
        SELECT gp_id, COUNT(DISTINCT fund_id)
        FROM fund_gp_affiliation
        GROUP BY gp_id
        """
    ):
        if gp_id in candidates:
            candidates[int(gp_id)].affiliated_fund_count = int(count or 0)

    for gp_id, fund_count, period_count in conn.execute(
        """
        SELECT gp_id, COUNT(DISTINCT fund_id), COUNT(DISTINCT period_id)
        FROM fund_period_snapshot
        WHERE gp_id IS NOT NULL
        GROUP BY gp_id
        """
    ):
        if gp_id in candidates:
            candidates[int(gp_id)].primary_fund_count = int(fund_count or 0)
            candidates[int(gp_id)].primary_observed_period_count = int(period_count or 0)

    for gp_id, fund_count, commitment in conn.execute(
        """
        SELECT gp_id, COUNT(DISTINCT fund_id), SUM(commitment_amount_krw_mn)
        FROM fund_period_snapshot
        WHERE period_id = ? AND gp_id IS NOT NULL
        GROUP BY gp_id
        """,
        (latest_period_id,),
    ):
        if gp_id in candidates:
            candidates[int(gp_id)].latest_primary_fund_count = int(fund_count or 0)
            candidates[int(gp_id)].latest_primary_commitment_krw_mn = float(commitment or 0.0)

    for gp_id, period_label, commitment in conn.execute(
        """
        WITH period_amount AS (
            SELECT
                fps.gp_id,
                rp.period_label,
                rp.as_of_date,
                SUM(fps.commitment_amount_krw_mn) AS commitment_amount_krw_mn,
                ROW_NUMBER() OVER (
                    PARTITION BY fps.gp_id
                    ORDER BY SUM(fps.commitment_amount_krw_mn) DESC, rp.as_of_date DESC
                ) AS rn
            FROM fund_period_snapshot fps
            JOIN reporting_period rp ON rp.period_id = fps.period_id
            WHERE fps.gp_id IS NOT NULL
            GROUP BY fps.gp_id, fps.period_id
        )
        SELECT gp_id, period_label, commitment_amount_krw_mn
        FROM period_amount
        WHERE rn = 1
        """
    ):
        if gp_id in candidates:
            candidates[int(gp_id)].max_primary_commitment_period = period_label or ""
            candidates[int(gp_id)].max_primary_commitment_krw_mn = float(commitment or 0.0)


def collect_variants(
    conn: sqlite3.Connection,
    candidates: dict[int, GpCandidate],
    periods: dict[str, PeriodInfo],
) -> None:
    norm_to_gp_id = {gp.gp_name_norm: gp_id for gp_id, gp in candidates.items()}
    if table_exists(conn, "gp_house_alias"):
        for alias_norm, canonical_gp_id, alias_name in conn.execute(
            """
            SELECT alias_gp_name_norm, canonical_gp_id, alias_gp_name
            FROM gp_house_alias
            """
        ):
            if canonical_gp_id in candidates:
                norm_to_gp_id[alias_norm] = canonical_gp_id
                candidates[canonical_gp_id].variants.setdefault(
                    alias_name,
                    VariantStat(raw_name=alias_name, norm=alias_norm),
                )

    for gp in candidates.values():
        norm = normalize_name(gp.gp_name)
        gp.variants[gp.gp_name] = VariantStat(
            raw_name=gp.gp_name,
            norm=norm,
            first_seen_date=gp.first_seen_date,
            first_seen_period=gp.first_seen_period,
            last_seen_date=gp.last_seen_date,
            last_seen_period=gp.last_seen_period,
            observation_count=0,
        )

    for primary_gp_id, raw_value, period_id in conn.execute(
        """
        SELECT gp_id, gp_name_raw, period_id
        FROM fund_period_snapshot
        WHERE gp_name_raw IS NOT NULL AND TRIM(gp_name_raw) <> ''
        """
    ):
        period = periods.get(period_id or "", PeriodInfo())
        for idx, raw_name in enumerate(split_gp_names(raw_value)):
            norm = normalize_name(raw_name)
            gp_id = norm_to_gp_id.get(norm)
            if idx == 0 and primary_gp_id in candidates:
                gp_id = int(primary_gp_id)
            if gp_id is None or gp_id not in candidates:
                continue
            variants = candidates[gp_id].variants
            stat = variants.get(raw_name)
            if stat is None:
                stat = VariantStat(raw_name=raw_name, norm=norm)
                variants[raw_name] = stat
            stat.observation_count += 1
            if period.as_of_date:
                if not stat.first_seen_date or period.as_of_date < stat.first_seen_date:
                    stat.first_seen_date = period.as_of_date
                    stat.first_seen_period = period.period_label
                if not stat.last_seen_date or period.as_of_date > stat.last_seen_date:
                    stat.last_seen_date = period.as_of_date
                    stat.last_seen_period = period.period_label

    for gp in candidates.values():
        if len(gp.variants) > 1:
            gp.needs_review = 1
            gp.review_reasons.add("raw_name_variants")


def add_alias_group(
    groups: dict[tuple[str, str], dict[str, object]],
    candidate_type: str,
    review_priority: str,
    review_key: str,
    gp_ids: list[int],
    reason: str,
) -> None:
    unique_gp_ids = sorted(set(gp_ids))
    if len(unique_gp_ids) < 2:
        return
    groups[(candidate_type, review_key)] = {
        "candidate_type": candidate_type,
        "review_priority": review_priority,
        "review_key": review_key,
        "gp_ids": unique_gp_ids,
        "reason": reason,
    }


def build_alias_groups(candidates: dict[int, GpCandidate]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], dict[str, object]] = {}
    high_priority_sets: set[tuple[int, ...]] = set()

    by_legal_key: dict[str, list[int]] = defaultdict(list)
    by_core_key: dict[str, list[int]] = defaultdict(list)
    for gp in candidates.values():
        l_key = legal_key(gp.gp_name)
        c_key = core_key(gp.gp_name)
        if len(l_key) >= 3:
            by_legal_key[l_key].append(gp.gp_id)
        if len(c_key) >= 4:
            by_core_key[c_key].append(gp.gp_id)

    for key, gp_ids in by_legal_key.items():
        unique_gp_ids = tuple(sorted(set(gp_ids)))
        if len(unique_gp_ids) > 1:
            add_alias_group(
                groups,
                "same_legal_key",
                "HIGH",
                key,
                list(unique_gp_ids),
                "Names become identical after removing legal-form markers and punctuation; do not merge without identifier check.",
            )
            high_priority_sets.add(unique_gp_ids)

    for key, gp_ids in by_core_key.items():
        unique_gp_ids = sorted(set(gp_ids))
        if tuple(unique_gp_ids) in high_priority_sets:
            continue
        if 1 < len(unique_gp_ids) <= 12:
            add_alias_group(
                groups,
                "same_core_key",
                "MEDIUM",
                key,
                unique_gp_ids,
                "Names share the same non-generic core after removing GP business descriptors; requires external identifier check.",
            )

    gp_list = sorted(candidates.values(), key=lambda gp: gp.gp_id)
    for idx, left in enumerate(gp_list):
        left_key = legal_key(left.gp_name)
        if len(left_key) < 5:
            continue
        for right in gp_list[idx + 1 :]:
            right_key = legal_key(right.gp_name)
            if len(right_key) < 5:
                continue
            if left_key[0] != right_key[0]:
                continue
            ratio = SequenceMatcher(None, left_key, right_key).ratio()
            if ratio >= 0.94:
                gp_ids = tuple(sorted([left.gp_id, right.gp_id]))
                if gp_ids in high_priority_sets:
                    continue
                review_key = f"{left_key}|{right_key}"
                add_alias_group(
                    groups,
                    "similar_legal_key",
                    "MEDIUM",
                    review_key,
                    [left.gp_id, right.gp_id],
                    f"Legal keys are highly similar by string ratio ({ratio:.3f}); requires external identifier check.",
                )

    ordered = sorted(
        groups.values(),
        key=lambda row: (
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(str(row["review_priority"]), 9),
            str(row["candidate_type"]),
            str(row["review_key"]),
        ),
    )
    for idx, row in enumerate(ordered, start=1):
        row["alias_candidate_group_id"] = f"alias_review_{idx:04d}"
    return ordered


def mark_alias_reviews(candidates: dict[int, GpCandidate], alias_groups: list[dict[str, object]]) -> None:
    for group in alias_groups:
        candidate_type = str(group["candidate_type"])
        for gp_id in group["gp_ids"]:  # type: ignore[index]
            gp = candidates[int(gp_id)]
            gp.alias_candidate_count += 1
            gp.needs_review = 1
            gp.review_reasons.add(candidate_type)


def trn_krw(value_krw_mn: float) -> float:
    return round((value_krw_mn or 0.0) / 1_000_000.0, 6)


def ensure_output_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS gp_master_candidate (
            gp_master_candidate_id TEXT PRIMARY KEY,
            source_gp_id INTEGER NOT NULL,
            standard_gp_name TEXT NOT NULL,
            gp_name_norm TEXT NOT NULL,
            mapping_status TEXT NOT NULL,
            verification_level TEXT NOT NULL,
            business_registration_number TEXT,
            corporate_registration_number TEXT,
            legal_entity_name_verified TEXT,
            homepage_url TEXT,
            first_seen_period TEXT,
            first_seen_date TEXT,
            last_seen_period TEXT,
            last_seen_date TEXT,
            active_in_latest_period INTEGER NOT NULL,
            affiliated_fund_count INTEGER NOT NULL,
            primary_fund_count INTEGER NOT NULL,
            primary_observed_period_count INTEGER NOT NULL,
            latest_primary_fund_count INTEGER NOT NULL,
            latest_primary_commitment_trn_krw REAL NOT NULL,
            max_primary_commitment_trn_krw REAL NOT NULL,
            max_primary_commitment_period TEXT,
            raw_name_variant_count INTEGER NOT NULL,
            raw_name_variants TEXT,
            alias_candidate_count INTEGER NOT NULL,
            needs_review INTEGER NOT NULL,
            review_reason TEXT,
            source_basis TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gp_name_variant (
            source_gp_id INTEGER NOT NULL,
            gp_master_candidate_id TEXT NOT NULL,
            standard_gp_name TEXT NOT NULL,
            raw_name_variant TEXT NOT NULL,
            raw_name_norm TEXT NOT NULL,
            first_seen_period TEXT,
            first_seen_date TEXT,
            last_seen_period TEXT,
            last_seen_date TEXT,
            observation_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gp_alias_review_candidate (
            alias_candidate_group_id TEXT PRIMARY KEY,
            candidate_type TEXT NOT NULL,
            review_priority TEXT NOT NULL,
            review_key TEXT NOT NULL,
            candidate_gp_ids TEXT NOT NULL,
            candidate_gp_names TEXT NOT NULL,
            candidate_count INTEGER NOT NULL,
            latest_primary_commitment_trn_krw_sum REAL NOT NULL,
            max_primary_commitment_trn_krw_sum REAL NOT NULL,
            reason TEXT NOT NULL,
            requires_external_identifier TEXT NOT NULL,
            recommended_check TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute("DELETE FROM gp_master_candidate")
    conn.execute("DELETE FROM gp_name_variant")
    conn.execute("DELETE FROM gp_alias_review_candidate")


def candidate_rows(candidates: dict[int, GpCandidate], created_at: str) -> list[dict[str, object]]:
    rows = []
    for gp in sorted(candidates.values(), key=lambda item: item.gp_id):
        variant_names = sorted({stat.raw_name for stat in gp.variants.values() if stat.raw_name})
        rows.append(
            {
                "gp_master_candidate_id": f"fss_gp_{gp.gp_id:05d}",
                "source_gp_id": gp.gp_id,
                "standard_gp_name": gp.gp_name,
                "gp_name_norm": gp.gp_name_norm,
                "mapping_status": "not_merged",
                "verification_level": "FSS_GP_NAME_ONLY",
                "business_registration_number": "",
                "corporate_registration_number": "",
                "legal_entity_name_verified": "",
                "homepage_url": "",
                "first_seen_period": gp.first_seen_period,
                "first_seen_date": gp.first_seen_date,
                "last_seen_period": gp.last_seen_period,
                "last_seen_date": gp.last_seen_date,
                "active_in_latest_period": gp.active_in_latest_period,
                "affiliated_fund_count": gp.affiliated_fund_count,
                "primary_fund_count": gp.primary_fund_count,
                "primary_observed_period_count": gp.primary_observed_period_count,
                "latest_primary_fund_count": gp.latest_primary_fund_count,
                "latest_primary_commitment_trn_krw": trn_krw(gp.latest_primary_commitment_krw_mn),
                "max_primary_commitment_trn_krw": trn_krw(gp.max_primary_commitment_krw_mn),
                "max_primary_commitment_period": gp.max_primary_commitment_period,
                "raw_name_variant_count": len(variant_names),
                "raw_name_variants": "; ".join(variant_names),
                "alias_candidate_count": gp.alias_candidate_count,
                "needs_review": gp.needs_review,
                "review_reason": "; ".join(sorted(gp.review_reasons)),
                "source_basis": "FSS quarterly PEF status; no external identifier verified yet",
                "created_at": created_at,
            }
        )
    return rows


def variant_rows(candidates: dict[int, GpCandidate], created_at: str) -> list[dict[str, object]]:
    rows = []
    for gp in sorted(candidates.values(), key=lambda item: item.gp_id):
        for stat in sorted(gp.variants.values(), key=lambda item: item.raw_name):
            rows.append(
                {
                    "source_gp_id": gp.gp_id,
                    "gp_master_candidate_id": f"fss_gp_{gp.gp_id:05d}",
                    "standard_gp_name": gp.gp_name,
                    "raw_name_variant": stat.raw_name,
                    "raw_name_norm": stat.norm,
                    "first_seen_period": stat.first_seen_period,
                    "first_seen_date": stat.first_seen_date,
                    "last_seen_period": stat.last_seen_period,
                    "last_seen_date": stat.last_seen_date,
                    "observation_count": stat.observation_count,
                    "created_at": created_at,
                }
            )
    return rows


def alias_rows(
    candidates: dict[int, GpCandidate],
    alias_groups: list[dict[str, object]],
    created_at: str,
) -> list[dict[str, object]]:
    rows = []
    for group in alias_groups:
        gp_ids = [int(gp_id) for gp_id in group["gp_ids"]]  # type: ignore[index]
        names = [candidates[gp_id].gp_name for gp_id in gp_ids]
        latest_sum = sum(candidates[gp_id].latest_primary_commitment_krw_mn for gp_id in gp_ids)
        max_sum = sum(candidates[gp_id].max_primary_commitment_krw_mn for gp_id in gp_ids)
        rows.append(
            {
                "alias_candidate_group_id": group["alias_candidate_group_id"],
                "candidate_type": group["candidate_type"],
                "review_priority": group["review_priority"],
                "review_key": group["review_key"],
                "candidate_gp_ids": "; ".join(str(gp_id) for gp_id in gp_ids),
                "candidate_gp_names": "; ".join(names),
                "candidate_count": len(gp_ids),
                "latest_primary_commitment_trn_krw_sum": trn_krw(latest_sum),
                "max_primary_commitment_trn_krw_sum": trn_krw(max_sum),
                "reason": group["reason"],
                "requires_external_identifier": "Y",
                "recommended_check": "Confirm with business registration number, corporate registration, DART, FSS registration record, or official company source before merging.",
                "created_at": created_at,
            }
        )
    return rows


def insert_rows(conn: sqlite3.Connection, table_name: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    conn.executemany(
        f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})",
        [[row[column] for column in columns] for row in rows],
    )


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def excel_col_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def clean_xml_text(value: object) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)


def cell_xml(row_idx: int, col_idx: int, value: object, is_header: bool = False) -> str:
    ref = f"{excel_col_name(col_idx)}{row_idx}"
    style = ' s="1"' if is_header else ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"{style}><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{style}><v>{value}</v></c>'
    text = escape(clean_xml_text(value))
    return f'<c r="{ref}" t="inlineStr"{style}><is><t>{text}</t></is></c>'


def sheet_xml(rows: list[dict[str, object]]) -> str:
    if not rows:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData></sheetData></worksheet>"
        )
    headers = list(rows[0].keys())
    sheet_rows = []
    header_cells = "".join(cell_xml(1, idx, header, is_header=True) for idx, header in enumerate(headers, start=1))
    sheet_rows.append(f'<row r="1">{header_cells}</row>')
    for row_idx, row in enumerate(rows, start=2):
        cells = "".join(cell_xml(row_idx, idx, row.get(header, "")) for idx, header in enumerate(headers, start=1))
        sheet_rows.append(f'<row r="{row_idx}">{cells}</row>')
    max_col = excel_col_name(len(headers))
    dimension = f'A1:{max_col}{len(rows) + 1}'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension}"/>'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        f'<autoFilter ref="{dimension}"/>'
        '</worksheet>'
    )


def write_xlsx(path: Path, sheets: list[tuple[str, list[dict[str, object]]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook_sheets = []
    workbook_rels = []
    content_overrides = [
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]

    for idx, (sheet_name, _rows) in enumerate(sheets, start=1):
        safe_name = escape(sheet_name[:31])
        workbook_sheets.append(f'<sheet name="{safe_name}" sheetId="{idx}" r:id="rId{idx}"/>')
        workbook_rels.append(
            f'<Relationship Id="rId{idx}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{idx}.xml"/>'
        )
        content_overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{idx}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )

    workbook_rels.append(
        f'<Relationship Id="rId{len(sheets) + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'{"".join(content_overrides)}'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(workbook_sheets)}</sheets>'
        '</workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(workbook_rels)}'
        '</Relationships>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/styles.xml", styles)
        for idx, (_sheet_name, rows) in enumerate(sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", sheet_xml(rows))


def build(db_path: Path, out_dir: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        if not table_exists(conn, "gp_house"):
            raise RuntimeError(f"Missing gp_house table in {db_path}")

        periods = fetch_periods(conn)
        latest_period_id, _latest_label, _latest_date = fetch_latest_period(conn)
        candidates = load_candidates(conn, periods, latest_period_id)
        add_count_stats(conn, candidates, latest_period_id)
        collect_variants(conn, candidates, periods)
        alias_groups = build_alias_groups(candidates)
        mark_alias_reviews(candidates, alias_groups)

        created_at = now_iso()
        master = candidate_rows(candidates, created_at)
        variants = variant_rows(candidates, created_at)
        aliases = alias_rows(candidates, alias_groups, created_at)

        ensure_output_tables(conn)
        insert_rows(conn, "gp_master_candidate", master)
        insert_rows(conn, "gp_name_variant", variants)
        insert_rows(conn, "gp_alias_review_candidate", aliases)
        conn.commit()

        write_csv(out_dir / "gp_master_candidates.csv", master)
        write_csv(out_dir / "gp_name_variants.csv", variants)
        write_csv(out_dir / "gp_alias_review_candidates.csv", aliases)
        write_xlsx(
            out_dir / "gp_master_candidates.xlsx",
            [
                ("gp_master", master),
                ("name_variants", variants),
                ("alias_review", aliases),
            ],
        )

        return {
            "gp_master_candidate": len(master),
            "gp_name_variant": len(variants),
            "gp_alias_review_candidate": len(aliases),
            "needs_review": sum(1 for row in master if row["needs_review"]),
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build GP master candidate review tables")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    counts = build(args.db, args.out)
    for key, value in counts.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
