"""Pure official-board adapters for POBA and the Police Mutual Aid Association.

The parsers never request URLs or run JavaScript. Notice identifiers and download
arguments must occur in the received official page; none are maintained here.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

try:
    from .collect_shared_lp_notices import Document, Node, valid_date
except ImportError:
    from collect_shared_lp_notices import Document, Node, valid_date


def _classes(node):
    return set(node.attrs.get('class', '').split())


def _context(html, url, config):
    institution = config['institution_id']
    base = config.get('listing_url', url)
    parsed, expected = urlsplit(url), urlsplit(base)
    official = {'poba': 'www.poba.or.kr', 'pmaa': 'www.pmaa.or.kr'}
    if institution not in official:
        raise ValueError('unsupported mutual-aid institution')
    # No implicit aliases or legacy-host rewrites: configuration owns the host.
    hosts = set(config.get('allowed_hosts', [official[institution]]))
    if (parsed.scheme != 'https' or parsed.hostname not in hosts or
            expected.hostname not in hosts or parsed.username or parsed.password or
            parsed.port not in (None, 443)):
        raise ValueError('official board host mismatch')
    if not re.search(r'</html\s*>', html, re.I):
        raise ValueError('incomplete official board HTML')
    if institution == 'poba':
        board = parse_qs(expected.query).get('sechBbsSeq', [''])[0]
        if not board.isdigit() or parse_qs(parsed.query).get('sechBbsSeq') != [board]:
            raise ValueError('POBA board identifier mismatch')
        if parsed.path not in ('/bbs/selectNttList', '/bbs/selectNttDetail'):
            raise ValueError('unexpected POBA board route')
    elif parsed.path != expected.path or not re.fullmatch(r'/www/\d+/bbs\.do', parsed.path):
        raise ValueError('PMAA board route mismatch')
    return institution, Document(html).root


def _same_host_url(value, base):
    target = urljoin(base, value)
    a, b = urlsplit(target), urlsplit(base)
    if a.scheme != 'https' or a.hostname != b.hostname or a.username or a.password or a.port not in (None, 443):
        raise ValueError('cross-host board link rejected')
    return target


def _poba_data(html, url):
    matches = list(re.finditer(r'\bvar\s+bbsMap\s*=\s*', html))
    if len(matches) != 1:
        raise ValueError('POBA board data missing or ambiguous')
    value, _ = json.JSONDecoder().raw_decode(html[matches[0].end():])
    data = value['bbsDvo']
    board = parse_qs(urlsplit(url).query)['sechBbsSeq'][0]
    if str(data['bbsMastDvo']['bbsSeq']) != board:
        raise ValueError('POBA response belongs to a different board')
    return data


def _dated(value):
    stamp = valid_date(str(value or ''))
    if not stamp:
        raise ValueError('official publication date missing')
    return stamp


def parse_listing(html: str, url: str, config: dict) -> list[dict]:
    institution, root = _context(html, url, config)
    rows = []
    if institution == 'poba':
        data = _poba_data(html, url)
        items = data['nttDvoList']
        if items is None and data.get('allCnt') == 0:
            return []
        if not isinstance(items, list) or (not items and data.get('allCnt') != 0):
            raise ValueError('POBA listing payload incomplete')
        requested = parse_qs(urlsplit(url).query).get('pageIndex', ['1'])[0]
        if str(data['nttPvo']['pageIndex']) != requested:
            raise ValueError('POBA response page mismatch')
        board = parse_qs(urlsplit(url).query)['sechBbsSeq'][0]
        for item in items:
            ident = str(item['bbstSeq'])
            title = item['bbstSj']
            if not ident.isdigit() or str(item['bbsSeq']) != board or not isinstance(title, str) or not title.strip():
                raise ValueError('invalid POBA listing record')
            target = urljoin(url, '/bbs/selectNttDetail') + '?' + urlencode({'sechBbsSeq': board, 'sechBbstSeq': ident})
            rows.append({'url': target, 'title': title, 'date': _dated(item['rgstDt']), 'source_id': 'poba:' + ident})
    else:
        tables = [t for t in root.nodes('table') if 'tb_list' in _classes(t)]
        if len(tables) != 1:
            raise ValueError('PMAA listing table missing or ambiguous')
        table = tables[0]
        if not {'번호', '제목', '작성일'}.issubset({n.clean() for n in table.nodes('th')}):
            raise ValueError('PMAA listing headings changed')
        for row in table.nodes('tr'):
            cells = [c for c in row.children if isinstance(c, Node) and c.tag == 'td']
            if not cells:
                continue
            if len(cells) == 1 and cells[0].clean() == '조회된 내용이 없습니다.' and cells[0].attrs.get('colspan', '').isdigit():
                continue
            if len(cells) != 5:
                raise ValueError('PMAA listing row incomplete')
            anchors = list(cells[1].nodes('a'))
            if len(anchors) != 1:
                raise ValueError('PMAA notice anchor missing or ambiguous')
            anchor = anchors[0]
            if anchor.attrs.get('href', '#') not in ('#', ''):
                _same_host_url(anchor.attrs['href'], url)
                raise ValueError('unsupported PMAA notice link format')
            match = re.fullmatch(r"\s*fn_view\('([0-9]+)'\);\s*return false;?\s*", anchor.attrs.get('onclick', ''))
            if not match or not anchor.clean():
                raise ValueError('invalid PMAA notice control')
            ident = match[1]
            target = urlsplit(url)._replace(query=urlencode({'type': 'view', 'bbsIdx': ident}), fragment='').geturl()
            rows.append({'url': target, 'title': anchor.clean(), 'date': _dated(cells[3].clean()), 'source_id': 'pmaa:' + ident})
        if not rows and not any(n.clean() == '조회된 내용이 없습니다.' for n in table.nodes('td')):
            raise ValueError('PMAA listing contains neither notices nor explicit empty marker')
    unique = {}
    for row in rows:
        old = unique.setdefault(row['source_id'], row)
        if old != row:
            raise ValueError('conflicting duplicate official notice')
    return list(unique.values())


def parse_detail(html: str, url: str, config: dict) -> dict:
    institution, root = _context(html, url, config)
    attachments = []
    if institution == 'poba':
        data = _poba_data(html, url)
        item = data['nttDvo']
        ident = parse_qs(urlsplit(url).query).get('sechBbstSeq', [''])[0]
        if not ident.isdigit() or str(item['bbstSeq']) != ident:
            raise ValueError('POBA detail identifier mismatch')
        title, stamp = item['bbstSj'], _dated(item['rgstDt'])
        body = Document(item.get('bbstCten') or '').root.clean()
        files = data.get('atchDvoList') or []
        # This endpoint is taken from the page's public download function, not
        # guessed from storage paths or server-side file metadata.
        control = re.search(r'function\s+fnFileDownLoad\([^)]*\)\s*\{(.*?)\n\s*\}', html, re.S)
        route = re.search(r'var\s+url\s*=\s*[\"\']([^\"\']+)[\"\']', control[1]) if control else None
        if files and not route:
            raise ValueError('POBA attachment control missing')
        endpoint = _same_host_url(route[1], url) if route else None
        for file in files:
            token = file['atchFileSeq']
            if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9+/=]+', token) or str(file['bbstSeq']) != ident:
                raise ValueError('invalid POBA attachment identity')
            attachments.append({'name': file['realAtchFileNm'], 'url': endpoint + '?' + urlencode({'sechAtchFileSeq': token, 'detailYn': 'Y', 'bbsSeq': data['bbsMastDvo']['bbsSeq']})})
    else:
        ident = parse_qs(urlsplit(url).query).get('bbsIdx', [''])[0]
        if not ident.isdigit() or parse_qs(urlsplit(url).query).get('type') != ['view']:
            raise ValueError('PMAA detail identifier missing')
        table = next((t for t in root.nodes('table') if 'tb_view' in _classes(t)), None)
        article = next((n for n in root.nodes('div') if 'bbs_article' in _classes(n)), None)
        if table is None or article is None:
            raise ValueError('PMAA detail content missing')
        caption = next(table.nodes('caption'), None)
        dates = [n for n in caption.nodes('span') if 'date' in _classes(n)] if caption else []
        if not caption or len(dates) != 1:
            raise ValueError('PMAA title/date missing')
        stamp = _dated(dates[0].clean())
        title = re.sub(r'\s+', ' ', ''.join(c.text() if isinstance(c, Node) and c not in dates else c if isinstance(c, str) else '' for c in caption.children)).strip()
        body = article.clean()
        for anchor in table.nodes('a'):
            call = anchor.attrs.get('onclick', '')
            if 'fn_www_download2' not in call:
                continue
            match = re.fullmatch(r"\s*fn_www_download2\('([^'\\]+)','([^'\\]+)','([^'\\]+)','([^'\\]+)'\);\s*return false;?\s*", call)
            if not match:
                raise ValueError('invalid PMAA attachment control')
            action, path, physical, name = match.groups()
            if not re.fullmatch(r'[A-Za-z0-9_-]+', path) or not re.fullmatch(r'[A-Za-z0-9_.-]+', physical) or '/' in name or '\\' in name:
                raise ValueError('unsafe PMAA attachment argument')
            endpoint = _same_host_url(action, url)
            attachments.append({'url': endpoint + '?' + urlencode({'path': path, 'physicalName': physical, 'original': name}), 'name': name})
    if not isinstance(title, str) or not title.strip() or not body.strip():
        raise ValueError('official notice title or body missing')
    return {'title': title, 'date': stamp, 'body': body, 'attachments': attachments}
