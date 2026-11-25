"""Link the KDB-led small league to the 2024 second-round official notices."""

import re

try:
    from .lp_kdb_growth_support_2024 import _own_round, _reception
    from .lp_kdb_innovation_terms import _MONEY, _int
    from .lp_kdb_policy_reopen import _ALLOCATION, mixed_vehicles
    from .lp_notice_triage import compact
except ImportError:
    from lp_kdb_growth_support_2024 import _own_round, _reception
    from lp_kdb_innovation_terms import _MONEY, _int
    from lp_kdb_policy_reopen import _ALLOCATION, mixed_vehicles
    from lp_notice_triage import compact


_FUND = r'[『「]혁신성장펀드\(혁신산업펀드\)[』」]'
_ROUND = '2024년2차'
_RECRUITMENT = re.compile(_FUND + _ROUND + r'(?:위탁운용사)?선정계획공고')
_SHARED = re.compile(r'[『「]혁신성장펀드[』」]' + _ROUND + r'위탁운용사(제안서접수결과|선정결과)')
_GROWTH_SUPPORT = re.compile(
    r'[『「]혁신성장펀드\(성장지원펀드\)[』」]' + _ROUND + r'(?:위탁운용사)?선정계획공고'
)
_GROWTH_FINANCE_ROW = re.compile(
    r'\n합계\(비율\)\n중형\n[\d,]+\n[\d,]+\n[\d,]+\(\d+%\)\n[\d,]+\n[1-9]\d?\n[\d,]+\n성장금융\n'
)
_PLAN = re.compile(r'\n재정\n산은\n사다리2주2\)\n합계\(비율\)\n소형주1\)\n'
                   + r'\n'.join([_MONEY] * 4) + r'\((\d{1,3})%\)\n' + _MONEY
                   + r'\n([1-9]\d?)\n' + _MONEY + r'\n산은\n')
_PURPOSE = re.compile(
    r'❶혁신성장공동품목기준해당중소·중견기업목표결성액의(\d+)%초과결성액의(\d+)%'
    r'❷❷-1新성장4\.03대분야15대프로젝트,❷-2‘글로벌초격차산업육성지원’및‘미래유망산업지원분야'
    r'영위중소·중견기업목표결성액의(\d+)%초과결성액의(\d+)%'
    r'❸중소·중견기업목표결성액의(\d+)%초과결성액의(\d+)%'
)
_AI = re.compile(
    r'\(선택\)아래품목을주목적투자대상으로추가제안한운용사를우선하여선정\(1개사\)'
    r'.{1,150}?소형\(1,000억원\)혁신성장공동기준품목중ai기반산업품목영위중소·중견기업'
    r'\(상세품목은별첨파일참조\)목표결성액의(\d+)%이상'
)
_APPLICATION_HEADER = '<혁신성장펀드2차출자사업위탁운용사접수결과>'
_RESULT_HEADER = (
    '혁신성장펀드년차위탁운용사선정결과<20242>',
    '단위억원개(:,)', '지원분야', '운용사수()펀드규모선정운용사명가나다순()주관기관',
)


def _recruitment(notice):
    return _own_round(notice) and _RECRUITMENT.fullmatch(compact(notice['title']))


def shared_stage(notice):
    if _own_round(notice) and (match := _SHARED.fullmatch(compact(notice['title']))):
        return match[1]
    return None


def growth_finance_recruitment(notice, texts):
    if not (_own_round(notice) and _GROWTH_SUPPORT.fullmatch(compact(notice['title']))):
        return False
    return any(_GROWTH_FINANCE_ROW.search(re.sub(r'[^\S\n]+', '', raw))
               for raw in texts(notice)[1:])


def _read_plan(raw):
    lines = '\n'.join(line for row in raw.splitlines() if (line := re.sub(r'\s+', '', row)))
    caps, plans = list(_ALLOCATION.finditer(lines)), list(_PLAN.finditer(lines))
    if (not re.match(_FUND + '\n' + _ROUND + '위탁운용사선정계획공고', lines)
            or len(caps) != 1 or len(plans) != 1):
        raise ValueError('혁신산업 2024년 2차 산업은행 소형 출자표 미확인')
    cap, plan = caps[0], plans[0]
    total, fiscal, bank, ladder, copy = map(_int, cap.groups())
    *shares, row_total, ratio, size, count, target = map(_int, plan.groups())
    if (shares != [fiscal, bank, ladder] or total != sum(shares) or total != copy or total != row_total
            or size * count != target or not 0 < ratio <= 100 or total * 100 != target * ratio):
        raise ValueError('혁신산업 2024년 2차 소형의 출자 합계·결성 목표 불일치')
    allocation = {'정부재정': fiscal * 10**8, '한국산업은행': bank * 10**8, '성장사다리펀드2': ladder * 10**8}
    return total, size, count, target, allocation, cap[0] + '\n' + plan[0]


