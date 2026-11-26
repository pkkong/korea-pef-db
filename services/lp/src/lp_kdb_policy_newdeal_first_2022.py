"""Replay the bank-led tracks of the 2022 first-round policy New Deal fund."""

from datetime import date
from decimal import Decimal
import hashlib
import json
import re
from urllib.parse import parse_qs

try:
    from . import collect_lp_institution_boards as boards, kgrowth_listing, lp_board_adapters_banks as banks
    from . import lp_kdb_materials_history_import as materials, lp_kgrowth_history_replay as replay, lp_newdeal_history_import as joint
    from .lp_history_notices import POLICY_FIRST_2022_IMPORT_KIND as IMPORT_KIND, POLICY_FIRST_2022_KIND as NOTICE_KIND
    from .lp_kgrowth_history_attachment_queue import file_labels
    from .lp_notice_publication import _refresh
    from .lp_notice_triage import compact
except ImportError:
    import collect_lp_institution_boards as boards
    import kgrowth_listing
    import lp_board_adapters_banks as banks
    import lp_kdb_materials_history_import as materials
    import lp_kgrowth_history_replay as replay
    import lp_newdeal_history_import as joint
    from lp_history_notices import POLICY_FIRST_2022_IMPORT_KIND as IMPORT_KIND, POLICY_FIRST_2022_KIND as NOTICE_KIND
    from lp_kgrowth_history_attachment_queue import file_labels
    from lp_notice_publication import _refresh
    from lp_notice_triage import compact


BUNDLE_KIND = 'lp_kdb_policy_newdeal_first_2022_source_v1'
ARCHIVE_KIND = 'lp_kdb_policy_newdeal_first_2022_original_review_v1'
_BANK = {'institution_id': 'kdb', 'listing_url': banks.KDB_PRESS_BOARD}
_IDENTITY = {'target_institution_id': 'kdb', 'fund': '정책형 뉴딜펀드', 'year': '2022', 'round': '1차',
             'track': '블라인드 중형·대형'}
_PRESS = {
    'recruitment': ('공동 모집 보도자료', '2022년정책형뉴딜펀드1차출자사업공고'),
    'applications': ('접수 결과', '정책형뉴딜펀드접수에50개운용사지원'),
    'screening': ('1차 심사 결과', '정책형뉴딜펀드」서류심사결과발표'),
    'selection': ('선정 결과', '정책형뉴딜펀드」14개운용사최종선정'),
}
_RECRUITMENT = '「정책형뉴딜펀드」2022년1차(기업투자,인프라)위탁운용사선정계획공고'


def validate_retained_notice(notice, checked_at):
    if notice.get('history_import') != NOTICE_KIND or not notice['date'].startswith('2022-'):
        raise ValueError('정책형 뉴딜 2022년 1차 원문의 종류·연도 불일치')
    if notice['institution_id'] == 'kdb':
        if not any(stage == notice['event_type'] and title in compact(notice['title']) for stage, title in _PRESS.values()):
            raise ValueError('정책형 뉴딜 2022년 1차 은행 원문 단계 불일치')
        return boards.validate_notice(notice, checked_at, _BANK, history_listing=True, require_attachment_bytes=False)
    proof = notice['joint_history_proof']
    hashes = notice['attachment_hashes']
    if (notice['institution_id'] != 'kgrowth' or notice.get('source_channel') != 'kgrowth_joint_history'
            or joint.source_key(notice['url']) != ('1', notice['source_id']) or notice['event_type'] != '모집 공고'
            or _RECRUITMENT not in compact(notice['title']) or len(hashes) != 1
            or not set(hashes) <= set(notice['attachments']) or notice.get('attachment_bytes')
            or joint._stamp(notice['checked_at']) > joint._stamp(checked_at)
            or any(not re.fullmatch(r'[a-f0-9]{64}', digest) for digest in hashes.values())):
        raise ValueError('정책형 뉴딜 2022년 1차 공동 모집 원문 불일치')
    replay._detail(notice, proof['detail_base64'], proof['detail_sha256'])
    return notice


