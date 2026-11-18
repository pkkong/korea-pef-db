"""Offline review of a hosted joint regular New Deal enterprise recruitment.

The caller validates retained notice metadata first. This reads one observed
enterprise attachment layout; detail/attachment byte replay, program deduplication
and publication remain separate. Policy capital is not the lead LP's own money.
"""
from __future__ import annotations

import hashlib
import io
import itertools
import re
from datetime import date
from decimal import Decimal
from typing import Literal, NotRequired, TypedDict
from urllib.parse import parse_qs, urlsplit

try:
    from .kgrowth_listing import source_id
    from .lp_kgrowth_scaleup_history import compact, evidence
except ImportError:
    from kgrowth_listing import source_id
    from lp_kgrowth_scaleup_history import compact, evidence


_FUND = '정책형뉴딜펀드'
_NUMBER = r'(?:0|[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d*)'
_INT = re.compile(_NUMBER)
_RATIO = re.compile(r'(?:[1-9]\d?|100)(?:\.\d{1,2})?')
_HEADER = ('지원분야정책출자자펀드별제안규모펀드별주1)최대출자액'
           '조성목표주관기관주2)출자총액비율주1)')


class JointTrackReview(TypedDict):
    key: str
    label: str
    program_lead_institution_id: str
    fund_kind: Literal['blind', 'project']
    planned_commitment_total_krw: int
    planned_formation_total_krw: int
    planned_per_fund_commitment_max_krw: int | None
    planned_contributions_krw: None
    lead_institution_own_capital_krw: None
    policy_capital_ratio_pct: float
    proposal_size_min_krw: int
    proposal_size_max_krw: int | None
    proposal_size_min_inclusive: bool
    planned_fund_count: None
    pe_only_current_legal_form_observed: bool
    legal_scope: str
    deadline: str
    selected_managers: list
    publication_ready: bool
    holds: list[str]
    strategy: NotRequired[dict[str, int | str]]
    reception: NotRequired[str]


class NewdealJointReview(TypedDict):
    kind: Literal['lp_kgrowth_newdeal_joint_history_review_v1']
    identity: dict[str, str]
    source_host_institution_id: str
    source_id: str
    source_url: str
    posted_date: str
    issued_date: str
    joint_issuer_institution_ids: list[str]
    terms_status: Literal['original_recruitment_plan']
    tracks: list[JointTrackReview]
    planned_commitment_total_krw: int
    planned_formation_total_krw: int
    named_policy_capital_participants: list[str]
    planned_contributions_krw: None
    amount_basis: str
    publication_ready: bool
    detail_raw_replayed: bool
    attachment_bytes_replayed: bool
    holds: list[str]
    evidence: dict[str, dict]
    board_attribution_evidence: dict
    other_retained_attachment_urls: NotRequired[list[str]]
    missing_advertised_attachment_urls: NotRequired[list[str]]


def _only(pattern, text, reason):
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise ValueError(reason)
    return matches[0]


def _integer(value):
    if not _INT.fullmatch(value):
        raise ValueError('공동 모집 숫자 표기 미확인')
    return int(value.replace(',', ''))


def _cells(text, count):
    """Bounded numeric-cell splits; never invent a delimiter or remove commas."""
    if len(text) > 72:
        raise ValueError('공동 모집 숫자 행 크기 초과')
    values, visits = [], 0

    def visit(at, parts):
        nonlocal visits
        visits += 1
        if visits > 20_000 or len(values) > 500:
            raise ValueError('공동 모집 숫자 분할 탐색 상한 초과')
        if len(parts) == count:
            if at == len(text):
                values.append(parts)
            return
        remaining = count - len(parts) - 1
        for end in range(at + 1, min(len(text) - remaining, at + 15) + 1):
            token = text[at:end]
            if _INT.fullmatch(token):
                visit(end, parts + (_integer(token),))

    visit(0, ())
    return values


def _amount_ratio(text):
    if len(text) > 40:
        raise ValueError('정책자금·비율 셀 크기 상한 초과')
    result = []
    for i in range(1, len(text)):
        amount, ratio = text[:i], text[i:]
        if _INT.fullmatch(amount) and _RATIO.fullmatch(ratio):
            value = Decimal(ratio)
            if _integer(amount) > 0 and 0 < value <= 100:
                result.append((_integer(amount), value))
    return result


