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

    def test_failed_detail_keeps_its_page_for_parser_fixes(self):
        fetch = tp_fetch(detail='<div>no detail table</div>')
        bundle = history.collect('tp', '2020-01-01', '2026-11-14', max_pages=3, page_budget=20,
                                 fetch_factory=lambda c: fetch, checked_at=STAMP)
        self.assertEqual(bundle['notices'], [])
        self.assertIn('no detail table', bundle['holds'][0]['detail_page'])


class KgrowthHistoryTests(unittest.TestCase):
    """성장금융: body once, then one public session (body → file) per attachment."""

    def run_collect(self, file_raw=b'%PDF-1.4 fake', attachment=True):
        from urllib.parse import parse_qs, urlsplit
        from services.lp.tests.test_audit_lp_official_inventory import growth
        from services.lp.tests.test_collect_lp_history_bodies import detail
        listing = {1: growth([('2', '1020', '2021년 PE 블라인드 펀드 위탁운용사 선정계획 공고', '2021-05-03')]),
                   2: growth([('1', '900', '오래된 공고', '2019-12-01')])}
        row = {'source_id': '1020', 'title': '2021년 PE 블라인드 펀드 위탁운용사 선정계획 공고', 'date': '2021-05-03'}
        page = detail(row, body='PE 블라인드 펀드 출자 공고 본문', attachment=attachment)

        def body_fetch(url, referer=None):
            if 'notice_view.asp' in url:
                return page
            return listing[int(parse_qs(urlsplit(url).query).get('page', ['1'])[0])].encode()

        sessions = []

        class FakeSession:
            def __init__(self, r):
                self.row, self.calls = r, []
                sessions.append(self)

            def __call__(self, url, kind):
                self.calls.append(kind)
                return {'raw': page if kind == 'body' else file_raw, 'set_cookie_seen': True}

        from services.lp.src import collect_lp_institution_history as h
        import services.lp.src.collect_lp_history_attachments as attach
        original = attach.read_attachment
        attach.read_attachment = lambda raw: {'text': '공고문 PE 블라인드'}
        try:
            bundle = h.collect_kgrowth('2020-01-01', '2022-12-31', max_pages=5, page_budget=20,
                                       body_fetch=body_fetch, session_factory=FakeSession, checked_at=STAMP)
        finally:
            attach.read_attachment = original
        return bundle, sessions

    def test_body_then_one_session_per_attachment(self):
        bundle, sessions = self.run_collect()
        self.assertEqual(len(bundle['notices']), 1, bundle['holds'])
        n = bundle['notices'][0]
        self.assertEqual((n['institution_id'], n['source_id'], n['date']), ('kgrowth', '1020', '2021-05-03'))
        self.assertEqual([s.calls for s in sessions], [['body', 'file']])
        self.assertEqual(len(n['attachment_hashes']), 1)

    def test_kgrowth_detail_bytes_survive_bundle_for_independent_replay(self):
        import base64
        import hashlib
        from services.lp.src.collect_lp_history_bodies import read_body
        bundle, _ = self.run_collect()
        with tempfile.TemporaryDirectory() as tmp:
            saved = json.loads(history.write_bundle(bundle, Path(tmp)).read_text())
        n = saved['notices'][0]
        proof = n['discovery_provenance']
        raw = base64.b64decode(proof['detail_response_base64'], validate=True)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), proof['detail_sha256'])
        replayed = read_body(n['source_id'], raw, 'kgrowth')
        self.assertTrue(all(n[k] == value for k, value in replayed.items()))
        self.assertNotIn('attachment_bytes', n)

    def test_blocked_file_is_held_not_stored(self):
        bundle, _ = self.run_collect(file_raw='비정상적인 접근입니다'.encode('cp949'))
        self.assertEqual(bundle['notices'][0]['attachment_hashes'], {})
        self.assertEqual(bundle['holds'][0]['stage'], 'history_attachment')


class HistoryNoticeStateTests(unittest.TestCase):
    """Imported history notices: no attachment bytes, every receipt re-checked each run."""

    def imported(self):
        from services.lp.src import lp_history_notices as hn
        fetch = tp_fetch()
        bundle = history.collect('tp', '2020-01-01', '2026-11-14', max_pages=3, page_budget=20,
                                 fetch_factory=lambda c: fetch, checked_at=STAMP)
        n = dict(bundle['notices'][0])
        n['attachment_bytes'] = {}
        n['history_import'] = hn.KIND
        return hn, n

    def test_valid_import_is_retained_and_marked(self):
        hn, n = self.imported()
        result = hn.update_catalog({}, {'notices': [n]}, '2026-11-15T00:00:00+00:00')
        self.assertEqual(len(result['history_notices']), 1)
        self.assertEqual(result['history_notice_holds'], [])
        again = hn.update_catalog(result, None, '2026-11-16T00:00:00+00:00')
        self.assertEqual(len(again['history_notices']), 1)

    def test_tampered_or_unmarked_or_byte_carrying_notices_are_held(self):
        hn, n = self.imported()
        bad_body = {**n, 'body': n['body'] + ' 변조'}
        unmarked = {k: v for k, v in n.items() if k != 'history_import'}
        with_bytes = {**n, 'attachment_bytes': {'x': 'eA=='}}
        result = hn.update_catalog({}, {'notices': [bad_body, unmarked, with_bytes]}, '2026-11-15T00:00:00+00:00')
        self.assertEqual(result['history_notices'], [])
        self.assertEqual(len(result['history_notice_holds']), 3)

    def test_merge_requires_the_reviewed_hash(self):
        from services.lp.src import build_lp_history_import as imp
        with tempfile.TemporaryDirectory() as tmp:
            collection, payload = Path(tmp) / 'c.json', Path(tmp) / 'i.json'
            collection.write_text(json.dumps({'notices': [], 'holds': []}))
            payload.write_bytes(json.dumps({'kind': 'lp_history_import_v1', 'notices': [{'url': 'u'}]}).encode())
            import hashlib
            digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                imp.merge(collection, payload, '0' * 64)
            self.assertEqual(imp.merge(collection, payload, digest), 1)
            self.assertEqual(json.loads(collection.read_text())['history_import']['sha256'], digest)


if __name__ == '__main__':
    unittest.main()
