import base64
import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from services.lp.src import probe_lp_report_storage as a


def bundles():
    stamp = '2026-11-09T06:00:00+00:00'
    raw = b'%PDF constructed source proof'
    digest = hashlib.sha256(raw).hexdigest()
    notice = {'source_id': '7', 'url': 'https://official.example/notice/7', 'title': 'Official title',
              'date': '2026-11-09', 'body': 'Original body', 'sha256': 'a' * 64,
              'attachments': ['https://official.example/file.pdf'],
              'attachment_hashes': {'https://official.example/file.pdf': digest},
              'attachment_texts': {'https://official.example/file.pdf': 'old layout'}, 'checked_at': stamp}
    priority = {'checked_at': stamp, 'sources': {'sample': {'checked_at': stamp, 'notices': [notice]}}}
    original = {'kgrowth-collection.json': {'checked_at': stamp, 'notices': [{'body': 'before\0after', 'literal': r'\u0000'}]},
                'lp-priority-collection.json': priority, 'lp-shared-collection.json': {'notices': [], 'checked_at': stamp},
                'lp-institution-collection.json': {'notices': [], 'checked_at': stamp}}
    encode = lambda d: {name: json.dumps(value, ensure_ascii=False).encode() for name, value in d.items()}
    original = encode(original)
    recovery = {k: v for k, v in original.items() if k != 'kgrowth-collection.json'}
    return original, recovery, raw


class Result:
    def __init__(self, values): self.values = values
    def fetchone(self): return self.values[0] if self.values else None
    def fetchall(self): return self.values


class LocalDatabase:
    def __init__(self, *, fail=False, altered=False, identity=('lp_report_probe', 'lp_probe')):
        self.parts = []; self.stored = None; self.queries = []; self.fail = fail
        self.altered = altered; self.identity = identity; self.committed = False; self.rolled_back = False
    def __enter__(self): return self
    def __exit__(self, kind, value, trace):
        self.committed = kind is None; self.rolled_back = kind is not None
    def execute(self, query, params=None):
        self.queries.append((query, params))
        if query.startswith('SELECT current_database'): return Result([self.identity])
        if query.startswith('SELECT name,setting,unit'):
            return Result([('server_version_num', '170006', None), ('work_mem', '4096', 'kB'),
                           ('shared_buffers', '16384', '8kB'), ('statement_timeout', '120000', 'ms')])
        if query.startswith('INSERT INTO pg_temp.lp_collection_report_parts'):
            self.parts.append(params); return Result([])
        if query.startswith('INSERT INTO lp_program_private.collection_runs'):
            if self.fail: raise RuntimeError('SECRET production-host.example Authorization: token')
            self.stored = json.loads(''.join(payload for _, payload in sorted(self.parts)))
            return Result([])
        if query.startswith('SELECT report FROM'):
            return Result([({'changed': True} if self.altered else self.stored,)])
        if query.startswith('SELECT count(*)'): return Result([(1,)])
        if query.startswith(('SET LOCAL ', 'CREATE SCHEMA ', 'CREATE TABLE ', 'CREATE TEMP TABLE ')): return Result([])
        raise AssertionError('Unexpected local probe query')


