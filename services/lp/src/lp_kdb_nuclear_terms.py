"""Read KDB's retained nuclear-industry subfund documents and their stated roles."""
import re
from datetime import datetime

try:
    from .lp_kdb_policy_reopen import mixed_vehicles
except ImportError:
    from lp_kdb_policy_reopen import mixed_vehicles


_TITLE = r'[「『]원전산업성장펀드[」』]자펀드위탁운용사'
_AMOUNT = r'([\d,]+)'
_ALLOCATION = re.compile(
    r'위탁운용총액:총' + _AMOUNT + r'억원\n\(단위:억원\)\n정책출자자\n지정출자자\n합계\n'
    r'재정\n\(원전산업성장펀드1호\)\n한국산업은행\n한국수력원자력\n\(원전산업성장펀드2호\)\n'
    + r'\n'.join([_AMOUNT] * 4) + r'\n\*출자자별'
)
_PLAN = re.compile(r'조성목표\n선정\n운용사수\n출자비율\n주관기관\n자율제안\*\n' + _AMOUNT
                   + r'\n(\d+)~(\d+)\n(\d+)%이내\n신한자산운용\n')
_RECEPTION = re.compile(r'접수일시○(20\d{2})년(\d{1,2})월(\d{1,2})일\([월화수목금토일]\)'
                        r'(\d{1,2}):(\d{2})~(\d{1,2}):(\d{2})\(신한자산운용앞제출\)접수방법○')
_MANDATE = re.compile(r'❶원전산업영위주1\)중소·중견기업목표결성액의(\d+)%'
                      r'❷SMR관련기업주2\(기업규모제한없음\)아래투자비율중선택주3\)'
                      r'목표결성액의①(\d+)%,②(\d+)%,③(\d+)%주1\)')


def _is_stage(notice, suffix):
    return notice.get('institution_id') == 'kdb' and re.fullmatch(_TITLE + suffix, re.sub(r'\s+', '', notice['title']))


def _read(raw, url, sha, posted):
    lines = '\n'.join(line for raw_line in raw.splitlines() if (line := re.sub(r'\s+', '', raw_line)))
    allocations = list(_ALLOCATION.finditer(lines))
    plans = list(_PLAN.finditer(lines))
    if len(allocations) != 1 or len(plans) != 1:
        raise ValueError('원전 자펀드 출자자·주관기관 표 불일치')
    allocation, plan = allocations[0], plans[0]
    total, fiscal, bank, khnp, table_total = (int(v.replace(',', '')) for v in allocation.groups())
    target, low, high, cap = (int(v.replace(',', '')) for v in plan.groups())
    if (not all((fiscal, bank, khnp, target, low, high, cap)) or total != table_total
            or total != fiscal + bank + khnp or low > high or total * 100 > target * cap or cap > 100):
        raise ValueError('원전 자펀드 공동 출자 규모와 계획표 합계 불일치')
    proof = lambda quote: {'source_url': url, 'sha256': sha, 'quote': quote}
    evidence = {'nuclear_joint_allocation': [proof(allocation[0] + '\n' + plan[0])]}
    terms = {'amount_scope': 'combined', 'commitment_amount_krw': total * 10**8,
             'commitment_label': f'공동 위탁운용 예정 {total:,}억원', 'fund_target_label': f'{target:,}억원',
             'manager_count_label': f'{low}~{high}개사',
             'contribution_allocations': {'정부재정': fiscal * 10**8, '한국산업은행': bank * 10**8, '한국수력원자력': khnp * 10**8},
             'commitment_detail': f'정부재정 {fiscal:,}억원 · 산업은행 {bank:,}억원 · 한국수력원자력 {khnp:,}억원',
             'contribution_note': '주관기관은 신한자산운용입니다. 출자자별 승인 절차를 거쳐 확정됩니다.',
             'extraction_evidence': evidence}
    compact = lines.replace('\n', '')
    reception = list(_RECEPTION.finditer(compact))
    if len(reception) == 1:
        year, month, day, start_hour, start_minute, end_hour, end_minute = map(int, reception[0].groups())
        try:
            start = datetime(year, month, day, start_hour, start_minute)
            end = datetime(year, month, day, end_hour, end_minute)
            if start >= end or end.date().isoformat() < posted:
                raise ValueError('invalid range')
            terms.update(deadline=end.isoformat() + '+09:00', deadline_precision='datetime')
            evidence['deadline'] = [proof(reception[0][0])]
        except ValueError:
            terms['deadline_error'] = '원전 자펀드 접수 시각과 게시일 불일치'
    mandate = _MANDATE.search(compact)
    if mandate:
        industry, *smr = map(int, mandate.groups())
        if 0 < industry <= 100 and all(0 < ratio <= 100 for ratio in smr) and smr == sorted(set(smr)):
            choices = ', '.join(f'{ratio}%' for ratio in smr)
            terms['primary_investment'] = {'source_url': url, 'items': [
                f'원전산업 영위 중소·중견기업 · 목표결성액의 {industry}%',
                f'소형모듈원자로(SMR) 관련 기업 · 목표결성액의 {choices} 중 선택']}
            evidence['purpose'] = [proof(mandate[0])]
    return terms


def terms(notice, sources):
    if not _is_stage(notice, r'선정계획공고'):
        return {}
    relevant = [(raw, url, sha) for url, raw, sha in sources if mixed_vehicles(raw)]
    if len(relevant) != 1:
        raise ValueError('원전 자펀드 공동 모집 원문의 범위 미확인')
    raw, url, sha = relevant[0]
    return _read(raw, url, sha, notice['date'])


def result_roster(result, text, program, split_names):
    if (not _is_stage(result, r'선정결과') or program.get('asset_scope') != 'PE·VC 공동 모집'
            or not program.get('extraction_evidence', {}).get('nuclear_joint_allocation')):
        return []
    match = re.fullmatch(r'\s*<\s*원전산업성장펀드\s*자펀드\s*위탁운용사\s*선정\s*결과\s*>\s*'
                         r'\(단위\s*:\s*억원,\s*개\)\s*운용사\s*수\s*펀드\s*규모\s*지원\s*운용사명\s*\(가나다순\)\s*'
                         r'([1-9])' + _AMOUNT + r'\(총\s*' + _AMOUNT + r'\)\s*([가-힣A-Za-z0-9& \t]{2,90})\s*', text)
    bounds = re.fullmatch(r'(\d+)~(\d+)개사', program.get('manager_count_label', ''))
    if not match or not bounds:
        return []
    count, amount, total = (int(value.replace(',', '')) for value in match.groups()[:3])
    if (count * amount != total or not int(bounds[1]) <= count <= int(bounds[2])
            or f'{total:,}억원' != program.get('fund_target_label')):
        return []
    names = split_names(match[4])
    return [('공동 모집', names)] if names and len(names) == count else []
