import unittest
import ssl
import subprocess
from http.client import IncompleteRead
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from unittest.mock import patch
from services.lp.src import collect_shared_lp_notices as shared
from services.lp.src.collect_shared_lp_notices import (
    collect, parse_listing, parse_detail, match_issuer, classify_scope, valid_date,
)

KVCA='https://www.kvca.or.kr/Program/invest/list.html?a_cd=8&page=1'
KOFIA='https://www.kofia.or.kr/brd/m_212/list.do'

class SharedCollectionTests(unittest.TestCase):
    def test_transport_retries_temporary_timeout_and_server_error(self):
        errors = [TimeoutError('slow'), URLError(TimeoutError('slow')),
                  HTTPError(KOFIA, 503, 'busy', {}, None)]
        for error in errors:
            with self.subTest(error=type(error).__name__), \
                 patch.object(shared, '_fetch_bytes_urllib', side_effect=[error, b'complete']) as fetch, \
                 patch.object(shared.time, 'sleep') as sleep:
                self.assertEqual(shared.fetch_bytes(KOFIA), b'complete')
                self.assertEqual(fetch.call_count, 2)
                sleep.assert_called_once_with(1)

    def test_truncated_response_then_curl_timeout_retries_complete_read(self):
        with patch.object(shared, '_fetch_bytes_urllib', side_effect=IncompleteRead(b'partial', 10)), \
             patch.object(shared.subprocess, 'run', side_effect=[
                 subprocess.CalledProcessError(28, ['curl'], output=b'partial'),
                 SimpleNamespace(stdout=b'<html>complete</html>')]) as curl, \
             patch.object(shared.time, 'sleep'):
            self.assertEqual(shared.fetch_bytes(KOFIA), b'<html>complete</html>')
            self.assertEqual(curl.call_count, 2)
            command = curl.call_args.args[0]
            self.assertIn('--http1.0', command)
            self.assertEqual(command[command.index('--user-agent') + 1],
                             'Mozilla/5.0 (LP public notice collector)')
            self.assertIn('Connection: close', command)
            self.assertNotIn('--insecure', command)
            self.assertNotIn('--location', command)

    def test_retries_stop_after_three_attempts_and_keep_failure_visible(self):
        with patch.object(shared, '_fetch_bytes_urllib', side_effect=TimeoutError('offline')) as fetch, \
             patch.object(shared.time, 'sleep') as sleep:
            with self.assertRaises(TimeoutError):
                shared.fetch_bytes(KOFIA)
            self.assertEqual(fetch.call_count, 3)
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])

    def test_certificate_refusal_and_validation_errors_are_not_retried(self):
        errors = [URLError(ssl.SSLCertVerificationError('untrusted')),
                  HTTPError(KOFIA, 404, 'missing', {}, None),
                  ValueError('cross-host redirect'), ValueError('oversized response'),
                  subprocess.CalledProcessError(60, ['curl'])]
        for error in errors:
            with self.subTest(error=str(error)), \
                 patch.object(shared, '_fetch_bytes_urllib', side_effect=error) as fetch, \
                 patch.object(shared.time, 'sleep') as sleep:
                with self.assertRaises(type(error)):
                    shared.fetch_bytes(KOFIA)
                self.assertEqual(fetch.call_count, 1)
                sleep.assert_not_called()

    def test_collection_shares_four_extra_attempts_and_still_writes_holds(self):
        # Three failing boards get seven calls, not nine; each new run resets.
        for _ in range(2):
            with patch.object(shared, '_fetch_bytes_urllib', side_effect=TimeoutError('offline')) as fetch, \
                 patch.object(shared.time, 'sleep'):
                result = collect(pages=1, aliases={})
                self.assertEqual(fetch.call_count, 7)
                self.assertEqual(len(result['holds']), 3)
                self.assertFalse(result['notices'])
                self.assertTrue(all(h['stage'] == 'listing' for h in result['holds']))

    def test_http_200_truncation_uses_complete_http10_response(self):
        partial = b'<html><table><tr><td><a href="view.do?seq=777">partial row</a></td></tr>'
        complete = b'<html><table><tr><td><a href="view.do?seq=888">verified row</a></td></tr></table></html>'
        with patch.object(shared, '_fetch_bytes_urllib', return_value=partial) as urllib, \
             patch.object(shared.subprocess, 'run', return_value=SimpleNamespace(stdout=complete)) as curl:
            result = collect(pages=1, aliases={}, channels={'kofia_212': KOFIA})
        self.assertEqual(urllib.call_count, 1)
        self.assertEqual(curl.call_count, 1)
        self.assertFalse(result['holds'])
        self.assertEqual([r['source_id'] for r in result['unmatched_notices']], ['kofia_212:888'])
        self.assertEqual(result['coverage']['channel_pages']['kofia_212']['pages'][0]['count'], 1)

    def test_incomplete_http10_response_retries_with_existing_budget(self):
        partial = b'<html>incomplete'
        complete = b'<html><table><tr><td><a href="view.do?seq=919">new row</a></td></tr></table></html>'
        with patch.object(shared, '_fetch_bytes_urllib', side_effect=[partial, complete]) as urllib, \
             patch.object(shared.subprocess, 'run', return_value=SimpleNamespace(stdout=partial)) as curl, \
             patch.object(shared.time, 'sleep') as sleep:
            result = collect(pages=1, aliases={}, channels={'kofia_212': KOFIA})
        self.assertFalse(result['holds'])
        self.assertEqual(urllib.call_count, 2)
        self.assertEqual(curl.call_count, 1)
        sleep.assert_called_once_with(1)
        self.assertEqual(result['unmatched_notices'][0]['source_id'], 'kofia_212:919')

    def test_permanent_200_truncation_holds_without_importing_partial_rows(self):
        partial = b'<html><table><tr><td><a href="view.do?seq=777">partial</a></td></tr>'
        with patch.object(shared, '_fetch_bytes_urllib', return_value=partial) as urllib, \
             patch.object(shared.subprocess, 'run', return_value=SimpleNamespace(stdout=partial)) as curl, \
             patch.object(shared.time, 'sleep'):
            result = collect(pages=1, aliases={}, channels={'kofia_212': KOFIA, 'kofia_17': shared.CHANNELS['kofia_17'], 'kvca': KVCA})
        # Same run-wide four-extra-attempt budget as transport failures, with at
        # most one urllib plus one HTTP/1.0 recovery request per attempt.
        self.assertEqual(urllib.call_count, 7)
        self.assertEqual(curl.call_count, 7)
        self.assertEqual(len(result['holds']), 3)
        self.assertTrue(all(h['error'] == 'incomplete listing HTML' for h in result['holds']))
        self.assertFalse(result['notices'])
        self.assertFalse(result['unmatched_notices'])
        self.assertEqual(result['update_policy'], 'upsert_successes_preserve_existing_on_holds')
        self.assertTrue(all(c['pages'][0]['status'] == 'error' for c in result['coverage']['channel_pages'].values()))

    def test_complete_empty_board_is_valid_and_does_not_follow_pagination(self):
        empty = '<html><table><thead><tr><th>번호</th><th>제목</th><th>작성일</th></tr></thead><tbody><tr><td colspan="5">등록된 게시물이 없습니다.</td></tr></tbody></table><a href="?page=2">2</a></html>'
        calls = []
        def fetch(url, referer=None):
            calls.append(url)
            return empty.encode()
        result = collect(fetch=fetch, pages=3, aliases={}, channels={'kofia_212': KOFIA})
        self.assertEqual(calls, [KOFIA])
        self.assertFalse(result['holds'])
        self.assertEqual(result['coverage']['channel_pages']['kofia_212']['pages'][0], {'page': 1, 'url': KOFIA, 'status': 'ok', 'count': 0})

    def test_complete_error_page_or_unlabelled_empty_message_is_not_success(self):
        for html in ('<html>Access denied</html>', '<html>등록된 게시물이 없습니다.</html>',
                     '<html><table><tr><td colspan="5">등록된 게시물이 없습니다.</td></tr></table></html>'):
            with self.subTest(html=html):
                result = collect(fetch=lambda url: html.encode(), pages=1, aliases={}, channels={'kofia_212': KOFIA})
                self.assertEqual(len(result['holds']), 1)
                self.assertEqual(result['holds'][0]['error'], 'listing parser found no notice rows')

    def test_novel_listing_ids_dates_and_pagination(self):
        html='''<html><table><tr><td>1</td><td><a href="listbody.html?po_no=99981">미래에셋증권</a></td><td><a href="listbody.html?po_no=99981">2026년 고용보험기금 PE 선정</a></td><td>2026-08-07</td><td>2026-08-20</td></tr></table><a href="list.html?a_cd=8&amp;page=2">2</a></html>'''
        rows,pages=parse_listing(html,KVCA,'kvca')
        self.assertEqual(rows[0]['source_id'],'kvca:99981')
        self.assertEqual(rows[0]['date'],'2026-08-07')
        self.assertEqual(rows[0]['issuer_name'],'미래에셋증권')
        self.assertEqual(pages[2],'https://www.kvca.or.kr/Program/invest/list.html?a_cd=8&page=2')

    def test_kofia_unknown_date_not_title_year_or_deadline(self):
        html='<table><tr><td>7</td><td><span><a href="./view.do?seq=98989"></span>[신협중앙회] 2026년 국내 PE 블라인드 공고</a></td><td>날짜 미기재</td></tr></table>'
        rows,_=parse_listing(html,KOFIA,'kofia_212')
        self.assertIsNone(rows[0]['date'])
        self.assertIsNone(valid_date('2026-02-30'))
        self.assertEqual(rows[0]['source_id'],'kofia_212:98989')

    def test_ocio_relationship_and_author_priority(self):
        aliases={'kgrowth':['한국성장금융'],'ibk':['IBK기업은행'],'moel_eif':['고용보험기금'],'moel_iaci':['산재보험기금']}
        self.assertEqual(match_issuer('고용보험기금 선정','미래에셋증권','',aliases),('moel_eif','fund_explicit'))
        self.assertEqual(match_issuer('산재보험기금 선정','삼성자산운용','',aliases),('moel_iaci','fund_explicit'))
        self.assertEqual(match_issuer('IBK기업은행 혁신펀드','한국성장금융','',aliases),('kgrowth','issuer_field'))
        self.assertEqual(match_issuer('운용사 모집','미래에셋증권','',aliases),(None,'unmatched'))

    def test_source_scope_requires_explicit_blind_and_pe(self):
        self.assertEqual(classify_scope('국내 사모펀드 공고',''),'needs_confirmation')
        self.assertEqual(classify_scope('국내 PEF 공고',''),'needs_confirmation')
        self.assertEqual(classify_scope('국내 PE·VC 블라인드 선정',''),'mixed_pe_blind')
        self.assertEqual(classify_scope('국내 VC 선정',''),'vc_only')
        self.assertEqual(classify_scope('해외 PE 블라인드 선정',''),'outside')
        self.assertEqual(classify_scope('국내 PE 블라인드 선정',''),'pe_blind')

    def test_prior_fund_blind_requirement_is_not_offered_scope(self):
        self.assertEqual(classify_scope('국내 PEF 모집', '기존 블라인드펀드 소진율 60% 이상인 운용사'), 'needs_confirmation')
        self.assertEqual(classify_scope('국내 PEF 모집', '최근 블라인드펀드 GP 모집 이력 보유자만 지원 가능'), 'needs_confirmation')

    def test_reversed_kvca_dates_use_labelled_registration_not_fake_original_date(self):
        html='<table><tr><th>공고명</th><td>국내 PE 블라인드</td></tr><tr><th>공고일</th><td>2026-08-31</td><th>신청기한</th><td>2026-08-14</td></tr><tr><th>등록일</th><td>2026-08-05</td></tr><tr><th>공고 내용</th><td>국내 PE 블라인드 모집</td></tr></table>'
        d=parse_detail(html,KVCA,'kvca')
        self.assertEqual(d['date'],'2026-08-05')
        self.assertEqual(d['claimed_official_date'],'2026-08-31')
        self.assertTrue(d['date_conflict'])
        self.assertEqual(d['date_basis'],'association_registered_at')

    def test_foreign_notice_link_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_listing('<table><tr><td><a href="https://evil.example/view.do?seq=4">공고</a></td></tr></table>',KOFIA,'kofia_212')

    def test_detail_excludes_navigation_and_retains_links(self):
        html='''<nav>국내 PE VC 블라인드</nav><table><tr><th>제목</th><td>[신협중앙회] 공고</td></tr><tr><th>작성일</th><td>2026-10-01 13:00</td></tr><tr><th>첨부1</th><td><a href="./down.do?seq=98989&amp;file_seq=1">공고문.hwpx</a></td></tr><tr><th>내용</th></tr><tr><td><div id="write">실제 <span>P</span><span>E</span> 내용 <a href="https://cu.co.kr/original">원공고</a></div></td></tr></table>'''
        detail=parse_detail(html,KOFIA,'kofia_212')
        self.assertNotIn('블라인드',detail['body'])
        self.assertIn('PE 내용',detail['body'])
        self.assertEqual(detail['date'],'2026-10-01')
        self.assertEqual(detail['attachments'][0]['url'],'https://www.kofia.or.kr/brd/m_212/down.do?seq=98989&file_seq=1')
        self.assertEqual(detail['original_links'][0]['url'],'https://cu.co.kr/original')

    def test_attachment_failure_preserves_notice_and_complete_text_is_not_cut(self):
        listing='<html><table><tr><td>1</td><td><a href="view.do?seq=909">[신협중앙회] 국내 PE 블라인드</a></td><td>2026-10-01</td></tr></table></html>'
        detail='<html><table><tr><th>제목</th><td>[신협중앙회] 국내 PE 블라인드</td></tr><tr><th>첨부1</th><td><a href="down.do?seq=909">공고문.pdf</a></td></tr><tr><td><div id="write">국내 PE 블라인드 모집</div></td></tr></table></html>'
        def fetch(url,referer=None):
            if url==KOFIA:return listing.encode()
            if 'view.do' in url:return detail.encode()
            return b'%PDF attachment'
        options=dict(fetch=fetch,aliases={'cu':['신협중앙회']},channels={'kofia_212':KOFIA})
        text='공고 원문 '+('x'*100001)+' 마지막 조건'
        with patch('services.lp.src.lp_attachment_text.extract_attachment',return_value={'text':text}):
            result=collect(**options)
        self.assertEqual(next(iter(result['notices'][0]['attachment_texts'].values())),text)
        with patch('services.lp.src.lp_attachment_text.extract_attachment',side_effect=ValueError('unsupported')):
            result=collect(**options)
        self.assertEqual(len(result['notices']),1)
        self.assertEqual(result['holds'][0]['stage'],'attachment')

    def test_failure_holds_do_not_discard_successful_notices(self):
        listing='''<html><table><tr><td>1</td><td><a href="view.do?seq=909">[신협중앙회] 국내 PE 블라인드</a></td><td>2026-10-01</td></tr><tr><td>2</td><td><a href="view.do?seq=910">[신협중앙회] 국내 PE 블라인드 추가공고</a></td><td>2026-10-02</td></tr></table></html>'''
        detail='''<html><table><tr><th>제목</th><td>[신협중앙회] 국내 PE 블라인드</td></tr><tr><th>작성일</th><td>2026-10-01</td></tr><tr><td><div id="write">국내 PE 블라인드 공개모집</div></td></tr></table></html>'''
        def fetch(url,referer=None):
            if url==KOFIA:return listing.encode()
            if 'seq=909' in url:return detail.encode()
            raise TimeoutError('unavailable')
        result=collect(fetch=fetch,aliases={'cu':['신협중앙회']},channels={'kofia_212':KOFIA,'kofia_17':'https://www.kofia.or.kr/brd/m_17/list.do'})
        self.assertEqual(len(result['notices']),1)
        self.assertEqual(result['notices'][0]['source_id'],'kofia_212:909')
        self.assertEqual({h['stage'] for h in result['holds']},{'listing','detail'})
        self.assertEqual(result['update_policy'],'upsert_successes_preserve_existing_on_holds')

    def test_view_counter_changes_do_not_change_source_fingerprint_and_missing_date_is_held(self):
        listing='<html><table><tr><td>1</td><td><a href="view.do?seq=909">[신협중앙회] 국내 PE 블라인드</a></td><td>2026-10-01</td></tr></table></html>'
        def response(counter,has_date=True):
            stamp='<tr><th>작성일</th><td>2026-10-01</td></tr>' if has_date else ''
            return '<html><table><tr><th>제목</th><td>[신협중앙회] 국내 PE 블라인드</td></tr>'+stamp+'<tr><th>조회수</th><td>'+str(counter)+'</td></tr><tr><td><div id="write">국내 PE 블라인드 공개모집</div></td></tr></table></html>'
        def run(counter,has_date=True):
            def fetch(url,referer=None):
                if url==KOFIA:return listing.replace('2026-10-01','날짜 없음').encode() if not has_date else listing.encode()
                return response(counter,has_date).encode()
            return collect(fetch=fetch,aliases={'cu':['신협중앙회']},channels={'kofia_212':KOFIA})
        self.assertEqual(run(1)['notices'][0]['sha256'],run(99)['notices'][0]['sha256'])
        missing=run(1,False)
        self.assertFalse(missing['notices'])
        self.assertEqual(missing['holds'][0]['stage'],'detail')

if __name__=='__main__':unittest.main()
