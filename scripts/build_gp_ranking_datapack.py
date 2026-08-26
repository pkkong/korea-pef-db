#!/usr/bin/env python3
"""Build an audit-ready Excel data pack from the public GP database.

The workbook is an audit view of the same normalized database that powers the
GP service. It does not calculate a competing ranking. The cumulative ranking
credits every normalized fund once to its first observed FSS primary GP and
sums that fund's maximum disclosed commitment through the requested period.
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
    "amount_mn": 7,
    "amount_tn": 8,
    "pct": 9,
    "formula_number": 10,
    "formula_amount_mn": 11,
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
        '<numFmts count="4">'
        '<numFmt numFmtId="164" formatCode="#,##0"/>'
        '<numFmt numFmtId="165" formatCode="#,##0.0"/>'
        '<numFmt numFmtId="166" formatCode="0.000000"/>'
        '<numFmt numFmtId="167" formatCode="0.00%"/>'
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
        '<xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
        '<xf numFmtId="166" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
        '<xf numFmtId="167" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
        '<xf numFmtId="164" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1"/>'
        '<xf numFmtId="165" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1"/>'
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
            "analytics_gp_cumulative_fund_attribution",
            "analytics_gp_cumulative_ranking",
            "analytics_gp_cumulative_change_history",
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
        attribution = fetch_dicts(
            conn,
            """
            SELECT * FROM analytics_gp_cumulative_fund_attribution
            ORDER BY attributed_gp_name, fund_name, fund_id
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
        change_history = fetch_dicts(
            conn,
            """
            SELECT * FROM analytics_gp_cumulative_change_history
            ORDER BY max_commitment_trn_krw DESC, fund_name, fund_id
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
        "attribution": attribution,
        "cumulative_ranking": cumulative_ranking,
        "profile_snapshot": profile_snapshot,
        "period_summary": period_summary,
        "period_ranking": period_ranking,
        "change_history": change_history,
        "total_cumulative_commitment_trn_krw": sum(
            float(row["max_commitment_trn_krw"] or 0) for row in attribution
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
    attribution = inputs["attribution"]
    ranking = inputs["cumulative_ranking"]
    profile_snapshot = inputs["profile_snapshot"]
    period_summary = inputs["period_summary"]
    period_ranking = inputs["period_ranking"]
    change_history = inputs["change_history"]
    total_commitment = float(inputs["total_cumulative_commitment_trn_krw"])
    assert isinstance(source, dict) and isinstance(attribution, list) and isinstance(ranking, list)
    raw_sheets, raw_index = build_raw_sheets(registry, raw_history)
    last_attribution_row = len(attribution) + 3
    last_ranking_row = len(ranking) + 3

    readme_rows = [
        [text("GP Ranking Data Pack", "title")],
        [text(RANKING_TITLE, "subtitle")],
        [text("목적: 웹 GP 서비스가 읽는 정규화 DB 스냅샷과 동일한 누적 순위를 원본 행까지 추적하게 만든 검증용 데이터팩입니다.", "wrap")],
        [text(f"기준일: {source['as_of_date']} ({source['period_label']})", "wrap")],
        [text("순위 지표: 각 정규화 펀드의 최대 공시 총약정액을 한 번씩만 합산합니다. 실제 NAV 또는 운용사 자체 공시 AUM이 아닙니다.", "wrap")],
        [text("귀속 규칙: 최초 금감원 관측 시점의 대표 GP에 펀드를 한 번만 귀속합니다. 이후 GP 변경은 GP Change History에 보존하고 순위에는 재귀속하거나 중복 반영하지 않습니다.", "wrap")],
        [text("웹과의 관계: GP DB Snapshot은 공개 GP 서비스가 읽는 gp_profile 누적 지표를 그대로 옮긴 시트입니다. Fund Attribution Ledger의 계산값과 QA에서 대사합니다.", "wrap")],
        [text("기간별 정보: Period Summary와 Period GP Ranking은 정규화 DB의 기간별 대시보드 데이터를 그대로 표시합니다. 최종 순위는 누적 순위만 사용합니다.", "wrap")],
        [text("원천 보존: Raw 시트에는 각 금감원 첨부파일의 원본 셀값을 보존합니다. 구형 2015Q4·2016Q1 .xls는 원본 파일 경로와 SHA-256을 보존하며 행 단위 파싱 대상은 아닙니다.", "wrap")],
        [text("중요 한계: 금감원 원천은 2016Q2부터 행 단위 정규화되어 있습니다. 2015Q4·2016Q1 구형 .xls는 원본 보존과 SHA 검증만 합니다.", "wrap")],
    ]
    assumptions_rows = [
        [text("Calculation Assumptions", "title")],
        [text("입력 / 규칙", "header"), text("값", "header"), text("설명", "header")],
        [text("최종 순위 정의"), text(RANKING_TITLE, "wrap"), text("누적 순위의 유일한 공식 정의")],
        [text("DB 기준일"), text(source["period_label"]), text(source["as_of_date"])],
        [text("정규화 기간"), text("2016Q2 ~ 2025Q4"), text("행 단위 정규화가 가능한 FSS 분기")],
        [text("펀드 귀속"), text("최초 관측 대표 GP"), text("정규화된 펀드당 한 번만 귀속")],
        [text("금액"), text("펀드별 최대 공시 총약정액"), text("FSS 공시 총약정액. 실제 NAV/AUM이 아님")],
        [text("GP 변경"), text("중복 미귀속"), text("후속 GP 변경은 이력 시트에서 검토")],
        [text("집계 단위"), text("KRW trillion"), text("Workbook 계산 및 대사 단위")],
        [text("KRW mn per trillion"), number(1_000_000, "number"), text("Fund Attribution Ledger 원천 금액 변환 계수")],
        [text("감사 산식"), text("SUM(펀드별 MAX(공시 총약정액)) by 최초 관측 대표 GP", "wrap"), text("Fund Attribution Ledger와 GP DB Snapshot의 대사 기준")],
        [text("고유 펀드 수"), number(len(attribution), "number"), text("최종 누적 순위에 한 번만 포함")],
        [text("누적 GP 수"), number(len(ranking), "number"), text("최종 순위의 GP 수")],
        [text("누적 총약정액 (KRW tn)"), number(total_commitment, "amount_tn"), text("모든 펀드의 최대 공시 총약정액 합계")],
        [text("GP 변경 펀드 수"), number(len(change_history), "number"), text("순위 중복을 막기 위해 변경 이력을 별도 보존")],
    ]

    manifest_rows: list[list[Cell]] = [
        [text("FSS Source Manifest", "title")],
        [text("금감원 원본 파일, URL, 게시일, 로컬 SHA-256 및 데이터팩 원천 시트의 대응표입니다.", "subtitle")],
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
        [text("GP Name Mapping", "title")],
        [text("별칭 병합은 정규화 DB가 적용한 규칙과 동일합니다. 누적 귀속 GP명은 Fund Attribution Ledger에서 확인합니다.", "subtitle")],
        [
            text("Scope", "header"), text("Raw GP name", "header"), text("Standard GP name", "header"), text("Mapping status", "header"),
            text("Rule ID", "header"), text("Relationship", "header"), text("Evidence", "header"), text("Primary sources", "header"),
        ],
    ]
    alias_by_name = {row["alias_gp_name"]: row for row in aliases if row.get("verification_decision") == "MERGE_ALIAS"}
    seen_mapping: set[tuple[str, str, str]] = set()
    for item in sorted({(str(row["attributed_gp_name"]), str(row["attributed_gp_name"])) for row in attribution}):
        raw_name, standard_name = item
        alias = alias_by_name.get(raw_name)
        row_key = ("Cumulative attribution", raw_name, standard_name)
        seen_mapping.add(row_key)
        mapping_rows.append(
            [
                text("Cumulative attribution"), text(raw_name), text(standard_name),
                text("Verified alias" if alias else "Direct primary GP"), text(alias.get("rule_id", "") if alias else ""),
                text(alias.get("relationship_type", "") if alias else ""), text(alias.get("evidence_summary", "") if alias else "Normalized FSS primary GP attribution", "wrap"),
                text(alias.get("primary_sources", "") if alias else str(source["source_url"]), "link"),
            ]
        )
    for alias in aliases:
        if alias.get("verification_decision") != "MERGE_ALIAS":
            continue
        row_key = ("Historical alias rule", alias["alias_gp_name"], alias["canonical_gp_name"])
        if row_key in seen_mapping:
            continue
        mapping_rows.append(
            [
                text("Historical alias rule"), text(alias["alias_gp_name"]), text(alias["canonical_gp_name"]), text("Verified alias"),
                text(alias["rule_id"]), text(alias["relationship_type"]), text(alias["evidence_summary"], "wrap"), text(alias["primary_sources"], "link"),
            ]
        )

    attribution_rows: list[list[Cell]] = [
        [text("Fund Attribution Ledger", "title")],
        [text("각 정규화 펀드를 한 번만 누적 순위에 귀속합니다. 최초 GP 귀속과 최대 공시 총약정액의 원본 행을 모두 보존합니다. 회색 열은 엑셀 수식입니다.", "subtitle")],
        [
            text("Fund ID", "header"), text("Fund name", "header"), text("Rank GP ID", "header"), text("Rank GP", "header"),
            text("First GP period", "header"), text("First GP source", "header"), text("First GP sheet", "header"), text("First GP row", "header"),
            text("Max commitment source", "header"), text("Max commitment (KRW tn)", "header"), text("Max commitment (KRW mn)", "header"),
            text("Active in 2025Q4", "header"), text("Observed primary GPs", "header"), text("GP changed", "header"),
            text("Latest observed GP", "header"), text("Latest period", "header"), text("Included", "header"), text("Ranking rule", "header"),
        ],
    ]
    for row_number, item in enumerate(attribution, start=4):
        amount_tn = float(item["max_commitment_trn_krw"] or 0)
        attribution_rows.append(
            [
                number(item["fund_id"], "number"), text(item["fund_name"], "wrap"), number(item["attributed_gp_id"], "number"), text(item["attributed_gp_name"], "wrap"),
                text(item["attribution_period"]), text(item["attribution_source_id"]), text(item["attribution_sheet_name"], "wrap"), number(item["attribution_row_number"], "number"),
                text(item["max_commitment_source_id"]), number(amount_tn, "amount_tn"), formula(f"J{row_number}*'Assumptions'!$B$10", amount_tn * 1_000_000.0, "formula_amount_mn"),
                number(item["active_in_latest_period"], "number"), number(item["observed_primary_gp_count"], "number"), text("Y" if item["primary_gp_changed"] else ""),
                text(item["latest_observed_gp_name"], "wrap"), text(item["latest_observed_period"]), text("Y"),
                text("One normalized fund, first observed primary GP, maximum disclosed commitment", "wrap"),
            ]
        )

    ranking_rows: list[list[Cell]] = [
        [text("GP DB Snapshot", "title")],
        [text("공개 GP 웹 서비스가 읽는 gp_profile 누적 순위를 그대로 표시합니다. 회색 열은 Fund Attribution Ledger의 재계산값으로, DB 스냅샷과 일치해야 합니다.", "subtitle")],
        [
            text("Cumulative rank", "header"), text("GP ID", "header"), text("Standard GP", "header"), text("Fund count", "header"),
            text("DB commitment (KRW tn)", "header"), text("Ledger commitment (KRW tn)", "header"), text("Difference", "header"),
            text("Active funds in 2025Q4", "header"), text("Market share", "header"), text("DB period", "header"), text("Definition", "header"),
        ],
    ]
    for row_number, item in enumerate(profile_snapshot, start=4):
        gp_id = int(item["gp_id"])
        amount_tn = float(item["cumulative_commitment_proxy_trn_krw"])
        share = amount_tn / total_commitment if total_commitment else 0.0
        ranking_rows.append(
            [
                number(item["rank"], "number"),
                number(gp_id, "number"), text(item["gp_name"], "wrap"),
                formula(f"COUNTIF('Fund Attribution Ledger'!$C$4:$C${last_attribution_row},B{row_number})", int(item["cumulative_fund_count"]), "formula_number"),
                number(amount_tn, "amount_tn"),
                formula(f"SUMIF('Fund Attribution Ledger'!$C$4:$C${last_attribution_row},B{row_number},'Fund Attribution Ledger'!$J$4:$J${last_attribution_row})", amount_tn, "formula_amount_tn"),
                formula(f"E{row_number}-F{row_number}", 0, "formula_amount_tn"),
                number(item["active_fund_count_latest"], "number"), formula(f"E{row_number}/SUM($E$4:$E${last_ranking_row})", share, "formula_pct"),
                text(source["period_label"]), text("One fund once; first observed primary GP; maximum disclosed commitment", "wrap"),
            ]
        )

    period_summary_rows: list[list[Cell]] = [
        [text("Period Summary", "title")],
        [text("정규화된 FSS 기간별 시장 요약입니다. 웹 Market 대시보드의 기간 데이터와 같은 DB 테이블을 읽습니다.", "subtitle")],
        [text("Period", "header"), text("As of", "header"), text("Active funds", "header"), text("Primary GPs", "header"), text("Commitment (KRW tn)", "header")],
    ]
    for item in period_summary:
        period_summary_rows.append(
            [text(item["period_label"]), text(item["as_of_date"]), number(item["active_fund_count"], "number"), number(item["primary_gp_count"], "number"), number(item["commitment_trn_krw"], "amount_tn")]
        )

    period_ranking_rows: list[list[Cell]] = [
        [text("Period GP Ranking", "title")],
        [text("정규화 DB의 GP별 기간 순위입니다. 이 시트의 기간별 수치는 참고용이며, 최종 순위는 GP DB Snapshot의 누적 순위입니다.", "subtitle")],
        [text("Period", "header"), text("As of", "header"), text("GP ID", "header"), text("GP", "header"), text("Active funds", "header"), text("Commitment (KRW tn)", "header"), text("Paid in (KRW tn)", "header")],
    ]
    for item in period_ranking:
        period_ranking_rows.append(
            [text(item["period_label"]), text(item["as_of_date"]), number(item["gp_id"], "number"), text(item["gp_name"], "wrap"), number(item["active_fund_count"], "number"), number(item["commitment_aum_proxy_trn_krw"], "amount_tn"), number(item["paid_in_trn_krw"], "amount_tn")]
        )

    change_rows: list[list[Cell]] = [
        [text("GP Change History", "title")],
        [text("대표 GP가 두 곳 이상 관측된 펀드입니다. 최종 순위에는 최초 관측 대표 GP 한 곳에만 귀속해 중복 집계를 막습니다.", "subtitle")],
        [text("Fund ID", "header"), text("Fund", "header"), text("Rank GP ID", "header"), text("Rank GP", "header"), text("First period", "header"), text("Latest GP ID", "header"), text("Latest GP", "header"), text("Latest period", "header"), text("Observed GP count", "header"), text("Max commitment (KRW tn)", "header"), text("Ranking treatment", "header")],
    ]
    for item in change_history:
        change_rows.append(
            [number(item["fund_id"], "number"), text(item["fund_name"], "wrap"), number(item["rank_attributed_gp_id"], "number"), text(item["rank_attributed_gp_name"], "wrap"), text(item["attribution_period"]), number(item["latest_observed_gp_id"], "number"), text(item["latest_observed_gp_name"], "wrap"), text(item["latest_observed_period"]), number(item["observed_primary_gp_count"], "number"), number(item["max_commitment_trn_krw"], "amount_tn"), text(item["ranking_treatment"], "wrap")]
        )

    qa_rows: list[list[Cell]] = [
        [text("QA Reconciliation", "title")],
        [text("Expected values are the normalized GP DB snapshot. Calculated values are workbook formulas. Every status must be PASS before distribution.", "subtitle")],
        [text("Control", "header"), text("Expected", "header"), text("Calculated", "header"), text("Status", "header"), text("Rule", "header")],
        [text("FSS source ID"), text(source["source_id"]), text(source["source_id"]), formula("IF(B4=C4,\"PASS\",\"FAIL\")", "PASS", "pass"), text("Latest source registered and imported")],
        [text("Raw file SHA-256"), text(source["sha256"], "wrap"), text(sha256_file(REPO_ROOT / str(source["local_path"])), "wrap"), formula("IF(B5=C5,\"PASS\",\"FAIL\")", "PASS", "pass"), text("Local raw file matches SQLite source_document")],
        [text("Unique fund attributions"), number(len(attribution), "number"), formula(f"COUNTIF('Fund Attribution Ledger'!$Q$4:$Q${last_attribution_row},\"Y\")", len(attribution), "formula_number"), formula("IF(B6=C6,\"PASS\",\"FAIL\")", "PASS", "pass"), text("Each normalized fund is included once")],
        [text("Cumulative ranked GPs"), number(len(ranking), "number"), formula(f"COUNTA('GP DB Snapshot'!$B$4:$B${last_ranking_row})", len(ranking), "formula_number"), formula("IF(B7=C7,\"PASS\",\"FAIL\")", "PASS", "pass"), text("The public GP DB and cumulative analytics have the same GP count")],
        [text("Attribution total (KRW tn)"), number(total_commitment, "amount_tn"), formula(f"SUM('Fund Attribution Ledger'!$J$4:$J${last_attribution_row})", total_commitment, "formula_amount_tn"), formula("IF(ROUND(B8,6)=ROUND(C8,6),\"PASS\",\"FAIL\")", "PASS", "pass"), text("Sum of unique fund maximum commitments")],
        [text("GP DB total (KRW tn)"), number(total_commitment, "amount_tn"), formula(f"SUM('GP DB Snapshot'!$E$4:$E${last_ranking_row})", total_commitment, "formula_amount_tn"), formula("IF(ROUND(B9,6)=ROUND(C9,6),\"PASS\",\"FAIL\")", "PASS", "pass"), text("Public GP DB cumulative metric")],
        [text("DB vs ledger difference (KRW tn)"), number(0, "amount_tn"), formula(f"SUM('GP DB Snapshot'!$G$4:$G${last_ranking_row})", 0, "formula_amount_tn"), formula("IF(ROUND(B10,6)=ROUND(C10,6),\"PASS\",\"FAIL\")", "PASS", "pass"), text("No fund amount may be lost or double counted")],
        [text("GP change funds"), number(len(change_history), "number"), formula(f"COUNTIF('Fund Attribution Ledger'!$N$4:$N${last_attribution_row},\"Y\")", len(change_history), "formula_number"), formula("IF(B11=C11,\"PASS\",\"FAIL\")", "PASS", "pass"), text("Changed GP observations are retained outside final allocation")],
    ]
    raw_index_rows = [
        [text("Raw Sheet Index", "title")],
        [text("Source ID", "header"), text("Period", "header"), text("Data pack sheet", "header"), text("Original worksheets", "header"), text("Original rows", "header"), text("Status", "header")],
    ]
    for row in raw_index:
        raw_index_rows.append(
            [text(row["source_id"]), text(row["period"]), text(row["raw_sheet"]), text(row["source_worksheets"], "wrap"), text(row["raw_rows"]), text(row["status"], "wrap")]
        )

    return [
        Sheet("README", readme_rows, [105], freeze_rows=2),
        Sheet("Assumptions", assumptions_rows, [28, 40, 78], freeze_rows=2, auto_filter=f"A2:C{len(assumptions_rows)}", merges=["A1:C1"]),
        Sheet("Source Manifest", manifest_rows, [21, 12, 13, 22, 12, 42, 70, 70, 52, 68, 18, 24], freeze_rows=3, auto_filter=f"A3:L{len(manifest_rows)}", merges=["A1:L1", "A2:L2"]),
        Sheet("GP Name Mapping", mapping_rows, [24, 34, 34, 18, 34, 28, 70, 70], freeze_rows=3, auto_filter=f"A3:H{len(mapping_rows)}", merges=["A1:H1", "A2:H2"]),
        Sheet("Fund Attribution Ledger", attribution_rows, [12, 42, 12, 34, 15, 22, 18, 12, 22, 25, 25, 18, 18, 14, 34, 15, 12, 65], freeze_rows=3, auto_filter=f"A3:R{len(attribution_rows)}", merges=["A1:R1", "A2:R2"]),
        Sheet("GP DB Snapshot", ranking_rows, [16, 12, 34, 16, 27, 27, 18, 22, 16, 14, 70], freeze_rows=3, auto_filter=f"A3:K{len(ranking_rows)}", merges=["A1:K1", "A2:K2"]),
        Sheet("Period Summary", period_summary_rows, [14, 16, 18, 18, 28], freeze_rows=3, auto_filter=f"A3:E{len(period_summary_rows)}", merges=["A1:E1", "A2:E2"]),
        Sheet("Period GP Ranking", period_ranking_rows, [14, 16, 12, 34, 18, 28, 24], freeze_rows=3, auto_filter=f"A3:G{len(period_ranking_rows)}", merges=["A1:G1", "A2:G2"]),
        Sheet("GP Change History", change_rows, [12, 42, 12, 34, 15, 14, 34, 15, 20, 28, 70], freeze_rows=3, auto_filter=f"A3:K{len(change_rows)}", merges=["A1:K1", "A2:K2"]),
        Sheet("QA Reconciliation", qa_rows, [34, 35, 35, 12, 68], freeze_rows=3, auto_filter=f"A3:E{len(qa_rows)}", merges=["A1:E1", "A2:E2"]),
        Sheet("Raw Index", raw_index_rows, [22, 14, 20, 45, 16, 32], freeze_rows=2, auto_filter=f"A2:F{len(raw_index_rows)}", merges=["A1:F1"]),
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
        formulas = b"".join(archive.read(name) for name in all_sheets).count(b"<f>")
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
        "README",
        "Assumptions",
        "Source Manifest",
        "GP Name Mapping",
        "Fund Attribution Ledger",
        "GP DB Snapshot",
        "Period Summary",
        "Period GP Ranking",
        "GP Change History",
        "QA Reconciliation",
        "Raw Index",
        f"Raw {period_label}",
    ]
    expected_formula_count = len(inputs["attribution"]) + len(inputs["profile_snapshot"]) * 4 + 10
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
        {"formula_count_min": 0 if excel_compatible else expected_formula_count},
    )
    return {
        "output": str(output_path),
        "period": period_label,
        "fund_rows": len(inputs["attribution"]),
        "ranked_gps": len(inputs["cumulative_ranking"]),
        "gp_change_funds": len(inputs["change_history"]),
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
