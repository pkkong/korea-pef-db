import base64
import copy
import unittest
from unittest.mock import patch

from services.lp.src import diagnose_lp_inventory_failures as probe
from services.lp.src import merge_lp_inventory_recovery as merger
from services.lp.tests.test_diagnose_lp_inventory_failures import paginated_saved
from services.lp.tests.test_lp_board_adapter_nh import fixture


def inputs():
    report, old = paginated_saved()
    report['institutions'][0].update(name='NH', role='verification', rows=[], counts={})
    report['institutions'].append({'institution_id': 'kgrowth', 'name': 'Growth', 'role': 'confirmed',
        'status': 'observed_query_boundary', 'counts': {'observed_recent_rows': 1},
        'queries': [{'pages': [1], 'boundary': 'observed_final_page'}],
        'rows': [{'source_id': 'kgrowth:1', 'relevant': True, 'disposition': 'not_in_archive',
                  'title_scope': 'outside_policy'}]})
    report['receipts'].append({'institution_id': 'kgrowth', 'url': 'https://www.kgrowth.or.kr/notice.asp',
                              'html': 'original other receipt', 'sha256': 'original-hash'})
    report['summary'] = {'institutions': 2, 'audited': 2, 'unconnected': 0, 'unmeasured': 0,
        'pages': 2, 'requests': 9, 'source_errors': 7, 'limited_institutions': [],
        'independent_unavailable': [], 'unarchived_relevant': 1}
    cache = {r['url']: base64.b64decode(r['raw_base64']) for r in old['results']}
    diagnostic = None
    for _ in range(4): diagnostic = probe.diagnose(report, fetch=lambda u: cache[u], resume=diagnostic)
    recovery = probe.recover_boundaries(report, diagnostic, fetch=lambda _: fixture(
        'bid', page=2, total=11, term='펀드').replace('2099.03.04', '2026.10.12').encode())
    identities = {'kind': 'lp_nh_retained_identity_index_v1', 'complete': True, 'read_only': True,
        'checked_at': '2026-11-09T00:00:00+00:00', 'public_run': 'existing-public-run',
        'retained_keys': ['nh_central:bid:90011'], 'public_keys': ['nh_central:bid:90001']}
    return report, recovery, identities


class InventoryMergeTests(unittest.TestCase):
    def test_only_nh_is_reclassified_other_entries_indexes_and_receipts_are_preserved(self):
        report, recovery, identities = inputs(); before = copy.deepcopy(report)
        with patch.object(probe.inventory.boards, 'Session', side_effect=AssertionError('no official HTTP')):
            result = merger.merge(report, recovery, identities)
        self.assertEqual(report, before)
        self.assertEqual(result['institutions'][1], before['institutions'][1])
        self.assertEqual(result['receipts'][:2], before['receipts'])
        entry = result['institutions'][0]
        rows = {r['source_id']: r for r in entry['rows']}
        self.assertEqual(rows['nh_central:bid:90011']['disposition'], 'archived_unpublished')
        self.assertEqual(rows['nh_central:bid:90001']['disposition'], 'public_linked')
        self.assertEqual(rows['nh_central:bid:90002']['disposition'], 'not_in_archive')
        self.assertFalse(result['holds'])
        self.assertEqual(result['listing_recovery']['original_holds'], before['holds'])
        self.assertEqual(result['listing_recovery']['original_summary'], before['summary'])
        self.assertFalse(result['listing_recovery']['scheduled_success'])
        self.assertEqual(result['summary']['new_official_http_requests'], 0)
        self.assertEqual(result['summary']['pages'], len(result['receipts']))
        for query in entry['queries']:
            self.assertTrue(all(result['receipts'][i]['institution_id'] == 'nh_central' for i in query['pages']))

    def test_missing_or_foreign_identity_index_is_not_treated_as_empty_archive(self):
        report, recovery, identities = inputs()
        for change in ({'complete': False}, {'read_only': False}, {'retained_keys': ['other:1']},
                       {'public_run': None}, {'retained_keys': None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                merger.merge(report, recovery, {**identities, **change})

    def test_identity_export_starts_read_only_and_rejects_unknown_retained_routes(self):
        class Connection:
            def __init__(self, urls): self.urls = urls; self.statements = []
            def execute(self, sql, params=None): self.statements.append(sql); return self
            def fetchone(self): return ({'programs': []}, 'current-run')
            def fetchall(self): return [(u,) for u in self.urls]
        valid = 'https://www.nonghyup.com/ecenter/bid/bidView.do?intgBsnBlbdGrpC=BBSMSTR_000000000019&blbdSqno=123'
        conn = Connection([valid]); index = merger.read_identity_index(conn)
        self.assertEqual(index['retained_keys'], ['nh_central:bid:123'])
        self.assertTrue(conn.statements[0].endswith('REPEATABLE READ READ ONLY'))
        self.assertTrue(all(s.startswith(('SET ', 'SELECT ')) for s in conn.statements))
        with self.assertRaises(ValueError): merger.read_identity_index(Connection(['https://evil.invalid/']))


if __name__ == '__main__': unittest.main()
