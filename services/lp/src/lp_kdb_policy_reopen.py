"""KDB reannouncements with a sourced year, round and joint policy allocation."""
import hashlib
import re


_ROUND = re.compile(
    r'[『「]([^』」]{3,80})[』」](20\d{2})년([1-9]\d*)차(\(재공고\))?(?:자펀드)?위탁운용사'
    r'(선정계획(?:\(재\)공고|재공고)|제안서접수결과|서류심사결과|선정결과|선정faq게시)'
)
_NUMBER = r'([\d,]+)'
_ALLOCATION = re.compile(
    r'정책출자자위탁운용총액:총' + _NUMBER + r'억원내외\n\(단위:억원\)\n정책출자자\n합계\n'
    r'정부재정\(재정모펀드\)\n한국산업은행\n성장사다리펀드2\n' + r'\n'.join([_NUMBER] * 4) + r'\n\*출자자별'
)
_PLAN = re.compile(
    r'\n재정\n산은\n사다리2\n합계\(비율\)\n' + r'\n'.join([_NUMBER] * 4)
    + r'\((\d+)%\)\n(\d+)\n' + _NUMBER + r'\n산은\n'
)
_MANDATES = re.compile(
    r'❶혁신성장공동기준품목영위중소·중견기업목표결성액의(\d+)%초과결성액의(\d+)%'
    r'❷新성장4\.03대분야15대프로젝트영위중소·중견기업목표결성액의(\d+)%초과결성액의(\d+)%'
    r'❸중소·중견기업목표결성액의(\d+)%초과결성액의(\d+)%○\(선택\)'
)


def _round(title):
    match = _ROUND.fullmatch(re.sub(r'\s+', '', title).casefold())
    if match and (match[4] or match[5].startswith('선정계획')):
        return match
    return None


def identity(notice):
    if notice.get('institution_id') != 'kdb' or not (match := _round(notice['title'])):
        return None
    fund = hashlib.sha256(match[1].encode()).hexdigest()[:16]
    return f'kdb:{match[2]}:{fund}:{match[3]}차:reopen'


def mixed_vehicles(text):
    compact = re.sub(r'\s+', '', text)
    return any('기관전용사모집합투자기구' in cell and '벤처투자조합' in cell
               for cell in re.findall(r'출자대상투자기구((?:○[^○※]{1,180}){2,7})(?=※선정된위탁운용사)', compact))


def _read(raw, url, sha):
    lines = '\n'.join(line for raw_line in raw.splitlines() if (line := re.sub(r'\s+', '', raw_line)))
    caps, tables = list(_ALLOCATION.finditer(lines)), list(_PLAN.finditer(lines))
    if not caps and not tables:
        return {}
    if len(caps) != 1 or len(tables) != 1:
        raise ValueError('산업은행 공동 정책출자 재공고 표 복수 또는 누락')
    cap, table = caps[0], tables[0]
    total, fiscal, kdb, ladder, copy_total = (int(x.replace(',', '')) for x in cap.groups())
    rows = [int(x.replace(',', '')) for x in table.groups()]
    ratio, count, target = rows[4:]
    if (not all((fiscal, kdb, ladder, count, target)) or [fiscal, kdb, ladder, total] != rows[:4]
            or fiscal + kdb + ladder != total or copy_total != total or total * 100 != target * ratio):
        raise ValueError('산업은행 공동 정책출자 재공고 표 합계 불일치')
    evidence = {'policy_allocation': [{'source_url': url, 'sha256': sha, 'quote': cap[0] + '\n' + table[0]}]}
    terms = {'amount_scope': 'combined', 'commitment_amount_krw': total * 10**8,
             'commitment_label': f'공동 정책출자 예정 {total:,}억원 내외', 'fund_target_label': f'{target:,}억원',
             'manager_count': count, 'manager_count_label': f'{count}개사',
             'contribution_allocations': {'정부재정': fiscal * 10**8, '한국산업은행': kdb * 10**8, '성장사다리펀드2': ladder * 10**8},
             'commitment_detail': f'정부재정 {fiscal:,}억원 · 산업은행 {kdb:,}억원 · 성장사다리펀드2 {ladder:,}억원',
             'contribution_note': '출자자별 승인 절차를 거쳐 확정됩니다.', 'extraction_evidence': evidence}
    mandate = _MANDATES.search(lines.replace('\n', ''))
    if mandate and all(0 < int(n) <= 100 for n in mandate.groups()):
        labels = ('혁신성장 공동기준 품목 영위 중소·중견기업', '신성장 4.0 분야 중소·중견기업', '중소·중견기업')
        terms['primary_investment'] = {'source_url': url, 'items': [
            f'{label} · 목표결성액의 {mandate[i]}%, 초과결성액의 {mandate[i+1]}%'
            for i, label in zip((1, 3, 5), labels)]}
        evidence['purpose'] = [{'source_url': url, 'sha256': sha, 'quote': mandate[0]}]
    return terms


def terms(notice, sources):
    if not identity(notice) or not _round(notice['title'])[5].startswith('선정계획'):
        return {}
    relevant = [(url, raw, sha) for url, raw, sha in sources if mixed_vehicles(raw)]
    if not relevant:
        return {}
    matches = [_read(raw, url, sha) for url, raw, sha in relevant]
    matches = [m for m in matches if m]
    if not matches:
        return {'amount_scope': 'combined'}
    if len(matches) != 1:
        raise ValueError('산업은행 공동 정책출자 재공고 원문 복수')
    return matches[0]


def result_roster(result, text, program):
    key = identity(result)
    if (not key or key != program.get('source_program_key') or program.get('manager_count') != 1
            or not program.get('contribution_allocations') or program.get('asset_scope') != 'PE·VC 공동 모집'):
        return []
    # One manager in a one-row table, independently corroborated by the plan's
    # expected manager count and fund formation target. Keep the joint scope.
    match = re.fullmatch(r'\s*<([^<>\n]{8,180}위탁운용사\s*선정\s*결과)\s*>\s*'
                         r'펀드\s*규모\s*선정\s*운용사명\s*([\d,]+)억원\s*([가-힣A-Za-z][가-힣A-Za-z0-9&]{1,34})\s*', text)
    if not match or f"{int(match[2].replace(',', '')):,}억원" != program.get('fund_target_label'):
        return []
    round = _round(result['title'])
    heading = f'{round[1]}{round[2]}년{round[3]}차(재공고)위탁운용사선정결과'
    if re.sub(r'\s+', '', match[1]).casefold() != heading:
        return []
    return [('공동 모집', [match[3]])]
