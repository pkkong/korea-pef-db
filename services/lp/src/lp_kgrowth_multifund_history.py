"""Pure review of a comma-separated recruitment notice's separate fund PDFs.

The caller still validates listing/detail originals and replays attachment bytes.
This module reads retained text and recorded fingerprints, never approves PE scope
or publishes programs. Budget cells describe recruitment plans, not GP awards.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import date
from urllib.parse import parse_qs, urlsplit

try:
    from .kgrowth_listing import source_id
    from .lp_notice_triage import notice_stage
except ImportError:
    from kgrowth_listing import source_id
    from lp_notice_triage import notice_stage


_NUMBER = r'(?:[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d*)'
_BULLET = r'[ㅇᄋ◦o]'
_HASH = re.compile(r'[a-f0-9]{64}')
_FUND_NAME = r'([가-힣A-Za-z0-9·ㆍ()\-]{1,80}?펀드(?:\(제?[1-9]\d*차\))?)'
_HEADING = _FUND_NAME + r'위탁운용사선정계획(?:공고|을아래와같이공고합니다\.)'


def _compact(value):
    return re.sub(r'\s|\u200b', '', unicodedata.normalize('NFKC', value))


def _quote(raw, normalized):
    chars, positions = [], []
    for i, char in enumerate(raw):
        for value in unicodedata.normalize('NFKC', char):
            if not value.isspace() and value != '\u200b':
                chars.append(value)
                positions.append(i)
    start = ''.join(chars).find(normalized)
    if start < 0 or not normalized:
        raise ValueError('첨부 원문과 모집조건 인용 불일치')
    return raw[positions[start]:positions[start + len(normalized) - 1] + 1]


def _money(value):
    if not re.fullmatch(_NUMBER, value):
        raise ValueError('금액 숫자 표기 미확인')
    return int(value.replace(',', '')) * 100_000_000


def _evidence(n, url, raw, normalized):
    return {'source_url': n['url'], 'sha256': n['sha256'],
            'attachment_url': url, 'attachment_sha256': n['attachment_hashes'][url],
            'quote': _quote(raw, normalized)}


def _split_round(name):
    rounds = re.findall(r'\(제?([1-9]\d*)차\)|제?([1-9]\d*)차$', name)
    values = {a or b for a, b in rounds}
    if len(values) > 1:
        raise ValueError('첨부 펀드명의 숫자 회차 충돌')
    base = re.sub(r'\(제?[1-9]\d*차\)|제?[1-9]\d*차$', '', name)
    return base, next(iter(values)) + '차' if values else ''


def _identity(text, posted, raw):
    clean = re.sub(r'^-\d+-', '', text)
    heading = re.match(_HEADING, clean)
    if not heading:
        raise ValueError('첨부 첫 머리말의 단일 전체 펀드명 미확인')
    fund, round_ = _split_round(heading[1])
    for line in raw.splitlines():
        repeated = re.match(_FUND_NAME + r'위탁운용사선정계획공고',
                            re.sub(r'^-\d+-', '', _compact(line)))
        if repeated and _split_round(repeated[1]) != (fund, round_):
            raise ValueError('첨부의 반복 모집 머리말 펀드명·회차 충돌')
    intro = re.search(r'(20\d{2})년(?:제?([1-9]\d*)차)?'
                      r'([가-힣A-Za-z0-9·ㆍ()\-]{1,80}펀드(?:\(제?[1-9]\d*차\))?)'
                      r'위탁운용사선정계획', clean[:350])
    years, quotes = set(), [heading[0]]
    if intro:
        intro_fund, intro_round = _split_round(intro[3])
        if intro[2]:
            if intro_round and intro_round != intro[2] + '차':
                raise ValueError('첨부 소개 문장의 회차 충돌')
            intro_round = intro[2] + '차'
        if intro_fund != fund or round_ and intro_round and round_ != intro_round:
            raise ValueError('첨부 머리말·소개 문장의 펀드명 또는 회차 충돌')
        round_ = round_ or intro_round
        years.add(intro[1])
        quotes.append(intro[0])
    footers = list(re.finditer(r'(20\d{2})년([1-9]\d?)월([1-9]\d?)일한국성장금융', text[-1300:]))
    if len(footers) != 1:
        raise ValueError('첨부 말미의 공고 연도·발행일 미확인')
    footer = footers[0]
    try:
        issued = date(*map(int, footer.group(1, 2, 3))).isoformat()
    except ValueError as exc:
        raise ValueError('첨부 발행일의 달력 날짜 미확인') from exc
    years.add(footer[1])
    if len(years) != 1 or issued != posted:
        raise ValueError('첨부의 사업 연도·발행일과 원공고 충돌')
    quotes.append(footer[0])
    return {'fund': fund, 'year': footer[1], 'round': round_,
            'year_basis': '첨부 발행일과 게시일 대조'}, quotes


def _parts(block, separator):
    result = []
    for value in re.split(separator, block):
        if not value:
            continue
        hit = re.fullmatch(r'(.+?)(' + _NUMBER + r')억원(?:이내)?', value)
        if not hit:
            raise ValueError('공동 출자자별 계획 금액 양식 미확인')
        result.append({'label': hit[1], 'amount_krw': _money(hit[2])})
    if not result:
        raise ValueError('공동 출자자별 계획 금액 없음')
    return result


def _reconciled(total, parts):
    if sum(p['amount_krw'] for p in parts) != total:
        raise ValueError('명시 총액과 공동 출자금액 합계 불일치')


def _one(pattern, text):
    matches = list(re.finditer(pattern, text))
    return matches[0] if len(matches) == 1 else None


def _budget(text):
    # The column headings, not fund names or notice IDs, select each layout.
    if '위탁운용금액및결성목표액' in text:
        hit = _one(r'위탁운용금액및결성목표액' + _BULLET + r'총(' + _NUMBER + r')억원이내'
            r'성장사다리펀드공동출자자합계결성목표액(' + _NUMBER + r')억원이내('
            + _NUMBER + r')억원이내(' + _NUMBER + r')억원(' + _NUMBER + r')억원', text)
        proposal = _one(r'운용사별로(' + _NUMBER + r')억원~(' + _NUMBER + r')억원범위내에서제안', text)
        if not hit or not proposal or '위탁운용금액범위내선정' not in text:
            raise ValueError('공동 출자·결성목표·제안 범위 표 미확인')
        total = _money(hit[1])
        parts = [{'label': '성장사다리펀드', 'amount_krw': _money(hit[2])},
                 {'label': '공동출자자', 'amount_krw': _money(hit[3])}]
        _reconciled(total, parts)
        if total != _money(hit[4]) or _money(proposal[1]) > _money(proposal[2]):
            raise ValueError('공통 출자 합계 또는 제안 금액 범위 불일치')
        return {'layout': 'co_investment_formation_target', 'shared_planned_amount_krw': total,
                'shared_tracks': [{'label': '공통 모집', 'amount_krw': total, 'amount_bound': '이내',
                    'planned_fund_count': None, 'selection_basis': '위탁운용금액 범위 내 선정',
                    'proposal_per_manager_min_krw': _money(proposal[1]),
                    'proposal_per_manager_max_krw': _money(proposal[2])}],
                'shared_contributors': parts, 'stated_formation_target_krw': _money(hit[5])}, [hit[0], proposal[0]]
    if re.search(r'항목세부내용[^\d]{1,20}리그[^\d]{1,20}리그위탁운용금액', text):
        row = (_BULLET + r'총(' + _NUMBER + r')억원-([^\d]+)(' + _NUMBER
               + r')억원-([^\d]+)(' + _NUMBER + r')억원')
        hit = _one(r'항목세부내용(.+?리그)(.+?리그)위탁운용금액' + row + row
                        + r'선정운용사수' + _BULLET + r'([1-9]\d?)개사' + _BULLET + r'([1-9]\d?)개사', text)
        sizes = _one(r'최소결성금액' + _BULLET + '(' + _NUMBER + r')억원' + _BULLET
                          + '(' + _NUMBER + r')억원출자비율' + _BULLET + r'약정총액의(100|[1-9]?\d)%이내'
                          + _BULLET + r'약정총액의(100|[1-9]?\d)%이내', text)
        if not hit or not sizes or hit[1] == hit[2]:
            raise ValueError('두 리그의 금액·예정 수·최소결성·상한 열 미확인')
        tracks = []
        for label_index, start, count_index, size_index in [(1, 3, 13, 1), (2, 8, 14, 2)]:
            parts = [{'label': hit[start + 1], 'amount_krw': _money(hit[start + 2])},
                     {'label': hit[start + 3], 'amount_krw': _money(hit[start + 4])}]
            total = _money(hit[start]); _reconciled(total, parts)
            tracks.append({'label': hit[label_index], 'amount_krw': total,
                           'planned_fund_count': int(hit[count_index]), 'shared_contributors': parts,
                           'minimum_fund_size_krw': _money(sizes[size_index]),
                           'lp_ratio_max_pct': int(sizes[size_index + 2])})
        return {'layout': 'two_stage_leagues', 'shared_tracks': tracks,
                'shared_planned_amount_krw': None}, [hit[0], sizes[0]]
    hit = _one(r'위탁운용금액' + _BULLET + r'(총)?(' + _NUMBER + r')억원이내-(.+?)'
                    r'선정운용사수' + _BULLET + r'([1-9]\d?)개사(이내)?', text)
    if not hit:
        raise ValueError('펀드별 공통 예산 표 미확인')
    total = _money(hit[2]); parts = _parts(hit[3], r'[-/]'); _reconciled(total, parts)
    track = {'label': '공통 모집', 'amount_krw': total, 'amount_bound': '이내',
             'planned_fund_count': int(hit[4]), 'fund_count_basis': hit[5] or '명시'}
    result = {'layout': 'shared_single_fund', 'shared_planned_amount_krw': total,
              'shared_tracks': [track], 'shared_contributors': parts}
    quotes = [hit[0]]
    if hit[1]:
        maxima = _one(r'위탁운용사별최대출자금액은(' + _NUMBER + r')억원,(' + _NUMBER + r')억원임', text)
        sizes = _one(r'최소결성금액' + _BULLET + '(' + _NUMBER + r')억원이상\(펀드별('
                          + _NUMBER + r')억원,(' + _NUMBER + r')억원\)이상출자금액' + _BULLET
                          + r'총(' + _NUMBER + r')억원이내\(펀드별(' + _NUMBER + r')억원,('
                          + _NUMBER + r')억원\)', text)
        primary = _one('주목적투자대상에(' + _NUMBER + r')억원\(펀드별(' + _NUMBER
                            + r')억원,(' + _NUMBER + r')억원\)이상', text)
        if not maxima or not sizes or not primary or int(hit[4]) != len(maxima.groups()):
            raise ValueError('펀드별 최대출자·최소결성·주목적 금액 열 미확인')
        max_values = [_money(v) for v in maxima.groups()]
        if (sum(max_values) != total or _money(sizes[4]) != total
                or [_money(sizes[5]), _money(sizes[6])] != max_values
                or _money(sizes[1]) != _money(sizes[2]) + _money(sizes[3])
                or _money(primary[1]) != _money(primary[2]) + _money(primary[3])):
            raise ValueError('펀드별 명시 금액과 합계 불일치')
        track.update(proposed_per_manager_maxima_krw=max_values,
                     minimum_fund_sizes_krw=[_money(sizes[2]), _money(sizes[3])],
                     primary_investment_minima_krw=[_money(primary[2]), _money(primary[3])])
        quotes += [maxima[0], sizes[0], primary[0]]
    else:
        size = _one('최소결성금액' + _BULLET + r'최소(' + _NUMBER + r')억원이상', text)
        if not size:
            raise ValueError('단일 공통 모집의 최소결성금액 미확인')
        track['minimum_fund_size_krw'] = _money(size[1]); quotes.append(size[0])
    return result, quotes


def _scope(text):
    legal = re.search(r'(?:출자대상)?투자기구' + _BULLET + r'.+?(?=운용사신청자격|운용사선정방법)', text)
    target = re.search(r'2\.(?:출자분야및)?투자대상.+?(?=3\.주요출자조건)', text)
    if not legal or not target:
        raise ValueError('현재 투자기구·투자대상 구간 미확인')
    pe = bool(re.search(r'경영참여형사모집합투자기구|기관전용사모집합투자기구', legal[0]))
    vc = bool(re.search(r'벤처투자조합|중소기업창업투자조합|신기술사업투자조합', legal[0]))
    direct = bool(re.search(r'투자대상(?:기업)?은법인형태의국내', target[0]))
    overseas = re.search(r'해외투자.+?비주목적투자.+?약정총액(100|[1-9]?\d)%', target[0])
    domestic = '국내 투자대상 명시' if direct else '국내 투자범위 미확인'
    if direct and overseas:
        domestic = '국내 주목적·해외 비주목적 허용'
    status = {'pe_legal_form_observed': pe, 'vc_legal_forms_observed': vc,
              'independent_pe_track_verified': False, 'blind_status': '미확인',
              'domestic_scope_status': domestic,
              'overseas_non_primary_max_pct': int(overseas[1]) if overseas else None}
    hold = ('PE·VC 허용 법형태가 혼합되어 독립 PE 블라인드 트랙 미확인' if pe and vc
            else '현재 모집의 독립 PE 블라인드 트랙 미확인')
    return status, hold, [legal[0], target[0]]


def parse_multifund_notice(notice):
    """Read separate fund attachments; unsupported notices return None.

    identities use the full heading's fund name with explicit numeric rounds
    separated into round. Roman fund stages remain part of the name. The parent
    must apply the same identity rule to result groups, without fuzzy joining.
    Attachment parse failures are retained in holds; other valid funds survive.
    """
    n = notice
    title = unicodedata.normalize('NFKC', n.get('title', ''))
    prefix = re.sub(r'^【[^】]*】', '', title).split('위탁운용사', 1)[0]
    # Commas inside a single quoted fund or parenthesized method are not a fund list.
    unparenthesized = re.sub(r'\([^()]*\)', '', prefix)
    if (notice_stage(title) != '모집 공고' or '위탁운용사선정계획공고' not in _compact(title)
            or re.search(r'[「『]', prefix)
            or unparenthesized.count(',') < 2):
        return None
    ident = source_id(n['url'])
    digest = hashlib.sha256(json.dumps([n['title'], n['date'], n['body']], ensure_ascii=False).encode()).hexdigest()
    if n.get('institution_id') != 'kgrowth' or n.get('source_id') != ident or digest != n.get('sha256'):
        raise ValueError('복수 모집 원문 기관·식별자·본문 지문 불일치')
    date.fromisoformat(n['date'])
    files, hashes, texts = n.get('attachments', []), n.get('attachment_hashes', {}), n.get('attachment_texts', {})
    if (not set(texts) <= set(hashes) <= set(files) or len(files) > 20
            or len(files) != len(set(files)) or any(not isinstance(t, str) for t in texts.values())):
        raise ValueError('복수 모집의 관측 첨부·지문·판독문 연결 불일치')
    for url in files:
        part = urlsplit(url)
        if (part.scheme != 'https' or part.hostname != 'www.kgrowth.or.kr' or part.path != '/down_file.asp'
                or part.username or part.password or part.fragment or part.port not in {None, 443}
                or parse_qs(part.query).get('idx') != [ident]
                or url in hashes and not _HASH.fullmatch(hashes[url])):
            raise ValueError('복수 모집 첨부의 출처·식별자·지문 불일치')
    funds, holds = [], []
    for url, raw in sorted(texts.items()):
        try:
            text = _compact(raw)
            identity, identity_quotes = _identity(text, n['date'], raw)
            terms, budget_quotes = _budget(text)
            scope, scope_hold, scope_quotes = _scope(text)
            evidence = [_evidence(n, url, raw, quote) for quote in identity_quotes + budget_quotes + scope_quotes]
            terms.update(scope_hold=scope_hold, pe_scope_verified=False, blind_track_observed=False,
                         amount_basis='공통 모집 계획; PE 전용액·실제 GP 배정액 아님',
                         evidence=evidence[len(identity_quotes)], strategy_evidence=evidence[-1],
                         legal_scope_evidence=evidence[-2])
            key = json.dumps([identity[k] for k in ['fund', 'year', 'round']], ensure_ascii=False)
            funds.append({'fund_key': 'kgrowth-history-' + hashlib.sha256(key.encode()).hexdigest()[:16],
                          'identity': identity, 'held_terms': terms, 'scope': scope, 'evidence': evidence,
                          'holds': [{'source_url': n['url'], 'attachment_url': url, 'reason': scope_hold}]})
        except ValueError as exc:
            holds.append({'source_url': n['url'], 'attachment_url': url,
                          'attachment_sha256': hashes[url], 'reason': str(exc)})
    grouped = defaultdict(list)
    for fund in funds:
        grouped[fund['fund_key']].append(fund)
    unique = []
    for values in grouped.values():
        if len(values) != 1:
            holds.append({'identity': values[0]['identity'], 'reason': '같은 펀드·연도·회차의 모집 첨부가 여러 개임',
                          'attachment_urls': [v['held_terms']['evidence']['attachment_url'] for v in values]})
        else:
            unique += values
    missing = sorted(set(files) - set(texts))
    if missing:
        holds.append({'reason': '관측했으나 판독문이 없는 첨부; 내용·펀드명 추정 금지', 'attachment_urls': missing})
    return {'kind': 'lp_kgrowth_multifund_history_v1', 'publication_ready': False,
            'raw_replay_required': True,
            'notice_evidence': {'source_url': n['url'], 'sha256': n['sha256'], 'title': n['title'], 'date': n['date']},
            'funds': sorted(unique, key=lambda f: tuple(f['identity'][k] for k in ['fund', 'year', 'round'])),
            'attachment_coverage': {'advertised_count': len(files), 'retained_hash_count': len(hashes),
                                    'retained_text_count': len(texts),
                                    'missing_attachment_urls': missing}, 'holds': holds}
