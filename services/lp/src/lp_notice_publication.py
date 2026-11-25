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
    from .lp_offering_policy import procurement_reason,central_not_investing
    from .lp_attachment_policy import is_submission_attachment
    from .collect_shared_lp_notices import classify_scope, scope_signals
    from .collect_lp_original_notices import load_channels, validate_url, validate_original
    from .lp_notice_triage import program_key, notice_stage, compact
    from .lp_notice_terms import INSTITUTIONS, extract_terms
    from .collect_koreapost_program import extract_preferred
    from .lp_shared_notice_terms import extract_shared_terms
    from .collect_lp_institution_boards import validate_notice as validate_institution_notice
    from .lp_institution_notice_terms import extract_terms as extract_institution_terms
    from .lp_institution_notice_terms import apply_iaci_allocation, kdb_joint_size_offering
    from .lp_kfcc_notice_terms import allocation as kfcc_allocation
    from . import lp_pck_programs as pck_programs
    from . import lp_kbiz_notice_terms as kbiz_terms
    from . import lp_mmaa_notice_terms as mmaa_terms
    from . import lp_result_rosters as result_rosters
    from . import lp_nps_notice_terms as nps_terms
    from . import lp_history_notices as history_notices
    from . import lp_kfinco_notice_terms as kfinco_terms
    from . import lp_kamco_notice_terms as kamco_terms
    from . import lp_kdb_policy_reopen as kdb_reopen
    from . import lp_kdb_nuclear_terms as kdb_nuclear
    from . import lp_kdb_media_terms as kdb_media
    from . import lp_kdb_innovation_terms as kdb_innovation
    from . import lp_kdb_growth_support_terms as kdb_growth_support
    from . import lp_kdb_growth_support_2024 as kdb_growth_support_2024
    from . import lp_kdb_innovation_2024_first as kdb_innovation_2024_first
    from . import lp_kdb_innovation_2024_second as kdb_innovation_2024_second
    from . import lp_kdb_recovery_market as kdb_recovery
    from . import lp_kdb_ai_fixed_terms as kdb_ai_fixed
    from . import lp_kdb_semiconductor_terms as kdb_semiconductor
except ImportError:
    from lp_offering_policy import procurement_reason,central_not_investing
    from lp_attachment_policy import is_submission_attachment
    from collect_shared_lp_notices import classify_scope, scope_signals
    from collect_lp_original_notices import load_channels, validate_url, validate_original
    from lp_notice_triage import program_key, notice_stage, compact
    from lp_notice_terms import INSTITUTIONS, extract_terms
    from collect_koreapost_program import extract_preferred
    from lp_shared_notice_terms import extract_shared_terms
    from collect_lp_institution_boards import validate_notice as validate_institution_notice
    from lp_institution_notice_terms import extract_terms as extract_institution_terms
    from lp_institution_notice_terms import apply_iaci_allocation, kdb_joint_size_offering
    from lp_kfcc_notice_terms import allocation as kfcc_allocation
    import lp_pck_programs as pck_programs
    import lp_kbiz_notice_terms as kbiz_terms
    import lp_mmaa_notice_terms as mmaa_terms
    import lp_result_rosters as result_rosters
    import lp_nps_notice_terms as nps_terms
    import lp_history_notices as history_notices
    import lp_kfinco_notice_terms as kfinco_terms
    import lp_kamco_notice_terms as kamco_terms
    import lp_kdb_policy_reopen as kdb_reopen
    import lp_kdb_nuclear_terms as kdb_nuclear
    import lp_kdb_media_terms as kdb_media
    import lp_kdb_innovation_terms as kdb_innovation
    import lp_kdb_growth_support_terms as kdb_growth_support
    import lp_kdb_growth_support_2024 as kdb_growth_support_2024
    import lp_kdb_innovation_2024_first as kdb_innovation_2024_first
    import lp_kdb_innovation_2024_second as kdb_innovation_2024_second
    import lp_kdb_recovery_market as kdb_recovery
    import lp_kdb_ai_fixed_terms as kdb_ai_fixed
    import lp_kdb_semiconductor_terms as kdb_semiconductor

ROOT = Path(__file__).resolve().parents[3]
# Large LPs whose policy/pension notices mix PE and VC (user decision 2026-11-12).
# 2026-11-14 (2020+ history, user decision): 산재보험기금 is 고용보험기금's twin fund under
# the same ministry; 군인공제회·과기공 run one annual joint PE·VC blind contest.
PE_TRACK_INSTITUTIONS = frozenset({'kdb', 'ibk', 'moel_eif', 'moel_iaci', 'nps', 'geps', 'cwma', 'kic', 'mmaa', 'sema'})
TITLE_SIGNAL_PE_TRACK = frozenset({'moel_iaci', 'mmaa', 'sema'})
MIXED_SCOPE_LABEL = 'PE·VC 공동 모집'


def _fund_key(value):
    return re.sub(r'[\s·ㆍ\-_()（）「」『』\[\]]', '', str(value or '')).lower()


def _fund_name(title):
    match = re.search(r'[「『]([^」』]{2,60})[」』]', str(title or ''))
    return _fund_key(match[1]) if match else ''


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
    if key := kdb_reopen.identity(n) or kdb_semiconductor.identity(n):
        return key
    title = re.sub(r'[\[【(][^\]】)]*공고\s*제?\s*20\d{2}\s*[-–]\s*\d+\s*호[^\]】)]*[\]】)]', '', n['title'])
    # 『펀드명』 and 펀드명 are the same fund: stage notices often drop the quote brackets.
    title = re.sub(r'[「」『』]', ' ', title)
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
    for raw in data.get('institution_notices', []):
        try:
            n = _valid(validate_institution_notice(raw, checked_at), checked_at)
            docs[n['url']] = n
        except (KeyError, TypeError, ValueError) as exc:
            holds.append({'stage': 'basic_publication', 'url': raw.get('url'), 'reason': str(exc)})
    for raw in data.get('history_notices', []):
        try:
            n = _valid(history_notices.validate_history_notice(raw, checked_at), checked_at)
            docs.setdefault(n['url'], n)  # a current daily version of the same notice wins
        except (KeyError, TypeError, ValueError) as exc:
            holds.append({'stage': 'basic_publication', 'url': raw.get('url'), 'reason': str(exc)})
    return docs, shared, holds


