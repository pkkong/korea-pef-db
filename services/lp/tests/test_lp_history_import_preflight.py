"""An import must retain URLs, source versions, private notes and GP history."""
import copy
import hashlib
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, quote, urlsplit

from services.lp.src import lp_history_import_preflight as p
from services.lp.src import collect_lp_institution_history as history
from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src.lp_history_notices import KIND
from services.lp.src.lp_state_storage import pack_state
from services.lp.tests.test_lp_kbiz_notice_terms import historical_notice
from services.lp.tests.test_lp_board_adapter_kbiz import HTML, DETAIL

STAMP = '2026-11-17T00:00:00+00:00'


def payload_fixture(body_extra=''):
    n = historical_notice(2020)
    n['body'] += body_extra
    listing = HTML.replace('국내 PE 펀드 모집', n['title']).replace('2026.07.10', '2020.07.30')
    detail = DETAIL.replace('[사업공고] 국내 펀드 모집', n['title']).replace('2026.07.10', '2020.07.30')
    start, end = detail.index('<div class="file-wrap">'), detail.index('<div class="detail-body">')
    detail = detail[:start] + detail[end:]
    start, end = detail.index('<div class="detail-body">'), detail.index('<div class="navigation">')
    detail = detail[:start] + '<div class="detail-body">' + n['body'] + '</div>' + detail[end:]
    config = {**boards.load_configs()['kbiz'], 'searches': ['PE'], 'pages': 1}
    def fetch(url, referer=None):
        if 'view.do?' in url:
            return detail.encode()
        term = parse_qs(urlsplit(url).query, keep_blank_values=True)['schTxt'][0]
        return listing.replace('value="PE"', f'value="{term}"').replace('schTxt=PE', 'schTxt=' + quote(term)).encode()
    with patch.object(boards, 'load_configs', return_value={'kbiz': config}):
        b = history.collect('kbiz', '2020-01-01', '2026-11-17', max_pages=2, page_budget=4,
                            fetch_factory=lambda c: fetch, checked_at=STAMP)
    assert len(b['notices']) == 1, (b['listing'], b['holds'])
    raw = b['notices'][0]
    raw['attachment_bytes'] = {}
    raw['history_import'] = KIND
    return {'kind': 'lp_history_import_v1', 'checked_at': STAMP, 'notices': [raw]}


def current_fixture(payload):
    empty = {'as_of': '2026-11-17', 'programs': []}
    added, _ = p.proposal(empty, payload, STAMP)
    old = copy.deepcopy(added['programs'][0])
    result_url = 'https://www.kbiz.or.kr/ko/contents/bbs/view.do?seq=999&topFixYn=N&mnSeq=211'
    old.update(id='existing-2026', source_program_key='kbiz:2026:existing', title='기존 사업',
               status='선정 완료', events=[{'type': '모집 공고', 'date': '2026-07-01',
                                        'title': '기존 모집', 'url': result_url + '&offer=1'},
                                       {'type': '선정 결과', 'date': '2026-09-01',
                                        'title': '기존 결과', 'url': result_url}],
               selected_gps=[{'id': 'existing-gp', 'name': '기존파트너스', 'asset_scope': 'PE', 'source_url': result_url}],
               preferred_gps=['기존파트너스'], manager_list_sources={'preferred_gps': result_url + '&preferred=1'})
    old['events'].append({'type': '우선협상대상자', 'date': '2026-08-01', 'title': '기존 우선협상',
                          'url': result_url + '&preferred=1'})
    return {'as_of': '2026-11-17', 'programs': [old], 'program_aliases': {'retired-2026': old['id']},
            'review_decisions': [{'id': 7, 'private_note': 'DO_NOT_EXPORT'}],
            'institution_notices': [{'keep': 'original evidence bytes'}],
            'history_notice_holds': [{'keep': 'existing hold'}], 'other_metadata': {'a': 0}}


class Rows:
    def __init__(self, values): self.values = values
    def fetchone(self): return self.values[0] if self.values else None
    def fetchall(self): return self.values


class ReadConnection:
    def __init__(self, current, readonly=True, present=True):
        self.current, self.readonly, self.present, self.sql = current, readonly, present, []
    def execute(self, sql):
        self.sql.append(sql)
        if sql.startswith('SET '): return Rows([])
        if sql == 'SHOW transaction_read_only': return Rows([('on' if self.readonly else 'off',)])
        if sql.startswith('SELECT data,run_id,updated_at'):
            return Rows([(pack_state(self.current), 'baseline-run', datetime(2026, 11, 17, tzinfo=timezone.utc))]
                        if self.present else [])
        if sql.startswith('SELECT to_jsonb(d)'): return Rows([(d,) for d in self.current['review_decisions']])
        raise AssertionError('Write or unexpected query: ' + sql)


class ImportPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.payload = payload_fixture()

    def setUp(self):
        self.payload = copy.deepcopy(type(self).payload)
        self.current = current_fixture(self.payload)

    def test_real_validated_receipt_adds_only_one_pe_recruitment(self):
        before = copy.deepcopy((self.current, self.payload))
        after, report = p.proposal(self.current, self.payload, STAMP)
        self.assertEqual((self.current, self.payload), before)
        self.assertEqual(after['programs'][:-1], self.current['programs'])
        new = after['programs'][-1]
        self.assertEqual(new['commitment_amount_krw'], 2000*10**8)
        self.assertEqual(new['manager_count'], 6)
        self.assertEqual(new['deadline'], '2020-08-13T17:00:00+09:00')
        self.assertEqual(new['selected_gps'], [])
        self.assertEqual(new['checked_at'], self.payload['notices'][0]['checked_at'])
        self.assertTrue(report['storage_roundtrip_verified'])
        for key in set(self.current) - {'programs', 'history_notices'}:
            self.assertEqual(after[key], self.current[key])
        self.assertNotIn('DO_NOT_EXPORT', json.dumps(report))

    def test_same_import_is_idempotent_and_retains_original_gp_and_receipt(self):
        after, _ = p.proposal(self.current, self.payload, STAMP)
        again, report = p.proposal(after, self.payload, STAMP)
        self.assertEqual(again, after)
        self.assertEqual(report['new_programs'], [])
        self.assertEqual(len(report['reused_program_ids']), 1)
        self.assertEqual(again['programs'][0]['selected_gps'], self.current['programs'][0]['selected_gps'])

    def test_alias_or_unrelated_program_id_collision_fails(self):
        new = p.proposal(self.current, self.payload, STAMP)[0]['programs'][-1]
        for collision in ('alias', 'program'):
            current = copy.deepcopy(self.current)
            if collision == 'alias': current['program_aliases'][new['id']] = current['programs'][0]['id']
            else: current['programs'][0]['id'] = new['id']
            with self.subTest(collision=collision), self.assertRaises(ValueError):
                p.proposal(current, self.payload, STAMP)

    def test_existing_source_owner_or_multiple_program_match_is_rejected(self):
        url = self.payload['notices'][0]['url']
        for collision in ('institution', 'multiple'):
            current = copy.deepcopy(self.current)
            current['programs'][0]['events'][0]['url'] = url
            if collision == 'institution': current['programs'][0]['institution_id'] = 'mmaa'
            else:
                duplicate = copy.deepcopy(current['programs'][0]); duplicate['id'] = 'other-existing'
                current['programs'].append(duplicate)
            with self.subTest(collision=collision), self.assertRaises(ValueError):
                p.proposal(current, self.payload, STAMP)

    def test_duplicate_or_corrupt_source_never_enters_catalog(self):
        for bad in ('duplicate', 'body', 'retained'):
            payload, current = copy.deepcopy(self.payload), copy.deepcopy(self.current)
            if bad == 'duplicate': payload['notices'].append(copy.deepcopy(payload['notices'][0]))
            elif bad == 'body': payload['notices'][0]['body'] += '변경'
            else:
                current['history_notices'] = copy.deepcopy(payload['notices'])
                current['history_notices'][0]['body'] += '변경'
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                p.proposal(current, payload, STAMP)

    def test_a_different_valid_source_version_in_any_catalog_blocks_import(self):
        changed = payload_fixture(' 공식 본문에 추가된 안내입니다.')['notices'][0]
        self.assertNotEqual(changed['sha256'], self.payload['notices'][0]['sha256'])
        for catalog in ('institution_notices', 'accepted_notices', 'supporting_notices', 'nested_original'):
            current = copy.deepcopy(self.current)
            if catalog == 'nested_original':
                current['shared_notices'] = [{'url': 'https://example.com/repost', 'original_notices': [changed]}]
            else:
                current[catalog] = [changed]
            before = copy.deepcopy(current)
            with self.subTest(catalog=catalog), self.assertRaisesRegex(ValueError, '버전 충돌'):
                p.proposal(current, self.payload, STAMP)
            self.assertEqual(current, before)

    def test_pinned_digest_bounded_payload_and_timestamp_are_required(self):
        raw = json.dumps(self.payload, ensure_ascii=False).encode()
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(p.load_import(raw, digest), self.payload)
        with self.assertRaises(ValueError): p.load_import(raw + b' ', digest)
        for key, value in [('notices', []), ('notices', self.payload['notices'] * 6),
                           ('kind', 'unapproved'), ('checked_at', '2099-01-01T00:00:00Z'),
                           ('checked_at', '2026-11-17T00:00:00')]:
            bad = {**self.payload, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                p.proposal(self.current, bad, STAMP)

    def test_preservation_guard_detects_hidden_field_gp_source_and_alias_mutation(self):
        current = copy.deepcopy(self.current)
        current['history_notices'] = copy.deepcopy(self.payload['notices'])
        after, _ = p.proposal(current, self.payload, STAMP)
        for field in ('metadata', 'gp', 'alias', 'as_of', 'receipt'):
            bad = copy.deepcopy(after)
            if field == 'metadata': bad['other_metadata']['a'] = 1
            elif field == 'gp': bad['programs'][0]['selected_gps'][0]['source_url'] += '&changed=1'
            elif field == 'alias': bad['program_aliases'] = {}
            elif field == 'as_of': bad['as_of'] = '2026-11-18'
            else: bad['history_notices'] = []
            with self.subTest(field=field), self.assertRaises(ValueError):
                p._assert_preserved(current, bad)

    def test_database_preflight_sets_readonly_before_select_and_never_exports_old_notes(self):
        conn = ReadConnection(self.current)
        with patch.object(p, 'build', return_value={'public_notice_context': {'notices': []}}) as render:
            result = p.preflight(conn, self.payload, STAMP)
        self.assertEqual(conn.sql[0], 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        self.assertTrue(all(q.startswith(('SET ', 'SHOW ', 'SELECT ')) for q in conn.sql))
        self.assertEqual(result['baseline_run_id'], 'baseline-run')
        self.assertEqual(result['database_writes'], 0)
        self.assertFalse(result['published'])
        self.assertTrue(result['existing_gp_context_preserved'])
        self.assertTrue(result['approval_required'])
        self.assertNotIn('DO_NOT_EXPORT', json.dumps(result))
        render.assert_called_once()

    def test_readonly_preflight_reports_changed_existing_gp_display_context(self):
        before = {'noticeId': self.current['programs'][0]['id'], 'title': '기존 사업 이름 (재)'}
        after = {**before, 'title': '기존 사업 이름 재공고'}
        added = {'noticeId': p.proposal(self.current, self.payload, STAMP)[0]['programs'][-1]['id'],
                 'title': '새 사업'}
        self.current['public_notice_context'] = {'notices': [before]}
        for title_row, expected in ((before, True), (after, False)):
            with self.subTest(preserved=expected), patch.object(
                    p, 'build', return_value={'public_notice_context': {'notices': [added, title_row]}}):
                result = p.preflight(ReadConnection(self.current), self.payload, STAMP)
                self.assertIs(result['existing_gp_context_preserved'], expected)
                self.assertEqual(result['database_writes'], 0)
                self.assertFalse(result['published'])

    def test_missing_database_or_nonreadonly_transaction_cannot_use_a_pilot_baseline(self):
        for conn in (ReadConnection(self.current, readonly=False), ReadConnection(self.current, present=False)):
            with self.assertRaises(ValueError), patch.object(p, 'build') as render:
                p.preflight(conn, self.payload, STAMP)
            render.assert_not_called()

    def test_actual_pages_and_alias_build_never_fetch_a_sibling_or_asset(self):
        with patch.dict(os.environ, {'NEWSLETTER_SKIP_BRAND_ASSET_DOWNLOADS': '1'}), \
                patch('socket.socket.connect', side_effect=AssertionError('Unexpected network')) as network:
            result = p.preflight(ReadConnection(self.current), self.payload, STAMP)
        network.assert_not_called()
        self.assertGreaterEqual(result['built_pages'], 6)
        self.assertGreater(result['pages_bytes'], 0)
        self.assertEqual(result['programs_after'], 2)

    def test_storage_bound_failure_never_changes_the_baseline(self):
        original = copy.deepcopy(self.current)
        with patch('services.lp.src.lp_state_storage.MAX_RAW_BYTES', 100), self.assertRaises(ValueError):
            p.proposal(self.current, self.payload, STAMP)
        self.assertEqual(self.current, original)

    def test_rebuild_keeps_different_programs_on_same_day_and_rejects_duplicates(self):
        n = copy.deepcopy(self.payload['notices'][0])
        listing = n['discovery_provenance']['listing']
        n['discovery_provenance']['listing'] = {k: listing[k] for k in ('url', 'sha256')}
        bundle = {'kind': 'lp_institution_history_v1', 'institution_id': 'kbiz',
                  'notices': [n], 'listing_receipts': {listing['sha256']: listing}}
        raw = json.dumps(self.payload, ensure_ascii=False, sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()
        existing = copy.deepcopy(self.current['programs'][0])
        existing['events'][1]['date'] = n['date']
        rebuilt, candidate, summary = p.build_pinned_import(bundle, [existing], STAMP, digest)
        self.assertEqual(candidate, raw)
        self.assertEqual(rebuilt, self.payload)
        self.assertEqual(summary['programs_imported'], 1)
        after, _ = p.proposal(self.current, self.payload, STAMP)
        duplicate = after['programs'][-1]
        for old in ({**existing, 'source_program_key': duplicate['source_program_key']},
                    {**duplicate, 'source_program_key': existing['source_program_key']}):
            with self.assertRaisesRegex(ValueError, '지문 불일치'):
                p.build_pinned_import(bundle, [old], STAMP, digest)

    def test_cli_never_overwrites_an_input_or_a_previous_result(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / 'source.json'
            raw = json.dumps(self.payload).encode()
            original.write_bytes(raw)
            with self.assertRaises(SystemExit):
                p.main(['--import-file', str(original), '--sha256', hashlib.sha256(raw).hexdigest(),
                        '--output', str(original)])
            self.assertEqual(original.read_bytes(), raw)


if __name__ == '__main__': unittest.main()
