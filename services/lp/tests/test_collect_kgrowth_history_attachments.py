import base64
import copy
import io
import json
import ssl
import unittest
import zipfile
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from services.lp.src import collect_kgrowth_history_attachments as a
from services.lp.src.lp_kgrowth_history_attachment_queue import plan
from services.lp.tests.test_lp_kgrowth_history_attachment_queue import fixture
from services.lp.tests.test_collect_lp_history_bodies import Connection, Result


def attachment(text='공식 공고 및 진행 결과 원문입니다.'):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('Contents/section0.xml', '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section">'
                         '<hs:p><hs:run><hs:t>' + text + '</hs:t></hs:run></hs:p></hs:sec>')
    return output.getvalue()


class Database(Connection):
    def __init__(self):
        super().__init__()
        self.sql = []
        self.lookup_rows = None
        self.readback_failure = False

    def execute(self, sql, args=None):
        self.sql.append((sql, args))
        if sql.startswith('SELECT document FROM lp_program_private.documents'):
            rows = self.lookup_rows if self.lookup_rows is not None else [
                n for (url, _), n in self.documents.items() if url in args[0]]
            return Result([(n,) for n in rows])
        if self.readback_failure and sql.startswith('SELECT source_url,content_hash'):
            return Result([])
        return super().execute(sql, args)

    def __enter__(self):
        self.saved_documents = copy.deepcopy(self.documents)
        return self

    def __exit__(self, kind, value, trace):
        if kind is not None:
            self.documents = self.saved_documents


class Response:
    def __init__(self, url, raw): self.url, self.raw = url, raw
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def geturl(self): return self.url
    def read(self, size): return self.raw[:size]


