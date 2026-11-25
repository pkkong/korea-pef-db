"""The KDB-led large growth-support league in the 2024 first policy round."""

import re
from datetime import datetime

try:
    from .lp_kdb_growth_support_terms import _ALLOCATION, _MANDATES
    from .lp_kdb_innovation_terms import _MONEY, _int
    from .lp_kdb_policy_reopen import mixed_vehicles
    from .lp_notice_triage import compact
except ImportError:
    from lp_kdb_growth_support_terms import _ALLOCATION, _MANDATES
    from lp_kdb_innovation_terms import _MONEY, _int
    from lp_kdb_policy_reopen import mixed_vehicles
    from lp_notice_triage import compact


_ROUND = '2024년1차'
_RECRUITMENT = re.compile(r'[『「]혁신성장펀드\(성장지원펀드\)[』」]' + _ROUND + r'(?:위탁운용사)?선정계획공고')
_SHARED = re.compile(r'[『「]혁신성장펀드[』」]' + _ROUND + r'위탁운용사(제안서접수결과|선정결과)')
_PLAN = re.compile(r'\n재정\n산은\n합계\(비율\)\n대형\n' + r'\n'.join([_MONEY] * 3)
                   + r'\((\d{1,3})%\)\n' + _MONEY + r'\n([1-9]\d?)\n' + _MONEY + r'\n산은\n')
_RECEPTION = re.compile(r'접수일시○(2024)년(\d{1,2})월(\d{1,2})일\(([월화수목금토일])\)'
                        r'(\d{1,2}):(\d{2})~(\d{1,2}):(\d{2})접수방법')
_RESULT_HEADER = ('<혁신성장펀드2024년1차위탁운용사선정결과>', '(단위:억원,개)', '지원분야',
                  '(운용사수)', '펀드규모', '선정운용사명(가나다순)', '주관기관')
_APPLICATION_HEADER = '혁신성장펀드차출자사업위탁운용사접수결과<1>'


def _own_round(notice):
    return (notice.get('institution_id') == 'kdb' and notice.get('source_channel') == 'institution_board'
            and notice['date'].startswith('2024-') and not notice.get('channel_id'))


def shared_stage(notice):
    if _own_round(notice) and (stage := _SHARED.fullmatch(compact(notice['title']))):
        return stage[1]
    return None


def _plan(raw):
    lines = '\n'.join(line for row in raw.splitlines() if (line := re.sub(r'\s+', '', row)))
    caps, plans = list(_ALLOCATION.finditer(lines)), list(_PLAN.finditer(lines))
    if (not re.search(r'^[『「]혁신성장펀드\(성장지원펀드\)[』」]\n' + _ROUND + '위탁운용사선정계획공고', lines)
            or not mixed_vehicles(raw) or len(caps) != 1 or len(plans) != 1):
        raise ValueError('성장지원 2024년 1차 모집의 산업은행 대형 출자표 미확인')
    cap, plan = caps[0], plans[0]
    total, fiscal, bank, check_total = map(_int, cap.groups())
    table_fiscal, table_bank, table_total, ratio, fund, count, target = map(_int, plan.groups())
    if ((table_fiscal, table_bank, table_total) != (fiscal, bank, total) or total != check_total
            or total != fiscal + bank or fund * count != target or not 0 < ratio <= 100
            or total * 100 != target * ratio):
        raise ValueError('성장지원 2024년 1차 출자 재원·결성 목표 합계 불일치')
    return total, fiscal, bank, fund, count, target, cap[0] + '\n' + plan[0]


def _reception(raw, announced):
    receptions = list(_RECEPTION.finditer(re.sub(r'\s+', '', raw)))
    if len(receptions) != 1:
        return None
    match = receptions[0]
    y, m, d, weekday, start_h, start_m, end_h, end_m = match.groups()
    try:
        start = datetime(*map(int, (y, m, d, start_h, start_m)))
        end = datetime(*map(int, (y, m, d, end_h, end_m)))
    except ValueError:
        return None
    if start < end and end.date().isoformat() > announced and '월화수목금토일'[end.weekday()] == weekday:
        return end, match[0]
    return None


