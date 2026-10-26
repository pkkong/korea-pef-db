"""Constructed format fixtures; no network or selected notice/value registry."""
import io
import random
import struct
import unittest
import zipfile
import zlib
from unittest.mock import patch

from services.lp.src.lp_attachment_text import extract_attachment, _paragraph, _records, _inflate


def record(text=None, payload=None, extended=False):
    data = text.encode("utf-16-le") if text is not None else payload
    tag = 67 if text is not None else 72
    return struct.pack("<I", tag | ((0xFFF if extended else len(data)) << 20)) + (struct.pack("<I", len(data)) if extended else b"") + data


def compound(sections, flags=1, preview="misleading preview", body=True):
    """Minimal CFB v3, regular streams with >=4096 bytes to avoid mini-FAT."""
    end, free = 0xFFFFFFFE, 0xFFFFFFFF
    file_header = bytearray(4096)
    file_header[:18] = b"HWP Document File\0"
    struct.pack_into("<I", file_header, 32, 0x05000300)
    struct.pack_into("<I", file_header, 36, flags)
    streams = [("FileHeader", bytes(file_header), None)]
    entropy = random.Random(7).randbytes(6000)
    for i, payload in enumerate(sections):
        data = payload + record(payload=entropy, extended=True)
        if flags & 1:
            compressor = zlib.compressobj(wbits=-15)
            data = compressor.compress(data) + compressor.flush()
        streams.append((f"Section{i}", data, "BodyText"))
    streams.append(("PrvText", preview.encode("utf-16-le").ljust(4096, b"\0"), None))
    # Directory: root, FileHeader, BodyText storage, Section*, PrvText.
    directory_count = len(streams) + 2
    dir_sectors = (directory_count * 128 + 511) // 512
    sector = dir_sectors
    allocations = []
    for name, data, storage in streams:
        count = (len(data) + 511) // 512
        allocations.append((name, data, storage, sector, count))
        sector += count
    fat_sector = sector
    if fat_sector >= 128:
        raise AssertionError("test CFB needs a second FAT")
    header = bytearray(512)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHH", header, 24, 0x3E, 3, 0xFFFE, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into("<IIIIIIIII", header, 40, 0, 1, 0, 0, 4096, end, 0, end, 0)
    struct.pack_into("<109I", header, 76, fat_sector, *([free] * 108))
    fat = [free] * 128
    for i in range(dir_sectors):
        fat[i] = i + 1 if i + 1 < dir_sectors else end
    for _, _, _, start, count in allocations:
        for i in range(start, start + count):
            fat[i] = i + 1 if i + 1 < start + count else end
    fat[fat_sector] = 0xFFFFFFFD

    def entry(name, kind, start=end, size=0, child=free, right=free):
        data = bytearray(128)
        encoded = (name + "\0").encode("utf-16-le")
        data[:len(encoded)] = encoded
        struct.pack_into("<HBBIII", data, 64, len(encoded), kind, 1, free, right, child)
        struct.pack_into("<IQ", data, 116, start, size)
        return data

    entries = [entry("Root Entry", 5, child=1)]
    entries.append(entry("FileHeader", 2, allocations[0][3], len(allocations[0][1]), right=2))
    preview_index = len(sections) + 3
    entries.append(entry("BodyText" if body else "OtherStorage", 1, child=3 if sections else free, right=preview_index))
    for i, allocation in enumerate(allocations[1:-1]):
        entries.append(entry(allocation[0], 2, allocation[3], len(allocation[1]), right=i + 4 if i + 1 < len(sections) else free))
    allocation = allocations[-1]
    entries.append(entry("PrvText", 2, allocation[3], len(allocation[1])))
    directory = b"".join(entries).ljust(dir_sectors * 512, b"\0")
    return bytes(header) + directory + b"".join(data.ljust(count * 512, b"\0") for _, data, _, _, count in allocations) + struct.pack("<128I", *fat)


