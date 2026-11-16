"""OCIO title/year/cursor isolation and source replay before publication."""
import copy
import unittest
from datetime import date
from html import escape
from unittest.mock import patch

from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src import lp_board_adapter_miraeasset as ma
from services.lp.src.lp_notice_publication import publish_basic_notices, _rule_valid_name
from services.lp.src.lp_result_rosters import pe_result_roster

STAMP = '2026-11-16T00:30:00+00:00'
TITLE = '2026년 고용보험기금 대체투자상품(PE, VC) 선정 최종 결과 안내'
# Structure and inline result observed 2026-11-16, messageId=2343655.
BODY = ('<div id="info_point">2026년 고용보험기금 대체투자상품(PE, VC) 선정 최종 결과를 다음과 같이 공지합니다.</div>'
        '<dl id="cont_list"><dt>최종 선정 결과</dt><dd>&middot; PE (2) : 에이치앤큐에쿼티파트너스, 제네시스프라이빗에쿼티<br />'
        '&middot; VC (3) : 미래에셋벤처투자, 브레인자산운용&middot;케이와이캐피탈, 파트너스인베스트먼트<br />※ 이상 가나다순</dd></dl>')


class Today(date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 16)


def config(**kwargs):
    return {**boards.load_configs(include_pending=True)['moel_eif_ocio'], **kwargs}


def urls(c=None):
    with patch.object(ma, 'date', Today):
        return list(ma.listing_urls(c or config()))


def form(q):
    return '<form id="viewForm">' + ''.join(
        f'<input name="{k}" value="{escape(v, quote=True)}">' for k, v in q.items() if k not in {'direction', 'listType'}
    ) + '</form>'


def listing(url, rows=None, next_url=None):
    q = ma._listing_query(url, config())
    if rows is None:
        rows = [('2343655', TITLE, '2026-10-26')] if q['searchStartYear'] == '2026' else []
    body = ''.join(f'<tr><td class="textColor">{d}</td><td class="left"><div class="subject">'
                   f'<a href="javascript:view(\'{i}\',\'1\')" id="bbsTitle0">{t}</a></div></td><td></td></tr>'
                   for i, t, d in rows) or '<tr><td colspan="3">게시물이 없습니다.</td></tr>'
    pager = (f'<div class="bbs_pagingWrap"><p class="bbs_paging"><span><a class="on">{q["curPage"]}</a></span>'
             + (f'<a href="{escape(next_url.removeprefix(ma.BASE + "/bbs/board/message/"), quote=True)}">다음</a>' if next_url else '')
             + '</p></div>') if rows else ''
    return ('<html>' + form(q) + '<table class="bbs_linetype2 mgt5"><caption>공지사항</caption>'
            '<thead><tr><th>작성일</th><th>제목</th><th>첨부</th></tr></thead><tbody>' + body + '</tbody></table>' + pager + '</html>')


def detail(url, title=TITLE, body=BODY):
    q = ma._query(url, ma.DETAIL_PATH, config())
    return ('<html>' + form(q) + '<table class="bbs_linetype2"><caption>공지사항 글읽기</caption>'
            '<thead><tr><th class="bbs_detailTitle"><h4>' + title + '</h4></th></tr></thead><tbody>'
            '<tr><th>작성일</th><td class="boline"><span class="mgr20">2026-10-26</span></td></tr>'
            '<tr><td class="bbs_detail_view"><div id="messageContentsDiv"><html><head><style>omit</style></head><body>'
            + body + '</body></html></div></td></tr></tbody></table></html>')


def detail_url():
    return ma._url(ma.DETAIL_PATH, dict(categoryId='66', messageId='2343655', startId='zzzzz~', startPage='1', curPage='1'))


