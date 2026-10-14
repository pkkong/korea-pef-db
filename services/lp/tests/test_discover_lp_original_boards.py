import copy
import hashlib
import unittest
from unittest.mock import patch

from services.lp.src.discover_lp_original_boards import (listing_links, page_url, channels,
    validate_listing_provenance, reuse_native_originals, validate_native_provenance, discover)
from services.lp.src.collect_lp_original_notices import validate_identity, load_aliases, parse_original, original_body_hash


class OfficialBoardTests(unittest.TestCase):
    def test_observed_javascript_controls_use_arbitrary_new_identifiers(self):
        config=channels()['kbiz'];url=page_url(config,1)
        html="<html><span onclick=\"goView(987654, 'N')\">2026년 국내 블라인드 펀드 선정 공고</span></html>"
        row=listing_links(html,url,config)[0]
        self.assertIn('seq=987654',row['url'])
        config=channels()['kamco'];url=page_url(config,1)
        html="<html><a onclick=\"goTo.view('list','765432','380','0701010000'); return false;\">펀드 선정</a></html>"
        self.assertIn('bIdx=765432',listing_links(html,url,config)[0]['url'])
        with self.assertRaises(ValueError):listing_links(html.replace("'380'","'999'"),url,config)

    def test_listing_proof_is_reparsed_instead_of_trusting_a_prepared_link(self):
        config=channels()['sema'];url=page_url(config,1)
        title='2026년 과학기술인공제회 국내 PE·VC 블라인드 펀드 선정계획 공고'
        html=f'<html><a href="/sema/bbs/B0000022/view.do?nttId=999000">{title}</a></html>'
        row=listing_links(html,url,config)[0]
        original={**row,'date':'2026-08-01','body':'과학기술인공제회 국내 블라인드 펀드 출자 모집입니다.',
                  'discovery_provenance':{'kind':'official_board','listing_url':url,'listing_html':html,
                  'listing_sha256':hashlib.sha256(html.encode()).hexdigest(),'listing_title':title}}
        validate_listing_provenance(original,'sema')
        for key,value in [('url',row['url'].replace('999000','111111')),('listing_sha256','bad'),('listing_url',url.replace('B0000022','B0000024'))]:
            n=copy.deepcopy(original)
            if key=='url':n[key]=value
            else:n['discovery_provenance'][key]=value
            with self.assertRaises(ValueError):validate_listing_provenance(n,'sema')

    def test_new_title_year_and_explicit_vc_or_matching_track_are_not_interchangeable(self):
        n={'institution_id':'kbiz','date':'2026-07-10','source_scope':'mixed_pe_blind',
           'title':'2026년 중소기업중앙회 국내 블라인드 펀드 선정 공고'}
        other={'title':'2026년 중소기업중앙회 국내 블라인드 VC펀드 선정 공고','body':'','date':None}
        with self.assertRaises(ValueError):validate_identity(n,other,load_aliases(),candidate_only=True)
        n={'institution_id':'kgrowth','title':'2026년 IBK 생산적금융펀드 1호 일반매칭 위탁운용사 선정계획 공고','date':'2026-09-01'}
        other={'title':n['title'].replace('일반매칭','자율제안'),'body':'한국성장금융 출자 모집 공고입니다.','date':'2026-09-01'}
        with self.assertRaises(ValueError):validate_identity(n,other,load_aliases())

    def test_yearless_official_title_needs_real_publication_year(self):
        n={'institution_id':'kamco','title':'2026년 캠코 주력산업 대출형 기업지원펀드 7호 선정계획 공고','date':'2026-09-21'}
        o={'title':'캠코 주력산업 대출형 기업지원펀드 7호 선정계획 공고','date':'2026-09-21','body':'첨부와 같이 캠코 주력산업 펀드 선정계획을 공고합니다.'}
        validate_identity(n,o,load_aliases())
        for year in ('2025',None):
            o['date']=year+'-09-21' if year else None
            with self.assertRaises(ValueError):validate_identity(n,o,load_aliases())

    def test_existing_collection_is_matched_without_any_selected_notice_list(self):
        title='「IBK 생산적금융펀드 9호」일반매칭 위탁운용사 선정계획 공고'
        source={'institution_id':'kgrowth','source_id':'987654','url':'https://www.kgrowth.or.kr/notice_view.asp?idx=987654',
                'title':'【선정공고】'+title,'date':'2026-09-01','body':'한국성장금융 국내 기업 투자와 펀드 모집을 공고합니다.',
                'sha256':'a'*64,'checked_at':'2026-10-14T01:00:00+00:00','attachments':[],'attachment_hashes':{}}
        source['sha256']=original_body_hash(source)
        n={'institution_id':'kgrowth','source_scope':'needs_confirmation','title':title,'date':'2026-09-01','url':'https://www.kvca.or.kr/notice'}
        current={'notices':[n]};original=copy.deepcopy(current)
        result=reuse_native_originals(current,[source],'2026-10-14T02:00:00+00:00')
        self.assertEqual(result['coverage']['existing_originals']['matched'],1)
        self.assertEqual(current,original)
        doc=result['notices'][0]['original_notices'][0]
        validate_native_provenance(doc,'kgrowth')
        both=copy.deepcopy(doc);both['body']='fabricated';both['discovery_provenance']['source_notice']['body']='fabricated'
        with self.assertRaises(ValueError):validate_native_provenance(both,'kgrowth')
        doc['discovery_provenance']['source_notice']['body']='fabricated'
        with self.assertRaises(ValueError):validate_native_provenance(doc,'kgrowth')

    def test_repeated_or_failed_source_discovery_preserves_existing_original(self):
        n={'institution_id':'sema','source_scope':'mixed_pe_blind','original_notices':[{'url':'prior'}]}
        old={'notices':[n],'holds':[],'coverage':{}}
        def failure(*args):raise TimeoutError('source outage')
        result=discover(old,fetch=failure,pages=1)
        self.assertEqual(old['notices'],result['notices'])
        self.assertEqual(len([h for h in result['holds'] if h['stage']=='original_board']),4)

    def test_accessible_poster_alt_and_kbiz_file_labels_are_official_body_evidence(self):
        html='<html><table><tr><th>제목</th><td>2026년 국내 PE 펀드 공고</td></tr><tr><th>작성일</th><td>2026-08-14 09:00</td></tr></table><td class="td_cont"><img alt="과학기술인공제회 국내 블라인드 펀드 출자 모집 2,700억원을 공고합니다."></td></html>'
        o=parse_original(html,'https://www.sema.or.kr/detail')
        self.assertIn('2,700억원',o['body'])
        html='<html><div class="subject-wrap"><strong>2026년 중소기업중앙회 국내 PE 펀드 공고</strong><em class="date">등록일 2026.07.10</em></div><div class="detail-body">중소기업중앙회 국내 블라인드 펀드 출자 모집에 관한 공식 공고 내용입니다.</div><li><em>공고문.hwp(160 KB)</em><a href="/download.do?seq=987654">다운로드</a></li></html>'
        o=parse_original(html,'https://www.kbiz.or.kr/detail')
        self.assertEqual(o['date'],'2026-07-10')
        self.assertEqual(o['attachments'][0]['name'],'공고문.hwp')


if __name__=='__main__':unittest.main()
