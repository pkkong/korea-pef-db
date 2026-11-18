"""Conservative labelled facts for independently validated issuer-board receipts."""
import copy
import re
from datetime import date, datetime
try:
    from .lp_attachment_policy import is_submission_attachment
    from .lp_shared_notice_terms import extract_offering_sources
    from .lp_kfcc_notice_terms import allocation as kfcc_allocation
    from .lp_moel_iaci_notice_terms import extract_deadline as iaci_deadline
    from .lp_moel_iaci_notice_terms import extract_allocation as iaci_allocation
except ImportError:
    from lp_attachment_policy import is_submission_attachment
    from lp_shared_notice_terms import extract_offering_sources
    from lp_kfcc_notice_terms import allocation as kfcc_allocation
    from lp_moel_iaci_notice_terms import extract_deadline as iaci_deadline
    from lp_moel_iaci_notice_terms import extract_allocation as iaci_allocation

NUM = r'(\d[\d,]*)'
_CWMA_OVERVIEW = re.compile(r'(?m)^1\.\s*선정\s*개요\s*$')
_CWMA_CONDITIONS = re.compile(r'(?m)^2\.\s*주요\s*출자조건\s*$')


def _cwma_pe_allocation(notice, sources):
    if notice.get('institution_id') != 'cwma' or '국내사모투자펀드' not in re.sub(r'\s+', '', notice['title']):
        return {}
    matches = []
    for url, raw, sha in sources:
        start = _CWMA_OVERVIEW.search(raw)
        end = _CWMA_CONDITIONS.search(raw, start.end()) if start else None
        if not end:
            continue
        section = raw[start.end():end.start()]
        compact = re.sub(r'\s+', '', section)
        if not all(marker in compact for marker in ('운용방식ㆍ블라인드형', '공개모집',
                                                   '기관전용사모집합투자기구', '창업·벤처전문사모투자기구제외')):
            continue
        rows = (
            re.findall(r'(?m)^운용사[ \t]+수[ \t]*\n[ \t]*ㆍ[ \t]*(\d+)개사[ \t]*이내[ \t]*$', section),
            re.findall(r'(?m)^공제회[ \t]+약정금액[ \t]*\n[ \t]*ㆍ[ \t]*총[ \t]*' + NUM
                       + r'억원\(운용사당[ \t]+' + NUM + r'억원\)[ \t]*이내[ \t]*$', section),
            re.findall(r'(?m)^최소[ \t]+결성금액[ \t]*\n[ \t]*ㆍ[ \t]*' + NUM
                       + r'억원\(공제회[ \t]+출자비율:[ \t]*펀드결성총액의[ \t]*\d+%[ \t]+이하\)[ \t]*$', section),
        )
        if any(len(row) != 1 for row in rows):
            raise ValueError('CWMA PE 모집 표의 출자 조건이 불명확함')
        count = int(rows[0][0])
        total, per_fund = (int(value.replace(',', '')) for value in rows[1][0])
        minimum = int(rows[2][0].replace(',', ''))
        if not (count > 0 and 0 < per_fund <= total <= minimum * count and total == count * per_fund):
            raise ValueError('CWMA PE 모집 표의 약정액과 운용사 수 불일치')
        matches.append(((count, total, per_fund, minimum), {
            'source_url': url, 'sha256': sha, 'quote': section.strip(),
        }))
    if not matches:
        return {}
    if len({facts for facts, _ in matches}) != 1:
        raise ValueError('CWMA 원문 사이에 PE 약정 조건 불일치')
    count, total, per_fund, minimum = matches[0][0]
    return {'commitment_amount_krw': total * 100_000_000, 'commitment_label': f'{total:,}억원 이내',
            'manager_count': count, 'manager_count_label': f'{count}개사 이내',
            'per_fund_amount_krw': per_fund * 100_000_000, 'per_fund_qualifier': '이내',
            'fund_target_label': f'최소 {minimum:,}억원', 'amount_scope': 'pe_only',
            'extraction_evidence': {'pe_allocation': [proof for _, proof in matches]}}


def apply_iaci_allocation(n, result):
    """Use the same explicit PE league totals for own-board and repost sources."""
    allocation = iaci_allocation(n)
    if not allocation:
        return result
    result = copy.deepcopy(result)
    evidence = result.setdefault('extraction_evidence', {})
    if allocation.get('allocation_error'):
        for key in ('commitment_amount_krw', 'total_commitment_amount_krw', 'commitment_label',
                    'list_commitment_label', 'manager_count', 'manager_count_label', 'segments',
                    'per_fund_amount_krw', 'per_fund_range_krw', 'per_fund_qualifier'):
            result.pop(key, None)
        for key in ('commitment', 'pe_allocation', 'manager_count', 'count', 'total', 'per_fund'):
            evidence.pop(key, None)
        result.update(allocation_error=allocation['allocation_error'], allocation_reading_failed=True)
    else:
        evidence.update(allocation.pop('extraction_evidence'))
        result.update(allocation)
    return result