def hwpx(sections, extras=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        for i, text in enumerate(sections):
            archive.writestr(f"Contents/section{i}.xml", text)
        for name, text in (extras or {}).items():
            archive.writestr(name, text)
    return output.getvalue()


def section(content):
    return '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">' + content + '</hs:sec>'


def para(text):
    return '<hp:p><hp:run><hp:t>' + text + '</hp:t></hp:run></hp:p>'


def cell(text, row, col, span=1):
    return f'<hp:tc><hp:subList>{para(text)}</hp:subList><hp:cellAddr rowAddr="{row}" colAddr="{col}"/><hp:cellSpan rowSpan="1" colSpan="{span}"/></hp:tc>'


class AttachmentTextTests(unittest.TestCase):
    def test_pdf_null_glyphs_preserve_word_and_amount_boundaries(self):
        from types import SimpleNamespace
        page = SimpleNamespace(extract_text=lambda: '100\x00200억원\n주목적\t국내 PE')
        with patch('pypdf.PdfReader', return_value=SimpleNamespace(is_encrypted=False, pages=[page])):
            value = extract_attachment(b'%PDF constructed test')
        self.assertEqual(value['text'], '100 200억원\n주목적\t국내 PE')

    def test_hwp_compressed_full_body_multiple_sections_not_preview(self):
        value = extract_attachment(compound([record("First paragraph\r") + record("Second paragraph\r"), record("Final body\r")]))
        self.assertEqual(value, {"format": "hwp", "text": "First paragraph\nSecond paragraph\nFinal body", "tables": []})

    def test_hwp_uncompressed_and_extended_records(self):
        self.assertEqual(extract_attachment(compound([record("Body", extended=True)], flags=0))["text"], "Body")

    def test_hwp_deflate_trailer_validates_crc_and_original_size(self):
        data = record("Complete body")
        compressor = zlib.compressobj(wbits=-15)
        compressed = compressor.compress(data) + compressor.flush()
        trailer = struct.pack("<II", zlib.crc32(data), len(data))
        self.assertEqual(_inflate(compressed + trailer), data)
        for tail in [b"x", struct.pack("<II", 0, len(data)), struct.pack("<II", zlib.crc32(data), len(data) + 1)]:
            with self.assertRaises(ValueError):
                _inflate(compressed + tail)

    def test_hwp_controls_strip_payload_preserve_tab_and_surrogates(self):
        ctrl = struct.pack("<8H", 11, *([0x3500] * 6), 11)
        tab = struct.pack("<8H", 9, *([0x3100] * 6), 9)
        payload = "A".encode("utf-16-le") + ctrl + tab + "10억원😀\r".encode("utf-16-le")
        self.assertEqual(_paragraph(payload), "A\t10억원😀")

    def test_hwp_rejects_control_and_record_truncation(self):
        for payload in [b"\x02\x00", b"\x41", b"\x00\xd8"]:
            with self.assertRaises((ValueError, UnicodeError)):
                _paragraph(payload)
        for payload in [b"a", struct.pack("<I", 67 | (10 << 20)) + b"xx", struct.pack("<I", 67 | (4095 << 20))]:
            with self.assertRaises(ValueError):
                list(_records(payload))

    def test_hwp_rejects_password_distribution_drm_and_preview_only(self):
        for flags in [2, 4, 256, 512]:
            with self.assertRaisesRegex(ValueError, "Encrypted"):
                extract_attachment(compound([record("Body")], flags=flags))
        with self.assertRaisesRegex(ValueError, "body sections"):
            extract_attachment(compound([record("Body")], body=False))

    def test_hwp_expansion_limit_is_enforced(self):
        with patch("services.lp.src.lp_attachment_text.MAX_SECTION_BYTES", 10000):
            with self.assertRaisesRegex(ValueError, "size limit"):
                extract_attachment(compound([record("x" * 9000, extended=True)]))

    def test_hwpx_body_sections_skip_header_xml_and_inline_header(self):
        doc = hwpx([section(para("First") + '<hp:header>' + para("Fake amount") + '</hp:header>' + para("Second")), section(para("Third"))], {"Contents/header.xml": "malformed ignored", "Preview/PrvText.txt": "Fake preview"})
        value = extract_attachment(doc)
        self.assertEqual(value["text"], "First\nSecond\nThird")

    def test_hwpx_table_uses_cell_addresses_not_xml_order(self):
        table = '<hp:tbl rowCnt="2" colCnt="2"><hp:tr>' + cell("B", 0, 1) + cell("A", 0, 0) + '</hp:tr><hp:tr>' + cell("20", 1, 1) + cell("10", 1, 0) + '</hp:tr></hp:tbl>'
        value = extract_attachment(hwpx([section(table)]))
        self.assertEqual(value["tables"], [[["A", "B"], ["10", "20"]]])
        self.assertEqual(value["text"], "A\tB\n10\t20")

    def test_hwpx_merged_cells_keep_only_the_source_anchor_value(self):
        cells=cell("PE 600억원",0,0,span=2)
        value=extract_attachment(hwpx([section('<hp:tbl rowCnt="1" colCnt="2"><hp:tr>'+cells+'</hp:tr></hp:tbl>')]))
        self.assertEqual(value['tables'],[[['PE 600억원','']]])
        self.assertEqual(value['text'].count('600'),1)
        rows='<hp:tr>'+cell('PE',0,0).replace('rowSpan="1"','rowSpan="2"')+cell('600',0,1)+'</hp:tr><hp:tr>'+cell('2개사',1,1)+'</hp:tr>'
        value=extract_attachment(hwpx([section('<hp:tbl rowCnt="2" colCnt="2">'+rows+'</hp:tbl>')]))
        self.assertEqual(value['tables'],[[['PE','600'],['','2개사']]])

    def test_hwpx_missing_overlapping_or_out_of_bounds_cells_are_rejected(self):
        for cells in [cell("A", 0, 0, span=3), cell("A",0,0,span=0),
                      cell("A",0,0,span=2)+cell("B",0,1), cell("A",0,0),
                      cell("A", 0, 0) + cell("B", 0, 0),
                      cell('A',0,0).replace('<hp:cellAddr rowAddr="0" colAddr="0"/>','')]:
            with self.assertRaises(ValueError):
                extract_attachment(hwpx([section('<hp:tbl rowCnt="1" colCnt="2"><hp:tr>' + cells + '</hp:tr></hp:tbl>')]))

    def test_nested_hwpx_tables_preserve_explicit_grids_and_enforce_depth(self):
        def enclosing(inner):
            return ('<hp:tbl rowCnt="1" colCnt="1"><hp:tr><hp:tc><hp:subList><hp:p><hp:run>'
                    +inner+'</hp:run></hp:p></hp:subList><hp:cellAddr rowAddr="0" colAddr="0"/>'
                    '<hp:cellSpan rowSpan="1" colSpan="1"/></hp:tc></hp:tr></hp:tbl>')
        inner='<hp:tbl rowCnt="1" colCnt="2"><hp:tr>'+cell('PEF',0,0)+cell('600억원',0,1)+'</hp:tr></hp:tbl>'
        result=extract_attachment(hwpx([section(enclosing(inner))]))
        self.assertEqual(result['tables'][0],[['PEF','600억원']])
        self.assertEqual(result['text'].count('600억원'),1)
        for _ in range(9):inner=enclosing(inner)
        with self.assertRaisesRegex(ValueError,'nesting'):
            extract_attachment(hwpx([section(inner)]))

    def test_hwpx_entities_and_archive_expansion_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "declarations"):
            extract_attachment(hwpx(['<!DOCTYPE a [<!ENTITY a "value">]>' + section(para("&a;"))]))
        with patch("services.lp.src.lp_attachment_text.MAX_EXPANDED_BYTES", 20):
            with self.assertRaisesRegex(ValueError, "size limit"):
                extract_attachment(hwpx([section(para("Text"))]))

    def test_xlsx_or_generic_zip_is_auxiliary_not_hwpx(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("xl/worksheets/sheet1.xml", "100亿元")
        self.assertEqual(extract_attachment(output.getvalue()), {"format": "zip", "text": "", "tables": []})

    def test_empty_html_corrupt_ole_and_truncated_zip_fail(self):
        for raw in [b"", b"<html>access denied</html>", bytes.fromhex("d0cf11e0a1b11ae1") + b"x", b"PKxx"]:
            with self.assertRaises(ValueError):
                extract_attachment(raw)

    def test_input_size_limit_is_enforced(self):
        with patch("services.lp.src.lp_attachment_text.MAX_FILE_BYTES", 3):
            with self.assertRaisesRegex(ValueError, "size limit"):
                extract_attachment(b"1234")

    def test_pdf_body_and_encryption_not_empty_or_preview(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=100, height=100)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 10 Tf 10 10 Td (Full PDF body) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        output = io.BytesIO()
        writer.write(output)
        self.assertEqual(extract_attachment(output.getvalue())["text"], "Full PDF body")
        writer.encrypt("protected")
        encrypted = io.BytesIO()
        writer.write(encrypted)
        with self.assertRaisesRegex(ValueError, "encrypted"):
            extract_attachment(encrypted.getvalue())

    def test_hwpx_rejects_spoofed_section_root(self):
        with self.assertRaisesRegex(ValueError, "root"):
            extract_attachment(hwpx(["<sec><p>Unrelated XML</p></sec>"]))


if __name__ == "__main__":
    unittest.main()
