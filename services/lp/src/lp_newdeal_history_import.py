"""Replay the official joint New Deal evidence for the historical publisher."""

import base64
import copy
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

try:
    from . import lp_kgrowth_history_replay as replay
    from .lp_history_notices import JOINT_KIND as NOTICE_KIND, JOINT_IMPORT_KIND as IMPORT_KIND
    from .lp_joint_history_projection import review_newdeal_growth_selection
    from .lp_kgrowth_press_probe import _press_detail_url, _press_result_detail_dom
    from .lp_notice_triage import compact
except ImportError:
    import lp_kgrowth_history_replay as replay
    from lp_history_notices import JOINT_KIND as NOTICE_KIND, JOINT_IMPORT_KIND as IMPORT_KIND
    from lp_joint_history_projection import review_newdeal_growth_selection
    from lp_kgrowth_press_probe import _press_detail_url, _press_result_detail_dom
    from lp_notice_triage import compact


BUNDLE_KIND = 'lp_newdeal_joint_history_source_v1'
_ROLES = ('search', 'followup', 'detail', 'failed_pdf', 'pdf')
_FUND = '정책형 뉴딜펀드'
_SOURCE_KEYS = {'kind', 'institution_id', 'bundle', 'recruitment', 'press', 'attachments'}


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
        if n['event_type'] != '모집 공고':
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
