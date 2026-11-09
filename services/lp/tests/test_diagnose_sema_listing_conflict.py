import base64
import copy
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError

from services.lp.src import diagnose_sema_listing_conflict as d
from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src import collect_lp_original_notices as original
from services.lp.tests.test_lp_board_adapter_sema import listing, TITLE


def parent():
    config = boards.load_configs()['sema']
    url = next(u for u in boards.listing_urls(config) if parse_qs(urlsplit(u).query)['searchWrd'] == ['위탁운용사'])
    return {'checked_at': '2026-11-09T01:50:46+00:00', 'notices': [], 'coverage': {},
            'holds': [{'institution_id': 'sema', 'stage': 'institution_listing',
                       'url': url, 'error': d.CONFLICT}]}


def duplicate_html(url, *, title=None, stamp=None, second_id=True):
    html = listing(url)
    row = re.search(r'<tr><td>1</td>.*?</tr>', html).group()
    pin = row.replace('<td>1</td>', '<td>공지</td>', 1)
    if title is not None: pin = pin.replace(TITLE, title)
    if stamp is not None: pin = pin.replace('2026-08-14', stamp)
    other = row.replace('990001', '990002') if second_id else ''
    return html.replace(row, pin + row + other)


class SemaConflictDiagnosticTests(unittest.TestCase):
    def test_raw_receipt_is_checkpointed_before_unchanged_parser_failure(self):
        source = parent(); url = source['holds'][0]['url']; raw = duplicate_html(url, title=TITLE + ' 변경').encode()
        before = copy.deepcopy(source); calls = []; checkpoints = []
        real_parser = d.sema.parse_listing
        def parse(*args, **kwargs):
            self.assertTrue(checkpoints)
            return real_parser(*args, **kwargs)
        with patch.object(d.sema, 'parse_listing', side_effect=parse):
            result = d.diagnose(source, lambda u: calls.append(u) or raw,
                                on_receipt=lambda r: checkpoints.append(r))
        self.assertEqual(calls, [url]); self.assertEqual(source, before)
        self.assertEqual(checkpoints[0]['parser'], {'status': 'not_attempted'})
        self.assertEqual(base64.b64decode(checkpoints[0]['response']['raw_base64']), raw)
        self.assertFalse(result['success'])
        self.assertEqual(result['parser']['error_code'], 'conflicting_duplicate_notice')
        self.assertEqual(result['logical_requests'], 1)
        self.assertEqual(result['transport_attempts'], 'not_measured')
        self.assertEqual(d.verify(result, source), result['parser'])
        self.assertFalse(result['previous_failure_resolved']); self.assertFalse(result['published'])
        self.assertEqual(result['database_writes'], 0)

    def test_occurrences_keep_other_id_and_actual_pin_url_title_date_differences(self):
        source = parent(); url = source['holds'][0]['url']
        for changes, fields in (({'title': TITLE + ' 변경'}, ['title', 'pinned']),
                                ({'stamp': '2026-08-15'}, ['date', 'pinned'])):
            raw = duplicate_html(url, **changes).encode()
            result = d.diagnose(source, lambda u: raw)
            analysis = result['parser']['occurrence_analysis']
            with self.subTest(changes=changes):
                self.assertEqual(analysis['source_data_rows'], 3)
                self.assertEqual(len(analysis['occurrences']), 3)
                self.assertEqual({r['source_id'] for r in analysis['occurrences']}, {'sema:990001', 'sema:990002'})
                self.assertEqual(analysis['duplicates'][0]['differing_fields'], fields)
                self.assertEqual(len(analysis['duplicates'][0]['occurrences']), 2)
                self.assertFalse(result['success'])
                d.verify(result, source)

    def test_pin_only_duplicate_now_parses_once_without_repairing_original_parent(self):
        source = parent(); url = source['holds'][0]['url']
        result = d.diagnose(source, lambda u: duplicate_html(url).encode())
        self.assertTrue(result['success'])
        rows = result['parser']['rows']
        self.assertEqual([r['source_id'] for r in rows], ['sema:990001', 'sema:990002'])
        self.assertTrue(rows[0]['pinned']); self.assertFalse(rows[1]['pinned'])
        self.assertFalse(result['previous_failure_resolved'])
        self.assertEqual(d.verify(result, source), result['parser'])

    def test_invalid_or_multiple_failures_and_unregistered_queries_never_fetch(self):
        source = parent(); url = source['holds'][0]['url']
        variants = []
        for changes in ({'error': 'different error'}, {'stage': 'institution_detail'}, {'institution_id': 'other'}):
            bad = copy.deepcopy(source); bad['holds'][0].update(changes); variants.append(bad)
        bad = copy.deepcopy(source); bad['holds'] *= 2; variants.append(bad)
        for target in (url.replace('https:', 'http:'), url.replace('www.sema.or.kr', 'evil.example'),
                       url.replace('www.sema.or.kr', 'user@www.sema.or.kr'), url + '&extra=1',
                       url + '&pageIndex=1', url.replace('pageIndex=1', 'pageIndex=11'),
                       url.replace('B0000022', 'B0000024'), url.replace('searchCnd=1', 'searchCnd=2')):
            bad = copy.deepcopy(source); bad['holds'][0]['url'] = target; variants.append(bad)
        for bad in variants:
            result = d.diagnose(bad, lambda u: self.fail('unregistered request fetched'))
            self.assertFalse(result['success']); self.assertEqual(result['logical_requests'], 0)
        with patch.object(d, 'MAX_INPUT_BYTES', 2):
            result = d.diagnose(source, lambda u: self.fail('oversized input fetched'))
        self.assertEqual(result['logical_requests'], 0)

    def test_normal_and_confirmed_empty_replay_never_claim_parent_recovery(self):
        source = parent(); url = source['holds'][0]['url']
        for raw in (listing(url).encode(), listing(url, empty=True).encode()):
            result = d.diagnose(source, lambda u: raw)
            self.assertTrue(result['success']); self.assertEqual(result['parser']['status'], 'parsed')
            self.assertFalse(result['previous_failure_resolved']); self.assertFalse(result['audit_recovered'])
            self.assertFalse(result['pe_approval']); self.assertFalse(result['selected_gp_approval'])
            self.assertEqual(d.verify(result, source), result['parser'])
        empty = d.diagnose(source, lambda u: listing(url, empty=True).encode())
        self.assertTrue(empty['parser']['confirmed_empty']); self.assertEqual(empty['parser']['rows'], [])

    def test_homepage_protection_bad_search_echo_and_empty_bytes_remain_failures(self):
        source = parent(); url = source['holds'][0]['url']
        for raw in (b'', b'<html>homepage</html>', '<html>로그인이 필요합니다</html>'.encode(),
                    listing(url).replace('value="위탁운용사"', 'value="출자"').encode(),
                    b'<html>partial'):
            result = d.diagnose(source, lambda u: raw)
            self.assertFalse(result['success']); self.assertEqual(result['logical_requests'], 1)
            self.assertEqual(base64.b64decode(result['response']['raw_base64']), raw)
            self.assertEqual(d.verify(result, source), result['parser'])

    def test_raw_hash_parent_parser_and_approval_tamper_are_detected_offline(self):
        source = parent(); url = source['holds'][0]['url']
        result = d.diagnose(source, lambda u: duplicate_html(url, title=TITLE + ' 변경').encode())
        for key in ('hash', 'raw', 'parent', 'parser', 'claim', 'requests', 'response_url'):
            bad = copy.deepcopy(result)
            if key == 'hash': bad['response']['sha256'] = '0' * 64
            elif key == 'raw': bad['response']['raw_base64'] = base64.b64encode(b'<html>forged</html>').decode()
            elif key == 'parent': bad['parent_report_sha256'] = '0' * 64
            elif key == 'parser': bad['parser']['occurrence_analysis']['duplicates'][0]['differing_fields'] = []
            elif key == 'claim': bad['previous_failure_resolved'] = True
            elif key == 'requests': bad['logical_requests'] = 2
            else: bad['response']['url'] = url + '&other=1'
            with self.subTest(key=key), self.assertRaises(ValueError): d.verify(bad, source)
        changed_parent = copy.deepcopy(source); changed_parent['checked_at'] += 'changed'
        with self.assertRaises(ValueError): d.verify(result, changed_parent)

    def test_oversized_raw_is_bounded_and_never_parsed(self):
        source = parent(); raw = b'raw response longer than eight bytes'
        with patch.object(d, 'MAX_RESPONSE_BYTES', 8), patch.object(d.sema, 'parse_listing') as parser:
            result = d.diagnose(source, lambda u: raw)
            self.assertFalse(result['success']); parser.assert_not_called()
            self.assertEqual(base64.b64decode(result['response']['raw_base64']), raw[:8])
            self.assertTrue(result['response']['truncated'])
            self.assertEqual(d.verify(result, source)['error_code'], 'response_size_limit')

    def test_existing_session_is_reused_once_with_original_referer_and_no_external_redirect(self):
        source = parent(); url = source['holds'][0]['url']; config = boards.load_configs()['sema']
        with patch.object(d.boards, 'Session') as session:
            session.return_value.return_value = listing(url).encode()
            result = d.diagnose(source)
            self.assertTrue(result['success']); session.assert_called_once_with(config)
            session.return_value.assert_called_once_with(url, config['listing_url'])
        with self.assertRaises(ValueError):
            original.OfficialRedirect({'sema.or.kr'}).redirect_request(None, None, 302, '', {}, 'https://evil.example/')
        calls = []
        def fail(u):
            calls.append(u)
            raise TimeoutError('Cookie: SECRET')
        result = d.diagnose(source, fail)
        self.assertEqual(calls, [url]); self.assertFalse(result['success'])
        self.assertNotIn('SECRET', json.dumps(result)); self.assertIsNone(result['response'])
        self.assertEqual(d.verify(result, source), {'status': 'not_attempted'})

    def test_rejected_http_response_is_retained_and_not_parsed_or_retried(self):
        source = parent(); url = source['holds'][0]['url']; calls = []
        raw = '<html>로그인이 필요합니다</html>'.encode()
        def denied(target):
            calls.append(target)
            raise HTTPError(target, 403, 'Cookie: SECRET', {'Set-Cookie': 'SECRET'}, io.BytesIO(raw))
        result = d.diagnose(source, denied)
        self.assertEqual(calls, [url]); self.assertFalse(result['success'])
        self.assertEqual(base64.b64decode(result['response']['raw_base64']), raw)
        self.assertEqual(result['parser'], {'status': 'not_parsed', 'error_code': 'http_error', 'http_status': 403})
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertEqual(d.verify(result, source), result['parser'])

    def test_cli_saves_receipt_then_failure_result_and_exit_code_without_network(self):
        source = parent(); raw = duplicate_html(source['holds'][0]['url'], title=TITLE + ' 변경').encode()
        real = d.diagnose
        with tempfile.TemporaryDirectory() as folder:
            collection = Path(folder) / 'collection.json'; collection.write_text(json.dumps(source))
            output = Path(folder) / 'diagnostic'
            checkpoint_seen = []
            def diagnose(report, **kwargs):
                callback = kwargs['on_receipt']
                def checkpoint(result):
                    callback(result)
                    saved = json.loads((output / 'listing-conflict.json').read_text())
                    checkpoint_seen.append(saved['parser']['status'])
                return real(report, lambda u: raw, on_receipt=checkpoint)
            with patch('sys.argv', ['diagnostic', '--collection', str(collection), '--output-dir', str(output)]), \
                 patch.object(d, 'diagnose', side_effect=diagnose), patch('sys.stdout', new=io.StringIO()):
                self.assertEqual(d.main(), 1)
            result = json.loads((output / 'listing-conflict.json').read_text())
            self.assertEqual(checkpoint_seen, ['not_attempted'])
            self.assertEqual(result['parser']['error_code'], 'conflicting_duplicate_notice')
            self.assertEqual(d.verify(result, source), result['parser'])


if __name__ == '__main__':
    unittest.main()
