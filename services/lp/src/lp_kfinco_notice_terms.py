"""Offering-labelled K-FINCO facts, without combining separate solicitations."""
import re
from datetime import date
try:
    from .lp_institution_notice_terms import extract_terms
except ImportError:
    from lp_institution_notice_terms import extract_terms


def terms(n):
    result=extract_terms(n)
    text=re.sub(r'\s+','',n['body'])
    amount=re.search(r'조합약정금액총([\d,]+)억원',text)
    if amount:
        value=int(amount[1].replace(',',''))*100_000_000
        if result.get('commitment_amount_krw') not in (None,value):raise ValueError('KFINCO amount evidence conflicts')
        result.update(commitment_amount_krw=value,commitment_label=f'{value/100_000_000:,.0f}억원',amount_scope='pe_only')
        result.setdefault('extraction_evidence',{}).setdefault('total',[]).append({'source_url':n['url'],'sha256':n['sha256'],'quote':amount[0]})
    final=re.search(r'진행일정.{0,200}최종선정[:：·-]*(\d{1,2})월(중|초|말)?',text)
    if final:
        month=int(final[1]);year=int(n['date'][:4]);stamp=date(year,month,1).strftime('%Y-%m')
        if stamp>=n['date'][:7]:
            stage={'stage':'selection','label':'최종 선정','original_label':'최종 선정','date':stamp,
                   'date_label':f'{month}월'+(' '+final[2] if final[2] else ''),'precision':'month_period' if final[2] else 'month','status':'planned'}
            result['schedule_stages']=[s for s in result.get('schedule_stages',[]) if s['stage']!='selection']+[stage]
            result.setdefault('extraction_evidence',{}).setdefault('schedule_selection',[]).append({'source_url':n['url'],'sha256':n['sha256'],'quote':final[0]})
    return result
