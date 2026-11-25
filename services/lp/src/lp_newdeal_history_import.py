"""Replay the official joint New Deal evidence for the historical publisher."""

import base64
import copy
import hashlib
import json
import re
from datetime import date, datetime
from urllib.parse import parse_qs, urlsplit

try:
    from . import lp_kgrowth_history_replay as replay
    from .lp_history_notices import JOINT_KIND as NOTICE_KIND, JOINT_IMPORT_KIND as IMPORT_KIND
    from .lp_history_notices import JOINT_FOLLOWUP_IMPORT_KIND as FOLLOWUP_IMPORT_KIND
    from .lp_kgrowth_history_attachment_queue import file_labels
    from .lp_joint_history_projection import review_newdeal_growth_selection
    from .lp_kgrowth_press_probe import _press_detail_url, _press_result_detail_dom
    from .lp_notice_triage import compact
    from .lp_notice_publication import _schedule_order
except ImportError:
    import lp_kgrowth_history_replay as replay
    from lp_history_notices import JOINT_KIND as NOTICE_KIND, JOINT_IMPORT_KIND as IMPORT_KIND
    from lp_history_notices import JOINT_FOLLOWUP_IMPORT_KIND as FOLLOWUP_IMPORT_KIND
    from lp_kgrowth_history_attachment_queue import file_labels
    from lp_joint_history_projection import review_newdeal_growth_selection
    from lp_kgrowth_press_probe import _press_detail_url, _press_result_detail_dom
    from lp_notice_triage import compact
    from lp_notice_publication import _schedule_order


BUNDLE_KIND = 'lp_newdeal_joint_history_source_v1'
FOLLOWUP_BUNDLE_KIND = 'lp_newdeal_joint_followup_source_v1'
_ROLES = ('search', 'followup', 'detail', 'failed_pdf', 'pdf')
_FUND = '정책형 뉴딜펀드'
_SOURCE_KEYS = {'kind', 'institution_id', 'bundle', 'recruitment', 'press', 'attachments'}
_FAQ_REVISION = re.compile(r"['‘’](\d{2})\.(\d{1,2})\.(\d{1,2})\(([월화수목금토일])\)에기업투자faq및붙임\d+를추가하여첨부")


def _faq_date(body):
    dates = _FAQ_REVISION.findall(compact(body))
    if len(dates) != 1:
        raise ValueError('뉴딜 기업투자 FAQ를 추가한 날짜가 미확인')
    year, month, day, weekday = dates[0]
    stamp = date(2000 + int(year), int(month), int(day))
    if '월화수목금토일'[stamp.weekday()] != weekday:
        raise ValueError('뉴딜 기업투자 FAQ 추가일과 요일 불일치')
    return stamp.isoformat()


def _decode(encoded, limit):
    if not isinstance(encoded, str) or not 0 < len(encoded) <= (limit + 2) // 3 * 4:
        raise ValueError('뉴딜 공동 원본 크기·형식 불일치')
    raw = base64.b64decode(encoded, validate=True)
    if not 0 < len(raw) <= limit:
        raise ValueError('뉴딜 공동 원본 크기 불일치')
    return raw


