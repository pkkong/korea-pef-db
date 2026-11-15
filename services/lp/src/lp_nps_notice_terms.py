"""국민연금 국내 사모투자 notices: the PEF section's budget, manager count and per-fund range.

Layout 2020-2026: "(1) PEF 항 목 내 용 위탁운용금액 ․총 8,000억원 이내 선정운용사 수 및 배정금액
․5개사 이내, 펀드별 800~2,000억원 범위 이내에서 자율적으로 제안 … (2) 벤처펀드 …".
Values outside plausible bounds (tracked-change HWP text such as "3,524,000억원", "346개사")
give nothing.
"""
import re

_SECTION = re.compile(r'\(\d\)\s*PEF\s*항\s*목\s*내\s*용(.*?)(?=\(\d\)\s*[^\s(]|Ⅱ\s*\.|\d\.\s*출자\s*조건|$)', re.S)
_TOTAL = re.compile(r'위탁\s*운용\s*금액\s*[․·•]?\s*총\s*(?:(\d+(?:\.\d+)?)\s*조\s*원|([\d,]+)\s*억\s*원)\s*(이내|이하)?')
_COUNT = re.compile(r'(\d+)\s*개사\s*(이내|이하)?')
_RANGE = re.compile(r'펀드별\s*([\d,]+)\s*~\s*([\d,]+)\s*억\s*원')


def _int(value):
    return int(value.replace(',', ''))


def pe_share(n):
    if n.get('institution_id') != 'nps':
        return {}
    readings = set()
    for text in [n.get('body', ''), *n.get('attachment_texts', {}).values()]:
        for m in _SECTION.finditer(text):
            section = m[1]
            total = _TOTAL.search(section)
            if not total:
                continue
            amount = round(float(total[1]) * 10_000) if total[1] else _int(total[2])  # 억원
            count = _COUNT.search(section[total.end():])
            spread = _RANGE.search(section[total.end():])
            count_value = int(count[1]) if count else None
            low, high = (_int(spread[1]), _int(spread[2])) if spread else (None, None)
            if not 500 <= amount <= 50_000 or (count_value is not None and not 1 <= count_value <= 20) \
                    or (low is not None and not 0 < low <= high <= amount):
                continue
            readings.add((amount, total[3] or '', count_value, low, high, re.sub(r'\s+', ' ', total[0])))
    if len({r[:5] for r in readings}) != 1:
        return {}
    amount, qualifier, count, low, high, quote = next(iter(readings))
    jo, rest = divmod(amount, 10_000)
    shown = (f'{jo}조' + (f' {rest:,}억원' if rest else '원')) if jo else f'{amount:,}억원'
    label = f'PE 부문 {shown}' + (f' {qualifier}' if qualifier else '')
    result = {'commitment_amount_krw': amount * 100_000_000, 'commitment_label': label, 'list_commitment_label': label,
              'amount_scope': 'pe_only',
              'extraction_evidence': {'commitment': [{'source_url': n['url'], 'sha256': n['sha256'], 'quote': quote}]}}
    if count:
        result.update(manager_count=count, manager_count_label=f'{count}개사')
    if low:
        result['per_fund_range_krw'] = [low * 100_000_000, high * 100_000_000]
    return result
