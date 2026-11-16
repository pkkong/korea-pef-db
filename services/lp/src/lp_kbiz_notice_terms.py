"""Isolate an officially offered KBIZ PE track without borrowing shared budgets."""
import re
from datetime import date, datetime
try:
    from .lp_institution_notice_terms import extract_terms
except ImportError:
    from lp_institution_notice_terms import extract_terms


def _compact(raw):
    return re.sub(r'[\s\u200b\ufeff]+', '', raw)


def _body_quote(n, compact_quote):
    raw = n['body']
    positions = [i for i, c in enumerate(raw) if not c.isspace() and c not in '\u200b\ufeff']
    text = ''.join(raw[i] for i in positions)
    at = text.find(compact_quote)
    if at < 0:
        raise ValueError('KBIZ body quote differs from retained text')
    return raw[positions[at]:positions[at + len(compact_quote) - 1] + 1]


def _historical_track(n):
    """The older current-offering table, not its historical GP qualifications.

    Joint notices label PE and VC legal forms separately and permit a single
    application field. PE-only notices need neither a VC row nor a PE/VC choice.
    The notice's own introduction explicitly says domestic blind PE.
    """
    if n.get('institution_id') != 'kbiz':
        return None
    title, body = _compact(n['title']), _compact(n['body'])
    if ('국내' not in title or not re.search(r'(?<![A-Za-z])PE(?![A-Za-z])', title)
            or re.search(r'결과|취소|정정|수정|변경|연장|평가|연구|용역|사무관리|멀티에셋|부동산|대출', title)):
        return None
    overview = re.search(r'1\.선정주요기준(.*?)신청자격', body)
    if not overview:
        return None
    years = set(re.findall(r'20\d{2}년', body[:overview.start()]))
    title_years = {y + '년' for y in re.findall(r'20\d{2}', title)}
    if len(years) != 1 or (title_years and title_years != years):
        return None
    intro = re.search(r'중소기업중앙회(?:\(노란우산(?:공제)?\))?국내블라인드PE(?:[∙·‧ㆍ]VC)?'
                      r'펀드선정계획을아래와같이공고합니다', body[:overview.start()])
    mode = re.search(r'운용방식[∙·‧ㆍ]*블라인드형태의PE(?P<vc>[∙·‧ㆍ]VC)?펀드운용사소재지', overview[1])
    vehicle = re.search(r'투자기구(.*?)출자금액', overview[1])
    if not all((intro, mode, vehicle)):
        return None
    legal_area = vehicle[1]
    mixed = bool(mode['vc'])
    markers = re.findall(r'\[(PE|VC)펀드\]', legal_area)
    if mixed:
        if markers != ['PE', 'VC']:
            return None
        pe = re.search(r'\[PE펀드\](.*?)\[VC펀드\]', legal_area)
        application = re.search(r'제안운용사는1개분야에만자율적으로지원가능', body)
        if not pe or not application:
            return None
        pe_legal = pe[1]
    else:
        if markers not in ([], ['PE']):
            return None
        application = None
        pe_legal = legal_area
    if re.search(r'창업|벤처|신기술|일반사모', pe_legal):
        return None
    legal = (re.search(r'기관전용사모집합투자기구.{0,35}경영참여목적투자', pe_legal)
             or re.search(r'경영참여형사모집합투자기구', pe_legal))
    if not legal:
        return None
    quotes = [intro[0], mode[0], vehicle[0]]
    if application:
        quotes.append(application[0])
    return {'mixed': mixed, 'quotes': [_body_quote(n, q) for q in quotes]}


def pe_track(n):
    if n.get('institution_id')!='kbiz':return []
    historical = _historical_track(n)
    if historical:
        return historical['quotes']
    title=re.sub(r'\s+','',n['title'])
    body=re.sub(r'\s+','',n['body'])
    if not ('국내' in title and '블라인드' in title) or re.search(r'VC펀드|부동산|대출|평가기관',title,re.I):return []
    offering=body.split('신청자격',1)[0]
    legal=re.search(r'투자기구.{0,30}\[PE\].{0,80}기관전용사모집합투자기구.{0,60}경영참여목적투자',offering)
    application=re.search(r'각운용사는매년1개부문의출자사업에만지원가능\(PE/VC공통\)',body,re.I)
    submission=re.search(r'PE또는VC택1',body,re.I)
    return [m[0] for m in (legal,application,submission)] if all((legal,application,submission)) else []


