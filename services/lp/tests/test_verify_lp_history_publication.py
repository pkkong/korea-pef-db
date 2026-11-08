import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from prepare_lp_history_publication import verified_documents, proposal
from lp_program_service import build
from verify_lp_history_publication import verify
from services.lp.tests.test_prepare_lp_history_publication import evidence


class HistoricalPublicVerificationTests(unittest.TestCase):
    def setUp(self):
        docs = verified_documents(*evidence())
        data, summary = proposal({'as_of': '2026-11-09', 'programs': []}, docs, '2026-11-09T06:30:00+09:00')
        with tempfile.TemporaryDirectory() as folder:
            build(copy.deepcopy(data), Path(folder))
            self.pages = {f.name: f.read_text() for f in Path(folder).glob('*.html')}
        self.pages['review.html'] = 'preserved review page'
        self.published = {**summary, 'published': True, 'run_id': 'public-run',
                          'program_ids': [p['id'] for p in data['programs']],
                          'new_program_ids': [p['id'] for p in summary['new_programs']]}
        self.health = {'status': 'ok', 'data_source': 'supabase', 'stale': False, 'run_id': 'public-run'}
        self.wrong_headers = False
        self.wrong_run = False

    def read(self, path):
        name = path.split('?')[0]
        if name == 'health.json': return json.dumps(self.health), {}
        headers = {'x-lp-data-source': 'supabase', 'x-lp-run': 'wrong' if self.wrong_run else 'public-run',
                   'x-robots-tag': 'index, follow'}
        if name == 'review.html':
            headers.update({'x-robots-tag': 'noindex, nofollow', 'cache-control': 'no-store', 'x-frame-options': 'DENY'})
            if self.wrong_headers: headers.pop('x-frame-options')
        return self.pages[name], headers

    def test_actual_renderer_minute_precision_passes_without_changing_stored_iso(self):
        result = verify(self.published, self.read)
        self.assertEqual(result['verified_programs'], 1)
        self.assertTrue(result['access_boundaries_verified'])
        self.assertEqual(self.published['new_programs'][0]['deadline'], '2025-04-04T15:00:00+09:00')

    def test_changed_closing_time_future_plan_run_health_or_review_policy_fails(self):
        detail = 'program-'+self.published['new_program_ids'][0]+'.html'
        original = self.pages[detail]
        for change in ('deadline', 'plan', 'run', 'health', 'review'):
            self.pages[detail] = original; self.wrong_headers = self.wrong_run = False; self.health['stale'] = False
            if change == 'deadline': self.pages[detail] = original.replace('2025-04-04 15:00', '2025-04-04 16:00')
            elif change == 'plan': self.pages[detail] = original.replace('>예정일 경과<', '>예정<', 1)
            elif change == 'run': self.wrong_run = True
            elif change == 'health': self.health['stale'] = True
            else: self.wrong_headers = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify(self.published, self.read)

    def test_noop_does_not_verify_old_publication_as_a_new_success(self):
        self.published['published'] = False
        result = verify(self.published, lambda path: self.fail('No-op must not request public pages'))
        self.assertFalse(result['published'])


if __name__ == '__main__':
    unittest.main()
