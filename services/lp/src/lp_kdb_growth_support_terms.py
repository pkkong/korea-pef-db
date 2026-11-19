"""Read the two-league KDB growth-support policy plan and its result."""

import re

try:
    from .lp_kdb_innovation_terms import _MONEY, _RANGE, _bounds, _int, _rounded, read_result_rows
    from .lp_kdb_policy_reopen import mixed_vehicles
except ImportError:
    from lp_kdb_innovation_terms import _MONEY, _RANGE, _bounds, _int, _rounded, read_result_rows
    from lp_kdb_policy_reopen import mixed_vehicles


_FUND = r'혁신성장펀드\(성장지원펀드\)'
_ALLOCATION = re.compile(
    r'정책출자자위탁운용총액:총' + _MONEY + r'억원내외\n\(단위:억원\)\n정책출자자\n합계\n'
    r'정부재정\(재정모펀드\)\n한국산업은행\n' + r'\n'.join([_MONEY] * 3) + r'\n\*출자자별'
)
_ROW = (r'(중형|대형)(?:\n\(자율제안\))?\n' + _MONEY + r'\n' + _MONEY + r'\n'
        + _MONEY + r'\((\d+)%\)\n(' + _RANGE + r')\n([1-9](?:~[1-9])?)\n' + _MONEY + r'\n(우리|산은)\n')
_PLAN = re.compile(
    r'\n재정\n산은\n합계\(비율\)\n((?:' + _ROW + r'){2})합계\n'
    + r'\n'.join([_MONEY] * 3) + r'\((\d+)%\)\n-\n([1-9](?:~[1-9])?)\n' + _MONEY + r'\n'
)
_LEADS = re.compile(r'대형중형주관기관한국산업은행\(정책펀드금융실\)우리자산운용\(신성장기업투자실\)')
_MANDATES = re.compile(
    r'❶창업후(\d+)년이상경과중소·중견기업목표결성액의(\d+)%초과결성액의(\d+)%'
    r'❷투자전기업가치\(Pre-MoneyValue\)' + _MONEY + r'억원이상중소·중견기업'
    r'목표결성액의(\d+)%초과결성액의(\d+)%'
    r'❸기업당투자금액이' + _MONEY + r'억원이상\(중소·중견기업限\)목표결성액의(\d+)%'
)
_RESULT = re.compile(
    r'<' + _FUND + r'(20\d{2})년위탁운용사선정결과>\(단위:억원,개\)'
    r'지원분야\(운용사수\)펀드규모선정운용사명\(가나다순\)(.+)'
)


def _stage(notice, suffix):
    if notice.get('institution_id') != 'kdb':
        return None
    return re.fullmatch(r'[「『]' + _FUND + r'[」』](20\d{2})년위탁운용사' + suffix, re.sub(r'\s+', '', notice['title']))


