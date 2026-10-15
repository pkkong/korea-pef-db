"""Bounded title searches on the official Growth Finance notice board.

Discovery receipts are evidence for review, never permission to publish a business.
"""
from __future__ import annotations
import copy
import hashlib
import re
from http.cookiejar import CookieJar
from urllib.request import build_opener, HTTPCookieProcessor, Request
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
try:
    from .collect_lp_original_notices import (fetch_bytes, safe_host, validate_identity, OfficialRedirect, MAX_BYTES,
        validate_original, original_body_hash, load_aliases)
    from .collect_shared_lp_notices import Document, decode_html, valid_date
    from .lp_attachment_text import extract_attachment
except ImportError:
    from collect_lp_original_notices import (fetch_bytes, safe_host, validate_identity, OfficialRedirect, MAX_BYTES,
        validate_original, original_body_hash, load_aliases)
    from collect_shared_lp_notices import Document, decode_html, valid_date
    from lp_attachment_text import extract_attachment

BASE='https://www.kgrowth.or.kr/'
MAX_QUERIES=8

def derive_query(title):
    quoted=re.search(r'「([^」]+)」',title)
    value=quoted[1] if quoted else title
    value=re.sub(r'^\s*(?:\[[^]]+\]|【[^】]+】)\s*','',value)
    value=re.sub(r'한국성장금융(?:투자운용)?','',value)
    value=re.sub(r'(?<!\d)20\d{2}\s*년(?:도)?','',value).strip()
    value=re.split(r'\d+\s*(?:차|호)|위탁\s*운용사|운용사\s*선정|선정\s*계획',value)[0]
    value=re.sub(r'\s+',' ',value).strip(' 「」[]')
    value=value.rstrip('(').strip()
    if len(re.sub(r'\W','',value))<5 or len(value)>100:
        raise ValueError('business search term is not sufficiently distinctive')
    return value

def search_url(query):
    return BASE+'notice.asp?'+urlencode({'str_type':'1','tab':'1','search_colume':'Title','search_text':query},encoding='cp949')

def official_url(url,route):
    p=urlsplit(url)
    if safe_host(url)!='kgrowth.or.kr' or p.scheme!='https' or p.path!=route or p.fragment:
        raise ValueError('unexpected Growth Finance official route')
    pairs=parse_qsl(p.query,keep_blank_values=True,encoding='cp949')
    if len(dict(pairs))!=len(pairs):raise ValueError('duplicate query keys')
    q=dict(pairs)
    if route in ('/notice.asp','/notice_view.asp'):
        allowed={'str_type','tab','search_colume','search_text','page'}|({'idx'} if route=='/notice_view.asp' else set())
        if set(q)-allowed or q.get('str_type')!='1' or q.get('tab')!='1':raise ValueError('unexpected board query')
        if route=='/notice_view.asp' and not q.get('idx','').isdigit():raise ValueError('invalid notice identifier')
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(pairs,encoding='cp949'),''))

def listing_links(html,url):
    if not isinstance(html,str) or len(html)>2_000_000 or '</html>' not in html.lower():
        raise ValueError('incomplete or oversized Growth Finance listing HTML')
    found={}
    for node in Document(html).root.nodes('a'):
        href=node.attrs.get('href','')
        if not href or 'notice_view.asp' not in href:continue
        try:target=official_url(urljoin(url,href),'/notice_view.asp')
        except ValueError:continue
        if node.clean():found[target]={'url':target,'title':node.clean()}
    return list(found.values())

def stage(title):
    t=re.sub(r'\s','',title).lower()
    for value,pattern in [('correction',r'정정|수정|변경|재공고|취소'),('form',r'faq|질의|서식|양식|제출자료'),('result',r'결과|선정완료'),('review',r'서류심사|접수현황')]:
        if re.search(pattern,t):return value
    return 'recruitment' if re.search(r'선정계획공고|모집공고|선정공고',t) else 'unknown'

def parse_detail(raw,url):
    # Match the actual view_info / veiw_contents DOM used by parse_notice.
    root=Document(decode_html(raw)).root
    info=next((n for n in root.nodes() if 'view_info' in n.attrs.get('class','').split()),None)
    body=next((n for n in root.nodes() if 'veiw_contents' in n.attrs.get('class','').split()),None)
    if info is None or body is None:raise ValueError('recognized Growth Finance detail DOM missing')
    title=next((n.clean() for n in info.nodes() if 'tit' in n.attrs.get('class','').split()),'')
    date=next((valid_date(n.clean()) for n in info.nodes() if 'date' in n.attrs.get('class','').split()),None)
    text=body.clean().replace('\x00',' ')
    if not title or not date or len(text)<30:raise ValueError('incomplete Growth Finance title/date/body')
    attachments=[]
    for node in root.nodes('a'):
        href=node.attrs.get('href','');name=node.clean()
        if 'down_file.asp' not in href or re.search(r'서식|양식|제안서|제출자료|template',name,re.I):continue
        try:target=official_url(urljoin(url,href),'/down_file.asp')
        except ValueError:continue
        if re.search(r'공고|계획|선정|안내|모집|\.pdf|\.hwp',name,re.I):attachments.append({'url':target,'name':name})
    return {'title':title.replace('\x00',' '),'date':date,'body':text,'attachments':attachments}

