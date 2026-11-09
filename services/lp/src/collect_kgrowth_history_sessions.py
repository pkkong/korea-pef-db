"""Bounded KGrowth body-to-file anonymous sessions; no PE/public approval.

V1 typed file documents stay byte-for-byte compatible. Fresh session responses
live in this v2 artifact, not in the database document or public read model.
Injected fetch(url, kind) is an offline/test transport: bytes or exactly
{'raw': bytes, 'set_cookie_seen': bool}. Its actual network attempts are zero
unless it exposes an attempts={'body': int, 'file': int} counter. Production
counts actual opener.open calls and makes one attempt per phase, no redirects.
"""
import argparse
import base64
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import collect_kgrowth_history_attachments as files
    from . import diagnose_kgrowth_history_session as control
    from .collect_lp_history_bodies import read_body, retain_documents
    from .lp_kgrowth_history_attachment_queue import plan, file_labels
    from .lp_history_sources import listing_digest
except ImportError:
    import collect_kgrowth_history_attachments as files
    import diagnose_kgrowth_history_session as control
    from collect_lp_history_bodies import read_body, retain_documents
    from lp_kgrowth_history_attachment_queue import plan, file_labels
    from lp_history_sources import listing_digest

KIND = 'kgrowth_history_sessions_v2'
SESSION_KIND = 'kgrowth_history_file_session_v2'
MAX_REPORT_BYTES = 150 * 1024 * 1024
MAX_BODY_BYTES = control.MAX_BODY_BYTES
MAX_FILE_BYTES = files.MAX_FILE_BYTES
document = files.document


