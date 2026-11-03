import unittest
from urllib.parse import urlencode
from services.lp.src import lp_board_adapter_cwma as c

CONFIG={'institution_id':'cwma','listing_url':c.BASE+'/board.do?'+urlencode(c.BOARD)}

def listing(page=1,total=11):
    rows=''
    for number in range(total-(page-1)*10,max(0,total-page*10),-1):
        rows+=f'''<tr><td>{number}</td><td>선정공고(자산운용)</td><td><a href="javascript:goView('29','248','view','{98700+number}')">2099년도 국내 사모 및 벤처펀드</a></td><td>담당부서</td><td>2099-02-03</td><td>0</td></tr>'''
    return '''<html><form id="boardAdmin" action="/board.do" method="post"><input name="boardConfigNo" value="29"><input name="menuNo" value="248"><input name="boardCategoryNo" value="66"><input name="searchValue" value=""></form><table class="board-list"><tr>'''+''.join('<th>'+x+'</th>' for x in ['번호','분류','제목','작성자','등록일','조회수'])+f'''</tr>{rows}</table><div class="pagination" id="paging"><strong>{page}</strong><a title="마지막페이지" href="javascript:goCategory('/board.do?boardConfigNo=29','248',2, '66')">2</a></div></html>'''


def detail():
    return '''<html><table class="board-view"><caption>[국내 사모 및 벤처펀드 모집] 게시물의 등록 내용을 보여줍니다.</caption><tr><th class="subject">국내 사모 및 벤처펀드 모집</th></tr><tr><th>작성일</th><td>2099-03-04 12:34</td></tr><tr><td class="content">공식 모집 본문</td></tr><tr><th>첨부파일</th><td><script>
var fileList = '';
fileList += "99999^AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE.hwp^새 공고문.hwp^/upload/boardAdmin/2099/03/AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE.hwp^12345^새 공고문.hwp^upload1";
var temp1 = fileList.split("|", 20);
var temp2 = temp1[i].split("^", 20);
DEXT5UPLOAD.AddUploadedFile(temp2[0], temp2[2], 'https://' + location.host + temp2[3], temp2[4], temp2[5], temp2[6]);
</script></td></tr></table></html>'''

DETAIL_URL=CONFIG['listing_url']+'&action=view&boardNo=98765'


class CwmaAdapterTests(unittest.TestCase):
    def test_detail_labels_and_literal_attachment(self):
        result=c.parse_detail(detail(),DETAIL_URL,CONFIG)
        self.assertEqual(result['date'],'2099-03-04')
        self.assertEqual(result['body'],'공식 모집 본문')
        self.assertEqual(result['attachments'][0]['name'],'새 공고문.hwp')
        self.assertEqual(result['attachments'][0]['url'],c.BASE+'/upload/boardAdmin/2099/03/AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE.hwp')
        self.assertNotIn('scope',result)

    def test_attachment_unsafe_path_mismatch_nonliteral_fail(self):
        for html in (detail().replace('/upload/boardAdmin/2099/03/','https://evil.invalid/'),detail().replace('/upload/boardAdmin/2099/03/','/upload/boardAdmin/2099/../'),detail().replace('^12345^','^notbytes^'),detail().replace('fileList += "99999','fileList += dynamic; fileList += "99999')):
            with self.assertRaises(ValueError):c.parse_detail(html,DETAIL_URL,CONFIG)
        uncertain=c.parse_detail(detail().replace("'https://' + location.host","'https://evil.invalid'"),DETAIL_URL,CONFIG)
        self.assertTrue(uncertain['unresolved_attachments'])
        self.assertEqual(uncertain['attachments'],[])
        self.assertEqual(uncertain['body'],'공식 모집 본문')

    def test_detail_title_date_and_unknown_widget_fail_closed(self):
        for html in (detail().replace('[국내 사모 및 벤처펀드 모집]','[다른 제목]'),detail().replace('2099-03-04 12:34','2099-02-30 12:34'),detail().replace('2099-03-04 12:34','2099-03-04'),detail().replace('공식 모집 본문','')):
            with self.assertRaises(ValueError):c.parse_detail(html,DETAIL_URL,CONFIG)
        self.assertTrue(c.parse_detail(detail().replace('fileList','unknownWidget'),DETAIL_URL,CONFIG)['unresolved_attachments'])

    def test_observed_ids_and_post_plans(self):
        rows=c.parse_listing(listing(),CONFIG['listing_url'],CONFIG)
        self.assertEqual(len(rows),10);self.assertEqual(rows[0]['source_id'],'cwma:98711')
        self.assertEqual(rows[0]['date'],'2099-02-03')  # retain future/old dates; collector owns cutoff
        self.assertEqual(c.last_page(listing(),CONFIG['listing_url'],CONFIG),2)
        req=c.request_plan(rows[0]['url'],CONFIG)
        self.assertEqual(req['method'],'POST');self.assertEqual(req['fields']['boardNo'],'98711')
        self.assertEqual(req['fields']['boardCategoryNo'],'66')
        req=c.request_plan(CONFIG['listing_url']+'&page=2',CONFIG)
        self.assertEqual(req['fields']['page'],'2');self.assertNotIn('action',req['fields'])
        self.assertEqual(c.request_plan(CONFIG['listing_url'],CONFIG)['method'],'GET')

    def test_final_page_and_old_date_retained(self):
        html=listing(2).replace('2099-02-03','2023-01-02')
        rows=c.parse_listing(html,CONFIG['listing_url']+'&page=2',CONFIG)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['date'],'2023-01-02')
        with self.assertRaises(ValueError):c.parse_listing(html,CONFIG['listing_url'],CONFIG)

    def test_wrong_board_search_counts_and_fake_empty(self):
        for html in (listing().replace('value="66"','value="99"'),listing().replace('name="searchValue" value=""','name="searchValue" value="PE"'),listing().replace('<td>11</td>','<td>99</td>'),listing().replace('2099-02-03','2099-02-30'),listing().replace('</html>',''),listing(2).replace('<td>1</td>','<td>등록된 게시물이 없습니다.</td>')):
            with self.assertRaises(ValueError):c.parse_listing(html,CONFIG['listing_url'],CONFIG)
        for url in (CONFIG['listing_url'].replace('www.cw.or.kr','evil.invalid'),CONFIG['listing_url']+'&page=2&page=3',CONFIG['listing_url'].replace('29','28'),CONFIG['listing_url']+'&searchValue=PE'):
            with self.assertRaises(ValueError):c.request_plan(url,CONFIG)

    def test_duplicate_ids_bad_pager_and_header_fail(self):
        for html in (listing().replace("'98710'","'98711'"),listing().replace("'248',2","'999',2"),listing().replace('<th>등록일</th>','<th>시작일</th>')):
            with self.assertRaises(ValueError):c.parse_listing(html,CONFIG['listing_url'],CONFIG)

if __name__=='__main__':unittest.main()
