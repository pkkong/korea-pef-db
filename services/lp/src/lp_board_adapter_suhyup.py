"""Suhyup public notice board contracts; no asset-scope or GP approval."""
import re
from urllib.parse import parse_qsl,urlencode,urlsplit
try:
    from .collect_shared_lp_notices import Document
    from .lp_board_adapter_geps import one,cls,date
except ImportError:
    from collect_shared_lp_notices import Document
    from lp_board_adapter_geps import one,cls,date

BASE='https://www.suhyup.co.kr'
LANDING='/suhyup/223/subview.do'
LIST='/bbs/suhyup/23/artclList.do'
FIELDS={'layout','page','srchColumn','srchWrd','bbsClSeq','bbsOpenWrdSeq','rgsBgndeStr','rgsEnddeStr','isViewMine'}


def validate(url,config,detail=False):
    p=urlsplit(url)
    if config.get('institution_id')!='suhyup':raise ValueError('wrong Suhyup institution')
    if (p.scheme!='https' or p.netloc!='www.suhyup.co.kr' or p.username or p.password
            or p.fragment or re.search(r'[\x00-\x20\\]',url)):raise ValueError('unsafe Suhyup URL')
    pairs=parse_qsl(p.query,keep_blank_values=True);q=dict(pairs)
    if len(pairs)!=len(q):raise ValueError('duplicate Suhyup query')
    if detail:
        match=re.fullmatch(r'/bbs/suhyup/23/([1-9][0-9]*)/artclView\.do',p.path)
        if not match or set(q)-{'layout'} or q.get('layout','unknown')!='unknown':raise ValueError('wrong Suhyup detail identity')
        return match[1],q
    if (p.path!=LANDING or set(q)-{'page','srchColumn','srchWrd'}
            or not re.fullmatch(r'[1-9][0-9]{0,4}',q.get('page','1'))
            or q.get('srchColumn','sj')!='sj' or len(q.get('srchWrd',''))>30
            or re.search(r'[\x00-\x1f\x7f]',q.get('srchWrd',''))):raise ValueError('unsupported Suhyup listing query')
    return None,q


def tree(html):
    if not isinstance(html,str) or len(html)>2_000_000 or '</html>' not in html.lower():raise ValueError('incomplete Suhyup HTML')
    return Document(html).root


def search_fields(html):
    """Read the current public theme fields, never a stored session/layout key."""
    root=tree(html)
    form=one(n for n in root.nodes('form') if n.attrs.get('name')=='pageForm')
    if form.attrs.get('method','').lower()!='post' or form.attrs.get('action')!=LIST:raise ValueError('Suhyup page form changed')
    fields={}
    for n in form.nodes('input'):
        key=n.attrs.get('name')
        if key not in FIELDS or key in fields:raise ValueError('unrecognized Suhyup search field')
        fields[key]=n.attrs.get('value','')
    if set(fields)!=FIELDS or fields['isViewMine']!='false' or not fields['layout']:raise ValueError('missing Suhyup public form fields')
    if any(fields[k] for k in ('bbsClSeq','bbsOpenWrdSeq','rgsBgndeStr','rgsEnddeStr')):raise ValueError('unobserved Suhyup board filters')
    search=one(n for n in root.nodes('form') if n.attrs.get('name')=='searchForm')
    select=one(n for n in search.nodes('select') if n.attrs.get('name')=='srchColumn')
    if one(n.attrs.get('value') for n in select.nodes('option') if n.clean()=='제목')!='sj':raise ValueError('Suhyup title search changed')
    return fields


def request_plan(url,config,*,fields=None):
    if urlsplit(url).path.endswith('/artclView.do'):
        validate(url,config,True)
        return {'url':url,'method':'GET','encoding':None,'fields':None}
    _,q=validate(url,config)
    if not q:return {'url':url,'method':'GET','encoding':None,'fields':None}
    if fields is None or set(fields)!=FIELDS:raise ValueError('public Suhyup form receipt required')
    payload=dict(fields,page=q.get('page','1'),srchColumn='sj',srchWrd=q.get('srchWrd',''))
    return {'url':BASE+LIST,'method':'POST','encoding':'form','fields':payload}


