"""Pure parsers for observed Teachers' Pension and Credit Union notice boards.

A valid empty search returns []; incomplete pages, wrong boards and conflicting
metadata fail explicitly. Networking and publication decisions belong elsewhere.
"""
from __future__ import annotations

import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit


class _Node:
    def __init__(self, tag='', attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def nodes(self, tag=None, cls=None):
        for child in self.children:
            if isinstance(child, _Node):
                if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get('class', '').split()):
                    yield child
                yield from child.nodes(tag, cls)

    def text(self):
        if self.tag in {'script', 'style'}:
            return ''
        if self.tag == 'img':
            return self.attrs.get('alt', '')
        return ' '.join(child.text() if isinstance(child, _Node) else child for child in self.children)

    def clean(self):
        return re.sub(r'\s+', ' ', self.text()).strip()


class _Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = _Node()
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in {'br', 'img', 'hr', 'meta', 'link', 'input', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'col'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def _one(nodes, label):
    values = list(nodes)
    if len(values) != 1:
        raise ValueError(f'{label}: missing or ambiguous official markup')
    return values[0]


def _host(url):
    value = urlsplit(url)
    if value.scheme != 'https' or not value.hostname or value.username or value.password or value.port not in {None, 443}:
        raise ValueError('Invalid official HTTPS URL')
    return value.hostname.lower().removeprefix('www.')


def _config(url, config, detail=False):
    institution = config.get('institution_id')
    if institution not in {'tp', 'cu'}:
        raise ValueError('Unsupported pension board institution')
    expected_host = 'tp.or.kr' if institution == 'tp' else 'cu.co.kr'
    listing = config.get('listing_url', '')
    if _host(listing) != expected_host or _host(url) != expected_host:
        raise ValueError('Institution board host mismatch')
    listing_path = '/tp-kr/bbs/i-151/list.do' if institution == 'tp' else '/cu/na/ntt/selectNttList.do'
    detail_path = '/tp-kr/bbs/i-151/detail.do' if institution == 'tp' else '/cu/na/ntt/selectNttInfo.do'
    if urlsplit(listing).path != listing_path or urlsplit(url).path != (detail_path if detail else listing_path):
        raise ValueError('Institution board route mismatch')
    for checked in [listing, url]:
        query = parse_qs(urlsplit(checked).query)
        if institution == 'cu':
            if (checked == listing or not detail) and query.get('bbsId') != ['1020']:
                raise ValueError('CU board identity mismatch')
            if 'bbsId' in query and query['bbsId'] != ['1020']:
                raise ValueError('CU board identity mismatch')
            if 'mi' in query and query['mi'] != ['100007']:
                raise ValueError('CU menu identity mismatch')
    return institution


def _identifier(url, institution):
    values = parse_qs(urlsplit(url).query).get('ntt_sn' if institution == 'tp' else 'nttSn', [])
    if len(values) != 1 or not re.fullmatch(r'\d+', values[0]):
        raise ValueError('Missing or ambiguous observed notice identifier')
    return values[0]


def _date(text):
    values = set()
    for match in re.finditer(r'(?<!\d)(20\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})(?!\d)', text):
        values.add(date(*map(int, match.groups())).isoformat())
    if len(values) != 1:
        raise ValueError('Missing or conflicting publication date')
    return values.pop()


def _label_date(nodes, label):
    return _date(_one((n for n in nodes if label in n.clean()), label).clean())


def parse_listing(html: str, url: str, config: dict) -> list[dict]:
    institution = _config(url, config)
    root, result = _Document(html).root, {}
    if institution == 'tp':
        container = _one((n for n in root.nodes('form') if n.attrs.get('id') == 'frmBbs'), 'TP search form')
        empty = any('공지사항 데이터가 없습니다.' in n.clean() for n in container.nodes('div', 'no-data'))
        rows = list(container.nodes('div', 'tit_box'))
    else:
        container = _one(root.nodes('div', 'bbs_ListA'), 'CU notice table')
        for node in root.nodes('input'):
            if node.attrs.get('name') == 'bbsId' and node.attrs.get('value', '').isdigit() and node.attrs.get('value') != '1020':
                raise ValueError('CU HTML board identity mismatch')
        empty = any('등록된 글이 없습니다.' in n.clean() for n in container.nodes('tr', 'no_date'))
        rows = list(container.nodes('tr'))
    for row in rows:
        anchors = [a for a in row.nodes('a') if ('detail.do?' if institution == 'tp' else 'selectNttInfo.do?') in a.attrs.get('href', '')]
        if not anchors:
            continue
        anchor = _one(anchors, 'Notice link')
        target = urljoin(url, anchor.attrs['href'])
        _config(target, config, detail=True)
        ident = _identifier(target, institution)
        title = anchor.clean()
        if not title:
            raise ValueError('Notice title missing')
        published = (_label_date(row.nodes('li'), '등록일') if institution == 'tp'
                     else _date(_one((n for n in row.nodes('td') if n.attrs.get('data-table') == 'date'), 'CU registration cell').clean()))
        item = {'url': target, 'title': title, 'date': published, 'source_id': f'{institution}:{ident}'}
        if target in result and item != result[target]:
            raise ValueError('Conflicting duplicate listing row')
        result[target] = item
    if empty and result:
        raise ValueError('Empty marker conflicts with listing rows')
    if not result and not empty:
        raise ValueError('Incomplete official listing; not a confirmed empty search')
    return list(result.values())


def parse_detail(html: str, url: str, config: dict) -> dict:
    institution = _config(url, config, detail=True)
    ident = _identifier(url, institution)
    root = _Document(html).root
    if institution == 'tp':
        title_node = _one((n for n in root.nodes('span', 'tit') if 'txt_full' in n.attrs.get('class', '').split()), 'TP detail title')
        published = _label_date(title_node.parent.nodes('li'), '등록일')
        content = _one(root.nodes('div', 'nostyle'), 'TP detail body')
        attachment_sections = list(root.nodes('div', 'attachments'))
    else:
        form = _one((n for n in root.nodes('form') if n.attrs.get('id') == 'nttViewForm'), 'CU detail form')
        for field, expected in [('bbsId', '1020'), ('nttSn', ident)]:
            values = [n.attrs.get('value') for n in form.nodes('input') if n.attrs.get('name') == field]
            if values != [expected]:
                raise ValueError('CU detail form board or notice identity mismatch')
        view = _one(root.nodes('div', 'bbs_ViewA'), 'CU detail view')
        title_node = _one((n for n in view.children if isinstance(n, _Node) and n.tag == 'h3'), 'CU detail title')
        metadata = _one(view.nodes('ul', 'bbsV_data'), 'CU detail metadata')
        published = _label_date(metadata.nodes('li'), '작성일')
        content = _one(view.nodes('div', 'bbsV_cont'), 'CU detail body')
        attachment_sections = list(view.nodes('ul', 'bbsV_file'))
        for node in root.nodes('input'):
            if node.attrs.get('name') == 'bbsId' and node.attrs.get('value', '').isdigit() and node.attrs.get('value') != '1020':
                raise ValueError('CU HTML board identity mismatch')
            if node.attrs.get('name') == 'nttSn' and node.attrs.get('value', '').isdigit() and node.attrs.get('value') != ident:
                raise ValueError('CU HTML notice identity mismatch')
    title, body = title_node.clean(), content.clean()
    if not title or not body:
        raise ValueError('Official title or body is empty')
    attachments = {}
    for section in attachment_sections:
        for anchor in section.nodes('a'):
            href = anchor.attrs.get('href', '')
            marker = 'down.do?' if institution == 'tp' else 'nttFileDownload.do?'
            if marker not in href:
                continue
            target = urljoin(url, href)
            if _host(target) != _host(url):
                raise ValueError('Attachment host mismatch')
            parsed, query = urlsplit(target), parse_qs(urlsplit(target).query)
            if institution == 'tp':
                if (parsed.path != '/tp-kr/bbs/i-151/down.do' or query.get('ntt_sn') != [ident]
                        or query.get('bbs_id') != ['tp-1003'] or query.get('data_ty_cd') != ['A']
                        or len(query.get('atfile_sn', [])) != 1 or not query['atfile_sn'][0].isdigit()):
                    raise ValueError('TP attachment belongs to another board or notice')
            elif parsed.path != '/common/nttFileDownload.do' or len(query.get('fileKey', [])) != 1 or not re.fullmatch('[0-9a-fA-F]{32}', query['fileKey'][0]):
                raise ValueError('CU attachment route or file identity mismatch')
            name = re.sub(r'\s*(?:\[다운로드\]|\(다운로드\s*:\s*[\d,]+회\))\s*$', '', anchor.clean()).strip()
            if not name:
                raise ValueError('Attachment name missing')
            item = {'url': target, 'name': name}
            if target in attachments and attachments[target] != item:
                raise ValueError('Conflicting attachment name')
            attachments[target] = item
    return {'title': title, 'date': published, 'body': body, 'attachments': list(attachments.values())}
