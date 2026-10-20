"""Sanitized fixtures preserving observed KDB/IBK structure, no network calls."""
import copy
import json
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from services.lp.src.lp_board_adapters_banks import listing_requests, parse_detail, parse_listing

KDB = {'institution_id': 'kdb', 'listing_url': 'https://www.kdb.co.kr/CHBIPR23N00.act?_mnuId=IHIHIR0087'}
IBK = {'institution_id': 'ibk', 'listing_url': 'https://www.ibk.co.kr/cyber/noticeListCyber.ibk?pageId=IR03010400'}
GROUP = '11111111-2222-3333-4444-555555555555'
FILE = 'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'
KDB_DATA = {'ITR_BLB_ID': 'STD119', 'COMMON_HEAD': {'ERROR': False},
            'HEADER_STD_WEB': {'TOT_PAG_ROW_CNT': 1, 'TOT_PAG_CNT': 1},
            'STDLIST_REC': [{'ITR_NAC_ID_MNG_SNO': '900001', 'NAC_CONE_TTL': '2026 남부권 지역성장지원펀드 위탁운용사 선정계획 공고',
                             'FST_ENR_DTM': '20260507100418', 'NAC_SMRY_CONE': 'This listing summary is not the detail body.'}]}
IBK_ROW = '<tr><td>12</td><td class="subject"><a href="/cyber/noticeDetailCyber.ibk?pageId=IR03010400&amp;srno=900002">2026 IBK 동행펀드 선정계획 공고</a></td><td>-</td><td>Mon May 18 00:00:00 KST 2026</td><td class="day">100</td></tr>'
IBK_LIST = '<div id="contents_in"><table><tbody>' + IBK_ROW + '</tbody></table></div>'
IBK_URL = 'https://www.ibk.co.kr/cyber/noticeDetailCyber.ibk?pageId=IR03010400&srno=900002'
KDB_HTML = '<input id="itrNacIdMngSno" value="900001"><input id="itrBlbId" value="STD119"><input name="APG_FL_MPN_ID" value="' + GROUP + '"><article class="bbs"><p class="tit">2026 남부권 지역성장지원펀드 위탁운용사 선정계획 공고</p><div class="bbsInfo"><span>작성일 : <time datetime="2026-05-07">2026-05-07</time></span><span>조회 : 100</span></div><div class="context editor"><p>실제 공식 상세 공고 본문입니다.</p></div><div class="fileList"><a href="/fileView?groupId=' + GROUP + '&amp;fileId=' + FILE + '">붙임1. 선정계획 공고.hwp</a></div></article><div class="bbs_view01">Mobile duplicated content is not a second source.</div>'
IBK_HTML = '<input name="srno" value="900002"><div id="contents_in"><table><tbody><tr><td class="view_tit">2026 IBK 동행펀드 선정계획 공고</td><td class="update">등록일 Mon May 18 00:00:00 KST 2026</td></tr><tr><td class="view"><p>공식 자체 출자 공고입니다.</p></td></tr><tr><td class="down_flie"><a href="/common/download.ibk?fileName=선정 공고.pdf&amp;fullName=fup/finemall/general/news/observed.pdf&amp;seq=900002&amp;category=null">선정 공고.pdf</a></td></tr></tbody></table></div>'


def kdb_url():
    row = parse_listing(json.dumps(KDB_DATA), listing_requests(KDB)[0]['url'], KDB)[0]
    return row['url']


