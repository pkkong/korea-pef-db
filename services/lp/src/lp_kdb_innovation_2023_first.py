"""Replay the KDB-led medium track of the first 2023 Innovation Growth Fund."""

from datetime import date
import json
import re
from urllib.parse import parse_qs

try:
    from . import collect_kgrowth_history_sessions as sessions, collect_lp_institution_boards as boards
    from . import lp_board_adapters_banks as banks, lp_kdb_materials_history_import as materials
    from . import lp_kgrowth_history_replay as replay
    from .lp_history_notices import INNOVATION_FIRST_2023_IMPORT_KIND as IMPORT_KIND, INNOVATION_FIRST_2023_KIND as NOTICE_KIND
    from .lp_notice_publication import _refresh
    from .lp_notice_triage import compact
except ImportError:
    import collect_kgrowth_history_sessions as sessions
    import collect_lp_institution_boards as boards
    import lp_board_adapters_banks as banks
    import lp_kdb_materials_history_import as materials
    import lp_kgrowth_history_replay as replay
    from lp_history_notices import INNOVATION_FIRST_2023_IMPORT_KIND as IMPORT_KIND, INNOVATION_FIRST_2023_KIND as NOTICE_KIND
    from lp_notice_publication import _refresh
    from lp_notice_triage import compact


BUNDLE_KIND = 'lp_kdb_innovation_first_2023_source_v1'
_BANK = {'institution_id': 'kdb', 'listing_url': banks.KDB_PRESS_BOARD}
_FUND = '혁신성장펀드'
_IDENTITY = {'target_institution_id': 'kdb', 'fund': _FUND, 'year': '2023', 'round': '1차', 'track': '혁신산업 일반 중형'}
_GROWTH = {
    '모집 공고': '2023년1차위탁운용사선정계획공고',
    '접수 결과': '2023년1차출자사업위탁운용사접수현황',
    '1차 심사 결과': '2023년1차위탁운용사선정서류심사결과',
    '선정 결과': '2023년1차위탁운용사선정결과',
}
_PRESS = {
    '공동 모집 보도자료': '혁신성장펀드1차출자사업공고',
    '접수 보도자료': '혁신성장펀드1차출자사업위탁운용사공모에',
    '서류심사 보도자료': '혁신성장펀드」1차출자사업서류심사결과발표',
}


def _one(items, evidence):
    items = list(items)
    if len(items) != 1:
        raise ValueError(f'혁신산업 2023년 1차 {evidence}의 원문 경계 불일치')
    return items[0]


def _growth_stage(notice):
    title = compact(notice['title'])
    if '혁신성장펀드」(혁신산업펀드)' not in title or not notice['date'].startswith('2023-'):
        return None
    return next((stage for stage, fragment in _GROWTH.items() if title.endswith(fragment)), None)


def validate_retained_notice(notice, checked_at):
    if notice.get('history_import') != NOTICE_KIND or not notice['date'].startswith('2023-'):
        raise ValueError('혁신산업 2023년 1차 원문 종류·연도 불일치')
    stage = notice['event_type']
    if notice['institution_id'] == 'kdb':
        if stage not in _PRESS or _PRESS[stage] not in compact(notice['title']):
            raise ValueError('혁신산업 2023년 1차 은행 보도자료 단계 불일치')
        return boards.validate_notice(notice, checked_at, _BANK, history_listing=True, require_attachment_bytes=False)
    hashes = notice['attachment_hashes']
    if (notice['institution_id'] != 'kgrowth' or notice.get('source_channel') != 'kgrowth_joint_history'
            or materials.source_key(notice['url']) != ('1', notice['source_id']) or stage not in _GROWTH
            or stage != _growth_stage(notice)
            or len(hashes) != 1 or not set(hashes) <= set(notice['attachments']) or notice.get('attachment_bytes')
            or replay._stamp(notice['checked_at']) > replay._stamp(checked_at)
            or any(not re.fullmatch(r'[a-f0-9]{64}', value) for value in hashes.values())):
        raise ValueError('혁신산업 2023년 1차 공동 원문 단계·출처·첨부 불일치')
    proof = notice['discovery_provenance']
    replay._detail(notice, proof['detail_response_base64'], proof['detail_response_sha256'])
    return notice


