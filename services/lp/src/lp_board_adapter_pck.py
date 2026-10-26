"""Pure, board-bound parsers for the PCK Pension Foundation notice board."""
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

try:
    from .lp_board_adapters_pensions import _Document, _Node, _one, _date
except ImportError:
    from lp_board_adapters_pensions import _Document, _Node, _one, _date

HOST = 'www.pension.or.kr'
LIST_PATH = '/modu/s_board/list.asp'
DETAIL_PATH = '/modu/s_board/read.asp'


def _route(url, path):
    p = urlsplit(url)
    q = parse_qs(p.query, keep_blank_values=True)
    if (p.scheme != 'https' or p.hostname != HOST or p.port not in {None, 443}
            or p.username or p.password or p.fragment or p.path != path
            or q.get('board_seq') != ['1'] or q.get('board_sub_seq') != ['1']
            or ('view_sub_seq' in q and q['view_sub_seq'] != ['0'])):
        raise ValueError('PCK official board or HTTPS route mismatch')
    return p, q


def canonical_notice(url):
    p, q = _route(url, DETAIL_PATH)
    if len(q.get('seq', [])) != 1 or not re.fullmatch(r'[0-9]+', q['seq'][0]):
        raise ValueError('PCK notice identity missing or ambiguous')
    return urlunsplit(p._replace(query=urlencode({k: q[k][0] for k in ('board_seq', 'board_sub_seq', 'seq')})))


def _config(url, config, detail=False):
    if config.get('institution_id') != 'pck_pension':
        raise ValueError('PCK institution mismatch')
    _route(config['listing_url'], LIST_PATH)
    return _route(url, DETAIL_PATH if detail else LIST_PATH)


def _listing(html, url, config):
    _, q = _config(url, config)
    if '</html>' not in html.lower():
        raise ValueError('Incomplete PCK listing')
    root = _Document(html).root
    form = _one((n for n in root.nodes('form') if n.attrs.get('name') == 'l_form'), 'PCK listing form')
    fields = {key: [n.attrs.get('value', '') for n in form.nodes('input') if n.attrs.get('name') == key]
              for key in ('board_seq', 'board_sub_seq', 'page', 'search_select', 'search_text')}
    expected = {'board_seq': ['1'], 'board_sub_seq': ['1'], 'page': q.get('page', ['1']),
                'search_select': q.get('search_select', ['']), 'search_text': q.get('search_text', [''])}
    if fields != expected or any(len(value) != 1 for value in expected.values()):
        raise ValueError('PCK listing board/page/search response not echoed')
    table = _one((n for n in form.nodes('table') if
                  {'sboard_list_tbl', 'sboard_listA_tbl'} & set(n.attrs.get('class', '').split())), 'PCK notice table')
    return root, table


def last_page(html, url, config):
    root, table = _listing(html, url, config)
    values = {n.clean() for n in root.nodes('div', 'navi_all_btn') if re.fullmatch(r'\d+/\d+', n.clean())}
    if len(values) != 1:
        raise ValueError('PCK page count missing or conflicting')
    current, last = map(int, values.pop().split('/'))
    requested = int(parse_qs(urlsplit(url).query).get('page', ['1'])[0])
    if current != requested or current < 1 or last < 0 or (last and current > last):
        raise ValueError('PCK page count does not match requested page')
    regular = [n for n in table.nodes('tr', 'sboard_list_line') if 'noti_color' not in n.attrs.get('class', '').split()]
    if not last and (current != 1 or regular):
        raise ValueError('PCK zero-page marker conflicts with regular rows')
    return last or 1