def _stamp(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('뉴딜 원문 관측 시각의 시간대 누락')
    return stamp


def source_key(url):
    """Identify the same public notice regardless of listing/search query fields."""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    identifier, board = query.get('idx', []), query.get('str_type', [])
    if (parts.scheme == 'https' and parts.hostname in ('www.kgrowth.or.kr', 'kgrowth.or.kr')
            and parts.path == '/notice_view.asp' and not parts.fragment
            and len(identifier) == len(board) == 1 and re.fullmatch(r'[1-9]\d*', identifier[0])
            and board[0] in ('1', '3')):
        return board[0], identifier[0]
    return None


def validate_retained_notice(notice, checked_at):
    """Reparse the preserved original detail without reintroducing the entire search bundle."""
    n = copy.deepcopy(notice)
    proof = n['joint_history_proof']
    received = _stamp(n['checked_at'])
    key = source_key(n['url'])
    if (n['history_import'] != NOTICE_KIND or n['institution_id'] != 'kgrowth'
            or n.get('source_channel') != 'kgrowth_joint_history' or not key
            or n['source_id'] != key[1] or received > _stamp(checked_at)
            or n['date'] > received.date().isoformat() or n.get('attachment_bytes')):
        raise ValueError('뉴딜 공동 원문의 출처·관측시각 불일치')
    if not n['attachment_hashes'] or not set(n['attachment_hashes']) <= set(n['attachments']) \
            or not all(re.fullmatch('[a-f0-9]{64}', h) for h in n['attachment_hashes'].values()):
        raise ValueError('뉴딜 공동 원문의 첨부 지문 불일치')
    encoded, digest = proof['detail_base64'], proof['detail_sha256']
    if key[0] == '1':
        if n['event_type'] == '질의응답':
            if not replay.newdeal_faq(n) or n['faq_date'] != _faq_date(n['body']) or n['faq_date'] < n['date']:
                raise ValueError('뉴딜 설명회·FAQ 원문의 단계·추가일 불일치')
        elif n['event_type'] != '모집 공고':
            raise ValueError('뉴딜 원모집의 공고 단계 불일치')
        replay._detail(n, encoded, digest)
    else:
        canonical, _ = _press_detail_url(n['url'], _FUND)
        raw = _decode(encoded, replay.MAX_DETAIL_BYTES)
        if canonical != n['url'] or replay._sha(raw) != digest:
            raise ValueError('뉴딜 최종 결과의 원문 주소·지문 불일치')
        detail, pdf = _press_result_detail_dom(raw, {**n, 'board_record_id': key[1]}, _FUND, digest)
        if (n['event_type'] != '선정 결과' or n['body'] != detail['body'] or n['sha256'] != detail['body_text_sha256']
                or n['attachments'] != [a['url'] for a in detail['attachments']]
                or set(n['attachment_hashes']) != {pdf['url']}):
            raise ValueError('뉴딜 최종 결과의 본문·첨부 원문 불일치')
    return n


def _source_notice(fields, detail_receipt):
    return {**fields, 'history_import': NOTICE_KIND, 'source_channel': 'kgrowth_joint_history',
            'institution_id': 'kgrowth', 'checked_at': detail_receipt['checked_at'],
            'joint_history_proof': {'detail_base64': detail_receipt['raw_base64'],
                                    'detail_sha256': detail_receipt['sha256']}}


def project(source, checked_at):
    """Read facts from bound originals. Neither prepared facts nor network access are inputs."""
    if (not isinstance(source, dict) or set(source) != _SOURCE_KEYS
            or source.get('kind') != BUNDLE_KIND or source.get('institution_id') != 'kdb'
            or not isinstance(source['press'], dict) or set(source['press']) != set(_ROLES)
            or not isinstance(source['attachments'], dict) or not 1 <= len(source['attachments']) <= 8):
        raise ValueError('뉴딜 공동 과거 원본 묶음 형식 불일치')
    maximum = replay.MAX_INPUT_BYTES
    bundle = _decode(source['bundle'], maximum)
    capture = json.loads(_decode(source['recruitment'], maximum))
    press = {role: _decode(source['press'][role], maximum) for role in _ROLES}

    def attachment(sha):
        return _decode(source['attachments'][sha], replay.MAX_FILE_BYTES)

    reviewed = review_newdeal_growth_selection(bundle, capture, attachment, press, checked_at=checked_at)
    program = reviewed['program']
    program.pop('publication_ready')
    program['joint_history_bundle_sha256'] = hashlib.sha256(bundle).hexdigest()
    recruitment_proof = reviewed['recruitment_proof']
    recruitment_url = recruitment_proof['url']
    original, = [n for n in json.loads(bundle)['notices'] if n['url'] == recruitment_url]
    capture_receipt, = [r for r in capture['responses'] if r['url'] == recruitment_url]
    recruitment = _source_notice(
        {**{k: original[k] for k in replay._FIELDS}, 'event_type': '모집 공고',
         'attachment_hashes': original['attachment_hashes']}, capture_receipt)
    result_proof = reviewed['official_result_proof']
    detail, pdf = result_proof['detail'], result_proof['source_pdf']
    result_receipt, = json.loads(press['detail'])['receipts']
    result_url = result_proof['source_detail']['url']
    result = _source_notice(
        {**{k: detail[k] for k in ('title', 'date', 'body')}, 'event_type': '선정 결과', 'url': result_url,
         'source_id': source_key(result_url)[1], 'sha256': detail['body_text_sha256'],
         'attachments': [a['url'] for a in detail['attachments']], 'attachment_hashes': {pdf['url']: pdf['sha256']}},
        result_receipt)
    program['extraction_evidence'] = {
        'joint_recruitment': [{'source_url': recruitment_url, 'sha256': recruitment['sha256'],
                              'attachment_sha256': a['sha256']} for a in recruitment_proof['attachments']],
        'joint_result': [{'source_url': result_url, 'sha256': result['sha256'],
                          'attachment_sha256': pdf['sha256']}],
    }
    return program, [validate_retained_notice(n, checked_at) for n in (recruitment, result)]


def assert_no_overlap(current_programs, program, sources):
    keys = {source_key(n['url']) for n in sources}
    first_posted = next(e['date'] for e in program['events'] if e['type'] == '모집 공고')
    for old in current_programs:
        title = compact(old['title'])
        same_recruitment_day = any(e['type'] == '모집 공고' and e['date'] == first_posted for e in old['events'])
        same_business = (old.get('joint_history_identity') == program['joint_history_identity']
                         or (compact(_FUND) in title and '수시' not in title
                             and ('2021' in title or same_recruitment_day)))
        shares_source = any(source_key(event['url']) in keys for event in old['events'])
        if same_business or shares_source:
            if (old['id'] != program['id'] or old['institution_id'] != program['institution_id']
                    or old.get('source_program_key') != program['source_program_key']):
                raise ValueError('뉴딜 공동 원문·사업연도·리그가 기존 공개 사업과 겹침')


def project_followup(source, current_programs, checked_at):
    """Replay one FAQ on the existing, independently selected KDB track."""
    if (not isinstance(source, dict) or set(source) != {'kind', 'institution_id', 'bundle', 'detail', 'faq_pdf'}
            or source.get('kind') != FOLLOWUP_BUNDLE_KIND or source.get('institution_id') != 'kdb'):
        raise ValueError('뉴딜 FAQ 과거 원본 묶음 형식 불일치')
    bundle_raw = _decode(source['bundle'], replay.MAX_INPUT_BYTES)
    bundle = json.loads(bundle_raw)
    group, notices = replay.target_group(bundle, review_scope=replay.NEWDEAL_FOLLOWUPS)
    original, = notices
    identity = {'target_institution_id': 'kdb', **{k: v for k, v in group['identity'].items() if k != 'kind'}}
    owners = [p for p in current_programs if p.get('joint_history_identity') == identity]
    if len(owners) != 1:
        raise ValueError('공개된 뉴딜성장형의 사업·회차 고유성이 미확인')
    program, = owners
    if (program['institution_id'] != 'kdb' or program.get('joint_history_track_keys') != ['blind_newdeal_growth']
            or program.get('joint_history_bundle_sha256') != replay._sha(bundle_raw)
            or program['status'] != '선정 완료' or program.get('manual_review_id')):
        raise ValueError('기존 뉴딜성장형의 원본·리그·선정 단계 불일치')
    original_events = [e for e in program['events'] if e['type'] == '모집 공고']
    if len(original_events) != 1 or not program.get('deadline') or not program.get('schedule_stages'):
        raise ValueError('기존 뉴딜성장형 모집·접수 일정 누락')
    key = source_key(original['url'])
    if any(source_key(e['url']) == key for p in current_programs if p is not program for e in p['events']):
        raise ValueError('뉴딜 FAQ 원문이 다른 공개 사업에 이미 연결됨')

    capture = json.loads(_decode(source['detail'], replay.MAX_INPUT_BYTES))
    if capture.get('holds'):
        raise ValueError('뉴딜 FAQ 상세 원본 보류')
    recovered = replay._captured(bundle, capture, notices, review_scope=replay.NEWDEAL_FOLLOWUPS, group=group)
    receipt = recovered[original['url']]
    labels = file_labels({**original, 'discovery_provenance': {'detail_response_base64': receipt['raw_base64'],
                                                             'detail_response_sha256': receipt['sha256']}})
    urls = [url for url, name in labels.items() if '기업투자' in compact(name) and 'faq' in compact(name)
            and compact(name).endswith('.pdf')]
    if len(urls) != 1:
        raise ValueError('공식 설명회에서 기업투자 FAQ PDF의 파일명과 주소 미확인')
    attachment_url, = urls
    raw_pdf = _decode(source['faq_pdf'], replay.MAX_FILE_BYTES)
    digest = replay._sha(raw_pdf)
    extracted = replay.kgrowth_attachment_text(raw_pdf)
    if (digest != original['attachment_hashes'].get(attachment_url)
            or extracted != original['attachment_texts'].get(attachment_url)):
        raise ValueError('뉴딜 FAQ의 원본 바이트·추출문 지문 불일치')
    faq_date = _faq_date(original['body'])
    text = compact(extracted)
    dated = '.'.join(str(int(part)) for part in faq_date.split('-'))
    if (not original_events[0]['date'] < original['date'] <= faq_date < program['deadline'][:10]
            or f'출자사업faq{dated}정책형뉴딜펀드운영사무국' not in text
            or not re.search(r'\(뉴딜성장형\)최소\d+개,최대\d+개운용사', text)
            or not re.search(r'뉴딜성장형[\d,]+~[\d,]+\d{2}%[\d,]+\d+산은\(단위:억원,%\)', text)):
        raise ValueError('뉴딜 FAQ 본문과 PDF의 발행일·산업은행 뉴딜성장형 구획 불일치')
    notice = _source_notice({**{k: original[k] for k in replay._FIELDS}, 'event_type': '질의응답',
                             'faq_date': faq_date, 'attachment_hashes': {attachment_url: digest}}, receipt)
    event = {'date': faq_date, 'type': '질의응답', 'title': '정책형 뉴딜펀드 기업투자 FAQ 추가', 'url': notice['url']}
    return program['id'], event, validate_retained_notice(notice, checked_at)


def append_followup(program, event):
    """Add a confirmed FAQ while preserving every existing stage and offering field."""
    if event['type'] != '질의응답':
        raise ValueError('확인된 뉴딜 FAQ만 기존 일정에 추가할 수 있음')
    previous = [e for e in program['events'] if source_key(e['url']) == source_key(event['url'])]
    if previous:
        if previous != [event]:
            raise ValueError('기존 공개 FAQ 원문·날짜와 다른 버전')
        return program
    output = copy.deepcopy(program)
    output['events'] = sorted([*output['events'], event], key=lambda e: e['date'])
    stage = {'stage': 'faq', 'label': '질의응답', 'original_label': '질의응답', 'date': event['date'],
             'precision': 'date', 'status': 'confirmed', 'source_url': event['url'], 'show_source': True,
             'detail': '기업투자 FAQ 추가'}
    output['schedule_stages'] = _schedule_order([*output['schedule_stages'], stage])
    if ([e for e in output['events'] if e != event] != program['events']
            or [s for s in output['schedule_stages'] if s != stage] != program['schedule_stages']):
        raise ValueError('뉴딜 FAQ 추가가 기존 공개 단계 순서를 변경함')
    return output
