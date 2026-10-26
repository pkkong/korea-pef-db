import unittest
from services.lp.src import lp_board_adapter_kamco as a
C={'institution_id':'kamco','listing_url':a.BASE+'/portal/bbs/list.do?mId=0701010000&ptIdx=380','search_params':{'searchType':'0','searchTxt':'PEF'}}
U=C['listing_url']+'&searchType=0&searchTxt=PEF&page=1'
D=a.BASE+'/portal/bbs/view.do?bIdx=987654&ptIdx=380&mId=0701010000'
L='''<html><select name="searchType"><option value="0" selected>제목</option></select><input name="searchTxt" value="PEF"><ul><li class="board-page-list">페이지</li><li class="board-page-list">1 / 2</li></ul><table><tbody><tr><td><a onclick="goTo.view('list','987654','380','0701010000'); return false;">펀드 모집</a></td><td class="list_date">2026-09-10</td></tr></tbody></table></html>'''
H='''<html><input id="bIdx" value="987654"><table class="table-view"><thead><tr><td date-label="제목">기업지원 PDF 모집</td><td date-label="등록일">2026-09-10</td></tr></thead><tbody><tr><td colspan="4">Private Debt Fund 모집입니다.</td></tr><tr><td colspan="4" class="grey-box"><div id="updateFileList"><a onclick="fn_egov_downFile('FILE_0000999','0'); return false;">공고.hwp</a></div></td></tr></tbody></table></html>'''
class Tests(unittest.TestCase):
 def test_observed_controls_arbitrary_id_and_dynamic_hold(self):
  row=a.parse_listing(L,U,C)[0];self.assertEqual(row['url'],D);self.assertEqual(row['source_id'],'kamco:987654');self.assertEqual(a.last_page(L,U,C),2)
  d=a.parse_detail(H,D,C);self.assertIn('Private Debt',d['body']);self.assertTrue(d['dynamic_attachments']);self.assertEqual(len(d['attachment_holds']),1);self.assertEqual(d['attachments'],[])
 def test_board_query_page_and_control_mismatches(self):
  for html,url in [(L.replace('value="PEF"','value="VC"'),U),(L,U.replace('page=1','page=2')),(L.replace("'380'","'381'"),U),(L,U.replace('www.kamco.or.kr','evil.test'))]:
   with self.assertRaises(ValueError):a.parse_listing(html,url,C)
 def test_detail_id_date_body_and_unresolved_control(self):
  for html in [H.replace('value="987654"','value="777"'),H.replace('2026-09-10','unknown'),H.replace('FILE_0000999','../bad'),H.replace('class="table-view"','class="unknown"')]:
   with self.assertRaises(ValueError):a.parse_detail(html,D,C)
  with self.assertRaises(ValueError):a.parse_listing('<html></html>',U,C)
 def test_verified_zero_first_page_only(self):
  import re
  empty=re.sub(r'<tbody>.*?</tbody>','<tbody><tr><td>등록된 게시물이 없습니다.</td></tr></tbody>',L).replace('<table>','<table class="board-table">')
  empty=empty.replace('1 / 2','1 / 1').replace('<ul>','<ul><li class="board-page-list">전체 0건</li>')
  self.assertEqual(a.parse_listing(empty,U,C),[])
  with self.assertRaises(ValueError):a.parse_listing(empty,U.replace('page=1','page=2'),C)
  with self.assertRaises(ValueError):a.parse_listing(empty.replace('전체 0건','전체 2건'),U,C)
 def test_observed_resolver_and_context_required(self):
  script='function fn_egov_downFile(atchFileId, fileSn) { if(window.G_CONTEXT_PATH != null) {window.open(window.G_CONTEXT_PATH + "/cmm/fms/FileDown.do?atchFileId="+atchFileId+"&fileSn="+fileSn);} else {window.open(yh.contextPath + "/cmm/fms/FileDown.do?atchFileId="+atchFileId+"&fileSn="+fileSn);} }'
  html=H.replace('<html>','<html><script>var yh={"contextPath": ""};</script><script src="/common/js/common/EgovFileUtils.js"></script>')
  self.assertEqual(a.attachment_request(html,D,C),a.BASE+'/common/js/common/EgovFileUtils.js')
  result=a.parse_detail(html,D,C,resolver_script=script)
  self.assertEqual(result['attachments'][0]['url'],a.BASE+'/cmm/fms/FileDown.do?atchFileId=FILE_0000999&fileSn=0')
  self.assertFalse(result['attachment_holds'])
  for changed in [script.replace('/cmm/fms','https://evil.test'),script.replace('fileSn);','fileSn+"x");')]:
   with self.assertRaises(ValueError):a.parse_detail(html,D,C,resolver_script=changed)
  with self.assertRaises(ValueError):a.parse_detail(html.replace('"contextPath": ""','"contextPath": "/other"'),D,C,resolver_script=script)
  with self.assertRaises(ValueError):a.parse_detail(H,D,C,resolver_script=script)
if __name__=='__main__':unittest.main()
