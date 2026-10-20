"""Mutual-aid official board formats, independent of individual notice IDs."""
import copy
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from services.lp.src.lp_board_adapters_mutuals import parse_detail, parse_listing

POBA = 'https://www.poba.or.kr/bbs/selectNttList?sechBbsSeq=10'
PMAA = 'https://www.pmaa.or.kr/www/1461128463820/bbs.do'
PC = {'institution_id': 'poba', 'listing_url': POBA}
MC = {'institution_id': 'pmaa', 'listing_url': PMAA}


def poba_html(*, rows=None, total=1, page=1, detail=False):
    item = {'bbstSeq': 880012, 'bbsSeq': 10, 'bbstSj': '2026년 국내 PE 블라인드 위탁운용사 선정 계획 공고', 'rgstDt': '2026-09-01', 'bbstCten': '<p>모집전략 Buyout·Growth / 공동투자</p>'}
    data = {'bbsMastDvo': {'bbsSeq': 10}, 'nttPvo': {'pageIndex': page}, 'nttDvoList': [item] if rows is None else rows, 'allCnt': total, 'nttDvo': item if detail else None, 'atchDvoList': []}
    return '<html><script>var bbsMap = ' + json.dumps({'bbsDvo': data}, ensure_ascii=False) + ';</script></html>'


def poba_json(html):
    return json.loads(html.split('var bbsMap = ', 1)[1].split(';</script>', 1)[0])


def rewrap(data, extra=''):
    return '<html><script>var bbsMap = ' + json.dumps(data, ensure_ascii=False) + ';</script>' + extra + '</html>'


def pmaa_list(rows=None):
    headings = '<thead><tr><th>번호</th><th>제목</th><th>작성자</th><th>작성일</th><th>조회수</th></tr></thead>'
    if rows is None:
        rows = '<tr><td>1</td><td><a href="#" onclick="fn_view(\'770021\'); return false;">[위탁운용사 공고] 국내 PE·VC 블라인드 선정 공고</a></td><td>경찰공제회</td><td>2026-09-02</td><td>1</td></tr>'
    return '<html><table class="tb_list">' + headings + '<tbody>' + rows + '</tbody></table></html>'


def pmaa_detail(extra=''):
    return '<html><table class="tb_view"><caption>국내 PE·VC 위탁 운용사 선정 공고<span class="date">2026-09-02</span></caption><tr><td>' + extra + '</td></tr></table><div class="bbs_article"><p>국내 PE·VC 블라인드 펀드</p><p>PE 부문 1,200억원 / VC 부문 600억원</p></div></html>'


