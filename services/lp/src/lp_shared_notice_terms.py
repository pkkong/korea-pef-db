"""Extract source-linked recruitment facts without approving a new program.

Rules bind values to offering labels and table columns, not notice IDs. Mixed
PE/VC totals remain combined unless an explicit PE allocation is reconciled.
"""
import json
import re
from collections import defaultdict
from datetime import date, datetime
from urllib.parse import urlsplit

try:
    from .collect_shared_lp_notices import classify_scope, source_id
except ImportError:
    from collect_shared_lp_notices import classify_scope, source_id

NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)'
CHANNELS = {'kvca': ('www.kvca.or.kr', '/Program/invest/listbody.html'),
            'kofia_212': ('www.kofia.or.kr', '/brd/m_212/view.do'),
            'kofia_17': ('www.kofia.or.kr', '/brd/m_17/view.do')}


def _compact(text):
    return re.sub(r'\s+', '', text.replace('\x00', ' '))


def _one(values, label):
    unique = {json.dumps(value, sort_keys=True, ensure_ascii=False): value for value in values}
    if len(unique) > 1:
        raise ValueError(f'{label}: 본문·첨부 값 불일치')
    return next(iter(unique.values())) if unique else None


def _planned_months(text):
    start=re.search(r'추진일정|진행일정|선정일정|선정절차및일정',text)
    if not start:
        return []
    section=text[start.start():start.start()+1800]
    stamp=r"[’']?(?P<year>20\d{2}|\d{2})[.년](?P<month>\d{1,2})월(?P<part>둘째주|셋째주|넷째주|다섯째주|첫째주|초|중|말)?(?:[~～](?P<endmonth>\d{1,2})월(?P<endpart>초|중|말)?)?"
    stage=r'(?P<stage>1차\(정량\)평가|2차\(정성\)평가|정량평가(?:및현장실사)?|PT[·ㆍ]정성평가|정성평가|구술심사|운용사실사|현장실사|최종선정|결과통보)'
    values, bound_spans=[], []
    for index,pattern in enumerate((stamp+stage,stage+r'[:：·Ÿ•-]*'+stamp)):
        for m in re.finditer(pattern,section):
            if index and any(start<=m.start()<end for start,end in bound_spans):
                continue
            if not index:bound_spans.append(m.span())
            year=int(m['year']) if len(m['year'])==4 else 2000+int(m['year'])
            month=date(year,int(m['month']),1).strftime('%Y-%m')
            name=m['stage']
            key=('selection' if name in ('최종선정','결과통보') else 'due_diligence' if name in ('운용사실사','현장실사')
                 else 'interview' if re.search(r'정성|구술|2차',name) else 'screening')
            label={'selection':'최종 선정','due_diligence':'실사','interview':'2차 심사','screening':'1차 심사'}[key]
            if '및현장실사' in name:label+='·실사'
            date_label=f'{int(m["month"])}월 {m["part"] or ""}'.strip()
            value={'stage':key,'label':label,'original_label':name,'date':month,'date_label':date_label,
                   'precision':'month_period' if m['part'] else 'month','status':'planned'}
            if m['endmonth']:
                end=date(year,int(m['endmonth']),1).strftime('%Y-%m')
                if end<month:raise ValueError('심사 예정 월 범위 역전')
                value.update(end_date=end,precision='month_range',date_label=date_label+f'~{int(m["endmonth"])}월 {m["endpart"] or ""}'.strip())
            values.append((value,m[0]))
    return values


