"""Collect official PE notices since a fixed start date from institution boards.

User decision 2026-11-14: every PE notice since 2020-01-01 must be archived so that
institution-level changes (size, leagues, selected GPs, strategy) can be shown.

The listing walk reuses the inventory audit (same parsers and boundaries); each
notice reuses the daily collector's `fetch_notice` and is validated with
`validate_notice(..., history_listing=True)`. Output is a review bundle: no DB
write, no program projection, no publication. Attachment bytes are written to a
separate directory so the text bundle stays small enough for a review branch.
"""
import argparse
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import audit_lp_official_inventory as inventory
    from . import collect_lp_institution_boards as boards
    from .collect_shared_lp_notices import classify_scope
except ImportError:
    import audit_lp_official_inventory as inventory
    import collect_lp_institution_boards as boards
    from collect_shared_lp_notices import classify_scope

KIND = 'lp_institution_history_v1'
# Titles kept for PE history: the same predicate the daily board collector uses,
# minus titles the inventory marks explicitly VC-only or outside policy.
_RELEVANT = re.compile(r'위탁|운용사|블라인드|PEF?|사모|선정', re.I)
_FUND = re.compile(r'(?:출자|펀드).*(?:공고|모집|공모|요청|결과)')


def history_candidate(row, institution):
    title = row['title']
    if row.get('title_scope') in ('outside_policy', 'vc_explicit') or not row.get('relevant'):
        return False
    return bool((_RELEVANT.search(title) or institution in {'kdb', 'ibk'} and re.search(r'출자사업|펀드', title)
                 or _FUND.search(title)) and classify_scope(title, title) != 'outside')


def _listing_row(receipt, notice_url, config):
    rows = boards.adapter(config).parse_listing(receipt['html'], receipt['url'], config)
    return next((row for row in rows if row['url'] == notice_url), None)


def collect(institution, start, end, *, max_pages=150, page_budget=1500, max_notices=400,
            fetch_factory=None, checked_at=None, skip_urls=()):
    configs = boards.load_configs(include_pending=True)
    if institution not in configs:
        raise ValueError(f'{institution}: no daily board adapter; use its dedicated history path')
    config = configs[institution]
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    fetch = (fetch_factory or boards.Session)(config)
    listing = inventory.audit({'programs': []}, as_of=end, max_pages=max_pages, page_budget=page_budget,
                              configs={institution: config},
                              scope={'confirmed_institution_ids': [institution], 'priority_verification_ids': []},
                              fetch_factory=lambda *a: fetch, independent=True, start=start, keep_html=True)
    entry = listing['institutions'][0]
    receipts = listing['receipts']
    bundle = {'kind': KIND, 'institution_id': institution, 'window': listing['window'], 'checked_at': checked_at,
              'listing': {'status': entry['status'], 'queries': entry['queries'], 'holds': listing['holds'],
                          'rows': len(entry['rows'])},
              'listing_receipts': {}, 'notices': [], 'holds': [], 'skipped': []}
    coverage = {'detail_count': 0, 'attachment_count': 0}
    resolver_cache = {}
    candidates = [r for r in entry['rows'] if history_candidate(r, institution) and r['url'] not in set(skip_urls)]
    bundle['candidate_count'] = len(candidates)
    if len(candidates) > max_notices:
        bundle['holds'].append({'stage': 'history_budget', 'error': f'{len(candidates)} candidates > {max_notices}; oldest left'})
    for row in sorted(candidates, key=lambda r: (r['date'], r['url']), reverse=True)[:max_notices]:
        receipt = receipts[row['receipt_index']]
        listing_receipt = {'url': receipt['url'], 'html': receipt['html'], 'sha256': receipt['sha256']}
        try:
            board_row = _listing_row(listing_receipt, row['url'], config)
            if board_row is None:
                raise ValueError('row not found when re-reading its listing page with the board adapter')
            notice = boards.fetch_notice(board_row, listing_receipt, config, fetch, checked_at, resolver_cache,
                                         bundle['holds'], coverage)
            notice = boards.validate_notice(notice, checked_at, config, history_listing=True)
        except boards.kfinco.RestrictedNotice as exc:
            bundle['skipped'].append({'url': exc.url, 'reason': 'owner_closed'})
            continue
        except Exception as exc:
            bundle['holds'].append({'stage': 'history_detail', 'url': row['url'], 'date': row['date'],
                                    'title': row['title'], 'error': str(exc)[:300]})
            continue
        notice['history_title_scope'] = row['title_scope']
        bundle['notices'].append(notice)
    bundle['coverage'] = coverage
    return bundle


def write_bundle(bundle, out):
    """Text bundle (JSON, listing receipts deduplicated) + attachment bytes as files."""
    out.mkdir(parents=True, exist_ok=True)
    files = out / 'attachments'
    files.mkdir(exist_ok=True)
    compact = {**bundle, 'notices': []}
    for notice in bundle['notices']:
        n = dict(notice)
        listing = n['discovery_provenance']['listing']
        compact['listing_receipts'][listing['sha256']] = listing
        n['discovery_provenance'] = {**n['discovery_provenance'], 'listing': {'sha256': listing['sha256'], 'url': listing['url']}}
        for url, encoded in n.pop('attachment_bytes').items():
            raw = base64.b64decode(encoded)
            (files / hashlib.sha256(raw).hexdigest()).write_bytes(raw)
        compact['notices'].append(n)
    path = out / f"{bundle['institution_id']}.json"
    path.write_text(json.dumps(compact, ensure_ascii=False) + '\n')
    return path


def summary(bundle):
    years = {}
    for n in bundle['notices']:
        years[n['date'][:4]] = years.get(n['date'][:4], 0) + 1
    return {'institution_id': bundle['institution_id'], 'listing_status': bundle['listing']['status'],
            'candidates': bundle['candidate_count'], 'collected': len(bundle['notices']),
            'attachments': bundle['coverage'].get('attachment_count', 0), 'holds': len(bundle['holds']),
            'by_year': dict(sorted(years.items()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--institutions', required=True, help='comma-separated institution ids')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-pages', type=int, default=150)
    parser.add_argument('--page-budget', type=int, default=1500)
    parser.add_argument('--max-notices', type=int, default=400)
    args = parser.parse_args()
    rows = []
    for institution in [i.strip() for i in args.institutions.split(',') if i.strip()]:
        try:
            bundle = collect(institution, args.start, args.end, max_pages=args.max_pages,
                             page_budget=args.page_budget, max_notices=args.max_notices)
            write_bundle(bundle, args.out)
            rows.append(summary(bundle))
        except Exception as exc:  # one institution never stops the others
            rows.append({'institution_id': institution, 'error': str(exc)[:300]})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    (args.out / 'summary.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    lines = [f'# 기관 게시판 과거 공고 수집 ({args.start} ~ {args.end})', '',
             '공식 게시판 원문(본문·첨부 텍스트)을 받아 검증만 했습니다. DB 저장·사업 연결·공개는 하지 않았습니다.', '',
             '| 기관 | 목록 상태 | 후보 | 수집 | 첨부 | 보류 | 연도별 |', '| --- | --- | ---: | ---: | ---: | ---: | --- |']
    for r in rows:
        if 'error' in r:
            lines.append(f"| {r['institution_id']} | 오류: {r['error'][:80]} | | | | | |")
        else:
            lines.append(f"| {r['institution_id']} | {r['listing_status']} | {r['candidates']} | {r['collected']} | "
                         f"{r['attachments']} | {r['holds']} | " + ', '.join(f'{y}:{n}' for y, n in r['by_year'].items()) + ' |')
    (args.out / 'README.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