def validate_search_provenance(original):
    proof=original.get('discovery_provenance',{})
    required={'kind','listing_url','listing_html','listing_sha256','listing_title','query','source_notice'}
    if set(proof)!=required or proof.get('kind')!='kgrowth_title_search' or original.get('institution_id')!='kgrowth':
        raise ValueError('invalid Growth Finance search proof keys')
    url=official_url(proof['listing_url'],'/notice.asp')
    if url!=search_url(proof['query']):raise ValueError('search receipt URL differs from query')
    html=proof['listing_html']
    if hashlib.sha256(html.encode()).hexdigest()!=proof['listing_sha256']:raise ValueError('search listing fingerprint differs')
    target=official_url(original['url'],'/notice_view.asp')
    if not any(n['url']==target and n['title']==proof['listing_title'] for n in listing_links(html,url)):
        raise ValueError('original link not observed in search response')
    if stage(proof['listing_title'])!=stage(original['title']):raise ValueError('listing/detail stages differ')
    validate_identity({'institution_id':'kgrowth','title':proof['listing_title'],'date':original.get('date')},original,load_aliases(),candidate_only=True)
    receipt=proof['source_notice']
    for key in ('url','title','date','body','sha256','attachments','attachment_hashes','attachment_texts'):
        if receipt.get(key)!=original.get(key):raise ValueError('original differs from source receipt: '+key)
    if original_body_hash(original)!=original['sha256']:raise ValueError('original semantic fingerprint differs')
    for a in original.get('attachments',[]):official_url(a['url'],'/down_file.asp')
    return True

def discover(collection,fetch=fetch_bytes,checked_at=None):
    result=copy.deepcopy(collection)
    checked_at=checked_at or datetime.now(timezone.utc).isoformat()
    aliases=load_aliases();cache={};linked=0
    opener=build_opener(OfficialRedirect({'kgrowth.or.kr'}),HTTPCookieProcessor(CookieJar()))
    def get(url,referer=BASE+'notice.asp?str_type=1&tab=1'):
        if fetch is not fetch_bytes:return fetch(url)
        with opener.open(Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':referer}),timeout=20) as response:
            raw=response.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:raise ValueError('official response exceeds size limit')
            return raw
    def hold(n,phase,error,url=None):
        result.setdefault('holds',[]).append({'stage':'growth_search','source_id':n.get('source_id'),'phase':phase,'url':url or n.get('url'),'error':str(error)})
    for n in result.get('notices',[]):
        if n.get('institution_id')!='kgrowth' or n.get('original_notices') or n.get('source_scope') in {'outside','vc_only'}:continue
        if stage(n['title'])!='recruitment':continue
        phase='matching'
        try:
            query=derive_query(n['title']);url=search_url(query)
            if query not in cache:
                if len(cache)>=MAX_QUERIES:raise ValueError('search query budget exhausted')
                phase='listing'
                cache[query]=None
                html=decode_html(get(url));cache[query]=(html,listing_links(html,url))
            phase='listing'
            if cache[query] is None:raise ValueError('previous query fetch failed')
            phase='matching'
            html,rows=cache[query];candidates=[]
            for row in rows:
                if stage(row['title'])!=stage(n['title']):continue
                tokens=lambda title:set(re.findall(r'(?<![A-Za-z])(?:PEF?|VC)(?![A-Za-z])',title.upper()))
                if tokens(row['title'])!=tokens(n['title']):continue
                try:validate_identity(n,row,aliases,candidate_only=True)
                except ValueError:continue
                candidates.append(row)
            if len(candidates)!=1:raise ValueError('expected exactly one matching recruitment; found '+str(len(candidates)))
            row=candidates[0];target=row['url'];phase='detail'
            original={**parse_detail(get(target,url),target),'institution_id':'kgrowth','url':target,
                      'checked_at':checked_at,'matched_republication_url':n['url'],'hash_kind':'semantic_v1','review_only':True,
                      'attachment_hashes':{},'attachment_texts':{}}
            phase='validation'
            if stage(original['title'])!=stage(n['title']):raise ValueError('detail is not the same recruitment stage')
            original['sha256']=original_body_hash(original)
            for a in original['attachments'][:1]:
                try:
                    data=get(a['url'],target)
                    text=extract_attachment(data)['text'].replace('\x00',' ')
                    if not text.strip():raise ValueError('attachment has no decoded text')
                    original['attachment_hashes'][a['url']]=hashlib.sha256(data).hexdigest()
                    original['attachment_texts'][a['url']]=text
                except Exception as exc:hold(n,'attachment',exc,a['url'])
            receipt=copy.deepcopy(original)
            original['discovery_provenance']={'kind':'kgrowth_title_search','listing_url':url,'listing_html':html,
                'listing_sha256':hashlib.sha256(html.encode()).hexdigest(),'listing_title':row['title'],'query':query,'source_notice':receipt}
            validate_search_provenance(original)
            original=validate_original(original,n,checked_at)
            n['original_notices']=[original];linked+=1
        except Exception as exc:hold(n,phase,exc)
    result.setdefault('coverage',{})['growth_search']={'queries':len(cache),'linked':linked,'max_queries':MAX_QUERIES}
    return result

def main():
    import argparse
    import json
    import os
    from pathlib import Path
    try:from .discover_lp_original_boards import reuse_native_originals
    except ImportError:from discover_lp_original_boards import reuse_native_originals
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True)
    parser.add_argument('--native-input',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    collection=json.loads(Path(args.input).read_text())
    native=json.loads(Path(args.native_input).read_text())
    if not isinstance(collection,dict) or not isinstance(collection.get('notices'),list) or not isinstance(native,dict) or not isinstance(native.get('notices'),list):
        raise ValueError('invalid input collection schema')
    checked_at=datetime.now(timezone.utc).isoformat()
    notices=[{**n,'institution_id':'kgrowth'} for n in native['notices']]
    report=discover(reuse_native_originals(collection,notices,checked_at),checked_at=checked_at)
    destination=Path(args.output)
    temporary=destination.with_name(destination.name+'.tmp')
    temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    os.replace(temporary,destination)
    print(json.dumps(report['coverage']['growth_search'],ensure_ascii=False))

if __name__=='__main__':main()
