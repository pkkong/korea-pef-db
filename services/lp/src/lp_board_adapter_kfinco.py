"""Pure archival parsers for K-FINCO's observed public JSON notice board.

Scope classification and publication are deliberately separate from parsing.
Only the currently observed page-one API contract is accepted.
"""
import re
from urllib.parse import urlsplit
try:
    from .discover_kfinco_originals import BASE, code, read_json, listing, attachments
    from .collect_shared_lp_notices import Document, valid_date
    from .lp_regional_transport import kfinco_url
except ImportError:
    from discover_kfinco_originals import BASE, code, read_json, listing, attachments
    from collect_shared_lp_notices import Document, valid_date
    from lp_regional_transport import kfinco_url


def _public_identifier(url):
    if not isinstance(url,str) or re.search(r'[\x00-\x20\x7f\\#]',url):
        raise ValueError('invalid KFINCO public detail URL')
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname!='www.kfinco.co.kr' or p.username or p.password or p.port not in {None,443} or p.query or p.fragment:
        raise ValueError('wrong KFINCO public detail origin or query')
    match=re.fullmatch(r'/pr/notice/detail/(NT[0-9]{14})',p.path)
    if not match:raise ValueError('wrong KFINCO public detail route')
    return code(match[1])


def detail_request(public_url):
    return BASE+'/api/pr/notice/detail/'+_public_identifier(public_url)


def _config(url,config,detail=False):
    if config.get('institution_id')!='kfinco':raise ValueError('wrong KFINCO institution configuration')
    listing_url=config.get('listing_url','')
    kfinco_url(listing_url)
    if urlsplit(listing_url).path!='/api/pr/notice/list':raise ValueError('wrong KFINCO configured board')
    if detail:_public_identifier(url)
    else:
        kfinco_url(url)
        if urlsplit(url).path!='/api/pr/notice/list':raise ValueError('wrong KFINCO listing route')


def _metadata(row):
    ident=code(row.get('ntCode'))
    title=row.get('ntTitle');published=row.get('ntDate')
    if not isinstance(title,str) or not title.strip() or '\x00' in title:raise ValueError('missing KFINCO title')
    if not isinstance(published,str) or valid_date(published)!=published:raise ValueError('invalid KFINCO publication date')
    if type(row.get('closed')) is not int or row['closed']!=0:
        raise ValueError('KFINCO public UI restricts closed notice; preserve as collection hold')
    return ident,title,published


def parse_listing(rawjson,url,config):
    _config(url,config)
    _,rows=listing(rawjson);_,value=read_json(rawjson)
    if len(rows)!=min(value['totalCount'],10):raise ValueError('incomplete KFINCO listing response')
    result=[];seen=set()
    for row in rows:
        ident,title,published=_metadata(row)
        if ident in seen:raise ValueError('duplicate KFINCO listing identifier')
        seen.add(ident)
        result.append({'source_id':'kfinco:'+ident,'url':BASE+'/pr/notice/detail/'+ident,
                       'title':title,'date':published})
    return result


def last_page(rawjson,url,config):
    parse_listing(rawjson,url,config)
    _,value=read_json(rawjson)
    return max(1,(value['totalCount']+9)//10)


def parse_detail(rawjson,url,config):
    _config(url,config,detail=True)
    ident=_public_identifier(url)
    _,value=read_json(rawjson);row=value.get('detail')
    if not isinstance(row,dict):raise ValueError('missing KFINCO detail object')
    observed,title,published=_metadata(row)
    if observed!=ident:raise ValueError('KFINCO detail identifier mismatch')
    html=row.get('ntContent')
    if not isinstance(html,str) or not html.strip():raise ValueError('missing KFINCO detail content')
    body=Document(html).root.clean().replace('\x00',' ')
    if not body.strip():raise ValueError('empty KFINCO detail content')
    files=attachments(row)
    for item in files:kfinco_url(item['url'])
    return {'title':title,'date':published,'body':body,'attachments':files}
