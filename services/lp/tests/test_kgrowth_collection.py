import copy
import importlib.util
import unittest
import sys
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

spec = importlib.util.spec_from_file_location("collector", Path(__file__).resolve().parents[1] / "src/collect_kgrowth_programs.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def html(title, body, date="2026-07-31"):
    return (f'<div class="view_info"><p class="tit">{title}</p><p class="date">작성일 {date}</p></div>'
            f'<div class="veiw_contents"><p>{body}</p></div><div>irrelevant footer</div>').encode("cp949")


class CollectionTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(c, 'recipes', return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def test_transient_official_network_error_retries(self):
        from urllib.error import URLError
        from unittest.mock import Mock
        class Response:
            def __init__(self, url, body):
                self.url, self.body = url, body
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def geturl(self): return self.url
            def read(self, limit=-1): return self.body[:limit] if limit >= 0 else self.body
        failures = []
        def open_request(request, timeout):
            url = request.full_url
            failures.append(url)
            if len(failures) == 1:
                raise URLError('temporary DNS failure')
            return Response(url, self.docs[url])
        with patch.object(c, 'build_opener', return_value=Mock(open=open_request)), patch.object(c.time, 'sleep') as sleep:
            result = c.collect(self.seed)
        self.assertEqual(failures[:2], [c.LIST_URL, c.LIST_URL])
        sleep.assert_called_once_with(1)
        self.assertEqual(len(result['programs']), 1)

    def test_new_notice_is_review_only(self):
        result = c.collect(self.seed, fetch=self.fetch)
        self.assertEqual(len(result["programs"]), 1)
        self.assertEqual(result["review"][0]["source_id"], "9999")
        self.assertEqual(len(result["programs"][0]["events"]), 4)

    def test_official_response_size_limit_is_enforced_without_retry(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = c.LIST_URL
        response.read.return_value = b'x' * (12 * 1024 * 1024 + 1)
        with patch.object(c, 'build_opener', return_value=MagicMock(open=MagicMock(return_value=response))) as opener:
            fetch = c.official_fetcher()
            with self.assertRaisesRegex(ValueError, 'exceeds 12 MiB'):
                fetch(c.LIST_URL)
        response.read.assert_called_once_with(12 * 1024 * 1024 + 1)
        self.assertEqual(opener.return_value.open.call_count, 1)

    def test_listing_pagination_detects_new_notice_without_registered_id(self):
        self.docs[c.LIST_URL] += b'<a href="Javascript:ListView(2,1,0)">2</a>'
        self.docs[c.LIST_URL+'&page=2'] = b'<a href="notice_view.asp?idx=987654">new</a>'
        self.docs[c.notice_url(987654)] = html('새 펀드 선정계획 공고','붙임 공고문 참고')
        result=c.collect(self.seed,fetch=self.fetch)
        self.assertIn('987654',[n['source_id'] for n in result['notices']])
        self.assertEqual(result['collection_coverage']['discovered_count'],2)
        self.assertEqual(result['collection_coverage']['missing_source_ids'],[])
        self.assertEqual(len(result['collection_coverage']['listing_urls']),2)

    def test_every_attachment_is_read_without_recipe_text_allowlist(self):
        self.docs[c.notice_url(9999)] = html('새 펀드 선정계획 공고','붙임 공고문 참고') + b'<a href="down_file.asp?idx=9999&SelType=Notice1">file</a>'
        attachment=c.BASE+'down_file.asp?idx=9999&SelType=Notice1'
        self.docs[attachment]=b'%PDF synthetic attachment'
        with patch.object(c,'extract_attachment',return_value={'format':'pdf','text':'출자 대상 기관전용 사모집합투자기구','tables':[]}):
            result=c.collect(self.seed,fetch=self.fetch)
        n=next(n for n in result['notices'] if n['source_id']=='9999')
        self.assertIn(attachment,n['attachment_texts'])
        self.assertTrue(result['collection_coverage']['attachments'][0]['readable'])

    def test_unreadable_new_attachment_keeps_notice_and_explicit_failure_reason(self):
        self.docs[c.notice_url(9999)] += b'<a href="down_file.asp?idx=9999&SelType=Notice1">file</a>'
        self.docs[c.BASE+'down_file.asp?idx=9999&SelType=Notice1']=b'%PDF synthetic attachment'
        with patch.object(c,'extract_attachment',side_effect=ValueError('Unreadable body')):
            result=c.collect(self.seed,fetch=self.fetch)
        self.assertEqual(result['collection_coverage']['attachments'][0]['reason'],'Unreadable body')
        self.assertFalse(result['collection_coverage']['attachments'][0]['readable'])

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

    def test_date_window_fetches_prior_year_and_keeps_older_tracked_notices(self):
        from services.lp.tests.test_kgrowth_listing import page
        baseline = c.collect(self.seed, fetch=self.fetch)
        self.docs[c.LIST_URL] = page([('3', '987654', '과거 사업', '2025-12-15')]).encode('cp949')
        self.docs[c.LIST_URL + '&page=2'] = page([('1', '987653', '오래된 사업', '2025-01-01')]).encode('cp949')
        self.docs[c.notice_url(987654)] = html('과거 사업', '공고 원문', '2025-12-15')
        result = c.collect(self.seed, baseline, self.fetch, listing_pages=20, lookback_days=365, as_of='2026-10-24')
        self.assertEqual({n['source_id'] for n in result['notices']}, {'1047', '1075', '1090', '1100', '9999', '987654'})
        self.assertEqual(result['collection_coverage']['discovered_count'], 1)
        self.assertTrue(result['collection_coverage']['date_discovery']['complete'])
        self.assertEqual(result['accepted_notices'], baseline['accepted_notices'])

    def test_incomplete_year_does_not_start_details_or_replace_baseline(self):
        from services.lp.tests.test_kgrowth_listing import page
        self.docs[c.LIST_URL] = page([('1', '9999', '최신', '2026-10-24')]).encode('cp949')
        with self.assertRaisesRegex(ValueError, 'discovery incomplete'):
            c.collect(self.seed, fetch=self.fetch, listing_pages=1, lookback_days=365, as_of='2026-10-24')

    def test_listing_detail_date_conflict_is_not_silently_accepted(self):
        from services.lp.tests.test_kgrowth_listing import page
        self.docs[c.LIST_URL] = page([('2', '9999', '최신', '2026-07-30')]).encode('cp949')
        self.docs[c.LIST_URL + '&page=2'] = page([('1', '9998', '과거', '2025-01-01')]).encode('cp949')
        with self.assertRaisesRegex(ValueError, 'publication dates differ'):
            c.collect(self.seed, fetch=self.fetch, listing_pages=20, lookback_days=365, as_of='2026-10-24')

    def empty_detail(self):
        return ('<html><body><div class="notice_view_wrap"><h3>출자사업공고</h3>'
                '<div class="view_info"><p class="tit"></p>'
                '<p class="date">작성일 <span></span></p></div>'
                '<div class="veiw_contents"> </div><ul class="file_list"> </ul>'
                '</div></body></html>').encode('cp949')

    def test_complete_empty_new_detail_is_held_and_retried_without_fake_facts(self):
        self.docs[c.notice_url(9999)] = self.empty_detail()
        result = c.collect(self.seed, fetch=self.fetch)
        self.assertNotIn('9999', [n['source_id'] for n in result['notices']])
        self.assertEqual(result['unavailable_notices'][0]['reason'], 'official_detail_empty')
        tracked = next(n for n in result['tracked_notices'] if n['source_id'] == '9999')
        self.assertEqual(set(tracked), {'source_id', 'url'})
        self.docs[c.LIST_URL] = b'<a href="notice_view.asp?idx=1100">known</a>'
        self.docs[c.notice_url(9999)] = html('새 공고', '본문')
        recovered = c.collect(self.seed, result, self.fetch)
        self.assertIn('9999', [n['source_id'] for n in recovered['notices']])

    def test_empty_tracked_detail_preserves_old_evidence_and_known_program(self):
        baseline = c.collect(self.seed, fetch=self.fetch)
        self.docs[c.notice_url(1100)] = self.empty_detail()
        result = c.collect(self.seed, baseline, self.fetch)
        self.assertTrue(result['requires_review'])
        self.assertEqual(result['programs'], baseline['programs'])
        self.assertEqual(result['accepted_notices'], baseline['accepted_notices'])
        old = next(n for n in baseline['tracked_notices'] if n['source_id'] == '1100')
        self.assertEqual(next(n for n in result['tracked_notices'] if n['source_id'] == '1100'), old)
        self.assertNotIn('1100', [n['source_id'] for n in result['notices']])

    def test_partial_malformed_restricted_and_attachment_pages_still_fail(self):
        empty = self.empty_detail().decode('cp949')
        for text in (empty.replace('</html>', ''), empty.replace('</div></body>', '</body>'), empty.replace('작성일', '오류'),
                     empty.replace('<p class="tit"></p>', '<p class="tit">제목</p>'),
                     empty.replace('<ul class="file_list"> </ul>', '<ul class="file_list"><a href="down_file.asp?idx=1">첨부</a></ul>'),
                     empty + '비정상적인 접근', empty.replace('class="notice_view_wrap"', 'class="other"')):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as error:
                    c.parse_notice(9999, text.encode('cp949'))
                self.assertNotIsInstance(error.exception, c.UnavailableNotice)

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
