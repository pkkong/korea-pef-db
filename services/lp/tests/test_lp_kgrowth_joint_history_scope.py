"""Do not assign three fund columns from two merged institution cells.

Observed joint notice 471, 2021-04-01. Attachment original SHA256:
dc1a8d583dd7b7ffe16019f3cba7087ebcf5c201ecf26cf231c78320fa36b384.
Excerpts are from pages 1, 2, 3 and 12; this is not raw publication evidence.
"""
import unittest

from services.lp.src.lp_kgrowth_history_terms import review_bundle
from services.lp.src.lp_notice_publication import _rule_valid_name
from services.lp.tests.test_lp_kgrowth_history_terms import notice, bundle

JOINT_OFFER = '''소재·부품·장비분야 투자 전용 펀드(2차) 위탁운용사 선정계획 공고
소재·부품·장비분야투자전용펀드(2차)위탁운용사선정계획을아래와같이공고합니다.
1.개요 항목 블라인드펀드 프로젝트펀드 ❶일반 ❷반도체
출자계획 ◦분야별출자계획(단위:억원)
지원분야 정책출자자 지정출자자 위탁운용금액 최소결성금액 출자비율
정부재정 산업은행
블라인드 ➊일반 1,100 200 - 1,300 2,000 65%
➋반도체 300 100 400 800 1,000 80%
프로젝트 1,000 - - 1,000 2,000 50%
합계 2,400 300 400 3,100 5,000 -
선정운용사수 ◦2개사 ◦1개사 ◦위탁운용금액소진시까지수시접수및선정
주관기관 ◦한국산업은행 ◦한국성장금융투자운용㈜
접수일시 2021년4월21일(수)16:00까지 ◦수시접수
2.블라인드펀드 ⑴제안관련사항 항목 세부내용 출자대상투자기구
❶일반 ◦「자본시장과금융투자업에관한법률」에의한경영참여형사모집합투자기구,
창업‧벤처전문경영참여형사모집합투자기구등 ◦「벤처투자촉진에관한법률」에의한벤처투자조합
❷반도체 ◦「자본시장과금융투자업에관한법률」에의한경영참여형사모집합투자기구,
창업‧벤처전문경영참여형사모집합투자기구등
운용사신청자격 ◦국내에설립된법인
⑵주요출자조건 ❷반도체한정 ◦반도체소재·부품·장비관련국내중소·중견기업에500억원이상투자
3.프로젝트펀드 ◦수시접수
4.접수처및문의방법
구분 블라인드펀드(➊일반,➋반도체) 프로젝트펀드
주관기관 한국산업은행간접투자금융실 한국성장금융투자운용본부'''


class JointHistoryOwnershipTests(unittest.TestCase):
    def test_hosted_joint_document_does_not_make_semiconductor_kgrowth_pe(self):
        n = notice('471', '【선정공고】 「소재·부품·장비 분야 투자 전용 펀드(2차)」 위탁운용사 선정계획 공고',
                   '2021-04-01', '블라인드펀드 제출서류는 한국산업은행 홈페이지 참고. 프로젝트펀드 문의는 한국성장금융.',
                   JOINT_OFFER)
        report = review_bundle(bundle(n), valid_name=_rule_valid_name)
        self.assertEqual(report['metadata_check']['errors'], [])
        self.assertEqual(report['summary']['parsed_pe_offerings'], 0)
        self.assertFalse(report['publication_ready'])
        self.assertTrue(report['groups'][0]['holds'])
        self.assertIsNone(report['groups'][0]['offering'])
        self.assertEqual(report['groups'][0]['rosters'], [])


if __name__ == '__main__':
    unittest.main()
