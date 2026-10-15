import copy
import hashlib
import unittest
from services.lp.src.discover_growth_originals import (discover, derive_query, search_url,
    listing_links, official_url, validate_search_provenance)

TITLE='「2026년 새로운산업펀드 4차」 위탁운용사 선정계획 공고'
WHEN='2026-10-15T00:00:00+00:00'

def notice():
    return {'source_id':'kvca:987600','institution_id':'kgrowth','title':TITLE,
            'date':'2026-06-01','url':'https://www.kvca.or.kr/notice?id=987600',
            'source_scope':'needs_confirmation'}

def link(ident='987654',title=TITLE):
    return f'<a href="notice_view.asp?idx={ident}&str_type=1&tab=1">{title}</a>'

def detail(title=TITLE,date='2026-06-01',attachment=False):
    value=f'<html><div class="view_info"><h2 class="tit">{title}</h2><span class="date">{date}</span></div><div class="veiw_contents">새로운산업펀드의 위탁운용사 선정계획을 다음과 같이 공고합니다. 자세한 조건은 공고문을 확인하십시오.</div>'
    if attachment:value+='<a href="down_file.asp?file=arbitrary.pdf">선정계획 공고문.pdf</a>'
    return (value+'</html>').encode('cp949')

class GrowthSearchTests(unittest.TestCase):
    def run_fixture(self,listing=None,raw=None):
        def fetch(url):
            if '/notice.asp?' in url:return ('<html>'+(listing if listing is not None else link())+'</html>').encode('cp949')
            if '/notice_view.asp?' in url:return raw or detail()
            raise OSError('attachment unavailable')
        return discover({'notices':[notice()]},fetch,WHEN)

    def test_arbitrary_id_and_derived_cp949_query(self):
        result=self.run_fixture()
        original=result['notices'][0]['original_notices'][0]
        self.assertIn('987654',original['url'])
        self.assertEqual(derive_query(TITLE),'새로운산업펀드')
        self.assertIn('%',search_url(derive_query(TITLE)))
        self.assertEqual(result['notices'][0]['source_scope'],'needs_confirmation')
        validate_search_provenance(original)

    def test_wrong_year_round_stage_not_fetched(self):
        for wrong in [TITLE.replace('2026','2025'),TITLE.replace('4차','3차'),TITLE.replace('선정계획 공고','선정 결과'),TITLE+' FAQ']:
            with self.subTest(wrong=wrong):
                result=self.run_fixture(link(title=wrong))
                self.assertNotIn('original_notices',result['notices'][0])
                self.assertTrue(result['holds'])

    def test_detail_year_and_date_are_not_invented(self):
        for raw in [detail(title=TITLE.replace('2026','2025')),detail(date='게시일 없음')]:
            result=self.run_fixture(raw=raw)
            self.assertNotIn('original_notices',result['notices'][0])

    def test_ambiguous_matches_are_held(self):
        result=self.run_fixture(link('123456')+link('777777'))
        self.assertNotIn('original_notices',result['notices'][0])
        self.assertIn('found 2',result['holds'][0]['error'])

    def test_host_and_route_rejected(self):
        for url in ['https://evil.example/notice_view.asp?idx=8&str_type=1&tab=1',
                    'https://www.kgrowth.or.kr/evil/notice_view.asp?idx=8&str_type=1&tab=1',
                    'https://www.kgrowth.or.kr/notice_view.asp?idx=8&idx=9&str_type=1&tab=1']:
            with self.assertRaises(ValueError):official_url(url,'/notice_view.asp')
            self.assertFalse(listing_links(f'<html><a href="{url}">{TITLE}</a></html>',search_url('새로운산업펀드')))

    def test_outage_preserves_existing_evidence_and_input(self):
        collection={'notices':[notice(),{**notice(),'source_id':'old','original_notices':[{'body':'retained'}]}],'holds':[{'error':'previous'}]}
        before=copy.deepcopy(collection)
        def failure(url):raise OSError('network outage')
        result=discover(collection,failure,WHEN)
        self.assertEqual(collection,before)
        self.assertEqual(result['notices'][1]['original_notices'],[{'body':'retained'}])
        self.assertEqual(result['holds'][0],{'error':'previous'})
        self.assertEqual(result['holds'][-1]['stage'],'growth_search')

    def test_attachment_failure_keeps_body(self):
        result=self.run_fixture(raw=detail(attachment=True))
        self.assertTrue(result['notices'][0]['original_notices'][0]['body'])
        self.assertEqual(result['holds'][0]['phase'],'attachment')

    def test_pe_vc_title_difference_and_excluded_scope(self):
        result=self.run_fixture(link(title=TITLE.replace('새로운산업펀드','새로운산업펀드 VC')))
        self.assertNotIn('original_notices',result['notices'][0])
        calls=[]
        source={**notice(),'source_scope':'vc_only'}
        result=discover({'notices':[source]},lambda url:calls.append(url),WHEN)
        self.assertEqual(calls,[])
        self.assertEqual(result['notices'][0],source)

    def test_incomplete_and_oversized_listing_rejected(self):
        for html in [link(),'<html>'+('x'*2_000_000)+'</html>']:
            with self.assertRaises(ValueError):listing_links(html,search_url('새로운산업펀드'))

    def test_forms_never_downloaded(self):
        raw=detail().decode('cp949').replace('</html>','<a href="down_file.asp?file=form.hwp">제안서 양식.hwp</a></html>').encode('cp949')
        result=self.run_fixture(raw=raw)
        self.assertEqual(result['notices'][0]['original_notices'][0]['attachments'],[])
        self.assertFalse(result.get('holds'))

    def test_same_stage_wrong_business_in_listing_receipt_rejected(self):
        original=self.run_fixture()['notices'][0]['original_notices'][0]
        proof=original['discovery_provenance']
        proof['listing_title']=TITLE.replace('4차','3차')
        proof['listing_html']=proof['listing_html'].replace('4차','3차')
        proof['listing_sha256']=hashlib.sha256(proof['listing_html'].encode()).hexdigest()
        with self.assertRaises(ValueError):validate_search_provenance(original)

    def test_source_failures_and_matching_holds_have_distinct_phases(self):
        def listing_failure(url):raise OSError('unavailable')
        self.assertEqual(discover({'notices':[notice()]},listing_failure,WHEN)['holds'][0]['phase'],'listing')
        def detail_failure(url):
            if '/notice.asp?' in url:return ('<html>'+link()+'</html>').encode('cp949')
            raise OSError('unavailable')
        self.assertEqual(discover({'notices':[notice()]},detail_failure,WHEN)['holds'][0]['phase'],'detail')
        self.assertEqual(self.run_fixture(listing='')['holds'][0]['phase'],'matching')

    def test_receipt_tampering_rejected(self):
        original=self.run_fixture()['notices'][0]['original_notices'][0]
        for field,value in [('listing_sha256','0'*64),('query','다른펀드'),('extra','unknown')]:
            mutated=copy.deepcopy(original);mutated['discovery_provenance'][field]=value
            with self.assertRaises(ValueError):validate_search_provenance(mutated)
        mutated=copy.deepcopy(original);mutated['body']='changed'
        with self.assertRaises(ValueError):validate_search_provenance(mutated)

if __name__=='__main__':unittest.main()