def _historical_allocation(n):
    """Read the PE-labelled budget and reconcile its league totals only.

    A league budget divided by its planned manager count is not a per-fund
    allocation. Joint PE/VC totals and VC league rows are never returned.
    """
    body = _compact(n['body'])
    areas = list(re.finditer(r'출자금액(.*?)신청자격', body))
    if len(areas) != 1:
        raise ValueError('KBIZ historical offering budget missing or repeated')
    blocks = list(re.finditer(r'\[(PE|VC)펀드\](.*?)(?=\[(?:PE|VC)펀드\]|$)', areas[0][1]))
    pe = [m for m in blocks if m[1] == 'PE']
    if len(pe) != 1:
        raise ValueError('KBIZ independent PE budget missing or repeated')
    part = pe[0][2].rstrip('∙·‧ㆍ')
    number = r'(?:\d{1,3}(?:,\d{3})+|\d+)'
    total = re.match(r'[:：]*총(' + number + r')억원(이내|내외|이하)?(?:\(순위별차등배분가능\))?', part)
    if not total:
        raise ValueError('KBIZ historical PE budget layout changed')
    rest = part[total.end():]
    pattern = re.compile(r'-([가-힣]+(?:\([가-힣]+\))?)[:：]총(' + number + r')억원(이내|내외|이하)?'
                         r'\((\d+)개사(이내|내외|이하)?\)')
    rows = list(pattern.finditer(rest))
    amount = int(total[1].replace(',', '')) * 100_000_000
    if not rows or ''.join(m[0] for m in rows) != rest or amount <= 0:
        raise ValueError('KBIZ historical PE league budget incomplete')
    segments = [{'name': m[1], 'amount_krw': int(m[2].replace(',', '')) * 100_000_000,
                 'manager_count': int(m[4]), 'count_approximate': m[5] == '내외'} for m in rows]
    if (len({s['name'] for s in segments}) != len(segments) or any(s['amount_krw'] <= 0 or s['manager_count'] <= 0 for s in segments)
            or sum(s['amount_krw'] for s in segments) != amount):
        raise ValueError('KBIZ historical PE league totals do not reconcile')
    count_qualifiers = {m[5] or '' for m in rows}
    if len(count_qualifiers) != 1:
        raise ValueError('KBIZ historical PE manager-count qualifiers differ')
    count = sum(s['manager_count'] for s in segments)
    qualifier = total[2] or ''
    evidence = {'source_url': n['url'], 'sha256': n['sha256'], 'quote': _body_quote(n, '[PE펀드]' + part)}
    return {'amount_scope': 'pe_only', 'commitment_amount_krw': amount,
            'commitment_label': f'{amount/100_000_000:,.0f}억원' + (' ' + qualifier if qualifier else ''),
            'manager_count': count, 'manager_count_label': f'{count}개사' + (' ' + next(iter(count_qualifiers)) if count_qualifiers != {''} else ''),
            'segments': segments, 'extraction_evidence': {'pe_allocation': [evidence]}}


def _historical_deadline(n):
    body = _compact(n['body'])
    sections = list(re.finditer(r'3\.제출서류및기한(.*?)(?=4\.)', body))
    if len(sections) != 1:
        return {}
    full = re.compile(r'기한[:：](20\d{2})년(\d{1,2})월(\d{1,2})일(?:\(([월화수목금토일])\))?'
                      r'(오전|오후)?(\d{1,2})(?::(\d{2})|시)')
    rows = list(full.finditer(sections[0][1]))
    if len(rows) != 1:
        raise ValueError('KBIZ historical submission deadline missing or repeated')
    def stamp(year, month, day, weekday, period, hour, minute):
        y, mo, d, h, mi = int(year), int(month), int(day), int(hour), int(minute or 0)
        y = y if y >= 2000 else 2000 + y
        if period and not 1 <= h <= 12:
            raise ValueError('KBIZ historical deadline AM/PM hour invalid')
        h = h % 12 + (12 if period == '오후' else 0) if period else h
        value = datetime(y, mo, d, h, mi)
        if weekday and '월화수목금토일'[value.weekday()] != weekday:
            raise ValueError('KBIZ historical deadline date and weekday conflict')
        if value.date().isoformat() < n['date']:
            raise ValueError('KBIZ historical deadline predates offering')
        return value.isoformat() + '+09:00'
    value = stamp(*rows[0].groups())
    table = re.compile(r"[’']?(20\d{2}|\d{2})\.(\d{1,2})\.(\d{1,2})(?:\(([월화수목금토일])\))?"
                       r'제안서접수마감(오전|오후)?(\d{1,2})(?::(\d{2})|시)')
    table_rows = list(table.finditer(body[:sections[0].start()]))
    if table_rows and (len(table_rows) != 1 or stamp(*table_rows[0].groups()) != value):
        raise ValueError('KBIZ historical table and submission deadline conflict')
    return {'deadline': value, 'deadline_precision': 'datetime', 'extraction_evidence': {'deadline': [
        {'source_url': n['url'], 'sha256': n['sha256'], 'quote': _body_quote(n, rows[0][0])}]}}


