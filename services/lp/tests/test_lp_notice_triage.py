import unittest

from services.lp.src.lp_notice_triage import assess_candidates


def notice(institution, source_id, title, date, body="", attachment_text=""):
    url = f"https://official.example/{source_id}"
    return {"institution_id": institution, "source_id": source_id, "title": title,
            "date": date, "body": body, "url": url,
            "attachment_texts": {"https://official.example/file": attachment_text}}


class NoticeTriageTests(unittest.TestCase):
    def test_post_recruitment_groups_later_stages_without_promoting_preferred_bidder(self):
        rows = [
            notice("koreapost", "0041:347", "2026년도 우체국예금 국내 공동투자 전략 펀드 위탁운용사 선정 공고",
                   "2026-03-23", attachment_text="투자기구 및 선정대상 기관전용 사모집합투자기구 및 투자신탁"),
            notice("koreapost", "0041:349", "2026년도 우체국예금 국내 공동투자 전략 펀드 1차 정량평가 결과 안내",
                   "2026-04-13"),
            notice("koreapost", "0041:351", "우체국예금 국내 공동투자전략 펀드 우선협상대상자 선정 안내",
                   "2026-04-21", body="운용사 실사 및 투자심의회를 거쳐 최종 선정 예정"),
            notice("koreapost", "0041:348", "우체국예금 해외 사모펀드 국내 재간접 위탁운용사 선정 공고",
                   "2026-03-30", body="해외 사모펀드(PE, PD) 운용을 위한 국내 재간접 위탁운용사"),
            notice("koreapost", "0041:350", "우체국예금 해외사모펀드 국내 재간접 정량평가 결과 안내",
                   "2026-04-15"),
            notice("koreapost", "0041:352", "우체국예금 해외사모펀드 국내재간접 우선협상대상자 알림",
                   "2026-04-22"),
        ]
        results = assess_candidates(rows, rows)
        by_id = {row["source_id"]: row for row in results}
        self.assertEqual({by_id[n]["program_key"] for n in ("0041:347", "0041:349", "0041:351")},
                         {"koreapost:2026:domestic-coinvestment"})
        self.assertEqual({by_id[n]["program_key"] for n in ("0041:348", "0041:350", "0041:352")},
                         {"koreapost:2026:overseas-private-feeder"})
        self.assertEqual(by_id["0041:351"]["stage"], "우선협상대상자")
        self.assertEqual(by_id["0041:351"]["scope"], "pe_eligible")
        self.assertEqual(by_id["0041:350"]["scope"], "pe_related_mandate")
        self.assertEqual(by_id["0041:349"]["recruitment_url"], rows[0]["url"])

    def test_legal_fund_form_outweighs_unrelated_appendix_terms(self):
        pe = notice("kexim", "pe", "임상3상 특화펀드 위탁운용사 선정계획 공고", "2026-05-11",
                    attachment_text="출자대상 기관전용사모집합투자기구. 운용인력은 벤처투자조합 경력도 검토")
        vc = notice("kexim", "vc", "LP성장펀드(Track 1) 출자사업 계획 공고", "2026-08-13",
                    attachment_text="출자 대상 벤처투자조합. 운용사 선정방법 별도")
        later = notice("kexim", "followup", "정책금융기관 글로벌 스케일업 협력펀드 제안서 접수 결과",
                       "2026-10-01", body="접수 결과를 첨부파일과 같이 공고")
        results = {row["source_id"]: row for row in assess_candidates([pe, vc, later], [pe, vc, later])}
        self.assertEqual(results["pe"]["scope"], "pe_eligible")
        self.assertEqual(results["vc"]["scope"], "vc_only")
        self.assertEqual(results["followup"]["scope"], "unknown")
        self.assertIsNone(results["followup"]["recruitment_url"])
        self.assertEqual(results["followup"]["stage"], "접수 결과")

    def test_candidate_without_retained_official_notice_fails_closed(self):
        with self.assertRaises(ValueError):
            assess_candidates([notice("kexim", "missing", "공고", "2026-10-01")], [])


if __name__ == "__main__":
    unittest.main()
