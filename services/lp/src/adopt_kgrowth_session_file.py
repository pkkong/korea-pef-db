"""Adopt one already captured normal-session file; never resume a failed batch.

All source bytes are replayed offline. Database retention is separately guarded
under the common publication lock and does not approve any PE/GP/public facts.
"""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path

try:
    from . import collect_kgrowth_history_attachments as files
    from . import diagnose_kgrowth_history_session as session
    from .lp_kgrowth_history_attachment_queue import plan
    from .collect_lp_history_bodies import retain_documents
    from .publish_lp_programs import document_hash
except ImportError:
    import collect_kgrowth_history_attachments as files
    import diagnose_kgrowth_history_session as session
    from lp_kgrowth_history_attachment_queue import plan
    from collect_lp_history_bodies import retain_documents
    from publish_lp_programs import document_hash

KIND = 'kgrowth_session_file_adoption_v1'
MAX_INPUT_BYTES = 150 * 1024 * 1024


def _json(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('KGrowth adoption input exceeds size limit')
    return raw


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _response(value, limit):
    keys = {'url', 'bytes', 'sha256', 'raw_base64', 'set_cookie_seen', 'http_status', 'truncated'}
    if (not isinstance(value, dict) or set(value) != keys
            or type(value['bytes']) is not int or type(value['set_cookie_seen']) is not bool
            or type(value['http_status']) is not int or value['http_status'] != 200
            or value['truncated'] is not False or not isinstance(value['raw_base64'], str)
            or len(value['raw_base64']) > (limit + 2) // 3 * 4):
        raise ValueError('Successful untruncated control response required')
    raw = base64.b64decode(value['raw_base64'], validate=True)
    if (not raw or len(raw) > limit or len(raw) != value['bytes']
            or hashlib.sha256(raw).hexdigest() != value['sha256']):
        raise ValueError('Control response bytes/hash differ')
    return raw


def produce(history, bodies, failed, control_report):
    provenance = {'listing_state_sha256': _hash(history), 'body_state_sha256': _hash(bodies),
                  'failed_state_sha256': _hash(failed), 'session_control_sha256': _hash(control_report)}
    q = files.validate_report(history, bodies, failed)
    if (q['holds'] or not q['rows'] or not isinstance(control_report, dict)
            or control_report.get('kind') != session.KIND or control_report.get('success') is not True
            or control_report.get('stage') != 'complete' or control_report.get('source') != q['rows'][0]
            or control_report.get('requests') != {'body': 1, 'file': 1}
            or any(type(control_report['requests'].get(k)) is not int for k in ('body', 'file'))
            or not isinstance(control_report.get('responses'), dict)
            or set(control_report['responses']) != {'body', 'file'}):
        raise ValueError('One successful source-discovered session control required')
    row = q['rows'][0]
    raw = {'body': _response(control_report['responses']['body'], session.MAX_BODY_BYTES),
           'file': _response(control_report['responses']['file'], files.MAX_FILE_BYTES)}
    if raw['file'].startswith(b'%PDF'):
        import pypdf
        if pypdf.__version__ != '6.10.0':
            raise ValueError('Historical PDF replay requires pypdf 6.10.0')
    calls = []
    def saved_fetch(url, kind):
        response = control_report['responses'][kind]
        if response['url'] != url:
            raise ValueError('Control response route differs from source queue')
        calls.append((url, kind))
        return {'raw': raw[kind], 'set_cookie_seen': response['set_cookie_seen']}
    replay = session.control(history, bodies, failed, saved_fetch, checked_at=control_report['checked_at'])
    # Canonical JSON equality also rejects bool/int substitutions, unknown
    # approval fields, altered counters, and modified failure/source references.
    if (_json(replay) != _json(control_report)
            or calls != [(row['source_url'], 'body'), (row['attachment_url'], 'file')]):
        raise ValueError('Session control differs from complete offline replay')
    response = control_report['responses']['file']
    record = {**copy.deepcopy(row), 'attachment_sha256': response['sha256'],
              'raw_base64': response['raw_base64'], 'extracted': copy.deepcopy(replay['extracted']),
              'checked_at': control_report['checked_at']}
    files._record(row, record)
    doc = files.document(bodies, record)
    completed = [files.receipt(r) for r in failed['records']] + [files.receipt(record)]
    remaining = plan(history, bodies, completed)
    return {'kind': KIND, 'institution_id': 'kgrowth', 'window': copy.deepcopy(history['window']),
            'checked_at': record['checked_at'], 'source': copy.deepcopy(row), 'provenance': provenance,
            'original_failure_response_sha256': failed['failed_response']['sha256'],
            'file_record': record, 'document_content_hash': document_hash(doc),
            'diagnostic_file_plan': {'eligible_files': q['eligible_files'], 'completed_in_failed_input': len(failed['records']),
                                     'pending_files_after_adoption': remaining['pending_files'], 'body_pending': q['body_pending'],
                                     'meaning': 'Report-scope file plan only; not complete DB coverage or PE/GP results'},
            'one_file_adoption_planned': True, 'original_failed_batch_preserved': True,
            'original_failed_batch_completed': False, 'official_http_requests': 0, 'downloaded_new_files': 0,
            'prior_session_logical_requests': {'body': 1, 'file': 1}, 'transport_attempts_this_operation': 0,
            'database_writes': 0, 'published': False, 'pe_approval': False, 'selected_gp_approval': False,
            'source_history_complete': False}


def verify(history, bodies, failed, control_report, report):
    expected = produce(history, bodies, failed, control_report)
    if _json(expected) != _json(report):
        raise ValueError('Adoption report differs from source-derived offline replay')
    return expected


def _same_file(left, right):
    keys = files.RECORD_KEYS - {'checked_at'}
    return _json({k: left[k] for k in keys}) == _json({k: right[k] for k in keys})


def _stored(conn, bodies, row, record):
    rows = conn.execute('SELECT document FROM lp_program_private.documents WHERE source_url=ANY(%s) '
                        'ORDER BY source_url,content_hash LIMIT 101', ([row['source_url']],)).fetchall()
    if len(rows) > 100:
        raise ValueError('Retained adoption source version limit exceeded')
    documents = [r[0] for r in rows]
    _json(documents)
    source = next(n for n in bodies['documents'] if n['source_id'] == row['source_id'])
    core = ('url', 'title', 'date', 'body', 'sha256', 'attachments')
    for n in documents:
        if not isinstance(n, dict) or files._protected(n):
            raise ValueError('Protected or failed retained adoption source')
        if any(n.get(k) != source[k] for k in core):
            raise ValueError('Conflicting retained adoption source body/metadata')
        digest = n.get('attachment_hashes', {}).get(row['attachment_url'])
        if digest and digest != record['attachment_sha256']:
            raise ValueError('Conflicting retained adoption file version')
    if not documents:
        raise ValueError('Exact original retained source body required before adoption')
    cached = files._cached_record(bodies, row, documents)
    if cached is not None and not _same_file(cached, record):
        raise ValueError('Retained typed file differs from session control')
    return cached


def persist(conn, history, bodies, failed, control_report, report, *, wrap_json=None):
    verified = verify(history, bodies, failed, control_report, report)
    row, record = verified['source'], verified['file_record']
    doc = files.document(bodies, record)
    before = {}
    def check_retained(locked_conn):
        cached = _stored(locked_conn, bodies, row, record)
        before['reused_existing_private_document'] = cached is not None
    result = retain_documents(conn, [doc], [doc], wrap_json=wrap_json, verify_retained=check_retained)
    if ('reused_existing_private_document' not in before or result['new_document_versions'] not in (0, 1)
            or result['verified_batch_documents'] != 1 or not result['public_state_preserved']):
        raise ValueError('One-file retention guard was not completed')
    # Check the actual stored JSON/raw proof while the same transaction/lock is
    # still held. Source-url/content-hash readback alone cannot prove raw reuse.
    cached = _stored(conn, bodies, row, record)
    if cached is None:
        raise ValueError('Stored typed raw file proof missing after adoption')
    return {**result, **before, 'kind': KIND, 'one_file_adopted': True, 'reuse_possible': True,
            'typed_file_readback_verified': True, 'new_typed_proof_retained': result['new_document_versions'] == 1,
            'original_failed_batch_preserved': True, 'original_failed_batch_completed': False,
            'pending_files_in_input_plan': verified['diagnostic_file_plan']['pending_files_after_adoption'],
            'official_http_requests': 0, 'transport_attempts_this_operation': 0,
            'downloaded_new_files': 0, 'published': False,
            'pe_approval': False, 'selected_gp_approval': False, 'source_history_complete': False}


def summary(report):
    return {k: copy.deepcopy(v) for k, v in report.items() if k != 'file_record'} | {
        'file_sha256': report['file_record']['attachment_sha256'],
        'format': report['file_record']['extracted']['format'],
        'text_chars': len(report['file_record']['extracted']['text'])}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('plan', 'verify', 'persist'), required=True)
    for name in ('listing-state', 'body-state', 'failed-state', 'session-control', 'output-dir'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--adoption-state', type=Path)
    args = p.parse_args()
    def load(path):
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError('Adoption input exceeds size limit')
        return json.loads(path.read_text())
    def save(name, value):
        target = args.output_dir / name
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False))
        temporary.replace(target)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    h, b, failed, control_report = (load(path) for path in (args.listing_state, args.body_state, args.failed_state, args.session_control))
    if args.mode == 'plan':
        report = produce(h, b, failed, control_report)
        save('adoption-state.json', report)
        save('adoption-summary.json', summary(report))
    else:
        if args.adoption_state is None:
            p.error('--adoption-state required')
        report = load(args.adoption_state)
        verify(h, b, failed, control_report, report)
        if args.mode == 'verify':
            save('adoption-summary.json', summary(report))
        else:
            import psycopg
            try:
                with psycopg.connect(os.environ.get('LP_SUPABASE_DB_URL') or os.environ['SUPABASE_DB_URL'],
                                      connect_timeout=20, prepare_threshold=None,
                                      application_name='kgrowth-session-file-adoption') as conn:
                    result = persist(conn, h, b, failed, control_report, report)
            except Exception as error:
                raise SystemExit('Private file adoption failed: ' + type(error).__name__) from None
            save('persistence.json', result)
    print(json.dumps({'kind': KIND, 'mode': args.mode, 'official_http_requests': 0, 'published': False}))


if __name__ == '__main__':
    main()
