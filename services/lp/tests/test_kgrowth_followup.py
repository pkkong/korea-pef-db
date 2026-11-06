import copy
import unittest
from services.lp.src.kgrowth_followup import recognize_followup, fingerprint


def notice(sid, title, body, date='2026-06-01'):
    n={'source_id':str(sid),'title':title,'body':body,'date':date,
       'url':f'https://www.kgrowth.or.kr/notice_view.asp?idx={sid}&str_type=1&tab=1'}
    n['sha256']=fingerprint(n);return n


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.recipe={'tracks':{'PE':'PE'}}
        self.recruit=notice(887,'[재공고]「시험펀드 2호」 선정계획 공고','공식 모집', '2026-05-01')
        self.final=notice(998,'【선정결과】[재공고]「시험펀드 2호」 선정 결과',
                          '[재공고]「시험펀드 2호」 선정 결과를 공지합니다.\n운용사명(가나다순)\n시험 자산운용')
    def call(self, notices=None, **kw):
        args=dict(recipe=self.recipe,recruitment=self.recruit,preceding_teams={'PE':['시험자산운용','다른운용']},
                  expected_manager_count=1,notices=notices if notices is not None else [self.final],
                  approved_source_ids=['887'],as_of='2026-07-01')
        args.update(kw);return recognize_followup(**args)
    def test_exact_final_and_whitespace_membership_preserve_inputs(self):
        before=copy.deepcopy(self.final)
        r=self.call();self.assertIsNone(r['hold']);self.assertEqual(r['evidence']['names'],['시험 자산운용'])
        self.assertEqual(r['layout'],{'heading':'운용사명(가나다순)','track':'PE','count':1})
        self.assertEqual(self.final,before)
    def test_round_reopen_track_and_quoted_name_not_fuzzy(self):
        for title in ['「시험펀드 2호」 선정 결과','[재공고]「시험펀드 2차」 선정 결과',
                      '[재공고]「시험펀드 2호」「다른펀드」 선정 결과']:
            n=notice(998,title,self.final['body']);self.assertIsNotNone(self.call([n])['hold'])
        self.assertIsNotNone(self.call(recipe={'tracks':{'PE':'PE','VC':'VC'}})['hold'])
    def test_dates_hash_url_and_approval_fail_closed(self):
        for stamp in ['2026-04-01','2026-08-01','2025-06-01']:
            n=copy.deepcopy(self.final);n['date']=stamp;n['sha256']=fingerprint(n)
            self.assertIsNotNone(self.call([n])['hold'])
        for key,value in [('sha256','a'*64),('body','changed'),('url','https://evil.test/x')]:
            n=copy.deepcopy(self.final);n[key]=value;self.assertIsNotNone(self.call([n])['hold'])
        self.assertEqual(self.call(approved_source_ids=['998'])['hold'],'result_already_approved')
    def test_duplicate_results_extra_names_unverified_names_and_attachments_held(self):
        self.assertEqual(self.call([self.final,self.final])['hold'],'multiple_result_records')
        for tail in ['시험 자산운용\n문의: 기타 문장','새로운 운용사','시험자산운용\n시험 자산운용', '첨부와 같이 공지합니다.']:
            n=notice(998,self.final['title'],self.final['body'].rsplit('\n',1)[0]+'\n'+tail)
            self.assertIsNotNone(self.call([n])['hold'])
    def test_amendment_and_first_stage_not_promoted(self):
        for word in ['정정','취소','연장','서류심사','1차']:
            n=notice(998,self.final['title']+' '+word,self.final['body'])
            self.assertIsNotNone(self.call([n])['hold'])
    def test_approved_display_label_and_unique_applicants(self):
        recruit=notice(887,'[재공고]「시험펀드(2차)」 선정계획 공고','공식 모집','2026-05-01')
        applicant=notice(990,'[재공고]「시험펀드(2차)」 접수 현황',
                         '[재공고]「시험펀드(2차)」 접수 현황을 공지합니다.\nㅇ 신청 펀드 수 : 총 2개\nㅇ 운용사명 (가나다순)\n- 시험자산운용\n- 다른운용','2026-05-20')
        kwargs=dict(recipe={'tracks':{'PE':'PE'},'title':'2026 시험펀드 2호 · 재공고'},
                    recruitment=recruit,preceding_teams={})
        result=self.call([applicant,self.final],**kwargs)
        self.assertIsNone(result['hold']);self.assertEqual(result['preceding_layout']['count'],2)
        self.assertEqual(result['preceding_match'],applicant)
        self.assertIsNotNone(self.call([applicant,applicant,self.final],**kwargs)['hold'])
        self.assertIsNotNone(self.call([applicant,self.final],**{**kwargs,'recipe':{'tracks':{'PE':'PE'}}})['hold'])
        broken=copy.deepcopy(applicant);broken['body']=broken['body'].replace('총 2개','총 3개');broken['sha256']=fingerprint(broken)
        self.assertIsNotNone(self.call([broken,self.final],**kwargs)['hold'])

    def test_preliminary_final_markers_and_real_attachment_metadata_held(self):
        for marker in ('예비','예정','조건부','후보','우선협상'):
            n=notice(998,self.final['title']+' '+marker,self.final['body'])
            self.assertIsNotNone(self.call([n])['hold'],marker)
        for marker in ('우선협상','예비','조건부'):
            n=notice(998,self.final['title'],self.final['body']+'\n'+marker)
            self.assertEqual(self.call([n])['hold'],'non_simple_result_body')
        for metadata in ({'attachments':[{'url':'https://www.kgrowth.or.kr/down_file.asp?idx=998&SelType=Notice1'}]},
                         {'attachment_hashes':{'https://www.kgrowth.or.kr/file':'a'*64}}):
            n={**self.final,**metadata}
            self.assertEqual(self.call([n])['hold'],'result_attachments_require_review')
            applicant=notice(990,'[재공고]「시험펀드 2호」 접수 현황',
                '[재공고]「시험펀드 2호」 접수 현황\nㅇ 신청 펀드 수 : 총 1개\n운용사명(가나다순)\n시험자산운용','2026-05-20')
            applicant.update(metadata)
            self.assertEqual(self.call([applicant,self.final],preceding_teams={})['hold'],
                             'applicant_attachments_require_review')

    def test_bullet_heading_and_name_supported(self):
        n=notice(998,self.final['title'],self.final['body'].replace('운용사명','ㅇ 운용사 명').replace('\n시험','\n- 시험'))
        self.assertIsNone(self.call([n])['hold'])

if __name__=='__main__':unittest.main()