def extract_shared_terms(notice, checked_at):
    channel = notice['source_channel']
    host, path = CHANNELS[channel]
    parsed = urlsplit(notice['url'])
    if (parsed.scheme != 'https' or parsed.hostname != host or parsed.path != path
            or source_id(notice['url'], channel) != notice['source_id']
            or not re.fullmatch('[0-9a-f]{64}', notice.get('sha256', ''))):
        raise ValueError('공식 공고 근거 불일치')
    if re.search(r'FAQ|질의|재공고|변경|취소|결과|현황|접수명단', notice['title'], re.I):
        raise ValueError('모집 원공고와 변경·후속 자료 분리 필요')
    if not re.search(r'공고|모집', notice['title']):
        raise ValueError('모집 공고 아님')
    sources = [(notice['url'], notice['body'], notice['sha256'])]
    for url, text in notice.get('attachment_texts', {}).items():
        digest = notice.get('attachment_hashes', {}).get(url, '')
        if urlsplit(url).hostname != host or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('첨부 근거 불일치')
        sources.append((url, text, digest))
    for original in notice.get('original_notices', []):
        try:
            from .collect_lp_original_notices import validate_original
        except ImportError:
            from collect_lp_original_notices import validate_original
        validate_original(original, notice, checked_at)
        sources.append((original['url'], original['body'], original['sha256']))
        sources.extend((url, text, original['attachment_hashes'][url])
                       for url, text in original.get('attachment_texts', {}).items())
    scope = classify_scope(notice['title'], ' '.join(text for _, text, _ in sources))
    if scope not in ('pe_blind', 'mixed_pe_blind'):
        raise ValueError('국내 PE 블라인드 모집 범위 미확인')
    if any(re.search(r'공동\s*출자|모태\s*펀드|출자자별',text) for _,text,_ in sources):
        raise ValueError('공동사업 출자기관별 금액 분리 필요')
    facts, evidence = defaultdict(list), defaultdict(list)

    def remember(field, value, url, digest, quote):
        facts[field].append(value)
        evidence[field].append({'source_url': url, 'sha256': digest, 'quote': quote})

    for url, raw, digest in sources:
        text = _compact(raw)
        # Repeated PE/VC detail sections must not become a second whole total.
        boundary = re.search(r'PE부문선정세부개요', text)
        overview = text[:boundary.start()] if boundary else text
        for m in re.finditer(r'(?:출자규모|출자금액|약정예정금액)[^\d]{0,10}(?:총)?(' + NUMBER + r')억원?(이내|내외)?', overview):
            prefix = overview[max(0, m.start()-35):m.start()]
            if re.search(r'펀드별|운용사별|최대출자자|PE분야VC분야', prefix):
                continue
            remember('total', int(m[1].replace(',', '')) * 100_000_000, url, digest, m[0])
            remember('amount_qualifier', m[2] or '', url, digest, m[0])
        for m in re.finditer(r'PE부문[:：·Ÿ•]*(' + NUMBER + r')억원?', overview, re.I):
            remember('pe_total', int(m[1].replace(',', '')) * 100_000_000, url, digest, m[0])
        for m in re.finditer(r'VC부문[:：·Ÿ•]*(' + NUMBER + r')억원?', overview, re.I):
            remember('vc_total', int(m[1].replace(',', '')) * 100_000_000, url, digest, m[0])
        # A summary matrix keeps spaces between numbers; concatenated PDF
        # digits cannot be assigned to columns safely. Require units + headers.
        matrix = re.search(r'구\s*분\s+계\s+PE\s+VC\s+출자\s*규모(?:\([^)]*\))?\s+('
                           + NUMBER + r')\s+(' + NUMBER + r')\s+(' + NUMBER
                           + r')\s+운용사(?:\([^)]*\))?\s+(\d+)\s+(\d+)\s+(\d+)', raw)
        if matrix:
            if not re.search(r'억원\s*[,·]\s*개사', raw[max(0,matrix.start()-120):matrix.start()]):
                raise ValueError('PE·VC 요약 표 단위 미확인')
            amounts = [int(v.replace(',', '')) * 100_000_000 for v in matrix.groups()[:3]]
            counts = [int(v) for v in matrix.groups()[3:]]
            if amounts[0] != amounts[1]+amounts[2] or counts[0] != counts[1]+counts[2]:
                raise ValueError('PE·VC 요약 표 합계 불일치')
            for field, value in zip(('total','pe_total','vc_total'),amounts):
                remember(field,value,url,digest,matrix[0])
            remember('amount_qualifier','내외' if '내외' in matrix[0] else '',url,digest,matrix[0])
            remember('pe_count',(counts[1], '내외' in matrix[0]),url,digest,matrix[0])
        for m in re.finditer(r'구\s*분\s+PE\s*분야\s+VC\s*분야\s+본회\s*출자규모\s+('
                             + NUMBER + r')억원\s*[~～]\s*(' + NUMBER + r')억원\s*(내외)?',raw):
            remember('pe_fund_range',[int(v.replace(',',''))*100_000_000 for v in m.groups()[:2]],url,digest,m[0])
            remember('pe_fund_qualifier',m[3] or '',url,digest,m[0])
        for m in re.finditer(r'(?:선정운용사(?:수)?|선정수)[^\d]{0,18}(?:총)?(\d+)개(?:사|운용사)(내외)?', text):
            remember('manager_count', (int(m[1]), bool(m[2])), url, digest, m[0])
        # Only labeled deadline dates are used, never document/LOC/track dates.
        for m in re.finditer(r'(?:제안서)?접수마감(?:일시|시한|일)?[:：·Ÿ•-]*[’\']?(20\d{2}|\d{2})[.년](\d{1,2})[.월](\d{1,2})[.일]?(?:\([월화수목금토일]\))?[,·]?(\d{1,2})(?::(\d{2})|시)', text):
            year = int(m[1]) if len(m[1]) == 4 else 2000 + int(m[1])
            stamp = datetime(year, int(m[2]), int(m[3]), int(m[4]), int(m[5] or 0))
            remember('deadline', stamp.isoformat() + '+09:00', url, digest, m[0])
        for m in re.finditer(r"[’']?(20\d{2}|\d{2})[.년](\d{1,2})[.월](\d{1,2})[.일]?(?:\([월화수목금토일]\))?제안서접수마감(\d{1,2}):(\d{2})",text):
            year=int(m[1]) if len(m[1])==4 else 2000+int(m[1])
            stamp=datetime(year,int(m[2]),int(m[3]),int(m[4]),int(m[5]))
            remember('deadline',stamp.isoformat()+'+09:00',url,digest,m[0])
        # Explicit PE/VC table headings bind per-fund amount and count. Fund
        # target sizes and example allocations are deliberately not consumed.
        for table in re.finditer(r'펀드별출자규모운용사수결성(?:예정)?규모.*?PE(.*?)(?:VC|선정방법|투자기구)', text):
            rows = []
            for m in re.finditer(r'(대형|중형이하|중형|소형|루키)(?:리그)?(' + NUMBER + r')억원?(\d+)개사(내외)?', table[1]):
                per_fund, count = int(m[2].replace(',', '')) * 100_000_000, int(m[3])
                rows.append({'name': m[1], 'per_fund_amount_krw': per_fund,
                             'manager_count': count, 'count_approximate': bool(m[4]),
                             'amount_krw': per_fund * count})
            if rows:
                remember('pe_segments', rows, url, digest, table[0])
        for m in re.finditer(r'펀드별(' + NUMBER + r')[~～](' + NUMBER + r')억원', text):
            remember('per_fund_range', [int(v.replace(',', '')) * 100_000_000 for v in m.groups()], url, digest, m[0])
        # Preserve literal purpose wording only when the document labels it.
        for m in re.finditer(r'(?:^|\n)\s*(?:\d+[.)]\s*)?(?:주목적(?:투자대상)?|투자목적)\s*[:：]\s*([^\n]{8,240})', raw):
            remember('purpose', re.sub(r'\s+', ' ', m[1]).strip(), url, digest, m[0])
        for m in re.finditer(r'(?:운용\s*목적|투자\s*목적|주목적)\s*[:：]\s*(.{8,240}?)(?=\s*[▪□■]\s*|$)',raw):
            remember('purpose',re.sub(r'\s+',' ',m[1]).strip(),url,digest,m[0])
        for schedule,quote in _planned_months(text):
            remember('schedule_'+schedule['stage'],schedule,url,digest,quote)

    total = _one(facts['total'], '총 출자액')
    pe_total = _one(facts['pe_total'], 'PE 출자액')
    vc_total = _one(facts['vc_total'], 'VC 출자액')
    segments = _one(facts['pe_segments'], 'PE 분야 표') or []
    count = _one(facts['manager_count'], '선정 수')
    deadline = _one(facts['deadline'], '접수 마감')
    purpose = _one(facts['purpose'], '주목적')
    ranges = _one(facts['per_fund_range'], '펀드별 출자액 범위')
    qualifier = '이내' if '이내' in facts['amount_qualifier'] else '내외' if '내외' in facts['amount_qualifier'] else ''
    if {'이내','내외'} <= set(facts['amount_qualifier']):
        raise ValueError('출자액 한도 조건 불일치')
    if total is not None and total <= 0:
        raise ValueError('출자액 범위 불일치')
    if pe_total is not None and (not total or not vc_total or pe_total + vc_total != total):
        raise ValueError('PE·VC 출자액과 총계 불일치')
    if segments:
        if not pe_total or sum(s['amount_krw'] for s in segments) != pe_total or len({s['name'] for s in segments}) != len(segments):
            raise ValueError('PE 분야 표 합계 불일치')
        count = (sum(s['manager_count'] for s in segments), any(s['count_approximate'] for s in segments))
    explicit_pe_count = _one(facts['pe_count'], 'PE 선정 수')
    if explicit_pe_count:
        count = explicit_pe_count
    elif pe_total is not None and scope=='mixed_pe_blind' and not segments:
        count = None
    pe_range = _one(facts['pe_fund_range'], 'PE 펀드별 출자액 범위')
    if pe_range:
        ranges = pe_range
        if not pe_total or not count or not ranges[0]*count[0] <= pe_total <= ranges[1]*count[0]:
            raise ValueError('PE 펀드별 출자 범위와 총액 불일치')
    if count and count[0] <= 0:
        raise ValueError('선정 수 범위 불일치')
    if ranges and (ranges[0] <= 0 or ranges[0] > ranges[1]):
        raise ValueError('펀드별 출자액 범위 불일치')
    original_dates = [o['date'] for o in notice.get('original_notices', []) if o.get('date')]
    announcement = min(original_dates) if original_dates else notice['date']
    if deadline and deadline[:10] < announcement:
        raise ValueError('접수 마감이 원공고일보다 빠름')
    if not any((total, count, deadline, purpose)):
        raise ValueError('지원하는 모집 조건을 찾지 못함')
    amount = pe_total or total
    combined = scope == 'mixed_pe_blind' and pe_total is None
    result = {'source_url': notice['url'], 'asset_scope': 'PE·VC' if combined else 'PE',
              'amount_scope': 'combined_pe_vc' if combined else 'pe_only',
              'segments': segments, 'extraction_evidence': dict(evidence), 'schedule_stages': []}
    if amount:
        result.update(commitment_amount_krw=amount, total_commitment_amount_krw=total,
                      commitment_label=f'{amount / 100_000_000:,.0f}억원'+(' '+qualifier if qualifier else '')+(' (PE·VC 합계)' if combined else ''))
    if count:
        result.update(manager_count=count[0], manager_count_label=f'{count[0]}개사'+(' 내외' if count[1] else '')+(' (PE·VC 합계)' if combined else ''))
        if not segments and count[0] == 1 and scope == 'pe_blind' and amount:
            result['per_fund_amount_krw'] = amount
    if ranges:
        result['per_fund_range_krw'] = ranges
        if pe_range:result['per_fund_qualifier'] = _one(facts['pe_fund_qualifier'],'펀드별 출자액 범위 조건') or ''
    if purpose:
        result['primary_investment'] = {'text': purpose}
    if deadline:
        result['deadline'] = deadline
        result['schedule_stages'].append({'stage': 'application', 'label': '접수 마감', 'date': deadline,
                                         'precision': 'datetime', 'status': 'announced_deadline'})
    for key in ('screening','due_diligence','interview','selection'):
        schedules=facts['schedule_'+key]
        # Literal stage captions can vary while their planned period agrees.
        periods=[{k:v for k,v in s.items() if k not in ('original_label','label')} for s in schedules]
        # '9월' and '9월 중' both mean during September. Keep the
        # explicit source wording, without interpreting '중' as mid-month.
        for coarse in list(periods):
            if coarse.get('precision')=='month':
                equivalents=[p for p in periods if p.get('precision')=='month_period'
                    and p.get('date')==coarse['date'] and p.get('stage')==coarse['stage']
                    and p.get('status')==coarse['status']
                    and re.fullmatch(r'\d+월\s*중',p.get('date_label',''))]
                if equivalents:periods.remove(coarse)
        period=_one(periods,'심사 예정 일정')
        if period:
            if period['date']<announcement[:7]:raise ValueError('심사 일정이 원공고보다 빠름')
            result['schedule_stages'].append(next(s for s in schedules if {k:v for k,v in s.items() if k not in ('original_label','label')}==period))
    result['missing_fields'] = [field for field in ('commitment_amount_krw', 'manager_count', 'deadline', 'primary_investment') if field not in result]
    return result


def shared_terms(notices, checked_at):
    terms, holds = {}, []
    for notice in notices:
        try:
            terms[notice['url']] = extract_shared_terms(notice, checked_at)
        except (ValueError, KeyError, TypeError) as exc:
            holds.append({'stage': 'shared_terms', 'url': notice['url'], 'error': str(exc)})
    return terms, holds
