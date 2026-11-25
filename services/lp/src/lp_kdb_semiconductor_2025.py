"""Read the two offerings in KDB's shared 2025 semiconductor notice."""

import re
from collections import defaultdict
from datetime import date, datetime

try:
    from .lp_notice_triage import compact
    from .lp_pdf_ocr import validate_proof
except ImportError:
    from lp_notice_triage import compact
    from lp_pdf_ocr import validate_proof


FUND = '반도체생태계펀드'
GENERAL, FISCAL = '일반', '재정'
TRACKS = (GENERAL, FISCAL)
KEYS = {track: f'kdb:2025:{FUND}:{track}' for track in TRACKS}
ROLES = {
    ('일반,재정', '선정계획공고'): 'recruitment',
    ('일반,재정', '제안서접수결과'): 'application',
    ('일반,재정', '서류심사결과'): 'screening',
    ('일반,재정', '선정결과'): 'selection',
    (GENERAL, '선정faq게시'): GENERAL,
    (FISCAL, '선정faq게시'): FISCAL,
}
_TITLE = re.compile(r'[「『]' + FUND + r'\(([^()]+)\)[」』]2025년(?:자펀드)?위탁운용사(.+)')
_DATE = re.compile(r'접수일시(?:[○•])?2025년(\d{1,2})월(\d{1,2})일\(([월화수목금토일])\)(\d\d):(\d\d)~(\d\d):(\d\d)')
_FISCAL_COLUMNS = '재정산은사다리2주1)기은주2)합계(비율)'
_FISCAL_PURPOSE = re.compile(r'목표결성액의(\d{1,3})%초과결성액의(\d{1,3})%.*?ip를보유한기업([\d,]+)억원이상')


def role(notice):
    if (notice['institution_id'] != 'kdb' or notice.get('source_channel') != 'institution_board'
            or not notice['date'].startswith('2025-')):
        return None
    match = _TITLE.fullmatch(compact(notice['title']))
    return ROLES.get(match.groups()) if match else None


def distinct_offerings(left, right):
    return (left['institution_id'] == right['institution_id'] == 'kdb'
            and {left.get('source_program_key'), right.get('source_program_key')} == set(KEYS.values()))


def _attachment(notice, name):
    matches = [(a['url'], notice.get('attachment_texts', {}).get(a['url']),
                notice.get('attachment_hashes', {}).get(a['url'])) for a in notice['attachments']
               if re.fullmatch(name, compact(a['name']))]
    if len(matches) != 1 or not matches[0][1] or not re.fullmatch('[0-9a-f]{64}', matches[0][2] or ''):
        raise ValueError('반도체 2025년 공고의 해당 리그 첨부 원문 미확인')
    return matches[0]


def _proof(url, sha, quote):
    return {'source_url': url, 'sha256': sha, 'quote': quote}


def _deadline(text, notice):
    matches = {match.groups(): match[0] for match in _DATE.finditer(text)}
    if len(matches) != 1:
        raise ValueError('반도체 2025년 리그 접수 시각 미확인')
    (month, day, weekday, start_h, start_m, end_h, end_m), quote = next(iter(matches.items()))
    stamp = date(2025, int(month), int(day))
    start = datetime(2025, stamp.month, stamp.day, int(start_h), int(start_m))
    end = datetime(2025, stamp.month, stamp.day, int(end_h), int(end_m))
    if (notice['date'] >= stamp.isoformat() or start >= end
            or '월화수목금토일'[stamp.weekday()] != weekday):
        raise ValueError('반도체 2025년 리그 접수 순서 또는 요일 불일치')
    return end.isoformat() + '+09:00', quote


def _vehicles(text):
    needed = ('기관전용사모집합투자기구', '경영참여목적에한함', '벤처투자조합')
    if not all(label in text for label in needed):
        raise ValueError('반도체 2025년 리그의 PE·VC 투자기구 미확인')


