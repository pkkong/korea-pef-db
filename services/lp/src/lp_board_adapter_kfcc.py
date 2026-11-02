"""Pure official MG notice/tender parsing; no selected notice identifiers."""
from __future__ import annotations
import re
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit
try:
    from .collect_shared_lp_notices import Document, Node, valid_date
except ImportError:
    from collect_shared_lp_notices import Document, Node, valid_date


def _classes(node):
    return set(node.attrs.get('class', '').split())


def _context(html, url, config):
    actual, listing = urlsplit(url), urlsplit(config['listing_url'])
    hosts = set(config.get('allowed_hosts', ['www.kfcc.co.kr']))
    if (config['institution_id'] != 'kfcc' or actual.scheme != 'https' or
            actual.hostname not in hosts or listing.hostname not in hosts or
            actual.username or actual.password or actual.port not in (None, 443)):
        raise ValueError('KFCC official HTTPS host mismatch')
    routes = {'/mgNotice/mgNoticeList.do': '/mgNotice/mgNoticeDetail.do',
              '/noticeofTender/noticeofTenderList.do': '/noticeofTender/noticeofTenderDetail.do'}
    if listing.path not in routes or actual.path not in (listing.path, routes[listing.path]):
        raise ValueError('KFCC board route mismatch')
    if not re.search(r'</html\s*>', html, re.I):
        raise ValueError('incomplete KFCC HTML')
    return Document(html).root, listing.path, routes[listing.path]


def _one(nodes, label):
    nodes = list(nodes)
    if len(nodes) != 1:
        raise ValueError('KFCC '+label+' missing or ambiguous')
    return nodes[0]


def parse_listing(html: str, url: str, config: dict) -> list[dict]:
    root, listing_path, detail_path = _context(html, url, config)
    if urlsplit(url).path != listing_path:
        raise ValueError('KFCC listing route expected')
    # The public form and its observed function together establish how row IDs
    # map to detail links. Do not derive IDs from neighboring links or counters.
    form = _one((n for n in root.nodes('form') if n.attrs.get('name') == 'brdForm'), 'listing form')
    if not any(n.attrs.get('name') == 'no' for n in form.nodes('input')):
        raise ValueError('KFCC notice ID form field missing')
    control = re.search(r'function\s+fnDetail\(no\)\s*\{(.*?)\}', html, re.S)
    action = re.search(r'f\.action\s*=\s*[\"\']([^\"\']+)[\"\']', control[1]) if control else None
    if not action or action[1] != detail_path or not re.search(r'f\.no\.value\s*=\s*no', control[1]):
        raise ValueError('KFCC observed detail action differs from board')
    area = _one((n for n in root.nodes('ul') if 'magazine' in _classes(n)), 'notice list')
    rows = []
    seen = set()
    for li in (n for n in area.children if isinstance(n, Node) and n.tag == 'li'):
        if 'top' in _classes(li):
            continue
        anchors = list(li.nodes('a'))
        if not anchors:
            if li.clean() == '해당 내역이 없습니다.':
                continue
            raise ValueError('KFCC notice row or empty marker missing')
        anchor = _one(anchors, 'notice anchor')
        match = re.fullmatch(r"javascript:fnDetail\('([0-9]+)'\)", anchor.attrs.get('href', ''))
        if not match or not anchor.clean():
            raise ValueError('KFCC invalid observed notice control')
        stamp = valid_date(_one((n for n in li.nodes('div') if 'date' in _classes(n)), 'listing date').clean())
        if not stamp:
            raise ValueError('KFCC listing date invalid')
        ident = match[1]
        if ident in seen:
            raise ValueError('KFCC duplicate notice ID')
        seen.add(ident)
        rows.append({'url': urljoin(url, detail_path) + '?' + urlencode({'no': ident}),
                     'title': anchor.clean(), 'date': stamp, 'source_id': 'kfcc:' + ident})
    if not rows and '해당 내역이 없습니다.' not in area.clean():
        raise ValueError('KFCC empty listing not explicitly confirmed')
    return rows


