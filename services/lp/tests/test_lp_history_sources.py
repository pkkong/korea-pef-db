import copy
import json
import unittest
from services.lp.src import lp_history_sources as sources
from services.lp.src import discover_ktcu_history as ktcu
from services.lp.src import collect_lp_history_bodies as bodies
from services.lp.src.lp_history_body_queue import plan
from services.lp.tests.test_collect_ktcu_program import listing
from services.lp.tests import test_collect_lp_history_bodies as body_tests
from services.lp.tests.test_discover_lp_history import seed


def fixture():
    h=ktcu.initial('2026-11-07')
    rows=[('999','기존 출자사업','2026-01-01','5')]+[
        (str(i),'과거 운용사 선정 공고',f'2023-0{i-108}-01',str(i-108)) for i in range(112,108,-1)]
    for term in ktcu.SEARCH_TERMS:
        h['searches'][term]=[ktcu.receipt(term,1,listing(rows,term=term).encode('utf-8'))]
    _,index=seed();n=index['records'][0]
    n.update(institution_id='ktcu',source_id='999',url=sources.canonical_url('999','ktcu'),
             title='기존 출자사업',date='2026-01-01')
    return h,index


def detail(row):
    return (f'<html><body><div class="notice-tit"><h3>{row["title"]}</h3><span class="date">{row["date"]}</span></div>'
            '<div class="notice-cont">공식 출자사업 자료입니다. 이 테스트는 PE 범위나 선정 운용사를 추정하지 않습니다.</div>'
            '<a href="/comm/getFile?fileId=abc">공고문.pdf</a></body></html>').encode('utf-8')


class HistorySourceTests(unittest.TestCase):
    def test_typed_ktcu_metadata_queue_raw_replay_and_private_retention(self):
        h,index=fixture();enriched=sources.effective_history(h,index=index);q=plan(enriched)
        self.assertEqual(q['retained_body_in_scope'],1);self.assertEqual(q['pending_count'],4)
        rows={r['url']:r for r in q['rows']};calls=[]
        def fetch(url):calls.append(url);return detail(rows[url])
        report=bodies.collect(enriched,None,fetch)
        self.assertEqual(len(calls),4);self.assertTrue(all('ktcu.or.kr' in u for u in calls))
        self.assertTrue(all(n['institution_id']=='ktcu' for n in report['documents']))
        self.assertEqual(bodies.validate_report(h,report)['pending_count'],0)
        self.assertEqual(len(report['retained_records']),1)
        proof=bodies.persist(body_tests.Connection(),h,report,wrap_json=lambda x:x)
        self.assertEqual(proof['new_document_versions'],4);self.assertEqual(proof['before'],proof['after'])
        self.assertFalse(proof['published']);self.assertFalse(proof['source_history_complete'])
        resumed=bodies.collect(h,report,lambda u:self.fail('known body must not be refetched'))
        self.assertEqual(resumed['batches'][-1]['detail_requests'],0)

    def test_metadata_cannot_count_an_association_or_missing_body_as_native_evidence(self):
        h,index=fixture()
        for change in ({'url':'https://www.kofia.or.kr/repost'}, {'body_present':False}):
            modified=copy.deepcopy(index);modified['records'][0].update(change)
            self.assertEqual(plan(sources.effective_history(h,index=modified))['retained_body_observed'],0)
        index['database_index_complete']=False
        with self.assertRaises(ValueError):sources.effective_history(h,index=index)
        with self.assertRaises(ValueError):sources.effective_history(h)

    def test_legacy_kgrowth_reports_keep_their_digest_and_identity(self):
        helper=body_tests.HistoricalBodyTests();h,fetch,_=helper.prepare();r=bodies.collect(h,None,fetch)
        r.pop('institution_id')
        self.assertEqual(bodies.validate_report(h,r)['pending_count'],0)
        k,index=fixture();k=sources.effective_history(k,index=index)
        with self.assertRaises(ValueError):bodies.validate_report(k,r)
        altered=copy.deepcopy(h);altered['institution_id']='ktcu'
        with self.assertRaises(ValueError):sources.institution(altered)


if __name__=='__main__':unittest.main()
