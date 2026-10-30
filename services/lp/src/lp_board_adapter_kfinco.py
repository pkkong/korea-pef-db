"""Pure archival parsers for K-FINCO's observed public JSON notice board.

Scope classification and publication are deliberately separate from parsing.
Only the currently observed page-one API contract is accepted.
"""
import re
import json
from urllib.parse import urlsplit, urljoin
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


class RestrictedNotice(ValueError):
    def __init__(self, ident):
        self.source_id = 'kfinco:' + ident
        self.url = BASE + '/pr/notice/detail/' + ident
        super().__init__('owner_closed')


def _metadata(row):
    ident=code(row.get('ntCode'))
    if type(row.get('closed')) is not int or row['closed'] not in (0,1):
        raise ValueError('Invalid KFINCO closed flag')
    if row['closed'] == 1:
        raise RestrictedNotice(ident)
    title=row.get('ntTitle');published=row.get('ntDate')
    if not isinstance(title,str) or not title.strip() or '\x00' in title:raise ValueError('missing KFINCO title')
    if not isinstance(published,str) or valid_date(published)!=published:raise ValueError('invalid KFINCO publication date')
    return ident,title,published


def listing_parts(rawjson,url,config):
    _config(url,config)
    _,rows=listing(rawjson);_,value=read_json(rawjson)
    if len(rows)!=min(value['totalCount'],10):raise ValueError('incomplete KFINCO listing response')
    result=[];restricted=[];seen=set()
    for row in rows:
        ident=code(row.get('ntCode'))
        if ident in seen:raise ValueError('duplicate KFINCO listing identifier')
        seen.add(ident)
        try:
            ident,title,published=_metadata(row)
        except RestrictedNotice as error:
            restricted.append({'source_id':error.source_id,'url':error.url,'reason':'owner_closed'})
            continue
        result.append({'source_id':'kfinco:'+ident,'url':BASE+'/pr/notice/detail/'+ident,
                       'title':title,'date':published})
    return result,restricted,len(rows),value['totalCount']


def parse_listing(rawjson,url,config):
    return listing_parts(rawjson,url,config)[0]


def listing_receipt(rawjson,url,config):
    # Keep all physical slots for replay/count integrity, but no restricted content.
    listing_parts(rawjson,url,config)
    _,value=read_json(rawjson)
    value['list']=[{'ntCode':row['ntCode'],'closed':1} if row['closed']==1 else row
                   for row in value['list']]
    return json.dumps({key:value[key] for key in ('success','list','totalCount')},ensure_ascii=False,separators=(',',':'))


def last_page(rawjson,url,config):
    _,_,_,total=listing_parts(rawjson,url,config)
    return max(1,(total+9)//10)


def parse_detail(rawjson,url,config):
    _config(url,config,detail=True)
    ident=_public_identifier(url)
    _,value=read_json(rawjson);row=value.get('detail')
    if not isinstance(row,dict):raise ValueError('missing KFINCO detail object')
    observed,title,published=_metadata(row)
    if observed!=ident:raise ValueError('KFINCO detail identifier mismatch')
    html=row.get('ntContent')
    if not isinstance(html,str) or not html.strip():raise ValueError('missing KFINCO detail content')
    root=Document(html).root
    body=root.clean().replace('\x00',' ')
    if not body.strip():raise ValueError('empty KFINCO detail content')
    files=attachments(row)
    for item in files:kfinco_url(item['url'])
    related=set()
    for a in root.nodes('a'):
        target=urljoin(url,a.attrs.get('href',''))
        if urlsplit(target).path.startswith('/pr/notice/detail/'):
            _public_identifier(target);related.add(target)
    return {'title':title,'date':published,'body':body,'attachments':files,'related_notice_urls':sorted(related)}


def diagnostic_listing_metadata(rawjson):
    """Allowlist diagnostics only; never retain titles, contents or attachment fields."""
    _, rows = listing(rawjson)
    _, value = read_json(rawjson)
    safe = []
    for index, row in enumerate(rows):
        identifier = row.get('ntCode')
        closed = row.get('closed')
        entry = {'row': index + 1, 'source_id': identifier if isinstance(identifier, str)
                 and re.fullmatch(r'NT[0-9]{14}', identifier) else None,
                 'closed_type': type(closed).__name__ if 'closed' in row else 'missing'}
        # Arbitrary strings/objects may contain private content: record type only.
        if type(closed) is int and -1000 <= closed <= 1000:
            entry['closed'] = closed
        elif closed is None or type(closed) is bool:
            entry['closed'] = closed
        safe.append(entry)
    return {'page': 1, 'row_count': len(rows), 'total_count': value['totalCount'], 'rows': safe}
