"""Reuse retained raw evidence before a bounded same-business preferred capture.

The source pair comes from an existing public PE program and retained collection,
never caller-supplied notice IDs. No result/amount/publication approval occurs.
"""
import argparse
import base64
import copy
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError
from urllib.parse import urlsplit

try:
    from . import collect_koreapost_program as k
    from .lp_notice_publication import _identity, _event
    from .lp_attachment_text import extract_attachment, MAX_FILE_BYTES
    from .koreapost_coinvestment_preferred import _safe_url, _download_url, _protected
except ImportError:
    import collect_koreapost_program as k
    from lp_notice_publication import _identity, _event
    from lp_attachment_text import extract_attachment, MAX_FILE_BYTES
    from koreapost_coinvestment_preferred import _safe_url, _download_url, _protected

KIND = 'koreapost_preferred_capture_v1'
MAX_BODY_BYTES = 12 * 1024 * 1024
MAX_INPUT_BYTES = 150 * 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def detail_proof(n, raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BODY_BYTES:
        raise ValueError('Invalid bounded KoreaPost detail response')
    number = re.fullmatch(r'0041:([1-9][0-9]*)', n['source_id'])
    parsed = k._detail(number[1], raw) if number else None
    if not parsed or any(n.get(key) != value for key, value in parsed.items()):
        raise ValueError('Retained KoreaPost body identity changed')
    return {'kind':'koreapost_detail_body_v1','raw_base64':base64.b64encode(raw).decode('ascii'),
            'sha256':sha(raw),'byte_length':len(raw)}


def attachment_proof(n, raw):
    import pypdf
    if (pypdf.__version__ != '6.10.0' or not isinstance(raw, bytes)
            or not raw.startswith(b'%PDF') or len(raw) > MAX_FILE_BYTES):
        raise ValueError('Pinned complete PDF reader required')
    url = n['attachments'][0]
    if n.get('attachment_hashes', {}).get(url) != sha(raw):
        raise ValueError('Retained KoreaPost recruitment PDF changed')
    return {'kind':'koreapost_attachment_body_v1','raw_base64':base64.b64encode(raw).decode('ascii'),
            'sha256':sha(raw),'byte_length':len(raw),'pdf_reader_version':'6.10.0',
            'extracted':extract_attachment(raw)}


def plan(source, programs, public_run):
    if source.get('error') or not source.get('notices'):
        raise ValueError('Healthy retained KoreaPost collection required')
    notices = [{**copy.deepcopy(n),'institution_id':'koreapost'} for n in source['notices']]
    if len({n['url'] for n in notices}) != len(notices) or len({n['source_id'] for n in notices}) != len(notices):
        raise ValueError('Duplicate retained KoreaPost identity')
    candidates=[]
    for p in programs:
        if (p['institution_id'] != 'koreapost' or p.get('asset_scope') != 'PE'
                or p.get('preferred_gps') or p.get('selected_gps') or p.get('manual_review_id')):
            continue
        events={e['url']:e['type'] for e in p['events']}
        originals=[n for n in notices if events.get(n['url'])=='모집 공고'
                   and _event(n)['type']=='모집 공고' and re.search(r'국내\s*공동\s*투자',n['title'])]
        preferred=[n for n in notices if events.get(n['url'])=='우선협상대상자'
                   and _event(n)['type']=='우선협상대상자']
        if len(originals)==1 and len(preferred)==1 and _identity(originals[0])==_identity(preferred[0]):
            candidates.append({'program_id':p['id'],'public_run':public_run,
                               'notices':[originals[0],preferred[0]]})
    if len(candidates)!=1:
        raise ValueError('Exactly one existing unconfirmed same-business preferred stage required')
    validate_target(candidates[0])
    return candidates[0]


def _raw(value, limit):
    if not isinstance(value,str) or len(value)>((limit+2)//3)*4:
        raise ValueError('Raw proof size/type invalid')
    raw=base64.b64decode(value,validate=True)
    if not raw or len(raw)>limit or base64.b64encode(raw).decode('ascii')!=value:
        raise ValueError('Raw proof encoding invalid')
    return raw


def validate_target(target):
    notices=target.get('notices')
    if not isinstance(notices,list) or len(notices)!=2:
        raise ValueError('Exactly two automatic source notices required')
    for n in notices:
        ident=re.fullmatch(r'0041:([1-9][0-9]*)',n.get('source_id',''))
        if (not ident or _protected(n) or re.search(r'비공개|로그인이필요|접근권한이없',re.sub(r'\s+','',n.get('body','')))
                or n.get('institution_id','koreapost')!='koreapost'
                or n.get('url')!=f'{k.BASE}/board.es?mid=a10510000000&bid=0041&act=view&list_no={ident[1]}'
                or n.get('sha256')!=k._fingerprint(n)):
            raise ValueError('Invalid same-business source identity before HTTP')
        _safe_url(n['url'])
        if n.get('detail_proof') is not None:
            raw=_raw(n['detail_proof']['raw_base64'],MAX_BODY_BYTES)
            if n['detail_proof']!=detail_proof(n,raw):raise ValueError('Invalid cached body proof before HTTP')
    a,b=notices
    if (_identity(a)!=_identity(b) or _event(a)['type']!='모집 공고'
            or _event(b)['type']!='우선협상대상자' or not re.search(r'국내\s*공동\s*투자',a['title'])
            or not a['date']<b['date'] or a['date'][:4]!=b['date'][:4] or b.get('attachments')):
        raise ValueError('Ambiguous same-business recruitment/preferred pair')
    url=_download_url(a['attachments'][0],a['source_id'])
    proofs=a.get('attachment_proofs',{})
    if proofs:
        if set(proofs)!={url}:raise ValueError('Invalid cached first PDF set')
        proof=proofs[url];raw=_raw(proof['raw_base64'],MAX_FILE_BYTES)
        if proof!=attachment_proof(a,raw):raise ValueError('Invalid cached PDF before HTTP')
    return notices


def lookup(conn, source):
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    conn.execute("SET LOCAL statement_timeout='120s'")
    public=conn.execute("SELECT run_id,data->'programs' FROM lp_program_private.program_state WHERE id=1").fetchone()
    target=plan(source,public[1],public[0])
    notices=validate_target(target);urls=[n['url'] for n in notices]
    rows=conn.execute('SELECT document FROM lp_program_private.documents WHERE source_url=ANY(%s) '
                      'ORDER BY source_url,content_hash LIMIT 101',(urls,)).fetchall()
    docs=[r[0] for r in rows]
    if len(docs)>100 or len(json.dumps(docs,ensure_ascii=False).encode())>MAX_INPUT_BYTES:
        raise ValueError('Retained source version lookup limit exceeded')
    for stored in docs:
        n=next((n for n in notices if n['url']==stored.get('url')),None)
        if not n or _protected(stored):raise ValueError('Foreign/protected retained source')
        if any(stored.get(key)!=n[key] for key in ('url','title','date','body','sha256','attachments')):
            raise ValueError('Conflicting retained source body before HTTP')
        for url,digest in stored.get('attachment_hashes',{}).items():
            if url in n.get('attachment_hashes',{}) and digest!=n['attachment_hashes'][url]:
                raise ValueError('Conflicting retained source file before HTTP')
        if 'detail_proof' in stored:
            proof=stored['detail_proof'];raw=_raw(proof['raw_base64'],MAX_BODY_BYTES)
            if proof!=detail_proof(n,raw):raise ValueError('Invalid retained body proof')
            if 'detail_proof' in n and n['detail_proof']!=proof:raise ValueError('Conflicting raw body versions')
            n['detail_proof']=copy.deepcopy(proof)
        old=stored.get('discovery_provenance',{})
        if 'detail_response_base64' in old:
            raw=_raw(old['detail_response_base64'],MAX_BODY_BYTES)
            if sha(raw)!=old.get('detail_response_sha256'):raise ValueError('Retained historical raw body hash mismatch')
            n.setdefault('detail_proof',detail_proof(n,raw))
        if n['attachments']:
            url=n['attachments'][0]
            proof=stored.get('attachment_proofs',{}).get(url)
            encoded=proof.get('raw_base64') if proof else stored.get('attachment_bytes',{}).get(url)
            if encoded is not None:
                raw=_raw(encoded,MAX_FILE_BYTES);verified=attachment_proof(n,raw)
                if proof is not None and proof!=verified:raise ValueError('Invalid retained PDF proof')
                n.setdefault('attachment_proofs',{})[url]=verified
    validate_target(target)
    return {'kind':KIND,'stage':'lookup','success':True,'target':target,
            'versions_examined':len(docs),'official_http_requests':0,'database_writes':0,'published':False,
            'pe_approval':False,'selected_gp_approval':False}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('KoreaPost capture redirect rejected')


def capture(retained, fetch=None):
    if (retained.get('kind')!=KIND or retained.get('stage')!='lookup' or retained.get('success') is not True
            or retained.get('published') is not False or retained.get('database_writes')!=0
            or retained.get('pe_approval') is not False or retained.get('selected_gp_approval') is not False):
        raise ValueError('Successful bounded retained-source lookup required')
    result=copy.deepcopy(retained);result.update(stage='capture',success=False,
        checked_at=datetime.now(timezone.utc).isoformat(),responses=[],detail_requests=0,
        attachment_requests=0,transport_attempts=0,errors=[])
    opener=build_opener(NoRedirect())
    def get(url,limit):
        if fetch is not None:return fetch(url,limit)
        result['transport_attempts']+=1
        request=Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':k.LIST_URL,'Accept-Encoding':'identity'})
        try:
            with opener.open(request,timeout=25) as response:
                if response.geturl()!=url:raise ValueError('KoreaPost response URL changed')
                return {'raw':response.read(limit+1),'status':response.status}
        except HTTPError as error:
            if error.geturl()!=url:raise ValueError('KoreaPost error response URL changed')
            return {'raw':error.read(limit+1),'status':error.code}
    def request(url,limit,phase):
        result[phase+'_requests']+=1
        result['official_http_requests']=result['detail_requests']+result['attachment_requests']
        value=get(url,limit)
        if isinstance(value,bytes):raw,status=value,200
        elif isinstance(value,dict) and set(value)=={'raw','status'}:raw,status=value['raw'],value['status']
        else:raise ValueError('Invalid KoreaPost response type')
        if not isinstance(raw,bytes) or type(status) is not int:raise ValueError('Invalid KoreaPost response fields')
        kept=raw[:limit]
        result['responses'].append({'url':url,'phase':phase,'raw_base64':base64.b64encode(kept).decode('ascii'),
                                    'sha256':sha(kept),'byte_length':len(kept),'truncated':len(raw)>limit,'http_status':status})
        if not raw or len(raw)>limit:raise ValueError('KoreaPost response size bound')
        if status!=200:raise ValueError('KoreaPost public HTTP error retained')
        return raw
    try:
        validate_target(result['target'])
        for n in result['target']['notices']:
            if not n.get('detail_proof'):
                n['detail_proof']=detail_proof(n,request(n['url'],MAX_BODY_BYTES,'detail'))
        n=result['target']['notices'][0];url=n['attachments'][0]
        if not n.get('attachment_proofs',{}).get(url):
            n.setdefault('attachment_proofs',{})[url]=attachment_proof(n,request(url,MAX_FILE_BYTES,'attachment'))
        try:
            from .koreapost_coinvestment_preferred import extract_preferred
        except ImportError:
            from koreapost_coinvestment_preferred import extract_preferred
        extract_preferred(*result['target']['notices'],checked_at=result['checked_at'])
        result['success']=True
    except Exception as error:
        result['errors'].append({'type':type(error).__name__,'code':'bounded_preferred_capture_or_replay_failed'})
    return result


def reuse(source, result):
    if (result.get('kind')!=KIND or result.get('stage')!='capture' or result.get('success') is not True
            or result.get('published') is not False or result.get('database_writes')!=0
            or result.get('pe_approval') is not False or result.get('selected_gp_approval') is not False):
        raise ValueError('Successful no-publication raw capture required')
    notices=validate_target(result['target'])
    body_count,file_count=result.get('detail_requests'),result.get('attachment_requests')
    if (type(body_count) is not int or not 0<=body_count<=2 or type(file_count) is not int or not 0<=file_count<=1
            or result.get('official_http_requests')!=body_count+file_count
            or type(result.get('transport_attempts')) is not int or not 0<=result['transport_attempts']<=body_count+file_count
            or not isinstance(result.get('responses'),list) or len(result['responses'])!=body_count+file_count):
        raise ValueError('Capture request/response counts differ')
    expected={n['url']:('detail',n['detail_proof']) for n in notices}
    a=notices[0];url=a['attachments'][0];expected[url]=('attachment',a['attachment_proofs'][url])
    seen=set();counts={'detail':0,'attachment':0}
    for response in result['responses']:
        if not isinstance(response,dict) or set(response)!={'url','phase','raw_base64','sha256','byte_length','truncated','http_status'}:
            raise ValueError('Capture response fields differ')
        url=response['url'];phase,proof=expected.get(url,(None,None))
        if (phase not in counts or url in seen or phase!=response['phase'] or response['truncated'] is not False
                or response['http_status']!=200 or any(response[key]!=proof[key] for key in ('raw_base64','sha256','byte_length'))):
            raise ValueError('Capture response differs from raw source proof')
        seen.add(url);counts[phase]+=1
    if counts!={'detail':body_count,'attachment':file_count}:
        raise ValueError('Capture phase counts differ')
    upgraded=copy.deepcopy(source);by_id={n['source_id']:n for n in upgraded['notices']}
    for verified in result['target']['notices']:
        old=by_id.get(verified['source_id'])
        if old is None:raise ValueError('Captured source not present in collection')
        for field in ('source_id','url','title','date','body','sha256','attachments','attachment_hashes','attachment_texts'):
            if old.get(field)!=verified.get(field):raise ValueError('Source identity/terms changed during capture')
        old['detail_proof']=copy.deepcopy(verified['detail_proof'])
        if 'attachment_proofs' in verified:old['attachment_proofs']=copy.deepcopy(verified['attachment_proofs'])
    try:
        from .koreapost_coinvestment_preferred import extract_preferred
    except ImportError:
        from koreapost_coinvestment_preferred import extract_preferred
    a,b=[by_id[n['source_id']] for n in result['target']['notices']]
    roster=extract_preferred(a,b,checked_at=result['checked_at'])
    return upgraded,{'program_id':result['target']['program_id'],'baseline_public_run':result['target']['public_run'],
                     'source_url':roster['source_url'],'preferred_count':len(roster['preferred_gps']),
                     'official_http_requests':0,'selected_gp_additions':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=('lookup','capture'),required=True)
    p.add_argument('--collection',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--retained',type=Path);args=p.parse_args()
    def load(path):
        if path.stat().st_size>MAX_INPUT_BYTES:raise ValueError('KoreaPost input size bound')
        return json.loads(path.read_text())
    if args.mode=='lookup':
        import psycopg
        try:
            with psycopg.connect(os.environ['SUPABASE_DB_URL'],connect_timeout=20,prepare_threshold=None,
                                 application_name='koreapost-preferred-raw-lookup') as conn:
                result=lookup(conn,load(args.collection)['sources']['koreapost'])
        except Exception as error:
            result={'kind':KIND,'stage':'lookup','success':False,'official_http_requests':0,
                    'database_writes':0,'published':False,'error_type':type(error).__name__}
    else:
        if not args.retained:p.error('--retained required')
        result=capture(load(args.retained))
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False))
    print(json.dumps({k:result[k] for k in ('kind','stage','success','official_http_requests','database_writes','published')}))
    if not result['success']:raise SystemExit('KoreaPost proof held; retained evidence available')


if __name__=='__main__':main()
