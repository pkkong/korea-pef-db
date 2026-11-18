"""Offline KDB candidates from hash-bound, KGrowth-hosted joint originals.

This module never reassigns a source document, accepts prepared review facts,
opens an operating connection, or grants publication permission. A decisive
recruitment attachment can support a basic candidate while an explicitly
advertised supplementary guideline remains missing. The full replay hold is
preserved separately. No result roster is inferred from a recruitment plan.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

try:
    from . import lp_kgrowth_history_replay as replay
    from .lp_kgrowth_history_terms import review_bundle, _identity as notice_identity
    from .lp_kgrowth_scaleup_history import compact
    from .lp_notice_publication import _rule_valid_name
    from .lp_notice_triage import notice_stage
    from .lp_program_service import validate
except ImportError:
    import lp_kgrowth_history_replay as replay
    from lp_kgrowth_history_terms import review_bundle, _identity as notice_identity
    from lp_kgrowth_scaleup_history import compact
    from lp_notice_publication import _rule_valid_name
    from lp_notice_triage import notice_stage
    from lp_program_service import validate


KIND = 'lp_joint_history_projection_review_v1'
_TARGET = 'kdb'
_TARGET_NAME = '한국산업은행'
MAX_BUNDLE_BYTES = 40 * 1024 * 1024


def _stamp(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('검증·관측시각의 시간대 누락')
    return stamp


class _Links(HTMLParser):
    def __init__(self, source_url):
        super().__init__(convert_charrefs=True)
        self.source_url, self.labels, self.current = source_url, {}, None

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            attrs = dict(attrs)
            self.current = (urljoin(self.source_url, attrs.get('href', '')),
                            [attrs.get('title', '')])

    def handle_data(self, data):
        if self.current:
            self.current[1].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.current:
            url, words = self.current
            self.labels.setdefault(url, []).append(' '.join(words))
            self.current = None


def _missing_guidelines(n, joint, capture):
    """Recognize only the source-advertised, referenced XLSX supplement layout."""
    missing = sorted(set(n['attachments']) - set(n['attachment_hashes']))
    if not missing:
        return []
    if len(missing) != 1 or 'current_strategy' not in joint['evidence']:
        raise ValueError('미확보 첨부의 용도·모집 핵심 여부 미확인')
    strategy = compact(joint['evidence']['current_strategy']['quote'])
    if '별도엑셀파일참고' not in strategy:
        raise ValueError('현재 모집 첨부의 별도 엑셀 참조 미확인')
    encoded = n['discovery_provenance'].get('detail_response_base64')
    if encoded is None:
        encoded = next((r['raw_base64'] for r in (capture or {}).get('responses', [])
                        if r['url'] == n['url']), None)
    if encoded is None:
        raise ValueError('미확보 첨부의 상세 원문 이름 미확인')
    links = _Links(n['url'])
    links.feed(base64.b64decode(encoded, validate=True).decode('cp949'))
    name = r'뉴딜투자가이드라인상분야및품목(?:\(6대핵심산업포함\))?\.xlsx'
    labels = links.labels.get(missing[0], [])
    if not labels or any(not re.search(name, compact(label)) for label in labels):
        raise ValueError('미확보 첨부가 원문에 명시된 분야·품목 XLSX인지 미확인')
    return [{'url': missing[0], 'advertised_labels': labels,
             'content_read': False, 'reason': '분야·품목 가이드라인 XLSX 원본·지문 미확보'}]


def _identity(joint):
    identity = {'target_institution_id': _TARGET, **joint['identity']}
    # Both formats have one blind recruitment family per explicit fund/round.
    # The enterprise attachment, not its neighbouring citizen/infra files, is
    # already isolated by the dedicated parser's mandatory heading.
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return identity, digest


def _change_title_identity(title, expected):
    """Read explicit title keys only; missing keys never inherit a post year.

    Unquoted amendments are common. Recognizing the full family name is enough
    to hold its old terms when the business year/round cannot be established;
    it is not enough to attach the amendment as a confirmed lifecycle event.
    """
    title = compact(title)
    fund = compact(expected['fund'])
    if fund not in title:
        return None
    quoted = re.findall(r'[「『]([^」』]+)[」』]', title)
    if quoted:
        families = [re.sub(r'\(?제?[1-9]\d*차(?:년도)?\)?|20\d{2}년?도?', '', q) for q in quoted]
        if fund not in families:
            return None  # A longer, explicitly quoted fund is a different family.
    header = re.split(r'위탁운용사|운용사선정|선정계획|출자사업|제안서|접수|마감|모집조건|모집일정',
                      title, maxsplit=1)[0]
    # An extension's new calendar deadline is not its business year.
    years = set(re.findall(r'20\d{2}', header))
    rounds = {re.sub(r'^제', '', r) for r in re.findall(r'제?[1-9]\d*차(?:년도)?', header)}
    rounds.update(re.findall(r'정시|수시', header))
    if len(years) == 1 and years != {expected['year']}:
        return None
    if len(rounds) == 1 and rounds != {expected['round']}:
        return None
    if years != {expected['year']} or rounds != {expected['round']} or len(quoted) > 1:
        return '같은 펀드명의 모집조건 후속 검토; 명시 사업 연도·회차 식별 미확인'
    return '같은 펀드·사업연도·회차의 모집 정정·연장·취소'


def _terms_changes(bundle, joint):
    changes = []
    for n in bundle['notices']:
        if (n['url'] == joint['source_url'] or n['date'] < joint['posted_date']
                or notice_stage(n['title']) != '변경 공고'):
            continue
        # A corrected result is not an amended recruitment/deadline. It needs
        # a separate track-specific result parser before any lifecycle link.
        if re.search(r'선정\s*결과|접수\s*(?:결과|현황)|심사\s*결과|최종\s*결과|우선협상대상자', n['title']):
            continue
        reason = _change_title_identity(n['title'], joint['identity'])
        if reason:
            changes.append({'url': n['url'], 'reason': reason})
    return sorted(changes, key=lambda c: (c['url'], c['reason']))


def _funding(tracks):
    total = sum(t['planned_commitment_total_krw'] for t in tracks)
    own = [(t.get('planned_contributions_krw') or {}).get(_TARGET_NAME) for t in tracks]
    return {'basis': 'joint_contributors_recruitment_plan',
            'planned_joint_commitment_total_krw': total,
            'lead_institution_own_planned_krw': sum(own) if all(v is not None for v in own) else None,
            'planned_formation_target_krw': sum(t['planned_formation_total_krw'] for t in tracks),
            'pe_annual_own_commitment_eligible': False, 'actual_gp_allocation_krw': None}


def _evidence_hashes(value, depth=0):
    if depth > 8:
        raise ValueError('기존 사업 근거의 중첩 상한 초과')
    if isinstance(value, dict):
        found = {v for k, v in value.items() if k in ('sha256', 'attachment_sha256', 'body_sha256')
                 and isinstance(v, str) and re.fullmatch('[a-f0-9]{64}', v)}
        for child in value.values():
            found |= _evidence_hashes(child, depth + 1)
        return found
    if isinstance(value, list):
        return set().union(*(_evidence_hashes(v, depth + 1) for v in value))
    return set()


def _existing_match(existing, n, identity, track_keys, program_id, program_key, decisive_hashes):
    matches = []
    for p in existing:
        urls = {e['url'] for e in p['events'] if e['type'] == '모집 공고'}
        same_url = n['url'] in urls
        same_key = p.get('source_program_key') == program_key
        stored_identity = p.get('joint_history_identity')
        same_identity = stored_identity == identity
        title_identity = None
        if re.search(r'[「『]', p['title']):
            try:
                title_identity = notice_identity({'title': p['title'], 'date': min(
                    (e['date'] for e in p['events'] if e['type'] == '모집 공고'), default=n['date'])})
            except ValueError:
                if same_url:
                    raise ValueError('기존 모집 제목의 사업 식별 근거 미확인')
        same_title = title_identity == {k: identity[k] for k in ('fund', 'year', 'round')}
        if not (same_url or same_key or same_identity or same_title or p['id'] == program_id):
            continue
        if p['institution_id'] != _TARGET:
            raise ValueError('같은 원문·사업키·ID에 다른 기관의 기존 사업이 있음')
        if stored_identity is not None and not same_identity:
            raise ValueError('기존 공동 사업의 펀드·사업연도·회차 충돌')
        if p.get('joint_history_track_keys') is not None and set(p['joint_history_track_keys']) != set(track_keys):
            raise ValueError('같은 모집 주소의 기존 리그 범위 충돌')
        for key, expected in (('business_year', identity['year']), ('business_round', identity['round'])):
            if p.get(key) is not None and str(p[key]) != expected:
                raise ValueError('기존 사업의 명시 연도·회차 충돌')
        same_hash = bool(_evidence_hashes(p.get('extraction_evidence', {})) & decisive_hashes)
        if not (same_url or same_key or same_identity or (same_title and same_hash)):
            if same_title:
                raise ValueError('같은 사업·연도·회차의 기존 사업이 있으나 원문 동일 근거 미확인')
            raise ValueError('후보 ID가 다른 기존 사업과 충돌')
        # A legacy source-URL match cannot silently override explicit title
        # identity. Curated titles without quoted identity stay reuse proposals.
        if same_url and stored_identity is None and title_identity is not None:
            if not same_title:
                raise ValueError('기존 모집 원문과 제목의 사업 식별 근거 충돌')
        matches.append(p)
    if len(matches) > 1:
        raise ValueError('복수 기존 사업과 연결됨; 기존 주소·리그 범위 검토 필요')
    return matches[0] if matches else None


def _candidate(bundle, joint, n, receipt, raw_replay, capture, existing, checked_at):
    if (joint['source_host_institution_id'] != n['institution_id'] or n['institution_id'] != 'kgrowth'
            or _TARGET not in joint['joint_issuer_institution_ids']):
        raise ValueError('게시기관 보존·공동 명의 증명 실패')
    if not receipt['detail']:
        raise ValueError('공동 모집의 검증된 상세 원본 없음')
    replayed = {a['url']: a for a in receipt['attachments']}
    for e in joint['evidence'].values():
        if (e['source_url'] != n['url'] or e['sha256'] != n['sha256']
                or e['attachment_url'] not in replayed
                or replayed[e['attachment_url']]['sha256'] != e['attachment_sha256']
                or e['quote'] not in n['attachment_texts'][e['attachment_url']]):
            raise ValueError('모집 핵심 첨부의 원본·지문·인용 재생 미확인')
    missing = _missing_guidelines(n, joint, capture)
    source_holds = [h for h in raw_replay['holds'] if h['url'] == n['url']]
    if source_holds and not (missing and all(h['reason'] == '관측 첨부의 원본 지문 없음' for h in source_holds)):
        raise ValueError('상세·첨부 원본 재생 충돌 또는 미확보')
    if set(n['attachment_hashes']) != set(replayed):
        raise ValueError('확보된 첨부 중 재생하지 못한 원본이 있음')
    changes = _terms_changes(bundle, joint)
    if changes:
        raise ValueError('후속 모집 정정·연장·취소 검토; 원조건 현재값 사용 보류: '
                         + '; '.join(c['url'] + ' (' + c['reason'] + ')' for c in changes))
    tracks = [copy.deepcopy(t) for t in joint['tracks']
              if t['program_lead_institution_id'] == _TARGET and t['fund_kind'] == 'blind']
    if len(tracks) != 2 or any(t['selected_managers'] for t in tracks):
        raise ValueError('KDB 블라인드 두 모집 리그 또는 빈 결과 명단 경계 미확인')
    keys = [t.get('key') or t['label'] for t in tracks]
    if len(set(keys)) != len(keys) or len({t['deadline'] for t in tracks}) != 1:
        raise ValueError('리그 식별자 중복 또는 접수 마감 충돌')
    legal = joint['evidence'].get('legal_scope', joint['evidence'].get('current_legal_forms'))
    if not legal or not all(token in compact(legal['quote']) for token in ('경영참여형사모집합투자기구', '벤처투자조합')):
        raise ValueError('현재 출자대상의 PE 포함·VC 기구 공동 허용 미확인')
    identity, digest = _identity(joint)
    program_id = f"{_TARGET}-{identity['year']}-{digest[:16]}"
    program_key = 'joint:' + digest
    funding = _funding(tracks)
    end = _stamp(tracks[0]['deadline'])
    if end < _stamp(joint['issued_date'] + 'T00:00:00+09:00'):
        raise ValueError('발행·접수 마감 순서 충돌')
    program = {'id': program_id, 'institution_id': _TARGET, 'institution_name': _TARGET_NAME,
               'title': n['title'], 'asset_scope': 'PE·VC 공동 모집',
               'status': '접수 마감' if end < _stamp(checked_at) else '접수 중',
               'basic_publication': True, 'source_program_key': program_key,
               'joint_history_identity': identity, 'joint_history_track_keys': sorted(keys),
               'business_year': identity['year'], 'business_round': identity['round'],
               'terms_status': 'original_recruitment_plan', 'selected_gps': [],
               'checked_at': n['checked_at'], 'deadline': tracks[0]['deadline'], 'deadline_precision': 'datetime',
               'commitment_label': f"공동출자자 모집 계획 {funding['planned_joint_commitment_total_krw']/100_000_000:,.0f}억원 (PE·VC 포함)",
               'funding_plan': copy.deepcopy(funding),
               'events': [{'date': n['date'], 'type': '모집 공고', 'title': n['title'], 'url': n['url']}],
               'publication_ready': False}
    validate({'as_of': checked_at[:10], 'programs': [program]})
    previous = _existing_match(existing or [], n, identity, keys, program_id, program_key,
                               {e['attachment_sha256'] for e in joint['evidence'].values()})
    return {'candidate_id': 'joint-' + program_id, 'identity': identity, 'identity_sha256': digest,
            'source_document': copy.deepcopy(n), 'source_replay': copy.deepcopy(receipt),
            'joint_issuer_institution_ids': copy.deepcopy(joint['joint_issuer_institution_ids']),
            'target_institution_id': _TARGET, 'issued_date': joint['issued_date'],
            'posted_date': n['date'], 'terms_status': joint['terms_status'],
            'tracks': tracks, 'funding_plan': funding, 'evidence': copy.deepcopy(joint['evidence']),
            'board_attribution_evidence': copy.deepcopy(joint['board_attribution_evidence']),
            'minimum_recruitment_evidence_verified': True,
            'source_full_replay_complete': not source_holds and not missing,
            'missing_advertised_attachments': missing,
            'existing_match_status': 'reuse_proposed' if previous else 'no_match' if existing is not None else 'not_checked',
            'program': None if previous else program,
            'reuse_proposal': {'program_id': previous['id'], 'existing_program': copy.deepcopy(previous),
                               'overwrite_existing_fields': False} if previous else None,
            'holds': ['해당 KDB 트랙의 공식 결과·선정 명단 별도 확인 필요',
                      '기존 사업·운영 보존 검증과 별도 공개 승인 전'], 'publication_ready': False}


def review_joint_candidates(bundle, capture, load_attachment, *, checked_at, existing_programs=None):
    """Recompute source proof and return offline candidates; no DB/HTTP/approval.

    ``load_attachment`` supplies retained bytes by SHA. A review/replay report is
    deliberately not an input. A reused public program is returned unmodified
    in ``reuse_proposal`` and never replaced by a newly parsed recruitment.
    IDs ignore input order; a capture still pins its exact original bundle.
    """
    result = {'kind': KIND, 'publication_ready': False, 'published': False,
              'official_http_requests': 0, 'database_reads': 0, 'database_writes': 0,
              'prepared_at': checked_at, 'candidates': [], 'holds': [], 'source_replay': None}
    try:
        limit = _stamp(checked_at)
        if limit > datetime.now(timezone.utc):
            raise ValueError('미래 검증시각')
        if not callable(load_attachment):
            raise ValueError('보관 첨부 바이트 loader가 필요함')
        if len(json.dumps(bundle, ensure_ascii=False).encode()) > MAX_BUNDLE_BYTES:
            raise ValueError('과거 원문 묶음 40MiB 상한 초과')
        review = review_bundle(bundle, valid_name=_rule_valid_name)
        result['metadata_check'] = copy.deepcopy(review['metadata_check'])
        result['joint_parse_holds'] = copy.deepcopy(review['joint_holds'])
        if review['metadata_check']['errors'] or review['joint_holds']:
            raise ValueError('보관 목록·본문 메타 또는 공동 모집 판독 실패')
        result['review_summary'] = review['summary']
        if existing_programs is not None:
            if not isinstance(existing_programs, (list, tuple)) or len(existing_programs) > 1000:
                raise ValueError('기존 사업 입력 형식·크기 상한 초과')
            validate({'as_of': checked_at[:10], 'programs': existing_programs})
            if any(not isinstance(p.get('institution_id'), str)
                   or not re.fullmatch('[a-z0-9_]+', p['institution_id']) for p in existing_programs):
                raise ValueError('기존 사업의 기관 식별자 미확인')
        raw = replay.replay_group(bundle, load_attachment, capture=capture, review_scope='joint_originals')
        result['source_replay'] = raw
        result['holds'].extend(copy.deepcopy(raw['holds']))
        receipts = {r['url']: r for r in raw['notices']}
        notices = {n['url']: n for n in bundle['notices']}
        for joint in review['joint_offerings']:
            if joint['source_url'] not in receipts:
                continue  # The existing bounded selection reports the remainder.
            n = notices[joint['source_url']]
            if (_stamp(n['checked_at']) > limit or n['date'] > n['checked_at'][:10]
                    or any(_stamp(r['checked_at']) > limit for r in (capture or {}).get('responses', []))):
                raise ValueError('원문·보완 관측시각이 검증시각보다 늦음')
            try:
                result['candidates'].append(_candidate(bundle, joint, n, receipts[n['url']], raw,
                                                       capture, existing_programs, checked_at))
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                result['holds'].append({'stage': 'joint_projection', 'url': n['url'], 'reason': str(exc)})
        result['candidates'].sort(key=lambda c: (c['identity']['fund'], c['identity']['year'], c['identity']['round']))
    except (ValueError, KeyError, TypeError, OSError, UnicodeError) as exc:
        result['candidates'] = []
        result['holds'].append({'stage': 'joint_source_validation', 'reason': str(exc)})
    return result


def review_newdeal_growth_selection(bundle_bytes, recruitment_capture, load_attachment, press_captures, *,
                                    checked_at, existing_programs=None):
    """Bind the KDB PE track to the official result, using only saved originals."""
    try:
        from .lp_kgrowth_newdeal_joint_history import read_newdeal_growth_result_pdf
        from .lp_kgrowth_press_probe import replay_press_result_pdf
    except ImportError:
        from lp_kgrowth_newdeal_joint_history import read_newdeal_growth_result_pdf
        from lp_kgrowth_press_probe import replay_press_result_pdf

    stages = ('search', 'followup', 'detail', 'failed_pdf', 'pdf')
    if (not isinstance(bundle_bytes, bytes) or not 0 < len(bundle_bytes) <= MAX_BUNDLE_BYTES
            or not isinstance(press_captures, dict) or set(press_captures) != set(stages)
            or any(not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BUNDLE_BYTES for raw in press_captures.values())):
        raise ValueError('뉴딜 모집·결과 원본 묶음 형식·크기 불일치')
    bundle = json.loads(bundle_bytes)
    captures = {name: json.loads(raw) for name, raw in press_captures.items()}
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in press_captures.items()}
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    if any(not isinstance(c, dict) or c.get('context_bundle_sha256') != bundle_sha for c in captures.values()):
        raise ValueError('모집 원문과 결과 조회의 묶음 지문 불일치')
    links = {'followup': {'prior': 'search'}, 'detail': {'prior': 'search', 'followup': 'followup'},
             'failed_pdf': {'prior': 'search', 'followup': 'followup', 'result': 'detail'},
             'pdf': {'prior': 'search', 'followup': 'followup', 'result': 'detail', 'failed': 'failed_pdf'}}
    if any(captures[stage].get(key + '_capture_sha256') != hashes[source]
           for stage, refs in links.items() for key, source in refs.items()):
        raise ValueError('결과 목록·상세·첨부 영수증 연결 지문 불일치')

    review = review_joint_candidates(bundle, recruitment_capture, load_attachment,
                                     checked_at=checked_at, existing_programs=existing_programs)
    matches = [c for c in review['candidates'] if any(t.get('key') == 'blind_newdeal_growth' for t in c['tracks'])]
    if len(matches) != 1 or matches[0]['reuse_proposal'] is not None:
        raise ValueError('뉴딜성장형 모집 원문 미확인 또는 기존 사업 재사용 검토 필요')
    candidate = matches[0]
    track = next(t for t in candidate['tracks'] if t['key'] == 'blind_newdeal_growth')
    raw, proof = replay_press_result_pdf(captures['search'], captures['followup'], captures['detail'], captures['pdf'],
                                         replay.press_search_terms(bundle), prior_failure=captures['failed_pdf'],
                                         checked_at=checked_at)
    identity = candidate['identity']
    detail = proof['detail']
    if (detail['stated_business_year'] != identity['year'] or detail['stated_round'] != identity['round']
            or not track['deadline'][:10] <= detail['date'] <= checked_at[:10]):
        raise ValueError('뉴딜 공식 결과의 사업연도·회차 또는 접수 마감 이후 게시일 불일치')
    selection = read_newdeal_growth_result_pdf(raw, candidate)
    source = candidate['source_document']
    result_url = proof['source_detail']['url']
    track_identity = {**identity, 'track': track['key']}
    digest = hashlib.sha256(json.dumps(track_identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    names = selection['selected_managers']
    strategy = track['strategy']
    program = {'id': f"{_TARGET}-{identity['year']}-{digest[:16]}",
               'institution_id': _TARGET, 'institution_name': _TARGET_NAME,
               'title': f"정책형 뉴딜펀드 {identity['year']}년 {identity['round']} · {track['label']}",
               'asset_scope': 'PE', 'status': '선정 완료', 'basic_publication': True,
               'source_program_key': 'joint-track:' + digest, 'joint_history_identity': copy.deepcopy(identity),
               'joint_history_track_keys': [track['key']], 'business_year': identity['year'],
               'business_round': identity['round'], 'checked_at': proof['source_pdf']['checked_at'],
               'deadline': track['deadline'], 'deadline_precision': 'datetime',
               'funding_plan': _funding([track]),
               'commitment_label': f"공동 정책출자 예정 {track['planned_commitment_total_krw'] / 10**8:,.0f}억원",
               'fund_target_label': f"{track['planned_formation_total_krw'] / 10**8:,.0f}억원",
               'primary_investment': {'source_url': source['url'], 'items': [
                   f"목표결성금액의 {strategy['newdeal_min_investment_pct']}% 이상을 뉴딜 지침의 {strategy['newdeal_field_count']}개 분야에 투자",
                   f"목표결성금액의 {strategy['domestic_sme_min_investment_pct']}% 이상을 국내 중소·중견기업에 투자"]},
               'events': [copy.deepcopy(candidate['program']['events'][0]),
                          {'date': detail['date'], 'type': '선정 결과', 'title': detail['title'], 'url': result_url}],
               'selected_gps': [{'name': name, 'id': _TARGET + '-' + hashlib.sha256(name.encode()).hexdigest()[:16],
                                 'asset_scope': 'PE', 'source_url': result_url} for name in names],
               'gp_tracks': {name: track['label'] for name in names},
               'manager_list_sources': {'selected_gps': result_url}, 'publication_ready': False}
    validate({'as_of': checked_at[:10], 'programs': [program]})
    return {'identity': copy.deepcopy(identity), 'track': copy.deepcopy(track), 'selection': selection, 'program': program,
            'recruitment_proof': candidate['source_replay'], 'official_result_proof': proof,
            'capture_sha256': hashes, 'existing_match_status': candidate['existing_match_status'],
            'publication_ready': False, 'published': False}