class ReportStorageProbeTests(unittest.TestCase):
    def test_local_dsn_is_strict_and_never_uses_production_environment(self):
        for dsn in ('postgresql://lp_probe:lp_probe@db.production.example:5432/lp_report_probe',
                    a.LOCAL_DSN + '?host=production.example', a.LOCAL_DSN + '#x',
                    a.LOCAL_DSN.replace(':5432/', ':6543/'), a.LOCAL_DSN.replace('/lp_report_probe', '/postgres'),
                    a.LOCAL_DSN.replace('lp_probe:lp_probe@', 'production:secret@'), a.LOCAL_DSN + '\n',
                    a.LOCAL_DSN.replace('127.0.0.1', '127.0.0.1,production.example'),
                    'host=localhost dbname=lp_report_probe'):
            factory = Mock()
            result = a.run_probe({'test': True}, dsn=dsn, connect=factory)
            with self.subTest(dsn=dsn):
                self.assertFalse(result['success']); factory.assert_not_called()
        conn = LocalDatabase(); factory = Mock(return_value=conn)
        with patch.dict(os.environ, {'SUPABASE_DB_URL': 'postgresql://SECRET@production.invalid/prod',
                                     'PGHOST': 'production.invalid', 'PGPORT': '6543'}):
            result = a.run_probe({'safe': True}, connect=factory)
        self.assertTrue(result['success'])
        self.assertEqual(factory.call_args.kwargs['hostaddr'], '127.0.0.1')
        self.assertEqual(factory.call_args.kwargs['dbname'], 'lp_report_probe')
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertEqual(a.local_connection_parameters(a.LOCAL_DSN.replace('127.0.0.1', 'localhost'))['host'], '127.0.0.1')

    def test_actual_unchanged_store_function_parts_and_full_readback_in_one_transaction(self):
        report = {'unicode': '한글🙂' * 190000, 'zero': 0, 'flag': False, 'none': None, 'literal': r'\u0000'}
        before = copy.deepcopy(report); conn = LocalDatabase(); updates = []
        publisher = a._publisher(); original = publisher.publication_phase
        result = a.run_probe(report, connect=Mock(return_value=conn), on_metadata=updates.append,
                             container_memory_limit=512 * 1024 * 1024)
        self.assertTrue(result['success']); self.assertTrue(conn.committed)
        self.assertEqual(report, before); self.assertEqual(conn.stored, report)
        self.assertIs(publisher.publication_phase, original)
        self.assertGreater(len(conn.parts), 1)
        self.assertTrue(all(len(payload.encode()) <= 1024 * 1024 for _, payload in conn.parts))
        self.assertTrue(any("string_agg(payload,'' ORDER BY seq)::jsonb" in sql for sql, _ in conn.queries))
        self.assertFalse(any('program_state' in sql or 'documents' in sql for sql, _ in conn.queries))
        self.assertEqual(result['readback_sha256'], result['report_sha256'])
        self.assertEqual(result['rows'], 1)
        self.assertTrue(any(item['stage'] == 'collection_report_parts' for item in updates))
        self.assertNotIn('한글', json.dumps(result, ensure_ascii=False))
        self.assertNotIn('string_agg', json.dumps(result))

    def test_failure_is_sanitized_non_success_and_readback_mismatch_rolls_back(self):
        for conn in (LocalDatabase(fail=True), LocalDatabase(altered=True), LocalDatabase(identity=('postgres', 'lp_probe'))):
            updates = []; result = a.run_probe({'test': True}, connect=lambda **kw: conn, on_metadata=updates.append)
            self.assertFalse(result['success']); self.assertTrue(conn.rolled_back)
            self.assertIn(result['error_type'], ('RuntimeError', 'ValueError'))
            self.assertNotIn('SECRET', json.dumps(result)); self.assertNotIn('production-host', json.dumps(updates))
        factory = Mock()
        self.assertFalse(a.run_probe({}, connect=factory, container_memory_limit=1024**3)['success'])
        factory.assert_not_called()

    def test_main_completed_recent_provenance_and_no_dispatch_inputs_assumption(self):
        now = datetime(2026, 11, 10, 0, tzinfo=timezone.utc)
        def run(ident, path, stamp, event, conclusion):
            return {'id': ident, 'repository': {'full_name': 'owner/repo'}, 'head_repository': {'full_name': 'owner/repo'},
                    'head_branch': 'main', 'head_sha': 'a' * 40, 'path': path, 'status': 'completed',
                    'created_at': stamp, 'event': event, 'conclusion': conclusion}
        collection = run(1, '.github/workflows/collect-kgrowth-programs.yml', '2026-11-09T06:00:00Z', 'schedule', 'failure')
        recovery = run(2, '.github/workflows/recover-lp-publication.yml', '2026-11-09T19:00:00Z', 'workflow_dispatch', 'cancelled')
        proof = a.validate_provenance(collection, recovery, 'owner/repo', now=now)
        self.assertFalse(proof['dispatch_inputs_assumed_available'])
        for key, value in [('head_branch', 'branch'), ('path', '.github/workflows/other.yml'), ('status', 'in_progress'),
                           ('created_at', '2026-11-01T00:00:00Z'), ('created_at', '2026-11-11T00:00:00Z'),
                           ('event', 'pull_request'), ('repository', {'full_name': 'other/repo'})]:
            changed = {**collection, key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): a.validate_provenance(changed, recovery, 'owner/repo', now=now)
        with self.assertRaises(ValueError): a.validate_provenance(collection, {**recovery, 'created_at': '2026-11-09T01:00:00Z'}, 'owner/repo', now=now)

    def test_bundle_binding_exact_bytes_notice_core_and_only_proven_raw_preview_deletion(self):
        original, recovery, raw = bundles(); before = copy.deepcopy((original, recovery))
        self.assertEqual(a.validate_bundles(original, recovery)['priority_notice_cores_matched'], 1)
        priority = json.loads(recovery['lp-priority-collection.json']); notice = priority['sources']['sample']['notices'][0]
        url = notice['attachments'][0]; notice['attachment_texts'] = {}
        notice['attachment_proofs'] = {url: {'sha256': hashlib.sha256(raw).hexdigest(),
                                           'raw_base64': base64.b64encode(raw).decode(), 'extracted': {'text': 'canonical proof'}}}
        upgraded = {**recovery, 'lp-priority-collection.json': json.dumps(priority).encode()}
        self.assertEqual(a.validate_bundles(original, upgraded)['deleted_legacy_previews_with_same_raw_file'], 1)
        # Hash maps alone cannot authorize a removed preview for a file that
        # was not an original attachment. Both supported link shapes count.
        for links, allowed in (([], False), ([{'url': url, 'name': 'official.pdf'}], True)):
            original_value = json.loads(original['lp-priority-collection.json'])
            recovered_value = copy.deepcopy(priority)
            for value in (original_value, recovered_value):
                value['sources']['sample']['notices'][0]['attachments'] = links
            source_bundle = {**original, 'lp-priority-collection.json': json.dumps(original_value).encode()}
            recovered_bundle = {**upgraded, 'lp-priority-collection.json': json.dumps(recovered_value).encode()}
            if allowed:
                self.assertEqual(a.validate_bundles(source_bundle, recovered_bundle)['deleted_legacy_previews_with_same_raw_file'], 1)
            else:
                with self.assertRaisesRegex(ValueError, 'Removed preview'):
                    a.validate_bundles(source_bundle, recovered_bundle)
        for change in ('shared', 'institution', 'body', 'file_hash', 'text_change', 'text_add', 'no_proof', 'bad_proof', 'extra_notice', 'field'):
            altered = copy.deepcopy(upgraded); p = json.loads(altered['lp-priority-collection.json']); n = p['sources']['sample']['notices'][0]
            if change == 'shared': altered['lp-shared-collection.json'] += b' '
            elif change == 'institution': altered['lp-institution-collection.json'] += b' '
            elif change == 'body': n['body'] += 'changed'
            elif change == 'file_hash': n['attachment_hashes'][url] = '0' * 64
            elif change == 'text_change': n['attachment_texts'][url] = 'changed text'
            elif change == 'text_add': n['attachment_texts']['other'] = 'new text'
            elif change == 'no_proof': del n['attachment_proofs']
            elif change == 'bad_proof': n['attachment_proofs'][url]['raw_base64'] = base64.b64encode(b'changed').decode()
            elif change == 'extra_notice': p['sources']['sample']['notices'].append(copy.deepcopy(n))
            else: n['selected_gps'] = ['unapproved']
            altered['lp-priority-collection.json'] = json.dumps(p).encode()
            with self.subTest(change=change), self.assertRaises(ValueError): a.validate_bundles(original, altered)
        self.assertEqual((original, recovery), before)

    def test_reconstruct_only_changes_report_replay_time_and_cleaning_not_source_inputs(self):
        original, recovery, _ = bundles(); before = copy.deepcopy((original, recovery))
        publisher = a._publisher()
        with patch.object(publisher, 'prepare', side_effect=AssertionError('No prepare/OCR')), \
             patch.object(publisher, 'connect', side_effect=AssertionError('No production connection')):
            report = a.reconstruct_report(original, recovery, checked_at='2026-11-10T00:00:00Z')
        self.assertEqual(report['collection_checked_at'], '2026-11-09T06:00:00+00:00')
        self.assertEqual(report['checked_at'], '2026-11-10T00:00:00Z')
        self.assertEqual(report['notices'][0]['body'], 'before after')
        self.assertEqual(report['notices'][0]['literal'], r'\u0000')
        self.assertEqual((original, recovery), before)

    def test_workflow_is_local_readonly_metadata_only_and_uses_shared_queue(self):
        text = (Path(__file__).resolve().parents[3] / '.github/workflows/probe-lp-report-storage.yml').read_text()
        for marker in ('group: lp-program-collection', 'contents: read', 'actions: read', "github.ref == 'refs/heads/main'",
                       'image: postgres:17', '--memory=512m', 'timeout-minutes: 10', "'psycopg[binary]==3.2.10'"):
            self.assertIn(marker, text)
        self.assertNotIn('secrets.', text); self.assertNotIn('SUPABASE_DB_URL', text)
        upload = text.split('- uses: actions/upload-artifact@v4', 1)[1]
        self.assertIn('/tmp/lp-report-probe-output/probe.json', upload)
        self.assertNotIn('probe-input', upload); self.assertNotIn('collection.json', upload)


if __name__ == '__main__':
    unittest.main()
