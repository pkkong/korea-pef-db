import json
import unittest
from urllib.parse import parse_qs, urlsplit

from services.lp.src import audit_lp_official_inventory as inventory


def growth(rows):
    return '<html><table>'+''.join('<tr><td>'+number+'</td><td><a href="notice_view.asp?idx='+ident+'&str_type=1&tab=1">'+title+'</a></td><td>'+stamp+'</td></tr>' for number,ident,title,stamp in rows)+'</table></html>'


class OfficialInventoryTests(unittest.TestCase):
    def audit(self, fetch, **kwargs):
        return inventory.audit({'programs':[]},as_of='2026-10-22',scope={'confirmed_institution_ids':['kgrowth','sema'],'priority_verification_ids':[]},configs={},fetch_factory=lambda *a:fetch,**kwargs)

    def test_rolling_year_is_inclusive_and_not_current_calendar_year(self):
        self.assertEqual(inventory.window('2026-10-22'),('2025-10-23','2026-10-22'))
        self.assertEqual(inventory.window('2024-03-01'),('2023-03-03','2024-03-01'))

    def test_all_pages_are_kept_and_late_prior_year_gap_is_visible(self):
        pages={1:growth([('2','200','2025년 국내 PE 블라인드 위탁운용사 선정 공고','2025-12-20')]),2:growth([('1','100','이전 공고','2025-01-01')])}
        report=self.audit(lambda url:pages[int(parse_qs(urlsplit(url).query)['page'][0])].encode())
        self.assertEqual(report['summary']['pages'],2)
        row=report['institutions'][0]
        self.assertEqual(row['queries'][0]['boundary'],'observed_older_page')
        self.assertEqual(row['counts']['explicit_pe_blind_unarchived'],1)
        self.assertEqual(row['rows'][0]['date'],'2025-12-20')
        self.assertEqual(inventory.notice_key('kgrowth',row['rows'][0]['url']),'kgrowth:200')
        self.assertIsNone(report['market_recall'])
        self.assertIsNone(report['institutions'][1]['counts'])
        self.assertEqual(report['institutions'][1]['status'],'inventory_not_connected')
        self.assertTrue(all(r['html'] and len(r['sha256'])==64 for r in report['receipts']))

    def test_pinned_old_notice_does_not_end_current_period(self):
        page=growth([('','1','상시 공지','2020-01-01'),('5','300','2026년 국내 PE 블라인드 선정 공고','2026-10-01')])
        report=self.audit(lambda url:page.encode(),max_pages=2)
        query=report['institutions'][0]['queries'][0]
        self.assertEqual(query['boundary'],'repeated_page')
        self.assertEqual(report['institutions'][0]['status'],'query_limit')

    def test_archived_notice_is_not_missing_and_publication_is_separate(self):
        url='https://www.kgrowth.or.kr/notice_view.asp?idx=200&str_type=1&tab=1'
        page=growth([('2','200','국내 PE 블라인드 모집 공고','2026-10-01')])
        scope={'confirmed_institution_ids':['kgrowth'],'priority_verification_ids':[]}
        archive={'notices':[{'institution_id':'kgrowth','title':'국내 PE 블라인드 모집 공고','url':url}]}
        report=inventory.audit({'programs':[]},[archive],as_of='2026-10-22',scope=scope,configs={},fetch_factory=lambda *a:lambda u:page.encode(),max_pages=1)
        self.assertEqual(report['institutions'][0]['rows'][0]['disposition'],'archived_unpublished')
        self.assertEqual(report['institutions'][0]['counts']['unarchived_relevant'],0)

    def test_query_cap_repeat_failure_and_unconnected_never_mean_full_recall(self):
        page=growth([('2','200','국내 PE 블라인드 모집 공고','2026-10-01')])
        report=self.audit(lambda url:page.encode(),max_pages=1)
        self.assertEqual(report['institutions'][0]['queries'][0]['boundary'],'page_limit')
        self.assertIsNone(report['market_recall'])
        def fail(url):raise TimeoutError('official source unavailable')
        failed=self.audit(fail)
        self.assertEqual(failed['institutions'][0]['status'],'source_error')
        self.assertIsNone(failed['institutions'][0]['counts'])
        self.assertEqual(len(failed['holds']),1)

    def test_invalid_fetched_page_is_retained_and_zero_budget_stays_unmeasured(self):
        report=self.audit(lambda url:b'<html>unrecognized official markup</html>')
        self.assertEqual(len(report['receipts']),1)
        self.assertIsNone(report['receipts'][0]['row_count'])
        self.assertIsNone(report['institutions'][0]['counts'])
        report=inventory.audit({'programs':[]},as_of='2026-10-22',scope={'confirmed_institution_ids':['kgrowth','ktcu'],'priority_verification_ids':[]},configs={},fetch_factory=lambda *a:lambda url:growth([('1','200','PE 블라인드 공고','2026-10-01')]).encode(),max_pages=1,page_budget=1)
        self.assertIsNone(report['institutions'][1]['counts'])

    def test_post_requests_explicit_window_and_refuses_default_six_month_echo(self):
        url=inventory.page_url('koreapost',{},'',1,'2025-10-23','2026-10-22')
        q=parse_qs(urlsplit(url).query)
        self.assertEqual(q['keySDate'],['2025-10-23'])
        html='<html><input name="keySDate" value="2026-04-22"><input name="keyEDate" value="2026-10-22"></html>'
        with self.assertRaisesRegex(ValueError,'date filter'):inventory.core_rows('koreapost',html,url)

    def test_post_identical_date_controls_in_two_real_forms_are_valid(self):
        url=inventory.page_url('koreapost',{},'',1,'2025-10-23','2026-10-22')
        controls='<input name="keySDate" value="2025-10-23"><input name="keyEDate" value="2026-10-22">'
        row='<table><tr><td><a href="/board.es?bid=0041&act=view&list_no=20" title="국내 PE 블라인드 모집 공고">공고</a></td><td>2026-10-01</td></tr></table>'
        html='<html><form>'+controls+'</form><form>'+controls+'</form>'+row+'</html>'
        self.assertEqual(len(inventory.core_rows('koreapost',html,url)),1)
        with self.assertRaises(ValueError):inventory.core_rows('koreapost',html.replace('2025-10-23','2026-04-22',1),url)

    def test_ktcu_advertised_final_page_avoids_empty_overrun(self):
        html='<html><div class="sort-tit txt-s">총 <em>1</em>건 (<em>1</em> / 1 페이지)</div><ul id="ulList"><li><span class="num">1</span><a href="javascript:fn_view(&#39;61742&#39;)">국내 PE 블라인드 위탁운용사 선정 공고</a><span>2026-09-04</span></li></ul></html>'
        calls=[]
        def fetch(url):
            calls.append(url)
            self.assertEqual(parse_qs(urlsplit(url).query)['curPage'],['1'])
            return html.encode()
        report=inventory.audit({'programs':[]},as_of='2026-10-22',scope={'confirmed_institution_ids':['ktcu'],'priority_verification_ids':[]},configs={},fetch_factory=lambda *a:fetch)
        self.assertEqual(report['holds'],[])
        self.assertEqual(len(calls),2)
        self.assertTrue(all(q['boundary']=='observed_final_page' for q in report['institutions'][0]['queries']))
        with self.assertRaisesRegex(ValueError,'page count'):
            inventory.core_last_page('ktcu',html,calls[0].replace('curPage=1','curPage=2'))

    def test_notice_identity_ignores_presentation_but_preserves_issuer_and_id(self):
        a='https://www.kgrowth.or.kr/notice_view.asp?idx=200&str_type=1&tab=1'
        b=a+'&page=2&search_text=test'
        self.assertEqual(inventory.notice_key('kgrowth',a),inventory.notice_key('kgrowth',b))
        for bad in [a.replace('https:','http:'),a.replace('kgrowth.or.kr','evil.example'),a+'&idx=201']:
            with self.assertRaises(ValueError):inventory.notice_key('kgrowth',bad)

    def test_explicit_other_board_cannot_match_an_archived_notice(self):
        cases=[('cu','https://www.cu.co.kr/cu/na/ntt/selectNttInfo.do?nttSn=1&bbsId=9999'),
               ('poba','https://www.poba.or.kr/bbs/selectNttDetail?sechBbstSeq=1&sechBbsSeq=99'),
               ('kgrowth','https://www.kgrowth.or.kr/notice_view.asp?idx=200&str_type=2'),
               ('pmaa','https://www.pmaa.or.kr/www/1461128463820/bbs.do?bbsIdx=1&type=list')]
        for code,url in cases:
            with self.subTest(institution=code),self.assertRaises(ValueError):inventory.notice_key(code,url)

    def test_bank_page_builder_crosses_regular_three_page_cap_without_fixed_notice_ids(self):
        config={'institution_id':'kdb','listing_url':'https://www.kdb.co.kr/CHBIPR23N00.act?_mnuId=IHIHIR0087','search_terms':['펀드'],'pages':3}
        url=inventory.page_url('kdb',config,'펀드',4,'2025-10-23','2026-10-22')
        payload=json.loads(parse_qs(urlsplit(url).query)['_JSON_'][0])
        self.assertEqual(payload['HEADER_STD_WEB']['REQ_PAGE_NO'],4)
        self.assertNotIn('ITR_NAC_ID_MNG_SNO',payload)

    def test_unrecognized_html_cannot_be_an_empty_year(self):
        for code,url in inventory.CORE.items():
            with self.subTest(institution=code),self.assertRaises(ValueError):inventory.core_rows(code,'<html>error</html>',url)

    def test_empty_message_outside_board_cannot_hide_broken_listing(self):
        for code,body in [('kexim','<div class="notice-list">응답 오류</div>'),('koreapost','<table><tr><th>제목</th><th>첨부</th></tr><tbody>응답 오류</tbody></table>')]:
            html='<html>'+body+'<footer>등록된 게시물이 없습니다</footer></html>'
            with self.subTest(institution=code),self.assertRaises(ValueError):inventory.core_rows(code,html,inventory.CORE[code])
        valid='<html><div class="notice-list">등록된 게시물이 없습니다</div></html>'
        self.assertEqual(inventory.core_rows('kexim',valid,inventory.CORE['kexim']),[])
