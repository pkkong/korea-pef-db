"""Bounded historical listing discovery; no detail fetches or publication.

The historical window starts on 2023-01-01. Its end is frozen to the retained
listing observation. Each successful batch is an independently replayable
artifact, not a database schema or a PE eligibility decision.
"""
import argparse
import base64
import copy
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from .kgrowth_listing import LIST_URL, parse_listing, source_id
    from .build_lp_history_coverage import validate_index, valid_index_record
except ImportError:
    from kgrowth_listing import LIST_URL, parse_listing, source_id
    from build_lp_history_coverage import validate_index, valid_index_record

START = '2023-01-01'
KIND = 'lp_history_listing_v1'
MAX_PAGES = 200
MAX_STATE_BYTES = 32 * 1024 * 1024


def page_url(page):
    if type(page) is not int or not 1 <= page <= MAX_PAGES:
        raise ValueError('Historical page outside safety limit')
    return LIST_URL if page == 1 else LIST_URL + '&page=' + str(page)


def receipt(page, raw):
    if not isinstance(raw, bytes) or len(raw) > 12 * 1024 * 1024:
        raise ValueError('Invalid historical listing response')
    html = raw.decode('cp949')
    rows = parse_listing(html, page_url(page))
    return {'page': page, 'url': page_url(page), 'sha256': hashlib.sha256(raw).hexdigest(),
            'html': html, 'row_count': len(rows)}


def receipt_rows(item, page):
    if item.get('page') != page or item.get('url') != page_url(page):
        raise ValueError('Historical receipt page identity mismatch')
    rebuilt = receipt(page, item['html'].encode('cp949'))
    if any(item.get(k) != rebuilt[k] for k in ('sha256', 'row_count')):
        raise ValueError('Historical receipt fingerprint or row count mismatch')
    return parse_listing(item['html'], item['url'])


def replay(state):
    if (state.get('kind') != KIND or state.get('institution_id') != 'kgrowth'
            or state.get('query') != {'listing_url': LIST_URL, 'search': ''}
            or state.get('window', {}).get('start') != START):
        raise ValueError('Historical cursor identity or fixed start mismatch')
    end = state['window']['end']
    if date.fromisoformat(end).isoformat() != end or end < START:
        raise ValueError('Invalid historical window end')
    receipts = state['receipts']
    if not isinstance(receipts, list) or len(receipts) > MAX_PAGES:
        raise ValueError('Historical receipt limit exceeded')
    observed, seen, prior, boundary = {}, set(), None, 'batch_limit'
    for page, item in enumerate(receipts, 1):
        if boundary != 'batch_limit':
            raise ValueError('Historical pages appear after a terminal boundary')
        rows = receipt_rows(item, page)
        regular = [r for r in rows if not r['pinned']]
        ids = {r['source_id'] for r in regular}
        if rows and (not regular or not ids - seen):
            raise ValueError('Repeated or pinned-only historical page')
        for row in rows:
            ident = row['source_id']
            if ident in observed and any(observed[ident][k] != row[k] for k in ('title', 'date', 'pinned')):
                raise ValueError('Historical listing metadata conflict')
            observed[ident] = row
        for row in regular:
            if prior is not None and row['date'] > prior:
                raise ValueError('Historical listing is not in descending date order')
            prior = row['date']
        seen.update(ids)
        if not rows:
            boundary = 'confirmed_empty'
        elif regular and all(r['date'] < START for r in regular):
            boundary = 'observed_older_page'
    return {'rows': [r for r in observed.values() if START <= r['date'] <= end],
            'boundary': boundary, 'listing_window_complete': boundary != 'batch_limit',
            'next_page': len(receipts) + 1}


def retained_index(index):
    validate_index(index)
    if (index.get('kind') != 'lp_document_index_v1' or index.get('database_index_complete') is not True
            or index.get('database_rows') != index.get('database_total_rows')):
        raise ValueError('Complete retained database metadata index required')
    retained = []
    for record in index['records']:
        if record.get('institution_id') != 'kgrowth':
            continue
        if not valid_index_record(record):
            raise ValueError('Invalid retained official body metadata')
        try:
            source_id(record['url'])
        except ValueError:
            continue  # Association reposts are not retained official body proof.
        # An existing URL alone is not proof of a reusable body version.
        if record.get('body_present') is True and re.fullmatch(r'[a-f0-9]{64}', record.get('source_sha256') or ''):
            retained.append({k: record[k] for k in ('url', 'date', 'title', 'source_sha256')})
    return retained


def bootstrap(collection, index):
    inventory = collection['collection_coverage']['date_discovery']
    if not inventory.get('receipts') or inventory.get('complete') is not True:
        raise ValueError('Verified retained listing receipts required')
    state = {'kind': KIND, 'institution_id': 'kgrowth',
             'query': {'listing_url': LIST_URL, 'search': ''},
             'window': {'start': START, 'end': inventory['window']['end']},
             'receipts': copy.deepcopy(inventory['receipts']), 'continuity_receipts': [],
             'retained_index_checked_at': index['checked_at'], 'retained_records': retained_index(index),
             'holds': [], 'batches': []}
    # Recompute the broader historical boundary; a 365-day boundary is not it.
    replay(state)
    return state


