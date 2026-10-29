"""Retain one bounded official response for diagnosis; never publish it."""
import argparse
import hashlib
import json
import re
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

from collect_kgrowth_programs import LIST_URL, notice_url, parse_notice

MAX_BYTES = 12 * 1024 * 1024


def source_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,8}', value):
        raise ValueError('Source ID must be an integer from 1 to 999999999')
    return int(value)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Unexpected official source redirect')


def fetch(url):
    # Match the collector's anonymous cookie session, timeout and retry policy.
    opener = build_opener(HTTPCookieProcessor(CookieJar()), NoRedirect())
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': LIST_URL})
    for attempt in range(3):
        try:
            try:
                response = opener.open(request, timeout=25)
            except HTTPError as error:
                response = error
            with response:
                if response.geturl() != url:
                    raise ValueError('Unexpected official source final route')
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError('Official response exceeds 12 MiB')
                return response.code, response.geturl(), raw
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def diagnose(value, output, transport=fetch):
    identifier = source_id(value)
    url = notice_url(identifier)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = {'source_id': str(identifier), 'url': url, 'status': None,
              'final_url': None, 'size': None, 'sha256': None,
              'parse_result': 'not_attempted', 'error_type': None}
    try:
        status, final_url, raw = transport(url)
        if final_url != url:
            raise ValueError('Unexpected official source final route')
        if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
            raise ValueError('Invalid or oversized official response')
        result.update(status=status, final_url=final_url, size=len(raw),
                      sha256=hashlib.sha256(raw).hexdigest())
        (output / 'response.html').write_bytes(raw)
        if status != 200:
            result.update(parse_result='http_error', error_type='HTTPError')
        else:
            try:
                parsed = parse_notice(identifier, raw)
                result.update(parse_result='parsed', title=parsed['title'], date=parsed['date'])
            except (ValueError, UnicodeError) as error:
                result.update(parse_result='invalid_content', error_type=type(error).__name__)
    except Exception as error:
        # Do not record exception messages, response headers, cookies or environment.
        result.update(parse_result='transport_error', error_type=type(error).__name__)
    (output / 'metadata.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-id', required=True)
    parser.add_argument('--output', type=Path, default=Path('/tmp/kgrowth-diagnostic'))
    args = parser.parse_args()
    print(json.dumps(diagnose(args.source_id, args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
