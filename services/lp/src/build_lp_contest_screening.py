"""Validate reviewed issuer evidence and render the launch-scope inventory."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
INPUTS = ['pensions', 'financial', 'operations']
CONFIRMED = {'core_confirmed', 'mixed_pe_confirmed'}
DECISIONS = CONFIRMED | {'needs_confirmation', 'exclude_scope'}
ASSOCIATION_HOSTS = {'www.kofia.or.kr', 'kofia.or.kr', 'www.kvca.or.kr', 'roadshow.kvca.or.kr'}


def validate(rows, scope):
    by_id = {}
    for row in rows:
        identity = row['institution_id']
        if identity in by_id or row['decision'] not in DECISIONS:
            raise ValueError('Duplicate institution or invalid screening decision')
        by_id[identity] = row
        evidence = row['evidence']
        for item in evidence:
            if urlparse(item['url']).scheme != 'https' or len(item.get('quote', '').split()) > 20:
                raise ValueError('Invalid evidence URL or overlong quote')
        if row['decision'] in CONFIRMED:
            primary = [e for e in evidence if e.get('official') or urlparse(e['url']).hostname in ASSOCIATION_HOSTS]
            if any(urlparse(e['url']).hostname in {'pe-vc-lp.com', 'api.pe-vc-lp.com'} for e in primary):
                raise ValueError('Third-party discovery cannot become primary evidence')
            if not (any(e.get('pe_explicit') for e in primary) and any(e.get('blind_explicit') for e in primary)):
                raise ValueError('Confirmed institution lacks PE and blind evidence')
            if not row.get('issuer_name') or not row.get('official_listing_url'):
                raise ValueError('Confirmed institution lacks issuer/channel relation')
    wanted = set(scope['confirmed_institution_ids'])
    actual = {row['institution_id'] for row in rows if row['decision'] in CONFIRMED}
    if wanted != actual:
        raise ValueError('Release scope differs from reviewed evidence')
    if set(scope['priority_verification_ids']) & wanted:
        raise ValueError('Confirmed and unconfirmed scope overlaps')
    if any(by_id[i]['decision'] != 'needs_confirmation' for i in scope['priority_verification_ids']):
        raise ValueError('Priority confirmation queue is invalid')
    if not set(scope['operating_collector_ids']) <= wanted:
        raise ValueError('Operating collector is outside confirmed scope')
    blocked = set(scope.get('blocked_collector_ids', []))
    if not blocked <= wanted or blocked & set(scope['operating_collector_ids']):
        raise ValueError('Blocked collectors must be confirmed and not reported operating')
    return by_id


def build(rows, scope, discovered, directory):
    by_id = validate(rows, scope)
    active = set(scope['operating_collector_ids'])
    aliases = {row['name']: row['institution_id'] for row in rows}
    aliases.update({'교직원공제회': 'ktcu', '행정공제회': 'poba', '사학연금': 'tp',
                    '국민연금공단': 'nps', '총회연금재단': 'pck_pension',
                    '한국성장금융투자운용': 'kgrowth', '삼성자산운용': 'moel_iaci',
                    '삼성자산운용 산재기금': 'moel_iaci', 'KIF(KTOA)': 'kif',
                    '한국통신사업자연합회': 'kif'})
    leads = [{**item, 'reviewed_institution_id': aliases.get(item['name'])}
             for item in discovered.get('issuers', [])]
    result = {'as_of': scope['as_of'], 'scope': scope['product_scope'],
              'baseline_directory_count': len(directory),
              'index_counts': discovered.get('index_counts', {}),
              'raw_discovery_issuer_labels': len(leads),
              'reviewed_institution_count': len(rows),
              'decision_counts': dict(Counter(row['decision'] for row in rows)),
              'institutions': rows, 'discovery_issuer_inventory': leads, 'launch_scope': scope}
    lines = ['# PE 블라인드 공고 발행기관 선별', '',
             f"자료 확인: {scope['as_of']}", '',
             f"기존 명단 {len(directory)}개와 제3자 발행기관 표시명 {len(leads)}개를 대조하고, 실제 공모 후보 {len(rows)}개를 공식 자료로 우선 확인했다.",
             '국내 전체 발행기관의 전수 확정 목록이나 기관별 공모 빈도 통계는 아니다. 미확인은 공모를 하지 않는다는 뜻이 아니다.', '',
             '## 출시 수집 대상', '',
             '| 기관·기금 | 확인한 공고 | 근거 | 수집 연결 |', '|---|---|---|---|']
    for identity in scope['confirmed_institution_ids']:
        row = by_id[identity]
        item = next((e for e in row['evidence'] if e.get('pe_explicit')), row['evidence'][0])
        linked = '접속 차단' if identity in scope.get('blocked_collector_ids', []) else '운영 연결' if identity in active else '추가 연결 필요'
        lines.append(f"| {row['name']} | {item['date']} · {item['title']} | [원문]({item['url']}) | {linked} |")
    lines += ['', '## 출시 전 우선 확인', '', '| 기관 | 남은 확인 |', '|---|---|']
    for identity in scope['priority_verification_ids']:
        row = by_id[identity]
        lines.append(f"| {row['name']} | {row['reason']} |")
    lines += ['', '## 빠른 출시 순서', '',
              '1. 협회 공고 채널을 공통 수집 경로에 연결해 여러 발행기관을 함께 발견하고, 기관 자체 원문으로 연결한다.',
              '2. 기존 4기관의 새 사업·접수·심사·선정 공고 연결을 마무리하고 동일 규칙을 확인된 발행기관으로 확장한다.',
              '3. 확인된 채널의 공고 누락·중복·PE/VC 혼합·실패 복구를 확인한 뒤 뉴스레터 LP 메뉴를 공식 경로로 전환한다.',
              '4. GP 프로필, 모든 과거 공고, 기관 일반현황 보강은 첫 출시 후 진행한다.', '',
              '원문은 기관별 대표 근거이며 미래 공고 ID 허용목록이 아니다. 기관 확정과 수집기 구현 완료를 구분한다.',
              '제3자 데이터의 금액·날짜·선정 GP는 공개 데이터로 복사하지 않는다.', '',
              '## 추가 발견 표시명', '',
              '아래는 공식 확인 전 발견 단서다. VC 사업·지역기관·수행운용사·재게시자가 포함되며 자동 LP 추가 대상이 아니다.', '']
    for item in leads:
        if not item['reviewed_institution_id']:
            lines.append('- ' + item['name'])
    return result, '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--discovery', type=Path, required=True)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for group in INPUTS:
        rows.extend(json.loads((ROOT/f'data/lp_blind_contest_screening_{group}.json').read_text())['institutions'])
    scope = json.loads((ROOT/'data/lp_blind_contest_scope.json').read_text())
    directory = (json.loads(args.directory.read_text())['entities'] if args.directory else
                 list(csv.DictReader((ROOT/'data/lp_institutions.csv').open())))
    result, markdown = build(rows, scope, json.loads(args.discovery.read_text()), directory)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'screening.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    (args.out/'screening.md').write_text(markdown)
    print(json.dumps({k: result[k] for k in ('baseline_directory_count', 'raw_discovery_issuer_labels',
                                            'reviewed_institution_count', 'decision_counts')}))


if __name__ == '__main__':
    main()
