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


def _kgrowth_tools():
    """성장금융 detail parser and the proven one-body-one-file public session."""
    try:
        from . import diagnose_kgrowth_history_session as control
        from .collect_lp_history_attachments import read_attachment
        from .collect_lp_history_bodies import read_body
        from .kgrowth_listing import LIST_URL
        from .lp_history_sources import canonical_url
    except ImportError:
        import diagnose_kgrowth_history_session as control
        from collect_lp_history_attachments import read_attachment
        from collect_lp_history_bodies import read_body
        from kgrowth_listing import LIST_URL
        from lp_history_sources import canonical_url
    return control, read_attachment, read_body, LIST_URL, canonical_url

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
    """The board adapter's own row for this notice. Search words and page numbers in
    notice URLs differ between queries (SEMA), so rows match on the official notice key."""
    institution = config['institution_id']
    rows = boards.adapter(config).parse_listing(receipt['html'], receipt['url'], config)
    exact = next((row for row in rows if row['url'] == notice_url), None)
    if exact:
        return exact
    key = inventory.notice_key(institution, notice_url)
    matches = [row for row in rows if inventory.notice_key(institution, row['url']) == key]
    return matches[0] if len(matches) == 1 else None


def _kgrowth_notice(row, listing_receipt, body_fetch, session_factory, checked_at, holds):
    control, read_attachment, read_body, list_url, canonical_url = _kgrowth_tools()
    ident = row['source_id'] if re.fullmatch(r'[1-9]\d*', str(row['source_id'])) else \
        re.search(r'idx=(\d+)', row['url'])[1]
    url = canonical_url(ident, 'kgrowth')
    raw = body_fetch(url, list_url)
    detail = read_body(ident, raw, 'kgrowth')
    if detail['date'] != row['date']:
        raise ValueError('official listing/detail date differs')
    n = {**detail, 'institution_id': 'kgrowth', 'checked_at': checked_at, 'source_channel': 'institution_board',
         'discovery_provenance': {'kind': 'kgrowth_history_2020_v1', 'listing': listing_receipt,
                                  'detail_sha256': hashlib.sha256(raw).hexdigest()},
         'attachment_hashes': {}, 'attachment_texts': {}, 'attachment_bytes': {}}
    outside = classify_scope(n['title'], n['title']) in {'outside', 'vc_only'}
    # 성장금융 detail pages list bare download URLs (no file names): the reader is picked
    # from the file's own signature, and at most four files are fetched per notice.
    for file_url in ([] if outside else n.get('attachments', [])[:4]):
        try:
            session = session_factory({'source_id': ident, 'source_url': url, 'attachment_url': file_url})
            session(url, 'body')
            file = session(file_url, 'file')
            file = file['raw'] if isinstance(file, dict) else file
            if control._blocked(file[:4096].decode('cp949', errors='ignore')):
                raise ValueError('public file blocked')
            if file[:5] == b'%PDF-':
                text = read_attachment(file)['text']
            elif file[:4] == b'\xd0\xcf\x11\xe0':
                text = boards.attachment_text(file, 'attachment.hwp')
            elif file[:2] == b'PK':
                text = boards.attachment_text(file, 'attachment.hwpx')
            else:
                raise ValueError('unrecognised attachment format')
            n['attachment_bytes'][file_url] = base64.b64encode(file).decode('ascii')
            n['attachment_hashes'][file_url] = hashlib.sha256(file).hexdigest()
            if text:
                n['attachment_texts'][file_url] = text
        except Exception as exc:
            holds.append({'stage': 'history_attachment', 'url': file_url, 'notice_url': url, 'error': str(exc)[:300]})
    return n


def collect_kgrowth(start, end, *, max_pages=150, page_budget=1500, max_notices=400, body_fetch=None,
                    session_factory=None, checked_at=None):
    """성장금융 board since `start` (its 2023+ originals already come from the existing history path)."""
    control = _kgrowth_tools()[0]
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    config = {'institution_id': 'kgrowth', 'listing_url': inventory.CORE['kgrowth']}
    if body_fetch is None:
        session = boards.Session(config)
        body_fetch = lambda url, referer: session(url, referer)
    session_factory = session_factory or control.PublicSession
    listing = inventory.audit({'programs': []}, as_of=end, max_pages=max_pages, page_budget=page_budget,
                              configs={}, scope={'confirmed_institution_ids': ['kgrowth'], 'priority_verification_ids': []},
                              fetch_factory=(lambda *a: (lambda url: body_fetch(url, config['listing_url']))),
                              independent=True, start=start, keep_html=True)
    entry, receipts = listing['institutions'][0], listing['receipts']
    bundle = {'kind': KIND, 'institution_id': 'kgrowth', 'window': listing['window'], 'checked_at': checked_at,
              'listing': {'status': entry['status'], 'queries': entry['queries'], 'holds': listing['holds'],
                          'rows': len(entry['rows'])},
              'listing_receipts': {}, 'notices': [], 'holds': [], 'skipped': []}
    candidates = [r for r in entry['rows'] if r['date'] <= end and history_candidate(r, 'kgrowth')]
    bundle['candidate_count'] = len(candidates)
    attachments = 0
    for row in sorted(candidates, key=lambda r: (r['date'], r['url']), reverse=True)[:max_notices]:
        receipt = receipts[row['receipt_index']]
        listing_receipt = {'url': receipt['url'], 'html': receipt['html'], 'sha256': receipt['sha256']}
        try:
            n = _kgrowth_notice(row, listing_receipt, body_fetch, session_factory, checked_at, bundle['holds'])
        except Exception as exc:
            bundle['holds'].append({'stage': 'history_detail', 'url': row['url'], 'date': row['date'],
                                    'title': row['title'], 'error': str(exc)[:300]})
            continue
        attachments += len(n['attachment_hashes'])
        n['history_title_scope'] = row['title_scope']
        bundle['notices'].append(n)
    bundle['coverage'] = {'detail_count': len(bundle['notices']), 'attachment_count': attachments}
    return bundle


def collect(institution, start, end, *, max_pages=150, page_budget=1500, max_notices=400,
            fetch_factory=None, checked_at=None, skip_urls=()):
    if institution == 'kgrowth' and fetch_factory is None:
        return collect_kgrowth(start, end, max_pages=max_pages, page_budget=page_budget,
                               max_notices=max_notices, checked_at=checked_at)
    configs = boards.load_configs(include_pending=True)
    if institution not in configs:
        raise ValueError(f'{institution}: no daily board adapter; use its dedicated history path')
    config = configs[institution]
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    session = (fetch_factory or boards.Session)(config)
    seen_pages = {}

    def fetch(url, referer=None):
        raw = session(url, referer)
        if url not in seen_pages and len(seen_pages) < 2000:
            seen_pages[url] = raw[:400_000]
        return raw
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
        board_row = None
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
            hold = {'stage': 'history_detail', 'url': row['url'], 'date': row['date'],
                    'title': row['title'], 'error': str(exc)[:300]}
            page = seen_pages.get(board_row['url'] if board_row else row['url'])
            if page is not None:
                # Kept so the parser can be fixed against the real (older) page format.
                hold['detail_page'] = boards.decode_html(page)[:200_000]
            bundle['holds'].append(hold)
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
