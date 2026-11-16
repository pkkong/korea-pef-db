"""고용보험기금 PE results on its OCIO's Mirae Asset Securities notice board.

Observed 2026-11-16: EUC-KR HTML, category 66, title search, one-year search
windows. Follow the pager's actual startId/startPage cursor, never invent one
by incrementing curPage. Recruitments still come from the ministry board.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

try:
    from .lp_board_adapters_pensions import _Document, _one
except ImportError:
    from lp_board_adapters_pensions import _Document, _one

HOST = 'securities.miraeasset.com'
BASE = f'https://{HOST}'
LIST_PATH = '/bbs/board/message/list.do'
DETAIL_PATH = '/bbs/board/message/view.do'
FUND = '고용보험기금'
MAX_HTML = 2_000_000
QUERY_ENCODING = 'euc-kr'
_VIEW = re.compile(r"javascript:view\('([1-9]\d{0,9})','\d+'\)")
_FIELDS = {'categoryId', 'searchType', 'searchText', 'startId', 'startPage',
           'curPage', 'listType', 'searchStartYear', 'searchStartMonth',
           'searchStartDay', 'searchEndYear', 'searchEndMonth', 'searchEndDay'}


def _query(url, path, config):
    p = urlsplit(url)
    if (config.get('institution_id') != 'moel_eif' or p.scheme != 'https'
            or p.hostname != HOST or p.port not in {None, 443} or p.username
            or p.password or p.fragment or p.path != path
            or re.search(r'[\x00-\x20\x7f]', url)):
        raise ValueError('미래에셋증권 OCIO URL or fund mismatch')
    pairs = parse_qsl(p.query, keep_blank_values=True, encoding='euc-kr', errors='strict')
    q = dict(pairs)
    if len(q) != len(pairs) or q.get('categoryId') != '66':
        raise ValueError('미래에셋증권 board or duplicate parameter mismatch')
    return q


def _url(path, query):
    return BASE + path + '?' + urlencode(query, encoding='euc-kr')


def _listing_query(url, config):
    q = _query(url, LIST_PATH, config)
    if (set(q) not in (_FIELDS, _FIELDS | {'direction'}) or q['searchText'] != FUND
            or q['searchType'] != '2' or q['listType'] != '1'
            or q.get('direction', '1') != '1'
            or not re.fullmatch(r'[A-Za-z0-9]{1,16}~', q['startId'])
            or not re.fullmatch(r'[1-9]\d{0,2}', q['curPage'])
            or not re.fullmatch(r'[1-9]\d{0,2}', q['startPage'])
            or not 1 <= int(q['startPage']) <= int(q['curPage']) <= config['pages']):
        raise ValueError('미래에셋증권 title search or cursor changed')
    try:
        start = date(int(q['searchStartYear']), int(q['searchStartMonth']), int(q['searchStartDay']))
        end = date(int(q['searchEndYear']), int(q['searchEndMonth']), int(q['searchEndDay']))
    except ValueError as exc:
        raise ValueError('미래에셋증권 invalid search window') from exc
    if (start < date.fromisoformat(config['since']) or start.year != end.year
            or start > end or end != date(end.year, 12, 31)
            or start != max(date(start.year, 1, 1), date.fromisoformat(config['since']))):
        raise ValueError('미래에셋증권 search must cover one OCIO year')
    return q


def listing_urls(config):
    start = date.fromisoformat(config['since'])
    for year in range(date.today().year, start.year - 1, -1):
        first = max(date(year, 1, 1), start)
        yield _url(LIST_PATH, dict(categoryId='66', searchType='2', searchText=FUND,
            startId='zzzzz~', startPage='1', curPage='1', listType='1',
            searchStartYear=str(year), searchStartMonth=f'{first.month:02}', searchStartDay=f'{first.day:02}',
            searchEndYear=str(year), searchEndMonth='12', searchEndDay='31'))


def listing_url_allowed(url, config):
    _listing_query(url, config)
    return True


def listing_stream(url, config):
    return _listing_query(url, config)['searchStartYear']


def _root(html):
    if not isinstance(html, str) or len(html) > MAX_HTML or '</html>' not in html.lower():
        raise ValueError('미래에셋증권 incomplete or oversized page')
    return _Document(html).root


def _form(root, q):
    form = _one((n for n in root.nodes('form') if n.attrs.get('id') == 'viewForm'), '미래에셋증권 form')
    inputs = list(form.nodes('input'))
    values = {n.attrs.get('name'): n.attrs.get('value', '') for n in inputs}
    if len(values) != len(inputs) or any(values.get(k) != v for k, v in q.items() if k not in {'direction', 'listType'}):
        raise ValueError('미래에셋증권 response search or notice identity differs')


def is_pe_result(title):
    return bool(FUND in title and re.search(r'대체투자(?:상품|펀드)\s*\([^()]*\bPEF?\b', title, re.I)
                and re.search(r'선정\s*(?:최종\s*)?결과', title) and '하위운용사' not in title)


def _table(root):
    return _one((n for n in root.nodes('table', 'bbs_linetype2')
                 if any(c.clean() == '공지사항' for c in n.nodes('caption'))), '미래에셋증권 notice table')


def parse_listing(html, url, config):
    q = _listing_query(url, config)
    root = _root(html)
    _form(root, q)
    table = _table(root)
    if [n.clean() for n in table.nodes('th')] != ['작성일', '제목', '첨부']:
        raise ValueError('미래에셋증권 listing headings changed')
    body = _one(table.nodes('tbody'), '미래에셋증권 listing body')
    rows, seen = [], set()
    for tr in body.nodes('tr'):
        cells = list(tr.nodes('td'))
        if len(cells) == 1 and cells[0].attrs.get('colspan') == '3' and cells[0].clean() == '게시물이 없습니다.':
            if rows or len(list(body.nodes('tr'))) != 1:
                raise ValueError('미래에셋증권 mixed empty and populated rows')
            return []
        if len(cells) != 3:
            raise ValueError('미래에셋증권 listing row changed')
        day, subject = cells[0].clean(), _one(cells[1].nodes('div', 'subject'), '미래에셋증권 subject')
        link = _one(subject.nodes('a'), '미래에셋증권 notice link')
        match = _VIEW.fullmatch(link.attrs.get('href', ''))
        title = link.clean()
        if not match or not title or match[1] in seen:
            raise ValueError('미래에셋증권 empty, duplicate or invalid notice')
        parsed_day = date.fromisoformat(day)
        if parsed_day.year != int(q['searchStartYear']):
            raise ValueError('미래에셋증권 row outside search year')
        seen.add(match[1])
        rows.append(dict(source_id=f'moel_eif:miraeasset:{match[1]}',
            institution_id='moel_eif' if is_pe_result(title) else None,
            url=_url(DETAIL_PATH, dict(categoryId='66', messageId=match[1], startId='zzzzz~', startPage='1', curPage='1')),
            title=title, date=day))
    if not rows:
        raise ValueError('미래에셋증권 missing explicit empty row')
    pager = _one(root.nodes('div', 'bbs_pagingWrap'), '미래에셋증권 pager')
    if _one(pager.nodes('a', 'on'), '미래에셋증권 current page').clean() != q['curPage']:
        raise ValueError('미래에셋증권 response page differs')
    return rows


def next_listing_url(html, url, config):
    q = _listing_query(url, config)
    root = _root(html)
    # Numbered links use the current cursor within a block; the next-block link
    # supplies a new startId. Select exactly the observed next page in either case.
    page = int(q['curPage'])
    targets = set()
    for pager in root.nodes('div', 'bbs_pagingWrap'):
        for link in pager.nodes('a'):
            href = link.attrs.get('href', '')
            if not href.startswith('list.do?'):
                continue
            target = urljoin(url, href)
            candidate = _query(target, LIST_PATH, config)
            if candidate.get('curPage') != str(page + 1):
                continue
            if any(candidate.get(k) != q[k] for k in _FIELDS - {'startId', 'startPage', 'curPage'}):
                raise ValueError('미래에셋증권 pager changed search')
            # Validate shape before budget enforcement; hitting the last allowed
            # page with a next link must report a depth hold, not look complete.
            _listing_query(target, {**config, 'pages': max(config['pages'], page + 1)})
            targets.add(target)
    if len(targets) > 1:
        raise ValueError('미래에셋증권 ambiguous next cursor')
    return next(iter(targets), None)


def last_page(html, url, config):
    page = int(_listing_query(url, config)['curPage'])
    return page + 1 if next_listing_url(html, url, config) else page


def parse_detail(html, url, config):
    q = _query(url, DETAIL_PATH, config)
    if (set(q) != {'categoryId', 'messageId', 'startId', 'startPage', 'curPage'}
            or not re.fullmatch(r'[1-9]\d{0,9}', q['messageId'])
            or any(q[k] != v for k, v in dict(startId='zzzzz~', startPage='1', curPage='1').items())):
        raise ValueError('미래에셋증권 detail identity changed')
    root = _root(html)
    _form(root, q)
    table = _one((n for n in root.nodes('table', 'bbs_linetype2')
                  if any(c.clean() == '공지사항 글읽기' for c in n.nodes('caption'))), '미래에셋증권 detail table')
    title = _one(table.nodes('h4'), '미래에셋증권 detail title').clean()
    dates = [list(tr.nodes('td')) for tr in table.nodes('tr')
             if any(th.clean() == '작성일' for th in tr.nodes('th'))]
    day = _one(_one(dates, '미래에셋증권 date row'), '미래에셋증권 date cell').clean()
    date.fromisoformat(day)
    content = _one((n for n in table.nodes('div') if n.attrs.get('id') == 'messageContentsDiv'), '미래에셋증권 result body')
    body = content.clean()
    if not is_pe_result(title) or FUND not in body or not body:
        raise ValueError('미래에셋증권 result does not identify the fund and PE track')
    # The observed result is inline. An attached or image-only replacement needs
    # explicit parsing rather than silently discarding its official evidence.
    if list(content.nodes('img')) or any(n.attrs.get('href', '').startswith(('download', '/bbs/board/attachment')) for n in table.nodes('a')):
        raise ValueError('미래에셋증권 result attachment or image needs review')
    return dict(title=title, date=day, body=body, attachments=[],
                source_id=f'moel_eif:miraeasset:{q["messageId"]}', url=url)