def _read_press(archive, checked_at):
    if archive.get('kind') != ARCHIVE_KIND or archive.get('institution_id') != 'kdb' or archive.get('published') is not False:
        raise ValueError('정책형 뉴딜 2022년 1차 보도자료 묶음 형식 불일치')
    term = _IDENTITY['fund']
    listing, = [r for r in archive['press_listings'] if r['board'] == 'press' and r['term'] == term]
    rows, raw_rows, listed_at, proof = materials._press_rows({
        **listing, 'url': listing['requested_url'], 'params': {'_JSON_': parse_qs(listing['request_body'])['_JSON_'][0]},
    }, term, checked_at)
    if set(archive['press_notices']) != set(_PRESS):
        raise ValueError('정책형 뉴딜 2022년 1차 은행 원문 단계 누락')
    notices, texts = {}, {}
    for key, (stage, title) in _PRESS.items():
        row, = [r for r in rows if r['date'].startswith('2022-') and title in compact(r['title'])]
        raw_row, = [r for r in raw_rows if 'kdb:' + r['ITR_NAC_ID_MNG_SNO'] == row['source_id']]
        source = archive['press_notices'][key]
        detail, file = source['detail'], source['attachment']
        markup = materials._raw(detail, row['url'], boards.MAX_BYTES, checked_at).decode()
        doc = banks.parse_detail(markup, row['url'], _BANK)
        opened = joint._stamp(detail['checked_at'])
        attachment, = doc['attachments']
        if (raw_row.get('OPWD_C') != '00' or raw_row.get('OPB_YN') == 'N' or row != source['listing_row']
                or detail['referer'] != banks.KDB_PRESS_BOARD or not listed_at <= opened <= joint._stamp(file['checked_at'])
                or markup.lower().count('</html>') != 1 or (doc['title'], doc['date']) != (row['title'], row['date'])
                or doc != source['document'] or attachment['name'] != file['name'] or not file['name'].endswith('.hwp')
                or file['referer'] != row['url']):
            raise ValueError('정책형 뉴딜 2022년 1차 은행 상세·첨부 원응답 불일치')
        raw = materials._raw(file, attachment['url'], boards.MAX_BYTES, checked_at)
        if not raw.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
            raise ValueError('정책형 뉴딜 2022년 1차 보도자료 HWP 형식 불일치')
        text = boards.attachment_text(raw, attachment['name'])
        if 'kdb산업은행홍보실공보팀' not in compact(text[:160]):
            raise ValueError('정책형 뉴딜 2022년 1차 은행 공식 보도자료 머리말 미확인')
        notice = {**row, **doc, 'history_import': NOTICE_KIND, 'event_type': stage, 'institution_id': 'kdb',
                  'source_channel': 'institution_board', 'checked_at': detail['checked_at'],
                  'discovery_provenance': {'kind': 'institution_board_v1', 'listing': proof, 'detail_html': markup,
                                           'detail_sha256': detail['sha256']},
                  'attachment_hashes': {file['url']: file['sha256']}, 'attachment_texts': {file['url']: text}}
        notice['sha256'] = boards.original_body_hash(notice)
        notices[stage], texts[key] = validate_retained_notice(notice, checked_at), text
    return notices, texts


def _read_recruitment(archive, capture, checked_at):
    evidence = archive['joint_recruitment_listing']
    listing, row = evidence['listing'], evidence['row']
    if (capture.get('kind') != 'lp_kgrowth_enterprise_recruitment_capture_v1' or capture['row'] != row
            or capture['published'] is not False or capture['database_writes'] != 0 or capture['holds']
            or listing['url'] != capture['listing_url'] or capture['listing_sha256'] != evidence['digest']
            or replay._sha(listing['html'].encode()) != evidence['digest']
            or row not in kgrowth_listing.parse_listing(listing['html'], listing['url'])):
        raise ValueError('정책형 뉴딜 2022년 1차 모집 원목록과 상세 지문 불일치')
    detail, file = capture['responses']
    if (detail['referer'] != listing['url'] or file['referer'] != row['url']
            or detail['final_url'] != row['url'] or detail['url'] != row['url'] or file['truncated'] or detail['truncated']):
        raise ValueError('정책형 뉴딜 2022년 1차 공개 상세 연결 불일치')
    raw = joint._observed_bytes(detail, replay.MAX_DETAIL_BYTES, joint._stamp('2022-01-07T00:00:00+09:00'), checked_at)
    doc = replay.read_body(row['source_id'], raw, 'kgrowth')
    if (doc['date'] != row['date'] or doc['title'] != row['title']
            or '기업투자펀드(블라인드중형및대형):한국산업은행홈페이지(공지사항)참고' not in compact(doc['body'])):
        raise ValueError('정책형 뉴딜 2022년 1차 모집 기관·게시일 불일치')
    labels = file_labels({**doc, 'discovery_provenance': {'detail_response_base64': detail['raw_base64'],
                                                         'detail_response_sha256': detail['sha256']}})
    attachments = [(url, name) for url, name in labels.items() if '(기업투자)' in compact(name) and name.endswith('.pdf')]
    expected, = attachments
    if expected != (file['url'], capture['attachment_name']) or file['final_url'] != file['url']:
        raise ValueError('정책형 뉴딜 2022년 1차 기업투자 모집 첨부 불일치')
    pdf = joint._observed_bytes(file, replay.MAX_FILE_BYTES, joint._stamp(detail['checked_at']), checked_at)
    if not re.match(br'%PDF-[12]\.\d[\r\n]', pdf) or not pdf.rstrip().endswith(b'%%EOF'):
        raise ValueError('정책형 뉴딜 2022년 1차 기업투자 PDF 경계 불일치')
    notice = {**joint._source_notice({**doc, 'event_type': '모집 공고', 'attachment_hashes': {file['url']: file['sha256']}},
                                     detail), 'history_import': NOTICE_KIND}
    return validate_retained_notice(notice, checked_at), replay.kgrowth_attachment_text(pdf)


