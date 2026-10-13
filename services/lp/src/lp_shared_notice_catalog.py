"""Retain association evidence and reclassify it independently of collectors.

This archive expands discovery/review, not permission to publish fund facts.
Only offering formats independently supported by the publisher can introduce
public program pages.
"""
import copy
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

try:
    from .collect_shared_lp_notices import classify_scope, match_issuer, load_aliases, source_id
    from .lp_notice_triage import program_key, notice_stage
except ImportError:
    from collect_shared_lp_notices import classify_scope, match_issuer, load_aliases, source_id
    from lp_notice_triage import program_key, notice_stage

ROOT = Path(__file__).resolve().parents[3]
CHANNEL_PATHS = {'kvca': '/Program/invest/listbody.html',
                 'kofia_212': '/brd/m_212/view.do', 'kofia_17': '/brd/m_17/view.do'}
LABELS = {'pe_blind': ('pe_eligible', '공식 공고가 국내 PE 블라인드 모집을 명시'),
          'mixed_pe_blind': ('mixed_legal_forms', '공식 공고에 PE와 VC 블라인드 모집이 함께 표시됨'),
          'vc_only': ('vc_only', '공식 공고에서 VC 모집 확인'),
          'needs_confirmation': ('unknown', 'PE 블라인드 모집 범위 추가 확인 필요')}


def update_shared_catalog(current, incoming, checked_at):
    aliases = load_aliases()
    names = {r['institution_id']: r['name'] for p in (ROOT/'data').glob('lp_blind_contest_screening_*.json')
             for r in json.loads(p.read_text()).get('institutions', [])}
    retained = {n['url']: copy.deepcopy(n) for n in current.get('shared_notices', [])}
    holds = copy.deepcopy((incoming or {}).get('holds', []))
    for raw in (incoming or {}).get('notices', []):
        try:
            n = copy.deepcopy(raw)
            channel = n['source_channel']
            parsed = urlparse(n['url'])
            host = 'www.kvca.or.kr' if channel == 'kvca' else 'www.kofia.or.kr'
            if (parsed.scheme != 'https' or parsed.hostname != host or
                    parsed.path != CHANNEL_PATHS[channel] or
                    source_id(n['url'], channel) != n['source_id']):
                raise ValueError('공식 협회 공고 주소 불일치')
            if not re.fullmatch(r'[0-9a-f]{64}', n.get('sha256', '')) or not n.get('body'):
                raise ValueError('공고 본문 또는 지문 누락')
            provenance=n.get('source_provenance', {})
            claimed,deadline=provenance.get('claimed_official_date'),provenance.get('application_deadline')
            if claimed and deadline and claimed>deadline:
                registered=provenance.get('association_registered_at')
                if not registered or n['date'] != registered:
                    raise ValueError('공고일·신청기한 역전; 원공고 일정 확인 필요')
                n['date_note']='협회 등록일 · 원공고일 확인 필요'
            date.fromisoformat(n['date'])
            if n['date'] > str(checked_at)[:10]:
                raise ValueError('미래 공고일 확인 필요')
            issuer = n.get('source_provenance', {}).get('reported_issuer')
            identity, confidence = match_issuer(n['title'], issuer, n['body'], aliases)
            if identity != n['institution_id']:
                raise ValueError('공고 발행기관 또는 기금 연결 재확인 필요')
            old = retained.get(n['url'])
            if old and old.get('attachment_hashes') == n.get('attachment_hashes'):
                n['attachment_texts'] = {**old.get('attachment_texts', {}),
                                         **{u: t for u, t in n.get('attachment_texts', {}).items() if t.strip()}}
            for url in n.get('attachment_texts', {}):
                if urlparse(url).hostname != host or not n.get('attachment_hashes', {}).get(url):
                    raise ValueError('첨부 본문 근거 불일치')
            n['institution_name'] = names[identity]
            n['match_confidence'] = confidence
            n['source_scope'] = classify_scope(n['title'], n['body']+' '+' '.join(n.get('attachment_texts', {}).values()))
            retained[n['url']] = n
        except (ValueError, KeyError, TypeError) as exc:
            holds.append({'stage': 'publication_validation', 'url': raw.get('url'), 'error': str(exc)})
    candidates = []
    for n in retained.values():
        # Reclassify the last retained source too; a forged prepared scope is
        # never approval, and unrelated job/share/bond notices stay archived.
        classified = classify_scope(n['title'], n['body']+' '+' '.join(n.get('attachment_texts', {}).values()))
        n['source_scope'] = classified
        if classified not in LABELS:
            continue
        scope, reason = LABELS[classified]
        candidates.append({'institution_id': n['institution_id'], 'institution_name': names[n['institution_id']],
                           'source_id': n['source_id'], 'url': n['url'], 'title': n['title'], 'date': n['date'],
                           'date_note': n.get('date_note',''),
                           'program_key': program_key(n), 'stage': notice_stage(n['title']), 'scope': scope,
                           'scope_reason': reason, 'scope_source_url': n['url'],
                           'recruitment_url': n['url'] if notice_stage(n['title']) == '모집 공고' else None,
                           'source_channel': n['source_channel']})
    return {'shared_notices': list(retained.values()), 'shared_discovery_candidates': candidates,
            'shared_unmatched_notices': copy.deepcopy((incoming or {}).get('unmatched_notices', current.get('shared_unmatched_notices', []))),
            'shared_collection_holds': holds,
            'shared_collection_coverage': copy.deepcopy((incoming or {}).get('coverage', current.get('shared_collection_coverage', {})))}
