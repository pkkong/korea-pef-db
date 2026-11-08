"""Probe at most two saved failed NH listing requests; never repair an audit."""
import argparse
import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

try:
    from . import audit_lp_official_inventory as inventory
except ImportError:
    import audit_lp_official_inventory as inventory


def failure_plan(report, *, limit=2, resume=None):
    """Accept only the observed first-page NH failures, not arbitrary URLs."""
    if type(limit) is not int or not 1 <= limit <= 2:
        raise ValueError('diagnostic request limit must be one or two')
    if report.get('query_policy') != 'independent_v1':
        raise ValueError('independent saved inventory required')
    start, end = inventory.window(report['as_of'])
    if report.get('window') != {'start': start, 'end': end, 'days': 365}:
        raise ValueError('saved inventory window changed')
    config = inventory.boards.load_configs(include_pending=True)['nh_central']
    entries = [e for e in report['institutions'] if e['institution_id'] == 'nh_central']
    if len(entries) != 1 or entries[0]['status'] != 'source_error':
        raise ValueError('one failed NH inventory required')
    expected = inventory.query_plan('nh_central', config, start, end, independent=True)
    queries = entries[0]['queries']
    if len(queries) != len(expected):
        raise ValueError('saved NH query plan changed')
    holds = [h for h in report['holds'] if h['institution_id'] == 'nh_central']
    failed = {h['url']: h for h in holds}
    if len(failed) != len(holds):
        raise ValueError('duplicate saved failure')
    requests = []
    for query, plan in zip(queries, expected):
        if any(query.get(k) != plan[k] for k in ('term', 'kind', 'limit', 'listing_url')):
            raise ValueError('saved NH query identity changed')
        if query['boundary'] != 'source_error':
            continue
        # Later-page/parser recovery needs its own continuity verification.
        if query['pages']:
            raise ValueError('only failed first-page requests are diagnostic targets')
        url = inventory.page_url('nh_central', config, plan['term'], 1, start, end,
                                 listing_url=plan['listing_url'])
        if url not in failed or not failed[url].get('error'):
            raise ValueError('saved failure and query do not match')
        requests.append({'url': url, 'term': plan['term'], 'kind': plan['kind'],
                         'original_error': failed[url]['error']})
    if not requests or {r['url'] for r in requests} != set(failed):
        raise ValueError('unmatched saved NH failures')
    reused = []
    if resume is not None:
        if (resume.get('kind') != 'lp_failed_listing_diagnostic_v1' or resume.get('status') != 'ok'
                or resume.get('original_audit_holds') != report['holds']
                or resume.get('audit_recovered') is not False or resume.get('publication') is not False):
            raise ValueError('only successful diagnostics of the same failures may resume')
        digest = hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if resume.get('inventory_sha256', digest) != digest:
            raise ValueError('diagnostic inventory changed')
        reused = resume.get('results')
        if (not isinstance(reused, list) or not reused or len(reused) > len(requests)
                or resume.get('attempted_queries') != len(reused)):
            raise ValueError('invalid diagnostic progress')
        for expected, observed in zip(requests, reused):
            if (any(observed.get(k) != value for k, value in expected.items())
                    or observed.get('status') != 'ok'):
                raise ValueError('diagnostic query order or status changed')
            raw = base64.b64decode(observed['raw_base64'], validate=True)
            if (len(raw) > inventory.boards.MAX_BYTES or len(raw) != observed['bytes']
                    or hashlib.sha256(raw).hexdigest() != observed['sha256']):
                raise ValueError('diagnostic response proof changed')
            rows = inventory.boards.nh.parse_listing(inventory.boards.decode_html(raw), expected['url'], config)
            if len(rows) != observed['row_count']:
                raise ValueError('diagnostic row count changed')
        reused = copy.deepcopy(reused)
    pending = requests[len(reused):]
    return {'institution_id': 'nh_central', 'failed_queries': len(requests),
            'requests': pending[:limit], 'reused_results': reused,
            'unprobed_queries': len(pending)-min(limit, len(pending))}


def diagnose(report, *, fetch=None, limit=2, resume=None):
    plan = failure_plan(report, limit=limit, resume=resume)
    reused = plan.pop('reused_results')
    config = inventory.boards.load_configs(include_pending=True)['nh_central']
    fetch = fetch or inventory.boards.Session(config)
    result = {**plan, 'kind': 'lp_failed_listing_diagnostic_v1',
              'checked_at': datetime.now(timezone.utc).isoformat(),
              'inventory_sha256': hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
              'original_audit_holds': report['holds'], 'results': reused,
              'reused_queries': len(reused),
              'audit_recovered': False, 'publication': False}
    for request in plan['requests']:
        observed = dict(request)
        try:
            raw = fetch(request['url'])
            if not isinstance(raw, bytes) or len(raw) > inventory.boards.MAX_BYTES:
                raise ValueError('diagnostic response size or type invalid')
            observed.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                            raw_base64=base64.b64encode(raw).decode('ascii'))
            html = inventory.boards.decode_html(raw)
            rows = inventory.boards.nh.parse_listing(html, request['url'], config)
            observed.update(status='ok', row_count=len(rows))
        except Exception as error:
            observed.update(status='error', error_type=type(error).__name__, error=str(error),
                            dns_error=inventory.boards.transient_dns(error))
        result['results'].append(observed)
        # A repeated outage is enough evidence; do not keep probing this host.
        if observed['status'] == 'error':
            break
    result['attempted_queries'] = len(result['results'])
    result['new_queries'] = result['attempted_queries']-result['reused_queries']
    result['unprobed_queries'] = plan['failed_queries']-result['attempted_queries']
    result['status'] = 'ok' if all(r['status'] == 'ok' for r in result['results']) else 'error'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--resume', type=Path)
    args = parser.parse_args()
    report = json.loads(args.inventory.read_text())
    resume = json.loads(args.resume.read_text()) if args.resume else None
    result = failure_plan(report, resume=resume) if args.plan_only else diagnose(report, resume=resume)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items()
                      if k not in {'requests', 'results', 'reused_results', 'original_audit_holds'}}, ensure_ascii=False))
    if result.get('status') == 'error':
        raise SystemExit('Failed listing diagnosis still has a source error; original audit unchanged')


if __name__ == '__main__':
    main()
