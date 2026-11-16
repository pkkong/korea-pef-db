"""Review a hosted joint original without changing its source institution.

The materials/equipment plan has two merged lead-institution cells for three
tracks. The explicit contact table, joint signatures and board text must agree;
cell order alone is never ownership evidence. All amounts are recruitment plans.
This offline reading is separate from KGrowth PE offerings and public programs.
"""
from __future__ import annotations

import itertools
import re
from datetime import date

try:
    from .lp_kgrowth_scaleup_history import compact, evidence
except ImportError:
    from lp_kgrowth_scaleup_history import compact, evidence


_NUMBER = re.compile(r'(?:0|[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d*)')
_FUND = '소재·부품·장비분야투자전용펀드'
_HEADING = _FUND + r'\(제?([1-9]\d*)차\)위탁운용사선정계획공고'
_TABLE = ('지원분야정책출자자지정출자자위탁운용금액최소결성금액'
          r'출자비율(?:주\))?정부재정산업은행')
_LEADS = (r'구분블라인드펀드\(➊일반,➋반도체\)프로젝트펀드'
          '주관기관한국산업은행간접투자금융실한국성장금융투자운용본부')


def _cell_options(text, count):
    """Bounded splits of collapsed numeric cells; commas and dashes are retained."""
    if len(text) > 96:
        raise ValueError('공동 출자표 행 크기 상한 초과')
    values, visits = [], 0

    def visit(at, parts):
        nonlocal visits
        visits += 1
        if visits > 20_000:
            raise ValueError('공동 출자표 숫자 분할 탐색 상한 초과')
        if len(parts) == count:
            if at == len(text):
                values.append(parts)
            return
        if len(values) > 500:
            raise ValueError('공동 출자표 숫자 판독 후보 상한 초과')
        remaining = count - len(parts) - 1
        for end in range(at + 1, min(len(text) - remaining, at + 15) + 1):
            token = text[at:end]
            if token == '-' or _NUMBER.fullmatch(token):
                visit(end, parts + (0 if token == '-' else int(token.replace(',', '')),))

    visit(0, ())
    return values


def _budget_rows(text):
    match = _only(_TABLE + r'블라인드➊일반(.+?)%➋반도체(.+?)%'
                  r'프로젝트(.+?)%합계(.+?)-(?:주\)|선정운용사수)', text,
                  '공동 출자표의 단일 머리말·트랙·합계 미확인')
    rows = []
    for block in match.groups()[:3]:
        options = []
        for row in _cell_options(block, 6):
            government, kdb, designated, amount, formation, ratio = row
            if (amount > 0 and formation > 0 and 0 < ratio <= 100
                    and government + kdb + designated == amount
                    and amount * 100 == formation * ratio):
                options.append(row)
        rows.append(options)
    totals = [r for r in _cell_options(match[4], 5) if sum(r[:3]) == r[3]]
    possibilities = 1
    for options in rows:
        possibilities *= len(options)
    if possibilities > 10_000:
        raise ValueError('공동 출자표 조합 상한 초과')
    solutions = [r for r in itertools.product(*rows)
                 if tuple(sum(row[i] for row in r) for i in range(5)) in totals]
    if len(solutions) != 1:
        raise ValueError('공동 출자표의 재원·금액·결성·비율 합계 단일 판독 불가')
    return solutions[0], match[0]


def _only(pattern, text, reason):
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise ValueError(reason)
    return matches[0]


