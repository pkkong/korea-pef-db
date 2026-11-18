"""Preserve one public press-list response; never parse or approve its rows.

The press board is a new, unverified source contract. Even an unblocked capture
only means that its bounded response was retained, not that the board is healthy
or its notices, programs, attachments or manager rosters were verified.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import re
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


KIND = 'lp_kgrowth_press_probe_v1'
PRESS_LISTING_URL = 'https://www.kgrowth.or.kr/notice.asp?str_type=3&tab=1'
_PRESS_FORM = {'search_colume': 'Title', 'str_type': '3', 'pagesize': '10',
               'orderby': '1', 'notice_type': '1', 'tab': '1'}
MAX_DETAIL_BYTES = 12 * 1024 * 1024
TIMEOUT_SECONDS = 25


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def press_search_url(term):
    """Encode the observed first-page title form using its declared charset."""
    if not re.fullmatch(r'[가-힣A-Za-z0-9· ]{2,60}', term) or term != term.strip():
        raise ValueError('성장금융 보도자료 검색어 형식 불일치')
    query = urlencode({**_PRESS_FORM, 'search_text': term}, encoding='euc-kr')
    return PRESS_LISTING_URL.split('?')[0] + '?' + query


def _fetch(url):
    """One workflow-only GET, with ordinary TLS verification and no credentials.

    HTTP error bodies are observations too. No cookies, response headers,
    redirects, proxy credentials, authentication handlers or retries are used.
    The extra byte detects an oversized body without reading it unboundedly.
    """
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    request = Request(url, method='GET', headers={
        'User-Agent': 'Mozilla/5.0 (LP public source verification)',
        'Accept-Encoding': 'identity',
    })
    try:
        response = opener.open(request, timeout=TIMEOUT_SECONDS)
    except HTTPError as error:
        response = error
    with response:
        return {'raw': response.read(MAX_DETAIL_BYTES + 1),
                'http_status': response.getcode(), 'geturl': response.geturl()}


def fetch_press_listing(url):
    if url != PRESS_LISTING_URL:
        raise ValueError('허용된 성장금융 보도자료 목록 주소가 아님')
    return _fetch(url)


def fetch_press_search(url):
    query = parse_qsl(urlsplit(url).query, keep_blank_values=True, encoding='euc-kr', errors='strict')
    terms = [term for key, term in query if key == 'search_text']
    if len(terms) != 1 or url != press_search_url(terms[0]):
        raise ValueError('허용된 보도자료 첫 제목 검색 주소가 아님')
    return _fetch(url)


def _checked_at(value):
    value = datetime.now(timezone.utc).isoformat() if value is None else value
    if not isinstance(value, str):
        raise ValueError('관측시각은 시간대가 있는 ISO 문자열이어야 함')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
        raise ValueError('시간대 없는 관측시각 또는 미래 관측시각')
    return value


def _complete_html(raw):
    if not re.search(br'<html(?:\s[^>]*)?>', raw, re.I) or not re.search(br'<body(?:\s[^>]*)?>', raw, re.I):
        return False
    closing = re.search(br'</body\s*>\s*</html\s*>', raw, re.I)
    if not closing:
        return False
    tail = raw[closing.end():].strip()
    if not tail:
        return True
    # The retained board-3 response appends a complete style and script pair
    # after </html>. Accept only that witnessed order and exact type markers;
    # unknown markup or an incomplete block remains a diagnostic hold.
    for tag, mime in ((b'style', b'text/css'), (b'script', b'text/javascript')):
        opened = re.match(br'<' + tag + br'\s+type="' + mime + br'"\s*>', tail, re.I)
        if not opened:
            return False
        ended = re.search(br'</' + tag + br'\s*>', tail[opened.end():], re.I)
        if not ended:
            return False
        tail = tail[opened.end() + ended.end():].strip()
    return not tail


def _validate_response(response, report, *, expected_url=PRESS_LISTING_URL):
    """Minimal capture checks, called only after persisting the observation."""
    if not isinstance(response, dict):
        raise ValueError('목록 응답 형식 미확인')
    if not isinstance(response.get('raw'), bytes):
        raise ValueError('목록 원응답이 bytes가 아님; wire 바이트를 추정하지 않음')
    if type(response.get('http_status')) is not int:
        raise ValueError('목록 HTTP 상태 타입 미확인')
    if response.get('geturl') != expected_url:
        raise ValueError('목록 응답 주소 변경 또는 실제 응답 주소 미확인')
    if response['http_status'] != 200:
        raise ValueError('목록 HTTP 응답 거절: ' + str(response['http_status']))
    if report['truncated']:
        raise ValueError('목록 응답 12MiB 상한 초과; 보존 구간은 전체 원문이 아님')
    raw = response['raw']
    if not raw:
        raise ValueError('목록 원응답이 비어 있음')
    # ASCII tag boundaries work for UTF-8 and CP949 without guessing or
    # transforming the source encoding. This is not a listing/row parser.
    if not _complete_html(raw):
        raise ValueError('목록 HTML 완결성 미확인')


def _capture(url, fetch, *, checked_at, retain):
    """Retain a single allowed observation before any response validation.

    ``fetch`` returns only the useful values ``raw``, ``http_status``, ``geturl``;
    extra headers/cookies/opaque values are ignored. Non-byte values never gain
    invented wire bytes or hashes. Oversized byte responses retain a bounded
    prefix with its own hash and an explicit truncation/lower-bound marker.

    A retention error propagates. A failed request/response never causes retry.
    """
    stamp = _checked_at(checked_at)
    if not callable(fetch) or not callable(retain):
        raise ValueError('목록 fetch와 원응답 보존 함수가 필요함')
    report = {'kind': KIND, 'source_institution_id': 'kgrowth', 'board_type': 3,
              'url': url, 'checked_at': stamp, 'requests': 0,
              'response_url': None, 'http_status': None, 'response_type': None,
              'http_status_type': None, 'response_url_type': None,
              'raw_type': None, 'bytes': None, 'observed_bytes': None,
              'sha256': None, 'raw_base64': None, 'truncated': False,
              'observed_bytes_is_lower_bound': False, 'response_retained': False,
              'full_response_retained': False,
              'capture_status': 'planned', 'holds': [], 'parsed': False,
              'source_health_verified': False, 'publication_ready': False,
              'published': False, 'database_reads': 0, 'database_writes': 0}
    retain(copy.deepcopy(report))
    report['requests'] = 1
    response, failure = None, None
    try:
        response = fetch(url)
    except Exception as error:
        # Exception repr/messages may contain opaque headers or credentials.
        failure = type(error).__name__
    report['response_type'] = type(response).__name__
    raw = response.get('raw') if isinstance(response, dict) else None
    report['raw_type'] = type(raw).__name__
    if isinstance(raw, bytes):
        prefix = raw[:MAX_DETAIL_BYTES]
        report.update(bytes=len(prefix), observed_bytes=len(raw),
                      sha256=hashlib.sha256(prefix).hexdigest(),
                      raw_base64=base64.b64encode(prefix).decode('ascii'),
                      truncated=len(raw) > MAX_DETAIL_BYTES,
                      observed_bytes_is_lower_bound=len(raw) > MAX_DETAIL_BYTES)
    if isinstance(response, dict):
        status, response_url = response.get('http_status'), response.get('geturl')
        # Keep primitive status evidence, never arbitrary object reprs.
        report['http_status_type'], report['response_url_type'] = type(status).__name__, type(response_url).__name__
        report['http_status'] = status if type(status) in (int, bool) else None
        report['response_url'] = response_url if isinstance(response_url, str) else None
    report['capture_status'] = 'observed'
    retain(copy.deepcopy(report))  # bytes/status/URL first; validation is next
    report['response_retained'] = isinstance(raw, bytes)
    report['full_response_retained'] = isinstance(raw, bytes) and not report['truncated']
    try:
        if failure:
            raise ValueError('목록 요청 실패: ' + failure)
        _validate_response(response, report, expected_url=url)
    except ValueError as error:
        report['holds'].append({'url': url, 'reason': str(error)})
    report['capture_status'] = 'held' if report['holds'] else 'response_retained'
    retain(copy.deepcopy(report))
    return report


def capture_press_listing(fetch, *, checked_at=None, retain=lambda report: None):
    return _capture(PRESS_LISTING_URL, fetch, checked_at=checked_at, retain=retain)


def _validate_search_echo(raw, term):
    try:
        from .collect_shared_lp_notices import Document
    except ImportError:
        from collect_shared_lp_notices import Document
    text = raw.decode('cp949')
    doc = Document(text).root
    if [n.clean() for n in doc.nodes('title')] != ['보도자료 > 공지사항 > 한국성장금융투자운용']:
        raise ValueError('보도자료 검색 응답 페이지 제목 불일치')
    forms = [f for f in doc.nodes('form') if f.attrs.get('name') == 'search' and f.attrs.get('id') == 'search']
    if (len(forms) != 1 or forms[0].attrs.get('method', '').lower() != 'get'
            or forms[0].attrs.get('action') not in (None, '', '/notice.asp')):
        raise ValueError('보도자료 검색 응답의 제목 검색 양식 미확인')
    fields = [(i.attrs.get('name'), i.attrs.get('value')) for i in forms[0].nodes('input')]
    expected = {**_PRESS_FORM, 'search_text': term}
    if len(fields) != len(expected) or dict(fields) != expected:
        raise ValueError('보도자료 검색 조건 또는 검색어 응답 불일치')


def capture_press_search(terms, fetch, *, checked_at=None, retain=lambda report: None):
    """Request a bounded batch of observed-form searches; verify echo, not rows."""
    if not 1 <= len(terms) <= 2 or len(set(terms)) != len(terms):
        raise ValueError('보도자료 검색어는 중복 없이 최대 두 개')
    targets = [(term, press_search_url(term)) for term in terms]
    reports = []
    for term, url in targets:
        def retain_current(receipt):
            retain(reports + [receipt])
        report = _capture(url, fetch, checked_at=checked_at, retain=retain_current)
        report['search_term'] = term
        report['search_echo_verified'] = False
        if not report['holds']:
            try:
                _validate_search_echo(base64.b64decode(report['raw_base64'], validate=True), term)
            except ValueError as error:
                report['holds'].append({'url': url, 'reason': str(error)})
                report['capture_status'] = 'held'
            else:
                report['search_echo_verified'] = True
        reports.append(report)
        retain(copy.deepcopy(reports))
    return reports
