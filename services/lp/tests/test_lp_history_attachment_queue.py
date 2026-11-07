import copy
import unittest
from unittest.mock import patch
from services.lp.src import lp_history_attachment_queue as q

URL='https://www.ktcu.or.kr/comm/getFile?srvcId=BBSTY1&fileTy=ATTACH&upperNo=abc%3D&fileNo=xyz'

def notice(ident='91', title='2023 PEF 블라인드 모집'):
    return {'source_id':ident,'url':f'https://www.ktcu.or.kr/PPW-CSB-000101/{ident}',
            'title':title,'date':'2023-01-01','sha256':'a'*64,'attachments':[
                {'name':'선정 공고문 및 제안요청서.hwp','url':URL},
                {'name':'공고문 제안서 양식.hwp','url':URL},
                {'name':'동의서.hwp','url':URL}]}

class AttachmentQueueTests(unittest.TestCase):
    def setUp(self):
        self.h={'kind':'ktcu_history_listings_v1','institution_id':'ktcu','window':{'start':'2023-01-01','end':'2026-11-07'}}
        self.r={'documents':[notice()], 'holds':[]}
        self.proof=patch.object(q,'validate_report').start();self.addCleanup(patch.stopall)
    def test_priority_selection_caps_and_immutability(self):
        self.r['documents']=[notice(str(i)) for i in (95,94,93,92,91)]+[notice('99','다른 운용사 모집')]
        before=copy.deepcopy((self.h,self.r));p=q.plan(self.h,self.r)
        self.assertEqual([n['source_id'] for n in p['rows']],['91','92','93','94'])
        self.assertEqual((p['priority_count'],p['pending_count'],p['deferred_count'],p['skipped_forms_count']),(5,5,1,10))
        self.assertEqual((self.h,self.r),before);self.proof.assert_called_once()
        self.assertFalse(p['pe_approval'])
    def test_missing_ambiguous_and_bad_url_are_held(self):
        for attachments,reason in (([], 'missing_announcement'),([{'name':'공고문','url':URL}]*2,'ambiguous_announcement'),([{'name':'공고문','url':'https://evil.test/file'}],'invalid_attachment_url')):
            self.r['documents'][0]['attachments']=attachments
            p=q.plan(self.h,self.r);self.assertEqual(p['rows'],[]);self.assertEqual(p['holds'][0]['reason'],reason)
    def test_strict_urls(self):
        self.assertEqual(q.validate_url(URL),URL)
        for url in (URL+'&fileNo=other',URL+'&extra=x',URL.replace('https:','http:'),URL.replace('www.ktcu.or.kr','user@www.ktcu.or.kr'),URL.replace('www.ktcu.or.kr','www.ktcu.or.kr:443'),URL+'#',URL.replace('/comm/getFile','/comm/%67etFile'),URL.replace('fileNo=xyz','fileNo='),URL.replace('BBSTY1','OTHER'),URL.replace('fileNo=xyz','fileNo=%0a')):
            with self.subTest(url=url),self.assertRaises(ValueError):q.validate_url(url)
    def test_completed_identity_hash_and_duplicates(self):
        receipt={**q.plan(self.h,self.r)['rows'][0],'attachment_sha256':'b'*64}
        before=copy.deepcopy(receipt)
        self.assertEqual(q.plan(self.h,self.r,[receipt])['pending_count'],0)
        self.assertEqual(receipt,before)
        for key in ('source_id','source_url','body_sha256','attachment_name','attachment_url','attachment_sha256','institution_id'):
            bad={**receipt,key:'wrong'}
            with self.subTest(key=key),self.assertRaises(ValueError):q.plan(self.h,self.r,[bad])
        with self.assertRaises(ValueError):q.plan(self.h,self.r,[receipt,receipt])
    def test_proof_failures_limits_and_institution(self):
        self.proof.side_effect=ValueError('bad raw proof')
        with self.assertRaises(ValueError):q.plan(self.h,self.r)
        self.proof.side_effect=None
        for limit in (0,5,True):
            with self.assertRaises(ValueError):q.plan(self.h,self.r,limit=limit)
        self.r['holds']=[{'reason':'failed'}]
        with self.assertRaises(ValueError):q.plan(self.h,self.r)
        with self.assertRaises(ValueError):q.plan({'kind':'lp_history_listing_v1','institution_id':'kgrowth'},self.r)

if __name__=='__main__':unittest.main()
