import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('pending_contracts',Path(__file__).resolve().parents[1]/'inspect_lp_pending_contracts.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


def hidden_form(name,fields,action=''):
    return '<form method="post" name="'+name+'" action="'+action+'">'+''.join('<input type="hidden" name="'+k+'" value="'+v+'">' for k,v in fields.items())+'</form>'


def nps(identifier='ZZ209900000012345678'):
    return '''<html><script src="/js/common_utils.js"></script><script>
$.httpAjax("/saveDgstfn.do", jsonData);
$.httpAjax("/impa/dlnginstslctnpbanclist/empty/getOHEF0017M0.do"
, jsonData, '', fncCallBack);
form.action = "/impa/dlnginstslctnpbancdtl/getOHEF0018M0.do";form.submit();
</script>'''+hidden_form('searchForm',dict(pstId='',hmpgBbsCd='',pageIndex='1',searchGbu='',searchText=''))+f'''<a href="javascript:fnc_goBbsDetail('{identifier}', 'BS20990099');">2099년 국내 사모투자 위탁운용사 선정 공고</a><a onclick="fnc_egov_select_linkPage(2)">2</a></html>'''


def cwma(identifier='987654'):
    fields=dict(menuNo='',contentsNo='',boardConfigNo='',moveMenu='',separator='',actionVal='',page='',boardCategoryNo='',boardWriterAddress2='',menuLayout='category_tabLayout',searchValue='',searchCategory='')
    vf=dict(boardConfigNo='',menuNo='',action='',boardNo='',pageNo='',menuLayout=' ',searchCategory='',searchValue='',boardCategoryNo='66')
    return '''<html><script>document.menuForm.method = "POST";document.menuForm.page.value = pageNo;document.menuForm.submit();document.boardViewForm.submit();</script>'''+hidden_form('menuForm',fields)+hidden_form('boardViewForm',vf,'/board.do')+f'''<table class="board-list"><tr><td><a href="javascript:goView('29','248','view','{identifier}')">2098년도 국내 사모투자펀드 및 벤처펀드 선정 공고</a></td></tr></table><div id="paging"><a href="javascript:goCategory('/board.do?boardConfigNo=29','248',2, '66')">2</a></div></html>'''


CONTROLLER='type        : "POST" JSON.stringify(data) application/json; function fncAtchFileDownload(atchFileId, atchFileSn) {let url = "/fileDown.do?atchFileId=" + atchFileId + "&atchFileSn=" + atchFileSn;window.open(url,"_blank");}'
NPS_DETAIL='''<html><script src="/js/common_utils.js"></script><div class="file-item"><p class="a-file">공고문.pdf</p><a class="btn-file-down" href="javascript:fncAtchFileDownload('FL99999999', '1');">다운로드</a></div></html>'''


class PendingContractsTests(unittest.TestCase):
    def test_observed_ids_forms_and_post_encoding(self):
        a=m.contracts(nps(),m.PENDING_ROOTS['nps'],'nps')
        self.assertEqual(a['detail']['fields']['pstId'],'ZZ209900000012345678')
        self.assertEqual(a['page']['fields']['pageIndex'],2)
        self.assertEqual(a['page']['encoding'],'json')
        b=m.contracts(cwma(),m.PENDING_ROOTS['cwma'],'cwma')
        self.assertEqual(b['detail']['fields']['boardNo'],'987654')
        self.assertEqual(b['page']['fields']['page'],'2')
        self.assertNotIn('action',b['page']['fields'])
        self.assertIn('벤처',b['detail']['title'])  # format sample, not scope approval

    def test_wrong_forms_routes_and_missing_controls_rejected(self):
        for html in (nps().replace('empty/getOHEF0017M0','evil/getOHEF0017M0'),nps().replace('method="post"','method="get"'),nps().replace('fnc_egov_select_linkPage(2)','fnc_egov_select_linkPage(9)'),nps().replace('</html>','')):
            with self.assertRaises(ValueError):m.contracts(html,m.PENDING_ROOTS['nps'],'nps')
        with self.assertRaises(ValueError):m.contracts(cwma().replace("'29','248','view'","'99','248','view'"),m.PENDING_ROOTS['cwma'],'cwma')

    def test_urls_and_unresolved_download_controls(self):
        for url in ('http://fund.nps.or.kr/a','https://evil.invalid/a','https://fund.nps.or.kr/%2e%2e/a','https://fund.nps.or.kr:443/a'):
            with self.assertRaises(ValueError):m.safe_url(url,'nps')
        html='''<a href="javascript:download('123')">모집 공고.hwp</a><a href="https://evil.invalid/offer.pdf">공고.pdf</a><a href="/files/form.pdf">제출 양식.pdf</a>'''
        selected=m.attachment_controls(html,m.PENDING_ROOTS['nps'],'nps')
        self.assertIsNone(selected['attachment']);self.assertEqual(len(selected['unresolved_controls']),1)
        self.assertEqual(m.attachment_controls('<a href="/files/offer.pdf">모집 공고.pdf</a>',m.PENDING_ROOTS['nps'],'nps')['attachment']['url'],'https://fund.nps.or.kr/files/offer.pdf')

    def test_full_fake_capture_preserves_post_receipts_and_bounds(self):
        calls=[]
        def fetch(method,url,fields,encoding,limit):
            calls.append((method,url,fields,encoding,limit))
            if url==m.PENDING_ROOTS['nps']:raw=nps().encode()
            elif url==m.PENDING_ROOTS['cwma']:raw=cwma().encode()
            elif url.endswith('common_utils.js'):raw=CONTROLLER.encode()
            elif 'files/' in url or 'fileDown.do?' in url:raw=b'%PDF-1.7 public sample'
            elif 'getOHEF0018M0.do?' in url or (fields or {}).get('action')=='view' or (fields or {}).get('pstId'):raw=(NPS_DETAIL.encode() if 'fund.nps' in url else b'<html><a href="/files/offer.pdf">offer.pdf</a></html>')
            else:raw=b'<html>page two observed</html>'
            return 200,url,raw
        with tempfile.TemporaryDirectory() as directory:
            report=m.inspect(directory,fetch)
            self.assertEqual(report['requests'],10)
            self.assertEqual(report['holds'],[])
            self.assertEqual(len(list(Path(directory).glob('*.bin'))),10)
            saved=json.loads((Path(directory)/'index.json').read_text())
            self.assertEqual(saved,report)
            self.assertTrue(all(call[4]<=3*1024*1024 for call in calls))
            self.assertFalse(any('cookie' in str(r).lower() for r in report['responses']))

    def test_failure_retained_and_other_institution_continues(self):
        def fetch(method,url,fields,encoding,limit):
            if 'fund.nps' in url:return 503,url,b'outage'
            if method=='GET':return 200,url,cwma().encode()
            return 200,url,b'<html>no literal attachment</html>'
        with tempfile.TemporaryDirectory() as directory:
            report=m.inspect(directory,fetch)
            self.assertEqual(report['responses'][0]['status'],503)
            self.assertTrue(report['responses'][0]['file'])
            self.assertTrue(any(r['kind']=='detail' and r['institution_id']=='cwma' for r in report['responses']))
            self.assertTrue(report['holds'])

    def test_cwma_missing_sample_moves_to_page_two(self):
        first=cwma().replace('국내 사모투자펀드 및 벤처펀드','국내 부동산')
        self.assertIsNone(m.contracts(first,m.PENDING_ROOTS['cwma'],'cwma')['detail'])
        def fetch(method,url,fields,encoding,limit):
            if 'fund.nps' in url:return 503,url,b'unavailable'
            if method=='GET':return 200,url,first.encode()
            if (fields or {}).get('page')=='2':return 200,url,cwma('765432').encode()
            return 200,url,b'<html>detail</html>'
        with tempfile.TemporaryDirectory() as directory:
            report=m.inspect(directory,fetch)
            detail=next(r for r in report['responses'] if r['kind']=='detail')
            self.assertEqual(detail['request_fields']['boardNo'],'765432')

    def test_nps_download_formula_and_ids(self):
        result=m.nps_downloads(NPS_DETAIL,m.PENDING_ROOTS['nps'],CONTROLLER)
        self.assertIn('atchFileId=FL99999999&atchFileSn=1',result[0]['url'])
        with self.assertRaises(ValueError):m.nps_downloads(NPS_DETAIL,m.PENDING_ROOTS['nps'],CONTROLLER.replace('/fileDown.do','https://evil.invalid/'))

    def test_request_cap_never_exceeded(self):
        calls=[]
        def fetch(method,url,fields,encoding,limit):
            calls.append(url)
            if url==m.PENDING_ROOTS['nps']:return 200,url,nps().encode()
            return 200,url,b'type        : "POST" JSON.stringify(data) application/json;'
        with tempfile.TemporaryDirectory() as directory, patch.object(m,'MAX_REQUESTS',2):
            report=m.inspect(directory,fetch)
            self.assertEqual(len(calls),2)
            self.assertEqual(report['requests'],2)
            self.assertTrue(report['holds'])

    def test_oversize_and_foreign_final_fail_closed(self):
        for response in (lambda url,limit:(200,url,b'x'*(limit+1)),lambda url,limit:(200,'https://evil.invalid/',b'x')):
            with tempfile.TemporaryDirectory() as directory:
                report=m.inspect(directory,lambda method,url,fields,encoding,limit:response(url,limit))
                self.assertEqual(len(report['holds']),2)
                self.assertFalse(list(Path(directory).glob('*.bin')))

if __name__=='__main__':unittest.main()
