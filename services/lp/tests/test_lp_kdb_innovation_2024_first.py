import unittest
from unittest.mock import patch

from services.lp.src.lp_kdb_innovation_2024_first import linked_stages
from services.lp.src.lp_kdb_innovation_terms import terms
from services.lp.src.lp_notice_publication import _texts, publish_basic_notices
from services.lp.tests.test_lp_kdb_growth_support_2024 import (
    APPLICATION_NOTICE, FINAL as GROWTH_FINAL, ORIGINAL as GROWTH, source,
)


PLAN = '''『혁신성장펀드(혁신산업펀드)』
2024년 1차 위탁운용사 선정계획 공고
정책출자자 위탁운용 총액 : 총 4,160억원 내외
(단위: 억원)
정책출자자
합계
정부재정(재정모펀드)
한국산업은행
성장사다리펀드2
1,770
2,090
300
4,160
* 출자자별 위탁운용금액은 조정될 수 있음
재정
산은
사다리2주2)
합계(비율)
소형주1)
510
240
300
1,050(35%)
1,000
3
3,000
신한
중형주1)
560
750
-
1,310(33%)
2,000
2
4,000
산은
대형
700
1,100
-
1,800(30%)
3,000
2
6,000
합계
1,770
2,090
300
4,160(32%)
-
7
13,000
접수일시 ○ 2024년 5월 2일(목) 13:00 ~ 16:00 (분야별 주관기관 앞 제출)
접수방법 ○ 지원분야별 주관기관 접수
출자대상 투자기구 ○기관전용 사모집합투자기구 ○벤처투자조합 ※선정된 위탁운용사는'''
ORIGINAL = source('innovation', '『혁신성장펀드(혁신산업펀드)』 2024년 1차 선정계획 공고', '2024-04-18', PLAN)

RESULT = '''< 혁신성장펀드 2024년 1차 위탁운용사 선정 결과 >
(단위 : 억원, 개)
지원분야
(운용사 수)
펀드규모
선정 운용사명 (가나다순)
주관기관
혁신산업/소형 (3)
1,000
(총 3,000)
더블유더블유지자산운용
신한
시냅틱인베스트먼트
파라투스인베스트먼트
혁신산업/중형 (2)
2,000
(총 4,000)
코스톤아시아
산은
한국투자파트너스
혁신산업/대형 (2)
3,000
(총 6,000)
아이엠엠인베스트먼트
산은
큐캐피탈파트너스
성장지원/대형 (2)
5,000
(총 10,000)
제이케이엘파트너스
산은
프리미어파트너스'''
FINAL = source('selection', GROWTH_FINAL['title'], GROWTH_FINAL['date'], RESULT)
APPLICATION = source('application', APPLICATION_NOTICE['title'], APPLICATION_NOTICE['date'],
                     '혁신성장펀드 차 출자사업 위탁운용사 접수 결과 < 1 >\n지원분야\n'
                     '혁신산업 소형(3) 1,000 총(3,000) 7 더블유더블유지자산운용\n'
                     '중형(2) 2,000 총(4,000) 4 코스톤아시아\n'
                     '대형(2) 3,000 총(6,000) 4 큐캐피탈파트너스\n'
                     '성장지원 대형(2) 5,000 총(10,000) 4 제이케이엘파트너스')


class KDBInnovation2024FirstTests(unittest.TestCase):
    def test_three_policy_leagues_keep_their_own_leads(self):
        def parse(raw):
            return terms(ORIGINAL, [('https://www.kdb.co.kr/plan.hwp', raw, 'b' * 64)])

        plan = parse(PLAN)
        self.assertEqual(plan['commitment_amount_krw'], 4_160 * 10**8)
        self.assertEqual(plan['contribution_allocations']['한국산업은행'], 2_090 * 10**8)
        self.assertEqual(plan['fund_target_label'], '13,000억원')
        self.assertEqual(plan['deadline'], '2024-05-02T16:00:00+09:00')
        self.assertIn('소형은 신한자산운용, 중형·대형은 한국산업은행', plan['contribution_note'])
        with self.assertRaises(ValueError):
            parse(PLAN.replace('\n신한\n', '\n산은\n'))
        wrong_lead = source('selection', FINAL['title'], FINAL['date'], RESULT.replace('\n신한\n', '\n산은\n'))
        self.assertEqual(linked_stages([ORIGINAL, wrong_lead], _texts), {})

    def test_shared_outcomes_preserve_both_program_ids_and_separate_rosters(self):
        notices = {n['url']: n for n in (ORIGINAL, GROWTH, APPLICATION, FINAL)}
        with patch('services.lp.src.lp_notice_publication._sources', return_value=(notices, {}, [])):
            programs, holds = publish_basic_notices({'programs': []}, [], '2026-11-25T07:50:00+00:00')
            replayed, replay_holds = publish_basic_notices({'programs': programs}, [], '2026-11-25T07:50:00+00:00')
        self.assertEqual(holds, replay_holds)
        self.assertEqual(holds, [])
        self.assertEqual(replayed, programs)
        self.assertEqual(len(programs), 2)
        self.assertEqual(len({p['id'] for p in programs}), 2)
        names = {p['events'][0]['url']: [g['name'] for g in p['selected_gps']] for p in programs}
        self.assertEqual(names[ORIGINAL['url']], [
            '더블유더블유지자산운용', '시냅틱인베스트먼트', '파라투스인베스트먼트',
            '코스톤아시아', '한국투자파트너스', '아이엠엠인베스트먼트', '큐캐피탈파트너스',
        ])
        self.assertEqual(names[GROWTH['url']], ['제이케이엘파트너스', '프리미어파트너스'])
        for program in programs:
            self.assertIn(FINAL['url'], {e['url'] for e in program['events']})
            self.assertIn(APPLICATION['url'], {e['url'] for e in program['events']})


if __name__ == '__main__':
    unittest.main()