def _texts(n):
    # Submission forms and historic eligibility references must not supply the
    # offered asset class. Only retained, fingerprinted offering text is usable.
    texts = [n['body']]
    for url, raw in n.get('attachment_texts', {}).items():
        if is_submission_attachment(n, url):
            continue
        if (urlsplit(url).hostname != urlsplit(n['url']).hostname or
                not re.fullmatch('[0-9a-f]{64}', n.get('attachment_hashes', {}).get(url, ''))):
            continue
        name = next((a.get('name', '') for a in n.get('attachments', []) if isinstance(a, dict) and a.get('url') == url), '')
        if n.get('source_channel') != 'institution_board' and re.search('서식|양식|제안서작성|제출서류', compact(name + raw[:100])):
            continue
        texts.append(raw)
    return texts


def _scope(n):
    if procurement_reason(n['title'],n['body']):
        return 'outside'
    if n.get('institution_id')=='nh_central':
        if any(central_not_investing(text) for text in _texts(n)):
            return 'outside'
        # This portal also hosts affiliate-bank and securities procurement.
        # Recompute from the validated article, never trust a supplied flag.
        try:
            from .lp_board_adapter_nh import issuer_evidence
        except ImportError:
            from lp_board_adapter_nh import issuer_evidence
        if issuer_evidence(n)['status']!='central_explicit':
            return 'needs_confirmation'
    if n.get('institution_id')=='suhyup' and re.search(r'(?:Sh)?수협은행',n['title']):
        return 'outside'
    if n.get('institution_id') == 'kamco' and kamco_terms.pe_track(n):
        return 'pe_blind'
    if n.get('institution_id') == 'kbiz' and kbiz_terms.pe_track(n):
        return 'mixed_pe_blind'
    if n.get('institution_id') == 'pck_pension':
        return 'pe_blind' if pck_programs.offering_sources(n) else 'unknown'
    if n.get('institution_id') == 'kfcc':
        return 'mixed_pe_blind' if kfcc_allocation(n) else 'unknown'
    texts = _texts(n)
    text = '\n'.join(texts)
    if (n.get('source_channel') == 'institution_board'
            and re.search(r'(?<![A-Za-z])VC(?![A-Za-z])', n['title'], re.I)
            and not re.search(r'(?<![A-Za-z])PEF?(?![A-Za-z])', n['title'], re.I)):
        return 'vc_only'
    # Co-investments, project funds and private debt are distinct product scope.
    if re.search(r'공동투자|프로젝트|사모대출|대출형|크레딧|부동산|인프라|헤지펀드|private\s*debt|평가\s*기관\s*선정'
                 r'|개발\s*(?:블라인드\s*)?펀드|개발사업|PF\s*사업장', n['title'], re.I):
        return 'outside'
    result = classify_scope(n['title'], text)
    if (n.get('institution_id') == 'kdb' and n.get('source_channel') == 'institution_board'
            and result != 'outside' and not re.search(r'모펀드|Pre-?IPO|주식|채권|멀티에셋|EMP|재간접|절대수익|헤지', n['title'], re.I)
            and (any(kdb_joint_size_offering(source) for source in texts)
                 or (kdb_reopen.identity(n) and any(kdb_reopen.mixed_vehicles(source) for source in texts)))):
        return 'mixed_pe_blind'
    # User decision 2026-11-12: for the large policy/pension LPs, an explicitly
    # offered PE fund is published even when blind/domestic wording is absent.
    # Fund-of-funds manager selections are not GP recruitments.
    if (result == 'needs_confirmation' and n.get('institution_id') in PE_TRACK_INSTITUTIONS
            and not re.search(r'모펀드', n['title'])
            # Listed-securities mandates mention "PE, VC" only as allowed vehicles (과기공 Pre-IPO 2026).
            and not re.search(r'Pre-?IPO|주식|채권|멀티에셋|EMP|재간접|절대수익|헤지', n['title'], re.I)
            # Institutions added for the 2020+ history must name the PE blind round in the title.
            and (n.get('institution_id') not in TITLE_SIGNAL_PE_TRACK
                 or re.search(r'블라인드|(?<![A-Za-z])PEF?(?![A-Za-z])', n['title'], re.I))):
        signals = scope_signals(n['title'], text)
        if signals['pe']:
            return 'mixed_pe_blind' if signals['vc'] else 'pe_blind'
    return result


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


# Headline budget lines in notices, read when the term parsers found no amount.
# "선정 규모 : 총 1,200억원 (PEF 600억원(2건), VC 600억원(3건))" gives the PE share itself.
_HEADLINE_PE_SPLIT = re.compile(r'선정규모[:：]?총([\d,]+)억원\(PEF([\d,]+)억원\((\d+)건\)', re.I)
_HEADLINE_TOTAL = re.compile(
    r'(?:\(출자금액\)|출자금액|위탁운용금액|위탁운용총액|출자규모|선정규모|투자금액)[:：∙·•\-\s]{0,3}총([\d,]+)억원(이내|내외)?'
    r'(?:\((\d+)건선정예정\))?')


def _won(text):
    return int(text.replace(',', '')) * 100_000_000


# "1. PE (부문) 선정개요 … 2. VC (부문) 선정개요". The leading 1 keeps a repeated table
# caption ("2. VC 부문 선정개요 PE 부문 선정개요 - 구분") from opening a second PE section.
_PE_SECTION = re.compile(r'(?<![\d.])1\s*\.?\s*PE\s*(?:부문\s*)?선정\s*개요(.*?)(?=2\s*\.?\s*VC\s*(?:부문\s*)?선정|VC\s*(?:부문\s*)?선정\s*개요|$)', re.S)


def _pe_section(n):
    """Texts cut to the PE part of a notice that sets out PE and VC separately
    ("1. PE 선정개요 … 2. VC 선정개요", 과기공 2020-2023); [] when there is none."""
    sections = [m[1] for text in _texts(n) for m in _PE_SECTION.finditer(text)]
    return [s for s in sections if s.strip()]


