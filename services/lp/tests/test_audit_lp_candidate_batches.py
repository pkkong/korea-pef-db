"""Offline batching regressions: no source HTTP or persisted generated fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from services.lp.src import audit_lp_candidate_batches as batches
from services.lp.tests.test_audit_lp_candidate_sources import candidate, receipt, KEXIM_TITLE


def fixtures(count=23, response_size=None):
    candidates=[]; receipts=[]; responses={}
    for index in range(count):
        identifier=str(880000+index)
        title=KEXIM_TITLE+f' 합성후보 {index:03d}'
        item=candidate('kexim')
        item.update(id=f'fixture-{index:03d}',title=title,
                    official_url=item['official_url'].replace('991100',identifier),
                    metadata={'zero':0,'false':False,'nullable':None,'label':'원문 연결'})
        candidates.append(item)
        listing=receipt()
        listing['url']='https://www.koreaexim.go.kr/HPHKBI039M01?curPage='+str(index+1)
        listing['html']=listing['html'].replace('991100',identifier).replace(KEXIM_TITLE,title)
        listing['sha256']=hashlib.sha256(listing['html'].encode()).hexdigest()
        receipts.append(listing)
        raw=(f'<html><h1 class="detail-view-title">{title}</h1>'
             '<span title="작성일">2026.10.01</span><div class="detail-view-box">'
             '사업타당성조사 지원사업은 신청기업을 대상으로 합니다.'
             '<div class="detail-view-file"></div></div></html>').encode()
        if response_size:
            raw += b' '*(response_size-len(raw))
            assert len(raw)==response_size
        responses[item['official_url'].split('?')[0]]=raw
    return {'status':'ok','items':list(reversed(candidates))}, {'receipts':receipts,'institutions':[]},responses


def run(discovery, inventory, responses, calls, **kwargs):
    def fetch(url):
        calls.append(url)
        if url not in responses:raise AssertionError('Unplanned source request')
        return responses[url]
    return batches.run_batches(discovery,inventory,fetch_factory=lambda *_:fetch,
                               as_of='2026-11-04',**kwargs)


class InterruptedBatch(Exception):pass


class CandidateBatchTests(unittest.TestCase):
    def test_failed_source_does_not_stop_later_batches_or_look_complete(self):
        discovery,inventory,responses=fixtures(3);calls=[]
        first=sorted(responses)[0]
        def fetch(url):
            calls.append(url)
            if url==first:raise TimeoutError('official source unavailable')
            return responses[url]
        report=batches.run_batches(discovery,inventory,batch_size=1,
            fetch_factory=lambda *_:fetch,as_of='2026-11-04')
        self.assertEqual(len(calls),3)
        self.assertEqual(report['summary']['verified'],2)
        self.assertEqual(report['summary']['source_errors'],1)
        self.assertEqual(report['summary']['remaining_count'],0)
        self.assertEqual(report['sources'][0]['failure_kind'],'source_error')
        self.assertFalse(report['complete'])

    def test_atomic_file_checkpoint_keeps_the_last_completed_batch(self):
        discovery,inventory,responses=fixtures(3)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'nested'/'checkpoint.json'
            def checkpoint(report):
                batches.atomic_checkpoint(path,report)
                if report['summary']['attempted']==2:raise InterruptedBatch()
            with self.assertRaises(InterruptedBatch):
                run(discovery,inventory,responses,[],batch_size=2,checkpoint=checkpoint)
            saved=json.loads(path.read_text())
            self.assertEqual(saved['summary']['attempted'],2)
            self.assertEqual(saved['summary']['remaining_count'],1)
            self.assertFalse(path.with_name(path.name+'.tmp').exists())
            calls=[];report=run(discovery,inventory,responses,calls,resume=saved)
            self.assertEqual(len(calls),1)
            self.assertEqual(report['summary']['verified'],3)

    def interrupted(self):
        discovery,inventory,responses=fixtures();saved=[];calls=[]
        def checkpoint(report):
            saved.append(copy.deepcopy(report))
            if report.get('summary',{}).get('attempted',0)>=20:raise InterruptedBatch()
        with self.assertRaises(InterruptedBatch):
            run(discovery,inventory,responses,calls,checkpoint=checkpoint)
        self.assertEqual(len(calls),20)
        self.assertGreaterEqual(len(saved),2)
        return discovery,inventory,responses,saved[-1]

    def test_twenty_three_candidates_complete_in_two_batches_with_all_metadata(self):
        discovery,inventory,responses=fixtures();before=copy.deepcopy((discovery,inventory));calls=[];saved=[]
        report=run(discovery,inventory,responses,calls,checkpoint=lambda r:saved.append(copy.deepcopy(r)))
        self.assertEqual((discovery,inventory),before)
        self.assertEqual(len(calls),23);self.assertEqual(len(set(calls)),23)
        self.assertEqual(report['batch_version'],1);self.assertTrue(report['input_sha256'])
        self.assertEqual(len(report['batches']),2);self.assertEqual(report['summary']['batch_count'],2)
        for key in ('candidates','attempted','verified'):self.assertEqual(report['summary'][key],23)
        for key in ('unresolved','remaining_count','source_errors'):self.assertEqual(report['summary'][key],0)
        self.assertEqual(len(report['sources']),23)
        expected={x['id']:x for x in discovery['items']}
        self.assertEqual({x['discovery_id']:x['candidate'] for x in report['sources']},expected)
        self.assertTrue(all(x['status']=='official_source_verified' for x in report['sources']))
        self.assertEqual(len(saved[0]['sources']),23)  # cancellation before first batch still accounts for every clue
        self.assertEqual(saved[0]['summary']['attempted'],0)
        self.assertEqual(saved[1]['summary']['attempted'],20)
        self.assertEqual(saved[-1]['summary']['attempted'],23)
        # Incoming order cannot change deterministic batch membership/order.
        reversed_input=copy.deepcopy(discovery);reversed_input['items'].reverse()
        other=run(reversed_input,inventory,responses,[])
        self.assertEqual([x['discovery_id'] for x in report['sources']], [x['discovery_id'] for x in other['sources']])

    def test_duplicate_url_across_batches_keeps_both_clues_but_fetches_once(self):
        discovery,inventory,responses=fixtures();duplicate=copy.deepcopy(discovery['items'][-1]);duplicate['id']='zz-other-discovery-link'
        discovery['items'].append(duplicate);calls=[]
        report=run(discovery,inventory,responses,calls)
        self.assertEqual(len(calls),23)
        self.assertEqual(report['summary']['candidates'],24)
        self.assertEqual(report['summary']['verified'],24)
        links=[x for x in report['sources'] if x['candidate']['official_url']==duplicate['official_url']]
        self.assertEqual(len(links),2)
        self.assertEqual(len({x['discovery_id'] for x in links}),2)

    def test_resume_replays_raw_receipts_and_ignores_forged_old_verdicts(self):
        discovery,inventory,responses,resume=self.interrupted()
        for item in resume['sources']:
            item.update(status='official_source_verified',classification='forged_pe_approval',
                        official_notice={'title':'fabricated','body':'fabricated','date':'2099-01-01'})
        calls=[];report=run(discovery,inventory,responses,calls,resume=resume)
        self.assertEqual(len(calls),3)
        self.assertEqual(report['summary']['verified'],23)
        self.assertEqual(report['summary']['remaining_count'],0)
        self.assertTrue(all(x['classification']=='outside_policy' for x in report['sources']))
        self.assertTrue(all(x['official_notice']['date']=='2026-10-01' for x in report['sources']))
        self.assertTrue(all('fabricated' not in x['official_notice']['body'] for x in report['sources']))

    def test_changed_inputs_or_tampered_receipts_fail_before_any_network(self):
        discovery,inventory,responses,resume=self.interrupted()
        cases=[]
        changed=copy.deepcopy(discovery);changed['items'][0]['title']+=' changed'
        cases.append((changed,inventory,copy.deepcopy(resume)))
        changed_inventory=copy.deepcopy(inventory);changed_inventory['receipts'][0]['html']+=' changed'
        cases.append((discovery,changed_inventory,copy.deepcopy(resume)))
        tampered=copy.deepcopy(resume);tampered['input_sha256']='invalid';cases.append((discovery,inventory,tampered))
        tampered=copy.deepcopy(resume);tampered['receipts'][0]['sha256']='0'*64;cases.append((discovery,inventory,tampered))
        for d,i,r in cases:
            calls=[]
            with self.assertRaises(ValueError):run(d,i,responses,calls,resume=r)
            self.assertEqual(calls,[])

    def test_budget_is_execution_wide_not_reset_for_each_batch(self):
        discovery,inventory,responses=fixtures(13,response_size=2*1024*1024);calls=[]
        report=run(discovery,inventory,responses,calls,batch_size=5)
        self.assertEqual(len(calls),10)
        self.assertEqual(report['summary']['network_bytes'],20*1024*1024)
        self.assertGreater(report['summary']['source_errors'],0)
        self.assertGreater(report['summary']['unresolved'],0)
        self.assertEqual(len(report['sources']),13)
        self.assertFalse(report['complete'])

    def test_invalid_batch_size_fails_before_fetch(self):
        discovery,inventory,responses=fixtures(1)
        for limit in (0,-1,21,True,1.5,'20',None):
            calls=[]
            with self.subTest(limit=limit),self.assertRaises(ValueError):run(discovery,inventory,responses,calls,batch_size=limit)
            self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
