"""Discover K-FINCO originals through the API observed on its public notice page.

Only same-date domestic PE blind recruitment is linked; all evidence stays review-only.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import re
import errno
import socket
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.error import HTTPError, URLError
try:
    from .collect_lp_original_notices import fetch_bytes_once as fetch_bytes, safe_host, original_body_hash
    from .collect_shared_lp_notices import Document, valid_date
    from .lp_attachment_text import extract_attachment
    from .lp_regional_transport import fetch_kfinco, kfinco_url
except ImportError:
    from collect_lp_original_notices import fetch_bytes_once as fetch_bytes, safe_host, original_body_hash
    from collect_shared_lp_notices import Document, valid_date
    from lp_attachment_text import extract_attachment
    from lp_regional_transport import fetch_kfinco, kfinco_url

BASE='https://www.kfinco.co.kr'
LIST_URL=BASE+'/api/pr/notice/list?page=1&size=10&searchKeyword='+quote('위탁운용사',safe='')
MAX_JSON=2_000_000

class EvidenceMismatch(ValueError):
    """Reachable source whose business evidence does not qualify."""

def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def code(value):
    if not isinstance(value,str) or not re.fullmatch(r'NT\d{14}',value):raise ValueError('invalid observed notice code')
    return value

def official(url,path):
    p=urlsplit(url)
    if safe_host(url)!='kfinco.co.kr' or p.scheme!='https' or p.path!=path or p.fragment:
        raise ValueError('unexpected K-FINCO official URL')
    return url

def read_json(raw):
    text=raw.decode('utf-8') if isinstance(raw,bytes) else raw
    if not isinstance(text,str) or len(text)>MAX_JSON:raise ValueError('oversized or invalid API response')
    value=json.loads(text)
    if not isinstance(value,dict) or value.get('success') is not True:raise ValueError('official API did not succeed')
    return text,value

def listing(raw):
    text,value=read_json(raw)
    rows=value.get('list');total=value.get('totalCount')
    if not isinstance(rows,list) or len(rows)>10 or type(total) is not int or total<len(rows):raise ValueError('invalid listing schema')
    if any(not isinstance(row,dict) for row in rows):raise ValueError('invalid listing record')
    return text,rows

def key(title):
    value=re.sub(r'\s+','',title).lower().replace('전문건설공제조합','')
    value=value.replace('사모투자','pe').replace('블라인드펀드','').replace('선정계획','선정')
    return re.sub(r'[^0-9a-z가-힣]','',value)

def recruitment(title):
    t=re.sub(r'\s+','',title).lower()
    if re.search(r'결과|현황|서류심사|정정|수정|변경|재공고|취소|연장|해외|프로젝트|벤처|vc|주식',t):return False
    return '국내' in t and bool(re.search(r'pe|사모투자',t)) and bool(re.search(r'위탁운용사선정(?:계획)?공고',t))

def matching(row,notice):
    if not recruitment(row.get('ntTitle','')) or not recruitment(notice.get('title','')):return False
    date=notice.get('date')
    if not isinstance(date,str) or valid_date(date)!=date or row.get('ntDate')!=date:return False
    year=date[:4]
    for title in (row['ntTitle'],notice['title']):
        if set(re.findall(r'(?<!\d)20\d{2}(?!\d)',title))!={year}:return False
    return key(row['ntTitle'])==key(notice['title'])

def attachments(detail):
    result=[]
    rows=detail.get('noticeAttachModelList',[])
    if not isinstance(rows,list):raise ValueError('invalid attachment list')
    for a in rows:
        if not isinstance(a,dict):raise ValueError('invalid attachment metadata')
        name=a.get('filenameOriginal','');saved=a.get('filenameSave','');path=a.get('filepath','')
        if not all(isinstance(v,str) for v in (name,saved,path)):raise ValueError('invalid attachment metadata strings')
        if not re.search(r'\.(?:hwp|hwpx|pdf)$',name,re.I) or re.search(r'양식|서식|제출서류|\.zip$',name,re.I):continue
        if not re.search(r'공고|RFP|제안요청서',name,re.I):continue
        if not re.fullmatch(r'/pds/notice/\d{4}-\d{2}',path) or not re.fullmatch(r'[A-Za-z0-9_-]+\.(?:hwp|hwpx|pdf)',saved,re.I):
            raise ValueError('unsafe observed attachment path')
        if a.get('ntCode')!=detail['ntCode']:raise ValueError('attachment belongs to another notice')
        # Exact makeEncodeUrl formula observed in the official detail page.
        url=BASE+'/util/download?filePath='+quote(path,safe='')+'/'+quote(saved,safe='')+'&downloadName='+quote(name,safe='')
        result.append({'name':name,'url':url})
    return result

def parse_detail(raw,expected_code):
    text,value=read_json(raw);d=value.get('detail')
    if not isinstance(d,dict) or d.get('ntCode')!=code(expected_code):raise ValueError('detail identifier differs from observed list')
    if type(d.get('closed')) is not int or d['closed']!=0:raise EvidenceMismatch('official detail is closed')
    if not isinstance(d.get('ntTitle'),str) or not isinstance(d.get('ntContent'),str):raise ValueError('detail title/body missing')
    body=Document(d['ntContent']).root.clean().replace('\x00',' ')
    compact=re.sub(r'\s+','',body).lower()
    opening=compact.split('선정개요',1)[0]
    if '국내사모투자블라인드펀드' not in opening or not re.search(r'투자부문국내사모투자\(pe\)',compact):
        raise EvidenceMismatch('official body does not explicitly establish domestic PE blind scope')
    if not isinstance(d.get('ntDate'),str) or valid_date(d['ntDate'])!=d['ntDate']:raise ValueError('invalid official publication date')
    return text,d,{'title':d['ntTitle'],'date':d['ntDate'],'body':body,'attachments':attachments(d)}

def validate_api_provenance(original,association_notice):
    if original.get('institution_id')!='kfinco' or association_notice.get('institution_id')!='kfinco':raise ValueError('wrong original institution')
    p=original.get('discovery_provenance',{})
    expected={'kind','listing_url','listing_json','listing_sha256','detail_url','detail_json','detail_sha256','observed_code','observed_title','observed_date'}
    if set(p)!=expected or p['kind']!='kfinco_official_api':raise ValueError('invalid official API proof keys')
    if p['listing_url']!=LIST_URL:raise ValueError('unrecognized official listing request')
    if digest(p['listing_json'])!=p['listing_sha256'] or digest(p['detail_json'])!=p['detail_sha256']:raise ValueError('API receipt fingerprint differs')
    ident=code(p['observed_code'])
    if p['detail_url']!=BASE+'/api/pr/notice/detail/'+ident or original.get('url')!=BASE+'/pr/notice/detail/'+ident:
        raise ValueError('unobserved original URL or API endpoint')
    official(p['detail_url'],'/api/pr/notice/detail/'+ident)
    _,rows=listing(p['listing_json'])
    candidates=[r for r in rows if matching(r,association_notice)]
    if len(candidates)!=1:raise ValueError('ambiguous or missing same-date official business')
    row=candidates[0]
    if row.get('ntCode')!=ident or type(row.get('closed')) is not int or row['closed']!=0:raise ValueError('official listing is closed or differs')
    _,d,parsed=parse_detail(p['detail_json'],ident)
    if not matching(d,association_notice):raise ValueError('official detail is a different dated business')
    if row.get('ntTitle')!=d['ntTitle'] or row.get('ntDate')!=d['ntDate'] or p['observed_title']!=d['ntTitle'] or p['observed_date']!=d['ntDate']:
        raise ValueError('listing/detail fields differ')
    for field in ('title','date','body','attachments'):
        if original.get(field)!=parsed[field]:raise ValueError('original differs from API content: '+field)
    if original.get('sha256')!=original_body_hash(original) or original.get('hash_kind')!='semantic_v1':raise ValueError('original semantic hash differs')
    if original.get('matched_republication_url')!=association_notice.get('url') or original.get('review_only') is not True:raise ValueError('original association/review contract differs')
    urls={a['url'] for a in parsed['attachments']}
    hashes=original.get('attachment_hashes',{});texts=original.get('attachment_texts',{})
    if not isinstance(hashes,dict) or not isinstance(texts,dict):raise ValueError('invalid attachment evidence maps')
    for url,h in hashes.items():
        if url not in urls or not isinstance(h,str) or not re.fullmatch('[0-9a-f]{64}',h):raise ValueError('invalid attachment hash or URL')
    for url,text in texts.items():
        if url not in hashes or not isinstance(text,str) or not text.strip() or '\x00' in text:raise ValueError('invalid attachment text')
    return True


def _transient_fetch_error(error):
    # macOS occasionally fails resolution of an otherwise available K-FINCO
    # host with EAI_NONAME (errno 8). Retry the transport, never source parsing.
    if isinstance(error, HTTPError):
        return error.code == 429 or 500 <= error.code <= 599
    if isinstance(error, URLError):
        return _transient_fetch_error(error.reason)
    if isinstance(error, ssl.SSLError):
        return False
    if isinstance(error, socket.gaierror):
        return error.errno in {socket.EAI_AGAIN, socket.EAI_NONAME, 8}
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    return isinstance(error, OSError) and error.errno in {
        errno.ETIMEDOUT, errno.ECONNRESET, errno.ECONNABORTED,
        errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH,
    }


def _fetch_with_retry(fetch, url, budget):
    # At most three attempts per URL, and four extra attempts shared by the
    # complete discovery run. Failures still reach the ordinary hold path.
    for attempt in range(3):
        try:
            return fetch(url)
        except Exception as error:
            if attempt == 2 or not _transient_fetch_error(error) or budget[0] == 0:
                raise
            budget[0] -= 1
            time.sleep(attempt + 1)

def discover(collection,fetch=fetch_bytes,checked_at=None):
    result=copy.deepcopy(collection);checked_at=checked_at or datetime.now(timezone.utc).isoformat()
    cache=None;attempted=False;linked=0
    retry_budget=[4]
    def request(url):
        return _fetch_with_retry(fetch, url, retry_budget)
    def hold(n,phase,error,url):
        result.setdefault('holds',[]).append({'stage':'kfinco_original','source_id':n.get('source_id'),'phase':phase,'url':url,'error':str(error)})
    for n in result.get('notices',[]):
        if n.get('institution_id')!='kfinco' or n.get('original_notices') or n.get('source_scope') in {'outside','vc_only'}:continue
        phase='listing';request_url=LIST_URL
        try:
            if not attempted:
                attempted=True;cache=listing(request(LIST_URL))
            if cache is None:raise ValueError('previous official listing fetch failed')
            raw,rows=cache;phase='matching'
            candidates=[r for r in rows if matching(r,n)]
            if len(candidates)!=1:raise ValueError('expected one same-date official business; found '+str(len(candidates)))
            row=candidates[0]
            if type(row.get('closed')) is not int or row['closed']!=0:raise ValueError('official public listing marks notice closed')
            ident=code(row.get('ntCode'));request_url=BASE+'/api/pr/notice/detail/'+ident;phase='detail'
            detail_raw,d,parsed=parse_detail(request(request_url),ident)
            phase='validation'
            original={**parsed,'institution_id':'kfinco','url':BASE+'/pr/notice/detail/'+ident,
                'checked_at':checked_at,'matched_republication_url':n['url'],'review_only':True,'hash_kind':'semantic_v1',
                'attachment_hashes':{},'attachment_texts':{}}
            original['sha256']=original_body_hash(original)
            original['discovery_provenance']={'kind':'kfinco_official_api','listing_url':LIST_URL,'listing_json':raw,
                'listing_sha256':digest(raw),'detail_url':request_url,'detail_json':detail_raw,'detail_sha256':digest(detail_raw),
                'observed_code':ident,'observed_title':row['ntTitle'],'observed_date':row['ntDate']}
            validate_api_provenance(original,n)
            for a in original['attachments'][:1]:
                try:
                    data=request(a['url']);original['attachment_hashes'][a['url']]=hashlib.sha256(data).hexdigest()
                    text=extract_attachment(data)['text'].replace('\x00',' ')
                    if not text.strip():raise ValueError('attachment has no decoded text')
                    original['attachment_texts'][a['url']]=text
                except Exception as exc:hold(n,'attachment',exc,a['url'])
            validate_api_provenance(original,n)
            n['original_notices']=[original];linked+=1
        except EvidenceMismatch as exc:hold(n,'validation',exc,request_url)
        except Exception as exc:hold(n,phase,exc,request_url)
    result.setdefault('coverage',{})['kfinco_original']={'listing_requests':int(attempted),'linked':linked,'retry_requests':4-retry_budget[0]}
    return result

def native_tls_fetch(url):
    # Use the OS certificate verifier; never weaken certificate/hostname checks.
    import ssl
    import truststore
    context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if context.verify_mode!=ssl.CERT_REQUIRED or not context.check_hostname:
        raise ValueError('native TLS must verify certificate and hostname')
    kfinco_url(url)
    try:
        return fetch_bytes(url,ssl_context=context)
    except HTTPError as error:
        token=os.environ.get('LP_SOURCE_WORKER_TOKEN','')
        if error.code!=400 or not token or error.geturl()!=url:raise
        body=error.read(4097)
        text=body.decode('utf-8','replace').lower()
        if len(body)>4096 or '400 bad request' not in text or 'contact the administrator' not in text:raise
        # The worker token is sent only to the fixed authenticated Seoul worker.
        # Worker failure becomes a non-retryable hold; native retry budget is unchanged.
        return fetch_kfinco(url,token)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--system-trust',action='store_true');args=p.parse_args()
    collection=json.loads(Path(args.input).read_text())
    if not isinstance(collection,dict) or not isinstance(collection.get('notices'),list):raise ValueError('invalid input collection')
    result=discover(collection,fetch=native_tls_fetch if args.system_trust else fetch_bytes);dest=Path(args.output);temp=dest.with_name(dest.name+'.tmp')
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');os.replace(temp,dest)
    print(json.dumps(result['coverage']['kfinco_original']))

if __name__=='__main__':main()
