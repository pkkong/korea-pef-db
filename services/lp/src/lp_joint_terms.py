"""Read multi-league joint-bank plans without approving them as pure PE."""
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse

try:
    from .lp_notice_triage import compact
    from .lp_notice_terms import _one, NUMBER
except ImportError:
    from lp_notice_triage import compact
    from lp_notice_terms import _one, NUMBER


def extract_joint_terms(notice):
    if notice.get('institution_id') != 'kdb' or urlparse(notice['url']).hostname != 'www.kdb.co.kr':
        raise ValueError('공동사업 공식 모집 원공고 없음')
    outputs = []
    for url, raw in notice.get('attachment_texts', {}).items():
        digest = notice.get('attachment_hashes', {}).get(url)
        if not digest or urlparse(url).hostname != 'www.kdb.co.kr':
            raise ValueError('공동사업 첨부 근거 없음')
        text = compact(raw)
        # Each column has units, so even a PDF with lost spaces is unambiguous.
        heading = '분야주관기관출자금액주관기관출자비율펀드별목표결성금액선정운용사수조성목표'
        table = re.search(re.escape(heading) + r'(.*?)합계(' + NUMBER + r')억원(\d+(?:\.\d+)?)%[-—](\d+)개(' + NUMBER + r')억원', text)
        if not table:
            continue
        rows = list(re.finditer(r'([가-힣]{1,12})(' + NUMBER + r')억원(\d+(?:\.\d+)?)%(' + NUMBER + r')억원(\d+)개(' + NUMBER + r')억원', table[1]))
        if len(rows) < 2 or ''.join(m[0] for m in rows) != table[1]:
            raise ValueError('출자계획 표의 분야 또는 숫자 열 미확인')
        segments = []
        for row in rows:
            label, amount, ratio, per_fund_target, count, target = row.groups()
            amount, per_fund_target, count, target = [int(v.replace(',', '')) for v in (amount, per_fund_target, count, target)]
            actual_ratio = (Decimal(amount) / Decimal(target) * 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) if target else None
            if min(amount, per_fund_target, count, target) <= 0 or amount > target or per_fund_target * count != target or actual_ratio != Decimal(ratio):
                raise ValueError('분야별 출자액·결성목표·비율 불일치')
            # Do not divide league commitments by managers or participating LPs.
            segments.append({'name': label, 'amount_krw': amount * 100_000_000,
                             'manager_count': count, 'per_fund_target_krw': per_fund_target * 100_000_000,
                             'fund_target_krw': target * 100_000_000, 'contribution_ratio_percent': ratio})
        amount, count, target = [int(table[i].replace(',', '')) for i in (2, 4, 5)]
        if (sum(s['amount_krw'] for s in segments) != amount * 100_000_000 or
                sum(s['manager_count'] for s in segments) != count or
                sum(s['fund_target_krw'] for s in segments) != target * 100_000_000 or
                len({s['name'] for s in segments}) != len(segments)):
            raise ValueError('분야별 합계와 총계 불일치')
        total_ratio = (Decimal(amount) / Decimal(target) * 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        if total_ratio != Decimal(table[3]):
            raise ValueError('총 출자비율 불일치')
        header = re.search(r'주관기관○(.*?)위탁운용금액○위탁운용금액:총(' + NUMBER + r')억원\(주관기관별각(' + NUMBER + r')억원\)', text)
        if not header:
            raise ValueError('기관별 출자계획 미확인')
        names = re.findall(r'한국산업은행|중소기업은행|한국수출입은행', header[1])
        bank_amount = int(header[3].replace(',', ''))
        if len(names) != len(set(names)) or len(names) * bank_amount != amount or int(header[2].replace(',', '')) != amount:
            raise ValueError('기관별 출자액과 공동 총계 불일치')
        deadline = re.search(r'접수일시및접수처○(20\d{2})년(\d{1,2})월(\d{1,2})일\([월화수목금토일]\)'
                             r'(\d{1,2}):(\d{2})[~∼～](\d{1,2}):(\d{2})', text)
        if not deadline:
            raise ValueError('접수 마감 미확인')
        values = [int(v) for v in deadline.groups()]
        start = datetime(*values[:3], *values[3:5])
        end = datetime(*values[:3], *values[5:7])
        if start >= end or end.date().isoformat() < notice['date']:
            raise ValueError('접수 일시 범위 불일치')
        purpose = re.search(r'주목적투자의무투자비율(.*?)(?:주관기관출자비율)', text)
        if not purpose:
            raise ValueError('주목적 투자조건 미확인')
        obligations = list(re.finditer(r'([❶❷❸❹❺])([^❶❷❸❹❺]+?)약정총액의(\d+)%', purpose[1]))
        if len(obligations) < 2 or len({m[1] for m in obligations}) != len(obligations):
            raise ValueError('주목적 의무 항목 미확인')
        # Preserve the original spacing for display; percentages are separate
        # obligations and may overlap. Their sum need not be at most 100.
        items = []
        for obligation in obligations:
            percent = int(obligation[3])
            if not 0 < percent <= 100:
                raise ValueError('주목적 투자비율 범위 불일치')
            spaced = re.search(re.escape(obligation[1]) + r'\s*([^❶❷❸❹❺]+?)약정총액의\s*' + obligation[3] + '%', raw)
            if not spaced:
                raise ValueError('주목적 원문 인용 미확인')
            subject = re.sub(r'\s+', ' ', spaced[1]).replace('*', '').strip()
            items.append({'text': subject, 'ratio_percent': percent})
        schedule = re.search(r'선정일정일자내용비고(.*?)(?:\*세부일정|6\.접수처)', text)
        planned = []
        if schedule:
            for m in re.finditer(r'(20\d{2})\.(\d{1,2})월(현장실사및심사|최종선정)', schedule[1]):
                datetime(int(m[1]), int(m[2]), 1)
                planned.append({'date': f'{m[1]}-{int(m[2]):02}', 'precision': 'month', 'status': 'planned',
                                'label': '심사' if m[3] == '현장실사및심사' else '최종 선정'})
        if not planned:
            raise ValueError('월 단위 심사·선정 계획 미확인')
        outputs.append({'total_commitment_amount_krw': amount * 100_000_000,
                        'contribution_allocations': {name: bank_amount * 100_000_000 for name in names},
                        'manager_count': count, 'fund_target_krw': target * 100_000_000,
                        'segments': segments, 'deadline': end.isoformat() + '+09:00',
                        'primary_obligations': items, 'planned_schedule': planned,
                        'amount_status': 'planned', 'source_url': notice['url'],
                        'evidence': {'attachment_url': url, 'sha256': digest,
                                     'quotes': [table[0], header[0], deadline[0], purpose[0]]}})
    return _one(outputs, '공동사업 모집 개요')


def discovered_joint_terms(candidates, notices):
    by_url = {n['url']: n for n in notices}
    terms, holds = {}, []
    for candidate in candidates:
        key = candidate['program_key']
        if candidate.get('scope') != 'mixed_legal_forms' or key in terms or any(h['program_id'] == key for h in holds):
            continue
        try:
            source = by_url[candidate['recruitment_url']]
            terms[key] = extract_joint_terms(source)
        except (KeyError, ValueError) as error:
            holds.append({'program_id': key, 'reason': f'공동사업 조건 추출 보류: {error}'})
    return terms, holds
