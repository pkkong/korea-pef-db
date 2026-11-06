import copy
import base64
import hashlib
import unittest
from urllib.parse import parse_qs, urlsplit

from services.lp.src import discover_lp_history as h
from services.lp.tests.test_kgrowth_listing import page


def raw(rows, extra=''):
    return page(rows, extra).encode('cp949')


def seed():
    collection = {'collection_coverage': {'date_discovery': {'complete': True,
        'window': {'start': '2025-11-07', 'end': '2026-11-06'},
        'receipts': [h.receipt(1, raw([('3', '801', '공고', '2026-01-01')]))]}}}
    index = {'kind': 'lp_document_index_v1', 'checked_at': '2026-11-06T12:00:00Z',
             'row_limit':10000,
             'database_index_complete': True, 'database_rows': 1, 'database_total_rows': 1,
             'records': [{'institution_id': 'kgrowth', 'url': h.LIST_URL.replace('notice.asp', 'notice_view.asp')+'&idx=801',
                          'title': '공고', 'date': '2026-01-01', 'body_present': True, 'source_sha256': 'a'*64,
                          'content_hash':'b'*64,'attachment_hashes':{},'source_id':'801','event_type':None}]}
    return collection, index


class HistoricalListingTests(unittest.TestCase):
    def run_pages(self, state, pages, **kwargs):
        calls = []
        def fetch(url):
            num = int(parse_qs(urlsplit(url).query).get('page', ['1'])[0])
            calls.append(num)
            return pages[num]
        result = h.run_batch(state, fetch, checked_at='2026-11-07T00:00:00Z', **kwargs)
        return result, calls

    def test_bootstrap_replays_retained_prefix_without_reusing_one_year_boundary(self):
        collection, index = seed(); before = copy.deepcopy(collection)
        state = h.bootstrap(collection, index)
        report = h.summary(state)
        self.assertEqual(report['window']['start'], '2023-01-01')
        self.assertFalse(report['listing_window_complete'])
        self.assertFalse(report['source_history_complete'])
        self.assertIsNone(report['pe_business_count'])
        self.assertEqual(report['retained_body_observed'], 1)
        self.assertEqual(report['next_page'], 2)
        self.assertEqual(collection, before)

    def test_two_batches_resume_without_restarting_and_recheck_overlap(self):
        c, i = seed(); state = h.bootstrap(c, i)
        pages = {1: c['collection_coverage']['date_discovery']['receipts'][0]['html'].encode('cp949'),
                 2: raw([('2','802','2027년 펀드 모집','2024-01-01')]),
                 3: raw([('1','803','과거','2022-12-31')])}
        first, calls = self.run_pages(state, pages, batch_pages=1)
        self.assertEqual(calls, [1, 2]); self.assertFalse(h.summary(first)['listing_window_complete'])
        second, calls = self.run_pages(first, pages, batch_pages=1)
        self.assertEqual(calls, [2, 3])
        report = h.summary(second)
        self.assertTrue(report['listing_window_complete'])
        self.assertEqual(report['boundary'], 'observed_older_page')
        self.assertEqual(report['listing_rows_by_year'], {'2026': 1, '2024': 1})
        self.assertEqual(report['pending_body_verification'], 1)
        complete, calls = self.run_pages(second, {})
        self.assertEqual(complete, second); self.assertEqual(calls, [])

    def test_pinned_old_row_cannot_end_history_and_dates_are_inclusive(self):
        c, i = seed(); state = h.bootstrap(c, i)
        pages = {1: c['collection_coverage']['date_discovery']['receipts'][0]['html'].encode('cp949'),
                 2: raw([('공지','900','상시안내','2020-01-01'),('2','802','공고','2023-01-01')]),
                 3: raw([], '<tr><td>등록된 게시물이 없습니다</td></tr>')}
        result, calls = self.run_pages(state, pages)
        report = h.summary(result)
        self.assertEqual(calls, [1, 2, 3]); self.assertTrue(report['listing_window_complete'])
        self.assertEqual({r['source_id'] for r in report['rows']}, {'801', '802'})

    def test_anchor_changes_hold_without_fetching_next_page(self):
        state = h.bootstrap(*seed()); before = copy.deepcopy(state)
        result, calls = self.run_pages(state, {1: raw([('4','899','새 공고','2026-11-06')])})
        self.assertEqual(calls, [1]); self.assertTrue(result['holds'])
        self.assertEqual(result['holds'][0]['page'],1)
        evidence=result['failed_response'];body=base64.b64decode(evidence['raw_base64'])
        self.assertEqual(evidence['page'],1)
        self.assertEqual(hashlib.sha256(body).hexdigest(),evidence['sha256'])
        self.assertEqual(result['receipts'], state['receipts'])
        self.assertEqual(state, before)
        with self.assertRaisesRegex(ValueError, 'saved historical failure'):
            h.run_batch(result, lambda u: self.fail('unexpected HTTP'))

    def test_pinned_identity_ignores_page_tracking_in_detail_links(self):
        c, i = seed()
        c['collection_coverage']['date_discovery']['receipts'][0] = h.receipt(1, raw([
            ('공지','900','안내','2020-01-01'),('3','801','공고','2026-01-01')]))
        state=h.bootstrap(c,i)
        next_page=raw([('공지','900','안내','2020-01-01'),('2','802','공고','2022-01-01')])
        next_page=next_page.replace(b'idx=900&',b'idx=900&page=2&')
        result,_=self.run_pages(state,{1:state['receipts'][0]['html'].encode('cp949'),2:next_page})
        self.assertTrue(h.summary(result)['listing_window_complete'])
        self.assertFalse(result['holds'])

    def test_repeated_malformed_and_out_of_order_pages_keep_valid_cursor(self):
        for bad in [raw([('3','801','공고','2026-01-01')]),
                    raw([('9','809','공고','2026-02-01')]), b'<html>partial']:
            state = h.bootstrap(*seed())
            result, _ = self.run_pages(state, {1: state['receipts'][0]['html'].encode('cp949'), 2: bad})
            self.assertEqual(len(result['receipts']), 1)
            self.assertEqual(result['holds'][0]['page'],2)
            self.assertEqual(base64.b64decode(result['failed_response']['raw_base64']),bad)
            self.assertTrue(result['holds']); self.assertFalse(h.summary(result)['listing_window_complete'])

    def test_transport_error_preserves_preceding_successful_pages(self):
        state = h.bootstrap(*seed())
        calls = []
        def fetch(url):
            n = int(parse_qs(urlsplit(url).query).get('page',['1'])[0]); calls.append(n)
            if n == 1: return state['receipts'][0]['html'].encode('cp949')
            if n == 2: return raw([('2','802','공고','2024-01-01')])
            raise TimeoutError('bounded transport exhausted')
        result = h.run_batch(state, fetch)
        self.assertEqual(calls,[1,2,3]); self.assertEqual(h.summary(result)['next_page'],3)
        self.assertEqual(result['batches'][-1]['new_pages'],1); self.assertTrue(result['holds'])

    def test_corrected_parser_replays_saved_duplicate_without_http_and_keeps_failure(self):
        state=h.bootstrap(*seed());failed=raw([('공지','900','안내','2024-01-01'),
            ('2','802','다른 공고','2024-02-01'),('1','900','안내','2024-01-01')])
        state['holds']=[{'page':2,'error':'ValueError: Conflicting Korea Growth listing metadata'}]
        state['failed_response']={'page':2,'url':h.page_url(2),'sha256':hashlib.sha256(failed).hexdigest(),
                                  'raw_base64':base64.b64encode(failed).decode()}
        repaired=h.recover_saved_duplicate(state)
        self.assertEqual(len(repaired['receipts']),2);self.assertEqual(repaired['holds'],[])
        self.assertEqual(repaired['recovered_failures'][0]['holds'],state['holds'])
        result,calls=self.run_pages(repaired,{2:failed,3:raw([('1','803','이전','2022-01-01')])},batch_pages=1)
        self.assertEqual(calls,[2,3]);self.assertTrue(h.summary(result)['listing_window_complete'])
        for change in ('sha','page','error'):
            bad=copy.deepcopy(state)
            if change=='sha':bad['failed_response']['sha256']='c'*64
            if change=='page':bad['failed_response']['page']=1
            if change=='error':bad['holds'][0]['error']='TimeoutError: timeout'
            with self.subTest(change=change),self.assertRaises(ValueError):
                h.run_batch(bad,lambda u:self.fail('unexpected HTTP'))

    def test_tampered_fingerprint_start_and_cursor_identity_fail_before_http(self):
        state = h.bootstrap(*seed())
        for field in ('hash', 'start', 'institution', 'url'):
            bad = copy.deepcopy(state)
            if field == 'hash': bad['receipts'][0]['sha256'] = 'b'*64
            if field == 'start': bad['window']['start'] = '2024-01-01'
            if field == 'institution': bad['institution_id'] = 'other'
            if field == 'url': bad['receipts'][0]['url'] += '&page=9'
            with self.subTest(field=field), self.assertRaises(ValueError):
                h.run_batch(bad, lambda u: self.fail('unexpected HTTP'))
        for count in (0,5,True):
            with self.assertRaises(ValueError): h.run_batch(state, lambda u:self.fail('HTTP'), batch_pages=count)

    def test_index_body_version_and_association_identity_are_not_assumed(self):
        c, i = seed()
        for change in ({'body_present': False}, {'source_sha256': None}, {'date':'2025-01-01'},
                       {'url':'https://www.kvca.or.kr/association-repost'}):
            index = copy.deepcopy(i); index['records'][0].update(change)
            self.assertEqual(h.summary(h.bootstrap(c,index))['retained_body_observed'],0)
        i['database_index_complete'] = False
        with self.assertRaises(ValueError): h.bootstrap(c,i)
        c,i=seed();i['records']=[]
        with self.assertRaises(ValueError): h.bootstrap(c,i)


if __name__ == '__main__':
    unittest.main()
