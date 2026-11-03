import unittest
from urllib.parse import urlencode
from services.lp.src import lp_board_adapter_suhyup as s

C={'institution_id':'suhyup'}
DETAIL=s.BASE+'/bbs/suhyup/23/99001/artclView.do'


def listing(page=1,total=11,term=''):
    fields=dict(layout='observed-public-theme',page=str(page),srchColumn='sj' if term else '',srchWrd=term,
                bbsClSeq='',bbsOpenWrdSeq='',rgsBgndeStr='',rgsEnddeStr='',isViewMine='false')
    form=''.join('<input name="'+k+'" value="'+v+'">' for k,v in fields.items())
    rows=''
    for number in range(total-(page-1)*10,max(0,total-page*10),-1):
        identity=99000+number
        rows+=f'''<tr><td>{number}</td><td><a href="/bbs/suhyup/23/{identity}/artclView.do" onclick="jf_viewArtcl('suhyup', '23', '{identity}')"><strong>2099년 국내 PEF 모집</strong><span class="new">새글</span></a></td><td>2099.03.04</td><td>10</td><td></td><td></td></tr>'''
    final=max(1,(total+9)//10)
    return f'''<html><form name="searchForm"><select name="srchColumn"><option value="sj">제목</option></select></form><form name="pageForm" method="post" action="{s.LIST}">{form}</form><p class="count-txt">{total}건, 현재페이지: {page}/{final}</p><table class="board-link-list"><tr>'''+''.join('<th>'+x+'</th>' for x in ['번호','제목','작성일','조회수','바로보기','첨부파일'])+f'''</tr>{rows}</table><div class="_paging"><span class="_curPage">{page}</span><span class="_totPage">{final}</span><a class="_last" href="javascript:page_link('{final}')">끝</a></div></html>'''


def detail():
    return '''<html><div class="board-view-info"><dl class="view-num"><dt>글번호</dt><dd>99001</dd></dl><h2 class="view-title">2099년 국내 PEF 모집</h2><dl class="write"><dt>등록일</dt><dd>2099.03.04</dd></dl><dl><dt>수정일</dt><dd>2099.04.05</dd></dl></div><div class="view-con">공식 모집 본문입니다.</div><div class="view-file"><a href="/bbs/suhyup/23/88001/download.do">모집 공고.hwp</a><a href="#preview">바로보기</a></div></html>'''


class SuhyupAdapterTests(unittest.TestCase):
    def test_rows_omit_new_badges_and_validate_paging(self):
        rows=s.parse_listing(listing(),s.BASE+s.LANDING,C)
        self.assertEqual(len(rows),10);self.assertEqual(rows[0]['title'],'2099년 국내 PEF 모집')
        self.assertEqual(rows[0]['source_id'],'suhyup:99011');self.assertEqual(s.last_page(listing(),s.BASE+s.LANDING,C),2)
        url=s.BASE+s.LANDING+'?'+urlencode({'srchWrd':'펀드','srchColumn':'sj','page':2})
        rows=s.parse_listing(listing(page=2,term='펀드'),url,C)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['url'],DETAIL)

    def test_observed_theme_is_taken_from_current_form_not_a_constant(self):
        fields=s.search_fields(listing())
        url=s.BASE+s.LANDING+'?'+urlencode({'page':2,'srchColumn':'sj','srchWrd':'운용사'})
        request=s.request_plan(url,C,fields=fields)
        self.assertEqual(request['method'],'POST');self.assertEqual(request['url'],s.BASE+s.LIST)
        self.assertEqual(request['fields']['layout'],'observed-public-theme')
        self.assertEqual(request['fields']['page'],'2');self.assertEqual(request['fields']['srchWrd'],'운용사')
        self.assertEqual(fields['page'],'1')
        with self.assertRaises(ValueError):s.request_plan(url,C)
        self.assertEqual(s.request_plan(DETAIL,C)['method'],'GET')

    def test_wrong_search_date_ids_board_count_and_false_empty_fail(self):
        url=s.BASE+s.LANDING
        for html in (listing().replace('2099.03.04','2099.02.30'),listing().replace('/23/99010/','/23/99011/'),
                     listing().replace('value="false"','value="true"'),listing().replace('value=""','value="unexpected"'),
                     listing().replace("page_link('2')","page_link('99')"),listing().replace('</html>',''),listing(total=0)):
            with self.assertRaises(ValueError):s.parse_listing(html,url,C)
        with self.assertRaises(ValueError):s.parse_listing(listing(term='펀드'),url+'?srchWrd=운용사',C)
        for target in (url.replace('www.suhyup.co.kr','evil.invalid'),url+'?page=1&page=2',DETAIL.replace('/23/','/88/')):
            with self.assertRaises(ValueError):s.request_plan(target,C)

    def test_observed_empty_row_is_zero_without_following_other_page(self):
        html=listing(total=0).replace('</table>','<tr><td class="no-data">게시물이(가) 없습니다.</td></tr></table>')
        self.assertEqual(s.parse_listing(html,s.BASE+s.LANDING,C),[])
        self.assertEqual(s.last_page(html,s.BASE+s.LANDING,C),1)
        with self.assertRaises(ValueError):s.parse_listing(html.replace('게시물이(가) 없습니다.','Access denied'),s.BASE+s.LANDING,C)

    def test_detail_requires_matching_article_number_and_original_posted_date(self):
        record=s.parse_detail(detail(),DETAIL,C)
        self.assertEqual(record['date'],'2099-03-04');self.assertEqual(record['body'],'공식 모집 본문입니다.')
        self.assertEqual(record['attachments'],[{'url':s.BASE+'/bbs/suhyup/23/88001/download.do','name':'모집 공고.hwp'}])
        for html in (detail().replace('<dd>99001','<dd>99002'),detail().replace('2099.03.04','2099.02.30'),detail().replace('공식 모집 본문입니다.','')):
            with self.assertRaises(ValueError):s.parse_detail(html,DETAIL,C)
        with self.assertRaises(ValueError):s.parse_detail(detail(),DETAIL+'&forged=1',C)

    def test_duplicate_files_and_unobserved_download_widgets_do_not_grant_files(self):
        html=detail().replace('<a href="#preview">','<a href="/bbs/suhyup/23/88001/download.do">copy</a><a href="#preview">')
        with self.assertRaises(ValueError):s.parse_detail(html,DETAIL,C)
        unknown=s.parse_detail(detail().replace('/bbs/suhyup/23/88001/download.do','https://evil.invalid/download.do'),DETAIL,C)
        self.assertEqual(unknown['attachments'],[]);self.assertTrue(unknown['unresolved_attachments'])


if __name__=='__main__':unittest.main()
