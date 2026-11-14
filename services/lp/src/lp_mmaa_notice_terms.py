"""군인공제회 annual joint PE·VC blind notices: the PE share of the budget.

Two official layouts (2020-2026):
- 2020-2021 prose: "위탁운용규모 : 총 1,500억원 이내 · PE 분야 : 600억원 내외 - 일반리그 : 400억원 내외(2개 내외) ..."
- 2022-     table: "구분 계 PE VC ... 출자규모(억원) 2,000 1,200 1,020 180 800 720 80 운용사(개) 22 11 9 2 11 9 2"
  (total, PE subtotal, PE leagues..., VC subtotal, VC leagues...).
A PE figure is returned only when PE + VC equals the stated total.
"""
import re

_PROSE = re.compile(r'총([\d,]+)억원(?:이내|내외)?·?PE분야[:：]([\d,]+)억원(?:이내|내외)?(.*?)·?VC분야[:：]([\d,]+)억원')
_TABLE = re.compile(r'구분계PEVC.{0,80}?출자규모\((?:억원|내외)\)((?:[\d,]+)+?)(?=운용사)')


def _ints(blob):
    return [int(x.replace(',', '')) for x in re.findall(r'\d{1,3}(?:,\d{3})+|\d+', blob)]


def _split(numbers):
    """(PE subtotal, index of VC subtotal) or None when the columns do not add up."""
    if len(numbers) < 3:
        return None
    total, pe = numbers[0], numbers[1]
    # League columns first: a PE league can equal the VC subtotal by coincidence (2024).
    running, j = 0, 2
    while j < len(numbers) and running < pe:
        running += numbers[j]
        j += 1
    if running == pe and j < len(numbers) and total == pe + numbers[j]:
        return pe, j
    if total == pe + numbers[2]:
        return pe, 2
    return None


def pe_share(n):
    """{'commitment_amount_krw', labels, manager_count?, 'amount_scope': 'pe_only', evidence} or {}."""
    if n.get('institution_id') != 'mmaa':
        return {}
    for text in [n.get('body', ''), *n.get('attachment_texts', {}).values()]:
        t = re.sub(r'\s+', '', text)
        m = _PROSE.search(t)
        if m:
            total, pe, vc = (int(m[i].replace(',', '')) for i in (1, 2, 4))
            pe_part = m[3]
            if total != pe + vc:
                continue
            counts = [int(c) for c in re.findall(r'\((\d+)개(?:내외|이내)?\)', pe_part)]
            return _result(n, pe, sum(counts) if counts else None, m[0])
        m = _TABLE.search(t)
        if m:
            # Digits of adjacent cells run together once spaces are removed; read them from the spaced text.
            spaced = re.search(r'출자\s*규모\s*\(\s*(?:억원|내외)\s*\)\s*([\d,\s]+?)\s*운용사', text)
            numbers = _ints(spaced[1]) if spaced else []
            split = _split(numbers)
            if not split:
                continue
            pe, vc_at = split
            count = None
            counted = re.search(r'운용사\s*\(\s*(?:개|내외)\s*\)\s*([\d\s]+)', text)
            if counted:
                cs = _ints(counted[1])[:len(numbers)]
                if len(cs) > vc_at and cs[0] == cs[1] + cs[vc_at]:
                    count = cs[1]
            quote = re.sub(r'\s+', ' ', (spaced[0] if spaced else m[0]))[:200]
            return _result(n, pe, count, quote)
    return {}


def _result(n, pe, count, quote):
    label = f'PE 부문 {pe:,}억원'
    result = {'commitment_amount_krw': pe * 100_000_000, 'commitment_label': label, 'list_commitment_label': label,
              'amount_scope': 'pe_only',
              'extraction_evidence': {'commitment': [{'source_url': n['url'], 'sha256': n['sha256'], 'quote': quote}]}}
    if count:
        result.update(manager_count=count, manager_count_label=f'{count}개사')
    return result
