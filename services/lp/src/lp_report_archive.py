"""Private immutable report archives, verified before a database stub is returned.

Injected transport: (method, url, headers, body, max_bytes, timeout) ->
(status_code, response_bytes). The default transport rejects all redirects.
This module never changes a database or deletes an object/report.
"""
from __future__ import annotations
import gzip
import io
import hashlib
import json
import re
import zlib
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

BUCKET = 'lp-collection-reports'
MAX_RAW_BYTES = 256 * 1024 * 1024
MAX_COMPRESSED_BYTES = 50 * 1024 * 1024
MAX_CONTROL_BYTES = 64 * 1024
TIMEOUT = 60
MARKER = '_lp_report_archive'
_META = {'version', 'codec', 'raw_sha256', 'gzip_sha256', 'raw_bytes', 'gzip_bytes'}
_LOCATOR = _META | {'bucket', 'object_path'}


class ArchiveError(ValueError):
    """Sanitized failure: callers retain the original database report."""


def _canonical(report):
    if not isinstance(report, dict):
        raise ArchiveError('archive report must be an object')
    try:
        pending, visited = [report], set()
        while pending:
            value = pending.pop()
            if isinstance(value, (dict, list)):
                if id(value) in visited:
                    continue
                visited.add(id(value))
                if isinstance(value, dict):
                    if any(not isinstance(k, str) for k in value):
                        raise ValueError()
                    pending.extend(value.values())
                else:
                    pending.extend(value)
            elif value is not None and type(value) not in (str, int, float, bool):
                raise ValueError()
        return json.dumps(report, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ArchiveError('archive report is not canonical JSON') from None


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _metadata(metadata, locator=False):
    keys = _LOCATOR if locator else _META
    if not isinstance(metadata, dict) or set(metadata) != keys:
        raise ArchiveError('invalid archive metadata schema')
    if type(metadata['version']) is not int or (metadata['version'], metadata['codec']) not in {(1,'json-gzip-v1'),(2,'json-chunks-gzip-v2')}:
        raise ArchiveError('unsupported archive format')
    for field in ('raw_sha256', 'gzip_sha256'):
        if not isinstance(metadata[field], str) or not re.fullmatch('[0-9a-f]{64}', metadata[field]):
            raise ArchiveError('invalid archive checksum metadata')
    for field, limit in (('raw_bytes', MAX_RAW_BYTES), ('gzip_bytes', MAX_COMPRESSED_BYTES)):
        if type(metadata[field]) is not int or not 0 < metadata[field] <= limit:
            raise ArchiveError('invalid archive size metadata')
    if locator:
        if metadata['bucket'] != BUCKET or not isinstance(metadata['object_path'], str):
            raise ArchiveError('invalid archive bucket or path')
        suffix = r'\.json\.gz' if metadata['version']==1 else r'\.manifest\.json\.gz'
        match = re.fullmatch(r'runs/([A-Za-z0-9][A-Za-z0-9_-]{0,127})/([0-9a-f]{64})'+suffix, metadata['object_path'])
        if not match or match[2] != metadata['raw_sha256']:
            raise ArchiveError('archive path does not match content checksum')
    return dict(metadata)


def encode_report(report):
    if isinstance(report, dict) and MARKER in report:
        raise ArchiveError('cannot archive an archive descriptor')
    raw = _canonical(report)
    if len(raw) > MAX_RAW_BYTES:
        raise ArchiveError('archive raw report exceeds limit')
    blob = gzip.compress(raw, mtime=0)
    if len(blob) > MAX_COMPRESSED_BYTES:
        raise ArchiveError('compressed archive exceeds limit')
    metadata = {'version': 1, 'codec': 'json-gzip-v1', 'raw_sha256': _sha(raw),
                'gzip_sha256': _sha(blob), 'raw_bytes': len(raw), 'gzip_bytes': len(blob)}
    return blob, metadata


def decode_report(blob, metadata):
    if not isinstance(metadata, dict):
        raise ArchiveError('invalid archive metadata schema')
    m = _metadata(metadata, locator=('object_path' in metadata or 'bucket' in metadata))
    if m['version'] != 1:raise ArchiveError('chunked archives require verified chunk retrieval')
    if not isinstance(blob, bytes) or len(blob) != m['gzip_bytes'] or _sha(blob) != m['gzip_sha256']:
        raise ArchiveError('compressed archive length or checksum differs')
    try:
        reader = zlib.decompressobj(16 + zlib.MAX_WBITS)
        raw = reader.decompress(blob, m['raw_bytes'] + 1)
        if len(raw) != m['raw_bytes'] or not reader.eof or reader.unused_data or reader.unconsumed_tail:
            raise ArchiveError('archive decompression size or stream differs')
    except zlib.error:
        raise ArchiveError('archive compressed stream is invalid') from None
    if _sha(raw) != m['raw_sha256']:
        raise ArchiveError('archive raw checksum differs')
    try:
        report = json.loads(raw.decode('utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise ArchiveError('archive JSON is invalid') from None
    if not isinstance(report, dict) or MARKER in report or _canonical(report) != raw:
        raise ArchiveError('archive report schema or canonical encoding differs')
    return report


def make_stub(run_id, metadata):
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', run_id):
        raise ArchiveError('unsafe archive run identifier')
    m = _metadata(metadata)
    return {MARKER: {**m, 'bucket': BUCKET,
                    'object_path': 'runs/' + run_id + '/' + m['raw_sha256'] + ('.json.gz' if m['version']==1 else '.manifest.json.gz')}}


def validate_locator(stub, run_id=None):
    if not isinstance(stub, dict) or set(stub) != {MARKER}:
        raise ArchiveError('invalid archive stub schema')
    descriptor = _metadata(stub[MARKER], locator=True)
    if run_id is not None:
        expected = make_stub(run_id, {k: descriptor[k] for k in _META})
        if expected != stub:
            raise ArchiveError('archive belongs to another run')
    return descriptor


def is_archive_stub(value):
    if not isinstance(value, dict) or MARKER not in value:
        return False
    validate_locator(value)
    return True


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ArchiveError('archive storage redirect rejected')


def _transport(method, url, headers, body, max_bytes, timeout):
    request = Request(url, data=body, headers=headers, method=method)
    try:
        response = build_opener(_NoRedirect()).open(request, timeout=timeout)
    except HTTPError as error:
        response = error
    try:
        with response:
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise ArchiveError('archive storage response exceeds limit')
            return response.code, raw
    except ArchiveError:
        raise
    except Exception:
        raise ArchiveError('archive storage transport failed') from None


def _missing(status, raw):
    if status == 404:
        return True
    if status != 400:
        return False
    try:
        error = json.loads(raw)
        return (isinstance(error, dict) and str(error.get('statusCode')) == '404'
                and error.get('error', error.get('code')) in {'not_found', 'NoSuchKey', 'NoSuchBucket'})
    except (ValueError, UnicodeError):
        return False


def _safe_http_failure(label, status, raw):
    # Provider errors can contain credentials/URLs. Retain only numeric status
    # and a fixed vocabulary, never the response body or arbitrary message.
    details = [f'HTTP {status}']
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            code = str(payload.get('statusCode', ''))
            if code.isascii() and code.isdigit() and 100 <= int(code) <= 599:
                details.append('statusCode ' + code)
            error = payload.get('error', payload.get('code'))
            known = {'not_found', 'NoSuchKey', 'NoSuchBucket', 'Bucket not found',
                     'Not Found', 'Unauthorized', 'InvalidJWT', 'AccessDenied'}
            if isinstance(error, str) and error in known:
                details.append(error)
    except (ValueError, UnicodeError):
        pass
    return ArchiveError(label + ' (' + ', '.join(details) + ')')


class ArchiveStore:
    def __init__(self, base_url, key, transport=None):
        if not isinstance(base_url, str) or not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co', base_url):
            raise ArchiveError('archive storage requires a Supabase HTTPS origin')
        if not isinstance(key, str) or not key or re.search(r'[\x00-\x20\x7f]', key):
            raise ArchiveError('archive storage credentials unavailable')
        self._origin, self._key = base_url, key
        self._transport = transport or _transport

    def _request(self, method, path, body=None, limit=MAX_CONTROL_BYTES, extra=None):
        if not path.startswith('/storage/v1/') or '..' in path or '%' in path or '?' in path or '#' in path:
            raise ArchiveError('invalid archive storage route')
        headers = {'Authorization': 'Bearer ' + self._key, 'apikey': self._key,
                   'Accept-Encoding': 'identity'}
        if extra:
            headers.update(extra)
        try:
            status, raw = self._transport(method, self._origin + path, headers, body, limit, TIMEOUT)
            if type(status) is not int or not isinstance(raw, bytes) or len(raw) > limit:
                raise ArchiveError('invalid archive storage response')
            if 300 <= status < 400:
                raise ArchiveError('archive storage redirect rejected')
            return status, raw
        except Exception:
            raise ArchiveError('archive storage request failed') from None

    def ensure_private_bucket(self):
        path = '/storage/v1/bucket/' + BUCKET
        status, raw = self._request('GET', path)
        if _missing(status, raw):
            status, _ = self._request('POST', '/storage/v1/bucket',
                json.dumps({'id': BUCKET, 'name': BUCKET, 'public': False}).encode(),
                extra={'Content-Type': 'application/json'})
            if status not in (200, 201, 409):
                raise ArchiveError('private archive bucket creation failed')
            status, raw = self._request('GET', path)
        if status != 200:
            raise _safe_http_failure('archive bucket verification failed', status, raw)
        try:
            bucket = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ArchiveError('invalid archive bucket response') from None
        if not isinstance(bucket, dict) or bucket.get('id') != BUCKET or bucket.get('public') is not False:
            raise ArchiveError('archive bucket is not verified private')
        return True

    def _download(self, descriptor):
        status, blob = self._request('GET', '/storage/v1/object/authenticated/' + BUCKET + '/' + descriptor['object_path'],
                                     limit=descriptor['gzip_bytes'])
        if status != 200:
            raise ArchiveError('archive object download failed')
        return blob

    def _put_object(self, path, blob):
        status, response = self._request('POST', '/storage/v1/object/' + BUCKET + '/' + path, blob,
            extra={'Content-Type': 'application/gzip', 'x-upsert': 'false'})
        duplicate = False
        if status == 400:
            try:
                error = json.loads(response)
                duplicate = isinstance(error, dict) and error.get('message') == 'The resource already exists' and error.get('error') == 'Duplicate' and str(error.get('statusCode')) == '409'
                duplicate = duplicate or (isinstance(error, dict) and error.get('message') == 'Asset already exists' and (error.get('code') == 'Duplicate' or error.get('error') == 'Duplicate'))
            except (ValueError, UnicodeError):
                pass
        if status not in (200, 201, 409) and not duplicate:
            raise ArchiveError('immutable archive upload failed')

    def _chunk(self, path, meta):
        status, blob = self._request('GET', '/storage/v1/object/authenticated/' + BUCKET + '/' + path,
            limit=max(MAX_CONTROL_BYTES, meta['gzip_bytes']))
        if status != 200:raise ArchiveError('archive chunk download failed')
        return _decode_chunk(blob, meta)

    def put_verified(self, run_id, report):
        manifest, metadata, chunks = _prepare_chunks(report)
        stub = make_stub(run_id, metadata)
        descriptor = validate_locator(stub, run_id)
        self.ensure_private_bucket()
        status, existing = self._request('GET', '/storage/v1/object/authenticated/' + BUCKET + '/' + descriptor['object_path'],
                                         limit=MAX_COMPRESSED_BYTES)
        if status == 200:
            # The gzip bitstream may differ after a Python/zlib upgrade. The
            # immutable path identifies plaintext, which is still fully checked.
            actual = {**metadata, 'gzip_sha256': _sha(existing), 'gzip_bytes': len(existing)}
            stored_stub = make_stub(run_id, actual)
            restored = _restore_chunks(existing, validate_locator(stored_stub, run_id), self._chunk)
            if _canonical(restored) != _canonical(report):
                raise ArchiveError('existing archive differs from source report')
            return stored_stub
        if not _missing(status, existing):
            raise ArchiveError('archive manifest lookup failed')
        actual_chunks = {}
        for path, (blob, meta) in chunks.items():
            status, existing = self._request('GET', '/storage/v1/object/authenticated/' + BUCKET + '/' + path,
                                             limit=MAX_COMPRESSED_BYTES)
            if _missing(status, existing):
                self._put_object(path, blob)
                self._chunk(path, meta)
                actual_chunks[path] = meta
            elif status == 200:
                actual = {**meta, 'gzip_sha256': _sha(existing), 'gzip_bytes': len(existing)}
                _decode_chunk(existing, actual)
                actual_chunks[path] = actual
            else:
                raise ArchiveError('archive chunk lookup failed')
        content = json.loads(gzip.decompress(manifest))
        for ref in content['chunks']:
            ref['metadata'] = actual_chunks[ref['object_path']]
        manifest = _compress_chunk(_canonical(content))
        metadata.update(gzip_sha256=_sha(manifest), gzip_bytes=len(manifest))
        stub = make_stub(run_id, metadata)
        descriptor = validate_locator(stub, run_id)
        self._put_object(descriptor['object_path'], manifest)
        restored = _restore_chunks(self._download(descriptor), descriptor, self._chunk)
        if _canonical(restored) != _canonical(report):
            raise ArchiveError('archive readback differs from source report')
        return stub

    def assert_private(self, stub, public_key):
        descriptor = validate_locator(stub)
        if public_key == self._key:
            raise ArchiveError('archive denial probe requires an unprivileged key')
        reader = ArchiveStore(self._origin, public_key, self._transport)
        status, raw = reader._request('GET', '/storage/v1/object/authenticated/' + BUCKET + '/' + descriptor['object_path'],
                                      limit=MAX_COMPRESSED_BYTES)
        if status in (403, 404) or _missing(status, raw):
            return status
        raise ArchiveError('archive is not proven inaccessible to public readers')

    def restore(self, stub):
        descriptor = validate_locator(stub)
        self.ensure_private_bucket()
        blob = self._download(descriptor)
        if descriptor['version']==1:return decode_report(blob, descriptor)
        return _restore_chunks(blob, descriptor, self._chunk)


CHUNK_THRESHOLD = 8192
MAX_CHUNK_REFS = 10000
MAX_PATH_DEPTH = 100
_CHUNK_FIELDS = {'raw_sha256','gzip_sha256','raw_bytes','gzip_bytes'}

def _chunk_metadata(meta):
    if not isinstance(meta,dict) or set(meta)!=_CHUNK_FIELDS:raise ArchiveError('invalid chunk metadata')
    _metadata({**meta,'version':1,'codec':'json-gzip-v1'})
    return meta

def _unpack(blob, meta, raw_limit):
    if not isinstance(blob,bytes) or len(blob)!=meta['gzip_bytes'] or _sha(blob)!=meta['gzip_sha256']:
        raise ArchiveError('chunk or manifest compressed checksum differs')
    try:
        reader=zlib.decompressobj(16+zlib.MAX_WBITS)
        raw=reader.decompress(blob,raw_limit+1)
        if len(raw)>raw_limit or not reader.eof or reader.unused_data or reader.unconsumed_tail:
            raise ArchiveError('chunk or manifest decompression bound exceeded')
    except zlib.error:raise ArchiveError('invalid chunk or manifest gzip') from None
    return raw

def _decode_chunk(blob, meta):
    _chunk_metadata(meta)
    raw=_unpack(blob,meta,meta['raw_bytes'])
    if len(raw)!=meta['raw_bytes'] or _sha(raw)!=meta['raw_sha256']:raise ArchiveError('chunk raw checksum differs')
    try:return raw.decode('utf-8')
    except UnicodeError:raise ArchiveError('chunk text is not UTF8') from None

def _compress_chunk(raw):
    # GzipFile has a stable OS-neutral header across supported Python runtimes.
    output=io.BytesIO()
    with gzip.GzipFile(filename='',mode='wb',compresslevel=9,fileobj=output,mtime=0) as writer:
        writer.write(raw)
    return output.getvalue()

def _prepare_chunks(report):
    if isinstance(report,dict) and MARKER in report:raise ArchiveError('cannot archive an archive descriptor')
    original_raw=_canonical(report)
    if len(original_raw)>MAX_RAW_BYTES:raise ArchiveError('archive raw report exceeds limit')
    original_meta={'raw_sha256':_sha(original_raw),'raw_bytes':len(original_raw)}
    # JSON round trip gives a detached skeleton with no alias/collision marker.
    skeleton=json.loads(original_raw)
    refs=[];chunks={}
    pending=[(skeleton,[])]
    while pending:
        value,path=pending.pop()
        if len(path)>MAX_PATH_DEPTH:raise ArchiveError('archive path depth exceeded')
        if isinstance(value,dict):items=list(value.items())
        elif isinstance(value,list):items=list(enumerate(value))
        else:continue
        for key,item in items:
            child=path+[key]
            if len(child)>MAX_PATH_DEPTH:raise ArchiveError('archive path depth exceeded')
            if isinstance(item,str) and len(item.encode('utf-8'))>=CHUNK_THRESHOLD:
                raw=item.encode('utf-8');sha=_sha(raw);object_path='chunks/'+sha+'.txt.gz'
                if object_path not in chunks:
                    blob=_compress_chunk(raw)
                    meta={'raw_sha256':sha,'gzip_sha256':_sha(blob),'raw_bytes':len(raw),'gzip_bytes':len(blob)}
                    _chunk_metadata(meta);chunks[object_path]=(blob,meta)
                refs.append({'path':child,'object_path':object_path,'metadata':dict(chunks[object_path][1])})
                if len(refs)>MAX_CHUNK_REFS:raise ArchiveError('too many archive chunk references')
                value[key]=None
            elif isinstance(item,(dict,list)):pending.append((item,child))
    raw_manifest=_canonical({'version':2,'skeleton':skeleton,'chunks':refs})
    if len(raw_manifest)>MAX_RAW_BYTES:raise ArchiveError('archive manifest exceeds limit')
    blob=_compress_chunk(raw_manifest)
    metadata={**original_meta,'version':2,'codec':'json-chunks-gzip-v2','gzip_sha256':_sha(blob),'gzip_bytes':len(blob)}
    _metadata(metadata)
    return blob,metadata,chunks

def estimate_report(report):
    """Upper bound for new compressed object bytes; existing chunks can reduce it."""
    blob,_,chunks=_prepare_chunks(report)
    return len(blob)+sum(len(value[0]) for value in chunks.values())

def _restore_chunks(blob,descriptor,get_chunk):
    _metadata(descriptor,locator=True)
    raw=_unpack(blob,descriptor,MAX_RAW_BYTES)
    try:manifest=json.loads(raw.decode('utf-8'))
    except (ValueError,UnicodeError,RecursionError):raise ArchiveError('invalid archive manifest JSON') from None
    if not isinstance(manifest,dict) or set(manifest)!={'version','skeleton','chunks'} or type(manifest['version']) is not int or manifest['version']!=2 or _canonical(manifest)!=raw:
        raise ArchiveError('invalid archive manifest schema')
    report=manifest['skeleton'];refs=manifest['chunks']
    if not isinstance(report,dict) or not isinstance(refs,list) or len(refs)>MAX_CHUNK_REFS:raise ArchiveError('invalid archive skeleton or references')
    paths=set();prefixes=set();cache={};aggregate=0
    # Validate all references before downloading any chunks.
    for ref in refs:
        if not isinstance(ref,dict) or set(ref)!={'path','object_path','metadata'}:raise ArchiveError('invalid chunk reference schema')
        path=ref['path'];meta=_chunk_metadata(ref['metadata'])
        if not isinstance(path,list) or not 1<=len(path)<=MAX_PATH_DEPTH or any(type(k) not in (str,int) or (type(k) is int and k<0) for k in path):raise ArchiveError('invalid chunk path')
        tokens=tuple((type(k).__name__,k) for k in path)
        if tokens in paths or tokens in prefixes or any(tokens[:i] in paths for i in range(1,len(tokens))):raise ArchiveError('duplicate or overlapping chunk paths')
        paths.add(tokens);prefixes.update(tokens[:i] for i in range(1,len(tokens)))
        if ref['object_path']!='chunks/'+meta['raw_sha256']+'.txt.gz':raise ArchiveError('chunk path does not match checksum')
        aggregate+=meta['raw_bytes']
        if aggregate>MAX_RAW_BYTES:raise ArchiveError('aggregate restored chunks exceed limit')
        node=report
        for k in path:
            if isinstance(node,dict) and type(k) is str and k in node:node=node[k]
            elif isinstance(node,list) and type(k) is int and k<len(node):node=node[k]
            else:raise ArchiveError('chunk path does not exist in skeleton')
        if node is not None:raise ArchiveError('chunk placeholder is not null')
        if ref['object_path'] in cache and cache[ref['object_path']]!=meta:raise ArchiveError('conflicting repeated chunk metadata')
        cache[ref['object_path']]=meta
    decoded={};restored_size=len(_canonical(report))
    for ref in refs:
        name=ref['object_path']
        if name not in decoded:decoded[name]=get_chunk(name,ref['metadata'])
        restored_size+=len(json.dumps(decoded[name],ensure_ascii=False,separators=(',',':')).encode('utf-8'))-4
        if restored_size>MAX_RAW_BYTES:raise ArchiveError('restored report exceeds aggregate limit')
        node=report
        for k in ref['path'][:-1]:node=node[k]
        node[ref['path'][-1]]=decoded[name]
    raw_report=_canonical(report)
    if MARKER in report or len(raw_report)!=descriptor['raw_bytes'] or _sha(raw_report)!=descriptor['raw_sha256']:
        raise ArchiveError('restored report full checksum differs')
    return report