class MutualBoardAdapterTests(unittest.TestCase):
    def test_poba_discovers_observed_json_ids_and_preserves_title(self):
        rows = parse_listing(poba_html(), POBA, PC)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['source_id'], 'poba:880012')
        self.assertEqual(rows[0]['date'], '2026-09-01')
        self.assertEqual(parse_qs(urlsplit(rows[0]['url']).query), {'sechBbsSeq': ['10'], 'sechBbstSeq': ['880012']})
        self.assertIn('국내 PE 블라인드', rows[0]['title'])

    def test_poba_arbitrary_future_notice_id_is_discovered_without_registry(self):
        data = poba_json(poba_html())
        data['bbsDvo']['nttDvoList'][0]['bbstSeq'] = 991573
        rows = parse_listing(rewrap(data), POBA, PC)
        self.assertEqual(rows[0]['source_id'], 'poba:991573')

    def test_poba_wrong_board_in_url_or_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_listing(poba_html(), POBA.replace('=10', '=11'), PC)
        data = poba_json(poba_html())
        data['bbsDvo']['bbsMastDvo']['bbsSeq'] = 11
        with self.assertRaises(ValueError):
            parse_listing(rewrap(data), POBA, PC)

    def test_poba_pagination_response_must_match_requested_page(self):
        with self.assertRaises(ValueError):
            parse_listing(poba_html(), POBA + '&pageIndex=2', PC)
        self.assertEqual(len(parse_listing(poba_html(page=2), POBA + '&pageIndex=2', PC)), 1)

    def test_poba_explicit_zero_total_is_empty_not_parser_failure(self):
        self.assertEqual(parse_listing(poba_html(rows=[], total=0), POBA, PC), [])
        with self.assertRaises(ValueError):
            parse_listing(poba_html(rows=[], total=5), POBA, PC)

    def test_poba_partial_json_or_bot_page_cannot_be_empty_success(self):
        for html in (poba_html()[:-7], '<html>서비스 접속이 차단 되었습니다.</html>', '<html><script>var bbsMap={</script></html>'):
            with self.subTest(html=html[:40]), self.assertRaises((ValueError, KeyError)):
                parse_listing(html, POBA, PC)

    def test_poba_detail_and_attachments_use_only_observed_download_arguments(self):
        data = poba_json(poba_html(detail=True))
        data['bbsDvo']['atchDvoList'] = [{'bbstSeq': 880012, 'atchFileSeq': 'YWJjLzEyMw==', 'realAtchFileNm': '공고문.pdf'}]
        control = '<script>function fnFileDownLoad(token) {\nvar url = "/bbs/downloadDetail";\n}</script>'
        detail = parse_detail(rewrap(data, control), 'https://www.poba.or.kr/bbs/selectNttDetail?sechBbsSeq=10&sechBbstSeq=880012', PC)
        self.assertEqual(detail['body'], '모집전략 Buyout·Growth / 공동투자')
        self.assertEqual(detail['attachments'][0]['name'], '공고문.pdf')
        self.assertEqual(parse_qs(urlsplit(detail['attachments'][0]['url']).query), {'sechAtchFileSeq': ['YWJjLzEyMw=='], 'detailYn': ['Y'], 'bbsSeq': ['10']})

    def test_poba_missing_or_cross_host_download_control_fails(self):
        data = poba_json(poba_html(detail=True))
        data['bbsDvo']['atchDvoList'] = [{'bbstSeq': 880012, 'atchFileSeq': 'YWJj', 'realAtchFileNm': '공고문.pdf'}]
        for control in ('', '<script>function fnFileDownLoad(token) {\nvar url = "https://unrelated.example/download";\n}</script>'):
            with self.subTest(control=control), self.assertRaises(ValueError):
                parse_detail(rewrap(data, control), 'https://www.poba.or.kr/bbs/selectNttDetail?sechBbsSeq=10&sechBbstSeq=880012', PC)

    def test_pmaa_discovers_js_controls_and_exact_publication_dates(self):
        rows = parse_listing(pmaa_list(), PMAA + '?searchType1=TITLE&searchText1=위탁', MC)
        self.assertEqual(rows[0]['source_id'], 'pmaa:770021')
        self.assertEqual(parse_qs(urlsplit(rows[0]['url']).query), {'type': ['view'], 'bbsIdx': ['770021']})
        self.assertEqual(rows[0]['date'], '2026-09-02')
        self.assertIn('PE·VC', rows[0]['title'])

    def test_pmaa_wrong_board_and_foreign_notice_links_fail(self):
        with self.assertRaises(ValueError):
            parse_listing(pmaa_list(), PMAA.replace('1461128463820', '999999'), MC)
        html = pmaa_list().replace('href="#"', 'href="https://unrelated.example/notice"')
        with self.assertRaises(ValueError):
            parse_listing(html, PMAA, MC)

    def test_pmaa_explicit_empty_marker_differs_from_missing_rows(self):
        self.assertEqual(parse_listing(pmaa_list('<tr><td colspan="5">조회된 내용이 없습니다.</td></tr>'), PMAA, MC), [])
        with self.assertRaises(ValueError):
            parse_listing(pmaa_list(''), PMAA, MC)

    def test_pmaa_truncation_or_invalid_control_is_not_accepted(self):
        for html in (pmaa_list()[:-7], pmaa_list().replace("fn_view('770021')", "fn_view('bad')")):
            with self.subTest(html=html[:40]), self.assertRaises(ValueError):
                parse_listing(html, PMAA, MC)

    def test_pmaa_detail_does_not_merge_pe_and_vc_amounts(self):
        detail = parse_detail(pmaa_detail(), PMAA + '?type=view&bbsIdx=770021', MC)
        self.assertEqual(detail['title'], '국내 PE·VC 위탁 운용사 선정 공고')
        self.assertEqual(detail['date'], '2026-09-02')
        self.assertIn('PE 부문 1,200억원 / VC 부문 600억원', detail['body'])
        self.assertEqual(detail['attachments'], [])

    def test_pmaa_download_uses_observed_action_and_named_form_arguments(self):
        anchor = '<a href="#" onclick="fn_www_download2(\'/fileDownload.do\',\'NOTICE\',\'new-file-987.pdf\',\'공고문.pdf\'); return false;">공고문.pdf</a>'
        detail = parse_detail(pmaa_detail(anchor), PMAA + '?type=view&bbsIdx=770021', MC)
        attachment = detail['attachments'][0]
        self.assertEqual(urlsplit(attachment['url']).path, '/fileDownload.do')
        self.assertEqual(parse_qs(urlsplit(attachment['url']).query), {'path': ['NOTICE'], 'physicalName': ['new-file-987.pdf'], 'original': ['공고문.pdf']})

    def test_pmaa_foreign_or_traversal_download_arguments_are_rejected(self):
        for action, physical in [('https://unrelated.example/download', 'offering.pdf'), ('/fileDownload.do', '../offering.pdf')]:
            anchor = '<a href="#" onclick="fn_www_download2(\'' + action + '\',\'NOTICE\',\'' + physical + '\',\'공고문.pdf\'); return false;">공고문.pdf</a>'
            with self.subTest(action=action, physical=physical), self.assertRaises(ValueError):
                parse_detail(pmaa_detail(anchor), PMAA + '?type=view&bbsIdx=770021', MC)

    def test_detail_missing_body_or_date_is_not_publishable(self):
        for html in (pmaa_detail().replace('2026-09-02', '날짜 없음'), pmaa_detail().replace('class="bbs_article"', 'class="unrelated"')):
            with self.subTest(html=html[:50]), self.assertRaises(ValueError):
                parse_detail(html, PMAA + '?type=view&bbsIdx=770021', MC)


if __name__ == '__main__':
    unittest.main()