def _offering(notice, url, sha, text, *, track, amount, target, count, funders, area,
              purpose, allocation_quote, purpose_quote, note):
    if amount != sum(funders.values()) or not 0 < amount <= target or not 0 < count <= 20:
        raise ValueError('반도체 2025년 리그 출자 예정액·결성 규모 표 불일치')
    deadline, deadline_quote = _deadline(text, notice)
    amount_label = f'블라인드 공동 출자 예정 {amount:,}억원' if track == GENERAL else f'공동 출자 예정 {amount:,}억원 내외'
    target_label = f'최소 결성 {target:,}억원' if track == GENERAL else f'결성 목표 {target:,}억원'
    return {
        'amount_scope': 'combined', 'commitment_amount_krw': amount * 10**8,
        'commitment_label': amount_label, 'fund_target_label': target_label,
        'manager_count': count, 'manager_count_label': f'{count}개사',
        'contribution_allocations': {name: share * 10**8 for name, share in funders.items()},
        'commitment_detail': ' · '.join(f'{name} {share:,}억원' for name, share in funders.items()),
        'contribution_note': note, 'deadline': deadline, 'deadline_precision': 'datetime',
        'segments': [{'name': area, 'amount_krw': amount * 10**8, 'manager_count': count,
                      'fund_target_total_krw': target * 10**8}],
        'primary_investment': {'items': purpose, 'source_url': url},
        'extraction_evidence': {'allocation': [_proof(url, sha, allocation_quote)],
                                'deadline': [_proof(url, sha, deadline_quote)],
                                'purpose': [_proof(url, sha, purpose_quote)]},
    }


def fiscal_terms(notice):
    url, raw, sha = _attachment(notice, r'붙임2\.' + FUND + r'\(재정\)2025년위탁운용사선정계획공고\.hwp')
    text = compact(raw)
    _vehicles(text)
    if not text.startswith(f'『{FUND}(재정)』2025년위탁운용사선정계획공고'):
        raise ValueError('반도체 2025년 재정 모집 첨부 제목 불일치')
    lines = [compact(line) for line in raw.splitlines() if line.strip()]
    header = lines.index('기업은행')
    first = list(map(int, lines[header + 1:header + 6]))
    header2 = lines.index('합계(비율)')
    values = lines[header2 + 1:header2 + 9]
    ratio = re.fullmatch(r'(\d+)\(\d{1,3}%\)', values[4]) if len(values) == 8 else None
    headline = re.search(r'위탁운용총액:총([\d,]+)억원내외', text)
    purpose = _FISCAL_PURPOSE.search(text)
    if (len(values) != 8 or values[7] != '산은' or not ratio or not headline or not purpose
            or _FISCAL_COLUMNS not in text or '사다리2기업은행' not in text
            or '기업은행혹은기업은행출자모펀드' not in text
            or first != [*map(int, values[:4]), int(ratio[1])]
            or first[-1] != int(headline[1].replace(',', ''))
            or not all(0 < int(purpose[i]) <= 100 for i in (1, 2))):
        raise ValueError('반도체 2025년 재정 정책·지정 출자표 또는 투자의무 불일치')
    funders = dict(zip(('정부재정', '한국산업은행', '성장사다리펀드2', '기업은행 또는 기업은행 출자 모펀드'), first[:4], strict=True))
    return _offering(notice, url, sha, text, track=FISCAL, amount=first[-1],
                     target=int(values[5].replace(',', '')), count=int(values[6]), funders=funders,
                     area='반도체 소부장·팹리스', purpose=[
                         f'반도체 소부장·팹리스 분야 중소·중견기업에 목표결성액의 {purpose[1]}%, 초과결성액의 {purpose[2]}% 투자',
                         f'같은 분야에서 사업화 관련 특허의 IP 가치평가를 받은 기업에 {purpose[3]}억원 이상 투자'],
                     allocation_quote=_FISCAL_COLUMNS + ''.join(values), purpose_quote=purpose[0],
                     note='산업은행이 주관했습니다.')