def _table_text(table):
    if any(True for _ in table.nodes('table')):
        raise ValueError('KFCC nested table requires structural review')
    lines, carry, width = [], {}, None
    for row in table.nodes('tr'):
        cells = [n for n in row.children if isinstance(n, Node) and n.tag in ('td', 'th')]
        if not cells:
            continue
        grid = {col: text for col, (text, _) in carry.items()}
        following = {col: (text, left-1) for col, (text, left) in carry.items() if left > 1}
        col = 0
        for cell in cells:
            while col in grid:
                col += 1
            span, down = int(cell.attrs.get('colspan', '1')), int(cell.attrs.get('rowspan', '1'))
            if not 1 <= span <= 20 or not 1 <= down <= 100:
                raise ValueError('KFCC table span exceeds limit')
            text = cell.clean()
            for offset in range(span):
                index = col + offset
                if index in grid:
                    raise ValueError('KFCC table cells overlap')
                grid[index] = text
                if down > 1:
                    following[index] = (text, down-1)
            col += span
        current = max(grid, default=-1) + 1
        if width is None:
            width = current
        if current != width or set(grid) != set(range(width)):
            raise ValueError('KFCC incomplete table row')
        lines.append('\t'.join(grid[c] for c in range(width)))
        carry = following
    if carry:
        raise ValueError('KFCC unfinished table rowspan')
    return '\n'.join(lines)


