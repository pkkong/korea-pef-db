"""Publish already-retained historical recruitments without daily recollection."""
import argparse
import copy
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from prepare_lp_history_publication import verified_documents, retained_documents, proposal
from publish_lp_programs import connect, baseline, publication_revision, store_collection_report, store_public_state
from lp_program_service import build
from lp_state_storage import unpack_state


def prepare(history, bodies, attachments, provenance, checked_at):
    documents = verified_documents(history, bodies, attachments)
    with connect() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL statement_timeout='120s'")
        current = baseline(conn)
        revision = publication_revision(conn)
        if revision[0] is None:
            raise ValueError('Existing public state required for historical publication')
        retained = retained_documents(conn, documents)
        old_pages = conn.execute('SELECT pages FROM lp_program_private.program_state WHERE id=1').fetchone()[0]
    data, summary = proposal(current, documents, checked_at)
    if not summary['new_programs']:
        return None, {**summary, 'baseline_run_id': revision[0][0], 'published': False,
                      'reason': 'no_new_verified_programs', 'official_http_requests': 0}
    if not isinstance(old_pages, dict) or not old_pages.get('review.html'):
        raise ValueError('Existing review page required for preservation')
    with tempfile.TemporaryDirectory() as folder:
        # The renderer adds GP page keys in-place; preserve the stored model.
        build(copy.deepcopy(data), Path(folder))
        rebuilt = {p.name: p.read_text() for p in Path(folder).glob('*.html')}
    for program in current['programs']:
        name = 'program-'+program['id']+'.html'
        if not old_pages.get(name) or rebuilt.get(name) != old_pages[name]:
            raise ValueError('Existing public detail changed during historical addition')
    pages = {**old_pages, **rebuilt}  # Keep review and other retained pages exactly.
    summary = {**summary, 'baseline_run_id': revision[0][0], 'pages': len(pages),
               'existing_detail_pages_preserved': True, 'review_page_preserved': True,
               'retained_documents': retained, 'official_http_requests': 0,
               'source_history_complete': False, 'scheduled_success': False}
    report = {'kind': 'lp_history_publication_v1', 'notices': documents,
              'checked_at': max(n['checked_at'] for n in documents), 'prepared_at': checked_at,
              'source_runs': copy.deepcopy(provenance), 'preflight': summary}
    return (report, data, pages, revision), summary


def commit(prepared):
    report, data, pages, revision = prepared
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    run_id = hashlib.sha256((datetime.now(timezone.utc).isoformat()+encoded).encode()).hexdigest()[:24]
    with connect() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        conn.execute("SET LOCAL lock_timeout='20s'")
        conn.execute("SET LOCAL statement_timeout='120s'")
        conn.execute("SET LOCAL idle_in_transaction_session_timeout='300s'")
        conn.execute('SELECT pg_advisory_xact_lock(728160921)')
        if publication_revision(conn) != revision:
            raise RuntimeError('LP publication or reviews changed; keep current publication')
        # Recheck immutable evidence under the same write lock. No document or
        # review INSERT/UPDATE is needed: these exact versions already exist.
        retained_documents(conn, report['notices'])
        store_collection_report(conn, encoded, run_id, 'lp_history')
        store_public_state(conn, data, pages, run_id)
        stored = conn.execute('SELECT data,pages,run_id FROM lp_program_private.program_state WHERE id=1').fetchone()
        if (not stored or unpack_state(stored[0]) != data or stored[1] != pages or stored[2] != run_id
                or publication_revision(conn)[1] != revision[1]):
            raise ValueError('Historical publication readback or review preservation failed')
    return {**report['preflight'], 'run_id': run_id, 'published': True,
            'database_readback_verified': True, 'document_versions_added': 0,
            'program_ids': [p['id'] for p in data['programs']],
            'new_program_ids': [p['id'] for p in report['preflight']['new_programs']]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('listing-state', 'body-state', 'attachment-state', 'provenance', 'output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    def load(path):
        if path.stat().st_size > 32*1024*1024:
            raise ValueError('Historical input exceeds size limit')
        return json.loads(path.read_text())
    prepared, summary = prepare(load(args.listing_state), load(args.body_state),
                                load(args.attachment_state), load(args.provenance),
                                datetime.now(timezone.utc).isoformat())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'preflight.json').write_text(json.dumps(summary, ensure_ascii=False))
    result = commit(prepared) if prepared is not None else summary
    (args.output_dir/'publication.json').write_text(json.dumps(result, ensure_ascii=False))
    print(json.dumps({k: result[k] for k in ('baseline_run_id', 'programs_before', 'programs_after', 'published')}))


if __name__ == '__main__':
    main()