class PolicyBankAdapterTests(unittest.TestCase):
    def test_requests_are_bounded_observed_get_templates(self):
        for config, count in [(KDB, 3), (IBK, 4)]:
            requests = listing_requests(config)
            self.assertEqual(len(requests), count)
            self.assertTrue(all(r['method'] == 'GET' and r['referer'].startswith('https://') for r in requests))
        request = listing_requests(KDB)[0]
        payload = json.loads(parse_qs(urlsplit(request['url']).query)['_JSON_'][0])
        self.assertEqual(payload['ITR_BLB_ID'], 'STD119')
        self.assertEqual(payload['SEARCH_KEYWORD'], '펀드')
        self.assertNotIn('ITR_NAC_ID_MNG_SNO', payload)
        for config in [dict(KDB, pages=9), dict(IBK, search_terms=[]), {'institution_id': 'unknown'}]:
            with self.assertRaises(ValueError):
                listing_requests(config)

    def test_kdb_observed_json_identifier_builds_documented_detail_navigation(self):
        rows = parse_listing(json.dumps(KDB_DATA), listing_requests(KDB)[0]['url'], KDB)
        self.assertEqual(rows[0]['source_id'], 'kdb:900001')
        self.assertEqual(rows[0]['date'], '2026-05-07')
        payload = json.loads(parse_qs(urlsplit(rows[0]['url']).query)['_PARM_DATA'][0])
        self.assertEqual(payload['ITR_NAC_ID_MNG_SNO'], '900001')
        self.assertEqual(payload['ITR_BLB_ID'], 'STD119')

    def test_kdb_explicit_empty_and_missing_or_rejected_payloads(self):
        empty = copy.deepcopy(KDB_DATA)
        empty['STDLIST_REC'] = []
        empty['HEADER_STD_WEB']['TOT_PAG_ROW_CNT'] = 0
        self.assertEqual(parse_listing(json.dumps(empty), listing_requests(KDB)[0]['url'], KDB), [])
        bads = [dict(KDB_DATA, STDLIST_REC=[]), dict(KDB_DATA, ITR_BLB_ID='STD999'),
                dict(KDB_DATA, COMMON_HEAD={'ERROR': True}), dict(KDB_DATA, STDLIST_REC=None), {}]
        for data in bads:
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    parse_listing(json.dumps(data), listing_requests(KDB)[0]['url'], KDB)

    def test_invalid_kdb_timestamp_or_identifier_is_rejected(self):
        for field, value in [('FST_ENR_DTM', '20260230120000'), ('FST_ENR_DTM', '20260507'), ('ITR_NAC_ID_MNG_SNO', '900001/other')]:
            data = copy.deepcopy(KDB_DATA)
            data['STDLIST_REC'][0][field] = value
            with self.assertRaises(ValueError):
                parse_listing(json.dumps(data), listing_requests(KDB)[0]['url'], KDB)

    def test_ibk_list_date_is_real_registration_not_source_title_year(self):
        rows = parse_listing(IBK_LIST.replace('2026 IBK', '2027 IBK'), listing_requests(IBK)[0]['url'], IBK)
        self.assertEqual(rows[0]['date'], '2026-05-18')
        self.assertEqual(rows[0]['source_id'], 'ibk:900002')
        self.assertEqual(rows[0]['url'], IBK_URL)

    def test_ibk_empty_is_distinguished_from_broken_html(self):
        url = listing_requests(IBK)[0]['url']
        self.assertEqual(parse_listing('<div id="contents_in"><table><td>등록된 게시물이 없습니다.</td></table></div>', url, IBK), [])
        for html in ['', '<html>로그인</html>', '<div id="contents_in"><table></table></div>']:
            with self.assertRaises(ValueError):
                parse_listing(html, url, IBK)

    def test_foreign_wrong_board_and_missing_identifiers_fail(self):
        for target in [IBK_URL.replace('www.ibk.co.kr', 'other.example'), IBK_URL.replace('IR03010400', 'IR03010200'), IBK_URL.replace('https:', 'http:'), IBK_URL.replace('900002', 'oops')]:
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    parse_detail(IBK_HTML, target, IBK)
        url = listing_requests(KDB)[0]['url']
        payload = json.loads(parse_qs(urlsplit(url).query)['_JSON_'][0])
        payload['ITR_BLB_ID'] = 'STD423'
        with self.assertRaises(ValueError):
            parse_listing(json.dumps(KDB_DATA), 'https://www.kdb.co.kr/BOUBUF01R01.jct?' + urlencode({'_JSON_': json.dumps(payload)}), KDB)

    def test_kdb_detail_uses_actual_html_and_preserves_hwp_attachment(self):
        n = parse_detail(KDB_HTML, kdb_url(), KDB)
        self.assertEqual(n['date'], '2026-05-07')
        self.assertEqual(n['body'], '실제 공식 상세 공고 본문입니다.')
        self.assertNotIn(KDB_DATA['STDLIST_REC'][0]['NAC_SMRY_CONE'], n['body'])
        self.assertEqual(n['attachments'][0]['name'], '붙임1. 선정계획 공고.hwp')
        self.assertEqual(len(n['attachments']), 1)

    def test_kdb_detail_wrong_notice_board_group_or_frame_fails(self):
        for html in [KDB_HTML.replace('value="900001"', 'value="900009"'), KDB_HTML.replace('value="STD119"', 'value="STD999"'), KDB_HTML.replace('groupId=' + GROUP, 'groupId=AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'), '<script>var listingSummary="not a detail"</script>']:
            with self.assertRaises(ValueError):
                parse_detail(html, kdb_url(), KDB)

    def test_ibk_detail_binds_notice_and_encodes_observed_unicode_file_names(self):
        n = parse_detail(IBK_HTML, IBK_URL, IBK)
        self.assertEqual(n['body'], '공식 자체 출자 공고입니다.')
        self.assertEqual(n['date'], '2026-05-18')
        self.assertEqual(n['attachments'][0]['name'], '선정 공고.pdf')
        query = parse_qs(urlsplit(n['attachments'][0]['url']).query)
        self.assertEqual(query['fileName'], ['선정 공고.pdf'])
        self.assertNotIn(' ', n['attachments'][0]['url'])
        self.assertEqual(query['seq'], ['900002'])

    def test_ibk_wrong_detail_notice_and_attachment_path_fail(self):
        for old, new in [('value="900002"', 'value="900003"'), ('seq=900002', 'seq=900003'), ('/common/download.ibk?', 'https://other.example/common/download.ibk?'), ('fup/finemall/general/news/observed.pdf', 'fup/finemall/general/news/../private.pdf')]:
            with self.subTest(replacement=new):
                with self.assertRaises(ValueError):
                    parse_detail(IBK_HTML.replace(old, new), IBK_URL, IBK)

    def test_date_corruption_and_conflicting_duplicates_fail(self):
        with self.assertRaises(ValueError):
            parse_listing(IBK_LIST.replace('May 18', 'Feb 30'), listing_requests(IBK)[0]['url'], IBK)
        with self.assertRaises(ValueError):
            parse_detail(KDB_HTML.replace('datetime="2026-05-07"', 'datetime="2026-05-08"'), kdb_url(), KDB)
        self.assertEqual(len(parse_listing(IBK_LIST.replace(IBK_ROW, IBK_ROW + IBK_ROW), listing_requests(IBK)[0]['url'], IBK)), 1)
        with self.assertRaises(ValueError):
            parse_listing(IBK_LIST.replace(IBK_ROW, IBK_ROW + IBK_ROW.replace('May 18', 'May 19')), listing_requests(IBK)[0]['url'], IBK)


if __name__ == '__main__':
    unittest.main()
