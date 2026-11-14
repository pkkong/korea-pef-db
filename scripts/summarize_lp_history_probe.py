"""Summarize a fixed-start official listing probe (audit_lp_official_inventory --start).

Per institution: relevant list rows by year, the oldest listing date each search
reached, and why each search stopped. A board whose oldest reachable row is after
the start date is reported as such; it is not counted as "no notices".
"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

REACHED = {'observed_older_page': '시작일 이전까지 도달',
           'observed_final_page': '게시판 마지막 쪽',
           'confirmed_empty': '빈 쪽',
           'repeated_page': '같은 쪽 반복',
           'page_limit': '쪽 상한(미완)',
           'global_page_budget': '전체 예산(미완)',
           'latest_board_probe': '최신 목록 확인용',
           'source_error': '접속/판독 오류'}


def summarize(report):
    start = report['window']['start']
    years = list(range(int(start[:4]), int(report['window']['end'][:4]) + 1))
    rows = []
    for entry in report['institutions']:
        relevant = [r for r in entry['rows'] if r['relevant']]
        by_year = Counter(r['date'][:4] for r in relevant)
        pe = Counter(r['date'][:4] for r in relevant if r['title_scope'] in ('pe_blind_title', 'mixed_pe_vc', 'scope_unconfirmed'))
        searches = [q for q in entry['queries'] if q['kind'] != 'latest_board_probe']
        oldest = min((q['minimum_date'] for q in searches if q['minimum_date']), default=None)
        stops = Counter(q['boundary'] for q in searches)
        complete = bool(searches) and all(q['boundary'] in ('observed_older_page', 'observed_final_page', 'confirmed_empty', 'repeated_page') for q in searches)
        rows.append({'institution_id': entry['institution_id'], 'name': entry['name'], 'status': entry['status'],
                     'oldest_listing_date': oldest, 'reaches_start': bool(oldest and oldest <= start),
                     'searches_complete': complete, 'stops': dict(stops),
                     'relevant_by_year': {str(y): by_year.get(str(y), 0) for y in years},
                     'pe_candidates_by_year': {str(y): pe.get(str(y), 0) for y in years}})
    return {'window': report['window'], 'summary': report['summary'], 'institutions': rows}


def markdown(result):
    w = result['window']
    years = sorted(next(iter(result['institutions']), {}).get('relevant_by_year', {}))
    lines = [f"# LP 공식 게시판 과거 도달 범위 ({w['start']} ~ {w['end']})", '',
             '목록 행(제목·날짜·주소)만 수집했습니다. 본문·첨부·DB 쓰기·공개 발행은 없습니다. 숫자는 관련 제목 수이며 PE 사업 수가 아닙니다.',
             'PE 후보는 제목상 PE 블라인드 명시·PE/VC 혼합·범위 미확인을 합친 값입니다.', '',
             '| 기관 | 가장 오래된 목록 | 시작일 도달 | 검색 완료 | ' + ' | '.join(years) + ' | 멈춘 이유 |',
             '| --- | --- | --- | --- | ' + ' | '.join('---:' for _ in years) + ' | --- |']
    for r in result['institutions']:
        cells = [f"{r['relevant_by_year'][y]}/{r['pe_candidates_by_year'][y]}" for y in years]
        stops = ', '.join(f"{REACHED.get(k, k)} {v}" for k, v in r['stops'].items()) or '미연결'
        lines.append(f"| {r['name']} | {r['oldest_listing_date'] or '—'} | {'예' if r['reaches_start'] else '아니오'} | "
                     f"{'예' if r['searches_complete'] else '아니오'} | " + ' | '.join(cells) + f' | {stops} |')
    lines += ['', '연도 칸은 `관련 제목/PE 후보` 입니다. 접속 오류·미연결 기관은 0건으로 해석하지 않습니다.']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    result = summarize(report)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'coverage.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (args.out / 'README.md').write_text(markdown(result))
    with (args.out / 'rows.csv').open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['institution_id', 'date', 'stage', 'title_scope', 'relevant', 'title', 'url'])
        for entry in report['institutions']:
            for row in entry['rows']:
                writer.writerow([entry['institution_id'], row['date'], row['stage'], row['title_scope'], row['relevant'], row['title'], row['url']])
    print(markdown(result))


if __name__ == '__main__':
    main()
