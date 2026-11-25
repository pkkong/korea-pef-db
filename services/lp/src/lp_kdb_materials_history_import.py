"""Replay official materials fund plans and their KDB press-board lifecycle."""

from __future__ import annotations

import copy
import hashlib
import html
import json
import re
from datetime import date
from urllib.parse import parse_qs, urlsplit

try:
    from . import collect_lp_institution_boards as boards
    from . import lp_board_adapters_banks as banks
    from . import lp_kgrowth_history_replay as replay
    from . import kgrowth_listing
    from . import lp_newdeal_history_import as joint_source
    from .lp_history_notices import KDB_MATERIALS_IMPORT_KIND as IMPORT_KIND, KDB_PRESS_KIND
    from .lp_joint_history_projection import review_joint_candidates
    from .lp_notice_publication import _refresh
    from .lp_notice_triage import compact
except ImportError:
    import collect_lp_institution_boards as boards
    import lp_board_adapters_banks as banks
    import lp_kgrowth_history_replay as replay
    import kgrowth_listing
    import lp_newdeal_history_import as joint_source
    from lp_history_notices import KDB_MATERIALS_IMPORT_KIND as IMPORT_KIND, KDB_PRESS_KIND
    from lp_joint_history_projection import review_joint_candidates
    from lp_notice_publication import _refresh
    from lp_notice_triage import compact


BUNDLE_KIND = 'lp_kdb_materials_joint_history_source_v1'
BUNDLE_2020_KIND = 'lp_kdb_materials_2020_originals_v1'
_CONFIG = {'institution_id': 'kdb', 'listing_url': banks.KDB_PRESS_BOARD, 'search_terms': ['소재·부품·장비'], 'pages': 1}
_IDENTITY = {'target_institution_id': 'kdb', 'fund': '소재·부품·장비분야투자전용펀드',
             'year': '2021', 'round': '2차'}
