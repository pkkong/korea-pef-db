"""Replay the first 2023 Growth Support solicitation and its large-track result."""

from datetime import date, time
import hashlib
import json
import re
from urllib.parse import urljoin

try:
    from . import lp_board_adapters_banks as boards, lp_kdb_innovation_2023_first as innovation
    from . import lp_kdb_materials_history_import as materials, lp_newdeal_history_import as joint, lp_pdf_ocr
    from .collect_lp_history_attachments import read_attachment
    from .lp_history_notices import GROWTH_FIRST_2023_IMPORT_KIND as IMPORT_KIND, GROWTH_FIRST_2023_KIND as NOTICE_KIND
    from .lp_notice_publication import _refresh
    from .lp_notice_triage import compact
except ImportError:
    import lp_board_adapters_banks as boards
    import lp_kdb_innovation_2023_first as innovation
    import lp_kdb_materials_history_import as materials
    import lp_newdeal_history_import as joint
    import lp_pdf_ocr
    from collect_lp_history_attachments import read_attachment
    from lp_history_notices import GROWTH_FIRST_2023_IMPORT_KIND as IMPORT_KIND, GROWTH_FIRST_2023_KIND as NOTICE_KIND
    from lp_notice_publication import _refresh
    from lp_notice_triage import compact


BUNDLE_KIND = 'lp_kdb_growth_support_first_2023_source_v1'
_ORIGIN = 'https://www.shinhanfund.com'
_DETAIL = re.compile(re.escape(_ORIGIN) + r'/ko/(?:pc|mobile)/board/noticeView\?no=([1-9]\d*)')
_HEAD = '혁신성장펀드(성장지원펀드)2023년1차'
_IDENTITY = {'target_institution_id': 'kdb', 'fund': '혁신성장펀드', 'year': '2023', 'round': '1차', 'track': '성장지원 일반 대형'}
_STAGES = {
    'recruitment': ('모집 공고', '위탁운용사선정계획공고'),
    'faq': ('질의응답', '위탁운용사선정계획관련faq'),
    'applications': ('접수 결과', '출자사업성장지원일반/대형분야위탁운용사접수결과'),
    'screening': ('1차 심사 결과', '위탁운용사선정서류심사결과'),
    'selection': ('선정 결과', '위탁운용사선정결과'),
}


def source_key(url):
    found = _DETAIL.fullmatch(url)
    return ('shinhanfund', found[1]) if found else materials.source_key(url)


def _receipt(receipt, url, checked_at):
    if (receipt.get('url') != url or receipt.get('final_url') != url or receipt.get('status') != 200
            or not joint._stamp('2023-01-01T00:00:00+00:00') <= joint._stamp(receipt['checked_at']) <= joint._stamp(checked_at)):
        raise ValueError('성장지원 공고 원응답 주소·관측시각 불일치')
    raw = joint._decode(receipt['raw_base64'], 2_000_000)
    if len(raw) != receipt['bytes'] or hashlib.sha256(raw).hexdigest() != receipt['sha256']:
        raise ValueError('성장지원 공고 원응답 크기·지문 불일치')
    return raw


def _detail(raw, url, role):
    key = _DETAIL.fullmatch(url)
    root = boards._Document(raw).root
    head = boards._one(root.nodes(cls='board-head'), '신한 공지 머리말')
    title = boards._one(head.nodes('h2', 'bv-title'), '신한 공지 제목').clean()
    stamp = boards._one(head.nodes('span', 'bv-date'), '신한 공지 게시일').clean().replace('.', '-')
    body = boards._one(root.nodes(cls='board-cont'), '신한 공지 본문').clean()
    canonical = boards._one((n.attrs.get('href') for n in root.nodes('link') if n.attrs.get('rel') == 'canonical'), '신한 공지 표준 주소')
    attachment = boards._one(root.nodes('a', 'atc-link'), '신한 공지 첨부')
    file = urljoin(url, attachment.attrs['href'])
    name = boards._one(attachment.nodes('span', 'atc-name'), '신한 공지 첨부명').clean().replace(' .pdf', '.pdf')
    next_links = {}
    for nav in root.nodes('dl', 'bnv-def'):
        label = boards._one(nav.nodes('dt'), '공지 인접 링크 종류').clean()
        link = boards._one(nav.nodes('a', 'bnv-link'), '공지 인접 링크').attrs['href']
        if label in next_links:
            raise ValueError('신한 공지 인접 링크 중복')
        next_links[label] = urljoin(url, link)
    if (not key or canonical != url or raw.lower().count('</html>') != 1
            or compact(title) != _HEAD + _STAGES[role][1] or not stamp.startswith('2023-')
            or date.fromisoformat(stamp).isoformat() != stamp or compact('혁신성장펀드(성장지원펀드)') not in compact(body)
            or not re.fullmatch(re.escape(_ORIGIN) + r'/file/download/[1-9]\d*', file)
            or not name.lower().endswith('.pdf')):
        raise ValueError('성장지원 2023년 1차 공지의 주소·제목·본문·첨부 불일치')
    return {'source_id': key[1], 'url': url, 'title': title, 'date': stamp, 'body': body,
            'attachments': [file]}, next_links


