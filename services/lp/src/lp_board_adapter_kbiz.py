"""Pure KBIZ official listing parser using observed search and pager controls."""
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urljoin

try:
    from .lp_board_adapters_banks import _Document, _Node, _one
    from .lp_board_adapters_pensions import _date
    from .collect_lp_original_notices import parse_original
except ImportError:
    from lp_board_adapters_banks import _Document, _Node, _one
    from lp_board_adapters_pensions import _date
    from collect_lp_original_notices import parse_original

BASE = 'https://www.kbiz.or.kr/ko/contents/bbs/'


def titles_match(listing_title, detail_title):
    """Allow only an omitted observed board category; preserve stored titles."""
    left, right = (re.sub(r'\s+', ' ', s).strip() for s in (listing_title, detail_title))
    if left == right:
        return True
    category = r'^\[(?:사업공고|입찰공고(?:\(재공고\))?)\]\s*'
    if bool(re.match(category, left)) == bool(re.match(category, right)):
        return False
    return re.sub(category, '', left) == re.sub(category, '', right)


def _query(url, route):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname != 'www.kbiz.or.kr' or p.port not in {None, 443}
            or p.username or p.password or p.fragment or p.path != '/ko/contents/bbs/' + route
            or re.search(r'[\x00-\x20\x7f]', url)):
        raise ValueError('KBIZ official URL mismatch')
    q = parse_qs(p.query, keep_blank_values=True)
    if q.get('mnSeq') != ['211'] or any(len(v) != 1 for v in q.values()):
        raise ValueError('KBIZ board identity mismatch')
    return q


def _listing(html, url, config):
    if config.get('institution_id') != 'kbiz':
        raise ValueError('KBIZ institution mismatch')
    _query(config['listing_url'], 'list.do')
    q = _query(url, 'list.do')
    if q.get('schFld') != ['ttl'] or not q.get('schTxt') or not re.fullmatch(r'[1-9][0-9]*', q.get('pg', [''])[0]):
        raise ValueError('KBIZ search/page mismatch')
    if '</html>' not in html.lower() or len(html) > 3 * 1024 * 1024:
        raise ValueError('Incomplete or oversized KBIZ listing')
    root = _Document(html).root
    for name in ('mnSeq', 'schFld', 'schTxt'):
        node = _one((n for n in root.nodes('input') if n.attrs.get('name') == name), 'KBIZ search echo')
        if q[name] != [node.attrs.get('value')]:
            raise ValueError('KBIZ search echo mismatch')
    # Parse literal arguments only; never execute official JavaScript.
    scripts = '\n'.join(''.join(c for c in s.children if isinstance(c, str)) for s in root.nodes('script'))
    pattern = r'\bpager\(\s*"\./list\.do"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*("(?:[^"\\]|\\.)*")\s*,\s*"(\d+)"\s*\)'
    total, size, encoded, current = _one(re.findall(pattern, scripts), 'KBIZ pager')
    pager_q = parse_qs(json.loads(encoded), keep_blank_values=True)
    if pager_q != {k: q[k] for k in ('mnSeq', 'schFld', 'schTxt')} or current != q['pg'][0]:
        raise ValueError('KBIZ pager search/page mismatch')
    total, size = int(total), int(size)
    if not 1 <= size <= 100 or total > 1000000:
        raise ValueError('KBIZ pager count invalid')
    tables = [t for t in root.nodes('table') if [n.clean() for n in t.nodes('th')] == ['번호', '제목', '첨부파일', '등록일']]
    if total == 0 and not tables:
        if int(current) != 1:
            raise ValueError('KBIZ empty page exceeds observed result')
        _one((n for n in root.nodes('ul', 'empty') if n.clean() == '검색결과가 없습니다.'), 'KBIZ verified empty result')
        return None, total, size, int(current)
    table = _one(tables, 'KBIZ notice table')
    return table, total, size, int(current)


