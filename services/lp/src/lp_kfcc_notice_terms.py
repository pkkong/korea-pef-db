"""Read PE-only allocations from the issuer's structured, replayed notice body.

Eligibility binds to the PE section and its actual columns. A VC table can
contain a mistaken PE cell, and credit allocations are not equity PE evidence.
"""
import re


def allocation(notice):
    if notice.get('institution_id') != 'kfcc':
        return None
    body = notice['body']
    start = re.search(r'(?m)^\d+\.\s*PE\s*부문\s*선정\s*개요\s*$', body)
    if not start:
        return None
    end = re.search(r'(?m)^\d+\.\s*VC\s*부문\s*선정\s*개요\s*$', body[start.end():])
    if not end:
        return None
    section = body[start.end():start.end()+end.start()]
    compact = re.sub(r'\s+', '', section)
    if not all(token in compact for token in ('블라인드형', '기관전용사모집합투자기구', '공개모집')):
        return None
    header = ['구분', '구분', '전략', '세부전략', '선정수', '총위탁금액', '운용사별위탁금액']
    rows, reading = [], False
    for line in section.splitlines():
        cells = [c.strip() for c in line.split('\t')]
        if [re.sub(r'\s+', '', c) for c in cells] == header:
            if reading:
                raise ValueError('ambiguous PE allocation table')
            reading = True
            continue
        if not reading:
            continue
        if len(cells) != 7:
            break
        if re.sub(r'\s+', '', cells[0]) != '국내' or cells[1] != 'PE':
            return None
        if not re.fullmatch(r'Special\s+Situation|Buyout\s*[,·]\s*Growth', cells[2], re.I):
            return None
        count = re.fullmatch(r'(\d+)개사', cells[4])
        amount = re.fullmatch(r'([\d,]+)억원', cells[5])
        per = re.fullmatch(r'([\d,]+)[~～]([\d,]+)억원', cells[6])
        if not count or not amount or not per:
            raise ValueError('PE allocation columns not independently readable')
        n, total = int(count[1]), int(amount[1].replace(',', ''))
        low, high = [int(value.replace(',', '')) for value in per.groups()]
        if not 0 < low <= high or not n*low <= total <= n*high:
            raise ValueError('PE allocation outside per-manager range')
        rows.append({'name': cells[2], 'amount_krw': total*100_000_000, 'manager_count': n,
                     'per_fund_min_krw': low*100_000_000, 'per_fund_max_krw': high*100_000_000,
                     'purpose': cells[3], 'quote': line})
    if not rows or len({r['name'] for r in rows}) != len(rows):
        return None
    total = sum(r['amount_krw'] for r in rows)
    count = sum(r['manager_count'] for r in rows)
    evidence = [{'source_url': notice['url'], 'sha256': notice['sha256'], 'quote': row['quote']} for row in rows]
    planned = []
    stages = {'1차심사': ('screening', '1차 심사'), '2차심사': ('interview', '2차 심사'),
              '현장실사': ('due_diligence', '실사'), '최종선정': ('selection', '최종 선정')}
    for line in body.splitlines():
        cells = line.split('\t')
        if len(cells) != 3:
            continue
        label = re.sub(r'[①②③④⑤\s]', '', cells[0])
        if label not in stages:
            continue
        period = re.fullmatch(r'(\d{1,2})월\s*(\d)주\s*[~～]\s*(?:(\d{1,2})월\s*)?(\d)주', cells[1].strip())
        if not period:
            continue
        month, week, end_month, end_week = map(int, (period[1], period[2], period[3] or period[1], period[4]))
        if not (1 <= month <= end_month <= 12 and 1 <= week <= 5 and 1 <= end_week <= 5) or (month == end_month and week > end_week):
            raise ValueError('invalid planned week range')
        key, title = stages[label]
        planned.append({'stage': key, 'label': title, 'original_label': title,
            'date': f'{notice["date"][:4]}-{month:02}', 'end_date': f'{notice["date"][:4]}-{end_month:02}',
            'date_label': cells[1].strip(), 'precision': 'month_range', 'status': 'planned', 'source_url': notice['url']})
    return {'planned_schedule': planned, 'commitment_amount_krw': total, 'commitment_label': f'{total/100_000_000:,.0f}억원',
            'manager_count': count, 'manager_count_label': f'{count}개사', 'amount_scope': 'pe_only',
            'segments': [{k: v for k, v in row.items() if k not in {'purpose', 'quote'}} for row in rows],
            'primary_investment': {'text': '; '.join(row['purpose'] for row in rows),
                'items': [row['name'] + ': ' + row['purpose'] for row in rows], 'source_url': notice['url']},
            'extraction_evidence': {'pe_allocation': evidence}}