def headline_amount(n):
    """Budget stated in a notice's headline line, with its quote; {} when absent or ambiguous.

    A PE share stated next to the total wins (amount_scope 'pe_only'); otherwise one total
    for the whole notice (amount_scope 'combined'). Different totals in one notice -> {}.
    """
    pe_only = _pe_section(n)
    texts = pe_only or _texts(n)
    splits = {(m[2], m[3], m[0]) for text in texts for m in _HEADLINE_PE_SPLIT.finditer(re.sub(r'\s+', '', text))}
    evidence = lambda quote: {'commitment': [{'source_url': n['url'], 'sha256': n['sha256'], 'quote': quote}]}
    if splits:
        if len({(a, c) for a, c, _ in splits}) != 1:
            return {}
        amount, count, quote = sorted(splits)[0]
        return {'commitment_amount_krw': _won(amount), 'commitment_label': f'PE 부문 {amount}억원',
                'list_commitment_label': f'PE 부문 {amount}억원', 'manager_count': int(count),
                'manager_count_label': f'{count}개사', 'amount_scope': 'pe_only', 'extraction_evidence': evidence(quote)}
    found = []
    for text in texts:
        hits = list(_HEADLINE_TOTAL.finditer(re.sub(r'\s+', '', text)))
        # A PE section's own total comes first; later totals in it belong to the next part.
        found.extend(hits[:1] if pe_only else hits)
    totals = {(m[1].replace(',', ''), m[2] or '', m[0]) for m in found}
    if not totals or len({a for a, _, _ in totals}) != 1:
        return {}
    amount, qualifier, quote = sorted(totals, key=lambda t: (not t[1], t[2]))[0]
    amount = f'{int(amount):,}'
    label = f'총 {amount}억원' + (f' {qualifier}' if qualifier else '')
    if pe_only:
        label = 'PE 부문 ' + label.removeprefix('총 ')
    result = {'commitment_amount_krw': _won(amount), 'commitment_label': label, 'list_commitment_label': label,
              'amount_scope': 'pe_only' if pe_only else 'combined', 'extraction_evidence': evidence(quote)}
    counts = {m[3] for m in found if m[3]}
    if len(counts) == 1:  # "총 1,500억원 (3건 선정 예정)"
        count = int(next(iter(counts)))
        result.update(manager_count=count, manager_count_label=f'{count}개사')
    return result


# Minimum fund size a proposal must reach, from explicit notice wording only.
# Tiers run in order; the first tier with any hit decides, and two different
# values inside that tier (PE vs VC columns, leagues) give no value at all.
_N = r'([\d,]+)억원?'
_FUND_SIZE_TIERS = (
    ('range', re.compile(r'결성규모는최소' + _N + r'~최대' + _N)),
    ('minimum', re.compile(r'최소(?:펀드)?결성규모[:：‧·ㆍ\-]*(?:최소펀드결성규모[:：]*)?' + _N + r'(이상)?')),
    ('blind_track', re.compile(r'블라인드형\].{0,80}?제안펀드결성규모' + _N + r'이상')),
    ('proposal', re.compile(r'(?:제안펀드결성규모가?|펀드별결성총액)' + _N + r'이상')),
    ('overview', re.compile(r'(?<!예상)펀드규모[:：]?' + _N + r'이상')),
)


def minimum_fund_size(n):
    """{'fund_target_label': '최소 N억원' | 'N억~M억원', evidence} or {} when absent/ambiguous."""
    texts = [re.sub(r'\s+', '', text) for text in (_pe_section(n) or _texts(n))]
    for kind, pattern in _FUND_SIZE_TIERS:
        hits, skipped_vc = [], False
        for text in texts:
            for m in pattern.finditer(text):
                after = text[m.end():m.end() + 60]
                if kind == 'minimum' and re.match(r'[\d,]+억원', after):
                    return {}  # side-by-side columns (e.g. PE | VC) without a header we can read
                if kind == 'minimum' and re.search(r'벤처투자조합|신기술사업투자조합', after) \
                        and not re.search(r'기관전용사모', after):
                    skipped_vc = True
                    continue  # the VC section's own minimum
                hits.append(m)
        if not hits:
            continue
        values = {m.groups()[:2] if kind == 'range' else m[1] for m in hits}
        if len(values) != 1:
            return {}
        m = hits[0]
        label = (f'{m[1]}억~{m[2]}억원' if kind == 'range' else f'최소 {m[1]}억원')
        if skipped_vc:
            label += ' (PE)'
        return {'fund_target_label': label, 'extraction_evidence': {
            'fund_target': [{'source_url': n['url'], 'sha256': n['sha256'], 'quote': m[0]}]}}
    return {}


def _terms(n, shared_notice, checked_at):
    terms = {}
    try:
        if n.get('source_channel') == 'institution_board':
            terms = (pck_programs.terms(n) if n['institution_id'] == 'pck_pension' else
                     kbiz_terms.terms(n) if n['institution_id'] == 'kbiz' and kbiz_terms.pe_track(n) else
                     kfinco_terms.terms(n) if n['institution_id'] == 'kfinco' else
                     kamco_terms.terms(n) if n['institution_id'] == 'kamco' and kamco_terms.pe_track(n) else
                     extract_institution_terms(n))
        elif shared_notice:
            terms = extract_shared_terms(shared_notice, checked_at)
        elif n['institution_id'] in INSTITUTIONS:
            terms = extract_terms(n)
    except (KeyError, TypeError, ValueError):
        pass
    if n.get('source_channel') != 'institution_board':
        terms = apply_iaci_allocation(n, terms)
    if not terms.get('allocation_reading_failed') and not (terms.get('commitment_amount_krw') or terms.get('commitment_label') or terms.get('segments')):
        try:
            headline = mmaa_terms.pe_share(n) or nps_terms.pe_share(n) or headline_amount(n)
        except (KeyError, TypeError, ValueError):
            headline = {}
        if headline and terms.get('amount_scope') == 'pe_track_without_allocation':
            if headline['amount_scope'] != 'combined':
                headline = {}
            else:
                # A PE track inside a joint PE·VC budget (e.g. 중소기업중앙회): the joint total is
                # shown as a labelled figure only. It is not this track's allocation, so no
                # number is stored for totals or statistics.
                headline.pop('commitment_amount_krw')
                headline.pop('amount_scope')
                headline.pop('manager_count', None)  # the joint notice's count, not this track's
                headline.pop('manager_count_label', None)
                for field in ('commitment_label', 'list_commitment_label'):
                    headline[field] += ' (PE·VC 합계)'
        if headline:
            if terms.get('manager_count'):  # the institution parser's count stands
                headline.pop('manager_count', None)
                headline.pop('manager_count_label', None)
            evidence = {**terms.get('extraction_evidence', {}), **headline.pop('extraction_evidence')}
            terms = {**terms, **headline, 'extraction_evidence': evidence}
    if not terms.get('fund_target_label'):
        try:
            size = minimum_fund_size(n)
        except (KeyError, TypeError, ValueError):
            size = {}
        if size:
            evidence = {**terms.get('extraction_evidence', {}), **size.pop('extraction_evidence')}
            terms = {**terms, **size, 'extraction_evidence': evidence}
    # Only fields validated by the existing term parser may be copied.
    result = {k: copy.deepcopy(v) for k, v in terms.items() if k in OFFERING_FIELDS}
    if shared_notice and result.get('primary_investment'):
        # The source's generic fund-management purpose (e.g. income or deal
        # opportunities) is not an investment mandate. Retain it in evidence,
        # but do not relabel it as 주목적 on the public program.
        quotes = terms.get('extraction_evidence', {}).get('purpose', [])
        if not any(re.search(r'주목적(?:투자대상)?\s*[:：]', compact(e['quote'])) for e in quotes):
            result.pop('primary_investment')
    if result.get('primary_investment'):
        result['primary_investment'].setdefault('source_url', n['url'])
    try:
        deadline = None if n.get('source_channel') == 'institution_board' else _deadline(n)
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
    stage = pck_programs.stage(n) if n['institution_id'] == 'pck_pension' else notice_stage(n['title'])
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


