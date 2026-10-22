import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

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

    def listing(self, rows, start="2025-10-23", end="2026-10-22", empty=False):
        # Minimal structure from the observed board: date inputs, board ID and
        # source links. Raw captured HTML is deliberately not versioned.
        controls = (f'<form><input name="bid" value="0041">'
                    f'<input name="keySDate" value="{start}">'
                    f'<input name="keyEDate" value="{end}"></form>')
        links = ''.join(f'<a href="/board.es?mid=a10510000000&amp;bid=0041&amp;act=view&amp;list_no={number}" title="{title}">공고</a>'
                        for number, title in rows)
        return (controls + links + ('<p>등록된 게시물이 없습니다.</p>' if empty else '')).encode()

    def collect_fixture(self, listing, details=None, checked="2026-10-22T05:00:00+00:00"):
        details = details or {}
        requests = []
        def fetch(url):
            requests.append(url)
            query = parse_qs(urlparse(url).query)
            if 'nPage' in query:
                return listing[int(query['nPage'][0])] if isinstance(listing, dict) else listing
            number = query['list_no'][0]
            if number == '400':
                date_value, title = self.recipe['source_date'], self.recipe['source_title']
            else:
                date_value, title = details[number]
            return (f'<p class="title">{title}</p><th>작성일시</th><td>{date_value} 09:00</td>'
                    '<td colspan="4" class="tb_contents">공식 본문</td>').encode()
        seed = {'id': post.PROGRAM_ID, 'title': self.recipe['program']['title']}
        with patch.object(post, 'project', return_value=([], [])):
            return post.collect(seed, checked, fetch=fetch), requests

    def test_rolling_window_uses_aware_korean_dates_and_exactly_365_days(self):
        from datetime import date
        start, end = post._date_window('2026-10-22T05:00:00Z')
        self.assertEqual((start, end), ('2025-10-23', '2026-10-22'))
        self.assertEqual((date.fromisoformat(end) - date.fromisoformat(start)).days + 1, 365)
        self.assertEqual(post._date_window('2026-10-22T15:30:00+00:00'), ('2025-10-24', '2026-10-23'))
        self.assertEqual(post._date_window('2024-03-01T12:00:00+09:00'), ('2023-03-03', '2024-03-01'))
        with self.assertRaises(ValueError): post._date_window('2026-10-22T12:00:00')

    def test_explicit_date_query_discovers_prior_year_only_from_observed_rows(self):
        title = '2025년도 우체국금융 국내 블라인드 PEF 위탁운용사 선정 공고'
        report, requests = self.collect_fixture(self.listing([('347', title)]), {'347': ('2025-12-20', title)})
        query = parse_qs(urlparse(requests[0]).query)
        self.assertEqual(query['keySDate'], ['2025-10-23'])
        self.assertEqual(query['keyEDate'], ['2026-10-22'])
        self.assertEqual({'0041:347', '0041:400'}, {n['source_id'] for n in report['notices']})
        self.assertEqual(['0041:347'], [n['source_id'] for n in report['discovery_candidates']])
        self.assertEqual({'347', '400'}, {parse_qs(urlparse(url).query)['list_no'][0] for url in requests if 'list_no=' in url})
        self.assertEqual(report['collection_coverage']['date_filter_validation'], 'echo_confirmed')
        self.assertEqual(report['collection_coverage']['window_completeness'], 'not_assessed')

    def test_detail_dates_enforce_inclusive_boundary_and_exclude_future_rows(self):
        title = '우체국금융 국내 사모투자펀드 운용사 모집 공고'
        details = {'395': ('2025-10-22', title), '396': ('2025-10-23', title),
                   '397': ('2026-10-22', title), '398': ('2026-10-23', title)}
        report, _ = self.collect_fixture(self.listing([(number, title) for number in details]), details)
        self.assertEqual({'0041:396', '0041:397', '0041:400'}, {n['source_id'] for n in report['notices']})

    def test_server_ignoring_filters_fails_and_missing_echo_stays_unknown(self):
        with self.assertRaisesRegex(ValueError, 'date filters differ'):
            self.collect_fixture(self.listing([], start='2026-04-22', empty=True))
        legacy = '<a href="/board.es?bid=0041&amp;act=view&amp;list_no=400" title="우체국금융 국내 PEF 공고">공고</a>'.encode()
        report, _ = self.collect_fixture(legacy)
        self.assertEqual(report['collection_coverage']['date_filter_validation'], 'unknown')
        self.assertEqual(report['collection_coverage']['window_completeness'], 'not_assessed')

    def test_explicit_empty_period_retains_reviewed_historical_source(self):
        report, requests = self.collect_fixture(self.listing([], start='2027-10-24', end='2028-10-22', empty=True),
                                               checked='2028-10-22T12:00:00+09:00')
        self.assertEqual([n['source_id'] for n in report['notices']], ['0041:400'])
        self.assertEqual(report['discovery_candidates'], [])
        self.assertEqual(report['collection_coverage']['pagination_end'], 'explicit_empty')
        self.assertEqual(len(requests), 2)

    def test_unrecognized_empty_is_failure_and_repeated_pages_do_not_complete(self):
        for malformed in [b'', b'<html>error</html>', self.listing([])]:
            with self.assertRaisesRegex(ValueError, 'no recognized notices'):
                self.collect_fixture(malformed)
        ten = self.listing([(str(n), '기타 자산 공고') for n in range(10)])
        with self.assertRaisesRegex(ValueError, 'pagination did not advance'):
            self.collect_fixture(ten)
        report, requests = self.collect_fixture({1: ten, 2: self.listing([], empty=True)})
        self.assertEqual(report['collection_coverage']['pagination_end'], 'explicit_empty')
        self.assertEqual(len([u for u in requests if 'nPage=' in u]), 2)
        for url in requests[:2]:
            self.assertIn('keySDate=2025-10-23', url)
            self.assertIn('keyEDate=2026-10-22', url)

    def test_pagination_budget_exhaustion_fails_instead_of_claiming_complete(self):
        pages = {p: self.listing([(str(p * 10 + i), '기타 공고') for i in range(10)]) for p in range(1, 11)}
        with self.assertRaisesRegex(ValueError, 'pagination exceeded'):
            self.collect_fixture(pages)

    def pager_listing(self, current, pages=(1, 2, 3), rows=()):
        html = self.listing(rows).decode()
        html += f'<input name="nPage" value="{current}"><input name="nPage" value="{current}">'
        html += '<div class="board_pager"><span class="inner">'
        for page in pages:
            cls = 'pageNow' if page == current else 'pageNone'
            html += (f'<a class="{cls}" href="/board.es?mid=a10510000000&amp;bid=0041&amp;nPage={page}">{page}</a>')
        return ('<html>' + html + '</span></div></html>').encode()

    def test_advertised_last_page_avoids_an_unrecognized_empty_page_after_it(self):
        # A full final page must not require a speculative fourth-page request.
        pages = {page: self.pager_listing(page, rows=[(str(page * 10 + i), '기타 자산 공고') for i in range(10)])
                 for page in (1, 2, 3)}
        report, requests = self.collect_fixture(pages)
        listing_urls = [url for url in requests if 'nPage=' in url]
        self.assertEqual([parse_qs(urlparse(u).query)['nPage'][0] for u in listing_urls], ['1', '2', '3'])
        self.assertEqual(report['collection_coverage']['pagination_end'], 'advertised_last_page')
        self.assertEqual(report['collection_coverage']['listing_pages'][-1]['advertised_last_page'], 3)

    def test_pager_helper_validates_own_links_request_and_current_page(self):
        url = post.LIST_URL + '&keySDate=2025-10-23&keyEDate=2026-10-22&nPage=2'
        raw = self.pager_listing(2)
        self.assertEqual(post._listing_last_page(raw, url), 3)
        invalid = [raw.replace(b'bid=0041', b'bid=0042'),
                   raw.replace(b'/board.es?mid=', b'https://foreign.example/board.es?mid='),
                   raw.replace(b'name="nPage" value="2"', b'name="nPage" value="1"'),
                   raw.replace(b'pageNow', b'pageNone'), raw.replace(b'</html>', b'')]
        for html in invalid:
            with self.subTest(html=html[:80]), self.assertRaises(ValueError):
                post._listing_last_page(html, url)
        with self.assertRaises(ValueError):
            post._listing_last_page(raw, url.replace('bid=0041', 'bid=0042'))

    def test_pager_number_block_is_not_assumed_to_be_the_final_block(self):
        url = post.LIST_URL + '&nPage=1'
        self.assertIsNone(post._listing_last_page(self.pager_listing(1, pages=tuple(range(1, 11))), url))
        self.assertIsNone(post._listing_last_page(self.pager_listing(1, pages=(1, 3)), url))
        self.assertIsNone(post._listing_last_page('<html><tbody></tbody></html>', url))

    def test_bare_empty_table_is_still_not_a_valid_empty_date_window(self):
        # The observed out-of-range page advertises 1..3 but returns empty on 4.
        raw = self.pager_listing(4).replace(b'<span class="inner">',
              '<table><thead><tr><th>번호</th><th>제목</th><th>작성자</th><th>작성일</th><th>첨부</th></tr></thead><tbody></tbody></table><span class="inner">'.encode())
        self.assertEqual(post._listing_last_page(raw, post.LIST_URL + '&nPage=4'), 3)
        self.assertFalse(post._explicit_empty_listing(raw))
        with self.assertRaises(ValueError):
            self.collect_fixture({1: self.pager_listing(1, rows=())})

    def test_foreign_board_link_is_not_a_discovery_source(self):
        raw = b'<a href="https://foreign.example/board.es?bid=0041&amp;act=view&amp;list_no=123" title="PEF">link</a>'
        self.assertEqual(post._listing(raw), [])

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
