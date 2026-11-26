"""Propose a pinned history import against one read-only operating snapshot.

Add a source-verified recruitment or append an official follow-up to one existing timeline.
Preserve existing addresses, offering terms, selection rosters and evidence catalogs.
This is an isolated import preview, not a simulation of new daily source updates,
and is never approval to publish or permission to call a write function.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from .lp_history_notices import validate_history_notice
    from .lp_notice_publication import publish_basic_notices
    from .lp_program_service import validate, assert_selected_gp_history, build
    from .lp_program_aliases import alias_pages, missing_published_ids
    from .lp_state_storage import pack_state, unpack_state, MARKER, EVIDENCE_KEYS
    from . import lp_kdb_semiconductor_2025 as kdb_semiconductor_2025
    from . import lp_kdb_materials_history_import as materials
    from . import lp_enterprise_newdeal_2022 as enterprise_2022
    from . import lp_kdb_policy_newdeal_first_2022 as policy_first_2022
    from . import lp_kdb_innovation_2023_first as innovation_first_2023
    from . import lp_newdeal_history_import as newdeal
except ImportError:
    from lp_history_notices import validate_history_notice
    from lp_notice_publication import publish_basic_notices
    from lp_program_service import validate, assert_selected_gp_history, build
    from lp_program_aliases import alias_pages, missing_published_ids
    from lp_state_storage import pack_state, unpack_state, MARKER, EVIDENCE_KEYS
    import lp_kdb_semiconductor_2025 as kdb_semiconductor_2025
    import lp_kdb_materials_history_import as materials
    import lp_enterprise_newdeal_2022 as enterprise_2022
    import lp_kdb_policy_newdeal_first_2022 as policy_first_2022
    import lp_kdb_innovation_2023_first as innovation_first_2023
    import lp_newdeal_history_import as newdeal

MAX_IMPORT_BYTES = 40 * 1024 * 1024
MAX_NOTICES = 6
_ALLOWED_CHANGED_KEYS = {'programs', 'history_notices'}
_JOINT_FOLLOWUPS = {newdeal.FOLLOWUP_IMPORT_KIND, newdeal.STAGES_IMPORT_KIND}
_JOINT_BUNDLES = {newdeal.BUNDLE_KIND: newdeal.IMPORT_KIND, newdeal.FOLLOWUP_BUNDLE_KIND: newdeal.FOLLOWUP_IMPORT_KIND,
                  newdeal.STAGES_BUNDLE_KIND: newdeal.STAGES_IMPORT_KIND,
                  materials.BUNDLE_KIND: materials.IMPORT_KIND, materials.BUNDLE_2020_KIND: materials.IMPORT_KIND,
                  enterprise_2022.BUNDLE_KIND: enterprise_2022.IMPORT_KIND,
                  policy_first_2022.BUNDLE_KIND: policy_first_2022.IMPORT_KIND,
                  innovation_first_2023.BUNDLE_KIND: innovation_first_2023.IMPORT_KIND}
_JOINT_IMPORTS = set(_JOINT_BUNDLES.values())


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _sha(value):
    return hashlib.sha256(_json(value)).hexdigest()


def retained_gp_context(context, new_programs):
    new_ids = {program['id'] for program in new_programs}
    return {**context, 'notices': [row for row in context['notices'] if row['noticeId'] not in new_ids]}


def load_import(raw, expected_sha256):
    if (not isinstance(raw, bytes) or len(raw) > MAX_IMPORT_BYTES
            or not isinstance(expected_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_sha256)
            or hashlib.sha256(raw).hexdigest() != expected_sha256):
        raise ValueError('검토한 과거 가져오기 파일의 크기·지문 불일치')
    payload = json.loads(raw)
    _validate_payload(payload)
    return payload


def _validate_payload(payload):
    joint = isinstance(payload, dict) and payload.get('kind') in _JOINT_IMPORTS
    if joint:
        if set(payload) != {'kind', 'checked_at', 'source'} or not isinstance(payload['checked_at'], str):
            raise ValueError('뉴딜 공동 과거 가져오기 형식 불일치')
    elif (not isinstance(payload, dict) or set(payload) != {'kind', 'checked_at', 'notices'}
            or payload['kind'] != 'lp_history_import_v1' or not isinstance(payload['notices'], list)
            or not 1 <= len(payload['notices']) <= MAX_NOTICES
            or not isinstance(payload['checked_at'], str)):
        raise ValueError(f'최대 {MAX_NOTICES}공고의 검토용 가져오기 형식 필요')
    stamp = datetime.fromisoformat(payload['checked_at'].replace('Z', '+00:00'))
    if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
        raise ValueError('가져오기 관측시각의 시간대·미래시각 불일치')


def _assert_preserved(current, after, updated=()):
    events = {row['id']: row['added_events'] for row in updated}
    expected = []
    for program in current['programs']:
        for event in events.get(program['id'], []):
            program = newdeal.append_followup(program, event)
        expected.append(program)
    if after['programs'][:len(current['programs'])] != expected:
        raise ValueError('기존 공개 사업 필드 변경')
    if after.get('history_notices', [])[:len(current.get('history_notices', []))] != current.get('history_notices', []):
        raise ValueError('기존 과거 원문 변경')
    before_other = {k: v for k, v in current.items() if k not in _ALLOWED_CHANGED_KEYS}
    after_other = {k: v for k, v in after.items() if k not in _ALLOWED_CHANGED_KEYS}
    if before_other != after_other:
        raise ValueError('기존 별칭·검토·관측일·다른 카탈로그 변경')
    assert_selected_gp_history(current['programs'], after['programs'])
    missing = missing_published_ids(current, after['programs'], after.get('program_aliases', {}))
    if missing:
        raise ValueError('기존 공개 주소 누락')


def build_pinned_import(bundle, programs, candidate_checked_at, expected_sha256):
    """Rebuild the reviewed import from pinned originals and live program identities."""
    source_kind = bundle.get('kind')
    if isinstance(source_kind, str) and (kind := _JOINT_BUNDLES.get(source_kind)):
        payload = {'kind': kind, 'checked_at': candidate_checked_at, 'source': bundle}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
        load_import(raw, expected_sha256)
        return payload, raw, {'source_type': source_kind}
    try:
        from .build_lp_history_import import build as build_import
    except ImportError:
        from build_lp_history_import import build as build_import
    institution = bundle.get('institution_id', '')
    if (bundle.get('kind') != 'lp_institution_history_v1'
            or not re.fullmatch(r'[a-z_]+', institution)
            or not 1 <= len(bundle.get('notices', [])) <= 400
            or any(n.get('institution_id') != institution for n in bundle['notices'])):
        raise ValueError('기관별 원문 묶음 형식·기관 불일치')
    with tempfile.TemporaryDirectory() as directory:
        (Path(directory) / (institution + '.json')).write_bytes(_json(bundle))
        payload, summary = build_import(directory, (), candidate_checked_at, live_programs=programs)
    if summary['rejected'] or summary['publication_holds']:
        raise ValueError('원문 검증·공개 범위 보류가 있는 가져오기 후보')
    # Match the existing build_lp_history_import CLI encoding exactly.
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    load_import(raw, expected_sha256)
    return payload, raw, summary


def _catalog_versions(current):
    pending = [n for key in sorted(EVIDENCE_KEYS) for n in current.get(key, [])]
    visited = 0
    while pending:
        n = pending.pop()
        visited += 1
        if visited > 20_000:
            raise ValueError('기존 원문 버전 대조 크기 상한 초과')
        if not isinstance(n, dict):
            continue
        yield n
        # Association receipts can retain the institution's original document.
        originals = n.get('original_notices', [])
        if isinstance(originals, list):
            pending.extend(originals)


def proposal(current, payload, checked_at):
    """Propose a verified historical addition with preservation checks."""
    _validate_payload(payload)
    validate(current)
    joint = payload['kind'] in _JOINT_IMPORTS
    materials_plan = payload['kind'] == materials.IMPORT_KIND
    policy_first = payload['kind'] == policy_first_2022.IMPORT_KIND
    innovation_first = payload['kind'] == innovation_first_2023.IMPORT_KIND
    followup = payload['kind'] in _JOINT_FOLLOWUPS
    if followup:
        if payload['kind'] == newdeal.FOLLOWUP_IMPORT_KIND:
            update_id, event, notice = newdeal.project_followup(payload['source'], current['programs'], checked_at)
            events, incoming = [event], [notice]
        else:
            update_id, events, incoming = newdeal.project_stages(payload['source'], current['programs'], checked_at)
        programs, holds = [], []
    elif materials_plan:
        program, incoming = materials.project(payload['source'], current['programs'], checked_at)
        programs, holds = [program], []
    elif payload['kind'] == enterprise_2022.IMPORT_KIND:
        program, incoming = enterprise_2022.project(payload['source'], current['programs'], checked_at)
        programs, holds = [program], []
    elif policy_first:
        program, incoming = policy_first_2022.project(payload['source'], current['programs'], checked_at)
        programs, holds = [program], []
    elif innovation_first:
        program, incoming = innovation_first_2023.project(payload['source'], current['programs'], checked_at)
        programs, holds = [program], []
    elif joint:
        program, incoming = newdeal.project(payload['source'], checked_at)
        newdeal.assert_no_overlap(current['programs'], program, incoming)
        programs, holds = [program], []
    else:
        incoming = [validate_history_notice(n, checked_at) for n in payload['notices']]
        programs, holds = publish_basic_notices({'programs': [], 'history_notices': incoming}, [], checked_at)
    if len({n['url'] for n in incoming}) != len(incoming):
        raise ValueError('가져올 원문 URL 중복')
    retained = {n['url']: n for n in current.get('history_notices', [])}
    if len(retained) != len(current.get('history_notices', [])):
        raise ValueError('기존 과거 원문 URL 중복')
    # Revalidate old receipts without replacing their bytes or metadata.
    for old in retained.values():
        validate_history_notice(old, checked_at)
    incoming_by_url = {n['url']: n for n in incoming}
    if any(old.get('attachment_ocr') != n.get('attachment_ocr') for url, n in incoming_by_url.items()
           if (old := retained.get(url)) is not None):
        raise ValueError('기존 과거 원문의 OCR 영수증과 가져올 버전 불일치')
    source_key = materials.source_key if materials_plan or policy_first or innovation_first else newdeal.source_key
    joint_by_key = {source_key(url): n for url, n in incoming_by_url.items()} if joint else {}
    for old in _catalog_versions(current):
        n = incoming_by_url.get(old.get('url'))
        if joint and n is None and old.get('url'):
            n = joint_by_key.get(source_key(old['url']))
        if n and (old.get('institution_id') != n['institution_id']
                  or old.get('sha256') != n['sha256']
                  or old.get('attachment_hashes', {}) != n.get('attachment_hashes', {})):
            raise ValueError('기존 원문 카탈로그의 기관·본문·첨부 버전 충돌')
    represented = {e['url'] for e in events} if followup else {e['url'] for p in programs for e in p['events']}
    if holds or represented != {n['url'] for n in incoming}:
        raise ValueError('가져오기 원문이 모두 검증된 모집 사업으로 연결되지 않음')
    after = copy.deepcopy(current)
    added, reused, updated = [], [], []
    ids = {p['id'] for p in current['programs']}
    if len(ids) != len(current['programs']):
        raise ValueError('기존 공개 사업 식별자 중복')
    aliases = current.get('program_aliases', {})
    if followup:
        index, = [i for i, p in enumerate(after['programs']) if p['id'] == update_id]
        program = after['programs'][index]
        added_events = []
        for event in events:
            once = newdeal.append_followup(program, event)
            if once != program:
                program = once
                added_events.append(event)
        if added_events:
            after['programs'][index] = program
            updated.append({'id': update_id, 'added_events': added_events})
    for p in programs:
        urls = {e['url'] for e in p['events'] if e['type'] == '모집 공고'}
        matches = []
        for old in current['programs']:
            old_urls = {e['url'] for e in old['events'] if e['type'] == '모집 공고'}
            same_key = p.get('source_program_key') and p.get('source_program_key') == old.get('source_program_key')
            shared_url = bool(urls & old_urls)
            if shared_url and old['institution_id'] != p['institution_id']:
                raise ValueError('공개 모집 원문의 기관 귀속 충돌')
            if shared_url and kdb_semiconductor_2025.distinct_offerings(p, old):
                continue
            if shared_url and p.get('source_program_key') in kdb_semiconductor_2025.KEYS.values() and not same_key:
                raise ValueError('반도체 2025년 공동 모집과 단일 기존 공개 사업의 관계 미확인')
            if old['institution_id'] == p['institution_id'] and (same_key or shared_url):
                matches.append(old)
        if len(matches) > 1 or (p['id'] in ids and not matches) or p['id'] in aliases:
            raise ValueError('기존 사업·공개 별칭과 후보 식별자 충돌')
        if matches:
            reused.append(matches[0]['id'])
            continue
        selection_urls = {e['url'] for e in p['events'] if e['type'] in ('선정 결과', '최종 선정')}
        if any(g.get('source_url') not in selection_urls for g in p['selected_gps']):
            raise ValueError('가져오기 선정 GP의 공식 결과 원문 연결 미확인')
        source = next(n for n in incoming if n['url'] in urls)
        if not joint:
            p['checked_at'] = source['checked_at']
        after['programs'].append(p)
        added.append(p)
        ids.add(p['id'])
    catalog = copy.deepcopy(current.get('history_notices', []))
    for n in incoming:
        if n['url'] not in retained:
            catalog.append(copy.deepcopy(n))
    if catalog or 'history_notices' in current:
        after['history_notices'] = catalog
    validate(after)
    _assert_preserved(current, after, updated)
    packed = pack_state(after)
    if unpack_state(packed) != after:
        raise ValueError('가져오기 후 상태 압축·복원 불일치')
    meta = packed.get(MARKER, {})
    return after, {'new_programs': added, 'reused_program_ids': reused, 'updated_programs': updated,
                   'programs_before': len(current['programs']), 'programs_after': len(after['programs']),
                   'history_notices_before': len(current.get('history_notices', [])),
                   'history_notices_after': len(catalog),
                   'existing_programs_preserved': True, 'existing_sources_preserved': True,
                   'other_state_fields_preserved': True, 'aliases_preserved': True,
                   'baseline_state_sha256': _sha(current), 'proposal_state_sha256': _sha(after),
                   'packed_state_bytes': len(_json(packed)),
                   'evidence_raw_bytes': meta.get('raw_bytes'), 'evidence_gzip_bytes': meta.get('gzip_bytes'),
                   'storage_roundtrip_verified': True}


def preflight(conn, payload, checked_at, *, source_bundle=None, candidate_checked_at=None,
              expected_sha256=None, retain_import=lambda raw: None):
    """Use a repeatable read-only transaction; return no existing private state."""
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    conn.execute("SET LOCAL statement_timeout='120s'")
    if conn.execute('SHOW transaction_read_only').fetchone()[0] != 'on':
        raise ValueError('데이터베이스 읽기 전용 거래 확인 실패')
    row = conn.execute('SELECT data,run_id,updated_at FROM lp_program_private.program_state WHERE id=1').fetchone()
    if row is None or not isinstance(row[1], str) or not row[1]:
        raise ValueError('실제 운영 상태가 있어야 사전 검증 가능')
    current = unpack_state(row[0])
    decisions = conn.execute(
        'SELECT to_jsonb(d) FROM lp_program_private.review_decisions d ORDER BY id LIMIT 1001').fetchall()
    if len(decisions) > 1000:
        raise ValueError('검토 기록 읽기 상한 초과')
    current['review_decisions'] = [d[0] for d in decisions]
    import_summary = None
    if source_bundle is not None:
        if payload is not None:
            raise ValueError('원문 재구성과 기존 후보 입력을 함께 사용할 수 없음')
        payload, raw, import_summary = build_pinned_import(
            source_bundle, current['programs'], candidate_checked_at, expected_sha256)
        retain_import(raw)
    after, result = proposal(current, payload, checked_at)
    profiles = current.get('gp_profile_contract', {}).get('profiles', {})
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        # The renderer adds nested GP page keys; isolate those display fields
        # from both the retained evidence and the proposed stored state.
        context = build(copy.deepcopy(after), out, gp_profiles=profiles)['public_notice_context']
        previous_context = current.get('public_notice_context')
        gp_context_preserved = previous_context is None or retained_gp_context(context, result['new_programs']) == previous_context
        generated_aliases = alias_pages(after['programs'], after.get('program_aliases', {}))
        if any((out / name).exists() for name in generated_aliases):
            raise ValueError('기존 별칭 주소와 새 공개 페이지 충돌')
        files = list(out.glob('*.html'))
        page_bytes = sum(p.stat().st_size for p in files)
        _assert_preserved(current, after, result['updated_programs'])
    return {**result, 'kind': 'lp_history_import_preflight_v1', 'checked_at': checked_at,
            'import_build_summary': import_summary,
            'existing_gp_context_preserved': gp_context_preserved,
            'baseline_run_id': row[1], 'baseline_updated_at': str(row[2]),
            'built_pages': len(files) + len(generated_aliases),
            'pages_bytes': page_bytes + sum(len(s.encode()) for s in generated_aliases.values()),
            'official_http_requests': 0, 'database_writes': 0, 'published': False,
            'approval_required': True, 'requires_recheck_before_publish': True,
            'scope': '고정 과거 원문의 사업 또는 후속 단계와 기존 공개본 보존을 비교'}


def main(argv=None):
    import argparse
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--import-file', type=Path)
    mode.add_argument('--bundle', type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--candidate-checked-at')
    parser.add_argument('--candidate-output', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    source = args.import_file or args.bundle
    for path in (args.output, args.candidate_output):
        if path and (path.exists() or path.is_symlink() or path.resolve() == source.resolve()):
            parser.error('기존 원본·검증 결과를 덮어쓸 수 없습니다')
    if args.candidate_output and args.candidate_output.resolve() == args.output.resolve():
        parser.error('후보 원문과 검증 결과는 다른 경로여야 합니다')
    if args.bundle and (not args.candidate_checked_at or not args.candidate_output):
        parser.error('원문 재구성에는 고정 관측시각·새 후보 출력 경로가 필요합니다')
    if source.stat().st_size > MAX_IMPORT_BYTES:
        parser.error('검토용 가져오기 크기 제한 초과')
    raw = source.read_bytes()
    payload = load_import(raw, args.sha256) if args.import_file else None
    bundle = json.loads(raw) if args.bundle else None
    def retain(candidate):
        args.candidate_output.parent.mkdir(parents=True, exist_ok=True)
        with args.candidate_output.open('xb') as handle:
            handle.write(candidate)
    import psycopg
    with psycopg.connect(os.environ['SUPABASE_DB_URL'], connect_timeout=20,
                        prepare_threshold=None, application_name='lp-history-import-preflight') as conn:
        result = preflight(conn, payload, datetime.now(timezone.utc).isoformat(), source_bundle=bundle,
                           candidate_checked_at=args.candidate_checked_at,
                           expected_sha256=args.sha256, retain_import=retain if args.bundle else lambda raw: None)
    result['candidate_sha256'] = args.sha256
    result['candidate_bytes'] = args.candidate_output.stat().st_size if args.bundle else len(raw)
    result['candidate_checked_at'] = args.candidate_checked_at if args.bundle else payload['checked_at']
    result['source_bundle_sha256'] = hashlib.sha256(raw).hexdigest() if args.bundle else None
    commit = os.environ.get('GITHUB_SHA')
    if commit is not None and not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('검증 실행의 코드 commit 식별자 불일치')
    result['source_code_commit'] = commit
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('baseline_run_id', 'programs_before', 'programs_after',
                                           'existing_programs_preserved', 'packed_state_bytes',
                                           'database_writes', 'published')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
