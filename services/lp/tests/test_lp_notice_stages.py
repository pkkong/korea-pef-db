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


if __name__ == "__main__":
    unittest.main()
