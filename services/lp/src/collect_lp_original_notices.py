#!/usr/bin/env python3
"""Trace observed association links to the same institution's original notice.

No search, listing crawl, notice registry, inferred dates, or publication approval.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

try:
    from .collect_shared_lp_notices import Document, Node, decode_html, valid_date, load_aliases
    from .lp_attachment_text import extract_attachment
except ImportError:
    from collect_shared_lp_notices import Document, Node, decode_html, valid_date, load_aliases
    from lp_attachment_text import extract_attachment

ROOT=Path(__file__).resolve().parents[3]
MAX_BYTES=12*1024*1024


def safe_host(url):
    if not isinstance(url,str) or not url:
        raise ValueError('official URL must be a nonempty string')
    p=urlsplit(url)
    if p.scheme not in {'https','http'} or not p.hostname or p.username or p.password or p.port not in {None,80,443}:
        raise ValueError('unsafe official source URL')
    # Only literal official config hosts are accepted; www is a common alias.
    return p.hostname.lower().removeprefix('www.')


def validate_url(url, allowed):
    if safe_host(url) not in allowed:
        raise ValueError('URL host does not match this institution official channel')


class OfficialRedirect(HTTPRedirectHandler):
    def __init__(self,allowed):
        self.allowed=allowed
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        validate_url(newurl,self.allowed)
        if urlsplit(req.full_url).scheme=='https' and urlsplit(newurl).scheme!='https':
            raise ValueError('HTTPS downgrade redirect rejected')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch_bytes(url,referer=None):
    allowed={safe_host(url)}
    headers={'User-Agent':'Mozilla/5.0 (LP original notice collector)','Accept-Encoding':'identity','Connection':'close'}
    if referer:headers['Referer']=referer
    with build_opener(OfficialRedirect(allowed)).open(Request(url,headers=headers),timeout=20) as r:
        data=r.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise ValueError('original response exceeds size limit')
        return data


def load_channels(root=ROOT):
    channels={}
    for path in sorted((root/'data').glob('lp_blind_contest_screening_*.json')):
        for row in json.loads(path.read_text()).get('institutions',[]):
            url=row.get('official_listing_url')
            if url:
                host=safe_host(url)
                # A repost channel is not an issuer's own original website.
                if host not in {'kofia.or.kr','kvca.or.kr','vcs.go.kr'}:
                    channels.setdefault(row['institution_id'],set()).add(host)
    return channels


def classes(node):
    return set(node.attrs.get('class','').split())


def parse_original(html,url):
    if '</html>' not in html.lower():raise ValueError('incomplete original HTML')
    root=Document(html).root
    title_nodes=[n for n in root.nodes() if classes(n)&{'board_tit','view_tit','view-title','subject','bbs_tit','title_view'}]
    title=next((n.clean() for n in title_nodes if n.clean()),None)
    # Labelled metadata is valid only in the notice detail, not page navigation.
    date_value=None
    for row in root.nodes('tr'):
        cells=[c for c in row.children if isinstance(c,Node) and c.tag in {'th','td'}]
        for i,c in enumerate(cells[:-1]):
            if c.tag=='th' and cells[i+1].tag=='td':
                if c.clean() in {'제목','공고명'} and not title:title=cells[i+1].clean()
                if c.clean() in {'등록일','작성일','게시일','공고일'}:
                    date_value=valid_date(cells[i+1].clean())
    if date_value is None:
        for n in root.nodes():
            if classes(n)&{'b_div','view_date','board_date','date'}:
                value=n.clean()
                if re.match(r'^(등록일|작성일|게시일|공고일)\s*[:：]?',value):
                    date_value=valid_date(value)
                    if date_value:break
    bodies=[n for n in root.nodes() if n.attrs.get('id') in {'write','bbsCn','boardContent','boardContents'} or classes(n)&{'b_content','view_cont','view_con','board_view_con','bbs_view_cont','board-view-content'}]
    if not title or not bodies:raise ValueError('recognized original detail title/body not found')
    body=max((n.clean() for n in bodies),key=len).replace('\x00',' ')
    if len(body)<30:raise ValueError('original notice body is empty or too short')
    attachments=[]
    for a in root.nodes('a'):
        href=a.attrs.get('href','');name=a.clean()
        if href and re.search(r'\.(pdf|hwp|hwpx)$',name,re.I) and not re.search(r'양식|서식|제출서류|제안서',name):
            if not href.lower().startswith(('javascript:','#')):
                attachments.append({'name':name,'url':urljoin(url,href)})
    dynamic=any(n.attrs.get('data-ax5uploader') for n in root.nodes())
    return {'title':title.replace('\x00',' '),'date':date_value,'body':body,'attachments':attachments,'dynamic_attachments':dynamic}


def years(title):
    values=set(re.findall(r'(?<!\d)(20\d{2})(?:년|년도|\b)',title))
    values.update('20'+n for n in re.findall(r"[’'‘](\d{2})\s*년",title))
    return values


def title_key(title):
    title=re.sub(r"[’'‘](\d{2})\s*년",lambda m:'20'+m[1]+'년',title)
    title=re.sub(r'\[(?:재)?공고[^\]]*\]','',title)
    return re.sub(r'[^0-9a-z가-힣]','',title.lower())


def validate_identity(notice,original,aliases):
    left,right=notice['title'],original['title']
    source_years,original_years=years(left),years(right)
    if not source_years or source_years!=original_years:
        raise ValueError('original notice year is missing or differs from republication')
    # Distinguish repeated annual leagues and stages rather than only their year.
    for pattern in (r'\d+\s*(?:차|호)',r'상반기|하반기',r'최종|접수현황|선정결과|서류심사|재공고|변경|정정|수정|취소'):
        if set(re.findall(pattern,left))!=set(re.findall(pattern,right)):
            raise ValueError('original notice business round or stage differs')
    a,b=title_key(left),title_key(right)
    if SequenceMatcher(None,a,b).ratio()<0.82:
        raise ValueError('original title does not identify the same business')
    institution=notice['institution_id']
    names=aliases.get(institution,[])
    if not names or not any(name in (right+' '+original['body'][:500]) for name in names):
        raise ValueError('original content does not identify the expected institution')
    other={i for i,values in aliases.items() if i!=institution and any(n in right for n in values)}
    if other and not any(n in right for n in names):
        raise ValueError('original title identifies another institution')


def validate_original(original, association_notice, checked_at, *, channels=None, aliases=None):
    """Return a defensive copy of validated evidence; raise ValueError on mismatch."""
    channels=load_channels() if channels is None else channels
    aliases=load_aliases() if aliases is None else aliases
    institution=association_notice.get('institution_id')
    if original.get('institution_id')!=institution:
        raise ValueError('original institution differs from association notice')
    url=original.get('url','')
    validate_url(url,channels.get(institution,set()))
    observed={link.get('url') for link in association_notice.get('source_provenance',{}).get('original_links',[]) if isinstance(link,dict)}
    if url not in observed or original.get('matched_republication_url')!=association_notice.get('url'):
        raise ValueError('original URL is not an observed association link')
    for field in ('title','body','checked_at'):
        if not isinstance(original.get(field),str) or not original[field].strip() or '\x00' in original[field]:
            raise ValueError('original '+field+' is invalid')
    try:
        observed_at=datetime.fromisoformat(original['checked_at'].replace('Z','+00:00'))
        limit=datetime.fromisoformat(checked_at.replace('Z','+00:00'))
        if observed_at.tzinfo is None:observed_at=observed_at.replace(tzinfo=timezone.utc)
        if limit.tzinfo is None:limit=limit.replace(tzinfo=timezone.utc)
        if observed_at>limit:raise ValueError('original checked_at is in the future')
    except (TypeError,ValueError) as exc:raise ValueError('invalid original observation time') from exc
    published=original.get('date')
    if published is not None:
        if not isinstance(published,str) or valid_date(published)!=published:
            raise ValueError('invalid original publication date')
        if published>observed_at.date().isoformat():raise ValueError('original publication date is in the future')
    if not isinstance(original.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',original['sha256']):
        raise ValueError('invalid original body hash')
    validate_identity(association_notice,original,aliases)
    attachments=original.get('attachments',[])
    if not isinstance(attachments,list):raise ValueError('invalid original attachments')
    urls=set()
    for attachment in attachments:
        if not isinstance(attachment,dict):raise ValueError('invalid original attachment record')
        validate_url(attachment.get('url',''),channels.get(institution,set()))
        if not isinstance(attachment.get('name'),str) or not attachment['name'].strip():raise ValueError('attachment name missing')
        urls.add(attachment['url'])
    hashes=original.get('attachment_hashes',{})
    texts=original.get('attachment_texts',{})
    if not isinstance(hashes,dict) or not isinstance(texts,dict):raise ValueError('invalid attachment evidence maps')
    for attachment_url,digest in hashes.items():
        if attachment_url not in urls or not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):
            raise ValueError('unlinked or invalid attachment hash')
    for attachment_url,text in texts.items():
        if attachment_url not in hashes or not isinstance(text,str) or not text.strip() or '\x00' in text:
            raise ValueError('unlinked or invalid attachment text')
    return copy.deepcopy(original)


def enrich(collection,fetch=fetch_bytes,*,channels=None,aliases=None,checked_at=None):
    result=copy.deepcopy(collection)
    channels=load_channels() if channels is None else channels
    aliases=load_aliases() if aliases is None else aliases
    checked_at=checked_at or datetime.now(timezone.utc).isoformat()
    holds=result.setdefault('holds',[])
    stats={'eligible_notices':0,'attempted':0,'matched':0,'missing_links':0,'skipped':0,'holds':0}
    def hold(notice,reason,url=None,**extra):
        holds.append({'stage':'original','source_id':notice.get('source_id'),'institution_id':notice.get('institution_id'),'url':url or notice.get('url'),'error':reason,**extra})
        stats['holds']+=1
    for n in result.get('notices',[]):
        if n.get('source_scope') in {'outside','vc_only'}:
            stats['skipped']+=1
            continue
        stats['eligible_notices']+=1
        allowed=channels.get(n.get('institution_id'),set())
        links=n.get('source_provenance',{}).get('original_links',[])
        candidates=[]
        for link in links:
            url=link.get('url','') if isinstance(link,dict) else ''
            if not url or url in candidates:continue
            try:validate_url(url,allowed)
            except ValueError as exc:
                hold(n,str(exc),url)
                continue
            candidates.append(url)
        if not candidates:
            stats['missing_links']+=1
            hold(n,'no observed link to this institution official original notice')
            continue
        originals=n.setdefault('original_notices',[])
        for url in candidates[:2]:
            stats['attempted']+=1
            try:
                raw=fetch(url,n.get('url'))
                if not isinstance(raw,bytes) or len(raw)>MAX_BYTES:raise ValueError('invalid or oversized original response')
                original=parse_original(decode_html(raw),url)
                validate_identity(n,original,aliases)
                hashes,texts={},{}
                attachments=[]
                for attachment in original['attachments']:
                    try:validate_url(attachment['url'],allowed)
                    except ValueError as exc:
                        hold(n,str(exc),attachment['url'],phase='attachment')
                        continue
                    if attachment not in attachments:attachments.append(attachment)
                for attachment in attachments[:1]:
                    try:
                        data=fetch(attachment['url'],url)
                        if len(data)>MAX_BYTES:raise ValueError('original attachment exceeds size limit')
                        hashes[attachment['url']]=hashlib.sha256(data).hexdigest()
                        texts[attachment['url']]=extract_attachment(data)['text'].replace('\x00',' ')
                    except Exception as exc:hold(n,str(exc),attachment['url'],phase='attachment')
                if original['dynamic_attachments'] and not attachments:
                    hold(n,'original attachment links require unsupported dynamic listing',url,phase='attachment_discovery')
                record={'institution_id':n['institution_id'],'url':url,'title':original['title'],'date':original['date'],'body':original['body'],'sha256':hashlib.sha256(raw).hexdigest(),'attachment_hashes':hashes,'attachment_texts':texts,'attachments':attachments,'matched_republication_url':n['url'],'checked_at':checked_at,'review_only':True}
                record=validate_original(record,n,checked_at,channels=channels,aliases=aliases)
                # Upsert only a successful observation; failed refreshes preserve prior evidence.
                originals[:]=[old for old in originals if old.get('url')!=url]+[record]
                stats['matched']+=1
            except Exception as exc:hold(n,str(exc),url)
    result.setdefault('coverage',{})['originals']=stats
    result['originals_checked_at']=checked_at
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=enrich(json.loads(args.input.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['coverage']['originals'],ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
