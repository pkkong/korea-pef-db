import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import collect_koreapost_program as post
from collect_koreapost_program import REGISTRY, _detail, _listing, _suggestions, project


class KoreaPostReviewTests(unittest.TestCase):
    def setUp(self):
        self.recipe = json.loads(REGISTRY.read_text())
        r = self.recipe
        self.notice = {"source_id": r["source_id"], "url": r["source_url"],
                       "title": r["source_title"], "date": r["source_date"],
                       "body": r["source_body"], "sha256": r["sha256"],
                       "attachment_hashes": r["attachment_hashes"],
                       "attachment_texts": {r["pdf_url"]: " ".join(f["quote"] for f in r["facts"] if f["source"] == "pdf")}}

    def test_approved_notice_has_deadline_schedule_and_no_gp(self):
        programs, holds = project([self.notice], "2026-10-03T00:00:00+09:00")
        self.assertEqual(holds, [])
        program = programs[0]
        self.assertEqual(program["status"], "접수 마감")
        self.assertEqual(program["commitment_amount_krw"], 245000000000)
        self.assertEqual([part["manager_count"] for part in program["segments"]], ["3~4개사", "2~3개사"])
        self.assertEqual(program["selected_gps"], [])
        self.assertEqual(program["schedule_stages"][-1]["status"], "planned")
        before, _ = project([self.notice], "2026-09-28T15:59:00+09:00")
        self.assertEqual(before[0]["status"], "모집 공고")

    def test_changed_source_attachment_or_quote_is_held(self):
        for change in ("body", "attachment", "quote"):
            changed = copy.deepcopy(self.notice)
            if change == "body":
                changed["body"] += " 변경"
            elif change == "attachment":
                changed["attachment_hashes"][self.recipe["pdf_url"]] = "changed"
            else:
                changed["attachment_texts"][self.recipe["pdf_url"]] = "문구 없음"
            programs, holds = project([changed], "2026-10-03T00:00:00+09:00")
            self.assertEqual(programs, [])
            self.assertEqual(holds[0]["program_id"], "koreapost-2026-domestic-pe")

    def test_new_result_is_only_connection_candidate(self):
        new = {"source_id": "0041:402", "url": "https://www.kpasset.go.kr/board.es?mid=a10510000000&bid=0041&act=view&list_no=402",
               "title": "2026년도 우체국금융 국내 블라인드 PEF 위탁운용사 선정 결과 안내",
               "date": "2026-11-15", "body": "최종 선정 GP: 확인되지 않은 운용사",
               "sha256": "new-fingerprint", "attachment_hashes": {}}
        programs, holds = project([self.notice, new], "2026-11-15T10:00:00+09:00")
        self.assertEqual(programs, [])
        self.assertIn("새 단계", holds[0]["reason"])
        suggestions = _suggestions([self.notice, new])
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["stage"], "최종 선정")
        self.assertEqual(suggestions[0]["programs"][0]["id"], "koreapost-2026-domestic-pe")
        self.assertNotIn("확인되지 않은 운용사", str(suggestions))

    def test_other_pe_strategy_is_discovered_without_rewriting_blind_pef(self):
        other = {"source_id": "0041:352", "url": "https://www.kpasset.go.kr/board.es?mid=a10510000000&bid=0041&act=view&list_no=352",
                 "title": "우체국예금 해외사모펀드 국내재간접 위탁운용사 우선협상대상자 알림",
                 "date": "2026-04-22", "body": "별도 사업 결과", "sha256": "candidate"}
        self.assertTrue(post._pe_discovery_title(other["title"]))
        programs, holds = project([self.notice, other], "2026-10-03T00:00:00+09:00")
        self.assertEqual([], holds)
        self.assertEqual(post.PROGRAM_ID, programs[0]["id"])
        self.assertEqual([], _suggestions([self.notice, other]))
        self.assertEqual("0041:352", post.discovery_candidates([self.notice, other])[0]["source_id"])

    def test_official_html_shapes_are_parsed_without_confusing_other_assets(self):
        listing = '''<a href="/board.es?mid=a10510000000&amp;bid=0041&amp;act=view&amp;list_no=400" title="2026년도 우체국금융 국내 블라인드 PEF 위탁운용사 선정 공고">PE..</a>
        <a href="/board.es?mid=a10510000000&amp;bid=0042&amp;act=view&amp;list_no=430" title="2026 보험 VC">VC</a>'''.encode()
        self.assertEqual(_listing(listing), [("400", "2026년도 우체국금융 국내 블라인드 PEF 위탁운용사 선정 공고")])
        detail = '''<p class="title">2026년도 우체국금융 국내 블라인드 PEF 선정</p>
        <th>작성일시</th><td>2026-09-10 09:36</td>
        <td colspan="4" class="tb_contents">모집<br/>공고</td>
        <a href="/download.es?filename=x.pdf&amp;seq=2">PDF</a>'''.encode()
        notice = _detail("400", detail)
        self.assertEqual(notice["date"], "2026-09-10")
        self.assertEqual(notice["body"], "모집\n공고")
        self.assertEqual(len(notice["attachments"]), 1)

    def test_bounded_history_finds_recruitment_missing_from_recent_listing(self):
        titles = {
            '400': ('2026-09-10', self.recipe['source_title']),
            '349': ('2026-04-13', '우체국예금 국내 공동투자 전략 펀드 정량평가 결과 안내'),
            '348': ('2026-03-30', '우체국예금 해외 사모펀드 국내 재간접 위탁운용사 선정 공고'),
            '347': ('2026-03-23', '2026년도 우체국예금 국내 공동투자 전략 펀드 위탁운용사 선정 공고'),
            '346': ('2025-12-20', '우체국예금 해외부동산 위탁운용사 선정 공고'),
        }
        listing = ('<a href="/board.es?mid=a10510000000&amp;bid=0041&amp;act=view&amp;list_no=349" '
                   'title="우체국예금 국내 공동투자 전략 펀드 정량평가 결과 안내">공고</a>').encode()
        def fetch(url):
            if 'nPage=' in url:
                return listing
            number = url.split('list_no=')[-1]
            date, title = titles[number]
            return (f'<p class="title">{title}</p><th>작성일시</th><td>{date} 09:00</td>'
                    '<td colspan="4" class="tb_contents">공식 본문</td>').encode()
        seed = {'id':post.PROGRAM_ID,'title':self.recipe['program']['title']}
        with patch.object(post,'project',return_value=([],[])):
            report = post.collect(seed,'2026-10-03T00:00:00+09:00',fetch=fetch)
        self.assertEqual({'0041:347','0041:348','0041:349','0041:400'},
                         {n['source_id'] for n in report['notices']})
        self.assertEqual(3,len(report['discovery_candidates']))

    def test_hash_reviewed_result_can_add_gps_without_changing_code(self):
        result = {"source_id": "0041:402", "url": "https://www.kpasset.go.kr/board.es?mid=a10510000000&bid=0041&act=view&list_no=402",
                  "title": "2026년도 우체국금융 국내 블라인드 PEF 위탁운용사 선정 결과",
                  "date": "2026-11-15", "body": "가운용사 최종 선정", "attachment_hashes": {}, "attachment_texts": {}}
        result["sha256"] = post._fingerprint(result)
        reviewed = copy.deepcopy(self.recipe)
        reviewed["stages"] = [{"source_id": result["source_id"], "title": result["title"], "date": result["date"],
                               "sha256": result["sha256"], "attachment_hashes": {}, "event": "최종 선정",
                               "manager_names": ["가운용사"], "quotes": ["최종 선정"]}]
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "review.json"
            registry.write_text(json.dumps(reviewed, ensure_ascii=False))
            with patch.object(post, "REGISTRY", registry):
                programs, holds = post.project([self.notice, result], "2026-11-16T00:00:00+09:00")
                self.assertEqual([], holds)
                self.assertEqual("선정 완료", programs[0]["status"])
                self.assertEqual(["가운용사"], [gp["name"] for gp in programs[0]["selected_gps"]])
                self.assertEqual([], post._suggestions([self.notice, result]))


if __name__ == "__main__":
    unittest.main()
