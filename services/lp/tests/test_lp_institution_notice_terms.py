import unittest
from services.lp.src.lp_institution_notice_terms import extract_terms


class InstitutionTermsTests(unittest.TestCase):
    def notice(self, body, title='국내 PE 블라인드 위탁운용사 선정 공고'):
        return {'url':'https://www.pmaa.or.kr/notice', 'title':title, 'date':'2025-01-01',
                'body':body,'sha256':'a'*64,'attachment_texts':{}}

    def test_pe_vc_totals_and_count_are_independently_reconciled(self):
        n=self.notice('출자 규모 : 총 1,800억원 - PE 부문 (1,200억원) : 각 400억원, 총 3개사 - VC 부문 (600억원) : 각 200억원, 총 3개사', '국내 PE·VC 블라인드 위탁운용사 선정 공고')
        result=extract_terms(n)
        self.assertEqual(result['commitment_amount_krw'],120_000_000_000)
        self.assertEqual(result['manager_count'],3)
        self.assertEqual(result['per_fund_amount_krw'],40_000_000_000)
        self.assertEqual(result['amount_scope'],'pe_only')
        with self.assertRaises(ValueError):
            extract_terms({**n,'body':n['body'].replace('1,800','1,900')})

    def test_blind_and_coinvestment_are_not_summed(self):
        n=self.notice('모집규모 : Buyout·Growth 2,000억원 이내 4개사 / 공동투자 1,500억원 이내 1개사')
        result=extract_terms(n)
        self.assertEqual(result['commitment_label'],'2,000억원 이내')
        self.assertEqual(result['manager_count'],4)
        self.assertTrue(result['extraction_evidence']['blind_allocation'])

    def test_per_fund_limit_is_never_whole_total(self):
        result=extract_terms(self.notice('펀드별 출자금액 : 펀드당 500억원 이내. 선정 운용사 수 - 미정'))
        self.assertEqual(result['per_fund_amount_krw'],50_000_000_000)
        self.assertNotIn('commitment_amount_krw',result)
        self.assertNotIn('manager_count',result)

    def test_conflicting_delivery_cutoff_retains_only_date(self):
        result=extract_terms(self.notice('마감일시: 2025.7.22.(화) 12:00 접수마감 7월22일 12시. 직접제출 : 퀵은 당일 한정(7월22일(화)15시까지 미제출시 접수불가)'))
        self.assertEqual(result['deadline'],'2025-07-22')
        self.assertEqual(result['deadline_precision'],'date')
        self.assertIn('불일치',result['deadline_error'])

    def test_total_count_qualifier_and_labeled_deadline(self):
        result=extract_terms(self.notice('위탁운용금액 : 총 4,000억원 이내. 선정 운용사 수 : 평가결과 상위 4개사 이내. 배정금액 : 1개사별 1,000억원 이하. 제출기한 : 2025년 9월 5일 오후 3시까지'))
        self.assertEqual(result['commitment_label'],'4,000억원 이내')
        self.assertEqual(result['manager_count_label'],'4개사 이내')
        self.assertEqual(result['per_fund_qualifier'],'이내')
        self.assertEqual(result['deadline'],'2025-09-05T15:00:00+09:00')


if __name__ == '__main__':
    unittest.main()
