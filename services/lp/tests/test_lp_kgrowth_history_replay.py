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
from services.lp.tests.test_lp_kgrowth_history_terms import iii

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


if __name__ == '__main__':
    unittest.main()