def summary(state):
    result = replay(state)
    compact = lambda value: re.sub(r'\s+', '', value)
    retained = {(source_id(r['url']), r['date'], compact(r['title'])) for r in state['retained_records']}
    for row in result['rows']:
        row['retained_body_observed'] = (row['source_id'], row['date'], compact(row['title'])) in retained
    years = {}
    for row in result['rows']:
        year = row['date'][:4]
        years[year] = years.get(year, 0) + 1
    return {**result, 'institution_id': 'kgrowth', 'window': state['window'],
            'listing_pages': len(state['receipts']), 'listing_rows_by_year': years,
            'retained_body_observed': sum(r['retained_body_observed'] for r in result['rows']),
            'pending_body_verification': sum(not r['retained_body_observed'] for r in result['rows']),
            'source_history_complete': False, 'pe_business_count': None,
            'holds': state['holds'], 'last_batch': state['batches'][-1] if state['batches'] else None}


def run_batch(previous, fetch, *, batch_pages=4, checked_at=None):
    if type(batch_pages) is not int or not 1 <= batch_pages <= 4:
        raise ValueError('Historical batch must contain 1 to 4 new pages')
    state = copy.deepcopy(previous)
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_STATE_BYTES:
        raise ValueError('Historical state size limit exceeded')
    result = replay(state)
    if state.get('holds'):
        raise ValueError('Resolve saved historical failure before resuming')
    if result['listing_window_complete']:
        return state
    stats = {'checked_at': checked_at or datetime.now(timezone.utc).isoformat(),
             'start_page': result['next_page'], 'new_pages': 0, 'listing_requests': 0,
             'successful_response_bytes': 0}
    state['batches'].append(stats)
    active_page, response_evidence = None, None

    def get(page):
        nonlocal active_page, response_evidence
        active_page, response_evidence = page, None
        url = page_url(page)
        stats['listing_requests'] += 1
        raw = fetch(url)
        stats['successful_response_bytes'] += len(raw)
        if not isinstance(raw, bytes) or len(raw) > 12 * 1024 * 1024:
            raise ValueError('Invalid historical listing response')
        response_evidence = {'page': page, 'url': url,
                             'sha256': hashlib.sha256(raw).hexdigest(),
                             'raw_base64': base64.b64encode(raw).decode('ascii')}
        return receipt(page, raw)

    try:
        # Page-number boards can shift between runs. Recheck the stored overlap
        # instead of silently skipping or duplicating records after an insertion.
        if state['receipts']:
            page = len(state['receipts'])
            anchor = get(page)
            if receipt_rows(anchor, page) != receipt_rows(state['receipts'][-1], page):
                raise ValueError('Historical pagination changed; saved prefix requires reconciliation')
            state['continuity_receipts'].append(anchor)
        for _ in range(batch_pages):
            page = len(state['receipts']) + 1
            item = get(page)
            candidate = {**state, 'receipts': state['receipts'] + [item]}
            next_result = replay(candidate)
            if len(json.dumps(candidate, ensure_ascii=False).encode()) > MAX_STATE_BYTES:
                raise ValueError('Historical state size limit exceeded')
            state['receipts'].append(item)
            stats['new_pages'] += 1
            if next_result['listing_window_complete']:
                break
    except Exception as exc:
        # Retain all valid pages and an actionable failure; never call it complete.
        state['holds'].append({'page': active_page,
                               'error': type(exc).__name__ + ': ' + str(exc)[:600]})
        if response_evidence is not None:
            state['failed_response'] = response_evidence
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--seed-collection', type=Path)
    parser.add_argument('--database-index', type=Path)
    parser.add_argument('--batch-pages', type=int, default=4)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if bool(args.state) == bool(args.seed_collection) or (not args.state and not args.database_index):
        parser.error('Choose a saved cursor, or a retained collection plus database index')
    def load(path):
        if path.stat().st_size > MAX_STATE_BYTES:
            raise ValueError('Historical input size limit exceeded')
        return json.loads(path.read_text())
    state = load(args.state) if args.state else bootstrap(load(args.seed_collection), load(args.database_index))
    # Existing transport keeps its cookie/TLS/size/timeout/three-attempt bounds.
    from collect_kgrowth_programs import official_fetcher
    result = run_batch(state, official_fetcher(), batch_pages=args.batch_pages)
    report = summary(result)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in (('history-state.json', result), ('history-summary.json', report)):
        target = args.output_dir / name
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False))
        temporary.replace(target)
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}, ensure_ascii=False))
    return 1 if result['holds'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
