"""Joint-bank originals are discovered by board search, not manual IDs."""
import json
import unittest
from unittest.mock import patch
from services.lp.src import collect_kdb_related as kdb
from services.lp.src.lp_notice_triage import assess_candidates


def source():
    return {"institution_id": "kexim", "source_id": "result-any-id", "date": "2026-10-01",
            "title": "정책금융기관 글로벌 스케일업 협력펀드 출자사업 운용사 제안서 접수 결과",
            "body": "접수 결과 공고", "url": "https://www.koreaexim.go.kr/result"}


def row(identity, title, date):
    return {"ITR_NAC_ID_MNG_SNO": identity, "NAC_CONE_TTL": title, "NAC_SMRY_CONE": "첨부파일 참고",
            "FST_ENR_DTM": date + "160000", "LST_CHG_DTM": "20260918160000"}


class RelatedTests(unittest.TestCase):
    def test_search_discovers_original_faq_and_misspelled_result_preserving_initial_date(self):
        rows = [row("random-original", "『정책금융기관 글로벌 스케일업 협력펀드』 위탁운용사 선정계획 공고", "20260907"),
                row("random-faq", "『정책금융기관 글로벌 스케일업 협력펀드』 위탁운용사 선정 FAQ 게시", "20260918"),
                row("random-result", "『정책금융기관 글로벌 스케일업 협력편드』 위탁운용사 제안서 접수결과", "20261001"),
                row("different", "『다른 스케일업 펀드』 공고", "20260907")]
        calls = []
        def fetch(url, payload=None):
            calls.append((url, payload))
            if payload:
                return json.dumps({"STDLIST_REC": rows, "HEADER_STD_WEB": {"TOT_PAG_CNT": 1}}).encode()
            if "/fileView?" in url: return b"%PDFofficial-bytes"
            return b'<a href="/fileView?groupId=dynamic&amp;fileId=dynamic">official.pdf</a>'
        original = source()
        text = "출자대상투자기구○벤처투자조합○신기술사업투자조합○기관전용사모집합투자기구※선정조건"
        with patch.object(kdb, "_pdf_text", return_value=text):
            notices, holds = kdb.collect_related([original], [original], "2026-10-07", fetch)
        self.assertEqual(holds, [])
        self.assertEqual(len(notices), 3)
        self.assertEqual(notices[0]["date"], "2026-09-07")
        self.assertEqual(notices[0]["modified_at"], "20260918160000")
        self.assertEqual(calls[0][1]["SEARCH_CONDITION"], "NAC_CONE_TTL")
        self.assertEqual(calls[0][1]["SEARCH_KEYWORD"], "스케일업")
        self.assertNotIn("random-original", json.dumps(calls[0][1]))
        assessed = assess_candidates([original], [original] + notices)[0]
        self.assertEqual(assessed["scope"], "mixed_legal_forms")
        self.assertEqual(assessed["recruitment_url"], notices[0]["url"])

    def test_official_source_failure_keeps_primary_notice_and_returns_hold(self):
        original = source()
        def fetch(url, payload=None): raise TimeoutError("official site unavailable")
        notices, holds = kdb.collect_related([original], [original], "2026-10-07", fetch)
        self.assertEqual(notices, [])
        self.assertEqual(len(holds), 1)
        self.assertEqual(assess_candidates([original], [original])[0]["scope"], "unknown")

    def test_external_or_unrelated_supporting_source_cannot_supply_eligibility(self):
        original = source()
        base = {"institution_id": "kdb", "date": "2026-09-07", "source_id": "unrelated", "title": "『다른펀드』 공고",
                "body": "출자대상투자기구벤처투자조합기관전용사모집합투자기구※조건",
                "url": "https://www.kdb.co.kr/unrelated", "related_program_key": assess_candidates([original], [original])[0]["program_key"]}
        for supporting in (base, {**base, "title": "『정책금융기관 글로벌 스케일업 협력펀드』 공고", "url": "https://unofficial.example/notice"}):
            self.assertEqual(assess_candidates([original], [original, supporting])[0]["scope"], "unknown")


if __name__ == "__main__": unittest.main()