class GrowthHistoricalFileTests(unittest.TestCase):
    def test_partial_body_queue_raw_replay_four_file_cap_and_noop_resume(self):
        h, bodies = fixture(limit=4)
        original = copy.deepcopy((h, bodies))
        calls = []
        report = a.collect(h, bodies, None, lambda u: calls.append(u) or attachment())
        self.assertEqual(len(calls), 4)
        self.assertEqual(report['batches'][0]['planned_ids'], ['9', '12', '90', '95'])
        self.assertEqual(report['batches'][0]['detail_requests'], 0)
        self.assertEqual(a.validate_report(h, bodies, report)['pending_files'], 0)
        self.assertTrue(all(r['extracted']['format'] == 'hwpx' for r in report['records']))
        resumed = a.collect(h, bodies, report, lambda u: self.fail('repeat file HTTP'))
        self.assertEqual(resumed['batches'][-1]['attachment_requests'], 0)
        self.assertEqual(a.summary(h, bodies, resumed)['validated_files'], 4)
        totals = a.summary(h, bodies, resumed)
        self.assertEqual(totals['logical_attachment_requests'], 4)
        self.assertEqual(totals['validated_downloads'], 4)
        self.assertEqual(totals['transport_attempts'], 'not_measured')
        self.assertNotIn('official_http_requests', totals)
        self.assertNotIn('database_writes', totals)
        self.assertEqual((h, bodies), original)
        h, bodies = fixture()
        partial = a.collect(h, bodies, None, lambda u: attachment())
        self.assertEqual(a.validate_report(h, bodies, partial)['body_pending'], 1)
        self.assertFalse(a.summary(h, bodies, partial)['pe_approval'])
        self.assertFalse(a.summary(h, bodies, partial)['selected_gp_approval'])

    def test_cache_uses_only_exact_typed_raw_files_and_retention_is_idempotent(self):
        h, bodies = fixture()
        report = a.collect(h, bodies, None, lambda u: attachment())
        conn = Database()
        first = a.persist(conn, h, bodies, report, wrap_json=lambda n: n)
        second = a.persist(conn, h, bodies, report, wrap_json=lambda n: n)
        self.assertEqual((first['new_document_versions'], second['new_document_versions']), (3, 0))
        self.assertEqual(first['before'], first['after'])
        docs = list(conn.documents.values())
        raw_only = copy.deepcopy(docs[0]); raw_only['discovery_provenance'].pop('attachment_evidence')
        raw_only['discovery_provenance']['kind'] = 'legacy'
        cached = a.lookup(conn, h, bodies)
        reused = a.collect(h, bodies, None, lambda u: self.fail('retained file must be reused'),
                           cached_documents=[raw_only] + cached)
        self.assertEqual(reused['batches'][-1]['attachment_requests'], 0)
        self.assertEqual(len(reused['batches'][-1]['reused_database_ids']), 3)
        persisted = a.persist(conn, h, bodies, reused, wrap_json=lambda n: n)
        self.assertEqual((persisted['submitted_documents'], persisted['new_document_versions']), (0, 0))
        self.assertEqual(persisted['reused_database_documents'], 3)
        self.assertEqual(a.persist(conn, h, bodies, a.collect(h, bodies, reused, None),
                                   wrap_json=lambda n: n)['new_document_versions'], 0)
        calls = []
        fetched = a.collect(h, bodies, None, lambda u: calls.append(u) or attachment(), cached_documents=[raw_only])
        self.assertEqual(len(calls), 3)  # Legacy hash/text is not raw evidence.
        self.assertEqual(fetched['batches'][-1]['reused_database_ids'], [])

    def test_readonly_lookup_bounds_and_hidden_proof_never_reused(self):
        h, bodies = fixture(); conn = Database()
        self.assertEqual(a.lookup(conn, h, bodies), [])
        self.assertIn('READ ONLY', conn.sql[0][0])
        sql, args = conn.sql[-1]
        self.assertIn('LIMIT 101', sql)
        self.assertEqual(args[0], [r['source_url'] for r in plan(h, bodies)['rows']])
        conn.lookup_rows = [{}] * 101
        with self.assertRaisesRegex(ValueError, 'lookup limit'): a.lookup(conn, h, bodies)
        conn.lookup_rows = [{'body': 'large'}]
        with patch.object(a, 'MAX_REPORT_BYTES', 2), self.assertRaises(ValueError):
            a.lookup(conn, h, bodies)
        report = a.collect(h, bodies, None, lambda u: attachment())
        doc = a.document(bodies, report['records'][0])
        for flags in ({'hidden': True}, {'status': 'restricted'}, {'protected': '1'},
                      {'status': ' PRIVATE '}, {'reason': ' OWNER_CLOSED '},
                      {'status': 'error'}, {'attachment_errors': {'file': 'unreadable'}},
                      {'discovery_provenance': {**doc['discovery_provenance'], 'owner_closed': True}}):
            blocked = {**doc, **flags}
            conn.lookup_rows = [blocked]
            with self.assertRaisesRegex(ValueError, 'before HTTP'):
                a.lookup(conn, h, bodies)
            held = a.collect(h, bodies, None, lambda u: self.fail('protected source fetched'),
                             cached_documents=[blocked])
            self.assertTrue(held['holds']); self.assertEqual(held['batches'][0]['attachment_requests'], 0)

    def test_tampered_raw_text_source_body_and_order_fail_before_database(self):
        h, bodies = fixture(); report = a.collect(h, bodies, None, lambda u: attachment())
        for change in ('text', 'hash', 'bytes', 'source', 'order', 'extra', 'batch', 'reused', 'timestamp'):
            bad = copy.deepcopy(report); record = bad['records'][0]
            if change == 'text': record['extracted']['text'] = 'fabricated'
            elif change == 'hash': record['attachment_sha256'] = 'f' * 64
            elif change == 'bytes': record['raw_base64'] = base64.b64encode(attachment('changed')).decode()
            elif change == 'source': record['source_url'] = 'https://evil.example/'
            elif change == 'order': bad['records'].reverse()
            elif change == 'extra': record['selected_gps'] = ['invented']
            elif change == 'batch': bad['batches'][0]['planned_ids'] = []
            elif change == 'reused': bad['batches'][0]['reused_database_ids'] = ['9']
            else: record['checked_at'] = '2026-01-01'
            conn = Database()
            with self.subTest(change=change), self.assertRaises(ValueError):
                a.persist(conn, h, bodies, bad, wrap_json=lambda n: n)
            self.assertEqual(conn.sql, [])
        changed = copy.deepcopy(bodies)
        changed['documents'][0]['body'] += 'forged'
        with self.assertRaises(ValueError): a.validate_report(h, changed, report)
        with self.assertRaises(ValueError): a.collect(h, bodies, None, None, cached_documents=[{}] * 101)

    def test_cache_tamper_and_conflicting_versions_hold_before_fetch(self):
        h, bodies = fixture(); report = a.collect(h, bodies, None, lambda u: attachment())
        doc = a.document(bodies, report['records'][0])
        for change in ('text', 'raw', 'body', 'extra', 'conflict'):
            bad = copy.deepcopy(doc)
            if change == 'text': bad['attachment_texts'][report['records'][0]['attachment_url']] = 'changed'
            elif change == 'raw': bad['discovery_provenance']['attachment_evidence']['raw_base64'] = 'bad'
            elif change == 'body': bad['sha256'] = '0' * 64
            elif change == 'extra': bad['selected_gps'] = ['invented']
            else:
                bad['discovery_provenance']['kind'] = 'legacy'
                bad['attachment_hashes'][report['records'][0]['attachment_url']] = '0' * 64
            cached = [doc, bad] if change == 'conflict' else [bad]
            held = a.collect(h, bodies, None, lambda u: self.fail('bad cache fetched'), cached_documents=cached)
            with self.subTest(change=change):
                self.assertTrue(held['holds']); self.assertEqual(held['batches'][0]['attachment_requests'], 0)
                with self.assertRaises(ValueError): a.persist(Database(), h, bodies, held, wrap_json=lambda n: n)

    def test_first_failure_retains_prior_and_failed_bytes_blocks_automatic_resume(self):
        h, bodies = fixture(); calls = []
        def fetch(url):
            calls.append(url)
            return attachment() if len(calls) == 1 else b'<html>Access denied</html>'
        report = a.collect(h, bodies, None, fetch)
        self.assertEqual(len(calls), 2); self.assertEqual(len(report['records']), 1)
        self.assertEqual(base64.b64decode(report['failed_response']['raw_base64']), b'<html>Access denied</html>')
        self.assertEqual(a.validate_report(h, bodies, report)['completed_files'], 1)
        with self.assertRaises(ValueError): a.collect(h, bodies, report, lambda u: self.fail('failed run resumed'))
        with self.assertRaises(ValueError): a.lookup(Database(), h, bodies, report)
        with self.assertRaises(ValueError): a.persist(Database(), h, bodies, report, wrap_json=lambda n: n)
        report['failed_response']['sha256'] = '0' * 64
        with self.assertRaises(ValueError): a.validate_report(h, bodies, report)

    def test_failure_proof_budget_is_reserved_before_http_and_reports_are_bounded(self):
        h, bodies = fixture()
        with patch.object(a, 'MAX_REPORT_BYTES', 4096):
            held = a.collect(h, bodies, None, lambda u: self.fail('no space for raw failure proof'))
        self.assertTrue(held['holds'])
        self.assertEqual(held['batches'][0]['attachment_requests'], 0)
        self.assertEqual(a.validate_report(h, bodies, held)['completed_files'], 0)
        report = a.collect(h, bodies, None, lambda u: attachment())
        with patch.object(a, 'MAX_REPORT_BYTES', 2), self.assertRaises(ValueError):
            a.validate_report(h, bodies, report)

    def test_append_only_transaction_rolls_back_on_guard_and_readback_errors(self):
        h, bodies = fixture(); report = a.collect(h, bodies, None, lambda u: attachment())
        for failure in ('guard', 'readback'):
            conn = Database()
            conn.documents[('existing', 'unchanged')] = {'unchanged': True}
            conn.change_public = failure == 'guard'; conn.readback_failure = failure == 'readback'
            before = copy.deepcopy(conn.documents)
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                with conn: a.persist(conn, h, bodies, report, wrap_json=lambda n: n)
            self.assertEqual(conn.documents, before)
        conn = Database()
        reused = a.collect(h, bodies, None, None,
                           cached_documents=[a.document(bodies, r) for r in report['records']])
        with self.assertRaisesRegex(ValueError, 'readback'):
            with conn: a.persist(conn, h, bodies, reused, wrap_json=lambda n: n)

    def test_transport_redirects_initial_intermediate_final_stay_on_same_source(self):
        url = 'https://www.kgrowth.or.kr/down_file.asp?idx=9&SelType=Notice3'
        redirects = a.OfficialRedirects('9')
        for target in (url.replace('https:', 'http:'), url.replace('www.kgrowth.or.kr', 'evil.example'),
                       url.replace('idx=9', 'idx=12'), url + '&extra=x'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                redirects.redirect_request(Request(url), None, 302, '', {}, target)
        with self.assertRaises(ValueError):
            redirects.redirect_request(Request('https://evil.example/'), None, 302, '', {}, url)
        with patch.object(a, 'build_opener') as factory:
            factory.return_value.open.return_value = Response(url, attachment())
            self.assertTrue(a.fetch_attachment(url))
            request = factory.return_value.open.call_args.args[0]
            self.assertIn('notice_view.asp?idx=9&', request.get_header('Referer'))
            self.assertEqual(factory.return_value.open.call_args.kwargs['timeout'], 25)
            factory.return_value.open.return_value = Response(url.replace('idx=9', 'idx=12'), attachment())
            with self.assertRaises(ValueError): a.fetch_attachment(url)

    def test_transport_retry_only_transient_errors_with_existing_limits(self):
        url = 'https://www.kgrowth.or.kr/down_file.asp?idx=9&SelType=Notice3'
        for error in (HTTPError(url, 401, 'auth', {}, None), HTTPError(url, 403, 'protected', {}, None),
                      HTTPError(url, 404, 'absent', {}, None), URLError(ssl.SSLCertVerificationError('bad certificate')),
                      URLError('untyped error')):
            with self.subTest(error=type(error).__name__), patch.object(a, 'build_opener') as factory, patch.object(a.time, 'sleep') as sleep:
                factory.return_value.open.side_effect = error
                with self.assertRaises(type(error)): a.fetch_attachment(url)
                self.assertEqual(factory.return_value.open.call_count, 1); sleep.assert_not_called()
        for error in (HTTPError(url, 503, 'temporary', {}, None), HTTPError(url, 429, 'limited', {}, None),
                      URLError(TimeoutError('timeout')), ConnectionResetError('reset')):
            with self.subTest(error=type(error).__name__), patch.object(a, 'build_opener') as factory, patch.object(a.time, 'sleep') as sleep:
                factory.return_value.open.side_effect = error
                with self.assertRaises(type(error)): a.fetch_attachment(url)
                self.assertEqual(factory.return_value.open.call_count, 3)
                self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])
        with patch.object(a, 'build_opener') as factory, patch.object(a, 'MAX_FILE_BYTES', 2):
            factory.return_value.open.return_value = Response(url, b'123')
            with self.assertRaises(ValueError): a.fetch_attachment(url)
            self.assertEqual(factory.return_value.open.call_count, 1)


if __name__ == '__main__':
    unittest.main()
