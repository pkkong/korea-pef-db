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
        def validate(observed, report):
            self.assertEqual(saved[-1]['capture_status'], 'observed')
            self.assertEqual(saved[-1]['holds'], [])
            self.assertEqual(base64.b64decode(saved[-1]['raw_base64']), b'Access denied')
            return original(observed, report)
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


if __name__ == '__main__':
    unittest.main()
