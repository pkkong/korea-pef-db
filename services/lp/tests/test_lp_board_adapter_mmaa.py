import copy,json,unittest
from services.lp.src import lp_board_adapter_mmaa as a
from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src.collect_lp_original_notices import original_body_hash
BASE=a.BASE
CFG={'institution_id':'mmaa','listing_url':BASE+'?schM=list&schFld=1&viewCount=10',
     'search_param':'schStr','searches':['블라인드'],'page_param':'page','pages':1,'lookback_days':365,'history_years':2}
URL=next(boards.listing_urls(CFG));DETAIL_URL=BASE+'?schM=view&id=123'
TITLE="’26년 국내 PE 블라인드 펀드 선정 공고"
QUERY='&schM=list&page=1&viewCount=10&id=&schFld=1&schStr=블라인드'
LISTING=('<html><script>var queryString = '+json.dumps(QUERY,ensure_ascii=False)+';</script>'
 '<form name="listForm"><input name="schStr" value="블라인드"></form>'
 '<table class="box_boardlist"><tr><th>번호</th><th>제목</th><th>첨부</th><th>날짜</th><th>조회수</th></tr>'
 '<tr><td>1</td><td><a onclick="fn_goView(\'123\')">'+TITLE+'</a></td><td></td><td>2026-08-01</td><td>1</td></tr></table>'
 '<div class="paging"><a class="active">1</a><a class="nextAll" onclick="fn_egov_link_page(1); return false;">마지막</a></div></html>')
DETAIL=('<html><div class="view_tit">'+TITLE.replace('’',"'")+'</div><table><tr><th>작성일</th><td>2026-08-01</td></tr></table>'
 '<div class="b_content">국내 PE 블라인드 펀드 위탁운용사 선정 모집 공고입니다. 제안서를 제출하시기 바랍니다.</div>'
 '<div data-ax5uploader="download1"><input name="fileId" value="abc123"><input name="useSecurity" value="false"><input name="uploadMode" value="db"></div>'
 '<script>$.ajax({url: "/afile/fileList.do",data:"fileId=abc123"});</script></html>')
FILES=json.dumps([{'result':1,'fileId':'abc123','fileIdx':'xyz1','fileName':'제안서 양식.hwp','downloadPath':'/afile/fileDownload/xyz1'}])

class MmaaTests(unittest.TestCase):
 def test_listing_and_resolved_form_links_are_replayed(self):
  self.assertEqual(a.last_page(LISTING,URL,CFG),1);self.assertEqual(a.parse_listing(LISTING,URL,CFG)[0]['url'],DETAIL_URL)
  request=a.attachment_request(DETAIL,DETAIL_URL,CFG)
  calls=[]
  def fetch(url,referer=None):
   calls.append(url);return (FILES if url==request else DETAIL if 'schM=view' in url else LISTING).encode()
  r=boards.collect({'mmaa':CFG},lambda c:fetch,'2026-10-26T00:00:00+00:00')
  self.assertFalse(r['holds']);self.assertEqual(len(r['notices']),1)
  n=r['notices'][0];self.assertEqual(n['sha256'],original_body_hash(n));self.assertFalse(n['attachment_bytes'])
  self.assertIn(request,calls);self.assertFalse(any('/fileDownload/' in u for u in calls))
  self.assertEqual(boards.validate_notice(n,r['checked_at'],CFG),n)
  bad=copy.deepcopy(n);bad['discovery_provenance']['attachment_resolution']['text']='[]'
  with self.assertRaises(ValueError):boards.validate_notice(bad,r['checked_at'],CFG)
 def test_file_identity_route_and_security_are_strict(self):
  for value in [FILES.replace('abc123','other'),FILES.replace('/afile/fileDownload/xyz1','/afile/fileRemove/xyz1'),FILES.replace('"result": 1','"result": true')]:
   with self.assertRaises(ValueError):a.parse_detail(DETAIL,DETAIL_URL,CFG,attachment_listing=value)
  with self.assertRaises(ValueError):a.attachment_request(DETAIL.replace('value="false"','value="true"'),DETAIL_URL,CFG)
  with self.assertRaises(ValueError):a.parse_listing(LISTING,URL.replace('page=1','page=2'),CFG)
  with self.assertRaises(ValueError):a.parse_listing(LISTING,URL.replace('www.mmaa.or.kr','evil.example'),CFG)
