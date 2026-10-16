import copy
import unittest
from services.lp.src.collect_lp_original_notices import original_body_hash

from services.lp.src.lp_shared_notice_terms import extract_shared_terms

STAMP='2026-10-14T09:00:00+09:00'


def notice(body, title='2026년 전문건설공제조합 국내 PE 블라인드 선정 공고', institution='kfinco'):
    return {'source_channel':'kofia_212','source_id':'kofia_212:987654',
            'url':'https://www.kofia.or.kr/brd/m_212/view.do?seq=987654',
            'institution_id':institution,'title':title,'date':'2026-07-01','body':body,
            'sha256':'a'*64,'attachment_hashes':{},'attachment_texts':{},'source_provenance':{}}


class SharedTermsTests(unittest.TestCase):
    def test_single_track_labels_and_planned_month_without_inventing_purpose(self):
        n=notice('선정 운용사 : 1개사 약정 예정금액 : 550억 원 접수 마감 : 2026년 10월 12일(월) 15시 이전 '
                 '추진 일정 최종 선정 : 2026년 11월 중')
        result=extract_shared_terms(n,STAMP)
        self.assertEqual(result['commitment_amount_krw'],55_000_000_000)
        self.assertEqual(result['per_fund_amount_krw'],55_000_000_000)
        self.assertEqual(result['deadline'],'2026-10-12T15:00:00+09:00')
        self.assertEqual(result['schedule_stages'][-1]['date'],'2026-11')
        self.assertEqual(result['schedule_stages'][-1]['status'],'planned')
        self.assertIn('primary_investment',result['missing_fields'])

    def test_integrated_pe_vc_is_never_split_or_divided_by_manager_count(self):
        n=notice('출자대상 : 국내 블라인드 PE·VC 펀드 출자금액 : 총 3,400억원 이내 선정 수 : 총 11개사 내외 '
                 '펀드별 100~900억원 범위 내 자율 제안 제안서 접수 마감일 : 2026. 7. 31(금) 15:00',
                 '2026년 중소기업중앙회 국내 블라인드 펀드 선정 공고','kbiz')
        result=extract_shared_terms(n,STAMP)
        self.assertEqual(result['amount_scope'],'combined_pe_vc')
        self.assertIn('PE·VC 합계',result['commitment_label'])
        self.assertEqual(result['manager_count'],11)
        self.assertEqual(result['per_fund_range_krw'],[10_000_000_000,90_000_000_000])
        self.assertNotIn('per_fund_amount_krw',result)

    def test_pe_league_table_reconciles_variable_values_and_preserves_week_precision(self):
        n=notice('출자규모 : 총 2,900억원 (PE 부문 : 1,700억원 / VC 부문 : 1,200억원) '
                 '주요 출자조건 부문 리그별 펀드별 출자규모 운용사 수 결성 예정규모 PE '
                 '대형 500억 1개사 내외 중형 이하 300억 4개사 내외 VC 일반 300억 4개사 '
                 '선정방법 선정 일정 ’26.10월 둘째 주 1차(정량)평가 ’26.10월 다섯째 주 최종 선정',
                 '2026년 과학기술인공제회 국내 PE·VC 블라인드 선정 공고','sema')
        result=extract_shared_terms(n,STAMP)
        self.assertEqual(result['commitment_amount_krw'],170_000_000_000)
        self.assertEqual(result['manager_count'],5)
        self.assertEqual(sum(s['amount_krw'] for s in result['segments']),170_000_000_000)
        self.assertEqual(result['schedule_stages'][-1]['date_label'],'10월 다섯째주')
        self.assertNotIn('T',result['schedule_stages'][-1]['date'])
        broken=copy.deepcopy(n);broken['body']=broken['body'].replace('1,700','1,800')
        with self.assertRaises(ValueError):extract_shared_terms(broken,STAMP)

    def test_same_business_original_matrix_binds_pe_columns_and_range(self):
        n=notice('기관 원문 참조',"'26년 군인공제회 국내 PE·VC 블라인드 펀드 선정계획 공고",'mmaa')
        url='https://www.mmaa.or.kr/web/contents/notice.do?schM=view&id=987654'
        n['source_provenance']['original_links']=[{'url':url}]
        body=('선정 개요 ▪ 운용 목적 : 국내 기업 블라인드 투자를 통한 기금 수익 제고 ▪ 위탁 운용 규모 '
              '(억원, 개사) 구 분 계 PE VC 출자 규모(내외) 1,000 700 300 운용사(내외) 8 5 3 '
              '주요 출자 조건 구 분 PE 분야 VC 분야 본회 출자규모 100억원 ~ 200억원 내외 100억원 내외 '
              "선정 절차 및 일정 '26.8.14.(금) 제안서 접수 마감 14:00 까지 '26.9월말 ~ 10월초 최종 선정")
        n['original_notices']=[{'institution_id':'mmaa','url':url,'title':n['title'],'date':'2026-07-31',
                               'body':body,'sha256':'b'*64,'checked_at':'2026-10-14T08:00:00+09:00',
                               'matched_republication_url':n['url'],'attachments':[],
                               'attachment_hashes':{},'attachment_texts':{}}]
        n['original_notices'][0].update(hash_kind='semantic_v1',sha256=original_body_hash(n['original_notices'][0]))
        result=extract_shared_terms(n,STAMP)
        self.assertEqual(result['commitment_amount_krw'],70_000_000_000)
        self.assertEqual(result['manager_count'],5)
        self.assertEqual(result['per_fund_range_krw'],[10_000_000_000,20_000_000_000])
        self.assertIn('수익 제고',result['primary_investment']['text'])
        self.assertEqual(result['schedule_stages'][-1]['precision'],'month_range')
        self.assertEqual(result['schedule_stages'][-1]['end_date'],'2026-10')
        self.assertEqual(result['extraction_evidence']['pe_total'][0]['source_url'],url)
        n['original_notices'][0]['title']=n['title'].replace('26년','25년')
        with self.assertRaises(ValueError):extract_shared_terms(n,STAMP)

    def test_month_and_during_same_month_agree_but_different_month_does_not(self):
        n=notice('출자규모: 총 300억원 추진 일정 최종 선정:2026.9월')
        url='https://www.kofia.or.kr/brd/m_212/down.do?seq=987654'
        n['attachment_hashes']={url:'c'*64}
        n['attachment_texts']={url:'추진 일정 최종 선정:2026.9월 중'}
        result=extract_shared_terms(n,STAMP)
        self.assertEqual(result['schedule_stages'][-1]['date_label'],'9월 중')
        self.assertEqual(result['schedule_stages'][-1]['status'],'planned')
        n['attachment_texts'][url]='추진 일정 최종 선정:2026.10월 중'
        with self.assertRaises(ValueError):extract_shared_terms(n,STAMP)

    def test_conflicting_deadlines_or_amounts_are_held(self):
        n=notice('출자규모: 총 300억원 접수마감: 2026.10.12.15:00')
        url='https://www.kofia.or.kr/brd/m_212/down.do?seq=987654'
        n['attachment_hashes']={url:'c'*64}
        n['attachment_texts']={url:'출자규모: 총 400억원 접수마감: 2026.10.13.15:00'}
        with self.assertRaises(ValueError):extract_shared_terms(n,STAMP)

    def test_combined_manager_count_is_not_assigned_to_a_pe_allocation(self):
        n=notice('출자규모: 총 3,000억원 (PE 부문 1,000억원 / VC 부문 2,000억원) 선정 수:10개사 내외',
                 '2026년 국내 PE·VC 블라인드 선정 공고')
        result=extract_shared_terms(n,STAMP)
        self.assertEqual(result['commitment_amount_krw'],100_000_000_000)
        self.assertNotIn('manager_count',result)
        self.assertIn('manager_count',result['missing_fields'])

    def test_mixed_offering_fields_outside_strategy_window_keep_combined_total(self):
        n=notice('출자규모: 총 3,000억원 PE 부문, VC 부문 모집 선정 수:10개사 내외')
        result=extract_shared_terms(n,STAMP)
        self.assertEqual(result['amount_scope'],'combined_pe_vc')
        self.assertIn('PE·VC 합계',result['commitment_label'])

    def test_other_fund_investors_are_not_a_joint_lp_program(self):
        n=notice('선정 운용사:1개사 약정 예정금액:300억원 펀드 규모 5,000억원 이상 '
                 '공동출자자 기관 및 법인 출자 원칙 접수 마감:2026년10월12일15시 '
                 '추진 일정 최종 선정:2026년11월 중')
        result=extract_shared_terms(n,STAMP)
        self.assertEqual(result['commitment_amount_krw'],30_000_000_000)
        self.assertEqual(result['manager_count'],1)
        self.assertEqual(result['schedule_stages'][-1]['date_label'],'11월 중')

    def test_joint_amounts_need_institution_allocation_instead_of_total_assumption(self):
        n=notice('공동 출자 총액 300억원 출자규모: 총 300억원 선정운용사:1개사')
        with self.assertRaises(ValueError):extract_shared_terms(n,STAMP)

    def test_foreign_attachment_and_faq_do_not_supply_recruitment_facts(self):
        n=notice('출자규모: 총 300억원')
        n['attachment_hashes']={'https://example.com/x.pdf':'c'*64}
        n['attachment_texts']={'https://example.com/x.pdf':'선정 수:1개사'}
        with self.assertRaises(ValueError):extract_shared_terms(n,STAMP)
        n=notice('출자규모: 총 300억원',title='2026년 국내 PE 블라인드 FAQ 공고')
        with self.assertRaises(ValueError):extract_shared_terms(n,STAMP)

    def test_fund_size_and_historical_capital_are_not_commitment_amounts(self):
        n=notice('최소 결성금액 1,000억원 운용사 AUM 2,000억원 펀드별 출자규모 300억원 선정 운용사:1개사')
        result=extract_shared_terms(n,STAMP)
        self.assertNotIn('commitment_amount_krw',result)
        self.assertNotIn('per_fund_amount_krw',result)


if __name__=='__main__':unittest.main()