def terms(n):
    quotes=pe_track(n)
    if not quotes:raise ValueError('Independent KBIZ domestic PE blind application not verified')
    historical = _historical_track(n)
    if historical:
        try:
            result = _historical_allocation(n)
        except ValueError as exc:
            # Basic PE publication is allowed without a readable allocation.
            # Keep the mixed-budget guard even when this older table cannot be
            # reconciled; an exception here would let the generic headline
            # fallback interpret a joint PE/VC budget as a PE-only number.
            result = {'amount_scope': 'pe_track_without_allocation' if historical['mixed'] else 'pe_only',
                      'allocation_error': str(exc), 'extraction_evidence': {}}
        if not historical['mixed'] and result.get('commitment_amount_krw'):
            result['total_commitment_amount_krw'] = result['commitment_amount_krw']
        try:
            deadline = _historical_deadline(n)
        except ValueError as exc:
            deadline = {'deadline_error': str(exc)}
        result['extraction_evidence'].update(deadline.pop('extraction_evidence', {}))
        result.update(deadline)
        result['extraction_evidence']['pe_track'] = [
            {'source_url': n['url'], 'sha256': n['sha256'], 'quote': q} for q in quotes]
        return result
    raw=extract_terms(n)
    result={k:raw[k] for k in ('deadline','deadline_precision','deadline_error','schedule_stages') if k in raw}
    result['amount_scope']='pe_track_without_allocation'
    result['extraction_evidence']={k:v for k,v in raw.get('extraction_evidence',{}).items() if k=='deadline' or k.startswith('schedule_')}
    result['extraction_evidence']['pe_track']=[{'source_url':n['url'],'sha256':n['sha256'],'quote':q} for q in quotes]
    text=re.sub(r'\s+','',n['body'])
    schedules=[]
    patterns=[('screening','1차 심사·실사',r'정량평가및현장실사(20\d{2})\.(\d{1,2})[~～](\d{1,2})월'),
              ('interview','2차 심사',r'기술능력평가\(정성,PT\)(20\d{2})\.(\d{1,2})월'),
              ('selection','최종 선정',r'내부승인절차및결과통보(20\d{2})\.(\d{1,2})월')]
    for stage,label,pattern in patterns:
        matches=list(re.finditer(pattern,text,re.I))
        if len(matches)>1:raise ValueError('Conflicting KBIZ planned schedule')
        if not matches:continue
        m=matches[0];year,month=map(int,m.groups()[:2])
        start=date(year,month,1).strftime('%Y-%m')
        if start<n['date'][:7]:raise ValueError('KBIZ planned date predates offering')
        item={'stage':stage,'label':label,'original_label':label,'date':start,'date_label':f'{month}월','precision':'month','status':'planned'}
        if len(m.groups())==3:
            endmonth=int(m[3]);end=date(year,endmonth,1).strftime('%Y-%m')
            if end<start:raise ValueError('Reversed KBIZ schedule range')
            item.update(end_date=end,precision='month_range',date_label=f'{month}~{endmonth}월')
        schedules.append(item)
        result['extraction_evidence'].setdefault('schedule_'+stage,[]).append({'source_url':n['url'],'sha256':n['sha256'],'quote':m[0]})
    if schedules:result['schedule_stages']=schedules
    return result