def _one(text, pattern, label):
    matches = list(re.finditer(pattern, text, re.S))
    if len(matches) != 1:
        raise ValueError('정책형 뉴딜 2022년 1차 ' + label + ' 구획 미확인')
    return matches[0]


def _terms(pdf_text, press, issued):
    pdf = compact(pdf_text)
    day = date.fromisoformat(issued)
    if ('정책형뉴딜펀드2022년1차(기업투자)위탁운용사선정계획' not in pdf
            or f'{day.year}년{day.month}월{day.day}일한국산업은행한국성장금융투자운용' not in pdf):
        raise ValueError('정책형 뉴딜 2022년 1차 기업투자 공고 서명·시각 미확인')
    legal = _one(pdf, r'출자대상투자기구(.+?)※\(공통사항\)', '공동 모집 투자기구')[1]
    if not all(s in legal for s in ('기관전용사모집합투자기구', '벤처투자조합')):
        raise ValueError('정책형 뉴딜 2022년 1차 PE·VC 공동 모집 요건 불일치')
    numbers = r'(\d{1,2},\d{3})(\d{2}\.\d)%(\d{1,2},\d{3})([1-9])(\d{1,2},\d{3})'
    plan = _one(pdf, r'블라인드소형[\d,.%]+성장중형' + numbers + '산은대형' + numbers + '산은프로젝트',
                '산은 중형·대형 규모').groups()
    tracks = {}
    for index, name in enumerate(('중형', '대형')):
        amount, percent, per_fund, count, total = plan[index*5:index*5+5]
        a, p, c, t = (int(token.replace(',', '')) for token in (amount, per_fund, count, total))
        brief = compact(press['recruitment'])
        if (t != p*c or a % c or Decimal(percent)*t != 100*a
                or f'{name}{amount}{int(Decimal(percent))}%{count}{per_fund}{total}' not in brief):
            raise ValueError('정책형 뉴딜 PDF와 보도자료 리그별 결성 목표·출자 예정액 불일치')
        tracks[name] = {'amount': a, 'target': t, 'per_fund': p, 'count': c}
    target = _one(pdf, r'접수일시○2022년(\d{1,2})월(\d{1,2})일\([월화수목금토일]\)(\d{2}:\d{2})까지', '마감')
    deadline = date(2022, int(target[1]), int(target[2])).isoformat() + 'T' + target[3] + ':00+09:00'
    common = _one(pdf, r'□소형·중형·대형공통○뉴딜투자공동기준\*상40개분야에약정금액의\[(\d+)%\]이상투자'
                       r'.+?○국내중소‧중견기업\*에약정금액의\[(\d+)%\]이상투자', '공통 투자 의무').groups()
    middle = _one(pdf, r'□소형·중형한정○아래6대핵심뉴딜산업내\(가\)그룹중1개,\(나\)그룹중1개선택\(총2개선택\)'
                       r'○2개선택분야에약정금액의\[(\d+)%\]이상투자○\(나\)그룹선택분야에약정금액의\[(\d+)%\]이상투자', '중형 투자 의무').groups()
    large = _one(pdf, r'□대형우선선정부문한정○탄소중립·녹색산업분야에약정금액의\[(\d+)%\]이상투자', '대형 우선선정')[1]
    return tracks, deadline, (*common, *middle, large)


