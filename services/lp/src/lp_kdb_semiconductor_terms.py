"""Terms and lifecycle for KDB's second-year semiconductor blind solicitation."""

import re
from datetime import date, datetime

try:
    from .lp_notice_triage import compact
except ImportError:
    from lp_notice_triage import compact


_FUND = '반도체생태계펀드'
_TITLE = r'[「『]' + _FUND + r'[」』]2차년도'
_RECRUITMENT = re.compile(_TITLE + '위탁운용사선정계획공고')
_APPLICATION = re.compile(_TITLE + '위탁운용사접수현황')
_BLIND_STAGE = re.compile(_TITLE + r'\(블라인드펀드\)위탁운용사선정(?:서류심사)?결과')
_SELECTION = re.compile(_TITLE + r'\(블라인드펀드\)위탁운용사선정결과')
_PLAN_TITLE = '「반도체생태계펀드(2차)」위탁운용사선정계획공고(안)'
_PLAN_HEADER = ('1.선정개요항목블라인드펀드프로젝트펀드주관기관○한국산업은행,한국성장금융○한국성장금융'
                '제안방식○모펀드제안방식○운용사제안방식위탁운용금액및선정운용사수')
_MONEY = r'([1-9][\d,]*)'
_SIZE_COLUMNS = '선정운용사수운용사별출자금액펀드별최소결성금액'
_PLAN = re.compile(
    re.escape(_PLAN_HEADER) + r'○총' + _MONEY + r'억원○총' + _MONEY + r'억원\*\(소부장' + _MONEY
    + r'\)\(단위:억원\)' + _SIZE_COLUMNS + r'([1-9]\d?)개([\d,]+)○총' + _MONEY
    + r'억원\*\(소부장' + _MONEY + ',팹리스' + _MONEY + r'\)\(단위:억원\)' + _SIZE_COLUMNS
    + r'제안금액,출자비율등을감안하여개별협의\*산업은행' + _MONEY + r'억원,ibk혁신성장펀드1호'
    + _MONEY + r'억원,반도체생태계모펀드' + _MONEY + r'억원\*1차년도공고'
)
_LEADS = '접수처및문의방법항목블라인드펀드(산업은행,성장금융공동주관)프로젝트펀드(성장금융주관)'
_RECEPTION = re.compile(r'접수일시(20\d{2})년(\d{1,2})월(\d{1,2})일\(([월화수목금토일])\)'
                        r'(\d{2}):(\d{2})~(\d{2}):(\d{2})수시접수')
_VEHICLES = re.compile(r'출자대상투자기구(○.{1,440}?)※본계획에따라선정된위탁운용사는')
_PURPOSE = re.compile(r'블라인드펀드소부장○반도체분야의.{1,140}?소재·부품·장비산업을영위하는기업에'
                      r'약정총액의\[(\d{1,3})%\]이상투자')
_RESULT_HEADER = ('<반도체생태계펀드(2차년도)블라인드펀드위탁운용사선정결과>', '(단위:억원,개)',
                  '지원분야', '(운용사수)', '펀드규모', '선정운용사명(가나다순)', '주관기관')


def _own(notice):
    return notice.get('institution_id') == 'kdb' and notice.get('source_channel') == 'institution_board'


def identity(notice):
    if not _own(notice):
        return None
    title = compact(notice['title'])
    blind_application = _APPLICATION.fullmatch(title) and re.match(
        _TITLE + r'\(블라인드펀드\)위탁운용사접수현황', compact(notice['body']))
    if _RECRUITMENT.fullmatch(title) or _BLIND_STAGE.fullmatch(title) or blind_application:
        return f"kdb:{notice['date'][:4]}:{_FUND}:2차년도:블라인드"
    return None


