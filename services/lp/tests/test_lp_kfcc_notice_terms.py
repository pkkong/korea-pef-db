import copy
import unittest
from services.lp.src.lp_institution_notice_terms import extract_terms
from services.lp.src.lp_kfcc_notice_terms import allocation
from services.lp.src.lp_notice_publication import _scope

BODY = '''1. PE 부문선정개요
구분\t구분\t전략\t세부전략\t선정수\t총위탁금액\t운용사별 위탁금액
국 내\tPE\tSpecial Situation\t특수상황 전략에 50% 이상 투자\t2개사\t1,200억원\t500~700억원
국 내\tPE\tBuyout, Growth\tBuyout 또는 Growth Capital 50% 이상 투자\t8개사\t3,200억원\t300~500억원
1-1. 선정 기준
운용 방식\t위탁펀드형 대체투자 (블라인드형)
선정 방식\t공개모집을 통한 경쟁방식
선정 대상\t기관전용 사모 집합투자기구
2. VC 부문 선정 개요
구분\t구분\t세부전략\t선정수\t총위탁금액\t운용사별 위탁금액
국 내\tPE\t벤처기업\t2개사\t600억원\t200~300억원
3. 추진일정
② 1차심사\t5월 2주 ~ 5월 4주\t심사
③ 2차심사\t5월 4주 ~ 6월 1주\t심사
④ 현장실사\t6월 1주 ~ 2주\t심사
⑤ 최종선정\t6월 3주 ~ 4주\t심사
접수기한 : 2025년 05월 14일 14시까지'''


class KfccTermsTests(unittest.TestCase):
    def notice(self, body=BODY):
        return {'institution_id': 'kfcc', 'source_channel': 'institution_board',
                'url': 'https://www.kfcc.co.kr/mgNotice/mgNoticeDetail.do?no=1',
                'title': '2025년 위탁펀드형 대체투자 운용사 선정 공고', 'date': '2025-04-30',
                'body': body, 'sha256': 'a'*64, 'attachment_texts': {}}

    def test_vc_typo_is_excluded_by_section_and_ranges_are_preserved(self):
        n = self.notice()
        self.assertEqual(_scope(n), 'mixed_pe_blind')
        result = extract_terms(n)
        self.assertEqual(result['commitment_amount_krw'], 440_000_000_000)
        self.assertEqual(result['manager_count'], 10)
        self.assertEqual(result['segments'][0]['per_fund_min_krw'], 50_000_000_000)
        self.assertEqual(result['segments'][1]['per_fund_max_krw'], 50_000_000_000)
        self.assertEqual(result['deadline'], '2025-05-14T14:00:00+09:00')
        self.assertNotIn('벤처기업', result['primary_investment']['text'])

    def test_week_windows_never_become_invented_calendar_days(self):
        result = extract_terms(self.notice())
        stages = result['planned_schedule']
        self.assertEqual(len(stages), 4)
        self.assertEqual(stages[1]['date'], '2025-05')
        self.assertEqual(stages[1]['end_date'], '2025-06')
        self.assertEqual(stages[1]['date_label'], '5월 4주 ~ 6월 1주')
        self.assertTrue(all(s['status']=='planned' for s in stages))

    def test_credit_missing_blind_or_missing_boundary_cannot_qualify(self):
        for body in (BODY.replace('Special Situation','Credit'), BODY.replace('블라인드형','일반형'),
                     BODY.replace('2. VC 부문 선정 개요','기타'), BODY.replace('국 내\tPE','해외\tPE')):
            self.assertIsNone(allocation(self.notice(body)))
            self.assertEqual(_scope(self.notice(body)), 'unknown')

    def test_forged_columns_or_unreconciled_manager_range_fail(self):
        for body in (BODY.replace('1,200억원','9,000억원'), BODY.replace('2개사\t1,200','x개사\t1,200')):
            with self.assertRaises(ValueError):
                allocation(self.notice(body))

    def test_identity_and_format_are_independent_of_specific_notice_id(self):
        n=self.notice()
        changed=copy.deepcopy(n); changed['url']=n['url'].replace('no=1','no=98765')
        self.assertEqual(allocation(n)['commitment_amount_krw'], allocation(changed)['commitment_amount_krw'])
        changed['institution_id']='ibk'
        self.assertIsNone(allocation(changed))


if __name__ == '__main__':
    unittest.main()
