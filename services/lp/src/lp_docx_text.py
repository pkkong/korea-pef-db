"""Bounded WordprocessingML body text, without headers, comments or revisions."""
import re
from xml.etree import ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def extract_docx(archive, max_section_bytes):
    name = 'word/document.xml'
    if archive.getinfo(name).file_size > max_section_bytes:
        raise ValueError('DOCX body exceeds extraction size limit')
    xml = archive.read(name).decode('utf-8-sig')
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)', xml, re.I):
        raise ValueError('DOCX XML declarations are unsupported')
    root = ET.fromstring(xml)
    bodies = root.findall(W + 'body')
    if root.tag != W + 'document' or len(bodies) != 1:
        raise ValueError('DOCX body root is missing or unsupported')
    tables = []
    def walk(n):
        if n.tag in {W + k for k in ('del', 'moveFrom', 'instrText', 'drawing', 'pict', 'sectPr')}:
            return ''
        if n.tag == W + 'r' and n.find(W + 'rPr/' + W + 'vanish') is not None:
            return ''
        if n.tag == W + 't':
            return n.text or ''
        if n.tag in {W + 'br', W + 'cr'}:
            return '\n'
        if n.tag == W + 'tab':
            return '\t'
        if n.tag == W + 'tbl':
            rows = []
            for row in n.findall(W + 'tr'):
                cells = row.findall(W + 'tc')
                rows.append([''.join(walk(x) for x in cell if x.tag != W + 'tcPr').strip() for cell in cells])
            # Retain actual text even when merged cells lack a reliable grid.
            if next(n.iter(W + 'vMerge'), None) is None and next(n.iter(W + 'gridSpan'), None) is None:
                tables.append(rows)
            return '\n'.join('\t'.join(row) for row in rows) + '\n'
        return ''.join(walk(x) for x in n) + ('\n' if n.tag == W + 'p' else '')
    return {'format': 'docx', 'text': walk(bodies[0]).strip(), 'tables': tables}
