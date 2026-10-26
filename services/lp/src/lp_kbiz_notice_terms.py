"""Isolate an officially offered KBIZ PE track without borrowing shared budgets."""
import re
try:
    from .lp_institution_notice_terms import extract_terms
except ImportError:
    from lp_institution_notice_terms import extract_terms


def pe_track(n):
    if n.get('institution_id')!='kbiz':return []
    title=re.sub(r'\s+','',n['title'])
    body=re.sub(r'\s+','',n['body'])
    if not ('국내' in title and '블라인드' in title) or re.search(r'VC펀드|부동산|대출|평가기관',title,re.I):return []
    offering=body.split('신청자격',1)[0]
    legal=re.search(r'투자기구.{0,30}\[PE\].{0,80}기관전용사모집합투자기구.{0,60}경영참여목적투자',offering)
    application=re.search(r'각운용사는매년1개부문의출자사업에만지원가능\(PE/VC공통\)',body,re.I)
    submission=re.search(r'PE또는VC택1',body,re.I)
    return [m[0] for m in (legal,application,submission)] if all((legal,application,submission)) else []


def terms(n):
    quotes=pe_track(n)
    if not quotes:raise ValueError('Independent KBIZ domestic PE blind application not verified')
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
        from datetime import date
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