def _read_growth(source, checked_at):
    history, bodies, files = (source[key] for key in ('history', 'body_report', 'file_report'))
    sessions.validate_report(history, bodies, files)
    if files['holds'] or bodies['holds'] or history['holds']:
        raise ValueError('혁신산업 2023년 1차 공동 원문에 미검증 단계가 있음')
    notices, texts = {}, {}
    for stage in _GROWTH:
        doc = _one((n for n in bodies['documents'] if _growth_stage(n) == stage), stage)
        record = _one((r for r in files['records'] if r['source_id'] == doc['source_id']), stage + ' HWP')
        url = record['attachment_url']
        if (record['stage'] != stage or record['extracted']['format'] != 'hwp'
                or record['source_url'] != doc['url'] or record['body_sha256'] != doc['sha256']
                or record['detail_response_sha256'] != doc['discovery_provenance']['detail_response_sha256']
                or replay._stamp(record['checked_at']) > replay._stamp(checked_at)):
            raise ValueError('혁신산업 2023년 1차 공동 원문과 첨부 증빙 불일치')
        text = texts[stage] = record['extracted']['text']
        notice = {**doc, 'attachment_collection_status': 'complete', 'history_import': NOTICE_KIND,
                  'source_channel': 'kgrowth_joint_history', 'event_type': stage,
                  'attachment_hashes': {url: record['attachment_sha256']}, 'attachment_texts': {url: text}}
        notices[stage] = validate_retained_notice(notice, checked_at)
    return notices, texts


def _read_bank(source, checked_at):
    listing = source['listing']
    if (listing['board'], listing['term'], listing['http_method'], listing['referer']) != (
            'press', _FUND, 'POST', banks.KDB_PRESS_BOARD):
        raise ValueError('혁신산업 2023년 1차 산업은행 보도자료 검색 출처 불일치')
    rows, raw_rows, listed_at, proof = materials._press_rows({
        **listing, 'url': listing['requested_url'], 'params': {'_JSON_': parse_qs(listing['request_body'])['_JSON_'][0]},
    }, _FUND, checked_at)
    notices, texts = {}, {}
    for stage, fragment in _PRESS.items():
        row = _one((r for r in rows if r['date'].startswith('2023-') and fragment in compact(r['title'])), stage)
        identifier = row['source_id'].split(':')[1]
        raw_row = _one((r for r in raw_rows if r['ITR_NAC_ID_MNG_SNO'] == identifier), stage)
        detail, file = source['documents'][identifier]
        markup = materials._raw(detail, row['url'], boards.MAX_BYTES, checked_at).decode()
        doc = banks.parse_detail(markup, row['url'], _BANK)
        attachment, = doc['attachments']
        if (raw_row.get('OPWD_C') != '00' or raw_row.get('OPB_YN') == 'N'
                or markup.lower().count('</html>') != 1 or detail['referer'] != banks.KDB_PRESS_BOARD
                or not listed_at <= replay._stamp(detail['checked_at']) <= replay._stamp(file['checked_at'])
                or (doc['title'], doc['date']) != (row['title'], row['date'])
                or not attachment['name'].endswith('.hwp') or file['referer'] != row['url']):
            raise ValueError('혁신산업 2023년 1차 은행 상세·첨부 원문 불일치')
        url = attachment['url']
        raw = materials._raw(file, url, boards.MAX_BYTES, checked_at)
        text = texts[stage] = boards.attachment_text(raw, attachment['name'])
        header = _one(re.finditer(r'보도자료\s+\(2023\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\)', text[:220]), stage + ' 날짜')
        if (not raw.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')
                or 'kdb산업은행홍보실공보팀' not in compact(text[:200])
                or date(2023, int(header[1]), int(header[2])).isoformat() != row['date']):
            raise ValueError('혁신산업 2023년 1차 산업은행 공식 HWP 머리말 불일치')
        notice = {**doc, **row, 'institution_id': 'kdb', 'source_channel': 'institution_board',
                  'history_import': NOTICE_KIND, 'event_type': stage, 'checked_at': detail['checked_at'],
                  'discovery_provenance': {'kind': 'institution_board_v1', 'listing': proof,
                                           'detail_html': markup, 'detail_sha256': detail['sha256']},
                  'attachment_hashes': {url: file['sha256']}, 'attachment_texts': {url: text}}
        notice['sha256'] = boards.original_body_hash(notice)
        notices[stage] = validate_retained_notice(notice, checked_at)
    return notices, texts


