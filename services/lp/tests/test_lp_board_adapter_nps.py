import unittest
from services.lp.src import lp_board_adapter_nps as n

CONFIG={'institution_id':'nps','listing_url':n.BASE+n.LIST}
PID='ZZ209900000000001234'
URL=n.BASE+n.DETAIL+'?pstId='+PID+'&hmpgBbsCd=BS20990001'
SCRIPT='function fncAtchFileDownload(atchFileId, atchFileSn) { let url = "/fileDown.do?atchFileId=" + atchFileId + "&atchFileSn=" + atchFileSn; window.open(url,"_blank"); }'


def listing(page=1):
    total=1 if page==1 else 11
    return f'''<html><form id="searchForm"><input name="pageIndex" value="{page}"><input name="searchGbu" value=""><input name="searchText" value=""></form><span class="total">총 {total}건</span><table><caption>거래기관 선정공고 목록</caption><tr><td class="title"><a href="javascript:fnc_goBbsDetail('{PID}', 'BS20990001');">2099년 국내 사모투자 모집</a></td><td class="date">2099/02/03</td></tr></table><a class="num current" data-pagenum="{page}">{page}</a></html>'''


def detail():
    return '''<html><script src="/js/common_utils.js"></script><div class="data-view-wrap"><strong class="view-title">국내 사모투자 모집</strong><ul><li><span class="label">등록일</span><span class="data">2099/02/03</span></li></ul><div class="view-info-table">공고번호 (사모)2099-1호</div><div class="data-view-contents">본문입니다.</div><div class="file-item"><p class="a-file">공고.pdf</p><a class="btn-file-down" href="javascript:fncAtchFileDownload('FL99999999', '1');">다운로드</a></div></div></html>'''


class NpsAdapterTests(unittest.TestCase):
    def test_arbitrary_ids_listing_and_post_mapping(self):
        rows=n.parse_listing(listing(),CONFIG['listing_url'],CONFIG)
        self.assertEqual(rows[0]['date'],'2099-02-03')
        self.assertEqual(rows[0]['url'],URL)
        self.assertEqual(n.last_page(listing(),CONFIG['listing_url'],CONFIG),1)
        req=n.request_plan(rows[0]['url'],CONFIG)
        self.assertEqual(req['method'],'POST');self.assertEqual(req['fields']['pstId'],PID)
        self.assertEqual(n.request_plan(CONFIG['listing_url']+'?pageIndex=2',CONFIG)['fields']['pageIndex'],2)

    def test_fragment_page_two_echo_and_counts(self):
        html=listing(2).replace('<html>','').replace('</html>','<!-- 서브내용 끝 -->')
        self.assertEqual(n.last_page(html,CONFIG['listing_url']+'?pageIndex=2',CONFIG),2)
        self.assertEqual(len(n.parse_listing(html,CONFIG['listing_url']+'?pageIndex=2',CONFIG)),1)
        for bad in (html.replace('value="2"','value="1"'),html.replace('총 11건','총 12건'),html.replace('data-pagenum="2"','data-pagenum="1"'),html[:-10]):
            with self.assertRaises(ValueError):n.parse_listing(bad,CONFIG['listing_url']+'?pageIndex=2',CONFIG)

    def test_detail_metadata_and_verified_attachments(self):
        d=n.parse_detail(detail(),URL,CONFIG,resolver_script=SCRIPT)
        self.assertEqual(d['date'],'2099-02-03');self.assertIn('공고번호',d['body'])
        self.assertEqual(d['attachments'][0]['url'],n.BASE+'/fileDown.do?atchFileId=FL99999999&atchFileSn=1')
        self.assertNotIn('scope',d)
        self.assertTrue(n.parse_detail(detail(),URL,CONFIG)['unresolved_attachments'])
        self.assertEqual(n.attachment_request(detail(),URL,CONFIG),n.SCRIPT)
        with self.assertRaises(ValueError):n.parse_detail(detail(),URL,CONFIG,resolver_script=SCRIPT.replace('/fileDown.do','/wrong.do'))

    def test_false_empty_malformed_date_foreign_duplicate_rejected(self):
        for bad in (listing().replace('총 1건','총 0건'),listing().replace('2099/02/03','2099/02/30'),listing().replace('</table>','<tr><td>missing metadata</td></tr></table>')):
            with self.assertRaises(ValueError):n.parse_listing(bad,CONFIG['listing_url'],CONFIG)
        for url in (URL.replace('fund.nps.or.kr','evil.invalid'),URL+'&pstId='+PID,URL.replace('ZZ','../'),URL.replace('https:','http:')):
            with self.assertRaises(ValueError):n.request_plan(url,CONFIG)
        with self.assertRaises(ValueError):n.parse_detail(detail().replace('FL99999999','../bad'),URL,CONFIG,resolver_script=SCRIPT)

if __name__=='__main__':unittest.main()
