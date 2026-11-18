"""Read KDB's K-content and media technology-depth recruitment and selection."""

import re
from datetime import datetime
from itertools import combinations

try:
    from .lp_kdb_policy_reopen import mixed_vehicles
except ImportError:
    from lp_kdb_policy_reopen import mixed_vehicles


_FUND = r'[「『]K-콘텐츠[·ㆍ]?미디어전략펀드[」』]위탁운용사'
_NUMBER = r'[1-9]\d{0,2}(?:,\d{3})*'
_ALLOCATION = re.compile(
    r'모펀드및지정출자자\(한국산업은행\)위탁운용금액:총(' + _NUMBER + r')억원이내'
    r'\(단위:억원\)모펀드지정출자자\(한국산업은행\)합계정부재정\(재정모펀드\)비재정모펀드'
    r'([0-9,]{4,32})분야별출자계획'
)
_PLAN_HEADER = (
    r'출자계획\(단위:개,억원\)지원분야출자금액출자비율펀드별목표결성금액선정운용사수조성목표'
    r'주관기관재정비재정산은기술심화\(블라인드펀드\)'
)
_RECEPTION = re.compile(r'접수일시○(20\d{2})년(\d{1,2})월(\d{1,2})일\([월화수목금토일]\)'
                        r'(\d{1,2}):(\d{2})~(\d{1,2}):(\d{2})접수방법○')
_MANDATE = re.compile(
    r'□콘텐츠·미디어산업관련기술심화◦콘텐츠·미디어관련기업및프로젝트에약정총액의\[(\d+)%\]이상투자'
    r'◦아래①~③을합산주1\)하여약정총액의\[(\d+)%\]이상투자'
    r'①방송영상콘텐츠·미디어산업에적용되는국내기술주2\)보유·개발기업'
    r'②방송영상콘텐츠·미디어산업에적용되는국내첨단기술주3\)보유·개발기업'
    r'③첨단기술을적용하여제작하는국내방송영상콘텐츠·미디어제작프로젝트주4\)'
)


def _compact(text):
    return re.sub(r'\s+', '', text)


def _is_stage(notice, suffix):
    return notice.get('institution_id') == 'kdb' and re.fullmatch(_FUND + suffix, _compact(notice['title']))


def _integer(value):
    return int(value.replace(',', ''))


def _shares(digits, total):
    # The PDF joins table cells. Accept only one partition with the source total.
    options = []
    for left, right in combinations(range(1, len(digits)), 2):
        cells = (digits[:left], digits[left:right], digits[right:])
        if all(re.fullmatch(_NUMBER, value) for value in cells):
            values = tuple(map(_integer, cells))
            if sum(values) == total:
                options.append(values)
    if len(options) != 1:
        raise ValueError('K-콘텐츠·미디어 출자자별 금액의 합계 또는 열 경계 불일치')
    return options[0]


def terms(notice, sources):
    if not _is_stage(notice, r'선정계획공고'):
        return {}
    relevant = [(url, _compact(raw), sha) for url, raw, sha in sources if mixed_vehicles(raw)]
    if len(relevant) != 1:
        raise ValueError('K-콘텐츠·미디어 기술심화 공동 모집 원문 미확인')
    url, text, sha = relevant[0]
    allocations = list(_ALLOCATION.finditer(text))
    if len(allocations) != 1 or not allocations[0][2].endswith(allocations[0][1]):
        raise ValueError('K-콘텐츠·미디어 기술심화 공동 출자 표 불일치')
    allocation = allocations[0]
    printed_total, cells = allocation.groups()
    total = _integer(printed_total)
    digits = cells[:-len(printed_total)]
    fiscal, investment_fund, bank = _shares(digits, total)
    plans = list(re.finditer(_PLAN_HEADER + re.escape(digits) + r'(\d{1,3})%이내(' + _NUMBER +
                             r')([1-9])(' + _NUMBER + r')산은◦', text))
    if len(plans) != 1:
        raise ValueError('K-콘텐츠·미디어 기술심화 분야별 출자계획과 출자자 표 불일치')
    plan = plans[0]
    cap, per_fund, count, target = map(_integer, plan.groups())
    if target != count * per_fund or not 0 < cap <= 100 or 100 * total > cap * target:
        raise ValueError('K-콘텐츠·미디어 기술심화 결성 목표 또는 출자비율 불일치')

    def proof(quote):
        return {'source_url': url, 'sha256': sha, 'quote': quote}

    evidence = {'media_joint_allocation': [proof(allocation[0]), proof(plan[0])]}
    result = {'amount_scope': 'combined', 'commitment_amount_krw': total * 10**8,
              'commitment_label': f'공동 위탁운용 예정 {total:,}억원 이내', 'fund_target_label': f'{target:,}억원',
              'manager_count': count, 'manager_count_label': f'{count}개사',
              'contribution_allocations': {'정부재정': fiscal * 10**8, '비재정모펀드': investment_fund * 10**8,
                                           '한국산업은행': bank * 10**8},
              'commitment_detail': f'정부재정 {fiscal:,}억원 · 비재정모펀드 {investment_fund:,}억원 · 산업은행 {bank:,}억원',
              'contribution_note': '주관기관은 한국산업은행입니다. 출자자별 승인 절차를 거쳐 확정됩니다.',
              'extraction_evidence': evidence}
    receptions = list(_RECEPTION.finditer(text))
    if len(receptions) == 1:
        reception = receptions[0]
        year, month, day, start_hour, start_minute, end_hour, end_minute = map(int, reception.groups())
        try:
            start = datetime(year, month, day, start_hour, start_minute)
            end = datetime(year, month, day, end_hour, end_minute)
            if start >= end or end.date().isoformat() < notice['date']:
                raise ValueError('invalid reception window')
        except ValueError:
            result['deadline_error'] = 'K-콘텐츠·미디어 기술심화 접수 구간 불일치'
        else:
            result.update(deadline=end.isoformat() + '+09:00', deadline_precision='datetime')
            evidence['deadline'] = [proof(reception[0])]
    elif receptions:
        result['deadline_error'] = 'K-콘텐츠·미디어 기술심화 접수 구간이 여러 개'
    mandate = _MANDATE.search(text)
    if mandate and all(0 < int(ratio) <= 100 for ratio in mandate.groups()):
        industry, technology = mandate.groups()
        result['primary_investment'] = {'source_url': url, 'items': [
            f'기술심화 · 콘텐츠·미디어 관련 기업 및 프로젝트에 약정총액의 {industry}% 이상 투자',
            f'국내 방송영상 콘텐츠·미디어 기술 보유·개발 기업 또는 첨단기술 제작 프로젝트 · 약정총액의 {technology}% 이상']}
        evidence['purpose'] = [proof(mandate[0])]
    return result


def result_roster(notice, text, program, split_names):
    if (not _is_stage(notice, r'선정결과') or program.get('asset_scope') != 'PE·VC 공동 모집'
            or not program.get('extraction_evidence', {}).get('media_joint_allocation')):
        return []
    match = re.fullmatch(_FUND + r'선정결과지원분야\(운용사수\)펀드규모\(억원\)선정운용사명\(가나다순\)'
                         r'기술심화\(([1-9])\)(' + _NUMBER + r')\(총(' + _NUMBER + r')\)'
                         r'([가-힣A-Za-z0-9&]{2,90})', _compact(text))
    if not match:
        return []
    count, per_fund, target = map(_integer, match.groups()[:3])
    if count != program.get('manager_count') or per_fund * count != target or f'{target:,}억원' != program.get('fund_target_label'):
        return []
    names = split_names(match[4])
    return [('기술심화', names)] if names and len(names) == count else []
