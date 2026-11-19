"""Sourced joint allocations for KDB's recovery-market secondary fund."""

import re
from datetime import date

try:
    from .lp_kdb_innovation_terms import _MONEY, _int, _rounded
    from .lp_kdb_policy_reopen import mixed_vehicles
    from .lp_notice_triage import compact
except ImportError:
    from lp_kdb_innovation_terms import _MONEY, _int, _rounded
    from lp_kdb_policy_reopen import mixed_vehicles
    from lp_notice_triage import compact


_FUND = r'[『「](20\d{2})회수시장지원세컨더리펀드[』」]'
_TITLE = re.compile(_FUND + r'위탁운용사(선정계획공고|\(소형\)선정계획재공고)')
_CAP = re.compile(r'위탁운용금액:총' + _MONEY + r'억원\*위탁운용금액은')
_TABLE = r'분야별출자계획○출자계획분야산은출자금액산은출자비율'
_ROW = r'(중형|소형)' + _MONEY + r'억원(\d+)\.0%' + _MONEY + r'억원([1-9]\d?)개'
_FULL = re.compile(_TABLE + r'펀드별목표결성금액선정운용사수조성목표'
                   + r'((?:' + _ROW + _MONEY + r'억원){2})'
                   + r'합계' + _MONEY + r'억원(\d+)\.0%-([1-9]\d?)개' + _MONEY + r'억원\*산은출자금액은')
_ROW_TOTAL = re.compile(_ROW + _MONEY + r'억원')
_SMALL = re.compile(_TABLE + r'목표결성금액선정운용사수' + _ROW + r'\*산은출자금액은')
_PRIOR = re.compile(r'○[ʹ’\'](\d{2})\.(\d{1,2})\.(\d{1,2})자공고한' + _FUND
                    + r'출자사업에지원하였던위탁운용사의재지원가능')
_MANDATE = re.compile(
    r'주목적투자대상및의무투자비율○기존펀드❶및운용사❷보유국내중소·벤처기업의기발행주식등\*의인수에'
    r'약정총액의(\d{1,3})%이상투자'
)


def terms(notice, sources):
    if notice.get('institution_id') != 'kdb' or notice.get('source_channel') != 'institution_board':
        return {}
    title = compact(notice['title'])
    match = _TITLE.fullmatch(title)
    if not match or match[1] != notice['date'][:4]:
        return {}
    plans = [(url, compact(raw), sha) for url, raw, sha in sources if mixed_vehicles(raw)]
    if len(plans) != 1:
        raise ValueError('산업은행 세컨더리 공동 투자기구 원문 미확인')
    url, text, sha = plans[0]
    reopen = match[2].startswith('(소형)')
    tables = list((_SMALL if reopen else _FULL).finditer(text))
    caps = _CAP.findall(text)
    if len(tables) != 1 or len(caps) != 1 or title not in text[:300]:
        raise ValueError('산업은행 세컨더리 출자계획 원문 표 미확인')
    table = tables[0]
    if reopen:
        name, amount, ratio, fund, managers = table.groups()
        total, ratio, count, goal = _int(amount), int(ratio), int(managers), _int(fund)
        rows = [(name, total, ratio, goal, count, goal)]
        if name != '소형' or count != 1:
            raise ValueError('세컨더리 소형 재공고 리그 불일치')
    else:
        total, ratio, count, goal = map(_int, table.groups()[-4:])
        rows = [(row[1], *map(_int, row.groups()[1:])) for row in _ROW_TOTAL.finditer(table[1])]
        if [row[0] for row in rows] != ['중형', '소형']:
            raise ValueError('세컨더리 모집 리그 불일치')
    if (_int(caps[0]) != total or not _rounded(total, goal, ratio)
            or [sum(row[i] for row in rows) for i in (1, 4, 5)] != [total, count, goal]
            or any(target * n != target_sum or not _rounded(value, target_sum, rate)
                   for _, value, rate, target, n, target_sum in rows)):
        raise ValueError('산업은행 세컨더리 출자액·예정 수·결성 목표 불일치')

    def proof(quote):
        return {'source_url': url, 'sha256': sha, 'quote': quote}

    evidence = {'secondary_joint_allocation': [proof(table[0])]}
    result = {'amount_scope': 'combined', 'commitment_amount_krw': total * 10**8,
              'commitment_label': f'{total:,}억원', 'manager_count_label': f'{count}개사',
              'fund_target_label': f'{goal:,}억원', 'extraction_evidence': evidence,
              'segments': [{'name': name, 'amount_krw': value * 10**8, 'manager_count': n,
                            'fund_target_total_krw': target_sum * 10**8}
                           for name, value, _, _, n, target_sum in rows]}
    if (mandate := _MANDATE.search(text)) and 0 < int(mandate[1]) <= 100:
        result['primary_investment'] = {'source_url': url, 'items': [
            f'기존 펀드와 운용사가 보유한 국내 중소·벤처기업 구주 등 인수에 약정총액의 {mandate[1]}% 이상 투자']}
        evidence['purpose'] = [proof(mandate[0])]
    if reopen and (prior := _PRIOR.search(text)) and '20' + prior[1] == prior[4] == match[1]:
        try:
            previous = date(int(prior[4]), int(prior[2]), int(prior[3]))
        except ValueError:
            return result
        if previous.isoformat() < notice['date']:
            result['commitment_detail'] = f'{previous.month}월 {previous.day}일 공고의 소형 분야 재모집'
            evidence['secondary_recruitment_reference'] = [proof(prior[0])]
    return result
