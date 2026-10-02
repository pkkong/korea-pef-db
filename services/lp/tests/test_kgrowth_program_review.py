import copy
import json
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))
from kgrowth_program_review import candidate_queue, fingerprint, link_suggestions, project, recipes
from publish_lp_programs import prepare


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.notices = json.loads((Path(__file__).parent/'fixtures/kgrowth_kculture.json').read_text())
        self.recipe = recipes()[0]

    def test_four_stages_and_two_tracks(self):
        p = project(self.recipe,self.notices)
        self.assertEqual([len(p['applicants_gps']),len(p['shortlisted_gps']),len(p['selected_gps'])],[13,6,2])
        self.assertEqual(p['commitment_amount_krw'],80000000000)
        self.assertEqual(p['deadline'],'2026-08-12T16:00:00+09:00')
        self.assertEqual([g['asset_scope'] for g in p['selected_gps']],['AI·IP','콘텐츠 혁신'])
        self.assertIn('목표 결성액',p['primary_investment']['items'][0])

    def test_changed_source_or_attachment_requires_new_review(self):
        for field,value in [('body','changed'),('attachment_hashes',{'file':'changed'})]:
            n=copy.deepcopy(self.notices); n[0][field]=value
            with self.assertRaises(ValueError):project(self.recipe,n)

    def test_missing_fact_evidence_rejected(self):
        self.notices[0]['attachment_texts']={}
        with self.assertRaises(ValueError):project(self.recipe,self.notices)

    def test_new_correction_holds_existing_program(self):
        self.notices.append({'source_id':'9999','title':'「k-컬처 밸류업 펀드」 정정 공고'})
        with self.assertRaises(ValueError):project(self.recipe,self.notices)

    def test_publisher_adds_reviewed_program_but_preserves_on_later_change(self):
        data=json.loads((SRC.parents[2]/'data/lp_programs_pilot.json').read_text())
        legacy=next(p for p in data['programs'] if p['institution_id']=='kgrowth')
        report={'checked_at':'2026-09-29','notices':self.notices,'programs':[legacy]}
        updated,pages=prepare(data,report)
        self.assertEqual(len(updated['programs']),6)
        self.assertIn('program-'+self.recipe['id']+'.html',pages)
        self.notices[0]['body']='changed'
        kept,_=prepare(updated,report)
        self.assertEqual(next(p for p in kept['programs'] if p['id']==self.recipe['id'])['commitment_amount_krw'],80000000000)
        self.assertIn(self.recipe['id'],[h['program_id'] for h in kept['program_holds']])

    def test_similar_series_and_nonbusiness_notices_stay_separate(self):
        notices=[{'source_id':str(i),'title':title,'date':'2026-09-01','url':'https://example.com'} for i,title in enumerate([
            '【선정결과】「부산 펀드 2호」 선정결과','【선정공고】[재공고]「부산 펀드(2차)」 공고',
            '【기타】 연락처 안내','【선정결과】「기술혁신7호(M.AX)」 선정결과','【선정결과】「기술혁신7호(지역)」 선정결과'])]
        groups=candidate_queue(notices)
        self.assertEqual(len(groups),5)
        self.assertEqual(groups[1]['disposition'],'기존 차수와 분리 검토')
        self.assertEqual(groups[2]['disposition'],'사업 공고 아님')

