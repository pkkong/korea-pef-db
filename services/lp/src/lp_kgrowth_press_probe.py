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


def _page_fields(term, page):
    return {'page': str(page), 'search_colume': 'Title', 'search_text': term,
            'SearchValue': '', 'SearchMode': '', 'SearchGubun': '', 'str_year': '',
            'str_type': '3', 'str_num': '', 'pagesize': '10', 'orderby': '1',
            'notice_type': '1', 'tab': '1'}


def _followup_url(term):
    press_search_url(term)  # The same source-derived term/encoding limits.
    return PRESS_LISTING_URL.split('?')[0] + '?' + urlencode(_page_fields(term, 2), encoding='euc-kr')


def fetch_press_followup(url):
    """Transport guard only; capture_press_followup verifies the prior proof."""
    fields = parse_qsl(urlsplit(url).query, keep_blank_values=True, encoding='euc-kr', errors='strict')
    terms = [value for key, value in fields if key == 'search_text']
    if len(terms) != 1 or url != _followup_url(terms[0]):
        raise ValueError('허용된 보도자료 검색 2쪽 주소가 아님')
    return _fetch(url)


def _page_contract(raw, term, page):
    """Validate visible pagination/form evidence, without extracting notice IDs."""
    try:
        from .collect_shared_lp_notices import Document
    except ImportError:
        from collect_shared_lp_notices import Document
    _validate_search_echo(raw, term)
    root = Document(raw.decode('cp949')).root
    charset = [n.attrs.get('content', '') for n in root.nodes('meta')
               if n.attrs.get('http-equiv', '').lower() == 'content-type']
    if len(charset) != 1 or not re.search(r'charset\s*=\s*euc-kr\b', charset[0], re.I):
        raise ValueError('보도자료 페이지의 원문 문자셋 미확인')
    forms = [f for f in root.nodes('form') if f.attrs.get('name') == 'List']
    if (len(forms) != 1 or forms[0].attrs.get('method', '').lower() != 'get'
            or forms[0].attrs.get('action') not in (None, '', '/notice.asp')):
        raise ValueError('보도자료 페이지 이동 원양식 미확인')
    inputs = list(forms[0].nodes('input'))
    fields = [(i.attrs.get('name'), i.attrs.get('value')) for i in inputs]
    expected = _page_fields(term, page)
    if (len(fields) != len(expected) or len(dict(fields)) != len(fields)
            or any(i.attrs.get('type', '').lower() != 'hidden' for i in inputs)
            or dict(fields).get('page') not in (None, '', str(page))
            or {k: v for k, v in fields if k != 'page'} != {k: v for k, v in expected.items() if k != 'page'}):
        raise ValueError('보도자료 페이지 이동의 전체 필드·검색어 불일치')
    totals = [n for n in root.nodes('div') if 'total_wrap' in n.attrs.get('class', '').split()]
    counts = re.findall(r'전체\s*(\d+)\s*개의\s*글이\s*있습니다\.', totals[0].clean()) if len(totals) == 1 else []
    tables = [n for n in root.nodes('table') if 'notice_tbl' in n.attrs.get('class', '').split()]
    if (len(counts) != 1 or len(tables) != 1
            or [n.clean() for n in tables[0].nodes('th')] != ['번호', '제목', '작성일', '첨부']):
        raise ValueError('보도자료 전체 건수·목록 표 구조 미확인')
    total = int(counts[0])
    # Count the observed rows only; no source ID, title, date or GP is emitted.
    rows = [n for n in tables[0].nodes('tr') if list(n.nodes('td')) and list(n.nodes('a'))]
    if len(rows) != min(10, max(0, total - (page - 1) * 10)):
        raise ValueError('보도자료 페이지의 표시 행 수 불일치')
    if total == 0 and not re.search(r'등록된\s*글이\s*없습니다\.', tables[0].clean()):
        raise ValueError('보도자료 빈 검색 결과 표시 미확인')
    pagers = [n for n in root.nodes('p') if 'page' in n.attrs.get('class', '').split()]
    links = [a for p in pagers for a in p.nodes('a')]
    current = [a for a in links if '현재 페이지' in a.attrs.get('title', '')]
    if total:
        if (len(pagers) != 1 or len(current) != 1
                or current[0].attrs.get('title') != f'{page} 페이지로 이동 [현재 페이지]'
                or current[0].attrs.get('href', '').lower() != f'javascript:listview({page},3,0)'
                or current[0].clean() != str(page)):
            raise ValueError('보도자료 현재 페이지 표시 불일치')
    elif current:
        raise ValueError('보도자료 빈 결과와 현재 페이지 표시 충돌')
    if any(not re.fullmatch(r'Javascript:ListView\([1-9]\d*,3,0\)', a.attrs.get('href', ''), re.I) for a in links):
        raise ValueError('보도자료 페이지 이동의 게시판·그룹 불일치')
    return {'total_count': total, 'observed_row_count': len(rows), 'current_page': page if total else None,
            'page_two_offered': any(a.attrs['href'].lower() == 'javascript:listview(2,3,0)' for a in links)}


