"""Recover and replay one source-discovered historical KGrowth group.

The text review selects a supported offering with an official PE roster, or a
bounded batch of hosted joint originals. No notice IDs are supplied by an
operator. A capture only fetches missing detail
pages, once each, and saves bounded responses before parsing. Attachments are
reused from the original collection artifact. This module never writes a DB,
projects a public program, or treats successful replay as domestic PE approval.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from .lp_kgrowth_history_terms import review_bundle
    from .kgrowth_listing import source_id
    from .lp_notice_publication import _rule_valid_name
    from .collect_lp_history_bodies import read_body
    from .collect_lp_institution_history import kgrowth_attachment_text
    from .lp_history_sources import canonical_url
except ImportError:
    from lp_kgrowth_history_terms import review_bundle
    from kgrowth_listing import source_id
    from lp_notice_publication import _rule_valid_name
    from collect_lp_history_bodies import read_body
    from collect_lp_institution_history import kgrowth_attachment_text
    from lp_history_sources import canonical_url

KIND = 'lp_kgrowth_history_capture_v1'
MAX_DETAIL_BYTES = 12 * 1024 * 1024
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_INPUT_BYTES = 40 * 1024 * 1024
_FIELDS = ('source_id', 'url', 'title', 'date', 'body', 'sha256', 'attachments')
REVIEW_SCOPES = ('pe_roster', 'joint_originals')
CAPTURE_SCOPES = REVIEW_SCOPES + ('press_listing', 'press_search', 'press_followup', 'press_result')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _bundle_sha(bundle):
    # Parsed JSON identity; the request separately pins the original file SHA.
    return _sha(json.dumps(bundle, ensure_ascii=False, sort_keys=True).encode())


def _stamp(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('원문 관측시각의 시간대 누락')
    return stamp


def target_group(bundle, *, review_scope='pe_roster'):
    """Choose a complete reviewable group; no hand-picked notice-ID queue."""
    if review_scope not in REVIEW_SCOPES:
        raise ValueError('지원하지 않는 원문 검토 범위')
    report = review_bundle(bundle, valid_name=_rule_valid_name)
    if report['metadata_check']['errors']:
        raise ValueError('보관 목록·본문 메타 검증 실패')
    if review_scope == 'joint_originals':
        if report['joint_holds']:
            raise ValueError('공동 모집 판독 보류를 먼저 확인해야 함')
        candidates = sorted(report['joint_offerings'], key=lambda g: (
            g['identity']['fund'], g['identity']['year'], g['identity']['round'], g['source_url']))
        if not candidates:
            raise ValueError('자동 판독된 공동 원모집이 없음')
        identities = [tuple(g['identity'][k] for k in ('fund', 'year', 'round')) for g in candidates]
        if len(set(identities)) != len(identities):
            raise ValueError('공동 원모집의 사업·연도·회차 중복')
        selected = candidates[:2]
        group = {'identity': {'kind': 'hosted_joint_originals',
                             'programs': [g['identity'] for g in selected]},
                 'remaining_candidates': len(candidates) - len(selected)}
        urls = {g['source_url'] for g in selected}
    else:
        candidates = [g for g in report['groups'] if g['offering'] and g['rosters']]
        if not candidates:
            return None, []
        group = candidates[0]  # review groups already have stable fund/year/round order
        urls = {n['url'] for n in group['notices']}
    notices = sorted((n for n in bundle['notices'] if n['url'] in urls),
                     key=lambda n: (n['date'], n['url']))
    if len(notices) > 4:
        raise ValueError('단일 검토 묶음의 상세 원문 4건 상한 초과')
    for n in notices:
        if n['url'] != canonical_url(n['source_id'], 'kgrowth'):
            raise ValueError('보관 상세의 표준 원문 주소 불일치')
        _stamp(n['checked_at'])
    return group, notices


def press_search_terms(bundle):
    group, notices = target_group(bundle, review_scope='joint_originals')
    expected = {item['fund'] for item in group['identity']['programs']}
    terms = []
    for notice in notices:
        names = re.findall(r'「([^」]+)」', notice['title'])
        if len(names) != 1:
            raise ValueError('공동 원모집 제목에서 펀드명 인용 확인 실패')
        term = re.sub(r'\([1-9][0-9]*차\)$', '', names[0]).strip()
        if re.sub(r'\s+', '', term) not in expected:
            raise ValueError('공동 원모집 펀드명과 검색어 불일치')
        terms.append(term)
    if {re.sub(r'\s+', '', term) for term in terms} != expected:
        raise ValueError('공동 원모집 검색 범위 불일치')
    return terms


def _detail(n, encoded, expected_sha):
    if not isinstance(encoded, str) or len(encoded) > (MAX_DETAIL_BYTES + 2) // 3 * 4:
        raise ValueError('상세 원문 크기 초과')
    raw = base64.b64decode(encoded, validate=True)
    if not raw or len(raw) > MAX_DETAIL_BYTES or _sha(raw) != expected_sha:
        raise ValueError('상세 원문 지문 불일치')
    parsed = read_body(n['source_id'], raw, 'kgrowth')
    if any(parsed[k] != n[k] for k in _FIELDS):
        raise ValueError('상세 원문 재생이 보관 제목·날짜·본문·첨부와 다름')
    return raw


def _captured(bundle, capture, notices, *, review_scope='pe_roster', group=None):
    if capture is None:
        return {}
    if (capture.get('kind') != KIND or capture.get('bundle_content_sha256') != _bundle_sha(bundle)
            or capture.get('review_scope', 'pe_roster') != review_scope
            or capture.get('identity') != (group['identity'] if group else None)
            or capture.get('remaining_candidates', 0) != (group.get('remaining_candidates', 0) if group else 0)
            or capture.get('planned_urls') != [n['url'] for n in notices]
            or len(capture.get('responses', [])) > 4):
        raise ValueError('상세 보완의 원래 묶음·자동 선택 불일치')
    missing_urls = [n['url'] for n in notices if not n['discovery_provenance'].get('detail_response_base64')]
    responses = capture['responses']
    if (type(capture.get('requests')) is not int or capture['requests'] != len(responses)
            or [r['url'] for r in responses] != missing_urls[:len(responses)]):
        raise ValueError('상세 보완의 요청 수·자동 순서 불일치')
    known, found = {n['url']: n for n in notices}, {}
    for entry in capture['responses']:
        n = known[entry['url']]
        if entry['url'] in found or entry['source_id'] != n['source_id']:
            raise ValueError('상세 보완의 원문 중복 또는 식별자 불일치')
        stamp = _stamp(entry['checked_at'])
        if stamp < _stamp(n['checked_at']) or stamp > datetime.now(timezone.utc):
            raise ValueError('상세 보완 시각이 원래 관측 전 또는 현재보다 미래임')
        if (entry['original_detail_sha256'] != n['discovery_provenance']['detail_sha256']
                or entry['http_status'] != 200 or entry['truncated']):
            raise ValueError('상세 보완의 이전 지문 또는 HTTP 응답 미확인')
        raw = _detail(n, entry['raw_base64'], entry['sha256'])
        if len(raw) != entry['bytes']:
            raise ValueError('상세 보완 응답 크기 불일치')
        found[n['url']] = entry
    return found


def capture_details(bundle, fetch, *, checked_at=None, retain=lambda report: None, limit=2,
                    review_scope='pe_roster'):
    """At most four detail GETs, one per missing page, stopping at first failure.

    ``retain`` persists the response receipt before any HTML parsing, including
    denied/truncated/changed pages. A failed capture is evidence, never a retry
    cursor. A new attempt needs a reviewed request change.
    """
    group, notices = target_group(bundle, review_scope=review_scope)
    if (type(limit) is not int or not 1 <= limit <= 4 or
            sum(not n['discovery_provenance'].get('detail_response_base64') for n in notices) > limit):
        raise ValueError('상세 보완 요청 상한 초과; 묶음을 나눠 추정 연결하지 않음')
    stamp = checked_at or datetime.now(timezone.utc).isoformat()
    if (_stamp(stamp) > datetime.now(timezone.utc) or
            any(_stamp(stamp) < _stamp(n['checked_at']) for n in notices)):
        raise ValueError('상세 보완 시각이 원래 관측 전 또는 현재보다 미래임')
    report = {'kind': KIND, 'bundle_content_sha256': _bundle_sha(bundle),
              'review_scope': review_scope,
              'remaining_candidates': group.get('remaining_candidates', 0) if group else 0,
              'identity': group['identity'] if group else None,
              'planned_urls': [n['url'] for n in notices], 'responses': [], 'holds': [],
              'requests': 0, 'published': False, 'database_writes': 0}
    retain(report)
    for n in notices:
        proof = n['discovery_provenance']
        if proof.get('detail_response_base64'):
            _detail(n, proof['detail_response_base64'], proof['detail_sha256'])
            continue
        try:
            report['requests'] += 1
            response = fetch(n['url'])
            raw, status = response['raw'], response['http_status']
            if not isinstance(raw, bytes) or type(status) is not int:
                raise ValueError('상세 응답 타입 미확인')
            retained = raw[:MAX_DETAIL_BYTES]
            entry = {'source_id': n['source_id'], 'url': n['url'], 'checked_at': stamp,
                     'original_detail_sha256': proof['detail_sha256'],
                     'sha256': _sha(retained), 'bytes': len(retained),
                     'http_status': status, 'truncated': len(raw) > MAX_DETAIL_BYTES,
                     'raw_base64': base64.b64encode(retained).decode('ascii')}
            report['responses'].append(entry)
            retain(report)  # save even an error response before parsing it
            _captured(bundle, report, notices, review_scope=review_scope, group=group)
        except Exception as exc:
            report['holds'].append({'url': n['url'], 'reason': f'{type(exc).__name__}: {str(exc)[:300]}'})
            retain(report)
            break
    return report


def replay_group(bundle, load_attachment, *, capture=None, review_scope='pe_roster'):
    """Replay current raw evidence; preserve old response hashes separately."""
    group, notices = target_group(bundle, review_scope=review_scope)
    # A failed receipt is not silently turned into usable source evidence.
    if capture and capture.get('holds'):
        raise ValueError('실패 응답 보완은 진단 후 별도 검토 필요')
    recovered = _captured(bundle, capture, notices, review_scope=review_scope, group=group)
    results, holds = [], []
    for n in notices:
        detail, attachments = None, []
        proof = n['discovery_provenance']
        try:
            if proof.get('detail_response_base64'):
                _detail(n, proof['detail_response_base64'], proof['detail_sha256'])
                detail = {'kind': 'retained_original', 'sha256': proof['detail_sha256']}
            elif n['url'] in recovered:
                entry = recovered[n['url']]
                detail = {'kind': 'recaptured_semantic_match', 'sha256': entry['sha256'],
                          'original_detail_sha256': proof['detail_sha256'],
                          'original_bytes_match': entry['sha256'] == proof['detail_sha256'],
                          'checked_at': entry['checked_at']}
            else:
                holds.append({'url': n['url'], 'reason': '상세 원본 없음'})
            for url in n['attachments']:
                sha = n.get('attachment_hashes', {}).get(url)
                if sha is None:
                    raise ValueError('관측 첨부의 원본 지문 없음')
                raw = load_attachment(sha)
                if not isinstance(raw, bytes) or len(raw) > MAX_FILE_BYTES or _sha(raw) != sha:
                    raise ValueError('첨부 원본 지문 또는 크기 불일치')
                text = kgrowth_attachment_text(raw)
                if text != n.get('attachment_texts', {}).get(url):
                    raise ValueError('첨부 원본 재생이 보관 판독문과 다름')
                attachments.append({'url': url, 'sha256': sha, 'bytes': len(raw),
                                    'text_sha256': _sha(text.encode()), 'text_replayed': True})
        except (ValueError, OSError, KeyError) as exc:
            holds.append({'url': n['url'], 'reason': str(exc)[:300]})
        results.append({'url': n['url'], 'detail': detail, 'attachments': attachments})
    return {'kind': 'lp_kgrowth_history_replay_v1', 'bundle_content_sha256': _bundle_sha(bundle),
            'review_scope': review_scope,
            'remaining_candidates': group.get('remaining_candidates', 0) if group else 0,
            'identity': group['identity'] if group else None, 'notices': results, 'holds': holds,
            'raw_replay_complete': bool(notices) and not holds,
            'publication_ready': False, 'domestic_investment_approved': False}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # HTTPError keeps the 3xx body; never follows the target


def fetch_detail(url):
    """Workflow-only one-shot public GET; no credentials, redirects or retries."""
    if url != canonical_url(source_id(url), 'kgrowth'):
        raise ValueError('상세 보완 원문 주소 미확인')
    opener = build_opener(_NoRedirect())
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0 (LP source verification)',
                                   'Accept-Encoding': 'identity'})
    try:
        response = opener.open(request, timeout=25)
    except HTTPError as error:
        response = error  # preserve bounded denied/error body too
    with response:
        return {'raw': response.read(MAX_DETAIL_BYTES + 1), 'http_status': response.code}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--capture-details', action='store_true')
    mode.add_argument('--assets', type=Path)
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--followup-capture', type=Path)
    parser.add_argument('--review-scope', choices=CAPTURE_SCOPES, default='pe_roster')
    args = parser.parse_args(argv)
    if args.review_scope in ('press_listing', 'press_search') and (not args.capture_details or args.capture):
        parser.error('보도자료 목록은 새 응답 진단만 지원하며 기존 묶음 재생에 쓸 수 없습니다')
    if args.review_scope in ('press_followup', 'press_result') and (not args.capture_details or not args.capture):
        parser.error('보도자료 후속 조회에는 앞선 검색 응답 영수증이 필요합니다')
    if bool(args.followup_capture) != (args.review_scope == 'press_result'):
        parser.error('보도자료 결과 상세에만 검증된 2쪽 응답 영수증을 지정합니다')
    if args.out.resolve() in {p.resolve() for p in (args.bundle, args.capture, args.followup_capture) if p}:
        parser.error('입력 원문·보완 영수증을 덮어쓸 수 없습니다')
    if args.out.exists() or args.out.is_symlink():
        parser.error('기존 원본·실패 영수증·보고서를 덮어쓸 수 없습니다. 새 출력 경로를 사용하세요')
    def read_json(path):
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError('검토 입력 40MiB 상한 초과')
        return json.loads(path.read_bytes())
    bundle = read_json(args.bundle)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Reserve a new output exclusively; subsequent writes belong to this one
    # invocation and retain each response before parsing it.
    args.out.open('x', encoding='utf-8').close()
    def save(report):
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if args.capture_details:
        if args.capture and args.review_scope not in ('press_followup', 'press_result'):
            parser.error('실패 보완을 자동 재시도하지 않습니다')
        if args.review_scope == 'press_listing':
            try:
                from .lp_kgrowth_press_probe import capture_press_listing, fetch_press_listing
            except ImportError:
                from lp_kgrowth_press_probe import capture_press_listing, fetch_press_listing
            report = capture_press_listing(fetch_press_listing, retain=save)
            report['review_scope'] = args.review_scope
            report['context_bundle_content_sha256'] = _bundle_sha(bundle)
            report['context_bundle_sha256'] = _sha(args.bundle.read_bytes())
            save(report)
        elif args.review_scope == 'press_search':
            try:
                from .lp_kgrowth_press_probe import capture_press_search, fetch_press_search
            except ImportError:
                from lp_kgrowth_press_probe import capture_press_search, fetch_press_search
            def search_report(receipts):
                return {'kind': 'lp_kgrowth_press_search_v1', 'review_scope': args.review_scope,
                        'context_bundle_sha256': _sha(args.bundle.read_bytes()),
                        'requests': sum(r['requests'] for r in receipts), 'receipts': receipts,
                        'holds': [hold for r in receipts for hold in r['holds']],
                        'parsed': False, 'source_health_verified': False,
                        'publication_ready': False, 'published': False}
            receipts = capture_press_search(press_search_terms(bundle), fetch_press_search,
                                            retain=lambda receipts: save(search_report(receipts)))
            report = search_report(receipts)
            save(report)
        elif args.review_scope in ('press_followup', 'press_result'):
            prior = read_json(args.capture)
            bundle_sha = _sha(args.bundle.read_bytes())
            if not isinstance(prior, dict) or prior.get('context_bundle_sha256') != bundle_sha:
                raise ValueError('보도자료 앞선 검색과 공동 원모집 묶음 지문 불일치')
            prior_sha = _sha(args.capture.read_bytes())
            proof = {'review_scope': args.review_scope, 'context_bundle_sha256': bundle_sha,
                     'prior_capture_sha256': prior_sha}
            def save_press(receipt):
                save({**receipt, **proof})
            terms = press_search_terms(bundle)
            if args.review_scope == 'press_followup':
                try:
                    from .lp_kgrowth_press_probe import capture_press_followup, fetch_press_followup
                except ImportError:
                    from lp_kgrowth_press_probe import capture_press_followup, fetch_press_followup
                report = capture_press_followup(prior, terms, fetch_press_followup, retain=save_press)
            else:
                try:
                    from .lp_kgrowth_press_probe import capture_press_result_detail, fetch_press_detail
                except ImportError:
                    from lp_kgrowth_press_probe import capture_press_result_detail, fetch_press_detail
                followup = read_json(args.followup_capture)
                if (not isinstance(followup, dict) or followup.get('context_bundle_sha256') != bundle_sha
                        or followup.get('prior_capture_sha256') != prior_sha):
                    raise ValueError('보도자료 2쪽과 앞선 검색 응답 지문 불일치')
                proof['followup_capture_sha256'] = _sha(args.followup_capture.read_bytes())
                report = capture_press_result_detail(prior, followup, terms, fetch_press_detail, retain=save_press)
            save_press(report)
        else:
            report = capture_details(bundle, fetch_detail, retain=save, review_scope=args.review_scope)
    else:
        def load(sha):
            path = args.assets / sha
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError('첨부 원본 25MiB 상한 초과')
            return path.read_bytes()
        report = replay_group(bundle, load, capture=read_json(args.capture) if args.capture else None,
                              review_scope=args.review_scope)
        save(report)
    print(json.dumps({k: v for k, v in report.items() if k in
                      {'kind', 'identity', 'review_scope', 'remaining_candidates', 'holds', 'requests',
                       'raw_replay_complete', 'publication_ready', 'board_type', 'capture_status',
                       'parsed', 'source_health_verified', 'http_status', 'bytes', 'sha256'}}, ensure_ascii=False))
    return 1 if report['holds'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
