"""Conservative labelled facts for independently validated issuer-board receipts."""
import re
from datetime import date, datetime
try:
    from .lp_shared_notice_terms import extract_offering_sources
except ImportError:
    from lp_shared_notice_terms import extract_offering_sources

NUM = r'(\d[\d,]*)'


def extract_terms(n):
    sources = [(n['url'], n['body'], n['sha256'])]
    sources += [(u, t, n['attachment_hashes'][u]) for u, t in n.get('attachment_texts', {}).items()]
    try:
        result = extract_offering_sources(n, sources)
    except ValueError:
        result = {}
    evidence = result.setdefault('extraction_evidence', {})
    totals, counts, per_fund, deadlines = set(), set(), set(), set()
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
        pattern = (r'(?:제안서)?(?:접수마감(?:일시|일|시한)?|제출기한|마감일시)[:：]*'
                   r'(20\d{2})[.년](\d{1,2})[.월](\d{1,2})[.일]?'
                   r'(?:\([월화수목금토일]\))?(오후|오전)?(\d{1,2})(?::(\d{2})|시)')
        for m in re.finditer(pattern, text):
            hour = int(m[5]) % 12 + 12 if m[4]=='오후' else (0 if m[4]=='오전' and m[5]=='12' else int(m[5]))
            stamp = datetime(int(m[1]),int(m[2]),int(m[3]),hour,int(m[6] or 0)).isoformat() + '+09:00'
            deadlines.add(stamp)
            record('deadline',m[0])
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
    if deadlines:
        days = {d[:10] for d in deadlines}
        if len(days)>1 or min(days)<n['date']:
            result.pop('deadline',None)
            result['deadline_error']='접수 마감 날짜 불일치'
        elif len(deadlines)>1 or result.get('deadline_error'):
            result.update(deadline=next(iter(days)), deadline_precision='date')
        else:
            result.update(deadline=next(iter(deadlines)), deadline_precision='datetime')
    return result
