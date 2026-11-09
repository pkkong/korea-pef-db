import base64
import copy
import json
import sys
import unittest
from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services.lp.src import collect_kgrowth_history_sessions as a
from services.lp.src import collect_kgrowth_history_attachments as files
from services.lp.src.publish_lp_programs import document_hash
from services.lp.tests.test_lp_kgrowth_history_attachment_queue import fixture
from services.lp.tests.test_collect_kgrowth_history_attachments import attachment, Database as BaseDatabase
from services.lp.tests.test_collect_lp_history_bodies import Result

STAMP = '2026-11-10T00:00:00+09:00'


def raw_bodies(bodies):
    return {n['url']: base64.b64decode(n['discovery_provenance']['detail_response_base64'], validate=True)
            for n in bodies['documents']}


def saved_fetch(bodies, calls):
    raw = raw_bodies(bodies)
    def fetch(url, kind):
        calls.append((url, kind))
        return {'raw': raw[url] if kind == 'body' else attachment(), 'set_cookie_seen': kind == 'body'}
    return fetch


def first_cached(history, bodies):
    report = files.collect(history, bodies, None, lambda url: attachment(), checked_at='2026-11-09T00:00:00+09:00')
    return files.document(bodies, report['records'][0])


class Database(BaseDatabase):
    def __init__(self, bodies, cached=()):
        super().__init__()
        for n in [*bodies['documents'], *cached]:
            self.documents[(n['url'], document_hash(n))] = copy.deepcopy(n)
        self.original = copy.deepcopy(bodies['documents'])
        self.lookups = 0
        self.after_guard = None
        self.guard_rows = 0

    def execute(self, sql, args=None):
        if sql.startswith('SELECT document FROM lp_program_private.documents'):
            self.lookups += 1
            if self.after_guard and self.lookups > self.guard_rows:
                if self.after_guard == 'old_body_only':
                    return Result([(n,) for n in self.original if n['url'] in args[0]])
                docs = [copy.deepcopy(n) for (url, _), n in self.documents.items() if url in args[0]]
                for n in docs:
                    if n.get('discovery_provenance', {}).get('kind') == files.KIND:
                        if self.after_guard == 'missing_record': n['discovery_provenance'].pop('attachment_evidence')
                        else: n['attachment_texts'] = {'changed': 'mangled raw document'}
                return Result([(n,) for n in docs])
        return super().execute(sql, args)


