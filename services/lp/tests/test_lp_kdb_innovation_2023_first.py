"""Only the medium track belongs to this historical KDB offering."""

from datetime import date
import unittest

from services.lp.src import lp_kdb_innovation_2023_first as innovation


class InnovationFirstMediumTests(unittest.TestCase):
    def test_medium_plan_uses_joint_sources_and_excludes_neighboring_tracks(self):
        recruitment = (
            '출자계획 (기업투자 블라인드펀드)\n혁신산업일반\n중형\n200\n400\n30.0%\n1,000\n2\n2,000\n산은\n소형\n'
            '접수일시 ○ 2023년 5월 17일(수) 10:00 ~ 15:00\n'
            '기관전용사모집합투자기구* * 경영참여 목적에 한함\n창업·벤처전문사모집합투자기구\n벤처투자조합\n'
            '혁신산업 일반 (소형/중형 공통) ○ ① ~ ③을 모두 충족\n'
            '① 혁신성장 공동기준 품목(별첨) 해당 기업에 약정총액의 [60%] 이상 투자\n'
            '② ‘新성장 4.0’ 또는 ‘글로벌 초격차산업 및 미래유망산업’ 분야(별첨)에 [정책출자금액] 이상 투자\n'
            '③ 중소ㆍ중견기업에 약정총액의 [60%] 이상 투자'
        )
        press = '혁신산업 일반 중형 산은 200 400 600 30.0 2 1,000 2,000 소형 성장'
        self.assertEqual(innovation._terms(recruitment, press),
                         (200, 400, 1000, 2, 2000, date(2023, 5, 17), '15:00', ('60', '60')))
        for bad_recruitment, bad_press in (
            (recruitment.replace('경영참여 목적에 한함', '일반지분투자'), press),
            (recruitment.replace('중형\n200', '대형\n200'), press),
            (recruitment.replace('30.0%', '31.0%'), press.replace('30.0', '31.0')),
            (recruitment, press.replace('200 400', '300 300')),
        ):
            with self.subTest(recruitment=bad_recruitment[:64], press=bad_press), self.assertRaises(ValueError):
                innovation._terms(bad_recruitment, bad_press)

    def test_selection_stays_in_its_league_and_must_agree_with_both_sources(self):
        header = '혁신산업 일반/소형 (1)\n300\n(총 300)\n소형벤처스\n혁신산업 일반/중형 (2)\n1,000\n(총 2,000)\n'
        neighbor = '\n성장지원 일반/대형 (1)\n9,000\n(총 9,000)\n대형파트너스'
        texts = {
            '접수 결과': header + '4\n산업파트너스\n은행운용\n구름캐피탈\n미래운용/함께운용',
            '1차 심사 결과': header + '산업파트너스\n은행운용\n구름캐피탈',
            '선정 결과': header + '산업파트너스\n산은\n은행운용' + neighbor,
        }
        bank = {'접수 보도자료': texts['접수 결과'] + neighbor, '서류심사 보도자료': texts['1차 심사 결과'] + neighbor}
        applied, screened, selected = innovation._medium_rosters(texts, bank, 2, 1000, 2000)
        self.assertEqual(applied[-1], ('미래운용', '함께운용'))
        self.assertEqual(len(screened), 3)
        self.assertEqual(selected, [('산업파트너스',), ('은행운용',)])
        for final in (texts['선정 결과'].replace('은행운용', '대형파트너스'),
                      texts['선정 결과'].replace('산은', '성장금융')):
            with self.subTest(final=final), self.assertRaises(ValueError):
                innovation._medium_rosters({**texts, '선정 결과': final}, bank, 2, 1000, 2000)
        with self.assertRaises(ValueError):
            innovation._medium_rosters(texts, {**bank, '서류심사 보도자료': bank['서류심사 보도자료'].replace('구름캐피탈', '다른운용')},
                                       2, 1000, 2000)