def _refresh(p, members, checked_at, *, original=None, previous_recruitment_url=None):
    phases = dict(STAGES)
    phases['최초 모집 공고'] = 'announcement'
    phases['질의응답'] = 'faq'
    if p['institution_id'] == 'pck_pension':
        phases['최종 선정'] = 'selection'
    existing_events = {e['url']: copy.deepcopy(e) for e in p['events']}
    for n in members:
        if p['institution_id'] == 'pck_pension':
            previous = next((e for e in existing_events.values() if pck_programs._canonical(e['url']) == n['url']), None)
            if previous:
                event = _event(n)
                if previous['type'] == '최종 선정' and event['type'] == '선정 결과':
                    event['type'] = previous['type']
                existing_events[previous['url']] = {**event, 'url': previous['url']}
                continue
        if n['url'] == previous_recruitment_url:
            existing_events[n['url']] = {**_event(n), 'type': '최초 모집 공고'}
        else:
            existing_events.setdefault(n['url'], _event(n))
    # The verified recruitment anchor precedes its same-day repost. Both the
    # detail header and the original deadline cite the first recruitment event.
    # URL alphabetic order must not make an association the primary source.
    p['events'] = sorted(existing_events.values(), key=lambda e: (
        e['date'], 0 if original and e['url'] == original['url'] else 1, e['url']))
    changed = any(_event(n)['type'] == '변경 공고' for n in members)
    confirmed = {phases[e['type']] for e in p['events'] if e['type'] in phases}
    stages = [s for s in p.get('schedule_stages', []) if not changed
              and s.get('status') == 'planned' and s['stage'] not in confirmed
              and s.get('source_url') in {e['url'] for e in p['events']}]
    for event in p['events']:
        kind = phases.get(event['type'])
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


def ibk_result_roster(text):
    """IBK posts results in the body as '□ league ㅇ 운용사명(가나다순) - A - B'.

    Returns [(league, [names])]. Co-GP names joined by '-' without spaces stay
    one manager. Anything outside that exact shape returns no roster.
    """
    rosters = []
    for match in re.finditer(r'□\s*([^□ㅇ]{1,40}?)\s*ㅇ\s*운용사명\s*\(가나다순\)\s*(.*?)(?=□|문의|$)', text, re.S):
        league = re.sub(r'\s+', '', match[1])
        names = [re.sub(r'\s+', ' ', n).strip() for n in re.split(r'(?:^|\s)-\s', match[2].strip()) if n.strip()]
        if not league or not names or any(len(n) > 60 or re.search(r'[:：@()\d]{3,}', n) for n in names):
            return []
        rosters.append((league, names))
    return rosters


# KDB posts results as an attachment table whose text extraction loses the cell
# borders: '지원분야 선정 운용사명(가나다순)\nPE더함파트너스릴슨프라이빗에쿼티'.
# Names are split only where exactly one reading is possible.
KDB_FIELD_LABELS = ('PE', 'VC', '대형', '중형', '소형', '도전', '루키', '일반')
GP_SUFFIX_WORDS = tuple(sorted((
    '프라이빗에쿼티', '프라이빗에퀴티', '인베스트먼트', '파트너스', '자산운용', '캐피탈', '에쿼티', '에퀴티',
    '벤처스', '벤처투자', '컴퍼니', '코리아', '증권', '매니지먼트', '홀딩스', '솔루션', '투자'), key=len, reverse=True))


def _gp_key(name):
    return re.sub(r'\(주\)|㈜|주식회사|\s+', '', name or '')


def _rule_valid_name(piece):
    """Stem + at most two trailing suffix words; the stem holds no suffix word."""
    stem, words = piece, 0
    while words < 2:
        word = next((w for w in GP_SUFFIX_WORDS if stem.endswith(w) and len(stem) > len(w)), None)
        if not word:
            break
        stem, words = stem[:-len(word)], words + 1
    return words > 0 and bool(stem) and not any(w in stem for w in GP_SUFFIX_WORDS) and bool(re.fullmatch(r'[가-힣A-Za-z0-9&]+', stem))


def split_glued_names(text, known=frozenset(), limit=64):
    """Split concatenated manager names. Returns a list, or None when the
    reading is not unique. Co-GP pairs joined by '-' or '/' stay one manager."""
    text = re.sub(r'\(\s*Co-?GP\s*\)', '', text, flags=re.I)
    text = re.sub(r'\s*([-/])\s*', r'\1', text).replace(' ', '')
    if not text:
        return None
    known = {_gp_key(k) for k in known}

    def piece_ok(piece):
        if piece in known:
            return 2
        return 1 if _rule_valid_name(piece) else 0

    from functools import lru_cache

    @lru_cache(maxsize=None)
    def solve(i):
        if i == len(text):
            return [((), 0)]
        found = []
        for j in range(i + 2, min(len(text), i + 40) + 1):
            chunk = text[i:j]
            parts = re.split(r'([-/])', chunk)
            if parts[0] == '' or parts[-1] == '' or len(parts) > 3:
                continue
            scores = [piece_ok(x) for x in parts[::2]]
            if not all(scores):
                continue
            for rest, score in solve(j):
                found.append(((chunk,) + rest, score + sum(scores)))
                if len(found) > limit:
                    return found
        return found

    options = solve(0)
    if not options or len(options) > limit:
        return None
    best = max(score for _, score in options)
    winners = {names for names, score in options if score == best}
    return list(next(iter(winners))) if len(winners) == 1 else None


