import unittest

from services.lp.src.lp_notice_publication import _rule_valid_name, split_glued_names
from services.lp.src.lp_result_rosters import pe_result_roster


def roster(text, pe_only=False, known=frozenset()):
    return pe_result_roster(text, known=known, valid=_rule_valid_name, split_glued=split_glued_names, pe_only_program=pe_only)


class ResultRosterTests(unittest.TestCase):
    def test_league_lists(self):
        text = ('선정 결과를 아래와 같이 공고합니다. <대형리그> 1. 아이엠엠프라이빗에쿼티 2. 엠비케이파트너스 '
                '<중형리그> 1. 프랙시스캐피탈파트너스 2. 프리미어파트너스 * 가나다순 공무원연금공단에서 제작한 본 저작물은')
        self.assertEqual(roster(text, pe_only=True), [('대형리그', ['아이엠엠프라이빗에쿼티', '엠비케이파트너스']),
                                                      ('중형리그', ['프랙시스캐피탈파트너스', '프리미어파트너스'])])

    def test_press_release_takes_only_the_pe_part_and_checks_the_count(self):
        text = ('PE분야는 △IMM인베스트먼트, △JKL파트너스, △제이앤프라이빗에쿼티(루키) 등 3곳이다. '
                'VC분야는 △DSC인베스트먼트, △메디치인베스트먼트 등 9개사다.')
        self.assertEqual(roster(text), [('PE', ['IMM인베스트먼트', 'JKL파트너스', '제이앤프라이빗에쿼티'])])
        self.assertIsNone(roster(text.replace('등 3곳', '등 4곳')))

    def test_numbered_sections_and_unknown_suffixless_names(self):
        text = ('2. 선정기관 1) PEF 4개사 : 스톤브릿지캐피탈 / IMM인베스트먼트 / 아주IB투자 / 스틱인베스트먼트 '
                '2) VC 2개사 : 한국투자파트너스 / 인터베스트 3. 관련문의')
        self.assertEqual(roster(text)[0][1], ['스톤브릿지캐피탈', 'IMM인베스트먼트', '아주IB투자', '스틱인베스트먼트'])
        kcgi = '1) 글로벌채권 : 하나자산운용 2) PEF : 케이씨지아이 / 원익투자파트너스 3) VC : 인터베스트 3. 관련문의'
        self.assertIsNone(roster(kcgi))  # 케이씨지아이 has no GP suffix and is not known
        self.assertEqual(roster(kcgi, known={'케이씨지아이'})[0][1], ['케이씨지아이', '원익투자파트너스'])

    def test_one_line_and_glued_table(self):
        self.assertEqual(roster('□ 선정 운용사 : (주)제이케이엘파트너스', pe_only=True), [('PE', ['제이케이엘파트너스'])])
        glued = ('선정결과 지원분야운용사명(가나다 순) 일 반 브이아이지파트너스오퍼스프라이빗에퀴티유진자산운용큐리어스파트너스 '
                 '루 키 그래비티프라이빗에쿼티그루투자파트너스')
        self.assertEqual(roster(glued, pe_only=True),
                         [('일반', ['브이아이지파트너스', '오퍼스프라이빗에퀴티', '유진자산운용', '큐리어스파트너스']),
                          ('루키', ['그래비티프라이빗에쿼티', '그루투자파트너스'])])

    def test_mixed_result_without_a_pe_part_gives_nothing(self):
        self.assertIsNone(roster('<일반리그> 1. 한국투자파트너스 2. 벤처캐피탈 VC 리그'))


if __name__ == '__main__':
    unittest.main()