def validate_retained_notice(notice, checked_at):
    proof = notice['discovery_provenance']
    raw = proof['detail_html']
    role = proof['role']
    parsed, _ = _detail(raw, notice['url'], role)
    hashes = notice['attachment_hashes']
    if (notice.get('history_import') != NOTICE_KIND or notice['institution_id'] != 'shinhanfund'
            or notice.get('source_channel') != 'shinhanfund_joint_history' or proof['kind'] != 'shinhanfund_joint_detail_v1'
            or notice['event_type'] != _STAGES[role][0] or any(notice[k] != v for k, v in parsed.items())
            or notice.get('attachment_bytes') or set(hashes) != set(parsed['attachments'])
            or not all(re.fullmatch(r'[a-f0-9]{64}', sha) for sha in hashes.values())
            or hashlib.sha256(raw.encode()).hexdigest() != proof['detail_sha256']
            or hashlib.sha256(notice['body'].encode()).hexdigest() != notice['sha256']
            or joint._stamp(notice['checked_at']) > joint._stamp(checked_at)):
        raise ValueError('성장지원 2023년 1차 보존 공고의 신원 또는 원문 지문 불일치')
    if role == 'recruitment':
        url, = hashes
        ocr = notice['attachment_ocr'][url]
        helper_sha = ocr['helper_sha256']
        if not re.fullmatch(r'[a-f0-9]{64}', helper_sha):
            raise ValueError('성장지원 보존 OCR 실행기 지문 불일치')
        lp_pdf_ocr.validate_proof(ocr, hashes[url], ocr['input_bytes'], helper_sha)
    return notice


def _read(source, checked_at):
    notices, texts, links = {}, {}, {}
    for role, (stage, _) in _STAGES.items():
        detail = source['documents'][role]['html']
        raw = _receipt(detail, detail['url'], checked_at).decode('utf-8')
        parsed, links[role] = _detail(raw, detail['url'], role)
        file, = source['documents'][role]['files']
        url, = parsed['attachments']
        pdf = _receipt(file, url, checked_at)
        contents = read_attachment(pdf)
        if file['referer'] != parsed['url'] or contents['format'] != 'pdf' or not pdf.rstrip().endswith(b'%%EOF'):
            raise ValueError('성장지원 원본 PDF가 공지의 파일 링크와 불일치')
        texts[role] = contents['text']
        notice = {**parsed, 'institution_id': 'shinhanfund', 'source_channel': 'shinhanfund_joint_history',
                  'history_import': NOTICE_KIND, 'event_type': stage, 'checked_at': detail['checked_at'],
                  'sha256': hashlib.sha256(parsed['body'].encode()).hexdigest(),
                  'discovery_provenance': {'kind': 'shinhanfund_joint_detail_v1', 'role': role,
                                           'detail_html': raw, 'detail_sha256': detail['sha256']},
                  'attachment_hashes': {url: file['sha256']}, 'attachment_texts': {url: texts[role]}}
        if role == 'recruitment':
            helper_sha = hashlib.sha256(lp_pdf_ocr.HELPER.read_bytes()).hexdigest()
            proof = source['recruitment_ocr']
            if proof.get('helper_sha256') != helper_sha:
                raise ValueError('성장지원 최초 공고 OCR 실행기 지문 불일치')
            notice['attachment_ocr'] = {url: lp_pdf_ocr.validate_result(proof, pdf, helper_sha)}
        notices[role] = validate_retained_notice(notice, checked_at)
    pairs = zip(_STAGES, tuple(_STAGES)[1:])
    if any(links[left].get('다음 글') != notices[right]['url'] or links[right].get('이전 글') != notices[left]['url']
           or notices[left]['date'] >= notices[right]['date'] for left, right in pairs):
        raise ValueError('성장지원 모집·FAQ·접수·서류심사·선정 공지의 날짜 또는 인접 링크 불일치')
    return notices, texts


