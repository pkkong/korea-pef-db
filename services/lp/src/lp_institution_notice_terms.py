"""Conservative labelled facts for independently validated issuer-board receipts."""
import copy
import re
from datetime import date, datetime
try:
    from .lp_attachment_policy import is_submission_attachment
    from .lp_shared_notice_terms import extract_offering_sources
    from .lp_kfcc_notice_terms import allocation as kfcc_allocation
    from .lp_kdb_policy_reopen import terms as kdb_reopen_terms
    from .lp_kdb_nuclear_terms import terms as kdb_nuclear_terms
    from .lp_moel_iaci_notice_terms import extract_deadline as iaci_deadline
    from .lp_moel_iaci_notice_terms import extract_allocation as iaci_allocation
except ImportError:
    from lp_attachment_policy import is_submission_attachment
    from lp_shared_notice_terms import extract_offering_sources
    from lp_kfcc_notice_terms import allocation as kfcc_allocation
    from lp_kdb_policy_reopen import terms as kdb_reopen_terms
    from lp_kdb_nuclear_terms import terms as kdb_nuclear_terms
    from lp_moel_iaci_notice_terms import extract_deadline as iaci_deadline
    from lp_moel_iaci_notice_terms import extract_allocation as iaci_allocation

NUM = r'(\d[\d,]*)'
_CWMA_OVERVIEW = re.compile(r'(?m)^1\.\s*선정\s*개요\s*$')
_CWMA_CONDITIONS = re.compile(r'(?m)^2\.\s*주요\s*출자조건\s*$')
_CWMA_JOINT_PE = re.compile(r'(?m)^□[ \t]*국내[ \t]+사모투자펀드\(PEF\)[ \t]+위탁운용사[ \t]+선정계획[ \t]*$')
_CWMA_JOINT_VC = re.compile(r'(?m)^□[ \t]*국내[ \t]+벤처펀드\(VC\)[ \t]+위탁운용사[ \t]+선정계획[ \t]*$')
_CWMA_PROCEDURE = re.compile(r'(?m)^\d+\.[ \t]*선정절차[ \t]*$')
_ALLOCATION_FIELDS = ('commitment_amount_krw', 'total_commitment_amount_krw', 'commitment_label',
                      'list_commitment_label', 'manager_count', 'manager_count_label', 'segments',
                      'per_fund_amount_krw', 'per_fund_range_krw', 'per_fund_qualifier', 'fund_target_label')


def kdb_joint_size_offering(raw):
    """Recognize the KDB size plan with one current eligible-vehicles cell."""
    text = re.sub(r'\s+', '', raw)
    if not _KDB_SIZE_PLAN.search(text):
        return False
    for cell in re.findall(r'출자대상투자기구((?:○[^○※]{1,180}){2,7})(?=※선정된위탁운용사)', text):
        rows = cell.split('○')[1:]
        if (any('기관전용사모집합투자기구' in row for row in rows)
                and any(re.search(r'창업[·ㆍ]벤처전문사모집합투자기구|법」에의한(?:벤처투자조합|신기술사업투자조합)', row)
                        for row in rows)):
            return True
    return False


