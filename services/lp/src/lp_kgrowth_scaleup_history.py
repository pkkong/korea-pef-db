"""Read the jointly funded growth-support plan's explicitly KGrowth-led league.

The policy-investor aggregate is neither a PE-only budget nor KGrowth's own
commitment. Fund legal forms remain mixed. This is an offline held reading.
"""
from __future__ import annotations

import itertools
import re
import unicodedata
from datetime import date

NUM = r'(?:[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d*)'
HEAD = '리그정책출자자출자총액선정운용사수정책출자자출자비율펀드별제안규모조성규모'
LABELS = ('중견', '스케일업성장대형VC', '일반', '스케일업혁신', '루키')


def compact(text):
    return re.sub(r'\s|\u200b', '', unicodedata.normalize('NFKC', text))


def quote(raw, fragment):
    chars, positions = [], []
    for i, char in enumerate(raw):
        for value in unicodedata.normalize('NFKC', char):
            if not value.isspace() and value != '\u200b':
                chars.append(value)
                positions.append(i)
    at = ''.join(chars).find(fragment)
    if at < 0:
        raise ValueError('성장지원 모집표 인용문 불일치')
    return raw[positions[at]:positions[at + len(fragment) - 1] + 1]


def evidence(n, raw, fragment, url):
    return {'source_url': n['url'], 'sha256': n['sha256'], 'quote': quote(raw, fragment),
            'attachment_url': url, 'attachment_sha256': n['attachment_hashes'][url]}


def number(s):
    return int(s.replace(',', '')) if re.fullmatch(NUM, s) else None


def amount_count(prefix):
    return [(number(prefix[:i]), int(prefix[i:])) for i in range(1, len(prefix))
            if number(prefix[:i]) and re.fullmatch(r'[1-9]\d?', prefix[i:])]


def row_options(text):
    front, sep, tail = text.partition('%')
    if not sep or '%' in tail:
        return []
    tail = re.sub(r'^이내', '', tail)
    metrics = []
    for i in range(1, len(tail)):
        proposal, formed = tail[:i], number(tail[i:])
        bounds = proposal.split('~')
        if formed and len(bounds) in (1, 2) and all(number(v) for v in bounds):
            lo, hi = number(bounds[0]), number(bounds[-1])
            if lo <= hi:
                metrics.append((lo, hi, formed))
    values = []
    for width in (1, 2, 3):
        ratio = front[-width:]
        if not re.fullmatch(r'[1-9]\d{0,2}', ratio) or int(ratio) > 100:
            continue
        counts = front[:-width].split('~')
        if len(counts) not in (1, 2):
            continue
        for amount, low in amount_count(counts[0]):
            high = low if len(counts) == 1 else int(counts[1]) if re.fullmatch(r'[1-9]\d?', counts[1]) else 0
            if low <= high:
                for proposal_lo, proposal_hi, formed in metrics:
                    values.append({'amount_krw': amount * 100_000_000,
                                   'planned_fund_count_min': low, 'planned_fund_count_max': high,
                                   'policy_ratio_pct': int(ratio),
                                   'proposal_size_min_krw': proposal_lo * 100_000_000,
                                   'proposal_size_max_krw': proposal_hi * 100_000_000,
                                   'planned_formation_krw': formed * 100_000_000})
    return values


