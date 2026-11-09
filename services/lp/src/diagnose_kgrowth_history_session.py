"""One normal anonymous notice-to-file control, never a failed-collector resume.

Injected fetch(url, kind) returns bytes, or {'raw': bytes,
'set_cookie_seen': bool}. Cookie values and HTTP headers are never retained.
The production transport makes one attempt per phase and follows no redirects.
"""
import argparse
import base64
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener

try:
    from .collect_kgrowth_history_attachments import validate_report, read_attachment, MAX_FILE_BYTES
    from .collect_lp_history_bodies import read_body
    from .lp_kgrowth_history_attachment_queue import file_labels, validate_url
    from .lp_history_sources import canonical_url
    from .kgrowth_listing import LIST_URL
except ImportError:
    from collect_kgrowth_history_attachments import validate_report, read_attachment, MAX_FILE_BYTES
    from collect_lp_history_bodies import read_body
    from lp_kgrowth_history_attachment_queue import file_labels, validate_url
    from lp_history_sources import canonical_url
    from kgrowth_listing import LIST_URL

KIND = 'kgrowth_history_session_control_v1'
MAX_BODY_BYTES = 12 * 1024 * 1024
MAX_INPUT_BYTES = 150 * 1024 * 1024


class ControlError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class PublicHTTPError(ControlError):
    def __init__(self, raw, status, set_cookie_seen=False):
        super().__init__('public_http_error')
        self.raw, self.status, self.set_cookie_seen = raw, status, set_cookie_seen


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _validate_url(url, kind, row):
    if kind == 'body':
        if url != canonical_url(row['source_id'], 'kgrowth'):
            raise ControlError('unexpected_public_notice_url')
    elif kind == 'file':
        validate_url(url, row['source_id'])
        if url != row['attachment_url']:
            raise ControlError('unexpected_public_file_url')
    else:
        raise ControlError('unexpected_public_session_phase')


class PublicRedirects(HTTPRedirectHandler):
    def __init__(self, row):
        super().__init__()
        self.row, self.kind = copy.deepcopy(row), None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(req.full_url, self.kind, self.row)
        _validate_url(newurl, self.kind, self.row)
        # This two-request experiment does not expand into redirect navigation.
        raise ControlError('public_session_redirect_rejected')


class PublicSession:
    def __init__(self, row):
        self.row = copy.deepcopy(row)
        _validate_url(row['source_url'], 'body', row)
        _validate_url(row['attachment_url'], 'file', row)
        self.redirects = PublicRedirects(row)
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()), self.redirects)
        self.calls = []

    def __call__(self, url, kind):
        _validate_url(url, kind, self.row)
        expected = 'body' if not self.calls else 'file' if self.calls == ['body'] else None
        if kind != expected:
            raise ControlError('public_session_request_limit')
        self.calls.append(kind)
        self.redirects.kind = kind
        limit = MAX_BODY_BYTES if kind == 'body' else MAX_FILE_BYTES
        referer = LIST_URL if kind == 'body' else self.row['source_url']
        request = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': referer,
                                        'Accept-Encoding': 'identity'})
        try:
            with self.opener.open(request, timeout=25) as response:
                _validate_url(response.geturl(), kind, self.row)
                raw = response.read(limit + 1)
                seen = bool(response.headers.get('Set-Cookie'))
                status = getattr(response, 'status', 200)
                if status != 200:
                    raise PublicHTTPError(raw, status, seen)
                return {'raw': raw, 'set_cookie_seen': seen}
        except HTTPError as error:
            _validate_url(error.geturl(), kind, self.row)
            raw = error.read(limit + 1)
            raise PublicHTTPError(raw, error.code, bool((error.headers or {}).get('Set-Cookie'))) from None


def _blocked(text):
    compact = re.sub(r'\s+', '', text)
    return any(marker in compact for marker in ('비정상적인접근', '로그인이필요', '로그인후이용',
                                               '접근권한이없', '열람권한이없', '접근이제한', '비공개게시물'))


def _report(checked_at=None):
    return {'kind': KIND, 'checked_at': checked_at or datetime.now(timezone.utc).isoformat(),
            'success': False, 'stage': 'preflight', 'original_failure': None, 'source': None,
            'requests': {'body': 0, 'file': 0}, 'responses': {}, 'errors': [],
            'cookie_hypothesis': 'unverified', 'collector_resumed': False,
            'database_writes': 0, 'published': False, 'pe_approval': False, 'selected_gp_approval': False,
            'source_history_complete': False}


