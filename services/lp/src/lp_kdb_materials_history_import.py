"""Replay the signed 2021 materials fund plan and its KDB press-board lifecycle."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date
from urllib.parse import parse_qs, urlsplit

try:
    from . import collect_lp_institution_boards as boards
    from . import lp_board_adapters_banks as banks
    from . import lp_kgrowth_history_replay as replay
    from . import lp_newdeal_history_import as joint_source
    from .lp_history_notices import KDB_MATERIALS_IMPORT_KIND as IMPORT_KIND, KDB_PRESS_KIND
    from .lp_joint_history_projection import review_joint_candidates
    from .lp_notice_publication import _refresh
    from .lp_notice_triage import compact
except ImportError:
    import collect_lp_institution_boards as boards
    import lp_board_adapters_banks as banks
    import lp_kgrowth_history_replay as replay
    import lp_newdeal_history_import as joint_source
    from lp_history_notices import KDB_MATERIALS_IMPORT_KIND as IMPORT_KIND, KDB_PRESS_KIND
    from lp_joint_history_projection import review_joint_candidates
    from lp_notice_publication import _refresh
    from lp_notice_triage import compact


BUNDLE_KIND = 'lp_kdb_materials_joint_history_source_v1'
_CONFIG = {'institution_id': 'kdb', 'listing_url': banks.KDB_PRESS_BOARD, 'search_terms': ['소재·부품·장비'], 'pages': 1}
_IDENTITY = {'target_institution_id': 'kdb', 'fund': '소재·부품·장비분야투자전용펀드',
             'year': '2021', 'round': '2차'}
_STAGES = {
    '공동 모집 보도자료': '투자전용펀드(2차)출자사업공고',
    '접수 결과': '블라인드펀드(2차)위탁운용사선정에',
    '1차 심사 결과': '블라인드펀드(2차)」서류심사결과발표',
    '선정 결과': '블라인드펀드(2차)」운용사최종선정',
}


def source_key(url):
    """Recognize a press-board notice independent of search fields."""
    parsed = urlsplit(url)
    if parsed.scheme == 'https' and parsed.netloc == 'www.kdb.co.kr' and parsed.path == '/BOUBUF02N00.act':
        values = parse_qs(parsed.query).get('_PARM_DATA', [])
        if len(values) == 1:
            try:
                payload = json.loads(values[0])
            except ValueError:
                return None
            if (isinstance(payload, dict) and payload.get('ITR_BLB_ID') == 'SMR024'
                    and payload.get('FIRST_MENU_ID') == 'CHBIPR25N00'
                    and re.fullmatch(r'[1-9]\d*', str(payload.get('ITR_NAC_ID_MNG_SNO', '')))):
                return 'kdb_press', str(payload['ITR_NAC_ID_MNG_SNO'])
    return joint_source.source_key(url)


def validate_retained_press(notice, checked_at):
    if notice['history_import'] != KDB_PRESS_KIND:
        raise ValueError('산업은행 보도자료 원문 종류 불일치')
    event_type = notice['event_type']
    if event_type not in _STAGES or _STAGES[event_type] not in compact(notice['title']):
        raise ValueError('산업은행 소부장 보도자료의 단계 불일치')
    return boards.validate_notice(notice, checked_at, _CONFIG, history_listing=True, require_attachment_bytes=False)


def _raw(receipt, url, limit, checked_at):
    if receipt.get('url') != url or receipt.get('final_url') != url or receipt.get('curl_status') != 0:
        raise ValueError('산업은행 보도자료 원응답 주소 불일치')
    return joint_source._observed_bytes(receipt, limit, joint_source._stamp('2021-01-01T00:00:00+00:00'), checked_at)


def _press_notices(source, checked_at):
    listing = source['listing']
    canonical = banks.listing_requests(_CONFIG)[0]['url']
    endpoint, query = canonical.split('?', 1)
    requested = parse_qs(query)['_JSON_'][0]
    if json.loads(requested) != json.loads(listing['params']['_JSON_']):
        raise ValueError('산업은행 보도자료 게시판·검색어·페이지 불일치')
    listing_body = _raw(listing, endpoint, boards.MAX_BYTES, checked_at).decode('utf-8')
    listed_at = joint_source._stamp(listing['checked_at'])
    rows = banks.parse_listing(listing_body, canonical, _CONFIG)
    listing_data = json.loads(listing_body)
    header = listing_data['HEADER_STD_WEB']
    if int(header['REQ_PAGE_NO']) != 1 or int(header['TOT_PAG_CNT']) != 1 \
            or int(header['TOT_PAG_ROW_CNT']) != len(rows):
        raise ValueError('산업은행 소부장 보도자료 원목록의 전체 행 미확인')
    if len(source['press_notices']) != len(_STAGES):
        raise ValueError('산업은행 소부장 모집·접수·심사·선정 보도자료 수 불일치')
    notices = {}
    for label, title_fragment in _STAGES.items():
        row, = [r for r in rows if r['date'][:4] == _IDENTITY['year'] and title_fragment in compact(r['title'])]
        identifier = row['source_id'].split(':')[1]
        target, = [n for n in listing_data['STDLIST_REC'] if n['ITR_NAC_ID_MNG_SNO'] == identifier]
        if target.get('OPWD_C') != '00' or target.get('OPB_YN') == 'N':
            raise ValueError('산업은행 소부장 보도자료 공개 읽기 경계 미확인')
        detail_receipt, file_receipt = source['press_notices'][identifier]
        markup = _raw(detail_receipt, row['url'], boards.MAX_BYTES, checked_at).decode('utf-8')
        detail_at = joint_source._stamp(detail_receipt['checked_at'])
        if markup.lower().count('</html>') != 1 or detail_receipt['referer'] != banks.KDB_PRESS_BOARD \
                or detail_at < listed_at:
            raise ValueError('산업은행 보도자료 상세의 완결성·관측 순서 불일치')
        detail = banks.parse_detail(markup, row['url'], _CONFIG)
        attachment, = detail['attachments']
        if (detail['title'] != row['title'] or detail['date'] != row['date']
                or attachment['name'] != file_receipt['name'] or not attachment['name'].endswith('.hwp')
                or file_receipt['referer'] != row['url'] or joint_source._stamp(file_receipt['checked_at']) < detail_at):
            raise ValueError('산업은행 보도자료 제목·게시일·HWP 첨부 불일치')
        url = attachment['url']
        raw = _raw(file_receipt, url, boards.MAX_BYTES, checked_at)
        if not raw.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
            raise ValueError('산업은행 보도자료 HWP 본파일 미확인')
        text = boards.attachment_text(raw, attachment['name'])
        if not text or 'kdb산업은행홍보실공보팀' not in compact(text[:160]):
            raise ValueError('산업은행 원문 HWP 보도자료 머리말 미확인')
        n = {**row, **detail, 'institution_id': 'kdb', 'source_channel': 'institution_board',
             'history_import': KDB_PRESS_KIND, 'event_type': label, 'checked_at': detail_receipt['checked_at'],
             'discovery_provenance': {'kind': 'institution_board_v1',
                 'listing': {'url': canonical, 'html': listing_body, 'sha256': listing['sha256']},
                 'detail_html': markup, 'detail_sha256': detail_receipt['sha256']},
             'attachment_texts': {url: text}, 'attachment_hashes': {url: file_receipt['sha256']}}
        n['sha256'] = boards.original_body_hash(n)
        notices[label] = (validate_retained_press(n, checked_at), text)
    return notices


def _part(text, pattern, label):
    matches = list(re.finditer(pattern, text, re.S))
    if len(matches) != 1:
        raise ValueError('소부장 보도자료의 ' + label + ' 구획 미확인')
    return matches[0]


def _teams(text):
    results = []
    for line in text.strip().splitlines():
        row = line.strip()
        if not row:
            continue
        names = [name.strip() for name in re.split(r'[,/&]', row)]
        if not 1 <= len(names) <= 2 or any(not re.fullmatch(r'[가-힣A-Za-z0-9]{2,35}', name) for name in names):
            raise ValueError('소부장 운용사 이름·공동운용 팀 경계 미확인')
        results.append(tuple(names))
    all_names = [name for team in results for name in team]
    if not all_names or len(set(all_names)) != len(all_names):
        raise ValueError('소부장 운용사 명단 누락·중복')
    return results


def _teams_by_league(text):
    """Reconcile actual applicant, shortlist and final team boundaries."""
    _, section = text['접수 결과'].split('선정 접수 현황', 1)
    m = _part(section, r'일반\s+소부장\s+(\d+)개사\s+\(\s*\d+개사\s*\)\s+(.+?)'
              r'반도체\s+소부장\s+(\d+)개사\s+\(\s*\d+개사\s*\)\s+(.+)\s*$', '접수 명단')
    applied = {'일반': _teams(m[2]), '반도체': _teams(m[4])}
    if [len(t) for t in applied.values()] != [int(m[1]), int(m[3])]:
        raise ValueError('소부장 접수 표의 팀 수 불일치')
    submitted = {frozenset(team): league for league, teams in applied.items() for team in teams}
    if len(submitted) != sum(map(len, applied.values())):
        raise ValueError('소부장 접수 표의 리그 간 공동운용 팀 중복')

    m = _part(text['1차 심사 결과'], r'운용사\s*\(가나다순\)\s+(.+?)\s+□\s*산은은', '서류심사 명단')
    screened_teams = _teams(re.sub(r'&[ \t]*\n[ \t]*', '&', m[1]))
    screened = {'일반': [], '반도체': []}
    for team in screened_teams:
        league = submitted.get(frozenset(team))
        if not league:
            raise ValueError('소부장 서류심사 팀이 접수 명단에 없음')
        screened[league].append(team)

    _, roster = text['선정 결과'].split('최종 선정 운용사 명단', 1)
    m = _part(roster, r'지원분야\s+운용사\s*\(가나다순\)\s+일반\s+소부장\s+(.+?)\s+'
              r'반도체\s+소부장\s+(.+)\s*$', '최종 선정 명단')
    selected = {'일반': _teams(m[1]), '반도체': _teams(m[2])}
    for league, teams in selected.items():
        advanced = {frozenset(team) for team in screened[league]}
        if any(frozenset(team) not in advanced for team in teams):
            raise ValueError('소부장 최종 선정 팀·리그가 서류심사 명단과 다름')
    return applied, screened, selected


def _announcement_date(text):
    stamp = _part(text[:200], r'보도자료\s+\((2021\.\d{2}\.\d{2})\)', '발표일')[1]
    return date.fromisoformat(stamp.replace('.', '-')).isoformat()


def _verify_recruitment_press(verified, tracks, text):
    """Cross-check the bank's own release against the signed joint offering."""
    issued = date.fromisoformat(verified['issued_date'])
    body = compact(text)
    if not re.search(rf'{issued.month}월{issued.day}일\([월화수목금토일]\)에공고함', body):
        raise ValueError('소부장 보도자료가 공동 모집 원발행일을 확인하지 못함')
    table = body.partition('위탁운용사선정계획*')[2].partition('합계')[0]
    for name, track in tracks.items():
        columns = track['planned_contributions_krw']
        amounts = [columns[key] // 10**8 for key in ('정부재정', '한국산업은행', '지정출자자')]
        contributions = ''.join(f'{amount:,}' if amount else '-' for amount in amounts)
        allocated = track['planned_commitment_total_krw'] // 10**8
        formation = track['planned_formation_total_krw'] // 10**8
        if f"{name}{contributions}{allocated:,}{formation:,}{track['commitment_to_min_formation_pct']}%" not in table:
            raise ValueError('산업은행 보도자료와 공동 모집의 블라인드 리그별 금액 불일치')


def _recruitment(source, checked_at):
    raw = joint_source._decode(source['bundle'], replay.MAX_INPUT_BYTES)
    bundle = json.loads(raw)
    capture = json.loads(joint_source._decode(source['capture'], replay.MAX_INPUT_BYTES))

    def attachment(sha):
        value = source['attachments'].get(sha)
        if not value:
            raise ValueError('소부장 공식 모집 첨부 지문 미보존')
        return joint_source._decode(value, replay.MAX_FILE_BYTES)

    review = review_joint_candidates(bundle, capture, attachment, checked_at=checked_at)
    verified, = [c for c in review['candidates'] if c['identity'] == _IDENTITY and c['source_full_replay_complete']]
    original = verified['source_document']
    receipt, = [r for r in capture['responses'] if r['url'] == original['url']]
    notice = joint_source._source_notice({**{k: original[k] for k in replay._FIELDS}, 'event_type': '모집 공고',
                                        'attachment_hashes': original['attachment_hashes']}, receipt)
    return verified, joint_source.validate_retained_notice(notice, checked_at), replay._sha(raw)


def _check_matches(program, current_programs, sources):
    keys = {source_key(n['url']) for n in sources}
    for old in current_programs:
        existing_keys = {source_key(event['url']) for event in old['events']}
        title = re.sub(r'[·‧]', '', compact(old['title']))
        same_fund = ('소재부품장비' in title or '소부장' in title) and '펀드' in title and '2차' in title
        overlaps = (old.get('joint_history_identity') == _IDENTITY or bool(keys & existing_keys)
                    or (same_fund and old['institution_id'] == 'kdb'
                        and (old.get('business_year') == '2021' or any(e['date'][:4] == '2021' for e in old['events']))))
        if overlaps and (old['id'], old['institution_id'], old.get('source_program_key')) != (
                program['id'], program['institution_id'], program['source_program_key']):
            raise ValueError('산업은행 소부장 2차가 기존 사업·원문 주소와 겹침')


def project(source, current_programs, checked_at):
    if (not isinstance(source, dict) or set(source) != {'kind', 'institution_id', 'recruitment', 'listing', 'press_notices'}
            or source.get('kind') != BUNDLE_KIND or source.get('institution_id') != 'kdb'):
        raise ValueError('산업은행 소부장 과거 원본 묶음 형식 불일치')
    verified, original, recruit_sha = _recruitment(source['recruitment'], checked_at)
    press = _press_notices(source, checked_at)
    dates = {kind: _announcement_date(text) for kind, (_, text) in press.items()}
    texts = {kind: text for kind, (_, text) in press.items()}
    applied, screened, selected = _teams_by_league(texts)
    program = copy.deepcopy(verified['program'])
    program.pop('publication_ready')
    tracks = {row['label']: row for row in verified['tracks']}
    if set(tracks) != {'일반', '반도체'} or program['asset_scope'] != 'PE·VC 공동 모집':
        raise ValueError('산업은행 소부장 블라인드의 일반·반도체 범위 불일치')
    _verify_recruitment_press(verified, tracks, texts['공동 모집 보도자료'])
    deadline = date.fromisoformat(program['deadline'][:10])
    final = compact(texts['선정 결과'])
    applications = sum(map(len, applied.values()))
    shortlist = sum(map(len, screened.values()))
    selected_count = sum(map(len, selected.values()))
    for league, track in tracks.items():
        cap = track['planned_per_fund_commitment_max_krw'] // 10**8
        minimum = track['min_formation_per_fund_krw'] // 10**8
        numbers = [len(rows[league]) for rows in (applied, screened, selected)]
        if (not 0 < numbers[2] <= numbers[1] <= numbers[0]
                or f'{league}소부장{numbers[0]}{numbers[1]}{numbers[2]}{cap:,}{minimum:,}이상' not in final
                or numbers[2] != track['planned_fund_count']):
            raise ValueError('소부장 최종 선정 표와 팀 수·펀드당 위탁 예정액 불일치')
    if (f'총{applications}개운용사가신청' not in compact(texts['접수 결과'])
            or f'{applications}개운용사중{shortlist}개사가통과' not in compact(texts['1차 심사 결과'])
            or f'지원한{applications}개운용사중최종{selected_count}개사를선정' not in final):
        raise ValueError('소부장 단계별 명단과 본문 총 팀 수 불일치')
    events = [program['events'][0]]
    descriptions = {'접수 결과': f"{applications}팀 접수 · 일반 {len(applied['일반'])}팀 · 반도체 {len(applied['반도체'])}팀",
                    '1차 심사 결과': f"{shortlist}팀 통과 · 일반 {len(screened['일반'])}팀 · 반도체 {len(screened['반도체'])}팀",
                    '선정 결과': f"{selected_count}팀 선정 · 일반 {len(selected['일반'])}팀 · 반도체 {len(selected['반도체'])}팀"}
    for event_type, (n, _) in press.items():
        announced = dates[event_type]
        if not original['date'] <= announced <= n['date']:
            raise ValueError('소부장 모집·발표·게시일 일치 미확인')
        detail = descriptions.get(event_type, '')
        if announced != n['date']:
            detail = f'{announced} 발표 · {detail}'
        events.append({'date': n['date'], 'type': event_type, 'title': n['title'], 'url': n['url'],
                       **({'detail': detail} if detail else {})})
    if not (events[0]['date'] < events[1]['date'] < deadline.isoformat() < dates['접수 결과']
            <= events[2]['date'] < events[3]['date'] < events[4]['date']):
        raise ValueError('소부장 접수·심사·선정 단계 순서 불일치')
    result_url = press['선정 결과'][0]['url']
    gps = []
    gp_tracks = {}
    for league, teams in selected.items():
        for team in teams:
            for name in team:
                gp_tracks[name] = league if len(team) == 1 else f'{league} · 공동운용'
                gps.append({'name': name, 'id': 'kdb-' + hashlib.sha256(name.encode()).hexdigest()[:16],
                            'asset_scope': program['asset_scope'], 'source_url': result_url})

    funding = program['funding_plan']
    labels = {'fund_target_label': f"최소 {funding['planned_formation_target_krw'] / 10**8:,.0f}억원",
              'manager_count_label': f'{selected_count}팀',
              'commitment_detail': f"산업은행 출자 예정 {funding['lead_institution_own_planned_krw'] / 10**8:,.0f}억원 포함",
              'contribution_note': '산업은행 주관 블라인드 펀드 일반·반도체 합계'}
    program.update(labels, events=events, selected_gps=gps, gp_tracks=gp_tracks,
                   manager_list_sources={'selected_gps': result_url}, joint_history_bundle_sha256=recruit_sha)
    program['segments'] = [{'name': name, 'amount_krw': t['planned_commitment_total_krw'],
                            'manager_count': t['planned_fund_count'],
                            'per_fund_max_krw': t['planned_per_fund_commitment_max_krw']} for name, t in tracks.items()]
    semiconductor = tracks['반도체']['strategy']
    common_pct = tracks['일반']['strategy']['materials_min_investment_pct']
    if not semiconductor['obligations_may_overlap'] or semiconductor['materials_min_investment_pct'] != common_pct:
        raise ValueError('소부장 리그별 투자 조건 불일치')
    program['primary_investment'] = {'source_url': original['url'], 'items': [
        f'일반·반도체 공통으로 소부장 관련 기업에 결성금액의 {common_pct}% 이상 투자',
        f"반도체는 국내 중소·중견 반도체 소부장 기업에 {semiconductor['domestic_sme_semiconductor_min_krw']/10**8:,.0f}억원 이상 투자",
        f"반도체는 국내 소부장 기업의 해외 진출에 {semiconductor['domestic_company_overseas_expansion_min_krw']/10**8:,.0f}억원 이상 투자. 투자 요건은 중복 인정"]}

    program['extraction_evidence'] = {'joint_recruitment': list(verified['evidence'].values())}
    _refresh(program, [], checked_at)
    notices = [original, *(n for n, _ in press.values())]
    _check_matches(program, current_programs, notices)
    return program, notices
