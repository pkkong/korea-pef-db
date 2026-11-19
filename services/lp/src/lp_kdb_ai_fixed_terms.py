"""KDB AI Korea rounds with a fixed-size plan and a merged-cell result PDF."""

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


_TITLE = r'[『「]ai코리아펀드[』」]위탁운용사'
_RECRUITMENT = re.compile(_TITLE + '선정계획공고')
_FAQ = re.compile(_TITLE + '선정faq게시')
_RESULT = re.compile(_TITLE + '선정결과')
_PLAN_HEADER = ('분야별출자계획○출자계획(단위:개,억원)분야산은출자금액출자비율펀드별목표결성금액'
                '선정운용사수조성목표ai코리아펀드')
_ALLOCATION = _MONEY + r'([1-9]\d?)\.0%'
_ROW = _ALLOCATION + _MONEY + r'([1-9])' + _MONEY
_PLAN = re.compile(re.escape(_PLAN_HEADER) + r'중형' + _ROW + r'소형' + _ROW + r'합계'
                   + _ALLOCATION + r'-([1-9])' + _MONEY + r'\*산은출자금액은')
_CAP = re.compile(r'위탁운용금액:총' + _MONEY + r'억원이내\*위탁운용금액은')
_MANDATE = re.compile(
    r'주목적투자대상및의무투자비율□아래①,②를모두충족하여야함①❶ai인프라,❷ai모델,❸ai응용서비스등'
    r'ai밸류체인에목표결성금액의\[(\d{1,3})%\]이상투자-단,‘ai핵심분야’기업에목표결성금액의'
    r'\[(\d{1,3})%\]이상투자.{0,1200}?②중소[·ㆍ․]중견기업에약정총액의\[(\d{1,3})%\]이상투자'
)
_RESULT_ROW = re.compile(r'[ \t]*(중형|소형)?[ \t]{5,}'
                         r'([가-힣A-Za-z0-9]+(?:[ \t]+-[ \t]+[가-힣A-Za-z0-9]+)?)')


def _own_notice(notice, title):
    return (notice.get('institution_id') == 'kdb' and notice.get('source_channel') == 'institution_board'
            and title.fullmatch(compact(notice['title'])))


def terms(notice, sources):
    if not _own_notice(notice, _RECRUITMENT):
        return {}
    plans = [(url, text, sha) for url, raw, sha in sources
             if _PLAN_HEADER in (text := compact(raw))]
    if not plans:
        return {}  # The later, variable-count AI plan has its own parser.
    if len(plans) != 1 or not mixed_vehicles(plans[0][1]):
        raise ValueError('AI 코리아 고정 리그의 공동 투자기구 또는 원문 미확인')
    url, text, sha = plans[0]
    tables, caps = list(_PLAN.finditer(text)), _CAP.findall(text)
    if len(tables) != 1 or len(caps) != 1:
        raise ValueError('AI 코리아 고정 리그 출자표 불일치')
    table = tables[0]
    values = list(map(_int, table.groups()))
    rows = [values[:5], values[5:10]]
    total, ratio, count, goal = values[10:]
    if (_int(caps[0]) != total or not _rounded(total, goal, ratio)
            or [sum(row[i] for row in rows) for i in (0, 3, 4)] != [total, count, goal]
            or any(target * managers != target_sum or not _rounded(amount, target_sum, share)
                   for amount, share, target, managers, target_sum in rows)):
        raise ValueError('AI 코리아 고정 리그 출자액·결성 목표·선정 수 불일치')

    def proof(quote):
        return {'source_url': url, 'sha256': sha, 'quote': quote}

    evidence = {'ai_fixed_joint_allocation': [proof(table[0])]}
    result = {'amount_scope': 'combined', 'commitment_amount_krw': total * 10**8,
              'commitment_label': f'{total:,}억원 이내', 'manager_count_label': f'{count}개사',
              'fund_target_label': f'{goal:,}억원', 'extraction_evidence': evidence,
              'segments': [{'name': name, 'amount_krw': amount * 10**8, 'manager_count': managers,
                            'fund_target_total_krw': target_sum * 10**8}
                           for name, (amount, _, _, managers, target_sum) in zip(('중형', '소형'), rows)]}
    if (mandate := _MANDATE.search(text)) and all(0 < int(value) <= 100 for value in mandate.groups()):
        result['primary_investment'] = {'source_url': url, 'items': [
            f'AI 밸류체인에 목표결성금액의 {mandate[1]}% 이상 투자',
            f'AI 핵심분야 기업에 목표결성금액의 {mandate[2]}% 이상 투자',
            f'중소·중견기업에 약정총액의 {mandate[3]}% 이상 투자']}
        evidence['purpose'] = [proof(mandate[0])]
    return result


def linked_faqs(notices, texts):
    """A same-year FAQ with its issue date and one earlier fixed-plan original."""
    originals = [n for n in notices if _own_notice(n, _RECRUITMENT)
                 and any(_PLAN_HEADER in compact(text) and mixed_vehicles(text) for text in texts(n))]
    links = {}
    for n in notices:
        if not _own_notice(n, _FAQ):
            continue
        stamp = date.fromisoformat(n['date'])
        dated_heading = rf'ai코리아펀드.{{0,1200}}?위탁운용사선정계획faq{stamp.year}\.0?{stamp.month}\.0?{stamp.day}\.'
        if not any(re.search(dated_heading, compact(text)) for text in texts(n)[1:]):
            continue
        anchors = [row for row in originals if row['date'][:4] == n['date'][:4] and row['date'] < n['date']]
        if len(anchors) == 1:
            links[n['url']] = anchors[0]
    return links


def result_roster(notice, text, program):
    """Use the retained vector layout to distinguish one team from the next."""
    if (not _own_notice(notice, _RESULT) or notice.get('attachment_extraction_version') != 3
            or program.get('asset_scope') != 'PE·VC 공동 모집'):
        return []
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if (len(lines) < 4 or compact(lines[0]) != '<ai코리아펀드위탁운용사선정결과>'
            or compact(lines[1]) != '지원분야선정운용사명(가나다순)'):
        return []
    rows = [_RESULT_ROW.fullmatch(line) for line in lines[2:]]
    segments = program.get('segments', [])
    if any(row is None for row in rows) or [s['name'] for s in segments] != ['중형', '소형']:
        return []
    medium, small = (s['manager_count'] for s in segments)
    if len(rows) != medium + small:
        return []
    groups = (('중형', rows[:medium]), ('소형', rows[medium:]))
    if any([row[1] for row in group if row[1]] != [league] for league, group in groups):
        return []
    roster = []
    for league, group in groups:
        for row in group:
            members = re.split(r'\s+-\s+', row[2])
            roster.append((league + (' · 공동운용' if len(members) == 2 else ''), members))
    return roster
