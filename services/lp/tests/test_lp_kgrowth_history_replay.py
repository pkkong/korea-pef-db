"""Original-byte continuity and fail-closed recovery, without origin HTTP."""
import base64
import copy
import hashlib
import html
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.lp.src import lp_kgrowth_history_replay as replay
from services.lp.src import lp_kgrowth_press_probe as press
from services.lp.tests.test_lp_kgrowth_history_terms import iii
from services.lp.tests.test_lp_kgrowth_history_terms import bundle, notice
from services.lp.tests.test_lp_kgrowth_joint_history import materials, OFFER, TITLE, BODY
from services.lp.tests.test_lp_kgrowth_newdeal_joint_history import newdeal

STAMP = '2026-11-16T12:31:00+00:00'


def detail(n, *, suffix=''):
    links = ''.join(f'<a href="{html.escape(u)}">file</a>' for u in n['attachments'])
    return (f'<html><body><div class="view_info"><p class="tit">{html.escape(n["title"])}</p>'
            f'<p class="date">{n["date"]}</p></div>'
            f'<div class="veiw_contents">{html.escape(n["body"])}</div>{links}{suffix}</body></html>').encode('cp949')


def fixture(*, retained=False):
    b = iii()
    raw = {}
    for n in b['notices']:
        raw[n['url']] = detail(n)
        p = n['discovery_provenance']
        p['detail_sha256'] = hashlib.sha256(raw[n['url']]).hexdigest()
        if retained:
            p['detail_response_base64'] = base64.b64encode(raw[n['url']]).decode()
    attachment = b'%PDF-1.4 fixture'
    n = b['notices'][0]
    n['attachment_hashes'] = {u: hashlib.sha256(attachment).hexdigest() for u in n['attachments']}
    return b, raw, attachment


