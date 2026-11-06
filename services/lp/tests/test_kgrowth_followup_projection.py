import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services.lp.src.kgrowth_program_review import project, fingerprint, matching_recipe_title
from services.lp.src.collect_kgrowth_programs import event_type


def notice(sid, title, body, day):
    n={'source_id':str(sid),'title':title,'body':body,'date':day,'attachments':[],
       'attachment_hashes':{},'url':f'https://www.kgrowth.or.kr/notice_view.asp?idx={sid}&str_type=1&tab=1'}
    n['sha256']=fingerprint(n)
    return n


class FollowupProjectionTests(unittest.TestCase):
    def setUp(self):
        self.recruit=notice(887,'[재공고]「시험펀드(2차)」 선정계획 공고','선정계획 공고. 운용사1개 선정','2026-05-01')
        self.app=notice(990,'[재공고]「시험펀드(2차)」 접수 현황',
                        '[재공고]「시험펀드(2차)」 접수 현황을 공지합니다.\nㅇ 신청 펀드 수 : 총 2개\nㅇ 운용사명 (가나다순)\n- 시험자산운용\n- 다른운용','2026-05-20')
        self.final=notice(998,'[재공고]「시험펀드 2호」 선정 결과',
                          '[재공고]「시험펀드 2호」 선정 결과를 공지합니다.\n운용사명(가나다순)\n시험 자산운용','2026-06-01')
        self.recipe={'id':'test-reopen','title':'2026 시험펀드 2호 · 재공고','source_title':'시험펀드',
                     'asset_scope':'PE','tracks':{'블라인드':'블라인드'},
                     'sources':[{'source_id':'887','sha256':self.recruit['sha256'],'attachment_hashes':{},'event':'모집 공고'}],
                     'facts':{'segments':{'source_id':'887','quote':'운용사1개 선정','value':[{'name':'블라인드','manager_count':1}]}}}

    def test_new_result_and_roster_use_retained_evidence_without_changing_review_recipe(self):
        before=copy.deepcopy(self.recipe)
        p=project(self.recipe,[self.recruit,self.app,self.final],'2026-06-02')
        self.assertEqual(p['status'],'선정 완료');self.assertEqual(p['selected_gps'][0]['name'],'시험 자산운용')
        self.assertEqual(p['selected_gps'][0]['source_url'],self.final['url'])
        self.assertNotIn('master_id',p['selected_gps'][0])
        self.assertEqual([e['type'] for e in p['events']],['모집 공고','접수 현황','최종 선정'])
        self.assertEqual(p['automatic_followup_evidence']['sha256'],self.final['sha256'])
        self.assertEqual(self.recipe,before)

    def test_original_and_reopen_are_separate_and_changed_explicit_exclusion_held(self):
        original={**self.recipe,'title':'2026 시험펀드 2호'}
        self.assertFalse(matching_recipe_title(original,self.final['title']))
        self.assertTrue(matching_recipe_title(self.recipe,self.final['title']))
        recipe=copy.deepcopy(self.recipe)
        other=notice(880,'「시험펀드 2호」 선정 결과','원래 사업 결과','2026-04-20')
        recipe['related_exclusions']=[{'source_id':'880','sha256':other['sha256'],'attachment_hashes':{}}]
        other['body']='changed'
        with self.assertRaises(ValueError):project(recipe,[self.recruit,self.app,self.final,other],'2026-06-02')

    def test_unapproved_correction_and_missing_count_cannot_update_results(self):
        correction=notice(999,'[재공고]「시험펀드 2호」 정정 공고','정정 공고','2026-06-02')
        with self.assertRaises(ValueError):project(self.recipe,[self.recruit,self.app,self.final,correction],'2026-06-03')
        recipe=copy.deepcopy(self.recipe);recipe['facts']={}
        with self.assertRaises(ValueError):project(recipe,[self.recruit,self.app,self.final],'2026-06-03')

    def test_reopened_final_has_its_stage_but_cancelled_result_does_not(self):
        self.assertEqual(event_type(self.final['title'],self.final['body']),'최종 선정')
        self.assertIsNone(event_type(self.final['title']+' 취소',self.final['body']))


if __name__=='__main__':unittest.main()
