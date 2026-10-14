import copy
import unittest
from unittest.mock import patch
from services.lp.src.collect_lp_original_notices import enrich,validate_original,OfficialRedirect
from urllib.request import Request

STAMP='2026-10-14T01:00:00+00:00'
CHANNELS={'mmaa':{'mmaa.or.kr'}}
ALIASES={'mmaa':['군인공제회'],'ktcu':['한국교직원공제회']}
URL='https://www.mmaa.or.kr/web/contents/notice.do?schM=view&id=987654'
TITLE='’26년 군인공제회 국내 PE·VC 블라인드 펀드 선정계획 공고'

def notice(url=URL):
    return {'source_id':'kvca:999999','institution_id':'mmaa','url':'https://www.kvca.or.kr/Program/invest/listbody.html?po_no=999999','title':TITLE,'date':None,'source_scope':'mixed_pe_blind','source_provenance':{'original_links':[{'url':url}]}}

def page(title=TITLE,body='군인공제회 국내 PE·VC 블라인드 펀드 모집. 위탁 운용 규모 및 제안 자격을 다음과 같이 공고합니다.',attachment=False,date=True):
    return ('<html><div class="b_info"><p class="board_tit">'+title+'</p>'+('<div class="b_div"><span>등록일</span>2026-07-31</div>' if date else '')+'</div><div class="b_content">'+body+'</div>'+('<a href="/files/offer.pdf">모집공고.pdf</a>' if attachment else '')+'</html>').encode()

def run(n=None,html=None,fetch=None):
    return enrich({'notices':[n or notice()],'holds':[],'coverage':{}},fetch=fetch or (lambda url,referer=None:html or page()),channels=CHANNELS,aliases=ALIASES,checked_at=STAMP)

class OriginalTracingTests(unittest.TestCase):
    def test_changed_ids_and_separate_original_date(self):
        n=notice(); source={'notices':[n],'holds':[],'coverage':{}}
        before=copy.deepcopy(source)
        result=enrich(source,fetch=lambda url,referer=None:page(),channels=CHANNELS,aliases=ALIASES,checked_at=STAMP)
        original=result['notices'][0]['original_notices'][0]
        self.assertEqual(original['date'],'2026-07-31')
        self.assertIsNone(result['notices'][0]['date'])
        self.assertEqual(source,before)
        self.assertEqual(original['url'],URL)
        self.assertTrue(original['review_only'])
        self.assertEqual(validate_original(original,n,STAMP,channels=CHANNELS,aliases=ALIASES),original)

    def test_year_institution_round_stage_and_title_mismatches(self):
        for title in [TITLE.replace('26년','25년'),TITLE.replace('군인공제회','한국교직원공제회'),TITLE.replace('선정계획 공고','최종 선정결과'),TITLE.replace('국내 PE·VC','해외 부동산'),TITLE.replace('펀드','펀드 2차'),'[재공고] '+TITLE,'[변경] '+TITLE]:
            with self.subTest(title=title):
                result=run(html=page(title))
                self.assertEqual(result['coverage']['originals']['matched'],0)
                self.assertTrue(result['holds'])

    def test_listing_footer_does_not_validate(self):
        html=('<html><h1>'+TITLE+'</h1><div>목록</div><footer>군인공제회</footer></html>').encode()
        self.assertEqual(run(html=html)['coverage']['originals']['matched'],0)
        generic=page(TITLE.replace('군인공제회',''),body='모집 공고입니다. '+('상세 내용 확인. '*60)+'군인공제회')
        self.assertEqual(run(html=generic)['coverage']['originals']['matched'],0)

    def test_foreign_and_other_institution_links_never_fetched(self):
        calls=[]
        result=run(n=notice('https://ktcu.or.kr/notice/123'),fetch=lambda *args:calls.append(args))
        self.assertEqual(calls,[])
        self.assertEqual(result['coverage']['originals']['matched'],0)
        self.assertTrue(result['holds'])
        with self.assertRaises(ValueError):
            OfficialRedirect({'mmaa.or.kr'}).redirect_request(Request(URL),None,302,'',{},'https://evil.example/file')

    def test_outage_preserves_existing_evidence(self):
        first=run()
        before=copy.deepcopy(first['notices'][0]['original_notices'])
        def failure(*args):raise TimeoutError('network down')
        second=enrich(first,fetch=failure,channels=CHANNELS,aliases=ALIASES,checked_at=STAMP)
        self.assertEqual(second['notices'][0]['original_notices'],before)
        self.assertEqual(second['holds'][-1]['stage'],'original')

    def test_attachment_failure_does_not_discard_original_and_nul_cleaning(self):
        def fetch(url,referer=None):return page(attachment=True) if url==URL else b'%PDF sample'
        with patch('services.lp.src.collect_lp_original_notices.extract_attachment',side_effect=ValueError('unsupported PDF')):
            result=run(fetch=fetch)
        self.assertEqual(result['coverage']['originals']['matched'],1)
        self.assertEqual(result['holds'][0]['phase'],'attachment')
        with patch('services.lp.src.collect_lp_original_notices.extract_attachment',return_value={'text':'금액 100\x00200억원'}):
            result=run(fetch=fetch)
        original=result['notices'][0]['original_notices'][0]
        self.assertEqual(next(iter(original['attachment_texts'].values())),'금액 100 200억원')

    def test_missing_date_is_not_invented(self):
        original=run(html=page(date=False))['notices'][0]['original_notices'][0]
        self.assertIsNone(original['date'])

    def test_validator_rejects_tampered_hash_link_date_attachment(self):
        original=run()['notices'][0]['original_notices'][0]
        for key,value in [('sha256','123'),('sha256','b'*64),('body','군인공제회 국내 PE·VC 블라인드 펀드 모집 금액 999억원'),('hash_kind',None),('url',URL.replace('987654','111')),('date','2026-02-30'),('attachment_hashes',{'https://evil.example/x':'a'*64}),('institution_id','ktcu')]:
            altered=copy.deepcopy(original);altered[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_original(altered,notice(),STAMP,channels=CHANNELS,aliases=ALIASES)

    def test_two_links_maximum_and_skipped_scope(self):
        n=notice();n['source_provenance']['original_links']=[{'url':URL+f'&variant={x}'} for x in range(4)]
        calls=[]
        result=run(n=n,fetch=lambda url,referer=None:(calls.append(url) or page()))
        self.assertEqual(len(calls),2)
        n['source_scope']='vc_only'
        result=run(n=n,fetch=lambda *args:self.fail('VC-only must not be fetched'))
        self.assertEqual(result['coverage']['originals']['skipped'],1)

if __name__=='__main__':unittest.main()