_KDB_RECEPTION = re.compile(
    r'접수일시○(20\d{2})년(\d{1,2})월(\d{1,2})일\([월화수목금토일]\)'
    r'(\d{1,2}):(\d{2})[~～](\d{1,2}):(\d{2})접수방법○'
)
_KDB_SIZE_PLAN = re.compile(
    r'분야별출자계획○출자계획분야산은출자금액산은출자비율펀드별목표결성금액선정운용사수조성목표'
    r'중형' + NUM + r'억원\d+(?:\.\d+)?%' + NUM + r'억원(\d+)개' + NUM + r'억원'
    r'소형' + NUM + r'억원\d+(?:\.\d+)?%[\d,]+또는[\d,]+억원\(운용사자율선택\)'
    r'(\d+)[~～](\d+)개' + NUM + r'억원'
    r'합계' + NUM + r'억원\d+(?:\.\d+)?%[-–](\d+)[~～](\d+)개' + NUM + r'억원'
)
_KDB_AI_MANDATE = re.compile(
    r'주목적투자대상및의무투자비율□아래①과②를모두충족하여야함'
    r'①➊AI인프라,➋AI모델,➌AI응용서비스,➍AI전환\(AIX\)등AI밸류체인에'
    r'목표결성금액의\[(\d{1,3})%\]이상투자※AI밸류체인.{1,1200}?'
    r'②중소[·․]중견기업에약정총액의(\d{1,3})%이상투자산은출자비율'
)
_KDB_SECTOR_PLAN = re.compile(
    r'분야별출자계획○출자계획분야산은출자금액산은출자비율펀드별목표결성금액\(최소결성규모\)선정운용사수조성목표'
    r'VC' + NUM + r'억원\d+(?:\.\d+)?%' + NUM + r'억원(\d+)개' + NUM + r'억원'
    r'PE신산업투자' + NUM + r'억원\d+(?:\.\d+)?%' + NUM + r'억원(\d+)개' + NUM + r'억원'
    r'사업재편' + NUM + r'억원\d+(?:\.\d+)?%' + NUM + r'억원(\d+)개' + NUM + r'억원'
    r'합계' + NUM + r'억원--(\d+)개' + NUM + r'억원'
)
_KDB_SECTOR_MANDATE = re.compile(
    r'○PE펀드.{1,16}?\[신산업투자\].{1,100}?남부권지역.{0,7}?중소[·․]중견기업에당행출자금의(\d+(?:\.\d+)?)배수\*이상투자'
    r'.{1,16}?\[사업재편\].{0,12}?남부권지역.{0,7}?중소[·․]중견기업의.{0,8}?사업재편에당행출자금의(\d+(?:\.\d+)?)배수\*이상투자'
    r'\*단,동남권지역기업에(\d+(?:\.\d+)?)배수이상및서남권지역기업에(\d+(?:\.\d+)?)배수이상투자하여야함'
)


def _kdb_size_plan(match):
    medium, medium_target, medium_count, medium_goal, small, small_low, small_high, small_goal, total, count_low, count_high, goal = (
        int(value.replace(',', '')) for value in match.groups())
    if (not all((medium, small, medium_count, small_low, small_goal)) or small_low > small_high
            or medium_target * medium_count != medium_goal or medium_goal + small_goal != goal
            or medium + small != total or (medium_count + small_low, medium_count + small_high) != (count_low, count_high)):
        return None
    return total * 10**8, {
        'segments': [{'name': '중형', 'amount_krw': medium * 10**8, 'manager_count': medium_count},
                     {'name': '소형', 'amount_krw': small * 10**8, 'manager_count': f'{small_low}~{small_high}'}],
        'manager_count_label': f'{count_low}~{count_high}개사', 'fund_target_label': f'{goal:,}억원'}


def _kdb_sector_plan(match):
    values = [int(value.replace(',', '')) for value in match.groups()]
    groups = [values[i:i+4] for i in (0, 4, 8)]
    total, count, goal = values[-3:]
    if (not all(values) or any(fund * managers != formation for _, fund, managers, formation in groups)
            or (sum(row[0] for row in groups), sum(row[2] for row in groups), sum(row[3] for row in groups)) != (total, count, goal)):
        raise ValueError('산업은행 PE·VC 리그 표 합계 불일치')
    pe = groups[1:]
    amount = sum(row[0] for row in pe)
    managers = sum(row[2] for row in pe)
    return {'amount_scope': 'pe_only', 'commitment_amount_krw': amount * 10**8,
            'total_commitment_amount_krw': total * 10**8,
            'commitment_label': f'PE 부문 {amount:,}억원 (PE·VC 합계 {total:,}억원 이내)',
            'list_commitment_label': f'PE 부문 {amount:,}억원', 'manager_count': managers,
            'manager_count_label': f'{managers}개사',
            'segments': [{'name': name, 'amount_krw': row[0] * 10**8, 'manager_count': row[2]}
                         for name, row in zip(('신산업 투자', '사업재편'), pe)]}