def _prior_search_receipt(receipt, term, checked_at):
    if not isinstance(receipt, dict):
        raise ValueError('선행 보도자료 원영수증 형식 불일치')
    url = press_search_url(term)
    if (receipt.get('kind') != KIND or receipt.get('source_institution_id') != 'kgrowth'
            or type(receipt.get('board_type')) is not int or receipt['board_type'] != 3
            or receipt.get('url') != url or receipt.get('response_url') != url
            or type(receipt.get('requests')) is not int or receipt['requests'] != 1
            or receipt.get('search_term') != term or receipt.get('search_echo_verified') is not True
            or receipt.get('capture_status') != 'response_retained' or receipt.get('holds') != []
            or any(receipt.get(k) is not True for k in ('response_retained', 'full_response_retained'))
            or any(receipt.get(k) is not False for k in ('truncated', 'observed_bytes_is_lower_bound', 'parsed',
                                                       'source_health_verified', 'publication_ready', 'published'))
            or receipt.get('raw_type') != 'bytes' or receipt.get('response_type') != 'dict'
            or receipt.get('http_status_type') != 'int' or receipt.get('response_url_type') != 'str'
            or any(type(receipt.get(k)) is not int or receipt[k] != 0 for k in ('database_reads', 'database_writes'))):
        raise ValueError('선행 보도자료 원영수증의 출처·완료 상태 불일치')
    if not isinstance(receipt.get('checked_at'), str):
        raise ValueError('선행 보도자료 관측시각 누락')
    prior_time = _checked_at(receipt['checked_at'])
    if datetime.fromisoformat(prior_time.replace('Z', '+00:00')) > datetime.fromisoformat(checked_at.replace('Z', '+00:00')):
        raise ValueError('선행 보도자료 관측시각이 후속 관측시각보다 늦음')
    encoded = receipt.get('raw_base64')
    if not isinstance(encoded, str) or len(encoded) > (MAX_DETAIL_BYTES + 2) // 3 * 4:
        raise ValueError('선행 보도자료 원바이트 누락·상한 초과')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('선행 보도자료 원바이트 인코딩 불일치') from error
    if (any(type(receipt.get(k)) is not int or receipt[k] != len(raw) for k in ('bytes', 'observed_bytes'))
            or hashlib.sha256(raw).hexdigest() != receipt.get('sha256')):
        raise ValueError('선행 보도자료 원바이트 크기·SHA 불일치')
    _validate_response({'raw': raw, 'http_status': receipt.get('http_status'), 'geturl': url}, receipt, expected_url=url)
    return _page_contract(raw, term, 1)


def capture_press_followup(prior_capture, expected_terms, fetch, *, checked_at=None, retain=lambda report: None):
    """Revalidate a retained first-search batch and capture its unique page 2."""
    stamp = _checked_at(checked_at)
    if (not isinstance(expected_terms, (list, tuple)) or not 1 <= len(expected_terms) <= 2
            or any(not isinstance(t, str) for t in expected_terms) or len(set(expected_terms)) != len(expected_terms)):
        raise ValueError('선행 보도자료 원검색어는 중복 없이 최대 두 개')
    if (not isinstance(prior_capture, dict) or prior_capture.get('kind') != 'lp_kgrowth_press_search_v1'
            or prior_capture.get('review_scope') != 'press_search' or prior_capture.get('holds') != []
            or type(prior_capture.get('requests')) is not int or prior_capture['requests'] != len(expected_terms)
            or any(prior_capture.get(k) is not False for k in ('parsed', 'source_health_verified', 'publication_ready', 'published'))):
        raise ValueError('선행 보도자료 검색 묶음의 종류·상태 불일치')
    receipts = prior_capture.get('receipts')
    if (not isinstance(receipts, list) or len(receipts) != len(expected_terms)
            or any(not isinstance(r, dict) for r in receipts)
            or any(not isinstance(r.get('search_term'), str) for r in receipts)
            or sorted(r.get('search_term', '') for r in receipts) != sorted(expected_terms)):
        raise ValueError('선행 보도자료 검색 묶음과 원검색어 불일치')
    candidates = []
    for term in expected_terms:
        receipt = next(r for r in receipts if r.get('search_term') == term)
        contract = _prior_search_receipt(receipt, term, stamp)
        if contract['page_two_offered'] and contract['total_count'] > 10:
            candidates.append((term, receipt, contract))
    if len(candidates) != 1:
        raise ValueError('선행 증거에 검색 2쪽 대상이 하나로 확인되지 않음')
    term, prior, previous = candidates[0]
    url = _followup_url(term)
    context = {'kind': 'lp_kgrowth_press_followup_v1', 'review_scope': 'press_followup',
               'source_institution_id': 'kgrowth', 'board_type': 3, 'search_term': term, 'requested_page': 2,
               'prior_receipt_sha256': prior['sha256'], 'prior_receipt_url': prior['url'],
               'prior_checked_at': prior['checked_at'], 'prior_page_contract': previous,
               'search_echo_verified': False, 'current_page_verified': False,
               'parsed': False, 'source_health_verified': False, 'publication_ready': False, 'published': False,
               'database_reads': 0, 'database_writes': 0}
    def save(receipt):
        retain({**copy.deepcopy(context), 'requests': receipt['requests'], 'receipts': [copy.deepcopy(receipt)],
                'search_echo_verified': receipt.get('search_echo_verified', False),
                'current_page_verified': receipt.get('current_page_verified', False),
                'holds': copy.deepcopy(receipt['holds'])})
    report = _capture(url, fetch, checked_at=stamp, retain=save)
    report.update(search_term=term, requested_page=2, search_echo_verified=False, current_page_verified=False)
    if not report['holds']:
        try:
            contract = _page_contract(base64.b64decode(report['raw_base64'], validate=True), term, 2)
            if contract['total_count'] != previous['total_count']:
                raise ValueError('보도자료 검색 전체 건수가 선행 원문과 다름')
        except ValueError as error:
            report['holds'].append({'url': url, 'reason': str(error)})
            report['capture_status'] = 'held'
        else:
            report.update(search_echo_verified=True, current_page_verified=True, page_contract=contract)
    save(report)
    return {**context, 'requests': report['requests'], 'receipts': [report],
            'search_echo_verified': report['search_echo_verified'], 'current_page_verified': report['current_page_verified'],
            'holds': copy.deepcopy(report['holds'])}
