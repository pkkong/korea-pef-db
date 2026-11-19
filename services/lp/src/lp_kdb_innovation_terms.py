"""KDB innovation-industry rounds with a three-league joint funding table."""

import re
from datetime import datetime

try:
    from .lp_kdb_policy_reopen import _ALLOCATION, mixed_vehicles
except ImportError:
    from lp_kdb_policy_reopen import _ALLOCATION, mixed_vehicles


_FUND = r'혁신성장펀드\(혁신산업펀드\)'
_NUM = r'[1-9]\d{0,2}(?:,\d{3})*'
_RANGE = _NUM + r'(?:~' + _NUM + r')?'
_MONEY = r'(' + _NUM + r')'
_ROW = (r'(소형|중형|M&A)(?:\n\(자율제안\))?\n' + _MONEY + r'\n' + _MONEY
        + r'\n(' + _NUM + r'|-)\n' + _MONEY + r'\((\d+)%\)\n(' + _RANGE + r')\n'
        + r'([1-9](?:~[1-9])?)\n' + _MONEY + r'(?:\n(?:신한|산은))?\n')
_PLAN = re.compile(
    r'\n재정\n산은\n사다리2\n합계\(비율\)\n((?:' + _ROW + r'){3})합계\n'
    + r'\n'.join([_MONEY] * 4) + r'\((\d+)%\)\n-\n([1-9]\d?(?:~[1-9]\d?)?)\n' + _MONEY + r'\n'
)
_LEADS = re.compile(r'중형·M&A소형주관기관한국산업은행\(정책펀드금융실\)신한자산운용\(특별자산운용실\)')
_RECEPTION = re.compile(r'접수일시○(20\d{2})년(\d{1,2})월(\d{1,2})일\([월화수목금토일]\)'
                        r'(\d{1,2}):(\d{2})~(\d{1,2}):(\d{2})\(분야별주관기관앞제출\)접수방법○')
_PURPOSE = re.compile(
    r'❶혁신성장공동기준품목영위중소·중견기업목표결성액의(\d+)%초과결성액의(\d+)%'
    r'❷新성장4\.03대분야15대프로젝트영위중소·중견기업목표결성액의(\d+)%초과결성액의(\d+)%'
    r'.{1,750}?\(M&A\)아래주목적투자비율준수주목적투자대상의무투자비율'
    r'혁신성장공동기준품목영위중소·중견기업의사업재편주\)목표결성액의(\d+)%초과결성액의(\d+)%'
)
_RESULT = re.compile(
    r'<' + _FUND + r'(20\d{2})년위탁운용사선정결과>\(단위:억원,개\)'
    r'지원분야\(운용사수\)펀드규모선정운용사명\(가나다순\)(.+)'
)
_RESULT_ROW = re.compile(r'(소형|중형|M&A)\(([1-9])\)(' + _RANGE + r')\(총' + _MONEY + r'\)')


def _stage(notice, suffix):
    if notice.get('institution_id') != 'kdb':
        return None
    return re.fullmatch(r'[「『]' + _FUND + r'[」』](20\d{2})년' + suffix, re.sub(r'\s+', '', notice['title']))


def _int(value):
    return 0 if value == '-' else int(value.replace(',', ''))


def _bounds(value):
    low, *high = map(_int, value.split('~'))
    return low, next(iter(high), low)


def _rounded(amount, target, ratio):
    return 0 < ratio <= 100 and 2 * abs(amount * 100 - ratio * target) <= target