def _terms(text, pages, bank):
    first, second, third = [compact(page['text']) for page in pages[:3]]
    native = compact(text)
    row = r'성장지원\s*일반\s*대형\s+([\d,]+)\s+([\d,]+)\s+(\d+\.\d)%\s+([\d,]+)\s+(\d+)\s+([\d,]+)\s+산은'
    table = boards._one(re.finditer(row, text), '성장지원 일반 대형 투자표')
    # PDF's visual table is column-based and the layout-blind text drops the deadline and thresholds.
    government, own, per_fund, count, target = (int(table[i].replace(',', '')) for i in (1, 2, 4, 5, 6))
    total = government + own
    if (total * 1000 != target * int(table[3].replace('.', '')) or target != count * per_fund
            or f'{government:,}{own:,}{table[3]}%{per_fund:,}{count}{target:,}산은' not in first
            or f'정책출자자위탁운용금액:총{total:,}억원내외' not in first
            or f'성장지원일반대형산은{government:,}{own:,}{total:,}{table[3]}{count}{per_fund:,}{target:,}' not in compact(bank)
            or '출자계획(기업투자블라인드펀드)' not in first or '공동운용(co-gp)제안은허용하지않음' not in second
            or not all(x in second for x in ('기관전용사모집합투자기구*', '경영참여목적에한함', '벤처투자조합'))
            or not all(x in native for x in ('기관전용사모집합투자기구', '벤처투자조합'))):
        raise ValueError('성장지원 대형 출자표·주관·PE/VC 범위의 교차 확인 실패')
    due = boards._one(re.finditer(r'접수일시(?:[0○•])?2023년(\d+)월(\d+)일\(([월화수목금토일])\)(\d{2}:\d{2})~(\d{2}:\d{2})',
                                  first), '성장지원 원문 마감')
    day = date(2023, int(due[1]), int(due[2]))
    if '월화수목금토일'[day.weekday()] != due[3] or time.fromisoformat(due[4]) >= time.fromisoformat(due[5]):
        raise ValueError('성장지원 모집 마감의 요일·시각 불일치')
    objective = boards._one(re.finditer(r'창업후(\d+)년이상경과한중소[·•ㆍ]중견기업에약정총액의\[(\d+)%\]이상투자'
                                        r'투자비율②투자전기업가치\(pre-moneyvalue\)([\d,]+)억원이상중소[·•ㆍ]중견기업에'
                                        r'약정총액의\[(\d+)%\]이상투자', third), '성장지원 대형 투자 의무')
    tenure, older_share, pre_money, value_share = (int(value.replace(',', '')) for value in objective.groups())
    if not (tenure > 0 and pre_money > 0 and 0 < older_share <= 100 and 0 < value_share <= 100):
        raise ValueError('성장지원 대형의 기업 요건과 투자비율 불일치')
    return government, own, per_fund, count, target, day, due[5], (tenure, older_share, pre_money, value_share)


def _rosters(texts, bank, count, per_fund, target):
    heading = rf'성장지원\s+일반/대형\s*\({count}\)\s+{per_fund:,}\s+\(총 {target:,}\)'
    published_header = rf'성장지원\s+일반\s+대형\s*/\s*\({count}\)\s+{per_fund:,}\s+총\s*\(\s*{target:,}\)'
    entries = r'\s+([가-힣\s]+?)\s*\Z'
    applied = boards._one(re.finditer(published_header + rf'\s+{count}' + entries, texts['applications']), '성장지원 대형 접수')
    screened = boards._one(re.finditer(published_header + entries, texts['screening']), '성장지원 대형 심사')
    selected = boards._one(re.finditer(published_header + r'\s+([가-힣]+)\s+산은\s+([가-힣]+)\s*\Z', texts['selection']),
                           '성장지원 대형 선정')
    bank_applied = boards._one(re.finditer(heading + rf'\s+{count}' + entries, bank['접수 보도자료']), '은행 성장지원 대형 접수')
    bank_screened = boards._one(re.finditer(heading + entries, bank['서류심사 보도자료']), '은행 성장지원 대형 심사')
    official = materials._teams('\n'.join(selected.groups()))
    applied_teams, screened_teams = materials._teams(applied[1]), materials._teams(screened[1])
    # The intake notice uses the shorter firm name. Expand only the explicit
    # short/long pair independently present in both issuers' same-track files.
    normalized_applications = [('어펄마캐피탈매니져스코리아',) if team == ('어펄마캐피탈',) else team for team in applied_teams]
    if (len(official) != count or len(applied_teams) != count or applied_teams != materials._teams(bank_applied[1])
            or screened_teams != materials._teams(bank_screened[1]) or official != screened_teams
            or official != normalized_applications
            or not all(len(team) == 1 for team in official)):
        raise ValueError('성장지원 대형 접수·심사·선정의 운용사와 주관 범위 불일치')
    return [name for name, in official]