def terms(notice, sources):
    if not _stage(notice, '선정계획공고'):
        return {}
    sources = [(url, raw, sha) for url, raw, sha in sources if mixed_vehicles(raw)]
    if len(sources) != 1:
        raise ValueError('성장지원 공동 모집의 투자기구 원문 미확인')
    url, raw, sha = sources[0]
    lines = '\n'.join(line for raw_line in raw.splitlines() if (line := re.sub(r'\s+', '', raw_line)))
    compact = lines.replace('\n', '')
    caps, plans = list(_ALLOCATION.finditer(lines)), list(_PLAN.finditer(lines))
    leads = _LEADS.search(compact)
    if len(caps) != 1 or len(plans) != 1 or not leads:
        raise ValueError('성장지원 공동 출자자·리그·주관기관 표 미확인')
    cap, plan = caps[0], plans[0]
    total, fiscal, bank, copy_total = map(_int, cap.groups())
    table_fiscal, table_bank, table_total, ratio = map(_int, plan.groups()[-6:-2])
    count, target = plan.groups()[-2], _int(plan.groups()[-1])
    rows = list(re.finditer(_ROW, plan[1]))
    if ([(r[1], r[9]) for r in rows] != [('중형', '우리'), ('대형', '산은')]
            or (fiscal, bank, total) != (table_fiscal, table_bank, table_total)
            or total != copy_total or total != fiscal + bank or not _rounded(total, target, ratio)):
        raise ValueError('성장지원 공동 출자 개요와 합계 행 불일치')
    if [sum(_int(r[i]) for r in rows) for i in (2, 3, 4, 8)] != [fiscal, bank, total, target]:
        raise ValueError('성장지원 리그별 출자액·결성 목표 합계 불일치')
    count_bounds = [_bounds(row[7]) for row in rows]
    if tuple(map(sum, zip(*count_bounds))) != _bounds(count):
        raise ValueError('성장지원 리그별 선정 예정 수 불일치')
    segments = []
    for row, (low, high) in zip(rows, count_bounds):
        name, fiscal_share, bank_share, amount, ratio, size, count_label, goal, _ = row.groups()
        fiscal_share, bank_share, amount, ratio, goal = map(_int, (fiscal_share, bank_share, amount, ratio, goal))
        minimum, maximum = _bounds(size)
        if (fiscal_share + bank_share != amount or not _rounded(amount, goal, ratio)
                or minimum > maximum or low > high or not low * minimum <= goal <= high * maximum):
            raise ValueError('성장지원 리그별 출자액·결성 범위 불일치')
        segments.append({'name': name, 'amount_krw': amount * 10**8, 'manager_count': count_label,
                         'fund_target_range_krw': [minimum * 10**8, maximum * 10**8],
                         'fund_target_total_krw': goal * 10**8})

    def proof(quote):
        return {'source_url': url, 'sha256': sha, 'quote': quote}

    bank_shares = ' · '.join(f'{row[1]} {_int(row[3]):,}억원' for row in rows)
    targets = ' · '.join(f'{row[1]} {_int(row[8]):,}억원' for row in rows)
    evidence = {'growth_support_joint_allocation': [proof(cap[0]), proof(plan[0]), proof(leads[0])]}
    result = {'amount_scope': 'combined', 'commitment_amount_krw': total * 10**8,
              'commitment_label': f'공동 정책출자 예정 {total:,}억원 내외', 'fund_target_label': f'{target:,}억원',
              'manager_count_label': f'{count}개 팀', 'segments': segments,
              'contribution_allocations': {'정부재정': fiscal * 10**8, '한국산업은행': bank * 10**8},
              'commitment_detail': f'정부재정 {fiscal:,}억원 · 산업은행 {bank:,}억원({bank_shares})',
              'contribution_note': (f'리그별 결성 목표는 {targets}입니다. 중형은 우리자산운용, 대형은 한국산업은행이 '
                                    '주관합니다. 출자자별 승인 절차를 거쳐 확정됩니다.'),
              'extraction_evidence': evidence}
    mandate = _MANDATES.search(compact)
    if mandate and all(0 < int(mandate[i]) <= 100 for i in (2, 3, 5, 6, 8)):
        result['primary_investment'] = {'source_url': url, 'items': [
            f'창업 후 {mandate[1]}년 이상 경과한 중소·중견기업 · 목표결성액의 {mandate[2]}%, 초과결성액의 {mandate[3]}%',
            f'투자 전 기업가치 {mandate[4]}억원 이상 중소·중견기업 · 목표결성액의 {mandate[5]}%, 초과결성액의 {mandate[6]}%',
            f'중소·중견기업당 {mandate[7]}억원 이상 투자 · 목표결성액의 {mandate[8]}%']}
        evidence['purpose'] = [proof(mandate[0])]
    return result


def result_roster(notice, text, program, split_names):
    stage = _stage(notice, '선정결과')
    if (not stage or program.get('asset_scope') != 'PE·VC 공동 모집'
            or not program.get('extraction_evidence', {}).get('growth_support_joint_allocation')):
        return []
    match = _RESULT.fullmatch(re.sub(r'\s+', '', text))
    if not match or match[1] != stage[1]:
        return []
    return read_result_rows(match[2], program.get('segments', []), split_names)
