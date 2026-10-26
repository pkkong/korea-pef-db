"""Pure GEPS notice parsing; no scope or publication decisions."""
import re
from urllib.parse import urlsplit,parse_qsl,urljoin
try:
    from .collect_shared_lp_notices import Document,valid_date
except ImportError:
    from collect_shared_lp_notices import Document,valid_date

BASE='https://www.geps.or.kr'
PATH='/notiCommunication_notice_center'
def one(values):
    values=list(values)
    if len(values)!=1:raise ValueError('missing or ambiguous official markup')
    return values[0]
def cls(node,name):return name in node.attrs.get('class','').split()
def tree(html):
    if not isinstance(html,str) or len(html)>2_000_000 or '</html>' not in html.lower():raise ValueError('incomplete official HTML')
    return Document(html).root
def query(url,host):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname!=host or p.username or p.password or p.port not in {None,443} or p.fragment or re.search(r'[\x00-\x20\\]',url):raise ValueError('invalid official URL')
    pairs=parse_qsl(p.query,keep_blank_values=True)
    if len(dict(pairs))!=len(pairs):raise ValueError('duplicate official query')
    return p,dict(pairs)
def date(text):
    if not re.fullmatch(r'20[0-9]{2}[-./][0-9]{1,2}[-./][0-9]{1,2}',text.strip()):raise ValueError('ambiguous official date')
    value=valid_date(text)
    if not value:raise ValueError('missing official date')
    return value
def search(root,q,config,fields):
    expected=config.get('search_params',{})
    for field in fields:
        if field not in q or (field in expected and q[field]!=expected[field]):raise ValueError('wrong configured search')
        nodes=[n for n in root.nodes() if n.attrs.get('name')==field and n.tag in {'input','select'}]
        n=one(nodes)
        value=n.attrs.get('value') if n.tag=='input' else one(o.attrs.get('value') for o in n.nodes('option') if 'selected' in o.attrs)
        if value!=q[field]:raise ValueError('search response echo mismatch')
def validate(url,config,detail=False):
    if config.get('institution_id')!='geps':raise ValueError('wrong institution')
    p,q=query(url,'www.geps.or.kr');c,_=query(config['listing_url'],'www.geps.or.kr')
    if c.path!=PATH or (not detail and p.path!=PATH) or (detail and not re.fullmatch(PATH+r'/[0-9]+',p.path)):raise ValueError('wrong GEPS route')
    if set(q)-{'curPage','srchKey','srchText'} or not q.get('curPage','1').isdigit():raise ValueError('wrong GEPS query')
    return p,q

def parse_listing(html,url,config):
    _,q=validate(url,config);root=tree(html);search(root,q,config,('srchKey','srchText'))
    table=one(n for n in root.nodes('table') if any(cls(t,'writngDe') for t in n.nodes('th')))
    result=[];seen=set()
    for tr in table.nodes('tr'):
        anchors=[a for td in tr.nodes('td') if cls(td,'sj') for a in td.nodes('a')]
        if not anchors:continue
        a=one(anchors);target=urljoin(url,a.attrs.get('href',''));p,_=validate(target,config,True)
        if target in seen:raise ValueError('duplicate GEPS row')
        seen.add(target);title=a.clean()
        if not title:raise ValueError('missing title')
        result.append({'source_id':'geps:'+p.path.rsplit('/',1)[1],'url':target,'title':title,'date':date(one(t.clean() for t in tr.nodes('td') if cls(t,'writngDe')))})
    empty=any(n.clean()=='데이터가 없습니다.' for n in table.nodes('td'))
    if empty and result:raise ValueError('conflicting GEPS empty marker')
    if not result and not empty:raise ValueError('GEPS empty response has no verified empty marker')
    last_page(html,url,config)
    return result

def last_page(html,url,config):
    _,q=validate(url,config);root=tree(html);search(root,q,config,('srchKey','srchText'))
    pager=one(n for n in root.nodes('ul') if cls(n,'pagination'))
    table=one(n for n in root.nodes('table') if any(cls(t,'writngDe') for t in n.nodes('th')))
    empty=any(n.clean()=='데이터가 없습니다.' for n in table.nodes('td'))
    if empty:
        if q.get('curPage','1')!='1' or list(pager.nodes('li')):raise ValueError('GEPS empty overrun or conflicting pagination')
        return 1
    current=one(n.clean() for n in pager.nodes('li') if cls(n,'active'))
    if current!=q.get('curPage','1'):raise ValueError('GEPS current page mismatch')
    last=one(a for a in pager.nodes('a') if a.attrs.get('title')=='마지막 페이지')
    href=last.attrs.get('href','')
    if href=='#none':return int(current)
    _,pq=validate(urljoin(url,href),config)
    if any(pq.get(k)!=q.get(k) for k in ('srchKey','srchText')):raise ValueError('GEPS pagination search mismatch')
    value=int(pq['curPage'])
    if value<int(current):raise ValueError('GEPS last page mismatch')
    return value

def parse_detail(html,url,config):
    validate(url,config,True);root=tree(html)
    header=one(n for n in root.nodes('div') if all(cls(n,c) for c in ('d-flex','justify-content-between','border-bottom')) and len(list(n.nodes('h6')))==2)
    hs=list(header.nodes('h6'));title=hs[0].clean();published=date(hs[1].clean())
    content=one(n for n in root.nodes('div') if cls(n,'viewCtn'));body=content.clean().replace('\x00',' ')
    if not title or not body:raise ValueError('missing GEPS detail content')
    files=[]
    for a in root.nodes('a'):
        if not cls(a,'file'):continue
        target=urljoin(url,a.attrs.get('href',''));p,q=query(target,'www.geps.or.kr')
        if p.path!='/comm/getFile' or set(q)!={'srvcId','fileUuid'} or q['srvcId']!='BBSTY1' or not re.fullmatch('[A-Fa-f0-9]{32}',q['fileUuid']):raise ValueError('wrong GEPS attachment')
        if not a.clean():raise ValueError('missing attachment name')
        files.append({'url':target,'name':a.clean()})
    return {'title':title,'date':published,'body':body,'attachments':files}
