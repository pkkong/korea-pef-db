import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import publish_lp_history as p
from services.lp.tests.test_prepare_lp_history_publication import evidence


class HistoryPublicationTests(unittest.TestCase):
    def setUp(self):
        self.sources = evidence()
        self.current = json.loads((Path(__file__).resolve().parents[3] / 'data/lp_programs_pilot.json').read_text())
        self.current['review_decisions'] = [{'id': 5, 'action': 'hold'}]
        with tempfile.TemporaryDirectory() as folder:
            p.build(copy.deepcopy(self.current), Path(folder))
            self.old_pages = {f.name: f.read_text() for f in Path(folder).glob('*.html')}
        self.old_pages['review.html'] = 'existing private review page'
        self.revision = (('old-run', 'old-stamp'), self.current['review_decisions'])

    def preparation(self, pages=None, current=None):
        conn = MagicMock(); conn.__enter__.return_value = conn
        active = []
        conn.__enter__.side_effect = lambda: active.append(True) or conn
        conn.__exit__.side_effect = lambda *a: active.pop()
        conn.execute.return_value.fetchone.return_value = (pages if pages is not None else self.old_pages,)
        real_build = p.build
        def offline_build(*args):
            self.assertFalse(active, 'Release pooled read connection before building pages')
            return real_build(*args)
        with patch.object(p, 'connect', return_value=conn), \
             patch.object(p, 'baseline', return_value=current or self.current), \
             patch.object(p, 'publication_revision', return_value=self.revision), \
             patch.object(p, 'retained_documents', return_value=[{'url': 'retained'}]), \
             patch.object(p, 'build', side_effect=offline_build):
            prepared, summary = p.prepare(*self.sources, {'trusted_runs': 'fixture'}, '2026-11-09T06:30:00+09:00')
        self.assertIn('READ ONLY', conn.execute.call_args_list[0].args[0])
        return prepared, summary

    def test_retained_source_replay_preserves_all_old_models_details_review_and_freshness(self):
        before = copy.deepcopy(self.current)
        prepared, result = self.preparation()
        report, data, pages, revision = prepared
        self.assertEqual(self.current, before)
        self.assertEqual(data['programs'][:-1], before['programs'])
        self.assertEqual(data['as_of'], before['as_of'])
        self.assertEqual(data['review_decisions'], before['review_decisions'])
        self.assertEqual(pages['review.html'], self.old_pages['review.html'])
        for program in before['programs']:
            name = 'program-'+program['id']+'.html'
            self.assertEqual(pages[name], self.old_pages[name])
        self.assertEqual(len(result['new_programs']), 1)
        self.assertEqual(result['new_programs'][0]['selected_gps'], [])
        self.assertEqual(report['kind'], 'lp_history_publication_v1')
        self.assertEqual(report['checked_at'], max(n['checked_at'] for n in report['notices']))
        self.assertNotEqual(report['checked_at'], report['prepared_at'])
        self.assertEqual(revision, self.revision)

    def test_changed_existing_html_or_missing_review_is_not_published(self):
        for change in ('detail', 'review'):
            pages = copy.deepcopy(self.old_pages)
            if change == 'review': pages.pop('review.html')
            else: pages['program-'+self.current['programs'][0]['id']+'.html'] = 'changed'
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.preparation(pages=pages)

    def test_already_present_recruitment_is_a_read_only_noop(self):
        prepared, _ = self.preparation()
        again, summary = self.preparation(current=prepared[1])
        self.assertIsNone(again)
        self.assertFalse(summary['published'])
        self.assertEqual(summary['reason'], 'no_new_verified_programs')

    def transaction(self, prepared, *, changed=False, bad_source=False, bad_readback=False, write_failure=False):
        conn = MagicMock(); conn.__enter__.return_value = conn
        stored = {}
        def execute(sql, args=None):
            if sql.startswith('SELECT data,pages,run_id'):
                return MagicMock(fetchone=lambda: (stored['data'], stored['pages'], 'wrong' if bad_readback else stored['run_id']))
            return MagicMock()
        conn.execute.side_effect = execute
        def source_check(c, docs):
            self.assertIn('pg_advisory_xact_lock', c.execute.call_args.args[0])
            if bad_source: raise ValueError('source changed')
        def store(c, data, pages, run):
            if write_failure: raise RuntimeError('state write failed')
            stored.update(data=data, pages=pages, run_id=run)
        revision = (('other-run', 'changed'), self.revision[1]) if changed else self.revision
        with patch.object(p, 'connect', return_value=conn), \
             patch.object(p, 'publication_revision', return_value=revision), \
             patch.object(p, 'retained_documents', side_effect=source_check), \
             patch.object(p, 'store_collection_report') as reports, \
             patch.object(p, 'store_public_state', side_effect=store) as state:
            try:
                result = p.commit(prepared)
            except (RuntimeError, ValueError):
                if changed or bad_source:
                    reports.assert_not_called(); state.assert_not_called()
                self.assertIsNotNone(conn.__exit__.call_args.args[0])
                raise
            reports.assert_called_once(); state.assert_called_once()
            self.assertEqual(reports.call_args.args[3], 'lp_history')
            self.assertIsNone(conn.__exit__.call_args.args[0])
            return result

    def test_changed_revision_evidence_readback_or_write_failure_rolls_back(self):
        prepared, _ = self.preparation()
        for option in ('changed', 'bad_source', 'bad_readback', 'write_failure'):
            with self.subTest(option=option), self.assertRaises((RuntimeError, ValueError)):
                self.transaction(prepared, **{option: True})

    def test_success_rechecks_sources_under_lock_and_confirms_readback(self):
        prepared, _ = self.preparation()
        result = self.transaction(prepared)
        self.assertTrue(result['published']); self.assertTrue(result['database_readback_verified'])
        self.assertEqual(result['official_http_requests'], 0)
        self.assertEqual(result['document_versions_added'], 0)
        self.assertEqual(len(result['new_program_ids']), 1)
        self.assertFalse(result['scheduled_success'])


if __name__ == '__main__':
    unittest.main()
