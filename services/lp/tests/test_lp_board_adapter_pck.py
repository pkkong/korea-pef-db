import copy
import io
import unittest
import zipfile
from urllib.parse import urlencode, parse_qs, urlsplit

from services.lp.src import lp_board_adapter_pck as pck
from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src.lp_attachment_text import extract_attachment

CONFIG = {'institution_id': 'pck_pension', 'listing_url': 'https://www.pension.or.kr/modu/s_board/list.asp?board_seq=1&board_sub_seq=1&view_sub_seq=0&search_select=subject',
          'search_param': 'search_text', 'searches': ['위탁'], 'page_param': 'page', 'pages': 2, 'history_years': 2}
URL = next(boards.listing_urls(CONFIG))
TITLE = '[총회연금재단] 2026년 하반기 대체투자 위탁운용사 선정 공고'


def detail_url(ident):
    return 'https://www.pension.or.kr/modu/s_board/read.asp?board_seq=1&board_sub_seq=1&seq=' + str(ident)


def listing(rows, page=1, last=2, term='위탁'):
    inputs = ''.join(f'<input name="{k}" value="{v}">' for k,v in
                     {'board_seq':'1', 'board_sub_seq':'1', 'page':str(page), 'search_select':'subject', 'search_text':term}.items())
    body = ''.join(f'<tr class="sboard_list_line {"noti_color" if pin else ""}"><td>{"공지" if pin else "10"}</td><td>'
                   f'<a class="sboard_list_sbj" href="read.asp?board_seq=1&board_sub_seq=1&seq={ident}&page={page}&search_text={term}">{title}</a>'
                   f'</td><td>작성자</td><td>{stamp}</td><td>10</td></tr>' for ident,title,stamp,pin in rows)
    return f'<html><form name="l_form">{inputs}<table class="sboard_list_tbl">{body}</table></form><div class="navi_all_btn">{page}/{last}</div></html>'


def detail(ident, stamp='2026-10-22', title=TITLE, body='새 공식 모집 본문', filename=None):
    files = ''
    if filename:
        url = 'download.asp?' + urlencode({'board_seq':'1','board_sub_seq':'1','view_sub_seq':'1','filename':filename})
        files = f'<table class="sboard_atch_file_tbl"><tr><td><a class="sboard_atch_file" href="{url}">{filename}</a></td></tr></table>'
    return (f'<html><table class="sboard_info_tbl"><tr><th>제목</th><td><span class="sboard_info_sbj">{title}</span></td></tr>'
            f'<tr><th>날짜</th><td>{stamp}</td></tr></table><div class="sboard_cont_details"><div class="sboard_cont_details">{body}</div></div>{files}'
            f'<form name="vform"><input name="board_seq" value="1"><input name="board_sub_seq" value="1"><input name="seq" value="{ident}"></form>'
            '<div class="sboard_list_pn">이전 글 제목과 작성일은 본문 아님</div></html>')


def docx(xml):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('word/document.xml', xml)
        z.writestr('word/header1.xml', '<header>과거 금액 999억원</header>')
    return b.getvalue()


