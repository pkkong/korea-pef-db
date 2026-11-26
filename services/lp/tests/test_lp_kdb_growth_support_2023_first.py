"""Guard the confirmed 2023 Growth Support large-track source boundaries."""

from datetime import date
import unittest

from services.lp.src import lp_kdb_growth_support_2023_first as growth


class GrowthSupportLargeTests(unittest.TestCase):
    def test_plan_requires_matching_table_and_visual_scope(self):
        text = ('성장지원일반대형 100 500 30.0% 1,000 2 2,000 산은\n'
                '기관전용사모집합투자기구 벤처투자조합')
        pages = [
            {'text': ('출자계획 (기업투자 블라인드펀드)\n정책출자자 위탁운용금액 : 총 600억원 내외\n'
                      '100 500 30.0% 1,000 2 2,000 산은\n접수일시 ○ 2023년 5월 17일(수) 10:00 ~ 15:30')},
            {'text': '기관전용사모집합투자기구* 경영참여 목적에 한함 벤처투자조합 공동운용(Co-GP) 제안은 허용하지 않음'},
            {'text': ('창업 후 4년 이상 경과한 중소·중견기업에 약정총액의 [65%] 이상 투자\n'
                      '투자비율 ② 투자 전 기업가치(Pre-Money Value) 400억원 이상 중소·중견기업에 '
                      '약정총액의 [50%] 이상 투자')},
        ]
        bank = '성장지원 일반 대형 산은 100 500 600 30.0 2 1,000 2,000'
        self.assertEqual(growth._terms(text, pages, bank),
                         (100, 500, 1000, 2, 2000, date(2023, 5, 17), '15:30', (4, 65, 400, 50)))
        for revised in (
            [dict(text=pages[0]['text'].replace('17일(수)', '17일(목)')), *pages[1:]],
            [pages[0], dict(text=pages[1]['text'].replace('경영참여', '시장매매')), pages[2]],
            [*pages[:2], dict(text=pages[2]['text'].replace('[50%]', '[150%]'))],
        ):
            with self.assertRaises(ValueError):
                growth._terms(text, revised, bank)
        with self.assertRaises(ValueError):
            growth._terms(text, pages, bank.replace('100 500', '200 400'))

    def test_official_roster_does_not_accept_another_league_or_a_joint_team(self):
        heading = '성장지원 일반 대형 /\n(2)\n1,000\n총 ( 2,000)\n'
        bank_heading = '성장지원 일반/대형 (2)\n1,000\n(총 2,000)\n'
        texts = {'applications': heading + '2\n어펄마캐피탈\n가람투자',
                 'screening': heading + '어펄마캐피탈매니져스코리아\n가람투자',
                 'selection': heading + '어펄마캐피탈매니져스코리아\n산은\n가람투자'}
        bank = {'접수 보도자료': bank_heading + '2\n어펄마캐피탈\n가람투자',
                '서류심사 보도자료': bank_heading + '어펄마캐피탈매니져스코리아\n가람투자'}
        self.assertEqual(growth._rosters(texts, bank, 2, 1000, 2000), ['어펄마캐피탈매니져스코리아', '가람투자'])
        for final in (texts['selection'].replace('산은', '성장금융'),
                      texts['selection'].replace('가람투자', '가람투자/나래파트너스'),
                      texts['selection'].replace('가람투자', '다른투자')):
            with self.assertRaises(ValueError):
                growth._rosters({**texts, 'selection': final}, bank, 2, 1000, 2000)