def _budget(text, cutoff):
    hit = _only(re.escape(_HEADER) + r'블라인드➊투자제안형(.+?)%(.+?)성장'
                r'(.+?)%(.+?)산은➋뉴딜성장형(.+?)%(.+?)산은'
                r'프로젝트➌투자제안형(.+?)%(.+?)성장합계(.+?)주1\)', text,
                '기업투자 표의 단일 머리말·네 트랙·합계 미확인')
    options = []
    for i in range(4):
        prefix, tail = hit[i * 2 + 1], hit[i * 2 + 2]
        if i == 0:
            size = re.fullmatch('(' + _NUMBER + r')~(.+)', tail)
        else:
            size = re.fullmatch('(' + _NUMBER + r')(초과|이상)(.+)', tail)
        if not size:
            raise ValueError('트랙별 제안규모의 범위·이하/초과/이상 미확인')
        lower = _integer(size[1])
        candidates = []
        if i == 0:
            for upper, cap, formation in _cells(size[2], 3):
                candidates.append((lower, upper, cap, formation))
        elif i == 3:
            if not size[3].startswith('-'):
                raise ValueError('프로젝트 최대출자액 미명시 셀 미확인')
            for (formation,) in _cells(size[3][1:], 1):
                candidates.append((lower, None, None, formation))
        else:
            for cap, formation in _cells(size[3], 2):
                candidates.append((lower, None, cap, formation))
        row_options = []
        for amount, ratio in _amount_ratio(prefix):
            for lower, upper, cap, formation in candidates:
                if (lower <= 0 or formation <= 0 or amount * 100 != formation * ratio
                        or cap is not None and not 0 < cap <= amount
                        or cap is not None and cap * 100 < lower * ratio
                        or i == 0 and not lower <= upper == cutoff
                        or i == 0 and cap * 100 > upper * ratio
                        or i == 1 and (size[2] != '초과' or lower != cutoff)
                        or i > 1 and size[2] != '이상'):
                    continue
                row_options.append((amount, ratio, lower, upper, cap, formation))
        options.append(row_options)
    stated = _only('정책출자자위탁운용금액:(' + _NUMBER + r')억원내외', text,
                   '기업투자 정책자금 총액 문장 미확인')
    possibilities = 1
    for rows in options:
        possibilities *= len(rows)
    if possibilities > 10_000:
        raise ValueError('기업투자 표 조합 탐색 상한 초과')
    totals = _cells(hit[9], 2)
    solutions = [rows for rows in itertools.product(*options)
                 if sum(row[0] for row in rows) == _integer(stated[1])
                 and (sum(row[0] for row in rows), sum(row[5] for row in rows)) in totals]
    if len(solutions) != 1:
        raise ValueError('정책자금·조성목표·비율 합계의 단일 판독 불가')
    return solutions[0], hit[0], stated[0]


def _dates(n, text, business_year):
    issued = _only(r'(20\d{2})년(\d{1,2})월(\d{1,2})일'
                   r'한국산업은행한국성장금융투자운용(?:\(주\))?$', text,
                   '공동명의·발행일 미확인')
    day = date(*map(int, issued.group(1, 2, 3)))
    posted = date.fromisoformat(n['date'])
    if day > posted or not day.year <= int(business_year) <= day.year + 1:
        raise ValueError('공동 공고의 사업연도·발행일·게시일 순서 충돌')
    clock = r'([01]?\d|2[0-3]):([0-5]\d)'
    head = _only(r'접수일시(20\d{2})년(\d{1,2})월(\d{1,2})일\(([월화수목금토일])\)'
                 + clock + '까지', text, '블라인드 접수일·마감 시각 미확인')
    schedule = _only(r'(20\d{2})\.(\d{1,2})\.(\d{1,2})\(([월화수목금토일])\)제안서접수'
                     + clock + '~' + clock, text, '블라인드 선정일정의 접수 행 미확인')
    deadline_day = date(*map(int, head.group(1, 2, 3)))
    scheduled_day = date(*map(int, schedule.group(1, 2, 3)))
    end = tuple(map(int, head.group(5, 6)))
    scheduled_end = tuple(map(int, schedule.group(7, 8)))
    start = tuple(map(int, schedule.group(5, 6)))
    if (deadline_day != scheduled_day or deadline_day < posted
            or str(deadline_day.year) != business_year or end != scheduled_end or start >= end
            or '월화수목금토일'[deadline_day.weekday()] != head[4]
            or '월화수목금토일'[scheduled_day.weekday()] != schedule[4]):
        raise ValueError('접수일·요일·연도·마감 시각 충돌')
    return (day.isoformat(), f'{deadline_day.isoformat()}T{end[0]:02d}:{end[1]:02d}:00+09:00',
            {'issuers_and_date': issued[0], 'deadline': head[0], 'deadline_schedule': schedule[0]})


