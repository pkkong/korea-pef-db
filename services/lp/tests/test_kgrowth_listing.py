import unittest
from urllib.parse import parse_qs, urlsplit

from services.lp.src import kgrowth_listing as listing


def page(rows, extra=''):
    return ('<html><table><tr><th>번호</th><th>제목</th><th>작성일</th><th>첨부</th></tr>' +
            ''.join(f'<tr><td>{num}</td><td><a href="notice_view.asp?idx={ident}&str_type=1&tab=1">{title}</a></td>'
                    f'<td>{stamp}</td><td></td></tr>' for num, ident, title, stamp in rows) + extra + '</table></html>')


class GrowthListingTests(unittest.TestCase):
    def discover(self, pages, **kwargs):
        calls = []
        def fetch(url):
            calls.append(url)
            num = int(parse_qs(urlsplit(url).query).get('page', ['1'])[0])
            return pages[num].encode('cp949')
        report = listing.discover_window(fetch, as_of='2026-10-24', **kwargs)
        return report, calls

    def test_crosses_page_groups_and_prior_year_without_registered_ids(self):
        pages = {num: page([(str(200-num), str(9000-num), '새 출자사업 공고', '2026-01-02')])
                 for num in range(1, 12)}
        pages[12] = page([('1', '8000', '이전 공고', '2025-01-01')])
        report, calls = self.discover(pages)
        self.assertTrue(report['complete'])
        self.assertEqual(report['boundary'], 'observed_older_page')
        self.assertEqual(len(report['rows']), 11)
        self.assertEqual(len(calls), 12)
        self.assertTrue(all(r['html'] and len(r['sha256']) == 64 for r in report['receipts']))

    def test_dates_are_inclusive_and_title_year_is_not_the_posting_date(self):
        report, _ = self.discover({1: page([('4', '4', '2027년 펀드', '2026-10-25'),
                                         ('3', '3', '2025년 펀드', '2026-10-24'),
                                         ('2', '2', '2026년 펀드', '2025-10-25')]),
                                   2: page([('1', '1', '2026년 펀드', '2025-10-24')])})
        self.assertEqual(report['window'], {'start': '2025-10-25', 'end': '2026-10-24', 'days': 365})
        self.assertEqual({r['source_id'] for r in report['rows']}, {'2', '3'})

    def test_old_pinned_notices_are_preserved_but_never_end_the_year(self):
        pin = ('공지', '90', '상시 안내', '2020-01-01')
        report, calls = self.discover({1: page([pin, ('3', '3', '최신', '2026-10-24')]),
                                       2: page([pin, ('2', '2', '과거', '2025-01-01')])})
        self.assertEqual(len(calls), 2)
        self.assertTrue(report['complete'])
        self.assertEqual({r['source_id'] for r in report['rows']}, {'90', '3'})

    def test_repeat_and_pinned_only_do_not_claim_completion(self):
        for rows in [[('공지', '9', '안내', '2020-01-01')],
                     [('공지', '9', '안내', '2020-01-01'), ('2', '2', '최신', '2026-10-24')]]:
            with self.subTest(rows=rows):
                report, _ = self.discover({1: page(rows), 2: page(rows)})
                self.assertFalse(report['complete'])
                self.assertEqual(report['boundary'], 'repeated_or_pinned_only_page')

    def test_limit_retains_evidence_without_saying_the_year_was_found(self):
        report, _ = self.discover({1: page([('1', '1', '최신', '2026-10-24')])}, max_pages=1)
        self.assertFalse(report['complete'])
        self.assertEqual(report['boundary'], 'page_limit')
        self.assertEqual(len(report['receipts']), 1)

    def test_only_board_empty_message_can_end_discovery(self):
        valid = page([], '<tr><td>등록된 게시물이 없습니다</td></tr>')
        report, _ = self.discover({1: valid})
        self.assertTrue(report['complete'])
        self.assertEqual(report['boundary'], 'confirmed_empty')
        for bad in ['<html>등록된 게시물이 없습니다</html>',
                    page([]) + '<footer>등록된 게시물이 없습니다</footer>']:
            with self.subTest(html=bad), self.assertRaises(ValueError):
                self.discover({1: bad})

    def test_missing_invalid_or_conflicting_dates_and_incomplete_markup_fail(self):
        valid = page([('1', '1', '공고', '2026-10-24')])
        for bad in [valid.replace('2026-10-24', ''), valid.replace('2026-10-24', '2026-02-30'),
                    valid.replace('2026-10-24', '2026-10-24 2026-10-23'), valid.replace('</html>', '')]:
            with self.subTest(html=bad), self.assertRaises(ValueError):
                self.discover({1: bad})

    def test_title_date_does_not_override_posting_column(self):
        rows = listing.parse_listing(page([('1', '1', '2026-11-01 마감 공고', '2026-10-24')]), listing.LIST_URL)
        self.assertEqual(rows[0]['date'], '2026-10-24')

    def test_out_of_order_dates_cannot_establish_an_age_boundary(self):
        with self.assertRaisesRegex(ValueError, 'descending'):
            self.discover({1: page([('2', '2', '공고', '2026-10-01')]),
                           2: page([('1', '1', '공고', '2026-10-24')])})

    def test_conflicting_pinned_metadata_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'metadata'):
            self.discover({1: page([('공지', '90', '안내', '2020-01-01'), ('2', '2', '공고', '2026-10-24')]),
                           2: page([('공지', '90', '변경 안내', '2020-01-01'), ('1', '1', '이전 공고', '2025-01-01')])})

    def test_other_board_or_conflicting_identifier_cannot_match(self):
        url = listing.BASE + 'notice_view.asp?idx=123&str_type=1&tab=1'
        self.assertEqual(listing.source_id(url + '&page=2'), '123')
        for bad in [url.replace('https:', 'http:'), url.replace('kgrowth.or.kr', 'evil.example'),
                    url + '&idx=124', url + '&str_type=2', url + '&tab=2']:
            with self.subTest(url=bad), self.assertRaises(ValueError):
                listing.source_id(bad)

    def test_safety_limits_fail_before_fetching(self):
        for days, max_pages in [(0, 20), (367, 20), (365, 0), (365, 21)]:
            with self.subTest(days=days, pages=max_pages), self.assertRaises(ValueError):
                listing.discover_window(lambda u: self.fail('unexpected network'), days=days, max_pages=max_pages)


if __name__ == '__main__':
    unittest.main()
