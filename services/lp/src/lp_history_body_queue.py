"""Pure bounded body plan; neither fetches documents nor approves PE publication."""
import copy
import hashlib
import json
import re

try:
    from .discover_lp_history import summary
except ImportError:
    from discover_lp_history import summary


def canonical_url(ident):
    if not isinstance(ident,str) or not re.fullmatch(r'[1-9][0-9]*',ident):
        raise ValueError('Invalid historical body source ID')
    return f'https://www.kgrowth.or.kr/notice_view.asp?idx={ident}&str_type=1&tab=1'


def fingerprint(document):
    return hashlib.sha256(json.dumps([document['title'],document['date'],document['body']],
                                     ensure_ascii=False).encode()).hexdigest()


def plan(state, completed_documents=(), *, limit=4):
    if type(limit) is not int or not 1 <= limit <= 4:
        raise ValueError('Body queue limit must be between 1 and 4')
    # Summary reparses original listing receipts rather than trusting saved counts.
    report=summary(copy.deepcopy(state))
    if not report['listing_window_complete'] or report.get('holds'):
        raise ValueError('Complete unblocked historical listing required')
    listing={r['source_id']:r for r in report['rows']}
    completed={}
    compact=lambda text:re.sub(r'\s+','',text)
    for document in completed_documents:
        if not isinstance(document,dict):raise ValueError('Invalid completed document')
        ident=document.get('source_id')
        url=canonical_url(ident)
        if (document.get('url')!=url or document.get('institution_id','kgrowth')!='kgrowth'
                or ident not in listing):
            raise ValueError('Completed body identity does not match listing')
        if (document.get('restricted') or document.get('owner_closed') or document.get('closed')
                or document.get('status') in {'restricted','owner_closed','closed'}
                or document.get('reason')=='owner_closed'):
            raise ValueError('Restricted document cannot complete body evidence')
        if any(not isinstance(document.get(k),str) or not document[k].strip()
               for k in ('title','date','body','sha256')):
            raise ValueError('Completed body evidence is missing')
        row=listing[ident]
        if (compact(document['title'])!=compact(row['title']) or document['date']!=row['date']
                or document['sha256']!=fingerprint(document)):
            raise ValueError('Completed body title/date/fingerprint mismatch')
        previous=completed.get(ident)
        if previous is not None and previous!=document['sha256']:
            raise ValueError('Conflicting completed body versions')
        completed[ident]=document['sha256']
    retained={r['source_id'] for r in listing.values() if r['retained_body_observed']}
    # Explicit official category only; ordinary notices mentioning forms remain eligible.
    forms={ident for ident,r in listing.items() if r['title'].startswith('【제출서식】')}
    pending=sorted((r for ident,r in listing.items()
                    if ident not in forms and ident not in retained and ident not in completed),
                   key=lambda r:(r['date'],int(r['source_id'])))
    rows=[]
    for row in pending[:limit]:
        rows.append({'institution_id':'kgrowth','source_id':row['source_id'],
                     'url':canonical_url(row['source_id']),'listing_url':row['url'],
                     'title':row['title'],'date':row['date']})
    return {'window':copy.deepcopy(report['window']), 'retained_body_observed':len(retained),
            'retained_body_in_scope':len(retained-forms),
            'submission_forms_listing_only':len(forms),
            'body_rows_in_scope':len(listing)-len(forms),
            'validated_body_completed':len(completed),
            'new_validated_body_completed':len(set(completed)-retained),
            'pending_count':len(pending),'planned_count':len(rows),'rows':rows,
            'attachment_completion':'not_assessed','source_history_complete':False,
            'meaning':'Retained metadata observations and validated body completions are distinct; no PE or publication decision.'}