def _rosters(texts, tracks):
    application = texts['applications'].split('지원 운용사 명 (가나다순)', 1)[1]
    screening = texts['screening'].split('지원 운용사 명(가나다순)', 1)[1]
    final = texts['selection'].split('운용사 명(가나다순)', 1)[1]
    m, l = (tracks[name] for name in ('중형', '대형'))
    mt, lt = f"{m['target']:,}", f"{l['target']:,}"
    mp, lp = f"{m['per_fund']:,}", f"{l['per_fund']:,}"
    a = _one(application, rf"중형\s+\({m['count']}\)\s+{mp}\s+\(총 {mt}\)\s+(\d+)\s+\(총 [\d,]+\)\s+(.+?)\s+"
                          rf"대형\s+\({l['count']}\)\s+{lp}\s+\(총 {lt}\)\s+(\d+)\s+\(총 [\d,]+\)\s+(.+?)\s+\*", '접수 명단')
    s = _one(screening, rf"중형\s+\({m['count']}\)\s+{mp}\s+(.+?)\s+대형\s+\({l['count']}\)\s+{lp}\s+(.+?)\s+\*", '심사 명단')
    f = _one(final, rf"중형\s+{mp}억원\s+(.+?)\s+대형\s+{lp}억원\s+(.+?)\s+\*\s+탄소중립", '선정 명단')
    results = {}
    for number, name in enumerate(tracks, 1):
        applied, screened, selected = [materials._teams(re.sub(r'\*(?=\s|$)', '', block))
                                       for block in (a[2*number], s[number], f[number])]
        plan = tracks[name]
        applied_count = int(a[2*number-1])
        private = plan['target'] - plan['amount']
        final_row = (f"{name}({plan['per_fund']:,}){plan['target']:,}{plan['amount']:,}"
                     f"{private:,}{applied_count}{plan['count']}")
        if (len(applied) != applied_count or len(selected) != plan['count'] or not set(selected) <= set(screened) <= set(applied)
                or f"{name}{plan['amount']:,}{plan['target']:,}{plan['count']}{len(applied)}{len(screened)}산은" not in compact(texts['screening'])
                or final_row not in compact(texts['selection'])):
            raise ValueError('정책형 뉴딜 2022년 1차 리그별 접수·심사·선정 인원 또는 명단 불일치')
        results[name] = applied, screened, selected
    names = [name for _, _, teams in results.values() for team in teams for name in team]
    if len(names) != len(set(names)):
        raise ValueError('정책형 뉴딜 2022년 1차 두 리그의 최종 운용사가 중복됨')
    return results


def _press_dates(press, texts):
    for key, (event, _) in _PRESS.items():
        header = _one(texts[key][:200], r'보도자료\s+\(2022\.\s*(\d{1,2})\.\s*(\d{1,2})\)', '은행 보도자료 날짜')
        if date(2022, int(header[1]), int(header[2])).isoformat() != press[event]['date']:
            raise ValueError('은행 보도자료 게시일·머리말 날짜 불일치')
    screening = _one(compact(texts['screening']),
                     r'한국성장금융\(사장[^)]+\)은(\d{1,2})월(\d{1,2})일\([월화수목금토일]\)『정책형뉴딜펀드』2022년1차',
                     '서류심사 발표일')
    issued = date(2022, int(screening[1]), int(screening[2])).isoformat()
    return {event: issued if key == 'screening' else press[event]['date'] for key, (event, _) in _PRESS.items()}


