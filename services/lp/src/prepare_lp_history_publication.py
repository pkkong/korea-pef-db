"""Read-only historical publication preflight, independent of daily collection.

Replay source-discovered files and require the exact retained database versions.
This command never collects, writes to the database, or publishes pages.
"""
import argparse
import copy
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from .lp_history_sources import listing_summary
    from .collect_lp_history_bodies import validate_report as validate_bodies
    from .collect_lp_history_attachments import validate_report, document, MAX_REPORT_BYTES
    from .lp_ktcu_history_terms import extract_offering
    from .lp_notice_publication import publish_basic_notices
except ImportError:
    from lp_history_sources import listing_summary
    from collect_lp_history_bodies import validate_report as validate_bodies
    from collect_lp_history_attachments import validate_report, document, MAX_REPORT_BYTES
    from lp_ktcu_history_terms import extract_offering
    from lp_notice_publication import publish_basic_notices


def verified_documents(history, bodies, attachments):
    listing = listing_summary(history)  # Reparse every retained listing byte/identity.
    body_queue = validate_bodies(history, bodies)
    queue = validate_report(history, bodies, attachments)
    if (not listing['listing_window_complete'] or listing['holds']
            or history['window']['start'] != '2023-01-01' or bodies.get('holds')
            or attachments.get('holds') or queue['holds'] or queue['pending_count']
            or body_queue['pending_count'] or not 1 <= len(attachments['records']) <= 4):
        raise ValueError('Complete unblocked bounded historical evidence required')
    return [document(bodies, record) for record in attachments['records']]


def retained_documents(conn, documents):
    """Compare both the stored content key and its actual JSON, not metadata alone."""
    from publish_lp_programs import document_hash
    rows = conn.execute(
        'SELECT source_url,content_hash,document FROM lp_program_private.documents '
        'WHERE source_url=ANY(%s) ORDER BY source_url,content_hash LIMIT 101',
        ([n['url'] for n in documents],)).fetchall()
    if len(rows) > 100:
        raise ValueError('Historical source version comparison exceeds bound')
    for n in documents:
        digest = document_hash(n)
        matches = [stored for url, key, stored in rows if url == n['url'] and key == digest]
        if len(matches) != 1 or document_hash(matches[0]) != digest:
            raise ValueError('Historical source version missing or inconsistent in database')
        for url, _, stored in rows:
            if url != n['url']:
                continue
            if stored.get('sha256') != n['sha256'] or any(
                    stored.get('attachment_hashes', {}).get(u, h) != h
                    for u, h in n['attachment_hashes'].items()):
                raise ValueError('Conflicting retained historical body or attachment version')
    return [{'url': n['url'], 'content_hash': document_hash(n)} for n in documents]


def proposal(current, documents, checked_at):
    """Add eligible recruitments while preserving every existing program field.

    Existing source owners are retained; conflicting IDs/ambiguous owners fail.
    Daily freshness, collection coverage and review decisions remain unchanged.
    """
    from lp_program_service import validate, assert_selected_gp_history
    from publish_lp_programs import document_hash
    eligible, held = [], []
    for notice in documents:
        try:
            extract_offering(notice)
        except ValueError as error:
            held.append({'url': notice['url'], 'date': notice['date'],
                         'stage': 'historical_offering', 'reason': str(error)})
        else:
            eligible.append(notice)
    programs, holds = publish_basic_notices({'programs': [], 'priority_notices': eligible}, [], checked_at)
    represented = {e['url'] for program in programs for e in program['events'] if e['type'] == '모집 공고'}
    if holds or represented != {n['url'] for n in eligible}:
        raise ValueError('Historical common publication validation failed')
    after = copy.deepcopy(current)
    existing = {p['id']: p for p in current['programs']}
    if len(existing) != len(current['programs']):
        raise ValueError('Duplicate existing program identity')
    added, reused = [], []
    for program in programs:
        urls = {e['url'] for e in program['events'] if e['type'] == '모집 공고'}
        matches = [p for p in current['programs'] if p['institution_id'] == program['institution_id']
                   and (p.get('source_program_key') == program['source_program_key']
                        or urls & {e['url'] for e in p['events'] if e['type'] == '모집 공고'})]
        if len(matches) > 1 or (program['id'] in existing and not matches):
            raise ValueError('Ambiguous or conflicting historical program identity')
        if matches:
            reused.append(matches[0]['id'])
            continue
        if program.get('selected_gps'):
            raise ValueError('Recruitment evidence cannot establish a final GP roster')
        # Replaying old bytes is not a new observation of the official source.
        source = next(n for n in eligible if n['url'] in urls)
        program['checked_at'] = source['checked_at']
        after['programs'].append(program)
        added.append(program)
    priority = {n['url']: n for n in after.get('priority_notices', [])}
    for notice in documents:
        previous = priority.get(notice['url'])
        if previous and document_hash(previous) != document_hash(notice):
            raise ValueError('Historical replay conflicts with a retained publication source')
        priority.setdefault(notice['url'], copy.deepcopy(notice))
    after['priority_notices'] = list(priority.values())
    validate(after)
    assert_selected_gp_history(current['programs'], after['programs'])
    if after['programs'][:len(current['programs'])] != current['programs']:
        raise ValueError('Existing public programs changed')
    return after, {'new_programs': added, 'retained_program_ids': reused, 'holds': held,
                   'programs_before': len(current['programs']), 'programs_after': len(after['programs']),
                   'existing_programs_preserved': True, 'daily_as_of_preserved': after.get('as_of') == current.get('as_of')}


def preflight(conn, history, bodies, attachments, checked_at):
    from publish_lp_programs import baseline, publication_revision
    from lp_program_service import build
    documents = verified_documents(history, bodies, attachments)
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    conn.execute("SET LOCAL statement_timeout='120s'")
    current = baseline(conn)
    before = publication_revision(conn)
    if before[0] is None:
        raise ValueError('Existing public state required for historical preflight')
    retained = retained_documents(conn, documents)
    after, result = proposal(current, documents, checked_at)
    with tempfile.TemporaryDirectory() as folder:
        build(after, Path(folder))
        pages = len(list(Path(folder).glob('*.html')))
    if publication_revision(conn) != before:
        raise ValueError('Read snapshot unexpectedly changed')
    return {**result, 'kind': 'lp_history_publication_preflight_v1', 'checked_at': checked_at,
            'baseline_run_id': before[0][0], 'retained_documents': retained, 'built_pages': pages,
            'official_http_requests': 0, 'database_writes': 0, 'published': False,
            'source_history_complete': False, 'scheduled_success': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('listing-state', 'body-state', 'attachment-state', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    def load(path):
        if path.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError('Historical artifact exceeds size limit')
        return json.loads(path.read_text())
    from publish_lp_programs import connect
    with connect() as conn:
        result = preflight(conn, load(args.listing_state), load(args.body_state),
                           load(args.attachment_state), datetime.now(timezone.utc).isoformat())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False))
    print(json.dumps({k: result[k] for k in ('baseline_run_id', 'programs_before', 'programs_after',
                                           'official_http_requests', 'database_writes', 'published')}))


if __name__ == '__main__':
    main()
