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


class RetainedEvidenceTests(unittest.TestCase):
    def pair(self):
        old={'checked_at':STAMP,'notices':[{'institution_id':'kdb','url':'https://www.kdb.co.kr/retained','body':'unchanged'}],
             'coverage':{'geps':{'detail_count':0},'kdb':{'detail_count':1}},
             'holds':[{'institution_id':'geps','stage':'institution_listing','error':'DNS unavailable'}]}
        new=copy.deepcopy(old)
        new.update(initial_checked_at=STAMP,checked_at='2026-11-03T08:00:00+00:00',holds=[])
        new['notices'].append({'institution_id':'geps','url':'https://www.geps.or.kr/recovered'})
        new['coverage']['geps']={'detail_count':1}
        new['retry_history']=[{'institution_id':'geps','previous_checked_at':STAMP,
                              'previous_holds':copy.deepcopy(old['holds']),
                              'previous_coverage':copy.deepcopy(old['coverage']['geps'])}]
        return old,new

    def test_reuses_recovered_receipts_without_http_and_without_mutating_inputs(self):
        old,new=self.pair();before=copy.deepcopy(new)
        with patch.object(r.boards,'Session') as session:
            result=r.reuse_institution_evidence(old,new)
            session.assert_not_called()
        self.assertEqual(result,new);result['coverage']['geps']['detail_count']=999
        self.assertEqual(new,before)

    def test_wrong_source_scope_and_modified_healthy_evidence_rejected(self):
        for field in ('stamp','scope','notice','coverage','hold','new_issuer'):
            old,new=self.pair()
            if field=='stamp':new['initial_checked_at']='2026-11-02T07:00:00+00:00'
            elif field=='scope':new['coverage']['other']={}
            elif field=='notice':new['notices'][0]['body']='changed'
            elif field=='coverage':new['coverage']['kdb']['detail_count']=2
            elif field=='hold':new['holds'].append({'institution_id':'kdb','stage':'institution_detail'})
            else:new['notices'].append({'institution_id':'unknown','url':'https://unknown.example/x'})
            with self.subTest(field=field),self.assertRaises(ValueError):r.reuse_institution_evidence(old,new)

    def test_failed_or_lost_recovery_history_cannot_be_reused(self):
        for field in ('history','original_error','still_failed','removed_url','not_failed'):
            old,new=self.pair()
            if field=='history':new['retry_history']=[]
            elif field=='original_error':new['retry_history'][0]['previous_holds']=[]
            elif field=='still_failed':new['holds']=copy.deepcopy(old['holds'])
            elif field=='removed_url':new['notices']=new['notices'][1:]
            else:old['holds']=[]
            with self.subTest(field=field),self.assertRaises(ValueError):r.reuse_institution_evidence(old,new)


class RetryFailedSourcesTests(unittest.TestCase):
    def test_one_association_retry_preserves_other_streams_and_verified_originals(self):
        report={'checked_at':STAMP,'notices':[{'source_id':'kofia_17:1','sha256':'same','original_notices':['verified original']},
                    {'source_id':'kvca:9','sha256':'retained'}],
                'holds':[{'stage':'listing','source_channel':'kofia_17','error':'truncated'},
                         {'stage':'listing','source_channel':'kofia_212','error':'other failure'}],
                'coverage':{'channel_pages':{'kvca':{'healthy':True},'kofia_17':{'old_error':True}}}}
        fresh={'notices':[{'source_id':'kofia_17:1','sha256':'same','original_notices':[]}],
               'holds':[],'coverage':{'channel_pages':{'kofia_17':{'pages':['fresh']}}}}
        before=copy.deepcopy(report)
        with patch.object(r.shared,'collect',return_value=fresh) as collect,patch.object(r,'enrich',side_effect=lambda value,**kw:value):
            result,channels=r.retry_association(report,checked_at=STAMP)
        self.assertEqual(channels,['kofia_17'])
        self.assertEqual(collect.call_args.kwargs['channels'],{'kofia_17':r.shared.CHANNELS['kofia_17']})
        self.assertEqual(collect.call_args.kwargs['pages'],3)
        self.assertEqual(result['notices'][0]['original_notices'],['verified original'])
        self.assertEqual(result['notices'][1],report['notices'][1])
        self.assertEqual(result['holds'],[report['holds'][1]])
        self.assertEqual(result['retry_history'][0]['previous_holds'],[report['holds'][0]])
        self.assertEqual(result['coverage']['channel_pages']['kvca'],{'healthy':True})
        self.assertEqual(report,before)

    def test_repeated_association_failure_remains_visible(self):
        report={'notices':[{'source_id':'kofia_17:1'}],'holds':[{'stage':'detail','source_id':'kofia_17:9','error':'first'}]}
        fresh={'notices':[],'holds':[{'stage':'detail','source_id':'kofia_17:9','error':'again'}],
               'coverage':{'channel_pages':{'kofia_17':{}}}}
        with patch.object(r.shared,'collect',return_value=fresh),patch.object(r,'enrich',side_effect=lambda value,**kw:value):
            result,channels=r.retry_association(report,checked_at=STAMP)
        self.assertEqual(result['holds'][0]['error'],'again');self.assertEqual(result['notices'],report['notices'])
        self.assertEqual(result['retry_history'][0]['previous_holds'][0]['error'],'first')

    def test_healthy_or_unknown_association_is_not_requested(self):
        for report in ({'holds':[]},{'holds':[{'stage':'listing','source_channel':'foreign'}]}):
            with patch.object(r.shared,'collect') as collect:
                result,channels=r.retry_association(report)
            collect.assert_not_called();self.assertEqual(channels,[]);self.assertEqual(result,report)

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