def project(source, current_programs, checked_at):
    if (not isinstance(source, dict) or set(source) != {'kind', 'institution_id', 'bank_archive', 'recruitment_capture'}
            or source['kind'] != BUNDLE_KIND or source['institution_id'] != 'kdb'):
        raise ValueError('정책형 뉴딜 2022년 1차 가져오기 원본 형식 불일치')
    archive = source['bank_archive']
    original, pdf = _read_recruitment(archive, source['recruitment_capture'], checked_at)
    press, texts = _read_press(archive, checked_at)
    tracks, deadline, objectives = _terms(pdf, texts, original['date'])
    rosters = _rosters(texts, tracks)
    notices = [original, *press.values()]
    announced = _press_dates(press, texts)
    dates = [n['date'] for n in notices]
    original_day, due_day = date.fromisoformat(dates[0]), date.fromisoformat(deadline[:10])
    application_note = compact(texts['applications'])
    if (f'지난{original_day.month}월{original_day.day}일공고한' not in application_note
            or f'운용사제안서접수를{due_day.month}월{due_day.day}일마감한결과' not in application_note
            or not (announced['공동 모집 보도자료'] == dates[1] < dates[0] < deadline[:10]
                    < announced['접수 결과'] == dates[2] < announced['1차 심사 결과'] <= dates[3] < announced['선정 결과'] == dates[4])):
        raise ValueError('정책형 뉴딜 2022년 1차 모집·마감·발표·게시 순서 불일치')

    descriptions = {'모집 공고': '공동 모집 · 산업은행 블라인드 중형·대형', '공동 모집 보도자료': f"{dates[0]} 공동 공고 안내"}
    for index, (event, label) in enumerate((('접수 결과', '접수'), ('1차 심사 결과', '통과'), ('선정 결과', '선정'))):
        detail = ' · '.join(f'{tier} {len(groups[index])}팀 {label}' for tier, groups in rosters.items())
        if announced[event] != press[event]['date']:
            detail += f' · {announced[event]} 발표'
        descriptions[event] = detail
    events = [{'date': n['date'], 'type': n['event_type'], 'title': n['title'], 'url': n['url'],
               'detail': descriptions[n['event_type']]} for n in notices]
    digest = replay._sha(json.dumps(_IDENTITY, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
    program_id, source_key = 'kdb-2022-' + digest[:16], 'joint:' + digest
    keys = {materials.source_key(e['url']) for e in events}
    for old in current_programs:
        title = compact(old['title'])
        same = (old.get('joint_history_identity') == _IDENTITY or any(materials.source_key(e['url']) in keys for e in old['events'])
                or (old['institution_id'] == 'kdb' and all(x in title for x in ('정책형뉴딜펀드', '2022', '1차'))))
        if same and (old['id'], old['institution_id'], old.get('source_program_key')) != (program_id, 'kdb', source_key):
            raise ValueError('정책형 뉴딜 2022년 1차 중형·대형이 기존 사업·원문과 겹침')
    amount, target, count = (sum(t[field] for t in tracks.values()) for field in ('amount', 'target', 'count'))
    won, scope, result = 10**8, 'PE·VC 공동 모집', press['선정 결과']['url']
    gps, gp_tracks = [], {}
    for league, (_, _, teams) in rosters.items():
        for team in teams:
            for name in team:
                gps.append({'name': name, 'id': 'kdb-' + hashlib.sha256(name.encode()).hexdigest()[:16],
                            'asset_scope': scope, 'source_url': result})
                gp_tracks[name] = league if len(team) == 1 else f'{league} · 공동운용'
    core, domestic, middle, secondary, green = objectives
    program = {'id': program_id, 'institution_id': 'kdb', 'institution_name': '한국산업은행',
               'title': '정책형 뉴딜펀드 2022년 1차 · 블라인드 중형·대형', 'asset_scope': scope, 'status': '선정 완료',
               'source_program_key': source_key, 'joint_history_identity': dict(_IDENTITY), 'joint_history_track_keys': list(tracks),
               'business_year': '2022', 'business_round': '1차', 'basic_publication': True,
               'deadline': deadline, 'deadline_precision': 'datetime', 'events': events,
               'commitment_label': f'공동 정책출자 예정 {amount:,}억원', 'fund_target_label': f'{target:,}억원',
               'manager_count_label': f'{count}팀',
               'commitment_detail': '펀드별 결성 목표 ' + ' · '.join(f"{name} {t['per_fund']:,}억원" for name, t in tracks.items()),
               'contribution_note': '산업은행 주관 블라인드 중형·대형 합계',
               'segments': [{'name': name, 'amount_krw': t['amount']*won, 'manager_count': t['count'],
                             'per_fund_amount_krw': t['amount']//t['count']*won} for name, t in tracks.items()],
               'funding_plan': {'basis': 'joint_contributors_recruitment_plan', 'pe_annual_own_commitment_eligible': False,
                                'planned_joint_commitment_total_krw': amount*won, 'planned_formation_target_krw': target*won},
               'selected_gps': gps, 'gp_tracks': gp_tracks, 'manager_list_sources': {'selected_gps': result},
               'primary_investment': {'source_url': original['url'], 'items': [
                   f'뉴딜 40개 분야에 약정금액의 {core}%, 국내 중소·중견기업에 {domestic}% 이상 투자',
                   f'중형은 6대 핵심 뉴딜산업의 두 선택 분야에 약정금액의 {middle}%, 그중 (나) 그룹 분야에 {secondary}% 이상 투자',
                   f'대형 우선선정 부문은 탄소중립·녹색산업에 약정금액의 {green}% 이상 투자']}}
    _refresh(program, [], checked_at)
    return program, notices
