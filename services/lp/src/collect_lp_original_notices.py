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


def original_text(node):
    if node.tag in {'script','style'}:return ''
    if node.tag=='img':
        alt=node.attrs.get('alt','')
        return alt if len(alt)>=30 else ''
    return ' '.join(original_text(child) if isinstance(child,Node) else child for child in node.children)


def parse_original(html,url):
    if '</html>' not in html.lower():raise ValueError('incomplete original HTML')
    root=Document(html).root
    title_nodes=[n for n in root.nodes() if classes(n)&{'board_tit','view_tit','view-title','subject','bbs_tit','title_view'}]
    title=next((n.clean() for n in title_nodes if n.clean()),None)
    if not title:
        subject=next((n for n in root.nodes() if 'subject-wrap' in classes(n)),None)
        if subject:title=next((n.clean() for n in subject.nodes('strong')),None)
    # Labelled metadata is valid only in the notice detail, not page navigation.
    date_value=None
    # Ministry notices use a definition-list header, not table cells.
    board=next((n for n in root.nodes() if 'board_view_wrap' in classes(n)),None)
    if board:
        for dl in board.nodes('dl'):
            cells=[n for n in dl.children if isinstance(n,Node) and n.tag in {'dt','dd'}]
            for i,c in enumerate(cells[:-1]):
                if c.tag=='dt' and cells[i+1].tag=='dd':
                    if c.clean() in {'제목','공고명'} and not title:title=cells[i+1].clean()
                    if c.clean() in {'등록일','작성일','게시일','공고일'}:date_value=valid_date(cells[i+1].clean())
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
    bodies=[n for n in root.nodes() if n.attrs.get('id') in {'write','bbsCn','boardContent','boardContents'} or classes(n)&{'b_content','view_cont','view_con','board_view_con','bbs_view_cont','board-view-content','td_cont','detail-body'}]
    if not bodies:
        board=next((n for n in root.nodes() if 'board-view-table' in classes(n)),None)
        if board:bodies=list(board.nodes('tbody'))
    if not title or not bodies:raise ValueError('recognized original detail title/body not found')
    body=re.sub(r'\s+',' ',max((original_text(n) for n in bodies),key=len)).replace('\x00',' ').strip()
    if len(body)<30:raise ValueError('original notice body is empty or too short')
    attachments=[]
    for a in root.nodes('a'):
        href=a.attrs.get('href','');name=a.clean()
        if href and re.search(r'\.(pdf|hwp|hwpx)$',name,re.I) and not re.search(r'양식|서식|제출서류|제안서',name):
            if not href.lower().startswith(('javascript:','#')):
                attachments.append({'name':name,'url':urljoin(url,href)})
    for li in root.nodes('li'):
        label=next((n.clean() for n in li.nodes('em')), '')
        if re.search(r'\.(?:pdf|hwpx?)(?:\(|$)',label,re.I) and not re.search(r'양식|서식|제출서류|제안서',label):
            for a in li.nodes('a'):
                href=a.attrs.get('href','')
                if 'download' in href.lower():attachments.append({'name':re.sub(r'\([^)]*KB\)$','',label).strip(),'url':urljoin(url,href)})
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


def validate_identity(notice,original,aliases,*,candidate_only=False):
    left,right=notice['title'],original['title']
    source_years,original_years=years(left),years(right)
    if not source_years and notice.get('date'):source_years={notice['date'][:4]}
    if not original_years and original.get('date'):original_years={original['date'][:4]}
    if (source_years and original_years and source_years!=original_years) or (not candidate_only and (not source_years or not original_years)):
        raise ValueError('original notice year is missing or differs from republication')
    # Distinguish repeated annual leagues and stages rather than only their year.
    for pattern in (r'\d+\s*(?:차|호)',r'상반기|하반기',r'최종|접수현황|선정결과|서류심사|재공고|변경|정정|수정|취소',r'일반매칭|자율제안|대형|중형|소형|루키|국민참여형|간접투자분야|프로젝트'):
        if set(re.findall(pattern,left))!=set(re.findall(pattern,right)):
            raise ValueError('original notice business round or stage differs')
    institution=notice['institution_id']
    names=list(aliases.get(institution,[]))
    if institution=='kamco':names.append('캠코')
    def identity_key(value):
        for name in names:value=value.replace(name,'')
        value=re.sub(r'^\s*[【\[](?:사업공고|선정공고|공고|입찰공고)[】\]]','',value)
        value=re.sub(r"[’'‘]?(?:20)?\d{2}(?:년도|년)",'',value)
        return title_key(value)
    a,b=identity_key(left),identity_key(right)
    if min(len(a),len(b))<10 or not re.search(r'펀드|pe|vc|사모',a):
        raise ValueError('Original business title is not distinctive enough')
    source_scope=notice.get('source_scope')
    if source_scope in ('mixed_pe_blind','pe_blind') and re.search(r'(?<![A-Za-z])VC(?![A-Za-z])',right,re.I) and not re.search(r'(?<![A-Za-z])PEF?(?![A-Za-z])',right,re.I):
        raise ValueError('VC-only title differs from the PE offering')
    if SequenceMatcher(None,a,b).ratio()<0.82:
        raise ValueError('original title does not identify the same business')
    native=original.get('discovery_provenance',{}).get('kind') in {'existing_official_collection','kgrowth_title_search'}
    if not candidate_only and not native and (not names or not any(name in (right+' '+original['body'][:500]) for name in names)):
        raise ValueError('original content does not identify the expected institution')
    other={i for i,values in aliases.items() if i!=institution and any(n in right for n in values)}
    if other and not any(n in right for n in names):
        raise ValueError('original title identifies another institution')


def original_body_hash(original):
    return hashlib.sha256(json.dumps([original['title'], original.get('date'), original['body']], ensure_ascii=False).encode()).hexdigest()


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
    discovery=original.get('discovery_provenance',{})
    if url not in observed or discovery.get('kind') in {'existing_official_collection','kgrowth_title_search'}:
        try:
            from .discover_lp_original_boards import validate_listing_provenance, validate_native_provenance
        except ImportError:
            from discover_lp_original_boards import validate_listing_provenance, validate_native_provenance
        if discovery.get('kind')=='official_board':validate_listing_provenance(original,institution)
        elif discovery.get('kind')=='existing_official_collection':validate_native_provenance(original,institution)
        elif discovery.get('kind')=='kgrowth_title_search':
            try:from .discover_growth_originals import validate_search_provenance
            except ImportError:from discover_growth_originals import validate_search_provenance
            if institution!='kgrowth':raise ValueError('Growth search proof belongs to another institution')
            validate_search_provenance(original)
        else:raise ValueError('original URL is not an observed association link')
    if original.get('matched_republication_url')!=association_notice.get('url'):
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
    if discovery.get('kind')!='existing_official_collection':
        if original.get('hash_kind')!='semantic_v1' or original_body_hash(original)!=original['sha256']:
            raise ValueError('original body hash does not match title/date/body')
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
                digest=hashlib.sha256(json.dumps([original['title'],original['date'],original['body']],ensure_ascii=False).encode()).hexdigest()
                record={'institution_id':n['institution_id'],'url':url,'title':original['title'],'date':original['date'],'body':original['body'],'sha256':digest,'hash_kind':'semantic_v1','attachment_hashes':hashes,'attachment_texts':texts,'attachments':attachments,'matched_republication_url':n['url'],'checked_at':checked_at,'review_only':True}
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