def terms(notice, sources):
    if not _recruitment(notice):
        return {}
    plans = [(url, raw, sha) for url, raw, sha in sources if url != notice['url'] and mixed_vehicles(raw)]
    if len(plans) != 1:
        raise ValueError('혁신산업 2024년 2차 모집의 투자기구 첨부를 하나로 확인할 수 없다')
    url, raw, sha = plans[0]
    total, size, count, target, allocation, quote = _read_plan(raw)

    def proof(text):
        return {'source_url': url, 'sha256': sha, 'quote': text}

    evidence = {'innovation_2024_second_allocation': [proof(quote)]}
    terms = {
        'amount_scope': 'combined', 'commitment_amount_krw': total * 10**8,
        'commitment_label': f'공동 정책출자 예정 {total:,}억원 내외', 'fund_target_label': f'{target:,}억원',
        'manager_count_label': f'{count}개사',
        'segments': [{'name': '소형', 'amount_krw': total * 10**8, 'manager_count': count,
                      'fund_target_range_krw': [size * 10**8, size * 10**8],
                      'fund_target_total_krw': target * 10**8}],
        'contribution_allocations': allocation,
        'commitment_detail': ' · '.join(
            f'{label} {amount // 10**8:,}억원'
            for label, amount in allocation.items()),
        'contribution_note': '소형 리그는 한국산업은행이 주관합니다. 출자자별 승인 절차를 거쳐 확정됩니다.',
        'extraction_evidence': evidence,
    }
    if reception := _reception(raw, notice['date']):
        deadline, fragment = reception
        terms.update(deadline=deadline.isoformat() + '+09:00', deadline_precision='datetime')
        evidence['deadline'] = [proof(fragment)]
    else:
        terms['deadline_error'] = '혁신산업 2024년 2차 접수 마감 시각 미확인'
    items, quotes = [], []
    if (purpose := _PURPOSE.search(re.sub(r'\s+', '', raw))) and all(0 < int(p) <= 100 for p in purpose.groups()):
        labels = ('혁신성장 공동품목기준에 해당하는 중소·중견기업',
                  '신성장 4.0·글로벌 초격차·미래유망 분야 영위 중소·중견기업', '중소·중견기업')
        items.extend(f'{label} · 목표결성액의 {purpose[i]}%, 초과결성액의 {purpose[i+1]}%'
                     for i, label in zip((1, 3, 5), labels))
        quotes.append(purpose[0])
    if (ai := _AI.search(compact(raw))) and 0 < int(ai[1]) <= 100:
        items.append(f'선택 주목적 · AI 기반 산업 품목 영위 중소·중견기업에 목표결성액의 {ai[1]}% 이상 투자 제안 시 1개사 우선 선정')
        quotes.append(ai[0])
    if items:
        terms['primary_investment'] = {'source_url': url, 'items': items}
        evidence['purpose'] = [proof(fragment) for fragment in quotes]
    return terms


def _selected(text, size, count, target):
    lines = [compact(line) for line in text.splitlines() if line.strip()]
    # The official PDF's text order separates the lead from adjacent names.
    # Limit the read to the innovation/small block before the growth-support row.
    boundaries = [i for i, line in enumerate(lines) if line.startswith('성장지원중형/')]
    if tuple(lines[:4]) != _RESULT_HEADER or lines.count(f'혁신산업소형/({count}){size:,}') != 1 or len(boundaries) != 1:
        return []
    block = lines[4:boundaries[0]]
    if (len(block) != 3 + count or block[:2] != [f'혁신산업소형/({count}){size:,}', f'총({target:,})']
            or block[3] != '산은'):
        return []
    names = [block[2], *block[4:]]
    return names if len(set(names)) == count and all(re.fullmatch(r'[가-힣]{3,48}', name) for name in names) else []


def linked_stages(notices, texts):
    originals = [n for n in notices if _recruitment(n)]
    if len(originals) != 1:
        return {}
    original, = originals
    plans = [raw for raw in texts(original)[1:] if mixed_vehicles(raw)]
    if len(plans) != 1:
        return {}
    try:
        _, size, count, target, _, _ = _read_plan(plans[0])
    except ValueError:
        return {}
    if not (reception := _reception(plans[0], original['date'])):
        return {}
    deadline = reception[0].date().isoformat()
    application_row = re.compile(rf'혁신산업소형\({count}\){size:,}\(총{target:,}\)(\d{{1,2}})[가-힣]')
    links = {}
    for notice in notices:
        phase = shared_stage(notice)
        if not phase or notice['date'] < deadline:
            continue
        attachments = texts(notice)[1:]
        if phase == '선정결과':
            valid = sum(bool(_selected(raw, size, count, target)) for raw in attachments) == 1
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
    return [('소형', names)] if names else []
