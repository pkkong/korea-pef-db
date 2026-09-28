import copy
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("collector", Path(__file__).resolve().parents[1] / "src/collect_kgrowth_programs.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def html(title, body, date="2026-07-31"):
    return (f'<div class="view_info"><p class="tit">{title}</p><p class="date">작성일 {date}</p></div>'
            f'<div class="veiw_contents"><p>{body}</p></div><div>irrelevant footer</div>').encode("cp949")


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.seed = {"programs": [{"id": c.PROGRAM_ID, "events": [], "selected_gps": [{"name": f"GP{i}"} for i in range(3)], "amount": "검토된 금액"}]}
        name = "은행권 중견기업 밸류업펀드(3차)"
        self.docs = {
            c.LIST_URL: b'<a href="notice_view.asp?idx=9999">new</a>',
            c.notice_url(1047): html(name + " 위탁운용사 선정계획 공고", "선정계획 공고", "2026-06-04"),
            c.notice_url(1075): html(name + " 접수현황", "신청 펀드 17개<br>운용사명(가나다순)<br>" + "<br>".join(f"- GP{i}" for i in range(17)), "2026-07-07"),
            c.notice_url(1090): html(name + " 서류심사 결과", "서류심사 통과 6개사<br>운용사명(가나다순)<br>" + "<br>".join(f"- GP{i}" for i in range(6)), "2026-07-23"),
            c.notice_url(1100): html(name + " 선정결과", "선정 결과<br>운용사명(가나다순)<br>GP0<br>GP1<br>GP2"),
            c.notice_url(9999): html("새로운 사업 선정결과", "선정 결과 운용사명 신규운용사")}

    def fetch(self, url, referer=None):
        return self.docs[url]

    def test_new_notice_is_review_only(self):
        result = c.collect(self.seed, fetch=self.fetch)
        self.assertEqual(len(result["programs"]), 1)
        self.assertEqual(result["review"][0]["source_id"], "9999")
        self.assertEqual(len(result["programs"][0]["events"]), 4)

    def test_change_stays_quarantined_across_runs(self):
        first = c.collect(self.seed, fetch=self.fetch)
        old = copy.deepcopy(first["programs"])
        self.docs[c.notice_url(1100)] = html("은행권 중견기업 밸류업펀드(3차) 선정결과", "선정 결과 운용사명 다른운용사")
        second = c.collect(self.seed, first, self.fetch)
        third = c.collect(self.seed, second, self.fetch)
        self.assertTrue(second["requires_review"])
        self.assertTrue(third["requires_review"])
        self.assertEqual(old, third["programs"])

    def test_unreviewed_notice_still_tracked_after_leaving_listing(self):
        first = c.collect(self.seed, fetch=self.fetch)
        self.docs[c.LIST_URL] = b'<a href="notice_view.asp?idx=1100">known</a>'
        self.docs[c.notice_url(9999)] = html("새로운 사업 정정", "변경된 공고")
        second = c.collect(self.seed, first, self.fetch)
        notice = next(n for n in second['tracked_notices'] if n['source_id'] == '9999')
        self.assertEqual(notice['body'], '변경된 공고')
        self.assertIn('9999', [n['source_id'] for n in second['review']])
        self.assertEqual(first['accepted_notices'], second['accepted_notices'])

    def test_failure_raises_without_empty_program(self):
        self.docs[c.notice_url(1047)] = b'<html>error</html>'
        with self.assertRaises(ValueError):
            c.collect(self.seed, fetch=self.fetch)

    def test_shortlist_is_not_final(self):
        self.assertEqual(c.event_type("선정결과 서류심사 결과", "서류심사 통과"), "서류심사 결과")
        self.assertIsNone(c.event_type("선정결과 정정", "선정 결과 운용사명"))

    def test_body_excludes_neighbouring_notices(self):
        parsed = c.parse_notice(1, html("제목", "본문"))
        self.assertEqual(parsed["body"], "본문")
        self.assertNotIn("footer", parsed["body"])

    def test_schedule_sync_keeps_reviewed_details(self):
        self.seed["programs"][0]["schedule_stages"] = [{"source_url": c.notice_url(1075), "date": "old", "detail": "검토된 내용"}]
        result = c.collect(self.seed, fetch=self.fetch)
        stage = result["programs"][0]["schedule_stages"][0]
        self.assertEqual(stage["date"], "2026-07-07")
        self.assertEqual(stage["detail"], "검토된 내용")

    def test_initial_unreviewed_date_rejected(self):
        self.docs[c.notice_url(1047)] = html("은행권 중견기업 밸류업펀드(3차) 선정계획 공고", "공고", "2026-06-05")
        with self.assertRaises(ValueError):
            c.collect(self.seed, fetch=self.fetch)


if __name__ == "__main__":
    unittest.main()
