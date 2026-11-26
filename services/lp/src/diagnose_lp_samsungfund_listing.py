"""Retain one Samsung OCIO listing response with the production request headers."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

try:
    from . import collect_lp_institution_boards as boards
    from .lp_kgrowth_history_replay import _NoRedirect
except ImportError:
    import collect_lp_institution_boards as boards
    from lp_kgrowth_history_replay import _NoRedirect


LIMIT = 2_000_000
_SAFE_HEADERS = ('Content-Type', 'Content-Length', 'Content-Encoding', 'Transfer-Encoding', 'Server', 'Date')


def fetch(url, headers):
    try:
        response = build_opener(_NoRedirect()).open(Request(url, headers=headers), timeout=20)
    except HTTPError as error:
        response = error
    with response:
        retained = {key: response.headers[key] for key in _SAFE_HEADERS if key in response.headers}
        return response.status, response.geturl(), retained, response.read(LIMIT + 1)


def capture(out, acquire=fetch):
    config = boards.load_configs()['moel_iaci_ocio']
    url = next(boards.listing_urls(config))
    headers = boards.request_headers(config['listing_url'])
    out.mkdir(parents=True, exist_ok=False)
    result = {'channel': 'moel_iaci_ocio', 'url': url, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'request_headers': headers, 'requests': 1, 'published': False, 'database_writes': 0}
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
            rows = boards.adapter(config).parse_listing(body.decode('utf-8'), url, config)
            result.update(row_count=len(rows), notice_ids=[row['source_id'] for row in rows])
        except (UnicodeError, ValueError) as error:
            result.update(parse_error=str(error)[:240])
    (out / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = capture(args.out)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
