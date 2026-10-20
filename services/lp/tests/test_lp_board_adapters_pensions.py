"""Minimal, sanitized structures observed on actual TP and CU public pages."""
import unittest

from services.lp.src.lp_board_adapters_pensions import parse_detail, parse_listing

TP = {'institution_id': 'tp', 'listing_url': 'https://www.tp.or.kr/tp-kr/bbs/i-151/list.do'}
CU = {'institution_id': 'cu', 'listing_url': 'https://www.cu.co.kr/cu/na/ntt/selectNttList.do?bbsId=1020&mi=100007'}
TP_TITLE = '2023년 사학연금 국내 PEF 블라인드펀드 위탁운용사 선정 공고'
CU_TITLE = '2025년 신협중앙회 국내 기업형 블라인드펀드 위탁운용사(중형PE) 선정 공고'
TP_URL = 'https://www.tp.or.kr/tp-kr/bbs/i-151/detail.do?ntt_sn=87654'
CU_URL = 'https://www.cu.co.kr/cu/na/ntt/selectNttInfo.do?nttSn=76543&mi=100007'
# IDs are arbitrary: parsers must follow hrefs rather than a selected notice list.
TP_ROW = '<div class="tit_box"><a href="./detail.do?ntt_sn=87654" class="tit">' + TP_TITLE + '</a><ul class="list_dia"><li>담당부서 : 기업금융팀</li><li><span>등록일 : </span>2023.07.24</li></ul></div>'
CU_ROW = '<tr><td>5</td><td class="bbs_tit"><a href="/cu/na/ntt/selectNttInfo.do?nttSn=76543&amp;mi=100007">' + CU_TITLE + '</a></td><td>정**</td><td data-table="date">2025.07.14</td><td>100</td></tr>'
TP_LIST = '<form id="frmBbs"><div class="board_wrap">' + TP_ROW + '</div></form>'
CU_LIST = '<input name="bbsId" value="1020"><div class="bbs_ListA"><table><tbody>' + CU_ROW + '</tbody></table></div>'
TP_DETAIL = '<div class="tit_box"><span class="tit txt_full">' + TP_TITLE + '</span><ul class="list_dia"><li>등록일 : 2023.07.24</li></ul></div><div class="view_wrap"><div class="nostyle"><p>국내 PEF 블라인드펀드 위탁운용사를 모집합니다.</p><p>제안서 접수 마감일 : 2023.8.14. 16:00</p></div></div><div class="attachments"><a href="./down.do?bbs_id=tp-1003&amp;atfile_sn=1&amp;data_ty_cd=A&amp;ntt_sn=87654">선정 공고.zip <span>[다운로드]</span></a></div>'
CU_DETAIL = '<form id="nttViewForm"><input name="bbsId" value="1020"><input name="nttSn" value="76543"><div class="bbs_ViewA"><h3>' + CU_TITLE + '</h3><ul class="bbsV_data"><li><strong>작성일</strong>2025.07.14</li><li>조회수 200</li></ul><div class="bbsV_cont"><p><img src="/upload/editor/notice.png" alt="' + CU_TITLE + ' 상세 내용은 첨부파일 참조"></p></div><ul class="bbsV_file"><li><a href="/common/nttFileDownload.do?fileKey=abcdef0123456789abcdef0123456789">붙임1. 선정 공고.pdf (다운로드 : 1,000회)</a><a href="javascript:htmlDocTransView()">[바로보기]</a></li></ul></div></form><form id="nttFileViewForm"><input name="bbsId" value="N"><input name="nttSn" value="N"></form>'


