import copy
import gzip
import hashlib
import io
import json
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError
from services.lp.src import lp_report_archive as a

REPORT={'zero':0,'false':False,'none':None,'한국어':['공고','literal \\n and \\uAC00','line\nactual'],'nested':{'x':1}}
ORIGIN='https://sample-project.supabase.co'

class MemoryTransport:
    def __init__(self,public=False,exists=True):
        self.public=public;self.exists=exists;self.objects={};self.calls=[];self.upload_status=200;self.corrupt=False
    def __call__(self,method,url,headers,body,limit,timeout):
        self.calls.append((method,url,dict(headers),body,limit,timeout))
        if '/bucket/' in url:return (200,json.dumps({'id':a.BUCKET,'public':self.public}).encode()) if self.exists else (404,b'{}')
        if url.endswith('/bucket'):
            assert json.loads(body)['public'] is False
            self.exists=True;return 201,b'{}'
        if method=='POST':
            assert headers['x-upsert']=='false'
            path=url.split('/object/',1)[1]
            if self.upload_status==200:self.objects[path]=body[:-1] if self.corrupt else body
            return self.upload_status,b'{}'
        key=url.split('/object/authenticated/',1)[1]
        return (200,self.objects[key]) if key in self.objects else (404,b'{}')

class ArchiveTests(unittest.TestCase):
    def test_storage_failure_diagnostic_never_echoes_provider_details(self):
        raw=json.dumps({'statusCode':'404','error':'Bucket not found','message':'SECRET https://private.example/path'}).encode()
        error=a._safe_http_failure('bucket failed',400,raw)
        self.assertEqual(str(error),'bucket failed (HTTP 400, statusCode 404, Bucket not found)')
        for body in [b'{"error":"SECRET","statusCode":"SECRET"}', b'not-json SECRET', b'[]', b'{"error":[]}']:
            self.assertEqual(str(a._safe_http_failure('bucket failed',400,body)),'bucket failed (HTTP 400)')

    def test_legacy_missing_response_creates_private_bucket(self):
        transport=MemoryTransport(exists=False)
        def legacy(method,url,headers,body,limit,timeout):
            if '/bucket/' in url and not transport.exists:
                return 400,b'{"statusCode":"404","error":"Bucket not found","message":"Bucket not found"}'
            return transport(method,url,headers,body,limit,timeout)
        self.assertTrue(a.ArchiveStore(ORIGIN,'key',legacy).ensure_private_bucket())
        for error in ['Bucket not found','Object not found','NoSuchKey','NoSuchBucket','not_found']:
            self.assertTrue(a._missing(400,json.dumps({'statusCode':'404','error':error}).encode()))
            self.assertFalse(a._missing(400,json.dumps({'statusCode':'403','error':error}).encode()))
        self.assertFalse(a._missing(400,b'{"statusCode":"404","error":"AccessDenied"}'))

    def test_deterministic_roundtrip_preserves_all_json_values(self):
        b,m=a.encode_report(REPORT)
        self.assertEqual((b,m),a.encode_report(dict(reversed(list(REPORT.items())))))
        self.assertEqual(a.decode_report(b,m),REPORT)
        stub=a.make_stub('run-123_safe',m)
        self.assertTrue(a.is_archive_stub(stub));self.assertEqual(a.decode_report(b,stub[a.MARKER]),REPORT)
        self.assertEqual(set(stub),{a.MARKER})
        self.assertFalse(a.is_archive_stub(REPORT))

    def test_metadata_schema_hash_lengths_and_path_fail_closed(self):
        b,m=a.encode_report(REPORT)
        for field,value in [('version',True),('codec','zip'),('raw_bytes',True),('gzip_bytes',0),('raw_sha256','a'*64),('gzip_sha256','0'*64),('extra',1)]:
            bad={**m,field:value}
            with self.subTest(field=field),self.assertRaises(a.ArchiveError):a.decode_report(b,bad)
        stub=a.make_stub('run',m)
        for field,value in [('bucket','public'),('object_path','runs/../bad.json.gz'),('object_path','runs/run/'+'0'*64+'.json.gz')]:
            bad=copy.deepcopy(stub);bad[a.MARKER][field]=value
            with self.assertRaises(a.ArchiveError):a.validate_locator(bad)
        with self.assertRaises(a.ArchiveError):a.validate_locator(stub,'other-run')
        with self.assertRaises(a.ArchiveError):a.is_archive_stub({a.MARKER:{}})
        with self.assertRaises(a.ArchiveError):a.validate_locator({**stub,'report':REPORT})
        for run in ['../escape','a/b','a%2Fb','',123]:
            with self.assertRaises(a.ArchiveError):a.make_stub(run,m)

    def test_corrupt_truncated_extra_member_and_decompression_limit(self):
        b,m=a.encode_report(REPORT)
        for blob in [b[:-1],b[:-3]+b'bad',b+gzip.compress(b'{}',mtime=0)]:
            bad={**m,'gzip_bytes':len(blob),'gzip_sha256':hashlib.sha256(blob).hexdigest()}
            with self.assertRaises(a.ArchiveError):a.decode_report(blob,bad)
        with patch.object(a,'MAX_RAW_BYTES',5):
            with self.assertRaises(a.ArchiveError):a.decode_report(b,m)
            with self.assertRaises(a.ArchiveError):a.encode_report(REPORT)
        with patch.object(a,'MAX_COMPRESSED_BYTES',5):
            with self.assertRaises(a.ArchiveError):a.decode_report(b,m)
        short={**m,'raw_bytes':2}
        with self.assertRaises(a.ArchiveError):a.decode_report(b,short)

    def test_nonfinite_nondict_noncanonical_duplicate_json_rejected(self):
        for report in [[],{'secret':float('nan')},{'secret':float('inf')},{'x':object()},{1:'numeric key'},{'tuple':(1,2)}]:
            with self.assertRaises(a.ArchiveError):a.encode_report(report)
        for raw in [b'[]',b'{ "x":1}',b'{"x":1,"x":2}',b'{"x":NaN}']:
            blob=gzip.compress(raw,mtime=0)
            m={'version':1,'codec':'json-gzip-v1','raw_sha256':hashlib.sha256(raw).hexdigest(),'gzip_sha256':hashlib.sha256(blob).hexdigest(),'raw_bytes':len(raw),'gzip_bytes':len(blob)}
            with self.assertRaises(a.ArchiveError):a.decode_report(blob,m)

    def test_upload_readback_then_stub_and_restore(self):
        transport=MemoryTransport();store=a.ArchiveStore(ORIGIN,'secret-key',transport)
        stub=store.put_verified('run-1',REPORT)
        self.assertEqual([r[0] for r in transport.calls],['GET','GET','POST','GET'])
        self.assertEqual(store.restore(stub),REPORT)
        for method,url,headers,body,limit,timeout in transport.calls:
            self.assertTrue(url.startswith(ORIGIN+'/storage/v1/'))
            self.assertNotIn('secret-key',url);self.assertEqual(headers['Authorization'],'Bearer secret-key')
            self.assertLessEqual(limit,a.MAX_COMPRESSED_BYTES);self.assertEqual(timeout,a.TIMEOUT)

    def test_private_bucket_creation_only_after404_and_public_rejected(self):
        transport=MemoryTransport(exists=False);store=a.ArchiveStore(ORIGIN,'key',transport)
        self.assertTrue(store.ensure_private_bucket())
        self.assertEqual([c[0] for c in transport.calls],['GET','POST','GET'])
        transport=MemoryTransport(public=True)
        with self.assertRaises(a.ArchiveError):a.ArchiveStore(ORIGIN,'key',transport).put_verified('r',REPORT)
        self.assertEqual(len(transport.calls),1)
        fail=Mock(return_value=(403,b'private detail'))
        with self.assertRaises(a.ArchiveError):a.ArchiveStore(ORIGIN,'key',fail).ensure_private_bucket()
        self.assertEqual(fail.call_count,1)

    def test_partial_upload_and_duplicate409_require_full_readback(self):
        transport=MemoryTransport();transport.corrupt=True
        with self.assertRaises(a.ArchiveError):a.ArchiveStore(ORIGIN,'key',transport).put_verified('r',REPORT)
        transport=MemoryTransport();store=a.ArchiveStore(ORIGIN,'key',transport);stub=store.put_verified('r',REPORT)
        transport.upload_status=409
        self.assertEqual(store.put_verified('r',REPORT),stub)
        key=next(iter(transport.objects));transport.objects[key]=b'bad'
        with self.assertRaises(a.ArchiveError):store.put_verified('r',REPORT)

    def test_known_duplicate400_only_and_no_secret_echo(self):
        transport=MemoryTransport();store=a.ArchiveStore(ORIGIN,'key',transport);stub=store.put_verified('r',REPORT)
        for response,accepted in [(b'{"error":"Duplicate","message":"Asset already exists"}',True),(b'{"message":"Asset already exists"}',False),(b'{"error":"private key","message":"bad upload"}',False)]:
            def wrapped(method,url,headers,body,limit,timeout):
                if method=='POST':return 400,response
                return transport(method,url,headers,body,limit,timeout)
            attempt=a.ArchiveStore(ORIGIN,'key',wrapped)
            if accepted:attempt._put_object('new-path',b'test')
            else:
                with self.assertRaises(a.ArchiveError) as caught:attempt._put_object('new-path',b'test')
                self.assertNotIn('private key',str(caught.exception))

    def test_redirect_origin_and_response_bounds(self):
        for url in ['http://p.supabase.co','https://p.supabase.co.evil.test','https://p.supabase.co/path','https://key@p.supabase.co','https://p.supabase.co:443']:
            with self.assertRaises(a.ArchiveError):a.ArchiveStore(url,'key')
        with self.assertRaises(a.ArchiveError):a._NoRedirect().redirect_request(None,None,302,'',{},'https://evil.test')
        for transport in [Mock(return_value=(302,b'')),Mock(return_value=(200,b'x'*(a.MAX_CONTROL_BYTES+1))),Mock(side_effect=RuntimeError('SECRET'))]:
            with self.assertRaises(a.ArchiveError) as caught:a.ArchiveStore(ORIGIN,'key',transport).ensure_private_bucket()
            self.assertNotIn('SECRET',str(caught.exception))

    def test_archive_private_probe_rejects_any_publicly_readable_object(self):
        _,meta=a.encode_report(REPORT);stub=a.make_stub('r',meta)
        store=a.ArchiveStore(ORIGIN,'service',Mock(return_value=(200,b'private object')))
        with self.assertRaises(a.ArchiveError):store.assert_private(stub,'anon')
        store=a.ArchiveStore(ORIGIN,'service',Mock(return_value=(403,b'{}')))
        self.assertEqual(store.assert_private(stub,'anon'),403)
        with self.assertRaises(a.ArchiveError):store.assert_private(stub,'service')
        store=a.ArchiveStore(ORIGIN,'service',Mock(return_value=(401,b'{}')))
        with self.assertRaises(a.ArchiveError):store.assert_private(stub,'invalid')

    def test_default_transport_bounds_reads_and_preserves_no_redirect_handler(self):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False);response.code=200;response.read.return_value=b'12345'
        with patch.object(a,'build_opener') as build:
            build.return_value.open.return_value=response
            with self.assertRaises(a.ArchiveError):a._transport('GET',ORIGIN+'/storage/v1/bucket/x',{},None,4,60)
            response.read.assert_called_once_with(5)
            self.assertIsInstance(build.call_args.args[0],a._NoRedirect)

