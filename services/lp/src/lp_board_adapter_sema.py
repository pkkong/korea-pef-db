"""Pure SEMA notice-board parser; no discovery IDs or network operations."""
import re
from urllib.parse import parse_qs, urljoin, urlsplit

try:
    from .lp_board_adapters_pensions import _Document, _Node, _one, _date
    from .collect_lp_original_notices import parse_original
except ImportError:
    from lp_board_adapters_pensions import _Document, _Node, _one, _date
    from collect_lp_original_notices import parse_original

BOARD = '/sema/bbs/B0000022/'


def _url(url, path):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname != 'www.sema.or.kr' or p.port not in {None, 443}
            or p.username or p.password or p.fragment or p.path != path
            or re.search(r'[\x00-\x20\x7f]', url)):
        raise ValueError('SEMA official URL mismatch')
    q = parse_qs(p.query, keep_blank_values=True)
    if any(len(v) != 1 for v in q.values()) or q.get('menuNo') != ['200017']:
        raise ValueError('SEMA board query mismatch')
    return q


def _context(html, url, config, detail=False):
    if config.get('institution_id') != 'sema':
        raise ValueError('SEMA institution mismatch')
    _url(config['listing_url'], BOARD + 'list.do')
    q = _url(url, BOARD + ('view.do' if detail else 'list.do'))
    if '</html>' not in html.lower() or len(html) > 3 * 1024 * 1024:
        raise ValueError('Incomplete or oversized SEMA HTML')
    if detail:
        if not re.fullmatch(r'[0-9]+', q.get('nttId', [''])[0]):
            raise ValueError('SEMA notice identifier missing')
    else:
        if q.get('optn1') != ['S'] or q.get('searchCnd') != ['1'] or not q.get('searchWrd'):
            raise ValueError('SEMA search query mismatch')
        if not re.fullmatch(r'[1-9][0-9]*', q.get('pageIndex', [''])[0]):
            raise ValueError('SEMA requested page missing')
    root = _Document(html).root
    if not detail:
        for name in ('optn1', 'searchWrd'):
            node = _one((n for n in root.nodes('input') if n.attrs.get('name') == name), 'SEMA search echo')
            if q[name] != [node.attrs.get('value')]:
                raise ValueError('SEMA search echo mismatch')
        select = _one((n for n in root.nodes('select') if n.attrs.get('name') == 'searchCnd'), 'SEMA search field')
        option = _one((n for n in select.nodes('option') if 'selected' in n.attrs), 'SEMA selected field')
        if q['searchCnd'] != [option.attrs.get('value')]:
            raise ValueError('SEMA selected field mismatch')
    return root, q


def parse_listing(html, url, config):
    root, query = _context(html, url, config)
    table = _one(root.nodes('table', 'dataTbl'), 'SEMA listing table')
    if [n.clean() for n in table.nodes('th')] != ['No', '분류', '제목', '작성일', '조회']:
        raise ValueError('SEMA listing headers changed')
    rows = []
    seen = {}
    for tr in table.nodes('tr'):
        cells = [n for n in tr.children if isinstance(n, _Node) and n.tag == 'td']
        if not cells:
            continue
        if len(cells) == 1 and cells[0].clean() == '게시글이 없습니다.':
            rows.append(None)
            continue
        if len(cells) != 5:
            raise ValueError('SEMA listing columns changed')
        link = _one(cells[2].nodes('a'), 'SEMA title link')
        target = urljoin(url, link.attrs.get('href', ''))
        q = _url(target, BOARD + 'view.do')
        ident = q.get('nttId', [''])[0]
        if not re.fullmatch(r'[0-9]+', ident) or not link.clean():
            raise ValueError('SEMA listing identity/title missing')
        row = dict(source_id='sema:' + ident, url=target, title=link.clean(), date=_date(cells[3].clean()))
        pinned = cells[0].clean() == '공지' or any(n.attrs.get('alt') == '공지' for n in cells[0].nodes('img'))
        row['pinned'] = pinned
        if not pinned and re.sub(r'\s+', '', query['searchWrd'][0]) not in re.sub(r'\s+', '', row['title']):
            raise ValueError('SEMA title search returned an unrelated regular row')
        if ident in seen and seen[ident] != row:
            raise ValueError('SEMA conflicting duplicate notice')
        seen[ident] = row
        rows.append(row)
    if not rows or (None in rows and len(rows) != 1):
        raise ValueError('SEMA listing is not a confirmed empty/result page')
    return list(seen.values())


def last_page(html, url, config):
    root, query = _context(html, url, config)
    pagers = list(root.nodes(cls='paginationSet'))
    if not pagers:
        if not parse_listing(html, url, config):
            if query['pageIndex'] == ['1']:
                return 1
            raise ValueError('SEMA empty response beyond observed first page')
        raise ValueError('SEMA populated listing has no pager')
    pager = _one(pagers, 'SEMA pager')
    current = _one((n for n in pager.nodes('em') if n.attrs.get('title') == '현재목록'), 'SEMA current page').clean()
    if query['pageIndex'] != [current]:
        raise ValueError('SEMA current page mismatch')
    last = _one((n for n in pager.nodes('a') if n.attrs.get('title') == '마지막 목록'), 'SEMA last page')
    q = _url(urljoin(url, last.attrs.get('href', '')), BOARD + 'list.do')
    for key in ('searchWrd', 'searchCnd', 'optn1'):
        if q.get(key) != query.get(key):
            raise ValueError('SEMA pager changes search')
    number = q.get('pageIndex', [''])[0]
    if not re.fullmatch(r'[1-9][0-9]*', number) or int(number) < int(current):
        raise ValueError('SEMA last page invalid')
    return int(number)


def parse_detail(html, url, config):
    root, query = _context(html, url, config, detail=True)
    table = _one((t for t in root.nodes('table', 'writeForm') if list(t.nodes('td', 'td_cont'))), 'SEMA detail table')
    _one(table.nodes('td', 'td_cont'), 'SEMA detail body')
    metadata = {}
    for tr in table.nodes('tr'):
        cells = [n for n in tr.children if isinstance(n, _Node) and n.tag in {'th', 'td'}]
        for i, cell in enumerate(cells[:-1]):
            if cell.tag == 'th' and cell.clean() in {'제목', '작성일'}:
                if cell.clean() in metadata:
                    raise ValueError('SEMA duplicate metadata')
                metadata[cell.clean()] = cells[i + 1].clean()
    source = parse_original(html, url)
    if source['title'] != metadata.get('제목') or source['date'] != _date(metadata.get('작성일', '')):
        raise ValueError('SEMA detail metadata mismatch')
    attachments = []
    seen = set()
    for link in table.nodes('a'):
        href = link.attrs.get('href', '')
        if 'fileDown.do' not in href:
            continue
        target = urljoin(url, href)
        q = _url(target, '/sema/cmmn/file/fileDown.do')
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', q.get('atchFileId', [''])[0])
                or not re.fullmatch(r'[0-9]+', q.get('fileSn', [''])[0])):
            raise ValueError('SEMA attachment identity missing')
        ident = (q['atchFileId'][0], q['fileSn'][0])
        if ident in seen or not link.clean():
            raise ValueError('SEMA duplicate/unnamed attachment')
        seen.add(ident)
        attachments.append(dict(name=link.clean(), url=target))
    source.update(source_id='sema:' + query['nttId'][0], url=url, attachments=attachments)
    return source
