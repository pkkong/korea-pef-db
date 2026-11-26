"""Retain one Samsung OCIO listing response with the production request headers."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

try:
    from . import collect_lp_institution_boards as boards
    from . import lp_board_adapter_samsungfund as samsung
    from .lp_kgrowth_history_replay import _NoRedirect
except ImportError:
    import collect_lp_institution_boards as boards
    import lp_board_adapter_samsungfund as samsung
    from lp_kgrowth_history_replay import _NoRedirect


LIMIT = 2_000_000
_SAFE_HEADERS = ('Content-Type', 'Content-Length', 'Content-Encoding', 'Transfer-Encoding', 'Server', 'Date')
_DESKTOP_LIST = 'https://www.samsungfund.com/fund/lounge/notice.do'
_DESKTOP_LINK = re.compile(r'notice-view\.do\?no=([1-9]\d{0,9})&searchText=([^&]*)')


def fetch(url, headers):
    try:
        response = build_opener(_NoRedirect()).open(Request(url, headers=headers), timeout=20)
    except HTTPError as error:
        response = error
    with response:
        retained = {key: response.headers[key] for key in _SAFE_HEADERS if key in response.headers}
        return response.status, response.geturl(), retained, response.read(LIMIT + 1)


def _desktop_rows(html, config):
    institution, fund = samsung._fund(config)
    if len(html) > LIMIT or html.lower().count('</html>') != 1:
        raise ValueError('삼성자산운용 데스크톱 검색 응답이 완결되지 않음')
    doc = samsung._Document(html).root
    main = samsung._one(doc.nodes('main', 'notice-wrap'), '삼성자산운용 데스크톱 공지 영역')
    field = samsung._one((n for n in main.nodes('input') if n.attrs.get('name') == 'searchText'), '공지 검색어')
    if field.attrs.get('value') != fund:
        raise ValueError('삼성자산운용 데스크톱 공지 검색어 불일치')
    area = samsung._one(main.nodes('div', 'list-wrap'), '삼성자산운용 데스크톱 목록')
    listing = samsung._one(area.nodes('ul', 'list'), '삼성자산운용 데스크톱 목록 행')
    items = list(listing.nodes('li'))
    if not 1 <= len(items) <= samsung.PAGE_ROWS:
        raise ValueError('삼성자산운용 데스크톱 목록 행 수 불일치')
    rows = []
    for item in items:
        link = samsung._one(item.nodes('a'), '삼성자산운용 데스크톱 공지 상세')
        found = _DESKTOP_LINK.fullmatch(link.attrs.get('href', ''))
        title = samsung._one(link.nodes('h3'), '삼성자산운용 데스크톱 공지 제목').clean()
        day = samsung._one(link.nodes('span', 'date'), '삼성자산운용 데스크톱 공지 날짜').clean()
        if not found or found[2] != fund or not title or not re.fullmatch(r'20\d{2}\.\d{2}\.\d{2}', day):
            raise ValueError('삼성자산운용 데스크톱 공지 상세 주소·제목·날짜 불일치')
        rows.append({'source_id': f'{institution}:samsungfund:{found[1]}', 'title': title, 'date': samsung._date(day),
                     'institution_id': institution if samsung.is_pe_result(title, fund) else None})
    if len({row['source_id'] for row in rows}) != len(rows):
        raise ValueError('삼성자산운용 데스크톱 공지 식별자 중복')
    return rows


def capture(out, acquire=fetch, *, desktop=False):
    config = boards.load_configs()['moel_iaci_ocio']
    if desktop:
        _, fund = samsung._fund(config)
        url = f'{_DESKTOP_LIST}?{urlencode({"searchText": fund})}'
        headers = boards.request_headers(_DESKTOP_LIST)
    else:
        url = next(boards.listing_urls(config))
        headers = boards.request_headers(config['listing_url'])
    out.mkdir(parents=True, exist_ok=False)
    result = {'channel': 'moel_iaci_ocio', 'url': url, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'view': 'desktop' if desktop else 'mobile', 'request_headers': headers,
              'requests': 1, 'published': False, 'database_writes': 0}
    try:
        status, final_url, observed, raw = acquire(url, headers)
    except OSError as error:
        result.update(transport_error=type(error).__name__)
        (out / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        return result
    body = raw[:LIMIT]
    (out / 'response.bin').write_bytes(body)
    result.update(http_status=status, final_url=final_url, response_headers=observed, bytes=len(body),
                  sha256=hashlib.sha256(body).hexdigest(), truncated=len(raw) > LIMIT)
    (out / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    if status == 200 and final_url == url and not result['truncated']:
        try:
            html = body.decode('utf-8')
            rows = _desktop_rows(html, config) if desktop else boards.adapter(config).parse_listing(html, url, config)
            result.update(row_count=len(rows), notice_ids=[row['source_id'] for row in rows],
                          pe_result_ids=[row['source_id'] for row in rows if row['institution_id']])
        except (UnicodeError, ValueError) as error:
            result.update(parse_error=str(error)[:240])
    (out / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--desktop', action='store_true')
    args = parser.parse_args()
    result = capture(args.out, desktop=args.desktop)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