def last_page(html, url, config):
    """Read observed pager/counts; never probe past a confirmed single page."""
    rows = parse_listing(html, url, config)
    root, listing_path, _ = _context(html, url, config)
    q = parse_qs(urlsplit(url).query, keep_blank_values=True)
    if any(len(values) != 1 for values in q.values()):
        raise ValueError('KFCC duplicate query parameter')
    requested = q.get('pageNo', ['1'])[0]
    if not re.fullmatch('[1-9][0-9]*', requested):
        raise ValueError('KFCC invalid requested page')
    form = _one((n for n in root.nodes('form') if n.attrs.get('name') == 'brdForm'), 'listing form')
    for field in ('schValue', 'pageNo'):
        values = [n.attrs.get('value', '') for n in form.nodes('input') if n.attrs.get('name') == field]
        if values != [q.get(field, ['1' if field == 'pageNo' else ''])[0]]:
            raise ValueError('KFCC search/page echo mismatch')
    selections = [o.attrs.get('value') for s in form.nodes('select') if s.attrs.get('name') == 'schType'
                  for o in s.nodes('option') if 'selected' in o.attrs]
    if selections != [q.get('schType', [''])[0]]:
        raise ValueError('KFCC search type echo mismatch')
    total_node = _one((n for n in form.nodes('div') if 'total' in _classes(n)), 'total count')
    match = re.fullmatch(r'총\s*([0-9,]+)\s*건', total_node.clean())
    if not match:
        raise ValueError('KFCC invalid total count')
    total = int(match[1].replace(',', ''))
    pager = _one((n for n in root.nodes('ul') if 'paging-list' in _classes(n)), 'pager')
    active = [n.clean() for n in pager.nodes('li') if 'active' in _classes(n)]
    if active != [requested]:
        raise ValueError('KFCC active page mismatch')
    endings = []
    for anchor in pager.nodes('a'):
        href = anchor.attrs.get('href', '')
        if href == '#none':
            continue
        if re.fullmatch(r"javascript:fnSearch\('([1-9][0-9]*)'\);", href):
            # Numeric controls alone are never evidence of the final page.
            continue
        target = urlsplit(urljoin(url, href)); params = parse_qs(target.query, keep_blank_values=True)
        if (target.scheme != 'https' or target.netloc != urlsplit(url).netloc or target.path != listing_path
                or target.fragment or any(len(v) != 1 for v in params.values())
                or any(params.get(k) != q.get(k, ['']) for k in ('schType','schValue'))
                or params.get('currentPageNo') != [requested]
                or params.get('totalRows') != [str(total)]):
            raise ValueError('KFCC pager route/search/count mismatch')
        size, page = params.get('pageRows',[''])[0], params.get('pageNo',[''])[0]
        if not size.isdigit() or not 1 <= int(size) <= 100 or not page.isdigit() or int(page) < 1:
            raise ValueError('KFCC pager size/page invalid')
        expected = max(1, (total + int(size) - 1) // int(size))
        if int(page) > expected or int(requested) > expected:
            raise ValueError('KFCC pager overrun')
        if len(rows) != min(int(size), max(0, total - (int(requested) - 1) * int(size))):
            raise ValueError('KFCC row count differs from pager metadata')
        if 'last' in _classes(anchor):
            if int(page) != expected:
                raise ValueError('KFCC last page disagrees with total')
            endings.append(expected)
    if endings:
        if len(endings) != 1:
            raise ValueError('KFCC ambiguous last page')
        return endings[0]
    if requested == '1' and total == len(rows) and len(list(pager.nodes('a'))) == 1:
        return 1
    raise ValueError('KFCC final page not confirmed')


def _body(node):
    if isinstance(node, str):
        return node
    if node.tag in ('script', 'style', 'img', 'button') or 'photo' in _classes(node):
        return ''
    if node.tag == 'table':
        return '\n' + _table_text(node) + '\n'
    value = ''.join(_body(child) for child in node.children)
    return '\n' + value + '\n' if node.tag in ('p', 'div', 'li', 'br', 'h1', 'h2', 'h3', 'h4') else value


def parse_detail(html: str, url: str, config: dict) -> dict:
    root, _, detail_path = _context(html, url, config)
    ident = parse_qs(urlsplit(url).query).get('no', [''])[0]
    if urlsplit(url).path != detail_path or not ident.isdigit():
        raise ValueError('KFCC detail identifier missing')
    form = _one((n for n in root.nodes('form') if n.attrs.get('name') == 'sltForm'), 'detail form')
    values = [n.attrs.get('value') for n in form.nodes('input') if n.attrs.get('name') == 'no']
    if values != [ident]:
        raise ValueError('KFCC detail belongs to another notice')
    area = _one((n for n in root.nodes('div') if 'bbs-view' in _classes(n)), 'detail content')
    info = _one((n for n in area.nodes('div') if 'info-area' in _classes(n)), 'detail heading')
    title = _one((n for n in info.nodes('span') if 'title' in _classes(n)), 'title').clean()
    stamp = valid_date(_one((n for n in info.nodes('div') if 'date' in _classes(n)), 'detail date').clean())
    content = _one((n for n in area.nodes('div') if 'con' in _classes(n)), 'body')
    body = '\n'.join(line.strip() for line in re.sub(r'[ \r\f\v]+', ' ', _body(content)).split('\n') if line.strip())
    if not title or not stamp or not body:
        raise ValueError('KFCC official title, date or body missing')
    attachments = []
    expected_board = 'A01' if detail_path.startswith('/mgNotice/') else 'A02'
    for button in area.nodes('button'):
        call = button.attrs.get('onclick', '')
        if 'fnDownload' not in call:
            continue
        match = re.fullmatch(r"fnDownload\('([A-Za-z0-9]+)','([0-9]+)','([0-9]+)','([^'\\]+)'\);?", call)
        if not match:
            raise ValueError('KFCC malformed attachment control')
        board, observed_id, file_no, name = match.groups()
        if board != expected_board or observed_id != ident or '/' in name or '\\' in name or '..' in name:
            raise ValueError('KFCC attachment board or notice mismatch')
        # fnDownload in the page's public /static/js/user.func.js uses the
        # current origin + /upload/neoboard/ + boardId + / + fileName. The
        # commented legacy /neoboard/download2.do call is not used.
        target = urljoin(url, '/upload/neoboard/' + quote(board, safe='') + '/' + quote(name, safe=''))
        attachments.append({'name': name, 'url': target})
    return {'title': title, 'date': stamp, 'body': body, 'attachments': attachments}
