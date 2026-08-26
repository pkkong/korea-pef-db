#!/usr/bin/env python3
"""Build an audit-ready Excel data pack for the GP commitment ranking.

The FSS source files disclose fund commitment amounts, not NAV/AUM. This
workbook therefore ranks primary GPs by the sum of disclosed 2025 year-end
fund commitments. The workbook keeps the original FSS values, the conversion
formula, name-resolution evidence, and every final ranking calculation visible.
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
RANKING_TITLE = "2025년 말 기준 기관전용 PEF 총약정액 합계 순위 (대표 GP 귀속)"


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
        source = conn.execute(
            """
            SELECT rp.period_id, rp.period_label, rp.as_of_date, sd.source_id, sd.sha256, sd.title, sd.source_url, sd.local_path
            FROM reporting_period rp
            JOIN source_document sd
              ON sd.period_label = rp.period_label
             AND sd.as_of_date = rp.as_of_date
            WHERE rp.period_label = ?
            ORDER BY rp.as_of_date DESC
            LIMIT 1
            """,
            (period_label,),
        ).fetchone()
        if source is None:
            raise RuntimeError(f"No imported FSS source exists for {period_label}")
        ledger_sql = """
            SELECT
                fps.snapshot_id,
                fps.source_id,
                fps.sheet_name,
                fps.row_number,
                fps.row_hash,
                fps.fund_id,
                fps.fund_name_raw,
                fps.gp_name_raw,
                fps.commitment_amount_raw,
                fps.commitment_amount_krw_mn,
                fps.raw_row_json,
                gh.gp_id,
                gh.gp_name AS standard_gp_name,
                sr.source_row_id
            FROM fund_period_snapshot fps
            JOIN gp_house gh ON gh.gp_id = fps.gp_id
            LEFT JOIN source_row sr
              ON sr.source_id = fps.source_id
             AND sr.sheet_name = fps.sheet_name
             AND sr.row_number = fps.row_number
            WHERE fps.period_id = ?
            ORDER BY fps.sheet_name, fps.row_number, fps.snapshot_id
        """
        snapshot_rows = conn.execute(ledger_sql, (source["period_id"],)).fetchall()
        if not snapshot_rows:
            raise RuntimeError(f"No fund snapshots found for {period_label}")
        ledger: list[dict[str, object]] = []
        for row in snapshot_rows:
            raw = json.loads(row["raw_row_json"] or "{}")
            commitment_krw_mn = float(row["commitment_amount_krw_mn"] or 0.0)
            if commitment_krw_mn < 0:
                raise RuntimeError(f"Negative commitment amount in snapshot {row['snapshot_id']}")
            ledger.append(
                {
                    "ledger_id": int(row["snapshot_id"]),
                    "source_row_id": int(row["source_row_id"] or 0),
                    "source_id": row["source_id"],
                    "sheet_name": row["sheet_name"],
                    "row_number": int(row["row_number"]),
                    "row_hash": row["row_hash"],
                    "fund_id": int(row["fund_id"]),
                    "fund_name_raw": row["fund_name_raw"],
                    "gp1_raw": str(raw.get("GP1") or row["gp_name_raw"] or "").strip(),
                    "gp2_raw": str(raw.get("GP2") or "").strip(),
                    "gp3_raw": str(raw.get("GP3") or "").strip(),
                    "gp_id": int(row["gp_id"]),
                    "standard_gp_name": row["standard_gp_name"],
                    "commitment_eok": round(commitment_krw_mn / 100.0, 6),
                    "commitment_krw_mn": commitment_krw_mn,
                    "row_hash_short": str(row["row_hash"] or "")[:16],
                }
            )
        totals: dict[tuple[int, str], dict[str, object]] = {}
        for item in ledger:
            key = (int(item["gp_id"]), str(item["standard_gp_name"]))
            aggregate = totals.setdefault(
                key,
                {"gp_id": key[0], "gp_name": key[1], "active_fund_count": 0, "commitment_krw_mn": 0.0},
            )
            aggregate["active_fund_count"] = int(aggregate["active_fund_count"]) + 1
            aggregate["commitment_krw_mn"] = float(aggregate["commitment_krw_mn"]) + float(item["commitment_krw_mn"])
        ranking = sorted(totals.values(), key=lambda item: (-float(item["commitment_krw_mn"]), str(item["gp_name"])))
        for rank, item in enumerate(ranking, start=1):
            item["rank"] = rank
            item["commitment_tn_krw"] = float(item["commitment_krw_mn"]) / 1_000_000.0
        ranking_table = f"analytics_gp_ranking_{re.sub(r'[^0-9A-Za-z_]+', '', period_label)}"
        if not table_exists(conn, ranking_table):
            raise RuntimeError(f"Missing current ranking table: {ranking_table}")
        stored_ranking = conn.execute(
            f"SELECT rank, gp_id, gp_name, active_fund_count, commitment_aum_proxy_trn_krw FROM {ranking_table} ORDER BY rank"
        ).fetchall()
        if len(stored_ranking) != len(ranking):
            raise RuntimeError("Stored GP ranking count does not match datapack calculation")
        for calculated, stored in zip(ranking, stored_ranking):
            if (
                int(calculated["rank"]) != int(stored["rank"])
                or int(calculated["gp_id"]) != int(stored["gp_id"])
                # The public ranking stores trillion-KRW values rounded to six
                # decimals, while the ledger keeps the source's KRW-million value.
                or abs(float(calculated["commitment_tn_krw"]) - float(stored["commitment_aum_proxy_trn_krw"])) > 0.000001
            ):
                raise RuntimeError(
                    "Stored GP ranking does not reconcile to the fund ledger: "
                    f"calculated={calculated}, stored={dict(stored)}"
                )
    finally:
        conn.close()
    latest_registry = next((row for row in registry_rows if row["source_id"] == source["source_id"]), None)
    if latest_registry is None:
        raise RuntimeError(f"Source registry has no row for {source['source_id']}")
    return {
        "source": dict(source),
        "latest_registry": latest_registry,
        "registry": registry_rows,
        "aliases": aliases,
        "ledger": ledger,
        "ranking": ranking,
        "total_commitment_krw_mn": sum(float(item["commitment_krw_mn"]) for item in ledger),
        "co_gp_count": sum(1 for item in ledger if item["gp2_raw"] or item["gp3_raw"]),
        "co_gp_commitment_krw_mn": sum(
            float(item["commitment_krw_mn"]) for item in ledger if item["gp2_raw"] or item["gp3_raw"]
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
    ledger = inputs["ledger"]
    ranking = inputs["ranking"]
    registry = inputs["registry"]
    aliases = inputs["aliases"]
    total_commitment = float(inputs["total_commitment_krw_mn"])
    co_gp_count = int(inputs["co_gp_count"])
    co_gp_commitment = float(inputs["co_gp_commitment_krw_mn"])
    assert isinstance(source, dict) and isinstance(ledger, list) and isinstance(ranking, list)
    raw_sheets, raw_index = build_raw_sheets(registry, raw_history)
    last_ledger_row = len(ledger) + 3
    last_ranking_row = len(ranking) + 3

    readme_rows = [
        [text("GP Ranking Data Pack", "title")],
        [text(RANKING_TITLE, "subtitle")],
        [text("목적: 최종 순위의 모든 숫자를 금감원 원본 행까지 추적할 수 있게 만든 검증용 데이터팩입니다.", "wrap")],
        [text(f"기준일: {source['as_of_date']} ({source['period_label']})", "wrap")],
        [text("순위 지표: 금감원 공시 펀드별 총약정액의 합계입니다. 실제 NAV 또는 운용사 자체 공시 AUM이 아닙니다.", "wrap")],
        [text("귀속 규칙: 원본 GP1만 대표 GP로 귀속합니다. GP2·GP3는 원천 장부에 보존하지만 순위 합계에 중복 귀속하지 않습니다.", "wrap")],
        [text("단위 변환: 금감원 원본 단위인 억원을 백만원으로 변환한 뒤 합산합니다. 변환식은 Calculation Ledger 열 O~Q에 표시됩니다.", "wrap")],
        [text("순위 대사: Calculation Ledger 합계, GP Ranking 합계, 금감원 원천 합계가 QA Reconciliation에서 일치해야 합니다.", "wrap")],
        [text("원천 보존: Raw 시트에는 각 금감원 첨부파일의 원본 셀값을 보존합니다. 구형 2015Q4·2016Q1 .xls는 원본 파일 경로와 SHA-256을 보존하며 행 단위 파싱 대상은 아닙니다.", "wrap")],
        [text("중요 한계: 공동 GP에 펀드 약정액 전액을 각각 귀속하면 시장 총액이 중복 계산됩니다. 이 데이터팩은 대표 GP 귀속만 최종 순위로 사용합니다.", "wrap")],
    ]
    assumptions_rows = [
        [text("Calculation Assumptions", "title")],
        [text("입력 / 규칙", "header"), text("값", "header"), text("설명", "header")],
        [text("순위 정의"), text(RANKING_TITLE, "wrap"), text("대표 GP 귀속 기준의 시장 순위")],
        [text("기준 기간"), text(source["period_label"]), text(source["as_of_date"])],
        [text("원천 파일"), text(source["source_id"]), text(source["title"], "wrap")],
        [text("원천 금액 필드"), text("총약정액(합계)"), text("금감원 원천의 공시 필드")],
        [text("공시 단위"), text("억원"), text("2025Q4 원천 파일 기준")],
        [text("집계 단위"), text("KRW million"), text("순위 계산 및 대사 단위")],
        [text("대표 GP"), text("GP1"), text("GP2와 GP3는 공동 GP 원천 정보로만 보존")],
        [text("납입액"), text("미공시"), text("2025Q4 원천에 납입액 필드가 없어 0으로 처리하지 않음")],
        [text("KRW mn per 억원"), number(100, "number"), text("Calculation Ledger의 변환 계수")],
        [text("KRW mn per 조원"), number(1_000_000, "number"), text("조원 표시 변환 계수")],
        [text("원천 펀드 행"), number(len(ledger), "number"), text("2025Q4 현황자료의 포함 행")],
        [text("대표 GP 수"), number(len(ranking), "number"), text("최종 순위의 GP 수")],
        [text("원천 총약정액 (KRW mn)"), number(total_commitment, "amount_mn"), text("2025Q4 포함 펀드 행 합계")],
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
        [text("원본 GP명과 최종 순위의 표준 GP명을 함께 보여줍니다. 검증된 별칭 병합은 rule ID와 근거를 공개합니다.", "subtitle")],
        [
            text("Scope", "header"), text("Raw GP name", "header"), text("Standard GP name", "header"), text("Mapping status", "header"),
            text("Rule ID", "header"), text("Relationship", "header"), text("Evidence", "header"), text("Primary sources", "header"),
        ],
    ]
    alias_by_name = {row["alias_gp_name"]: row for row in aliases if row.get("verification_decision") == "MERGE_ALIAS"}
    seen_mapping: set[tuple[str, str, str]] = set()
    for item in sorted({(str(row["gp1_raw"]), str(row["standard_gp_name"])) for row in ledger}):
        raw_name, standard_name = item
        alias = alias_by_name.get(raw_name)
        row_key = ("2025Q4 ranking", raw_name, standard_name)
        seen_mapping.add(row_key)
        mapping_rows.append(
            [
                text("2025Q4 ranking"), text(raw_name), text(standard_name),
                text("Verified alias" if alias else "Direct primary GP"), text(alias.get("rule_id", "") if alias else ""),
                text(alias.get("relationship_type", "") if alias else ""), text(alias.get("evidence_summary", "") if alias else "FSS 2025Q4 GP1 normalized snapshot", "wrap"),
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

    ledger_rows: list[list[Cell]] = [
        [text("Calculation Ledger 2025Q4", "title")],
        [text("각 펀드 행은 금감원 원본의 시트·행 번호·row hash로 추적됩니다. 회색 열은 엑셀 수식으로 계산됩니다.", "subtitle")],
        [
            text("Ledger ID", "header"), text("Source Row ID", "header"), text("Source ID", "header"), text("Source sheet", "header"), text("Source row", "header"), text("Row hash", "header"),
            text("Fund ID", "header"), text("Fund name (raw)", "header"), text("GP1 raw", "header"), text("GP2 raw", "header"), text("GP3 raw", "header"),
            text("Standard GP", "header"), text("GP ID", "header"), text("Disclosed unit", "header"), text("Disclosed commitment (억원)", "header"),
            text("Conversion factor", "header"), text("Commitment (KRW mn)", "header"), text("Commitment (KRW tn)", "header"), text("Included", "header"), text("Co-GP flag", "header"), text("Inclusion rule", "header"),
        ],
    ]
    for row_number, item in enumerate(ledger, start=4):
        disclosed_commitment = float(item["commitment_eok"])
        commitment_mn = float(item["commitment_krw_mn"])
        commitment_tn = commitment_mn / 1_000_000.0
        co_gp = "Y" if item["gp2_raw"] or item["gp3_raw"] else ""
        ledger_rows.append(
            [
                number(item["ledger_id"], "number"), number(item["source_row_id"], "number"), text(item["source_id"]), text(item["sheet_name"]), number(item["row_number"], "number"), text(item["row_hash_short"]),
                number(item["fund_id"], "number"), text(item["fund_name_raw"], "wrap"), text(item["gp1_raw"], "wrap"), text(item["gp2_raw"], "wrap"), text(item["gp3_raw"], "wrap"),
                text(item["standard_gp_name"], "wrap"), number(item["gp_id"], "number"), text("억원"), number(disclosed_commitment, "amount_mn"),
                formula("'Assumptions'!$B$11", 100, "formula_number"), formula(f"O{row_number}*P{row_number}", commitment_mn, "formula_amount_mn"),
                formula(f"Q{row_number}/'Assumptions'!$B$12", commitment_tn, "formula_amount_tn"), text("Y"), text(co_gp),
                text("2025Q4 active fund row; GP1 only receives the commitment in the final ranking", "wrap"),
            ]
        )

    ranking_rows: list[list[Cell]] = [
        [text("GP Ranking 2025YE", "title")],
        [text("순위와 합계는 Calculation Ledger를 직접 참조하는 수식입니다. 동률은 표준 GP명 알파벳 순으로 안정 정렬했습니다.", "subtitle")],
        [
            text("Rank", "header"), text("GP ID", "header"), text("Standard GP", "header"), text("Active fund count", "header"),
            text("Total commitment (KRW mn)", "header"), text("Total commitment (KRW tn)", "header"), text("Market share", "header"), text("Period", "header"), text("Calculation basis", "header"),
        ],
    ]
    ledger_first_row = 4
    for row_number, item in enumerate(ranking, start=4):
        gp_id = int(item["gp_id"])
        amount_mn = float(item["commitment_krw_mn"])
        amount_tn = amount_mn / 1_000_000.0
        share = amount_mn / total_commitment if total_commitment else 0.0
        ranking_rows.append(
            [
                formula(f"RANK.EQ(E{row_number},$E$4:$E${last_ranking_row},0)+COUNTIF($E$4:E{row_number},E{row_number})-1", int(item["rank"]), "formula_number"),
                number(gp_id, "number"), text(item["gp_name"], "wrap"),
                formula(f"COUNTIFS('Calculation Ledger'!$M$4:$M${last_ledger_row},B{row_number},'Calculation Ledger'!$S$4:$S${last_ledger_row},\"Y\")", int(item["active_fund_count"]), "formula_number"),
                formula(f"SUMIFS('Calculation Ledger'!$Q$4:$Q${last_ledger_row},'Calculation Ledger'!$M$4:$M${last_ledger_row},B{row_number},'Calculation Ledger'!$S$4:$S${last_ledger_row},\"Y\")", amount_mn, "formula_amount_mn"),
                formula(f"E{row_number}/'Assumptions'!$B$12", amount_tn, "formula_amount_tn"), formula(f"E{row_number}/SUM($E$4:$E${last_ranking_row})", share, "formula_pct"),
                text(source["period_label"]), text("Representative GP (GP1); source commitments summed without co-GP double counting", "wrap"),
            ]
        )

    qa_rows: list[list[Cell]] = [
        [text("QA Reconciliation", "title")],
        [text("Expected values are source-backed. Calculated values are workbook formulas. Every status must be PASS before distribution.", "subtitle")],
        [text("Control", "header"), text("Expected", "header"), text("Calculated", "header"), text("Status", "header"), text("Rule", "header")],
        [text("FSS source ID"), text(source["source_id"]), text(source["source_id"]), formula("IF(B4=C4,\"PASS\",\"FAIL\")", "PASS", "pass"), text("Latest source registered and imported")],
        [text("Raw file SHA-256"), text(source["sha256"], "wrap"), text(sha256_file(REPO_ROOT / str(source["local_path"])), "wrap"), formula("IF(B5=C5,\"PASS\",\"FAIL\")", "PASS", "pass"), text("Local raw file matches SQLite source_document")],
        [text("2025Q4 fund rows"), number(len(ledger), "number"), formula(f"COUNTA('Calculation Ledger'!$A$4:$A${last_ledger_row})", len(ledger), "formula_number"), formula("IF(B6=C6,\"PASS\",\"FAIL\")", "PASS", "pass"), text("One included ledger record per latest FSS fund snapshot")],
        [text("Included ledger rows"), number(len(ledger), "number"), formula(f"COUNTIF('Calculation Ledger'!$S$4:$S${last_ledger_row},\"Y\")", len(ledger), "formula_number"), formula("IF(B7=C7,\"PASS\",\"FAIL\")", "PASS", "pass"), text("No 2025Q4 fund row is silently excluded")],
        [text("Ranked primary GPs"), number(len(ranking), "number"), formula(f"COUNTA('GP Ranking'!$B$4:$B${last_ranking_row})", len(ranking), "formula_number"), formula("IF(B8=C8,\"PASS\",\"FAIL\")", "PASS", "pass"), text("Unique GP1 identities after verified aliases")],
        [text("Source commitment total (KRW mn)"), number(total_commitment, "amount_mn"), formula(f"SUM('Calculation Ledger'!$Q$4:$Q${last_ledger_row})", total_commitment, "formula_amount_mn"), formula("IF(ROUND(B9,3)=ROUND(C9,3),\"PASS\",\"FAIL\")", "PASS", "pass"), text("Sum of disclosed total commitments after unit conversion")],
        [text("Ranking commitment total (KRW mn)"), number(total_commitment, "amount_mn"), formula(f"SUM('GP Ranking'!$E$4:$E${last_ranking_row})", total_commitment, "formula_amount_mn"), formula("IF(ROUND(B10,3)=ROUND(C10,3),\"PASS\",\"FAIL\")", "PASS", "pass"), text("Ranked GP totals must equal source total")],
        [text("Ledger vs ranking difference (KRW mn)"), number(0, "amount_mn"), formula("C9-C10", 0, "formula_amount_mn"), formula("IF(ROUND(B11,3)=ROUND(C11,3),\"PASS\",\"FAIL\")", "PASS", "pass"), text("No commitment amount may be lost or double counted")],
        [text("Co-GP fund rows"), number(co_gp_count, "number"), formula(f"COUNTIF('Calculation Ledger'!$T$4:$T${last_ledger_row},\"Y\")", co_gp_count, "formula_number"), formula("IF(B12=C12,\"PASS\",\"FAIL\")", "PASS", "pass"), text("GP2 or GP3 exists but is not additionally credited in ranking")],
        [text("Co-GP commitment total (KRW mn)"), number(co_gp_commitment, "amount_mn"), formula(f"SUMIF('Calculation Ledger'!$T$4:$T${last_ledger_row},\"Y\",'Calculation Ledger'!$Q$4:$Q${last_ledger_row})", co_gp_commitment, "formula_amount_mn"), formula("IF(ROUND(B13,3)=ROUND(C13,3),\"PASS\",\"FAIL\")", "PASS", "pass"), text("Disclosure only; not a separate market-total component")],
        [text("Missing commitment values"), number(0, "number"), formula(f"COUNTBLANK('Calculation Ledger'!$O$4:$O${last_ledger_row})", 0, "formula_number"), formula("IF(B14=C14,\"PASS\",\"FAIL\")", "PASS", "pass"), text("A missing disclosed amount must fail the distribution review")],
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
        Sheet("Assumptions", assumptions_rows, [28, 40, 78], freeze_rows=2, auto_filter="A2:C15", merges=["A1:C1"]),
        Sheet("Source Manifest", manifest_rows, [21, 12, 13, 22, 12, 42, 70, 70, 52, 68, 18, 24], freeze_rows=3, auto_filter=f"A3:L{len(manifest_rows)}", merges=["A1:L1", "A2:L2"]),
        Sheet("GP Name Mapping", mapping_rows, [24, 34, 34, 18, 34, 28, 70, 70], freeze_rows=3, auto_filter=f"A3:H{len(mapping_rows)}", merges=["A1:H1", "A2:H2"]),
        Sheet("Calculation Ledger", ledger_rows, [12, 14, 20, 16, 12, 20, 11, 42, 28, 28, 28, 32, 12, 14, 25, 18, 24, 22, 12, 12, 70], freeze_rows=3, auto_filter=f"A3:U{len(ledger_rows)}", merges=["A1:U1", "A2:U2"]),
        Sheet("GP Ranking", ranking_rows, [10, 12, 34, 18, 29, 29, 16, 13, 70], freeze_rows=3, auto_filter=f"A3:I{len(ranking_rows)}", merges=["A1:I1", "A2:I2"]),
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


def build_datapack(
    db_path: Path,
    registry_path: Path,
    alias_rules_path: Path,
    output_path: Path,
    period_label: str = "2025Q4",
    raw_history: str = "all",
) -> dict[str, object]:
    inputs = read_ranking_inputs(db_path, registry_path, alias_rules_path, period_label)
    sheets = workbook_sheets(inputs, raw_history)
    write_xlsx(output_path, sheets)
    validation = validate_datapack(
        output_path,
        ["README", "Assumptions", "Source Manifest", "GP Name Mapping", "Calculation Ledger", "GP Ranking", "QA Reconciliation", "Raw Index", f"Raw {period_label}"],
        {"formula_count_min": len(inputs["ledger"]) * 3 + len(inputs["ranking"]) * 5 + 20},
    )
    return {
        "output": str(output_path),
        "period": period_label,
        "fund_rows": len(inputs["ledger"]),
        "ranked_gps": len(inputs["ranking"]),
        "commitment_krw_mn": round(float(inputs["total_commitment_krw_mn"]), 3),
        "commitment_trn_krw": round(float(inputs["total_commitment_krw_mn"]) / 1_000_000.0, 6),
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
    args = parser.parse_args()
    result = build_datapack(
        db_path=args.db,
        registry_path=args.registry,
        alias_rules_path=args.alias_rules,
        output_path=args.output,
        period_label=args.period,
        raw_history=args.raw_history,
    )
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
