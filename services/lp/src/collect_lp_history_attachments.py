"""Bounded announcement attachment evidence, separate from PE/public approval."""
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
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from .lp_history_attachment_queue import plan, validate_url
    from .lp_history_sources import listing_digest
    from .lp_attachment_text import extract_attachment, MAX_FILE_BYTES
    from .collect_lp_history_bodies import retain_documents
except ImportError:
    from lp_history_attachment_queue import plan, validate_url
    from lp_history_sources import listing_digest
    from lp_attachment_text import extract_attachment, MAX_FILE_BYTES
    from collect_lp_history_bodies import retain_documents

KIND = 'lp_history_attachments_v1'
MAX_REPORT_BYTES = 150 * 1024 * 1024
IDENTITY = ('institution_id', 'source_id', 'source_url', 'body_sha256',
            'attachment_name', 'attachment_url')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_attachment(raw):
    result = extract_attachment(raw)
    if result['format'] not in ('hwp', 'hwpx', 'pdf', 'docx') or not result['text'].strip():
        raise ValueError('Announcement file has no supported readable body')
    return result


def receipt(record):
    return {k: record[k] for k in (*IDENTITY, 'attachment_sha256')}


def validate_report(history, bodies, report):
    if (report.get('kind') != KIND or report.get('institution_id') != 'ktcu'
            or report.get('window') != history['window']
            or report.get('listing_digest') != listing_digest(history)):
        raise ValueError('Attachment evidence/listing mismatch')
    completed = []
    # Each record must be the next source-discovered announcement. Re-decode
    # retained bytes rather than trusting a stored text or claimed checksum.
    for record in report['records']:
        q = plan(history, bodies, completed)
        if not q['rows'] or any(record.get(k) != q['rows'][0][k] for k in IDENTITY):
            raise ValueError('Attachment evidence does not follow the automatic queue')
        allowed = set(IDENTITY) | {'attachment_sha256', 'raw_base64', 'extracted', 'checked_at'}
        if set(record) != allowed or not isinstance(record['checked_at'], str):
            raise ValueError('Unexpected attachment evidence fields')
        if len(record['raw_base64']) > (MAX_FILE_BYTES + 2) // 3 * 4:
            raise ValueError('Attachment proof exceeds size limit')
        raw = base64.b64decode(record['raw_base64'], validate=True)
        if sha(raw) != record['attachment_sha256'] or read_attachment(raw) != record['extracted']:
            raise ValueError('Attachment raw hash or decoded body mismatch')
        completed.append(receipt(record))
    return plan(history, bodies, completed)


def collect(history, bodies, previous, fetch, *, checked_at=None):
    report = copy.deepcopy(previous) if previous else {
        'kind': KIND, 'institution_id': 'ktcu', 'window': copy.deepcopy(history['window']),
        'listing_digest': listing_digest(history), 'records': [], 'batches': [], 'holds': []}
    q = validate_report(history, bodies, report)
    if report['holds'] or q['holds']:
        raise ValueError('Saved or ambiguous attachment failure requires diagnosis')
    batch = {'checked_at': checked_at or datetime.now(timezone.utc).isoformat(),
             'planned_ids': [r['source_id'] for r in q['rows']],
             'completed_ids': [], 'attachment_requests': 0, 'detail_requests': 0}
    report['batches'].append(batch)
    for row in q['rows']:
        raw = None
        try:
            validate_url(row['attachment_url'])
            batch['attachment_requests'] += 1
            raw = fetch(row['attachment_url'])
            record = {**row, 'attachment_sha256': sha(raw),
                      'raw_base64': base64.b64encode(raw).decode('ascii'),
                      'extracted': read_attachment(raw), 'checked_at': batch['checked_at']}
            if len(json.dumps(report, ensure_ascii=False).encode()) + len(json.dumps(record, ensure_ascii=False).encode()) > MAX_REPORT_BYTES:
                raise ValueError('Attachment evidence report exceeds size limit')
            report['records'].append(record)
            batch['completed_ids'].append(row['source_id'])
        except Exception as error:
            report['holds'].append({'source_id': row['source_id'], 'error': type(error).__name__})
            if isinstance(raw, bytes) and len(raw) <= MAX_FILE_BYTES:
                report['failed_response'] = {'source_id': row['source_id'], 'sha256': sha(raw),
                                             'raw_base64': base64.b64encode(raw).decode('ascii')}
            break
    return report