def _terms(text, press):
    body = compact(text)
    if ('출자계획(기업투자블라인드펀드)' not in body
            or '기관전용사모집합투자기구*' not in body or '경영참여목적에한함' not in body
            or not all(term in body for term in ('창업·벤처전문사모집합투자기구', '벤처투자조합'))):
        raise ValueError('혁신산업 2023년 1차 기업투자 블라인드 PE·VC 원문 미확인')
    fields = _one(re.finditer(r'혁신산업일반\s+중형\s+([\d,]+)\s+([\d,]+)\s+(\d+\.\d)%\s+'
                             r'([\d,]+)\s+(\d+)\s+([\d,]+)\s+산은\s+소형', text), '산업은행 중형 출자표')
    government, own, per_fund, count, target = (int(fields[i].replace(',', '')) for i in (1, 2, 4, 5, 6))
    joint = government + own
    plan_cells = f'혁신산업일반중형산은{government:,}{own:,}{joint:,}{fields[3]}{count}{per_fund:,}{target:,}'
    if (not all((government, own, per_fund, count)) or target != count * per_fund
            or joint * 1000 != target * int(fields[3].replace('.', '')) or plan_cells not in compact(press)):
        raise ValueError('혁신산업 2023년 1차 중형 출자표의 합계 또는 은행 원문 불일치')
    due = _one(re.finditer(r'접수일시○2023년(\d+)월(\d+)일\([월화수목금토일]\)\d{2}:\d{2}~(\d{2}:\d{2})', body), '접수 마감')
    day = date(2023, int(due[1]), int(due[2]))
    objective = _one(re.finditer(r'혁신산업일반\(소형/중형공통\)○①~③을모두충족'
                                 r'①혁신성장공동기준품목\(별첨\)해당기업에약정총액의\[(\d+)%\]이상투자'
                                 r'②‘新성장4\.0’또는‘글로벌초격차산업및미래유망산업’분야\(별첨\)에\[정책출자금액\]이상투자'
                                 r'③중소ㆍ중견기업에약정총액의\[(\d+)%\]이상투자', body), '주목적 투자 조건')
    return government, own, per_fund, count, target, day, due[3], objective.groups()


def _medium_rosters(texts, bank_texts, count, per_fund, target):
    header = rf'혁신산업 일반/중형\s*\({count}\)\s+{per_fund:,}\s+\(총 {target:,}\)\s+'
    names = r'([가-힣A-Za-z0-9/\s]+?)'
    next_track = r'(?=\s+성장지원 일반/대형|\s*\Z)'
    application = re.compile(header + r'(\d+)\s+' + names + next_track)
    screening = re.compile(header + names + next_track)
    applied = _one(application.finditer(texts['접수 결과']), '중형 접수 명단')
    bank_applied = _one(application.finditer(bank_texts['접수 보도자료']), '산업은행 중형 접수 명단')
    screened = materials._teams(_one(screening.finditer(texts['1차 심사 결과']), '중형 심사 명단')[1])
    bank_screened = _one(screening.finditer(bank_texts['서류심사 보도자료']), '산업은행 중형 심사 명단')
    final = _one(re.finditer(header + r'([^\n]+)\s+산은\s+' + names + next_track, texts['선정 결과']),
                 '산업은행 주관 중형 선정 명단')
    selected = materials._teams(final[1] + '\n' + final[2])
    teams = materials._teams(applied[2])
    if (int(applied[1]) != len(teams) or int(bank_applied[1]) != len(teams)
            or materials._teams(bank_applied[2]) != teams
            or materials._teams(bank_screened[1]) != screened
            or len(selected) != count or not set(selected) <= set(screened) <= set(teams)):
        raise ValueError('혁신산업 2023년 1차 중형 접수·심사·선정 명단 교차 검증 실패')
    return teams, screened, selected


