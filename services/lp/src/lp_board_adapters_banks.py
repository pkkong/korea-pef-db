"""Pure official-board adapters for KDB JSON listings and IBK HTML notices."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit


class _Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def nodes(self, tag=None, cls=None):
        for child in self.children:
            if isinstance(child, _Node):
                if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get('class', '').split()):
                    yield child
                yield from child.nodes(tag, cls)

    def clean(self):
        if self.tag in {'script', 'style'}:
            return ''
        if self.tag == 'img':
            return self.attrs.get('alt', '')
        return re.sub(r'\s+', ' ', ' '.join(n.clean() if isinstance(n, _Node) else n for n in self.children)).strip()


class _Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root, self.stack = _Node(), []
        self.stack.append(self.root)
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'br', 'img', 'hr', 'meta', 'link', 'input', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'col'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _one(values, label):
    values = list(values)
    if len(values) != 1:
        raise ValueError(f'{label}: missing or ambiguous official markup')
    return values[0]


def _url(url, institution, paths):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname not in {institution + '.co.kr', 'www.' + institution + '.co.kr'}
            or p.username or p.password or p.port not in {None, 443} or p.path not in paths):
        raise ValueError('Official bank URL host or route mismatch')
    return parse_qs(p.query, keep_blank_values=True)


def _context(url, config, detail=False):
    institution = config.get('institution_id')
    if institution not in {'kdb', 'ibk'}:
        raise ValueError('Unsupported policy bank institution')
    if institution == 'kdb':
        listing = config.get('listing_url', 'https://www.kdb.co.kr/CHBIPR23N00.act?_mnuId=IHIHIR0087')
        _url(listing, 'kdb', {'/CHBIPR23N00.act', '/BOUBUF01R01.jct'})
        query = _url(url, 'kdb', {'/BOUBUF02N00.act'} if detail else {'/BOUBUF01R01.jct'})
        if query.get('_mnuId', ['IHIHIR0087']) != ['IHIHIR0087']:
            raise ValueError('KDB menu mismatch')
        parameter = '_PARM_DATA' if detail else '_JSON_'
        raw = _one(query.get(parameter, []), 'KDB request payload')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get('ITR_BLB_ID') != 'STD119':
            raise ValueError('KDB board identity mismatch')
        if detail and payload.get('FIRST_MENU_ID') != 'CHBIPR23N00':
            raise ValueError('KDB detail parent menu mismatch')
        return institution, payload
    listing = config.get('listing_url', 'https://www.ibk.co.kr/cyber/noticeListCyber.ibk?pageId=IR03010400')
    listing_query = _url(listing, 'ibk', {'/cyber/noticeListCyber.ibk'})
    query = _url(url, 'ibk', {'/cyber/noticeDetailCyber.ibk'} if detail else {'/cyber/noticeListCyber.ibk'})
    if listing_query.get('pageId') != ['IR03010400'] or query.get('pageId') != ['IR03010400']:
        raise ValueError('IBK notice board identity mismatch')
    return institution, query


def listing_requests(config: dict) -> list[dict]:
    """Return observed GET search requests; no network, selected IDs or dates."""
    institution = config.get('institution_id')
    terms = config.get('search_terms', ['펀드', '위탁운용사'] if institution == 'ibk' else ['펀드'])
    pages = config.get('pages', 2 if institution == 'ibk' else 3)
    if institution not in {'kdb', 'ibk'} or not isinstance(pages, int) or not 1 <= pages <= 3:
        raise ValueError('Invalid policy-bank request limits')
    if not isinstance(terms, list) or not 1 <= len(terms) <= 5 or any(not isinstance(t, str) or not t.strip() for t in terms):
        raise ValueError('Invalid policy-bank search terms')
    result = []
    for term in terms:
        for page in range(1, pages + 1):
            if institution == 'kdb':
                payload = {'SEARCH_CONDITION': 'NAC_CONE_TTL', 'SEARCH_KEYWORD': term, 'SEARCH_CATEGORY': '',
                           'ORDER_TYPE': 'new', 'MODE': '1,2,5,6', 'ITR_BLB_ID': 'STD119',
                           'HEADER_STD_WEB': {'REQ_PAGE_NO': page, 'PAGE_ROW_COUNT': '50', 'NEXT_PAGE_YN': 'S',
                                              'NEXTPAGDTT': 'P', 'GRID_NEXTKEY_ITR_CND': ''}}
                url = 'https://www.kdb.co.kr/BOUBUF01R01.jct?' + urlencode({'_JSON_': json.dumps(payload, ensure_ascii=False)})
                referer = 'https://www.kdb.co.kr/CHBIPR23N00.act?_mnuId=IHIHIR0087'
            else:
                url = 'https://www.ibk.co.kr/cyber/noticeListCyber.ibk?' + urlencode(
                    {'pageId': 'IR03010400', 'pageNum': page, 'searchKey': 'TTL', 'searchValue': term})
                referer = 'https://www.ibk.co.kr/cyber/noticeListCyber.ibk?pageId=IR03010400'
            _context(url, config)
            result.append({'url': url, 'method': 'GET', 'referer': referer})
    return result


def ibk_last_page(html: str, url: str, config: dict) -> int | None:
    """Read the observed mobile total and final-page control, never a pager window."""
    institution, query = _context(url, config)
    if institution != 'ibk':
        raise ValueError('IBK pagination requires the IBK board')
    root = _Document(html).root
    pagers = list(root.nodes(cls='m_pagination'))
    if not pagers:
        return None
    pager = _one(pagers, 'IBK mobile pager')
    current = _one(pager.nodes(cls='current_m_page'), 'IBK current page').clean()
    total = _one(pager.nodes(cls='others_m_page'), 'IBK page total').clean()
    if not re.fullmatch(r'[1-9]\d{0,5}', current) or not re.fullmatch(r'/\s*[1-9]\d{0,5}', total):
        raise ValueError('Invalid IBK page counters')
    last = int(total.lstrip('/').strip())
    if int(current) > last or query.get('pageNum') != [current]:
        raise ValueError('IBK requested and displayed page mismatch')
    controls = [a for a in pager.nodes('a') if any(
        img.attrs.get('alt') == '마지막 페이지로 이동' for img in a.nodes('img'))]
    control = _one(controls, 'IBK final-page control')
    match = re.fullmatch(r'javascript:getListData\(([1-9]\d{0,5})\);?', control.attrs.get('href', ''))
    if not match or int(match[1]) != last:
        raise ValueError('Conflicting IBK final page')
    form = _one((f for f in root.nodes('form') if f.attrs.get('name') == 'searchForm'), 'IBK search form')
    if form.attrs.get('action') != '/cyber/noticeListCyber.ibk':
        raise ValueError('IBK search form route mismatch')
    for key in ('pageId', 'pageNum', 'searchValue'):
        value = _one((n for n in form.nodes('input') if n.attrs.get('name') == key), 'IBK ' + key).attrs.get('value')
        if query.get(key) != [value]:
            raise ValueError('IBK requested and displayed search mismatch')
    select = _one((n for n in form.nodes('select') if n.attrs.get('name') == 'searchKey'), 'IBK search field')
    selected = _one((n for n in select.nodes('option') if 'selected' in n.attrs), 'IBK selected search field')
    if query.get('searchKey') != [selected.attrs.get('value')]:
        raise ValueError('IBK requested and displayed search field mismatch')
    return last


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+', value):
        raise ValueError('Missing or invalid observed bank notice identifier')
    return value


def _calendar(text):
    values = set()
    for m in re.finditer(r'(?<!\d)(20\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})(?!\d)', text):
        values.add(date(*map(int, m.groups())).isoformat())
    months = {name: i + 1 for i, name in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])}
    for m in re.finditer(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Z][a-z]{2})\s+(\d{1,2})\s+\d{2}:\d{2}:\d{2}\s+KST\s+(20\d{2})\b', text):
        if m[1] not in months:
            raise ValueError('Invalid IBK registration month')
        values.add(date(int(m[3]), months[m[1]], int(m[2])).isoformat())
    if len(values) != 1:
        raise ValueError('Missing or conflicting bank publication date')
    return values.pop()


def _kdb_detail_url(ident):
    payload = {'ITR_NAC_ID_MNG_SNO': ident, 'ITR_BLB_ID': 'STD119', 'NAC_SNO': '', 'FIRST_MENU_ID': 'CHBIPR23N00'}
    return 'https://www.kdb.co.kr/BOUBUF02N00.act?' + urlencode(
        {'_mnuId': 'IHIHIR0087', '_PARAM_NAME': 'NEXT_DATA', '_PARM_DATA': json.dumps(payload, ensure_ascii=False, separators=(',', ':'))})


def parse_listing(html_or_json: str, url: str, config: dict) -> list[dict]:
    institution, _ = _context(url, config)
    result = {}
    if institution == 'kdb':
        data = json.loads(html_or_json)
        if (not isinstance(data, dict) or data.get('ITR_BLB_ID') != 'STD119'
                or not isinstance(data.get('COMMON_HEAD'), dict) or data['COMMON_HEAD'].get('ERROR') is not False
                or not isinstance(data.get('STDLIST_REC'), list) or not isinstance(data.get('HEADER_STD_WEB'), dict)):
            raise ValueError('Incomplete or rejected KDB JSON listing')
        rows = data['STDLIST_REC']
        total = int(data['HEADER_STD_WEB']['TOT_PAG_ROW_CNT'])
        if total < 0 or (not rows and total != 0):
            raise ValueError('KDB empty rows conflict with listing count')
        for row in rows:
            ident = _identifier(row['ITR_NAC_ID_MNG_SNO'])
            stamp = row['FST_ENR_DTM']
            if not isinstance(stamp, str) or not re.fullmatch(r'\d{14}', stamp):
                raise ValueError('Invalid KDB registration timestamp')
            published = datetime.strptime(stamp, '%Y%m%d%H%M%S').date().isoformat()
            title = row['NAC_CONE_TTL']
            if not isinstance(title, str) or not title.strip():
                raise ValueError('KDB notice title missing')
            item = {'url': _kdb_detail_url(ident), 'title': title.strip(), 'date': published, 'source_id': 'kdb:' + ident}
            if ident in result and result[ident] != item:
                raise ValueError('Conflicting KDB duplicate source')
            result[ident] = item
        return list(result.values())
    root = _Document(html_or_json).root
    content = _one((n for n in root.nodes('div') if n.attrs.get('id') == 'contents_in'), 'IBK list content')
    for row in content.nodes('tr'):
        anchors = [a for a in row.nodes('a') if 'noticeDetailCyber.ibk' in a.attrs.get('href', '')]
        if not anchors:
            continue
        anchor = _one(anchors, 'IBK notice link')
        target = urljoin(url, anchor.attrs['href'])
        _, query = _context(target, config, detail=True)
        ident = _identifier(_one(query.get('srno', []), 'IBK notice identifier'))
        cells = [n for n in row.children if isinstance(n, _Node) and n.tag == 'td']
        if len(cells) != 5 or not anchor.clean():
            raise ValueError('Incomplete IBK listing row')
        item = {'url': target, 'title': anchor.clean(), 'date': _calendar(cells[3].clean()), 'source_id': 'ibk:' + ident}
        if ident in result and result[ident] != item:
            raise ValueError('Conflicting IBK duplicate source')
        result[ident] = item
    empty = any('등록된 게시물이 없습니다.' in n.clean() for n in content.nodes('td'))
    if (empty and result) or (not empty and not result):
        raise ValueError('Incomplete or contradictory IBK listing')
    return list(result.values())


def parse_detail(html: str, url: str, config: dict) -> dict:
    institution, payload = _context(url, config, detail=True)
    root = _Document(html).root
    if institution == 'kdb':
        ident = _identifier(payload.get('ITR_NAC_ID_MNG_SNO'))
        for field, expected in [('itrNacIdMngSno', ident), ('itrBlbId', 'STD119')]:
            if _one((n.attrs.get('value') for n in root.nodes('input') if n.attrs.get('id') == field), 'KDB detail identity') != expected:
                raise ValueError('KDB detail notice or board mismatch')
        article = _one(root.nodes('article', 'bbs'), 'KDB detail article')
        title = _one(article.nodes('p', 'tit'), 'KDB detail title').clean()
        metadata = _one(article.nodes('div', 'bbsInfo'), 'KDB detail metadata')
        published = _calendar(metadata.clean())
        for node in metadata.nodes('time'):
            if node.attrs.get('datetime') != published:
                raise ValueError('KDB datetime differs from registration text')
        body = _one(article.nodes('div', 'context'), 'KDB actual HTML body').clean()
        anchors = [a for section in article.nodes('div', 'fileList') for a in section.nodes('a')]
        file_groups = [n.attrs.get('value') for n in root.nodes('input') if n.attrs.get('name') == 'APG_FL_MPN_ID']
        if anchors and len(file_groups) != 1:
            raise ValueError('KDB attachment group binding missing')
    else:
        ident = _identifier(_one(payload.get('srno', []), 'IBK detail identifier'))
        declared = [n.attrs.get('value') for n in root.nodes('input') if n.attrs.get('name') == 'srno' and n.attrs.get('value')]
        if declared != [ident]:
            raise ValueError('IBK detail notice identity mismatch')
        content = _one((n for n in root.nodes('div') if n.attrs.get('id') == 'contents_in'), 'IBK detail content')
        title = _one(content.nodes('td', 'view_tit'), 'IBK detail title').clean()
        published = _calendar(_one(content.nodes('td', 'update'), 'IBK registration field').clean())
        body = _one(content.nodes('td', 'view'), 'IBK actual HTML body').clean()
        anchors = [a for section in content.nodes('td', 'down_flie') for a in section.nodes('a')]
    if not title or not body:
        raise ValueError('Official bank title or actual body is missing')
    attachments = {}
    for anchor in anchors:
        href = anchor.attrs.get('href', '')
        marker = 'fileView?' if institution == 'kdb' else '/common/download.ibk?'
        if marker not in href:
            continue
        target = urljoin(url, href)
        query = _url(target, institution, {'/fileView'} if institution == 'kdb' else {'/common/download.ibk'})
        if institution == 'kdb':
            for field in ['groupId', 'fileId']:
                if not re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}', _one(query.get(field, []), 'KDB attachment identifier')):
                    raise ValueError('Invalid observed KDB attachment identity')
            if query['groupId'] != file_groups:
                raise ValueError('KDB attachment belongs to another notice group')
        else:
            full = _one(query.get('fullName', []), 'IBK attachment path')
            if (query.get('seq') != [ident] or not full.startswith('fup/finemall/general/news/')
                    or '..' in full.split('/') or '\\' in full or '\x00' in full):
                raise ValueError('IBK attachment belongs to another notice or unsafe path')
        name = anchor.clean() or anchor.attrs.get('title', '')
        if not name:
            raise ValueError('Bank attachment name missing')
        # URL percent encoding changes no observed path/query values; IBK emits
        # Unicode/spaces in fileName, which urllib cannot transmit verbatim.
        target = quote(target, safe=':/?&=%')
        item = {'url': target, 'name': name}
        if target in attachments and attachments[target] != item:
            raise ValueError('Conflicting bank attachment name')
        attachments[target] = item
    return {'title': title, 'date': published, 'body': body, 'attachments': list(attachments.values())}
