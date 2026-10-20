import copy
import json
import unittest
from html import escape
from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src.lp_notice_publication import publish_basic_notices
from services.lp.src.lp_program_detail import render_detail_body
from services.lp.tests.test_lp_board_adapter_kfcc import listing, detail
from services.lp.tests.test_lp_kfcc_notice_terms import BODY
from services.lp.tests.test_lp_board_adapters_banks import KDB_DATA, KDB_HTML

STAMP='2026-10-20T13:00:00+00:00'


class ThreeBoardCollectionTests(unittest.TestCase):
    def test_kfcc_publication_from_replayed_table_not_prepared_facts(self):
        config=boards.load_configs()['kfcc']
        html=''
        for line in BODY.splitlines():
            cells=line.split('\t')
            html += '<table><tr>'+''.join('<td>'+escape(c)+'</td>' for c in cells)+'</tr></table>' if len(cells)>1 else '<p>'+escape(line)+'</p>'
        def fetch(url, referer=None):
            return (detail(html) if 'Detail.do?' in url else listing()).encode()
        report=boards.collect({'kfcc':config},lambda c:fetch,STAMP)
        self.assertFalse(report['holds'])
        programs,holds=publish_basic_notices({'programs':[],'institution_notices':report['notices']},[],STAMP)
        self.assertFalse(holds)
        self.assertEqual(len(programs),1)
        p=programs[0]
        self.assertEqual(p['commitment_amount_krw'],440_000_000_000)
        self.assertEqual(len([s for s in p['schedule_stages'] if s['status']=='planned']),4)
        rendered=render_detail_body(p)
        self.assertIn('500~700억원',rendered)
        self.assertNotIn('700억원 이내',rendered)
        again,_=publish_basic_notices({'programs':programs,'institution_notices':report['notices']},[],STAMP)
        self.assertEqual([p['id'] for p in again],[p['id']])

    def test_json_listing_is_replayed_and_forged_receipt_rejected(self):
        config=boards.load_configs()['kdb']
        detail_html='<html>'+KDB_HTML[:KDB_HTML.index('<div class="fileList">')]+'</article></html>'
        def fetch(url, referer=None):
            return (json.dumps(KDB_DATA) if '/BOUBUF01R01.jct?' in url else detail_html).encode()
        report=boards.collect({'kdb':config},lambda c:fetch,STAMP)
        self.assertFalse(report['holds'])
        n=report['notices'][0]
        self.assertEqual(boards.validate_notice(n,STAMP),n)
        changed=copy.deepcopy(n)
        receipt=changed['discovery_provenance']['listing']
        data=json.loads(receipt['html']); data['STDLIST_REC'][0]['ITR_NAC_ID_MNG_SNO']='99999'
        receipt['html']=json.dumps(data);receipt['sha256']=boards.digest(receipt['html'])
        with self.assertRaises(ValueError):boards.validate_notice(changed,STAMP)
        programs,_=publish_basic_notices({'programs':[],'institution_notices':[n]},[],STAMP)
        self.assertFalse(programs,'bank legal-form permission alone does not prove PE blind scope')

    def test_bank_history_budget_is_explicit_and_not_an_id_allowlist(self):
        cfg=boards.load_configs()
        self.assertEqual(cfg['kdb']['history_years'],1)
        self.assertEqual(cfg['kdb']['max_details'],50)
        self.assertEqual(cfg['kfcc']['history_years'],4)
        for c in cfg.values():
            self.assertFalse(set(c)&{'notice_ids','source_ids','detail_urls'})


if __name__=='__main__':unittest.main()