def control(history, bodies, failed, fetch=None, *, checked_at=None):
    report = _report(checked_at)
    def retain(raw, kind, url, seen=False, status=200):
        limit = MAX_BODY_BYTES if kind == 'body' else MAX_FILE_BYTES
        if not isinstance(raw, bytes) or type(seen) is not bool:
            raise ControlError('invalid_public_session_response')
        prefix = raw[:limit]
        report['responses'][kind] = {'url': url, 'bytes': len(prefix), 'sha256': sha(prefix),
                                      'raw_base64': base64.b64encode(prefix).decode('ascii'),
                                      'set_cookie_seen': seen, 'http_status': status,
                                      'truncated': len(raw) > limit}
        if not raw or len(raw) > limit:
            raise ControlError('public_session_response_size_limit')
        return raw

    def request(url, kind):
        _validate_url(url, kind, row)
        report['stage'] = kind
        report['requests'][kind] += 1
        try:
            value = get(url, kind)
        except PublicHTTPError as error:
            retain(error.raw, kind, url, error.set_cookie_seen, error.status)
            raise
        if isinstance(value, bytes):
            return retain(value, kind, url)
        if not isinstance(value, dict) or set(value) != {'raw', 'set_cookie_seen'}:
            raise ControlError('invalid_public_session_response')
        return retain(value['raw'], kind, url, value['set_cookie_seen'])

    try:
        stamp = datetime.fromisoformat(report['checked_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ControlError('invalid_observation_time')
        q = validate_report(history, bodies, failed)
        if (q['holds'] or not q['rows'] or len(failed['holds']) != 1
                or 'failed_response' not in failed):
            raise ControlError('saved_abnormal_access_failure_required')
        row = q['rows'][0]
        failure = failed['failed_response']
        held = failed['holds'][0]
        if any(held.get(k) != row[k] or failure.get(k) != row[k] for k in ('source_id', 'attachment_url')):
            raise ControlError('saved_failure_queue_identity_differs')
        raw = base64.b64decode(failure['raw_base64'], validate=True)
        denied = raw.decode('cp949')
        if (len(raw) > MAX_FILE_BYTES or sha(raw) != failure['sha256']
                or not re.search(r'<script\b', denied, re.I)
                or '비정상적인접근' not in re.sub(r'\s+', '', denied)):
            raise ControlError('saved_abnormal_access_script_required')
        report['original_failure'] = {'state_sha256': sha(json.dumps(failed, sort_keys=True, ensure_ascii=False).encode()),
                                      'response_sha256': failure['sha256'], 'response_bytes': len(raw)}
        report['source'] = copy.deepcopy(row)
        old = next(n for n in bodies['documents'] if n['source_id'] == row['source_id'])
        labels = file_labels(old)
        get = fetch if fetch is not None else PublicSession(row)
        new_raw = request(row['source_url'], 'body')
        if _blocked(new_raw.decode('cp949')):
            raise ControlError('public_notice_blocked')
        parsed = read_body(row['source_id'], new_raw, 'kgrowth')
        if any(parsed[k] != old[k] for k in ('source_id', 'url', 'title', 'date', 'body', 'sha256', 'attachments')):
            raise ControlError('public_notice_continuity_mismatch')
        current = {**parsed, 'discovery_provenance': {**old['discovery_provenance'],
                    'detail_response_base64': base64.b64encode(new_raw).decode('ascii'),
                    'detail_response_sha256': sha(new_raw)}}
        if file_labels(current) != labels:
            raise ControlError('public_file_labels_changed')
        report['body_continuity'] = {'semantic_sha256': parsed['sha256'], 'all_attachment_labels_unchanged': True,
                                      'original_response_sha256': old['discovery_provenance']['detail_response_sha256'],
                                      'control_response_sha256': sha(new_raw)}
        new_file = request(row['attachment_url'], 'file')
        # HTML/script denials are never retried or interpreted as document bodies.
        if _blocked(new_file[:4096].decode('cp949', errors='ignore')):
            raise ControlError('public_file_blocked')
        extracted = read_attachment(new_file)
        if _blocked(extracted['text'][:4096]):
            raise ControlError('public_file_protected')
        report['extracted'] = extracted
        report['success'] = True
        report['stage'] = 'complete'
        report['cookie_hypothesis'] = 'normal_session_file_read_succeeded_cause_not_isolated'
    except Exception as error:
        # Exception messages can include request headers/cookies; retain only
        # safe internal codes and exception class names.
        report['errors'].append({'stage': report['stage'], 'type': type(error).__name__,
                                  'code': error.code if isinstance(error, ControlError) else 'control_failed'})
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('listing-state', 'body-state', 'failed-state', 'output-dir'):
        p.add_argument('--' + name, type=Path, required=True)
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    def load(path):
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ControlError('control_input_size_limit')
        return json.loads(path.read_text())
    try:
        report = control(load(args.listing_state), load(args.body_state), load(args.failed_state))
    except Exception as error:
        report = _report()
        report['errors'] = [{'stage': 'preflight', 'type': type(error).__name__, 'code': 'invalid_control_input'}]
    target = args.output_dir / 'session-control.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False))
    temporary.replace(target)
    print(json.dumps({k: report[k] for k in ('kind', 'success', 'stage', 'requests')}))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
