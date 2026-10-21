import copy
import json
import unittest
from pathlib import Path

from services.lp.src.build_lp_contest_screening import ROOT, INPUTS, build, validate


class ScreeningContracts(unittest.TestCase):
    def setUp(self):
        self.rows = [row for group in INPUTS for row in json.loads(
            (ROOT/f'data/lp_blind_contest_screening_{group}.json').read_text())['institutions']]
        self.scope = json.loads((ROOT/'data/lp_blind_contest_scope.json').read_text())

    def test_reviewed_scope_is_complete_and_central_funds_are_not_duplicate_issuers(self):
        by_id = validate(self.rows, self.scope)
        self.assertEqual(len(self.scope['confirmed_institution_ids']), 17)
        self.assertIn('nps', self.scope['priority_verification_ids'])
        self.assertIn('kfcc', self.scope['confirmed_institution_ids'])
        self.assertNotIn('kfcc', self.scope['blocked_collector_ids'])
        self.assertIn('kfcc', self.scope['operating_collector_ids'])
        self.assertEqual(by_id['kfcc']['decision'], 'core_confirmed')
        self.assertNotEqual(by_id['moel_iaci']['issuer_name'], by_id['moel_iaci']['name'])
        self.assertEqual(by_id['noran_umbrella']['decision'], 'exclude_scope')

    def test_vc_wording_cannot_qualify_nps_as_blind_pe(self):
        rows = copy.deepcopy(self.rows)
        next(row for row in rows if row['institution_id']=='nps')['decision'] = 'core_confirmed'
        with self.assertRaisesRegex(ValueError, 'PE and blind'):
            validate(rows, self.scope)

    def test_aggregator_or_press_cannot_replace_issuer_evidence(self):
        for url, official in [('https://api.pe-vc-lp.com/att/notice.pdf', True),
                              ('https://example.com/news/pe-blind', False)]:
            rows = copy.deepcopy(self.rows)
            row = next(r for r in rows if r['institution_id']=='cu')
            row['evidence'] = [{**row['evidence'][0], 'url': url, 'official': official}]
            with self.assertRaises(ValueError):validate(rows, self.scope)

    def test_report_distinguishes_scope_from_working_collectors(self):
        _, markdown = build(self.rows, self.scope, {'issuers': []}, [{}]*133)
        self.assertIn('추가 연결 필요', markdown)
        self.assertIn('운영 연결', markdown)
        blocked = copy.deepcopy(self.scope)
        blocked['operating_collector_ids'].remove('kfcc')
        blocked['blocked_collector_ids'].append('kfcc')
        _, blocked_markdown = build(self.rows, blocked, {'issuers': []}, [])
        self.assertIn('접속 차단', blocked_markdown)
        self.assertIn('미확인은 공모를 하지 않는다는 뜻이 아니다', markdown)
        bad = copy.deepcopy(self.scope)
        bad['confirmed_institution_ids'].remove('cu')
        with self.assertRaises(ValueError):validate(self.rows, bad)


if __name__ == '__main__':unittest.main()
