import copy
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

from services.lp.src import adopt_kgrowth_session_file as a
from services.lp.src import collect_kgrowth_history_attachments as files
from services.lp.src.publish_lp_programs import document_hash
from services.lp.tests.test_diagnose_kgrowth_history_session import inputs
from services.lp.tests.test_collect_kgrowth_history_attachments import Database as BaseDatabase, attachment
from services.lp.tests.test_collect_lp_history_bodies import Cursor, Result


def evidence():
    h, b, failed, raw = inputs()
    report = a.session.control(h, b, failed, lambda url, kind: {
        'raw': raw if kind == 'body' else attachment(), 'set_cookie_seen': kind == 'body'})
    if not report['success']:
        raise AssertionError(report['errors'])
    return h, b, failed, report


class LoggedCursor(Cursor):
    def execute(self, sql, args):
        self.conn.sql.append((sql, args))
        return super().execute(sql, args)


class Database(BaseDatabase):
    def __init__(self, body):
        super().__init__()
        self.documents[(body['url'], document_hash(body))] = copy.deepcopy(body)
        self.original_body = copy.deepcopy(body)
        self.lookups = 0
        self.post_corruption = None

    def cursor(self): return LoggedCursor(self)

    def execute(self, sql, args=None):
        if sql.startswith('SELECT document FROM lp_program_private.documents'):
            self.lookups += 1
            if self.lookups == 2 and self.post_corruption:
                self.sql.append((sql, args))
                if self.post_corruption == 'old_body_only':
                    return Result([(self.original_body,)])
                docs = copy.deepcopy(list(self.documents.values()))
                typed = next(n for n in docs if n.get('discovery_provenance', {}).get('kind') == files.KIND)
                if self.post_corruption == 'missing_record': typed['discovery_provenance'].pop('attachment_evidence')
                else: typed['attachment_texts'] = {'changed': 'mangled stored JSON'}
                return Result([(n,) for n in docs])
        return super().execute(sql, args)


