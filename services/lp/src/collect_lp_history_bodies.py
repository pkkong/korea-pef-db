"""Collect a small historical body batch and optionally retain private evidence.

Attachments, PE eligibility, business projection and public publication remain
separate stages. Only source-discovered rows enter this queue.
"""
import argparse
import base64
import copy
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from .lp_history_body_queue import plan
    from .lp_history_sources import institution,listing_digest,effective_history,parse_detail,transport
except ImportError:
    from lp_history_body_queue import plan
    from lp_history_sources import institution,listing_digest,effective_history,parse_detail,transport

KIND = 'lp_history_bodies_v1'
MAX_BYTES = 32 * 1024 * 1024


def read_body(ident, raw, iid='kgrowth'):
    if not isinstance(raw, bytes) or len(raw) > 12 * 1024 * 1024:
        raise ValueError('Historical body response size/type invalid')
    if not re.search(r'</body>\s*</html>',raw.decode('cp949' if iid=='kgrowth' else 'utf-8'),re.I):
        raise ValueError('Historical detail response is incomplete')
    notice = parse_detail(ident,raw,iid)
    if (any('\x00' in notice[k] for k in ('title','body','date','url'))
            or re.search(r'접근\s*권한이\s*없|열람\s*권한이\s*없|비공개\s*게시물|로그인이\s*필요|접근이\s*제한',notice['body'])):
        raise ValueError('Historical body unavailable or unsupported')
    return notice


def validate_report(history, report):
    iid=institution(history)
    if (report.get('kind') != KIND or report.get('window') != history['window']
            or report.get('listing_digest') != listing_digest(history)
            or report.get('institution_id','kgrowth')!=iid):
        raise ValueError('Historical body cursor/listing mismatch')
    ids = []
    for document in report['documents']:
        proof = document.get('discovery_provenance', {})
        if (document.get('institution_id') != iid or proof.get('kind') != 'lp_history_body'
                or proof.get('window') != report['window'] or proof.get('listing_digest') != report['listing_digest']):
            raise ValueError('Historical body retrieval proof missing')
        raw = base64.b64decode(proof['detail_response_base64'],validate=True)
        if len(raw) > 12*1024*1024 or hashlib.sha256(raw).hexdigest() != proof.get('detail_response_sha256'):
            raise ValueError('Historical body response fingerprint mismatch')
        parsed = read_body(document['source_id'],raw,iid)
        allowed = set(parsed) | {'institution_id','checked_at','attachment_hashes',
                                 'attachment_collection_status','discovery_provenance'}
        if (set(document) != allowed or any(parsed[k] != document.get(k) for k in parsed)
                or document.get('attachment_hashes') != {}
                or document.get('attachment_collection_status') != ('pending' if parsed['attachments'] else 'not_applicable')):
            raise ValueError('Historical body differs from retained raw response')
        ids.append(document['source_id'])
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate historical body cursor entry')
    return plan(effective_history(history,report), report['documents'])


