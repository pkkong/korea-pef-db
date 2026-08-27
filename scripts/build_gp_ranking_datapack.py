#!/usr/bin/env python3
"""Build the GP ranking workbook from the public GP database.

The workbook uses the same normalized database and cumulative ranking as the
GP service. Each GP named for a fund in the imported FSS history receives the
fund's full maximum disclosed commitment. Joint-GP amounts are therefore
intentionally duplicated across the relevant GP rows.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_fss_statistics_ready import check_fss_statistics
from scripts.ingest_fss_pef import read_xlsx


DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_REGISTRY = REPO_ROOT / "data" / "source_registry_fss_pef.csv"
DEFAULT_ALIAS_RULES = REPO_ROOT / "data" / "gp_alias_merge_rules.csv"
DEFAULT_OUTPUT = REPO_ROOT / "exports" / "gp_ranking_datapack_2025YE.xlsx"
RANKING_TITLE = "2025년 말 기준 기관전용 PEF 누적 운용자산 순위 (금감원 공시 총약정액 기준)"
KRW_100MN_PER_TRILLION = 10_000.0


@dataclass(frozen=True)
class Cell:
    value: object = ""
    style: str = "body"
    formula: str | None = None
    cached_value: object | None = None


@dataclass
class Sheet:
    name: str
    rows: list[list[Cell]]
    widths: list[float] = field(default_factory=list)
    freeze_rows: int = 1
    auto_filter: str = ""
    merges: list[str] = field(default_factory=list)


def text(value: object, style: str = "body") -> Cell:
    return Cell(value="" if value is None else str(value), style=style)


def number(value: object, style: str = "number") -> Cell:
    return Cell(value=value, style=style)


def formula(value: str, cached_value: object, style: str) -> Cell:
    return Cell(style=style, formula=value.lstrip("="), cached_value=cached_value)


def to_krw_100mn(value_trn_krw: object) -> float:
    return float(value_trn_krw or 0) * KRW_100MN_PER_TRILLION


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: str(value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def excel_column(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def clean_xml(value: object) -> str:
    return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", "" if value is None else str(value))


STYLE_INDEX = {
    "body": 0,
    "title": 1,
    "subtitle": 2,
    "section": 3,
    "header": 4,
    "wrap": 5,
    "number": 6,
    "amount_100mn": 7,
    "amount_tn": 8,
    "pct": 9,
    "formula_number": 10,
    "formula_amount_100mn": 11,
    "formula_amount_tn": 12,
    "formula_pct": 13,
    "pass": 14,
    "warning": 15,
    "link": 16,
}


def cell_xml(row_index: int, column_index: int, cell: Cell) -> str:
    ref = f"{excel_column(column_index)}{row_index}"
    style = STYLE_INDEX[cell.style]
    attrs = f' r="{ref}" s="{style}"'
    if cell.formula is not None:
        cached = cell.cached_value
        formula_text = escape(clean_xml(cell.formula))
        if isinstance(cached, bool):
            return f'<c{attrs} t="b"><f>{formula_text}</f><v>{int(cached)}</v></c>'
        if isinstance(cached, (int, float)) and not isinstance(cached, bool):
            return f'<c{attrs}><f>{formula_text}</f><v>{cached}</v></c>'
        return f'<c{attrs} t="str"><f>{formula_text}</f><v>{escape(clean_xml(cached))}</v></c>'

    value = cell.value
    if value in (None, ""):
        return f'<c{attrs}/>'
    if isinstance(value, bool):
        return f'<c{attrs} t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c{attrs}><v>{value}</v></c>'
    rendered = escape(clean_xml(value))
    preserve = ' xml:space="preserve"' if rendered[:1].isspace() or rendered[-1:].isspace() else ""
    return f'<c{attrs} t="inlineStr"><is><t{preserve}>{rendered}</t></is></c>'


def style_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="5">'
        '<numFmt numFmtId="164" formatCode="#,##0"/>'
        '<numFmt numFmtId="165" formatCode="#,##0.0"/>'
        '<numFmt numFmtId="166" formatCode="0.000000"/>'
        '<numFmt numFmtId="167" formatCode="0.00%"/>'
        '<numFmt numFmtId="168" formatCode="#,##0.00"/>'
        '</numFmts>'
        '<fonts count="5">'
        '<font><sz val="10"/><name val="Apple SD Gothic Neo"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="16"/><name val="Apple SD Gothic Neo"/></font>'
        '<font><b/><color rgb="FF334155"/><sz val="11"/><name val="Apple SD Gothic Neo"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Apple SD Gothic Neo"/></font>'
        '<font><u/><color rgb="FF0563C1"/><sz val="10"/><name val="Apple SD Gothic Neo"/></font>'
        '</fonts>'
        '<fills count="7">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF0F172A"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFE2E8F0"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF1E3A5F"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFDCFCE7"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFEF3C7"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="2">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border><left style="thin"><color rgb="FFD1D5DB"/></left><right style="thin"><color rgb="FFD1D5DB"/></right><top style="thin"><color rgb="FFD1D5DB"/></top><bottom style="thin"><color rgb="FFD1D5DB"/></bottom><diagonal/></border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="17">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
        '<xf numFmtId="0" fontId="3" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>'
        '<xf numFmtId="0" fontId="3" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
        '<xf numFmtId="168" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
        '<xf numFmtId="166" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
        '<xf numFmtId="167" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
        '<xf numFmtId="164" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1"/>'
        '<xf numFmtId="168" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1"/>'
        '<xf numFmtId="166" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1"/>'
        '<xf numFmtId="167" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="5" borderId="1" xfId="0" applyFill="1" applyBorder="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="6" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
        '<xf numFmtId="0" fontId="4" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
        '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def sheet_xml(sheet: Sheet) -> str:
    row_xml: list[str] = []
    max_columns = max((len(row) for row in sheet.rows), default=1)
    for row_index, row in enumerate(sheet.rows, start=1):
        cells = "".join(cell_xml(row_index, column_index, cell) for column_index, cell in enumerate(row, start=1))
        row_xml.append(f'<row r="{row_index}">{cells}</row>')
    max_column = excel_column(max_columns)
    dimension = f"A1:{max_column}{max(len(sheet.rows), 1)}"
    widths = sheet.widths or [18.0] * max_columns
    columns = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(widths[:max_columns], start=1)
    )
    pane = ""
    if sheet.freeze_rows:
        pane = (
            f'<pane ySplit="{sheet.freeze_rows}" topLeftCell="A{sheet.freeze_rows + 1}" '
            'activePane="bottomLeft" state="frozen"/>'
        )
    merges = "".join(f'<mergeCell ref="{merge}"/>' for merge in sheet.merges)
    merge_xml = f'<mergeCells count="{len(sheet.merges)}">{merges}</mergeCells>' if sheet.merges else ""
    filter_xml = f'<autoFilter ref="{sheet.auto_filter}"/>' if sheet.auto_filter else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>'
        f'<dimension ref="{dimension}"/><sheetViews><sheetView workbookViewId="0">{pane}</sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f'<cols>{columns}</cols><sheetData>{"".join(row_xml)}</sheetData>{merge_xml}{filter_xml}'
        '<pageMargins left="0.25" right="0.25" top="0.4" bottom="0.4" header="0.15" footer="0.15"/>'
        '<pageSetup orientation="landscape" paperSize="9" fitToWidth="1" fitToHeight="0"/>'
        '</worksheet>'
    )


def write_xlsx(path: Path, sheets: list[Sheet]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(sheets) > 255:
        raise ValueError("Excel workbook cannot contain more than 255 sheets")
    if len({sheet.name for sheet in sheets}) != len(sheets):
        raise ValueError("Excel sheet names must be unique")

    content_overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    workbook_sheets: list[str] = []
    workbook_relationships: list[str] = []
    for index, sheet in enumerate(sheets, start=1):
        if len(sheet.name) > 31:
            raise ValueError(f"Excel sheet name is too long: {sheet.name}")
        workbook_sheets.append(f'<sheet name="{escape(sheet.name)}" sheetId="{index}" r:id="rId{index}"/>')
        workbook_relationships.append(
            f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        )
        content_overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    style_relationship_id = len(sheets) + 1
    workbook_relationships.append(
        f'<Relationship Id="rId{style_relationship_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'{"".join(content_overrides)}</Types>'
    )
    root_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        '</Relationships>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(workbook_sheets)}</sheets><calcPr calcId="191029" calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/>'
        '</workbook>'
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>KPEF Brief</dc:creator>'
        '<dc:title>GP Ranking Data Pack 2025YE</dc:title><dc:subject>FSS PEF commitment ranking audit pack</dc:subject></cp:coreProperties>'
    )
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>KPEF Brief</Application></Properties>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(workbook_relationships)}</Relationships>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_relationships)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/styles.xml", style_xml())
        archive.writestr("docProps/core.xml", core)
        archive.writestr("docProps/app.xml", app)
        for index, sheet in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(sheet))


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ? LIMIT 1", (table_name,)
    ).fetchone() is not None


def fetch_dicts(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
    cursor = conn.execute(query, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _require_table(conn: sqlite3.Connection, table_name: str) -> None:
    if not table_exists(conn, table_name):
        raise RuntimeError(
            f"Missing {table_name}. Rebuild the normalized GP analytics before creating the data pack."
        )


def read_ranking_inputs(
    db_path: Path, registry_path: Path, alias_rules_path: Path, period_label: str
) -> dict[str, object]:
    check_fss_statistics(
        db_path=db_path,
        registry_path=registry_path,
        expected_latest_period=period_label,
    )
    registry_rows = read_csv(registry_path)
    aliases = read_csv(alias_rules_path)
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        for table_name in (
            "analytics_gp_cumulative_fund_credit",
            "analytics_gp_cumulative_ranking",
            "analytics_gp_cumulative_multi_gp_detail",
            "analytics_gp_period_aum",
            "gp_profile",
        ):
            _require_table(conn, table_name)
        source_rows = fetch_dicts(
            conn,
            """
            SELECT rp.period_id, rp.period_label, rp.as_of_date, sd.source_id, sd.sha256, sd.title, sd.source_url, sd.local_path
            FROM reporting_period rp
            JOIN source_document sd ON sd.period_label = rp.period_label AND sd.as_of_date = rp.as_of_date
            WHERE rp.period_label = ?
            ORDER BY rp.as_of_date DESC
            LIMIT 1
            """,
            (period_label,),
        )
        if not source_rows:
            raise RuntimeError(f"No imported FSS source exists for {period_label}")
        source = source_rows[0]
        fund_credit = fetch_dicts(
            conn,
            """
            SELECT * FROM analytics_gp_cumulative_fund_credit
            ORDER BY credited_gp_name, fund_name, fund_id
            """,
        )
        cumulative_ranking = fetch_dicts(
            conn,
            """
            SELECT rank, gp_id, gp_name, cumulative_fund_count,
                   cumulative_commitment_proxy_trn_krw, active_fund_count_latest,
                   market_share_pct, as_of_period, basis
            FROM analytics_gp_cumulative_ranking
            ORDER BY rank
            """,
        )
        profile_snapshot = fetch_dicts(
            conn,
            """
            SELECT CAST(cumulative_primary_rank AS INTEGER) AS rank, source_gp_id AS gp_id,
                   standard_gp_name AS gp_name,
                   cumulative_primary_fund_count AS cumulative_fund_count,
                   ROUND(cumulative_primary_commitment_proxy_krw_100mn / 10000.0, 6)
                       AS cumulative_commitment_proxy_trn_krw,
                   cumulative_primary_active_fund_count_latest AS active_fund_count_latest
            FROM gp_profile
            WHERE CAST(cumulative_primary_rank AS INTEGER) > 0
            ORDER BY CAST(cumulative_primary_rank AS INTEGER)
            """,
        )
        if len(profile_snapshot) != len(cumulative_ranking):
            raise RuntimeError("GP profile snapshot count differs from normalized cumulative ranking")
        for database_row, analytics_row in zip(profile_snapshot, cumulative_ranking):
            fields = ("rank", "gp_id", "cumulative_fund_count", "active_fund_count_latest")
            if any(int(database_row[field]) != int(analytics_row[field]) for field in fields):
                raise RuntimeError(f"GP profile snapshot differs from cumulative analytics: {database_row} != {analytics_row}")
            if abs(
                float(database_row["cumulative_commitment_proxy_trn_krw"])
                - float(analytics_row["cumulative_commitment_proxy_trn_krw"])
            ) > 0.000001:
                raise RuntimeError(f"GP profile amount differs from cumulative analytics: {database_row} != {analytics_row}")
        period_summary = fetch_dicts(
            conn,
            """
            SELECT rp.period_label, rp.as_of_date, COUNT(DISTINCT fps.fund_id) AS active_fund_count,
                   COUNT(DISTINCT fps.gp_id) AS primary_gp_count,
                   ROUND(SUM(fps.commitment_amount_krw_mn) / 1000000.0, 6) AS commitment_trn_krw
            FROM reporting_period rp
            JOIN fund_period_snapshot fps ON fps.period_id = rp.period_id
            GROUP BY rp.period_id
            ORDER BY rp.as_of_date
            """,
        )
        period_ranking = fetch_dicts(
            conn,
            """
            SELECT period_label, as_of_date, gp_id, gp_name, active_fund_count,
                   commitment_aum_proxy_trn_krw, paid_in_trn_krw
            FROM analytics_gp_period_aum
            ORDER BY as_of_date, commitment_aum_proxy_trn_krw DESC, gp_name
            """,
        )
        multi_gp_detail = fetch_dicts(
            conn,
            """
            SELECT * FROM analytics_gp_cumulative_multi_gp_detail
            ORDER BY max_commitment_trn_krw DESC, fund_name, credited_gp_name
            """,
        )
    finally:
        conn.close()
    latest_registry = next((row for row in registry_rows if row["source_id"] == source["source_id"]), None)
    if latest_registry is None:
        raise RuntimeError(f"Source registry has no row for {source['source_id']}")
    return {
        "source": source,
        "latest_registry": latest_registry,
        "registry": registry_rows,
        "aliases": aliases,
        "fund_credit": fund_credit,
        "cumulative_ranking": cumulative_ranking,
        "profile_snapshot": profile_snapshot,
        "period_summary": period_summary,
        "period_ranking": period_ranking,
        "multi_gp_detail": multi_gp_detail,
        "total_cumulative_commitment_trn_krw": sum(
            float(row["max_commitment_trn_krw"] or 0) for row in fund_credit
        ),
    }


def build_raw_sheets(registry_rows: list[dict[str, str]], raw_history: str) -> tuple[list[Sheet], list[dict[str, object]]]:
    selected = registry_rows if raw_history == "all" else [registry_rows[-1]]
    sheets: list[Sheet] = []
    index_rows: list[dict[str, object]] = []
    for source_row in selected:
        period = source_row["period_label"]
        sheet_name = f"Raw {period}"
        raw_path = REPO_ROOT / source_row["local_file"]
        if raw_path.suffix.lower() != ".xlsx":
            note_rows = [
                [text(f"{period} FSS 원본 (구형 .xls)", "title"), text(""), text("")],
                [text("원본 파일"), text(source_row["original_file_name"], "wrap"), text("")],
                [text("보존 경로"), text(source_row["local_file"], "link"), text("")],
                [text("SHA-256"), text(sha256_file(raw_path), "wrap"), text("")],
                [text("상태"), text("표준 라이브러리 파서는 .xls를 행 단위로 읽지 않는다. 원본 파일은 변경 없이 보존된다.", "warning"), text("")],
            ]
            sheets.append(Sheet(name=sheet_name, rows=note_rows, widths=[22, 105, 4], freeze_rows=0, merges=["A1:C1"]))
            index_rows.append(
                {
                    "source_id": source_row["source_id"],
                    "period": period,
                    "raw_sheet": sheet_name,
                    "source_worksheets": "N/A (.xls)",
                    "raw_rows": "N/A (.xls)",
                    "status": "원본 파일 보존, 미파싱",
                }
            )
            continue
        source_sheets = read_xlsx(raw_path)
        widest = max((len(row) for source_sheet in source_sheets for row in source_sheet.rows), default=1)
        rows: list[list[Cell]] = [
            [text(f"{period} 금감원 원본 셀값", "title")],
            [text("원본 파일"), text(source_row["original_file_name"], "wrap")],
            [text("원본 파일 SHA-256"), text(sha256_file(raw_path), "wrap")],
            [text("원본 워크시트", "header"), text("원본 행", "header")]
            + [text(excel_column(index), "header") for index in range(1, widest + 1)],
        ]
        raw_row_count = 0
        source_names: list[str] = []
        for source_sheet in source_sheets:
            source_names.append(source_sheet.name)
            for original_row_number, original_row in enumerate(source_sheet.rows, start=1):
                padded = original_row + [""] * (widest - len(original_row))
                rows.append(
                    [text(source_sheet.name), number(original_row_number, "number")]
                    + [text(value, "body") for value in padded]
                )
                raw_row_count += 1
        max_col = excel_column(widest + 2)
        sheets.append(
            Sheet(
                name=sheet_name,
                rows=rows,
                widths=[24, 11] + [18] * widest,
                freeze_rows=4,
                auto_filter=f"A4:{max_col}{len(rows)}",
                merges=[f"A1:{max_col}1"],
            )
        )
        index_rows.append(
            {
                "source_id": source_row["source_id"],
                "period": period,
                "raw_sheet": sheet_name,
                "source_worksheets": "; ".join(source_names),
                "raw_rows": raw_row_count,
                "status": "원본 셀값 보존",
            }
        )
    return sheets, index_rows


def workbook_sheets(inputs: dict[str, object], raw_history: str) -> list[Sheet]:
    source = inputs["source"]
    registry = inputs["registry"]
    aliases = inputs["aliases"]
    fund_credit = inputs["fund_credit"]
    ranking = inputs["cumulative_ranking"]
    profile_snapshot = inputs["profile_snapshot"]
    period_summary = inputs["period_summary"]
    period_ranking = inputs["period_ranking"]
    multi_gp_detail = inputs["multi_gp_detail"]
    total_commitment = float(inputs["total_cumulative_commitment_trn_krw"])
    total_commitment_100mn = to_krw_100mn(total_commitment)
    assert isinstance(source, dict) and isinstance(fund_credit, list) and isinstance(ranking, list)
    raw_sheets, raw_index = build_raw_sheets(registry, raw_history)
    last_fund_credit_row = len(fund_credit) + 3
    last_ranking_row = len(ranking) + 3
    unique_fund_count = len({int(row["fund_id"]) for row in fund_credit})
    multi_gp_fund_count = len({int(row["fund_id"]) for row in multi_gp_detail})

    readme_rows = [
        [text("2025년 말 GP 누적 운용자산 순위", "title")],
        [text(RANKING_TITLE, "subtitle")],
        [text(f"기준일  {source['as_of_date']}  |  {source['period_label']}", "wrap")],
        [text("기준 금액  펀드별 최대 공시 총약정액이며, 표시 단위는 억원입니다. 실제 NAV나 운용사 자체 공시 AUM이 아닙니다.", "wrap")],
        [text("공동 GP  금감원 이력에 공동 업무집행사원으로 기재된 경우, 각 GP에 전액 반영합니다. 따라서 순위표 합계는 펀드 전체 총약정액보다 클 수 있습니다.", "wrap")],
        [text("누적 순위  웹 GP 목록과 같은 DB 기준입니다. 상세 내역은 '펀드별 반영' 시트에서 확인합니다.", "wrap")],
        [text("기간별 자료  '기간별 요약'과 '기간별 GP 순위'는 분기별 현황입니다.", "wrap")],
        [text("원본 자료  Raw 시트는 금감원 첨부파일의 원본 셀값입니다. 2015Q4·2016Q1 .xls는 원본 파일만 보존합니다.", "wrap")],
    ]
    assumptions_rows = [
        [text("집계 기준", "title")],
        [text("항목", "header"), text("기준", "header"), text("비고", "header")],
        [text("순위"), text(RANKING_TITLE, "wrap"), text("웹 GP 목록과 동일")],
        [text("DB 기준일"), text(source["period_label"]), text(source["as_of_date"])],
        [text("정규화 기간"), text("2016Q2 ~ 2025Q4"), text("금감원 분기 자료")],
        [text("GP 반영"), text("금감원 기재 업무집행사원"), text("공동 GP는 각각 전액 반영")],
        [text("금액"), text("펀드별 최대 공시 총약정액"), text("FSS 공시 총약정액. 실제 NAV/AUM이 아님")],
        [text("집계 단위"), text("억원"), text("기본 표시 단위")],
        [text("1조원당 환산액"), number(KRW_100MN_PER_TRILLION, "number"), text("억원 환산 계수")],
        [text("산식"), text("GP별 SUM(펀드별 MAX(공시 총약정액))", "wrap"), text("공동 GP는 각 GP에 전액 반영")],
        [text("고유 펀드 수"), number(unique_fund_count, "number"), text("정규화된 펀드")],
        [text("GP 반영 행"), number(len(fund_credit), "number"), text("펀드×GP 행")],
        [text("누적 GP 수"), number(len(ranking), "number"), text("순위표 GP 수")],
        [text("누적 반영액 (억원)"), number(total_commitment_100mn, "amount_100mn"), text("공동 GP 중복 반영 후 합계")],
        [text("복수 GP 펀드 수"), number(multi_gp_fund_count, "number"), text("2개 이상 GP가 기재된 펀드")],
    ]

    manifest_rows: list[list[Cell]] = [
        [text("금감원 원본 목록", "title")],
        [text("데이터팩에 포함한 원본 파일과 수록 시트", "subtitle")],
        [
            text("Source ID", "header"), text("Period", "header"), text("As of", "header"), text("Regime", "header"),
            text("Posted", "header"), text("Original file", "header"), text("FSS post URL", "header"), text("Download URL", "header"),
            text("Local raw path", "header"), text("SHA-256", "header"), text("Raw sheet", "header"), text("Status", "header"),
        ],
    ]
    raw_index_by_source = {str(row["source_id"]): row for row in raw_index}
    for row in registry:
        raw_path = REPO_ROOT / row["local_file"]
        raw_info = raw_index_by_source.get(row["source_id"], {})
        manifest_rows.append(
            [
                text(row["source_id"]), text(row["period_label"]), text(row["as_of_date"]), text(row["regime"]), text(row["posted_date"]),
                text(row["original_file_name"], "wrap"), text(row["post_url"], "link"), text(row["download_url"], "link"),
                text(row["local_file"], "link"), text(sha256_file(raw_path), "wrap"), text(raw_info.get("raw_sheet", "Not included")), text(raw_info.get("status", "Not included"), "wrap"),
            ]
        )

    mapping_rows: list[list[Cell]] = [
        [text("GP 명칭 정리", "title")],
        [text("동일 법인으로 확인된 표기만 통합", "subtitle")],
        [
            text("Scope", "header"), text("Raw GP name", "header"), text("Standard GP name", "header"), text("Mapping status", "header"),
            text("Rule ID", "header"), text("Relationship", "header"), text("Evidence", "header"), text("Primary sources", "header"),
        ],
    ]
    alias_by_name = {row["alias_gp_name"]: row for row in aliases if row.get("verification_decision") == "MERGE_ALIAS"}
    seen_mapping: set[tuple[str, str, str]] = set()
    for item in sorted({(str(row["credited_gp_name"]), str(row["credited_gp_name"])) for row in fund_credit}):
        raw_name, standard_name = item
        alias = alias_by_name.get(raw_name)
        row_key = ("누적 반영", raw_name, standard_name)
        seen_mapping.add(row_key)
        mapping_rows.append(
            [
                text("누적 반영"), text(raw_name), text(standard_name),
                text("통합 확인" if alias else "원본 기재"), text(alias.get("rule_id", "") if alias else ""),
                text(alias.get("relationship_type", "") if alias else ""), text(alias.get("evidence_summary", "") if alias else "금감원 업무집행사원 기재", "wrap"),
                text(alias.get("primary_sources", "") if alias else str(source["source_url"]), "link"),
            ]
        )
    for alias in aliases:
        if alias.get("verification_decision") != "MERGE_ALIAS":
            continue
        row_key = ("과거 명칭 규칙", alias["alias_gp_name"], alias["canonical_gp_name"])
        if row_key in seen_mapping:
            continue
        mapping_rows.append(
            [
                text("과거 명칭 규칙"), text(alias["alias_gp_name"]), text(alias["canonical_gp_name"]), text("통합 확인"),
                text(alias["rule_id"]), text(alias["relationship_type"]), text(alias["evidence_summary"], "wrap"), text(alias["primary_sources"], "link"),
            ]
        )

    fund_credit_rows: list[list[Cell]] = [
        [text("펀드별 반영", "title")],
        [text("금감원 이력에 기재된 펀드와 업무집행사원 GP의 대응표. 복수 GP는 각 GP에 전액 반영", "subtitle")],
        [
            text("펀드 ID", "header"), text("펀드명", "header"), text("GP ID", "header"), text("GP", "header"),
            text("최초 기재 분기", "header"), text("최초 기재 원본", "header"), text("최초 기재 시트", "header"), text("최초 기재 행", "header"),
            text("최대 약정액 원본", "header"), text("최대 총약정액 (억원)", "header"), text("2025Q4 기재", "header"),
            text("기재 GP 수", "header"), text("복수 GP", "header"), text("최종 기재 분기", "header"),
            text("반영", "header"), text("반영 기준", "header"),
        ],
    ]
    for item in fund_credit:
        amount_100mn = to_krw_100mn(item["max_commitment_trn_krw"])
        fund_credit_rows.append(
            [
                number(item["fund_id"], "number"), text(item["fund_name"], "wrap"), number(item["credited_gp_id"], "number"), text(item["credited_gp_name"], "wrap"),
                text(item["first_listed_period"]), text(item["first_listed_source_id"]), text(item["first_listed_sheet_name"], "wrap"), number(item["first_listed_row_number"], "number"),
                text(item["max_commitment_source_id"]), number(amount_100mn, "amount_100mn"),
                number(item["active_in_latest_period"], "number"), number(item["listed_gp_count"], "number"), text("Y" if item["multiple_gp_listed"] else ""),
                text(item["last_listed_period"]), text("Y"),
                text("금감원 기재 GP별 최대 총약정액 전액 반영", "wrap"),
            ]
        )

    ranking_rows: list[list[Cell]] = [
        [text("누적 순위", "title")],
        [text("웹 GP 목록과 같은 순위. 공동 GP는 각 GP에 전액 반영", "subtitle")],
        [
            text("순위", "header"), text("GP ID", "header"), text("GP", "header"), text("반영 펀드 수", "header"),
            text("DB 금액 (억원)", "header"), text("펀드별 반영 합계 (억원)", "header"), text("차이 (억원)", "header"),
            text("2025Q4 기재 펀드 수", "header"), text("비중", "header"), text("기준 분기", "header"), text("집계 기준", "header"),
        ],
    ]
    for row_number, item in enumerate(profile_snapshot, start=4):
        gp_id = int(item["gp_id"])
        amount_100mn = to_krw_100mn(item["cumulative_commitment_proxy_trn_krw"])
        share = amount_100mn / total_commitment_100mn if total_commitment_100mn else 0.0
        ranking_rows.append(
            [
                number(item["rank"], "number"),
                number(gp_id, "number"), text(item["gp_name"], "wrap"),
                formula(f"COUNTIF('펀드별 반영'!$C$4:$C${last_fund_credit_row},B{row_number})", int(item["cumulative_fund_count"]), "formula_number"),
                number(amount_100mn, "amount_100mn"),
                formula(f"SUMIF('펀드별 반영'!$C$4:$C${last_fund_credit_row},B{row_number},'펀드별 반영'!$J$4:$J${last_fund_credit_row})", amount_100mn, "formula_amount_100mn"),
                formula(f"E{row_number}-F{row_number}", 0, "formula_amount_100mn"),
                number(item["active_fund_count_latest"], "number"), formula(f"E{row_number}/SUM($E$4:$E${last_ranking_row})", share, "formula_pct"),
                text(source["period_label"]), text("금감원 기재 GP별 최대 총약정액 전액 반영", "wrap"),
            ]
        )

    period_summary_rows: list[list[Cell]] = [
        [text("기간별 요약", "title")],
        [text("웹 Market 대시보드의 분기별 시장 현황", "subtitle")],
        [text("분기", "header"), text("기준일", "header"), text("펀드 수", "header"), text("대표 GP 수", "header"), text("총약정액 (억원)", "header")],
    ]
    for item in period_summary:
        period_summary_rows.append(
            [text(item["period_label"]), text(item["as_of_date"]), number(item["active_fund_count"], "number"), number(item["primary_gp_count"], "number"), number(to_krw_100mn(item["commitment_trn_krw"]), "amount_100mn")]
        )

    period_ranking_rows: list[list[Cell]] = [
        [text("기간별 GP 순위", "title")],
        [text("분기별 대표 GP 기준 현황. 최종 누적 순위와는 별도 지표", "subtitle")],
        [text("분기", "header"), text("기준일", "header"), text("GP ID", "header"), text("GP", "header"), text("펀드 수", "header"), text("총약정액 (억원)", "header"), text("납입액 (억원)", "header")],
    ]
    for item in period_ranking:
        period_ranking_rows.append(
            [text(item["period_label"]), text(item["as_of_date"]), number(item["gp_id"], "number"), text(item["gp_name"], "wrap"), number(item["active_fund_count"], "number"), number(to_krw_100mn(item["commitment_aum_proxy_trn_krw"]), "amount_100mn"), number(to_krw_100mn(item["paid_in_trn_krw"]), "amount_100mn")]
        )

    multi_gp_rows: list[list[Cell]] = [
        [text("복수 GP 내역", "title")],
        [text("금감원 이력에 2개 이상 GP가 기재된 펀드. 각 GP 행에 최대 총약정액 전액 반영", "subtitle")],
        [text("펀드 ID", "header"), text("펀드명", "header"), text("GP ID", "header"), text("GP", "header"), text("최초 기재 분기", "header"), text("최종 기재 분기", "header"), text("기재 GP 수", "header"), text("최대 총약정액 (억원)", "header"), text("반영 기준", "header")],
    ]
    for item in multi_gp_detail:
        multi_gp_rows.append(
            [number(item["fund_id"], "number"), text(item["fund_name"], "wrap"), number(item["credited_gp_id"], "number"), text(item["credited_gp_name"], "wrap"), text(item["first_listed_period"]), text(item["last_listed_period"]), number(item["listed_gp_count"], "number"), number(to_krw_100mn(item["max_commitment_trn_krw"]), "amount_100mn"), text(item["ranking_treatment"], "wrap")]
        )

    qa_rows: list[list[Cell]] = [
        [text("검증", "title")],
        [text("정규화 DB와 엑셀 계산값 비교", "subtitle")],
        [text("항목", "header"), text("DB 기준", "header"), text("엑셀 계산", "header"), text("결과", "header"), text("확인 내용", "header")],
        [text("FSS 원본 ID"), text(source["source_id"]), text(source["source_id"]), formula("IF(B4=C4,\"PASS\",\"FAIL\")", "PASS", "pass"), text("최신 원본 등록·적재")],
        [text("원본 SHA-256"), text(source["sha256"], "wrap"), text(sha256_file(REPO_ROOT / str(source["local_path"])), "wrap"), formula("IF(B5=C5,\"PASS\",\"FAIL\")", "PASS", "pass"), text("원본 파일 일치")],
        [text("GP 반영 행"), number(len(fund_credit), "number"), formula(f"COUNTIF('펀드별 반영'!$O$4:$O${last_fund_credit_row},\"Y\")", len(fund_credit), "formula_number"), formula("IF(B6=C6,\"PASS\",\"FAIL\")", "PASS", "pass"), text("펀드×GP 반영 행 수")],
        [text("누적 순위 GP 수"), number(len(ranking), "number"), formula(f"COUNTA('누적 순위'!$B$4:$B${last_ranking_row})", len(ranking), "formula_number"), formula("IF(B7=C7,\"PASS\",\"FAIL\")", "PASS", "pass"), text("웹 GP DB와 일치")],
        [text("펀드별 반영 합계 (억원)"), number(total_commitment_100mn, "amount_100mn"), formula(f"SUM('펀드별 반영'!$J$4:$J${last_fund_credit_row})", total_commitment_100mn, "formula_amount_100mn"), formula("IF(ROUND(B8,2)=ROUND(C8,2),\"PASS\",\"FAIL\")", "PASS", "pass"), text("공동 GP 중복 반영 후 합계")],
        [text("누적 순위 합계 (억원)"), number(total_commitment_100mn, "amount_100mn"), formula(f"SUM('누적 순위'!$E$4:$E${last_ranking_row})", total_commitment_100mn, "formula_amount_100mn"), formula("IF(ROUND(B9,2)=ROUND(C9,2),\"PASS\",\"FAIL\")", "PASS", "pass"), text("웹 GP DB 누적 지표")],
        [text("DB-펀드별 반영 차이 (억원)"), number(0, "amount_100mn"), formula(f"SUM('누적 순위'!$G$4:$G${last_ranking_row})", 0, "formula_amount_100mn"), formula("IF(ROUND(B10,2)=ROUND(C10,2),\"PASS\",\"FAIL\")", "PASS", "pass"), text("순위와 상세 내역 대사")],
        [text("복수 GP 반영 행"), number(len(multi_gp_detail), "number"), formula(f"COUNTIF('펀드별 반영'!$M$4:$M${last_fund_credit_row},\"Y\")", len(multi_gp_detail), "formula_number"), formula("IF(B11=C11,\"PASS\",\"FAIL\")", "PASS", "pass"), text("공동 GP 전액 반영 대상")],
    ]
    raw_index_rows = [
        [text("원본 시트 목록", "title")],
        [text("원본 ID", "header"), text("분기", "header"), text("데이터팩 시트", "header"), text("원본 워크시트", "header"), text("원본 행 수", "header"), text("상태", "header")],
    ]
    for row in raw_index:
        raw_index_rows.append(
            [text(row["source_id"]), text(row["period"]), text(row["raw_sheet"]), text(row["source_worksheets"], "wrap"), text(row["raw_rows"]), text(row["status"], "wrap")]
        )

    return [
        Sheet("안내", readme_rows, [105], freeze_rows=2),
        Sheet("집계 기준", assumptions_rows, [28, 40, 78], freeze_rows=2, auto_filter=f"A2:C{len(assumptions_rows)}", merges=["A1:C1"]),
        Sheet("원천 목록", manifest_rows, [21, 12, 13, 22, 12, 42, 70, 70, 52, 68, 18, 24], freeze_rows=3, auto_filter=f"A3:L{len(manifest_rows)}", merges=["A1:L1", "A2:L2"]),
        Sheet("GP 명칭 정리", mapping_rows, [24, 34, 34, 18, 34, 28, 70, 70], freeze_rows=3, auto_filter=f"A3:H{len(mapping_rows)}", merges=["A1:H1", "A2:H2"]),
        Sheet("펀드별 반영", fund_credit_rows, [12, 42, 12, 34, 15, 22, 18, 12, 22, 25, 18, 18, 14, 16, 12, 52], freeze_rows=3, auto_filter=f"A3:P{len(fund_credit_rows)}", merges=["A1:P1", "A2:P2"]),
        Sheet("누적 순위", ranking_rows, [16, 12, 34, 16, 27, 27, 18, 22, 16, 14, 58], freeze_rows=3, auto_filter=f"A3:K{len(ranking_rows)}", merges=["A1:K1", "A2:K2"]),
        Sheet("기간별 요약", period_summary_rows, [14, 16, 18, 18, 28], freeze_rows=3, auto_filter=f"A3:E{len(period_summary_rows)}", merges=["A1:E1", "A2:E2"]),
        Sheet("기간별 GP 순위", period_ranking_rows, [14, 16, 12, 34, 18, 28, 24], freeze_rows=3, auto_filter=f"A3:G{len(period_ranking_rows)}", merges=["A1:G1", "A2:G2"]),
        Sheet("복수 GP 내역", multi_gp_rows, [12, 42, 12, 34, 15, 15, 16, 28, 36], freeze_rows=3, auto_filter=f"A3:I{len(multi_gp_rows)}", merges=["A1:I1", "A2:I2"]),
        Sheet("검증", qa_rows, [34, 35, 35, 12, 54], freeze_rows=3, auto_filter=f"A3:E{len(qa_rows)}", merges=["A1:E1", "A2:E2"]),
        Sheet("원본 시트 목록", raw_index_rows, [22, 14, 20, 45, 16, 32], freeze_rows=2, auto_filter=f"A2:F{len(raw_index_rows)}", merges=["A1:F1"]),
        *raw_sheets,
    ]


def validate_datapack(path: Path, expected_sheets: list[str], expected_metrics: dict[str, int | float]) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"Data pack was not created: {path}")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        required = {"[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml"}
        if not required.issubset(names):
            raise RuntimeError("Generated workbook is missing required XLSX parts")
        workbook = archive.read("xl/workbook.xml").decode("utf-8")
        missing_sheets = [name for name in expected_sheets if f'name="{name}"' not in workbook]
        if missing_sheets:
            raise RuntimeError(f"Generated workbook is missing sheets: {', '.join(missing_sheets)}")
        all_sheets = [name for name in names if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")]
        # LibreOffice may add attributes to formula tags while normalizing.
        formulas = sum(archive.read(name).count(b"<f") for name in all_sheets)
        if formulas < int(expected_metrics["formula_count_min"]):
            raise RuntimeError(f"Generated workbook has too few formulas: {formulas}")
    return {"file_size_bytes": path.stat().st_size, "sheet_count": len(all_sheets), "formula_count": formulas}


def normalize_xlsx_for_excel(path: Path, soffice_binary: Path) -> None:
    """Rewrite the OOXML package with LibreOffice before external delivery.

    The raw writer is intentionally lightweight so the data pack can run with
    the standard library. LibreOffice produces a stricter Office-compatible
    package from that deterministic intermediate file. Delivery builds must
    use this normalization step and the resulting file is then opened in
    Microsoft Excel during release verification.
    """
    if not soffice_binary.is_file():
        raise RuntimeError(f"LibreOffice executable was not found: {soffice_binary}")
    with tempfile.TemporaryDirectory(prefix="gp-datapack-excel-") as temp_dir:
        temp_root = Path(temp_dir)
        source_dir = temp_root / "source"
        output_dir = temp_root / "output"
        profile_dir = temp_root / "profile"
        source_dir.mkdir()
        output_dir.mkdir()
        source_path = source_dir / path.name
        shutil.copy2(path, source_path)
        completed = subprocess.run(
            [
                str(soffice_binary),
                "--headless",
                f"-env:UserInstallation={profile_dir.as_uri()}",
                "--convert-to",
                "xlsx",
                "--outdir",
                str(output_dir),
                str(source_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        normalized_path = output_dir / path.name
        if completed.returncode != 0 or not normalized_path.is_file() or normalized_path.stat().st_size <= 0:
            raise RuntimeError(
                "LibreOffice could not normalize the workbook: "
                f"returncode={completed.returncode}; stdout={completed.stdout.strip()}; stderr={completed.stderr.strip()}"
            )
        shutil.copy2(normalized_path, path)


def build_datapack(
    db_path: Path,
    registry_path: Path,
    alias_rules_path: Path,
    output_path: Path,
    period_label: str = "2025Q4",
    raw_history: str = "all",
    excel_compatible: bool = False,
    soffice_binary: Path | None = None,
) -> dict[str, object]:
    inputs = read_ranking_inputs(db_path, registry_path, alias_rules_path, period_label)
    sheets = workbook_sheets(inputs, raw_history)
    write_xlsx(output_path, sheets)
    expected_sheets = [
        "안내",
        "집계 기준",
        "원천 목록",
        "GP 명칭 정리",
        "펀드별 반영",
        "누적 순위",
        "기간별 요약",
        "기간별 GP 순위",
        "복수 GP 내역",
        "검증",
        "원본 시트 목록",
        f"Raw {period_label}",
    ]
    expected_formula_count = len(inputs["profile_snapshot"]) * 4 + 10
    raw_validation = validate_datapack(
        output_path,
        expected_sheets,
        {"formula_count_min": expected_formula_count},
    )
    if excel_compatible:
        if soffice_binary is None:
            configured = os.environ.get("SOFFICE_BIN") or shutil.which("soffice")
            if not configured:
                raise RuntimeError("Excel-compatible delivery requires --soffice or SOFFICE_BIN")
            soffice_binary = Path(configured)
        normalize_xlsx_for_excel(output_path, soffice_binary)
    validation = validate_datapack(
        output_path,
        expected_sheets,
        {"formula_count_min": expected_formula_count},
    )
    return {
        "output": str(output_path),
        "period": period_label,
        "fund_rows": len(inputs["fund_credit"]),
        "ranked_gps": len(inputs["cumulative_ranking"]),
        "multi_gp_rows": len(inputs["multi_gp_detail"]),
        "commitment_trn_krw": round(float(inputs["total_cumulative_commitment_trn_krw"]), 6),
        "excel_normalized": excel_compatible,
        "source_formula_count": raw_validation["formula_count"],
        **validation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an audit-ready GP ranking Excel data pack")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--alias-rules", type=Path, default=DEFAULT_ALIAS_RULES)
    parser.add_argument("--period", default="2025Q4")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-history", choices=("all", "latest"), default="all")
    parser.add_argument("--excel-compatible", action="store_true", help="Normalize the delivery file with LibreOffice")
    parser.add_argument("--soffice", type=Path, help="Path to the LibreOffice soffice executable")
    args = parser.parse_args()
    result = build_datapack(
        db_path=args.db,
        registry_path=args.registry,
        alias_rules_path=args.alias_rules,
        output_path=args.output,
        period_label=args.period,
        raw_history=args.raw_history,
        excel_compatible=args.excel_compatible,
        soffice_binary=args.soffice,
    )
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
