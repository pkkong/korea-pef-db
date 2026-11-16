"""산재보험기금 PE recruitment deadline from the offering's actual schedule.

Observed 2020–2026: the offering calls it "제안서 접수", not "접수마감일".
The schedule supplies its own four-digit announcement year; a date-only row
can be completed by the explicit submission footnote. PEF/VC columns are read
in their labelled order, and the closing time is the end of the reception
window. Other dates (LOC, screening, selection, writing examples) are ignored.

Input must already have passed the institution notice/raw attachment validator.
This pure parser does not authenticate parsed text or fetch any original. On a
conflict it returns deadline_error without a deadline. Callers handling a
changed/cancelled notice must discard a previously stored deadline in that case.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone, timedelta

try:
    from .lp_notice_triage import notice_stage
except ImportError:
    from lp_notice_triage import notice_stage

_KST = timezone(timedelta(hours=9))
_HASH = re.compile(r'[a-f0-9]{64}')
_PE = re.compile(r'(?<![A-Za-z])PEF?(?![A-Za-z])', re.I)
_DATE = (r"(?:[’'‘]?(?P<year>20\d{2}|\d{2})년)?"
         r'(?P<month>\d{1,2})월(?P<day>\d{1,2})일'
         r'(?:\((?P<weekday>[월화수목금토일])\))?')
_RECEPTION = re.compile(_DATE + r'(?:'
    r'(?P<start_hour>\d{1,2}):(?P<start_minute>\d{2})(?:[~∼～]|부터)'
    r'(?P<end_hour>\d{1,2}):(?P<end_minute>\d{2})(?:까지)?' r')?')
_SECTION = re.compile(r'\d+\.향후추진일정(?:\(안\))?(.*?)'
                      r'(?=\d+\.선정결과통지)', re.S)


def _compact(text):
    positions = [i for i, char in enumerate(text) if not char.isspace() and char != '\u200b']
    return ''.join(text[i] for i in positions), positions


def _quote(raw, positions, start, end):
    return raw[positions[start]:positions[end - 1] + 1]


def _day(match, base_year):
    year = match['year']
    year = int(year) if year and len(year) == 4 else 2000 + int(year) if year else base_year
    value = date(year, int(match['month']), int(match['day']))
    if match['weekday'] and '월화수목금토일'[value.weekday()] != match['weekday']:
        raise ValueError('제안서 접수일의 날짜와 요일 불일치')
    return value


def _reception(text, base_year):
    readings = list(_RECEPTION.finditer(text))
    if not readings or ''.join(m[0] for m in readings) != text:
        raise ValueError('제안서 접수 날짜·시각 행 양식 미확인')
    result = []
    for match in readings:
        day = _day(match, base_year)
        if match['start_hour'] is None:
            result.append((day.isoformat(), 'date'))
            continue
        start = datetime.combine(day, datetime.min.time(), _KST).replace(
            hour=int(match['start_hour']), minute=int(match['start_minute']))
        end = datetime.combine(day, datetime.min.time(), _KST).replace(
            hour=int(match['end_hour']), minute=int(match['end_minute']))
        if start >= end:
            raise ValueError('제안서 접수 시작·종료 시각 순서 불일치')
        result.append((end.isoformat(), 'datetime'))
    return result


def _parse_document(raw, title_year, published_day, *, mixed):
    text, positions = _compact(raw)
    declared = re.findall(r'(20\d{2})년도?(?:고용노동부)?산재보험기금대체투자상품', text[:240])
    if set(declared) != {title_year} or '선정공고' not in text[:100]:
        raise ValueError('산재보험기금 공고문 제목·연도 미확인')
    sections = list(_SECTION.finditer(text))
    if len(sections) != 1:
        raise ValueError('산재보험기금 향후 추진일정 절 누락 또는 중복')
    section = sections[0]
    schedule = section[1]
    overview = re.fullmatch(
        r'절차일정(?P<columns>(?:PEF|VC)*)대체투자상품선정공고'
        r'(?P<announcement>.*?)제안서접수\*?(?P<reception>.*?)주간운용사1차심사.*', schedule, re.S)
    if not overview:
        raise ValueError('산재보험기금 접수 행 또는 표 머리글 미확인')
    announced = _RECEPTION.fullmatch(overview['announcement'])
    if not announced or not announced['year'] or len(announced['year']) != 4 or announced['start_hour']:
        raise ValueError('추진일정 표의 공고 연도 미확인')
    announcement_day = _day(announced, int(title_year))
    if str(announcement_day.year) != title_year:
        raise ValueError('공고문과 추진일정 표의 연도 불일치')
    columns = re.findall('PEF|VC', overview['columns'])
    if mixed:
        if len(columns) != 2 or set(columns) != {'PEF', 'VC'}:
            raise ValueError('PEF·VC 접수 표의 독립 열 미확인')
        at = columns.index('PEF')
    else:
        if columns not in ([], ['PEF']):
            raise ValueError('PE 단독 공고의 접수 표 열 불일치')
        at = 0
    rows = _reception(overview['reception'], announcement_day.year)
    if len(rows) != (2 if mixed else 1):
        raise ValueError('접수 표의 날짜 행 수와 PEF·VC 열 수 불일치')
    chosen = rows[at]
    quotes = [_quote(raw, positions, section.start(), section.start(1) + overview.end('reception'))]
    # A common footnote that refers back to the schedule has no new date. An
    # explicit date/time footnote must agree with the independently read PE row.
    footnotes = list(re.finditer(r'\*제안서는(.*?)주간운용사에제출', schedule))
    explicit = []
    for footnote in footnotes:
        if re.search(r'\d{1,2}월\d{1,2}일', footnote[1]):
            if mixed:
                raise ValueError('PEF·VC 별도 표와 공통 접수 각주의 적용 범위 미확인')
            values = _reception(footnote[1], announcement_day.year)
            if len(values) != 1:
                raise ValueError('제안서 제출 각주의 날짜·시각 복수 값')
            explicit.append(values[0])
            quotes.append(_quote(raw, positions, section.start(1) + footnote.start(),
                                 section.start(1) + footnote.end()))
    dates = {value[0][:10] for value in [chosen, *explicit]}
    times = {value[0] for value in [chosen, *explicit] if value[1] == 'datetime'}
    if len(dates) != 1 or len(times) > 1:
        raise ValueError('접수 표와 제출 각주의 날짜·시각 불일치')
    if min(dates) < published_day or min(dates) < announcement_day.isoformat():
        raise ValueError('제안서 접수 마감이 원공고보다 빠름')
    if times:
        return (next(iter(times)), 'datetime'), quotes
    return chosen, quotes


def extract_deadline(n):
    """Return deadline/precision/evidence, {}, or deadline_error without a date.

    Only an already validated 산재보험기금 PE recruitment is eligible. Repeated
    evidence must agree. No source year, PE column, complete row or recognized
    schedule means no inferred deadline.
    """
    title = n.get('title', '')
    if (n.get('institution_id') != 'moel_iaci' or '산재보험기금' not in title
            or not re.search(r'대체투자(?:상품|펀드)', title) or not _PE.search(title)):
        return {}
    if re.search(r'취소|철회|중단', title):
        return {'deadline_error': '취소·철회 공고에는 이전 접수 마감을 유지하지 않음'}
    changed = bool(re.search(r'정정|수정|변경|연장', title))
    if changed:
        return {'deadline_error': '별도 정정·변경 공고의 마감은 기존 일정과 대조 후 반영 필요'}
    if notice_stage(title) != '모집 공고':
        return {}
    years = set(re.findall(r'20\d{2}', title))
    if len(years) != 1:
        return {'deadline_error': '산재보험기금 공고의 사업 연도 미확인'}
    year = next(iter(years))
    mixed = bool(re.search(r'(?<![A-Za-z])VC(?![A-Za-z])', title, re.I))
    observed = {a['url']: a['name'] for a in n.get('attachments', [])}
    readings, evidence, errors = [], [], []
    for url, raw in n.get('attachment_texts', {}).items():
        label = observed.get(url, '')
        if re.search(r'제안요청서|RFP|제출서류|서식|양식|개인정보|동의서', label, re.I):
            continue
        compact, _ = _compact(raw)
        if not re.search(r'향후추진일정', compact):
            continue
        sha = n.get('attachment_hashes', {}).get(url, '')
        if not label or not isinstance(sha, str) or not _HASH.fullmatch(sha):
            errors.append('접수 일정 첨부의 관측 이름 또는 지문 누락')
            continue
        try:
            date.fromisoformat(n['date'])
            reading, quotes = _parse_document(raw, year, n['date'], mixed=mixed)
            readings.append(reading)
            evidence.extend({'source_url': url, 'sha256': sha, 'quote': quote} for quote in quotes)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(str(exc))
    if errors:
        return {'deadline_error': '; '.join(dict.fromkeys(errors))}
    if not readings:
        return {}
    days = {r[0][:10] for r in readings}
    times = {r[0] for r in readings if r[1] == 'datetime'}
    if len(days) != 1 or len(times) > 1:
        return {'deadline_error': '산재보험기금 모집 첨부 사이 접수 마감 불일치'}
    value, precision = (next(iter(times)), 'datetime') if times else (next(iter(days)), 'date')
    return {'deadline': value, 'deadline_precision': precision,
            'extraction_evidence': {'deadline': evidence}}
