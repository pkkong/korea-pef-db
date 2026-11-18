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
from datetime import date, datetime, timezone
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener


KIND = 'lp_kgrowth_press_probe_v1'
PRESS_LISTING_URL = 'https://www.kgrowth.or.kr/notice.asp?str_type=3&tab=1'
_PRESS_FORM = {'search_colume': 'Title', 'str_type': '3', 'pagesize': '10',
               'orderby': '1', 'notice_type': '1', 'tab': '1'}
MAX_DETAIL_BYTES = 12 * 1024 * 1024
TIMEOUT_SECONDS = 25
_DETAIL_SUFFIX = """<script type="text/javascript">
<!--
var tab = '1';
$(function(){
//if (tab != '') {
var sT = $('#notice2').offset().top - $('header').outerHeight() + 20;
$(document).scrollTop(sT, 0);
//}
});
//-->
</script>"""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def press_search_url(term):
    """Encode the observed first-page title form using its declared charset."""
    if not re.fullmatch(r'[가-힣A-Za-z0-9· ]{2,60}', term) or term != term.strip():
        raise ValueError('성장금융 보도자료 검색어 형식 불일치')
    query = urlencode({**_PRESS_FORM, 'search_text': term}, encoding='euc-kr')
    return PRESS_LISTING_URL.split('?')[0] + '?' + query


def _fetch(url, *, opener=None, referer=None):
    """One workflow-only GET, with ordinary TLS verification and no credentials.

    HTTP error bodies are observations too. No redirects, proxy credentials,
    authentication handlers or retries are used. The extra byte detects overflow.
    """
    opener = opener or build_opener(ProxyHandler({}), _NoRedirect())
    headers = {
        'User-Agent': 'Mozilla/5.0 (LP public source verification)',
        'Accept-Encoding': 'identity',
    }
    if referer:
        headers['Referer'] = referer
    request = Request(url, method='GET', headers=headers)
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


def _validate_wire_response(response, report, *, expected_url):
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
    return raw


def _validate_response(response, report, *, expected_url=PRESS_LISTING_URL):
    """Minimal capture checks, called only after persisting the observation."""
    raw = _validate_wire_response(response, report, expected_url=expected_url)
    # ASCII tag boundaries work for UTF-8 and CP949 without guessing or
    # transforming the source encoding. This is not a listing/row parser.
    if not _complete_html(raw):
        raise ValueError('목록 HTML 완결성 미확인')


def _capture(url, fetch, *, checked_at, retain, validate=_validate_response):
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
        validate(response, report, expected_url=url)
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


def _press_detail_url(value, term=None):
    """Canonicalise only the observed board-3 page-2 notice-link fields."""
    parsed = urlsplit(value)
    fields = parse_qsl(parsed.query, keep_blank_values=True, encoding='euc-kr', errors='strict')
    query = dict(fields)
    if (parsed.scheme != 'https' or parsed.netloc != 'www.kgrowth.or.kr'
            or parsed.path != '/notice_view.asp' or parsed.fragment
            or len(fields) != 6 or set(query) != {'page', 'search_colume', 'search_text', 'idx', 'str_type', 'tab'}
            or query.get('page') != '2' or query.get('search_colume') != 'Title'
            or query.get('str_type') != '3' or query.get('tab') != '1'
            or not re.fullmatch(r'[1-9]\d*', query.get('idx', ''))
            or term is not None and query.get('search_text') != term):
        raise ValueError('보도자료 상세 링크의 출처·게시판·검색어·ID 경계 불일치')
    press_search_url(query['search_text'])
    return 'https://www.kgrowth.or.kr/notice_view.asp?' + urlencode(fields, encoding='euc-kr'), query['idx']


def fetch_press_detail(url):
    """Strict one-shot transport; the capture API requires retained list proof."""
    canonical, _ = _press_detail_url(url)
    if canonical != url:
        raise ValueError('허용된 보도자료 상세 요청 주소가 아님')
    return _fetch(url)


