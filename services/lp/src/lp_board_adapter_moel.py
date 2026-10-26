"""Pure parser for the two MOEL fund notices on one official board.

The board serves both funds together. Only an explicit fund name in a title
assigns a row to a fund; a shared board URL never establishes its issuer.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlsplit

try:
    from .lp_board_adapters_pensions import _Document, _Node, _one, _date
    from .collect_lp_original_notices import parse_original
except ImportError:
    from lp_board_adapters_pensions import _Document, _Node, _one, _date
    from collect_lp_original_notices import parse_original


HOST = 'www.moel.go.kr'
LIST_PATH = '/info/astmgmt/employ/imchaeBbsList.do'
DETAIL_PATH = '/info/astmgmt/employ/imchaeBbsView.do'
FILE_PATH = '/common/downloadFile.do'
FUND_NAMES = {'moel_eif': '고용보험기금', 'moel_iaci': '산재보험기금'}
MAX_HTML = 2_000_000
HEADERS = ['번호', '제목', '담당부서', '첨부', '등록일', '조회']


def _url(url, path):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname != HOST or p.port not in {None, 443}
            or p.username or p.password or p.fragment or p.path != path
            or re.search(r'[\x00-\x20\x7f]', url)):
        raise ValueError('MOEL official board URL mismatch')
    query = parse_qs(p.query, keep_blank_values=True)
    if any(len(values) != 1 for values in query.values()):
        raise ValueError('MOEL duplicate query parameter')
    return query


def _context(html, url, config, detail=False):
    institution = config.get('institution_id')
    if institution not in FUND_NAMES:
        raise ValueError('MOEL fund identity missing')
    if set(_url(config.get('listing_url', ''), LIST_PATH)) - {'pageIndex', 'searchField', 'searchText', 'pageUnit'}:
        raise ValueError('MOEL configured listing query changed')
    query = _url(url, DETAIL_PATH if detail else LIST_PATH)
    allowed = {'bbs_seq'} if detail else {'pageIndex', 'searchField', 'searchText', 'pageUnit'}
    if set(query) - allowed:
        raise ValueError('MOEL unexpected board query parameter')
    if detail:
        if set(query) != {'bbs_seq'} or not re.fullmatch(r'20\d{9}', query['bbs_seq'][0]):
            raise ValueError('MOEL detail identifier missing')
    else:
        if not re.fullmatch(r'[1-9]\d*', query.get('pageIndex', [''])[0]):
            raise ValueError('MOEL requested listing page missing')
        if query.get('searchText', [''])[0] and query.get('searchField') != ['1']:
            raise ValueError('MOEL title search field mismatch')
        if query.get('pageUnit') and query['pageUnit'] != ['10']:
            raise ValueError('MOEL unsupported listing size')
    if not isinstance(html, str) or len(html) > MAX_HTML or '</html>' not in html.lower():
        raise ValueError('MOEL official response incomplete or oversized')
    root = _Document(html).root
    if not detail:
        form = _one((n for n in root.nodes('form') if n.attrs.get('id') == 'frm'), 'MOEL notice form')
        if (form.attrs.get('action') != LIST_PATH or form.attrs.get('method', '').lower() != 'post'):
            raise ValueError('MOEL notice form route changed')
        page = _one((n for n in form.nodes('input') if n.attrs.get('name') == 'pageIndex'), 'MOEL page echo')
        if page.attrs.get('value') != query['pageIndex'][0]:
            raise ValueError('MOEL listing page echo mismatch')
        if query.get('searchText', [''])[0]:
            search = _one((n for n in form.nodes('input') if n.attrs.get('name') == 'searchText'), 'MOEL search echo')
            if search.attrs.get('value') != query['searchText'][0]:
                raise ValueError('MOEL search term echo mismatch')
            field = _one((n for n in form.nodes('select') if n.attrs.get('name') == 'searchField'), 'MOEL search field')
            selected = _one((n for n in field.nodes('option') if 'selected' in n.attrs), 'MOEL selected search field')
            if selected.attrs.get('value') != '1':
                raise ValueError('MOEL title search field was not selected')
    return root, query


def _table(root):
    table = _one(root.nodes('table', 'tstyle_list'), 'MOEL notice listing table')
    header = _one(table.nodes('thead'), 'MOEL listing header')
    if [n.clean() for n in header.nodes('th')] != HEADERS:
        raise ValueError('MOEL listing columns changed')
    return table


def parse_listing(html, url, config):
    root, _ = _context(html, url, config)
    table = _table(root)
    body = _one(table.nodes('tbody'), 'MOEL listing rows')
    rows, seen = [], set()
    for tr in body.nodes('tr'):
        cells = [c for c in tr.children if isinstance(c, _Node) and c.tag == 'td']
        if len(cells) != 6:
            raise ValueError('MOEL listing row columns changed')
        if cells[1].attrs.get('aria-label') != '제목' or cells[4].attrs.get('aria-label') != '등록일':
            raise ValueError('MOEL title/date row labels changed')
        title_link = _one(cells[1].nodes('a'), 'MOEL title link')
        title = title_link.clean()
        target = urljoin(url, title_link.attrs.get('href', ''))
        detail_query = _url(target, DETAIL_PATH)
        if set(detail_query) != {'bbs_seq'} or not re.fullmatch(r'20\d{9}', detail_query['bbs_seq'][0]):
            raise ValueError('MOEL listed detail identity changed')
        ident = detail_query['bbs_seq'][0]
        call = title_link.attrs.get('onclick', '')
        if call and not re.fullmatch(r"\s*scEventListener\.fnView\(['\"]"+ident+r"['\"]\);\s*return false;?\s*", call):
            raise ValueError('MOEL title link script identity changed')
        if not title or ident in seen:
            raise ValueError('MOEL empty or repeated listed identity')
        seen.add(ident)
        institutions = [institution for institution, name in FUND_NAMES.items() if name in title]
        if len(institutions) > 1:
            raise ValueError('MOEL notice title names both funds')
        institution = institutions[0] if institutions else None
        rows.append({'source_id': (institution or 'moel_board') + ':' + ident,
                     'institution_id': institution, 'url': target,
                     'title': title, 'date': _date(cells[4].clean())})
    return rows


def last_page(html, url, config):
    root, query = _context(html, url, config)
    _table(root)
    pager = _one(root.nodes(cls='board_pager'), 'MOEL pager')
    current = _one((n for n in pager.nodes('a') if n.attrs.get('title') == '현재 페이지'), 'MOEL active page')
    current_no = current.clean()
    if current_no != query['pageIndex'][0] or not re.fullmatch(r'[1-9]\d*', current_no):
        raise ValueError('MOEL pager current page differs')
    last = _one((n for n in pager.nodes('a') if 'last' in n.attrs.get('class', '').split()), 'MOEL last page')
    target = urljoin(url, last.attrs.get('href', ''))
    last_query = _url(target, LIST_PATH)
    if set(last_query) != {'pageIndex'} or not re.fullmatch(r'[1-9]\d*', last_query['pageIndex'][0]):
        raise ValueError('MOEL last page route differs')
    last_no = int(last_query['pageIndex'][0])
    count = _one(root.nodes(cls='page-total'), 'MOEL page count').clean()
    if count != '/ ' + str(last_no) or last_no < int(current_no):
        raise ValueError('MOEL last page count differs')
    total = _one(root.nodes(cls='total'), 'MOEL total count')
    match = re.fullmatch(r'전체\s*([0-9,]+)', total.clean())
    if not match or (int(match[1].replace(',', '')) + 9) // 10 != last_no:
        raise ValueError('MOEL total row count differs from pager')
    return last_no


def parse_detail(html, url, config):
    _, query = _context(html, url, config, detail=True)
    source = parse_original(html, url)
    title = source['title']
    if FUND_NAMES[config['institution_id']] not in title or any(
            name in title for ident, name in FUND_NAMES.items() if ident != config['institution_id']):
        raise ValueError('MOEL detail belongs to another or unnamed fund')
    if not source['date'] or not source['body']:
        raise ValueError('MOEL detail date or body missing')
    attachments, seen = [], set()
    for item in source['attachments']:
        name, target = item['name'], item['url']
        q = _url(target, FILE_PATH)
        if (set(q) != {'file_seq', 'bbs_seq', 'bbs_id', 'file_ext'}
                or q['bbs_seq'] != query['bbs_seq'] or q['bbs_id'] != ['27']
                or not re.fullmatch(r'20\d{9}', q['file_seq'][0])
                or q['file_ext'][0].lower() not in {'hwp', 'hwpx', 'pdf', 'zip'}):
            raise ValueError('MOEL attachment does not belong to the listed notice')
        if target in seen:
            raise ValueError('MOEL duplicate attachment URL')
        seen.add(target)
        if re.search(r'_VC(?=\.|\b)|개인정보|동의서', name, re.I):
            continue
        attachments.append(item)
    source.update(source_id=config['institution_id'] + ':' + query['bbs_seq'][0],
                  url=url, attachments=attachments)
    return source


def has_pe_blind_offering(body, attachment_texts=()):
    """Find an offered blind PEF track; domestic scope needs separate evidence."""
    texts = [body, *attachment_texts]
    for text in texts:
        if not isinstance(text, str):
            continue
        opening = re.split(r'펀드\s*및\s*운용사\s*자격|제안\s*자격|과거\s*운용', text, maxsplit=1)[0]
        compact = re.sub(r'\s+', '', opening)
        if re.search(r'(?:선정유형|투자유형|선정대상)[:：]?블라인드(?:형)?PEF', compact, re.I):
            return True
    return False