class HistoricalSessionTests(unittest.TestCase):
    def setUp(self):
        self.bare = patch.object(files, 'fetch_attachment', side_effect=AssertionError('Bare v1 file HTTP forbidden')).start()
        self.addCleanup(patch.stopall)

    def test_first_adopted_v1_file_reused_and_at_most_three_new_sessions(self):
        h, b = fixture(limit=4); cache = first_cached(h, b); calls = []
        original = copy.deepcopy((h, b, cache))
        with patch.object(a, 'PublicSession', side_effect=AssertionError('Injected offline fetch only')):
            report = a.collect(h, b, fetch=saved_fetch(b, calls), cached_documents=[cache], checked_at=STAMP)
            q = a.validate_report(h, b, report)
        batch = report['batches'][0]
        self.assertEqual(batch['planned_ids'], ['9', '12', '90', '95'])
        self.assertEqual(batch['reused_database_ids'], ['9'])
        self.assertEqual(batch['new_ids'], ['12', '90', '95'])
        self.assertEqual([phase for _, phase in calls], ['body', 'file'] * 3)
        self.assertEqual(batch['detail_requests'], 3); self.assertEqual(batch['attachment_requests'], 3)
        self.assertEqual(batch['transport_attempts'], {'body': 0, 'file': 0})
        self.assertEqual(report['records'][0], cache['discovery_provenance']['attachment_evidence'])
        self.assertEqual(q['pending_files'], 0)
        summary = a.summary(h, b, report)
        self.assertEqual(summary['validated_files'], 4)
        self.assertEqual(summary['validated_downloads'], 3)
        self.assertFalse(summary['published']); self.assertFalse(summary['selected_gp_approval'])
        self.assertFalse(summary['session_report_stored_in_database'])
        self.assertEqual((h, b, cache), original)
        self.bare.assert_not_called()

    def test_all_cached_and_complete_resume_are_zero_http(self):
        h, b = fixture(); legacy = files.collect(h, b, None, lambda url: attachment())
        cached = [files.document(b, r) for r in legacy['records']]
        with patch.object(a, 'PublicSession', side_effect=AssertionError('No transport for cached/no-op resume')):
            report = a.collect(h, b, cached_documents=cached, checked_at=STAMP)
            resumed = a.collect(h, b, report, checked_at=STAMP)
            a.validate_report(h, b, resumed)
        self.assertEqual(report['sessions'], [])
        self.assertEqual(report['batches'][0]['detail_requests'], 0)
        self.assertEqual(resumed['batches'][-1]['planned_ids'], [])
        self.assertEqual(a.summary(h, b, resumed)['body_pending'], 1)

    def test_successful_v1_preserved_verbatim_failed_v1_is_terminal(self):
        h, b = fixture(); legacy = files.collect(h, b, None, lambda url: attachment())
        before = copy.deepcopy(legacy)
        with patch.object(a, 'PublicSession', side_effect=AssertionError('No new queue')):
            report = a.collect(h, b, legacy, checked_at=STAMP)
        self.assertEqual(report['legacy_state'], before)
        self.assertEqual(legacy, before)
        self.assertEqual(report['records'], [])
        self.assertEqual(a.summary(h, b, report)['validated_files'], 3)
        failed = files.collect(h, b, None, lambda url: b'<script>denied</script>')
        with self.assertRaisesRegex(ValueError, 'terminal'):
            a.collect(h, b, failed, lambda *args: self.fail('Failed legacy retried'))

    def test_changed_body_fields_or_labels_never_request_file_and_hold_blocks_resume(self):
        h, b = fixture(); original = raw_bodies(b); first = next(iter(original))
        raw = original[first]
        cases = [raw.replace('중견기업'.encode('cp949'), '다른기업'.encode('cp949')),
                 raw.replace(b'2023-01-01', b'2023-01-02'),
                 raw.replace('공식 원문'.encode('cp949'), '변경 원문'.encode('cp949')),
                 raw.replace(b'SelType=Notice3', b'SelType=Notice2'),
                 raw.replace('공고문.pdf'.encode('cp949'), '변경공고문.pdf'.encode('cp949')),
                 '<script>alert("비정상적인 접근입니다.")</script>'.encode('cp949')]
        for changed in cases:
            calls = []
            def fetch(url, kind): calls.append(kind); return changed
            held = a.collect(h, b, fetch=fetch, checked_at=STAMP)
            with self.subTest(raw_hash=files.sha(changed)):
                self.assertEqual(calls, ['body'])
                self.assertEqual(held['batches'][0]['attachment_requests'], 0)
                self.assertEqual(held['records'], [])
                self.assertEqual(base64.b64decode(held['sessions'][0]['responses']['body']['raw_base64']), changed)
                a.validate_report(h, b, held)
                with self.assertRaisesRegex(ValueError, 'requires independent diagnosis'):
                    a.collect(h, b, held, lambda *args: self.fail('Failure auto-resumed'))

    def test_abnormal_file_http_error_and_failure_bytes_stop_without_retry(self):
        h, b = fixture(); raw = raw_bodies(b); blocker = '<script>alert("비정상적인 접근입니다.")</script>'.encode('cp949')
        for status in (200, 403, 503):
            calls = []
            class Fetch:
                def __init__(self): self.attempts = {'body': 0, 'file': 0}
                def __call__(self, url, kind):
                    self.attempts[kind] += 1; calls.append(kind)
                    if kind == 'body': return raw[url]
                    if status != 200: raise a.control.PublicHTTPError(blocker, status, True)
                    return blocker
            held = a.collect(h, b, fetch=Fetch(), checked_at=STAMP)
            self.assertEqual(calls, ['body', 'file'])
            proof = held['sessions'][0]
            self.assertEqual(proof['transport_attempts'], {'body': 1, 'file': 1})
            self.assertEqual(proof['responses']['file']['http_status'], status)
            self.assertEqual(base64.b64decode(proof['responses']['file']['raw_base64']), blocker)
            a.validate_report(h, b, held)
            self.assertEqual(held['records'], [])

    def test_report_raw_text_source_counters_and_approvals_tamper_rejected(self):
        h, b = fixture(); report = a.collect(h, b, fetch=saved_fetch(b, []), checked_at=STAMP)
        for change in ('body_hash', 'body_raw', 'label', 'file_hash', 'text', 'source', 'counter', 'bool', 'extra', 'new_reuse', 'legacy'):
            bad = copy.deepcopy(report); proof = bad['sessions'][0]
            if change == 'body_hash': proof['responses']['body']['sha256'] = '0' * 64
            elif change == 'body_raw': proof['responses']['body']['raw_base64'] = 'bad'
            elif change == 'label': proof['source']['attachment_name'] = 'other.pdf'
            elif change == 'file_hash': proof['responses']['file']['sha256'] = '0' * 64
            elif change == 'text': proof['extracted']['text'] = 'invented'
            elif change == 'source': bad['records'][0]['source_id'] = '999'
            elif change == 'counter': bad['batches'][0]['attachment_requests'] = 0
            elif change == 'bool': proof['requests']['body'] = True
            elif change == 'extra': bad['pe_approval'] = True
            elif change == 'new_reuse': bad['batches'][0]['reused_database_ids'] = ['9']
            else: bad['legacy_state']['holds'] = [{'error': 'failed'}]
            with self.subTest(change=change), self.assertRaises((ValueError, IndexError)):
                a.validate_report(h, b, bad)
        changed = copy.deepcopy(b); changed['documents'][0]['body'] += 'forged'
        with self.assertRaises(ValueError): a.validate_report(h, changed, report)

    def test_cache_protection_conflicting_versions_and_lookup_limits_fail_before_http(self):
        h, b = fixture(); good = first_cached(h, b)
        for flags in ({'status': ' PRIVATE '}, {'error': 'failure'}, {'title': 'changed'}, {'sha256': '0' * 64}):
            bad = {**copy.deepcopy(good), **flags}
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                a.collect(h, b, fetch=lambda *args: self.fail('Unsafe cache fetched'), cached_documents=[bad])
        conn = Database(b, [good]); cached = a.lookup(conn, h, b)
        self.assertIn(good, cached)
        self.assertIn('READ ONLY', conn.sql[0][0]); self.assertIn('LIMIT 101', conn.sql[-1][0])
        conn.lookup_rows = [good] * 101
        with self.assertRaises(ValueError): a.lookup(conn, h, b)

    def test_locked_preflight_and_post_actual_json_readback_keep_public_state(self):
        h, b = fixture(limit=4); cache = first_cached(h, b)
        report = a.collect(h, b, fetch=saved_fetch(b, []), cached_documents=[cache], checked_at=STAMP)
        conn = Database(b, [cache]); before_count = len(conn.documents)
        with conn: result = a.persist(conn, h, b, report, wrap_json=lambda n: n)
        self.assertEqual(result['new_document_versions'], 3)
        self.assertEqual(result['reused_database_documents'], 1)
        self.assertEqual(result['documents_after'], before_count + 3)
        self.assertEqual(result['before'], result['after'])
        self.assertTrue(result['typed_raw_readback_verified'])
        self.assertFalse(result['session_report_stored_in_database'])
        lock = next(i for i, (sql, _) in enumerate(conn.sql) if sql.startswith('SELECT pg_advisory_xact_lock'))
        source = next(i for i, (sql, _) in enumerate(conn.sql) if sql.startswith('SELECT document'))
        self.assertLess(lock, source)
        with conn: again = a.persist(conn, h, b, report, wrap_json=lambda n: n)
        self.assertEqual(again['new_document_versions'], 0)
        self.assertEqual(again['existing_typed_before'], 4)
        for mode in ('old_body_only', 'mangled', 'missing_record'):
            broken = Database(b, [cache]); broken.guard_rows = 4; broken.after_guard = mode
            before = copy.deepcopy(broken.documents)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                with broken: a.persist(broken, h, b, report, wrap_json=lambda n: n)
            self.assertEqual(broken.documents, before)
        for corrupt in ('protected', 'public', 'missing_reused'):
            broken = Database(b, [cache]); before = copy.deepcopy(broken.documents)
            if corrupt == 'protected': broken.documents[(b['documents'][1]['url'], 'blocked')] = {**b['documents'][1], 'hidden': True}
            elif corrupt == 'public': broken.change_public = True
            else: broken.documents = {(u, d): n for (u, d), n in broken.documents.items() if n != cache}
            before = copy.deepcopy(broken.documents)
            with self.subTest(corrupt=corrupt), self.assertRaises(ValueError):
                with broken: a.persist(broken, h, b, report, wrap_json=lambda n: n)
            self.assertEqual(broken.documents, before)

    def test_production_ordinary_session_counts_open_calls_and_never_exports_cookies(self):
        h, b = fixture(); raw = raw_bodies(b)
        class Response(BytesIO):
            def __init__(self, url, value):
                super().__init__(value); self.url = url; self.headers = Message(); self.headers['Set-Cookie'] = 'sid=SECRET; Path=/'
            def geturl(self): return self.url
        class Opener:
            def open(self, request, timeout):
                self.timeout = timeout
                return Response(request.full_url, raw[request.full_url] if request.full_url in raw else attachment())
        with patch.object(a.control, 'build_opener', side_effect=lambda *handlers: Opener()) as build:
            report = a.collect(h, b, checked_at=STAMP)
        self.assertEqual(build.call_count, 3)  # a fresh anonymous jar for each source
        self.assertEqual(report['batches'][0]['transport_attempts'], {'body': 3, 'file': 3})
        self.assertNotIn('SECRET', json.dumps(report)); self.assertNotIn('Cookie', json.dumps(report))
        row = a.plan(h, b)['rows'][0]
        session = a.PublicSession(row)
        session.redirects.kind = 'body'
        with self.assertRaises(ValueError):
            session.redirects.redirect_request(Request(row['source_url']), None, 302, 'redirect', {}, row['source_url'])
        session.redirects.kind = 'file'
        with self.assertRaises(ValueError):
            session.redirects.redirect_request(Request(row['attachment_url']), None, 302, 'redirect', {}, 'https://evil.example/')

    def test_bounded_failed_bytes_and_safe_transport_error_replay(self):
        h, b = fixture()
        with patch.object(a, 'MAX_BODY_BYTES', 32):
            held = a.collect(h, b, fetch=saved_fetch(b, []), checked_at=STAMP)
            body = held['sessions'][0]['responses']['body']
            self.assertEqual(body['bytes'], 32); self.assertTrue(body['truncated'])
            self.assertEqual(held['sessions'][0]['requests'], {'body': 1, 'file': 0})
            a.validate_report(h, b, held)
        raw = raw_bodies(b)
        with patch.object(a, 'MAX_FILE_BYTES', 32):
            held = a.collect(h, b, fetch=lambda url, kind: raw[url] if kind == 'body' else b'x' * 100, checked_at=STAMP)
            self.assertTrue(held['sessions'][0]['responses']['file']['truncated'])
            a.validate_report(h, b, held)
        def failure(*args): raise TimeoutError('Authorization: SECRET_COOKIE_VALUE')
        held = a.collect(h, b, fetch=failure, checked_at=STAMP)
        self.assertNotIn('SECRET_COOKIE_VALUE', json.dumps(held))
        self.assertEqual(held['sessions'][0]['responses'], {})
        a.validate_report(h, b, held)
        with patch.object(a, 'MAX_REPORT_BYTES', 45 * 1024 * 1024):
            held = a.collect(h, b, fetch=lambda *args: self.fail('Budget checked after HTTP'), checked_at=STAMP)
            self.assertEqual(held['sessions'], [])
            self.assertEqual(held['holds'][0]['error'], 'pre_request_report_budget')
            a.validate_report(h, b, held)

    def test_legacy_same_content_hash_without_typed_proof_rolls_back(self):
        h, b = fixture(); report = a.collect(h, b, fetch=saved_fetch(b, []), checked_at=STAMP)
        conn = Database(b)
        legacy = files.document(b, report['records'][0])
        legacy['discovery_provenance']['kind'] = 'legacy'
        conn.documents[(legacy['url'], document_hash(legacy))] = copy.deepcopy(legacy)
        before = copy.deepcopy(conn.documents)
        with self.assertRaisesRegex(ValueError, 'typed raw proof missing'):
            with conn: a.persist(conn, h, b, report, wrap_json=lambda n: n)
        self.assertEqual(conn.documents, before)


if __name__ == '__main__':
    unittest.main()