def general_terms(notice):
    url, raw, sha = _attachment(notice, r'붙임1\.' + FUND + r'\(일반\)2025년위탁운용사선정계획공고\.pdf')
    native = compact(raw)
    _vehicles(native)
    receipt = notice.get('attachment_ocr', {}).get(url, {})
    helper = receipt.get('helper_sha256') if isinstance(receipt, dict) else None
    if not isinstance(helper, str) or not re.fullmatch(r'[0-9a-f]{64}', helper):
        raise ValueError('반도체 2025년 일반 모집의 OCR 영수증 미확인')
    pages = validate_proof(receipt, sha, receipt.get('input_bytes'), helper)['pages']
    if len(pages) < 2:
        raise ValueError('반도체 2025년 일반 모집의 표 또는 주목적 원문 누락')
    first, second = (compact(page['text']) for page in pages[:2])
    _vehicles(first)
    total = re.search(r'한국산업은행,한국성장금융한국성장금융(?:0|[○•])?총(\d+)억원[\'’*]?[○•]총(\d+)억원\(이월금액포함\)', first)
    targets = re.search(r'선정([1-9]\d?)개', first)
    detail = re.search(r'산업은행(\d+)억원,ibk혁신성장펀드1호(\d+)억원반도체생태계모펀드(\d+)억원', first)
    split = re.search(r'소부장(\d+)-소부장(\d+),팹리스(\d+)', first)
    purpose = re.search(r'영위하는기업에약정총액의\[(\d{1,3})%\]이상투자', second)
    if (not first.startswith(f'『{FUND}(일반)』2025년위탁운용사선정계획공고')
            or '블라인드펀드프로젝트펀드주관기관' not in first
            or '수시접수' not in first or not all((total, targets, detail, split, purpose))
            or '국내중소' not in second or '인드소부장' not in second
            or not 0 < int(purpose[1]) <= 100):
        raise ValueError('반도체 2025년 일반 모집의 블라인드·프로젝트 또는 투자의무 표 미확인')
    blind, project = map(int, total.groups())
    count = int(targets[1])
    row = re.search(rf'선정{count}개{blind}([1-9][\d,]+)제안금액', first)
    blind_sector, project_sector, fabless = map(int, split.groups())
    funders = dict(zip(('한국산업은행', 'IBK혁신성장펀드1호', '반도체 생태계 모펀드'), map(int, detail.groups()), strict=True))
    if (not row or blind != blind_sector or project != project_sector + fabless
            or not re.search(rf'산업은행억원혁신성장펀드호억원{funders["한국산업은행"]},ibk1{funders["IBK혁신성장펀드1호"]},', native)
            or f'반도체생태계모펀드억원{funders["반도체 생태계 모펀드"]}' not in native):
        raise ValueError('반도체 2025년 일반 PDF 기본 추출과 OCR 출자표 불일치')
    return _offering(notice, url, sha, first, track=GENERAL, amount=blind,
                     target=int(row[1].replace(',', '')), count=count, funders=funders,
                     area='반도체 소부장', purpose=[
                         f'국내 중소·중견기업 중 반도체 소재·부품·장비 기업에 약정총액의 {purpose[1]}% 이상 투자'],
                     allocation_quote=' / '.join((total[0], row[0], detail[0])), purpose_quote=purpose[0],
                     note=f'산업은행과 한국성장금융이 공동 주관했습니다. 프로젝트 {project:,}억원은 한국성장금융이 별도로 모집했습니다.')