def parse_scaleup_notice(n):
    title = compact(n['title'])
    match = re.fullmatch(r'【선정공고】(20\d{2})년제?([1-9]\d*)차(성장지원펀드)위탁운용사선정계획공고', title)
    if not match:
        return None
    year, round_no, fund = match.groups()
    readings = []
    for url, raw in n.get('attachment_texts', {}).items():
        text = compact(raw)
        intro = re.search(r'(20\d{2})년제?([1-9]\d*)차성장지원펀드위탁운용사선정계획공고', text[:350])
        if not intro:
            continue
        if intro.group(1, 2) != (year, round_no):
            raise ValueError('성장지원 모집 첨부의 연도·회차 충돌')
        total = re.search(r'정책출자자위탁운용금액:총(' + NUM + r')억원이내', text)
        table = re.search(re.escape(HEAD) + r'중견(.+?)스케일업성장대형VC(.+?)일반(.+?)'
                          r'스케일업혁신(.+?)루키(.+?)합계(.+?)\*중견리그', text)
        owner = re.search(r'리그별주관기관:한국산업은행\(([^()]*)\),한국성장금융\(([^()]*)\)', text)
        if (not total or not table or not owner or owner[2] != '스케일업혁신'
                or set(re.split(r'[·‧∙]', owner[1])) != {'중견', '스케일업성장', '루키'}):
            raise ValueError('성장지원 리그별 표 또는 주관기관 구분 미확인')
        if len(table[0]) > 4096 or any(len(block) > 256 for block in table.groups()):
            raise ValueError('성장지원 모집표 판독 크기 상한 초과')
        totals = []
        parts = table[6].split('~')
        if len(parts) == 2:
            for amount, low in amount_count(parts[0]):
                for width in (1, 2):
                    high, formed = parts[1][:width], number(parts[1][width:])
                    if re.fullmatch(r'[1-9]\d?', high) and formed:
                        totals.append((amount * 100_000_000, low, int(high), formed * 100_000_000))
        options = [row_options(block) for block in table.groups()[:5]]
        combinations = 1
        for values in options:
            combinations *= len(values)
        if combinations > 50_000:
            raise ValueError('성장지원 모집표 후보 조합 상한 초과')
        solutions = [rows for rows in itertools.product(*options)
                     if (sum(r['amount_krw'] for r in rows), sum(r['planned_fund_count_min'] for r in rows),
                         sum(r['planned_fund_count_max'] for r in rows), sum(r['planned_formation_krw'] for r in rows)) in totals
                     and sum(r['amount_krw'] for r in rows) == number(total[1]) * 100_000_000]
        if len(solutions) != 1:
            raise ValueError('성장지원 리그별 예산·예정 수·조성규모 합계의 단일 판독 불가')
        legal = re.search(r'출자대상투자기구(.+?)운용사선정방법', text)
        strategy = re.search(r'2\.출자분야(.+?)3\.주요출자조건', text)
        if (not legal or not strategy or '경영참여형사모집합투자기구' not in legal[1]
                or '신기술사업투자조합' not in legal[1] or '한국벤처투자조합' not in legal[1]):
            raise ValueError('성장지원 혼합 투자기구·현재 투자대상 구간 미확인')
        domestic = re.search(r'국내중소[·‧∙]중견기업\*?에리그별최소결성금액의(100|[1-9]\d?)%이상투자', strategy[1])
        owned = dict(solutions[0][3], label=owner[2], amount_basis='성장금융 주관 리그의 정책출자자 합계; 성장금융 단독 출자 아님')
        deadline = ''
        dates = list(re.finditer(r'접수일시(20\d{2})년([1-9]\d?)월([1-9]\d?)일\(([월화수목금토일])\)'
                                 r'\(([01]\d|2[0-3]):([0-5]\d)~([01]\d|2[0-3]):([0-5]\d)限\)', text))
        if len(dates) == 1:
            d = dates[0]
            try:
                day = date(*map(int, d.group(1, 2, 3)))
                if (d[1] == year and day.isoformat() >= n['date'] and '월화수목금토일'[day.weekday()] == d[4]
                        and d.group(5, 6) < d.group(7, 8)):
                    deadline = f'{day.isoformat()}T{d[7]}:{d[8]}:00+09:00'
            except ValueError:
                pass
        held = {'layout': 'shared_growth_support_owned_league', 'shared_tracks': [owned],
                'shared_planned_amount_krw': owned['amount_krw'],
                'policy_investor_total_krw': number(total[1]) * 100_000_000,
                'excluded_other_leagues': [dict(r, label=label, lead_institution='한국산업은행')
                                           for label, r in zip(LABELS, solutions[0]) if label != owner[2]],
                'pe_scope_verified': False, 'blind_track_observed': False,
                'domestic_investment_verified': bool(domestic),
                'strategy': {'domestic_sme_min_pct': int(domestic[1]) if domestic else None,
                             'obligation_basis': '리그별 최소결성금액'},
                'deadline': deadline, 'scope_hold': '성장금융 주관 리그도 PE·VC 투자기구 자율선택; 독립 PE 트랙 미확인',
                'amount_basis': '정책출자자들의 모집 계획 합계; 실제 GP 배정액 또는 성장금융 단독 출자 아님',
                'evidence': evidence(n, raw, table[0], url),
                'lead_evidence': evidence(n, raw, owner[0], url),
                'legal_scope_evidence': evidence(n, raw, legal[0], url),
                'strategy_evidence': evidence(n, raw, strategy[0], url)}
        if deadline:
            held['deadline_evidence'] = evidence(n, raw, dates[0][0], url)
        else:
            held['deadline_error'] = '성장지원 명시 접수 날짜·요일·연도·시각 미확인'
        readings.append({'identity': {'fund': f'{fund}({owner[2]}리그)', 'year': year, 'round': round_no + '차'},
                         'held_terms': held, 'holds': [held['scope_hold']]})
    if len(readings) != 1:
        raise ValueError('성장지원 리그별 원 모집 첨부가 없거나 여러 개임')
    return {'publication_ready': False, 'funds': readings}
