"""Resumable historical KTCU search listings, never detail or PE approval."""
import argparse
import base64
import copy
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

try:
    from .ktcu_listing import parse_rows,last_page
    from .collect_ktcu_program import SEARCH_TERMS,BASE
except ImportError:
    from ktcu_listing import parse_rows,last_page
    from collect_ktcu_program import SEARCH_TERMS,BASE

START='2023-01-01'
MAX_BYTES=32*1024*1024


def url(term,page):
    if term not in SEARCH_TERMS or type(page) is not int or not 1<=page<=200:
        raise ValueError('Invalid KTCU historical search/page')
    return BASE+'/PPW-CSB-000101?'+urlencode({'srchKey':'sj','srchText':term,'curPage':page})


def initial(as_of):
    if date.fromisoformat(as_of).isoformat()!=as_of or as_of<START:
        raise ValueError('Invalid KTCU historical window')
    return {'kind':'ktcu_history_listings_v1','institution_id':'ktcu',
            'window':{'start':START,'end':as_of},'searches':{s:[] for s in SEARCH_TERMS},
            'batches':[],'continuity_receipts':[],'holds':[]}


def receipt(term,page,raw):
    if not isinstance(raw,bytes) or len(raw)>12*1024*1024:
        raise ValueError('KTCU historical response size/type invalid')
    html=raw.decode('utf-8');target=url(term,page)
    rows=parse_rows(html,target)
    return {'term':term,'page':page,'url':target,'sha256':hashlib.sha256(raw).hexdigest(),
            'html':html,'row_count':len(rows),'last_page':last_page(html,target)}


def replay(state):
    if (state.get('kind')!='ktcu_history_listings_v1' or state.get('institution_id')!='ktcu'
            or state.get('window',{}).get('start')!=START or set(state['searches'])!=set(SEARCH_TERMS)):
        raise ValueError('KTCU historical cursor identity mismatch')
    initial(state['window']['end'])
    all_rows={};streams={}
    for term in SEARCH_TERMS:
        receipts=state['searches'][term]
        if not isinstance(receipts,list) or len(receipts)>200:
            raise ValueError('KTCU historical page limit exceeded')
        boundary='batch_limit';seen=set();previous_date=None
        for page,item in enumerate(receipts,1):
            if boundary!='batch_limit':raise ValueError('KTCU receipt after completed search boundary')
            rebuilt=receipt(term,page,item['html'].encode('utf-8'))
            if any(item.get(k)!=rebuilt[k] for k in rebuilt):
                raise ValueError('KTCU historical receipt identity/fingerprint mismatch')
            rows=parse_rows(item['html'],item['url']);regular=[r for r in rows if not r['pinned']]
            fresh={r['source_id'] for r in regular}-seen
            for row in regular:
                if previous_date is not None and row['date']>previous_date:
                    raise ValueError('KTCU historical dates are not descending')
                previous_date=row['date']
            for row in rows:
                ident=row['source_id']
                if ident in all_rows and any(all_rows[ident][k]!=row[k] for k in ('title','date')):
                    raise ValueError('KTCU historical metadata conflict across searches')
                all_rows[ident]=row
            if regular and not fresh:
                raise ValueError('KTCU historical pagination did not advance')
            if not rows:boundary='confirmed_empty'
            elif regular and all(r['date']<START for r in regular):boundary='observed_older_page'
            elif item['last_page'] is not None and page==item['last_page']:boundary='observed_last_page'
            elif not fresh:raise ValueError('KTCU historical pagination did not advance')
            seen.update(r['source_id'] for r in regular)
        streams[term]={'pages':len(receipts),'next_page':len(receipts)+1,'boundary':boundary,
                       'complete':boundary!='batch_limit'}
    rows=[r for r in all_rows.values() if START<=r['date']<=state['window']['end']]
    return {'institution_id':'ktcu','window':state['window'],'searches':streams,'rows':rows,
            'listing_window_complete':all(s['complete'] for s in streams.values()),
            'source_history_complete':False,'pe_business_count':None,'holds':state['holds'],
            'last_batch':state['batches'][-1] if state['batches'] else None}


def run_batch(previous,fetch,*,max_requests=4):
    if type(max_requests) is not int or not 2<=max_requests<=4:
        raise ValueError('KTCU history batch request limit invalid')
    state=copy.deepcopy(previous)
    if len(json.dumps(state,ensure_ascii=False).encode())>MAX_BYTES:
        raise ValueError('KTCU historical cursor size exceeded')
    status=replay(state)
    if state['holds']:raise ValueError('Resolve saved KTCU historical failure first')
    if status['listing_window_complete']:return state
    stats={'checked_at':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),'requests':0,'new_pages':0};state['batches'].append(stats)
    active=None;raw=None
    try:
        for term in SEARCH_TERMS:
            stream=status['searches'][term]
            if stream['complete']:continue
            if state['searches'][term]:
                if stats['requests']>=max_requests:break
                page=len(state['searches'][term]);active={'term':term,'page':page,'url':url(term,page)};raw=None
                stats['requests']+=1;raw=fetch(active['url']);anchor=receipt(term,page,raw)
                prior=state['searches'][term][-1]
                if (parse_rows(anchor['html'],anchor['url'])!=parse_rows(prior['html'],prior['url'])
                        or anchor['last_page']!=prior['last_page']):
                    raise ValueError('KTCU historical pagination changed')
                state['continuity_receipts'].append(anchor)
            while stats['requests']<max_requests:
                page=len(state['searches'][term])+1;active={'term':term,'page':page,'url':url(term,page)};raw=None
                stats['requests']+=1;raw=fetch(active['url']);item=receipt(term,page,raw)
                candidate=copy.deepcopy(state);candidate['searches'][term].append(item)
                next_status=replay(candidate)
                if len(json.dumps(candidate,ensure_ascii=False).encode())>MAX_BYTES:
                    raise ValueError('KTCU historical cursor size exceeded')
                state['searches'][term].append(item);stats['new_pages']+=1
                if next_status['searches'][term]['complete']:break
    except Exception as error:
        state['holds'].append({**(active or {}),'error':type(error).__name__+': '+str(error)[:600]})
        if isinstance(raw,bytes) and len(raw)<=12*1024*1024:
            state['failed_response']={**(active or {}),'sha256':hashlib.sha256(raw).hexdigest(),
                                      'raw_base64':base64.b64encode(raw).decode('ascii')}
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path)
    parser.add_argument('--as-of')
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    if args.state and args.as_of:parser.error('Choose saved cursor or initial as-of date')
    if args.state:
        if args.state.stat().st_size>MAX_BYTES:raise ValueError('KTCU historical input size exceeded')
        state=json.loads(args.state.read_text())
    else:state=initial(args.as_of or datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat())
    try:
        from .collect_ktcu_program import _get
    except ImportError:
        from collect_ktcu_program import _get
    result=run_batch(state,_get);summary=replay(result)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for name,value in (('history-state.json',result),('history-summary.json',summary)):
        target=args.output_dir/name;temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(value,ensure_ascii=False));temporary.replace(target)
    print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False))
    return 1 if result['holds'] else 0


if __name__=='__main__':raise SystemExit(main())