def _read(n, url, raw, round_no):
    if len(raw) > 256_000:
        raise ValueError('공동 공고 첨부 판독문 크기 상한 초과')
    text = compact(raw)
    heading = _only(_HEADING, text[:350], '공동 공고 첨부의 단일 모집 머리말 미확인')
    if heading[1] != round_no:
        raise ValueError('공동 공고 제목·첨부 회차 충돌')
    columns = _only(r'1\.개요항목블라인드펀드프로젝트펀드❶일반❷반도체', text,
                    '공동 공고 개요의 블라인드·프로젝트·세부 열 머리말 미확인')
    leads = _only(_LEADS, text, '병합 셀과 별개인 트랙별 주관기관 접수처 표 미확인')
    overview_leads = _only(r'주관기관◦한국산업은행◦한국성장금융투자운용\(주\)접수일시',
                          text, '공동 공고 개요의 병합 주관기관과 접수처 표 대조 불가')
    issued = _only(r'(20\d{2})년([1-9]\d?)월([1-9]\d?)일한국산업은행한국성장금융투자운용\(주\)$',
                   text, '공동 공고 발행일·공동명의 미확인')
    issued_day = date(*map(int, issued.group(1, 2, 3)))
    posted = date.fromisoformat(n['date'])
    if issued_day > posted or issued_day.year != posted.year:
        raise ValueError('공동 공고 발행일·게시일 순서 또는 연도 충돌')
    body = compact(n['body'])
    if ('블라인드펀드제출서류및관련양식:한국산업은행홈페이지공지사항' not in body
            or '프로젝트펀드문의:한국성장금융투자운용' not in body):
        raise ValueError('공동 공고 본문의 블라인드·프로젝트 담당기관 대조 불가')
    rows, budget_quote = _budget_rows(text)
    overview = _only(r'선정운용사수◦([1-9]\d?)개사◦([1-9]\d?)개사◦위탁운용금액소진시까지수시접수및선정'
                     r'최소결성금액◦펀드별([1-9]\d{0,2}(?:,\d{3})*|[1-9]\d*)억원',
                     text, '공동 공고의 블라인드 예정 수·펀드별 최소결성 미확인')
    minimum = int(overview[3].replace(',', ''))
    if any(row[4] != int(overview[i + 1]) * minimum for i, row in enumerate(rows[:2])):
        raise ValueError('블라인드 예정 수·펀드별 최소결성과 트랙 결성 합계 불일치')
    caps = _only(r'운용사별배정금액◦([\d,]+)억원이내\(최소결성금액의(\d+)%이내\)'
                 r'◦([\d,]+)억원이내\(최소결성금액의(\d+)%이내\)'
                 r'◦펀드별최대([\d,]+)억원이내\(최소결성금액의(\d+)%이내\)',
                 text, '공동 공고의 예정 배정 상한·비율 미확인')
    cap_values = [int(caps[i].replace(',', '')) for i in (1, 3, 5)]
    if (any(int(caps[i * 2 + 2]) != rows[i][5] for i in range(3))
            or any(cap_values[i] * int(overview[i + 1]) != rows[i][3] for i in range(2))):
        raise ValueError('예정 배정 상한·예정 수·출자비율과 출자표 불일치')
    deadline = _only(r'접수일시(20\d{2})년([1-9]\d?)월([1-9]\d?)일\(([월화수목금토일])\)'
                     r'([01]\d|2[0-3]):([0-5]\d)까지◦수시접수', text,
                     '블라인드 접수 시각·프로젝트 수시접수 구분 미확인')
    day = date(*map(int, deadline.group(1, 2, 3)))
    if (day < posted or day.year != issued_day.year or '월화수목금토일'[day.weekday()] != deadline[4]):
        raise ValueError('공동 공고 접수일의 연도·요일·순서 충돌')
    legal = _only(r'출자대상투자기구❶일반(.+?)❷반도체(.+?)※\(공통사항\)', text,
                  '트랙별 현재 출자대상 투자기구 미확인')
    if (any('경영참여형사모집합투자기구' not in legal[i]
            or '창업‧벤처전문경영참여형사모집합투자기구' not in legal[i] for i in (1, 2))
            or '벤처투자조합' not in legal[1]):
        raise ValueError('공동 공고의 현재 PE 포함·혼합 법형태 미확인')
    strategy = _only(r'주목적투자대상및의무투자비율(.+?)운용사출자금액', text,
                     '블라인드의 현재 투자대상 구간 미확인')
    common = _only(r'소재·부품·장비산업관련기업에결성금액의(100|[1-9]\d?)%이상투자', strategy[1],
                   '소부장 공통 의무투자 비율·분모 미확인')
    domestic = _only(r'❷반도체한정◦반도체소재·부품·장비관련국내중소·중견기업에([\d,]+)억원이상투자',
                     strategy[1], '반도체 국내 중소·중견기업 투자의무 미확인')
    overseas = _only(r'소재·부품·장비산업관련국내기업의해외진출\*지원에([\d,]+)억원이상투자',
                     strategy[1], '반도체 해외진출 투자의무 미확인')
    if '각각해당될경우중복인정' not in strategy[1]:
        raise ValueError('반도체 투자의무 중복 적용 여부 미확인')
    tracks = []
    for i, (label, row) in enumerate(zip(('일반', '반도체', '프로젝트'), rows)):
        government, kdb, designated, amount, formation, ratio = row
        track = {'label': label, 'program_lead_institution_id': 'kdb' if i < 2 else 'kgrowth',
                 'fund_kind': 'blind' if i < 2 else 'project',
                 'planned_commitment_total_krw': amount * 100_000_000,
                 'planned_contributions_krw': {'정부재정': government * 100_000_000,
                                             '한국산업은행': kdb * 100_000_000,
                                             '지정출자자': designated * 100_000_000},
                 'planned_formation_total_krw': formation * 100_000_000,
                 'commitment_to_min_formation_pct': ratio,
                 'planned_per_fund_commitment_max_krw': cap_values[i] * 100_000_000,
                 'selected_managers': [], 'publication_ready': False}
        if i < 2:
            track.update(planned_fund_count=int(overview[i + 1]),
                         min_formation_per_fund_krw=minimum * 100_000_000,
                         deadline=f'{day.isoformat()}T{deadline[5]}:{deadline[6]}:00+09:00',
                         legal_scope='PE 포함 복수 투자기구; 독립 PE 확정 아님',
                         independent_pe_scope_verified=False,
                         legal_forms_quote=legal[i + 1],
                         strategy={'materials_min_investment_pct': int(common[1]),
                                   'obligation_basis': '펀드 결성금액'},
                         holds=['대형 LP PE·VC 모집 규칙의 별도 범위 검토 필요',
                                '해당 주관 트랙의 공식 결과 원문·명단 미확인'])
            if i == 1:
                track['strategy'].update(domestic_sme_semiconductor_min_krw=int(domestic[1].replace(',', '')) * 100_000_000,
                                         domestic_company_overseas_expansion_min_krw=int(overseas[1].replace(',', '')) * 100_000_000,
                                         obligations_may_overlap=True)
            else:
                track['holds'].append('국내 기업만의 투자범위 미확인; 운용사 국내 설립과 구분')
        else:
            track.update(deadline='', reception='수시접수; 위탁운용금액 소진 시까지',
                         holds=['프로젝트 펀드는 PE 블라인드 사업으로 공개하지 않음'])
        tracks.append(track)
    return {'identity': {'fund': _FUND, 'year': str(issued_day.year), 'round': round_no + '차'},
            'source_host_institution_id': n['institution_id'],
            'source_id': n['source_id'], 'source_url': n['url'], 'posted_date': n['date'],
            'issued_date': issued_day.isoformat(),
            'joint_issuer_institution_ids': ['kdb', 'kgrowth'],
            'terms_status': 'original_recruitment_plan',
            'tracks': tracks,
            'planned_commitment_total_krw': sum(row[3] for row in rows) * 100_000_000,
            'amount_basis': '공동 모집의 재원별 계획; 주관기관 단독 출자·실제 GP 배정 아님',
            'publication_ready': False, 'detail_raw_replayed': False, 'attachment_bytes_replayed': False,
            'holds': ['원래 상세 바이트 보완·원본 재생 및 기존 사업 중복 검증 필요',
                      '게시기관 보존; 검토 결과만으로 기관 변경·운영 가져오기 금지'],
            'evidence': {key: evidence(n, raw, fragment, url) for key, fragment in (
                ('budget', budget_quote), ('overview_columns', columns[0]), ('lead', leads[0]),
                ('overview_leads', overview_leads[0]),
                ('issuers', issued[0]),
                ('count_and_minimum', overview[0]), ('allocation_caps', caps[0]),
                ('deadline', deadline[0]), ('legal_scope', legal[0]), ('strategy', strategy[0]))},
            'board_attribution_evidence': {'source_url': n['url'], 'sha256': n['sha256'], 'quote': n['body']}}


def parse_materials_joint_notice(n):
    """Return only the observed joint plan layout, leaving unsupported titles alone.

    The caller validates retained listing/body/hash metadata before calling this.
    It must replay raw originals separately. No institution or input is mutated.
    """
    title = compact(n['title'])
    heading = re.fullmatch(r'【선정공고】[「『]' + _FUND + r'\(제?([1-9]\d*)차\)[」』]'
                           r'위탁운용사선정계획공고', title)
    if not heading:
        return None
    if n.get('institution_id') != 'kgrowth':
        raise ValueError('공동 공고의 원 게시기관 변경 감지')
    readings = []
    for url, raw in n.get('attachment_texts', {}).items():
        if re.search(_HEADING, compact(raw)[:350]):
            readings.append(_read(n, url, raw, heading[1]))
    if len(readings) != 1:
        raise ValueError('공동 공고의 원 모집 첨부가 없거나 여러 개임')
    return readings[0]
