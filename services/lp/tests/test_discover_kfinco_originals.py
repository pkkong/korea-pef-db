import copy
import io
import json
import unittest
import ssl
import socket
from urllib.error import HTTPError, URLError
from types import SimpleNamespace
from unittest.mock import patch
from services.lp.src.discover_kfinco_originals import discover, validate_api_provenance, digest, attachments, official, native_tls_fetch, BASE, LIST_URL

CODE='NT20991231010203'
TITLE='2026년 전문건설공제조합 국내 사모투자 위탁운용사 선정 계획 공고'
BODY='<p>2026년 전문건설공제조합 국내 사모투자 블라인드펀드 위탁운용사 선정 계획 공고</p><p>선정 개요 투자 부문 국내 사모투자(PE) 300억원</p>'
NOW='2026-10-15T09:00:00+00:00'

def source():return {'institution_id':'kfinco','source_id':'kofia:987','url':'https://www.kofia.or.kr/brd/m_212/view.do?seq=987','title':'[전문건설공제조합] 2026년 국내PE 블라인드펀드 위탁운용사 선정 공고','date':'2026-09-30','source_scope':'pe_blind'}
def row(code=CODE,date='2026-09-30'):
    return {'ntCode':code,'ntTitle':TITLE,'ntDate':date,'closed':0,'noticeAttachModelList':[]}
def encode(x):return json.dumps(x,ensure_ascii=False).encode()
def listing(rows):return encode({'success':True,'totalCount':len(rows),'list':rows})
def detail(r):return encode({'success':True,'detail':{**r,'ntContent':BODY}})