def listing_tree(html,url,config):
    _,q=validate(url,config);root=tree(html);fields=search_fields(html)
    if fields['page']!=q.get('page','1') or fields['srchWrd']!=q.get('srchWrd',''):
        raise ValueError('Suhyup page/search echo mismatch')
    if fields['srchColumn'] not in ({'sj'} if q.get('srchWrd') else {'','sj'}):raise ValueError('Suhyup title search echo mismatch')
    stats=one(n.clean() for n in root.nodes('p') if cls(n,'count-txt'))
    match=re.fullmatch(r'([0-9,]+)건,\s*현재페이지:\s*([1-9][0-9]*)/([1-9][0-9]*)',stats)
    if not match:raise ValueError('Suhyup count contract changed')
    total,current,final=map(lambda s:int(s.replace(',','')),match.groups())
    if current!=int(q.get('page','1')) or final!=max(1,(total+9)//10) or current>final:raise ValueError('Suhyup count/page mismatch')
    pager=one(n for n in root.nodes('div') if cls(n,'_paging'))
    if (one(n.clean() for n in pager.nodes('span') if cls(n,'_curPage'))!=str(current)
            or one(n.clean() for n in pager.nodes('span') if cls(n,'_totPage'))!=str(final)):raise ValueError('Suhyup visible pager mismatch')
    last=one(n for n in pager.nodes('a') if cls(n,'_last'))
    if last.attrs.get('href')!="javascript:page_link('"+str(final)+"')":raise ValueError('Suhyup final page control changed')
    table=one(n for n in root.nodes('table') if cls(n,'board-link-list'))
    if [n.clean() for n in table.nodes('th')]!=['번호','제목','작성일','조회수','바로보기','첨부파일']:raise ValueError('Suhyup listing columns changed')
    if not total:
        cells=list(table.nodes('td'))
        if len(cells)!=1 or not cls(cells[0],'no-data') or cells[0].clean()!='게시물이(가) 없습니다.':
            raise ValueError('unverified Suhyup empty response')
    return table,total,current,final


def last_page(html,url,config):return listing_tree(html,url,config)[3]


def parse_listing(html,url,config):
    table,total,current,final=listing_tree(html,url,config);rows=[];numbers=[];seen=set()
    if not total:return rows
    for tr in table.nodes('tr'):
        cells=list(tr.nodes('td'))
        if not cells:continue
        if len(cells)!=6 or not re.fullmatch(r'[1-9][0-9]*',cells[0].clean()):raise ValueError('unverified Suhyup empty/pinned row')
        numbers.append(int(cells[0].clean()))
        a=one(cells[1].nodes('a'));target=BASE+a.attrs.get('href','');identifier,_=validate(target,config,True)
        if a.attrs.get('onclick')!="jf_viewArtcl('suhyup', '23', '"+identifier+"')":raise ValueError('Suhyup detail control mismatch')
        title=one(n.clean() for n in a.nodes('strong'))
        if not title or identifier in seen:raise ValueError('empty or duplicate Suhyup row')
        seen.add(identifier)
        rows.append({'source_id':'suhyup:'+identifier,'url':target,'title':title,'date':date(cells[2].clean())})
    if numbers!=list(range(total-(current-1)*10,max(0,total-current*10),-1)):raise ValueError('Suhyup row count/order mismatch')
    return rows


def parse_detail(html,url,config):
    identifier,_=validate(url,config,True);root=tree(html)
    info=one(n for n in root.nodes('div') if cls(n,'board-view-info'))
    number=one(n for n in info.nodes('dl') if cls(n,'view-num'))
    if one(n.clean() for n in number.nodes('dt'))!='글번호' or one(n.clean() for n in number.nodes('dd'))!=identifier:
        raise ValueError('Suhyup detail response identity mismatch')
    title=one(n.clean() for n in info.nodes('h2') if cls(n,'view-title'))
    published=one(n for n in info.nodes('dl') if cls(n,'write'))
    if one(n.clean() for n in published.nodes('dt'))!='등록일':raise ValueError('Suhyup posted-date label changed')
    stamp=date(one(n.clean() for n in published.nodes('dd')))
    body=one(n.clean() for n in root.nodes('div') if cls(n,'view-con')).replace('\x00',' ')
    if not title or not body:raise ValueError('empty Suhyup detail')
    result={'title':title,'date':stamp,'body':body,'attachments':[]}
    files=[n for n in root.nodes('div') if cls(n,'view-file')]
    if not files:
        result['unresolved_attachments']=True
        return result
    file=one(files);seen=set()
    for a in file.nodes('a'):
        href=a.attrs.get('href','')
        if not re.fullmatch(r'/bbs/suhyup/23/[1-9][0-9]*/download\.do',href):
            if re.search('download',href,re.I):result['unresolved_attachments']=True
            continue
        if not a.clean() or href in seen:raise ValueError('empty or duplicate Suhyup file')
        seen.add(href);result['attachments'].append({'url':BASE+href,'name':a.clean()})
    return result
