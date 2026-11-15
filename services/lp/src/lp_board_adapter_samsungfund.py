"""Pure parser for 삼성자산운용 notices posted as the 산재보험기금 주간운용사 (OCIO).

The fund's own board (고용노동부) carries the recruitments but never the results;
the OCIO's notice board carries both (2020-2026 observed). This channel takes only
the PE result notices, so a recruitment is never read twice. A row belongs to the
fund only when its title names the fund; the OCIO's own business never qualifies.

Listing: GET /fund/lounge/notice-ajax.do?category=ALL&searchText=<fund>&pageNo=N
returns an HTML fragment of ten <li> rows (an empty fragment after the last page).
Detail: /fund/lounge/notice-view.do?no=N (title, date, body, download links).
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlsplit

try:
    from .lp_board_adapters_pensions import _Document, _one, _date
except ImportError:
    from lp_board_adapters_pensions import _Document, _one, _date


HOST = 'm.samsungfund.com'
LIST_PATH = '/fund/lounge/notice-ajax.do'
DETAIL_PATH = '/fund/lounge/notice-view.do'
FILE_PATH = '/fund/download.do'
FUND_NAMES = {'moel_iaci': '산재보험기금'}
PAGE_ROWS = 10
MAX_HTML = 2_000_000
_CALL = re.compile(r"javascript:goDetail\('notice-view\.do\?no=([1-9]\d{0,9})&searchText=([^'&]*)'\)")


def _url(url, path):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname != HOST or p.port not in {None, 443}
            or p.username or p.password or p.fragment or p.path != path
            or re.search(r'[\x00-\x20\x7f]', url)):
        raise ValueError('삼성자산운용 official notice URL mismatch')
    query = parse_qs(p.query, keep_blank_values=True)
    if any(len(values) != 1 for values in query.values()):
        raise ValueError('삼성자산운용 duplicate query parameter')
    return {k: v[0] for k, v in query.items()}


def _fund(config):
    institution = config.get('institution_id')
    if institution not in FUND_NAMES:
        raise ValueError('삼성자산운용 OCIO fund identity missing')
    return institution, FUND_NAMES[institution]


def is_pe_result(title, fund):
    """A final result of the fund's 대체투자상품 selection with a PE track."""
    m = re.search(r'대체투자상품\s*\(([^()]*)\)', title)
    return bool(fund in title and m and re.search(r'(?<![A-Za-z])PEF?(?![A-Za-z])', m[1])
                and re.search(r'결과', title) and '하위운용사' not in title)


def _listing_query(url, config):
    _, fund = _fund(config)
    query = _url(url, LIST_PATH)
    if set(query) != {'category', 'searchText', 'pageNo'} or query['category'] != 'ALL':
        raise ValueError('삼성자산운용 listing query changed')
    if query['searchText'] != fund or not re.fullmatch(r'[1-9]\d{0,2}', query['pageNo']):
        raise ValueError('삼성자산운용 listing must search the fund name')
    return query


def _items(html, url, config):
    query = _listing_query(url, config)
    if not isinstance(html, str) or len(html) > MAX_HTML or re.search(r'<\s*html', html, re.I):
        raise ValueError('삼성자산운용 listing fragment incomplete or oversized')
    root = _Document(html).root
    items = list(root.nodes('li'))
    if len(items) > PAGE_ROWS or (not items and html.strip()):
        raise ValueError('삼성자산운용 listing rows changed')
    return query, items


def parse_listing(html, url, config):
    institution, fund = _fund(config)
    query, items = _items(html, url, config)
    rows, seen = [], set()
    for li in items:
        link = _one(li.nodes('a'), '삼성자산운용 notice link')
        match = _CALL.fullmatch(link.attrs.get('href', ''))
        if not match or match[2] != query['searchText']:
            raise ValueError('삼성자산운용 notice link script changed')
        ident = match[1]
        title = _one(link.nodes('h3'), '삼성자산운용 notice title').clean()
        day = _one(link.nodes('span', 'date'), '삼성자산운용 notice date').clean()
        if not title or ident in seen or not re.fullmatch(r'20\d{2}\.\d{2}\.\d{2}', day):
            raise ValueError('삼성자산운용 empty, repeated or undated row')
        seen.add(ident)
        rows.append({'source_id': f'{institution}:samsungfund:{ident}',
                     'institution_id': institution if is_pe_result(title, fund) else None,
                     'url': f'https://{HOST}{DETAIL_PATH}?no={ident}',
                     'title': title, 'date': _date(day)})
    return rows


def last_page(html, url, config):
    """The fragment has no pager: a full page may continue, a short one is the last."""
    query, items = _items(html, url, config)
    page = int(query['pageNo'])
    return page + 1 if len(items) == PAGE_ROWS else page


def parse_detail(html, url, config):
    institution, fund = _fund(config)
    query = _url(url, DETAIL_PATH)
    if set(query) != {'no'} or not re.fullmatch(r'[1-9]\d{0,9}', query['no']):
        raise ValueError('삼성자산운용 detail identifier missing')
    if not isinstance(html, str) or len(html) > MAX_HTML or '</html>' not in html.lower():
        raise ValueError('삼성자산운용 detail incomplete or oversized')
    root = _Document(html).root
    main = _one((n for n in root.nodes('main') if 'notice-view-wrap' in n.attrs.get('class', '').split()),
                '삼성자산운용 notice view')
    head = _one(main.nodes('div', 'viewer-title-wrap'), '삼성자산운용 title block')
    title = _one(head.nodes('h2'), '삼성자산운용 title').clean()
    day = _date(_one(head.nodes('p', 'date'), '삼성자산운용 date').clean())
    body = _one(main.nodes('div', 'con-textarea'), '삼성자산운용 body').clean()
    if fund not in title or not body:
        raise ValueError('삼성자산운용 detail does not name the fund or has no body')
    attachments, seen = [], set()
    for link in main.nodes('a'):
        href = link.attrs.get('href', '')
        if not href.startswith(FILE_PATH):
            continue
        target = urljoin(url, href)
        q = _url(target, FILE_PATH)
        if set(q) != {'fileSeq', 'fileNo'} or q['fileSeq'] != query['no'] or not re.fullmatch(r'[1-9]\d?', q['fileNo']):
            raise ValueError('삼성자산운용 attachment does not belong to the notice')
        name = _one(link.nodes('span', 'txt'), '삼성자산운용 attachment name').clean()
        if target in seen or not name:
            raise ValueError('삼성자산운용 duplicate or unnamed attachment')
        seen.add(target)
        if not re.search(r'개인정보|동의서', name):
            attachments.append({'name': name, 'url': target})
    return {'title': title, 'date': day, 'body': body, 'attachments': attachments,
            'source_id': f'{institution}:samsungfund:{query["no"]}', 'url': url}
