"""Conservative, article-local exclusions for non-investment procurements."""
import re


def procurement_reason(title,body):
    title=re.sub(r'\s+','',title);body=re.sub(r'\s+','',body)
    if re.search(r'(?<![A-Za-z])PEF?(?![A-Za-z])|기관전용|경영참여형|블라인드',title,re.I):
        return None  # A mixed title needs track evidence rather than exclusion.
    if (all(word in title for word in ('미스터리쇼핑','용역','입찰'))
            and all(word in body for word in ('미스터리쇼핑','용역','사업예산','계약방법'))):
        return 'fund_sales_monitoring_procurement'
    if (re.search(r'재해복구시스템.*구축.*입찰',title)
            and '공고명' in body and '재해복구시스템구축' in body and 'ICT전략실' in body):
        return 'it_disaster_recovery_procurement'
    return None


def central_not_investing(text):
    text=re.sub(r'\s+','',text)
    return ('농협중앙회가직접계약서체결및자금출자를진행하지않음' in text
            and '개별회원조합과자산매각및투자계약을각각개별적으로체결' in text)
