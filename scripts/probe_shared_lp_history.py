"""Walk association repost boards (KVCA, KOFIA) back to a fixed start date.

Read-only list rows only, through the shared collector's fetch and parser. Shows
whether reposts can backfill LPs whose own boards no longer keep old notices.
"""
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/lp/src'))

import collect_shared_lp_notices as shared  # noqa: E402

RELEVANT = ('펀드', '출자', '블라인드', '운용사', '사모', 'PEF', 'PE')


def walk(channel, base, start, max_pages, fetch):
    rows, stops, pending, done = [], 'page_limit', {1: base}, set()
    while pending and len(done) < max_pages:
        number = min(pending)
        url = pending.pop(number)
        done.add(number)
        try:
            html = shared._complete_html(fetch(url), 'listing')
            found, pages = shared.parse_listing(html, url, channel)
        except Exception as error:  # keep what was walked; the stop reason says why
            return rows, f'source_error: {error}'[:200], len(done)
        if not found:
            return rows, 'empty_page', len(done)
        rows.extend({**row, 'page': number} for row in found)
        dated = [row['date'] for row in found if row['date']]
        if dated and max(dated) < start:
            return rows, 'reached_start', len(done)
        pending.update({p: u for p, u in pages.items() if p > number and p not in done})
        if not pending:
            stops = 'last_page'
    return rows, stops, len(done)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', required=True)
    parser.add_argument('--max-pages', type=int, default=400)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    fetch = lambda url: shared.fetch_bytes(url, html_kind='listing')
    args.out.mkdir(parents=True, exist_ok=True)
    summary, lines = {}, [f'# 협회 재게시 게시판 과거 도달 범위 (시작 {args.start})', '',
                          '목록 행만 읽었습니다. 관련 제목 수는 PE 사업 수가 아닙니다.', '',
                          '| 게시판 | 읽은 쪽 | 가장 오래된 날짜 | 멈춘 이유 | 연도별 관련 제목 |', '| --- | ---: | --- | --- | --- |']
    with (args.out / 'rows.csv').open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['channel', 'date', 'issuer', 'title', 'url'])
        for channel, base in shared.CHANNELS.items():
            rows, stop, pages = walk(channel, base, args.start, args.max_pages, fetch)
            kept = [r for r in rows if r['date'] and r['date'] >= args.start]
            relevant = [r for r in kept if any(w in r['title'] for w in RELEVANT)]
            years = Counter(r['date'][:4] for r in relevant)
            issuers = defaultdict(Counter)
            for r in relevant:
                issuers[r.get('issuer_name') or ''][r['date'][:4]] += 1
            oldest = min((r['date'] for r in rows if r['date']), default=None)
            summary[channel] = {'pages': pages, 'stop': stop, 'oldest_date': oldest, 'rows_since_start': len(kept),
                                'relevant_by_year': dict(sorted(years.items())),
                                'relevant_by_issuer': {k: dict(sorted(v.items())) for k, v in issuers.items() if k}}
            lines.append(f"| {channel} | {pages} | {oldest or '—'} | {stop} | " + ', '.join(f'{y}:{n}' for y, n in sorted(years.items())) + ' |')
            for r in kept:
                writer.writerow([channel, r['date'], r.get('issuer_name') or '', r['title'], r['url']])
    (args.out / 'coverage.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    (args.out / 'README.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