def collect(history, previous, fetch, *, cached_documents=(), limit=4, checked_at=None):
    history=effective_history(history,previous)
    iid=institution(history)
    report = copy.deepcopy(previous) if previous else {
        'kind': KIND, 'institution_id':iid,'window': copy.deepcopy(history['window']), 'listing_digest': listing_digest(history),
        'documents': [], 'batches': [], 'holds': []}
    if previous is None and iid=='ktcu':report['retained_records']=copy.deepcopy(history['retained_records'])
    validate_report(history, report)
    if report['holds']:
        raise ValueError('Saved body failure requires diagnosis before resumption')
    queue = plan(history, report['documents'], limit=limit)
    batch = {'checked_at': checked_at or datetime.now(timezone.utc).isoformat(),
             'planned_ids': [r['source_id'] for r in queue['rows']], 'new_ids': [],
             'reused_database_ids': [],
             'detail_requests': 0, 'attachment_requests': 0}
    report['batches'].append(batch)
    for row in queue['rows']:
        raw = None
        try:
            cached = [n for n in cached_documents if n.get('url') == row['url']]
            if cached:
                if len({n.get('sha256') for n in cached}) != 1:
                    raise ValueError('Conflicting retained historical body versions')
                proofs = [n for n in cached if n.get('discovery_provenance',{}).get('kind')=='lp_history_body']
                if not proofs:
                    raise ValueError('Stored body needs retained original retrieval evidence')
                for document in proofs:
                    validate_report(history,{**report,'documents':report['documents']+[document]})
                report['documents'].append(copy.deepcopy(proofs[0]))
                batch['reused_database_ids'].append(row['source_id'])
                continue
            batch['detail_requests'] += 1
            raw = fetch(row['url'])
            notice = read_body(row['source_id'], raw,iid)
            notice.update(institution_id=iid, checked_at=batch['checked_at'], attachment_hashes={},
                          attachment_collection_status='pending' if notice['attachments'] else 'not_applicable')
            notice['discovery_provenance'] = {
                'kind': 'lp_history_body', 'window': report['window'], 'listing_digest': report['listing_digest'],
                'listing_url': row['listing_url'], 'detail_response_sha256': hashlib.sha256(raw).hexdigest(),
                'detail_response_base64': base64.b64encode(raw).decode('ascii')}
            candidate = report['documents'] + [notice]
            plan(history, candidate)  # Replay listing/title/date/body fingerprint independently.
            if len(json.dumps(candidate, ensure_ascii=False).encode()) > MAX_BYTES:
                raise ValueError('Historical body evidence size limit exceeded')
            report['documents'].append(notice)
            batch['new_ids'].append(row['source_id'])
        except Exception as error:
            report['holds'].append({'source_id':row['source_id'], 'url':row['url'],
                                    'error':type(error).__name__+': '+str(error)[:600]})
            if isinstance(raw,bytes) and len(raw)<=12*1024*1024:
                report['failed_response']={'source_id':row['source_id'],'url':row['url'],
                    'sha256':hashlib.sha256(raw).hexdigest(),'raw_base64':base64.b64encode(raw).decode('ascii')}
            break
    return report


def lookup(conn, history, previous):
    history=effective_history(history,previous)
    documents = previous['documents'] if previous else []
    if previous:
        validate_report(history,previous)
        if previous['holds']:
            raise ValueError('Saved body failure requires diagnosis')
    rows = plan(history,documents)['rows']
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    conn.execute("SET LOCAL statement_timeout='120s'")
    results = conn.execute("SELECT document FROM lp_program_private.documents WHERE source_url=ANY(%s) "
                           "AND COALESCE(document->>'owner_closed','false') NOT IN ('true','1') "
                           "AND COALESCE(document->>'restricted','false') NOT IN ('true','1') "
                           "AND COALESCE(document->>'closed','false') NOT IN ('true','1') "
                           "AND COALESCE(document->>'status','') NOT IN ('restricted','owner_closed','closed') "
                           "AND COALESCE(document->>'reason','') <> 'owner_closed' "
                           "AND COALESCE(document#>>'{discovery_provenance,owner_closed}','false') NOT IN ('true','1') "
                           'ORDER BY source_url,content_hash LIMIT 101',([r['url'] for r in rows],)).fetchall()
    if len(results)>100:
        raise ValueError('Retained body version lookup limit exceeded')
    cached = [r[0] for r in results]
    if len(json.dumps(cached,ensure_ascii=False).encode())>MAX_BYTES:
        raise ValueError('Retained body lookup size limit exceeded')
    return cached


def public_guard(conn):
    state = conn.execute('SELECT run_id,md5(data::text),md5(pages::text) '
                         'FROM lp_program_private.program_state WHERE id=1').fetchone()
    reviews = conn.execute("SELECT count(*),md5(COALESCE(jsonb_agg(to_jsonb(d) ORDER BY id),'[]'::jsonb)::text) "
                           'FROM lp_program_private.review_decisions d').fetchone()
    return {'published':list(state) if state else None,'reviews':list(reviews)}


def persist(conn, history, report, *, wrap_json=None):
    validate_report(history, report)
    history=effective_history(history,report)
    if report['holds'] or not report['batches']:
        raise ValueError('Unblocked completed body batch required before retention')
    batch = report['batches'][-1]
    ids = batch['new_ids']
    reused = batch['reused_database_ids']
    produced = ids+reused
    if (len(produced) > 4 or len(set(produced)) != len(produced) or set(produced) != set(batch['planned_ids'])
            or batch['attachment_requests'] != 0 or batch['detail_requests'] > 4):
        raise ValueError('Incomplete or unbounded historical body batch')
    documents = [n for n in report['documents'] if n['source_id'] in ids]
    verified = [n for n in report['documents'] if n['source_id'] in produced]
    if len(documents) != len(ids) or len(verified)!=len(produced):
        raise ValueError('Historical body batch evidence mismatch')
    preceding = [n for n in report['documents'] if n['source_id'] not in produced]
    if batch['planned_ids'] != [r['source_id'] for r in plan(history,preceding)['rows']]:
        raise ValueError('Historical body batch does not follow the automatic queue')
    result = retain_documents(conn, documents, verified, wrap_json=wrap_json)
    return {**result, 'reused_database_documents':len(reused),
            'attachment_completion':'pending', 'source_history_complete':False,'published':False}


