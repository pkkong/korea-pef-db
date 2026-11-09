import base64
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request

from services.lp.src import diagnose_kgrowth_history_session as d
from services.lp.src import collect_kgrowth_history_attachments as a
from services.lp.tests.test_lp_kgrowth_history_attachment_queue import fixture
from services.lp.tests.test_collect_kgrowth_history_attachments import attachment

DENIED = "<script>alert('비정상적인 접근입니다.');location.href='/';</script>".encode('cp949')


def inputs():
    history, bodies = fixture()
    failed = a.collect(history, bodies, None, lambda u: DENIED)
    notice = next(n for n in bodies['documents'] if n['source_id'] == failed['failed_response']['source_id'])
    raw = base64.b64decode(notice['discovery_provenance']['detail_response_base64'])
    return history, bodies, failed, raw


class Response:
    def __init__(self, url, raw, headers=None, status=200):
        self.url, self.raw, self.headers, self.status = url, raw, headers or {}, status
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def geturl(self): return self.url
    def read(self, size): return self.raw[:size]


class PublicSessionControlTests(unittest.TestCase):
    def test_one_public_body_then_one_linked_hwpx_preserves_original_failure(self):
        history, bodies, failed, raw = inputs()
        before = copy.deepcopy((history, bodies, failed)); calls = []
        def fetch(url, kind):
            calls.append((url, kind))
            return {'raw': raw if kind == 'body' else attachment(), 'set_cookie_seen': kind == 'body'}
        result = d.control(history, bodies, failed, fetch)
        self.assertTrue(result['success'])
        self.assertEqual([kind for _, kind in calls], ['body', 'file'])
        self.assertEqual(result['requests'], {'body': 1, 'file': 1})
        self.assertEqual(result['extracted']['format'], 'hwpx')
        self.assertEqual(base64.b64decode(result['responses']['body']['raw_base64']), raw)
        self.assertEqual(result['original_failure']['response_sha256'], hashlib.sha256(DENIED).hexdigest())
        self.assertTrue(result['body_continuity']['all_attachment_labels_unchanged'])
        self.assertEqual(result['database_writes'], 0)
        self.assertFalse(result['collector_resumed']); self.assertFalse(result['published'])
        self.assertFalse(result['pe_approval']); self.assertFalse(result['selected_gp_approval'])
        self.assertIn('cause_not_isolated', result['cookie_hypothesis'])
        self.assertEqual((history, bodies, failed), before)

    def test_original_raw_source_and_failure_tamper_fail_without_http(self):
        history, bodies, failed, raw = inputs()
        for change in ('body_hash', 'failure_hash', 'failure_source', 'failure_marker', 'held_source'):
            h, b, f = copy.deepcopy((history, bodies, failed))
            if change == 'body_hash': b['documents'][0]['discovery_provenance']['detail_response_sha256'] = '0' * 64
            elif change == 'failure_hash': f['failed_response']['sha256'] = '0' * 64
            elif change == 'failure_source': f['failed_response']['source_id'] = '999'
            elif change == 'held_source': f['holds'][0]['source_id'] = '999'
            else:
                other = b'<script>not an abnormal-access response</script>'
                f['failed_response']['raw_base64'] = base64.b64encode(other).decode()
                f['failed_response']['sha256'] = hashlib.sha256(other).hexdigest()
            result = d.control(h, b, f, lambda *args: self.fail('unverified control made HTTP'))
            with self.subTest(change=change):
                self.assertFalse(result['success']); self.assertEqual(result['requests'], {'body': 0, 'file': 0})

    def test_changed_title_date_body_links_or_labels_never_request_file(self):
        history, bodies, failed, raw = inputs()
        for change in ('title', 'date', 'body', 'link', 'label', 'login'):
            changed = raw
            if change == 'title': changed = raw.replace('중견기업'.encode('cp949'), '다른기업'.encode('cp949'))
            elif change == 'date': changed = raw.replace(b'2023-01-01', b'2023-01-02')
            elif change == 'body': changed = raw.replace('공식 원문'.encode('cp949'), '변경 원문'.encode('cp949'))
            elif change == 'link': changed = raw.replace(b'SelType=Notice3', b'SelType=Notice2')
            elif change == 'label': changed = raw.replace('공고문.pdf'.encode('cp949'), '공고문 수정.pdf'.encode('cp949'))
            else: changed = raw.replace('공식 원문'.encode('cp949'), '로그인이 필요합니다'.encode('cp949'))
            calls = []
            def fetch(url, kind):
                calls.append(kind)
                if kind != 'body': self.fail('changed public notice fetched a file')
                return changed
            result = d.control(history, bodies, failed, fetch)
            with self.subTest(change=change):
                self.assertFalse(result['success']); self.assertEqual(calls, ['body'])
                self.assertEqual(result['requests']['file'], 0)
                self.assertEqual(base64.b64decode(result['responses']['body']['raw_base64']), changed)

    def test_repeated_abnormal_access_or_protected_file_is_preserved_without_retry(self):
        history, bodies, failed, raw = inputs()
        for payload in (DENIED, b'<html>unsupported response</html>', attachment('로그인이 필요합니다')):
            calls = []
            def fetch(url, kind):
                calls.append(kind)
                return raw if kind == 'body' else payload
            result = d.control(history, bodies, failed, fetch)
            with self.subTest(payload_size=len(payload)):
                self.assertFalse(result['success']); self.assertEqual(calls, ['body', 'file'])
                self.assertEqual(base64.b64decode(result['responses']['file']['raw_base64']), payload)
                self.assertEqual(result['cookie_hypothesis'], 'unverified')
                self.assertNotIn('extracted', result)

    def test_public_transport_has_one_shared_anonymous_cookie_jar_and_no_secret_output(self):
        history, bodies, failed, raw = inputs()
        with patch.object(d, 'build_opener') as factory:
            def respond(request, timeout):
                self.assertEqual(timeout, 25)
                if 'notice_view.asp' in request.full_url:
                    self.assertEqual(request.get_header('Referer'), d.LIST_URL)
                    return Response(request.full_url, raw, {'Set-Cookie': 'ASPSESSION=DO_NOT_STORE'})
                self.assertEqual(request.get_header('Referer'), bodies['documents'][0]['url'])
                return Response(request.full_url, attachment(), {'Set-Cookie': 'ANOTHER_SECRET'})
            factory.return_value.open.side_effect = respond
            result = d.control(history, bodies, failed)
            self.assertTrue(result['success'])
            self.assertEqual(factory.call_count, 1); self.assertEqual(factory.return_value.open.call_count, 2)
            self.assertTrue(any(isinstance(handler, HTTPCookieProcessor) for handler in factory.call_args.args))
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertNotIn('DO_NOT_STORE', serialized); self.assertNotIn('ANOTHER_SECRET', serialized)
            self.assertNotIn('Set-Cookie', serialized); self.assertNotIn('headers', serialized)
            self.assertTrue(result['responses']['body']['set_cookie_seen'])

    def test_http_403_and_timeout_are_single_attempt_failures_with_safe_error_metadata(self):
        history, bodies, failed, raw = inputs()
        for phase in ('body', 'file'):
            for mode in ('403', 'timeout'):
                with self.subTest(phase=phase, mode=mode), patch.object(d, 'build_opener') as factory:
                    def respond(request, timeout):
                        actual = 'body' if 'notice_view.asp' in request.full_url else 'file'
                        if actual != phase: return Response(request.full_url, raw)
                        if mode == '403':
                            raise HTTPError(request.full_url, 403, 'Cookie: NEVER_EXPOSE',
                                            {'Set-Cookie': 'NEVER_EXPOSE'}, io.BytesIO(DENIED))
                        raise TimeoutError('Cookie: NEVER_EXPOSE')
                    factory.return_value.open.side_effect = respond
                    result = d.control(history, bodies, failed)
                    self.assertFalse(result['success'])
                    self.assertEqual(factory.return_value.open.call_count, 1 if phase == 'body' else 2)
                    self.assertNotIn('NEVER_EXPOSE', json.dumps(result))
                    if mode == '403':
                        self.assertEqual(result['responses'][phase]['http_status'], 403)
                        self.assertEqual(base64.b64decode(result['responses'][phase]['raw_base64']), DENIED)

    def test_strict_initial_redirect_final_urls_and_no_extra_navigation(self):
        history, bodies, failed, raw = inputs()
        row = a.validate_report(history, bodies, failed)['rows'][0]
        redirects = d.PublicRedirects(row)
        for kind, original in (('body', row['source_url']), ('file', row['attachment_url'])):
            redirects.kind = kind
            for target in (original, original.replace('https:', 'http:'),
                           original.replace('www.kgrowth.or.kr', 'user@www.kgrowth.or.kr'),
                           original.replace('www.kgrowth.or.kr', 'evil.example'), original + '&extra=1'):
                with self.subTest(kind=kind, target=target), self.assertRaises(ValueError):
                    redirects.redirect_request(Request(original), None, 302, '', {}, target)
        with patch.object(d, 'build_opener') as factory:
            session = d.PublicSession(row)
            with self.assertRaises(ValueError): session(row['attachment_url'], 'file')
            self.assertEqual(factory.return_value.open.call_count, 0)
            factory.return_value.open.return_value = Response('https://evil.example/', raw)
            with self.assertRaises(ValueError): session(row['source_url'], 'body')
            with self.assertRaises(ValueError): session(row['source_url'], 'body')
            self.assertEqual(factory.return_value.open.call_count, 1)

    def test_oversized_response_is_bounded_marked_and_stops_next_phase(self):
        history, bodies, failed, raw = inputs()
        with patch.object(d, 'MAX_BODY_BYTES', 32):
            result = d.control(history, bodies, failed, lambda url, kind: raw)
        self.assertFalse(result['success']); self.assertEqual(result['requests']['file'], 0)
        response = result['responses']['body']
        self.assertTrue(response['truncated']); self.assertEqual(response['bytes'], 32)
        self.assertEqual(base64.b64decode(response['raw_base64']), raw[:32])

    def test_injected_headers_and_exception_messages_are_never_retained(self):
        history, bodies, failed, raw = inputs()
        result = d.control(history, bodies, failed, lambda *args: {'raw': raw, 'headers': {'Cookie': 'SECRET'}})
        self.assertFalse(result['success']); self.assertNotIn('SECRET', json.dumps(result))
        def fail(*args): raise ValueError('Cookie: SECRET')
        result = d.control(history, bodies, failed, fail)
        self.assertFalse(result['success']); self.assertNotIn('SECRET', json.dumps(result))

    def test_cli_keeps_failure_artifact_when_input_cannot_be_read(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = str(Path(folder) / 'missing.json')
            out = Path(folder) / 'result'
            args = ['control', '--listing-state', missing, '--body-state', missing,
                    '--failed-state', missing, '--output-dir', str(out)]
            with patch('sys.argv', args):
                self.assertEqual(d.main(), 1)
            result = json.loads((out / 'session-control.json').read_text())
            self.assertFalse(result['success']); self.assertEqual(result['requests'], {'body': 0, 'file': 0})


if __name__ == '__main__':
    unittest.main()
