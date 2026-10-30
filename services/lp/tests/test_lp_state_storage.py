import base64
import copy
import gzip
import hashlib
import json
import unittest
from unittest.mock import patch, Mock
from services.lp.src import lp_state_storage as s


class StateStorageTests(unittest.TestCase):
    def setUp(self):
        self.state = {'programs': [{'id': 'one', 'amount': 0}], 'review_outcomes': [False, None],
                      'other': '그대로', **{key: [{'body': '원문\\u0000\n' * 1000,
                        'zero': 0, 'flag': False, 'null': None}] for key in s.EVIDENCE_KEYS}}

    def test_legacy_roundtrip_sql_fields_and_idempotence(self):
        before = copy.deepcopy(self.state)
        packed = s.pack_state(self.state)
        self.assertEqual(s.unpack_state(self.state), before)
        self.assertEqual(self.state, before)
        self.assertEqual(s.unpack_state(packed), before)
        self.assertEqual(s.pack_state(packed), packed)
        self.assertEqual(s.unpack_state(s.unpack_state(packed)), before)
        self.assertEqual(packed['programs'], before['programs'])
        self.assertEqual(packed['review_outcomes'], before['review_outcomes'])
        self.assertLess(len(json.dumps(packed)), len(json.dumps(before)) / 5)
        packed['programs'][0]['amount'] = 7
        packed['review_outcomes'] = ['changed']
        restored = s.unpack_state(packed)
        self.assertEqual(restored['programs'][0]['amount'], 7)
        self.assertEqual(restored['review_outcomes'], ['changed'])
        for key in s.EVIDENCE_KEYS:
            self.assertEqual(restored[key], before[key])

    def test_all_evidence_value_types_remain_lossless(self):
        for value in [0, False, None, [], {}, '한국어', 1.5]:
            data = {'tracked_notices': value}
            self.assertEqual(s.unpack_state(s.pack_state(data)), data)

    def _with_raw(self, raw, blob=None):
        packed = s.pack_state(self.state)
        blob = gzip.compress(raw, mtime=0) if blob is None else blob
        packed[s.MARKER].update(raw_bytes=len(raw), raw_sha256=hashlib.sha256(raw).hexdigest(),
            gzip_bytes=len(blob), gzip_sha256=hashlib.sha256(blob).hexdigest(),
            payload=base64.b64encode(blob).decode())
        return packed

    def test_corruption_unknown_marker_overlap_and_bounds_fail_closed(self):
        packed = s.pack_state(self.state)
        for field, value in [('version', 2), ('version', True), ('codec', 'other'),
                             ('raw_sha256', '0' * 64), ('gzip_sha256', '0' * 64),
                             ('raw_bytes', 1), ('gzip_bytes', s.MAX_COMPRESSED_BYTES + 1),
                             ('payload', '!'), ('raw_bytes', s.MAX_RAW_BYTES + 1)]:
            bad = copy.deepcopy(packed); bad[s.MARKER][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                s.unpack_state(bad)
        bad = copy.deepcopy(packed); bad['tracked_notices'] = []
        with self.assertRaises(ValueError): s.unpack_state(bad)
        for bad in [{s.MARKER: None}, {s.MARKER: {}}, {'number': float('nan')}]:
            with self.assertRaises(ValueError): s.pack_state(bad)
        for raw in [b'{"programs":[]}', b'{"tracked_notices":NaN}',
                    b'{"tracked_notices":[],"tracked_notices":[]}', b'{}', b'[]']:
            with self.assertRaises(ValueError): s.unpack_state(self._with_raw(raw))
        raw = b'{"tracked_notices":[]}'
        for blob in [gzip.compress(raw) + gzip.compress(b'{}'), gzip.compress(raw)[:-1]]:
            with self.assertRaises(ValueError): s.unpack_state(self._with_raw(raw, blob))
        with patch.object(s, 'MAX_RAW_BYTES', 10), self.assertRaises(ValueError): s.pack_state(self.state)
        with patch.object(s, 'MAX_COMPRESSED_BYTES', 10), self.assertRaises(ValueError): s.pack_state(self.state)

    def test_sql_writer_only_packs_parameter_and_baseline_restores(self):
        from services.lp.tests.test_lp_program_publish import store_public_state
        from publish_lp_programs import baseline
        conn = Mock()
        before = copy.deepcopy(self.state)
        with patch('publish_lp_programs.publication_phase'):
            store_public_state(conn, self.state, {'index.html': 'unchanged'}, 'r')
        params = conn.execute.call_args.args[1]
        packed = json.loads(params[0])
        self.assertIn(s.MARKER, packed)
        self.assertEqual(self.state, before)
        conn.execute.return_value.fetchone.return_value = (packed,)
        conn.execute.return_value.fetchall.return_value = []
        hydrated = baseline(conn)
        self.assertEqual(hydrated, {**before, 'review_decisions': []})

    def test_next_prepare_preserves_previous_only_sources_and_review(self):
        from services.lp.tests.test_lp_program_publish import SRC, prepare
        from services.lp.tests.test_lp_notice_terms import official
        current = json.loads((SRC.parents[2] / 'data/lp_programs_pilot.json').read_text())
        program = next(p for p in current['programs'] if p['institution_id'] == 'kgrowth')
        report = {'checked_at': '2026-09-21', 'notices': [{'source_id': '1047', 'title': '공고',
            'date': '2026-09-21', 'body': '본문', 'url': 'https://www.kgrowth.or.kr/notice_view.asp?idx=1047'}],
            'programs': [copy.deepcopy(program)]}
        notice = official('운용방식: 국내 블라인드 PEF 공개모집', title='2026년 국내 신규전략 PEF 선정 공고')
        notice['sha256'] = 'a' * 64
        first_report = {**report, 'priority_sources': {'koreapost': {'notices': [notice], 'holds': []}}}
        previous, _ = prepare(current, first_report)
        expected, pages = prepare(previous, report)
        actual, actual_pages = prepare(s.unpack_state(s.pack_state(previous)), report)
        self.assertEqual(actual, expected)
        self.assertEqual(actual_pages, pages)
        self.assertIn(notice['url'], [n['url'] for n in actual['priority_notices']])


if __name__ == '__main__': unittest.main()
