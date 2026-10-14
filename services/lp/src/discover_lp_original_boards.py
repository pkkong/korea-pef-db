"""Find same-business originals from observed official listing controls.

Board configuration contains routes/search fields, never chosen notice IDs.
Listing evidence is retained and independently reparsed by the publisher.
"""
import argparse
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit, unquote

try:
    from .collect_shared_lp_notices import Document, decode_html
    from .collect_lp_original_notices import (fetch_bytes, load_aliases, load_channels,
        parse_original, safe_host, validate_url, validate_identity, validate_original, original_body_hash)
    from .lp_attachment_text import extract_attachment
except ImportError:
    from collect_shared_lp_notices import Document, decode_html
    from collect_lp_original_notices import (fetch_bytes, load_aliases, load_channels,
        parse_original, safe_host, validate_url, validate_identity, validate_original, original_body_hash)
    from lp_attachment_text import extract_attachment

ROOT=Path(__file__).resolve().parents[3]
MAX_LISTING_CHARS=2_000_000
NATIVE={'kgrowth':('https://www.kgrowth.or.kr/notice.asp?str_type=1&tab=1','/notice_view.asp','idx')}


def channels():
    return {row['institution_id']:row for row in json.loads((ROOT/'data/lp_original_board_channels.json').read_text())['channels']}


def page_url(config,page):
    p=urlsplit(config['listing_url']);q=parse_qs(p.query)
    q.update({k:[v] for k,v in config['search_params'].items()})
    q[config['page_param']]=[str(page)]
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q,doseq=True),''))


def listing_links(html,url,config):
    if len(html)>MAX_LISTING_CHARS or '</html>' not in html.lower():
        raise ValueError('Incomplete or oversized official listing')
    root=Document(html).root
    links={}
    for node in root.nodes():
        title=node.clean()
        if not title or len(title)>240:
            continue
        href=node.attrs.get('href','')
        call=node.attrs.get('onclick','')
        target=None
        if config['adapter']=='kbiz':
            m=re.fullmatch(r"\s*goView\((\d+),\s*['\"]([YN])['\"]\)\s*;?\s*",call)
            if m:
                base=parse_qs(urlsplit(config['listing_url']).query)
                target=urljoin(url,config['detail_path'])+'?'+urlencode({'seq':m[1],'topFixYn':m[2],**{k:v[0] for k,v in base.items()}})
        elif config['adapter']=='kamco':
            m=re.fullmatch(r"\s*goTo\.view\(['\"]list['\"],['\"](\d+)['\"],['\"](\d+)['\"],['\"](\d+)['\"]\);\s*return false;?\s*",call)
            if m:
                base=parse_qs(urlsplit(config['listing_url']).query)
                if base.get('ptIdx')!=[m[2]] or base.get('mId')!=[m[3]]:
                    raise ValueError('Listing points to a different institutional board')
                target=urljoin(url,config['detail_path'])+'?'+urlencode({'bIdx':m[1],'ptIdx':m[2],'mId':m[3]})
        elif node.tag=='a' and href:
            candidate=urljoin(url,href)
            path=urlsplit(candidate).path
            matches=(bool(re.fullmatch(re.escape(config['detail_path'])+r'\d+',path)) if config['detail_path'].endswith('/') else path==config['detail_path'])
            if matches:
                target=candidate
        if target:
            validate_url(target,{safe_host(config['listing_url'])})
            links[target]={'url':target,'title':title,'institution_id':config['institution_id']}
    return list(links.values())


def validate_listing_provenance(original,institution):
    proof=original.get('discovery_provenance',{})
    config=channels().get(institution)
    if not config or proof.get('kind')!='official_board':
        raise ValueError('Unknown official listing provenance')
    url=proof.get('listing_url','')
    validate_url(url,{safe_host(config['listing_url'])})
    if urlsplit(url).path!=urlsplit(config['listing_url']).path:
        raise ValueError('Unexpected official listing route')
    base=parse_qs(urlsplit(config['listing_url']).query);query=parse_qs(urlsplit(url).query)
    if any(query.get(k)!=v for k,v in base.items()):
        raise ValueError('Official board identity differs')
    html=proof.get('listing_html','')
    if not isinstance(html,str) or len(html)>MAX_LISTING_CHARS or hashlib.sha256(html.encode()).hexdigest()!=proof.get('listing_sha256'):
        raise ValueError('Listing snapshot hash mismatch')
    rows=listing_links(html,url,config)
    row=next((r for r in rows if r['url']==original['url']),None)
    if not row or row['title']!=proof.get('listing_title'):
        raise ValueError('Original was not observed in this official listing')
    validate_identity({'institution_id':institution,'title':row['title'],'date':original.get('date')},original,load_aliases())


def validate_native_provenance(original,institution):
    proof=original.get('discovery_provenance',{})
    if institution not in NATIVE or proof.get('kind')!='existing_official_collection':
        raise ValueError('Unsupported original collection receipt')
    board,path,key=NATIVE[institution]
    if proof.get('listing_url')!=board or urlsplit(original['url']).path!=path:
        raise ValueError('Original receipt route differs')
    source=proof.get('source_notice',{})
    if original_body_hash(original)!=original.get('sha256'):
        raise ValueError('Original receipt body hash mismatch')
    for field in ('url','title','date','body','sha256','attachment_hashes'):
        if source.get(field,{} if field.startswith('attachment_') else None)!=original.get(field,{} if field.startswith('attachment_') else None):
            raise ValueError('Original receipt differs from collected evidence')
    if any(source.get('attachment_texts',{}).get(url)!=text for url,text in original.get('attachment_texts',{}).items()):
        raise ValueError('Original receipt attachment text differs')
    if parse_qs(urlsplit(original['url']).query).get(key)!=[str(source.get('source_id'))]:
        raise ValueError('Original receipt identifier differs from observed URL')