def terms(notice, sources):
    if not _own_round(notice) or not _RECRUITMENT.fullmatch(compact(notice['title'])):
        return {}
    plans = [(url, raw, sha) for url, raw, sha in sources if url != notice['url'] and mixed_vehicles(raw)]
    if len(plans) != 1:
        raise ValueError('성장지원 2024년 1차 모집의 투자기구 첨부를 하나로 확인할 수 없다')
    url, raw, sha = plans[0]
    total, fiscal, bank, fund, count, target, quote = _plan(raw)

    def proof(fragment):
        return {'source_url': url, 'sha256': sha, 'quote': fragment}

    evidence = {'growth_support_2024_first_allocation': [proof(quote)]}
    result = {'amount_scope': 'combined', 'commitment_amount_krw': total * 10**8,
              'commitment_label': f'공동 정책출자 예정 {total:,}억원 내외', 'fund_target_label': f'{target:,}억원',
              'manager_count_label': f'{count}개사',
              'segments': [{'name': '대형', 'amount_krw': total * 10**8, 'manager_count': count,
                            'fund_target_range_krw': [fund * 10**8, fund * 10**8],
                            'fund_target_total_krw': target * 10**8}],
              'contribution_allocations': {'정부재정': fiscal * 10**8, '한국산업은행': bank * 10**8},
              'commitment_detail': f'정부재정 {fiscal:,}억원 · 산업은행 {bank:,}억원',
              'contribution_note': '대형 리그는 한국산업은행이 주관합니다. 출자자별 승인 절차를 거쳐 확정됩니다.',
              'extraction_evidence': evidence}
    if reception := _reception(raw, notice['date']):
        deadline, fragment = reception
        result.update(deadline=deadline.isoformat() + '+09:00', deadline_precision='datetime')
        evidence['deadline'] = [proof(fragment)]
    else:
        result['deadline_error'] = '성장지원 2024년 1차 접수 마감 시각 미확인'
    mandate = _MANDATES.search(re.sub(r'\s+', '', raw))
    if mandate and all(0 < int(mandate[i]) <= 100 for i in (2, 3, 5, 6, 8)):
        result['primary_investment'] = {'source_url': url, 'items': [
            f'창업 후 {mandate[1]}년 이상 경과한 중소·중견기업 · 목표결성액의 {mandate[2]}%, 초과결성액의 {mandate[3]}%',
            f'투자 전 기업가치 {mandate[4]}억원 이상 중소·중견기업 · 목표결성액의 {mandate[5]}%, 초과결성액의 {mandate[6]}%',
            f'중소·중견기업당 {mandate[7]}억원 이상 투자 · 목표결성액의 {mandate[8]}%']}
        evidence['purpose'] = [proof(mandate[0])]
    return result


def _selected(text, fund, count, target):
    lines = [compact(line) for line in text.splitlines() if line.strip()]
    markers = [i for i, line in enumerate(lines) if line.startswith('성장지원/대형')]
    if tuple(lines[:7]) != _RESULT_HEADER or len(markers) != 1:
        return []
    block = lines[markers[0]:]
    if (len(block) != 4 + count or block[:3] != [f'성장지원/대형({count})', f'{fund:,}', f'(총{target:,})']
            or block[4] != '산은'):
        return []
    names = [block[3], *block[5:]]
    if len(set(names)) == count and all(re.fullmatch(r'[가-힣]{3,48}', name) for name in names):
        return names
    return []


def linked_stages(notices, texts):
    originals = [n for n in notices if _own_round(n) and _RECRUITMENT.fullmatch(compact(n['title']))]
    if len(originals) != 1:
        return {}
    original, = originals
    plans = [raw for raw in texts(original)[1:] if mixed_vehicles(raw)]
    try:
        if len(plans) != 1:
            return {}
        _, _, _, fund, count, target, _ = _plan(plans[0])
    except ValueError:
        return {}
    if not (reception := _reception(plans[0], original['date'])):
        return {}
    deadline = reception[0].date().isoformat()
    application_row = re.compile(rf'성장지원대형\({count}\){fund:,}총\({target:,}\)(\d{{1,2}})[가-힣]')
    links = {}
    for notice in notices:
        phase = shared_stage(notice)
        if not phase or notice['date'] < deadline:
            continue
        attachments = texts(notice)[1:]
        if phase == '선정결과':
            valid = sum(bool(_selected(raw, fund, count, target)) for raw in attachments) == 1
        else:
            tables = [table for raw in attachments if (table := compact(raw)).startswith(_APPLICATION_HEADER)]
            valid = (len(tables) == 1 and len(matches := application_row.findall(tables[0])) == 1
                     and int(matches[0]) >= count)
        if valid:
            links[notice['url']] = original
    return links


def result_roster(notice, text, program):
    if shared_stage(notice) != '선정결과' or program.get('asset_scope') != 'PE·VC 공동 모집':
        return []
    segment, = program['segments']
    names = _selected(text, segment['fund_target_range_krw'][0] // 10**8, segment['manager_count'],
                      segment['fund_target_total_krw'] // 10**8)
    return [('대형', names)] if names else []