class AdditionalReviewTests(unittest.TestCase):
    def setUp(self):
        self.notices=json.loads((Path(__file__).parent/'fixtures/kgrowth_additional.json').read_text())
        self.recipes={r['id']:r for r in recipes()[1:]}

    def test_separate_rounds_and_actual_selection(self):
        original=project(self.recipes['kgrowth-2026-busan-2'],self.notices)
        reopen=project(self.recipes['kgrowth-2026-busan-2-reopen'],self.notices)
        self.assertEqual(original['manager_count_label'],'3개사')
        self.assertEqual(len(original['selected_gps']),2)
        self.assertEqual(reopen['commitment_amount_krw'],15000000000)
        self.assertEqual(reopen['status'],'모집 공고')
        after=project(self.recipes['kgrowth-2026-busan-2-reopen'],self.notices,'2026-10-01T07:01:00+00:00')
        self.assertEqual(after['status'],'접수 마감')
        before=project(self.recipes['kgrowth-2026-busan-2-reopen'],self.notices,'2026-10-01T06:59:00+00:00')
        self.assertEqual(before['status'],'모집 공고')
        self.assertEqual(reopen['selected_gps'],[])
        self.assertEqual(reopen['deadline'],'2026-10-01T16:00:00+09:00')

    def test_changed_related_round_is_not_silently_ignored(self):
        next(n for n in self.notices if n['source_id']=='1119')['body']+=' 변경'
        with self.assertRaises(ValueError):project(self.recipes['kgrowth-2026-busan-2'],self.notices)

    def test_flat_lists_and_html_joined_bullets(self):
        p=project(self.recipes['kgrowth-2026-zero-emission'],self.notices)
        self.assertEqual([len(p['applicants_gps']),len(p['shortlisted_gps']),len(p['selected_gps'])],[6,4,2])
        self.assertIn('이지스자산운용',p['shortlisted_gps'])
        self.assertIn('제이케이엘인베스트먼트',p['shortlisted_gps'])
        self.assertEqual(p['commitment_amount_krw'],40000000000)
        self.assertIn('약정총액의 70%',p['primary_investment']['items'][0])

    def test_applicants_visible_without_shortlist(self):
        from lp_program_detail import render_detail_body
        p=project(self.recipes['kgrowth-2026-max-7'],self.notices)
        for gp in p['selected_gps']:gp['page_key']=gp['id']
        html=render_detail_body(p)
        self.assertIn('접수 6개 팀',html)
        self.assertIn('노틱인베스트먼트',html)
        self.assertEqual(p['selected_gps'][0]['master_id'],'719')
        self.assertNotIn('1차 통과',html)
        self.assertEqual(p['commitment_amount_krw'],100000000000)

    def test_unknown_final_manager_rejected_even_without_shortlist(self):
        from kgrowth_program_review import fingerprint
        r=copy.deepcopy(self.recipes['kgrowth-2026-max-7'])
        n=next(n for n in self.notices if n['source_id']=='1112')
        n['body']=n['body'].replace('우리프라이빗에퀴티자산운용','다른운용사')
        r['sources'][-1]['sha256']=fingerprint(n)
        with self.assertRaises(ValueError):project(r,self.notices)

    def test_classification_expires_when_attachment_changes(self):
        from kgrowth_program_review import notice_classification
        n=next(n for n in self.notices if n['source_id']=='1122')
        self.assertEqual(notice_classification(n)['label'],'제출서식')
        n['attachment_hashes']={}
        self.assertIsNone(notice_classification(n))


    def test_new_busan_result_is_ambiguous_review_candidate(self):
        new={'source_id':'9999','title':'【선정결과】「부산 미래산업 전환펀드 2호」 위탁운용사 선정 결과',
             'date':'2026-10-02','body':'운용사명\n새운용사','url':'https://www.kgrowth.or.kr/notice_view.asp?idx=9999',
             'attachment_hashes':{}}
        notices=self.notices+[new]
        suggestions=link_suggestions(notices)
        self.assertEqual(len(suggestions),1)
        self.assertEqual(suggestions[0]['stage'],'최종 선정')
        self.assertEqual({p['id'] for p in suggestions[0]['programs']},
                         {'kgrowth-2026-busan-2','kgrowth-2026-busan-2-reopen'})
        self.assertEqual(suggestions[0]['sha256'],fingerprint(new))
        for key in ('kgrowth-2026-busan-2','kgrowth-2026-busan-2-reopen'):
            with self.assertRaisesRegex(ValueError,'requires review'):
                project(self.recipes[key],notices)

    def test_candidate_does_not_publish_unreviewed_gp(self):
        seed=json.loads((SRC.parents[2]/'data/lp_programs_pilot.json').read_text())
        report={'checked_at':'2026-10-02T02:00:00+00:00','notices':self.notices,
                'programs':[next(p for p in seed['programs'] if p['id']=='kgrowth-2026-bank-valueup-3')]}
        current,_=prepare(seed,report)
        old=next(p for p in current['programs'] if p['id']=='kgrowth-2026-busan-2-reopen')
        report['notices'].append({'source_id':'9999','title':'【선정결과】「부산 미래산업 전환펀드 2호」 위탁운용사 선정 결과',
                                  'date':'2026-10-02','body':'운용사명\n새운용사',
                                  'url':'https://www.kgrowth.or.kr/notice_view.asp?idx=9999','attachment_hashes':{}})
        updated,_=prepare(current,report)
        new=next(p for p in updated['programs'] if p['id']==old['id'])
        self.assertEqual(new['status'],'접수 마감')
        self.assertEqual(new['selected_gps'],[])
        self.assertIn(old['id'],[h['program_id'] for h in updated['program_holds']])
        self.assertEqual(len(updated['link_suggestions']),1)
        self.assertEqual(len(updated['link_suggestions'][0]['programs']),2)

    def test_new_max_result_suggested_but_regional_result_not_merged(self):
        new={'source_id':'9999','title':'【선정결과】「기술혁신전문펀드 7호」 M.AX 산업대전환 혁신 서류심사 결과',
             'date':'2026-10-02','body':'공식 결과','url':'https://www.kgrowth.or.kr/notice_view.asp?idx=9999',
             'attachment_hashes':{}}
        suggestions=link_suggestions(self.notices+[new])
        self.assertEqual([(s['stage'],[p['id'] for p in s['programs']]) for s in suggestions],
                         [('서류심사 결과',['kgrowth-2026-max-7'])])
        with self.assertRaisesRegex(ValueError,'requires review'):
            project(self.recipes['kgrowth-2026-max-7'],self.notices+[new])