_STAGES = {
    '공동 모집 보도자료': '투자전용펀드(2차)출자사업공고',
    '접수 결과': '블라인드펀드(2차)위탁운용사선정에',
    '1차 심사 결과': '블라인드펀드(2차)」서류심사결과발표',
    '선정 결과': '블라인드펀드(2차)」운용사최종선정',
}
_STAGES_2020 = {
    '공동 모집 보도자료': ('소재·부품·장비', '소재·부품·장비전용펀드출자사업」공고'),
    '접수 결과': ('소부장', '소부장투자전용펀드위탁운용사접수결과'),
    '1차 심사 결과': ('소재·부품·장비', '소재·부품·장비블라인드펀드위탁운용사선정」서류심사결과발표'),
    '선정 결과': ('소부장', '국내최대규모소부장전용펀드운용사선정'),
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
    year = notice['date'][:4]
    fragments = {stage: v[1] for stage, v in _STAGES_2020.items()} if year == '2020' else _STAGES
    if year not in ('2020', '2021') or event_type not in fragments or fragments[event_type] not in compact(notice['title']):
        raise ValueError('산업은행 소부장 보도자료의 단계 불일치')
    title_match = _application_title_match if year == '2020' and event_type == '접수 결과' else None
    return boards.validate_notice(notice, checked_at, _CONFIG, history_listing=True, require_attachment_bytes=False,
                                  title_match=title_match)


def _application_title_match(list_title, detail_title):
    """The 2020 application's title render collapses the space after the comma."""
    return list_title == detail_title or list_title.replace('산업은행,  소부장', '산업은행, 소부장', 1) == detail_title


def _raw(receipt, url, limit, checked_at):
    if receipt.get('url') != url or receipt.get('final_url') != url or receipt.get('curl_status') != 0:
        raise ValueError('산업은행 보도자료 원응답 주소 불일치')
    return joint_source._observed_bytes(receipt, limit, joint_source._stamp('2020-01-01T00:00:00+00:00'), checked_at)


def _press_rows(listing, term, checked_at):
    config = {**_CONFIG, 'search_terms': [term]}
    canonical = banks.listing_requests(config)[0]['url']
    endpoint, query = canonical.split('?', 1)
    requested = parse_qs(query)['_JSON_'][0]
    if json.loads(requested) != json.loads(listing['params']['_JSON_']):
        raise ValueError('산업은행 보도자료 게시판·검색어·페이지 불일치')
    listing_body = _raw(listing, endpoint, boards.MAX_BYTES, checked_at).decode('utf-8')
    listed_at = joint_source._stamp(listing['checked_at'])
    rows = banks.parse_listing(listing_body, canonical, config)
    listing_data = json.loads(listing_body)
    header = listing_data['HEADER_STD_WEB']
    if int(header['REQ_PAGE_NO']) != 1 or int(header['TOT_PAG_CNT']) != 1 \
            or int(header['TOT_PAG_ROW_CNT']) != len(rows):
        raise ValueError('산업은행 소부장 보도자료 원목록의 전체 행 미확인')
    return rows, listing_data['STDLIST_REC'], listed_at, {'url': canonical, 'html': listing_body, 'sha256': listing['sha256']}


def _press_notices(source, checked_at, year='2021'):
    if year == '2020':
        stages = _STAGES_2020
        listings = source['press_listings']
    else:
        stages = {stage: ('소재·부품·장비', value) for stage, value in _STAGES.items()}
        listings = [source['listing']]
    terms = {term for term, _ in stages.values()}
    captured = {entry['term']: entry for entry in listings}
    if set(captured) != terms or len(captured) != len(listings):
        raise ValueError('산업은행 소부장 보도자료 검색어 묶음 불일치')
    by_term = {term: _press_rows(captured[term], term, checked_at) for term in sorted(terms)}
    if year == '2020':
        second_round, = [row for row in by_term['소재·부품·장비'][1]
                         if row['FST_ENR_DTM'].startswith('2021')
                         and _STAGES['공동 모집 보도자료'] in compact(row['NAC_CONE_TTL'])]
        later_body = compact(html.unescape(second_round['NAC_SMRY_CONE']))
        if '20년1차사업에이어소부장산업지원을위해조성' not in later_body:
            raise ValueError('산업은행의 다음 회차 원목록에서 소부장 2020년 1차 확인 실패')
    if len(source['press_notices']) != len(stages):
        raise ValueError('산업은행 소부장 모집·접수·심사·선정 보도자료 수 불일치')
    notices = {}
    for label, (term, title_fragment) in stages.items():
        rows, raw_rows, listed_at, listing_proof = by_term[term]
        row, = [r for r in rows if r['date'][:4] == year and title_fragment in compact(r['title'])]
        identifier = row['source_id'].split(':')[1]
        target, = [n for n in raw_rows if n['ITR_NAC_ID_MNG_SNO'] == identifier]
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
        match = (_application_title_match(row['title'], detail['title']) if year == '2020' and label == '접수 결과'
                 else detail['title'] == row['title'])
        if (not match or detail['date'] != row['date']
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
                 'listing': listing_proof,
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


def _announcement_date(text, year='2021'):
    stamp = _part(text[:200], rf'보도자료\s+\(({year}\.\d{{2}}\.\d{{2}})\)', '발표일')[1]
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
    identity = program['joint_history_identity']
    year = identity['year']
    keys = {source_key(n['url']) for n in sources}
    for old in current_programs:
        existing_keys = {source_key(event['url']) for event in old['events']}
        title = re.sub(r'[·‧]', '', compact(old['title']))
        same_fund = (('소재부품장비' in title or '소부장' in title) and '펀드' in title
                     and '기업성장' not in title and ('2차' in title if year == '2021' else '2차' not in title))
        overlaps = (old.get('joint_history_identity') == identity or bool(keys & existing_keys)
                    or (same_fund and old['institution_id'] == 'kdb'
                        and (old.get('business_year') == year or any(e['date'][:4] == year for e in old['events']))))
        if overlaps and (old['id'], old['institution_id'], old.get('source_program_key')) != (
                program['id'], program['institution_id'], program['source_program_key']):
            raise ValueError('산업은행 소부장이 기존 사업·원문 주소와 겹침')


def project(source, current_programs, checked_at):
    if isinstance(source, dict) and source.get('kind') == BUNDLE_2020_KIND:
        return _project_2020(source, current_programs, checked_at)
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


def _plan_2020(source, press_text):
    """Bind the retained joint PDF to the matching KDB release and signed terms."""
    original = source['document']
    listing = source['listing']
    proof = original['discovery_provenance']['listing']
    body_digest = replay._sha(json.dumps([original['title'], original['date'], original['body']], ensure_ascii=False).encode())
    if (original['institution_id'] != 'kgrowth' or listing['url'] != proof['url'] or listing['sha256'] != proof['sha256']
            or replay._sha(listing['html'].encode()) != listing['sha256']
            or body_digest != original['sha256']):
        raise ValueError('소부장 1차 공동 모집 목록·본문 지문 불일치')
    row, = [r for r in kgrowth_listing.parse_listing(listing['html'], listing['url'])
            if r['source_id'] == original['source_id']]
    if (row['title'], row['date'], kgrowth_listing.source_id(original['url'])) != (
            original['title'], original['date'], row['source_id']):
        raise ValueError('소부장 1차 공동 모집 원목록에 없는 공고')
    attachment, = original['attachments']
    pdf = joint_source._decode(source['pdf_base64'], replay.MAX_FILE_BYTES)
    digest = replay._sha(pdf)
    if not pdf.startswith(b'%PDF-') or original['attachment_hashes'] != {attachment: digest}:
        raise ValueError('소부장 1차 공동 모집 PDF 원바이트 지문 불일치')
    extracted = replay.kgrowth_attachment_text(pdf)
    if original['attachment_texts'] != {attachment: extracted}:
        raise ValueError('소부장 1차 공동 모집 PDF 추출문 불일치')
    body = compact(extracted)
    release = compact(press_text)
    title = '소재·부품·장비분야투자전용펀드위탁운용사선정계획공고'
    if title not in body[:240] or title not in compact(original['title']).replace('「', '').replace('」', ''):
        raise ValueError('소부장 1차 투자 전용 원모집 제목 불일치')
    amount_pattern = (r'위탁운용금액◦총([\d,]+)억원이내\(정부재정([\d,]+)억원,한국산업은행([\d,]+)억원\)'
                      r'◦총([\d,]+)억원이내\(정부재정[\d,]+억원\)')
    overview = _part(body, amount_pattern, '원모집 블라인드 출자액')
    total, government, own, project = (int(s.replace(',', '')) for s in overview.groups())
    count = int(_part(body, r'선정운용사수◦(\d+)개사◦위탁운용금액소진시까지', '선정 예정 팀 수')[1])
    minimum = int(_part(body, r'최소결성금액◦펀드별([\d,]+)억원', '펀드별 최소 결성액')[1].replace(',', ''))
    cap = int(_part(body, r'운용사별배정금액◦([\d,]+)억원이내', '펀드별 출자 한도')[1].replace(',', ''))
    month, day, clock = _part(
        body, r'블라인드펀드접수일시:2020\.(\d{1,2})\.(\d{1,2})\.\([월화수목금토일]\)\((\d{2}:\d{2})限\)', '마감').groups()
    deadline_day = date(2020, int(month), int(day))
    pct = int(_part(body, r'소재·부품·장비산업관련기업-결성금액의(\d+)%이상투자', '주목적 의무')[1])
    signed = date.fromisoformat(original['date'])
    legal = _part(body, r'1\.블라인드펀드⑴제안관련사항항목세부내용출자대상투자기구(.+?)※본계획', '블라인드 법적 형태')[1]
    if (not 0 < own < total or government + own != total or signed.year != 2020
            or f'2020년{signed.month}월{signed.day}일한국산업은행한국성장금융투자운용' not in body
            or '주관기관◦한국산업은행◦한국성장금융투자운용' not in body
            or not all(s in legal for s in ('경영참여형사모집합투자기구', '창업투자조합', '벤처투자조합'))
            or f'{signed.month}월{signed.day}일' not in release
            or overview[0] not in release
            or f'재정·정책자금{total + project:,}억원출자' not in release
            or f'블라인드펀드접수일시:2020.{month}.{day}.' not in release
            or f'선정주관:블라인드펀드는산업은행에서,프로젝트펀드는성장금융이수행' not in release):
        raise ValueError('소부장 1차 산업은행 보도 원문과 공동 모집 조건 불일치')
    return {'total': total, 'own': own, 'count': count, 'minimum': minimum, 'cap': cap, 'pct': pct,
            'deadline': deadline_day.isoformat() + 'T' + clock + ':00+09:00', 'digest': digest,
            'signed_date': signed}


def _labelled_teams(text):
    pattern = r'\s*([가-힣A-Za-z0-9]{2,35}(?:\s*/\s*[가-힣A-Za-z0-9]{2,35})?)\s+(PE|VC)'
    matches = re.findall(pattern, text)
    if not matches or re.sub(pattern, '', text).strip():
        raise ValueError('소부장 1차 팀별 투자기구 구획 불일치')
    names = _teams('\n'.join(team.replace('\n', '') for team, _ in matches))
    return {frozenset(team): scope for team, (_, scope) in zip(names, matches)}


def _rosters_2020(texts):
    app = _part(texts['접수 결과'], r'비\s*고\s+(\d+)\s+\(\s*(\d+)\s*\)\s+(.+?)\s+\*\s*지원 운용사명', '접수 표')
    submissions = _labelled_teams(app[3])
    screened = _part(texts['1차 심사 결과'],
                     r'서류심사 통과 운용사 명단\s*>\s+운용사명\s+투자기구\s+(.+?)\s+\*\s*운용사명', '서류심사 표')
    shortlist = _labelled_teams(screened[1])
    if int(app[1]) != len(submissions) or any(submissions.get(t) != scope for t, scope in shortlist.items()):
        raise ValueError('소부장 1차 접수·심사 명단의 팀 또는 투자기구 불일치')
    roster = _part(texts['선정 결과'], r'선정된 위탁운용사는\s+(.+?)로\s+2020년', '최종 선정 본문')
    abbreviated_teams = [s.strip().rstrip('*').split('·') for s in roster[1].split(',')]
    # The same companies are spelled out in the official screening and
    # application tables. Each abbreviation must resolve to that exact team.
    expanded_names = {'BNW인베스트먼트': '비엔더블유인베스트먼트', '기업은행': '중소기업은행',
                      'SKS PE': '에스케이에스프라이빗에쿼티', '한투PE': '한국투자프라이빗에쿼티'}
    selected = [tuple(expanded_names.get(name.strip(), name.strip()) for name in team) for team in abbreviated_teams]
    if (not selected or len({frozenset(team) for team in selected}) != len(selected)
            or any(shortlist.get(frozenset(team)) != 'PE' for team in selected)
            or len(selected) != int(app[2])):
        raise ValueError('소부장 1차 최종 공동운용과 서류심사 PE 표 불일치')
    return len(submissions), len(shortlist), selected


def _project_2020(source, current_programs, checked_at):
    if set(source) != {'kind', 'institution_id', 'press_listings', 'discovery', 'press_notices', 'joint_recruitment'} \
            or source['institution_id'] != 'kdb':
        raise ValueError('산업은행 소부장 1차 원본 묶음 형식 불일치')
    press = _press_notices(source, checked_at, '2020')
    texts = {kind: text for kind, (_, text) in press.items()}
    plan = _plan_2020(source['joint_recruitment'], texts['공동 모집 보도자료'])
    dates = {kind: _announcement_date(text, '2020') for kind, text in texts.items()}
    original = plan['signed_date'].isoformat()
    applied, screened, selected = _rosters_2020(texts)
    selected_count = len(selected)
    final = compact(texts['선정 결과'])
    final_table = f'소부장펀드{applied}{screened}{selected_count}{plan["cap"]:,}{plan["minimum"] * plan["count"]:,}이상'
    if (not 0 < selected_count == plan['count'] < screened < applied or final_table not in final
            or f'총{applied}개운용사가신청' not in compact(texts['접수 결과'])
            or f'{applied}개운용사중{screened}개사가통과' not in compact(texts['1차 심사 결과'])
            or not original < dates['공동 모집 보도자료'] < plan['deadline'][:10] <= dates['접수 결과']
            or not dates['접수 결과'] < dates['1차 심사 결과'] < dates['선정 결과']):
        raise ValueError('소부장 1차 단계별 팀 수·발표 순서·펀드당 정책출자액 불일치')
    labels = {'공동 모집 보도자료': f'{original} 공동 공고',
              '접수 결과': f'{applied}팀 접수', '1차 심사 결과': f'{screened}팀 통과',
              '선정 결과': f'{selected_count}팀 선정'}
    events = []
    for kind, (notice, _) in press.items():
        if dates[kind] > notice['date']:
            raise ValueError('소부장 1차 은행 보도자료 발표일과 게시일 불일치')
        note = labels[kind]
        if dates[kind] != notice['date']:
            note += f' · {dates[kind]} 발표'
        events.append({'date': notice['date'], 'type': '모집 공고' if kind == '공동 모집 보도자료' else kind,
                       'title': notice['title'], 'url': notice['url'], 'detail': note})
    if [e['date'] for e in events] != sorted({e['date'] for e in events}):
        raise ValueError('소부장 1차 은행 보도자료 게시 순서 불일치')
    scope = 'PE·VC 공동 모집'
    result_url = events[-1]['url']
    gps = [{'name': name, 'id': 'kdb-' + hashlib.sha256(name.encode()).hexdigest()[:16],
            'asset_scope': scope, 'source_url': result_url} for team in selected for name in team]
    identity = {**_IDENTITY, 'year': '2020', 'round': '1차'}
    digest = replay._sha(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
    factor = 10**8
    total_formation = plan['minimum'] * plan['count']
    program = {'id': f'kdb-2020-{digest[:16]}', 'institution_id': 'kdb', 'institution_name': '한국산업은행',
               'title': '소재·부품·장비 투자 전용 펀드 2020년 1차 블라인드', 'asset_scope': scope, 'basic_publication': True,
               'status': '선정 완료', 'checked_at': checked_at, 'source_program_key': 'joint:' + digest,
               'business_year': '2020', 'business_round': '1차', 'joint_history_identity': identity,
               'joint_history_track_keys': ['블라인드'], 'events': events, 'selected_gps': gps,
               'gp_tracks': {g['name']: '블라인드 · 공동운용' for g in gps},
               'manager_list_sources': {'selected_gps': result_url},
               'deadline': plan['deadline'], 'deadline_precision': 'datetime',
               'commitment_label': f"공동 정책출자 예정 {plan['total']:,}억원 이내",
               'fund_target_label': f'최소 {total_formation:,}억원',
               'manager_count_label': f"{plan['count']}팀",
               'per_fund_amount_krw': plan['cap'] * factor, 'per_fund_qualifier': '이내',
               'commitment_detail': f"산업은행 출자 예정 {plan['own']:,}억원 포함",
               'contribution_note': '산업은행 주관 블라인드 펀드',
               'funding_plan': {'basis': 'joint_contributors_recruitment_plan',
                                'planned_joint_commitment_total_krw': plan['total'] * factor,
                                'lead_institution_own_planned_krw': plan['own'] * factor,
                                'planned_formation_target_krw': total_formation * factor,
                                'pe_annual_own_commitment_eligible': False, 'actual_gp_allocation_krw': None},
               'primary_investment': {'source_url': events[0]['url'], 'items': [
                   f"소재·부품·장비 산업 관련 기업에 결성금액의 {plan['pct']}% 이상 투자"]},
               'extraction_evidence': {'joint_recruitment': [
                   {'source_url': source['joint_recruitment']['document']['url'], 'attachment_sha256': plan['digest']}]}}
    _refresh(program, [], checked_at)
    notices = [notice for notice, _ in press.values()]
    _check_matches(program, current_programs, notices)
    return program, notices
