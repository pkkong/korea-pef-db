"""Typed history source adapters; source identity never comes from a notice ID list."""
import copy
import hashlib
import json
import re


def institution(history):
    expected={'lp_history_listing_v1':'kgrowth','ktcu_history_listings_v1':'ktcu'}
    iid=expected.get(history.get('kind'))
    if iid is None or history.get('institution_id')!=iid:
        raise ValueError('Unsupported historical institution/cursor identity')
    return iid


def canonical_url(ident, iid='kgrowth'):
    if not isinstance(ident,str) or not re.fullmatch(r'[1-9][0-9]*',ident):
        raise ValueError('Invalid historical body source ID')
    if iid=='kgrowth':return f'https://www.kgrowth.or.kr/notice_view.asp?idx={ident}&str_type=1&tab=1'
    if iid=='ktcu':return f'https://www.ktcu.or.kr/PPW-CSB-000101/{ident}'
    raise ValueError('Unsupported historical institution')


def listing_summary(history):
    iid=institution(history)
    if iid=='kgrowth':
        try:from .discover_lp_history import summary
        except ImportError:from discover_lp_history import summary
        return summary(history)
    try:from .discover_ktcu_history import replay
    except ImportError:from discover_ktcu_history import replay
    result=copy.deepcopy(replay(history))
    retained=set()
    for record in history.get('retained_records',[]):
        match=re.fullmatch(r'https://www\.ktcu\.or\.kr/PPW-CSB-000101/([1-9][0-9]*)',record.get('url',''))
        if not match or not re.fullmatch(r'[a-f0-9]{64}',record.get('source_sha256','')):
            raise ValueError('Invalid retained KTCU metadata identity')
        retained.add((match[1],record['date'],re.sub(r'\s+','',record['title'])))
    for row in result['rows']:
        if not row['source_id'].startswith('ktcu:'):
            raise ValueError('Invalid KTCU listing identity')
        row['source_id']=row['source_id'].removeprefix('ktcu:')
        if row['url']!=canonical_url(row['source_id'],'ktcu'):
            raise ValueError('KTCU body/listing URL mismatch')
        row['retained_body_observed']=(row['source_id'],row['date'],re.sub(r'\s+','',row['title'])) in retained
    return result


def listing_digest(history):
    if institution(history)=='kgrowth':
        parts=[r['sha256'] for r in history['receipts']]
    else:parts=[(term,[r['sha256'] for r in receipts]) for term,receipts in sorted(history['searches'].items())]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def retained_ktcu(index):
    try:from .build_lp_history_coverage import validate_index,valid_index_record
    except ImportError:from build_lp_history_coverage import validate_index,valid_index_record
    validate_index(index)
    if not index['database_index_complete'] or index['database_rows']!=index['database_total_rows']:
        raise ValueError('Complete retained metadata index required')
    records=[]
    for n in index['records']:
        if n.get('institution_id')!='ktcu':continue
        if not valid_index_record(n):raise ValueError('Invalid KTCU body metadata')
        if (not n['body_present'] or not re.fullmatch(r'[a-f0-9]{64}',n.get('source_sha256') or '')
                or not re.fullmatch(r'https://www\.ktcu\.or\.kr/PPW-CSB-000101/[1-9][0-9]*',n.get('url',''))):continue
        records.append({k:n[k] for k in ('url','date','title','source_sha256')})
    return records


def effective_history(history,report=None,index=None):
    result=copy.deepcopy(history)
    if institution(history)=='ktcu':
        if report is not None:
            if 'retained_records' not in report:raise ValueError('Retained KTCU metadata snapshot required')
            result['retained_records']=copy.deepcopy(report['retained_records'])
        elif index is not None:result['retained_records']=retained_ktcu(index)
        elif 'retained_records' not in result:raise ValueError('Retained KTCU metadata snapshot required')
    return result


def parse_detail(ident,raw,iid):
    if iid=='kgrowth':
        try:from .collect_kgrowth_programs import parse_notice
        except ImportError:from collect_kgrowth_programs import parse_notice
        return parse_notice(ident,raw)
    if iid=='ktcu':
        try:from .collect_ktcu_program import parse_notice
        except ImportError:from collect_ktcu_program import parse_notice
        return parse_notice(ident,raw)
    raise ValueError('Unsupported historical body source')


def transport(history):
    if institution(history)=='kgrowth':
        try:from .collect_kgrowth_programs import official_fetcher
        except ImportError:from collect_kgrowth_programs import official_fetcher
        return official_fetcher()
    try:from .collect_ktcu_program import _get
    except ImportError:from collect_ktcu_program import _get
    return _get
