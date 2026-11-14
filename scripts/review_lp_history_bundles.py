"""Offline quality review of institution history bundles (lp-history-bundles branch).

Runs the same basic publication code on collected originals, without the DB or the
live program state, and reports per institution which programs would form and which
fields are filled. Read-only; nothing is stored or published.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/lp/src'))
sys.path.insert(0, str(ROOT))

from lp_notice_publication import publish_basic_notices  # noqa: E402
from lp_program_detail import clean_title  # noqa: E402
from lp_program_service import institution_title_names  # noqa: E402


def public_title(p):
    return clean_title(p['title'], institution_title_names(p['institution_id'], p.get('institution_name') or ''))

FIELDS = (('금액', lambda p: p.get('commitment_label') or p.get('commitment_amount_krw')),
          ('운용사 수', lambda p: p.get('manager_count')),
          ('최소 결성', lambda p: p.get('fund_target_label')),
          ('마감', lambda p: p.get('deadline')),
          ('선정 GP', lambda p: p.get('selected_gps')))


def load(directory):
    notices, bundles = [], []
    for path in sorted(Path(directory).glob('*.json')):
        if path.name == 'summary.json':
            continue
        bundle = json.loads(path.read_text())
        bundles.append(bundle)
        for n in bundle['notices']:
            receipt = bundle['listing_receipts'].get(n['discovery_provenance']['listing']['sha256'])
            if receipt:
                n['discovery_provenance']['listing'] = receipt
            notices.append(n)
    return bundles, notices


def review(notices, checked_at=None):
    """Programs plus per-institution unlinked counts; `review.skips` keeps why groups were left out."""
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    skips = []
    # Same path as the daily institution-board notices. The bundles were validated in
    # Actions (validate_notice with history_listing=True, attachment bytes included);
    # the text bundle has no bytes, so re-validation is replaced by a copy here.
    import copy
    import lp_notice_publication as publication
    original = publication.validate_institution_notice
    publication.validate_institution_notice = lambda raw, checked_at: copy.deepcopy(raw)
    try:
        programs, holds = publish_basic_notices({'programs': [], 'institution_notices': notices}, [], checked_at, skips)
    finally:
        publication.validate_institution_notice = original
    review.skips = skips
    by_inst = defaultdict(list)
    for p in programs:
        by_inst[p['institution_id']].append(p)
    represented = {e['url'] for p in programs for e in p['events']}
    unlinked = Counter(n['institution_id'] for n in notices if n['url'] not in represented)
    hold_reasons = Counter((h.get('stage'), (h.get('reason') or '')[:60]) for h in holds)
    return programs, by_inst, unlinked, hold_reasons


def markdown(by_inst, unlinked, hold_reasons, notices):
    total = Counter(n['institution_id'] for n in notices)
    lines = ['# 과거 원문 → 사업 판독 점검 (오프라인)', '',
             '수집 묶음만으로 공개 코드가 만들 사업을 계산했습니다. DB·공개 상태는 바뀌지 않습니다.', '',
             '| 기관 | 원문 | 사업 | 사업 연결 안 된 원문 | ' + ' | '.join(f'{name} 채움' for name, _ in FIELDS) + ' | 연도별 사업 |',
             '| --- | ---: | ---: | ---: | ' + ' | '.join('---:' for _ in FIELDS) + ' | --- |']
    for inst in sorted(total):
        ps = by_inst.get(inst, [])
        filled = [sum(bool(get(p)) for p in ps) for _, get in FIELDS]
        years = Counter((p['events'][0]['date'] if p.get('events') else '')[:4] for p in ps)
        lines.append(f"| {inst} | {total[inst]} | {len(ps)} | {unlinked.get(inst, 0)} | "
                     + ' | '.join(f'{n}/{len(ps)}' for n in filled) + ' | '
                     + ', '.join(f'{y}:{n}' for y, n in sorted(years.items())) + ' |')
    lines += ['', '## 보류 사유 (상위)', '']
    lines += [f'- {stage} · {reason} — {n}건' for (stage, reason), n in hold_reasons.most_common(15)]
    lines += ['', '## 기관별 사업 목록', '']
    for inst in sorted(by_inst):
        lines += [f'### {inst}', '']
        for p in sorted(by_inst[inst], key=lambda p: p['events'][0]['date'] if p.get('events') else ''):
            first = p['events'][0]['date'] if p.get('events') else ''
            gps = ', '.join(g['name'] for g in p.get('selected_gps') or [])
            lines.append(f"- {first} · {public_title(p)} · {p.get('status')} · {p.get('commitment_label') or ''}"
                         f" · {('최소 ' + p['fund_target_label']) if p.get('fund_target_label') and not p['fund_target_label'].startswith('최소') else p.get('fund_target_label') or ''}"
                         + (f' · 선정: {gps}' if gps else ''))
        lines.append('')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundles', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    _, notices = load(args.bundles)
    programs, by_inst, unlinked, hold_reasons = review(notices)
    args.out.write_text(markdown(by_inst, unlinked, hold_reasons, notices))
    print(f'{len(notices)} originals -> {len(programs)} programs; report {args.out}')


if __name__ == '__main__':
    main()
