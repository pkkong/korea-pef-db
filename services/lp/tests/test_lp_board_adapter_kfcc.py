"""KFCC official controls and lossless offering table boundaries."""
import unittest
from urllib.parse import parse_qs, unquote, urlsplit
from services.lp.src.lp_board_adapter_kfcc import parse_listing, parse_detail

BASE = 'https://www.kfcc.co.kr'
LIST = BASE + '/mgNotice/mgNoticeList.do?schType=subject&schValue=운용사&pageNo=1'
CONFIG = {'institution_id': 'kfcc', 'listing_url': BASE + '/mgNotice/mgNoticeList.do?schType=subject'}
DETAIL = BASE + '/mgNotice/mgNoticeDetail.do?no=880012'
TITLE = '2025년 위탁펀드형 대체투자 운용사 선정 공고'


def listing(row=None):
    row = '<li><div class="info"><a href="javascript:fnDetail(\'880012\')">' + TITLE + '</a></div><div class="date">2025.04.30</div></li>' if row is None else row
    return '<html><script>function fnDetail(no){var f=document.brdForm;f.no.value=no;f.action="/mgNotice/mgNoticeDetail.do";f.submit();}</script><form name="brdForm"><input name="no"><input name="pageNo" value="1"></form><ul class="magazine"><li class="top">제목 등록일</li>' + row + '</ul></html>'


def detail(body=None, attachments=''):
    body = '<p>PE 부문 선정 개요</p><p>국내 기관전용 사모 집합투자기구</p><p>운용 방식: 위탁펀드형 대체투자 (블라인드형)</p>' if body is None else body
    return '<html><form name="sltForm"><input name="no" value="880012"></form><div class="bbs-view"><div class="info-area"><span class="title">' + TITLE + '</span><div class="date">2025.04.30<button>인쇄</button></div></div><div class="con">' + body + '</div>' + attachments + '</div></html>'