def _same_proof(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_proof(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_proof(a, b) for a, b in zip(left, right))
    return left == right


def _verified_followup(first_capture, followup_capture, expected_terms, checked_at):
    if not isinstance(followup_capture, dict):
        raise ValueError('보도자료 2쪽 보존 묶음 형식 불일치')
    receipts = followup_capture.get('receipts')
    if not isinstance(receipts, list) or len(receipts) != 1 or not isinstance(receipts[0], dict):
        raise ValueError('보도자료 2쪽 원영수증이 하나가 아님')
    receipt = receipts[0]
    if not isinstance(receipt.get('checked_at'), str):
        raise ValueError('보도자료 2쪽 관측시각 누락')
    observed = _checked_at(receipt['checked_at'])
    if datetime.fromisoformat(observed.replace('Z', '+00:00')) > datetime.fromisoformat(checked_at.replace('Z', '+00:00')):
        raise ValueError('보도자료 2쪽 관측시각이 상세 관측시각보다 늦음')
    encoded = receipt.get('raw_base64')
    if not isinstance(encoded, str) or len(encoded) > (MAX_DETAIL_BYTES + 2) // 3 * 4:
        raise ValueError('보도자료 2쪽 원바이트 누락·상한 초과')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('보도자료 2쪽 원바이트 인코딩 불일치') from error
    # This callback replays retained bytes only. No origin request or diagnostic
    # flags supplied by the caller can replace the complete first->second check.
    replayed = capture_press_followup(first_capture, expected_terms, lambda url: {
        'raw': raw, 'http_status': receipt.get('http_status'), 'geturl': receipt.get('response_url')},
        checked_at=observed)
    if (replayed['holds'] or not _same_proof(replayed['receipts'][0], receipt)
            or any(not _same_proof(followup_capture.get(key), value) for key, value in replayed.items() if key != 'receipts')):
        raise ValueError('보도자료 첫 검색→2쪽 원영수증 재생 불일치')
    return raw, receipt, replayed


def _joint_result_listing_target(raw, term, listing_url, observed_at):
    try:
        from .collect_shared_lp_notices import Document
    except ImportError:
        from collect_shared_lp_notices import Document
    root = Document(raw.decode('cp949')).root
    table = next(t for t in root.nodes('table') if 'notice_tbl' in t.attrs.get('class', '').split())
    candidates, seen = [], set()
    previous_date = None
    pattern = (r'\(보도자료\)産銀·성장금융「' + re.escape(re.sub(r'\s+', '', term))
               + r'」[1-9]\d*개운용사최종선정')
    for row in table.nodes('tr'):
        cells = [n for n in row.children if getattr(n, 'tag', '') == 'td']
        if not cells:
            continue
        links = list(row.nodes('a'))
        if len(cells) != 4 or len(links) != 1 or not cells[0].clean().isdigit():
            raise ValueError('보도자료 목록 행의 제목·날짜·링크 구획 미확인')
        title, day = cells[1].clean(), cells[2].clean()
        if not title or title != links[0].clean() or not re.fullmatch(r'20\d{2}-\d{2}-\d{2}', day):
            raise ValueError('보도자료 목록의 제목·게시일 불일치')
        date.fromisoformat(day)
        if day > observed_at[:10] or previous_date is not None and day > previous_date:
            raise ValueError('보도자료 목록의 게시일·정렬 불일치')
        previous_date = day
        href = links[0].attrs.get('href', '')
        url, ident = _press_detail_url(urljoin(listing_url, href), term)
        if ident in seen:
            raise ValueError('보도자료 목록의 공고 ID 중복·충돌')
        seen.add(ident)
        if re.fullmatch(pattern, re.sub(r'\s+', '', title)):
            candidates.append({'source_institution_id': 'kgrowth', 'board_type': 3,
                               'source_id': 'kgrowth:press:' + ident, 'board_record_id': ident,
                               'title': title, 'date': day, 'url': url, 'observed_href': href})
    if len(candidates) != 1:
        raise ValueError('공동 최종 선정 보도자료가 실제 목록에서 하나로 확인되지 않음')
    return candidates[0]


def capture_press_result_detail(first_capture, followup_capture, expected_terms, fetch, *,
                                checked_at=None, retain=lambda report: None):
    """Capture one list-derived result response; its detail template is unknown.

    Selection is discovery only. The observed joint title does not assign the
    article's managers to a particular LP, PE track, business year or round.
    """
    stamp = _checked_at(checked_at)
    raw, prior, replayed = _verified_followup(first_capture, followup_capture, expected_terms, stamp)
    term = replayed['search_term']
    target = _joint_result_listing_target(raw, term, prior['url'], prior['checked_at'])
    context = {'kind': 'lp_kgrowth_press_result_detail_v1', 'review_scope': 'press_result',
               'source_institution_id': 'kgrowth', 'board_type': 3, 'search_term': term,
               'listing_target': target, 'prior_receipt_sha256': prior['sha256'],
               'first_receipt_sha256': replayed['prior_receipt_sha256'],
               'parsed': False, 'source_health_verified': False, 'publication_ready': False, 'published': False,
               'detail_template_verified': False, 'notice_identity_verified': False, 'roster_verified': False,
               'database_reads': 0, 'database_writes': 0}
    def save(receipt):
        retain({**copy.deepcopy(context), 'requests': receipt['requests'],
                'receipts': [copy.deepcopy(receipt)], 'holds': copy.deepcopy(receipt['holds'])})
    report = _capture(target['url'], fetch, checked_at=stamp, retain=save)
    listing_hashes = {r['sha256'] for r in first_capture['receipts']} | {prior['sha256']}
    if not report['holds'] and report['sha256'] in listing_hashes:
        report['holds'].append({'url': target['url'], 'reason': '상세 요청에 선행 목록 원바이트가 반복됨'})
        report['capture_status'] = 'held'
    save(report)
    return {**context, 'requests': report['requests'], 'receipts': [report], 'holds': copy.deepcopy(report['holds'])}


def _complete_press_detail(raw):
    """Only the separately witnessed detail suffix; listing checks stay strict."""
    closing = list(re.finditer(br'</body\s*>\s*</html\s*>', raw, re.I))
    if (len(closing) != 1 or len(re.findall(br'<html(?:\s[^>]*)?>', raw, re.I)) != 1
            or len(re.findall(br'<body(?:\s[^>]*)?>', raw, re.I)) != 1):
        raise ValueError('보도자료 상세 HTML 경계 미확인')
    def lines(value):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if lines(raw[closing[0].end():]) != lines(_DETAIL_SUFFIX.encode('ascii')):
        raise ValueError('보도자료 상세의 관측된 단일 script 끝부분 불일치')


def _press_result_detail_dom(raw, target, term, digest):
    try:
        from .collect_shared_lp_notices import Document
    except ImportError:
        from collect_shared_lp_notices import Document
    _complete_press_detail(raw)
    root = Document(raw.decode('cp949')).root
    def one(nodes, label):
        values = list(nodes)
        if len(values) != 1:
            raise ValueError('보도자료 상세의 ' + label + ' 구획 누락·중복')
        return values[0]
    def cls(node, tag, name):
        return [n for n in node.nodes(tag) if name in n.attrs.get('class', '').split()]
    if [n.clean() for n in root.nodes('title')] != ['보도자료 > 공지사항 > 한국성장금융투자운용']:
        raise ValueError('보도자료 상세 문서 제목 불일치')
    meta = one((n for n in root.nodes('meta') if n.attrs.get('http-equiv', '').lower() == 'content-type'), '문자셋')
    if not re.search(r'charset\s*=\s*euc-kr\b', meta.attrs.get('content', ''), re.I):
        raise ValueError('보도자료 상세 원문 문자셋 미확인')
    wrap = one(cls(root, 'div', 'notice_view_wrap'), '본문 틀')
    inner = one(cls(wrap, 'div', 'notice_view_inner'), '본문 내부 틀')
    if [n.clean() for n in one(cls(inner, 'div', 'noti_view_top'), '게시판 이름').nodes('h3')] != ['보도자료']:
        raise ValueError('보도자료 상세 게시판 이름 불일치')
    article = one(cls(inner, 'div', 'noti_veiw'), '공고')
    info = one(cls(article, 'div', 'view_info'), '제목·날짜')
    title = one(cls(info, 'p', 'tit'), '공고 제목').clean()
    posted = one(cls(info, 'p', 'date'), '게시일')
    day = one(posted.nodes('span'), '게시일 값').clean()
    if title != target['title'] or day != target['date'] or posted.clean() != '작성일 ' + day:
        raise ValueError('보도자료 상세 제목·게시일이 원목록과 다름')
    contents = one(cls(article, 'div', 'veiw_contents'), '공고 본문')
    if len(cls(root, 'div', 'view_info')) != 1 or len(cls(root, 'div', 'veiw_contents')) != 1:
        raise ValueError('보도자료 상세에 이웃 제목·본문 구획이 섞임')
    body = contents.clean()
    compact = re.sub(r'[\s\u200b\xa0]+', '', body)
    business = re.search(r'『' + re.escape(re.sub(r'\s+', '', term)) + r'』(20\d{2})년정시위탁운용사선정결과', compact)
    headline = re.search(r'([1-9]\d*)개운용사최종선정$', re.sub(r'\s+', '', title))
    if (not business or not headline or not all(name in compact for name in ('한국산업은행', '한국성장금융'))
            or not re.search(r'최종' + re.escape(headline[1]) + r'개사가선정되었다고', compact)):
        raise ValueError('보도자료 상세의 공동 정시 최종 선정 본문 불일치')
    files = one(cls(article, 'ul', 'file_list'), '첨부 목록')
    anchors = list(files.nodes('a'))
    if len(anchors) != 2 or len(cls(root, 'ul', 'file_list')) != 1:
        raise ValueError('보도자료 상세의 HWP·PDF 첨부 수 불일치')
    stem = re.sub(r'\s+', ' ', title.replace('産銀·성장금융', '산은 성장금융').replace('「', '').replace('」', '')).strip()
    attachments = {}
    for anchor in anchors:
        name = anchor.clean()
        url = urljoin(target['url'], anchor.attrs.get('href', ''))
        parsed = urlsplit(url)
        fields = parse_qsl(parsed.query, keep_blank_values=True)
        query = dict(fields)
        slot = query.get('SelType')
        if (parsed.scheme != 'https' or parsed.netloc != 'www.kgrowth.or.kr' or parsed.path != '/down_file.asp'
                or parsed.fragment or len(fields) != 2 or set(query) != {'idx', 'SelType'}
                or query.get('idx') != target['board_record_id'] or slot not in ('News1', 'News2')
                or slot in attachments or url != 'https://www.kgrowth.or.kr/down_file.asp?' + urlencode(
                    {'idx': target['board_record_id'], 'SelType': slot})):
            raise ValueError('보도자료 첨부의 호스트·경로·ID·News 구획 불일치')
        extension = '.hwp' if slot == 'News1' else '.pdf'
        if name != stem + extension or anchor.attrs.get('title') != f'첨부파일 [{name}] 다운로드':
            raise ValueError('보도자료 첨부 파일명·형식과 공고 제목 불일치')
        attachments[slot] = {'url': url, 'name': name, 'slot': slot,
                             'board_record_id': target['board_record_id'], 'source_detail_sha256': digest,
                             'downloaded': False}
    if set(attachments) != {'News1', 'News2'}:
        raise ValueError('보도자료의 단일 News2 PDF 원문 링크 미확인')
    return {'title': title, 'date': day, 'body': body,
            'body_text_sha256': hashlib.sha256(body.encode('utf-8')).hexdigest(),
            'stated_business_year': business[1], 'stated_round': '정시',
            'attachments': [attachments['News1'], attachments['News2']]}, attachments['News2']


def replay_press_result_detail(first_capture, followup_capture, detail_capture, expected_terms, *,
                               checked_at=None, retain=lambda report: None):
    """Recheck saved bytes only; never revise the original held capture receipt."""
    stamp = _checked_at(checked_at)
    result = {'kind': 'lp_kgrowth_press_result_replay_v1', 'checked_at': stamp, 'requests': 0,
              'source_institution_id': 'kgrowth', 'board_type': 3, 'replay_complete': False,
              'detail_template_verified': False, 'notice_identity_verified': False, 'pdf_link_verified': False,
              'roster_verified': False, 'parsed': False, 'source_health_verified': False,
              'publication_ready': False, 'published': False, 'database_reads': 0, 'database_writes': 0,
              'holds': []}
    try:
        if not isinstance(detail_capture, dict):
            raise ValueError('보도자료 상세 보존 묶음 형식 불일치')
        receipts = detail_capture.get('receipts')
        if not isinstance(receipts, list) or len(receipts) != 1 or not isinstance(receipts[0], dict):
            raise ValueError('보도자료 상세 원영수증이 하나가 아님')
        receipt = receipts[0]
        if not isinstance(receipt.get('checked_at'), str):
            raise ValueError('보도자료 상세 관측시각 누락')
        observed = _checked_at(receipt['checked_at'])
        if datetime.fromisoformat(observed.replace('Z', '+00:00')) > datetime.fromisoformat(stamp.replace('Z', '+00:00')):
            raise ValueError('보도자료 상세 관측시각이 재생시각보다 늦음')
        encoded = receipt.get('raw_base64')
        if not isinstance(encoded, str) or len(encoded) > (MAX_DETAIL_BYTES + 2) // 3 * 4:
            raise ValueError('보도자료 상세 원바이트 누락·상한 초과')
        raw = base64.b64decode(encoded, validate=True)
        replayed = capture_press_result_detail(first_capture, followup_capture, expected_terms, lambda url: {
            'raw': raw, 'http_status': receipt.get('http_status'), 'geturl': receipt.get('response_url')}, checked_at=observed)
        if (not _same_proof(replayed['receipts'][0], receipt)
                or any(not _same_proof(detail_capture.get(k), v) for k, v in replayed.items() if k != 'receipts')):
            raise ValueError('보도자료 목록→상세 원영수증 재생 불일치')
        target = replayed['listing_target']
        allowed_hold = [{'url': target['url'], 'reason': '목록 HTML 완결성 미확인'}]
        if (type(receipt.get('http_status')) is not int or receipt['http_status'] != 200
                or receipt.get('full_response_retained') is not True
                or replayed['holds'] not in ([], allowed_hold)):
            raise ValueError('보도자료 상세 응답 상태·전체 원문 보존 미확인')
        result.update(listing_target=target,
                      source_detail={k: receipt[k] for k in ('url', 'sha256', 'bytes', 'checked_at')},
                      original_capture_status=receipt['capture_status'], original_capture_holds=copy.deepcopy(receipt['holds']))
        detail, pdf = _press_result_detail_dom(raw, target, replayed['search_term'], receipt['sha256'])
        result.update(replay_complete=True, detail_template_verified=True, notice_identity_verified=True,
                      pdf_link_verified=True, detail=detail, pdf_attachment=pdf)
    except (ValueError, KeyError, TypeError, StopIteration) as error:
        result['holds'].append({'reason': str(error) if isinstance(error, ValueError) else '보도자료 상세 증거 형식 불일치'})
    retain(copy.deepcopy(result))
    return result


def _validate_pdf_response(response, report, *, expected_url):
    raw = _validate_wire_response(response, report, expected_url=expected_url)
    if not re.match(br'%PDF-[12]\.\d[\r\n]', raw) or not raw.rstrip().endswith(b'%%EOF'):
        raise ValueError('보도자료 첨부의 PDF 시작·종료 표식 불일치')


def _validate_session_detail(response, receipt, replay, search_term, *, expected_url):
    raw = _validate_wire_response(response, receipt, expected_url=expected_url)
    source, pdf = _press_result_detail_dom(raw, replay['listing_target'], search_term, receipt['sha256'])
    if (any(source[key] != replay['detail'][key] for key in ('title', 'date', 'body_text_sha256'))
            or pdf['url'] != replay['pdf_attachment']['url']):
        raise ValueError('공개 세션의 상세 제목·게시일·본문·PDF 주소가 저장 원문과 다름')


def capture_press_result_pdf(first, followup, detail, terms, *, prior_failure=None,
                             checked_at=None, retain=lambda report: None):
    """Replay the official chain and retain its one observed PDF before reading it."""
    stamp = _checked_at(checked_at)
    replay = replay_press_result_detail(first, followup, detail, terms, checked_at=stamp)
    scope = 'press_pdf_session' if prior_failure is not None else 'press_pdf'
    result = {'kind': 'lp_kgrowth_press_result_pdf_v1', 'review_scope': scope,
              'detail_replay': replay, 'requests': 0, 'receipts': [], 'holds': replay['holds'],
              'pdf_container_observed': False, 'parsed': False, 'roster_verified': False,
              'publication_ready': False, 'published': False, 'database_reads': 0, 'database_writes': 0}
    if not replay['pdf_link_verified']:
        retain(copy.deepcopy(result))
        return result

    def save(receipt):
        retain({**copy.deepcopy(result), 'requests': result['requests'] + receipt['requests'],
                'receipts': [*copy.deepcopy(result['receipts']), receipt],
                'holds': copy.deepcopy(receipt['holds'])})

    pdf_url = replay['pdf_attachment']['url']
    fetch = _fetch
    if prior_failure is not None:
        result['prior_direct_failure_sha256'] = _check_pdf_direct_failure(prior_failure, replay)
        opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()), _NoRedirect())
        source_url = replay['source_detail']['url']

        def validate_detail(response, receipt, *, expected_url):
            _validate_session_detail(response, receipt, replay, followup['search_term'], expected_url=expected_url)

        body = _capture(source_url, lambda url: _fetch(url, opener=opener, referer=followup['receipts'][0]['url']),
                        checked_at=stamp, retain=save, validate=validate_detail)
        result.update(requests=body['requests'], receipts=[body], holds=body['holds'])
        if body['holds']:
            retain(copy.deepcopy(result))
            return result

        def fetch(url):
            return _fetch(url, opener=opener, referer=source_url)

    receipt = _capture(pdf_url, fetch, checked_at=stamp, retain=save, validate=_validate_pdf_response)
    result.update(requests=result['requests'] + receipt['requests'], receipts=[*result['receipts'], receipt], holds=receipt['holds'],
                  pdf_container_observed=not receipt['holds'])
    retain(copy.deepcopy(result))
    return result


