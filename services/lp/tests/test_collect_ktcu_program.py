import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import collect_ktcu_program as ktcu


class KtcuProgramCollectionTest(unittest.TestCase):
    def setUp(self):
        self.seed = next(p for p in json.loads((ktcu.ROOT / "data/lp_programs_pilot.json").read_text())["programs"]
                         if p["id"] == ktcu.PROGRAM_ID)
        self.notice = {"source_id": "61742", "url": "https://www.ktcu.or.kr/PPW-CSB-000101/61742",
                       "title": "2026년 블라인드 PEF 모집", "date": "2026-09-04",
                       "body": "출자규모 3,000억원, 선정 9개사, 접수 9월 11일 15시",
                       "attachment_hashes": {"공고.pdf": "reviewed-pdf"},
                       "attachment_text": "국내 소재 기업에 펀드 70% 이상 투자"}
        self.notice["sha256"] = hashlib.sha256(json.dumps(
            [self.notice["title"], self.notice["date"], self.notice["body"]], ensure_ascii=False).encode()).hexdigest()
        self.recipe = {"sources": [{"source_id": "61742", "event": "모집 공고",
                                     **{k: self.notice[k] for k in ("url", "title", "date", "sha256")},
                                     "body_quotes": ["3,000억원", "9월 11일"],
                                     "attachment_hashes": {"공고.pdf": "reviewed-pdf"},
                                     "attachment_quotes": ["70% 이상"]}]}
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "recipe.json"
        self.path.write_text(json.dumps(self.recipe, ensure_ascii=False))
        patcher = patch.object(ktcu, "REVIEW", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reviewed_notice_closes_recruitment_without_inventing_gps(self):
        programs, holds = ktcu.project([self.notice], "2026-10-03T00:00:00+00:00", self.seed)
        self.assertEqual([], holds)
        self.assertEqual("접수 마감", programs[0]["status"])
        self.assertEqual([], programs[0]["selected_gps"])
        self.assertNotIn("공고상 접수 마감", [e["type"] for e in programs[0]["events"]])

    def test_changed_source_or_pdf_preserves_previous_publication(self):
        edited = copy.deepcopy(self.notice)
        edited["body"] += " 변경"
        self.assertEqual([], ktcu.project([edited], "2026-10-03T00:00:00+00:00", self.seed)[0])
        edited = copy.deepcopy(self.notice)
        edited["attachment_hashes"]["공고.pdf"] = "changed-pdf"
        self.assertEqual([], ktcu.project([edited], "2026-10-03T00:00:00+00:00", self.seed)[0])

    def test_unreviewed_result_is_only_a_link_candidate(self):
        result = {"source_id": "62000", "url": "https://www.ktcu.or.kr/PPW-CSB-000101/62000",
                  "title": "2026년 블라인드 PEF 선정 결과", "date": "2026-10-30",
                  "body": "A운용사 최종 선정", "sha256": "candidate"}
        programs, holds = ktcu.project([self.notice, result], "2026-10-31T00:00:00+00:00", self.seed)
        self.assertEqual([], programs)
        self.assertIn("검토 필요", holds[0]["reason"])
        self.assertEqual("62000", ktcu.link_suggestions([self.notice, result], self.seed["title"])[0]["source_id"])

    def test_next_year_pef_is_a_new_program_candidate_without_holding_2026(self):
        later = {"source_id": "70000", "url": "https://www.ktcu.or.kr/PPW-CSB-000101/70000",
                 "title": "2027년 블라인드 PEF 위탁운용사 선정 공고", "date": "2026-12-01",
                 "body": "별도 출자사업 모집 공고", "sha256": "candidate"}
        programs, holds = ktcu.project([self.notice, later], "2026-12-02T00:00:00+00:00", self.seed)
        self.assertEqual([], holds)
        self.assertEqual(ktcu.PROGRAM_ID, programs[0]["id"])
        self.assertEqual([], ktcu.link_suggestions([self.notice, later], self.seed["title"]))
        self.assertEqual("70000", ktcu.discovery_candidates([self.notice, later])[0]["source_id"])

    def test_result_review_requires_names_in_official_source(self):
        result = {"source_id": "62000", "url": "https://www.ktcu.or.kr/PPW-CSB-000101/62000",
                  "title": "2026년 블라인드 PEF 선정 결과", "date": "2026-10-30",
                  "body": "B운용사 최종 선정", "attachment_hashes": {}}
        result["sha256"] = hashlib.sha256(json.dumps(
            [result["title"], result["date"], result["body"]], ensure_ascii=False).encode()).hexdigest()
        self.recipe["sources"].append({"source_id": "62000", "event": "최종 선정",
                                        **{k: result[k] for k in ("url", "title", "date", "sha256")},
                                        "manager_names": ["A운용사"]})
        self.path.write_text(json.dumps(self.recipe, ensure_ascii=False))
        programs, holds = ktcu.project([self.notice, result], "2026-10-31T00:00:00+00:00", self.seed)
        self.assertEqual([], programs)
        self.assertIn("명단", holds[0]["reason"])


if __name__ == "__main__":
    unittest.main()