def _json(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError('Historical session input/report exceeds size limit')
    return raw


def _stored(conn, bodies, row, record):
    # Keep publication/DB imports out of a pure offline collection/replay.
    try:
        from .adopt_kgrowth_session_file import _stored as guard
    except ImportError:
        from adopt_kgrowth_session_file import _stored as guard
    return guard(conn, bodies, row, record)


class PublicSession(control.PublicSession):
    """One ordinary anonymous cookie jar per source; count actual open calls."""
    def __init__(self, row):
        super().__init__(row)
        self.attempts = {'body': 0, 'file': 0}
        original, owner = self.opener, self
        class CountedOpener:
            def open(self, request, timeout):
                owner.attempts[owner.redirects.kind] += 1
                return original.open(request, timeout=timeout)
        self.opener = CountedOpener()


def _empty_v1(history):
    return {'kind': files.KIND, 'institution_id': 'kgrowth', 'window': copy.deepcopy(history['window']),
            'listing_digest': listing_digest(history), 'records': [], 'batches': [], 'holds': []}


def _records(report):
    return report['legacy_state']['records'] + report['records']


def _completed(report):
    return [files.receipt(r) for r in _records(report)]


def _start(history, bodies, previous):
    _json(history); _json(bodies)
    if previous is not None and not isinstance(previous, dict):
        raise ValueError('Historical session state must be an object')
    if previous is not None and previous.get('kind') == KIND:
        report = copy.deepcopy(previous)
        q = validate_report(history, bodies, report)
    else:
        legacy = copy.deepcopy(previous) if previous is not None else _empty_v1(history)
        q = files.validate_report(history, bodies, legacy)
        if legacy['holds'] or 'failed_response' in legacy:
            raise ValueError('Failed v1 state is terminal and cannot be resumed or cleared')
        report = {'kind': KIND, 'institution_id': 'kgrowth', 'window': copy.deepcopy(history['window']),
                  'listing_digest': listing_digest(history), 'legacy_state': legacy,
                  'records': [], 'batches': [], 'sessions': [], 'holds': []}
    if report['holds'] or q['holds']:
        raise ValueError('Saved or ambiguous session failure requires independent diagnosis')
    return report, q


def _pdf_version(raw):
    if raw.startswith(b'%PDF'):
        import pypdf
        if pypdf.__version__ != '6.10.0':
            raise control.ControlError('pdf_reader_version_mismatch')


def _session(bodies, row, fetch, checked_at):
    proof = {'kind': SESSION_KIND, 'source': copy.deepcopy(row), 'checked_at': checked_at,
             'success': False, 'stage': 'body', 'requests': {'body': 0, 'file': 0},
             'transport_attempts': {'body': 0, 'file': 0}, 'responses': {},
             'body_continuity': None, 'extracted': None, 'error': None}
    get = fetch if fetch is not None else PublicSession(row)

    def retain(raw, phase, url, seen=False, status=200):
        limit = MAX_BODY_BYTES if phase == 'body' else MAX_FILE_BYTES
        if not isinstance(raw, bytes) or type(seen) is not bool or type(status) is not int:
            raise control.ControlError('invalid_public_session_response')
        prefix = raw[:limit]
        proof['responses'][phase] = {'url': url, 'bytes': len(prefix), 'sha256': files.sha(prefix),
                                    'raw_base64': base64.b64encode(prefix).decode('ascii'),
                                    'set_cookie_seen': seen, 'http_status': status, 'truncated': len(raw) > limit}
        if not raw or len(raw) > limit:
            raise control.ControlError('public_session_response_size_limit')
        return raw

    def request(url, phase):
        control._validate_url(url, phase, row)
        proof['stage'] = phase
        proof['requests'][phase] += 1
        before = getattr(get, 'attempts', {}).get(phase, 0)
        try:
            value = get(url, phase)
        except control.PublicHTTPError as error:
            retain(error.raw, phase, url, error.set_cookie_seen, error.status)
            raise
        finally:
            after = getattr(get, 'attempts', {}).get(phase, before)
            if type(before) is not int or type(after) is not int or not 0 <= after - before <= 1:
                raise control.ControlError('invalid_public_transport_counter')
            proof['transport_attempts'][phase] = after - before
        if isinstance(value, bytes):
            return retain(value, phase, url)
        if not isinstance(value, dict) or set(value) != {'raw', 'set_cookie_seen'}:
            raise control.ControlError('invalid_public_session_response')
        return retain(value['raw'], phase, url, value['set_cookie_seen'])

    try:
        files._stamp(checked_at)
        old = next(n for n in bodies['documents'] if n['source_id'] == row['source_id'])
        labels = file_labels(old)
        raw = request(row['source_url'], 'body')
        if control._blocked(raw.decode('cp949')):
            raise control.ControlError('public_notice_blocked')
        parsed = read_body(row['source_id'], raw, 'kgrowth')
        if any(parsed[k] != old[k] for k in ('source_id', 'url', 'title', 'date', 'body', 'sha256', 'attachments')):
            raise control.ControlError('public_notice_continuity_mismatch')
        current = {**parsed, 'discovery_provenance': {**old['discovery_provenance'],
                   'detail_response_base64': base64.b64encode(raw).decode('ascii'),
                   'detail_response_sha256': files.sha(raw)}}
        if file_labels(current) != labels:
            raise control.ControlError('public_file_labels_changed')
        proof['body_continuity'] = {'semantic_sha256': parsed['sha256'], 'all_attachment_labels_unchanged': True,
                                    'original_response_sha256': old['discovery_provenance']['detail_response_sha256'],
                                    'session_response_sha256': files.sha(raw)}
        raw = request(row['attachment_url'], 'file')
        if control._blocked(raw[:4096].decode('cp949', errors='ignore')):
            raise control.ControlError('public_file_blocked')
        _pdf_version(raw)
        extracted = files.read_attachment(raw)
        if control._blocked(extracted['text'][:4096]):
            raise control.ControlError('public_file_protected')
        proof.update(success=True, stage='complete', extracted=extracted)
    except Exception as error:
        proof['error'] = error.code if isinstance(error, control.ControlError) else 'public_session_failed'
    return proof


def _response(value, limit):
    keys = {'url', 'bytes', 'sha256', 'raw_base64', 'set_cookie_seen', 'http_status', 'truncated'}
    if (not isinstance(value, dict) or set(value) != keys or type(value['bytes']) is not int
            or type(value['set_cookie_seen']) is not bool or type(value['truncated']) is not bool
            or type(value['http_status']) is not int or not 100 <= value['http_status'] <= 599
            or not isinstance(value['raw_base64'], str) or len(value['raw_base64']) > (limit + 2) // 3 * 4):
        raise ValueError('Invalid session response fields/size')
    raw = base64.b64decode(value['raw_base64'], validate=True)
    if (len(raw) > limit or len(raw) != value['bytes'] or files.sha(raw) != value['sha256']
            or base64.b64encode(raw).decode('ascii') != value['raw_base64']
            or (value['truncated'] and len(raw) != limit)):
        raise ValueError('Session response raw bytes/hash differ')
    return raw + (b'\0' if value['truncated'] else b'')


def _replay_session(bodies, row, proof):
    expected = {'kind', 'source', 'checked_at', 'success', 'stage', 'requests', 'transport_attempts',
                'responses', 'body_continuity', 'extracted', 'error'}
    if (not isinstance(proof, dict) or set(proof) != expected or proof['kind'] != SESSION_KIND
            or proof['source'] != row or not isinstance(proof['responses'], dict)
            or set(proof['responses']) - {'body', 'file'}):
        raise ValueError('Session proof source/schema differs')
    for key in ('requests', 'transport_attempts'):
        if (not isinstance(proof[key], dict) or set(proof[key]) != {'body', 'file'}
                or any(type(v) is not int or not 0 <= v <= 1 for v in proof[key].values())):
            raise ValueError('Session proof request/transport count differs')
    raw = {phase: _response(value, MAX_BODY_BYTES if phase == 'body' else MAX_FILE_BYTES)
           for phase, value in proof['responses'].items()}
    class Saved:
        def __init__(self): self.attempts = {'body': 0, 'file': 0}
        def __call__(self, url, phase):
            self.attempts[phase] = proof['transport_attempts'][phase]
            value = proof['responses'].get(phase)
            if value is None:
                if proof['error'] not in ('public_session_failed', 'public_session_redirect_rejected'):
                    raise ValueError('Unsupported no-response session error')
                raise control.ControlError(proof['error'])
            if value['url'] != url:
                raise ValueError('Session response URL differs from source queue')
            if value['http_status'] != 200:
                raise control.PublicHTTPError(raw[phase], value['http_status'], value['set_cookie_seen'])
            return {'raw': raw[phase], 'set_cookie_seen': value['set_cookie_seen']}
    replay = _session(bodies, row, Saved(), proof['checked_at'])
    if _json(replay) != _json(proof):
        raise ValueError('Session proof differs from complete offline replay')
    return replay


def validate_report(history, bodies, report):
    keys = {'kind', 'institution_id', 'window', 'listing_digest', 'legacy_state', 'records', 'batches', 'sessions', 'holds'}
    if (not isinstance(report, dict) or set(report) != keys or report['kind'] != KIND
            or report['institution_id'] != 'kgrowth' or report['window'] != history['window']
            or report['listing_digest'] != listing_digest(history)
            or any(not isinstance(report[k], list) for k in ('records', 'batches', 'sessions', 'holds'))):
        raise ValueError('Historical session report schema/listing differs')
    if len(_json(report)) > MAX_REPORT_BYTES:
        raise ValueError('Historical session report exceeds size limit')
    legacy = report['legacy_state']
    files.validate_report(history, bodies, legacy)
    if legacy['holds'] or 'failed_response' in legacy:
        raise ValueError('Failed v1 state cannot be inherited')
    completed = [files.receipt(r) for r in legacy['records']]
    offset = 0; session_offset = 0
    for index, batch in enumerate(report['batches']):
        fields = {'checked_at', 'planned_ids', 'completed_ids', 'new_ids', 'reused_database_ids',
                  'attachment_requests', 'detail_requests', 'transport_attempts'}
        if not isinstance(batch, dict) or set(batch) != fields:
            raise ValueError('Historical session batch schema differs')
        files._stamp(batch['checked_at'])
        q = plan(history, bodies, completed)
        planned = [r['source_id'] for r in q['rows']]
        for key in ('planned_ids', 'completed_ids', 'new_ids', 'reused_database_ids'):
            if (not isinstance(batch[key], list) or any(not isinstance(v, str) for v in batch[key])
                    or len(set(batch[key])) != len(batch[key])):
                raise ValueError('Historical session batch IDs invalid')
        done, new, reused = (batch[k] for k in ('completed_ids', 'new_ids', 'reused_database_ids'))
        failure = bool(report['holds']) and index == len(report['batches']) - 1
        if (batch['planned_ids'] != planned or done != planned[:len(done)] or len(done) > 4
                or set(new) & set(reused) or set(new + reused) != set(done)
                or new != [ident for ident in done if ident not in reused]
                or reused != [ident for ident in done if ident not in new]
                or (not failure and done != planned)):
            raise ValueError('Historical session progress differs from bounded automatic queue')
        records = report['records'][offset:offset + len(done)]
        if [r.get('source_id') for r in records] != done:
            raise ValueError('Historical session records differ from progress')
        sessions = []
        for record in records:
            row = plan(history, bodies, completed)['rows'][0]
            files._record(row, record)
            if record['source_id'] in new:
                if session_offset >= len(report['sessions']):
                    raise ValueError('New historical file lacks session proof')
                proof = report['sessions'][session_offset]; session_offset += 1
                replay = _replay_session(bodies, row, proof)
                response = replay['responses'].get('file', {})
                if (not replay['success'] or replay['checked_at'] != batch['checked_at']
                        or record['checked_at'] != batch['checked_at']
                        or response.get('raw_base64') != record['raw_base64']
                        or response.get('sha256') != record['attachment_sha256']
                        or replay['extracted'] != record['extracted']):
                    raise ValueError('New file differs from successful fresh session proof')
                sessions.append(proof)
            completed.append(files.receipt(record))
        if failure:
            q = plan(history, bodies, completed)
            if len(report['holds']) != 1 or not q['rows']:
                raise ValueError('Invalid terminal session hold')
            row = q['rows'][0]
            held = report['holds'][0]
            if (not isinstance(held, dict) or set(held) != {'source_id', 'attachment_url', 'error'}
                    or any(held[k] != row[k] for k in ('source_id', 'attachment_url'))):
                raise ValueError('Session hold differs from next source queue row')
            if held['error'] != 'pre_request_report_budget':
                if session_offset >= len(report['sessions']):
                    raise ValueError('Terminal session hold lacks response proof')
                proof = report['sessions'][session_offset]; session_offset += 1
                replay = _replay_session(bodies, row, proof)
                if replay['success'] or replay['error'] != held['error'] or replay['checked_at'] != batch['checked_at']:
                    raise ValueError('Terminal session failure proof differs')
                sessions.append(proof)
        expected_requests = {phase: sum(p['requests'][phase] for p in sessions) for phase in ('body', 'file')}
        attempts = {phase: sum(p['transport_attempts'][phase] for p in sessions) for phase in ('body', 'file')}
        if (type(batch['attachment_requests']) is not int or type(batch['detail_requests']) is not int
                or batch['attachment_requests'] != expected_requests['file']
                or batch['detail_requests'] != expected_requests['body']
                or _json(batch['transport_attempts']) != _json(attempts)
                or max(expected_requests.values(), default=0) > 4):
            raise ValueError('Session logical request/actual transport counts differ')
        offset += len(done)
    if offset != len(report['records']) or session_offset != len(report['sessions']) or (report['holds'] and not report['batches']):
        raise ValueError('Historical session records/proofs lack batch evidence')
    return plan(history, bodies, completed)


def _cache(bodies, rows, cached):
    if (not isinstance(cached, (list, tuple)) or len(cached) > 100
            or any(not isinstance(n, dict) for n in cached) or len(_json(cached)) > MAX_REPORT_BYTES):
        raise ValueError('Retained session cache exceeds size/type/version limit')
    by_url = {r['source_url']: r for r in rows}
    for n in cached:
        row = by_url.get(n.get('url'))
        if row is None or files._protected(n):
            raise ValueError('Foreign/protected/failed retained source requires diagnosis before HTTP')
        original = next(b for b in bodies['documents'] if b['source_id'] == row['source_id'])
        if any(n.get(k) != original[k] for k in ('url', 'title', 'date', 'body', 'sha256', 'attachments')):
            raise ValueError('Conflicting retained session source metadata before HTTP')
    return {r['source_id']: files._cached_record(bodies, r, cached) for r in rows}


def lookup(conn, history, bodies, previous=None):
    _, q = _start(history, bodies, previous)
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    conn.execute("SET LOCAL statement_timeout='120s'")
    rows = conn.execute('SELECT document FROM lp_program_private.documents WHERE source_url=ANY(%s) '
                        'ORDER BY source_url,content_hash LIMIT 101', ([r['source_url'] for r in q['rows']],)).fetchall()
    cached = [row[0] for row in rows]
    _cache(bodies, q['rows'], cached)
    return cached


def collect(history, bodies, previous=None, fetch=None, *, cached_documents=(), checked_at=None):
    report, q = _start(history, bodies, previous)
    cached = _cache(bodies, q['rows'], cached_documents)
    batch = {'checked_at': checked_at or datetime.now(timezone.utc).isoformat(),
             'planned_ids': [r['source_id'] for r in q['rows']], 'completed_ids': [], 'new_ids': [],
             'reused_database_ids': [], 'attachment_requests': 0, 'detail_requests': 0,
             'transport_attempts': {'body': 0, 'file': 0}}
    files._stamp(batch['checked_at']); report['batches'].append(batch)
    for row in q['rows']:
        record = cached[row['source_id']]
        if record is None:
            # Reserve both raw responses, duplicate v1 file record and extracted
            # text before any request, so failures can always keep bounded bytes.
            reserve = ((MAX_BODY_BYTES + 2) // 3 * 4 + 2 * ((MAX_FILE_BYTES + 2) // 3 * 4)
                       + 32 * 1024 * 1024 + 3 * len(_json(row)) + 65536)
            if len(_json(report)) + reserve > MAX_REPORT_BYTES:
                report['holds'].append({'source_id': row['source_id'], 'attachment_url': row['attachment_url'],
                                        'error': 'pre_request_report_budget'})
                break
            proof = _session(bodies, row, fetch, batch['checked_at'])
            report['sessions'].append(proof)
            batch['attachment_requests'] += proof['requests']['file']
            batch['detail_requests'] += proof['requests']['body']
            for phase in ('body', 'file'):
                batch['transport_attempts'][phase] += proof['transport_attempts'][phase]
            if not proof['success']:
                report['holds'].append({'source_id': row['source_id'], 'attachment_url': row['attachment_url'], 'error': proof['error']})
                break
            response = proof['responses']['file']
            record = {**row, 'attachment_sha256': response['sha256'], 'raw_base64': response['raw_base64'],
                      'extracted': copy.deepcopy(proof['extracted']), 'checked_at': batch['checked_at']}
            files._record(row, record)
            category = 'new_ids'
        else:
            category = 'reused_database_ids'
            if len(_json(report)) + len(_json(record)) + 65536 > MAX_REPORT_BYTES:
                report['holds'].append({'source_id': row['source_id'], 'attachment_url': row['attachment_url'],
                                        'error': 'pre_request_report_budget'})
                break
        report['records'].append(copy.deepcopy(record))
        batch[category].append(row['source_id']); batch['completed_ids'].append(row['source_id'])
    validate_report(history, bodies, report)
    return report


def persist(conn, history, bodies, report, *, wrap_json=None):
    q = validate_report(history, bodies, report)
    if report['holds'] or q['holds'] or not report['batches']:
        raise ValueError('Successful unblocked session batch required for persistence')
    batch = report['batches'][-1]
    records = [r for r in report['records'] if r['source_id'] in batch['completed_ids']]
    verified = [document(bodies, record) for record in records]
    docs = [document(bodies, record) for record in records if record['source_id'] in batch['new_ids']]
    before = {}
    def guard(locked):
        for record in records:
            row = {k: record[k] for k in files.IDENTITY}
            cached = _stored(locked, bodies, row, record)
            if record['source_id'] in batch['reused_database_ids'] and cached is None:
                raise ValueError('Claimed cached typed file missing under shared lock')
            before[record['source_id']] = cached is not None
    result = retain_documents(conn, docs, verified, wrap_json=wrap_json, verify_retained=guard)
    if (len(before) != len(records) or result['verified_batch_documents'] != len(records)
            or not result['public_state_preserved'] or not 0 <= result['new_document_versions'] <= len(docs)):
        raise ValueError('Historical session retention guard incomplete')
    for record in records:
        row = {k: record[k] for k in files.IDENTITY}
        if _stored(conn, bodies, row, record) is None:
            raise ValueError('Actual stored typed raw proof missing after session retention')
    return {**result, 'kind': KIND, 'reused_database_documents': len(batch['reused_database_ids']),
            'existing_typed_before': sum(before.values()), 'typed_raw_readback_verified': True,
            'pending_files': q['pending_files'], 'body_pending': q['body_pending'],
            'session_report_stored_in_database': False, 'official_http_requests_this_operation': 0,
            'pe_approval': False, 'selected_gp_approval': False, 'published': False, 'source_history_complete': False}


def summary(history, bodies, report):
    q = validate_report(history, bodies, report)
    legacy = report['legacy_state']
    return {'kind': KIND, 'validated_files': len(_records(report)), 'pending_files': q['pending_files'],
            'body_pending': q['body_pending'], 'holds': report['holds'] + q['holds'],
            'legacy_records': len(legacy['records']), 'legacy_batches': len(legacy['batches']),
            'legacy_transport_attempts': 'not_measured', 'batches': report['batches'],
            'logical_body_requests': sum(b['detail_requests'] for b in report['batches']),
            'logical_attachment_requests': sum(b['attachment_requests'] for b in report['batches']),
            'actual_transport_attempts': {p: sum(b['transport_attempts'][p] for b in report['batches']) for p in ('body', 'file')},
            'validated_downloads': sum(len(b['new_ids']) for b in report['batches']),
            'reused_database_files': sum(len(b['reused_database_ids']) for b in report['batches']),
            'files': [{**files.receipt(r), 'format': r['extracted']['format'], 'text_chars': len(r['extracted']['text'])} for r in _records(report)],
            'database_persistence': 'separate_operation', 'session_report_stored_in_database': False,
            'pe_approval': False, 'selected_gp_approval': False, 'published': False, 'source_history_complete': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('lookup', 'collect', 'verify', 'persist'), required=True)
    for name in ('listing-state', 'body-state', 'output-dir'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--attachment-state', type=Path); p.add_argument('--cached-documents', type=Path)
    args = p.parse_args()
    def load(path):
        if path.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError('Historical session input exceeds size limit')
        value = json.loads(path.read_text()); _json(value); return value
    def save(name, value):
        target = args.output_dir / name; temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False)); temporary.replace(target)
    h, b = load(args.listing_state), load(args.body_state)
    previous = load(args.attachment_state) if args.attachment_state else None
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == 'collect':
        report = collect(h, b, previous, cached_documents=load(args.cached_documents) if args.cached_documents else ())
        save('attachment-state.json', report); result = summary(h, b, report); save('attachment-summary.json', result)
    elif args.mode == 'verify':
        if previous is None: p.error('--attachment-state required')
        result = summary(h, b, previous); save('attachment-summary.json', result)
    else:
        if args.mode == 'persist' and previous is None: p.error('--attachment-state required')
        import psycopg
        try:
            with psycopg.connect(os.environ.get('LP_SUPABASE_DB_URL') or os.environ['SUPABASE_DB_URL'],
                                  connect_timeout=20, prepare_threshold=None, application_name='kgrowth-history-sessions') as conn:
                result = lookup(conn, h, b, previous) if args.mode == 'lookup' else persist(conn, h, b, previous)
        except Exception as error:
            raise SystemExit('Private historical session operation failed: ' + type(error).__name__) from None
        save('cached-attachments.json' if args.mode == 'lookup' else 'persistence.json', result)
    if args.mode in ('collect', 'verify'):
        print(json.dumps({k: result[k] for k in ('kind', 'validated_files', 'pending_files', 'body_pending')}))
        if result['holds']: raise SystemExit('Historical session held; inspect retained evidence')


if __name__ == '__main__':
    main()