def replay_press_result_pdf(first, followup, detail, pdf_capture, terms, *, prior_failure=None, checked_at=None):
    """Recover PDF bytes from the original receipts without making a request."""
    limit = datetime.fromisoformat(_checked_at(checked_at).replace('Z', '+00:00'))
    session = prior_failure is not None
    scope = 'press_pdf_session' if session else 'press_pdf'
    if not isinstance(pdf_capture, dict):
        raise ValueError('보도자료 PDF 보존 묶음 형식 불일치')
    receipts = pdf_capture.get('receipts')
    if (pdf_capture.get('kind') != 'lp_kgrowth_press_result_pdf_v1' or pdf_capture.get('review_scope') != scope
            or not isinstance(receipts, list) or len(receipts) != (2 if session else 1)
            or any(not isinstance(receipt, dict) for receipt in receipts)
            or type(pdf_capture.get('requests')) is not int or pdf_capture['requests'] != len(receipts)
            or pdf_capture.get('holds') != [] or pdf_capture.get('pdf_container_observed') is not True):
        raise ValueError('보도자료 PDF 보존 묶음 형식 불일치')
    stamp = receipts[0].get('checked_at')
    if (not isinstance(stamp, str) or any(receipt.get('checked_at') != stamp for receipt in receipts)
            or datetime.fromisoformat(_checked_at(stamp).replace('Z', '+00:00')) > limit):
        raise ValueError('보도자료 PDF 관측시각 불일치')
    replay = replay_press_result_detail(first, followup, detail, terms, checked_at=stamp)
    if not replay['pdf_link_verified'] or not _same_proof(pdf_capture.get('detail_replay'), replay):
        raise ValueError('보도자료 목록·상세·PDF 링크 재생 불일치')

    def verify(receipt, url, validator):
        encoded = receipt.get('raw_base64')
        if not isinstance(encoded, str) or len(encoded) > (MAX_DETAIL_BYTES + 2) // 3 * 4:
            raise ValueError('보도자료 원바이트 누락·상한 초과')
        raw = base64.b64decode(encoded, validate=True)
        response = {'raw': raw, 'http_status': receipt.get('http_status'), 'geturl': receipt.get('response_url')}
        expected = _capture(url, lambda _: response, checked_at=stamp, retain=lambda _: None, validate=validator)
        if expected['holds'] or not _same_proof(receipt, expected):
            raise ValueError('보도자료 원응답·지문·파일 완결 재생 불일치')
        return raw

    if session:
        if pdf_capture.get('prior_direct_failure_sha256') != _check_pdf_direct_failure(prior_failure, replay):
            raise ValueError('보도자료 PDF 직접 접근 실패 지문 불일치')

        def validate_detail(response, receipt, *, expected_url):
            _validate_session_detail(response, receipt, replay, followup['search_term'], expected_url=expected_url)

        verify(receipts[0], replay['source_detail']['url'], validate_detail)
    raw = verify(receipts[-1], replay['pdf_attachment']['url'], _validate_pdf_response)
    return raw, {'source_detail': replay['source_detail'], 'detail': replay['detail'],
                 'source_pdf': {k: receipts[-1][k] for k in ('url', 'sha256', 'bytes', 'checked_at')}}