class MiraeAssetTests(unittest.TestCase):
    def collect(self, fetch=None, c=None):
        c = c or config()
        def default(url, referer=None):
            return (detail(url) if ma.DETAIL_PATH in url else listing(url)).encode('euc-kr')
        with patch.object(ma, 'date', Today):
            return boards.collect({'moel_eif_ocio': c}, fetch_factory=lambda c: fetch or default,
                                  checked_at=STAMP, retry_failures=False)

    def test_pending_channel_belongs_to_the_fund_and_uses_annual_windows(self):
        self.assertNotIn('moel_eif_ocio', boards.load_configs())
        self.assertEqual(config()['institution_id'], 'moel_eif')
        self.assertIs(boards.adapter(config()), ma)
        windows = [ma._listing_query(u, config()) for u in urls()]
        self.assertEqual([q['searchStartYear'] for q in windows], ['2026', '2025', '2024', '2023'])
        self.assertEqual(windows[-1]['searchStartMonth'], '07')
        self.assertIn('%B0%ED%BF%EB', urls()[0])

    def test_only_named_fund_pe_results_are_candidates(self):
        rows = [('1', TITLE, '2026-10-26'),
                ('2', TITLE.replace('(PE, VC)', '(VC)'), '2026-10-25'),
                ('3', TITLE.replace('고용보험기금', '산재보험기금'), '2026-10-24'),
                ('4', TITLE.replace('최종 결과 안내', '공고'), '2026-08-07'),
                ('5', '고용보험기금 하위운용사 유니버스 최종 선정결과 안내', '2026-07-01')]
        parsed = ma.parse_listing(listing(urls()[0], rows), urls()[0], config())
        self.assertEqual([r['institution_id'] for r in parsed], ['moel_eif', None, None, None, None])

    def test_euc_kr_collection_replays_and_roster_excludes_vc(self):
        report = self.collect()
        self.assertEqual(report['holds'], [])
        self.assertEqual(len(report['notices']), 1)
        self.assertEqual(len(report['coverage']['moel_eif_ocio']['listing_boundaries']), 4)
        n = report['notices'][0]
        self.assertEqual(n['source_id'], 'moel_eif:miraeasset:2343655')
        self.assertEqual(boards.validate_notice(n, STAMP, config()), n)
        self.assertEqual(pe_result_roster(n['body'], valid=_rule_valid_name),
                         [('PE', ['에이치앤큐에쿼티파트너스', '제네시스프라이빗에쿼티'])])

    def test_actual_next_cursor_is_followed_and_validated(self):
        first = urls()[0]
        q = ma._listing_query(first, config())
        q.update(startId='09pRU~', startPage='2', curPage='2', direction='1')
        second = ma._url(ma.LIST_PATH, q)
        fetched = []
        def fetch(url, referer=None):
            fetched.append(url)
            if url == first:
                return listing(url, [('2', TITLE.replace('(PE, VC)', '(VC)'), '2026-10-27')], second).encode('euc-kr')
            return (detail(url) if ma.DETAIL_PATH in url else listing(url)).encode('euc-kr')
        r = self.collect(fetch)
        self.assertEqual(r['holds'], [])
        self.assertIn(second, fetched)
        self.assertEqual(r['notices'][0]['discovery_provenance']['listing']['url'], second)
        self.assertEqual(boards.validate_notice(r['notices'][0], STAMP, config()), r['notices'][0])

    def test_repeated_cursor_content_is_a_failure(self):
        first = urls()[0]
        q = ma._listing_query(first, config()); q.update(startId='09pRU~', startPage='2', curPage='2')
        second = ma._url(ma.LIST_PATH, q)
        def fetch(url, referer=None):
            return (detail(url) if ma.DETAIL_PATH in url else listing(url, next_url=second if url == first else None)).encode('euc-kr')
        r = self.collect(fetch)
        self.assertTrue(any('repeated' in h.get('error', '') for h in r['holds']))

    def test_depth_limit_is_not_reported_as_complete(self):
        c = config(pages=1)
        first = urls(c)[0]
        q = ma._listing_query(first, c); q.update(startId='09pRU~', startPage='2', curPage='2')
        second = ma._url(ma.LIST_PATH, q)
        def fetch(url, referer=None):
            return (detail(url) if ma.DETAIL_PATH in url else listing(url, next_url=second if url == first else None)).encode('euc-kr')
        r = self.collect(fetch, c)
        self.assertTrue(any(h['stage'] == 'institution_depth' for h in r['holds']))

    def test_wrong_category_fund_year_and_repeated_query_fail(self):
        u = urls()[0]
        for bad in [u.replace('categoryId=66', 'categoryId=1525'), u + '&categoryId=66',
                    u.replace('searchStartYear=2026', 'searchStartYear=2020'),
                    u.replace(ma.HOST, 'evil.example')]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ma.parse_listing(listing(u), bad, config())
        with self.assertRaises(ValueError):
            ma.parse_listing(listing(u).replace('고용보험기금', '산재보험기금'), u, config())

    def test_missing_empty_marker_or_pager_and_error_page_fail(self):
        u = urls()[0]
        for h in ['<html><img src="return_notice.jpg"></html>',
                  listing(u, []).replace('게시물이 없습니다.', ''),
                  listing(u).replace('bbs_pagingWrap', 'unknown')]:
            with self.subTest(h=h[:50]), self.assertRaises(ValueError):
                ma.parse_listing(h, u, config())

    def test_detail_identity_and_missing_fund_or_image_fail(self):
        u = detail_url()
        for h in [detail(u).replace('value="2343655"', 'value="2343656"'),
                  detail(u, title=TITLE.replace('고용보험기금', '산재보험기금')),
                  detail(u, body='최종 선정 결과'), detail(u, body=BODY + '<img src="result.png">')]:
            with self.subTest(h=h[:40]), self.assertRaises(ValueError):
                ma.parse_detail(h, u, config())

    def test_tampered_source_receipts_do_not_validate(self):
        n = self.collect()['notices'][0]
        for k in ['body', 'title']:
            changed = copy.deepcopy(n); changed[k] += '변조'
            with self.assertRaises(ValueError):
                boards.validate_notice(changed, STAMP, config())
        changed = copy.deepcopy(n)
        changed['discovery_provenance']['listing']['html'] += '변조'
        with self.assertRaises(ValueError):
            boards.validate_notice(changed, STAMP, config())

    def test_ministry_recruitment_receives_only_pe_results(self):
        from services.lp.tests import test_lp_board_adapter_moel as fx
        c = {**boards.load_configs()['moel_eif'], 'pages': 1}
        def fetch(url, referer=None):
            return (fx.detail(files=False) if 'imchaeBbsView' in url else fx.listing()).encode()
        own = boards.collect({'moel_eif': c}, fetch_factory=lambda c: fetch, checked_at=STAMP, retry_failures=False)
        self.assertEqual(len(own['notices']), 1, own['holds'])
        n = self.collect()['notices'][0]
        # Publication validation uses active channels; pending status must be lifted
        # only after the read-only runner check. Simulate that gate in this test.
        active = {**boards.load_configs(), 'moel_eif_ocio': config(enabled=True)}
        with patch.object(boards, 'load_configs', return_value=active):
            programs, holds = publish_basic_notices({'programs': [], 'institution_notices': own['notices'] + [n]}, [], STAMP)
        self.assertEqual(len(programs), 1, holds)
        self.assertEqual(programs[0]['status'], '선정 완료')
        self.assertEqual([g['name'] for g in programs[0]['selected_gps']], ['에이치앤큐에쿼티파트너스', '제네시스프라이빗에쿼티'])


if __name__ == '__main__':
    unittest.main()
