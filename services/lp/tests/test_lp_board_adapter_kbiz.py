"""Sanitized observed KBIZ markup; no live requests."""
import unittest
from services.lp.src import lp_board_adapter_kbiz as kbiz

CONFIG = {'institution_id': 'kbiz', 'listing_url': kbiz.BASE + 'list.do?mnSeq=211'}
URL = CONFIG['listing_url'] + '&schFld=ttl&schTxt=PE&pg=1'
ROW = '''<tr><td>1</td><td class="subject"><span onclick="goView(123, 'N')">국내 PE 펀드 모집</span></td><td>파일</td><td>2026.07.10</td></tr>'''
HTML = '''<html><input name="mnSeq" value="211"><input name="schFld" value="ttl"><input name="schTxt" value="PE">
<table><thead><tr><th>번호</th><th>제목</th><th>첨부파일</th><th>등록일</th></tr></thead><tbody>''' + ROW + '''</tbody></table>
<script>pager("./list.do", 1, 10, "mnSeq=211\\u0026schFld=ttl\\u0026schTxt=PE", "1");</script></html>'''
DETAIL_URL = kbiz.BASE + 'view.do?seq=123&topFixYn=N&mnSeq=211'
DETAIL = '''<html><div id="contents"><div class="subject-wrap"><strong>[사업공고] 국내 펀드 모집</strong>
<div class="date-flex"><em class="date">등록일 2026.07.10</em></div></div>
<div class="file-wrap"><ul><li><em><img alt="첨부파일">선정계획.hwp(160 KB)</em>
<a href="/download.do?orgalFle=6162&saveFle=123456.hwp&fleDwnDs=bbsAttachFile&seq=456">다운로드</a></li></ul></div>
<div class="detail-body"><p>국내 블라인드 펀드 위탁운용사 선정계획을 다음과 같이 공고합니다. PE 및 VC 부문에 지원할 수 있습니다.</p></div>
<div class="navigation">다음글 사모펀드의 다른 선정 결과입니다.</div></div>
<script>function goList(){move("./list.do?mnSeq=" + ["211"] + "&" + "seq=123\\u0026topFixYn=N");}</script></html>'''


class KbizTests(unittest.TestCase):
    def test_detail_preserves_title_body_url_and_attachment(self):
        n = kbiz.parse_detail(DETAIL, DETAIL_URL, CONFIG)
        self.assertEqual(n['title'], '[사업공고] 국내 펀드 모집')
        self.assertEqual(n['url'], DETAIL_URL)
        self.assertEqual(n['date'], '2026-07-10')
        self.assertNotIn('다음글', n['body'])
        self.assertEqual(n['attachments'][0]['name'], '선정계획.hwp')
        nofile = DETAIL[:DETAIL.index('<div class="file-wrap">')] + DETAIL[DETAIL.index('<div class="detail-body">'):]
        self.assertEqual(kbiz.parse_detail(nofile, DETAIL_URL, CONFIG)['attachments'], [])

    def test_detail_identity_and_download_boundaries(self):
        for old, new in [('seq=123\\u0026', 'seq=124\\u0026'), ('id="contents"', 'id="other"'),
                         ('/download.do?', 'https://evil.example/download.do?'), ('saveFle=123456.hwp', 'saveFle=../private.hwp'),
                         ('fleDwnDs=bbsAttachFile', 'fleDwnDs=other'), ('seq=456', 'seq=456&seq=789'),
                         ('2026.07.10', '2026.02.30'), ('</html>', '')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                kbiz.parse_detail(DETAIL.replace(old, new), DETAIL_URL, CONFIG)
        with self.assertRaises(ValueError):
            kbiz.parse_detail(DETAIL, DETAIL_URL.replace('seq=123', 'seq=124'), CONFIG)

    def test_title_comparison_only_omitted_observed_category(self):
        self.assertTrue(kbiz.titles_match('국내 펀드 모집', '[사업공고] 국내 펀드 모집'))
        for a, b in [('[사업공고] 국내 펀드 모집', '[입찰공고] 국내 펀드 모집'),
                     ('국내 펀드 모집', '[재공고] 국내 펀드 모집'),
                     ('2025 국내 펀드 모집', '[사업공고] 2026 국내 펀드 모집')]:
            self.assertFalse(kbiz.titles_match(a, b))

    def test_rows_and_official_pagination(self):
        rows = kbiz.parse_listing(HTML, URL, CONFIG)
        self.assertEqual(rows[0]['date'], '2026-07-10')
        self.assertEqual(rows[0]['url'], kbiz.BASE + 'view.do?seq=123&topFixYn=N&mnSeq=211')
        self.assertEqual(kbiz.last_page(HTML, URL, CONFIG), 1)
        self.assertEqual(kbiz.last_page(HTML.replace('1, 10,', '17, 10,'), URL, CONFIG), 2)

    def test_pinned_row_is_not_counted_as_normal_result(self):
        pinned = ROW.replace('<tr>', '<tr class="notice">').replace('123', '456').replace("'N'", "'Y'").replace('<td>1</td>', '<td><img alt="공지"></td>')
        rows = kbiz.parse_listing(HTML.replace(ROW, pinned + ROW), URL, CONFIG)
        self.assertEqual([r['pinned'] for r in rows], [True, False])

    def test_search_route_and_echo_guards(self):
        for target in [URL.replace('www.kbiz.or.kr', 'evil.example'), URL.replace('211', '212'), URL + '&pg=2', URL.replace('pg=1', 'pg=2')]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                kbiz.parse_listing(HTML, target, CONFIG)
        for old, new in [('value="PE"', 'value="VC"'), ('schTxt=PE', 'schTxt=VC'), ('1, 10,', '1, 0,'), ('등록일', '수정일')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                kbiz.parse_listing(HTML.replace(old, new), URL, CONFIG)

    def test_incomplete_and_duplicate_rows_stay_visible_failures(self):
        for html in [HTML.replace(ROW, ''), HTML.replace(ROW, ROW + ROW), HTML.replace('</html>', ''),
                     HTML.replace('2026.07.10', '2026.02.30'), HTML.replace("'N'", "'Y'"),
                     HTML.replace(ROW, '<tr><td>게시물이 없습니다.</td></tr>')]:
            with self.subTest(html=html[:30]), self.assertRaises(ValueError):
                kbiz.parse_listing(html, URL, CONFIG)


if __name__ == '__main__':
    unittest.main()