class PckBoardTests(unittest.TestCase):
    def test_canonical_identity_ignores_search_presentation_but_not_board(self):
        url=detail_url(990001)
        self.assertEqual(pck.canonical_notice(url+'&page=8&search_text=위탁&lef=05'),url)
        for bad in [url.replace('https:', 'http:'), url.replace('pension.or.kr','evil.example'),
                    url+'&seq=990002', url+'&board_seq=2', url.replace('board_sub_seq=1','board_sub_seq=2')]:
            with self.subTest(url=bad),self.assertRaises(ValueError):pck.canonical_notice(bad)

    def test_listing_replays_dates_and_stable_urls_including_pinned_unmatched_search(self):
        rows=pck.parse_listing(listing([(990001,TITLE,'2026-10-22',False),(990002,'다른 상시 안내','2020-01-01',True)]),URL,CONFIG)
        self.assertEqual(rows[0]['url'],detail_url(990001))
        self.assertEqual(rows[0]['source_id'],'pck_pension:990001')
        self.assertTrue(rows[1]['pinned'])

    def test_wrong_echo_missing_markup_unrelated_row_and_date_fail(self):
        good=listing([(990001,TITLE,'2026-10-22',False)])
        for bad in [good.replace('name="board_seq" value="1"','name="board_seq" value="2"'),
                    good.replace('name="search_text" value="위탁"','name="search_text" value=""'),
                    good.replace('name="page" value="1"','name="page" value="2"'),good.replace('</html>',''),
                    good.replace(TITLE,'뉴스레터'),good.replace('2026-10-22','2026-02-30')]:
            with self.subTest(html=bad),self.assertRaises(ValueError):pck.parse_listing(bad,URL,CONFIG)

    def test_pinned_only_zero_page_is_valid_but_missing_rows_on_normal_page_is_not(self):
        html=listing([(990001,TITLE,'2026-10-22',True)],last=0)
        self.assertEqual(pck.last_page(html,URL,CONFIG),1)
        self.assertEqual(len(pck.parse_listing(html,URL,CONFIG)),1)
        with self.assertRaises(ValueError):pck.parse_listing(listing([],last=1),URL,CONFIG)

    def test_detail_uses_own_metadata_content_and_observed_attachment(self):
        n=pck.parse_detail(detail(990001,filename='위탁운용사 선정 계획.docx'),detail_url(990001),CONFIG)
        self.assertEqual(n['body'],'새 공식 모집 본문')
        self.assertEqual(n['date'],'2026-10-22')
        self.assertEqual(n['attachments'][0]['name'],'위탁운용사 선정 계획.docx')
        self.assertNotIn('이전 글',n['body'])

    def test_foreign_attachment_wrong_notice_and_unobserved_filename_fail(self):
        html=detail(990001,filename='공고.docx')
        for bad in [html.replace('name="seq" value="990001"','name="seq" value="990002"'),
                    html.replace('href="download.asp?','href="https://evil.example/download.asp?'),
                    html.replace('filename=%EA%B3%B5%EA%B3%A0.docx','filename=other.docx'),
                    html.replace('</html>','')]:
            with self.subTest(html=bad),self.assertRaises(ValueError):pck.parse_detail(bad,detail_url(990001),CONFIG)

    def test_discovery_fetches_new_id_without_registry_and_replays_receipts(self):
        def fetch(url,referer=None):
            if 'read.asp' in url:
                ident=parse_qs(urlsplit(url).query)['seq'][0]
                return detail(ident).encode()
            page=int(parse_qs(urlsplit(url).query)['page'][0])
            return listing([(990001,TITLE,'2026-10-22',False)] if page==1 else [(880001,TITLE,'2024-01-01',False)],page=page).encode()
        r=boards.collect({'pck_pension':CONFIG},fetch_factory=lambda c:fetch,checked_at='2026-10-25T00:00:00+00:00')
        self.assertFalse(r['holds'])
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(boards.validate_notice(r['notices'][0],r['checked_at'],CONFIG),r['notices'][0])
        forged=copy.deepcopy(r['notices'][0]);forged['body']='위조 금액'
        with self.assertRaises(ValueError):boards.validate_notice(forged,r['checked_at'],CONFIG)


class DocxBodyTests(unittest.TestCase):
    prefix='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    suffix='</w:body></w:document>'
    def read(self,body):return extract_attachment(docx(self.prefix+body+self.suffix))

    def test_offering_body_and_table_exclude_hidden_deleted_header_and_field_text(self):
        r=self.read('<w:p><w:r><w:t>국내 PE 블라인드</w:t></w:r><w:r><w:rPr><w:vanish/></w:rPr><w:t>999억</w:t></w:r>'
                    '<w:del><w:r><w:t>과거 500억</w:t></w:r></w:del><w:r><w:instrText>외부 필드</w:instrText></w:r></w:p>'
                    '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>선정 수</w:t></w:r></w:p></w:tc>'
                    '<w:tc><w:p><w:r><w:t>2개사</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
        self.assertEqual(r['format'],'docx');self.assertIn('선정 수\t2개사',r['text'])
        for excluded in ('999','과거','외부 필드'):self.assertNotIn(excluded,r['text'])
        self.assertEqual(r['tables'],[[['선정 수','2개사']]])

    def test_wrong_root_entities_empty_body_and_oversized_body_fail(self):
        for xml in ['<document>가짜 문서</document>',self.prefix+self.suffix,
                    '<!DOCTYPE x [<!ENTITY e "fake">]>'+self.prefix+'<w:p>&e;</w:p>'+self.suffix,
                    self.prefix+('x'*(8*1024*1024+1))+self.suffix]:
            with self.subTest(length=len(xml)),self.assertRaises(ValueError):extract_attachment(docx(xml))

    def test_merged_table_keeps_text_without_inventing_column_coordinates(self):
        r=self.read('<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
                    '<w:p><w:r><w:t>합쳐진 셀</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
        self.assertIn('합쳐진 셀',r['text']);self.assertEqual(r['tables'],[])


if __name__=='__main__':unittest.main()
