"""End-to-end replay and transport boundaries for unfiltered official boards."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit
from services.lp.src import collect_lp_institution_boards as b
from services.lp.src import audit_lp_official_inventory as audit
from services.lp.src.lp_notice_publication import publish_basic_notices
from services.lp.tests import test_lp_board_adapter_nps as n
from services.lp.tests import test_lp_board_adapter_cwma as c

STAMP='2099-03-05T00:00:00+00:00'

class PendingCollectionTests(unittest.TestCase):
    def test_nps_discovery_and_byte_replay_excludes_vc_historical_pe(self):
        config=dict(b.load_configs()['nps'])
        body='투자기구 및 선정대상: 벤처투자조합, 신기술사업투자조합. '+('벤처펀드 모집 조건. '*30)+'\n직전 기금펀드 PEF 이력은 제외'
        html=n.detail().replace('국내 사모투자 모집','2099년 국내 사모투자 모집')
        calls=[]
        def fetch(url,referer=None):
            calls.append(url)
            if url==b.nps.SCRIPT:return n.SCRIPT.encode()
            if 'fileDown.do?' in url:return b'%PDF-scan'
            return (html if 'getOHEF0018M0.do' in url else n.listing()).encode()
        with patch.object(b,'extract_attachment',return_value={'format':'pdf','text':'watermark\nwatermark'}),patch.object(b,'recognize_pdf',return_value={'pages':[{'text':body}]}):
            result=b.collect({'nps':config},lambda _:fetch,STAMP)
            self.assertEqual(result['holds'],[])
            self.assertEqual(len(result['notices']),1)
            notice=result['notices'][0]
            self.assertEqual(b.validate_notice(notice,STAMP),notice)
            self.assertIn(body,list(notice['attachment_texts'].values()))
            programs,_=publish_basic_notices({'programs':[],'institution_notices':[notice]},[],STAMP)
            self.assertEqual(programs,[])
            forged=copy.deepcopy(notice);forged['attachment_texts'][next(iter(forged['attachment_texts']))]='domestic PE blind invented'
            with self.assertRaisesRegex(ValueError,'does not match'):b.validate_notice(forged,STAMP)
        self.assertEqual(len([u for u in calls if b.nps.DETAIL in u]),1)

    def test_cwma_unfiltered_discovery_old_boundary_and_proof(self):
        config=b.load_configs()['cwma'];calls=[]
        listing=c.listing(1,total=1).replace("'248',2", "'248',1").replace('2099년도 국내 사모 및 벤처펀드','국내 사모 및 벤처펀드 모집').replace('2099-02-03','2099-03-04')
        html=c.detail().replace('새 공고문.hwp','제안서 양식.hwp')
        def fetch(url,referer=None):
            calls.append(url);return (html if 'action=view' in url else listing).encode()
        result=b.collect({'cwma':config},lambda _:fetch,STAMP)
        self.assertEqual(result['holds'],[]);self.assertEqual(len(result['notices']),1)
        self.assertEqual(b.validate_notice(result['notices'][0],STAMP),result['notices'][0])
        self.assertEqual(len(calls),2)  # form download and page overrun prohibited
        old=listing.replace('2099-03-04','2097-03-04')
        result=b.collect({'cwma':config},lambda _:lambda *args:old.encode(),STAMP)
        self.assertEqual(result['notices'],[]);self.assertEqual(result['holds'],[])
        self.assertEqual(result['coverage']['cwma']['listing_boundaries'][0]['boundary'],'observed_older_page')

    def test_logical_urls_use_observed_posts_but_scripts_files_keep_get(self):
        for iid,urls in [('nps',[b.nps.BASE+b.nps.LIST+'?pageIndex=2',n.URL,b.nps.SCRIPT]),('cwma',[c.CONFIG['listing_url']+'&page=2',c.DETAIL_URL,b.cwma.BASE+'/upload/boardAdmin/file.hwp'])]:
            session=b.Session(b.load_configs()[iid]);session.opener=MagicMock()
            session.opener.open.return_value.__enter__.return_value.read.return_value=b'ok'
            for url in urls:session(url,'https://example.invalid/')
            reqs=[v.args[0] for v in session.opener.open.call_args_list]
            self.assertEqual([r.get_method() for r in reqs],['POST','POST','GET'])
            self.assertIsNone(reqs[2].data)
            if iid=='nps':
                self.assertEqual(json.loads(reqs[0].data)['pageIndex'],2)
                self.assertEqual(parse_qs(reqs[1].data.decode())['pstId'],[n.PID])
            else:self.assertEqual(parse_qs(reqs[1].data.decode())['boardNo'],['98765'])

    def test_version_two_scan_only_and_legacy_proof_unchanged(self):
        raw=b'%PDF-test'
        with patch.object(b,'extract_attachment',return_value={'format':'pdf','text':'watermark\nwatermark'}),patch.object(b,'recognize_pdf',side_effect=ValueError('OCR unavailable')) as ocr:
            self.assertEqual(b.attachment_text(raw,'공고.pdf'),'watermark\nwatermark');ocr.assert_not_called()
            with self.assertRaisesRegex(ValueError,'OCR unavailable'):b.attachment_text(raw,'공고.pdf',extraction_version=2)
        with patch.object(b,'extract_attachment',return_value={'format':'pdf','text':'valid body '*50}),patch.object(b,'recognize_pdf') as ocr:
            self.assertEqual(b.attachment_text(raw,'공고.pdf',extraction_version=2),'valid body '*50);ocr.assert_not_called()
        for version in (True,0,3,'2'):
            with self.assertRaises(ValueError):b.validate_notice({'attachment_extraction_version':version},STAMP)

    def test_independent_inventory_uses_whole_board_and_validated_identity(self):
        for iid,url,expected in [('nps',n.URL,'nps:BS20990001:'+n.PID),('cwma',c.DETAIL_URL,'cwma:98765')]:
            config=b.load_configs()[iid]
            self.assertEqual(audit.notice_key(iid,url),expected)
            self.assertEqual([(q['term'],q['kind']) for q in audit.query_plan(iid,config,'a','b',independent=True)],[('','board_listing')])
            with self.assertRaises(ValueError):audit.notice_key(iid,url+'&boardNo=forged' if iid=='cwma' else url+'&pstId=forged')

    def test_scan_replay_jobs_have_native_ocr_runtime(self):
        root=Path(__file__).resolve().parents[3]
        workflow=(root/'.github/workflows/collect-kgrowth-programs.yml').read_text().split('  collect:\n',1)[1]
        self.assertIn('runs-on: macos-latest',workflow)
        self.assertIn('runs-on: macos-latest',(root/'.github/workflows/recover-lp-publication.yml').read_text())

if __name__=='__main__':unittest.main()
