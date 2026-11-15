"""Summarize read-only board channel collections: notices, holds and PE result rosters.

Used by verify-lp-board-channel.yml. Reads collect_lp_institution_boards.py outputs and
writes README.md and summary.json; never writes a database or a public page.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/lp/src'))

from lp_notice_publication import _rule_valid_name  # noqa: E402
from lp_notice_triage import notice_stage  # noqa: E402
from lp_result_rosters import pe_result_roster  # noqa: E402


def summarize(reports):
    notices, holds, coverage = [], [], {}
    for report in reports:
        coverage.update(report.get('coverage', {}))
        holds.extend(report.get('holds', []))
        for n in report.get('notices', []):
            texts = [n['body'], *n.get('attachment_texts', {}).values()]
            rosters = [r for r in (pe_result_roster(t, valid=_rule_valid_name, pe_only_program=True) for t in texts) if r]
            notices.append({'institution_id': n['institution_id'], 'channel_id': n.get('channel_id'),
                            'date': n['date'], 'title': n['title'], 'url': n['url'],
                            'stage': notice_stage(n['title']), 'body': n['body'][:400],
                            'attachments': [a['name'] for a in n.get('attachments', [])],
                            'roster': rosters[0] if rosters else None,
                            'rosters_agree': all(r == rosters[0] for r in rosters)})
    notices.sort(key=lambda n: n['date'])
    return {'notices': notices, 'holds': holds, 'coverage': coverage}


def markdown(summary):
    lines = ['# LP board channel check', '',
             f"notices {len(summary['notices'])}, holds {len(summary['holds'])}", '',
             '| 날짜 | 제목 | 단계 | PE 명단 |', '|---|---|---|---|']
    for n in summary['notices']:
        roster = '; '.join(f"{label}: {', '.join(names)}" for label, names in (n['roster'] or []))
        lines.append(f"| {n['date']} | {n['title']} | {n['stage']} | {roster or '없음'} |")
    if summary['holds']:
        lines += ['', '## holds', '']
        lines += [f"- {h.get('stage')}: {h.get('url', '')} {h.get('error', h.get('reason', ''))}" for h in summary['holds']]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('reports', nargs='*', type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    reports = [json.loads(p.read_text()) for p in args.reports if p.exists()]
    summary = summarize(reports)
    (args.out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (args.out / 'README.md').write_text(markdown(summary) if reports else 'no channel report\n')


if __name__ == '__main__':
    main()