def _check_pdf_direct_failure(failure, replay):
    """Require the retained direct-link entry alert for this very attachment."""
    if (not isinstance(failure, dict) or failure.get('review_scope') != 'press_pdf'
            or type(failure.get('requests')) is not int or failure['requests'] != 1
            or failure.get('pdf_container_observed') is not False or failure.get('published') is not False
            or not isinstance(failure.get('detail_replay'), dict)
            or any(not _same_proof(failure['detail_replay'].get(key), replay[key])
                   for key in ('source_detail', 'pdf_attachment'))):
        raise ValueError('같은 보도자료 첨부의 이전 직접 접근 실패가 필요함')
    receipts = failure.get('receipts')
    if not isinstance(receipts, list) or len(receipts) != 1 or not isinstance(receipts[0], dict):
        raise ValueError('보도자료 첨부 접근 실패 영수증 형식 불일치')
    url = replay['pdf_attachment']['url']
    receipt = receipts[0]
    raw = "<script>alert('비정상적인 접근입니다.');location.href='/';</script>".encode('cp949')
    response = {'raw': raw, 'http_status': 200, 'geturl': url}
    expected = _capture(url, lambda _: response, checked_at=receipt.get('checked_at'),
                        retain=lambda _: None, validate=_validate_pdf_response)
    if not _same_proof(expected, receipt) or not _same_proof(failure.get('holds'), expected['holds']):
        raise ValueError('보도자료 첨부의 실제 직접 접근 실패 응답 불일치')
    return receipt['sha256']
