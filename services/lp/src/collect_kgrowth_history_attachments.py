"""Retain bounded KGrowth historical file evidence, without PE/public approval.

Only the source-derived offline queue selects files. Original body and file
bytes are replayed on every resume; collection runs only in the Actions lane.
"""
import argparse
import base64
import copy
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from .lp_kgrowth_history_attachment_queue import IDENTITY, plan, validate_url
    from .lp_history_sources import listing_digest, canonical_url
    from .collect_lp_history_attachments import read_attachment, MAX_FILE_BYTES
    from .collect_lp_history_bodies import retain_documents
except ImportError:
    from lp_kgrowth_history_attachment_queue import IDENTITY, plan, validate_url
    from lp_history_sources import listing_digest, canonical_url
    from collect_lp_history_attachments import read_attachment, MAX_FILE_BYTES
    from collect_lp_history_bodies import retain_documents

KIND = 'kgrowth_history_attachments_v1'
MAX_REPORT_BYTES = 150 * 1024 * 1024
RECORD_KEYS = set(IDENTITY) | {'attachment_sha256', 'raw_base64', 'extracted', 'checked_at'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def receipt(record):
    return {k: record[k] for k in (*IDENTITY, 'attachment_sha256')}


def _stamp(value):
    if not isinstance(value, str):
        raise ValueError('Historical file observation time missing')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Invalid historical file observation time') from None
    if stamp.tzinfo is None:
        raise ValueError('Historical file observation time needs a timezone')


def _record(row, record):
    if (not isinstance(record, dict) or set(record) != RECORD_KEYS
            or any(record.get(k) != row[k] for k in IDENTITY)):
        raise ValueError('Historical file identity or proof fields differ')
    _stamp(record['checked_at'])
    encoded = record['raw_base64']
    if not isinstance(encoded, str) or len(encoded) > (MAX_FILE_BYTES + 2) // 3 * 4:
        raise ValueError('Historical file raw proof exceeds size limit')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise ValueError('Invalid historical file byte proof') from None
    if (sha(raw) != record['attachment_sha256']
            or read_attachment(raw) != record['extracted']):
        raise ValueError('Historical file hash or extracted body differs')


def validate_report(history, bodies, report):
    required = {'kind', 'institution_id', 'window', 'listing_digest', 'records', 'batches', 'holds'}
    if (not isinstance(report, dict) or not required <= set(report)
            or set(report) - required - {'failed_response'}
            or report['kind'] != KIND or report['institution_id'] != 'kgrowth'
            or report['window'] != history['window']
            or report['listing_digest'] != listing_digest(history)
            or any(not isinstance(report[k], list) for k in ('records', 'batches', 'holds'))):
        raise ValueError('KGrowth attachment report/listing identity differs')
    if len(json.dumps(report, ensure_ascii=False).encode()) > MAX_REPORT_BYTES:
        raise ValueError('Historical file report size limit exceeded')
    completed = []
    for record in report['records']:
        q = plan(history, bodies, completed)
        if not q['rows']:
            raise ValueError('Historical file is outside the automatic queue')
        _record(q['rows'][0], record)
        completed.append(receipt(record))
    # Batches are also proofs of the next bounded queue, not caller-selected IDs.
    offset = 0
    for index, batch in enumerate(report['batches']):
        fields = {'checked_at', 'planned_ids', 'completed_ids', 'new_ids',
                  'reused_database_ids', 'attachment_requests', 'detail_requests'}
        if not isinstance(batch, dict) or set(batch) != fields:
            raise ValueError('Unexpected historical file batch fields')
        _stamp(batch['checked_at'])
        q = plan(history, bodies, completed[:offset])
        planned = [r['source_id'] for r in q['rows']]
        for key in ('planned_ids', 'completed_ids', 'new_ids', 'reused_database_ids'):
            if (not isinstance(batch[key], list) or any(not isinstance(v, str) for v in batch[key])
                    or len(set(batch[key])) != len(batch[key])):
                raise ValueError('Invalid historical file batch IDs')
        done, new, reused = (batch[k] for k in ('completed_ids', 'new_ids', 'reused_database_ids'))
        failed = bool(report['holds']) and index == len(report['batches']) - 1
        if (batch['planned_ids'] != planned or done != planned[:len(done)]
                or len(done) > 4 or set(new) & set(reused) or set(new + reused) != set(done)
                or type(batch['attachment_requests']) is not int
                or type(batch['detail_requests']) is not int or batch['detail_requests'] != 0
                or not len(new) <= batch['attachment_requests'] <= len(new) + int(failed)
                or batch['attachment_requests'] > 4
                or (not failed and done != planned)):
            raise ValueError('Incomplete or unbounded historical file batch')
        records = report['records'][offset:offset + len(done)]
        if [r['source_id'] for r in records] != done:
            raise ValueError('Historical file records differ from batch progress')
        if any(r['checked_at'] != batch['checked_at'] for r in records if r['source_id'] in new):
            raise ValueError('New historical file observation time differs')
        offset += len(done)
    if offset != len(completed):
        raise ValueError('Historical file records lack batch evidence')
    if 'failed_response' in report:
        failure = report['failed_response']
        if (not report['holds'] or not isinstance(failure, dict)
                or set(failure) != {'source_id', 'attachment_url', 'sha256', 'raw_base64'}
                or not isinstance(failure['raw_base64'], str)
                or len(failure['raw_base64']) > (MAX_FILE_BYTES + 2) // 3 * 4):
            raise ValueError('Invalid saved historical file failure')
        raw = base64.b64decode(failure['raw_base64'], validate=True)
        q = plan(history, bodies, completed)
        if (len(raw) > MAX_FILE_BYTES or sha(raw) != failure['sha256'] or not q['rows']
                or any(failure[k] != q['rows'][0][k] for k in ('source_id', 'attachment_url'))):
            raise ValueError('Saved historical file failure identity/hash differs')
    return plan(history, bodies, completed)


def _unblocked(history, bodies, previous):
    report = copy.deepcopy(previous) if previous is not None else {
        'kind': KIND, 'institution_id': 'kgrowth', 'window': copy.deepcopy(history['window']),
        'listing_digest': listing_digest(history), 'records': [], 'batches': [], 'holds': []}
    q = validate_report(history, bodies, report)
    if report['holds'] or q['holds']:
        raise ValueError('Saved or ambiguous historical file failure requires diagnosis')
    return report, q


def _protected(n):
    proof = n.get('discovery_provenance', {})
    flags = ('owner_closed', 'restricted', 'closed', 'hidden', 'protected')
    return (any(str(n.get(k, '')).strip().lower() in {'true', '1'}
                or str(proof.get(k, '')).strip().lower() in {'true', '1'} for k in flags)
            or str(n.get('status', '')).strip().lower() in {'restricted', 'owner_closed', 'closed', 'hidden', 'protected', 'private', 'error', 'failed'}
            or bool(n.get('attachment_errors')) or bool(n.get('error'))
            or str(n.get('reason', '')).strip().lower() == 'owner_closed')


def lookup(conn, history, bodies, previous=None):
    _, q = _unblocked(history, bodies, previous)
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    conn.execute("SET LOCAL statement_timeout='120s'")
    # Keep blocked versions visible: an empty filtered cache must never
    # authorize a fresh request for a protected or failed retained source.
    rows = conn.execute('SELECT document FROM lp_program_private.documents WHERE source_url=ANY(%s)'
                        ' ORDER BY source_url,content_hash LIMIT 101',
                        ([r['source_url'] for r in q['rows']],)).fetchall()
    if len(rows) > 100:
        raise ValueError('Retained historical file version lookup limit exceeded')
    cached = [row[0] for row in rows]
    if any(not isinstance(n, dict) for n in cached) or len(json.dumps(cached, ensure_ascii=False).encode()) > MAX_REPORT_BYTES:
        raise ValueError('Retained historical file lookup size/type limit exceeded')
    if any(_protected(n) for n in cached):
        raise ValueError('Protected or failed retained source requires diagnosis before HTTP')
    return cached


def document(bodies, record):
    n = copy.deepcopy(next(n for n in bodies['documents'] if n['source_id'] == record['source_id']))
    n['checked_at'] = record['checked_at']
    n['attachment_texts'] = {record['attachment_url']: record['extracted']['text']}
    n['attachment_hashes'] = {record['attachment_url']: record['attachment_sha256']}
    n['attachment_collection_status'] = 'primary_file_only'
    n['discovery_provenance'] = {**n['discovery_provenance'], 'kind': KIND,
                               'attachment_evidence': copy.deepcopy(record)}
    return n


def _cached_record(bodies, row, cached):
    records = []
    digests = set()
    for n in cached:
        if n.get('url') != row['source_url']:
            continue
        if _protected(n):
            raise ValueError('Protected historical file cannot be reused or fetched')
        if n.get('sha256') != row['body_sha256']:
            raise ValueError('Conflicting retained historical notice body')
        digest = n.get('attachment_hashes', {}).get(row['attachment_url'])
        if digest:
            digests.add(digest)
        proof = n.get('discovery_provenance', {})
        if proof.get('kind') != KIND:
            continue  # Hash/text-only observations are not raw file proof.
        record = proof.get('attachment_evidence')
        _record(row, record)
        if n != document(bodies, record):
            raise ValueError('Cached historical file differs from original body/file proof')
        records.append(record)
    if len(digests) > 1 or (records and any(r['attachment_sha256'] not in digests for r in records)):
        raise ValueError('Conflicting retained historical file versions')
    return copy.deepcopy(records[0]) if records else None


def collect(history, bodies, previous, fetch, *, cached_documents=(), checked_at=None):
    report, q = _unblocked(history, bodies, previous)
    if (not isinstance(cached_documents, (list, tuple)) or len(cached_documents) > 100
            or any(not isinstance(n, dict) for n in cached_documents)
            or len(json.dumps(cached_documents, ensure_ascii=False).encode()) > MAX_REPORT_BYTES):
        raise ValueError('Cached historical file input exceeds size/type limit')
    batch = {'checked_at': checked_at or datetime.now(timezone.utc).isoformat(),
             'planned_ids': [r['source_id'] for r in q['rows']], 'completed_ids': [],
             'new_ids': [], 'reused_database_ids': [], 'attachment_requests': 0, 'detail_requests': 0}
    _stamp(batch['checked_at'])
    report['batches'].append(batch)
    for row in q['rows']:
        raw = None
        try:
            record = _cached_record(bodies, row, cached_documents)
            if record is None:
                # Reserve enough report space to keep a full bounded failed
                # response even when decoding or the decoded-text budget fails.
                if len(json.dumps(report, ensure_ascii=False).encode()) + (MAX_FILE_BYTES + 2) // 3 * 4 + 4096 > MAX_REPORT_BYTES:
                    raise ValueError('Historical file failure-proof budget exhausted before HTTP')
                batch['attachment_requests'] += 1
                raw = fetch(row['attachment_url'])
                record = {**row, 'attachment_sha256': sha(raw), 'raw_base64': base64.b64encode(raw).decode('ascii'),
                          'extracted': read_attachment(raw), 'checked_at': batch['checked_at']}
                _record(row, record)
                category = 'new_ids'
            else:
                category = 'reused_database_ids'
            if len(json.dumps(report, ensure_ascii=False).encode()) + len(json.dumps(record, ensure_ascii=False).encode()) > MAX_REPORT_BYTES:
                raise ValueError('Historical file report size limit exceeded')
            report['records'].append(record)
            batch[category].append(row['source_id'])
            batch['completed_ids'].append(row['source_id'])
        except Exception as error:
            report['holds'].append({'source_id': row['source_id'], 'attachment_url': row['attachment_url'],
                                    'error': type(error).__name__ + ': ' + str(error)[:300]})
            if isinstance(raw, bytes) and len(raw) <= MAX_FILE_BYTES:
                report['failed_response'] = {'source_id': row['source_id'], 'attachment_url': row['attachment_url'],
                                             'sha256': sha(raw), 'raw_base64': base64.b64encode(raw).decode('ascii')}
            break
    return report


def persist(conn, history, bodies, report, *, wrap_json=None):
    q = validate_report(history, bodies, report)
    if report['holds'] or q['holds'] or not report['batches']:
        raise ValueError('Unblocked completed historical file batch required')
    batch = report['batches'][-1]
    ids = batch['completed_ids']
    records = [r for r in report['records'] if r['source_id'] in ids]
    verified = [document(bodies, r) for r in records]
    docs = [document(bodies, r) for r in records if r['source_id'] in batch['new_ids']]
    result = retain_documents(conn, docs, verified, wrap_json=wrap_json)
    return {**result, 'reused_database_documents': len(batch['reused_database_ids']),
            'pending_files': q['pending_files'], 'body_pending': q['body_pending'],
            'source_history_complete': False, 'pe_approval': False, 'selected_gp_approval': False, 'published': False}


class OfficialRedirects(HTTPRedirectHandler):
    def __init__(self, source_id):
        super().__init__()
        self.source_id = source_id

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, self.source_id)
        validate_url(req.full_url, self.source_id)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_attachment(url):
    """Actions-only bounded transport; redirects cannot leave this notice/file route."""
    from urllib.parse import urlsplit
    ident = parse_qs(urlsplit(url).query).get('idx', [''])[0]
    validate_url(url, ident)
    opener = build_opener(OfficialRedirects(ident))
    for attempt in range(3):
        try:
            request = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept-Encoding': 'identity',
                                            'Referer': canonical_url(ident, 'kgrowth')})
            with opener.open(request, timeout=25) as response:
                validate_url(response.geturl(), ident)
                raw = response.read(MAX_FILE_BYTES + 1)
            if not isinstance(raw, bytes) or not raw or len(raw) > MAX_FILE_BYTES:
                raise ValueError('Historical file response empty or oversized')
            return raw
        except HTTPError as error:
            if error.code not in (408, 429) and not 500 <= error.code < 600:
                raise
            if attempt == 2:
                raise
        except URLError as error:
            # TLS, permission and untyped URL errors never select a retry.
            if attempt == 2 or not isinstance(error.reason, (TimeoutError, ConnectionError)):
                raise
        except (TimeoutError, ConnectionError):
            if attempt == 2:
                raise
        time.sleep(attempt + 1)


