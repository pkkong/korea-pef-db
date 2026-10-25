"""SEMA official routes, page boundaries and independently replayed discovery."""
import copy
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit
from services.lp.src import lp_board_adapter_sema as sema
from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src.lp_notice_publication import publish_basic_notices

TITLE = '2026년 국내 PE·VC 블라인드 펀드 위탁운용사 출자 선정 공고'
BODY = ('국내 PE·VC 블라인드 펀드 선정 개요 운용방식 블라인드형 '
        '출자규모 총 4,600억원 (PE 부문 2,700억원 / VC 부문 1,900억원) '
        '펀드별 출자규모 운용사 수 결성 예정규모 PE 대형 600억 1개사 내외 '
        '중형이하 400억 5개사 내외 루키 100억 1개사 내외 VC '
        '투자기구 기관전용 사모집합투자기구 마감일시 : ’26. 9. 7. (월) 16:00')
STAMP = '2026-10-25T00:00:00+00:00'


def listing(url, *, ident='990001', stamp='2026-08-14', last=1, empty=False):
    q = parse_qs(urlsplit(url).query); page = q['pageIndex'][0]
    detail_url = sema.BOARD+'view.do?'+urlencode({**{k:v[0] for k,v in q.items()},'nttId':ident})
    target = sema.BOARD+'list.do?'+urlencode({**{k:v[0] for k,v in q.items()},'pageIndex':last})
    row = ('<tr><td colspan="5">게시글이 없습니다.</td></tr>' if empty else
           f'<tr><td>1</td><td>SEMA</td><td><a class="aLink" href="{detail_url}">{TITLE}</a></td><td>{stamp}</td><td>10</td></tr>')
    pager = '' if empty else f'<div class="paginationSet"><em title="현재목록">{page}</em><a title="마지막 목록" href="{target}">마지막</a></div>'
    return (f'<html><input name="optn1" value="S"><input name="searchWrd" value="{q["searchWrd"][0]}">'
            '<select name="searchCnd"><option selected value="1">제목</option></select>'
            '<table class="dataTbl"><tr><th>No</th><th>분류</th><th>제목</th><th>작성일</th><th>조회</th></tr>'
            +row+'</table>'+pager+'</html>')


def detail(*, body=BODY, title=TITLE, stamp='2026-08-14', files=False):
    attachments = ('<tr><th>첨부파일</th><td><a href="/sema/cmmn/file/fileDown.do?menuNo=200017&atchFileId=abcdef&fileSn=1">제안서 양식.xlsx</a></td></tr>' if files else '')
    return ('<html><table class="writeForm"><tr><th>제목</th><td>'+title+'</td></tr>'
            '<tr><th>작성일</th><td>'+stamp+' 09:30</td></tr>'+attachments+
            '<tr><td class="td_cont">'+body+'</td></tr></table>'
            '<table class="prevNext"><tr><td>해외주식 다른 공고</td></tr></table></html>')


