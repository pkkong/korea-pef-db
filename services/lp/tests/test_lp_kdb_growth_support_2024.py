import unittest

from services.lp.src import lp_kdb_growth_support_2024 as support
from services.lp.src.lp_notice_publication import publish_basic_notices


PLAN = '''『혁신성장펀드(성장지원펀드)』
2024년 1차 위탁운용사 선정계획 공고
정책출자자 위탁운용 총액 : 총 3,000억원 내외
(단위: 억원)
정책출자자
합 계
정부재정(재정모펀드)
한국산업은행
200
2,800
3,000
* 출자자별 위탁운용금액은 조정될 수 있음
재정
산은
합계(비율)
대형
200
2,800
3,000(30%)
5,000
2
10,000
산은
접수일시 ○ 2024년 5월 2일(목) 13:00 ~ 16:00
접수방법
출자대상 투자기구 ○기관전용 사모집합투자기구 ○벤처투자조합 ※선정된 위탁운용사는'''
RESULT = '''< 혁신성장펀드 2024년 1차 위탁운용사 선정 결과 >
(단위 : 억원, 개)
지원분야
(운용사 수)
펀드규모
선정 운용사명 (가나다순)
주관기관
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
APPLICATION = ('혁신성장펀드 차 출자사업 위탁운용사 접수 결과 < 1 >\n지원분야\n'
               '성장 지원 대형 (2) 5,000 총 (10,000) 4 제이케이엘파트너스')


def source(route, title, date, raw):
    url = 'https://www.kdb.co.kr/' + route
    attachment = url + '/attachment.hwp'
    return {'url': url, 'date': date, 'title': title, 'institution_id': 'kdb',
            'source_channel': 'institution_board', 'body': '공식 첨부 참고', 'sha256': 'a' * 64,
            'attachments': [{'name': '공식 첨부.hwp', 'url': attachment}],
            'attachment_hashes': {attachment: 'b' * 64}, 'attachment_texts': {attachment: raw}}


ORIGINAL = source('offering', '『혁신성장펀드(성장지원펀드)』 2024년 1차 선정계획 공고', '2024-04-18', PLAN)
APPLICATION_NOTICE = source('application', '「혁신성장펀드」2024년 1차 위탁운용사 제안서 접수결과', '2024-05-03', APPLICATION)
FINAL = source('selection', '「혁신성장펀드」2024년 1차 위탁운용사 선정 결과', '2024-05-31', RESULT)


class KDBGrowthSupport2024Tests(unittest.TestCase):
    def test_combined_plan_and_own_contribution(self):
        plan = support.terms(ORIGINAL, [('https://www.kdb.co.kr/plan.hwp', PLAN, 'b' * 64)])
        self.assertEqual(plan['commitment_amount_krw'], 3_000 * 10**8)
        self.assertEqual(plan['contribution_allocations']['한국산업은행'], 2_800 * 10**8)
        self.assertEqual(plan['segments'][0]['fund_target_total_krw'], 10_000 * 10**8)
        self.assertEqual(plan['deadline'], '2024-05-02T16:00:00+09:00')

    def test_does_not_attach_wrong_round_or_wrong_table(self):
        def links(notices):
            return support.linked_stages(notices, lambda n: [n['body'], *n['attachment_texts'].values()])

        self.assertEqual(set(links([FINAL, ORIGINAL, APPLICATION_NOTICE])), {FINAL['url'], APPLICATION_NOTICE['url']})
        same_size_other_fund = source('selection', FINAL['title'], FINAL['date'], RESULT.replace('성장지원', '혁신산업'))
        different_lead = source('selection', FINAL['title'], FINAL['date'], RESULT.replace('\n산은\n프리미어', '\n성장금융\n프리미어'))
        self.assertEqual(links([ORIGINAL, same_size_other_fund, different_lead]), {})
        self.assertEqual(links([ORIGINAL, {**APPLICATION_NOTICE, 'date': '2024-05-01'}]), {})
        self.assertEqual(links([{**ORIGINAL, 'title': ORIGINAL['title'].replace('1차', '2차')}, FINAL]), {})

    def test_shared_stage_does_not_reuse_another_program(self):
        from unittest.mock import patch

        peer = {'id': 'already-published-innovation', 'institution_id': 'kdb',
                'title': '혁신성장펀드(혁신산업펀드) 2024년 1차 선정계획 공고',
                'events': [{'date': '2024-04-18', 'type': '모집 공고', 'url': 'https://www.kdb.co.kr/another'},
                           {'date': FINAL['date'], 'type': '선정 결과', 'url': FINAL['url']}], 'selected_gps': []}
        sources = {n['url']: n for n in (ORIGINAL, APPLICATION_NOTICE, FINAL)}
        with patch('services.lp.src.lp_notice_publication._sources', return_value=(sources, {}, [])):
            programs, holds = publish_basic_notices({'programs': [peer]}, [], '2026-11-25T03:00:00+00:00')
        self.assertEqual(holds, [])
        self.assertEqual(programs[0], peer)
        self.assertEqual(programs[1]['status'], '선정 완료')
        self.assertEqual([g['name'] for g in programs[1]['selected_gps']], ['제이케이엘파트너스', '프리미어파트너스'])


if __name__ == '__main__':
    unittest.main()
