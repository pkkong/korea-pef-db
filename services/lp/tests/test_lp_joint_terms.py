"""Joint totals, per-fund targets and overlapping obligations stay distinct."""
import copy
import unittest
from services.lp.src.lp_joint_terms import extract_joint_terms, discovered_joint_terms

PLAN = '''주관기관○한국산업은행(산은),중소기업은행(기은),한국수출입은행(수은)
위탁운용금액○위탁운용금액:총4,500억원(주관기관별각1,500억원)
분야주관기관출자금액주관기관출자비율펀드별목표결성금액선정운용사수조성목표
대형1,926억원64.20%3,000억원1개3,000억원
중형2,574억원64.35%2,000억원2개4,000억원
합계4,500억원64.29%-3개7,000억원
접수일시및접수처○2026년9월30일(수)10:00~15:00
주목적 투자의무 투자비율
❶ 중소·중견기업에 기업당 50억원 이상 신주 투자약정총액의 50%
❷ 중소·중견기업의 해외진출 지원에 투자약정총액의 30%
❸ 중소기업에 투자 약정총액의 30%
주관기관출자비율○기타조건
선정일정일자내용비고2026.9.30(수)제안서접수10:00∼15:00
2026.10월현장실사및심사2026.11월최종선정*세부일정변동가능'''


def notice(text=PLAN):
    attachment='https://www.kdb.co.kr/fileView?groupId=discovered&fileId=discovered'
    return {'institution_id':'kdb','source_id':'any-board-row','title':'공동펀드 모집 공고',
            'date':'2026-09-07','url':'https://www.kdb.co.kr/official',
            'attachment_texts':{attachment:text},'attachment_hashes':{attachment:'checked-bytes'}}


class JointTermsTests(unittest.TestCase):
    def test_aggregate_fields_are_not_divided_into_unannounced_allocations(self):
        result=extract_joint_terms(notice())
        self.assertEqual(result['total_commitment_amount_krw'],450_000_000_000)
        self.assertEqual(result['contribution_allocations']['한국수출입은행'],150_000_000_000)
        self.assertEqual(result['manager_count'],3)
        self.assertEqual(result['segments'][1]['amount_krw'],257_400_000_000)
        self.assertEqual(result['segments'][1]['per_fund_target_krw'],200_000_000_000)
        self.assertNotIn('per_fund_max_krw',result['segments'][1])
        self.assertNotIn('bank_allocations',result['segments'][1])
        self.assertEqual(result['deadline'],'2026-09-30T15:00:00+09:00')
        self.assertEqual(result['planned_schedule'][1]['date'],'2026-11')

    def test_overlapping_obligations_can_exceed_one_hundred_in_sum(self):
        result=extract_joint_terms(notice())
        self.assertEqual(sum(item['ratio_percent'] for item in result['primary_obligations']),110)
        self.assertEqual(len(result['primary_obligations']),3)
        self.assertEqual(result['amount_status'],'planned')

    def test_altered_totals_targets_units_or_missing_columns_are_held(self):
        for text in (PLAN.replace('합계4,500','합계4,600'),
                     PLAN.replace('2개4,000억원','2개4,100억원'),
                     PLAN.replace('64.35%','65.35%'),
                     PLAN.replace('억원','백만원'),
                     PLAN.replace('주관기관별각1,500','주관기관별각1,400'),
                     PLAN.replace('10:00~15:00','16:00~15:00'),
                     PLAN.replace('약정총액의 30%','약정총액의 130%'),
                     PLAN.replace('2026.11월최종선정','')):
            # A missing planned final date is optional, but other data must fail.
            if '2026.11월최종선정' not in text and text==PLAN.replace('2026.11월최종선정',''):
                self.assertEqual(len(extract_joint_terms(notice(text))['planned_schedule']),1)
            else:
                with self.assertRaises(ValueError):extract_joint_terms(notice(text))

    def test_missing_official_original_or_digest_not_used(self):
        n=notice();n['attachment_hashes']={}
        with self.assertRaises(ValueError):extract_joint_terms(n)
        n=notice();n['url']='https://unofficial.example/notice'
        with self.assertRaises(ValueError):extract_joint_terms(n)

    def test_candidates_are_grouped_and_faq_is_not_a_terms_override(self):
        n=notice();faq=notice(PLAN.replace('4,500','9,000'));faq['url']='https://www.kdb.co.kr/faq'
        candidates=[{'program_key':'same-business','scope':'mixed_legal_forms','recruitment_url':n['url']},
                    {'program_key':'same-business','scope':'mixed_legal_forms','recruitment_url':n['url']}]
        terms,holds=discovered_joint_terms(candidates,[n,faq])
        self.assertEqual(holds,[])
        self.assertEqual(len(terms),1)
        self.assertEqual(terms['same-business']['total_commitment_amount_krw'],450_000_000_000)


if __name__=='__main__':unittest.main()
