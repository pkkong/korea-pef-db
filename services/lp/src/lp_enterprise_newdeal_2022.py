"""Read KDB's regional track from the joint 2022 enterprise New Deal originals."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal

try:
    from . import kgrowth_listing, lp_kgrowth_history_replay as replay, lp_newdeal_history_import as joint
    from .lp_history_notices import ENTERPRISE_2022_IMPORT_KIND as IMPORT_KIND, ENTERPRISE_2022_KIND as NOTICE_KIND
    from .lp_kgrowth_history_attachment_queue import file_labels
    from .lp_notice_publication import _refresh
    from .lp_notice_triage import compact
except ImportError:
    import kgrowth_listing
    import lp_kgrowth_history_replay as replay
    import lp_newdeal_history_import as joint
    from lp_history_notices import ENTERPRISE_2022_IMPORT_KIND as IMPORT_KIND, ENTERPRISE_2022_KIND as NOTICE_KIND
    from lp_kgrowth_history_attachment_queue import file_labels
    from lp_notice_publication import _refresh
    from lp_notice_triage import compact


BUNDLE_KIND = 'lp_kdb_enterprise_newdeal_2022_source_v1'
JOINT_SOURCE_KIND = 'lp_kgrowth_2022_enterprise_newdeal_originals_v1'
_FUND = '혁신성장뉴딜펀드'
_IDENTITY = {'target_institution_id': 'kdb', 'fund': _FUND, 'year': '2022', 'round': '2차', 'track': '지역혁신'}
_STAGES = {
    '모집 공고': '위탁운용사선정계획공고',
    '질의응답': '출자사업온라인설명회',
    '접수 결과': '위탁운용사접수현황',
    '1차 심사 결과': '1차심사결과',
    '선정 결과': '위탁운용사선정결과',
}
_OWNERS = '○주관기관-기업투자펀드(지역혁신):한국산업은행-기업투자펀드(혁신루키):한국성장금융'


def _compact(value):
    return compact(value.replace('\u200b', ''))


def _stage(title):
    prefix = f'「{_FUND}」2022년2차(기업투자)'
    matched = [stage for stage, suffix in _STAGES.items() if re.fullmatch(r'【[^】]+】' + re.escape(prefix + suffix), _compact(title))]
    if len(matched) != 1:
        raise ValueError('혁신성장뉴딜 2022년 2차 기업투자 공고 단계 미확인')
    return matched[0]


def validate_retained_notice(notice, checked_at):
    """Reparse the official text and retain only verified attachment fingerprints."""
    key = joint.source_key(notice['url'])
    observed = joint._stamp(notice['checked_at'])
    if (notice['history_import'] != NOTICE_KIND or notice['institution_id'] != 'kgrowth'
            or notice.get('source_channel') != 'kgrowth_joint_history'
            or key != ('1', notice['source_id']) or observed > joint._stamp(checked_at)
            or notice['date'][:4] != '2022' or notice['date'] > observed.date().isoformat()
            or notice.get('attachment_bytes') or _stage(notice['title']) != notice['event_type']):
        raise ValueError('혁신성장뉴딜 2022년 2차 원문의 기관·단계·시각 불일치')
    evidence = notice['joint_history_proof']
    hashes = notice['attachment_hashes']
    count = {'모집 공고': 1, '질의응답': 1, '접수 결과': 2, '1차 심사 결과': 1, '선정 결과': 0}[notice['event_type']]
    if (len(hashes) != count or not set(hashes) <= set(notice['attachments'])
            or any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in hashes.values())):
        raise ValueError('혁신성장뉴딜 2022년 2차의 첨부 지문 불일치')
    replay._detail(notice, evidence['detail_base64'], evidence['detail_sha256'])
    return notice


def _read_notices(source, checked_at):
    if (not isinstance(source, dict) or set(source) != {'kind', 'institution_id', 'notices', 'bank_press_searches',
                                                        'supplemental_attachment_hold'}
            or source['kind'] != JOINT_SOURCE_KIND or source['institution_id'] != 'kgrowth'
            or not isinstance(source['notices'], list) or len(source['notices']) != len(_STAGES)):
        raise ValueError('혁신성장뉴딜 2022년 2차의 원본 묶음 형식 불일치')
    notices = {}
    texts = {}
    for entry in source['notices']:
        original, listing, receipt = (entry[key] for key in ('document', 'listing', 'detail'))
        discovery = original['discovery_provenance']['listing']
        if (listing['url'] != discovery['url'] or listing['sha256'] != discovery['sha256']
                or listing['sha256'] != replay._sha(listing['html'].encode())
                or listing['url'] != receipt['listing_url'] or listing['sha256'] != receipt['listing_sha256']):
            raise ValueError('혁신성장뉴딜 2022년 2차 원목록 지문 불일치')
        row, = [r for r in kgrowth_listing.parse_listing(listing['html'], listing['url']) if r['source_id'] == original['source_id']]
        if ((row['title'], row['date']) != (original['title'], original['date'])
                or row['url'] != receipt['url'] or row['url'] != receipt['final_url']
                or original['url'] != receipt['canonical_url'] or receipt['curl_status'] != 0):
            raise ValueError('혁신성장뉴딜 2022년 2차 원목록과 상세 주소·제목·게시일 불일치')
        joint._observed_bytes(receipt, replay.MAX_DETAIL_BYTES, joint._stamp(original['checked_at']), checked_at)
        label = _stage(original['title'])
        if label in notices:
            raise ValueError('혁신성장뉴딜 2022년 2차 단계 중복')
        fields = {**{k: original[k] for k in replay._FIELDS}, 'event_type': label,
                  'attachment_hashes': original['attachment_hashes']}
        notice = {**joint._source_notice(fields, receipt), 'history_import': NOTICE_KIND}
        bound = validate_retained_notice(notice, checked_at)
        files = file_labels({**original, 'discovery_provenance': {
            'detail_response_base64': receipt['raw_base64'], 'detail_response_sha256': receipt['sha256']}})
        if set(files) != set(original['attachments']) or set(entry['attachments']) != set(original['attachment_hashes']):
            raise ValueError('혁신성장뉴딜 2022년 2차 첨부 목록 누락·변경')
        if label in ('접수 결과', '1차 심사 결과', '선정 결과') and _OWNERS not in _compact(notice['body']):
            raise ValueError('혁신성장뉴딜 2022년 2차 후속 공고의 두 주관기관 불일치')
        parsed = {}
        for url, attachment in entry['attachments'].items():
            raw = joint._decode(attachment['raw_base64'], replay.MAX_FILE_BYTES)
            if (attachment['sha256'] != original['attachment_hashes'][url] or len(raw) != attachment['bytes']
                    or replay._sha(raw) != attachment['sha256']):
                raise ValueError('혁신성장뉴딜 2022년 2차 첨부 원바이트 지문 불일치')
            text = replay.kgrowth_attachment_text(raw)
            suffix = files[url].rsplit('.', 1)[-1].lower()
            if suffix not in ('hwp', 'pdf') or suffix in parsed or original['attachment_texts'][url] != text:
                raise ValueError('혁신성장뉴딜 2022년 2차 첨부 원판독과 불일치')
            parsed[suffix] = text
        missing = set(files) - set(entry['attachments'])
        if missing:
            supplement = source['supplemental_attachment_hold']
            if (label != '모집 공고' or missing != {supplement['url']}
                    or files[supplement['url']] != supplement['name']
                    or '뉴딜투자공동기준및혁신성장분야.xlsx' not in _compact(supplement['name'])
                    or receipt['url'] != supplement['referer']
                    or supplement['final_url'] != supplement['url'] or supplement['curl_status'] != 0):
                raise ValueError('혁신성장뉴딜 2022년 2차 누락 첨부의 용도 미확인')
            response = joint._observed_bytes(supplement, replay.MAX_FILE_BYTES,
                                             joint._stamp(receipt['checked_at']), checked_at)
            if not response.startswith(b'<script>alert(') or not response.endswith(b'</script>'):
                raise ValueError('혁신성장뉴딜 2022년 2차 미확보 XLSX 응답 변경')
        notices[label], texts[label] = bound, parsed
    if set(notices) != set(_STAGES):
        raise ValueError('혁신성장뉴딜 2022년 2차 모집·설명회·접수·심사·선정 누락')
    return notices, texts


def _part(text, pattern, where):
    matches = list(re.finditer(pattern, text, re.S))
    if len(matches) != 1:
        raise ValueError('혁신성장뉴딜 2022년 2차 ' + where + ' 구획 미확인')
    return matches[0]


def _amount(token):
    return int(token.replace(',', ''))


def _plan(recruitment, faq):
    pdf, hwp = _compact(recruitment), _compact(faq)
    if not all(phrase in pdf for phrase in (
            '2022년2차(산은·성장금융주관)위탁운용사선정계획',
            '혁신루키,프로젝트주관기관한국산업은행(간접투자금융실)한국성장금융투자운용',
            '2022년9월19일한국산업은행한국성장금융투자운용')):
        raise ValueError('공동 모집 원문에 2022년 2차 발행·주관 명시가 없음')
    legal = _part(pdf, r'2\.블라인드펀드가\.기본항목항목세부내용출자대상투자기구(.+?)※\(공통사항\)', '블라인드 법형태')[1]
    if not all(token in legal for token in ('기관전용사모집합투자기구', '벤처투자조합')) \
            or '기관전용사모집합투자기구*/신기술사업투자조합/벤처투자조합中선택' not in hwp:
        raise ValueError('산업은행 지역혁신의 PE·VC 공동 모집 요건 불일치')

    m = _part(faq, r'지역혁신\s+([\d,]+)\s+(\d+(?:\.\d+)?)%\s+([\d,]+)\s+(\d+)\s+([\d,]+)\s+산은\s+'
              r'혁신루키\s+([\d,]+)\s+(\d+(?:\.\d+)?)%\s+([\d,]+)\s+(\d+)\s+([\d,]+)\s+성장', '리그 금액')
    amount, pct, total, count, per_fund, other_amount, other_pct, other_total, other_count, other_size = m.groups()
    expected = f'지역혁신{amount}{pct}%{per_fund}{count}{total}산은혁신루키{other_amount}{other_pct}%{other_count}{other_total}성장{other_size}'
    if (expected not in pdf or _amount(total) != int(count) * _amount(per_fund)
            or _amount(other_total) != int(other_count) * _amount(other_size)
            or Decimal(pct) * _amount(total) != 100 * _amount(amount)
            or Decimal(other_pct) * _amount(other_total) != 100 * _amount(other_amount)):
        raise ValueError('공동 모집 PDF와 FAQ의 리그별 예정액 불일치')
    timing = _part(pdf, r'접수일시○2022년(\d{1,2})월(\d{1,2})일\([월화수목금토일]\)\d{2}:\d{2}~(\d{2}:\d{2})', '접수 마감')
    deadline = date(2022, int(timing[1]), int(timing[2])).isoformat() + 'T' + timing[3] + ':00+09:00'
    objective = _part(pdf, r'□지역혁신○비수도권소재뉴딜분야\*중소·중견기업에약정총액의\[(\d+)%\]이상투자'
                      r'.+?○비수도권소재혁신성장분야\*중소·중견기업에약정총액의\[(\d+)%\]이상투자'
                      r'.+?주목적투자실적중복인정□혁신루키', '지역혁신 투자 의무')
    if (f'비수도권소재뉴딜분야중소‧중견기업에약정총액의{objective[1]}%이상투자' not in hwp
            or f'비수도권소재혁신성장분야중소‧중견기업에약정총액의{objective[2]}%이상투자' not in hwp):
        raise ValueError('공동 모집 PDF와 FAQ 지역혁신 투자 의무 불일치')
    return {'amount': _amount(amount), 'count': int(count), 'target': _amount(total), 'per_fund': _amount(per_fund),
            'deadline': deadline, 'objective': objective.groups(), 'other_count': int(other_count), 'other_size': _amount(other_size)}


def _teams(text):
    rows = [line.strip().replace('\u200b', '') for line in text.strip().splitlines() if line.strip()]
    if not rows or len(rows) != len(set(rows)) or any(not re.fullmatch(r'[가-힣A-Za-z0-9]+(?:-[가-힣A-Za-z0-9]+)?', row) for row in rows):
        raise ValueError('혁신성장뉴딜 2022년 2차 운용사 명단의 팀 구획 불일치')
    return rows


def _rosters(texts, result, plan):
    app = _part(texts['접수 결과']['hwp'], r'지역혁신\s+\((\d+)\)\s+([\d,]+)\s+(\d+)\s+(.+?)\s+'
                r'혁신루키\s+\((\d+)\)\s+([\d,]+)\s+(\d+)\s+(.+)$', '접수 명단')
    screening = _part(texts['1차 심사 결과']['hwp'], r'지역혁신\s+\((\d+)\)\s+([\d,]+)\s+(.+?)\s+'
                      r'혁신루키\s+\((\d+)\)\s+([\d,]+)\s+(.+)$', '서류심사 명단')
    selection = _part(result, r'지원분야\s+운용사\s+지역혁신\s+(.+?)\s+혁신루키\s+(.+?)\s+○\s*주관기관', '최종 선정 명단')
    expected = [plan['count'], plan['per_fund'], plan['other_count'], plan['other_size']]
    if [_amount(app[i]) for i in (1, 2, 5, 6)] != expected or [_amount(screening[i]) for i in (1, 2, 4, 5)] != expected:
        raise ValueError('접수·심사 표의 리그별 결성목표·선정 예정 수가 모집과 다름')
    regional = [_teams(t) for t in (app[4], screening[3], selection[1])]
    rookie = [_teams(t) for t in (app[8], screening[6], selection[2])]
    for (applied, screened, selected), total, count in ((regional, int(app[3]), plan['count']),
                                                        (rookie, int(app[7]), plan['other_count'])):
        if len(applied) != total or len(selected) != count or not set(selected) <= set(screened) <= set(applied):
            raise ValueError('혁신성장뉴딜 2022년 2차 리그별 접수·심사·선정 명단 불일치')
    pdf = _compact(texts['접수 결과']['pdf'])
    for league, rows, sizes in (('지역혁신', regional, expected[:2]), ('혁신루키', rookie, expected[2:])):
        applied = rows[0]
        if f'{league}({sizes[0]}){sizes[1]}{len(applied)}' + ''.join(applied) not in pdf:
            raise ValueError('혁신성장뉴딜 2022년 2차 접수 PDF·HWP 명단 불일치')
    if set(regional[2]) & set(rookie[2]):
        raise ValueError('혁신성장뉴딜 2022년 2차 최종 명단의 리그 중복')
    return regional


def project(source, current_programs, checked_at):
    if (not isinstance(source, dict) or set(source) != {'kind', 'institution_id', 'joint_source'}
            or source['kind'] != BUNDLE_KIND or source['institution_id'] != 'kdb'):
        raise ValueError('산업은행 2022년 지역혁신 과거 원본 형식 불일치')
    notices, texts = _read_notices(source['joint_source'], checked_at)
    plan = _plan(texts['모집 공고']['pdf'], texts['질의응답']['hwp'])
    applicants, screened, selected = _rosters(texts, notices['선정 결과']['body'], plan)
    dates = [notices[stage]['date'] for stage in _STAGES]
    if (dates != sorted(set(dates)) or not dates[1] < plan['deadline'][:10] < dates[2]
            or '기업투자펀드(블라인드지역혁신):한국산업은행홈페이지(공지사항)참고' not in _compact(notices['모집 공고']['body'])):
        raise ValueError('혁신성장뉴딜 2022년 2차 지역혁신 주관·일정 불일치')
    details = ('공동 모집 · 블라인드 지역혁신', '온라인 설명회·질의응답',
               f'지역혁신 {len(applicants)}팀 접수', f'지역혁신 {len(screened)}팀 통과', f'지역혁신 {len(selected)}팀 선정')
    events = [{'date': notices[stage]['date'], 'type': stage, 'title': notices[stage]['title'], 'url': notices[stage]['url'],
               'detail': detail} for stage, detail in zip(_STAGES, details)]
    digest = replay._sha(json.dumps(_IDENTITY, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
    program_id = 'kdb-2022-' + digest[:16]
    source_key = 'joint:' + digest
    keys = {joint.source_key(event['url']) for event in events}
    for old in current_programs:
        title = _compact(old['title'])
        same = (old.get('joint_history_identity') == _IDENTITY
                or any(joint.source_key(e['url']) in keys for e in old['events'])
                or (old['institution_id'] == 'kdb' and all(word in title for word in (_FUND, '2022', '2차', '지역혁신'))))
        if same and (old['id'], old['institution_id'], old.get('source_program_key')) != (program_id, 'kdb', source_key):
            raise ValueError('혁신성장뉴딜 2022년 2차 지역혁신이 기존 사업·원문과 겹침')
    funding = 10**8
    scope = 'PE·VC 공동 모집'
    result_url = notices['선정 결과']['url']
    newdeal_pct, growth_pct = plan['objective']
    program = {'id': program_id, 'institution_id': 'kdb', 'institution_name': '한국산업은행',
               'title': f'{_FUND} 2022년 2차 · 지역혁신', 'status': '선정 완료', 'asset_scope': scope,
               'source_program_key': source_key, 'joint_history_identity': dict(_IDENTITY), 'joint_history_track_keys': ['지역혁신'],
               'business_year': '2022', 'business_round': '2차', 'basic_publication': True,
               'deadline': plan['deadline'], 'deadline_precision': 'datetime', 'events': events,
               'commitment_label': f"공동 정책출자 예정 {plan['amount']:,}억원",
               'fund_target_label': f"{plan['target']:,}억원",
               'manager_count_label': f"{plan['count']}팀",
               'commitment_detail': f"펀드별 결성 목표 {plan['per_fund']:,}억원",
               'contribution_note': '산업은행 주관 블라인드 지역혁신',
               'funding_plan': {'basis': 'joint_contributors_recruitment_plan', 'pe_annual_own_commitment_eligible': False,
                                'planned_joint_commitment_total_krw': plan['amount'] * funding,
                                'planned_formation_target_krw': plan['target'] * funding},
               'selected_gps': [{'name': name, 'id': 'kdb-' + hashlib.sha256(name.encode()).hexdigest()[:16],
                                 'asset_scope': scope, 'source_url': result_url} for name in selected],
               'gp_tracks': dict.fromkeys(selected, '지역혁신'), 'manager_list_sources': {'selected_gps': result_url},
               'primary_investment': {'source_url': notices['모집 공고']['url'], 'items': [
                   f'비수도권 뉴딜 분야 중소·중견기업에 약정총액의 {newdeal_pct}% 이상 투자',
                   f'비수도권 혁신성장 분야 중소·중견기업에 약정총액의 {growth_pct}% 이상 투자. 두 분야의 투자 요건은 중복 인정']}}
    _refresh(program, [], checked_at)
    return program, list(notices.values())
