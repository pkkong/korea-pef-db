import unittest
from urllib.parse import urlencode
from services.lp.src import lp_board_adapter_nh as n
C={'institution_id':'nh_central'}

def fixture(board='notice',page=1,total=11,term=''):
    path='/ecenter/'+board+'/'+board
    rows=''.join(f'''<tr><td>{i}</td><td class="tit_brdlist"><a onclick="fn_select_brdView('{90000+i}');">2099 국내 펀드 운용사 모집</a></td><td></td><td>2099.03.04</td><td>0</td></tr>''' for i in range(total-(page-1)*10,max(0,total-page*10),-1))
    selected=' selected' if term else ''
    return f'''<html><script>function fn_select_brdList(pageNo){{form.action = "{path}List.do";form.submit();}} function fn_select_brdView(blbdSqno){{form.action = "{path}View.do";form.submit();}}</script><dl class="sum"><strong>{total}</strong></dl><form id="frm" action="{path}List.do" method="post"><input name="intgBsnBlbdGrpC" value="{n.BOARDS[board]}"><input name="pageIndex" value="{page}"><input name="searchWrd" value="{term}"><select name="searchCnd"><option value="0">전체</option><option value="1"{selected}>제목</option><option value="2">내용</option></select></form><table class="list"><tr><th>번호</th><th>제목</th><th>첨부파일</th><th>등록일</th><th>조회수</th></tr>{rows}</table><div class="page"><button class="on">{page}</button><button class="btn_next0" onclick="fn_select_brdList({(total+9)//10});return false; ">마지막</button></div></html>'''

def url(board='notice',**q):return n.BASE+'/ecenter/'+board+'/'+board+'List.do'+('?' + urlencode(q) if q else '')

class NhAdapterTests(unittest.TestCase):
    def test_two_boards_same_identifier_distinct_sources(self):
        rows=[n.parse_listing(fixture(b),url(b),C)[0] for b in ('notice','bid')]
        self.assertNotEqual(rows[0]['source_id'],rows[1]['source_id'])
        for r in rows:
            self.assertEqual(r['date'],'2099-03-04')
            plan=n.request_plan(r['url'],C)
            self.assertEqual(plan['fields']['blbdSqno'],'90011');self.assertEqual(plan['method'],'POST')
        self.assertEqual(n.request_plan(url(),C)['method'],'GET')

    def test_search_echo_second_page_and_request_plan(self):
        u=url(pageIndex='2',searchCnd='1',searchWrd='운용사')
        rows=n.parse_listing(fixture(page=2,term='운용사'),u,C)
        self.assertEqual(len(rows),1);self.assertEqual(n.last_page(fixture(page=2,term='운용사'),u,C),2)
        self.assertEqual(n.request_plan(u,C)['fields']['searchWrd'],'운용사')
        with self.assertRaises(ValueError):n.parse_listing(fixture(page=2,term='펀드'),u,C)
        with self.assertRaises(ValueError):n.parse_listing(fixture(page=1,term='운용사'),u,C)

    def test_invalid_response_metadata_and_false_empty(self):
        for s in (fixture().replace('000000000012','000000000019'),fixture().replace('2099.03.04','2099.02.30'),fixture().replace("'90010'","'90011'"),fixture().replace('</html>',''),fixture(total=0),fixture().replace('<th>등록일</th>','<th>기간</th>'),fixture().replace('fn_select_brdList(2);return','fn_select_brdList(3);return')):
            with self.assertRaises(ValueError):n.parse_listing(s,url(),C)

    def test_foreign_route_group_duplicate_queries_rejected(self):
        row=n.parse_listing(fixture(),url(),C)[0]
        for u in (url().replace('www.nonghyup.com','evil.invalid'),url()+'?pageIndex=1&pageIndex=2',url()+'?searchCnd=2&searchWrd=펀드',row['url'].replace('000000000012','000000000019'),row['url'].replace('noticeView','bidView')):
            with self.assertRaises(ValueError):n.request_plan(u,C)

if __name__=='__main__':unittest.main()
