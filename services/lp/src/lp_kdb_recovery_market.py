"""KDB recovery-market recruitment, cross-year stages and league allocations."""

import re
from collections import defaultdict
from datetime import date, time

try:
    from .lp_kdb_innovation_terms import _MONEY, _int, _rounded
    from .lp_kdb_policy_reopen import mixed_vehicles
    from .lp_notice_triage import compact
except ImportError:
    from lp_kdb_innovation_terms import _MONEY, _int, _rounded
    from lp_kdb_policy_reopen import mixed_vehicles
    from lp_notice_triage import compact


_FUND = '회수시장활성화지원펀드'
_TITLE = r'(?:『' + _FUND + r'』|「' + _FUND + r'」)' + '위탁운용사'
RECRUITMENT = '선정계획공고'
_FAQ = '선정faq게시'
_RECEIPT = '제안서접수결과'
_SCREENING = '선정서류심사결과'
_SELECTION = '선정결과'
_ROLES = (RECRUITMENT, _FAQ, _RECEIPT, _SCREENING, _SELECTION)
_NOTICE = re.compile(_TITLE + '(' + '|'.join(_ROLES) + ')')
_CAP = re.compile(r'위탁운용금액:총' + _MONEY + r'억원이내')
_TABLE = re.compile(
    r'분야별출자계획○출자계획분야산은출자금액산은출자비율펀드별목표결성금액\(최소결성규모\)'
    r'선정운용사수조성목표회수시장활성화m&a' + _MONEY + r'억원(\d+)\.0%'
    + _MONEY + r'억원이상' + _MONEY + r'억원이하자율제안([1-9]\d?)개사이내' + _MONEY + r'억원'
    r'세컨더리' + _MONEY + r'억원(\d+)\.0%' + _MONEY + r'억원([1-9]\d?)개사' + _MONEY
    + r'억원합계' + _MONEY + r'억원(\d+)\.0%--' + _MONEY
    + r'억원\*산은출자금액은펀드별목표결성금액의(\d+)%를초과할수없음'
)
_HOURS = r'(\d{1,2}):(\d{2})[~～](\d{1,2}):(\d{2})'
_WEEKDAY = r'\([월화수목금토일]\)'
_SCHEDULE = re.compile(r'선정일정일자내용비고(20\d{2})\.(\d{1,2})\.(\d{1,2})' + _WEEKDAY
                       + '제안서접수' + _HOURS + r'(20\d{2})\.(\d{1,2})월중최종선정')
_RECEPTION = re.compile(r'접수일시○(20\d{2})년(\d{1,2})월(\d{1,2})일' + _WEEKDAY + _HOURS + '접수방법○')
_MANDATES = re.compile(
    r'주목적투자대상및의무투자비율□m&a펀드:아래①과②를모두충족하여야함'
    r'①\[m&a투자\]의방법으로약정총액의(\d{1,3})%이상투자.{1,750}?'
    r'②중소[·․]중견기업에약정총액의(\d{1,3})%이상투자'
    r'□세컨더리펀드:\[세컨더리투자\]의방법으로약정총액의(\d{1,3})%이상투자'
    r'▪\[세컨더리투자\]:기존펀드주\)가보유한국내중소·벤처기업의기발행주식등'
)
_HEADERS = {
    _FAQ: _FUND + r'.{0,1200}?위탁운용사선정계획faq20\d{2}\.\d{1,2}\.\d{1,2}\.',
    _RECEIPT: _TITLE + r'접수현황\(단위:억원\)지원분야\(지원규모\)조성목표',
    _SCREENING: '<' + _FUND + r'출자사업서류심사통과운용사>지원분야지원운용사명\(가나다순\)',
    _SELECTION: '<' + _FUND + r'위탁운용사선정결과>지원분야선정운용사명\(가나다순\)',
}


def role(notice):
    if notice.get('institution_id') == 'kdb' and notice.get('source_channel') == 'institution_board':
        match = _NOTICE.fullmatch(compact(notice['title']))
        return match[1] if match else None
    return None


def _window(notice, texts):
    plans = [compact(text) for text in texts if mixed_vehicles(text)]
    if len(plans) != 1 or not _TABLE.search(plans[0]):
        return None
    schedules = _SCHEDULE.findall(plans[0])
    receptions = _RECEPTION.findall(plans[0])
    if len(schedules) != 1 or len(receptions) != 1:
        return None
    schedule = tuple(map(int, schedules[0]))
    if tuple(map(int, receptions[0])) != schedule[:7]:
        return None
    year, month, day, start_hour, start_minute, end_hour, end_minute, final_year, final_month = schedule
    try:
        deadline = date(year, month, day)
        selection_month = date(final_year, final_month, 1)
        if time(start_hour, start_minute) >= time(end_hour, end_minute):
            return None
        if date.fromisoformat(notice['date']) <= deadline and 0 <= (selection_month - deadline.replace(day=1)).days <= 62:
            return deadline.isoformat(), selection_month.isoformat()[:7]
    except ValueError:
        return None
    return None