def project(source, current_programs, checked_at):
    if (not isinstance(source, dict) or set(source) != {'kind', 'institution_id', 'bank', 'documents', 'recruitment_ocr'}
            or source['kind'] != BUNDLE_KIND or source['institution_id'] != 'kdb' or set(source['documents']) != set(_STAGES)):
        raise ValueError('성장지원 대형 가져오기 원문 형식 불일치')
    notices, texts = _read(source, checked_at)
    bank_notices, bank_texts = innovation._read_bank(source['bank'], checked_at)
    original = notices['recruitment']
    pdf, = original['attachments']
    pages = original['attachment_ocr'][pdf]['pages']
    government, own, per_fund, count, target, due, end, (tenure, older_share, pre_money, value_share) = _terms(
        texts['recruitment'], pages, bank_texts['공동 모집 보도자료'])
    names = _rosters(texts, bank_texts, count, per_fund, target)
    if (original['date'] != bank_notices['공동 모집 보도자료']['date']
            or not notices['faq']['date'] < due.isoformat() < notices['applications']['date'] == bank_notices['접수 보도자료']['date']
            or f'제안서접수를{due.month}월{due.day}일' not in compact(bank_texts['접수 보도자료'])):
        raise ValueError('성장지원 대형의 모집·접수 공통 일정 불일치')
    scope = 'PE·VC 공동 모집'
    result = notices['selection']['url']
    digest = hashlib.sha256(json.dumps(_IDENTITY, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    identifier, program_key = 'kdb-2023-' + digest[:16], 'joint:' + digest
    keys = {source_key(n['url']) for n in notices.values()}
    for old in current_programs:
        title = compact(old['title'])
        same = (old.get('joint_history_identity') == _IDENTITY or any(source_key(e['url']) in keys for e in old['events'])
                or (old['institution_id'] == 'kdb' and all(x in title for x in ('성장지원', '2023', '1차', '대형'))))
        if same and (old['id'], old['institution_id'], old.get('source_program_key')) != (identifier, 'kdb', program_key):
            raise ValueError('성장지원 대형 후보가 기존 사업·원문과 겹침')
    timeline = {'recruitment': '공동 모집 · 산업은행 주관 성장지원 일반 대형',
                'faq': '혁신산업펀드·성장지원펀드 공통 질의응답',
                'applications': f'대형 {count}팀 접수', 'screening': f'대형 {count}팀 통과',
                'selection': f'대형 {count}팀 선정'}
    events = [{'date': n['date'], 'type': n['event_type'], 'title': n['title'], 'url': n['url'],
               'detail': timeline[role]} for role, n in notices.items()]
    gps = [{'name': name, 'id': 'kdb-' + hashlib.sha256(name.encode()).hexdigest()[:16], 'asset_scope': scope, 'source_url': result}
           for name in names]
    won = 10**8
    program = {'id': identifier, 'institution_id': 'kdb', 'institution_name': '한국산업은행',
               'title': '혁신성장펀드 2023년 1차 · 성장지원 일반 대형', 'asset_scope': scope, 'status': '선정 완료',
               'source_program_key': program_key, 'joint_history_identity': dict(_IDENTITY),
               'joint_history_track_keys': ['성장지원 일반 대형'], 'business_year': '2023', 'business_round': '1차',
               'basic_publication': True, 'deadline': f'{due.isoformat()}T{end}:00+09:00', 'deadline_precision': 'datetime',
               'events': events, 'selected_gps': gps, 'gp_tracks': {g['name']: '대형' for g in gps},
               'manager_list_sources': {'selected_gps': result},
               'commitment_label': f'공동 정책출자 예정 {own+government:,}억원 내외', 'fund_target_label': f'{target:,}억원',
               'manager_count_label': f'{count}팀',
               'commitment_detail': f'산업은행 {own:,}억원 · 정부 재정 {government:,}억원 · 펀드별 결성 목표 {per_fund:,}억원',
               'contribution_note': '산업은행 주관 성장지원 일반 대형',
               'funding_plan': {'basis': 'joint_contributors_recruitment_plan', 'pe_annual_own_commitment_eligible': False,
                                'planned_joint_commitment_total_krw': (own+government) * won,
                                'lead_institution_own_planned_krw': own * won, 'planned_formation_target_krw': target * won},
               'primary_investment': {'source_url': original['url'], 'items': [
                   f'창업 후 {tenure}년 이상 지난 중소·중견기업에 약정총액의 {older_share}% 이상 투자',
                   f'투자 전 기업가치 {pre_money:,}억원 이상인 중소·중견기업에 약정총액의 {value_share}% 이상 투자']}}
    _refresh(program, [], checked_at)
    return program, list(notices.values())