class ChunkedArchiveTests(unittest.TestCase):
    def test_v2_shared_strings_and_lossless_restore(self):
        text='공고 원문\n'+('한글\\u1234 '+ 'x'*100)*100
        first={**REPORT,'timestamp':'one','body':text,'repeat':[None,text]}
        second={**first,'timestamp':'two'}
        transport=MemoryTransport();store=a.ArchiveStore(ORIGIN,'key',transport)
        stub1=store.put_verified('one',first);stub2=store.put_verified('two',second)
        self.assertEqual(stub1[a.MARKER]['version'],2)
        self.assertEqual(store.restore(stub1),first);self.assertEqual(store.restore(stub2),second)
        chunks=[key for key in transport.objects if '/chunks/' in key]
        self.assertEqual(len(chunks),1)
        posts=[c for c in transport.calls if c[0]=='POST' and '/chunks/' in c[1]]
        self.assertEqual(len(posts),1)
        self.assertEqual(len(transport.objects),3)
        self.assertGreaterEqual(a.estimate_report(first),sum(len(v) for k,v in transport.objects.items() if k!=a.BUCKET+'/'+stub2[a.MARKER]['object_path']))

    def test_existing_different_gzip_encodings_are_reused_without_overwrite(self):
        report={'body':'A'*12000, 'null':None}
        transport=MemoryTransport();store=a.ArchiveStore(ORIGIN,'key',transport)
        raw=report['body'].encode();sha=hashlib.sha256(raw).hexdigest()
        transport.objects[a.BUCKET+'/chunks/'+sha+'.txt.gz']=gzip.compress(raw,compresslevel=1,mtime=99)
        stub=store.put_verified('first',report)
        self.assertEqual(store.restore(stub),report)
        key=a.BUCKET+'/'+stub[a.MARKER]['object_path']
        manifest=gzip.decompress(transport.objects[key])
        transport.objects[key]=gzip.compress(manifest,compresslevel=1,mtime=123)
        before=len(transport.calls)
        revised=store.put_verified('first',report)
        self.assertEqual(store.restore(revised),report)
        self.assertFalse(any(c[0]=='POST' for c in transport.calls[before:]))
        self.assertNotEqual(revised[a.MARKER]['gzip_sha256'],stub[a.MARKER]['gzip_sha256'])

    def test_legacy_missing_error_is_not_an_authentication_error(self):
        self.assertTrue(a._missing(400,b'{"statusCode":"404","error":"not_found"}'))
        self.assertFalse(a._missing(400,b'{"statusCode":"401","error":"unauthorized"}'))
        self.assertFalse(a._missing(403,b'{"statusCode":"404","error":"not_found"}'))

    def test_v1_store_restore_stays_compatible(self):
        blob,meta=a.encode_report(REPORT);stub=a.make_stub('old',meta)
        transport=MemoryTransport();transport.objects[a.BUCKET+'/'+stub[a.MARKER]['object_path']]=blob
        self.assertEqual(a.ArchiveStore(ORIGIN,'key',transport).restore(stub),REPORT)

    def test_missing_corrupt_chunks_fail_without_replacement(self):
        for mutation in ['delete','corrupt']:
            transport=MemoryTransport();store=a.ArchiveStore(ORIGIN,'key',transport)
            stub=store.put_verified('r',{'body':'A'*9000})
            path=next(k for k in transport.objects if '/chunks/' in k)
            if mutation=='delete':del transport.objects[path]
            else:transport.objects[path]=b'bad'
            with self.assertRaises(a.ArchiveError):store.restore(stub)
            if mutation=='corrupt':
                before=len(transport.calls)
                with self.assertRaises(a.ArchiveError):store.put_verified('next',{'body':'A'*9000})
                self.assertFalse(any(c[0]=='POST' for c in transport.calls[before:]))

    def test_manifest_paths_placeholders_and_metadata_rejected(self):
        blob,meta,chunks=a._prepare_chunks({'body':'A'*9000,'nested':[None,'B'*9000]})
        original=json.loads(gzip.decompress(blob))
        def check(manifest):
            raw=a._canonical(manifest);packed=gzip.compress(raw,mtime=0)
            m={**meta,'gzip_sha256':hashlib.sha256(packed).hexdigest(),'gzip_bytes':len(packed)}
            with self.assertRaises(a.ArchiveError):a._restore_chunks(packed,a.make_stub('r',m)[a.MARKER],lambda path,metadata:a._decode_chunk(chunks[path][0],metadata))
        bad=copy.deepcopy(original);bad['chunks'].append(copy.deepcopy(bad['chunks'][0]));check(bad)
        bad=copy.deepcopy(original);bad['chunks'][0]['path']=['missing'];check(bad)
        bad=copy.deepcopy(original);bad['chunks'][0]['path']=[True];check(bad)
        bad=copy.deepcopy(original);bad['chunks'][0]['object_path']='chunks/../escape';check(bad)
        bad=copy.deepcopy(original);bad['skeleton']['body']='not-null';check(bad)
        bad=copy.deepcopy(original);bad['chunks'][0]['metadata']['raw_sha256']='0'*64;check(bad)
        bad=copy.deepcopy(original);bad['chunks'].pop();check(bad)
        bad=copy.deepcopy(original);bad['skeleton']['extra']='changed';check(bad)
        with patch.object(a,'MAX_CHUNK_REFS',1):
            with self.assertRaises(a.ArchiveError):a._restore_chunks(blob,a.make_stub('r',meta)[a.MARKER],lambda *_:'')
        with patch.object(a,'MAX_PATH_DEPTH',1):
            with self.assertRaises(a.ArchiveError):a.estimate_report({'nested':{'body':'x'*9000}})

if __name__=='__main__':unittest.main()