class ScopeReviewTests(unittest.TestCase):
    def setUp(self):
        self.notices=json.loads((Path(__file__).parent/'fixtures/kgrowth_scope_2026.json').read_text())
        self.recipes={r['id']:r for r in recipes()}

    def test_regional_program_keeps_applicants_and_selected_managers(self):
        p=project(self.recipes['kgrowth-2026-tech-7-regional'],self.notices)
        self.assertEqual([len(p['applicants_gps']),len(p['selected_gps'])],[25,4])
        self.assertEqual(p['commitment_amount_krw'],50000000000)
        self.assertEqual(p['segments'][0]['per_fund_max_krw'],12500000000)
        self.assertIn('투자집행금액의 80%',p['primary_investment']['items'][2])
        self.assertEqual([g['name'] for g in p['selected_gps']],
                         ['마그나인베스트먼트','엔에이치벤처투자','이앤벤처파트너스','코리아에셋투자증권'])

    def test_ibk_hwp_facts_are_bound_to_reviewed_file_hash(self):
        p=project(self.recipes['kgrowth-2026-ibk-productive-1-general'],self.notices,
                  '2026-10-02T02:00:00+00:00')
        self.assertEqual(p['status'],'모집 공고')
        self.assertEqual(p['commitment_amount_krw'],35000000000)
        self.assertEqual([s['manager_count'] for s in p['segments']],[5,5])
        self.assertEqual(sum(s['amount_krw'] for s in p['segments']),35000000000)
        self.assertNotIn('30%',str(p['primary_investment']))
        self.assertEqual(p['selected_gps'],[])
        changed=copy.deepcopy(self.notices)
        next(n for n in changed if n['source_id']=='1121')['attachment_hashes']={}
        with self.assertRaisesRegex(ValueError,'attachment changed'):
            project(self.recipes['kgrowth-2026-ibk-productive-1-general'],changed)

    def test_publication_with_reviewed_new_sources(self):
        all_notices=self.notices[:]
        for filename in ('kgrowth_kculture.json','kgrowth_additional.json'):
            all_notices+=json.loads((Path(__file__).parent/'fixtures'/filename).read_text())
        report={'checked_at':'2026-10-02T02:00:00+00:00',
                'notices':list({n['source_id']:n for n in all_notices}.values())}
        seed=json.loads((SRC.parents[2]/'data/lp_programs_pilot.json').read_text())
        report['programs']=[next(p for p in seed['programs'] if p['id']=='kgrowth-2026-bank-valueup-3')]
        updated,pages=prepare(seed,report)
        self.assertEqual(len(updated['programs']),12)
        self.assertEqual(updated['program_holds'],[])
        self.assertIn('program-kgrowth-2026-tech-7-regional.html',pages)
        self.assertIn('program-kgrowth-2026-ibk-productive-1-general.html',pages)

if __name__=='__main__':unittest.main()