def summary(history, bodies, report):
    q = validate_report(history, bodies, report)
    excluded = {'rows', 'holds', 'official_http_requests', 'downloaded_files', 'database_writes', 'raw_file_validation'}
    return {**{k: v for k, v in q.items() if k not in excluded}, 'kind': KIND,
            'holds': report['holds'] + q['holds'], 'batches': report['batches'],
            'validated_files': len(report['records']),
            'logical_attachment_requests': sum(b['attachment_requests'] for b in report['batches']),
            'transport_attempts': 'not_measured',
            'validated_downloads': sum(len(b['new_ids']) for b in report['batches']),
            'reused_database_files': sum(len(b['reused_database_ids']) for b in report['batches']),
            'database_persistence': 'separate_operation',
            'raw_file_validation': 'replayed',
            'files': [{**receipt(r), 'format': r['extracted']['format'],
                       'text_chars': len(r['extracted']['text'])} for r in report['records']],
            'published': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('lookup', 'collect', 'verify', 'persist'), required=True)
    for name in ('listing-state', 'body-state', 'output-dir'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--attachment-state', type=Path)
    p.add_argument('--cached-documents', type=Path)
    args = p.parse_args()
    def load(path):
        if path.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError('Historical file input exceeds size limit')
        return json.loads(path.read_text())
    def save(name, value):
        target = args.output_dir / name
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False))
        temporary.replace(target)
    history, bodies = load(args.listing_state), load(args.body_state)
    previous = load(args.attachment_state) if args.attachment_state else None
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == 'collect':
        report = collect(history, bodies, previous, fetch_attachment,
                         cached_documents=load(args.cached_documents) if args.cached_documents else ())
        save('attachment-state.json', report)
        result = summary(history, bodies, report)
        save('attachment-summary.json', result)
        print(json.dumps({k: result[k] for k in ('validated_files', 'pending_files', 'body_pending')}))
        if result['holds']:
            raise SystemExit('Historical file collection held; inspect saved failure evidence')
    elif args.mode == 'verify':
        if previous is None:
            p.error('--attachment-state required')
        result = summary(history, bodies, previous)
        save('attachment-summary.json', result)
        if result['holds']:
            raise SystemExit('Historical file evidence has retained holds')
    else:
        if args.mode == 'persist' and previous is None:
            p.error('--attachment-state required')
        import psycopg
        try:
            with psycopg.connect(os.environ.get('LP_SUPABASE_DB_URL') or os.environ['SUPABASE_DB_URL'],
                                  connect_timeout=20, prepare_threshold=None,
                                  application_name='kgrowth-history-attachments') as conn:
                result = lookup(conn, history, bodies, previous) if args.mode == 'lookup' else persist(conn, history, bodies, previous)
        except Exception as error:
            raise SystemExit('Private historical file operation failed: ' + type(error).__name__) from None
        save('cached-attachments.json' if args.mode == 'lookup' else 'persistence.json', result)


if __name__ == '__main__':
    main()