class AdoptSessionFileTests(unittest.TestCase):
    def setUp(self):
        # Neither valid nor invalid adoption inputs may instantiate a transport.
        self.no_http = patch.object(a.session, 'PublicSession', side_effect=AssertionError('actual HTTP forbidden')).start()
        self.addCleanup(patch.stopall)

    def test_complete_control_replay_one_file_partial_plan_and_original_failure_preserved(self):
        h, b, failed, control = evidence(); before = copy.deepcopy((h, b, failed, control))
        report = a.produce(h, b, failed, control)
        self.assertEqual(a.verify(h, b, failed, control, report), report)
        self.assertEqual(report['kind'], a.KIND)
        self.assertEqual(report['file_record']['extracted']['format'], 'hwpx')
        self.assertEqual(report['diagnostic_file_plan']['pending_files_after_adoption'], 2)
        self.assertEqual(report['diagnostic_file_plan']['body_pending'], 1)
        self.assertEqual(report['official_http_requests'], 0)
        self.assertEqual(report['transport_attempts_this_operation'], 0)
        self.assertEqual(report['prior_session_logical_requests'], {'body': 1, 'file': 1})
        self.assertEqual(report['downloaded_new_files'], 0)
        self.assertTrue(report['original_failed_batch_preserved'])
        self.assertFalse(report['original_failed_batch_completed']); self.assertFalse(report['published'])
        self.assertFalse(report['pe_approval']); self.assertFalse(report['selected_gp_approval'])
        doc = files.document(b, report['file_record'])
        self.assertEqual(doc['discovery_provenance']['kind'], files.KIND)
        self.assertEqual((h, b, failed, control), before)
        self.no_http.assert_not_called()

    def test_locked_source_guard_append_readback_and_idempotent_actual_typed_reuse(self):
        h, b, failed, control = evidence(); report = a.produce(h, b, failed, control)
        body = next(n for n in b['documents'] if n['source_id'] == report['source']['source_id'])
        conn = Database(body)
        with conn:
            first = a.persist(conn, h, b, failed, control, report, wrap_json=lambda n: n)
        self.assertEqual((first['documents_before'], first['documents_after'], first['new_document_versions']), (1, 2, 1))
        self.assertFalse(first['reused_existing_private_document'])
        self.assertTrue(first['new_typed_proof_retained']); self.assertTrue(first['typed_file_readback_verified'])
        self.assertTrue(first['one_file_adopted']); self.assertTrue(first['reuse_possible'])
        self.assertEqual(first['before'], first['after'])
        lock = next(i for i, (sql, _) in enumerate(conn.sql) if sql.startswith('SELECT pg_advisory_xact_lock'))
        lookup = next(i for i, (sql, _) in enumerate(conn.sql) if sql.startswith('SELECT document'))
        write = next(i for i, (sql, _) in enumerate(conn.sql) if sql.startswith('INSERT INTO'))
        self.assertLess(lock, lookup); self.assertLess(lookup, write)
        self.assertEqual(conn.lookups, 2)
        conn.lookups = 0
        with conn:
            second = a.persist(conn, h, b, failed, control, report, wrap_json=lambda n: n)
        self.assertEqual(second['new_document_versions'], 0)
        self.assertTrue(second['reused_existing_private_document']); self.assertTrue(second['reuse_possible'])
        self.assertFalse(second['new_typed_proof_retained'])
        self.no_http.assert_not_called()

    def test_control_raw_extracted_source_counter_flags_and_failure_reference_tamper(self):
        h, b, failed, control = evidence()
        for change in ('raw', 'extracted', 'source', 'counter', 'bool_counter', 'approval', 'extra', 'failure', 'status', 'cookie'):
            changed = copy.deepcopy(control)
            if change == 'raw': changed['responses']['file']['sha256'] = '0' * 64
            elif change == 'extracted': changed['extracted']['text'] = 'invented'
            elif change == 'source': changed['source']['attachment_name'] = 'different file'
            elif change == 'counter': changed['requests']['file'] = 2
            elif change == 'bool_counter': changed['requests']['file'] = True
            elif change == 'approval': changed['published'] = 0
            elif change == 'extra': changed['selected_gps'] = ['invented']
            elif change == 'failure': changed['original_failure']['state_sha256'] = '0' * 64
            elif change == 'status': changed['responses']['file']['http_status'] = 403
            else: changed['responses']['body']['set_cookie_seen'] = 'SECRET'
            with self.subTest(change=change), self.assertRaises(ValueError):
                a.produce(h, b, failed, changed)
        bad = copy.deepcopy(failed); bad['holds'] = []
        with self.assertRaises(ValueError): a.produce(h, b, bad, control)
        failed_control = a.session.control(h, b, failed, lambda url, kind: b'<html>unavailable</html>')
        with self.assertRaises(ValueError): a.produce(h, b, failed, failed_control)
        self.no_http.assert_not_called()

    def test_report_provenance_record_claim_and_unknown_schema_tamper_fail_before_db(self):
        h, b, failed, control = evidence(); report = a.produce(h, b, failed, control)
        for change in ('provenance', 'record', 'counter', 'extra', 'batch'):
            bad = copy.deepcopy(report)
            if change == 'provenance': bad['provenance']['body_state_sha256'] = '0' * 64
            elif change == 'record': bad['file_record']['extracted']['text'] = 'changed'
            elif change == 'counter': bad['official_http_requests'] = False
            elif change == 'extra': bad['selected_gps'] = ['invented']
            else: bad['original_failed_batch_completed'] = True
            conn = Database(b['documents'][0])
            with self.subTest(change=change), self.assertRaises(ValueError):
                a.persist(conn, h, b, failed, control, bad, wrap_json=lambda n: n)
            self.assertEqual(conn.sql, [])
        self.no_http.assert_not_called()

    def test_missing_protected_failed_or_conflicting_retained_body_prevents_write(self):
        h, b, failed, control = evidence(); report = a.produce(h, b, failed, control); body = b['documents'][0]
        budget = max(len(a._json(value)) for value in (h, b, failed, control, report)) + 512
        for change in ('missing', 'hidden', 'failed', 'body', 'title_same_sha', 'attachments_same_sha', 'foreign_url', 'not_dict', 'too_many', 'too_large', 'file_hash'):
            conn = Database(body)
            bad = copy.deepcopy(body)
            if change == 'missing': conn.lookup_rows = []
            elif change == 'hidden': bad['status'] = ' PRIVATE '
            elif change == 'failed': bad['attachment_errors'] = {'file': 'blocked'}
            elif change == 'body': bad['body'] += 'modified'
            elif change == 'title_same_sha': bad['title'] += 'modified'
            elif change == 'attachments_same_sha': bad['attachments'] = []
            elif change == 'foreign_url': bad['url'] = 'https://evil.example/'
            elif change == 'not_dict': conn.lookup_rows = ['not a document']
            elif change == 'too_many': conn.lookup_rows = [bad] * 101
            elif change == 'too_large': bad['extra'] = 'x' * (budget + 1)
            else: bad['attachment_hashes'] = {report['source']['attachment_url']: '0' * 64}
            if conn.lookup_rows is None: conn.lookup_rows = [bad]
            before = copy.deepcopy(conn.documents)
            size = patch.object(a, 'MAX_INPUT_BYTES', budget) if change == 'too_large' else patch.object(a, 'MAX_INPUT_BYTES', a.MAX_INPUT_BYTES)
            with self.subTest(change=change), size, self.assertRaises((ValueError, AttributeError)):
                with conn: a.persist(conn, h, b, failed, control, report, wrap_json=lambda n: n)
            self.assertEqual(conn.documents, before)
            self.assertFalse(any(sql.startswith('INSERT INTO') for sql, _ in conn.sql))
            if change == 'too_large':
                self.assertTrue(any(sql.startswith('SELECT document FROM') for sql, _ in conn.sql))
        self.no_http.assert_not_called()

    def test_postwrite_old_body_missing_typed_record_or_mangled_json_rolls_back(self):
        h, b, failed, control = evidence(); report = a.produce(h, b, failed, control)
        for corruption in ('old_body_only', 'missing_record', 'mangled_json'):
            conn = Database(b['documents'][0]); conn.post_corruption = corruption
            before = copy.deepcopy(conn.documents)
            with self.subTest(corruption=corruption), self.assertRaises((ValueError, TypeError)):
                with conn: a.persist(conn, h, b, failed, control, report, wrap_json=lambda n: n)
            self.assertEqual(conn.documents, before)
            self.assertTrue(any(sql.startswith('INSERT INTO') for sql, _ in conn.sql))
        self.no_http.assert_not_called()

    def test_common_readback_or_public_change_rolls_back(self):
        h, b, failed, control = evidence(); report = a.produce(h, b, failed, control)
        for mode in ('readback', 'public'):
            conn = Database(b['documents'][0]); before = copy.deepcopy(conn.documents)
            conn.readback_failure = mode == 'readback'; conn.change_public = mode == 'public'
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                with conn: a.persist(conn, h, b, failed, control, report, wrap_json=lambda n: n)
            self.assertEqual(conn.documents, before)

    def test_same_content_hash_legacy_without_typed_bytes_cannot_fake_adoption_success(self):
        h, b, failed, control = evidence(); report = a.produce(h, b, failed, control)
        conn = Database(b['documents'][0])
        typed = files.document(b, report['file_record'])
        legacy = copy.deepcopy(typed)
        legacy['discovery_provenance']['kind'] = 'legacy'
        legacy['discovery_provenance'].pop('attachment_evidence')
        self.assertEqual(document_hash(legacy), document_hash(typed))
        key = (legacy['url'], document_hash(legacy))
        conn.documents[key] = legacy
        before = copy.deepcopy(conn.documents)
        with self.assertRaisesRegex(ValueError, 'typed raw file proof missing'):
            with conn: a.persist(conn, h, b, failed, control, report, wrap_json=lambda n: n)
        self.assertEqual(conn.lookups, 2)
        self.assertEqual(conn.documents, before)
        self.assertEqual(len(conn.documents), 2)
        self.assertEqual(conn.documents[key]['discovery_provenance']['kind'], 'legacy')
        self.assertNotIn('attachment_evidence', conn.documents[key]['discovery_provenance'])
        self.no_http.assert_not_called()

    def test_input_bounds_and_pdf_decoder_version_are_explicit(self):
        h, b, failed, control = evidence()
        for value in (h, b, failed, control):
            limit = len(a._json(value)) - 1
            with patch.object(a, 'MAX_INPUT_BYTES', limit), self.assertRaises(ValueError): a._json(value)
        changed = copy.deepcopy(control)
        import base64, hashlib
        raw = b'%PDF synthetic version guard'
        changed['responses']['file'].update(raw_base64=base64.b64encode(raw).decode(), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        with patch.dict(sys.modules, {'pypdf': types.SimpleNamespace(__version__='6.21.4')}), self.assertRaisesRegex(ValueError, 'pypdf 6.10.0'):
            a.produce(h, b, failed, changed)
        self.no_http.assert_not_called()

    def test_plan_and_verify_cli_are_offline_and_use_separate_adoption_artifacts(self):
        h, b, failed, control = evidence()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); paths = []
            for name, value in (('listing', h), ('body', b), ('failed', failed), ('control', control)):
                path = root / (name + '.json'); path.write_text(json.dumps(value)); paths.append(str(path))
            output = root / 'adoption'
            args = ['adopt', '--mode', 'plan', '--listing-state', paths[0], '--body-state', paths[1],
                    '--failed-state', paths[2], '--session-control', paths[3], '--output-dir', str(output)]
            with patch('sys.argv', args), patch('sys.stdout', new=io.StringIO()): a.main()
            report = json.loads((output / 'adoption-state.json').read_text())
            totals = json.loads((output / 'adoption-summary.json').read_text())
            self.assertNotIn('file_record', totals)
            self.assertEqual(totals['official_http_requests'], 0)
            args[2] = 'verify'; args += ['--adoption-state', str(output / 'adoption-state.json')]
            with patch('sys.argv', args), patch('sys.stdout', new=io.StringIO()): a.main()
            self.assertEqual(a.verify(h, b, failed, control, report), report)
            with patch.object(a, 'MAX_INPUT_BYTES', 2), patch('sys.argv', args), self.assertRaises(ValueError): a.main()
        self.no_http.assert_not_called()


if __name__ == '__main__':
    unittest.main()
