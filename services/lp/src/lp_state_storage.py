"""Lossless private state encoding; public/reviewer SQL fields remain plain."""
import base64
import binascii
import gzip
import hashlib
import json
import re
import zlib

MARKER = '_lp_state_evidence'
MAX_RAW_BYTES = 256 * 1024 * 1024
MAX_COMPRESSED_BYTES = 50 * 1024 * 1024
# These cumulative receipts are consumed after baseline hydration, never by SQL.
EVIDENCE_KEYS = frozenset({'accepted_notices', 'tracked_notices', 'priority_notices',
                          'supporting_notices', 'shared_notices', 'institution_notices'})


def _json(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict:
            if any(type(k) is not str for k in item):
                raise ValueError('state keys must be strings')
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise ValueError('state contains a non-JSON value')
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _copy(state):
    if type(state) is not dict:
        raise ValueError('state must be an object')
    return json.loads(_json(state))


def unpack_state(state):
    state = _copy(state)
    if MARKER not in state:
        return state
    meta = state.pop(MARKER)
    fields = {'version', 'codec', 'raw_sha256', 'raw_bytes', 'gzip_sha256', 'gzip_bytes', 'payload'}
    if (type(meta) is not dict or set(meta) != fields or type(meta['version']) is not int
            or meta['version'] != 1 or meta['codec'] != 'json-gzip-base64-v1'):
        raise ValueError('invalid state evidence descriptor')
    for key, limit in [('raw_bytes', MAX_RAW_BYTES), ('gzip_bytes', MAX_COMPRESSED_BYTES)]:
        if type(meta[key]) is not int or not 0 < meta[key] <= limit:
            raise ValueError('state evidence size exceeds bounds')
    for key in ('raw_sha256', 'gzip_sha256'):
        if type(meta[key]) is not str or not re.fullmatch('[0-9a-f]{64}', meta[key]):
            raise ValueError('invalid state evidence checksum')
    value = meta['payload']
    if type(value) is not str or len(value) != 4 * ((meta['gzip_bytes'] + 2) // 3):
        raise ValueError('invalid state evidence base64 size')
    try:
        blob = base64.b64decode(value.encode('ascii'), validate=True)
    except (UnicodeError, binascii.Error, ValueError):
        raise ValueError('invalid state evidence base64') from None
    if (len(blob) != meta['gzip_bytes'] or hashlib.sha256(blob).hexdigest() != meta['gzip_sha256']
            or base64.b64encode(blob).decode('ascii') != value):
        raise ValueError('state evidence compressed checksum mismatch')
    try:
        decoder = zlib.decompressobj(31)
        raw = decoder.decompress(blob, meta['raw_bytes'] + 1)
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('invalid state evidence gzip boundary')
    except zlib.error:
        raise ValueError('invalid state evidence gzip') from None
    if len(raw) != meta['raw_bytes'] or hashlib.sha256(raw).hexdigest() != meta['raw_sha256']:
        raise ValueError('state evidence raw checksum mismatch')
    try:
        evidence = json.loads(raw)
        valid = (type(evidence) is dict and bool(evidence) and set(evidence) <= EVIDENCE_KEYS
                 and not set(evidence) & set(state) and _json(evidence) == raw)
    except (ValueError, UnicodeError):
        raise ValueError('invalid state evidence JSON') from None
    if not valid:
        raise ValueError('invalid or overlapping state evidence keys')
    state.update(evidence)
    return state


def pack_state(state):
    state = unpack_state(state)
    evidence = {key: state.pop(key) for key in sorted(EVIDENCE_KEYS) if key in state}
    if not evidence:
        return state
    raw = _json(evidence)
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError('state evidence raw size exceeds bounds')
    blob = gzip.compress(raw, mtime=0)
    if len(blob) > MAX_COMPRESSED_BYTES:
        raise ValueError('state evidence compressed size exceeds bounds')
    state[MARKER] = {'version': 1, 'codec': 'json-gzip-base64-v1',
                     'raw_sha256': hashlib.sha256(raw).hexdigest(), 'raw_bytes': len(raw),
                     'gzip_sha256': hashlib.sha256(blob).hexdigest(), 'gzip_bytes': len(blob),
                     'payload': base64.b64encode(blob).decode('ascii')}
    return state