def terms(notice, sources):
    if not _own(notice) or not _RECRUITMENT.fullmatch(compact(notice['title'])):
        return {}
    originals = [(url, text, sha) for url, raw, sha in sources
                 if url != notice['url'] and _PLAN_TITLE in (text := compact(raw))[:170]]
    if len(originals) != 1:
        raise ValueError('반도체 2차년도 모집 첨부가 누락되거나 여러 개다')
    url, text, sha = originals[0]
    plans = list(_PLAN.finditer(text))
    vehicles = _VEHICLES.findall(text)
    if (len(plans) != 1 or len(vehicles) != 1 or text.count(_LEADS) != 1
            or not all(form in vehicles[0] for form in ('기관전용사모집합투자기구', '벤처투자조합'))):
        raise ValueError('반도체 2차년도 출자표·공동 주관·투자기구를 확인할 수 없다')
    plan = plans[0]
    total, blind, sector, count, row, project, project_sector, fabless, bank, ibk, parent = (
        int(value.replace(',', '')) for value in plan.groups())
    per_fund, remainder = divmod(blind, count)
    row_match = re.fullmatch(rf'{per_fund}([1-9]\d*)', str(row))
    if (not row_match or remainder or blind != sector or blind + project != total
            or project_sector + fabless != project or bank + ibk + parent != blind):
        raise ValueError('반도체 2차년도 블라인드·프로젝트 출자표 합계가 맞지 않는다')
    min_fund = int(row_match[1])
    ratios = re.findall(r'모펀드출자비율○펀드별약정총액의(\d{1,3})%이내', text)
    if len(ratios) != 1 or not 0 < int(ratios[0]) <= 100 or per_fund * 100 > min_fund * int(ratios[0]):
        raise ValueError('반도체 2차년도 펀드별 최소 결성액을 확인할 수 없다')

    def proof(quote):
        return {'source_url': url, 'sha256': sha, 'quote': quote}

    evidence = {'semiconductor_blind_allocation': [proof(plan[0]), proof(_LEADS)]}
    result = {'amount_scope': 'combined', 'commitment_amount_krw': blind * 10**8,
              'commitment_label': f'블라인드 공동 출자 예정 {blind:,}억원', 'manager_count': count,
              'manager_count_label': f'{count}개사', 'fund_target_label': f'펀드별 최소 {min_fund:,}억원',
              'contribution_allocations': {'한국산업은행': bank * 10**8, 'IBK혁신성장펀드1호': ibk * 10**8,
                                           '반도체 생태계 모펀드': parent * 10**8},
              'commitment_detail': f'산업은행 {bank:,}억원 · IBK혁신성장펀드1호 {ibk:,}억원 · 반도체 생태계 모펀드 {parent:,}억원',
              'contribution_note': f'블라인드는 산업은행과 한국성장금융 공동 주관입니다. 프로젝트 {project:,}억원은 한국성장금융이 별도로 모집했습니다.',
              'segments': [{'name': '반도체 소부장', 'amount_krw': blind * 10**8, 'manager_count': count,
                            'per_fund_amount_krw': per_fund * 10**8,
                            'fund_target_total_krw': min_fund * count * 10**8}],
              'extraction_evidence': evidence}
    times = list(_RECEPTION.finditer(text))
    if len(times) == 2 and times[0].groups() == times[1].groups():
        year, month, day = map(int, times[0].group(1, 2, 3))
        try:
            stamp = date(year, month, day)
            start = datetime(year, month, day, *map(int, times[0].group(5, 6)))
            end = datetime(year, month, day, *map(int, times[0].group(7, 8)))
            if (start >= end or notice['date'] >= stamp.isoformat() or str(year) != notice['date'][:4]
                    or '월화수목금토일'[stamp.weekday()] != times[0][4]):
                raise ValueError('접수일 순서 또는 요일 불일치')
        except ValueError:
            pass
        else:
            result.update(deadline=end.isoformat() + '+09:00', deadline_precision='datetime')
            evidence['deadline'] = [proof(times[0][0])]
    if 'deadline' not in result:
        result['deadline_error'] = '반도체 2차년도 블라인드 접수처·개요 시각이 일치하지 않는다'
    purposes = list(_PURPOSE.finditer(text))
    if (len(purposes) == 1 and 0 < int(purposes[0][1]) <= 100
            and '주목적투자대상○투자대상은국내중소·중견기업' in text):
        result['primary_investment'] = {'items': [
            f'국내 중소·중견기업 중 반도체 소재·부품·장비 기업에 약정총액의 {purposes[0][1]}% 이상 투자'],
            'source_url': url}
        evidence['purpose'] = [proof(purposes[0][0])]
    return result


def result_roster(notice, text, program):
    if (not _own(notice) or not _SELECTION.fullmatch(compact(notice['title']))
            or program.get('asset_scope') != 'PE·VC 공동 모집'):
        return []
    lines = [re.sub(r'\s+', '', line) for line in text.splitlines() if line.strip()]
    segment, = program['segments']
    count = segment['manager_count']
    size = segment['fund_target_total_krw'] // (count * 10**8)
    # The first name shares its row with the common lead-institution cell.
    if (tuple(lines[:7]) != _RESULT_HEADER or len(lines) != 13 + count
            or lines[7:11] != ['반도체소부장', f'({count})', f'{size:,}', f'(총{size * count:,})']
            or lines[12:14] != ['산업은행/성장금융', '(공동주관)']):
        return []
    names = [lines[11], *lines[14:]]
    if not all(re.fullmatch(r'[가-힣A-Za-z0-9]{3,48}', name) for name in names) or len(set(names)) != count:
        return []
    return [('반도체 소부장', names)]
