"""Read official attachment bodies without trusting previews or file extensions.

HWP5 paragraph controls follow Hancom's public file format specification:
https://tech.hancom.com/python-hwp-parsing-2/
HWPX body sections follow https://tech.hancom.com/hwpxformat/ .
This decoder preserves paragraphs and simple HWPX table cells. HWP5 table
coordinates are not inferred from paragraph order.
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
import zlib
from xml.etree import ElementTree as ET

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_SECTION_BYTES = 8 * 1024 * 1024
MAX_SECTIONS = 512
MAX_TEXT_CHARS = 4_000_000
_OLE = bytes.fromhex("d0cf11e0a1b11ae1")
_WIDE_CONTROLS = frozenset(range(1, 10)) | frozenset(range(11, 13)) | frozenset(range(14, 24))


def _paragraph(payload):
    if len(payload) % 2:
        raise ValueError("HWP paragraph has an incomplete UTF-16 character")
    units = struct.unpack("<" + "H" * (len(payload) // 2), payload)
    output, index = [], 0
    while index < len(units):
        code = units[index]
        if code in _WIDE_CONTROLS:
            if index + 8 > len(units):
                raise ValueError("HWP paragraph control is truncated")
            # Control payloads contain ASCII identifiers and numeric values;
            # decoding them as Unicode creates spurious text or amounts.
            if code == 9:
                output.append(9)
            index += 8
            continue
        if code in (10, 13):
            output.append(10)
        elif code in (30, 31):
            output.append(32)
        elif code >= 32:
            output.append(code)
        index += 1
    return struct.pack("<" + "H" * len(output), *output).decode("utf-16-le").strip("\n")


def _records(data):
    index = 0
    while index < len(data):
        if index + 4 > len(data):
            raise ValueError("HWP record header is truncated")
        header = struct.unpack_from("<I", data, index)[0]
        index += 4
        size = header >> 20
        if size == 0xFFF:
            if index + 4 > len(data):
                raise ValueError("HWP extended record length is truncated")
            size = struct.unpack_from("<I", data, index)[0]
            index += 4
        if index + size > len(data):
            raise ValueError("HWP record payload is truncated")
        yield header & 0x3FF, (header >> 10) & 0x3FF, data[index:index + size]
        index += size


def _inflate(data):
    inflater = zlib.decompressobj(-15)
    body = inflater.decompress(data, MAX_SECTION_BYTES + 1)
    if len(body) > MAX_SECTION_BYTES or inflater.unconsumed_tail:
        raise ValueError("HWP section exceeds extraction size limit")
    if not inflater.eof:
        raise ValueError("HWP compressed section is incomplete")
    if inflater.unused_data:
        # Real Hancom files also use a raw DEFLATE stream followed by the
        # gzip CRC32/ISIZE trailer. Validate it instead of silently ignoring it.
        if len(inflater.unused_data) != 8:
            raise ValueError("HWP compressed section has unexpected trailing data")
        checksum, size = struct.unpack("<II", inflater.unused_data)
        if checksum != zlib.crc32(body) or size != len(body):
            raise ValueError("HWP compressed section checksum or size mismatch")
    return body


def _hwp(raw):
    try:
        import olefile
    except ImportError as error:
        raise ValueError("HWP extraction requires olefile") from error
    with olefile.OleFileIO(io.BytesIO(raw), raise_defects=olefile.DEFECT_INCORRECT) as archive:
        header = archive.openstream("FileHeader").read()
        if len(header) < 40 or not header.startswith(b"HWP Document File\0") or header[35] != 5:
            raise ValueError("Unsupported HWP version or invalid FileHeader")
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & (2 | 4 | 256 | 512):
            raise ValueError("Encrypted, DRM or distribution HWP cannot be extracted")
        paths = [p for p in archive.listdir() if len(p) == 2 and p[0] == "BodyText"
                 and re.fullmatch(r"Section\d+", p[1])]
        paths.sort(key=lambda p: int(p[1][7:]))
        if not paths or len(paths) > MAX_SECTIONS:
            raise ValueError("HWP has no supported body sections")
        if [int(p[1][7:]) for p in paths] != list(range(len(paths))):
            raise ValueError("HWP body section numbering is incomplete")
        texts, expanded = [], 0
        for path in paths:
            if archive.get_size(path) > MAX_SECTION_BYTES:
                raise ValueError("HWP section exceeds extraction size limit")
            data = archive.openstream(path).read()
            data = _inflate(data) if flags & 1 else data
            expanded += len(data)
            if expanded > MAX_EXPANDED_BYTES:
                raise ValueError("HWP body exceeds extraction size limit")
            skip_level = None
            for tag, level, payload in _records(data):
                if skip_level is not None:
                    if level > skip_level:
                        continue
                    skip_level = None
                if tag == 71 and payload[:4] in (b"daeh", b"toof"):
                    skip_level = level
                elif tag == 67:
                    text = _paragraph(payload)
                    if text.strip():
                        texts.append(text)
        return {"format": "hwp", "text": "\n".join(texts), "tables": []}


def _local(element):
    return element.tag.rsplit("}", 1)[-1]


def _hwpx(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        items = archive.infolist()
        if len(items) > 2000 or sum(i.file_size for i in items) > MAX_EXPANDED_BYTES:
            raise ValueError("Attachment archive exceeds extraction size limit")
        names = [i.filename for i in items]
        if len(names) != len(set(names)) or any(i.flag_bits & 1 for i in items):
            raise ValueError("Duplicate or encrypted attachment archive members")
        sections = sorted([n for n in names if re.fullmatch(r"Contents/section\d+\.xml", n)],
                          key=lambda n: int(re.search(r"(\d+)\.xml$", n)[1]))
        if not sections:
            # XLSX and other auxiliary ZIP formats are not HWPX body evidence.
            return {"format": "zip", "text": "", "tables": []}
        if len(sections) > MAX_SECTIONS or [int(re.search(r"(\d+)\.xml$", n)[1]) for n in sections] != list(range(len(sections))):
            raise ValueError("HWPX body section numbering is incomplete")
        texts, tables = [], []

        def walk(element):
            kind = _local(element)
            if kind in {"header", "footer", "secPr", "masterPage", "memo", "comment"}:
                return ""
            if kind == "tbl":
                grid = table(element)
                tables.append(grid)
                return "\n".join("\t".join(row) for row in grid)
            if kind == "t":
                return (element.text or "") + "".join(walk(c) + (c.tail or "") for c in element)
            if kind in {"lineBreak", "br"}:
                return "\n"
            if kind == "tab":
                return "\t"
            value = "".join(walk(c) for c in element)
            return value + ("\n" if kind == "p" else "")

        def table(element):
            rows = [e for e in element if _local(e) == "tr"]
            nr, nc = int(element.get("rowCnt", len(rows))), int(element.get("colCnt", 0))
            if not 0 < nr <= 1000 or not 0 < nc <= 100 or nr * nc > 10000 or len(rows) != nr:
                raise ValueError("HWPX table dimensions are invalid")
            grid = [[None] * nc for _ in range(nr)]
            for row in rows:
                for cell in [e for e in row if _local(e) == "tc"]:
                    if any(_local(e) == "tbl" for e in cell.iter()):
                        raise ValueError("Nested HWPX tables require structural review")
                    addr = next((e for e in cell if _local(e) == "cellAddr"), None)
                    span = next((e for e in cell if _local(e) == "cellSpan"), None)
                    if addr is None or span is None or int(span.get("rowSpan", 1)) != 1 or int(span.get("colSpan", 1)) != 1:
                        raise ValueError("Merged or unaddressed HWPX cells require structural review")
                    r, c = int(addr.get("rowAddr", -1)), int(addr.get("colAddr", -1))
                    if not (0 <= r < nr and 0 <= c < nc) or grid[r][c] is not None:
                        raise ValueError("HWPX table cell address is invalid or duplicated")
                    grid[r][c] = "".join(walk(e) for e in cell if _local(e) == "subList").strip()
            if any(cell is None for row in grid for cell in row):
                raise ValueError("HWPX table grid has missing cells")
            return grid

        for name in sections:
            if archive.getinfo(name).file_size > MAX_SECTION_BYTES:
                raise ValueError("HWPX section exceeds extraction size limit")
            data = archive.read(name).decode("utf-8-sig")
            if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", data, re.I):
                raise ValueError("HWPX XML declarations are unsupported")
            root = ET.fromstring(data)
            if root.tag != "{http://www.hancom.co.kr/hwpml/2011/section}sec":
                raise ValueError("HWPX section root is invalid")
            texts.append(walk(root).strip())
        return {"format": "hwpx", "text": "\n".join(texts), "tables": tables}


def extract_attachment(raw: bytes) -> dict:
    """Return complete body evidence or raise ValueError; never use PrvText."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_FILE_BYTES:
        raise ValueError("Attachment is empty or exceeds extraction size limit")
    try:
        if raw.startswith(_OLE):
            result = _hwp(raw)
        elif raw.startswith(b"PK"):
            result = _hwpx(raw)
        elif raw.startswith(b"%PDF"):
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted or len(reader.pages) > 500:
                raise ValueError("PDF is encrypted or exceeds extraction page limit")
            parts, length = [], 0
            for page in reader.pages:
                text = page.extract_text() or ""
                length += len(text)
                if length > MAX_TEXT_CHARS:
                    raise ValueError("PDF text exceeds extraction size limit")
                parts.append(text)
            result = {"format": "pdf", "text": "\n".join(parts), "tables": []}
        else:
            raise ValueError("Unsupported attachment format")
        if len(result["text"]) > MAX_TEXT_CHARS or (not result["text"].strip() and result["format"] != "zip"):
            raise ValueError("Attachment has no readable body or exceeds text limit")
        return result
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"Attachment extraction failed: {type(error).__name__}") from error