def terms(notice, sources):
    if not _stage(notice, r'위탁운용사선정계획공고'):
        return {}
    sources = [(url, raw, sha) for url, raw, sha in sources if mixed_vehicles(raw)]
    if len(sources) != 1:
        raise ValueError('혁신산업 공동 모집의 투자기구 원문 미확인')
    url, raw, sha = sources[0]
    lines = '\n'.join(line for line in re.sub(r'[^\S\n]+', '', raw).splitlines() if line)
    caps, plans = list(_ALLOCATION.finditer(lines)), list(_PLAN.finditer(lines))
    compact = lines.replace('\n', '')
    leads = _LEADS.search(compact)
    if len(caps) != 1 or len(plans) != 1 or not leads:
        raise ValueError('혁신산업 공동 출자자·리그·주관기관 표 미확인')
    cap, plan = caps[0], plans[0]
    total, fiscal, bank, ladder, table_total = map(_int, cap.groups())
    table_fiscal, table_bank, table_ladder, planned, ratio = map(_int, plan.groups()[-7:-2])
    count, target = plan.groups()[-2], _int(plan.groups()[-1])
    rows = list(re.finditer(_ROW, plan[1]))
    if ([r[1] for r in rows] != ['소형', '중형', 'M&A']
            or (fiscal, bank, ladder, total) != (table_fiscal, table_bank, table_ladder, planned)
            or total != table_total or total != fiscal + bank + ladder or not _rounded(total, target, ratio)):
        raise ValueError('혁신산업 공동 출자 개요와 합계 행 불일치')
    if [sum(_int(r[i]) for r in rows) for i in (2, 3, 4, 5, 9)] != [fiscal, bank, ladder, total, target]:
        raise ValueError('혁신산업 리그별 공동 출자와 결성 목표 합계 불일치')
    count_bounds = [_bounds(r[8]) for r in rows]
    if tuple(map(sum, zip(*count_bounds))) != _bounds(count):
        raise ValueError('혁신산업 리그별 선정 예정 수 불일치')
    segments = []
    for row, (count_low, count_high) in zip(rows, count_bounds):
        name, fiscal_share, bank_share, ladder_share, amount, ratio, size, count_label, goal = row.groups()
        fiscal_share, bank_share, ladder_share, amount, ratio, goal = map(
            _int, (fiscal_share, bank_share, ladder_share, amount, ratio, goal))
        minimum, maximum = _bounds(size)
        if (fiscal_share + bank_share + ladder_share != amount or not _rounded(amount, goal, ratio)
                or minimum > maximum or count_low > count_high or not count_low * minimum <= goal <= count_high * maximum):
            raise ValueError('혁신산업 리그별 출자액·결성 범위 불일치')
        segments.append({'name': name, 'amount_krw': amount * 10**8, 'manager_count': count_label,
                         'fund_target_range_krw': [minimum * 10**8, maximum * 10**8],
                         'fund_target_total_krw': goal * 10**8})

    def proof(quote):
        return {'source_url': url, 'sha256': sha, 'quote': quote}

    contributions = {'정부재정': fiscal * 10**8, '한국산업은행': bank * 10**8, '성장사다리펀드2': ladder * 10**8}
    bank_shares = ' · '.join(f'{row[1]} {_int(row[3]):,}억원' for row in rows)
    target_shares = ' · '.join(f'{row[1]} {_int(row[9]):,}억원' for row in rows)
    evidence = {'innovation_joint_allocation': [proof(cap[0]), proof(plan[0]), proof(leads[0])]}
    result = {'amount_scope': 'combined', 'commitment_amount_krw': total * 10**8,
              'commitment_label': f'공동 정책출자 예정 {total:,}억원 내외', 'fund_target_label': f'{target:,}억원',
              'manager_count_label': f'{count}개 팀', 'segments': segments, 'contribution_allocations': contributions,
              'commitment_detail': (f'정부재정 {fiscal:,}억원 · 산업은행 {bank:,}억원({bank_shares})'
                                    f' · 성장사다리펀드2 {ladder:,}억원'),
              'contribution_note': (f'리그별 결성 목표는 {target_shares}입니다. 소형은 신한자산운용, 중형·M&A는 '
                                    '한국산업은행이 주관합니다. 출자자별 승인 절차를 거쳐 확정됩니다.'),
              'extraction_evidence': evidence}
    receptions = list(_RECEPTION.finditer(compact))
    if len(receptions) == 1:
        reception = receptions[0]
        year, month, day, start_hour, start_minute, end_hour, end_minute = map(int, reception.groups())
        try:
            start = datetime(year, month, day, start_hour, start_minute)
            end = datetime(year, month, day, end_hour, end_minute)
            if start >= end or end.date().isoformat() < notice['date']:
                raise ValueError('invalid reception window')
        except ValueError:
            result['deadline_error'] = '혁신산업 공동 모집의 접수 구간 불일치'
        else:
            result.update(deadline=end.isoformat() + '+09:00', deadline_precision='datetime')
            evidence['deadline'] = [proof(reception[0])]
    elif receptions:
        result['deadline_error'] = '혁신산업 공동 모집의 접수 구간이 여러 개'
    mandate = _PURPOSE.search(compact)
    if mandate and all(0 < int(pct) <= 100 for pct in mandate.groups()):
        labels = ('소형·중형 · 혁신성장 공동기준 품목 영위 중소·중견기업',
                  '소형·중형 · 신성장 4.0 분야 중소·중견기업', 'M&A · 혁신성장 공동기준 품목 영위 중소·중견기업의 사업재편')
        result['primary_investment'] = {'source_url': url, 'items': [
            f'{label} · 목표결성액의 {mandate[i]}%, 초과결성액의 {mandate[i+1]}%'
            for i, label in zip((1, 3, 5), labels)]}
        evidence['purpose'] = [proof(mandate[0])]
    return result


def _row_roster(label, raw_names, expected, split_names):
    if not re.fullmatch(r'[가-힣A-Za-z0-9&/]{2,420}', raw_names.replace('(Co-GP)', '')):
        return []
    teams = split_names(raw_names)
    if not teams or len(teams) != expected:
        return []
    pairs = [team for team in teams if '/' in team]
    if len(pairs) != raw_names.count('(Co-GP)') or len(pairs) > 1:
        return []
    if not pairs:
        return [(label, teams)]
    pair = pairs[0]
    if pair + '(Co-GP)' not in raw_names:
        return []
    return [(f'{label} · 공동운용', team.split('/')) if team == pair else (label, [team]) for team in teams]


def result_roster(notice, text, program, split_names):
    stage = _stage(notice, r'위탁운용사선정결과')
    if (not stage or program.get('asset_scope') != 'PE·VC 공동 모집'
            or not program.get('extraction_evidence', {}).get('innovation_joint_allocation')):
        return []
    match = _RESULT.fullmatch(re.sub(r'\s+', '', text))
    if not match or stage[1] != match[1]:
        return []
    body = match[2]
    rows = list(_RESULT_ROW.finditer(body))
    segments = program.get('segments', [])
    if not rows or rows[0].start() or [m[1] for m in rows] != [s['name'] for s in segments]:
        return []
    rosters = []
    for row, segment, next_row in zip(rows, segments, rows[1:] + [None]):
        label, count, fund_size, target = row.groups()
        count = int(count)
        low, high = _bounds(segment['manager_count'])
        fund_range = [amount * 10**8 for amount in _bounds(fund_size)]
        if (not low <= count <= high or fund_range != segment['fund_target_range_krw']
                or _int(target) * 10**8 != segment['fund_target_total_krw']):
            return []
        group = _row_roster(label, body[row.end():next_row.start() if next_row else len(body)], count, split_names)
        if not group:
            return []
        rosters.extend(group)
    return rosters