def project(source, current_programs, checked_at):
    if (not isinstance(source, dict) or set(source) != {'kind', 'institution_id', 'bank', 'growth'}
            or source['kind'] != BUNDLE_KIND or source['institution_id'] != 'kdb'):
        raise ValueError('혁신산업 2023년 1차 가져오기 원문 묶음 형식 불일치')
    growth, texts = _read_growth(source['growth'], checked_at)
    bank, bank_texts = _read_bank(source['bank'], checked_at)
    government, own, per_fund, count, target, due, time, (scope_pct, company_pct) = _terms(
        texts['모집 공고'], bank_texts['공동 모집 보도자료'])
    applied, screened, selected = _medium_rosters(texts, bank_texts, count, per_fund, target)
    recruitment, applications, screening, selection = (n['date'] for n in growth.values())
    opened, reported, reviewed = (n['date'] for n in bank.values())
    screened_day = date.fromisoformat(screening)
    if (not opened == recruitment < due.isoformat() < applications == reported < screening <= reviewed < selection
            or f'제안서접수를{due.month}월{due.day}일' not in compact(bank_texts['접수 보도자료'])
            or f'{screened_day.month}월{screened_day.day}일' not in compact(bank_texts['서류심사 보도자료'])):
        raise ValueError('혁신산업 2023년 1차 모집·마감·결과 관측일 불일치')

    scope, result = 'PE·VC 공동 모집', growth['선정 결과']['url']
    joint, won = government + own, 10**8
    digest = replay._sha(json.dumps(_IDENTITY, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
    identifier = 'kdb-2023-' + digest[:16]
    notices = [*growth.values(), *bank.values()]
    notes = {'모집 공고': '공동 모집 · 산업은행 주관 혁신산업 일반 중형',
             '접수 결과': f'중형 {len(applied)}팀 접수', '1차 심사 결과': f'중형 {len(screened)}팀 통과',
             '선정 결과': f'중형 {len(selected)}팀 선정', '공동 모집 보도자료': '중형 정책출자·결성 목표 확인',
             '접수 보도자료': f'중형 {len(applied)}팀 접수 확인', '서류심사 보도자료': f'{screening} 중형 {len(screened)}팀 통과 발표'}
    events = [{'date': n['date'], 'type': n['event_type'], 'title': n['title'], 'url': n['url'],
               'detail': notes[n['event_type']]} for n in notices]
    keys = {materials.source_key(n['url']) for n in notices}
    for old in current_programs:
        title = compact(old['title'])
        same = (old.get('joint_history_identity') == _IDENTITY
                or any(materials.source_key(e['url']) in keys for e in old['events'])
                or (old['institution_id'] == 'kdb' and all(x in title for x in ('혁신산업', '2023', '1차', '중형'))))
        if same and (old['id'], old['institution_id'], old.get('source_program_key')) != (identifier, 'kdb', 'joint:' + digest):
            raise ValueError('혁신산업 2023년 1차 중형이 기존 사업·원문과 겹침')
    gps = [{'name': name, 'id': 'kdb-' + replay._sha(name.encode())[:16], 'asset_scope': scope, 'source_url': result}
           for team in selected for name in team]
    program = {'id': identifier, 'institution_id': 'kdb', 'institution_name': '한국산업은행',
               'title': '혁신성장펀드 2023년 1차 · 혁신산업 일반 중형', 'asset_scope': scope, 'status': '선정 완료',
               'source_program_key': 'joint:' + digest, 'joint_history_identity': dict(_IDENTITY),
               'joint_history_track_keys': ['혁신산업 일반 중형'], 'business_year': '2023', 'business_round': '1차',
               'basic_publication': True, 'deadline': f'{due.isoformat()}T{time}:00+09:00', 'deadline_precision': 'datetime',
               'events': events, 'selected_gps': gps, 'gp_tracks': {g['name']: '중형' for g in gps},
               'manager_list_sources': {'selected_gps': result},
               'commitment_label': f'공동 정책출자 예정 {joint:,}억원', 'fund_target_label': f'{target:,}억원',
               'manager_count_label': f'{count}팀',
               'commitment_detail': f'산업은행 {own:,}억원 · 정부 재정 {government:,}억원 · 펀드별 결성 목표 {per_fund:,}억원',
               'contribution_note': '산업은행 주관 혁신산업 일반 중형',
               'funding_plan': {'basis': 'joint_contributors_recruitment_plan', 'pe_annual_own_commitment_eligible': False,
                                'planned_joint_commitment_total_krw': joint * won, 'lead_institution_own_planned_krw': own * won,
                                'planned_formation_target_krw': target * won},
               'primary_investment': {'source_url': growth['모집 공고']['url'], 'items': [
                   f'혁신성장 공동기준 품목 해당 기업에 약정총액의 {scope_pct}% 이상 투자',
                   '신성장 4.0 또는 글로벌 초격차산업 및 미래유망산업에 정책출자금액 이상 투자',
                   f'중소·중견기업에 약정총액의 {company_pct}% 이상 투자']}}
    _refresh(program, [], checked_at)
    return program, notices
