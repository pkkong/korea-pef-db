import unittest

from services.lp.src import lp_kdb_semiconductor_terms as semi


TITLE = '「반도체 생태계펀드」 2차년도 '
BOARD = {'institution_id': 'kdb', 'source_channel': 'institution_board', 'date': '2024-04-26',
         'url': 'https://www.kdb.co.kr/board', 'body': '첨부파일 참고'}
ORIGINAL = {**BOARD, 'title': TITLE + '위탁운용사 선정계획 공고'}
PLAN = '''「반도체생태계펀드(2차)」위탁운용사선정계획공고(안)
1. 선정 개요 항목 블라인드 펀드 프로젝트 펀드 주관기관 ○한국산업은행,한국성장금융 ○한국성장금융
제안방식 ○모펀드 제안방식 ○운용사 제안방식 위탁운용금액 및 선정운용사수
○총 650억원 ○총 300억원*(소부장 300)(단위: 억원)선정운용사수 운용사별 출자금액 펀드별 최소결성금액
2개150300 ○총 350억원*(소부장 150,팹리스 200)(단위: 억원)선정운용사수 운용사별 출자금액 펀드별 최소결성금액
제안금액, 출자비율 등을 감안하여 개별 협의*산업은행 125억원, IBK혁신성장펀드1호 100억원, 반도체 생태계 모펀드 75억원
*1차년도 공고 이월 별도 모펀드 출자비율 ○펀드별 약정총액의 50% 이내
출자대상 투자기구 ○기관전용 사모집합투자기구 ○벤처투자조합 ※본 계획에 따라 선정된 위탁운용사는
접수일시 2024년 5월 17일(금)10:00~16:00 수시 접수
주목적 투자대상 ○투자대상은 국내 중소·중견기업
블라인드펀드 소부장 ○반도체 분야의 특별조치법상 소재·부품·장비 산업을 영위하는 기업에 약정총액의 [60%] 이상 투자
접수처 및 문의방법 항목 블라인드펀드(산업은행,성장금융 공동주관) 프로젝트펀드(성장금융 주관)
접수일시 2024년 5월 17일(금)10:00~16:00 수시 접수'''
FINAL = {**BOARD, 'date': '2024-06-28', 'title': TITLE + '(블라인드펀드) 위탁운용사 선정 결과'}
ROSTER = '''< 반도체 생태계펀드(2차년도) 블라인드펀드 위탁운용사 선정 결과 >
    (단위 : 억원, 개)
지원분야
(운용사 수)
펀드규모
선정 운용사명 (가나다순)
주관기관
반도체 소부장
(2)
300
(총 600)
비전에쿼티파트너스
산업은행/성장금융
(공동주관)
펜타스톤인베스트먼트'''


def terms(text=PLAN):
    return semi.terms(ORIGINAL, [('https://www.kdb.co.kr/plan.pdf', text, 'c' * 64)])


class KBDSemiconductorTermsTests(unittest.TestCase):
    def test_blind_track_amount_deadline_and_mandate(self):
        result = terms()
        self.assertEqual((result['amount_scope'], result['commitment_amount_krw']), ('combined', 300 * 10**8))
        self.assertEqual(result['contribution_allocations']['한국산업은행'], 125 * 10**8)
        self.assertEqual(result['segments'][0]['per_fund_amount_krw'], 150 * 10**8)
        self.assertEqual(result['segments'][0]['fund_target_total_krw'], 600 * 10**8)
        self.assertEqual(result['deadline'], '2024-05-17T16:00:00+09:00')
        self.assertIn('약정총액의 60%', result['primary_investment']['items'][0])

    def test_rejects_inconsistent_sources_and_clears_conflicting_deadline(self):
        for changed in (PLAN.replace('650억원', '651억원'), PLAN.replace('125억원', '126억원'),
                        PLAN.replace('벤처투자조합', '과거 실적'), PLAN.replace('2개150300', '2개155300')):
            with self.assertRaises(ValueError):
                terms(changed)
        result = terms(PLAN.replace('16:00', '15:00', 1))
        self.assertNotIn('deadline', result)
        self.assertIn('deadline_error', result)

    def test_attachment_requires_blind_round_evidence(self):
        application = {**BOARD, 'date': '2024-05-20', 'title': TITLE + '위탁운용사 접수 현황',
                       'body': TITLE + '(블라인드 펀드) 위탁운용사 접수 현황을 공지합니다.'}
        self.assertEqual(semi.identity(application), semi.identity(ORIGINAL))
        self.assertEqual(semi.identity(FINAL), semi.identity(ORIGINAL))
        self.assertIsNone(semi.identity({**application, 'body': application['body'].replace('블라인드', '프로젝트')}))
        self.assertIsNone(semi.identity({**FINAL, 'title': FINAL['title'].replace('2차년도', '3차년도')}))
        self.assertNotEqual(semi.identity({**FINAL, 'date': '2025-06-28'}), semi.identity(ORIGINAL))

    def test_selection_table_verifies_count_and_size(self):
        program = {**terms(), 'asset_scope': 'PE·VC 공동 모집'}
        self.assertEqual(semi.result_roster(FINAL, ROSTER, program),
                         [('반도체 소부장', ['비전에쿼티파트너스', '펜타스톤인베스트먼트'])])
        for changed in (ROSTER.replace('펜타스톤인베스트먼트', '비전에쿼티파트너스'),
                        ROSTER.replace('총 600', '총 700'), ROSTER.replace('공동주관', '단독주관')):
            self.assertEqual(semi.result_roster(FINAL, changed, program), [])


if __name__ == '__main__':
    unittest.main()