class GrowthReplayTests(unittest.TestCase):
    def capture(self, b, raw, **kwargs):
        calls = []
        def fetch(url):
            calls.append(url)
            return {'raw': raw[url], 'http_status': 200}
        result = replay.capture_details(b, fetch, checked_at=STAMP, **kwargs)
        return result, calls

    def test_selection_uses_observed_group_and_is_order_independent(self):
        b, _, _ = fixture()
        a = replay.target_group(b)
        b['notices'].reverse()
        c = replay.target_group(b)
        self.assertEqual([n['url'] for n in a[1]], [n['url'] for n in c[1]])
        self.assertEqual(len(a[1]), 2)
        self.assertTrue(a[0]['rosters'])

    def test_two_missing_details_only_and_no_attachment_fetch(self):
        b, raw, _ = fixture()
        r, calls = self.capture(b, raw)
        self.assertEqual(r['holds'], [])
        self.assertEqual(calls, r['planned_urls'])
        self.assertEqual(r['requests'], 2)
        self.assertTrue(all('notice_view.asp' in url for url in calls))
        self.assertEqual(r['database_writes'], 0)
        self.assertFalse(r['published'])

    def test_response_is_retained_before_detail_parser_runs(self):
        b, raw, _ = fixture()
        saved, original = [], replay.read_body
        def parse(*args):
            self.assertTrue(saved[-1]['responses'][-1]['raw_base64'])
            return original(*args)
        with patch.object(replay, 'read_body', side_effect=parse):
            r, _ = self.capture(b, raw, retain=lambda report: saved.append(copy.deepcopy(report)))
        self.assertFalse(r['holds'])

    def test_blocked_http_body_is_retained_and_stops_the_batch(self):
        b, _, _ = fixture()
        saved = []
        r = replay.capture_details(b, lambda url: {'raw': b'Access denied', 'http_status': 403},
                                   checked_at=STAMP, retain=lambda report: saved.append(copy.deepcopy(report)))
        self.assertEqual(r['requests'], 1)
        self.assertTrue(r['holds'])
        self.assertEqual(base64.b64decode(saved[-1]['responses'][0]['raw_base64']), b'Access denied')
        with self.assertRaisesRegex(ValueError, '실패 응답'):
            replay.replay_group(b, lambda sha: None, capture=r)

    def test_changed_semantics_never_overwrite_the_old_body_or_hash(self):
        b, raw, _ = fixture()
        original = copy.deepcopy(b)
        first = b['notices'][0]
        raw[first['url']] = detail({**first, 'body': '다른 공고 본문'})
        r, calls = self.capture(b, raw)
        self.assertEqual(len(calls), 1)
        self.assertIn('보관 제목', r['holds'][0]['reason'])
        self.assertEqual(b, original)

    def test_recaptured_page_does_not_claim_original_byte_equality(self):
        b, raw, attachment = fixture()
        first = b['notices'][0]
        raw[first['url']] = detail(first, suffix='<!-- dynamic view counter -->')
        r, _ = self.capture(b, raw)
        with patch.object(replay, 'kgrowth_attachment_text', return_value=next(iter(first['attachment_texts'].values()))):
            result = replay.replay_group(b, lambda sha: attachment, capture=r)
        self.assertTrue(result['raw_replay_complete'], result['holds'])
        self.assertFalse(result['notices'][0]['detail']['original_bytes_match'])
        self.assertFalse(result['publication_ready'])
        self.assertFalse(result['domestic_investment_approved'])

    def test_missing_raw_stays_incomplete_even_with_replayed_attachment(self):
        b, _, attachment = fixture()
        text = next(iter(b['notices'][0]['attachment_texts'].values()))
        with patch.object(replay, 'kgrowth_attachment_text', return_value=text):
            r = replay.replay_group(b, lambda sha: attachment)
        self.assertFalse(r['raw_replay_complete'])
        self.assertEqual(len(r['holds']), 2)
        self.assertTrue(r['notices'][0]['attachments'][0]['text_replayed'])

    def test_corrupt_attachment_or_changed_extraction_remains_held(self):
        b, raw, attachment = fixture()
        r, _ = self.capture(b, raw)
        bad_hash = replay.replay_group(b, lambda sha: b'corrupt', capture=r)
        self.assertFalse(bad_hash['raw_replay_complete'])
        with patch.object(replay, 'kgrowth_attachment_text', return_value='altered text'):
            bad_text = replay.replay_group(b, lambda sha: attachment, capture=r)
        self.assertFalse(bad_text['raw_replay_complete'])

    def test_tampered_receipt_bundle_time_hash_identity_or_status_rejected(self):
        b, raw, _ = fixture()
        r, _ = self.capture(b, raw)
        for key, value in [('sha256', '0' * 64), ('checked_at', '2026-01-01T00:00:00Z'),
                           ('checked_at', '2099-01-01T00:00:00Z'),
                           ('source_id', '999'), ('http_status', 403), ('truncated', True),
                           ('original_detail_sha256', '0' * 64), ('bytes', 1)]:
            with self.subTest(key=key):
                changed = copy.deepcopy(r)
                changed['responses'][0][key] = value
                with self.assertRaises(ValueError):
                    replay.replay_group(b, lambda sha: None, capture=changed)
        changed = copy.deepcopy(r)
        changed['bundle_content_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            replay.replay_group(b, lambda sha: None, capture=changed)

    def test_forged_request_count_or_reordered_responses_is_rejected(self):
        b, raw, _ = fixture()
        r, _ = self.capture(b, raw)
        for change in ('count', 'order'):
            changed = copy.deepcopy(r)
            if change == 'count':
                changed['requests'] = 999
            else:
                changed['responses'].reverse()
            with self.assertRaisesRegex(ValueError, '요청 수·자동 순서'):
                replay.replay_group(b, lambda sha: None, capture=changed)

    def test_existing_asset_or_failed_capture_output_cannot_be_overwritten(self):
        b, _, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / 'bundle.json'
            bundle.write_text(json.dumps(b), encoding='utf-8')
            for name, content in [('a' * 64, b'%PDF original bytes'),
                                  ('failed.json', b'{"holds":["blocked response"]}')]:
                out = root / name
                out.write_bytes(content)
                with patch.object(replay, 'fetch_detail') as fetch, self.assertRaises(SystemExit):
                    replay.main(['--bundle', str(bundle), '--capture-details', '--out', str(out)])
                self.assertEqual(out.read_bytes(), content)
                fetch.assert_not_called()

    def test_prior_originals_are_replayed_without_any_http(self):
        b, raw, _ = fixture(retained=True)
        r, calls = self.capture(b, raw)
        self.assertEqual(r['holds'], [])
        self.assertEqual(calls, [])
        proof = b['notices'][0]['discovery_provenance']
        proof['detail_response_base64'] = base64.b64encode(b'corrupt').decode()
        with self.assertRaisesRegex(ValueError, '지문'):
            self.capture(b, raw)

    def test_metadata_failure_and_request_limit_fail_before_http(self):
        b, raw, _ = fixture()
        with self.assertRaisesRegex(ValueError, '상한'):
            self.capture(b, raw, limit=1)
        b['notices'][0]['body'] += 'altered'
        with self.assertRaisesRegex(ValueError, '메타 검증'):
            self.capture(b, raw)

    def test_capture_does_not_follow_redirects_or_accept_other_urls(self):
        self.assertIsNone(replay._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))
        with self.assertRaises(ValueError):
            replay.fetch_detail('https://other.example/notice_view.asp?idx=489')

    def test_joint_originals_are_selected_without_a_roster_or_source_id_input(self):
        b = bundle(materials())
        group, selected = replay.target_group(b, review_scope='joint_originals')
        self.assertEqual(len(selected), 1)
        self.assertEqual(group['identity']['kind'], 'hosted_joint_originals')
        self.assertEqual(selected[0]['institution_id'], 'kgrowth')
        self.assertEqual(replay.target_group(b), (None, []))
        before = copy.deepcopy(b)
        n = selected[0]
        captured, calls = self.capture(b, {n['url']: detail(n)}, review_scope='joint_originals')
        self.assertEqual(captured['holds'], [])
        self.assertEqual(calls, [n['url']])
        self.assertEqual(b, before)
        self.assertEqual(captured['database_writes'], 0)
        self.assertFalse(captured['published'])

    def test_joint_selection_is_stable_bounded_and_reports_remaining_sources(self):
        ns = [notice(str(471 + i), TITLE.replace('(2차)', f'({i+2}차)'), '2021-04-01', BODY,
                     OFFER.replace('(2차)', f'({i+2}차)')) for i in range(3)]
        b = bundle(*reversed(ns))
        group, selected = replay.target_group(b, review_scope='joint_originals')
        b['notices'].reverse()
        other, ordered = replay.target_group(b, review_scope='joint_originals')
        self.assertEqual(group, other)
        self.assertEqual([n['url'] for n in selected], [n['url'] for n in ordered])
        self.assertEqual(len(selected), 2)
        self.assertEqual(group['remaining_candidates'], 1)
        with self.assertRaisesRegex(ValueError, '상한'):
            self.capture(b, {}, limit=1, review_scope='joint_originals')

    def test_different_joint_plans_are_selected_without_reassigning_or_merging_them(self):
        b = bundle(materials(), newdeal())
        group, ns = replay.target_group(b, review_scope='joint_originals')
        self.assertEqual(len(ns), 2)
        self.assertEqual([i['year'] for i in group['identity']['programs']], ['2021', '2021'])
        self.assertEqual([i['round'] for i in group['identity']['programs']], ['2차', '정시'])
        self.assertEqual({n['institution_id'] for n in ns}, {'kgrowth'})
        self.assertEqual([n['date'] for n in ns], ['2020-12-29', '2021-04-01'])
        result, calls = self.capture(b, {n['url']: detail(n) for n in ns}, review_scope='joint_originals')
        self.assertEqual(result['holds'], [])
        self.assertEqual(result['requests'], 2)
        self.assertEqual(calls, [n['url'] for n in ns])
        self.assertEqual(result['remaining_candidates'], 0)

    def test_press_search_selects_quoted_funds_from_verified_joint_offerings(self):
        expected = ['정책형 뉴딜펀드', '소재·부품·장비 분야 투자 전용 펀드']
        self.assertEqual(replay.press_search_terms(bundle(materials(), newdeal())), expected)
        self.assertEqual(replay.press_search_terms(bundle(newdeal(), materials())), expected)
        with self.assertRaisesRegex(ValueError, '공동 원모집'):
            replay.press_search_terms(iii())

    def test_newdeal_followup_capture_selects_only_the_source_advertised_faq(self):
        faq = notice('701', '【선정공고】 「정책형 뉴딜펀드」 2021년 정시 출자사업 온라인 설명회',
                     '2021-01-06', '기업투자 FAQ를 추가하여 첨부하였으니 참고하시기 바랍니다.', '')
        unrelated = notice('702', '【선정결과】 「정책형 뉴딜펀드」 2021년 정시 기업투자 1차 심사 결과',
                           '2021-02-17', '1차 심사를 통과한 15개 펀드', '')
        b = bundle(newdeal(), unrelated, faq)
        capture, calls = self.capture(b, {faq['url']: detail(faq)}, review_scope=replay.NEWDEAL_FOLLOWUPS)
        self.assertEqual(calls, [faq['url']])
        self.assertEqual(capture['holds'], [])
        self.assertEqual(capture['database_writes'], 0)
        self.assertFalse(capture['published'])

    def test_joint_capture_and_attachment_replay_preserve_source_identity(self):
        b = bundle(materials())
        n = b['notices'][0]
        attachment = b'%PDF joint fixture'
        url = n['attachments'][0]
        n['attachment_hashes'][url] = hashlib.sha256(attachment).hexdigest()
        captured, _ = self.capture(b, {n['url']: detail(n)}, review_scope='joint_originals')
        with patch.object(replay, 'kgrowth_attachment_text', return_value=OFFER):
            result = replay.replay_group(b, lambda sha: attachment, capture=captured, review_scope='joint_originals')
        self.assertTrue(result['raw_replay_complete'], result['holds'])
        self.assertFalse(result['publication_ready'])
        self.assertFalse(result['domestic_investment_approved'])
        self.assertEqual(result['review_scope'], 'joint_originals')
        for key, value in [('review_scope', 'pe_roster'), ('identity', {'fund': '다른 사업'}),
                           ('remaining_candidates', 999)]:
            changed = copy.deepcopy(captured)
            changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, '자동 선택'):
                replay.replay_group(b, lambda sha: attachment, capture=changed, review_scope='joint_originals')

    def test_joint_scope_rejects_unknown_empty_held_and_duplicate_candidates_before_http(self):
        for b, scope in [(bundle(materials()), 'arbitrary_id'), (iii(), 'joint_originals'),
                         (bundle(materials(OFFER.replace('3,100 5,000', '3,200 5,000'))), 'joint_originals'),
                         (bundle(materials(), notice('472', TITLE, '2021-04-01', BODY, OFFER)), 'joint_originals')]:
            with self.subTest(scope=scope), patch.object(replay, 'fetch_detail') as fetch:
                with self.assertRaises(ValueError):
                    replay.capture_details(b, fetch, checked_at=STAMP, review_scope=scope)
                fetch.assert_not_called()

    def test_pre_scope_pe_receipts_still_replay_without_recapture(self):
        b, raw, attachment = fixture()
        captured, _ = self.capture(b, raw)
        del captured['review_scope']
        del captured['remaining_candidates']
        text = next(iter(b['notices'][0]['attachment_texts'].values()))
        with patch.object(replay, 'kgrowth_attachment_text', return_value=text):
            result = replay.replay_group(b, lambda sha: attachment, capture=captured)
        self.assertTrue(result['raw_replay_complete'])

    def test_press_cli_preserves_one_raw_response_without_using_notice_identities(self):
        b, _, _ = fixture()
        raw = b'<html><body>Unparsed press board</body></html>'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, out = root/'bundle.json', root/'press.json'
            path.write_text(json.dumps(b))
            with patch.object(press, 'fetch_press_listing', return_value={
                    'raw': raw, 'http_status': 200, 'geturl': press.PRESS_LISTING_URL}) as fetch:
                self.assertEqual(replay.main(['--bundle', str(path), '--capture-details',
                                              '--review-scope', 'press_listing', '--out', str(out)]), 0)
            fetch.assert_called_once_with(press.PRESS_LISTING_URL)
            report = json.loads(out.read_text())
            self.assertEqual(report['kind'], press.KIND)
            self.assertEqual(report['context_bundle_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(base64.b64decode(report['raw_base64']), raw)
            self.assertFalse(report['parsed'])
            self.assertFalse(report['source_health_verified'])
            with self.assertRaises(ValueError):
                replay.replay_group(b, lambda sha: None, capture=report)

    def test_press_scope_never_weakens_the_existing_group_selector(self):
        b, _, _ = fixture()
        with self.assertRaisesRegex(ValueError, '범위'):
            replay.target_group(b, review_scope='press_listing')

    def test_press_listing_cannot_be_used_as_a_replayed_notice_or_overwrite_an_input(self):
        b, _, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path, out = Path(directory)/'bundle.json', Path(directory)/'out.json'
            path.write_text(json.dumps(b))
            with patch.object(press, 'fetch_press_listing') as fetch, self.assertRaises(SystemExit):
                replay.main(['--bundle', str(path), '--assets', directory,
                             '--review-scope', 'press_listing', '--out', str(out)])
            fetch.assert_not_called()
            self.assertFalse(out.exists())
            before = path.read_bytes()
            with self.assertRaises(SystemExit):
                replay.main(['--bundle', str(path), '--capture-details',
                             '--review-scope', 'press_listing', '--out', str(path)])
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
