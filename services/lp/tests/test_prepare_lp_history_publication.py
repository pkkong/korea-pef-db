import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services.lp.src import prepare_lp_history_publication as p
from services.lp.src import collect_lp_history_attachments as a
from services.lp.src import collect_lp_history_bodies as b
from services.lp.tests.test_collect_lp_history_attachments import fixture, attachment
from services.lp.tests.test_lp_ktcu_history_terms import TEXT
from publish_lp_programs import document_hash


def evidence():
    history, source_bodies = fixture()
    def fetch(url):
        n = next(n for n in source_bodies['documents'] if n['url'] == url)
        return ('<html><body><div class="notice-tit"><h3>'+n['title']+'</h3><span class="date">'+n['date']+
                '</span></div><div class="notice-cont">공식 모집 공고문을 첨부하오니 내용을 확인하고 제안서를 제출하시기 바랍니다.</div>'
                '<a href="/comm/getFile?srvcId=BBSTY1&amp;fileTy=ATTACH&amp;upperNo=abc&amp;fileNo='+n['source_id']+
                '">선정 공고문.hwpx</a></body></html>').encode()
    # One announcement link rather than a fixture's duplicate form/file URL.
    bodies = b.collect(history, None, fetch)
    report = a.collect(history, bodies, None, lambda url: attachment(
        TEXT if url.endswith('92') else TEXT.replace('2025', '2023').replace(
            '펀드 규모의 70% 이상을 국내 소재 기업에 투자', '운용사 사무소가 국내 소재')))
    return history, bodies, report


class Result:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows


class Connection:
    def __init__(self, docs):
        self.sql = []
        self.rows = [(n['url'], document_hash(n), copy.deepcopy(n)) for n in docs]
    def execute(self, sql, args=None):
        self.sql.append(sql)
        if sql.startswith('SELECT source_url,content_hash,document'):
            return Result(self.rows)
        if sql.startswith('SET '): return Result([])
        raise AssertionError('Unexpected SQL: '+sql)


class HistoricalPublicationPreparationTests(unittest.TestCase):
    def setUp(self):
        self.history, self.bodies, self.attachments = evidence()
        self.docs = p.verified_documents(self.history, self.bodies, self.attachments)
        self.current = json.loads((Path(__file__).resolve().parents[3] / 'data/lp_programs_pilot.json').read_text())
        self.current['review_decisions'] = [{'id': 7, 'private_note': 'preserve'}]

    def test_real_bytes_produce_one_program_and_explicit_domestic_scope_hold(self):
        before = copy.deepcopy((self.current, self.docs))
        after, result = p.proposal(self.current, self.docs, '2026-11-09T05:40:00+09:00')
        self.assertEqual((self.current, self.docs), before)
        self.assertEqual(len(result['new_programs']), 1)
        program = result['new_programs'][0]
        self.assertEqual(program['commitment_amount_krw'], 700_000_000_000)
        self.assertEqual(program['deadline'], '2025-04-04T15:00:00+09:00')
        self.assertEqual(program['selected_gps'], [])
        self.assertEqual(after['programs'][:-1], self.current['programs'])
        self.assertEqual(after['review_decisions'], self.current['review_decisions'])
        self.assertEqual(after['as_of'], self.current['as_of'])
        self.assertEqual(result['holds'][0]['reason'], 'Verified domestic PE blind recruitment required')
        self.assertEqual(program['checked_at'], self.docs[1]['checked_at'])
        again, second = p.proposal(after, self.docs, '2026-11-10T05:40:00+09:00')
        self.assertEqual(again, after)
        self.assertEqual(second['new_programs'], [])
        self.assertEqual(second['retained_program_ids'], [program['id']])

    def test_database_requires_exact_content_and_rejects_corruption_or_conflict(self):
        conn = Connection(self.docs)
        self.assertEqual(len(p.retained_documents(conn, self.docs)), 2)
        for change in ('missing', 'forged_key', 'body', 'attachment', 'bound'):
            conn = Connection(self.docs)
            if change == 'missing': conn.rows.pop()
            elif change == 'forged_key': conn.rows[0][2]['body'] = 'tampered'
            elif change == 'bound': conn.rows *= 51
            else:
                changed = copy.deepcopy(self.docs[0])
                if change == 'body': changed['sha256'] = 'a'*64
                else: changed['attachment_hashes'] = {u: 'a'*64 for u in changed['attachment_hashes']}
                conn.rows.append((changed['url'], document_hash(changed), changed))
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.retained_documents(conn, self.docs)

    def test_changed_proof_missing_file_or_saved_failure_never_reaches_database(self):
        for change in ('text', 'missing', 'failure', 'window', 'listing'):
            h, b, r = copy.deepcopy((self.history, self.bodies, self.attachments))
            if change == 'text': r['records'][0]['extracted']['text'] += 'forged'
            elif change == 'missing': r['records'].pop()
            elif change == 'failure': r['holds'].append({'error': 'saved failure'})
            elif change == 'window': h['window']['start'] = '2024-01-01'
            else: h['searches'].pop(next(iter(h['searches'])))
            with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                p.verified_documents(h, b, r)

    def test_conflicting_published_source_or_multiple_owners_are_not_merged(self):
        after, _ = p.proposal(self.current, self.docs, '2026-11-09T05:40:00+09:00')
        bad = copy.deepcopy(after)
        bad['priority_notices'][0]['body'] = 'changed source'
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            p.proposal(bad, self.docs, '2026-11-09T05:40:00+09:00')
        bad = copy.deepcopy(after)
        other = copy.deepcopy(bad['programs'][-1]); other['id'] += '-duplicate'
        bad['programs'].append(other)
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            p.proposal(bad, self.docs, '2026-11-09T05:40:00+09:00')
        with patch.object(p, 'publish_basic_notices', return_value=([], [])), self.assertRaisesRegex(ValueError, 'common publication'):
            p.proposal(self.current, self.docs, '2026-11-09T05:40:00+09:00')

    def test_preflight_builds_pages_in_read_only_snapshot_and_does_not_publish(self):
        conn = Connection(self.docs)
        revision = (('public-run', 'timestamp'), self.current['review_decisions'])
        with patch('publish_lp_programs.baseline', return_value=self.current), \
             patch('publish_lp_programs.publication_revision', return_value=revision):
            result = p.preflight(conn, self.history, self.bodies, self.attachments, '2026-11-09T05:40:00+09:00')
        self.assertEqual(conn.sql[0], 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        self.assertTrue(all(s.startswith(('SET ', 'SELECT ')) for s in conn.sql))
        self.assertFalse(result['published']); self.assertFalse(result['scheduled_success'])
        self.assertEqual(result['database_writes'], 0)
        self.assertEqual(result['official_http_requests'], 0)
        self.assertEqual(result['baseline_run_id'], 'public-run')
        self.assertGreater(result['built_pages'], result['programs_after'])
        self.assertNotIn('review_decisions', result)


if __name__ == '__main__':
    unittest.main()
