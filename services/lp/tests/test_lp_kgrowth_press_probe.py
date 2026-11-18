"""One-shot diagnostic capture; synthetic transport only, no origin access."""
import base64
import copy
import hashlib
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler

from services.lp.src import lp_kgrowth_press_probe as probe
from services.lp.src.kgrowth_listing import source_id


STAMP = '2026-11-16T12:31:00+00:00'
HTML = '<html lang="ko"><body>보도자료 목록 관측용</body></html>'.encode('cp949')


def response(raw=HTML, status=200, url=probe.PRESS_LISTING_URL, **extra):
    return {'raw': raw, 'http_status': status, 'geturl': url, **extra}


class _HTTPResponse:
    def __init__(self, raw=HTML, status=200, url=probe.PRESS_LISTING_URL):
        self.body, self.code, self.url = io.BytesIO(raw), status, url
        self.read_limits, self.closed = [], False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, limit):
        self.read_limits.append(limit)
        return self.body.read(limit)

    def getcode(self):
        return self.code

    def geturl(self):
        return self.url


class PressListingProbeTests(unittest.TestCase):
    def capture(self, observed=None, **kwargs):
        fetch = Mock(return_value=response() if observed is None else observed)
        saved = []
        report = probe.capture_press_listing(fetch, checked_at=STAMP,
                                             retain=lambda r: saved.append(r), **kwargs)
        fetch.assert_called_once_with(probe.PRESS_LISTING_URL)
        return report, saved

    def test_complete_capture_preserves_exact_bytes_without_parsing_or_approval(self):
        report, saved = self.capture()
        self.assertEqual(report['kind'], 'lp_kgrowth_press_probe_v1')
        self.assertEqual((report['source_institution_id'], report['board_type']), ('kgrowth', 3))
        self.assertEqual(report['url'], probe.PRESS_LISTING_URL)
        self.assertEqual(report['response_url'], probe.PRESS_LISTING_URL)
        self.assertEqual(report['checked_at'], STAMP)
        self.assertEqual(report['requests'], 1)
        self.assertEqual(report['holds'], [])
        self.assertEqual(report['capture_status'], 'response_retained')
        self.assertEqual(base64.b64decode(report['raw_base64']), HTML)
        self.assertEqual(report['sha256'], hashlib.sha256(HTML).hexdigest())
        self.assertEqual((report['bytes'], report['observed_bytes']), (len(HTML), len(HTML)))
        self.assertTrue(report['full_response_retained'])
        for key in ('parsed', 'source_health_verified', 'publication_ready', 'published'):
            self.assertFalse(report[key])
        self.assertEqual((report['database_reads'], report['database_writes']), (0, 0))
        self.assertTrue(all(k not in report for k in ('rows', 'programs', 'selected_gps')))
        report['holds'].append({'reason':'later mutation'})
        self.assertEqual(saved[-1]['holds'], [])

    def test_response_is_retained_before_even_type_or_html_validation(self):
        saved, original = [], probe._validate_response
        def validate(observed, report, *, expected_url):
            self.assertEqual(saved[-1]['capture_status'], 'observed')
            self.assertEqual(saved[-1]['holds'], [])
            self.assertEqual(base64.b64decode(saved[-1]['raw_base64']), b'Access denied')
            return original(observed, report, expected_url=expected_url)
        with patch.object(probe, '_validate_response', side_effect=validate):
            result = probe.capture_press_listing(Mock(return_value=response(b'Access denied',403)),
                                                 checked_at=STAMP, retain=saved.append)
        self.assertTrue(result['holds'])
        self.assertEqual(result['requests'], 1)
        self.assertEqual(result['http_status'], 403)

    def test_first_http_rejection_is_kept_without_any_retry(self):
        for status in (301, 302, 401, 403, 404, 500):
            with self.subTest(status=status):
                report, saved = self.capture(response(b'blocked response',status))
                self.assertEqual(report['requests'], 1)
                self.assertTrue(report['holds'])
                self.assertEqual(base64.b64decode(saved[1]['raw_base64']), b'blocked response')
                self.assertEqual(report['capture_status'], 'held')

    def test_empty_or_incomplete_html_keeps_original_evidence(self):
        for raw in (b'', b'<html><body>incomplete', b'<html></html>', b'not html',
                    b'<html><body>no closing body</html>'):
            with self.subTest(raw=raw):
                report, saved = self.capture(response(raw))
                self.assertTrue(report['holds'])
                self.assertEqual(base64.b64decode(report['raw_base64']), raw)
                self.assertEqual(report['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(base64.b64decode(saved[1]['raw_base64']), raw)

    def test_oversized_body_preserves_bounded_prefix_and_not_full_size_claim(self):
        raw = b'x' * 40
        with patch.object(probe, 'MAX_DETAIL_BYTES', 32):
            report, saved = self.capture(response(raw))
        self.assertEqual(base64.b64decode(report['raw_base64']), raw[:32])
        self.assertEqual(report['sha256'], hashlib.sha256(raw[:32]).hexdigest())
        self.assertEqual((report['bytes'], report['observed_bytes']), (32, 40))
        self.assertTrue(report['truncated'])
        self.assertTrue(report['observed_bytes_is_lower_bound'])
        self.assertFalse(report['full_response_retained'])
        self.assertEqual(saved[1]['holds'], [])
        self.assertTrue(report['holds'])

    def test_utf8_and_cp949_are_retained_without_guessing_source_encoding(self):
        for encoding in ('utf-8', 'cp949'):
            with self.subTest(encoding=encoding):
                raw = '<html><body>보도자료</body></html>'.encode(encoding)
                report, _ = self.capture(response(raw))
                self.assertEqual(report['holds'], [])
                self.assertEqual(base64.b64decode(report['raw_base64']), raw)
                self.assertFalse(report['parsed'])
        for raw in ('<html><body>UTF 문자열</body></html>', bytearray(HTML), None, 7):
            with self.subTest(raw_type=type(raw).__name__):
                report, saved = self.capture(response(raw))
                self.assertTrue(report['holds'])
                self.assertEqual(report['raw_type'], type(raw).__name__)
                self.assertIsNone(report['raw_base64'])
                self.assertIsNone(report['sha256'])
                self.assertIsNone(saved[1]['raw_base64'])

    def test_abnormal_status_and_response_shape_are_json_safe_held_observations(self):
        for status in (True, '200', None, 200.0, float('nan'), object()):
            with self.subTest(status_type=type(status).__name__):
                report, _ = self.capture(response(status=status))
                self.assertTrue(report['holds'])
                json.dumps(report, allow_nan=False)
                self.assertEqual(base64.b64decode(report['raw_base64']), HTML)
        for observed in ([], b'returned without transport metadata', 'wrong response shape'):
            with self.subTest(response_type=type(observed).__name__):
                report, _ = self.capture(observed)
                self.assertTrue(report['holds'])
                self.assertEqual(report['response_type'], type(observed).__name__)

    def test_changed_response_url_or_missing_geturl_is_not_accepted(self):
        for url in (probe.PRESS_LISTING_URL.replace('str_type=3','str_type=1'),
                    'https://other.example/notice.asp', None, 3):
            with self.subTest(url=url):
                report, saved = self.capture(response(url=url))
                self.assertTrue(report['holds'])
                self.assertEqual(report['url'], probe.PRESS_LISTING_URL)
                self.assertEqual(base64.b64decode(saved[1]['raw_base64']), HTML)
        observed = response()
        observed.pop('geturl')
        self.assertTrue(self.capture(observed)[0]['holds'])

    def test_headers_cookies_and_opaque_response_extras_are_never_copied(self):
        observed = response(headers={'Set-Cookie':'server-secret-cookie'}, cookies='secret-cookie',
                            opaque=object(), authorization='secret-auth')
        before_keys = list(observed)
        report, saved = self.capture(observed)
        encoded = json.dumps([report,*saved])
        self.assertNotIn('server-secret-cookie', encoded)
        self.assertNotIn('secret-auth', encoded)
        self.assertNotIn('secret-cookie', encoded)
        self.assertEqual(list(observed), before_keys)

    def test_complete_http_200_is_only_capture_success_even_for_an_error_page(self):
        report, _ = self.capture(response(b'<html><body>Access denied</body></html>'))
        self.assertEqual(report['holds'], [])
        self.assertEqual(report['capture_status'], 'response_retained')
        self.assertFalse(report['parsed'])
        self.assertFalse(report['source_health_verified'])
        self.assertFalse(report['publication_ready'])

    def test_invalid_or_future_observation_time_rejects_before_fetch(self):
        for stamp in ('2099-01-01T00:00:00Z', '2026-11-16T12:31:00', '', 7, object()):
            with self.subTest(stamp_type=type(stamp).__name__):
                fetch, retain = Mock(), Mock()
                with self.assertRaises(ValueError):
                    probe.capture_press_listing(fetch, checked_at=stamp, retain=retain)
                fetch.assert_not_called()
                retain.assert_not_called()

    def test_default_timestamp_and_utc_z_are_timezone_aware(self):
        for stamp in (None, STAMP.replace('+00:00','Z')):
            with self.subTest(stamp=stamp):
                result = probe.capture_press_listing(Mock(return_value=response()), checked_at=stamp)
                self.assertEqual(result['holds'], [])
                self.assertTrue(result['checked_at'].endswith(('+00:00','Z')))

    def test_network_exception_is_retained_without_credentials_or_retry(self):
        fetch = Mock(side_effect=TimeoutError('opaque header secret-cookie'))
        saved = []
        report = probe.capture_press_listing(fetch, checked_at=STAMP, retain=saved.append)
        fetch.assert_called_once_with(probe.PRESS_LISTING_URL)
        self.assertEqual(report['requests'], 1)
        self.assertEqual(report['capture_status'], 'held')
        self.assertIn('TimeoutError', report['holds'][0]['reason'])
        self.assertNotIn('secret-cookie', json.dumps(saved))
        self.assertFalse(report['response_retained'])

    def test_retention_failure_never_returns_success_or_triggers_retry(self):
        fetch = Mock(return_value=response())
        with self.assertRaises(OSError):
            probe.capture_press_listing(fetch, checked_at=STAMP, retain=Mock(side_effect=OSError('disk full')))
        fetch.assert_not_called()
        saved = []
        def retain(report):
            saved.append(copy.deepcopy(report))
            if report['raw_base64'] is not None:
                raise OSError('raw storage failed')
        with patch.object(probe, '_validate_response') as validate, self.assertRaises(OSError):
            probe.capture_press_listing(fetch, checked_at=STAMP, retain=retain)
        validate.assert_not_called()
        fetch.assert_called_once()
        self.assertEqual(base64.b64decode(saved[-1]['raw_base64']), HTML)

    def test_fetch_only_allows_the_exact_constant_source_url(self):
        urls = [probe.PRESS_LISTING_URL.replace('str_type=3','str_type=1'),
                probe.PRESS_LISTING_URL+'&idx=258', 'http://www.kgrowth.or.kr/notice.asp?str_type=3&tab=1',
                'https://other.example/notice.asp?str_type=3&tab=1',
                'https://www.kgrowth.or.kr/notice.asp?tab=1&str_type=3']
        for url in urls:
            with self.subTest(url=url), patch.object(probe, 'build_opener') as opener, self.assertRaises(ValueError):
                probe.fetch_press_listing(url)
            opener.assert_not_called()
        fetch = Mock()
        with self.assertRaises(TypeError):
            probe.capture_press_listing(fetch, checked_at=STAMP, url=probe.PRESS_LISTING_URL)
        fetch.assert_not_called()

    def test_fetch_is_a_single_bounded_get_with_timeout_and_no_proxy_auth(self):
        observed = _HTTPResponse()
        opener = Mock()
        opener.open.return_value = observed
        with patch.object(probe, 'build_opener', return_value=opener) as build:
            result = probe.fetch_press_listing(probe.PRESS_LISTING_URL)
        opener.open.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, probe.PRESS_LISTING_URL)
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        self.assertEqual(opener.open.call_args.kwargs, {'timeout':25})
        self.assertEqual(observed.read_limits, [probe.MAX_DETAIL_BYTES+1])
        self.assertTrue(observed.closed)
        self.assertEqual(set(result), {'raw','http_status','geturl'})
        self.assertEqual(result, response())
        handlers = build.call_args.args
        self.assertEqual(len(handlers), 2)
        self.assertIsInstance(handlers[0], ProxyHandler)
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsInstance(handlers[1], probe._NoRedirect)
        self.assertFalse(any(k.lower() in ('cookie','authorization','proxy-authorization') for k in request.headers))

    def test_fetch_preserves_http_error_body_without_following_redirects(self):
        for status in (302,403):
            with self.subTest(status=status):
                error = HTTPError(probe.PRESS_LISTING_URL,status,'denied',{'Set-Cookie':'secret'},io.BytesIO(b'denied body'))
                opener = Mock()
                opener.open.side_effect = error
                with patch.object(probe, 'build_opener', return_value=opener):
                    report = probe.capture_press_listing(probe.fetch_press_listing, checked_at=STAMP)
                opener.open.assert_called_once()
                self.assertEqual(report['http_status'], status)
                self.assertEqual(base64.b64decode(report['raw_base64']), b'denied body')
                self.assertTrue(report['holds'])
                self.assertNotIn('secret', json.dumps(report))
        self.assertIsNone(probe._NoRedirect().redirect_request(None,None,302,'',{},'https://other.example'))

    def test_original_type_one_validator_is_not_relaxed(self):
        with self.assertRaises(ValueError):
            source_id('https://www.kgrowth.or.kr/notice_view.asp?idx=258&str_type=3&tab=1')

    @staticmethod
    def search_page(term):
        fields = {**probe._PRESS_FORM, 'search_text': term}
        inputs = ''.join(f'<input name="{k}" value="{v}">' for k, v in fields.items())
        return ('<html><head><title>보도자료 > 공지사항 > 한국성장금융투자운용</title></head>'
                f'<body><form name="search" id="search" method="get">{inputs}</form></body></html>').encode('cp949')

    def test_search_uses_observed_title_form_and_keeps_original_responses(self):
        term = '정책형 뉴딜펀드'
        url = probe.press_search_url(term)
        self.assertEqual(url, probe.PRESS_LISTING_URL.split('?')[0] +
                         '?search_colume=Title&str_type=3&pagesize=10&orderby=1&notice_type=1'
                         '&tab=1&search_text=%C1%A4%C3%A5%C7%FC+%B4%BA%B5%F4%C6%DD%B5%E5')
        raw = self.search_page(term)
        fetch = Mock(return_value=response(raw, url=url))
        saved = []
        report, = probe.capture_press_search([term], fetch, checked_at=STAMP, retain=saved.append)
        fetch.assert_called_once_with(url)
        self.assertTrue(report['search_echo_verified'])
        self.assertTrue(any(r[0]['capture_status'] == 'observed' for r in saved))
        self.assertEqual(base64.b64decode(report['raw_base64']), raw)
        self.assertEqual(report['holds'], [])
        self.assertFalse(report['parsed'])

    def test_search_echo_mismatch_keeps_raw_and_holds(self):
        term = '정책형 뉴딜펀드'
        other = '소재·부품·장비 분야 투자 전용 펀드'
        terms = [term, other]
        calls = []
        def fetch(url):
            calls.append(url)
            return response(self.search_page(''), url=url)
        receipts = probe.capture_press_search(terms, fetch, checked_at=STAMP)
        self.assertEqual(calls, [probe.press_search_url(t) for t in terms])
        self.assertTrue(all(not r['search_echo_verified'] and r['holds'] and r['response_retained']
                            for r in receipts))

    def test_search_transport_rejects_extra_parameters_and_other_hosts(self):
        url = probe.press_search_url('정책형 뉴딜펀드')
        with patch.object(probe, '_fetch') as fetch:
            for changed in (url + '&page=2', url + '&idx=258', url.replace('str_type=3', 'str_type=1'),
                            url.replace('www.kgrowth.or.kr', 'other.example')):
                with self.subTest(url=changed), self.assertRaises(ValueError):
                    probe.fetch_press_search(changed)
            fetch.assert_not_called()

    def test_observed_complete_style_script_postamble_retains_original_bytes(self):
        # The actual retained board-3 page has these two complete blocks after
        # </html>. Their contents are not executed or treated as notice rows.
        tail = (b'\r\n<style type="text/css">\r\n.txt_line { overflow: hidden; }\r\n</style>\r\n'
                b'<script type="text/javascript">\r\n<!--\r\nvar tab = \'1\';\r\n//-->\r\n</script>')
        raw = HTML + tail
        report, _ = self.capture(response(raw))
        self.assertEqual(report['holds'], [])
        self.assertEqual(base64.b64decode(report['raw_base64']), raw)
        for field in ('parsed', 'source_health_verified', 'publication_ready', 'published'):
            self.assertFalse(report[field])

    def test_postamble_requires_complete_observed_pair_and_no_other_markup(self):
        style = b'<style type="text/css">.txt_line { overflow: hidden; }</style>'
        script = b'<script type="text/javascript">var tab = \'1\';</script>'
        for tail in (style, script, script + style, style + script[:-1],
                     style + script + b'<div>other document</div>',
                     style.replace(b'text/css', b'text/plain') + script,
                     style + b'<script type="text/javascript">'):
            with self.subTest(tail=tail):
                report, _ = self.capture(response(HTML + tail))
                self.assertTrue(report['holds'])
                self.assertTrue(report['response_retained'])
                self.assertEqual(base64.b64decode(report['raw_base64']), HTML + tail)


class PressFollowupProbeTests(unittest.TestCase):
    term = '정책형 뉴딜펀드'
    empty_term = '소재·부품·장비 분야 투자 전용 펀드'

    @staticmethod
    def page(term, page=1, total=17):
        # Small observed form/pagination excerpts from the retained first search.
        # Page 2 and repeated row scaffolding are synthetic, never roster facts.
        fields = f'''<form name="List" method="get">
<input type="hidden" name="page">
<input type="hidden" name="search_colume" value="Title">
<input type="hidden" name="search_text" value="{term}">
<input type="hidden" name="SearchValue" value=""><input type="hidden" name="SearchMode" value="">
<input type="hidden" name="SearchGubun" value=""><input type="hidden" name="str_year" value="">
<input type="hidden" name="str_type" value="3"><input type="hidden" name="str_num" value="">
<input type="hidden" name="pagesize" value="10"><input type="hidden" name="orderby" value="1">
<input type="hidden" name="notice_type" value="1"><input type="hidden" name="tab" value="1"></form>
<div class="total_wrap">전체 <span>{total}</span>개의 글이 있습니다.</div>
<form name="search" id="search" method="get">
<input name="search_colume" value="Title"><input name="str_type" value="3">
<input name="pagesize" value="10"><input name="orderby" value="1">
<input name="notice_type" value="1"><input name="tab" value="1">
<input name="search_text" value="{term}"></form>'''
        count = min(10, max(0, total - (page - 1) * 10))
        rows = ''.join('<tr><td>8</td><td><a href="#">(보도자료) 「정책형 뉴딜펀드」 결성 및 투자 순항</a>'
                       '</td><td>2021-04-26</td><td></td></tr>' for _ in range(count))
        if not total:
            rows = '<tr><td colspan="4">등록된 글이 없습니다.</td></tr>'
        table = '<table class="notice_tbl"><tr><th>번호</th><th>제목</th><th>작성일</th><th>첨부</th></tr>' + rows + '</table>'
        pager = ('<p class="page">' + ''.join(
            f'<a href="Javascript:ListView({n},3,0)" title="{n} 페이지로 이동'
            + (' [현재 페이지]' if n == page else '') + f'">{n}</a>' for n in (1, 2)) + '</p>') if total else ''
        return ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=euc-kr">'
                '<title>보도자료 > 공지사항 > 한국성장금융투자운용</title></head><body>'
                + fields + table + pager + '</body></html>').encode('cp949')

    def prior(self):
        terms = [self.term, self.empty_term]
        responses = {probe.press_search_url(t): self.page(t, total=17 if t == self.term else 0) for t in terms}
        receipts = probe.capture_press_search(terms, lambda url: response(responses[url], url=url), checked_at=STAMP)
        return {'kind': 'lp_kgrowth_press_search_v1', 'review_scope': 'press_search', 'requests': 2,
                'receipts': receipts, 'holds': [], 'parsed': False, 'source_health_verified': False,
                'publication_ready': False, 'published': False}

    @staticmethod
    def reseal(receipt, raw):
        receipt.update(raw_base64=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest(),
                       bytes=len(raw), observed_bytes=len(raw))

    def test_one_followup_keeps_every_source_form_field_and_retains_before_page_validation(self):
        from urllib.parse import parse_qsl, urlsplit
        prior, saved, calls = self.prior(), [], []
        raw = self.page(self.term, page=2)
        def fetch(url):
            calls.append(url)
            return response(raw, url=url)
        original = probe._page_contract
        def validate(observed, term, page):
            if page == 2:
                self.assertFalse(saved[-1]['current_page_verified'])
                self.assertEqual(base64.b64decode(saved[-1]['receipts'][0]['raw_base64']), raw)
            return original(observed, term, page)
        with patch.object(probe, '_page_contract', side_effect=validate):
            report = probe.capture_press_followup(prior, [self.empty_term, self.term], fetch,
                                                  checked_at=STAMP, retain=saved.append)
        self.assertEqual(len(calls), 1)
        self.assertEqual(dict(parse_qsl(urlsplit(calls[0]).query, keep_blank_values=True, encoding='euc-kr')),
                         {'page': '2', 'search_colume': 'Title', 'search_text': self.term, 'SearchValue': '',
                          'SearchMode': '', 'SearchGubun': '', 'str_year': '', 'str_type': '3', 'str_num': '',
                          'pagesize': '10', 'orderby': '1', 'notice_type': '1', 'tab': '1'})
        self.assertEqual(report['kind'], 'lp_kgrowth_press_followup_v1')
        self.assertEqual((report['requests'], report['requested_page']), (1, 2))
        self.assertEqual(report['holds'], [])
        self.assertTrue(report['current_page_verified'])
        self.assertTrue(report['search_echo_verified'])
        self.assertEqual(report['prior_receipt_sha256'], prior['receipts'][0]['sha256'])
        self.assertEqual(report['receipts'][0]['page_contract']['observed_row_count'], 7)
        for key in ('parsed', 'source_health_verified', 'publication_ready', 'published'):
            self.assertIs(report[key], False)
        self.assertTrue(any(r['receipts'][0]['capture_status'] == 'observed' for r in saved))
        self.assertEqual((report['database_reads'], report['database_writes']), (0, 0))
        self.assertTrue(all(key not in report for key in ('rows', 'programs', 'selected_gps')))

    def test_forged_or_incomplete_prior_receipt_never_sends_a_request(self):
        alterations = [('sha256', '0'*64), ('bytes', 1), ('http_status', 403), ('checked_at', None),
                       ('checked_at', '2026-11-17T00:00:00+00:00'), ('source_institution_id', 'kdb'),
                       ('board_type', 1), ('search_echo_verified', False), ('full_response_retained', False),
                       ('truncated', True), ('raw_base64', 'not base64'), ('holds', [{'reason': 'held'}])]
        for key, value in alterations:
            prior, fetch = self.prior(), Mock()
            prior['receipts'][0][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                probe.capture_press_followup(prior, [self.term, self.empty_term], fetch, checked_at=STAMP)
            fetch.assert_not_called()
        for old, new in [(b'ListView(2,3,0)', b'ListView(2,1,0)'),
                         ('[현재 페이지]'.encode('cp949'), b''),
                         (b'name="str_num" value=""', b'name="str_num" value="0"'),
                         (b'name="page"', b'name="idx"')]:
            prior, fetch = self.prior(), Mock()
            raw = base64.b64decode(prior['receipts'][0]['raw_base64']).replace(old, new)
            self.reseal(prior['receipts'][0], raw)  # Even forged success flags and a matching SHA cannot bypass HTML proof.
            with self.subTest(raw_change=old), self.assertRaises(ValueError):
                probe.capture_press_followup(prior, [self.term, self.empty_term], fetch, checked_at=STAMP)
            fetch.assert_not_called()

    def test_batch_terms_provenance_and_unique_next_page_are_required(self):
        for mutate in [lambda c: c.update(kind='lp_kgrowth_press_followup_v1'),
                       lambda c: c.update(requests=1), lambda c: c.update(receipts=c['receipts'][:1]),
                       lambda c: c['receipts'][1].update(search_term=self.term)]:
            prior, fetch = self.prior(), Mock(); mutate(prior)
            with self.assertRaises(ValueError):
                probe.capture_press_followup(prior, [self.term, self.empty_term], fetch, checked_at=STAMP)
            fetch.assert_not_called()
        prior, fetch = self.prior(), Mock()
        with self.assertRaises(ValueError):
            probe.capture_press_followup(prior, ['다른 펀드', self.empty_term], fetch, checked_at=STAMP)
        fetch.assert_not_called()
        self.reseal(prior['receipts'][1], self.page(self.empty_term))
        with self.assertRaises(ValueError):
            probe.capture_press_followup(prior, [self.term, self.empty_term], fetch, checked_at=STAMP)
        fetch.assert_not_called()

    def test_wrong_second_page_echo_current_marker_and_transport_are_retained_as_holds(self):
        correct = self.page(self.term, page=2)
        cases = [(self.page(self.term), 200), (self.page(self.empty_term, page=2), 200),
                 (correct.replace('2 페이지로 이동 [현재 페이지]'.encode('cp949'), b'other marker'), 200),
                 (self.page(self.term, page=2, total=18), 200), (correct[:-7], 200), (b'denied', 403)]
        for raw, status in cases:
            calls, saved = [], []
            def fetch(url):
                calls.append(url)
                return response(raw, status=status, url=url)
            report = probe.capture_press_followup(self.prior(), [self.term, self.empty_term], fetch,
                                                  checked_at=STAMP, retain=saved.append)
            self.assertEqual(len(calls), 1)
            self.assertTrue(report['holds'])
            self.assertFalse(report['current_page_verified'])
            self.assertEqual(base64.b64decode(report['receipts'][0]['raw_base64']), raw)
            self.assertTrue(any(r['receipts'][0]['capture_status'] == 'observed' for r in saved))

    def test_followup_transport_rejects_user_ids_other_pages_and_changed_form(self):
        url = probe._followup_url(self.term)
        for changed in (url + '&idx=1', url + '&page=2', url.replace('page=2', 'page=3'),
                        url.replace('str_type=3', 'str_type=1'), url.replace('tab=1', 'tab=3'),
                        url.replace('www.kgrowth.or.kr', 'other.example')):
            with self.subTest(url=changed), patch.object(probe, '_fetch') as fetch, self.assertRaises(ValueError):
                probe.fetch_press_followup(changed)
            fetch.assert_not_called()
        with patch.object(probe, '_fetch', return_value=response()) as fetch:
            probe.fetch_press_followup(url)
            fetch.assert_called_once_with(url)


if __name__ == '__main__':
    unittest.main()
