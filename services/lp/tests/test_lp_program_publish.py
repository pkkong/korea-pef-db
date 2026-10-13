import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1]/'src'
sys.path.insert(0,str(SRC))
from publish_lp_programs import prepare, document_hash

class PublishContracts(unittest.TestCase):
    def test_identical_document_is_not_versioned_again_for_check_time(self):
        doc = {'body':'same', 'attachment_hashes':{'file':'v1'}, 'checked_at':'first'}
        later = dict(doc, checked_at='later')
        self.assertEqual(document_hash(doc), document_hash(later))
        later['attachment_hashes'] = {'file':'v2'}
        self.assertNotEqual(document_hash(doc), document_hash(later))

    def setUp(self):
        self.data=json.loads((SRC.parents[2]/'data/lp_programs_pilot.json').read_text())
        self.p=next(p for p in self.data['programs'] if p['institution_id']=='kgrowth')
        self.report={'checked_at':'2026-09-21','notices':[{'source_id':'1047','title':'공고','date':'2026-09-21','body':'본문','url':'https://www.kgrowth.or.kr/notice_view.asp?idx=1047'}],'programs':[copy.deepcopy(self.p)]}
    def test_review_preserves_program_and_accepted_fingerprint(self):
        self.data['accepted_notices']=[{'source_id':'1047','sha256':'old'}]
        self.report['accepted_notices']=self.data['accepted_notices']
        self.report['requires_review']=True
        self.report['programs'][0]['title']='UNREVIEWED EDIT'
        result,_=prepare(self.data,self.report)
        self.assertEqual(self.data['accepted_notices'],result['accepted_notices'])
        self.assertNotIn('UNREVIEWED EDIT',[p['title'] for p in result['programs']])

    def test_empty_collection_cannot_erase_pages(self):
        self.report['notices']=[]
        with self.assertRaises(ValueError):prepare(self.data,self.report)
    def test_unreviewed_tracking_survives_publication(self):
        self.report['tracked_notices'] = [{'source_id':'9999','sha256':'new'}]
        self.report['requires_review'] = True
        result,_=prepare(self.data,self.report)
        self.assertEqual(self.report['tracked_notices'], result['tracked_notices'])
    def test_unreviewed_program_cannot_be_published(self):
        self.report['programs'][0]['id']='unreviewed'
        with self.assertRaises(ValueError):prepare(self.data,self.report)
    def test_other_institutions_remain_unchanged(self):
        data,pages=prepare(self.data,self.report)
        before={p['id']:p for p in self.data['programs'] if p['institution_id']!='kgrowth'}
        after={p['id']:p for p in data['programs'] if p['institution_id']!='kgrowth'}
        # Renderer may add page_key to a copy; original input must remain intact.
        for p in after.values():
            for gp in p['selected_gps']:gp.pop('page_key',None)
        self.assertEqual(before,after)
        self.assertEqual(5,len([n for n in pages if n.startswith('program-')]))

    def test_priority_program_comes_from_reprojected_evidence_not_collector_payload(self):
        verified=copy.deepcopy(next(p for p in self.data['programs'] if p['institution_id']=='ktcu'))
        verified['status']='접수 마감'
        self.report['priority_sources']={'ktcu':{'notices':[{'source_id':'61742', 'url':'https://www.ktcu.or.kr/PPW-CSB-000101/61742',
                                                              'date':'2026-09-04','title':'공식 모집','body':'공식 본문'}],
                                                 'programs':[{'id':'unreviewed-ktcu','institution_id':'ktcu'}],
                                                 'holds':[]}}
        with patch('publish_lp_programs.project_ktcu',return_value=([verified],[])):
            data,pages=prepare(self.data,self.report)
        self.assertEqual('접수 마감',next(p for p in data['programs'] if p['id']==verified['id'])['status'])
        self.assertNotIn('unreviewed-ktcu',{p['id'] for p in data['programs']})
        self.assertIn('program-ktcu-2026-blind-pef.html',pages)

    def test_priority_source_failure_keeps_last_published_program(self):
        original=copy.deepcopy(next(p for p in self.data['programs'] if p['institution_id']=='koreapost'))
        self.report['priority_sources']={'koreapost':{'notices':[],'programs':[],
                                                       'holds':[{'program_id':original['id'],'reason':'공식 자료 수집 실패'}]}}
        data,_=prepare(self.data,self.report)
        self.assertEqual(original,next(p for p in data['programs'] if p['id']==original['id']))
        self.assertIn('공식 자료 수집 실패',[hold['reason'] for hold in data['program_holds']])

    def test_new_business_candidates_are_recomputed_from_notices(self):
        notice={'source_id':'114023','url':'https://www.koreaexim.go.kr/HPHKBI039M01/114023',
                'date':'2026-05-11','title':'임상3상 특화펀드 위탁운용사 선정계획 공고',
                'body':'공식 출자 공고'}
        self.report['priority_sources']={'kexim':{'notices':[notice], 'programs':[],
                                                  'discovery_candidates':[{'title':'임의 사업'}],
                                                  'holds':[]}}
        candidate={k:notice[k] for k in ('source_id','url','date','title')}
        candidate['institution_id']='kexim'
        with patch('publish_lp_programs.project_kexim',return_value=([],[])), \
             patch('publish_lp_programs.suggest_kexim',return_value=[]), \
             patch('publish_lp_programs.discover_kexim',return_value=[candidate]):
            data,pages=prepare(self.data,self.report)
        self.assertEqual(1,len(data['discovery_candidates']))
        self.assertEqual(candidate['source_id'],data['discovery_candidates'][0]['source_id'])
        self.assertEqual('unknown',data['discovery_candidates'][0]['scope'])
        self.assertEqual('모집 공고',data['discovery_candidates'][0]['stage'])
        self.assertIn('새 출자공고 후보',pages['review.html'])
        self.assertNotIn('임의 사업',pages['review.html'])

    def test_discovered_notice_survives_listing_age_out_or_source_outage(self):
        notice={'source_id':'0041:352','institution_id':'koreapost',
                'url':'https://www.kpasset.go.kr/board.es?mid=a10510000000&bid=0041&act=view&list_no=352',
                'date':'2026-04-22','title':'우체국예금 해외사모펀드 국내재간접 위탁운용사 안내',
                'body':'공식 후속 공고'}
        self.data['priority_notices']=[notice]
        self.report['priority_sources']={'koreapost':{'notices':[],'programs':[],
                                                       'holds':[{'program_id':'koreapost','reason':'일시적 접속 실패'}]}}
        data,pages=prepare(self.data,self.report)
        self.assertEqual([notice],data['priority_notices'])
        self.assertEqual('0041:352',data['discovery_candidates'][0]['source_id'])
        self.assertIn('우체국예금 해외사모펀드',pages['review.html'])

    def test_same_attachment_keeps_extracted_fund_form_when_ocr_temporarily_fails(self):
        url='https://www.koreaexim.go.kr/HPHKBI039M01/115546'
        document={'source_id':'115546','institution_id':'kexim','url':url,
                  'date':'2026-08-13','title':'2026년 LP성장펀드(Track 1) 출자사업 계획 공고',
                  'body':'공식 공고', 'attachment_hashes':{'official-pdf':'same-bytes'},
                  'attachment_texts':{'official-pdf':'출자 대상 벤처투자조합'}}
        self.data['priority_notices']=[document]
        fresh={key:value for key,value in document.items() if key!='attachment_texts'}
        self.report['priority_sources']={'kexim':{'notices':[fresh], 'programs':[], 'holds':[]}}
        with patch('publish_lp_programs.project_kexim',return_value=([],[])):
            data,_=prepare(self.data,self.report)
        self.assertEqual(document['attachment_texts'],data['priority_notices'][0]['attachment_texts'])
        self.assertEqual('vc_only',data['discovery_candidates'][0]['scope'])

    def test_new_official_program_is_published_without_per_notice_recipe(self):
        from services.lp.tests.test_lp_notice_terms import official, BODY
        notice=official(BODY)
        self.report['priority_sources']={'koreapost':{'notices':[notice], 'holds':[]}}
        data,pages=prepare(self.data,self.report)
        automatic=next(p for p in data['programs'] if p.get('auto_extracted'))
        self.assertEqual('koreapost-2026-domestic-coinvestment',automatic['id'])
        self.assertEqual('2,000억원 이내',automatic['commitment_label'])
        self.assertIn('program-'+automatic['id']+'.html',pages)
        self.assertIn('주목적',pages['program-'+automatic['id']+'.html'])
        # A missing source later preserves the last successful public terms.
        self.report['priority_sources']={'koreapost':{'notices':[], 'holds':[]}}
        later,_=prepare(data,self.report)
        self.assertEqual(automatic,next(p for p in later['programs'] if p['id']==automatic['id']))
        # A conflicting revision is held, rather than overwriting with a guess.
        changed={**notice,'body':notice['body']+'\n투자규모 : 총 3,000억원'}
        self.report['priority_sources']={'koreapost':{'notices':[changed], 'holds':[]}}
        revised,_=prepare(data,self.report)
        self.assertEqual(automatic,next(p for p in revised['programs'] if p['id']==automatic['id']))
        self.assertTrue(any(h['program_id']==automatic['id'] for h in revised['program_holds']))

    def test_growth_repeated_collection_revalidates_and_preserves_last_good(self):
        from services.lp.tests.test_kgrowth_notice_terms import notice, DOCUMENT
        n=notice()
        self.report.update(checked_at='2026-11-13T18:00:00+09:00',notices=[n],
                           offering_terms={n['url']:{'commitment_amount_krw':999}})
        first,pages=prepare(self.data,self.report)
        auto=next(p for p in first['programs'] if p.get('auto_extracted'))
        self.assertEqual(auto['commitment_amount_krw'],24_000_000_000)
        self.assertEqual(auto['status'],'접수 마감')
        self.assertIn('<time>2026-12</time>',pages['program-'+auto['id']+'.html'])
        second,_=prepare(first,self.report)
        repeated=next(p for p in second['programs'] if p['id']==auto['id'])
        self.assertEqual(auto,repeated)
        self.assertFalse(any(h['program_id']==auto['id'] for h in second['program_holds']))
        broken=notice(DOCUMENT.replace('▪ 6개','▪ 7개'))
        self.report['notices']=[broken]
        third,_=prepare(second,self.report)
        self.assertEqual(auto,next(p for p in third['programs'] if p['id']==auto['id']))
        self.assertTrue(any(h['program_id']==auto['id'] for h in third['program_holds']))

    def test_growth_mixed_source_is_reviewed_without_other_bank_parser(self):
        from services.lp.tests.test_kgrowth_notice_terms import notice, DOCUMENT
        n=notice(DOCUMENT.replace('▪ 기관전용 사모집합투자기구','▪ 기관전용 사모집합투자기구, 벤처투자조합'))
        self.report.update(checked_at='2026-11-13',notices=[n])
        data,pages=prepare(self.data,self.report)
        self.assertEqual(len(data['programs']),len(self.data['programs']))
        self.assertEqual(data['discovery_candidates'][0]['scope'],'mixed_legal_forms')
        self.assertIn(n['url'],data['kgrowth_offering_terms'])
        self.assertIn('총 240억원',pages['review.html'])
        self.assertFalse(any('공동사업 조건 추출 보류' in h['reason'] for h in data['program_holds']))

    def test_growth_result_is_connected_by_business_not_notice_id(self):
        from services.lp.tests.test_kgrowth_notice_terms import notice
        n=notice();n['title']='【선정공고】'+n['title']
        result={**n,'source_id':'999999','url':n['url'].replace('76543','999999'),
                           'title':n['title'].replace('【선정공고】','【선정결과】').replace('선정계획','선정결과'),'date':'2026-12-08',
                           'attachment_texts':{},'attachment_documents':{},'attachment_hashes':{}}
        self.report.update(checked_at='2026-12-09',notices=[n,result])
        data,_=prepare(self.data,self.report)
        auto=next(p for p in data['programs'] if p.get('auto_extracted'))
        self.assertEqual(auto['status'],'선정 결과 발표')
        self.assertEqual(auto['selected_gps'],[])
        self.assertIn(result['url'],[e['url'] for e in auto['events']])

    def test_growth_amendment_or_cancellation_holds_the_original_business(self):
        from services.lp.tests.test_kgrowth_notice_terms import notice
        n=notice();n['title']='【선정공고】'+n['title']
        self.report.update(checked_at='2026-11-13',notices=[n])
        first,_=prepare(self.data,self.report)
        auto=next(p for p in first['programs'] if p.get('auto_extracted'))
        for title in (n['title']+'(수정)',n['title'].replace('선정계획 공고','선정계획 취소 공고')):
            amended={**n,'source_id':'888888','url':n['url'].replace('76543','888888'),
                     'title':title,'date':'2026-11-12'}
            self.report['notices']=[n,amended]
            data,_=prepare(first,self.report)
            self.assertEqual([auto['id']],[p['id'] for p in data['programs'] if p.get('auto_extracted')])
            self.assertEqual(auto,next(p for p in data['programs'] if p['id']==auto['id']))
            self.assertTrue(any(h['program_id']==auto['id'] and '변경' in h['reason'] for h in data['program_holds']))

    def test_shared_evidence_is_retained_without_approving_fund_terms(self):
        from services.lp.tests.test_lp_shared_notice_catalog import notice
        self.report['checked_at']='2026-10-13'
        self.report['shared_collection']={'notices':[notice()],'coverage':{'notice_count':1}}
        data,pages=prepare(self.data,self.report)
        self.assertEqual(len(self.data['programs']),len(data['programs']))
        self.assertEqual(data['shared_notices'][0]['institution_id'],'cu')
        self.assertIn('신협중앙회',pages['review.html'])
        self.assertIn('공고 본문',pages['review.html'])
        self.report['shared_collection']={'notices':[]}
        again,_=prepare(data,self.report)
        self.assertEqual(again['shared_notices'],data['shared_notices'])

if __name__=='__main__':unittest.main()
