import unittest
from unittest.mock import patch

from services.lp.src import lp_kdb_innovation_2024_second as innovation
from services.lp.src.lp_notice_publication import _texts, publish_basic_notices


PLAN = '''『혁신성장펀드 (혁신산업펀드)』
2024년 2차 위탁운용사 선정계획 공고
정책출자자 위탁운용 총액 : 총 740억원 내외
(단위: 억원)
정책출자자
합 계
정부재정(재정모펀드)
한국산업은행
성장사다리펀드2
230
310
200
740
* 출자자별 위탁운용금액은 조정될 수 있음
재정
산은
사다리2주2)
합계(비율)
소형주1)
230
310
200
740(37%)
1,000
2
2,000
산은
접수일시 ○ 2024년 6월 12일(수) 13:00 ~ 16:00
접수방법
출자대상 투자기구 ○기관전용 사모집합투자기구 ○벤처투자조합 ※선정된 위탁운용사는'''
RESULT = '''혁신성장펀드 년 차 위탁운용사 선정 결과 < 2024 2 >
단위 억원 개( : , )
지원분야
운용사 수( ) 펀드규모 선정 운용사명 가나다순( ) 주관기관
혁신산업 소형 / (2) 1,000
총 ( 2,000)
엘비프라이빗에쿼티
산은
유안타인베스트먼트
성장지원 중형 / (2) 2,500
총 ( 5,000)
프랙시스캐피탈파트너스
성장금융
한국투자프라이빗에쿼티'''
APPLICATION = '''< 혁신성장펀드 2차 출자사업 위탁운용사 접수 결과 >
혁신산업 소형 (2)1,000(총 2,000)3 엘비프라이빗에쿼티유안타인베스트먼트화인자산운용
성장지원 중형 (2)2,500(총 5,000)6'''
GROWTH_PLAN = '''재정
산은
합계(비율)
중형
800
800
1,600(32%)
2,500
2
5,000
성장금융
출자대상 투자기구 ○기관전용 사모집합투자기구 ○벤처투자조합 ※선정된 위탁운용사는'''


def source(route, title, date, raw):
    url = 'https://www.kdb.co.kr/' + route
    attachment = url + '/attachment.hwp'
    return {'url': url, 'date': date, 'title': title, 'institution_id': 'kdb',
            'source_channel': 'institution_board', 'body': '공식 첨부 참고', 'sha256': 'a' * 64,
            'attachments': [{'name': '공식 첨부.hwp', 'url': attachment}],
            'attachment_hashes': {attachment: 'b' * 64}, 'attachment_texts': {attachment: raw}}


ORIGINAL = source('offering', '『혁신성장펀드(혁신산업펀드)』 2024년 2차 선정계획 공고', '2024-05-30', PLAN)
GROWTH = source('growth', '『혁신성장펀드(성장지원펀드)』 2024년 2차 선정계획 공고', '2024-05-30', GROWTH_PLAN)
APPLICATION_NOTICE = source('applied', '「혁신성장펀드」2024년 2차 위탁운용사 제안서 접수결과', '2024-06-13', APPLICATION)
FINAL = source('selection', '「혁신성장펀드」2024년 2차 위탁운용사 선정 결과', '2024-06-28', RESULT)


class KDBInnovation2024SecondTests(unittest.TestCase):
    def test_plan_requires_matching_funder_rows_and_bank_lead(self):
        def parse(raw):
            return innovation.terms(ORIGINAL, [('https://www.kdb.co.kr/plan.hwp', raw, 'b' * 64)])

        terms = parse(PLAN)
        self.assertEqual(terms['commitment_amount_krw'], 740 * 10**8)
        self.assertEqual(terms['contribution_allocations']['한국산업은행'], 310 * 10**8)
        self.assertEqual(terms['fund_target_label'], '2,000억원')
        self.assertEqual(terms['deadline'], '2024-06-12T16:00:00+09:00')
        for invalid in (PLAN.replace('740(37%)', '740(38%)'), PLAN.replace('\n산은\n접수일시', '\n성장금융\n접수일시')):
            with self.assertRaises(ValueError):
                parse(invalid)

    def test_shared_dates_tables_and_lead_must_match(self):
        def links(notices):
            return innovation.linked_stages(notices, _texts)

        self.assertEqual(set(links([FINAL, GROWTH, ORIGINAL, APPLICATION_NOTICE])), {FINAL['url'], APPLICATION_NOTICE['url']})
        self.assertEqual(links([ORIGINAL, {**FINAL, 'date': '2024-06-11'}]), {})
        wrong = source('wrong', FINAL['title'], FINAL['date'], RESULT.replace('\n산은\n', '\n성장금융\n'))
        self.assertEqual(links([ORIGINAL, wrong]), {})
        reopened = {**ORIGINAL, 'title': ORIGINAL['title'].replace('계획 공고', '계획 (재)공고')}
        self.assertEqual(links([reopened, FINAL]), {})

    def test_keeps_peer_and_growth_finance_out_of_the_bank_program(self):
        peer = {
            'id': 'retained-reopening', 'institution_id': 'kdb',
            'title': '혁신성장펀드(혁신산업펀드) 2024년 2차 재공고',
            'events': [{'date': FINAL['date'], 'type': '선정 결과', 'url': FINAL['url']}], 'selected_gps': [],
        }
        docs = {n['url']: n for n in (ORIGINAL, GROWTH, APPLICATION_NOTICE, FINAL)}
        skips = []
        with patch('services.lp.src.lp_notice_publication._sources', return_value=(docs, {}, [])):
            programs, holds = publish_basic_notices({'programs': [peer]}, [], '2026-11-25T04:55:00+00:00', skips)
        self.assertEqual(holds, [])
        self.assertEqual(programs[0], peer)
        self.assertEqual(len(programs), 2)
        self.assertEqual([skip['reason'] for skip in skips], ['different_policy_lead'])
        added = programs[1]
        self.assertEqual(added['status'], '선정 완료')
        self.assertEqual([gp['name'] for gp in added['selected_gps']], ['엘비프라이빗에쿼티', '유안타인베스트먼트'])


if __name__ == '__main__':
    unittest.main()
