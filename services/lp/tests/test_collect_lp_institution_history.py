import json
import tempfile
import unittest
from pathlib import Path

from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src import collect_lp_institution_history as history
from services.lp.tests.test_lp_board_adapters_pensions import TP_LIST, TP_DETAIL

STAMP = '2026-11-14T15:00:00+00:00'


def tp_fetch(detail=TP_DETAIL):
    listing, detail = ['<html>' + s + '</html>' for s in (TP_LIST, detail)]
    calls = []
    def fetch(url, referer=None):
        calls.append(url)
        if 'detail.do?' in url:
            return detail.encode()
        if 'download' in url or 'fileDown' in url or url.endswith('.zip'):
            return b'not a real zip'
        return listing.encode()
    fetch.calls = calls
    return fetch


class InstitutionHistoryTests(unittest.TestCase):
    def test_history_walk_collects_and_validates_with_shared_daily_steps(self):
        fetch = tp_fetch()
        bundle = history.collect('tp', '2020-01-01', '2026-11-14', max_pages=3, page_budget=20,
                                 fetch_factory=lambda c: fetch, checked_at=STAMP)
        self.assertEqual(bundle['kind'], history.KIND)
        self.assertGreaterEqual(bundle['candidate_count'], 1)
        self.assertEqual(len(bundle['notices']), bundle['candidate_count'], bundle['holds'])
        n = bundle['notices'][0]
        self.assertEqual(n['source_channel'], 'institution_board')
        # A notice from a history listing page fails the daily page-set check but passes the history one.
        self.assertEqual(boards.validate_notice(n, STAMP, boards.load_configs()['tp'], history_listing=True)['sha256'], n['sha256'])

    def test_listing_from_another_host_is_rejected_in_history_mode(self):
        config = boards.load_configs()['tp']
        self.assertFalse(boards._history_listing_ok('https://evil.example/tp-kr/bbs/i-151/list.do', config))

    def test_bundle_writes_text_json_and_attachment_files_separately(self):
        fetch = tp_fetch()
        bundle = history.collect('tp', '2020-01-01', '2026-11-14', max_pages=3, page_budget=20,
                                 fetch_factory=lambda c: fetch, checked_at=STAMP)
        with tempfile.TemporaryDirectory() as tmp:
            path = history.write_bundle(bundle, Path(tmp))
            data = json.loads(path.read_text())
            self.assertTrue(all('attachment_bytes' not in n for n in data['notices']))
            listing = data['notices'][0]['discovery_provenance']['listing']
            self.assertIn(listing['sha256'], data['listing_receipts'])
        self.assertEqual(history.summary(bundle)['collected'], len(bundle['notices']))

    def test_vc_only_and_outside_titles_are_not_history_candidates(self):
        base = {'relevant': True, 'title_scope': 'scope_unconfirmed'}
        self.assertTrue(history.history_candidate({**base, 'title': '2021년 국내 PE 블라인드 펀드 위탁운용사 선정 공고'}, 'tp'))
        self.assertFalse(history.history_candidate({**base, 'title_scope': 'vc_explicit', 'title': '2021년 VC 위탁운용사 선정'}, 'tp'))
        self.assertFalse(history.history_candidate({**base, 'relevant': False, 'title': '직원 채용 공고'}, 'tp'))

    def test_institution_without_board_adapter_is_refused(self):
        with self.assertRaises(ValueError):
            history.collect('kgrowth', '2020-01-01', '2026-11-14', fetch_factory=lambda c: None)

    def test_offline_review_turns_bundle_into_programs_without_db(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('review', Path(__file__).resolve().parents[3] / 'scripts/review_lp_history_bundles.py')
        review = importlib.util.module_from_spec(spec); spec.loader.exec_module(review)
        fetch = tp_fetch()
        bundle = history.collect('tp', '2020-01-01', '2026-11-14', max_pages=3, page_budget=20,
                                 fetch_factory=lambda c: fetch, checked_at=STAMP)
        with tempfile.TemporaryDirectory() as tmp:
            history.write_bundle(bundle, Path(tmp))
            _, notices = review.load(tmp)
        programs, by_inst, unlinked, _ = review.review(notices, STAMP)
        self.assertEqual(len(by_inst['tp']), 1)
        self.assertEqual(unlinked.get('tp', 0), 0)
        self.assertIn('| tp | 1 | 1 | 0 |', review.markdown(by_inst, unlinked, __import__('collections').Counter(), notices))


if __name__ == '__main__':
    unittest.main()