def retain_documents(conn, documents, verified, *, wrap_json=None, verify_retained=None):
    """Append independently validated evidence; never change reviews/publication.

    Callers must replay their source-specific raw proof and automatic queue
    before entering this shared transaction. Existing versions are immutable.
    An optional source guard runs under the publication lock before any store.
    """
    try:
        from .publish_lp_programs import document_hash, store_documents
    except ImportError:
        from publish_lp_programs import document_hash, store_documents
    if not 0 <= len(documents) <= len(verified) <= 4:
        raise ValueError('Unbounded historical evidence retention')
    if verify_retained is not None and not callable(verify_retained):
        raise ValueError('Historical evidence guard must be callable')
    if wrap_json is None:
        from psycopg.types.json import Jsonb
        wrap_json = Jsonb
    conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
    conn.execute("SET LOCAL lock_timeout='20s'")
    conn.execute("SET LOCAL statement_timeout='120s'")
    conn.execute('SELECT pg_advisory_xact_lock(728160921)')
    before = public_guard(conn)
    before_count = conn.execute('SELECT count(*) FROM lp_program_private.documents').fetchone()[0]
    if verify_retained is not None:
        verify_retained(conn)
    stored = store_documents(conn, {'notices':documents}, {}, wrap_json)
    expected = {(n['url'],document_hash(n)) for n in verified}
    rows = conn.execute('SELECT source_url,content_hash FROM lp_program_private.documents '
                        'WHERE source_url=ANY(%s)', ([n['url'] for n in verified],)).fetchall()
    if not expected <= set(rows):
        raise ValueError('Historical body database readback mismatch')
    after_count = conn.execute('SELECT count(*) FROM lp_program_private.documents').fetchone()[0]
    after = public_guard(conn)
    if before != after or not 0 <= after_count-before_count <= len(documents):
        raise ValueError('Public state/review or document count changed unexpectedly')
    return {'documents_before':before_count,'documents_after':after_count,
            'new_document_versions':after_count-before_count,'verified_batch_documents':len(verified),
            'submitted_documents':stored,
            'before':before,'after':after,'public_state_preserved':True,
            'source_urls':[n['url'] for n in documents]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('lookup','collect','persist'),required=True)
    parser.add_argument('--listing-state',type=Path,required=True)
    parser.add_argument('--body-state',type=Path)
    parser.add_argument('--cached-documents',type=Path)
    parser.add_argument('--database-index',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    args = parser.parse_args()
    def load(path):
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('Historical evidence input size limit exceeded')
        return json.loads(path.read_text())
    def save(name,data):
        target=args.output_dir/name
        temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False))
        temporary.replace(target)
    history = load(args.listing_state)
    previous=load(args.body_state) if args.body_state else None
    history=effective_history(history,previous,load(args.database_index) if args.database_index else None)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    if args.mode == 'collect':
        report = collect(history,previous,transport(history),
                         cached_documents=load(args.cached_documents) if args.cached_documents else ())
        queue = validate_report(history,report)
        result = {k:v for k,v in queue.items() if k!='rows'}
        result.update(holds=report['holds'],last_batch=report['batches'][-1],published=False)
        save('body-state.json',report)
        save('body-summary.json',result)
        print(json.dumps(result,ensure_ascii=False))
        return 1 if report['holds'] else 0
    if args.mode=='persist' and not args.body_state:
        parser.error('Persistence requires saved body evidence')
    import psycopg
    with psycopg.connect(os.environ.get('LP_SUPABASE_DB_URL') or os.environ['SUPABASE_DB_URL'],
                          connect_timeout=20,prepare_threshold=None,application_name='lp-history-bodies') as conn:
        if args.mode=='lookup':
            cached = lookup(conn,history,previous)
            save('cached-bodies.json',cached)
            print(json.dumps({'bounded_retained_versions':len(cached),'official_http_requests':0}))
            return 0
        result = persist(conn,history,previous)
    save('persistence.json',result)
    print(json.dumps(result,ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        raise SystemExit('LP historical body operation failed: '+type(error).__name__) from None