def parse_listing(html, url, config):
    table, total, size, current = _listing(html, url, config)
    if table is None:
        return []
    result = {}
    regular = 0
    for tr in table.nodes('tr'):
        cells = [n for n in tr.children if isinstance(n, _Node) and n.tag == 'td']
        if not cells:
            continue
        if len(cells) != 4:
            raise ValueError('KBIZ unrecognized row/empty-result markup')
        title = _one((n for n in cells[1].nodes() if 'onclick' in n.attrs), 'KBIZ notice control')
        match = re.fullmatch(r"\s*goView\((\d+),\s*['\"]([YN])['\"]\)\s*;?\s*", title.attrs['onclick'])
        if not match or not title.clean():
            raise ValueError('KBIZ notice control/title invalid')
        ident, flag = match.groups()
        pinned = 'notice' in tr.attrs.get('class', '').split()
        if pinned != (flag == 'Y'):
            raise ValueError('KBIZ pinned state mismatch')
        if not pinned:
            if not cells[0].clean().isdigit():
                raise ValueError('KBIZ normal row number missing')
            regular += 1
        target = BASE + 'view.do?' + urlencode({'seq': ident, 'topFixYn': flag, 'mnSeq': '211'})
        row = dict(source_id='kbiz:' + ident, url=target, title=title.clean(), date=_date(cells[3].clean()), pinned=pinned)
        if ident in result:
            raise ValueError('KBIZ duplicate notice identity')
        result[ident] = row
    expected = max(0, min(size, total - (current - 1) * size))
    if regular != expected or not result:
        raise ValueError('KBIZ listing count/empty-result not verified')
    return list(result.values())


def last_page(html, url, config):
    _, total, size, current = _listing(html, url, config)
    last = max(1, (total + size - 1) // size)
    if current > last:
        raise ValueError('KBIZ page exceeds observed total')
    return last


def parse_detail(html, url, config):
    if config.get('institution_id') != 'kbiz':
        raise ValueError('KBIZ institution mismatch')
    _query(config['listing_url'], 'list.do')
    q = _query(url, 'view.do')
    if not re.fullmatch(r'[0-9]+', q.get('seq', [''])[0]) or q.get('topFixYn') not in (['N'], ['Y']):
        raise ValueError('KBIZ detail identity missing')
    if '</html>' not in html.lower() or len(html) > 3 * 1024 * 1024:
        raise ValueError('Incomplete or oversized KBIZ detail')
    root = _Document(html).root
    scripts = '\n'.join(''.join(c for c in s.children if isinstance(c, str)) for s in root.nodes('script'))
    matches = re.findall(r'move\("\./list\.do\?mnSeq="\s*\+\s*\["211"\]\s*\+\s*"&"\s*\+\s*("(?:[^"\\]|\\.)*")\)', scripts)
    echo = parse_qs(json.loads(_one(matches, 'KBIZ detail return link')), keep_blank_values=True)
    if echo.get('seq') != q['seq'] or echo.get('topFixYn') != q['topFixYn'] or any(len(v) != 1 for v in echo.values()):
        raise ValueError('KBIZ returned notice differs')
    content = _one((n for n in root.nodes() if n.attrs.get('id') == 'contents'), 'KBIZ content')
    heading = _one(content.nodes('div', 'subject-wrap'), 'KBIZ heading')
    title = _one(heading.nodes('strong'), 'KBIZ title').clean()
    stamp = _date(_one(heading.nodes('em', 'date'), 'KBIZ date').clean())
    _one(content.nodes('div', 'detail-body'), 'KBIZ body')
    source = parse_original(html, url)
    if source['title'] != title or source['date'] != stamp:
        raise ValueError('KBIZ detail metadata differs')
    attachments = []
    seen = set()
    for area in content.nodes('div', 'file-wrap'):
        for li in area.nodes('li'):
            name = _one(li.nodes('em'), 'KBIZ attachment label').clean()
            name = re.sub(r'^첨부파일\s*', '', name)
            name = re.sub(r'\([\d.,]+\s*KB\)$', '', name).strip()
            link = _one((n for n in li.nodes('a') if 'download.do' in n.attrs.get('href', '')), 'KBIZ download')
            target = urljoin(url, link.attrs['href']); p = urlsplit(target)
            if (p.scheme != 'https' or p.hostname != 'www.kbiz.or.kr' or p.port not in {None, 443}
                    or p.username or p.password or p.fragment or p.path != '/download.do'):
                raise ValueError('KBIZ download route mismatch')
            args = parse_qs(p.query, keep_blank_values=True)
            if (set(args) != {'orgalFle', 'saveFle', 'fleDwnDs', 'seq'} or any(len(v) != 1 or not v[0] for v in args.values())
                    or args['fleDwnDs'] != ['bbsAttachFile'] or not re.fullmatch(r'\d+', args['seq'][0])
                    or not re.fullmatch(r'[a-fA-F0-9]+', args['orgalFle'][0])
                    or not re.fullmatch(r'\d+\.[A-Za-z0-9]+', args['saveFle'][0])):
                raise ValueError('KBIZ download identity mismatch')
            if args['seq'][0] in seen or not name:
                raise ValueError('KBIZ duplicate/unnamed file')
            seen.add(args['seq'][0]); attachments.append(dict(name=name, url=target))
    source.update(source_id='kbiz:' + q['seq'][0], url=url, attachments=attachments)
    return source
