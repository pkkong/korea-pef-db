import json,unittest
from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src.lp_notice_publication import publish_basic_notices
from services.lp.tests.test_lp_board_adapter_kfinco import row,listing,detail,public

STAMP='2026-10-26T00:00:00+00:00'
A='NT20260618000001';B='NT20260930000002';C='NT20261020000003'

def collect(with_result=False,linked=True):
    rows=[row(A,date='2026-06-18'),row(B,date='2026-09-30')]
    body=lambda deadline,month: ('<p>2026년 국내 사모투자 블라인드펀드 위탁운용사 선정 계획 공고 '
        '선정 개요 선정 운용사 1개사 조합 약정 금액 총 300억원 펀드 규모 5,000억원 이상 '
        '투자 부문 국내 사모투자(PE) 투자 기구 기관전용 사모집합투자기구 '
        '진행 일정 접수 마감: '+deadline+' 최종 선정: '+month+'월 중</p>')
    bodies={public(A):detail(rows[0],body('2026.7.1 15:00','9')), public(B):detail(rows[1],body('2026.10.12 15:00','11'))}
    if with_result:
        rows.append(row(C,date='2026-10-20',title='2026년 국내 사모투자 위탁운용사 선정 결과 공고'))
        bodies[public(C)]=detail(rows[-1],'<p>공식 심사 결과를 안내합니다.</p>'+('<a href="'+public(B)+'">모집 원공고</a>' if linked else ''))
    def fetch(url,referer=None):
        return (bodies[url] if url in bodies else listing(rows)).encode()
    return boards.collect({'kfinco':boards.load_configs()['kfinco']},lambda c:fetch,STAMP)

class KfincoTermsTests(unittest.TestCase):
    def test_two_recruitments_keep_separate_terms_and_existing_identity(self):
        r=collect();self.assertFalse(r['holds']);self.assertEqual(len(r['notices']),2)
        programs,holds=publish_basic_notices({'programs':[],'institution_notices':r['notices']},[],STAMP)
        self.assertFalse(holds);self.assertEqual(len(programs),2)
        by_date={p['events'][0]['date']:p for p in programs}
        for day,deadline,month in [('2026-06-18','2026-07-01T15:00:00+09:00','2026-09'),('2026-09-30','2026-10-12T15:00:00+09:00','2026-11')]:
            p=by_date[day];self.assertEqual(p['deadline'],deadline)
            self.assertEqual(p['commitment_amount_krw'],30_000_000_000);self.assertEqual(p['manager_count'],1)
            self.assertTrue(any(s['stage']=='selection' and s['date']==month for s in p['schedule_stages']))
            self.assertFalse(p['selected_gps'])
        later,_=publish_basic_notices({'programs':programs,'institution_notices':r['notices']},[],STAMP)
        self.assertEqual({p['id'] for p in later},{p['id'] for p in programs})

    def test_result_requires_a_unique_official_recruitment_link(self):
        for linked in [True,False]:
            r=collect(with_result=True,linked=linked);self.assertFalse(r['holds'])
            programs,holds=publish_basic_notices({'programs':[],'institution_notices':r['notices']},[],STAMP)
            self.assertEqual(len(programs),2)
            june=next(p for p in programs if p['events'][0]['date']=='2026-06-18')
            september=next(p for p in programs if p['events'][0]['date']=='2026-09-30')
            self.assertEqual(len(june['events']),1)
            self.assertEqual(len(september['events']),2 if linked else 1)
            self.assertEqual(any(h['stage']=='basic_stage_link' for h in holds),not linked)