def parse_listing(html, url, config):
    root, table = _listing(html, url, config)
    last_page(html, url, config)
    rows = {}
    for row in table.nodes('tr', 'sboard_list_line'):
        a = _one(row.nodes('a', 'sboard_list_sbj'), 'PCK notice link')
        target = canonical_notice(urljoin(url, a.attrs.get('href', '')))
        cells = [n for n in row.children if isinstance(n, _Node) and n.tag == 'td']
        if len(cells) != 5 or not a.clean():
            raise ValueError('PCK listing columns or title missing')
        pinned = 'noti_color' in row.attrs.get('class', '').split()
        query = parse_qs(urlsplit(url).query)
        term = query.get('search_text', [''])[0]
        if not pinned and term and term not in a.clean():
            raise ValueError('PCK title search returned an unrelated regular row')
        ident = parse_qs(urlsplit(target).query)['seq'][0]
        item = {'url': target, 'title': a.clean(), 'date': _date(cells[3].clean()),
                'source_id': 'pck_pension:' + ident, 'pinned': pinned}
        if target in rows and rows[target] != item:
            raise ValueError('Conflicting duplicate PCK listing row')
        rows[target] = item
    if not rows and not any(n.clean() == '1/0' for n in root.nodes('div', 'navi_all_btn')):
        raise ValueError('PCK missing rows are not a confirmed empty search')
    return list(rows.values())


def parse_detail(html, url, config):
    _config(url, config, detail=True)
    ident = parse_qs(urlsplit(canonical_notice(url)).query)['seq'][0]
    if '</html>' not in html.lower():
        raise ValueError('Incomplete PCK detail')
    root = _Document(html).root
    form = _one((n for n in root.nodes('form') if n.attrs.get('name') == 'vform'), 'PCK detail form')
    for field, expected in (('board_seq', '1'), ('board_sub_seq', '1'), ('seq', ident)):
        if [n.attrs.get('value') for n in form.nodes('input') if n.attrs.get('name') == field] != [expected]:
            raise ValueError('PCK detail board or notice identity mismatch')
    info = _one(root.nodes('table', 'sboard_info_tbl'), 'PCK detail metadata')
    title = _one(info.nodes('span', 'sboard_info_sbj'), 'PCK detail title').clean()
    stamps = []
    for row in info.nodes('tr'):
        if any(n.clean() == '날짜' for n in row.nodes('th')):
            stamps.append(_date(_one(row.nodes('td'), 'PCK publication date').clean()))
    if len(stamps) != 1:
        raise ValueError('PCK publication date missing or ambiguous')
    # The source sometimes pastes a second content div inside the first one.
    contents = list(root.nodes('div', 'sboard_cont_details'))
    outer = [n for n in contents if not any(n in list(parent.nodes()) for parent in contents if parent is not n)]
    content = _one(outer, 'PCK detail body')
    body = content.clean()
    related = set()
    for a in content.nodes('a'):
        target = urljoin(url, a.attrs.get('href', ''))
        if urlsplit(target).path == DETAIL_PATH:
            related.add(canonical_notice(target))
    if not title or not body:
        raise ValueError('PCK title or body missing')
    attachments = {}
    for table in root.nodes('table', 'sboard_atch_file_tbl'):
        for a in table.nodes('a', 'sboard_atch_file'):
            target = urljoin(url, a.attrs.get('href', ''))
            p = urlsplit(target); q = parse_qs(p.query, keep_blank_values=True)
            names = q.get('filename', [])
            if (p.scheme != 'https' or p.hostname != HOST or p.port not in {None, 443}
                    or p.username or p.password or p.fragment or p.path != '/modu/s_board/download.asp'
                    or q.get('board_seq') != ['1'] or q.get('board_sub_seq') != ['1']
                    or q.get('view_sub_seq') != ['1'] or len(names) != 1 or not names[0]
                    or any(c in names[0] for c in ('/', '\\', '\x00')) or names[0] in {'.', '..'}
                    or a.clean() != names[0]):
                raise ValueError('PCK attachment board, filename or observed label mismatch')
            attachments[target] = {'url': target, 'name': names[0]}
    return {'title': title, 'date': stamps[0], 'body': body, 'attachments': list(attachments.values()),
            'related_notice_urls': sorted(related)}
