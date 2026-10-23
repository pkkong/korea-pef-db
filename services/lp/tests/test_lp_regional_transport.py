import hashlib
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from services.lp.src import lp_regional_transport as relay
from services.lp.src import collect_lp_institution_boards as boards

URL='https://www.kfcc.co.kr/mgNotice/mgNoticeList.do?schType=subject&schValue=test&pageNo=1'


class RegionalTransportTests(unittest.TestCase):
    def response(self, raw=b'<html>official</html>'):
        response=Mock()
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=raw
        response.headers={'X-LP-Source-Region':'icn1','X-LP-Upstream-SHA256':hashlib.sha256(raw).hexdigest()}
        return response

    def test_token_goes_only_to_fixed_worker_and_exact_bytes_are_returned(self):
        response=self.response(b'\xd0\xcf\x11\xe0bytes')
        with patch.object(relay,'build_opener') as opener:
            opener.return_value.open.return_value=response
            self.assertEqual(relay.fetch_kfcc(URL,URL,'test-private-key'),b'\xd0\xcf\x11\xe0bytes')
            request=opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url,relay.WORKER)
            self.assertEqual(request.get_method(),'POST')
            self.assertEqual(request.get_header('Authorization'),'Bearer test-private-key')
            self.assertEqual(json.loads(request.data)['url'],URL)
            self.assertEqual(opener.return_value.open.call_count,1)

    def test_foreign_unsafe_and_unconfigured_requests_never_send_credentials(self):
        bad=[URL.replace('www.kfcc.co.kr','evil.example'), URL.replace('https:','http:'),
             URL.replace('/mgNotice/mgNoticeList.do','/private'),
             'https://www.kfcc.co.kr/upload/neoboard/A01/%252e%252e/private.hwp',
             'https://user:password@www.kfcc.co.kr/mgNotice/mgNoticeList.do']
        with patch.object(relay,'build_opener') as opener:
            for url in bad:
                with self.subTest(url=url),self.assertRaises(ValueError):relay.fetch_kfcc(url,None,'key')
            with self.assertRaises(ValueError):relay.fetch_kfcc(URL,None,'')
            with self.assertRaises(ValueError):relay.fetch_kfcc(URL,'https://evil.example','key')
            opener.assert_not_called()

    def test_location_hash_empty_and_size_are_verified(self):
        responses=[self.response(),self.response(),self.response(b''),self.response(b'x'*(relay.MAX_BYTES+1))]
        responses[0].headers['X-LP-Source-Region']='iad1';responses[1].headers['X-LP-Upstream-SHA256']='a'*64
        for response in responses:
            with self.subTest(response=response),patch.object(relay,'build_opener') as opener:
                opener.return_value.open.return_value=response
                with self.assertRaises(ValueError):relay.fetch_kfcc(URL,None,'key')

    def test_worker_redirect_or_http_error_cannot_masquerade_as_official_bytes(self):
        with self.assertRaises(ValueError):relay.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example')
        error=HTTPError(relay.WORKER,502,'private key never echoed',{},io.BytesIO(b'secret'))
        with patch.object(relay,'build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaisesRegex(ValueError,'HTTP 502') as caught:relay.fetch_kfcc(URL,None,'key')
            self.assertNotIn('secret',str(caught.exception))
            self.assertEqual(opener.return_value.open.call_count,1)

    def test_only_known_worker_failure_category_is_reported_without_raw_body(self):
        for code in ['upstream_status','source_fetch_failed']:
            error=HTTPError(relay.WORKER,502,'private',{},io.BytesIO(json.dumps({'error':code,'secret':'private'}).encode()))
            with patch.object(relay,'build_opener') as opener:
                opener.return_value.open.side_effect=error
                with self.assertRaisesRegex(ValueError,code) as caught:relay.fetch_kfcc(URL,None,'key')
                self.assertNotIn('private',str(caught.exception))

    def test_kfinco_exact_routes_and_worker_authentication(self):
        from urllib.parse import quote
        url='https://www.kfinco.co.kr/api/pr/notice/list?page=1&size=10&searchKeyword='+quote('위탁운용사')
        with patch.object(relay,'build_opener') as opener:
            opener.return_value.open.return_value=self.response(b'official')
            self.assertEqual(relay.fetch_kfinco(url,'private-key'),b'official')
            req=opener.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url,relay.WORKER)
            self.assertEqual(json.loads(req.data),{'url':url})
            self.assertEqual(req.get_header('Authorization'),'Bearer private-key')
        self.assertEqual(relay.kfinco_url('https://www.kfinco.co.kr/api/pr/notice/detail/NT20990101010101'),'https://www.kfinco.co.kr/api/pr/notice/detail/NT20990101010101')
        bad=[url.replace('www.kfinco.co.kr','evil.test'),url+'&page=1',url.replace('size=10','size=100'),url.replace('page=1','page=2'),
             'https://www.kfinco.co.kr/api/pr/notice/detail/NT20990101010101?x=1',
             'https://www.kfinco.co.kr/util/download?filePath=%2Fpds%2Fnotice%2F2026-09%2F%252e%252e%2Fa.hwp&downloadName=a.hwp',
             'https://www.kfinco.co.kr/util/download?filePath=%2Fpds%2Fnotice%2F2026-09%2Fa.hwp&downloadName=..%2Fa.hwp']
        with patch.object(relay,'build_opener') as opener:
            for value in bad:
                with self.subTest(value=value),self.assertRaises(ValueError):relay.fetch_kfinco(value,'private-key')
            opener.assert_not_called()

    def test_kfinco_worker_network_failure_is_not_retryable_or_secret_bearing(self):
        from urllib.error import URLError
        url='https://www.kfinco.co.kr/api/pr/notice/detail/NT20990101010101'
        with patch.object(relay,'build_opener') as opener:
            opener.return_value.open.side_effect=URLError('private-key')
            with self.assertRaisesRegex(ValueError,'transport unavailable') as error:relay.fetch_kfinco(url,'private-key')
            self.assertNotIn('private-key',str(error.exception))
            self.assertEqual(opener.return_value.open.call_count,1)

    def session(self,institution='kfcc',body=b'<h1>Request Blocked</h1>',code=400):
        session=boards.Session(boards.load_configs()[institution])
        session.opener=Mock()
        session.opener.open.side_effect=HTTPError(URL,code,'Bad Request',{},io.BytesIO(body))
        return session

    def test_only_observed_kfcc_block_uses_regional_fallback_once(self):
        session=self.session()
        with patch.dict(boards.os.environ,{'LP_SOURCE_WORKER_TOKEN':'key'}),patch.object(boards,'fetch_kfcc',return_value=b'official bytes') as fetch:
            self.assertEqual(session(URL,URL),b'official bytes')
            self.assertEqual(session.regional_fetches,1)
            fetch.assert_called_once_with(URL,URL,'key')
            self.assertEqual(session.opener.open.call_count,1)

    def test_normal_400_missing_key_or_other_issuer_keeps_failure(self):
        scenarios=[(self.session(body=b'invalid parameter'),URL,'key'),(self.session(),URL,''),
                   (self.session('pmaa'),'https://www.pmaa.or.kr/test','key')]
        for session,url,key in scenarios:
            with patch.dict(boards.os.environ,{'LP_SOURCE_WORKER_TOKEN':key}),patch.object(boards,'fetch_kfcc') as fetch:
                with self.assertRaises(HTTPError):session(url)
                fetch.assert_not_called()

    def test_regional_failure_has_no_nested_retry_and_no_false_success(self):
        session=self.session()
        with patch.dict(boards.os.environ,{'LP_SOURCE_WORKER_TOKEN':'key'}),patch.object(boards,'fetch_kfcc',side_effect=ValueError('regional failure')) as fetch:
            with self.assertRaisesRegex(ValueError,'regional failure'):session(URL)
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(session.opener.open.call_count,1)
            self.assertEqual(session.regional_fetches,0)


if __name__=='__main__':unittest.main()
