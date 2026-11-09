import base64
import copy
import unittest
from unittest.mock import MagicMock, patch
from services.lp.src import capture_koreapost_preferred as c
from services.lp.tests.test_koreapost_coinvestment_preferred import evidence


def fixture():
    a,b=evidence()
    source={'notices':[a,b]}
    p={'id':'existing-pe','institution_id':'koreapost','asset_scope':'PE',
       'status':'우선협상대상자','selected_gps':[],
       'events':[{'url':a['url'],'type':'모집 공고'},{'url':b['url'],'type':'우선협상대상자'}]}
    return source,p


def retained(source,p):
    return {'kind':c.KIND,'stage':'lookup','success':True,'target':c.plan(source,[p],'old-public'),
            'versions_examined':2,'official_http_requests':0,'database_writes':0,'published':False,
            'pe_approval':False,'selected_gp_approval':False}


class CapturePreferredTests(unittest.TestCase):
    def test_proven_existing_pair_all_raw_reused_without_http_or_new_approval(self):
        source,p=fixture();before=copy.deepcopy(source)
        r=c.capture(retained(source,p),fetch=lambda *_:self.fail('No HTTP needed'))
        self.assertTrue(r['success']);self.assertEqual(r['official_http_requests'],0)
        self.assertEqual(r['transport_attempts'],0)
        upgraded,receipt=c.reuse(source,r)
        self.assertEqual(receipt['preferred_count'],1);self.assertEqual(receipt['selected_gp_additions'],0)
        self.assertEqual(receipt['baseline_public_run'],'old-public');self.assertEqual(source,before)
        self.assertEqual(upgraded,source)

    def test_missing_raw_needs_exactly_two_bodies_and_first_file(self):
        source,p=fixture();raw={n['url']:base64.b64decode(n['detail_proof']['raw_base64']) for n in source['notices']}
        a=source['notices'][0];url=a['attachments'][0]
        raw[url]=base64.b64decode(a['attachment_proofs'][url]['raw_base64'])
        for n in source['notices']:n.pop('detail_proof')
        a.pop('attachment_proofs');calls=[]
        def fetch(url,limit):calls.append(url);return raw[url]
        r=c.capture(retained(source,p),fetch=fetch)
        self.assertTrue(r['success']);self.assertEqual(calls,[n['url'] for n in source['notices']]+[url])
        self.assertEqual((r['detail_requests'],r['attachment_requests'],r['official_http_requests']),(2,1,3))
        self.assertEqual(r['transport_attempts'],0)
        self.assertTrue(c.reuse(source,r)[0]['notices'][0]['attachment_proofs'])

    def test_wrong_origin_or_cached_tamper_is_held_before_any_request(self):
        source,p=fixture();good=retained(source,p)
        for change in ('origin','raw','file'):
            r=copy.deepcopy(good);a=r['target']['notices'][0]
            if change=='origin':a['url']='https://other.example/board.es'
            elif change=='raw':a['detail_proof']['raw_base64']=base64.b64encode(b'changed').decode()
            else:a['attachment_proofs'][a['attachments'][0]]['sha256']='f'*64
            with self.subTest(change=change):
                out=c.capture(r,fetch=lambda *_:self.fail('Prevalidation must stop HTTP'))
                self.assertFalse(out['success']);self.assertEqual(out['official_http_requests'],0)

    def test_changed_body_or_http_error_keeps_raw_failure_and_never_reads_file(self):
        source,p=fixture();r=retained(source,p);n=r['target']['notices'][0]
        raw=base64.b64decode(n.pop('detail_proof')['raw_base64'])
        for value in (raw.replace(b'2026',b'2025'),{'raw':b'public failure','status':403}):
            with self.subTest(value_type=type(value).__name__):
                out=c.capture(r,fetch=lambda *_:value)
                self.assertFalse(out['success']);self.assertEqual(out['detail_requests'],1)
                self.assertEqual(out['attachment_requests'],0);self.assertEqual(len(out['responses']),1)
                self.assertIn('raw_base64',out['responses'][0])
                if isinstance(value,dict):self.assertEqual(out['responses'][0]['http_status'],403)

    def test_no_user_chosen_id_or_ambiguous_public_business(self):
        source,p=fixture()
        for programs in ([],[p,p]):
            with self.assertRaises(ValueError):c.plan(source,programs,'old')
        p['preferred_gps']=['already-known']
        with self.assertRaises(ValueError):c.plan(source,[p],'old')
        source,p=fixture();source['notices']*=2
        with self.assertRaises(ValueError):c.plan(source,[p],'old')

    def test_read_only_lookup_and_retained_protection_never_fallback_to_http(self):
        source,p=fixture();conn=MagicMock()
        def execute(query,params=None):
            cur=MagicMock()
            if "data->'programs'" in query:cur.fetchone.return_value=('old-public',[p])
            elif 'SELECT document' in query:cur.fetchall.return_value=[(n,) for n in source['notices']]
            return cur
        conn.execute.side_effect=execute
        r=c.lookup(conn,source);self.assertTrue(r['success']);self.assertEqual(r['versions_examined'],2)
        self.assertIn('READ ONLY',conn.execute.call_args_list[0].args[0])
        self.assertFalse(any(word in ' '.join(x.args[0] for x in conn.execute.call_args_list)
                             for word in ('INSERT','UPDATE','DELETE')))
        conn.commit.assert_not_called()
        source['notices'][0]['owner_closed']=True
        with self.assertRaises(ValueError):c.lookup(conn,source)

    def test_priority_reload_keeps_raw_failure_signal_and_other_public_program(self):
        from services.lp.src import collect_koreapost_program as collector
        source,p=fixture();source['notices'][0]['attachment_proofs'][source['notices'][0]['attachments'][0]]['sha256']='f'*64
        with patch.object(collector,'_reviewed_project',return_value=([p],[])):
            programs,holds=collector.project(source['notices'],'2026-11-10T03:00:00+09:00')
        self.assertEqual(programs,[p]);self.assertEqual(len(holds),1)
        self.assertEqual(holds[0]['stage'],'institution_attachment_text')
        for n in source['notices']:
            n.pop('detail_proof');n.pop('attachment_proofs',None)
        with patch.object(collector,'_reviewed_project',return_value=([p],[])):
            self.assertEqual(collector.project(source['notices'],'2026-11-10T03:00:00+09:00'),([p],[]))

    def test_success_counts_and_approval_flags_cannot_be_forged(self):
        source,p=fixture();result=c.capture(retained(source,p),fetch=lambda *_:self.fail('No HTTP'))
        for key,value in [('detail_requests',3),('official_http_requests',1),('pe_approval',True),('selected_gp_approval',True)]:
            bad=copy.deepcopy(result);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):c.reuse(source,bad)

    def test_reuse_cannot_change_existing_conditions_or_notice_fields(self):
        source,p=fixture();result=c.capture(retained(source,p),fetch=lambda *_:self.fail('No HTTP'))
        result['target']['notices'][0]['attachment_texts']={'changed':'changed'}
        with self.assertRaises(ValueError):c.reuse(source,result)


if __name__=='__main__':unittest.main()
