"""Compare saved NH listing recovery with a read-only retained identity index."""
import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

try:
    from . import audit_lp_official_inventory as inventory
    from .diagnose_lp_inventory_failures import recover_boundaries
    from .lp_state_storage import unpack_state
except ImportError:
    import audit_lp_official_inventory as inventory
    from diagnose_lp_inventory_failures import recover_boundaries
    from lp_state_storage import unpack_state


def read_identity_index(conn):
    # This must be the first statement of a fresh transaction.
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    conn.execute("SET LOCAL statement_timeout='120s'")
    row = conn.execute('SELECT data,run_id FROM lp_program_private.program_state WHERE id=1').fetchone()
    if row is None:
        raise ValueError('published state required for identity comparison')
    data = unpack_state(row[0])
    public = {key for key in inventory.known_keys([{'programs': data['programs']}])
              if key.startswith('nh_central:')}
    rows = conn.execute("SELECT DISTINCT source_url FROM lp_program_private.documents "
        "WHERE document->>'institution_id'=%s OR source_url LIKE %s ORDER BY source_url LIMIT 10001",
        ('nh_central', 'https://www.nonghyup.com/%')).fetchall()
    if len(rows) > 10000:
        raise ValueError('retained NH identity index exceeded its bound')
    retained, supporting = set(), set()
    for item in rows:
        # The issuer field also labels association reposts. Those are retained
        # supporting sources, never native NH board identities.
        parsed = urlsplit(item[0])
        board = re.fullmatch(r'/brd/m_(212|17)/view.do', parsed.path)
        if (parsed.scheme == 'https' and parsed.hostname == 'www.kofia.or.kr' and board
                and not parsed.username and not parsed.password and parsed.port in {None, 443}
                and not parsed.fragment):
            identifiers = parse_qs(parsed.query).get('seq', [])
            if len(identifiers) != 1 or not identifiers[0].isdigit():
                raise ValueError('invalid retained association notice identity')
            supporting.add('kofia_'+board[1]+':'+identifiers[0])
            continue
        retained.add(inventory.notice_key('nh_central', item[0]))
    return {'kind': 'lp_nh_retained_identity_index_v1', 'complete': True, 'read_only': True,
            'checked_at': datetime.now(timezone.utc).isoformat(), 'public_run': row[1],
            'retained_source_urls': len(rows), 'retained_keys': sorted(retained),
            'supporting_source_keys': sorted(supporting), 'public_keys': sorted(public)}


def merge(report, recovery, identities):
    if (identities.get('kind') != 'lp_nh_retained_identity_index_v1'
            or identities.get('complete') is not True or identities.get('read_only') is not True
            or not identities.get('checked_at') or not identities.get('public_run')):
        raise ValueError('complete read-only NH identity comparison required')
    for field in ('retained_keys', 'public_keys'):
        if not isinstance(identities.get(field), list) or any(
                not isinstance(k, str) or not re.fullmatch(r'nh_central:(?:notice|bid):[1-9][0-9]*', k)
                for k in identities[field]):
            raise ValueError('invalid retained or public NH identity')
    def no_source_http(_):
        raise AssertionError('comparison must not fetch official sources')
    replay = recover_boundaries(report, recovery, fetch=no_source_http, plan_only=True)
    if not replay['nh_listing_boundaries_complete'] or replay['status'] != 'ok':
        raise ValueError('NH listing boundaries still incomplete')
    cache = {r['url']: r['html'].encode() for r in replay['listing_receipts']}
    nh = inventory.audit({}, as_of=report['as_of'],
        configs={'nh_central': inventory.boards.load_configs(include_pending=True)['nh_central']},
        scope={'confirmed_institution_ids': [], 'priority_verification_ids': ['nh_central']},
        independent=True, page_budget=200, fetch_factory=lambda *a: lambda u: cache[u])
    if nh['holds'] or nh['institutions'][0]['status'] != 'observed_query_boundary':
        raise ValueError('saved NH listing replay is incomplete')
    entry = nh['institutions'][0]
    public, retained = set(identities['public_keys']), set(identities['retained_keys'])
    for item in entry['rows']:
        item['disposition'] = ('public_linked' if item['source_id'] in public else
                               'archived_unpublished' if item['source_id'] in retained else 'not_in_archive')
    entry['counts']['by_disposition'] = dict(Counter(r['disposition'] for r in entry['rows']))
    entry['counts']['unarchived_relevant'] = sum(r['relevant'] and r['disposition'] == 'not_in_archive' for r in entry['rows'])
    entry['counts']['explicit_pe_blind_unarchived'] = sum(r['relevant'] and r['disposition'] == 'not_in_archive'
        and r['title_scope'] == 'pe_blind_title' for r in entry['rows'])
    result = copy.deepcopy(report)
    # Preserve all old indexes: the other 23 entries and all 116 old receipts
    # remain exact copies. Only newly observed NH receipts are appended.
    positions = {(r['url'], r['sha256']): i for i, r in enumerate(result['receipts'])}
    mapping = {}
    for i, receipt in enumerate(nh['receipts']):
        key = (receipt['url'], receipt['sha256'])
        if key not in positions:
            positions[key] = len(result['receipts'])
            result['receipts'].append(receipt)
        mapping[i] = positions[key]
    for query in entry['queries']:
        query['pages'] = [mapping[i] for i in query['pages']]
    old = next(i for i, e in enumerate(result['institutions']) if e['institution_id'] == 'nh_central')
    entry['name'] = result['institutions'][old]['name']
    entry['role'] = result['institutions'][old]['role']
    result['institutions'][old] = entry
    result['holds'] = [h for h in result['holds'] if h['institution_id'] != 'nh_central']
    summary = result['summary']
    summary.update(pages=len(result['receipts']), requests=len(result['receipts']),
        requests_kind='saved_listing_replay', new_official_http_requests=0,
        source_errors=len(result['holds']),
        audited=sum(e['counts'] is not None for e in result['institutions']),
        unmeasured=sum(e['counts'] is None for e in result['institutions']),
        limited_institutions=[e['institution_id'] for e in result['institutions'] if e['status'] == 'query_limit'])
    candidates = [r for e in result['institutions'] for r in e['rows']
                  if r['relevant'] and r['disposition'] == 'not_in_archive']
    summary['unarchived_relevant'] = len(candidates)
    summary['unarchived_by_title_scope'] = dict(Counter(r['title_scope'] for r in candidates))
    result['listing_recovery'] = {'mode': 'manual_saved_receipt_replay', 'scheduled_success': False,
        'original_summary': copy.deepcopy(report['summary']), 'original_holds': copy.deepcopy(report['holds']),
        'identity_comparison_scope': ['nh_central'], 'identity_index': copy.deepcopy(identities),
        'new_official_http_requests': 0, 'publication': False}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--recovery', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.inventory.read_text())
    recovery = json.loads(args.recovery.read_text())
    # Validate every saved receipt before opening the read-only DB transaction.
    replay = recover_boundaries(source, recovery, plan_only=True)
    if not replay['nh_listing_boundaries_complete'] or replay['new_queries']:
        raise ValueError('completed saved boundary recovery required')
    import psycopg
    with psycopg.connect(os.environ['SUPABASE_DB_URL'], connect_timeout=20,
                        application_name='lp-inventory-read-only-comparison') as conn:
        identities = read_identity_index(conn)
    result = merge(source, recovery, identities)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    args.output.with_suffix('.md').write_text(inventory.markdown(result))
    print(json.dumps({'summary': result['summary'], 'identity_index': identities}, ensure_ascii=False))


if __name__ == '__main__':
    main()