def _cwma_joint_table(section, kind):
    """Read rows inside one named current-offering section, never its neighbour."""
    def row(label, pattern):
        values = re.findall(r'(?m)^' + label + r'[ \t]*\n[ \t]*' + pattern + r'[ \t]*$', section)
        if len(values) != 1:
            raise ValueError('CWMA PE·VC 모집 표의 행 누락·중복: ' + label)
        return values[0]

    is_pe = kind == 'PE'
    fund = r'사모투자펀드\(PEF\)' if is_pe else r'벤처펀드\(VC\)'
    division = r'국내[ \t]+사모투자펀드\(Private Equity\)' if is_pe else r'국내[ \t]+벤처펀드\(Venture Capital\)'
    row(r'구[ \t]+분', division)
    row('운용방식', r'ㆍ[ \t]*블라인드[ \t]+형태의[ \t]+' + fund)
    row('선정방식', r'ㆍ[ \t]*공개모집[ \t]+공고를[ \t]+통해[ \t]+일괄심사방식으로[ \t]+선정')
    count = int(row(r'선정[ \t]+운용사[ \t]+수', r'ㆍ[ \t]*(\d+)개사[ \t]+이내'))
    total, per_manager = (int(v.replace(',', '')) for v in row(
        r'공제회[ \t]+선정규모', r'ㆍ[ \t]*총[ \t]+' + NUM + r'억원\(1개사[ \t]+당[ \t]+'
        + NUM + r'억원[ \t]+이내\)[ \t]+이내'))
    minimum, maximum = (int(v.replace(',', '')) for v in row(
        '펀드결성총액', r'ㆍ[ \t]*' + NUM + r'억원[ \t]+이상[ \t]+' + NUM
        + r'억원[ \t]+이하(?:[ \t]*※[^\n]*)?'))
    legal = re.findall(r'(?ms)^투자기구[ \t]*\n(.+?)^운용사[ \t]+의무출자[ \t]*$', section)
    if len(legal) != 1:
        raise ValueError('CWMA PE·VC 모집 표의 투자기구 구획 미확인')
    compact = re.sub(r'\s+', '', legal[0])
    if is_pe:
        valid_legal = ('기관전용사모집합투자기구(PEF)' in compact
                       and not re.search(r'벤처|신기술', compact))
    else:
        valid_legal = all(word in compact for word in (
            '벤처투자조합', '신기술사업투자조합', '창업·벤처전문기관전용사모집합투자기구'))
    if not valid_legal:
        raise ValueError('CWMA PE·VC 현재 투자기구 구분 미확인')
    if not (count > 0 and 0 < per_manager <= total and total == count * per_manager
            and per_manager <= minimum <= maximum):
        raise ValueError('CWMA PE·VC 금액·운용사 수·결성규모 불일치')
    return count, total, per_manager, minimum, maximum


def _cwma_joint_allocation(notice, sources):
    title = re.sub(r'\s+', '', notice['title'])
    shared_table = '국내벤처펀드및사모투자펀드' in title
    if notice.get('institution_id') != 'cwma' or not (
            shared_table or all(word in title for word in ('국내사모투자펀드', '벤처펀드'))):
        return {}
    if re.search(r'결과|정정|수정|연장|취소', title):
        raise ValueError('CWMA 후속 공고의 원모집 조건 사용 보류')
    matches = []
    for url, raw, sha in sources:
        if shared_table:
            start = _CWMA_OVERVIEW.search(raw)
            end = _CWMA_CONDITIONS.search(raw, start.end()) if start else None
            if start and end:
                section = raw[start.end():end.start()]
                matches.append((_cwma_joint_shared_table(section),
                                {'source_url': url, 'sha256': sha, 'quote': section.strip()}))
            continue
        pe, vc, end = [list(pattern.finditer(raw)) for pattern in (_CWMA_JOINT_PE, _CWMA_JOINT_VC, _CWMA_PROCEDURE)]
        if not (pe or vc):
            continue
        if len(pe) != 1 or len(vc) != 1 or len(end) != 1 or not pe[0].end() < vc[0].start() < end[0].start():
            raise ValueError('CWMA PE·VC 현재 모집 구획 누락·중복·순서 불일치')
        pe_text, vc_text = raw[pe[0].end():vc[0].start()], raw[vc[0].end():end[0].start()]
        facts = (_cwma_joint_table(pe_text, 'PE'), _cwma_joint_table(vc_text, 'VC'))
        matches.append((facts, {'source_url': url, 'sha256': sha,
                                'quote': raw[pe[0].start():end[0].start()].strip()}))
    if not matches:
        raise ValueError('CWMA PE·VC 분리 모집 표 원문 미확인')
    if len({facts for facts, _ in matches}) != 1:
        raise ValueError('CWMA 원문 사이에 PE·VC 모집 조건 불일치')
    matches.sort(key=lambda item: (item[1]['source_url'], item[1]['sha256']))
    facts = matches[0][0]
    total = sum(f[1] for f in facts)
    segments = []
    for name, (number, amount, per_manager, minimum, maximum) in zip(('국내 사모투자펀드(PEF)', '국내 벤처펀드(VC)'), facts):
        segment = {'name': name, 'amount_krw': amount * 100_000_000,
                   'per_fund_max_krw': per_manager * 100_000_000,
                   'fund_target_label': f'{minimum:,}~{maximum:,}억원' if maximum else f'최소 {minimum:,}억원'}
        if number is not None:
            segment['manager_count'] = number
        segments.append(segment)
    counts = {}
    if all(f[0] is not None for f in facts):
        count = sum(f[0] for f in facts)
        counts = {'manager_count': count, 'manager_count_label': f'{count}개사 이내 (PE·VC 합계)'}
    return {'commitment_amount_krw': total * 100_000_000, 'commitment_label': f'{total:,}억원 이내',
            'list_commitment_label': f'{total:,}억원 이내', 'amount_scope': 'combined', **counts,
            'segments': segments, 'fund_target_label': ' · '.join(
                f'{name} {segment["fund_target_label"]}' for name, segment in zip(('PE', 'VC'), segments)),
            'extraction_evidence': {'combined_allocation': [proof for _, proof in matches]}}


