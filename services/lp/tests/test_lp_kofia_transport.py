import hashlib
import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode
from services.lp.src import lp_regional_transport as relay

ROOT='https://www.kofia.or.kr/brd/m_17/list.do'
QUERY=dict(page='2',srchFr='',srchTo='',srchWord='',srchTp='',multi_itm_seq='0',
           itm_seq_1='0',itm_seq_2='0',company_cd='',company_nm='')


class KofiaTransportTests(unittest.TestCase):
    def response(self,raw=b'<html>complete</html>'):
        r=Mock();r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=False)
        r.read.return_value=raw
        r.headers={'X-LP-Source-Region':'icn1','X-LP-Upstream-SHA256':hashlib.sha256(raw).hexdigest()}
        return r

    def test_exact_official_list_routes_and_authenticated_bytes(self):
        for url in [ROOT]+[ROOT+'?'+urlencode({**QUERY,'page':str(n)}) for n in (1,2,3)]:
            with self.subTest(url=url),patch.object(relay,'build_opener') as opener:
                opener.return_value.open.return_value=self.response()
                self.assertEqual(relay.fetch_kofia_listing(url,ROOT,'test-token'),b'<html>complete</html>')
                req=opener.return_value.open.call_args.args[0]
                self.assertEqual(req.full_url,relay.WORKER)
                self.assertEqual(json.loads(req.data),{'url':url,'referer':ROOT})
                self.assertEqual(req.get_header('Authorization'),'Bearer test-token')
                self.assertEqual(opener.return_value.open.call_count,1)

    def test_rejected_routes_or_tokens_never_connect(self):
        url=ROOT+'?'+urlencode(QUERY)
        bad=[url+'&page=2',ROOT+'?page=2',url+'&extra=',url.replace('page=2','page=4'),
             url.replace('m_17','m_212'),url.replace('list.do','view.do'),url.replace('list.do','down.do'),
             url.replace('srchWord=','srchWord=PE'),url.replace('https:','http:'),
             url.replace('www.kofia.or.kr','user:password@www.kofia.or.kr'),
             url.replace('www.kofia.or.kr','evil.example'),url.replace('www.kofia.or.kr','www.kofia.or.kr:444'),
             url+'#part',url.replace('/brd/','/brd/%2e%2e/'),url.replace('/brd/','/brd/../'),
             url.replace('/brd/','/%62rd/'),url.replace('/brd/','/brd/%252e%252e/')]
        with patch.object(relay,'build_opener') as opener:
            for value in bad:
                with self.subTest(url=value),self.assertRaises(ValueError):relay.fetch_kofia_listing(value,ROOT,'test-token')
            for token in ('','bad token','bad\nvalue'):
                with self.assertRaises(ValueError):relay.fetch_kofia_listing(ROOT,None,token)
            with self.assertRaises(ValueError):relay.fetch_kofia_listing(ROOT,'https://evil.example','test-token')
            opener.assert_not_called()

    def test_regional_hash_region_empty_and_size_limits(self):
        receipts=[self.response(),self.response(),self.response(b''),self.response(b'x'*(relay.MAX_BYTES+1))]
        receipts[0].headers['X-LP-Source-Region']='iad1'
        receipts[1].headers['X-LP-Upstream-SHA256']='wrong'
        for receipt in receipts:
            with patch.object(relay,'build_opener') as opener:
                opener.return_value.open.return_value=receipt
                with self.assertRaises(ValueError):relay.fetch_kofia_listing(ROOT,None,'test-token')
                self.assertEqual(receipt.read.call_args.args[0],relay.MAX_BYTES+1)


if __name__=='__main__':unittest.main()
