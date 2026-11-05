"""Summarize retained direct-source observations, never market completeness scores."""
import argparse
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CORE = {'kgrowth', 'ktcu', 'koreapost', 'kexim'}
ASSOCIATION_CHANNELS = {'kvca', 'kofia_212', 'kofia_17'}
SOURCE_STAGES = {'institution_listing', 'institution_detail', 'institution_depth', 'institution_validation'}


def count(value):
    return value if type(value) is int and value >= 0 else None


def objects(value):
    return value if isinstance(value, list) else []


def hold_counts(holds):
    out = dict(source_errors=0, attachment_holds=0, restricted_holds=0, review_holds=0, unknown_holds=0)
    for h in objects(holds):
        if not isinstance(h, dict):
            out['unknown_holds'] += 1
        elif h.get('stage') in SOURCE_STAGES or h.get('error') and not h.get('stage'):
            out['source_errors'] += 1
        elif str(h.get('stage', '')).startswith('institution_attachment'):
            out['attachment_holds'] += 1
        elif h.get('stage') == 'institution_restricted':
            out['restricted_holds'] += 1
        elif h.get('program_id') and h.get('reason') and not h.get('error'):
            out['review_holds'] += 1
        else:
            out['unknown_holds'] += 1
    return out


def attachment_count(notices):
    # Count stored source/hash pairs, not discovered attachment links.
    return len({(n.get('url'), url, digest) for n in notices if isinstance(n, dict)
                for url, digest in n.get('attachment_hashes', {}).items()
                if isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest)})


def build_report(growth=None, priority=None, institution=None, publication=None, *, shared=None,
                 publication_verified=False, scope=None, channels=None):
    if scope is None:
        scope = json.loads((ROOT / 'data/lp_blind_contest_scope.json').read_text())
    if channels is None:
        channels = json.loads((ROOT / 'data/lp_institution_board_channels.json').read_text())['channels']
    targets = list(dict.fromkeys(scope['confirmed_institution_ids'] + scope['priority_verification_ids']))
    modes = {c['institution_id']: c.get('enabled', True) for c in channels}
    with (ROOT / 'data/lp_institutions.csv').open() as source:
        names = {row['lp_code']: row['lp_name'] for row in csv.DictReader(source)}
    for path in (ROOT / 'data').glob('lp_blind_contest_screening_*.json'):
        names.update({row['institution_id']: row['name'] for row in json.loads(path.read_text()).get('institutions', [])})
    pub = (publication or {}).get('programs_by_institution', {})
    if not isinstance(pub, dict) or any(count(v) is None for v in pub.values()):
        raise ValueError('invalid publication counts')
    total = (publication or {}).get('programs')
    complete_counts = 'programs_by_institution' in (publication or {}) and count(total) is not None
    if complete_counts and sum(pub.values()) != total:
        raise ValueError('publication counts do not match total')
    reports = {'growth': growth or {}, 'priority': priority or {}, 'institution': institution or {}}
    global_issues = []
    for label, report in reports.items():
        for h in objects(report.get('holds')):
            if not isinstance(h, dict) or h.get('institution_id') not in targets:
                global_issues.append({'report': label, 'kind': 'unattributed_hold'})
        if report.get('error') or report.get('errors'):
            global_issues.append({'report': label, 'kind': 'report_error'})
    rows = []
    for iid in targets:
        daily = iid in CORE or modes.get(iid) is True
        report = reports['growth'] if iid == 'kgrowth' else (
            reports['priority'].get('sources', {}).get(iid, {}) if iid in CORE else reports['institution'])
        if not isinstance(report, dict):
            report = {'error': True}
        row = {'institution_id': iid, 'name': names.get(iid, iid), 'frequency': 'daily' if daily else 'weekly',
               'checked_at': report.get('checked_at') if daily else None,
               'body_count': None, 'supporting_body_count': None, 'stored_attachment_count': None,
               'listing_count': None, **hold_counts([]), 'unavailable_notice_holds': 0,
               'public_program_count': pub.get(iid, 0 if complete_counts else None)}
        row['publication_availability'] = ('unknown' if row['public_program_count'] is None else
                                           'available' if row['public_program_count'] else 'none')
        observed = False
        if iid == 'kgrowth':
            c = report.get('collection_coverage', {})
            row.update(body_count=count(c.get('fetched_count')), listing_count=len(objects(c.get('listing_urls'))))
            row['stored_attachment_count'] = attachment_count(objects(report.get('notices')))
            missing = set(map(str, objects(c.get('missing_source_ids'))))
            unavailable = objects(c.get('unavailable_notices', report.get('unavailable_notices')))
            # A complete official empty template is a retained evidence hold,
            # not a DNS/HTTP/collection failure. Never hide other missing reads.
            for h in unavailable:
                if (isinstance(h, dict) and h.get('reason') == 'official_detail_empty'
                        and re.fullmatch('[0-9a-f]{64}', h.get('response_sha256', ''))
                        and count(h.get('response_size')) not in (None, 0)):
                    row['unavailable_notice_holds'] += 1
                else:
                    missing.add(str(h.get('source_id')) if isinstance(h, dict) else 'unknown')
            row['source_errors'] = len(missing)
            date_discovery = c.get('date_discovery')
            if isinstance(date_discovery, dict) and date_discovery.get('complete') is not True:
                row['source_errors'] += 1
            row['attachment_holds'] = sum(bool(a.get('reason')) for a in objects(c.get('attachments')) if isinstance(a, dict))
            row['review_holds'] = len(objects(report.get('review'))) + len(objects(report.get('program_holds'))) + len(objects(report.get('extraction_holds')))
            observed = bool(row['listing_count']) and row['body_count'] is not None
        elif iid in CORE:
            notices = objects(report.get('notices'))
            supporting = objects(report.get('supporting_notices'))
            row.update(hold_counts(objects(report.get('holds')) + objects(report.get('supporting_holds'))))
            row.update(body_count=len(notices), supporting_body_count=len(supporting),
                       stored_attachment_count=attachment_count(notices + supporting))
            c = report.get('collection_coverage', {})
            row['listing_count'] = len(objects(c.get('listing_pages'))) if c else None
            observed = isinstance(report.get('notices'), list) and (bool(notices) or bool(row['listing_count']))
        else:
            c = report.get('coverage', {}).get(iid, {})
            row.update(hold_counts([h for h in objects(report.get('holds')) if isinstance(h, dict) and h.get('institution_id') == iid]))
            row.update(body_count=count(c.get('detail_count')), stored_attachment_count=count(c.get('attachment_count')),
                       listing_count=len(objects(c.get('listing_pages'))))
            observed = bool(row['listing_count']) and row['body_count'] is not None and row['stored_attachment_count'] is not None
        if report.get('error') or report.get('errors'):
            row['source_errors'] += 1
        row['source_health'] = ('weekly_only' if not daily else 'error' if row['source_errors'] or row['unknown_holds']
                                else 'ok' if observed and row['checked_at'] else 'not_observed')
        if not observed:
            row['body_count'] = row['stored_attachment_count'] = None
        rows.append(row)
    association = {'observed': isinstance(shared, dict), 'source_errors': None, 'attachment_holds': None}
    if isinstance(shared, dict):
        holds = objects(shared.get('holds'))
        association['source_errors'] = sum(
            h.get('stage') in {'listing', 'detail', 'original_board'} or
            (h.get('stage') in {'growth_search', 'kfinco_original'} and h.get('phase') in {'listing', 'detail'})
            for h in holds if isinstance(h, dict))
        association['attachment_holds'] = sum(h.get('stage') == 'attachment' for h in holds if isinstance(h, dict))
        if any(not isinstance(h, dict) for h in holds):
            global_issues.append({'report': 'shared', 'kind': 'invalid_hold'})
        channel_pages = shared.get('coverage', {}).get('channel_pages')
        association['observed'] = (isinstance(channel_pages, dict) and
            ASSOCIATION_CHANNELS <= set(channel_pages) and all(
                isinstance(channel_pages[c], dict) and bool(objects(channel_pages[c].get('pages')))
                and all(isinstance(p, dict) and p.get('status') == 'ok' for p in channel_pages[c]['pages'])
                for c in ASSOCIATION_CHANNELS))
    daily = [row for row in rows if row['frequency'] == 'daily']
    daily_ok = sum(row['source_health'] == 'ok' for row in daily)
    return {'version': 1, 'scope': 'institution_and_association_source_observations',
            'interpretation': 'Counts describe supplied source runs; not market recall, completeness scores, or current live health.',
            'target_count': len(rows), 'daily_expected': len(daily), 'daily_sources_ok': daily_ok,
            'all_collection_sources_ok': daily_ok == len(daily) and not global_issues and
                                         association['observed'] and association['source_errors'] == 0,
            'publication_verified': bool(publication_verified),
            'publication_run_id': (publication or {}).get('run_id'),
            'association': association, 'global_issues': global_issues, 'institutions': rows}