class PensionBoardAdaptersTests(unittest.TestCase):
    def test_tp_listing_retains_observed_date_and_id(self):
        rows = parse_listing(TP_LIST, TP['listing_url'], TP)
        self.assertEqual(rows, [{'url': TP_URL, 'title': TP_TITLE, 'date': '2023-07-24', 'source_id': 'tp:87654'}])

    def test_cu_listing_retains_medium_track_without_2026_inference(self):
        rows = parse_listing(CU_LIST, CU['listing_url'], CU)
        self.assertEqual(rows, [{'url': CU_URL, 'title': CU_TITLE, 'date': '2025-07-14', 'source_id': 'cu:76543'}])

    def test_explicit_empty_pages_are_successfully_empty(self):
        cases = [('<form id="frmBbs"><div class="no-data"><strong>공지사항 데이터가 없습니다.</strong></div></form>', TP),
                 ('<div class="bbs_ListA"><table><tbody><tr class="no_date"><td>등록된 글이 없습니다.</td></tr></tbody></table></div>', CU)]
        for html, config in cases:
            with self.subTest(institution=config['institution_id']):
                self.assertEqual(parse_listing(html, config['listing_url'], config), [])

    def test_blank_or_menu_empty_message_is_not_a_valid_empty_board(self):
        for html in ['', '<html><body>로그인</body></html>', '<script>msg="공지사항 데이터가 없습니다.";</script>', '<form id="frmBbs"><div class="board_wrap"></div></form>']:
            with self.subTest(html=html):
                with self.assertRaises(ValueError):
                    parse_listing(html, TP['listing_url'], TP)
        with self.assertRaises(ValueError):
            parse_listing('<div class="bbs_ListA"><table></table></div>', CU['listing_url'], CU)

    def test_foreign_host_other_board_and_downgrade_are_rejected(self):
        for config, html, bad in [(TP, TP_LIST, 'https://other.example/tp-kr/bbs/i-151/detail.do?ntt_sn=87654'),
                                  (TP, TP_LIST, '/tp-kr/bbs/i-999/detail.do?ntt_sn=87654'),
                                  (CU, CU_LIST, 'https://www.cu.co.kr/cu/na/ntt/selectNttInfo.do?nttSn=76543&mi=100008'),
                                  (CU, CU_LIST, 'http://www.cu.co.kr/cu/na/ntt/selectNttInfo.do?nttSn=76543&mi=100007')]:
            old = './detail.do?ntt_sn=87654' if config is TP else '/cu/na/ntt/selectNttInfo.do?nttSn=76543&amp;mi=100007'
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_listing(html.replace(old, bad), config['listing_url'], config)

    def test_duplicate_rows_deduplicate_and_conflicting_metadata_fails(self):
        html = TP_LIST.replace(TP_ROW, TP_ROW + TP_ROW)
        self.assertEqual(len(parse_listing(html, TP['listing_url'], TP)), 1)
        with self.assertRaises(ValueError):
            parse_listing(TP_LIST.replace(TP_ROW, TP_ROW + TP_ROW.replace('2023.07.24', '2023.07.25')), TP['listing_url'], TP)

    def test_missing_and_impossible_publication_dates_fail(self):
        for old, new in [('2023.07.24', ''), ('2023.07.24', '2023.02.30')]:
            with self.subTest(value=new):
                with self.assertRaises(ValueError):
                    parse_listing(TP_LIST.replace(old, new), TP['listing_url'], TP)

    def test_tp_detail_returns_actual_body_and_observed_zip_link(self):
        data = parse_detail(TP_DETAIL, TP_URL, TP)
        self.assertEqual((data['title'], data['date']), (TP_TITLE, '2023-07-24'))
        self.assertIn('2023.8.14.', data['body'])
        self.assertEqual(data['attachments'], [{'url': 'https://www.tp.or.kr/tp-kr/bbs/i-151/down.do?bbs_id=tp-1003&atfile_sn=1&data_ty_cd=A&ntt_sn=87654', 'name': '선정 공고.zip'}])

    def test_cu_image_alt_is_body_and_preview_placeholder_is_not_a_board_id(self):
        data = parse_detail(CU_DETAIL, CU_URL, CU)
        self.assertEqual((data['title'], data['date']), (CU_TITLE, '2025-07-14'))
        self.assertIn(CU_TITLE, data['body'])
        self.assertEqual(data['attachments'], [{'url': 'https://www.cu.co.kr/common/nttFileDownload.do?fileKey=abcdef0123456789abcdef0123456789', 'name': '붙임1. 선정 공고.pdf'}])

    def test_detail_wrong_board_or_notice_binding_fails(self):
        for old, new in [('value="1020"', 'value="1021"'), ('value="76543"', 'value="76544"')]:
            with self.subTest(replacement=new):
                with self.assertRaises(ValueError):
                    parse_detail(CU_DETAIL.replace(old, new), CU_URL, CU)

    def test_tp_download_must_be_same_board_and_notice(self):
        for old, new in [('ntt_sn=87654', 'ntt_sn=87655'), ('bbs_id=tp-1003', 'bbs_id=other'), ('./down.do?', 'https://other.example/down.do?')]:
            with self.subTest(replacement=new):
                with self.assertRaises(ValueError):
                    parse_detail(TP_DETAIL.replace(old, new), TP_URL, TP)

    def test_empty_body_is_not_replaced_with_navigation_text(self):
        with self.assertRaises(ValueError):
            parse_detail(CU_DETAIL.replace('alt="' + CU_TITLE + ' 상세 내용은 첨부파일 참조"', 'alt=""'), CU_URL, CU)


if __name__ == '__main__':
    unittest.main()