class KfccBoardAdapterTests(unittest.TestCase):
    def test_observed_notice_identifier_and_exact_title_date(self):
        rows = parse_listing(listing(), LIST, CONFIG)
        self.assertEqual(rows, [{'url': DETAIL, 'title': TITLE, 'date': '2025-04-30', 'source_id': 'kfcc:880012'}])

    def test_new_notice_id_requires_no_manual_registry(self):
        rows = parse_listing(listing().replace('880012', '990057'), LIST, CONFIG)
        self.assertEqual(rows[0]['source_id'], 'kfcc:990057')

    def test_foreign_host_and_wrong_board_rejected(self):
        for url in (LIST.replace('www.kfcc.co.kr', 'evil.example'), LIST.replace('/mgNotice/', '/noticeofTender/')):
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_listing(listing(), url, CONFIG)

    def test_observed_action_must_match_board_and_assign_form_id(self):
        for html in (listing().replace('f.no.value=no;', ''), listing().replace('f.action="/mgNotice/mgNoticeDetail.do"', 'f.action="https://evil.example/detail"')):
            with self.subTest(html=html[:100]), self.assertRaises(ValueError):
                parse_listing(html, LIST, CONFIG)

    def test_explicit_empty_board_is_healthy(self):
        self.assertEqual(parse_listing(listing('<li>해당 내역이 없습니다.</li>'), LIST, CONFIG), [])

    def test_unexplained_empty_or_bot_page_is_not_healthy(self):
        for html in (listing(''), '<html>접근 차단</html>', listing()[:-7]):
            with self.subTest(html=html[:30]), self.assertRaises(ValueError):
                parse_listing(html, LIST, CONFIG)

    def test_missing_or_invalid_publication_date_fails(self):
        for html in (listing().replace('2025.04.30', ''), listing().replace('2025.04.30', '2025.02.30')):
            with self.subTest(html=html[-80:]), self.assertRaises(ValueError):
                parse_listing(html, LIST, CONFIG)

    def test_foreign_or_unobserved_row_control_rejected(self):
        for href in ('https://evil.example/notice', "javascript:fnDetail('not-numeric')"):
            html = listing().replace("javascript:fnDetail('880012')", href)
            with self.subTest(href=href), self.assertRaises(ValueError):
                parse_listing(html, LIST, CONFIG)

    def test_detail_title_body_and_source_year_preserved(self):
        result = parse_detail(detail(), DETAIL, CONFIG)
        self.assertEqual(result['title'], TITLE)
        self.assertEqual(result['date'], '2025-04-30')
        self.assertIn('블라인드형', result['body'])
        self.assertNotIn('인쇄', result['body'])

    def test_detail_form_identifier_binds_receipt_to_requested_notice(self):
        with self.assertRaises(ValueError):
            parse_detail(detail().replace('value="880012"', 'value="990057"'), DETAIL, CONFIG)

    def test_rowspan_labels_and_table_columns_are_preserved(self):
        table = '<p>1. PE 부문선정개요</p><table><tr><td colspan="2">구분</td><td>전략</td><td>선정수</td><td>총위탁금액</td></tr><tr><td rowspan="2">국 내</td><td rowspan="2">PE</td><td>Special Situation</td><td>2개사</td><td>1,200억원</td></tr><tr><td>Buyout, Growth</td><td>8개사</td><td>3,200억원</td></tr></table><p>2. VC 부문 선정 개요</p><table><tr><td>국 내</td><td>PE</td><td>2개사</td><td>600억원</td></tr></table>'
        result = parse_detail(detail(table), DETAIL, CONFIG)
        self.assertIn('국 내\tPE\tSpecial Situation\t2개사\t1,200억원', result['body'])
        self.assertIn('국 내\tPE\tBuyout, Growth\t8개사\t3,200억원', result['body'])
        self.assertIn('2. VC 부문 선정 개요\n국 내\tPE\t2개사\t600억원', result['body'], 'VC section boundary must survive independent of its source table typo')
        self.assertNotIn('commitment_amount_krw', result)

    def test_incomplete_or_overlapping_table_is_rejected(self):
        for table in ('<table><tr><td>A</td><td>B</td></tr><tr><td>one</td></tr></table>', '<table><tr><td rowspan="2">A</td></tr></table>'):
            with self.subTest(table=table), self.assertRaises(ValueError):
                parse_detail(detail(table), DETAIL, CONFIG)

    def test_attachment_url_uses_observed_download_formula_and_same_host(self):
        button = '<button onclick="fnDownload(\'A01\',\'880012\',\'2\',\'공고안_987.hwp\');">공고안</button>'
        result = parse_detail(detail(attachments=button), DETAIL, CONFIG)
        self.assertEqual(result['attachments'][0]['name'], '공고안_987.hwp')
        self.assertEqual(unquote(result['attachments'][0]['url']), BASE + '/upload/neoboard/A01/공고안_987.hwp')

    def test_attachment_board_notice_or_traversal_mismatch_rejected(self):
        for board, ident, name in [('A02', '880012', '공고.hwp'), ('A01', '990057', '공고.hwp'), ('A01', '880012', '../공고.hwp')]:
            button = '<button onclick="fnDownload(\'' + board + '\',\'' + ident + '\',\'2\',\'' + name + '\');">파일</button>'
            with self.subTest(board=board, ident=ident, name=name), self.assertRaises(ValueError):
                parse_detail(detail(attachments=button), DETAIL, CONFIG)

    def test_submission_form_names_are_preserved_for_collector_filtering(self):
        button = '<button onclick="fnDownload(\'A01\',\'880012\',\'3\',\'제안서_양식.hwp\');">양식</button>'
        result = parse_detail(detail(attachments=button), DETAIL, CONFIG)
        self.assertEqual(result['attachments'][0]['name'], '제안서_양식.hwp')
        self.assertNotIn('제안서_양식', result['body'])


if __name__ == '__main__':
    unittest.main()