_STAGE_FILES = {
    'application': '위탁운용사지원현황_게시용',
    'screening': '서류심사결과',
    'selection': '위탁운용사선정결과',
}
_STAGE_HEADERS = {
    'application': ('자펀드위탁운용사접수결과', '지원운용사수'),
    'screening': ('서류심사통과운용사', '지원운용사명'),
    'selection': ('위탁운용사선정결과', '선정운용사명'),
}
_STAGE_ROW = re.compile(r'(재정|일반)\(([1-9]\d?)\)([\d,]+).*')
# The application's applicant count adjoins the fund size in the text layer.
_APPLICATION_ROW = re.compile(r'(재정|일반)\(([1-9]\d?)\)([1-9]\d?(?:,\d{3})|[1-9]\d{2})[1-9]\d?.*')


def _stage_rows(notice, phase):
    name = re.escape(f'{FUND}(일반,재정)2025년{_STAGE_FILES[phase]}.pdf')
    _, text, _ = _attachment(notice, name)
    lines = [compact(line) for line in text.splitlines() if line.strip()]
    header = ''.join(lines[:5])
    if not all(token in header for token in (FUND, *_STAGE_HEADERS[phase], '펀드규모', '2025')):
        raise ValueError('반도체 2025년 공동 후속 첨부의 표 머리말 불일치')
    pattern = _APPLICATION_ROW if phase == 'application' else _STAGE_ROW
    rows = []
    for line in lines:
        if match := pattern.fullmatch(line):
            rows.append((match[1], int(match[2]), int(match[3].replace(',', ''))))
    if len(rows) != 2 or {row[0] for row in rows} != set(TRACKS):
        raise ValueError('반도체 2025년 공동 후속 첨부의 일반·재정 행 미확인')
    return {track: (count, size) for track, count, size in rows}


def result_roster(notice, text, program):
    key = program.get('source_program_key')
    if role(notice) != 'selection' or key not in KEYS.values():
        return []
    track = next(track for track, candidate in KEYS.items() if candidate == key)
    segment, = program['segments']
    expected = (segment['manager_count'], segment['fund_target_total_krw'] // 10**8)
    if expected[0] != 1:
        return []
    size = f'{expected[1]:,}'
    matches = re.findall(rf'(?m)^{track}\(1\){size}([가-힣]{{3,48}})$', '\n'.join(compact(line) for line in text.splitlines()))
    return [(track, matches)] if len(matches) == 1 else []


def offerings(notices):
    by_role = defaultdict(list)
    for notice in notices:
        if phase := role(notice):
            by_role[phase].append(notice)
    if not by_role:
        return {}
    if len(by_role['recruitment']) != 1 or any(len(value) > 1 for value in by_role.values()):
        raise ValueError('반도체 2025년 공동 모집 원공고 또는 후속 게시물 중복·누락')
    original, = by_role['recruitment']
    terms = {GENERAL: general_terms(original), FISCAL: fiscal_terms(original)}
    previous_date = original['date']
    for phase in _STAGE_FILES:
        if not by_role[phase]:
            continue
        notice, = by_role[phase]
        expected = {track: (facts['manager_count'], facts['segments'][0]['fund_target_total_krw'] // 10**8)
                    for track, facts in terms.items()}
        if notice['date'] < previous_date or _stage_rows(notice, phase) != expected:
            raise ValueError('반도체 2025년 공동 후속 공고의 순서·리그별 예정 수·펀드 규모 불일치')
        previous_date = notice['date']
    for track in TRACKS:
        if not by_role[track]:
            continue
        faq, = by_role[track]
        extension = 'pdf' if track == GENERAL else 'hwp'
        _attachment(faq, re.escape(f'{FUND}({track})2025년위탁운용사선정계획faq.{extension}'))
        if not original['date'] < faq['date'] < terms[track]['deadline'][:10]:
            raise ValueError('반도체 2025년 리그 FAQ 게시 순서 불일치')
    common = [original, *(n for phase in _STAGE_FILES for n in by_role[phase])]
    return {KEYS[track]: (f'{FUND}({track}) 2025년' + (' 블라인드' if track == GENERAL else ''),
                          terms[track], [*common, *by_role[track]]) for track in TRACKS}