def _cwma_joint_shared_table(section):
    """The retained parallel VC/PE overview orders each pair VC first."""
    compact = re.sub(r'\s+', '', section)
    if (not compact.startswith('구분벤처펀드사모투자펀드운용방식ㆍ개별합동펀드(블라인드형)선정방식ㆍ공개모집')
            or compact.count('투자기구') != 3
            or '벤처투자조합' not in compact or '신기술사업투자조합' not in compact
            or not re.search(r'창업·벤처전문경영참여형사모집합투자기구ㆍ[^ㆍ]+의한경영참여형사모집합투자기구(?:＊|\*)', compact)):
        raise ValueError('CWMA 병렬 모집 표의 현재 PE·VC 열과 투자기구 미확인')
    money = r'ㆍ총' + NUM + r'억원\(운용사당' + NUM + r'억원\)이내'
    minimum = r'ㆍ' + NUM + '억원'
    rows = re.findall('공제회약정금액' + money + money + '최소결성금액' + minimum + minimum + '투자기구', compact)
    if len(rows) != 1:
        raise ValueError('CWMA 병렬 모집 표의 PE·VC 금액 행 누락·중복')
    vc, vc_per, pe, pe_per, vc_min, pe_min = (int(value.replace(',', '')) for value in rows[0])
    if not (0 < vc_per <= vc and vc_per <= vc_min and 0 < pe_per <= pe and pe_per <= pe_min):
        raise ValueError('CWMA 병렬 모집 표의 PE·VC 금액 불일치')
    # The extracted shared manager-count row does not identify a track count.
    return (None, pe, pe_per, pe_min, None), (None, vc, vc_per, vc_min, None)


def _cwma_pe_allocation(notice, sources):
    if notice.get('institution_id') != 'cwma' or '국내사모투자펀드' not in re.sub(r'\s+', '', notice['title']):
        return {}
    matches = []
    for url, raw, sha in sources:
        start = _CWMA_OVERVIEW.search(raw)
        end = _CWMA_CONDITIONS.search(raw, start.end()) if start else None
        if not end:
            continue
        section = raw[start.end():end.start()]
        compact = re.sub(r'\s+', '', section)
        if not all(marker in compact for marker in ('운용방식ㆍ블라인드형', '공개모집',
                                                   '기관전용사모집합투자기구', '창업·벤처전문사모투자기구제외')):
            continue
        rows = (
            re.findall(r'(?m)^운용사[ \t]+수[ \t]*\n[ \t]*ㆍ[ \t]*(\d+)개사[ \t]*이내[ \t]*$', section),
            re.findall(r'(?m)^공제회[ \t]+약정금액[ \t]*\n[ \t]*ㆍ[ \t]*총[ \t]*' + NUM
                       + r'억원\(운용사당[ \t]+' + NUM + r'억원\)[ \t]*이내[ \t]*$', section),
            re.findall(r'(?m)^최소[ \t]+결성금액[ \t]*\n[ \t]*ㆍ[ \t]*' + NUM
                       + r'억원\(공제회[ \t]+출자비율:[ \t]*펀드결성총액의[ \t]*\d+%[ \t]+이하\)[ \t]*$', section),
        )
        if any(len(row) != 1 for row in rows):
            raise ValueError('CWMA PE 모집 표의 출자 조건이 불명확함')
        count = int(rows[0][0])
        total, per_fund = (int(value.replace(',', '')) for value in rows[1][0])
        minimum = int(rows[2][0].replace(',', ''))
        if not (count > 0 and 0 < per_fund <= total <= minimum * count and total == count * per_fund):
            raise ValueError('CWMA PE 모집 표의 약정액과 운용사 수 불일치')
        matches.append(((count, total, per_fund, minimum), {
            'source_url': url, 'sha256': sha, 'quote': section.strip(),
        }))
    if not matches:
        return {}
    if len({facts for facts, _ in matches}) != 1:
        raise ValueError('CWMA 원문 사이에 PE 약정 조건 불일치')
    count, total, per_fund, minimum = matches[0][0]
    return {'commitment_amount_krw': total * 100_000_000, 'commitment_label': f'{total:,}억원 이내',
            'manager_count': count, 'manager_count_label': f'{count}개사 이내',
            'per_fund_amount_krw': per_fund * 100_000_000, 'per_fund_qualifier': '이내',
            'fund_target_label': f'최소 {minimum:,}억원', 'amount_scope': 'pe_only',
            'extraction_evidence': {'pe_allocation': [proof for _, proof in matches]}}