def reuse_native_originals(collection,official_notices,checked_at):
    result=copy.deepcopy(collection or {'notices':[],'holds':[],'coverage':{}})
    aliases=load_aliases();allowed=load_channels();matched=0
    for n in result.get('notices',[]):
        if n.get('original_notices') or n.get('source_scope') in ('outside','vc_only') or n.get('institution_id') not in NATIVE:
            continue
        options=[]
        for source in official_notices:
            if source.get('institution_id')!=n['institution_id']:
                continue
            original={**copy.deepcopy(source),'matched_republication_url':n['url'],
                      'review_only':True,'discovery_provenance':{'kind':'existing_official_collection',
                      'listing_url':NATIVE[n['institution_id']][0],'source_notice':copy.deepcopy(source)}}
            original.setdefault('attachment_hashes',{});original.setdefault('attachment_texts',{});original.setdefault('attachments',[])
            original['attachments']=[a if isinstance(a,dict) else {'url':a,'name':unquote(urlsplit(a).path.rsplit('/',1)[-1])} for a in original['attachments']]
            forms={a['url'] for a in original['attachments'] if re.search(r'서식|양식|제안서|template',a['name'],re.I)}
            original['attachment_texts']={url:text for url,text in original['attachment_texts'].items() if url not in forms}
            try:
                validate_url(original['url'],allowed[n['institution_id']])
                options.append(validate_original(original,n,checked_at))
            except (ValueError,KeyError,TypeError):
                pass
        if len(options)==1:
            n['original_notices']=options;matched+=1
        elif len(options)>1:
            result.setdefault('holds',[]).append({'stage':'original','url':n['url'],'error':'Multiple official originals match; preserve as unlinked'})
    result.setdefault('coverage',{})['existing_originals']={'matched':matched}
    return result


def discover(collection,fetch=fetch_bytes,pages=2,checked_at=None):
    if not 1<=pages<=3:raise ValueError('Official listing pages must be between 1 and 3')
    result=copy.deepcopy(collection);checked_at=checked_at or datetime.now(timezone.utc).isoformat()
    aliases=load_aliases();allowed=load_channels();stats={};seen=[]
    for institution,config in channels().items():
        targets=[n for n in result.get('notices',[]) if n.get('institution_id')==institution and not n.get('original_notices') and n.get('source_scope') not in ('outside','vc_only')]
        stats[institution]={'pages':0,'discovered':0,'matched':0,'errors':0,'target_notices':len(targets)}
        for page in range(1,pages+1):
            if page>1 and all(n.get('original_notices') for n in targets):break
            url=page_url(config,page)
            try:
                html=decode_html(fetch(url)).replace('\x00',' ')
                rows=listing_links(html,url,config)
                stats[institution]['pages']+=1;stats[institution]['discovered']+=len(rows)
                seen.extend({**row,'listing_url':url} for row in rows)
                for n in targets:
                    if n.get('original_notices'):continue
                    candidates=[]
                    for row in rows:
                        probe={'title':row['title'],'body':'','date':None}
                        try:validate_identity(n,probe,aliases,candidate_only=True)
                        except (ValueError,KeyError):continue
                        candidates.append(row)
                    if len(candidates)>1:
                        raise ValueError('Multiple matching official listing rows')
                    for row in candidates:
                        raw=fetch(row['url'],url)
                        doc=parse_original(decode_html(raw),row['url'])
                        digest=hashlib.sha256(json.dumps([doc['title'],doc['date'],doc['body']],ensure_ascii=False).encode()).hexdigest()
                        record={**doc,'institution_id':institution,'url':row['url'],'sha256':digest,'hash_kind':'semantic_v1',
                                'attachment_hashes':{},'attachment_texts':{},'checked_at':checked_at,
                                'matched_republication_url':n['url'],'review_only':True,
                                'discovery_provenance':{'kind':'official_board','listing_url':url,'listing_html':html,
                                'listing_sha256':hashlib.sha256(html.encode()).hexdigest(),'listing_title':row['title']}}
                        for a in record['attachments'][:1]:
                            try:
                                validate_url(a['url'],allowed[institution]);data=fetch(a['url'],row['url'])
                                record['attachment_hashes'][a['url']]=hashlib.sha256(data).hexdigest()
                                record['attachment_texts'][a['url']]=extract_attachment(data)['text']
                            except Exception as exc:
                                result.setdefault('holds',[]).append({'stage':'original','phase':'attachment','url':a['url'],'error':str(exc)})
                        n['original_notices']=[validate_original(record,n,checked_at)]
                        stats[institution]['matched']+=1
            except Exception as exc:
                stats[institution]['errors']+=1
                result.setdefault('holds',[]).append({'stage':'original_board','institution_id':institution,'url':url,'error':str(exc)})
    result.setdefault('coverage',{})['official_boards']=stats
    result['official_board_discovered_rows']=seen
    result['originals_checked_at']=checked_at
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--pages',type=int,default=2);args=parser.parse_args()
    result=discover(json.loads(args.input.read_text()),pages=args.pages)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['coverage']['official_boards'],ensure_ascii=False))


if __name__=='__main__':main()
