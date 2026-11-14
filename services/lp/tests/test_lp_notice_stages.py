import unittest

from services.lp.src.lp_notice_triage import notice_stage


class NoticeStageTests(unittest.TestCase):
    def test_selection_and_quantitative_boundary_is_screening(self):
        titles = [
            "우체국예금 해외사모펀드 국내 재간접 위탁운용사 선정 정량평가 결과 안내",
            "2026년 국내 블라인드 PEF 위탁운용사 선정 정량평가 결과 안내",
            "위탁운용사 선정정량평가결과 안내",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(notice_stage(title), "1차 심사 결과")

    def test_reopening_qualifier_does_not_hide_later_stage(self):
        for wording, expected in [
            ("【접수현황】[재공고]부산 전환펀드 위탁운용사 접수 현황", "접수 결과"),
            ("[재공고] 부산 전환펀드 위탁운용사 서류심사 결과", "1차 심사 결과"),
            ("【선정결과】[재공고]부산 전환펀드 위탁운용사 선정 결과", "선정 결과"),
            ("[재공고] 부산 전환펀드 우선협상대상자 선정 안내", "우선협상대상자"),
            ("[재공고] 부산 전환펀드 질의응답", "질의응답"),
        ]:
            with self.subTest(title=wording):
                self.assertEqual(notice_stage(wording), expected)

    def test_initial_reopening_is_still_amendment(self):
        self.assertEqual(notice_stage("【선정공고】[재공고]부산 전환펀드 위탁운용사 선정계획 공고"), "변경 공고")

    def test_actual_amendments_override_result_or_reopening_qualifier(self):
        for title in [
            "[정정] 위탁운용사 선정 정량평가 결과 안내",
            "위탁운용사 선정결과 정정 공고",
            "[재공고] 위탁운용사 선정계획 취소 공고",
            "위탁운용사 선정계획 공고(수정)",
            "위탁운용사 접수기간 연장 안내",
            "위탁운용사 선정계획 변경 공고",
            "【취소공고】위탁운용사 선정계획",
            "위탁운용사 선정 취소",
        ]:
            with self.subTest(title=title):
                self.assertEqual(notice_stage(title), "변경 공고")

    def test_unknown_title_stays_unknown(self):
        self.assertEqual(notice_stage("2026년 출자사업 담당자 연락처"), "단계 확인 필요")

    def test_recruitment_titled_as_selection_or_plan_without_notice_word(self):
        self.assertEqual(notice_stage("2024년 공무원연금공단 국내 사모대체 블라인드펀드(PEF) 위탁운용사 선정"), "모집 공고")
        self.assertEqual(notice_stage("2024년도 대체투자(유럽기업 선순위 대출펀드) 위탁운용사 선정계획"), "모집 공고")
        self.assertEqual(notice_stage("2024년 국내 사모대체 블라인드펀드(PEF) 위탁운용사 선정 결과 공고"), "선정 결과")

    def test_press_release_results_on_the_board(self):
        self.assertEqual(notice_stage("군인공제회, 국내 블라인드 펀드 운용사 8곳 선정"), "선정 결과")
        self.assertEqual(notice_stage("군인공제회, 2차 국내 블라인드 펀드 운용사 선정"), "선정 결과")

    def test_guidance_about_a_round_is_not_the_round(self):
        self.assertEqual(notice_stage("[공고] 2020년 PE·VC 정기출자 제안서 접수 관련 안내사항"), "단계 확인 필요")


if __name__ == "__main__":
    unittest.main()