def markdown(report):
    lines = ['## LP 기관별 수집 결과', '',
             f"매일 수집 기관 정상: **{report['daily_sources_ok']}/{report['daily_expected']}** · 공개 화면 검증: {'통과' if report['publication_verified'] else '미확인'}", '',
             '이번 실행의 관측치이며 시장 수집률·완성도 점수가 아닙니다.', '',
             '| 기관 | 주기 | 출처 상태 | 본문 | 보조 본문 | 저장 첨부 | 출처 오류 | 첨부 보류 | 접근 제한 | 원문 빈 양식 | 공개 사업 |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    labels = {'daily': '매일', 'weekly': '주간', 'ok': '정상', 'error': '오류',
              'not_observed': '미관측', 'weekly_only': '주간 탐색'}
    for row in report['institutions']:
        keys = ('name','frequency','source_health','body_count','supporting_body_count','stored_attachment_count',
                'source_errors','attachment_holds','restricted_holds','unavailable_notice_holds','public_program_count')
        lines.append('| ' + ' | '.join('미관측' if row[k] is None else labels.get(str(row[k]), str(row[k])) for k in keys) + ' |')
    association = report['association']
    lines += ['', f"협회 목록·본문 오류: {association['source_errors'] if association['observed'] else '미관측'} · 첨부 판독 보류: {association['attachment_holds']}",
              f"기관 미귀속/보고서 전체 문제: {len(report['global_issues'])}건"]
    return '\n'.join(lines) + '\n'


def main():
    p = argparse.ArgumentParser()
    for name in ('growth', 'priority', 'institution', 'publication'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--shared')
    p.add_argument('--publication-verified', choices=('true', 'false'), default='false')
    p.add_argument('--output', required=True)
    p.add_argument('--markdown', required=True)
    args = p.parse_args()
    inputs = {name: json.loads(Path(getattr(args, name)).read_text()) if Path(getattr(args, name)).exists() else None
              for name in ('growth', 'priority', 'institution', 'publication')}
    if args.shared:
        inputs['shared'] = json.loads(Path(args.shared).read_text()) if Path(args.shared).exists() else None
    report = build_report(**inputs, publication_verified=args.publication_verified == 'true')
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    Path(args.markdown).write_text(markdown(report))


if __name__ == '__main__':
    main()