class SemaBoardTests(unittest.TestCase):
    def setUp(self):
        self.config=boards.load_configs()['sema']; self.url=next(boards.listing_urls(self.config))

    def test_observed_board_title_date_and_last_page(self):
        rows=sema.parse_listing(listing(self.url),self.url,self.config)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['source_id'],'sema:990001')
        self.assertEqual(sema.last_page(listing(self.url),self.url,self.config),1)
        n=sema.parse_detail(detail(files=True),rows[0]['url'],self.config)
        self.assertEqual(n['body'],BODY);self.assertEqual(n['date'],'2026-08-14')
        self.assertEqual(len(n['attachments']),1)

    def test_empty_is_a_board_row_not_homepage_or_blank_table(self):
        html=listing(self.url,empty=True)
        self.assertEqual(sema.parse_listing(html,self.url,self.config),[])
        self.assertEqual(sema.last_page(html,self.url,self.config),1)
        for value in ['<html>회원 서비스 게시글이 없습니다.</html>',html.replace('게시글이 없습니다.','')]:
            with self.assertRaises(ValueError):sema.parse_listing(value,self.url,self.config)
        with self.assertRaises(ValueError):sema.last_page(html,self.url.replace('pageIndex=1','pageIndex=2'),self.config)

    def test_wrong_board_search_page_or_duplicate_id_fails(self):
        html=listing(self.url)
        for value in [self.url.replace('B0000022','B0000024'),self.url.replace('menuNo=200017','menuNo=200018'),
                      self.url.replace('pageIndex=1','pageIndex=2'),self.url.replace('searchCnd=1','searchCnd=2')]:
            with self.assertRaises(ValueError):sema.last_page(html,value,self.config)
        with self.assertRaises(ValueError):sema.parse_listing(html.replace('nttId=990001','nttId=990001&nttId=2'),self.url,self.config)
        with self.assertRaises(ValueError):sema.parse_listing(html.replace(TITLE,'다른 게시글'),self.url,self.config)
        with self.assertRaises(ValueError):sema.last_page(html.replace('title="마지막 목록"','title="변경"'),self.url,self.config)

    def test_detail_metadata_body_and_attachment_host_are_strict(self):
        url=sema.parse_listing(listing(self.url),self.url,self.config)[0]['url']
        for html in [detail().replace('작성일','조회일'), detail().replace('td_cont','missing'),
                     detail(files=True).replace('/sema/cmmn/file/fileDown.do','https://evil.example/fileDown.do')]:
            with self.assertRaises(ValueError):sema.parse_detail(html,url,self.config)
        with self.assertRaises(ValueError):sema.parse_detail(detail(),url.replace('nttId=990001','nttId=no'),self.config)

    def collect(self, *, config=None, source_date='2026-08-14', last=1, wrong_date=False):
        calls=[]
        def fetch(url,referer=None):
            calls.append(url)
            if 'list.do?' in url:return listing(url,stamp=source_date,last=last).encode()
            return detail(stamp='2026-08-13' if wrong_date else source_date,files=True).encode()
        result=boards.collect({'sema':config or self.config},lambda c:fetch,STAMP)
        return result,calls

    def test_searches_deduplicate_identity_and_stop_at_actual_final_page(self):
        r,calls=self.collect();self.assertFalse(r['holds']);self.assertEqual(len(r['notices']),1)
        self.assertEqual(sum('list.do?' in u for u in calls),3)
        self.assertEqual(sum('view.do?' in u for u in calls),1)
        self.assertFalse(any('fileDown.do' in u for u in calls))
        self.assertEqual(len(r['coverage']['sema']['listing_boundaries']),3)
        self.assertEqual(boards.validate_notice(r['notices'][0],STAMP),r['notices'][0])
        changed=copy.deepcopy(r['notices'][0]);changed['body']='위조된 본문'
        with self.assertRaises(ValueError):boards.validate_notice(changed,STAMP)

    def test_rolling_year_stops_at_old_rows_and_repetition_is_not_completion(self):
        r,calls=self.collect(source_date='2025-10-25',last=20)
        self.assertFalse(r['holds']);self.assertFalse(r['notices']);self.assertEqual(len(calls),3)
        self.assertEqual(r['coverage']['sema']['window_start'],'2025-10-26')
        r,_=self.collect(last=20)
        self.assertTrue(any('repeated' in h.get('error','') for h in r['holds']))
        r,_=self.collect(config={**self.config,'pages':1},last=20)
        self.assertTrue(any(h['stage']=='institution_depth' for h in r['holds']))

    def test_listing_detail_mismatch_is_not_a_public_document(self):
        r,_=self.collect(wrong_date=True)
        self.assertFalse(r['notices']);self.assertTrue(r['holds'])

    def test_pe_track_publishes_without_association_and_vc_total_is_not_used(self):
        r,_=self.collect()
        programs,holds=publish_basic_notices({'programs':[],'institution_notices':r['notices']},[],STAMP)
        self.assertFalse(holds);self.assertEqual(len(programs),1)
        p=programs[0];self.assertEqual(p['commitment_amount_krw'],270_000_000_000)
        self.assertEqual(p['manager_count'],7);self.assertEqual(p['deadline'],'2026-09-07T16:00:00+09:00')
        self.assertFalse(p['selected_gps'])
        again,_=publish_basic_notices({'programs':programs,'institution_notices':r['notices']},[],STAMP)
        self.assertEqual([p['id'] for p in programs],[p['id'] for p in again])
        for n in r['notices']: n['title']=n['title'].replace('PE·VC','VC')
        # Mutating a prepared title without the receipt must never qualify it.
        rejected,_=publish_basic_notices({'programs':[],'institution_notices':r['notices']},[],STAMP)
        self.assertFalse(rejected)