def document(bodies, record):
    n = copy.deepcopy(next(n for n in bodies['documents'] if n['source_id'] == record['source_id']))
    n['checked_at'] = record['checked_at']
    n['attachment_texts'] = {record['attachment_url']: record['extracted']['text']}
    n['attachment_hashes'] = {record['attachment_url']: record['attachment_sha256']}
    n['attachment_collection_status'] = 'announcement_only'
    n['discovery_provenance'] = {**n['discovery_provenance'], 'kind': 'lp_history_attachment',
                               'attachment_evidence': copy.deepcopy(record)}
    return n


def persist(conn, history, bodies, report, *, wrap_json=None):
    q = validate_report(history, bodies, report)
    if report['holds'] or q['holds'] or not report['batches']:
        raise ValueError('Unblocked attachment batch required before retention')
    batch = report['batches'][-1]
    ids = batch['completed_ids']
    if (len(ids) > 4 or len(set(ids)) != len(ids) or ids != batch['planned_ids']
            or batch['detail_requests'] != 0 or batch['attachment_requests'] != len(ids)):
        raise ValueError('Incomplete or unbounded historical attachment batch')
    preceding = [receipt(r) for r in report['records'] if r['source_id'] not in ids]
    if ids != [r['source_id'] for r in plan(history, bodies, preceding)['rows']]:
        raise ValueError('Attachment batch does not follow automatic queue')
    docs = [document(bodies, r) for r in report['records'] if r['source_id'] in ids]
    if len(docs) != len(ids):
        raise ValueError('Attachment batch evidence missing')
    result = retain_documents(conn, docs, docs, wrap_json=wrap_json)
    return {**result, 'announcement_pending': q['pending_count'],
            'source_history_complete': False, 'pe_approval': False, 'published': False}


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_attachment(url):
    """Actions-only caller; cap reads and preserve the existing 25s/3 attempts."""
    validate_url(url)
    opener = build_opener(OfficialRedirects())
    for attempt in range(3):
        try:
            req = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept-Encoding': 'identity'})
            with opener.open(req, timeout=25) as response:
                validate_url(response.geturl())
                raw = response.read(MAX_FILE_BYTES + 1)
            if not raw or len(raw) > MAX_FILE_BYTES:
                raise ValueError('Attachment response empty or oversized')
            return raw
        except HTTPError as error:
            if error.code not in (408, 429) and error.code < 500:
                raise
            if attempt == 2:
                raise
        except (URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
        time.sleep(attempt + 1)


def summary(history, bodies, report):
    q = validate_report(history, bodies, report)
    return {**{k: v for k, v in q.items() if k not in ('rows', 'holds')},
            'holds': report['holds'] + q['holds'],
            'batches': report['batches'],
            'files': [{**receipt(r), 'format': r['extracted']['format'],
                       'text_chars': len(r['extracted']['text'])} for r in report['records']],
            'published': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('collect', 'verify', 'persist'), required=True)
    p.add_argument('--listing-state', type=Path, required=True)
    p.add_argument('--body-state', type=Path, required=True)
    p.add_argument('--attachment-state', type=Path)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    def load(path):
        if path.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError('Historical input exceeds size limit')
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
        report = collect(history, bodies, previous, fetch_attachment)
        save('attachment-state.json', report)
        result = summary(history, bodies, report)
        save('attachment-summary.json', result)
        if result['holds']:
            raise SystemExit('Historical announcement held; inspect saved failure evidence')
    elif args.mode == 'verify':
        if previous is None:
            p.error('--attachment-state required')
        save('attachment-summary.json', summary(history, bodies, previous))
    else:
        if previous is None:
            p.error('--attachment-state required')
        import psycopg
        try:
            with psycopg.connect(os.environ.get('LP_SUPABASE_DB_URL') or os.environ['SUPABASE_DB_URL'],
                                  connect_timeout=20, prepare_threshold=None,
                                  application_name='lp-history-attachments') as conn:
                result = persist(conn, history, bodies, previous)
        except Exception as error:
            raise SystemExit('Private attachment retention failed: ' + type(error).__name__) from None
        save('persistence.json', result)


if __name__ == '__main__':
    main()
