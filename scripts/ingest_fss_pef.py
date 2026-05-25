#!/usr/bin/env python
"""Import FSS PEF quarterly status workbooks into SQLite.

The script intentionally uses only the Python standard library so it can run in
this project without installing Excel dependencies. It supports .xlsx files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_SCHEMA = REPO_ROOT / "schema" / "fss_pef.sql"
DEFAULT_REGISTRY = REPO_ROOT / "data" / "source_registry_fss_pef.csv"

NS_MAIN = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}


@dataclass(frozen=True)
class RegistryEntry:
    source_id: str
    as_of_date: str
    period_label: str
    regime: str
    title: str
    source_url: str
    local_file: Path
    notes: str


@dataclass(frozen=True)
class SheetRows:
    name: str
    rows: list[list[str]]


@dataclass(frozen=True)
class ParsedRow:
    sheet_name: str
    sheet_role: str
    row_number: int
    raw: dict[str, str]
    fund_name: str
    gp_name: str
    gp_names: list[str]
    fund_type: str
    status: str
    established_date: str
    liquidation_date: str
    commitment_raw: str
    commitment_krw_mn: float | None
    paid_in_raw: str
    paid_in_krw_mn: float | None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_name(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"\s+", "", value)
    value = value.replace("㈜", "주식회사")
    value = value.replace("(주)", "주식회사")
    value = value.replace("（주）", "주식회사")
    return value.lower()


def normalize_fund_name(value: str) -> str:
    normalized = normalize_name(value)
    suffixes = [
        "사모투자전문회사",
        "사모투자합자회사",
        "사모투자회사",
        "사모집합투자기구",
        "기관전용사모집합투자기구",
        "기관전용사모펀드",
    ]
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                changed = True
    return normalized


def normalize_header(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"\s+", "", value)
    value = value.replace("(", "").replace(")", "")
    value = value.replace("[", "").replace("]", "")
    return value


def period_id(period_label: str, regime: str) -> str:
    suffix = "pef" if regime == "management_participation" else "inst"
    return f"{period_label}_{suffix}"


def quarter_from_date(date_text: str) -> tuple[int, int]:
    year, month, _day = [int(part) for part in date_text.split("-")]
    quarter = ((month - 1) // 3) + 1
    return year, quarter


def rel_target_to_path(target: str) -> str:
    target = target.replace("\\", "/")
    if target.startswith("/"):
        target = target.lstrip("/")
    if not target.startswith("xl/"):
        target = f"xl/{target}"
    return target


def col_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    idx = 0
    for char in letters:
        idx = idx * 26 + (ord(char) - 64)
    return max(idx, 1)


def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    strings: list[str] = []
    for item in root.findall("x:si", NS_MAIN):
        parts = [node.text or "" for node in item.findall(".//x:t", NS_MAIN)]
        strings.append("".join(parts))
    return strings


def workbook_sheet_paths(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel_target_to_path(rel.attrib["Target"])
        for rel in rels.findall("r:Relationship", NS_REL)
    }
    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall(".//x:sheet", NS_MAIN):
        name = sheet.attrib.get("name", "")
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if rel_id and rel_id in rel_map:
            sheets.append((name, rel_map[rel_id]))
    return sheets


def read_cell(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        parts = [node.text or "" for node in cell.findall(".//x:t", NS_MAIN)]
        return "".join(parts).strip()

    value_node = cell.find("x:v", NS_MAIN)
    if value_node is None or value_node.text is None:
        return ""

    value = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(value)].strip()
        except (ValueError, IndexError):
            return ""
    return value.strip()


def read_sheet_rows(zf: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]) -> list[list[str]]:
    root = ET.fromstring(zf.read(sheet_path))
    rows: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", NS_MAIN):
        values_by_col: dict[int, str] = {}
        max_col = 0
        for cell in row.findall("x:c", NS_MAIN):
            cell_ref = cell.attrib.get("r", "A1")
            idx = col_index(cell_ref)
            max_col = max(max_col, idx)
            values_by_col[idx] = read_cell(cell, shared_strings)
        if max_col == 0:
            rows.append([])
        else:
            rows.append([values_by_col.get(i, "") for i in range(1, max_col + 1)])
    return rows


def read_xlsx(path: Path) -> list[SheetRows]:
    with zipfile.ZipFile(path) as zf:
        shared_strings = read_shared_strings(zf)
        sheets = workbook_sheet_paths(zf)
        return [
            SheetRows(name=sheet_name, rows=read_sheet_rows(zf, sheet_path, shared_strings))
            for sheet_name, sheet_path in sheets
        ]


def compact_row(row: Iterable[str]) -> str:
    return " ".join(str(cell).strip() for cell in row if str(cell).strip())


def is_header_row(row: list[str]) -> bool:
    joined = normalize_header(compact_row(row))
    if not joined:
        return False
    has_fund = any(token in joined for token in ["펀드", "PEF", "사모집합투자기구", "사모투자", "회사명"])
    has_gp = any(token in joined for token in ["업무집행", "무한책임", "GP", "운용사"])
    has_amount = any(token in joined for token in ["약정", "이행", "출자"])
    return has_fund and (has_gp or has_amount)


def sheet_role(sheet_name: str, header: list[str]) -> str:
    text = normalize_header(sheet_name)
    if any(token in text for token in ["해산", "청산", "소멸"]):
        return "liquidated"
    if any(token in text for token in ["신설", "신규", "설립"]):
        return "new_or_established"
    return "active_or_status"


def find_header_row(rows: list[list[str]]) -> int | None:
    for idx, row in enumerate(rows):
        if is_header_row(row):
            return idx
    return None


def classify_columns(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, header in enumerate(headers):
        h = normalize_header(header)
        if not h:
            continue
        if "순번" in h or h in {"no", "NO"}:
            continue
        if "fund_name" not in mapping and any(
            token in h for token in ["펀드명", "PEF명", "사모집합투자기구명", "사모투자합자회사명", "명칭", "회사명"]
        ):
            mapping["fund_name"] = idx
        if "gp_name" not in mapping and any(token in h for token in ["업무집행사원", "무한책임사원", "GP", "운용사"]):
            mapping["gp_name"] = idx
        if h in {"GP1", "GP"} and "gp_name" not in mapping:
            mapping["gp_name"] = idx
        if "established_date" not in mapping and any(token in h for token in ["설립일", "등록일", "결성일"]):
            mapping["established_date"] = idx
        if "liquidation_date" not in mapping and any(token in h for token in ["해산일", "청산일", "소멸일"]):
            mapping["liquidation_date"] = idx
        if "commitment" not in mapping and any(token in h for token in ["출자약정", "약정액", "약정금액"]):
            mapping["commitment"] = idx
        if "paid_in" not in mapping and any(token in h for token in ["출자이행", "이행액", "납입", "출자금"]):
            mapping["paid_in"] = idx
        if "fund_type" not in mapping and any(token in h for token in ["종류", "유형"]):
            mapping["fund_type"] = idx
        if "status" not in mapping and any(token in h for token in ["상태", "구분"]):
            mapping["status"] = idx
    return mapping


def gp_column_indexes(headers: list[str], mapping: dict[str, int]) -> list[int]:
    indexes: list[int] = []
    for idx, header in enumerate(headers):
        h = normalize_header(header).upper()
        if h == "GP" or re.fullmatch(r"GP\d+", h):
            indexes.append(idx)
    if not indexes and "gp_name" in mapping:
        gp_idx = mapping["gp_name"]
        stop_candidates = [
            idx
            for key, idx in mapping.items()
            if key != "gp_name" and idx > gp_idx
        ]
        stop = min(stop_candidates) if stop_candidates else gp_idx + 1
        indexes.extend(range(gp_idx, stop))
    return sorted(set(indexes))


def unit_multiplier_to_krw_mn(header: str, default_unit: str) -> float | None:
    text = normalize_header(header)
    if "백만원" in text:
        return 1.0
    if "억원" in text or "억" in text:
        return 100.0
    if "조원" in text or "조" in text:
        return 1_000_000.0
    if "원" in text:
        return 0.000001
    if default_unit == "eok":
        return 100.0
    if default_unit == "krw_mn":
        return 1.0
    if default_unit == "krw":
        return 0.000001
    return None


def parse_amount(raw: str, header: str, default_unit: str) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in {"-", "－", "N/A"}:
        return None
    text = text.replace(",", "").replace(" ", "")
    if re.fullmatch(r"\(?\d+(\.\d+)?\)?", text):
        negative = text.startswith("(") and text.endswith(")")
        value = float(text.strip("()"))
        multiplier = unit_multiplier_to_krw_mn(header, default_unit)
        if multiplier is None:
            return None
        return -value * multiplier if negative else value * multiplier

    total = 0.0
    matched = False
    jo = re.search(r"([\d.]+)조", text)
    eok = re.search(r"([\d.]+)억", text)
    man = re.search(r"([\d.]+)만", text)
    if jo:
        total += float(jo.group(1)) * 1_000_000.0
        matched = True
    if eok:
        total += float(eok.group(1)) * 100.0
        matched = True
    if man:
        total += float(man.group(1)) * 0.01
        matched = True
    return total if matched else None


def parse_date(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"\d+(\.\d+)?", text):
        # Excel serial date. Excel's serial 1 is 1899-12-31 with a 1900 leap-year bug.
        serial = int(float(text))
        if 20_000 <= serial <= 80_000:
            from datetime import date, timedelta

            return (date(1899, 12, 30) + timedelta(days=serial)).isoformat()
    match = re.search(r"(\d{4})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    match = re.search(r"(\d{4})[.\-/년]\s*(\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    return text


def get_value(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return str(row[idx]).strip()


def parse_workbook_rows(path: Path, default_amount_unit: str) -> list[ParsedRow]:
    parsed: list[ParsedRow] = []
    seen_sheet_signatures: set[str] = set()
    for sheet in read_xlsx(path):
        header_idx = find_header_row(sheet.rows)
        if header_idx is None:
            continue
        headers = sheet.rows[header_idx]
        mapping = classify_columns(headers)
        if "fund_name" not in mapping:
            continue
        gp_indexes = gp_column_indexes(headers, mapping)
        first_funds = []
        for row in sheet.rows[header_idx + 1 : header_idx + 21]:
            fund_name = get_value(row, mapping.get("fund_name"))
            if fund_name:
                first_funds.append(normalize_fund_name(fund_name))
        signature = sha256_text(json.dumps([headers, first_funds], ensure_ascii=False))
        if signature in seen_sheet_signatures:
            continue
        seen_sheet_signatures.add(signature)
        role = sheet_role(sheet.name, headers)
        blank_streak = 0
        for offset, row in enumerate(sheet.rows[header_idx + 1 :], start=header_idx + 2):
            if not compact_row(row):
                blank_streak += 1
                if blank_streak >= 5:
                    break
                continue
            blank_streak = 0
            if is_header_row(row):
                continue
            fund_name = get_value(row, mapping.get("fund_name"))
            if not fund_name or fund_name in {"합계", "총계", "소계"}:
                continue
            gp_names = [get_value(row, idx) for idx in gp_indexes]
            gp_names = [name for name in gp_names if name and name not in {"-", "－"}]
            gp_name = "; ".join(gp_names)
            commitment_header = headers[mapping["commitment"]] if "commitment" in mapping else ""
            paid_in_header = headers[mapping["paid_in"]] if "paid_in" in mapping else ""
            raw = {
                headers[i] if i < len(headers) and headers[i] else f"col_{i + 1}": get_value(row, i)
                for i in range(max(len(headers), len(row)))
            }
            parsed.append(
                ParsedRow(
                    sheet_name=sheet.name,
                    sheet_role=role,
                    row_number=offset,
                    raw=raw,
                    fund_name=fund_name,
                    gp_name=gp_name,
                    gp_names=gp_names,
                    fund_type=get_value(row, mapping.get("fund_type")),
                    status=get_value(row, mapping.get("status")),
                    established_date=parse_date(get_value(row, mapping.get("established_date"))),
                    liquidation_date=parse_date(get_value(row, mapping.get("liquidation_date"))),
                    commitment_raw=get_value(row, mapping.get("commitment")),
                    commitment_krw_mn=parse_amount(get_value(row, mapping.get("commitment")), commitment_header, default_amount_unit),
                    paid_in_raw=get_value(row, mapping.get("paid_in")),
                    paid_in_krw_mn=parse_amount(get_value(row, mapping.get("paid_in")), paid_in_header, default_amount_unit),
                )
            )
    return parsed


def read_registry(path: Path) -> list[RegistryEntry]:
    entries: list[RegistryEntry] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not row.get("source_id"):
                continue
            local_file = Path(row.get("local_file", ""))
            if not local_file.is_absolute():
                local_file = REPO_ROOT / local_file
            entries.append(
                RegistryEntry(
                    source_id=row["source_id"].strip(),
                    as_of_date=row["as_of_date"].strip(),
                    period_label=row["period_label"].strip(),
                    regime=row["regime"].strip(),
                    title=row["title"].strip(),
                    source_url=row.get("source_url", "").strip(),
                    local_file=local_file,
                    notes=row.get("notes", "").strip(),
                )
            )
    return entries


def connect_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path, schema_path: Path) -> None:
    conn = connect_db(db_path)
    try:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def upsert_period(conn: sqlite3.Connection, entry: RegistryEntry) -> str:
    year, quarter = quarter_from_date(entry.as_of_date)
    pid = period_id(entry.period_label, entry.regime)
    conn.execute(
        """
        INSERT INTO reporting_period(period_id, period_label, as_of_date, year, quarter, regime)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(period_id) DO UPDATE SET
            period_label=excluded.period_label,
            as_of_date=excluded.as_of_date,
            year=excluded.year,
            quarter=excluded.quarter,
            regime=excluded.regime
        """,
        (pid, entry.period_label, entry.as_of_date, year, quarter, entry.regime),
    )
    return pid


def upsert_source(conn: sqlite3.Connection, entry: RegistryEntry, file_sha: str) -> None:
    conn.execute(
        """
        INSERT INTO source_document(
            source_id, title, regime, period_label, as_of_date, source_url,
            local_path, sha256, parsed_at, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            title=excluded.title,
            regime=excluded.regime,
            period_label=excluded.period_label,
            as_of_date=excluded.as_of_date,
            source_url=excluded.source_url,
            local_path=excluded.local_path,
            sha256=excluded.sha256,
            parsed_at=excluded.parsed_at,
            notes=excluded.notes
        """,
        (
            entry.source_id,
            entry.title,
            entry.regime,
            entry.period_label,
            entry.as_of_date,
            entry.source_url,
            str(entry.local_file.relative_to(REPO_ROOT)) if entry.local_file.is_relative_to(REPO_ROOT) else str(entry.local_file),
            file_sha,
            now_iso(),
            entry.notes,
        ),
    )


def upsert_gp(conn: sqlite3.Connection, gp_name: str, period_id_value: str) -> int | None:
    if not gp_name:
        return None
    norm = normalize_name(gp_name)
    conn.execute(
        """
        INSERT INTO gp_house(gp_name, gp_name_norm, first_seen_period_id, last_seen_period_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(gp_name_norm) DO UPDATE SET
            gp_name=excluded.gp_name,
            last_seen_period_id=excluded.last_seen_period_id,
            updated_at=CURRENT_TIMESTAMP
        """,
        (gp_name, norm, period_id_value, period_id_value),
    )
    return int(conn.execute("SELECT gp_id FROM gp_house WHERE gp_name_norm = ?", (norm,)).fetchone()[0])


def upsert_fund(conn: sqlite3.Connection, row: ParsedRow, regime: str) -> int:
    norm = normalize_fund_name(row.fund_name)
    conn.execute(
        """
        INSERT INTO pef_fund(fund_name, fund_name_norm, regime_first_seen, fund_type, established_date, liquidation_date)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(fund_name_norm) DO UPDATE SET
            fund_name=excluded.fund_name,
            fund_type=COALESCE(NULLIF(excluded.fund_type, ''), pef_fund.fund_type),
            established_date=COALESCE(NULLIF(pef_fund.established_date, ''), NULLIF(excluded.established_date, '')),
            liquidation_date=COALESCE(NULLIF(excluded.liquidation_date, ''), pef_fund.liquidation_date),
            updated_at=CURRENT_TIMESTAMP
        """,
        (row.fund_name, norm, regime, row.fund_type, row.established_date, row.liquidation_date),
    )
    return int(conn.execute("SELECT fund_id FROM pef_fund WHERE fund_name_norm = ?", (norm,)).fetchone()[0])


def upsert_affiliation(conn: sqlite3.Connection, fund_id: int, gp_id: int | None, period_id_value: str) -> None:
    if gp_id is None:
        return
    conn.execute(
        """
        INSERT INTO fund_gp_affiliation(fund_id, gp_id, first_seen_period_id, last_seen_period_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(fund_id, gp_id, role) DO UPDATE SET
            last_seen_period_id=excluded.last_seen_period_id
        """,
        (fund_id, gp_id, period_id_value, period_id_value),
    )


def insert_parsed_row(
    conn: sqlite3.Connection,
    entry: RegistryEntry,
    period_id_value: str,
    row: ParsedRow,
) -> None:
    raw_json = json.dumps(row.raw, ensure_ascii=False, sort_keys=True)
    row_hash = sha256_text(raw_json)
    fund_id = upsert_fund(conn, row, entry.regime)
    gp_ids = [upsert_gp(conn, gp_name, period_id_value) for gp_name in row.gp_names]
    gp_ids = [gp_id for gp_id in gp_ids if gp_id is not None]
    gp_id = gp_ids[0] if gp_ids else None
    for affiliated_gp_id in gp_ids:
        upsert_affiliation(conn, fund_id, affiliated_gp_id, period_id_value)

    conn.execute(
        """
        INSERT INTO source_row(source_id, sheet_name, row_number, raw_row_json, row_hash)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_id, sheet_name, row_number) DO UPDATE SET
            raw_row_json=excluded.raw_row_json,
            row_hash=excluded.row_hash
        """,
        (entry.source_id, row.sheet_name, row.row_number, raw_json, row_hash),
    )
    conn.execute(
        """
        INSERT INTO fund_period_snapshot(
            fund_id, period_id, source_id, gp_id, sheet_name, row_number, sheet_role,
            fund_name_raw, gp_name_raw, fund_type_raw, status_raw,
            established_date_raw, liquidation_date_raw,
            commitment_amount_raw, commitment_amount_krw_mn,
            paid_in_amount_raw, paid_in_amount_krw_mn,
            raw_row_json, row_hash
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, sheet_name, row_number) DO UPDATE SET
            fund_id=excluded.fund_id,
            period_id=excluded.period_id,
            gp_id=excluded.gp_id,
            sheet_role=excluded.sheet_role,
            fund_name_raw=excluded.fund_name_raw,
            gp_name_raw=excluded.gp_name_raw,
            fund_type_raw=excluded.fund_type_raw,
            status_raw=excluded.status_raw,
            established_date_raw=excluded.established_date_raw,
            liquidation_date_raw=excluded.liquidation_date_raw,
            commitment_amount_raw=excluded.commitment_amount_raw,
            commitment_amount_krw_mn=excluded.commitment_amount_krw_mn,
            paid_in_amount_raw=excluded.paid_in_amount_raw,
            paid_in_amount_krw_mn=excluded.paid_in_amount_krw_mn,
            raw_row_json=excluded.raw_row_json,
            row_hash=excluded.row_hash
        """,
        (
            fund_id,
            period_id_value,
            entry.source_id,
            gp_id,
            row.sheet_name,
            row.row_number,
            row.sheet_role,
            row.fund_name,
            row.gp_name,
            row.fund_type,
            row.status,
            row.established_date,
            row.liquidation_date,
            row.commitment_raw,
            row.commitment_krw_mn,
            row.paid_in_raw,
            row.paid_in_krw_mn,
            raw_json,
            row_hash,
        ),
    )

    if row.sheet_role == "new_or_established" or row.established_date:
        insert_event(
            conn,
            fund_id,
            gp_id,
            "established",
            row.established_date or entry.as_of_date,
            period_id_value,
            entry.source_id,
            "FSS row indicates establishment/new fund",
        )
    if row.sheet_role == "liquidated" or row.liquidation_date:
        insert_event(
            conn,
            fund_id,
            gp_id,
            "liquidated",
            row.liquidation_date or entry.as_of_date,
            period_id_value,
            entry.source_id,
            "FSS row indicates liquidation/dissolution",
        )


def insert_event(
    conn: sqlite3.Connection,
    fund_id: int,
    gp_id: int | None,
    event_type: str,
    event_date: str,
    period_id_value: str,
    source_id: str | None,
    basis: str,
) -> None:
    existing = conn.execute(
        """
        SELECT 1
        FROM fund_event
        WHERE fund_id = ?
          AND event_type = ?
          AND COALESCE(event_date, '') = COALESCE(?, '')
        LIMIT 1
        """,
        (fund_id, event_type, event_date),
    ).fetchone()
    if existing:
        return
    conn.execute(
        """
        INSERT OR IGNORE INTO fund_event(
            fund_id, gp_id, event_type, event_date, period_id, source_id, confidence, basis
        )
        VALUES (?, ?, ?, ?, ?, ?, 'A', ?)
        """,
        (fund_id, gp_id, event_type, event_date, period_id_value, source_id, basis),
    )


def ingest_registry(db_path: Path, registry_path: Path, default_amount_unit: str) -> None:
    conn = connect_db(db_path)
    total_files = 0
    total_rows = 0
    try:
        for entry in read_registry(registry_path):
            if not entry.local_file.exists():
                print(f"SKIP missing raw file: {entry.local_file}")
                continue
            workbook_path = entry.local_file
            if entry.local_file.suffix.lower() == ".xls":
                converted_path = entry.local_file.with_suffix(".xlsx")
                if converted_path.exists():
                    workbook_path = converted_path
                else:
                    print(f"SKIP unsupported .xls without converted .xlsx: {entry.local_file}")
                    continue
            if workbook_path.suffix.lower() != ".xlsx":
                print(f"SKIP unsupported file type: {entry.local_file}")
                continue
            file_sha = sha256_file(entry.local_file)
            pid = upsert_period(conn, entry)
            upsert_source(conn, entry, file_sha)
            parsed_rows = parse_workbook_rows(workbook_path, default_amount_unit)
            for row in parsed_rows:
                insert_parsed_row(conn, entry, pid, row)
            conn.commit()
            total_files += 1
            total_rows += len(parsed_rows)
            parsed_note = f" parsed={workbook_path.name}" if workbook_path != entry.local_file else ""
            print(f"INGESTED {entry.source_id}: rows={len(parsed_rows)} file={entry.local_file.name}{parsed_note}")
        derive_first_seen_events(conn)
        dedupe_events(conn)
        conn.commit()
    finally:
        conn.close()
    print(f"DONE files={total_files} rows={total_rows} db={db_path}")


def derive_first_seen_events(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT
            fps.fund_id,
            fps.gp_id,
            fps.period_id,
            fps.source_id,
            rp.as_of_date
        FROM fund_period_snapshot fps
        JOIN reporting_period rp ON rp.period_id = fps.period_id
        JOIN (
            SELECT fund_id, MIN(rp2.as_of_date) AS first_as_of_date
            FROM fund_period_snapshot fps2
            JOIN reporting_period rp2 ON rp2.period_id = fps2.period_id
            GROUP BY fund_id
        ) first_seen
          ON first_seen.fund_id = fps.fund_id
         AND first_seen.first_as_of_date = rp.as_of_date
        """
    ).fetchall()
    for fund_id, gp_id, pid, source_id, as_of_date in rows:
        insert_event(
            conn,
            int(fund_id),
            int(gp_id) if gp_id is not None else None,
            "first_seen",
            as_of_date,
            pid,
            source_id,
            "First appearance in imported FSS quarterly status series",
        )


def dedupe_events(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        DELETE FROM fund_event
        WHERE event_id NOT IN (
            SELECT MIN(event_id)
            FROM fund_event
            GROUP BY fund_id, event_type, COALESCE(event_date, '')
        )
        """
    )


def inspect_workbook(path: Path, default_amount_unit: str) -> None:
    print(f"file={path}")
    sheets = read_xlsx(path)
    print(f"sheets={len(sheets)}")
    for sheet in sheets:
        header_idx = find_header_row(sheet.rows)
        print(f"- sheet={sheet.name!r} rows={len(sheet.rows)} header_row={None if header_idx is None else header_idx + 1}")
        if header_idx is not None:
            headers = sheet.rows[header_idx]
            print(f"  role={sheet_role(sheet.name, headers)}")
            print(f"  headers={headers}")
            print(f"  mapping={classify_columns(headers)}")
    parsed = parse_workbook_rows(path, default_amount_unit)
    print(f"parsed_rows={len(parsed)}")
    for row in parsed[:5]:
        print(
            "  sample="
            + json.dumps(
                {
                    "sheet": row.sheet_name,
                    "row": row.row_number,
                    "fund": row.fund_name,
                    "gp": row.gp_name,
                    "gp_names": row.gp_names,
                    "commitment_raw": row.commitment_raw,
                    "commitment_krw_mn": row.commitment_krw_mn,
                },
                ensure_ascii=False,
            )
        )


def export_summary(db_path: Path) -> None:
    conn = connect_db(db_path)
    try:
        for label, query in [
            ("source_document", "SELECT COUNT(*) FROM source_document"),
            ("reporting_period", "SELECT COUNT(*) FROM reporting_period"),
            ("gp_house", "SELECT COUNT(*) FROM gp_house"),
            ("pef_fund", "SELECT COUNT(*) FROM pef_fund"),
            ("fund_period_snapshot", "SELECT COUNT(*) FROM fund_period_snapshot"),
            ("fund_event", "SELECT COUNT(*) FROM fund_event"),
        ]:
            print(f"{label}={conn.execute(query).fetchone()[0]}")
        print("top_gp_commitment:")
        for row in conn.execute(
            """
            SELECT period_label, gp_name, ROUND(commitment_amount_krw_mn / 1000000.0, 3) AS commitment_trn_krw
            FROM v_gp_period_commitment
            WHERE gp_name IS NOT NULL
            ORDER BY as_of_date DESC, commitment_amount_krw_mn DESC
            LIMIT 20
            """
        ):
            print(f"  {row[0]}\t{row[1]}\t{row[2]}조원")
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import FSS PEF quarterly status files")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--default-amount-unit",
        choices=["eok", "krw_mn", "krw", "unknown"],
        default="eok",
        help="Unit for numeric amount cells when the workbook header does not say the unit.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Create or update SQLite tables")
    sub.add_parser("rebuild", help="Delete and rebuild the SQLite DB from registered raw files")
    inspect_cmd = sub.add_parser("inspect", help="Inspect one .xlsx workbook")
    inspect_cmd.add_argument("xlsx", type=Path)
    sub.add_parser("ingest", help="Import all existing local files in the source registry")
    sub.add_parser("summary", help="Print DB row counts and GP aggregate sample")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init-db":
        init_db(args.db, args.schema)
        print(f"initialized db={args.db}")
        return 0
    if args.command == "rebuild":
        if args.db.exists():
            args.db.unlink()
        init_db(args.db, args.schema)
        ingest_registry(args.db, args.registry, args.default_amount_unit)
        return 0
    if args.command == "inspect":
        inspect_workbook(args.xlsx, args.default_amount_unit)
        return 0
    if args.command == "ingest":
        init_db(args.db, args.schema)
        ingest_registry(args.db, args.registry, args.default_amount_unit)
        return 0
    if args.command == "summary":
        export_summary(args.db)
        return 0
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