def _read(n, url, raw, year) -> NewdealJointReview:
    if not isinstance(raw, str) or len(raw) > 256_000:
        raise ValueError('기업투자 모집 판독문 형식·크기 상한 초과')
    text = compact(raw)
    header = _only(r'[『「]' + _FUND + r'[』」](20\d{2})년정시\(기업투자\)선정계획공고'
                   + _FUND + r'(20\d{2})년정시\(기업투자\)위탁운용사선정계획을아래와같이공고합니다\.',
                   text[:350], '단일 기업투자 모집 머리말·소개 문장 미확인')
    if header[1] != year or header[2] != year:
        raise ValueError('제목·기업투자 첨부의 사업연도 충돌')
    leads = _only(r'구분➊투자제안형\((' + _NUMBER + r')억원초과\),➋뉴딜성장형'
                  r'➊투자제안형\((' + _NUMBER + r')억원이하\),➌투자제안형\(프로젝트\)'
                  '주관기관한국산업은행간접투자금융실한국성장금융투자운용본부', text,
                  '주관기관·지원규모 접수처 표 미확인')
    if _integer(leads[1]) != _integer(leads[2]) or _integer(leads[1]) <= 0:
        raise ValueError('기관별 이하/초과 규모 경계 충돌')
    cutoff = _integer(leads[1])
    body = compact(n['body'])
    if _FUND + year + '년정시위탁운용사선정계획' not in re.sub(r'[「」『』]', '', body):
        raise ValueError('게시글 본문과 모집 사업·연도·정시 회차 불일치')
    referral = _only(r'한국산업은행주관사업인투자제안형\(제안규모(' + _NUMBER
                     + r')억원초과블라인드펀드\),뉴딜성장형은한국산업은행홈페이지\(공지사항\)참고',
                     body, '게시글의 KDB 주관 트랙 안내 미확인')
    if _integer(referral[1]) != cutoff:
        raise ValueError('게시글과 접수처 표의 지원규모 경계 충돌')
    alias = _only(r'주2\)‘산은’은한국산업은행,‘성장’은한국성장금융투자운용\(주\)을의미',
                  text, '주관기관 약칭과 실제 기관 대조 불가')
    rows, budget_quote, stated_quote = _budget(text, cutoff)
    issued_day, deadline, date_quotes = _dates(n, text, year)
    blind = _only(r'2\.블라인드펀드(.+?)3\.프로젝트펀드', text,
                  '현재 블라인드와 프로젝트 모집 구간 분리 불가')
    legal = _only(r'출자대상투자기구❶투자제안형(.+?)❷뉴딜성장형(.+?)※\(공통사항\)',
                  blind[1], '현재 지원분야별 투자기구 구간 미확인')
    growth_legal = '○‘자본시장과금융투자업에관한법률’에의한경영참여형사모집합투자기구'
    if (legal[2] != growth_legal or any(v not in legal[1] for v in
            ['경영참여형사모집합투자기구', '신기술사업투자조합', '벤처투자조합'])):
        raise ValueError('뉴딜성장형의 현재 PEF 단독·투자제안형 혼합 법형태 대조 불가')
    strategy = _only(r'주목적투자비율➊투자제안형,➋뉴딜성장형공통(.+?)➊투자제안형한정',
                     blind[1], '블라인드 현재 공통 투자대상 구간 미확인')
    theme = _only(r'뉴딜투자가이드라인\*상([1-9]\d{0,2})개분야에목표결성금액의\[(100|[1-9]\d?)%\]이상투자',
                  strategy[1], '뉴딜 의무투자 비율·분모 미확인')
    domestic = _only(r'국내중소‧중견기업\*에목표결성금액의\[(100|[1-9]\d?)%\]이상투자',
                     strategy[1], '현재 국내 중소·중견기업 투자의무 미확인')
    project = _only(r'3\.프로젝트펀드\(➌투자제안형분야\)(.+?)4\.선정우대항목', text,
                    '별도 프로젝트 모집 구간 미확인')
    reception = _only(r'접수일시○수시접수심사결과발표○수시선정', project[1],
                      '프로젝트 수시접수와 블라인드 마감 구분 미확인')
    funders = _only(r'정책출자자\(([^()]+)\)앞배분되는금액', text,
                    '정책자금 참여자 명시 구간 미확인')
    keys = ['blind_proposal_at_most_boundary', 'blind_proposal_above_boundary',
            'blind_newdeal_growth', 'project_proposal']
    labels = ['투자제안형(규모 경계 이하)', '투자제안형(규모 경계 초과)', '뉴딜성장형', '투자제안형(프로젝트)']
    tracks: list[JointTrackReview] = []
    for i, row in enumerate(rows):
        amount, ratio, lower, upper, cap, formation = row
        track: JointTrackReview = {
            'key': keys[i], 'label': labels[i], 'program_lead_institution_id': 'kdb' if i in (1, 2) else 'kgrowth',
            'fund_kind': 'project' if i == 3 else 'blind',
            'planned_commitment_total_krw': amount * 100_000_000,
            'planned_formation_total_krw': formation * 100_000_000,
            'planned_per_fund_commitment_max_krw': cap * 100_000_000 if cap is not None else None,
            'planned_contributions_krw': None, 'lead_institution_own_capital_krw': None,
            'policy_capital_ratio_pct': float(ratio), 'proposal_size_min_krw': lower * 100_000_000,
            'proposal_size_max_krw': upper * 100_000_000 if upper is not None else None,
            'proposal_size_min_inclusive': i != 1, 'planned_fund_count': None,
            'pe_only_current_legal_form_observed': i == 2,
            'legal_scope': '현재 경영참여형 사모기구만 명시' if i == 2 else '현재 PE/VC 혼합 허용' if i < 2 else '별도 프로젝트 모집',
            'deadline': deadline if i < 3 else '', 'selected_managers': [], 'publication_ready': False,
            'holds': ['원본 상세 재생·기존 사업 중복 및 별도 공개 판정 필요']}
        if i < 3:
            track['strategy'] = {'newdeal_min_investment_pct': int(theme[2]),
                                 'newdeal_field_count': int(theme[1]),
                                 'domestic_sme_min_investment_pct': int(domestic[1]),
                                 'obligation_basis': '목표결성금액'}
            if i != 2:
                track['holds'].append('투자제안형의 혼합 허용 금액·이름을 PE 전용값으로 올리지 않음')
            if i in (1, 2):
                track['holds'].append('해당 주관 트랙의 공식 결과 원문·명단 별도 확인 필요')
        else:
            track['reception'] = '수시접수·수시선정'
            track['holds'].append('프로젝트는 독립 PE 블라인드로 공개하지 않음')
        tracks.append(track)
    quotes = {'heading': header[0], 'lead_scope': leads[0], 'lead_aliases': alias[0],
              'budget': budget_quote, 'stated_policy_total': stated_quote,
              'current_legal_forms': legal[0], 'current_strategy': strategy[0],
              'project_reception': reception[0], 'policy_capital_participants': funders[0], **date_quotes}
    return {'kind': 'lp_kgrowth_newdeal_joint_history_review_v1',
            'identity': {'fund': _FUND, 'year': year, 'round': '정시'},
            'source_host_institution_id': n['institution_id'], 'source_id': n['source_id'], 'source_url': n['url'],
            'posted_date': n['date'], 'issued_date': issued_day,
            'joint_issuer_institution_ids': ['kdb', 'kgrowth'],
            'terms_status': 'original_recruitment_plan', 'tracks': tracks,
            'planned_commitment_total_krw': sum(row[0] for row in rows) * 100_000_000,
            'planned_formation_total_krw': sum(row[5] for row in rows) * 100_000_000,
            'named_policy_capital_participants': funders[1].split(','),
            'planned_contributions_krw': None,
            'amount_basis': '기업투자 정책자금 모집 계획; 주관기관 자체 재원·GP 실제 배정액 아님',
            'publication_ready': False, 'detail_raw_replayed': False, 'attachment_bytes_replayed': False,
            'holds': ['게시기관·공동명의·주관기관을 보존; 자동 기관 재귀속·발행 승인 아님',
                      '국민참여·인프라 첨부는 기업투자 PE 금액·명단에 합치지 않음',
                      '모집 판독만 수행하며 GP 명단 판독·이름 상수·공고ID 분기 없음'],
            'evidence': {key: evidence(n, raw, fragment, url) for key, fragment in quotes.items()},
            'board_attribution_evidence': {'source_url': n['url'], 'sha256': n['sha256'],
                                           'quote': n['body']}}


