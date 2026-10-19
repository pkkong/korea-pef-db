"""Publish sourced PE notices independently of complete terms or GP identities.

Only retained official documents are inputs. A recruitment anchors identity;
later documents must share its institution/year/track/round key. Missing terms
never become guessed values, and changes never silently preserve obsolete terms.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

try:
    from .collect_shared_lp_notices import classify_scope
    from .collect_lp_original_notices import load_channels, validate_url, validate_original
    from .lp_notice_triage import program_key, notice_stage, compact
    from .lp_notice_terms import INSTITUTIONS, extract_terms
    from .lp_shared_notice_terms import extract_shared_terms
except ImportError:
    from collect_shared_lp_notices import classify_scope
    from collect_lp_original_notices import load_channels, validate_url, validate_original
    from lp_notice_triage import program_key, notice_stage, compact
    from lp_notice_terms import INSTITUTIONS, extract_terms
    from lp_shared_notice_terms import extract_shared_terms

ROOT = Path(__file__).resolve().parents[3]
OFFERING_FIELDS = (
    'deadline', 'deadline_precision', 'commitment_amount_krw', 'commitment_label',
    'list_commitment_label', 'manager_count', 'manager_count_label', 'primary_investment',
    'segments', 'fund_target_label', 'commitment_detail', 'contribution_note',
    'contribution_allocations', 'total_commitment_amount_krw', 'per_fund_amount_krw',
    'per_fund_range_krw', 'per_fund_qualifier', 'extraction_evidence',
)
STAGES = {'모집 공고': 'announcement', '접수 결과': 'application',
          '1차 심사 결과': 'screening', '우선협상대상자': 'selection',
          '선정 결과': 'selection', '변경 공고': 'announcement'}


def _identity(n):
    # A reannouncement is a separate solicitation unless a source explicitly
    # ties its later documents to that round. Never merge it with the first call.
    title = re.sub(r'[\[【(][^\]】)]*공고\s*제?\s*20\d{2}\s*[-–]\s*\d+\s*호[^\]】)]*[\]】)]', '', n['title'])
    title = re.sub(r'(?:제?\d+차)\s*(?=정량평가|평가|심사|서류|면접)', '', title)
    title = re.sub(r'[（(\[【](?:정정|수정|변경|연장|취소)[）)\]】]', '', title)
    title = re.sub(r'(정정|수정|변경|연장|취소)\s*(?=공고|안내)', '', title)
    title = re.sub(r'(선정계획|모집|공고)\s*(정정|수정|변경|연장|취소)', r'\1', title)
    title = compact(title)
    title = re.sub(r'[【\[](?:선정공고|접수현황|접수결과|서류심사결과|선정결과)[】\]]', '', title)
    title = re.sub(r'(?:정량평가결과|서류심사결과|1차평가결과|접수현황|접수결과|선정결과|우선협상대상자)(?:선정)?(?:공고|안내|알림)?', '', title)
    title = re.sub(r'((?:위탁)?운용사)선정(?:계획)?', r'\1', title)
    title = re.sub(r'선정(?:계획)?(?=공고|$)', '', title)
    key = program_key({**n, 'title': title})
    qualifiers = re.findall(r'제?\d+차|\d+호|상반기|하반기|track\d+|일반매칭|루키|중형|소형|대형|국내|해외', compact(title))
    return key + ':' + ','.join(sorted(set(qualifiers))) + (':reopen' if '재공고' in n['title'] else '')


def _names():
    names = dict((key, value[0]) for key, value in INSTITUTIONS.items())
    for path in sorted((ROOT / 'data').glob('lp_blind_contest_screening_*.json')):
        names.update({n['institution_id']: n['name'] for n in json.loads(path.read_text()).get('institutions', [])})
    return names


def _valid(n, checked_at):
    published = date.fromisoformat(n['date'])
    if published.isoformat() > str(checked_at)[:10]:
        raise ValueError('미래 공고일')
    if not all(isinstance(n.get(k), str) and n[k].strip() for k in ('title', 'body', 'url')):
        raise ValueError('공식 공고 본문 누락')
    if urlsplit(n['url']).scheme != 'https' or not re.fullmatch('[0-9a-f]{64}', n.get('sha256', '')):
        raise ValueError('공식 공고 주소 또는 지문 누락')
    return n


def _sources(data, growth_notices, checked_at):
    docs, shared, holds = {}, {}, []
    channels = load_channels()
    for raw in growth_notices + data.get('priority_notices', []):
        try:
            n = _valid(copy.deepcopy(raw), checked_at)
            institution = n['institution_id']
            allowed = set(channels.get(institution, set()))
            if institution in INSTITUTIONS:
                allowed.add(INSTITUTIONS[institution][1].removeprefix('www.'))
            validate_url(n['url'], allowed)
            docs[n['url']] = n
        except (KeyError, TypeError, ValueError) as exc:
            holds.append({'stage': 'basic_publication', 'url': raw.get('url'), 'reason': str(exc)})
    # update_shared_catalog has already validated the association receipt. Prefer
    # the validated institution original, to deduplicate reposts and native runs.
    for raw in data.get('shared_notices', []):
        try:
            n = _valid(copy.deepcopy(raw), checked_at)
            originals = [validate_original(o, n, checked_at) for o in n.get('original_notices', [])]
            if len(originals) > 1:
                raise ValueError('복수 기관 원문 연결 보류')
            source = _valid(originals[0], checked_at) if originals else n
            source['institution_id'] = n['institution_id']
            shared[source['url']] = n
            docs.setdefault(source['url'], source)
        except (KeyError, TypeError, ValueError) as exc:
            holds.append({'stage': 'basic_publication', 'url': raw.get('url'), 'reason': str(exc)})
    return docs, shared, holds


def _texts(n):
    # Submission forms and historic eligibility references must not supply the
    # offered asset class. Only retained, fingerprinted offering text is usable.
    texts = [n['body']]
    for url, raw in n.get('attachment_texts', {}).items():
        if (urlsplit(url).hostname != urlsplit(n['url']).hostname or
                not re.fullmatch('[0-9a-f]{64}', n.get('attachment_hashes', {}).get(url, ''))):
            continue
        name = next((a.get('name', '') for a in n.get('attachments', []) if isinstance(a, dict) and a.get('url') == url), '')
        if re.search('서식|양식|제안서작성|제출서류', compact(name + raw[:100])):
            continue
        texts.append(raw)
    return texts


def _scope(n):
    text = '\n'.join(_texts(n))
    # Co-investments, project funds and private debt are distinct product scope.
    if re.search(r'공동투자|프로젝트|사모대출|대출형|크레딧|private\s*debt', n['title'], re.I):
        return 'outside'
    return classify_scope(n['title'], text)


def _deadline(n):
    hits = set()
    for text in _texts(n):
        for m in re.finditer(r'(?:제안서)?접수마감(?:일시|일|시한)?[:：·\-]*'
                             r'(20\d{2})[.년](\d{1,2})[.월](\d{1,2})[.일]?'
                             r'(?:\([월화수목금토일]\))?(?:(\d{1,2})(?:시|:)(\d{2})?분?)?', compact(text)):
            day = date(int(m[1]), int(m[2]), int(m[3])).isoformat()
            if m[4] is not None:
                value = datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5] or 0)).isoformat() + '+09:00'
                hits.add((value, 'datetime'))
            else:
                hits.add((day, 'date'))
    # A date-only caption and explicit time for that same day agree.
    timed = {h for h in hits if h[1] == 'datetime'}
    hits = {h for h in hits if h[1] != 'date' or not any(t[0][:10] == h[0] for t in timed)}
    if len(hits) > 1:
        raise ValueError('접수 마감 복수 값 확인 필요')
    result = next(iter(hits), None)
    if result and result[0][:10] < n['date']:
        raise ValueError('마감이 원공고보다 빠름')
    return result


def _terms(n, shared_notice, checked_at):
    terms = {}
    try:
        if shared_notice:
            terms = extract_shared_terms(shared_notice, checked_at)
        elif n['institution_id'] in INSTITUTIONS:
            terms = extract_terms(n)
    except (KeyError, TypeError, ValueError):
        pass
    # Only fields validated by the existing term parser may be copied.
    result = {k: copy.deepcopy(v) for k, v in terms.items() if k in OFFERING_FIELDS}
    if result.get('primary_investment'):
        result['primary_investment'].setdefault('source_url', n['url'])
    try:
        deadline = _deadline(n)
    except ValueError as exc:
        deadline = None
        result.pop('deadline', None)
        raw_terms = dict(terms, deadline_error=str(exc))
        terms = raw_terms
    if deadline:
        if result.get('deadline') and result['deadline'] != deadline[0]:
            if deadline[1] == 'date' and result['deadline'][:10] == deadline[0]:
                deadline = (result['deadline'], 'datetime')
            else:
                result.pop('deadline', None)
                terms = dict(terms, deadline_error='추출된 마감과 원문 마감 불일치')
                deadline = None
        if deadline:
            result.update(deadline=deadline[0], deadline_precision=deadline[1])
    if result.get('deadline'):
        result.setdefault('deadline_precision', 'datetime')
    return result, terms


def _event(n):
    stage = notice_stage(n['title'])
    if stage == '변경 공고' and '재공고' in n['title'] and not re.search(r'취소|정정|수정|연장|변경', n['title']):
        stage = '모집 공고'
    return {'date': n['date'], 'type': stage, 'title': n['title'], 'url': n['url']}


def _schedule_order(stages):
    """Sort coarse periods after known prior stages, without inventing dates."""
    phase = {'announcement': 0, 'application': 1, 'screening': 2,
             'interview': 3, 'due_diligence': 4, 'selection': 5}
    def key(item):
        stamp = item['date']
        if len(stamp) >= 10:
            return stamp[:7], float(stamp[8:10]), stamp
        rank = phase.get(item['stage'], 6)
        earlier_days = [int(s['date'][8:10]) for s in stages if len(s['date']) >= 10
                        and s['date'][:7] == stamp[:7] and phase.get(s['stage'], 6) < rank]
        return stamp[:7], max(earlier_days, default=0) + (rank + 1) / 10, stamp
    return sorted(stages, key=key)


def _refresh(p, members, checked_at):
    existing_events = {e['url']: copy.deepcopy(e) for e in p['events']}
    for n in members:
        existing_events.setdefault(n['url'], _event(n))
    p['events'] = sorted(existing_events.values(), key=lambda e: (e['date'], e['url']))
    changed = any(_event(n)['type'] == '변경 공고' for n in members)
    confirmed = {STAGES[e['type']] for e in p['events'] if e['type'] in STAGES}
    stages = [s for s in p.get('schedule_stages', []) if not changed
              and s.get('status') == 'planned' and s['stage'] not in confirmed
              and s.get('source_url') in {e['url'] for e in p['events']}]
    for event in p['events']:
        kind = STAGES.get(event['type'])
        if kind:
            stages.append({'stage': kind, 'label': event['type'], 'original_label': event['type'],
                           'date': event['date'], 'precision': 'date', 'status': 'confirmed',
                           'source_url': event['url'], 'show_source': True})
    if p.get('deadline'):
        original = next(e['url'] for e in p['events'] if e['type'] == '모집 공고')
        stages.append({'stage': 'application', 'label': '접수 마감', 'original_label': '접수 마감',
                       'date': p['deadline'], 'precision': p.get('deadline_precision', 'datetime'),
                       'status': 'announced_deadline', 'source_url': p.get('deadline_source_url', original), 'show_source': True})
    p['schedule_stages'] = _schedule_order(stages)
    rank = {'모집 공고': 0, '접수 결과': 1, '1차 심사 결과': 2, '우선협상대상자': 3, '선정 결과': 4, '최종 선정': 4, '변경 공고': 5}
    latest = max(p['events'], key=lambda e: (e['date'], rank.get(e['type'], -1), e['url']))
    stage = latest['type']
    if any('취소' in n['title'] for n in members):
        p['status'] = '모집 취소'
    elif stage == '변경 공고':
        p['status'] = '변경 공고'
    elif stage in ('선정 결과', '최종 선정'):
        p['status'] = '선정 완료' if p['selected_gps'] else '선정 결과 발표'
    elif stage not in ('모집 공고', '질의응답', '단계 확인 필요'):
        p['status'] = stage
    elif p.get('deadline'):
        now = datetime.fromisoformat(str(checked_at))
        end = datetime.fromisoformat(p['deadline'])
        ended = (end < now if end.tzinfo and now.tzinfo else p['deadline'][:10] < str(checked_at)[:10])
        p['status'] = '접수 마감' if ended else '접수 중'
    else:
        p['status'] = '모집 공고'
    p['checked_at'] = checked_at


def publish_basic_notices(data, growth_notices, checked_at):
    """Extend validated public programs; never consume a prepared candidate fact."""
    names = _names()
    docs, shared, holds = _sources(data, growth_notices, checked_at)
    groups = defaultdict(list)
    for n in docs.values():
        if n['institution_id'] in names and notice_stage(n['title']) in STAGES:
            groups[_identity(n)].append(n)
    programs = {p['id']: copy.deepcopy(p) for p in data['programs']}
    for key, members in sorted(groups.items()):
        try:
            originals = [n for n in members if _event(n)['type'] == '모집 공고']
            if len(originals) != 1:
                continue
            original = originals[0]
            urls = {n['url'] for n in members}
            matches = [p for p in programs.values() if p['institution_id'] == original['institution_id']
                       and (p.get('source_program_key') == key or urls & {e['url'] for e in p['events']})]
            if len(matches) > 1:
                raise ValueError('복수 기존 사업과 연결; 차수 확인 필요')
            if matches and matches[0].get('manual_review_id'):
                continue
            # A previously reviewed public program already owns its eligibility
            # evidence. Advancing its sourced stage does not require reapproving
            # its terms or interpreting its GP list again.
            reviewed = matches and not matches[0].get('basic_publication')
            if not reviewed and _scope(original) not in ('pe_blind', 'mixed_pe_blind'):
                continue
            terms, raw_terms = _terms(original, shared.get(original['url']), checked_at)
            if raw_terms.get('deadline_error'):
                holds.append({'stage': 'basic_deadline', 'url': original['url'], 'reason': raw_terms['deadline_error']})
            if not reviewed and _scope(original) == 'mixed_pe_blind' and not (raw_terms.get('amount_scope') == 'pe_only' and raw_terms.get('commitment_amount_krw')):
                continue
            if matches:
                p = matches[0]
                if not p.get('basic_publication') and not p.get('publication_version') and not (urls - {e['url'] for e in p['events']}):
                    continue
                # Complete reviewed programs retain their validated offering
                # facts. Lifecycle links can advance without guessing GP names.
                if p.get('basic_publication'):
                    for field in OFFERING_FIELDS:
                        p.pop(field, None)
                    p.update(terms)
            else:
                identity = original['institution_id'] + '-' + original['date'][:4] + '-' + hashlib.sha256(original['url'].encode()).hexdigest()[:16]
                p = {'id': identity, 'institution_id': original['institution_id'],
                     'institution_name': names[original['institution_id']], 'title': original['title'],
                     'asset_scope': 'PE', 'status': '모집 공고', 'selected_gps': [], 'events': [],
                     'basic_publication': True, 'source_program_key': key, **terms}
            if p.get('basic_publication'):
                planned = raw_terms.get('planned_schedule', raw_terms.get('schedule_stages', []))
                p['schedule_stages'] = [{**s, 'original_label': s.get('original_label', s['label']),
                                         'source_url': s.get('source_url', original['url']), 'show_source': True}
                                        for s in planned if s.get('status') == 'planned']
            changes = [n for n in members if _event(n)['type'] == '변경 공고']
            if changes:
                # Original amounts/deadlines may be obsolete after a correction.
                # Keep history privately; expose only a uniquely explicit new
                # deadline, otherwise the change notice itself is authoritative.
                p['previous_offering_terms'] = {f: p[f] for f in OFFERING_FIELDS if f in p}
                for field in OFFERING_FIELDS:
                    p.pop(field, None)
                if not any('취소' in n['title'] for n in changes):
                    latest = max(changes, key=lambda n: (n['date'], n['url']))
                    try:
                        if re.search(r'당초|변경\s*전|변경\s*후|종전', '\n'.join(_texts(latest))):
                            raise ValueError('변경 전후 일정 표는 새 마감 확인 필요')
                        revised = _deadline(latest)
                    except ValueError as exc:
                        revised = None
                        holds.append({'stage': 'basic_deadline', 'url': latest['url'], 'reason': str(exc)})
                    if revised:
                        p.update(deadline=revised[0], deadline_precision=revised[1], deadline_source_url=latest['url'])
            _refresh(p, members, checked_at)
            p['publication_version'] = 1
            p['source_program_key'] = key
            programs[p['id']] = p
        except (KeyError, TypeError, ValueError) as exc:
            holds.append({'stage': 'basic_publication', 'program_key': key, 'reason': str(exc)})
    return list(programs.values()), holds
