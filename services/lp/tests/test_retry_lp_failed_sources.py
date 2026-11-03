import copy
import unittest
from unittest.mock import patch
from services.lp.src import retry_lp_failed_sources as r

STAMP='2026-11-03T07:00:00+00:00'

def direct(ids=()):
    return {'checked_at':STAMP,'notices':[{'url':'retained'}],'coverage':{},
            'holds':[{'institution_id':iid,'stage':'institution_listing','error':'first failure'} for iid in ids]}

def priorities(failed=True):
    return {'sources':{'ktcu':{'notices':['retained KTCU']},
                       'kexim':{'notices':[],'error':'first DNS failure','holds':['first hold']} if failed else {'notices':['healthy']}}}


class RetryFailedSourcesTests(unittest.TestCase):
    def test_global_two_issuer_budget_keeps_healthy_and_unselected_sources(self):
        d=direct(['nps','tp']);p=priorities();before=copy.deepcopy((d,p));configs={iid:{'institution_id':iid} for iid in ('nps','tp')}
        with patch.object(r.boards,'retry_failed_sources',side_effect=lambda report,*args,**kwargs:report) as native:
            after,pr,ids=r.retry_reports(d,p,configs=configs,checked_at=STAMP,collectors={'kexim':lambda:{'notices':['fresh'],'programs':[],'holds':[]}})
        self.assertEqual(ids,['kexim','nps']);self.assertEqual(set(native.call_args.args[1]),{'nps'})
        self.assertEqual(pr['sources']['ktcu'],p['sources']['ktcu'])
        self.assertNotIn('error',pr['sources']['kexim'])
        self.assertEqual(pr['sources']['kexim']['retry_history'][0]['previous_source'],p['sources']['kexim'])
        self.assertEqual((d,p),before)

    def test_healthy_priority_does_not_consume_native_budget_or_make_requests(self):
        d=direct(['nps','tp','cu']);p=priorities(False);configs={iid:{} for iid in ('nps','tp','cu')}
        with patch.object(r.boards,'retry_failed_sources',side_effect=lambda report,*args,**kwargs:report) as native,patch.object(r.priority,'collect') as priority:
            after,pr,ids=r.retry_reports(d,p,configs=configs,checked_at=STAMP)
        priority.assert_not_called();self.assertEqual(ids,['nps','tp'])
        self.assertEqual(set(native.call_args.args[1]),{'nps','tp'});self.assertEqual(pr,p)

    def test_repeated_failure_remains_an_error_and_keeps_first_attempt(self):
        def fail():raise TimeoutError('second failure')
        with patch.object(r.boards,'retry_failed_sources') as native:
            after,p,ids=r.retry_reports(direct(),priorities(),configs={},checked_at=STAMP,collectors={'kexim':fail})
        native.assert_not_called();self.assertIn('second failure',p['sources']['kexim']['error'])
        self.assertEqual(p['sources']['kexim']['retry_history'][0]['previous_source']['error'],'first DNS failure')
        self.assertEqual(ids,['kexim']);self.assertEqual(after['notices'],[{'url':'retained'}])

    def test_no_errors_means_no_retry(self):
        d,p=direct(),priorities(False)
        with patch.object(r.boards,'retry_failed_sources') as native,patch.object(r.priority,'collect') as priority:
            a,b,ids=r.retry_reports(d,p,configs={})
        native.assert_not_called();priority.assert_not_called();self.assertEqual(ids,[]);self.assertEqual((a,b),(d,p))

    def test_maintenance_is_not_retried_and_other_collectors_forbidden(self):
        d=direct(['nps']);d['holds'][0]['failure_kind']='official_maintenance'
        with patch.object(r.boards,'retry_failed_sources') as native:
            r.retry_reports(d,priorities(False),configs={'nps':{}})
        native.assert_not_called()
        with self.assertRaises(ValueError):r.retry_reports(direct(),priorities(),configs={},collectors={})


if __name__=='__main__':unittest.main()