def _result_growth_roster(summary, appendix, recruitment):
    identity = recruitment['identity']
    tracks = [t for t in recruitment['tracks'] if t.get('key') == 'blind_newdeal_growth']
    year = identity.get('year', '')
    if (identity.get('fund') != _FUND or identity.get('round') != '정시' or not re.fullmatch(r'20\d{2}', year)
            or len(tracks) != 1
            or tracks[0].get('program_lead_institution_id') != 'kdb' or tracks[0].get('fund_kind') != 'blind'
            or tracks[0].get('pe_only_current_legal_form_observed') is not True):
        raise ValueError('뉴딜성장형 모집의 산은 주관·독립 PE 범위 미확인')
    heading = _FUND + year + '년정시위탁운용사선정'
    compact_summary = compact(summary)
    if (heading + '결과' not in compact_summary or heading + '명단' not in compact(appendix)
            or not all(issuer in compact_summary for issuer in ('한국산업은행', '한국성장금융'))):
        raise ValueError('정책형 뉴딜펀드 공동 결과의 모집 연도·회차·기관 불일치')
    count = _only(r'지원분야별로는투자제안형(\d+)개사,뉴딜성장형(\d+)개사,국민참여형(\d+)개사,인프라(\d+)개사등총(\d+)개사',
                  compact_summary, '보도자료 결과의 리그별 선정 수 미확인')
    proposal_count, growth_count, citizen_count, infra_count, total_count = map(int, count.groups())
    if (not all(0 < n <= 50 for n in (proposal_count, growth_count, citizen_count, infra_count))
            or sum((proposal_count, growth_count, citizen_count, infra_count)) != total_count):
        raise ValueError('뉴딜 공동 결과의 리그별 수와 전체 선정 수 불일치')
    table = _only(r'(?ms)^[ \t]*지원분야[ \t]{2,}운용사[ \t]*\(가나다순\)[ \t]*\n(.+?)^[ \t]*-[ \t]*\d+[ \t]*-[ \t]*$',
                  appendix, '뉴딜 공동 결과 별첨 명단 표 미확인')[1]
    rows, labels = [], {}
    for line in table.splitlines():
        if not line.strip():
            continue
        label = re.fullmatch(r'[ \t]{0,7}(1200억원|이하|초과|투자|제안형|뉴딜성장형|국민참여형|인프라)(?:[ \t]{2,}(.+?))?[ \t]*', line)
        if label:
            labels.setdefault(label[1], []).append(len(rows))
            name = label[2]
        else:
            name = line.strip() if re.match(r'^ {8,}\S', line) else None
            if name is None:
                raise ValueError('뉴딜 공동 결과 별첨 이름 열의 위치 불일치')
        if name:
            rows.append(name)
    growth_end = proposal_count + growth_count
    citizen_end = growth_end + citizen_count
    for label, low, high in (('투자', 0, proposal_count), ('제안형', 0, proposal_count),
                             ('뉴딜성장형', proposal_count, growth_end),
                             ('국민참여형', growth_end, citizen_end), ('인프라', citizen_end, total_count)):
        positions = labels.get(label, [])
        if len(positions) != 1 or not low <= positions[0] < high:
            raise ValueError('뉴딜 공동 결과 별첨 구획과 리그별 선정 수 불일치')
    names = rows[proposal_count:growth_end]
    if (len(rows) != total_count or len(set(names)) != growth_count
            or any(not re.fullmatch(r'[가-힣A-Za-z0-9]+(?:[ \t][가-힣A-Za-z0-9]+)*', n) for n in names)):
        raise ValueError('뉴딜성장형 운용사 이름·중복·선정 수 불일치')
    return names, total_count


