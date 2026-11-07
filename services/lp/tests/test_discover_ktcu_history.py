import copy
import unittest
from urllib.parse import parse_qs,urlsplit
from services.lp.src import discover_ktcu_history as h
from services.lp.tests.test_collect_ktcu_program import listing


def page(term,number,rows,last=1):
    return listing(rows,page=number,last=last,term=term).encode('utf-8')


class KtcuHistoryTests(unittest.TestCase):
    def batch(self,state,pages,**kwargs):
        calls=[]
        def fetch(url):
            q=parse_qs(urlsplit(url).query);key=(q['srchText'][0],int(q['curPage'][0]));calls.append(key)
            return pages[key]
        return h.run_batch(state,fetch,**kwargs),calls

    def test_four_searches_share_identity_and_fixed_start_not_title_year(self):
        state=h.initial('2026-11-06');before=copy.deepcopy(state)
        pages={(term,1):page(term,1,[('99','2027년 출자사업','2023-01-01','1')]) for term in h.SEARCH_TERMS}
        result,calls=self.batch(state,pages)
        report=h.replay(result)
        self.assertEqual(len(calls),4);self.assertTrue(report['listing_window_complete'])
        self.assertEqual(report['window']['start'],'2023-01-01');self.assertEqual(len(report['rows']),1)
        self.assertFalse(report['source_history_complete']);self.assertIsNone(report['pe_business_count'])
        self.assertEqual(state,before)
        completed,calls=self.batch(result,{})
        self.assertEqual(completed,result);self.assertFalse(calls)

    def test_resume_uses_one_overlap_then_only_remaining_queries(self):
        state=h.initial('2026-11-06')
        pages={('PEF',1):page('PEF',1,[('10','모집 공고','2026-01-01','3')],last=3),
               ('PEF',2):page('PEF',2,[('9','모집 공고','2024-01-01','2')],last=3),
               ('PEF',3):page('PEF',3,[('8','모집 공고','2022-12-31','1')],last=3)}
        pages.update({(term,1):page(term,1,[('10','모집 공고','2026-01-01','1')]) for term in h.SEARCH_TERMS[1:]})
        first,calls=self.batch(state,pages,max_requests=2)
        self.assertEqual(calls,[('PEF',1),('PEF',2)])
        second,calls=self.batch(first,pages)
        self.assertEqual(calls,[('PEF',2),('PEF',3),('블라인드',1),('운용사',1)])
        third,calls=self.batch(second,pages)
        self.assertEqual(calls,[('펀드',1)])
        self.assertTrue(h.replay(third)['listing_window_complete'])
        self.assertEqual(h.replay(third)['searches']['PEF']['boundary'],'observed_older_page')

    def test_malformed_or_changed_anchor_keeps_actual_failure_response(self):
        state=h.initial('2026-11-06')
        state['searches']['PEF']=[h.receipt('PEF',1,page('PEF',1,[('10','공고','2026-01-01','3')],last=3))]
        for bad in [b'<html>partial',page('PEF',1,[('10','변경공고','2026-01-01','3')],last=3)]:
            result,calls=self.batch(state,{('PEF',1):bad})
            self.assertEqual(calls,[('PEF',1)]);self.assertTrue(result['holds'])
            self.assertEqual(result['holds'][0]['page'],1)
            self.assertEqual(result['failed_response']['term'],'PEF')
            with self.assertRaises(ValueError):h.run_batch(result,lambda u:self.fail('unexpected source request'))

    def test_repeated_last_page_is_not_completion_and_pins_do_not_establish_age(self):
        state=h.initial('2026-11-06')
        p1=page('PEF',1,[('80','상시 안내','2020-01-01','공지'),('10','공고','2026-01-01','2')],last=2)
        state['searches']['PEF']=[h.receipt('PEF',1,p1)]
        p2=page('PEF',2,[('80','상시 안내','2020-01-01','공지'),('10','공고','2026-01-01','2')],last=2)
        result,_=self.batch(state,{('PEF',1):p1,('PEF',2):p2})
        self.assertTrue(result['holds']);self.assertFalse(h.replay(result)['listing_window_complete'])

    def test_state_and_request_bounds_fail_before_http(self):
        for field in ('start','query','digest'):
            state=h.initial('2026-11-06')
            state['searches']['PEF']=[h.receipt('PEF',1,page('PEF',1,[('10','공고','2026-01-01','2')],last=2))]
            if field=='start':state['window']['start']='2024-01-01'
            if field=='query':state['searches']['PEF'][0]['url']=h.url('운용사',1)
            if field=='digest':state['searches']['PEF'][0]['sha256']='f'*64
            with self.subTest(field=field),self.assertRaises(ValueError):h.run_batch(state,lambda u:self.fail('HTTP'))
        for size in (0,1,5,True):
            with self.assertRaises(ValueError):h.run_batch(h.initial('2026-11-06'),lambda u:self.fail('HTTP'),max_requests=size)


if __name__=='__main__':unittest.main()
