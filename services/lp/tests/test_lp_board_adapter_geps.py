import unittest
from services.lp.src import lp_board_adapter_geps as a
C={'institution_id':'geps','listing_url':a.BASE+a.PATH,'search_params':{'srchKey':'sj','srchText':'PEF'}}
U=C['listing_url']+'?srchKey=sj&srchText=PEF&curPage=1'
D=a.BASE+a.PATH+'/987654?curPage=1'
L='''<html><select name="srchKey"><option value="sj" selected>제목</option></select><input name="srchText" value="PEF"><table><thead><tr><th class="writngDe">등록일</th></tr></thead><tbody><tr><td class="sj"><a href="/notiCommunication_notice_center/987654?curPage=1">국내 PEF 위탁운용사 모집</a></td><td class="writngDe">2026.09.10</td></tr></tbody></table><ul class="pagination"><li class="active">1</li><li><a title="마지막 페이지" href="?curPage=2&amp;srchKey=sj&amp;srchText=PEF">끝</a></li></ul></html>'''
H='''<html><div class="d-flex justify-content-between border-bottom"><h6><strong>국내 PEF 모집</strong></h6><h6>2026-09-10</h6></div><div class="viewCtn">공식 모집내용입니다.</div><a class="file" href="/comm/getFile?srvcId=BBSTY1&amp;fileUuid=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA">공고문.pdf</a></html>'''
class Tests(unittest.TestCase):
 def test_actual_controls_and_arbitrary_id(self):
  r=a.parse_listing(L,U,C)[0];self.assertEqual(r['source_id'],'geps:987654');self.assertEqual(r['url'],D);self.assertEqual(a.last_page(L,U,C),2)
  d=a.parse_detail(H,D,C);self.assertEqual(d['date'],'2026-09-10');self.assertEqual(len(d['attachments']),1)
 def test_query_page_route_and_duplicate_errors(self):
  for html,url in [(L.replace('value="PEF"','value="VC"'),U),(L,U.replace('curPage=1','curPage=2')),(L,U.replace('www.geps.or.kr','evil.test')),(L.replace('</tbody>',L[L.index('<tr><td'):L.index('</tbody>')]+'</tbody>'),U)]:
   with self.assertRaises(ValueError):a.parse_listing(html,url,C)
 def test_bad_metadata_attachment_and_empty_unconfirmed(self):
  for html in [H.replace('2026-09-10','missing'),H.replace('srvcId=BBSTY1','srvcId=OTHER'),H.replace('/comm/getFile','https://evil.test/comm/getFile')]:
   with self.assertRaises(ValueError):a.parse_detail(html,D,C)
  with self.assertRaises(ValueError):a.parse_listing('<html></html>',U,C)
 def test_verified_first_page_zero_and_overrun(self):
  import re
  empty=re.sub(r'<tbody>.*?</tbody>','<tbody><tr><td>데이터가 없습니다.</td></tr></tbody>',L)
  empty=re.sub(r'<ul class="pagination">.*?</ul>','<ul class="pagination"></ul>',empty)
  self.assertEqual(a.parse_listing(empty,U,C),[]);self.assertEqual(a.last_page(empty,U,C),1)
  with self.assertRaises(ValueError):a.parse_listing(empty,U.replace('curPage=1','curPage=2'),C)
  with self.assertRaises(ValueError):a.parse_listing(empty.replace('<td>데이터가 없습니다.</td>','<td></td>')+'데이터가 없습니다.',U,C)
 def test_receipt_keyword_can_vary_without_static_config_search(self):
  config={k:v for k,v in C.items() if k!='search_params'}
  self.assertEqual(len(a.parse_listing(L.replace('PEF','블라인드'),U.replace('PEF','%EB%B8%94%EB%9D%BC%EC%9D%B8%EB%93%9C'),config)),1)
if __name__=='__main__':unittest.main()