def read_newdeal_growth_result_pdf(raw, recruitment):
    """Read the separate PE league of the retained official selection PDF."""
    from pypdf import PdfReader

    if not isinstance(raw, bytes) or not 0 < len(raw) <= 12 * 1024 * 1024 or not raw.startswith(b'%PDF-'):
        raise ValueError('뉴딜 선정 결과 PDF 크기·원문 형식 불일치')
    pdf = PdfReader(io.BytesIO(raw), strict=True)
    if pdf.is_encrypted or len(pdf.pages) != 3:
        raise ValueError('뉴딜 선정 결과 PDF의 관측 양식·페이지 구성 불일치')
    summary, appendix = (pdf.pages[i].extract_text(extraction_mode='layout') for i in (0, 2))
    names, total_count = _result_growth_roster(summary, appendix, recruitment)
    return {'kind': 'lp_kgrowth_newdeal_growth_result_review_v1', 'identity': recruitment['identity'],
            'source_sha256': hashlib.sha256(raw).hexdigest(), 'track_key': 'blind_newdeal_growth',
            'program_lead_institution_id': 'kdb', 'selected_managers': names,
            'joint_total_selected_count': total_count, 'publication_ready': False}


def parse_newdeal_joint_notice(n) -> NewdealJointReview | None:
    """Return the retained joint enterprise layout, never public program rows."""
    title = compact(n['title'])
    found = re.fullmatch(r'【선정공고】[「『]' + _FUND + r'[」』](20\d{2})년정시위탁운용사선정계획공고', title)
    if not found:
        return None
    if n.get('institution_id') != 'kgrowth':
        raise ValueError('공동 모집의 원 게시기관 변경 감지')
    ident = source_id(n['url'])
    if ident != n.get('source_id') or n.get('source_channel') != 'institution_board':
        raise ValueError('공동 모집 원문 식별자·게시판 경로 불일치')
    files, hashes, texts = n.get('attachments', []), n.get('attachment_hashes', {}), n.get('attachment_texts', {})
    if (not set(texts) <= set(hashes) <= set(files) or len(texts) > 12
            or any(not re.fullmatch(r'[a-f0-9]{64}', sha) for sha in hashes.values())):
        raise ValueError('공동 모집의 보관 첨부·지문·판독문 연결 불일치')
    for url in files:
        parsed_url = urlsplit(url)
        if (parsed_url.scheme != 'https' or parsed_url.hostname != 'www.kgrowth.or.kr'
                or parsed_url.path != '/down_file.asp' or parsed_url.username or parsed_url.password
                or parsed_url.fragment or parsed_url.port not in {None, 443}
                or parse_qs(parsed_url.query).get('idx') != [ident]):
            raise ValueError('공동 모집 첨부의 원 기관·원문 식별자 불일치')
    readings = []
    for url, raw in texts.items():
        if isinstance(raw, str) and re.search(r'[『「]' + _FUND + r'[』」]20\d{2}년정시\(기업투자\)선정계획공고', compact(raw)[:350]):
            readings.append(_read(n, url, raw, found[1]))
    if len(readings) != 1:
        raise ValueError('기업투자 원 모집 첨부가 없거나 여러 개임')
    result = readings[0]
    result['other_retained_attachment_urls'] = sorted(set(texts) - {result['evidence']['heading']['attachment_url']})
    result['missing_advertised_attachment_urls'] = sorted(set(files) - set(texts))
    return result