def extract_terms(n):
    sources = [(n['url'], n['body'], n['sha256'])]
    sources += [(u, t, n['attachment_hashes'][u]) for u, t in n.get('attachment_texts', {}).items()
                if not is_submission_attachment(n, u)]
    try:
        result = extract_offering_sources(n, sources)
    except ValueError:
        result = {}
    allocation = kfcc_allocation(n)
    if allocation:
        result = allocation
    evidence = result.setdefault('extraction_evidence', {})
    totals, counts, per_fund, deadlines = set(), set(), set(), set()
    dates_only, dated_quotes = set(), []
    mixed = bool(re.search(r'PE\s*[·,/]\s*VC|PE.*VC', n['title'], re.I))
    for url, raw, sha in sources:
        text = re.sub(r'\s+', '', raw)
        def record(key, quote):
            evidence.setdefault(key, []).append({'source_url': url, 'sha256': sha, 'quote': quote})
        # Explicit split allocations must reconcile before a PE field is emitted.
        if mixed:
            pe = re.search(r'PE부문[(:：]*' + NUM + r'억원[)]?[:：]*각' + NUM + r'억원[,，]*총(\d+)개사', text)
            vc = re.search(r'VC부문[(:：]*' + NUM + r'억원[)]?[:：]*각' + NUM + r'억원[,，]*총(\d+)개사', text)
            total = re.search(r'출자규모[:：]*총' + NUM + r'억원', text)
            if pe and vc and total:
                p, v, t = [[int(x.replace(',', '')) for x in m.groups()] for m in (pe, vc, total)]
                if p[0] != p[1]*p[2] or v[0] != v[1]*v[2] or p[0]+v[0] != t[0]:
                    raise ValueError('PE/VC split allocation does not reconcile')
                if result.get('commitment_amount_krw') not in (None, p[0]*100_000_000, t[0]*100_000_000):
                    raise ValueError('conflicting independently parsed PE/VC total')
                totals.add((p[0]*100_000_000, ''))
                counts.add((p[2], ''))
                per_fund.add((p[1]*100_000_000, ''))
                record('pe_allocation', pe[0] + ' / ' + vc[0] + ' / ' + total[0])
                result['amount_scope'] = 'pe_only'
        else:
            for match in re.finditer(r'위탁운용금액[:：]*총' + NUM + r'억원(이내|내외)?', text):
                totals.add((int(match[1].replace(',', ''))*100_000_000, match[2] or ''))
                record('total', match[0])
            # The co-investment track shares a notice, but its amount must never
            # be included in the blind Buyout/Growth allocation.
            for match in re.finditer(r'모집규모[:：]*Buyout[·‧ㆍ]Growth' + NUM + r'억원(이내|내외)?(\d+)개사', text, re.I):
                totals.add((int(match[1].replace(',', ''))*100_000_000, match[2] or ''))
                counts.add((int(match[3]), ''))
                record('blind_allocation', match[0])
            for match in re.finditer(r'선정운용사수[:：-]*(?:평가결과상위)?(\d+)개사(이내|내외)?', text):
                counts.add((int(match[1]), match[2] or ''))
                record('manager_count', match[0])
            for match in re.finditer(r'(?:펀드당|1개사별)' + NUM + r'억원(이내|이하|내외)?', text):
                per_fund.add((int(match[1].replace(',', ''))*100_000_000, '이내' if match[2]=='이하' else match[2] or ''))
                record('per_fund', match[0])
        # Only explicitly labelled dates; historical-fund dates cannot supply a
        # deadline. Date-only is retained when source submission times disagree.
        date_text = re.sub(r'(?<=[가-힣])\s+(?=[가-힣])', '', raw)
        labels = r'(?:제안서)?(?:접수마감(?:일시|일|시한)?|접수기한|제출기한|마감일시)'
        pattern = (labels + r"\s*[:：]*\s*[’'‘]?(20\d{2}|\d{2})[.년]\s*(\d{1,2})[.월]\s*(\d{1,2})"
                   r'(?:[.일]\s*(?:\([월화수목금토일](?:요일)?\)\s*)?|\([월화수목금토일](?:요일)?\)\s*|\s+)'
                   r'(오후|오전)?\s*(\d{1,2})(?::(\d{2})|시)')
        for m in re.finditer(pattern, date_text):
            hour = int(m[5]) % 12 + 12 if m[4]=='오후' else (0 if m[4]=='오전' and m[5]=='12' else int(m[5]))
            year = int(m[1]) if len(m[1]) == 4 else 2000 + int(m[1])
            stamp = datetime(year,int(m[2]),int(m[3]),hour,int(m[6] or 0)).isoformat() + '+09:00'
            deadlines.add(stamp)
            record('deadline',m[0])
        # "마감일: 2026. 8. 20.(목) (PEF 오전 11시까지, VC 오후 4시까지)": the PE track's own time.
        track = (labels + r"\s*[:：]*\s*[’'‘]?(20\d{2}|\d{2})[.년]\s*(\d{1,2})[.월]\s*(\d{1,2})[.일]?\s*"
                 r'(?:\([월화수목금토일](?:요일)?\)\s*)?\(\s*PEF?\s*(오후|오전)?\s*(\d{1,2})(?::(\d{2})|시)')
        for m in re.finditer(track, date_text):
            hour = int(m[5]) % 12 + 12 if m[4]=='오후' else (0 if m[4]=='오전' and m[5]=='12' else int(m[5]))
            year = int(m[1]) if len(m[1]) == 4 else 2000 + int(m[1])
            deadlines.add(datetime(year,int(m[2]),int(m[3]),hour,int(m[6] or 0)).isoformat() + '+09:00')
            record('deadline',m[0])
        # A labelled date with no time at all is still the deadline, shown date-only.
        dated = labels + r"\s*[:：]*\s*[’'‘]?(20\d{2}|\d{2})[.년]\s*(\d{1,2})[.월]\s*(\d{1,2})(?![\d])"
        for m in re.finditer(dated, date_text):
            year = int(m[1]) if len(m[1]) == 4 else 2000 + int(m[1])
            dates_only.add(date(year,int(m[2]),int(m[3])).isoformat())
            dated_quotes.append({'source_url': url, 'sha256': sha, 'quote': m[0]})
        if re.search(labels + r"\s*[:：]*\s*[’'‘]?(?:20\d{2}|\d{2})[.년]\d{1,2}[.월]\d{2,4}:\d{2}", date_text):
            result.pop('deadline', None)
            result['deadline_error'] = '접수 날짜와 시각 경계 불명확'
        # A direct/quick-delivery cutoff can conflict with the captioned time.
        delivery = re.findall(r'(?:직접제출|퀵).{0,90}?(\d{1,2})(?:시|:\d{2})까지', text)
        if delivery and deadlines and any(int(h) != int(d[11:13]) for h in delivery for d in deadlines):
            result['deadline_error'] = '접수 마감과 직접 제출 시각 불일치; 날짜만 표시'
    for values, field in ((totals,'total'), (counts,'count'), (per_fund,'per_fund')):
        if len(values)>1:
            raise ValueError('conflicting institution offering '+field)
    if totals:
        amount, qualifier = next(iter(totals))
        if not mixed and result.get('commitment_amount_krw') and amount != result['commitment_amount_krw']:
            raise ValueError('conflicting independently parsed total')
        result.update(commitment_amount_krw=amount, commitment_label=f'{amount/100_000_000:,.0f}억원'+(' '+qualifier if qualifier else ''), amount_scope='pe_only')
    if counts:
        count, qualifier = next(iter(counts))
        result.update(manager_count=count, manager_count_label=f'{count}개사'+(' '+qualifier if qualifier else ''))
    if per_fund:
        amount, qualifier = next(iter(per_fund))
        result.update(per_fund_amount_krw=amount, per_fund_qualifier=qualifier)
    if not deadlines and dates_only and len(dates_only) == 1 and min(dates_only) >= n['date']:
        evidence.setdefault('deadline', []).extend(dated_quotes)
        result.update(deadline=next(iter(dates_only)), deadline_precision='date')
    if deadlines:
        days = {d[:10] for d in deadlines}
        if len(days)>1 or min(days)<n['date']:
            result.pop('deadline',None)
            result['deadline_error']='접수 마감 날짜 불일치'
        elif len(deadlines)>1 or result.get('deadline_error'):
            result.update(deadline=next(iter(days)), deadline_precision='date')
        else:
            result.update(deadline=next(iter(deadlines)), deadline_precision='datetime')
    specific = iaci_deadline(n)
    if specific:
        conflict = specific.get('deadline_error') or result.get('deadline_error')
        if specific.get('deadline') and result.get('deadline'):
            current, revised = result['deadline'], specific['deadline']
            if current[:10] != revised[:10] or (len(current) > 10 and len(revised) > 10 and current != revised):
                conflict = '접수 일정 표와 다른 원문 마감 불일치'
        if conflict:
            result.pop('deadline', None)
            result.pop('deadline_precision', None)
            evidence.pop('deadline', None)
            result['deadline_error'] = conflict
        else:
            result.update(deadline=specific['deadline'], deadline_precision=specific['deadline_precision'])
            evidence.setdefault('deadline', []).extend(specific['extraction_evidence']['deadline'])
    cwma = _cwma_pe_allocation(n, sources)
    if cwma:
        evidence.update(cwma.pop('extraction_evidence'))
        result.update(cwma)
    return apply_iaci_allocation(n, result)