class KfincoTests(unittest.TestCase):
    def fixture(self,rows=None,raw=None):
        rows=[row()] if rows is None else rows
        def fetch(url):
            if url==LIST_URL:return listing(rows)
            if '/api/pr/notice/detail/' in url:return raw or detail(rows[0])
            raise OSError('attachment outage')
        return discover({'notices':[source()]},fetch,NOW)

    def test_native_tls_requires_certificate_and_hostname_verification(self):
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with patch.dict('sys.modules',{'truststore':SimpleNamespace(SSLContext=lambda protocol:context)}), patch('services.lp.src.discover_kfinco_originals.fetch_bytes',return_value=b'verified') as fetch:
            self.assertEqual(native_tls_fetch(LIST_URL),b'verified')
            self.assertEqual(fetch.call_args.kwargs['ssl_context'].verify_mode,ssl.CERT_REQUIRED)
            self.assertTrue(fetch.call_args.kwargs['ssl_context'].check_hostname)
            context.check_hostname=False
            with self.assertRaises(ValueError):native_tls_fetch(LIST_URL)
            self.assertEqual(fetch.call_count,1)

    def test_temporary_macos_dns_listing_error_recovers_without_hold(self):
        responses = [URLError(socket.gaierror(8, 'nodename nor servname provided, or not known')), listing([row()]), detail(row())]
        with patch('services.lp.src.discover_kfinco_originals.time.sleep') as sleep:
            fetch = unittest.mock.Mock(side_effect=responses)
            out = discover({'notices': [source()]}, fetch, NOW)
        self.assertNotIn('holds', out)
        self.assertEqual(out['notices'][0]['original_notices'][0]['title'], TITLE)
        self.assertEqual([c.args[0] for c in fetch.call_args_list], [LIST_URL, LIST_URL, BASE + '/api/pr/notice/detail/' + CODE])
        self.assertEqual(out['coverage']['kfinco_original']['retry_requests'], 1)
        sleep.assert_called_once_with(1)

    def test_timeout_connection_rate_limit_and_server_error_retry_only_transport(self):
        errors = [TimeoutError('slow'), URLError(TimeoutError('slow')),
                  URLError(ConnectionResetError('closed')), socket.gaierror(socket.EAI_AGAIN, 'temporary DNS'),
                  HTTPError(LIST_URL, 429, 'rate limited', {}, None),
                  HTTPError(LIST_URL, 503, 'unavailable', {}, None)]
        for error in errors:
            with self.subTest(error=type(error).__name__), patch('services.lp.src.discover_kfinco_originals.time.sleep') as sleep:
                fetch = unittest.mock.Mock(side_effect=[error, listing([row()]), detail(row())])
                out = discover({'notices': [source()]}, fetch, NOW)
                self.assertEqual(out['coverage']['kfinco_original']['linked'], 1)
                self.assertEqual(fetch.call_count, 3)
                sleep.assert_called_once_with(1)

    def test_tls_host_http_refusal_and_source_validation_errors_do_not_retry(self):
        errors = [URLError(ssl.SSLCertVerificationError('certificate hostname mismatch')),
                  HTTPError(LIST_URL, 404, 'missing', {}, None),
                  HTTPError(LIST_URL, 403, 'forbidden', {}, None),
                  ValueError('host validation failed')]
        for error in errors:
            with self.subTest(error=type(error).__name__), patch('services.lp.src.discover_kfinco_originals.time.sleep') as sleep:
                fetch = unittest.mock.Mock(side_effect=error)
                out = discover({'notices': [source()]}, fetch, NOW)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(out['holds'][0]['phase'], 'listing')
                sleep.assert_not_called()
        with patch('services.lp.src.discover_kfinco_originals.time.sleep') as sleep:
            fetch = unittest.mock.Mock(return_value=b'{"success": false}')
            out = discover({'notices': [source()]}, fetch, NOW)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(out['holds'][0]['phase'], 'listing')
            sleep.assert_not_called()

    def test_persistent_dns_error_stops_after_three_attempts_and_preserves_existing(self):
        retained = {**source(), 'original_notices': [{'body': 'previous verified original'}]}
        collection = {'notices': [source(), retained]}
        before = copy.deepcopy(collection)
        with patch('services.lp.src.discover_kfinco_originals.time.sleep') as sleep:
            fetch = unittest.mock.Mock(side_effect=URLError(socket.gaierror(8, 'nodename nor servname provided, or not known')))
            out = discover(collection, fetch, NOW)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])
        self.assertEqual(collection, before)
        self.assertEqual(out['notices'][1], retained)
        self.assertEqual(out['holds'][0]['phase'], 'listing')
        self.assertNotIn('original_notices', out['notices'][0])

    def test_temporary_detail_failure_recovers_but_invalid_body_is_not_retried(self):
        with patch('services.lp.src.discover_kfinco_originals.time.sleep') as sleep:
            fetch = unittest.mock.Mock(side_effect=[listing([row()]), TimeoutError('detail timeout'), detail(row())])
            out = discover({'notices': [source()]}, fetch, NOW)
            self.assertEqual(out['coverage']['kfinco_original']['linked'], 1)
            self.assertEqual(fetch.call_count, 3)
            sleep.assert_called_once_with(1)
        invalid = encode({'success': True, 'detail': {**row(), 'ntContent': 'scope missing'}})
        with patch('services.lp.src.discover_kfinco_originals.time.sleep') as sleep:
            fetch = unittest.mock.Mock(side_effect=[listing([row()]), invalid])
            out = discover({'notices': [source()]}, fetch, NOW)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(out['holds'][0]['phase'], 'validation')
            sleep.assert_not_called()

    def test_listing_detail_and_attachment_share_four_extra_attempts(self):
        r = {**row(), 'noticeAttachModelList': [{'ntCode': CODE, 'filepath': '/pds/notice/2026-09', 'filenameSave': 'a.hwp', 'filenameOriginal': '공고문.hwp'}]}
        counts = {'listing': 0, 'detail': 0, 'attachment': 0}
        def fetch(url):
            phase = 'listing' if url == LIST_URL else 'detail' if '/api/pr/notice/detail/' in url else 'attachment'
            counts[phase] += 1
            if counts[phase] <= 2 or phase == 'attachment':
                raise TimeoutError('temporary ' + phase)
            return listing([r]) if phase == 'listing' else detail(r)
        with patch('services.lp.src.discover_kfinco_originals.time.sleep') as sleep:
            out = discover({'notices': [source()]}, fetch, NOW)
        self.assertEqual(counts, {'listing': 3, 'detail': 3, 'attachment': 1})
        self.assertEqual(sleep.call_count, 4)
        self.assertEqual(out['coverage']['kfinco_original']['retry_requests'], 4)
        self.assertEqual(out['holds'][0]['phase'], 'attachment')
        self.assertTrue(out['notices'][0]['original_notices'][0]['body'])

    def test_previous_success_does_not_hide_a_later_run_dns_failure(self):
        first = self.fixture()
        self.assertEqual(first['coverage']['kfinco_original']['linked'], 1)
        with patch('services.lp.src.discover_kfinco_originals.time.sleep'):
            fetch = unittest.mock.Mock(side_effect=URLError(socket.gaierror(8, 'DNS unavailable')))
            later = discover({'notices': [source()]}, fetch, NOW)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(later['coverage']['kfinco_original']['linked'], 0)
        self.assertEqual(later['holds'][0]['phase'], 'listing')

    def test_native_verified_block_falls_back_once_without_upstream_token(self):
        from services.lp.src import discover_kfinco_originals as module
        context=SimpleNamespace(verify_mode=ssl.CERT_REQUIRED,check_hostname=True)
        block=HTTPError(LIST_URL,400,'Bad Request',{},io.BytesIO(b'<html>400 Bad Request contact the administrator</html>'))
        with patch.dict('sys.modules',{'truststore':SimpleNamespace(SSLContext=lambda protocol:context)}), patch.dict(module.os.environ,{'LP_SOURCE_WORKER_TOKEN':'private-key'}), patch.object(module,'fetch_bytes',side_effect=block) as native, patch.object(module,'fetch_kfinco',return_value=b'official') as regional:
            self.assertEqual(module.native_tls_fetch(LIST_URL),b'official')
            native.assert_called_once_with(LIST_URL,ssl_context=context)
            regional.assert_called_once_with(LIST_URL,'private-key')

    def test_wrong_400_no_token_ssl_or_404_never_use_regional(self):
        from services.lp.src import discover_kfinco_originals as module
        context=SimpleNamespace(verify_mode=ssl.CERT_REQUIRED,check_hostname=True)
        cases=[(400,b'invalid parameter','key'),(400,b'400 Bad Request contact the administrator',''),(404,b'400 Bad Request contact the administrator','key'),(400,b'x'*4097+b'400 Bad Request contact the administrator','key')]
        errors=[(HTTPError(LIST_URL,status,'failure',{},io.BytesIO(body)),token) for status,body,token in cases]
        errors.append((URLError(ssl.SSLCertVerificationError('certificate failure')),'key'))
        for error,token in errors:
            with patch.dict('sys.modules',{'truststore':SimpleNamespace(SSLContext=lambda protocol:context)}), patch.dict(module.os.environ,{'LP_SOURCE_WORKER_TOKEN':token}), patch.object(module,'fetch_bytes',side_effect=error), patch.object(module,'fetch_kfinco') as regional:
                with self.assertRaises((HTTPError,URLError)):module.native_tls_fetch(LIST_URL)
                regional.assert_not_called()

    def test_worker_failure_does_not_restart_native_retry_budget(self):
        from services.lp.src import discover_kfinco_originals as module
        context=SimpleNamespace(verify_mode=ssl.CERT_REQUIRED,check_hostname=True)
        block=HTTPError(LIST_URL,400,'failure',{},io.BytesIO(b'400 Bad Request contact the administrator'))
        with patch.dict('sys.modules',{'truststore':SimpleNamespace(SSLContext=lambda protocol:context)}), patch.dict(module.os.environ,{'LP_SOURCE_WORKER_TOKEN':'key'}), patch.object(module,'fetch_bytes',side_effect=block) as native, patch.object(module,'fetch_kfinco',side_effect=ValueError('regional failure')) as regional, patch.object(module.time,'sleep') as sleep:
            result=module.discover({'notices':[source()]},fetch=module.native_tls_fetch,checked_at=NOW)
            self.assertEqual(native.call_count,1);self.assertEqual(regional.call_count,1);sleep.assert_not_called()
            self.assertEqual(result['holds'][0]['phase'],'listing')
            self.assertEqual(result['coverage']['kfinco_original']['retry_requests'],0)

    def test_new_arbitrary_identifier_and_unchanged_title(self):
        out=self.fixture();o=out['notices'][0]['original_notices'][0]
        self.assertTrue(o['url'].endswith(CODE));self.assertEqual(o['title'],TITLE)
        self.assertTrue(o['review_only']);validate_api_provenance(o,source())

    def test_june_and_september_are_different_businesses(self):
        june=row('NT20990101010101','2026-06-18');sept=row()
        out=self.fixture([june,sept],detail(sept))
        self.assertEqual(out['notices'][0]['original_notices'][0]['date'],'2026-09-30')
        self.assertNotIn('original_notices',self.fixture([june])['notices'][0])

    def test_ambiguous_same_date_and_closed_do_not_fetch_detail(self):
        for rows in [[row(),row('NT20990202020202')],[{**row(),'closed':1}]]:
            calls=[]
            def fetch(url):calls.append(url);return listing(rows)
            out=discover({'notices':[source()]},fetch,NOW)
            self.assertEqual(calls,[LIST_URL]);self.assertEqual(out['holds'][0]['phase'],'matching')

    def test_wrong_year_round_stage_vc_and_foreign_held(self):
        for title in [TITLE.replace('2026','2025'),TITLE.replace('선정 계획 공고','선정 결과'),TITLE.replace('사모투자','VC'),TITLE.replace('국내','해외'),TITLE.replace('사모투자','프로젝트'),TITLE.replace('2026년','2026년 2차')]:
            r={**row(),'ntTitle':title}
            self.assertNotIn('original_notices',self.fixture([r])['notices'][0])

    def test_body_must_explicitly_confirm_pe_blind(self):
        for wrong in [BODY.replace('블라인드',''),BODY.replace('(PE)','(VC)'),BODY.replace('국내','해외')]:
            raw=encode({'success':True,'detail':{**row(),'ntContent':wrong}})
            out=self.fixture(raw=raw)
            self.assertNotIn('original_notices',out['notices'][0])
            self.assertEqual(out['holds'][0]['phase'],'validation')

    def test_foreign_route_and_traversal_rejected(self):
        with self.assertRaises(ValueError):official('https://evil.test/api/pr/notice/list','/api/pr/notice/list')
        with self.assertRaises(ValueError):official(BASE+'/x/../api/pr/notice/list','/api/pr/notice/list')
        d={**row(),'noticeAttachModelList':[{'ntCode':CODE,'filepath':'/pds/notice/2026-09/../private','filenameSave':'a.hwp','filenameOriginal':'공고문.hwp'}]}
        with self.assertRaises(ValueError):attachments(d)
        d['noticeAttachModelList'][0]['filepath']='/pds/notice/2026-09'
        d['noticeAttachModelList'][0]['filenameSave']='../secret.hwp'
        with self.assertRaises(ValueError):attachments(d)

    def test_receipt_or_body_tampering_rejected(self):
        o=self.fixture()['notices'][0]['original_notices'][0]
        for field,value in [('body','changed'),('title',TITLE+' changed'),('url','https://evil.test/pr/notice/detail/'+CODE)]:
            bad=copy.deepcopy(o);bad[field]=value
            with self.assertRaises(ValueError):validate_api_provenance(bad,source())
        bad=copy.deepcopy(o);bad['discovery_provenance']['listing_sha256']='0'*64
        with self.assertRaises(ValueError):validate_api_provenance(bad,source())
        bad=copy.deepcopy(o);p=bad['discovery_provenance'];d=json.loads(p['detail_json']);d['detail']['ntDate']='2026-06-18';p['detail_json']=json.dumps(d);p['detail_sha256']=digest(p['detail_json'])
        with self.assertRaises(ValueError):validate_api_provenance(bad,source())

    def test_attachment_failure_preserves_body(self):
        r={**row(),'noticeAttachModelList':[{'ntCode':CODE,'filepath':'/pds/notice/2026-09','filenameSave':'a.hwp','filenameOriginal':'공고문.hwp'}]}
        out=self.fixture([r]);self.assertTrue(out['notices'][0]['original_notices'][0]['body']);self.assertEqual(out['holds'][0]['phase'],'attachment')

    def test_outage_preserves_existing_originals_and_input(self):
        x={'notices':[source(),{**source(),'original_notices':[{'body':'existing'}]}]};before=copy.deepcopy(x)
        def fail(url):raise OSError('outage')
        out=discover(x,fail,NOW)
        self.assertEqual(x,before);self.assertEqual(out['notices'][1],before['notices'][1]);self.assertEqual(out['holds'][0]['phase'],'listing')

    def test_form_zip_skipped(self):
        r={**row(),'noticeAttachModelList':[{'filenameOriginal':'양식.zip'}]}
        self.assertEqual(attachments(r),[])

if __name__=='__main__':unittest.main()