def apply_iaci_allocation(n, result):
    """Use the same explicit PE league totals for own-board and repost sources."""
    allocation = iaci_allocation(n)
    if not allocation:
        return result
    result = copy.deepcopy(result)
    evidence = result.setdefault('extraction_evidence', {})
    if allocation.get('allocation_error'):
        for key in ('commitment_amount_krw', 'total_commitment_amount_krw', 'commitment_label',
                    'list_commitment_label', 'manager_count', 'manager_count_label', 'segments',
                    'per_fund_amount_krw', 'per_fund_range_krw', 'per_fund_qualifier'):
            result.pop(key, None)
        for key in ('commitment', 'pe_allocation', 'manager_count', 'count', 'total', 'per_fund'):
            evidence.pop(key, None)
        result.update(allocation_error=allocation['allocation_error'], allocation_reading_failed=True)
    else:
        evidence.update(allocation.pop('extraction_evidence'))
        result.update(allocation)
    return result


def extract_terms(n):
    sources = [(n['url'], n['body'], n['sha256'])]
    sources += [(u, t, n['attachment_hashes'][u]) for u, t in n.get('attachment_texts', {}).items()
                if not is_submission_attachment(n, u)]
    try:
        cwma_joint = _cwma_joint_allocation(n, sources)
    except ValueError as exc:
        cwma_joint = {'allocation_reading_failed': True, 'allocation_error': str(exc)}
    try:
        kdb_policy = kdb_reopen_terms(n, sources) or kdb_nuclear_terms(n, sources)
    except ValueError as exc:
        kdb_policy = {'allocation_reading_failed': True, 'allocation_error': str(exc)}
    try:
        result = extract_offering_sources(n, sources)
    except ValueError:
        result = {}
    allocation = kfcc_allocation(n)
    if allocation:
        result = allocation
    evidence = result.setdefault('extraction_evidence', {})
    totals, counts, per_fund, deadlines = set(), set(), set(), set()
    dates_only, dated_quotes = set(), []
    mixed = bool(re.search(r'PE\s*[·,/]\s*VC|PE.*VC', n['title'], re.I))
    kdb_vehicles_sources = {url for url, text, _ in sources if n.get('institution_id') == 'kdb' and kdb_joint_size_offering(text)}
    kdb_joint = bool(kdb_vehicles_sources)
    kdb_plan = None
    kdb_mandates = []
    sector_plan, sector_mandates = None, []
    for url, raw, sha in sources:
        text = re.sub(r'\s+', '', raw)
        def record(key, quote):
            evidence.setdefault(key, []).append({'source_url': url, 'sha256': sha, 'quote': quote})
        # Explicit split allocations must reconcile before a PE field is emitted.
        if cwma_joint:
            pass  # This named two-section layout is validated independently.
        elif mixed:
            pe = re.search(r'PE부문[(:：]*' + NUM + r'억원[)]?[:：]*각' + NUM + r'억원[,，]*총(\d+)개사', text)
            vc = re.search(r'VC부문[(:：]*' + NUM + r'억원[)]?[:：]*각' + NUM + r'억원[,，]*총(\d+)개사', text)
            total = re.search(r'출자규모[:：]*총' + NUM + r'억원', text)
            if pe and vc and total:
                p, v, t = [[int(x.replace(',', '')) for x in m.groups()] for m in (pe, vc, total)]
                if p[0] != p[1]*p[2] or v[0] != v[1]*v[2] or p[0]+v[0] != t[0]:
                    raise ValueError('PE/VC split allocation does not reconcile')
                if result.get('commitment_amount_krw') not in (None, p[0]*100_000_000, t[0]*100_000_000):
                    raise ValueError('conflicting independently parsed PE/VC total')
                totals.add((p[0]*100_000_000, ''))
                counts.add((p[2], ''))
                per_fund.add((p[1]*100_000_000, ''))
                record('pe_allocation', pe[0] + ' / ' + vc[0] + ' / ' + total[0])
                result['amount_scope'] = 'pe_only'
        else:
            for match in re.finditer(r'위탁운용금액[:：]*총' + NUM + r'억원(이내|내외)?', text):
                totals.add((int(match[1].replace(',', ''))*100_000_000, match[2] or ''))
                record('total', match[0])
            # The co-investment track shares a notice, but its amount must never
            # be included in the blind Buyout/Growth allocation.
            for match in re.finditer(r'모집규모[:：]*Buyout[·‧ㆍ]Growth' + NUM + r'억원(이내|내외)?(\d+)개사', text, re.I):
                totals.add((int(match[1].replace(',', ''))*100_000_000, match[2] or ''))
                counts.add((int(match[3]), ''))
                record('blind_allocation', match[0])
            for match in re.finditer(r'선정운용사수[:：-]*(?:평가결과상위)?(\d+)개사(이내|내외)?', text):
                counts.add((int(match[1]), match[2] or ''))
                record('manager_count', match[0])
            for match in re.finditer(r'(?:펀드당|1개사별)' + NUM + r'억원(이내|이하|내외)?', text):
                per_fund.add((int(match[1].replace(',', ''))*100_000_000, '이내' if match[2]=='이하' else match[2] or ''))
                record('per_fund', match[0])
        # Only explicitly labelled dates; historical-fund dates cannot supply a
        # deadline. Date-only is retained when source submission times disagree.
        date_text = re.sub(r'(?<=[가-힣])\s+(?=[가-힣])', '', raw)
        labels = r'(?:제안서)?(?:접수마감(?:일시|일|시한)?|접수기한|제출기한|마감일시)'
        pattern = (labels + r"\s*[:：]*\s*[’'‘]?(20\d{2}|\d{2})[.년]\s*(\d{1,2})[.월]\s*(\d{1,2})"
                   r'(?:[.일]\s*(?:\([월화수목금토일](?:요일)?\)\s*)?|\([월화수목금토일](?:요일)?\)\s*|\s+)'
                   r'(오후|오전)?\s*(\d{1,2})(?::(\d{2})|시)')
        for m in re.finditer(pattern, date_text):
            hour = int(m[5]) % 12 + 12 if m[4]=='오후' else (0 if m[4]=='오전' and m[5]=='12' else int(m[5]))
            year = int(m[1]) if len(m[1]) == 4 else 2000 + int(m[1])
            stamp = datetime(year,int(m[2]),int(m[3]),hour,int(m[6] or 0)).isoformat() + '+09:00'
            deadlines.add(stamp)
            record('deadline',m[0])
        sector = _KDB_SECTOR_PLAN.search(text) if n.get('institution_id') == 'kdb' else None
        if sector:
            try:
                allocation = _kdb_sector_plan(sector)
                caps = {int(value.replace(',', '')) * 10**8 for value in
                        re.findall(r'위탁운용금액[:：]*총' + NUM + r'억원이내', text)}
                if caps != {allocation['total_commitment_amount_krw']}:
                    raise ValueError('산업은행 PE·VC 표와 모집 상한 불일치')
                if sector_plan is not None and allocation != sector_plan:
                    raise ValueError('산업은행 PE·VC 리그 표 복수 값')
                sector_plan = allocation
                record('pe_allocation', sector[0])
            except ValueError as exc:
                result.update(allocation_reading_failed=True, allocation_error=str(exc))
            mandate = _KDB_SECTOR_MANDATE.search(text)
            if mandate:
                sector_mandates.append((mandate, url, sha))
        if kdb_joint or sector or kdb_policy:
            for m in _KDB_RECEPTION.finditer(text):
                year, month, day, start_hour, start_minute, end_hour, end_minute = map(int, m.groups())
                start = datetime(year, month, day, start_hour, start_minute)
                end = datetime(year, month, day, end_hour, end_minute)
                if start >= end:
                    result['deadline_error'] = '산업은행 접수 시작·마감 시각 불일치'
                    continue
                deadlines.add(end.isoformat() + '+09:00')
                record('deadline', m[0])
            if url in kdb_vehicles_sources:
                size_plan = _KDB_SIZE_PLAN.search(text)
                plan = _kdb_size_plan(size_plan) if size_plan else None
                if plan:
                    if kdb_plan is not None and kdb_plan != plan:
                        raise ValueError('conflicting KDB funding size tables')
                    kdb_plan = plan
                    record('size_plan', size_plan[0])
                mandate = _KDB_AI_MANDATE.search(text)
                if mandate and all(1 <= int(value) <= 100 for value in mandate.groups()):
                    kdb_mandates.append((mandate, url, sha))
        # "마감일: 2026. 8. 20.(목) (PEF 오전 11시까지, VC 오후 4시까지)": the PE track's own time.
        track = (labels + r"\s*[:：]*\s*[’'‘]?(20\d{2}|\d{2})[.년]\s*(\d{1,2})[.월]\s*(\d{1,2})[.일]?\s*"
                 r'(?:\([월화수목금토일](?:요일)?\)\s*)?\(\s*PEF?\s*(오후|오전)?\s*(\d{1,2})(?::(\d{2})|시)')
        for m in re.finditer(track, date_text):
            hour = int(m[5]) % 12 + 12 if m[4]=='오후' else (0 if m[4]=='오전' and m[5]=='12' else int(m[5]))
            year = int(m[1]) if len(m[1]) == 4 else 2000 + int(m[1])
            deadlines.add(datetime(year,int(m[2]),int(m[3]),hour,int(m[6] or 0)).isoformat() + '+09:00')
            record('deadline',m[0])
        # A labelled date with no time at all is still the deadline, shown date-only.
        dated = labels + r"\s*[:：]*\s*[’'‘]?(20\d{2}|\d{2})[.년]\s*(\d{1,2})[.월]\s*(\d{1,2})(?![\d])"
        for m in re.finditer(dated, date_text):
            year = int(m[1]) if len(m[1]) == 4 else 2000 + int(m[1])
            dates_only.add(date(year,int(m[2]),int(m[3])).isoformat())
            dated_quotes.append({'source_url': url, 'sha256': sha, 'quote': m[0]})
        if re.search(labels + r"\s*[:：]*\s*[’'‘]?(?:20\d{2}|\d{2})[.년]\d{1,2}[.월]\d{2,4}:\d{2}", date_text):
            result.pop('deadline', None)
            result['deadline_error'] = '접수 날짜와 시각 경계 불명확'
        # A direct/quick-delivery cutoff can conflict with the captioned time.
        delivery = re.findall(r'(?:직접제출|퀵).{0,90}?(\d{1,2})(?:시|:\d{2})까지', text)
        if delivery and deadlines and any(int(h) != int(d[11:13]) for h in delivery for d in deadlines):
            result['deadline_error'] = '접수 마감과 직접 제출 시각 불일치; 날짜만 표시'
    for values, field in ((totals,'total'), (counts,'count'), (per_fund,'per_fund')):
        if len(values)>1:
            raise ValueError('conflicting institution offering '+field)
    if totals:
        amount, qualifier = next(iter(totals))
        if not mixed and result.get('commitment_amount_krw') and amount != result['commitment_amount_krw']:
            raise ValueError('conflicting independently parsed total')
        result.update(commitment_amount_krw=amount, commitment_label=f'{amount/100_000_000:,.0f}억원'+(' '+qualifier if qualifier else ''),
                      amount_scope='combined' if kdb_joint and not mixed else 'pe_only')
        if kdb_plan and result['amount_scope'] == 'combined' and kdb_plan[0] == amount:
            result.update(kdb_plan[1])
    if counts:
        count, qualifier = next(iter(counts))
        result.update(manager_count=count, manager_count_label=f'{count}개사'+(' '+qualifier if qualifier else ''))
    if kdb_mandates:
        result.pop('primary_investment', None)
        evidence.pop('purpose', None)
        if len({m.groups() for m, _, _ in kdb_mandates}) == 1:
            mandate, url, _ = kdb_mandates[0]
            result['primary_investment'] = {
                'items': [f'목표결성금액의 {mandate[1]}% 이상을 AI 밸류체인에 투자',
                          f'약정총액의 {mandate[2]}% 이상을 중소·중견기업에 투자'], 'source_url': url}
            evidence['purpose'] = [{'source_url': url, 'sha256': sha, 'quote': m[0]} for m, url, sha in kdb_mandates]
    if result.get('allocation_reading_failed'):
        for field in _ALLOCATION_FIELDS:
            result.pop(field, None)
    elif sector_plan:
        result.update(sector_plan)
        if sector_mandates and len({m.groups() for m, _, _ in sector_mandates}) == 1:
            mandate, url, _ = sector_mandates[0]
            result['primary_investment'] = {'source_url': url, 'items': [
                f'신산업 투자 · 남부권 중소·중견기업에 산업은행 출자금의 {mandate[1]}배 이상 투자',
                f'사업재편 · 남부권 중소·중견기업 사업재편에 산업은행 출자금의 {mandate[2]}배 이상 투자',
                f'산업은행 출자금의 {mandate[3]}배 이상을 동남권 기업에, {mandate[4]}배 이상을 서남권 기업에 투자']}
            evidence['purpose'] = [{'source_url': url, 'sha256': sha, 'quote': m[0]} for m, url, sha in sector_mandates]
    if per_fund:
        amount, qualifier = next(iter(per_fund))
        result.update(per_fund_amount_krw=amount, per_fund_qualifier=qualifier)
    if not deadlines and dates_only and len(dates_only) == 1 and min(dates_only) >= n['date']:
        evidence.setdefault('deadline', []).extend(dated_quotes)
        result.update(deadline=next(iter(dates_only)), deadline_precision='date')
    if deadlines:
        days = {d[:10] for d in deadlines}
        if len(days)>1 or min(days)<n['date']:
            result.pop('deadline',None)
            result['deadline_error']='접수 마감 날짜 불일치'
        elif len(deadlines)>1 or result.get('deadline_error'):
            result.update(deadline=next(iter(days)), deadline_precision='date')
        else:
            result.update(deadline=next(iter(deadlines)), deadline_precision='datetime')
    specific = iaci_deadline(n)
    if specific:
        conflict = specific.get('deadline_error') or result.get('deadline_error')
        if specific.get('deadline') and result.get('deadline'):
            current, revised = result['deadline'], specific['deadline']
            if current[:10] != revised[:10] or (len(current) > 10 and len(revised) > 10 and current != revised):
                conflict = '접수 일정 표와 다른 원문 마감 불일치'
        if conflict:
            result.pop('deadline', None)
            result.pop('deadline_precision', None)
            evidence.pop('deadline', None)
            result['deadline_error'] = conflict
        else:
            result.update(deadline=specific['deadline'], deadline_precision=specific['deadline_precision'])
            evidence.setdefault('deadline', []).extend(specific['extraction_evidence']['deadline'])
    cwma = {} if cwma_joint else _cwma_pe_allocation(n, sources)
    if cwma:
        evidence.update(cwma.pop('extraction_evidence'))
        result.update(cwma)
    if cwma_joint:
        for field in _ALLOCATION_FIELDS:
            result.pop(field, None)
        for field in ('manager_count', 'count', 'total', 'pe_total', 'vc_total', 'pe_count',
                      'per_fund', 'pe_segments', 'pe_fund_range', 'pe_fund_qualifier', 'amount_qualifier'):
            evidence.pop(field, None)
        evidence.update(cwma_joint.pop('extraction_evidence', {}))
        result.update(cwma_joint)
        result['missing_fields'] = [field for field in (
            'commitment_amount_krw', 'manager_count', 'deadline', 'primary_investment') if field not in result]
    if kdb_policy:
        for field in _ALLOCATION_FIELDS:
            result.pop(field, None)
        evidence.update(kdb_policy.pop('extraction_evidence', {}))
        result.update(kdb_policy)
    return apply_iaci_allocation(n, result)