def kdb_result_roster(text, known=frozenset()):
    """[(field, [names])] from a KDB result table, or [] when any line is unclear."""
    match = re.search(r'운용사명\s*(?:\(가나다순\))?', text)
    if not match:
        return []
    rosters = []
    pending_size = None
    lines = text[match.end():].splitlines()
    size_labels = {'대형', '중형', '소형'}
    wrapped_size_table = (re.search(r'지원분야\s*선정\s*운용사명', text[:match.end()])
                          and any(line.strip() in size_labels for line in lines))
    for line in lines:
        line = line.strip()
        if not line:
            continue
        label = next((l for l in KDB_FIELD_LABELS if line.startswith(l)), None)
        if pending_size:
            if label:
                return []
            label, pending_size = pending_size, None
            manager_text = line
        elif label:
            manager_text = line[len(label):]
            if wrapped_size_table and label in size_labels and not manager_text:
                pending_size = label
                continue
        else:
            return []
        if wrapped_size_table and label in size_labels:
            manager_text = re.sub(r'\((?:주|유)\)|㈜', '', manager_text)
        names = split_glued_names(manager_text, known)
        if not names:
            return []
        rosters.append((label, names))
    labels = {label for label, _ in rosters}
    if pending_size:
        return []
    if labels & {'PE', 'VC'}:
        # Mixed PE·VC programs: only the PE field is a PE result.
        rosters = [(label, names) for label, names in rosters if label == 'PE']
    return rosters


def _attach_result_roster(p, members, holds, known=frozenset()):
    """Official result names: IBK result body, KDB result attachment table, and the
    board layouts in lp_result_rosters for the other institutions (2020+ history)."""
    institution = p.get('institution_id')
    if p.get('selected_gps') or institution in ('kgrowth', 'kexim', 'koreapost'):
        return  # these have their own reviewed or dedicated roster paths
    results = [n for n in members if _event(n)['type'] in ('선정 결과', '최종 선정')]
    if len(results) != 1:
        return
    result = results[0]
    if institution == 'ibk':
        rosters = ibk_result_roster(result['body'])
    elif institution != 'kdb':
        readings = [result_rosters.pe_result_roster(text, known=known, valid=_rule_valid_name,
                                                    split_glued=split_glued_names,
                                                    pe_only_program=p.get('asset_scope') == 'PE')
                    for text in _texts(result)]
        readings = [r for r in readings if r]
        if not readings:
            return
        if any(r != readings[0] for r in readings[1:]):
            holds.append({'stage': 'result_roster', 'url': result['url'], 'reason': '본문·첨부 명단이 서로 다름'})
            return
        rosters = readings[0]
    else:
        def split_names(names):
            return split_glued_names(names, known)

        texts = _texts(result)[1:]
        evidence = p.get('extraction_evidence', {})
        if evidence.get('growth_support_joint_allocation'):
            bank_names = known | set(INSTITUTION_TITLE_NAMES.get('ibk', ()))
            tables = [kdb_growth_support.result_roster(result, text, p, lambda names: split_glued_names(names, bank_names))
                      for text in texts]
        elif evidence.get('growth_support_2024_first_allocation'):
            tables = [kdb_growth_support_2024.result_roster(result, text, p) for text in texts]
        elif evidence.get('innovation_2024_first_allocation'):
            tables = [kdb_innovation_2024_first.result_roster(result, text, p) for text in texts]
        elif evidence.get('innovation_2024_second_allocation'):
            tables = [kdb_innovation_2024_second.result_roster(result, text, p) for text in texts]
        elif evidence.get('innovation_joint_allocation'):
            tables = [kdb_innovation.result_roster(result, text, p, split_names) for text in texts]
        elif evidence.get('recovery_market_allocation'):
            tables = [kdb_recovery.result_roster(result, text, p, split_names) for text in texts]
        elif evidence.get('ai_fixed_joint_allocation'):
            tables = [kdb_ai_fixed.result_roster(result, text, p) for text in texts]
        elif evidence.get('semiconductor_blind_allocation'):
            tables = [kdb_semiconductor.result_roster(result, text, p) for text in texts]
        else:
            tables = [kdb_result_roster(text, known) or kdb_reopen.result_roster(result, text, p)
                      or kdb_nuclear.result_roster(result, text, p, split_names)
                      or kdb_media.result_roster(result, text, p, split_names) for text in texts]
        tables = [t for t in tables if t]
        if len(tables) != 1:
            if tables:
                holds.append({'stage': 'result_roster', 'url': result['url'], 'reason': '결과 첨부 표가 여러 개'})
            return
        rosters = tables[0]
    names = [name for _, names in rosters for name in names]
    if not names:
        return
    if len(set(names)) != len(names):
        holds.append({'stage': 'result_roster', 'url': result['url'], 'reason': '선정 명단 중복'})
        return
    p['selected_gps'] = [{'name': name, 'id': f'{institution}-' + hashlib.sha256(name.encode()).hexdigest()[:16],
                          'source_url': result['url'],
                          'asset_scope': 'PE' if {l for l, _ in rosters} == {'PE'} else p.get('asset_scope', 'PE'),
                          'identity_match': 'official_result_body'} for name in names]
    p.setdefault('gp_tracks', {}).update({name: league for league, names in rosters for name in names})
    p.setdefault('manager_list_sources', {})['selected_gps'] = result['url']
    if p.get('status') == '선정 결과 발표':
        p['status'] = '선정 완료'


def _attach_preferred_roster(p, original, members, checked_at, holds):
    if original['institution_id'] != 'koreapost':
        return
    preferred = [n for n in members if _event(n)['type'] == '우선협상대상자']
    if preferred:
        try:
            if len(preferred) != 1:
                raise ValueError('Conflicting preferred-bidder notices')
            roster = extract_preferred(original, preferred[0], checked_at=checked_at)
            if roster['source_url'] not in {e['url'] for e in p['events'] if e['type'] == '우선협상대상자'}:
                raise ValueError('Preferred roster lacks matching program stage')
            prior = p.get('preferred_gps', [])
            if prior and (prior != roster['preferred_gps'] or
                          p.get('manager_list_sources', {}).get('preferred_gps') != roster['source_url']):
                raise ValueError('Existing preferred roster changed')
            tracks = {name: r['league'] for r in roster['rosters'] for name in r['names']}
            if any(name in p.get('gp_tracks', {}) and p['gp_tracks'][name] != track for name, track in tracks.items()):
                raise ValueError('Preferred roster league conflicts with prior evidence')
            p['preferred_gps'] = copy.deepcopy(roster['preferred_gps'])
            p.setdefault('manager_list_sources', {})['preferred_gps'] = roster['source_url']
            p.setdefault('gp_tracks', {}).update(tracks)
        except (KeyError, TypeError, ValueError) as exc:
            holds.append({'stage': 'preferred_roster', 'url': preferred[0]['url'], 'reason': str(exc)})


