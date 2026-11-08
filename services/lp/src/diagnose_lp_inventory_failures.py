"""Probe at most two saved failed NH listing requests; never repair an audit."""
import argparse
import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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


def recover_boundaries(report, prior, *, fetch=None, limit=2, plan_only=False):
    """Follow only pages requested by replaying saved NH listing boundaries."""
    if type(limit) is not int or not 1 <= limit <= 2:
        raise ValueError('followup request limit must be one or two')
    previous = prior.get('kind') == 'lp_inventory_boundary_recovery_v1'
    if previous and prior.get('status') != 'ok':
        raise ValueError('failed boundary recovery cannot be retried by resume')
    diagnostic = prior['diagnostic'] if previous else prior
    validated = failure_plan(report, resume=diagnostic)
    if validated['requests'] or validated['unprobed_queries']:
        raise ValueError('all failed first pages must be verified before following pages')
    config = inventory.boards.load_configs(include_pending=True)['nh_central']
    cache = {}
    entry = next(e for e in report['institutions'] if e['institution_id'] == 'nh_central')
    for query in entry['queries']:
        for index in query['pages']:
            receipt = report['receipts'][index]
            expected = inventory.page_url('nh_central', config, query['term'], receipt['page'],
                report['window']['start'], report['window']['end'], listing_url=query['listing_url'])
            if (receipt['institution_id'] != 'nh_central' or receipt['url'] != expected
                    or hashlib.sha256(receipt['html'].encode()).hexdigest() != receipt['sha256']):
                raise ValueError('healthy saved NH receipt changed')
            raw = receipt['html'].encode()
            rows = inventory.boards.nh.parse_listing(receipt['html'], expected, config)
            if len(rows) != receipt['row_count']:
                raise ValueError('healthy saved NH row count changed')
            cache[expected] = raw
    for row in validated['reused_results']:
        cache[row['url']] = base64.b64decode(row['raw_base64'], validate=True)

    def replay():
        missing = []
        def cached(url):
            if url not in cache:
                missing.append(url)
                raise ValueError('followup response not saved; no HTTP attempted')
            return cache[url]
        value = inventory.audit({}, as_of=report['as_of'], configs={'nh_central': config},
            scope={'confirmed_institution_ids': [], 'priority_verification_ids': ['nh_central']},
            independent=True, page_budget=200, fetch_factory=lambda *a: cached)
        if any(h['url'] not in missing for h in value['holds']):
            raise ValueError('saved NH boundary replay failed')
        return value, list(dict.fromkeys(missing))

    def reuse(row):
        raw = base64.b64decode(row['raw_base64'], validate=True)
        if (row.get('status') != 'ok' or len(raw) > inventory.boards.MAX_BYTES
                or len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']):
            raise ValueError('followup response proof changed')
        html = inventory.boards.decode_html(raw)
        if len(inventory.boards.nh.parse_listing(html, row['url'], config)) != row['row_count']:
            raise ValueError('followup response row count changed')
        page = int(parse_qs(urlsplit(row['url']).query)['pageIndex'][0])
        previous_url = inventory._query(row['url'], {'pageIndex': page-1})
        if page <= 1 or previous_url not in cache:
            raise ValueError('preceding NH listing page required')
        prior_total = inventory.boards.nh.listing_tree(
            inventory.boards.decode_html(cache[previous_url]), previous_url, config)[4]
        if inventory.boards.nh.listing_tree(html, row['url'], config)[4] != prior_total:
            raise ValueError('NH listing total changed during pagination')
        cache[row['url']] = raw

    followups = copy.deepcopy(prior['followups']) if previous else []
    for row in followups:
        _, pending = replay()
        if not pending or row['url'] != pending[0]:
            raise ValueError('followup is not the next observed page')
        reuse(row)
    reused = len(followups)
    value, pending = replay()
    fetch = fetch or inventory.boards.Session(config)
    status = 'ok'
    replay_error = None
    while pending and len(followups)-reused < limit and not plan_only:
        row = {'url': pending[0], 'checked_at': datetime.now(timezone.utc).isoformat()}
        try:
            raw = fetch(row['url'])
            if not isinstance(raw, bytes) or len(raw) > inventory.boards.MAX_BYTES:
                raise ValueError('followup response size or type invalid')
            row.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                       raw_base64=base64.b64encode(raw).decode('ascii'))
            rows = inventory.boards.nh.parse_listing(inventory.boards.decode_html(raw), row['url'], config)
            row.update(status='ok', row_count=len(rows))
            reuse(row)
        except Exception as error:
            row.update(status='error', error_type=type(error).__name__, error=str(error))
            status = 'error'
        followups.append(row)
        if status == 'error':
            break
        try:
            value, pending = replay()
        except ValueError as error:
            status = 'error'
            replay_error = str(error)
            break
    queries = copy.deepcopy(value['institutions'][0]['queries'])
    for query in queries:
        if query['boundary'] == 'source_error':
            query['boundary'] = 'followup_response_not_saved'
    complete = not pending and value['institutions'][0]['status'] == 'observed_query_boundary'
    return {'kind': 'lp_inventory_boundary_recovery_v1', 'status': status,
            'checked_at': datetime.now(timezone.utc).isoformat(), 'diagnostic': copy.deepcopy(diagnostic),
            'original_audit_holds': copy.deepcopy(report['holds']), 'followups': followups,
            'new_queries': len(followups)-reused, 'reused_followups': reused,
            'pending_urls': pending, 'queries': queries, 'listing_receipts': value['receipts'],
            'nh_listing_boundaries_complete': complete, 'archive_comparison_performed': False,
            'boundary_replay_error': replay_error,
            'audit_recovered': False, 'publication': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--followup-boundaries', action='store_true')
    args = parser.parse_args()
    report = json.loads(args.inventory.read_text())
    resume = json.loads(args.resume.read_text()) if args.resume else None
    if args.followup_boundaries:
        if resume is None:
            raise ValueError('verified diagnostic resume required for followup boundaries')
        result = recover_boundaries(report, resume, plan_only=args.plan_only)
    else:
        result = failure_plan(report, resume=resume) if args.plan_only else diagnose(report, resume=resume)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items()
                      if k not in {'requests', 'results', 'reused_results', 'original_audit_holds',
                                   'diagnostic', 'followups', 'queries', 'listing_receipts'}}, ensure_ascii=False))
    if result.get('status') == 'error':
        raise SystemExit('Failed listing diagnosis still has a source error; original audit unchanged')


if __name__ == '__main__':
    main()