def linked_stages(notices, texts):
    """Match only the sole same-fund recruitment whose printed schedule fits."""
    rounds, later = [], []
    for notice in notices:
        phase = role(notice)
        if phase == RECRUITMENT:
            if window := _window(notice, texts(notice)):
                rounds.append((notice, *window))
        elif phase:
            later.append((notice, phase))
    within_round = defaultdict(list)
    for notice, phase in later:
        stamp = notice['date']
        if not any(re.search(_HEADERS[phase], compact(text)) for text in texts(notice)[1:]):
            continue
        anchors = []
        for original, deadline, selection in rounds:
            if phase == _FAQ:
                fits = original['date'] < stamp < deadline
            elif phase == _SELECTION:
                fits = (deadline < stamp and stamp[:7] == selection
                        and re.match(selection[:4] + '년' + _TITLE + phase, compact(notice['body'])))
            else:
                fits = deadline <= stamp and stamp[:7] <= selection
            if fits:
                anchors.append(original)
        if len(anchors) == 1:
            within_round[anchors[0]['url']].append((notice, _ROLES.index(phase)))
    originals = {n['url']: n for n, _, _ in rounds}
    linked = {}
    for url, entries in within_round.items():
        phases = [phase for _, phase in sorted(entries, key=lambda item: (item[0]['date'], item[1]))]
        if phases == sorted(set(phases)):
            linked.update({notice['url']: originals[url] for notice, _ in entries})
    return linked


def terms(notice, sources):
    if role(notice) != RECRUITMENT:
        return {}
    plans = [(url, compact(raw), sha) for url, raw, sha in sources if mixed_vehicles(raw)]
    if len(plans) != 1 or not (table := _TABLE.search(plans[0][1])):
        raise ValueError('회수시장 활성화 리그 표 또는 투자기구 원문 미확인')
    url, text, sha = plans[0]
    caps = list(_CAP.finditer(text))
    ma, ma_pct, low, high, ma_count, ma_goal, secondary, sec_pct, sec_size, sec_count, sec_goal, total, pct, goal, limit = (
        map(_int, table.groups()))
    if (len(caps) != 1 or _int(caps[0][1]) != total or ma + secondary != total or ma_goal + sec_goal != goal
            or not all(_rounded(*row) for row in ((ma, ma_goal, ma_pct), (secondary, sec_goal, sec_pct), (total, goal, pct)))
            or not max(ma_pct, sec_pct, pct) <= limit <= 100
            or low > high or not low <= ma_goal <= ma_count * high or sec_size * sec_count != sec_goal):
        raise ValueError('회수시장 활성화 리그별 출자액·결성 목표·모집 상한 불일치')

    def proof(quote):
        return {'source_url': url, 'sha256': sha, 'quote': quote}

    evidence = {'recovery_market_allocation': [proof(caps[0][0]), proof(table[0])]}
    result = {'amount_scope': 'combined', 'commitment_amount_krw': total * 10**8,
              'commitment_label': f'산업은행 출자 예정 {total:,}억원 이내', 'fund_target_label': f'{goal:,}억원',
              'commitment_detail': f'산업은행 출자 한도는 펀드별 목표결성금액의 {limit}%입니다.',
              'manager_count_label': f'{ma_count + sec_count}개사 이내',
              'segments': [
                  {'name': 'M&A', 'amount_krw': ma * 10**8, 'manager_count': f'{ma_count}개사 이내',
                   'fund_target_range_krw': [low * 10**8, high * 10**8]},
                  {'name': '세컨더리', 'amount_krw': secondary * 10**8, 'manager_count': sec_count,
                   'fund_target_range_krw': [sec_size * 10**8, sec_size * 10**8]}],
              'contribution_note': (f'M&A 결성 목표 {ma_goal:,}억원(펀드별 {low:,}억~{high:,}억원 자율 제안), '
                                    f'세컨더리 결성 목표 {sec_goal:,}억원(펀드별 {sec_size:,}억원)입니다.'),
              'extraction_evidence': evidence}
    if (mandate := _MANDATES.search(text)) and all(0 < int(pct) <= 100 for pct in mandate.groups()):
        result['primary_investment'] = {'source_url': url, 'items': [
            f'M&A · M&A 방식 투자에 약정총액의 {mandate[1]}% 이상 투자',
            f'M&A · 중소·중견기업에 약정총액의 {mandate[2]}% 이상 투자',
            f'세컨더리 · 기존 펀드가 보유한 국내 중소·벤처기업 구주 등 인수에 약정총액의 {mandate[3]}% 이상 투자']}
        evidence['purpose'] = [proof(mandate[0])]
    return result


def result_roster(notice, text, program, split_names):
    if role(notice) != _SELECTION or program.get('asset_scope') != 'PE·VC 공동 모집':
        return []
    result = re.fullmatch(_HEADERS[_SELECTION] + r'[Mm]&[Aa]([가-힣A-Za-z0-9]+)세컨더리([가-힣A-Za-z0-9]+)',
                          re.sub(r'\s+', '', text))
    if not result:
        return []
    rosters = [(segment['name'], split_names(names)) for segment, names in zip(program['segments'], result.groups())]
    return rosters if len(rosters) == 2 and all(
        names and len(names) <= int(re.match(r'\d+', str(segment['manager_count']))[0])
        for segment, (_, names) in zip(program['segments'], rosters)) else []