def _institution_title_names():
    """Each institution's own names (master CSV name and 3+ character Korean aliases)."""
    import csv
    names = {}
    try:
        with open(ROOT / 'data' / 'lp_institutions.csv', encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                aliases = [a.strip() for a in row.get('aliases', '').split(';') if re.search(r'[가-힣]{3,}', a)]
                names[row['lp_code']] = tuple(n for n in (row.get('lp_name', ''), *aliases) if n)
    except (OSError, KeyError):
        pass
    for key, name in _names().items():
        names[key] = tuple(dict.fromkeys((*names.get(key, ()), name)))
    return names


INSTITUTION_TITLE_NAMES = _institution_title_names()
_RESULT_TYPES = ('선정 결과', '최종 선정', '우선협상대상자', '1차 심사 결과', '접수 결과')
_ORPHAN_WINDOW_DAYS = 240


def _identity_without_institution(n):
    """Identity title without the institution's own names (공무원연금 2024: the
    recruitment names 공무원연금공단, the result does not)."""
    title = n['title']
    for name in sorted(INSTITUTION_TITLE_NAMES.get(n['institution_id'], ()), key=len, reverse=True):
        title = title.replace(name, ' ')
    return _identity({**n, 'title': title})


_GENERIC_RESULT_WORDS = re.compile(
    r'20\d{2}년?도?|[\'’`´]\d{2}년?|위탁운용사|운용사|위탁|최종|선정|결과|공지|공고|안내|게시|발표|알림|재단|[\[\]【】()（）,.·\s]')


def _generic_result_title(n):
    """A result title that names no fund, round, track or year of its own once the
    institution's names are removed ("총회연금재단 2026 위탁운용사 최종 선정 결과 공지").
    Results that name anything specific must match by title instead."""
    title = n['title']
    for name in sorted(INSTITUTION_TITLE_NAMES.get(n['institution_id'], ()), key=len, reverse=True):
        title = title.replace(name, ' ')
    year = re.search(r'20\d{2}', title)
    if year and year[0] != n['date'][:4]:
        return False
    return not _GENERIC_RESULT_WORDS.sub('', title)


def _recruitments(members, shared, checked_at):
    """One ministry/LP original may also appear as a verified association repost.

    Keep every source in members/events, but use the own-board notice as the
    recruitment anchor only when date, title, scope, PE amount, fund count and
    deadline agree. A date-only repost may refine to the own board's time on
    that same date. Conflicting or incomplete facts remain separate candidates.
    """
    originals = [n for n in members if _event(n)['type'] == '모집 공고']
    if len(originals) < 2 or checked_at is None:
        return originals
    own = [n for n in originals if n.get('source_channel') == 'institution_board' and not n.get('channel_id')]
    if len(own) != 1:
        return originals
    anchor = own[0]
    scope = _scope(anchor)
    if scope not in ('pe_blind', 'mixed_pe_blind'):
        return originals
    facts, raw = _terms(anchor, shared.get(anchor['url']), checked_at)
    if raw.get('deadline_error') or any(facts.get(k) is None for k in ('deadline', 'commitment_amount_krw', 'manager_count')):
        return originals
    for n in originals:
        if n is anchor:
            continue
        host = (urlsplit(n['url']).hostname or '').removeprefix('www.')
        if (host not in REPOST_HOSTS or n.get('source_channel') == 'institution_board'
                or n['institution_id'] != anchor['institution_id'] or n['date'] != anchor['date']
                or compact(n['title']) != compact(anchor['title']) or _scope(n) != scope):
            return originals
        other, raw = _terms(n, shared.get(n['url']), checked_at)
        if (raw.get('deadline_error') or not other.get('deadline')
                or any(other.get(k) != facts[k] for k in ('commitment_amount_krw', 'manager_count'))
                or other['deadline'][:10] != facts['deadline'][:10]
                or (other.get('deadline_precision') == facts.get('deadline_precision') == 'datetime'
                    and other['deadline'] != facts['deadline'])):
            return originals
    return [anchor]


def _merge_orphan_results(groups, shared=None, checked_at=None):
    """Attach result-only groups to their recruitment group at the same institution.

    Joined when the titles match without the institution's names, or when exactly one
    PE recruitment of that institution was announced in the 240 days before the result
    and the result itself speaks of PE. Anything ambiguous stays apart (no guess)."""
    announcements = {}
    for key, members in groups.items():
        originals = _recruitments(members, shared or {}, checked_at)
        if len(originals) == 1:
            announcements[key] = originals[0]
    for key, members in list(groups.items()):
        if key not in groups or any(_event(n)['type'] == '모집 공고' for n in members):
            continue
        if not members or not all(_event(n)['type'] in _RESULT_TYPES for n in members):
            continue
        first = min(members, key=lambda n: n['date'])
        institution = first['institution_id']
        same = {k: a for k, a in announcements.items() if a['institution_id'] == institution and k in groups}
        by_title = [k for k, a in same.items() if _identity_without_institution(a) == _identity_without_institution(first)]
        target = by_title[0] if len(by_title) == 1 else None
        # A result posted by the fund's OCIO (second channel, AGENTS.md source order) names
        # the fund, its year and the PE track but words the track differently from the
        # fund's own recruitment ("(PE)" for "(PEF, VC)"): same window rule, same year.
        ocio = bool(first.get('channel_id')) and re.search(r'20\d{2}', first['title'])
        if target is None and not by_title and (_generic_result_title(first) or ocio):
            text = ' '.join([first['title'], first.get('body', '')[:4000]])
            if re.search(r'(?<![A-Za-z])PEF?(?![A-Za-z])|사모|블라인드', text, re.I):
                window = [k for k, a in same.items()
                          if 0 <= (date.fromisoformat(first['date']) - date.fromisoformat(a['date'])).days <= _ORPHAN_WINDOW_DAYS
                          and (not ocio or ocio[0] in a['title'] or (not re.search(r'20\d{2}', a['title'])
                                                                    and a['date'][:4] == ocio[0]))
                          and _scope(a) in ('pe_blind', 'mixed_pe_blind')
                          and not any(_event(n)['type'] in ('선정 결과', '최종 선정') for n in groups[k])]
                target = window[0] if len(window) == 1 else None
        if target is not None:
            for n in members:
                n.setdefault('stage_link', 'title_without_institution_name' if by_title else
                             'ocio_result_single_recruitment' if ocio else 'single_recruitment_in_window')
            groups[target] = groups[target] + members
            del groups[key]


def publish_basic_notices(data, growth_notices, checked_at, skips=None, known_gp_names=()):
    """Extend validated public programs; never consume a prepared candidate fact.

    `skips` (optional list) receives the groups left out without a hold, with the
    rule that left them out; used by offline history review only."""
    def skip(key, members, reason):
        if skips is not None:
            skips.append({'program_key': key, 'reason': reason,
                          'urls': sorted(n['url'] for n in members), 'titles': sorted({n['title'] for n in members})})
    names = _names()
    docs, shared, holds = _sources(data, growth_notices, checked_at)
    groups = defaultdict(list)
    recovery_stages = kdb_recovery.linked_stages(docs.values(), _texts)
    ai_faqs = kdb_ai_fixed.linked_faqs(docs.values(), _texts)
    policy_stages = defaultdict(list)
    for policy in (kdb_growth_support_2024, kdb_innovation_2024_first, kdb_innovation_2024_second):
        for url, original in policy.linked_stages(docs.values(), _texts).items():
            policy_stages[url].append(original)
    for n in docs.values():
        if (phase := kdb_recovery.role(n)) and phase != kdb_recovery.RECRUITMENT:
            if original := recovery_stages.get(n['url']):
                groups[_identity(original)].append(n)
            else:
                holds.append({'stage': 'basic_stage_link', 'url': n['url'], 'reason': '회수시장 활성화 원공고 일정 또는 후속 근거 미확인'})
        elif original := ai_faqs.get(n['url']):
            groups[_identity(original)].append(n)
        elif kdb_growth_support_2024.shared_stage(n) or kdb_innovation_2024_second.shared_stage(n):
            if originals := policy_stages.get(n['url']):
                for original in originals:
                    groups[_identity(original)].append(n)
            else:
                skip(_identity(n), [n], 'unverified_shared_stage')
        elif kdb_innovation_2024_second.growth_finance_recruitment(n, _texts):
            skip(_identity(n), [n], 'different_policy_lead')
        elif n['institution_id'] in names and n['institution_id'] not in {'pck_pension','kfinco'} and notice_stage(n['title']) in STAGES:
            groups[_identity(n)].append(n)
    # Each observed recruitment anchors its own solicitation. Similar June and
    # September titles do not establish one round or share each other's dates.
    kfinco_originals={n['url']:n for n in docs.values() if n['institution_id']=='kfinco' and _event(n)['type']=='모집 공고'}
    for source in kfinco_originals.values():
        groups[_identity(source)+':'+source['url']].append(source)
    for source in docs.values():
        if source['institution_id']!='kfinco' or source['url'] in kfinco_originals or _event(source)['type'] not in STAGES:
            continue
        anchors=[kfinco_originals[url] for url in source.get('related_notice_urls',[]) if url in kfinco_originals and kfinco_originals[url]['date']<=source['date']]
        if len(anchors)==1:
            anchor=anchors[0];groups[_identity(anchor)+':'+anchor['url']].append(source)
        else:
            holds.append({'stage':'basic_stage_link','url':source['url'],'reason':'KFINCO stage has no unique official recruitment link'})
    pck_groups, pck_holds = pck_programs.groups([n for n in docs.values() if n['institution_id'] == 'pck_pension'], data['programs'])
    groups.update(pck_groups)
    holds.extend(pck_holds)
    _merge_orphan_results(groups, shared, checked_at)
    programs = {p['id']: copy.deepcopy(p) for p in data['programs']}
    # Manager names already published anywhere help split glued result tables.
    known_names = frozenset(
        name for p in data['programs']
        for name in [*(g.get('name') for g in p.get('selected_gps') or []), *(p.get('preferred_gps') or []),
                     *(p.get('shortlisted_gps') or []), *(p.get('applicants_gps') or [])]
        if isinstance(name, str) and name.strip()) | frozenset(n for n in known_gp_names if isinstance(n, str) and n.strip())
    for key, members in sorted(groups.items()):
        try:
            originals = _recruitments(members, shared, checked_at)
            previous_recruitment = None
            previous_recruitment_url = None
            if len(originals) == 2:
                ordered = sorted(originals, key=lambda n: n['date'])
                previous_recruitment = kdb_media.verified_previous_recruitment(ordered)
                if previous_recruitment:
                    previous, current = ordered
                    if any(n['date'] < current['date'] and n['url'] != previous['url'] for n in members):
                        raise ValueError('K-콘텐츠·미디어 첫 모집 후속 공고의 리그 분리 필요')
                    previous_recruitment_url = previous['url']
                    originals = [current]
            if len(originals) > 1:
                # Same-titled recruitments in one year (국민연금 2020: PEF+VC in March, VC only in
                # August): keep the single PE one; the others are not this program's recruitment.
                pe = [o for o in originals if _scope(o) in ('pe_blind', 'mixed_pe_blind')]
                if len(pe) == 1:
                    members = [n for n in members if n not in originals or n is pe[0]]
                    originals = pe
            if len(originals) != 1:
                skip(key, members, 'no_announcement' if not originals else 'several_announcements')
                continue
            original = originals[0]
            urls = {n['url'] for n in members}
            # Shared lifecycle notices establish a stage, not a program's identity.
            identity_urls = urls - policy_stages.keys()
            matches = [p for p in programs.values() if p['institution_id'] == original['institution_id']
                       and (p.get('source_program_key') == key or identity_urls & {e['url'] for e in p['events']}
                            or (original['institution_id'] == 'pck_pension' and urls & {
                                pck_programs._canonical(e['url']) for e in p['events']}))]
            if len(matches) > 1:
                raise ValueError('복수 기존 사업과 연결; 차수 확인 필요')
            if matches and matches[0].get('manual_review_id'):
                continue
            # A previously reviewed public program already owns its eligibility
            # evidence. Advancing its sourced stage does not require reapproving
            # its terms or interpreting its GP list again.
            reviewed = matches and not matches[0].get('basic_publication')
            if not reviewed and _scope(original) not in ('pe_blind', 'mixed_pe_blind'):
                skip(key, members, 'scope:' + str(_scope(original)))
                continue
            terms, raw_terms = _terms(original, shared.get(original['url']), checked_at)
            if previous_recruitment:
                terms.setdefault('extraction_evidence', {})['prior_media_recruitment'] = [previous_recruitment]
            if raw_terms.get('deadline_error'):
                holds.append({'stage': 'basic_deadline', 'url': original['url'], 'reason': raw_terms['deadline_error']})
            if raw_terms.get('allocation_reading_failed'):
                holds.append({'stage': 'basic_allocation', 'url': original['url'], 'reason': raw_terms['allocation_error']})
            mixed_open = False
            if not reviewed and _scope(original) == 'mixed_pe_blind' and not ((raw_terms.get('amount_scope') == 'pe_only' and raw_terms.get('commitment_amount_krw')) or kbiz_terms.pe_track(original)):
                if original['institution_id'] not in PE_TRACK_INSTITUTIONS:
                    skip(key, members, 'mixed_without_pe_amount')
                    continue
                # Published as one joint PE·VC program; a combined amount says so.
                mixed_open = True
                for field in ('commitment_label', 'list_commitment_label'):
                    if terms.get(field) and raw_terms.get('amount_scope') != 'pe_only':
                        terms[field] = f"{terms[field]} (PE·VC 합계)"
            if (not reviewed and original.get('source_channel') == 'institution_board'
                    and '공동투자' in original['body'] and not raw_terms.get('extraction_evidence', {}).get('blind_allocation')):
                skip(key, members, 'coinvestment_without_blind_allocation')
                continue
            if matches:
                p = matches[0]
                if (not p.get('basic_publication') and not p.get('publication_version')
                        and not (urls - {e['url'] for e in p['events']})
                        and original['institution_id'] != 'pck_pension'):
                    # A retained preferred event may gain its verified roster
                    # without refreshing reviewed terms, dates or schedules.
                    if p.get('status') == '우선협상대상자' and not p.get('preferred_gps'):
                        _attach_preferred_roster(p, original, members, checked_at, holds)
                    continue
                # Complete reviewed programs retain their validated offering
                # facts. Lifecycle links can advance without guessing GP names.
                if p.get('basic_publication'):
                    for field in OFFERING_FIELDS:
                        p.pop(field, None)
                    p.update(terms)
                elif original['institution_id'] == 'pck_pension' and pck_programs.offering_sources(original):
                    # Refresh only sourced dates for the old reviewed round;
                    # never reinterpret its GP list or combined budget.
                    for field in ('deadline', 'deadline_precision', 'extraction_evidence'):
                        if field in terms:
                            p[field] = copy.deepcopy(terms[field])
            else:
                fund = _fund_name(original['title'])
                if original['institution_id'] in PE_TRACK_INSTITUTIONS and fund and any(
                        q['institution_id'] != original['institution_id']
                        and (fund in _fund_key(q.get('title')) or fund in _fund_key(q.get('display_title')))
                        for q in programs.values()):
                    # Another round of the same institution's fund (1차 → 2차) is its own program.
                    # Joint notices (several LPs) and funds already published by another LP.
                    holds.append({'stage': 'basic_publication', 'program_key': key, 'reason': '같은 펀드가 다른 기관 사업으로 이미 공개됨'})
                    continue
                identity = original['institution_id'] + '-' + original['date'][:4] + '-' + hashlib.sha256(original['url'].encode()).hexdigest()[:16]
                p = {'id': identity, 'institution_id': original['institution_id'],
                     'institution_name': names[original['institution_id']], 'title': original['title'],
                     'asset_scope': 'PE', 'status': '모집 공고', 'selected_gps': [], 'events': [],
                     'basic_publication': True, 'source_program_key': key, **terms}
            if mixed_open:
                p['asset_scope'] = MIXED_SCOPE_LABEL
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
            _refresh(p, members, checked_at, original=original, previous_recruitment_url=previous_recruitment_url)
            _attach_preferred_roster(p, original, members, checked_at, holds)
            _attach_result_roster(p, members, holds, known_names)
            p['publication_version'] = 1
            p['source_program_key'] = key
            programs[p['id']] = p
        except (KeyError, TypeError, ValueError) as exc:
            holds.append({'stage': 'basic_publication', 'program_key': key, 'reason': str(exc)})
    return merge_reposted_duplicates(list(programs.values()), holds), holds


def _title_core(title):
    """Title without board prefixes, '[기관명]', 계획/공고 wording or spacing."""
    text = re.sub(r'^\s*(?:\[[^\]]{1,30}\]\s*)+', '', str(title or ''))
    text = re.sub(r'선정\s*계획|선정|계획|공고|위탁운용사|운용사', '', text)
    return re.sub(r'[^0-9A-Za-z가-힣]', '', text).lower()


# Association boards that repost institutions' notices (collect_lp_original_notices.load_channels).
REPOST_HOSTS = ('kofia.or.kr', 'kvca.or.kr', 'vcs.go.kr')


def _own_site(p):
    """True when a program's notice comes from the institution's own site, not a repost board."""
    hosts = [(urlsplit(e.get('url', '')).hostname or '').removeprefix('www.') for e in p.get('events', [])]
    return any(host and not host.endswith(REPOST_HOSTS) for host in hosts)


def merge_reposted_duplicates(programs, holds):
    """One program per solicitation when an association repost and the institution's own
    board both produced one (same institution, announcement date, deadline, amount and title).

    The program on the institution's own site is kept; the repost's extra dated events are
    added to it. Reviewed programs (not basic_publication) are never merged.
    """
    def signature(p):
        announced = min((e['date'] for e in p.get('events', []) if e.get('type') == '모집 공고'), default=None)
        return (p['institution_id'], announced, p.get('deadline'), p.get('commitment_amount_krw'), _title_core(p.get('title')))

    groups = defaultdict(list)
    for p in programs:
        sig = signature(p)
        if p.get('basic_publication') and sig[1] and sig[2]:
            groups[sig].append(p)
    dropped = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        keep = sorted(members, key=lambda p: (not _own_site(p), -len(p.get('selected_gps') or []), -len(p.get('events', [])), p['id']))[0]
        seen = {(e.get('type'), e.get('date')) for e in keep.get('events', [])}
        for other in members:
            if other is keep:
                continue
            for event in other.get('events', []):
                if (event.get('type'), event.get('date')) not in seen:
                    keep['events'].append(copy.deepcopy(event))
                    seen.add((event.get('type'), event.get('date')))
            dropped.add(other['id'])
            holds.append({'stage': 'basic_duplicate', 'program_key': other.get('source_program_key'),
                          'program_id': other['id'], 'kept_program_id': keep['id'],
                          'reason': f"같은 출자사업의 재게시 공고: {keep['id']}로 합침"})
        keep['events'].sort(key=lambda e: (e['date'], e.get('type', '')))
    return [p for p in programs if p['id'] not in dropped]
