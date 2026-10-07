"""Extraction failures must never turn into plausible public fund terms."""
import copy
import unittest
from services.lp.src.lp_notice_terms import extract_terms, project_discovered


def official(body, text="", institution="koreapost", title="2026년 국내 공동투자 전략 PEF 선정 공고"):
    host = "www.kpasset.go.kr" if institution == "koreapost" else "www.koreaexim.go.kr"
    url = f"https://{host}/notice/98765"
    attachment = f"https://{host}/official.pdf"
    return {"institution_id": institution, "source_id": "98765", "date": "2026-03-23",
            "title": title, "body": body, "url": url, "sha256": "body-digest",
            "attachment_texts": {attachment: text} if text else {},
            "attachment_hashes": {attachment: "attachment-digest"} if text else {}}


BODY = """1. 투자전략 : 우정사업본부가 제공하는 국내 공동투자건에 대하여 펀드 약정액의 100% 투자
2. 투자규모 : 총 2,000억원 이내
3. 선정 운용사 수 : 총 1개 운용사
5. 제안서 접수 마감일 : 2026. 4. 6.(월) 15시"""
PLAN = """모태펀드(보건복지부) 2026년 5월 수시 출자사업 계획 공고
출자규모·총700억원이내
출자대상 기관전용사모집합투자기구
접수마감시한·2026년6월5일(금),14:00
- 2 -
2.출자분야별출자계획 (단위:억원)
분야 출자예산 결성목표액 선정조합수 자조합별출자액 신청가능조합형태
보건바이오헬스 700 1,500 1개 700 ․ 기관전용사모집합투자기구
주2) 한국수출입은행,중소기업은행(이하“공동출자자”)이총200억원을출자할계획임.
공동출자자 출자 예정 금액 (단위:억원)
구분 한국수출입은행 중소기업은행 공동출자합계
출자금액 100 100 200
- 3 -
3.출자분야및투자대상 분야주목적투자대상
◦다음①~③중1개이상의조건을충족하는제약·바이오분야임상3상추진중인기업주1)에약정총액의60%이상투자.
- 4 -
4.주요출자조건"""


class TermsTests(unittest.TestCase):
    def test_labeled_terms_and_provenance_not_first_number_in_document(self):
        n = official("GP 의무출자 15%, 결성목표 5,000억원\n" + BODY)
        terms = extract_terms(n)
        self.assertEqual(terms["commitment_amount_krw"], 200_000_000_000)
        self.assertEqual(terms["deadline"], "2026-04-06T15:00:00+09:00")
        self.assertEqual(terms["manager_count_label"], "1개사")
        self.assertEqual(terms["extraction_evidence"]["base_amount"][0]["source_url"], n["url"])

    def test_joint_amounts_bind_to_institution_and_reconcile_total(self):
        n = official("공식 공고", PLAN, "kexim", "임상3상 특화펀드 선정계획 공고")
        terms = extract_terms(n)
        self.assertEqual(terms["commitment_amount_krw"], 10_000_000_000)
        self.assertEqual(terms["total_commitment_amount_krw"], 90_000_000_000)
        self.assertEqual(terms["fund_target_label"], "1,500억원")
        self.assertEqual(sum(terms["contribution_allocations"].values()), terms["total_commitment_amount_krw"])
        self.assertIn("60%", terms["primary_investment"]["text"])

    def test_no_id_allowlist_required_and_preferred_bidder_never_final(self):
        n = official(BODY)
        later = {**n, "source_id": "any-new-id", "url": n["url"] + "/later", "date": "2026-04-21",
                 "title": "2026년 국내 공동투자 전략 PEF 우선협상대상자 선정 안내", "body": "최종 선정 예정"}
        programs, holds = project_discovered([n, later], [n, later], "2026-10-07")
        self.assertEqual(holds, [])
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0]["status"], "우선협상대상자")
        self.assertEqual(programs[0]["selected_gps"], [])
        self.assertEqual(len(programs[0]["schedule_stages"]), 3)

    def test_missing_conflicting_and_invalid_dates_fail_closed(self):
        for body in (BODY.replace("3. 선정 운용사 수 : 총 1개 운용사", ""),
                     BODY + "\n투자규모 : 총 3,000억원",
                     BODY.replace("4. 6.", "2. 30.")):
            n = official(body)
            programs, holds = project_discovered([n], [n], "2026-10-07")
            self.assertEqual(programs, [])
            self.assertEqual(len(holds), 1)

    def test_ambiguous_tables_wrong_sum_or_unanchored_text_fail(self):
        for plan in (PLAN.replace("700 1,500 1개 700", "7001,5001개700"),
                     PLAN.replace("100 100 200", "100 150 200"),
                     PLAN.replace("1개 700", "2개 700")):
            with self.assertRaises(ValueError):
                extract_terms(official("공식 공고", plan, "kexim", "특화펀드 선정계획 공고"))
        n = official("공식 공고", PLAN, "kexim")
        n["attachment_hashes"] = {}
        with self.assertRaises(ValueError): extract_terms(n)

    def test_vc_mandate_missing_original_and_amendments_not_published(self):
        for title, body in (("2026 VC펀드 출자 공고", "출자대상 벤처투자조합\n" + BODY),
                            ("2026 해외 사모펀드 재간접 선정 공고", "해외사모펀드(PE, PD)\n" + BODY),
                            ("2026 국내 공동투자 전략 PEF 접수 결과", BODY)):
            n = official(body, title=title)
            self.assertEqual(project_discovered([n], [n], "2026-10-07")[0], [])
        n = official(BODY)
        amendment = {**n, "source_id": "amend", "url": n["url"] + "/amend", "title": "2026 국내 공동투자 전략 PEF 변경 공고"}
        self.assertEqual(project_discovered([n, amendment], [n, amendment], "2026-10-07")[0], [])

    def test_input_candidate_scope_is_not_publication_permission(self):
        n = official(BODY, title="알 수 없는 펀드 공고")
        candidate = {**n, "scope": "pe_eligible"}
        self.assertEqual(project_discovered([candidate], [n], "2026-10-07")[0], [])
        n = official(BODY); n["url"] = "https://unofficial.example/notice"
        with self.assertRaises(ValueError): extract_terms(n)


if __name__ == "__main__": unittest.main()
