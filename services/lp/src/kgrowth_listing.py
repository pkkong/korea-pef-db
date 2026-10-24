"""Date-based discovery on Korea Growth's official notice board.

The observed date boundary is evidence about this board, not PE eligibility.
Pinned rows never establish the age boundary. Repeats and safety limits are
reported as incomplete rather than silently treated as a complete year.
"""
from datetime import date, datetime, timedelta
import hashlib
import re
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

try:
    from .lp_board_adapters_pensions import _Document, _date
except ImportError:
    from lp_board_adapters_pensions import _Document, _date

BASE = 'https://www.kgrowth.or.kr/'
LIST_URL = BASE + 'notice.asp?str_type=1&tab=1'


def source_id(url):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (parsed.scheme != 'https' or parsed.hostname not in {'kgrowth.or.kr', 'www.kgrowth.or.kr'}
            or parsed.username or parsed.password or parsed.port not in {None, 443}
            or parsed.path != '/notice_view.asp' or parsed.fragment
            or len(query.get('idx', [])) != 1 or not query['idx'][0].isdigit()
            or any(key in query and query[key] != ['1'] for key in ('str_type', 'tab'))):
        raise ValueError('Invalid Korea Growth notice identity')
    return query['idx'][0]


def parse_listing(html, url):
    if '</html>' not in html.lower():
        raise ValueError('Incomplete Korea Growth listing')
    root = _Document(html).root
    rows = {}
    for node in root.nodes('tr'):
        anchors = []
        for anchor in node.nodes('a'):
            target = urljoin(url, anchor.attrs.get('href', ''))
            try:
                ident = source_id(target)
            except ValueError:
                continue
            anchors.append((ident, anchor, target))
        if not anchors:
            continue
        if len({a[0] for a in anchors}) != 1:
            raise ValueError('Conflicting Korea Growth listing links')
        ident, anchor, target = anchors[0]
        cells = [n for n in node.children if getattr(n, 'tag', None) == 'td']
        if len(cells) < 3:
            raise ValueError('Missing Korea Growth listing columns')
        title = anchor.attrs.get('title') or anchor.clean()
        if not title:
            raise ValueError('Missing Korea Growth listing title')
        row = {'source_id': ident, 'title': title, 'date': _date(cells[2].clean()),
               'url': target, 'pinned': not cells[0].clean().isdigit()}
        if ident in rows and rows[ident] != row:
            raise ValueError('Conflicting Korea Growth listing metadata')
        rows[ident] = row
    if not rows:
        tables = [n for n in root.nodes('table')
                  if {'제목', '첨부'}.issubset({h.clean() for h in n.nodes('th')})]
        empty = r'(?:등록된|검색된|조회된)\s*(?:게시물|게시글|자료|내용|결과)(?:이|가)?\s*없'
        if not tables or not all(re.search(empty, n.clean()) for n in tables):
            raise ValueError('Unrecognized Korea Growth listing, not confirmed empty')
    return list(rows.values())


def discover_window(fetch, *, days=365, as_of=None, max_pages=20):
    if not 1 <= days <= 366 or not 1 <= max_pages <= 20:
        raise ValueError('Korea Growth discovery safety limit invalid')
    end = date.fromisoformat(as_of) if as_of else datetime.now(ZoneInfo('Asia/Seoul')).date()
    start = end - timedelta(days=days - 1)
    report = {'window': {'start': start.isoformat(), 'end': end.isoformat(), 'days': days},
              'boundary': 'page_limit', 'complete': False, 'rows': [], 'receipts': []}
    observed = {}
    seen_regular = set()
    prior_regular_date = None
    for page in range(1, max_pages + 1):
        url = LIST_URL if page == 1 else LIST_URL + '&page=' + str(page)
        raw = fetch(url)
        html = raw.decode('cp949')
        receipt = {'page': page, 'url': url, 'sha256': hashlib.sha256(raw).hexdigest(),
                   'html': html, 'row_count': None}
        report['receipts'].append(receipt)
        rows = parse_listing(html, url)
        receipt['row_count'] = len(rows)
        regular = [row for row in rows if not row['pinned']]
        ids = {row['source_id'] for row in regular}
        # A pinned row on every page is not progress through the dated stream.
        if rows and (not regular or not ids - seen_regular):
            report['boundary'] = 'repeated_or_pinned_only_page'
            break
        for row in rows:
            ident = row['source_id']
            if ident in observed and any(observed[ident][key] != row[key] for key in ('title', 'date', 'pinned')):
                raise ValueError('Conflicting Korea Growth metadata across pages')
            observed[ident] = row
        for row in regular:
            stamp = row['date']
            if prior_regular_date is not None and stamp > prior_regular_date:
                raise ValueError('Korea Growth listing is not in descending publication order')
            prior_regular_date = stamp
        seen_regular.update(ids)
        if not rows:
            report.update(boundary='confirmed_empty', complete=True)
            break
        if regular and all(row['date'] < start.isoformat() for row in regular):
            report.update(boundary='observed_older_page', complete=True)
            break
    # Old pinned notices are retained as board notices, not counted in the year.
    report['rows'] = [row for row in observed.values()
                      if row['pinned'] or start.isoformat() <= row['date'] <= end.isoformat()]
    return report
