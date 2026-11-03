"""Observed NH Central notice/bid listing contracts; no scope approval or HTTP."""
import re
from urllib.parse import urlsplit, parse_qsl, urlencode
try:
    from .collect_shared_lp_notices import Document
    from .lp_board_adapter_geps import one, cls, date
except ImportError:
    from collect_shared_lp_notices import Document
    from lp_board_adapter_geps import one, cls, date

BASE='https://www.nonghyup.com'
BOARDS={'notice':'BBSMSTR_000000000012','bid':'BBSMSTR_000000000019'}


def validate(url,config,detail=False):
    p=urlsplit(url)
    if config.get('institution_id')!='nh_central':raise ValueError('wrong NH institution')
    if (p.scheme!='https' or p.netloc!='www.nonghyup.com' or p.fragment
            or p.username or p.password or re.search(r'[\x00-\x20\\]',url)):
        raise ValueError('unsafe NH URL')
    match=re.fullmatch(r'/ecenter/(notice|bid)/\1'+('View' if detail else 'List')+r'\.do',p.path)
    if not match:raise ValueError('unobserved NH board route')
    board=match[1];pairs=parse_qsl(p.query,keep_blank_values=True);q=dict(pairs)
    if len(q)!=len(pairs):raise ValueError('duplicate NH query')
    if detail:
        if set(q)!={'intgBsnBlbdGrpC','blbdSqno'} or q['intgBsnBlbdGrpC']!=BOARDS[board] or not re.fullmatch(r'[1-9][0-9]*',q['blbdSqno']):raise ValueError('NH detail identity mismatch')
    else:
        if set(q)-{'pageIndex','searchCnd','searchWrd'} or not re.fullmatch(r'[1-9][0-9]{0,4}',q.get('pageIndex','1')):raise ValueError('invalid NH listing query')
        condition=q.get('searchCnd','0');term=q.get('searchWrd','')
        if condition not in {'0','1'} or len(term)>20 or re.search(r'[\x00-\x1f\x7f]',term) or (condition=='0' and term):raise ValueError('unsupported NH title search')
    return board,q


def request_plan(url,config):
    """Logical URL to witnessed frm submission; public detail GET unverified."""
    detail=urlsplit(url).path.endswith('View.do');board,q=validate(url,config,detail)
    fields={'intgBsnBlbdGrpC':BOARDS[board],'pageIndex':'1','blbdSqno':'','searchCnd':'0','searchWrd':''}
    fields.update(q)
    # Initial bare listing is proven GET; query-bearing pages use actual POST.
    if not detail and not q:return {'url':url,'method':'GET','encoding':None,'fields':None}
    return {'url':BASE+urlsplit(url).path,'method':'POST','encoding':'form','fields':fields}


def listing_tree(html,url,config):
    board,q=validate(url,config)
    if not isinstance(html,str) or len(html)>2_000_000 or '</html>' not in html.lower():raise ValueError('incomplete NH HTML')
    root=Document(html).root
    form=one(n for n in root.nodes('form') if n.attrs.get('id')=='frm')
    path='/ecenter/'+board+'/'+board+'List.do'
    if form.attrs.get('action')!=path or form.attrs.get('method','').lower()!='post':raise ValueError('NH form action mismatch')
    for name,expected in {'intgBsnBlbdGrpC':BOARDS[board],'pageIndex':q.get('pageIndex','1'),'searchWrd':q.get('searchWrd','')}.items():
        if one(n.attrs.get('value','') for n in form.nodes('input') if n.attrs.get('name')==name)!=expected:raise ValueError('NH group/page/search echo mismatch')
    select=one(n for n in form.nodes('select') if n.attrs.get('name')=='searchCnd')
    options=list(select.nodes('option'))
    if [(n.attrs.get('value'),n.clean()) for n in options]!=[('0','전체'),('1','제목'),('2','내용')]:raise ValueError('NH search control changed')
    selected=[n.attrs['value'] for n in options if 'selected' in n.attrs]
    actual=one(selected) if selected else options[0].attrs['value']
    if actual!=q.get('searchCnd','0'):raise ValueError('NH search type echo mismatch')
    # Confirm both actual JavaScript form destinations, never execute JavaScript.
    for function,destination in [('fn_select_brdList',path),('fn_select_brdView','/ecenter/'+board+'/'+board+'View.do')]:
        body=one(re.findall(r'function\s+'+function+r'\([^)]*\)\s*\{([^}]+)\}',html))
        if not re.search(r'form\.action\s*=\s*"'+re.escape(destination)+r'"\s*;',body) or 'form.submit()' not in body:raise ValueError('NH controller action mismatch')
    table=one(n for n in root.nodes('table') if cls(n,'list'))
    if [n.clean() for n in table.nodes('th')]!=['번호','제목','첨부파일','등록일','조회수']:raise ValueError('NH table columns changed')
    total_text=one(n.clean() for dl in root.nodes('dl') if cls(dl,'sum') for n in dl.nodes('strong'))
    if not re.fullmatch(r'[0-9]+(?:,[0-9]{3})*',total_text):raise ValueError('invalid NH total count')
    total=int(total_text.replace(',',''))
    if total==0:raise ValueError('NH zero-result response not yet verified')
    pager=one(n for n in root.nodes('div') if cls(n,'page'))
    current=one(n.clean() for n in pager.nodes('button') if cls(n,'on'))
    if current!=q.get('pageIndex','1'):raise ValueError('NH visible page mismatch')
    last=one(n for n in pager.nodes('button') if cls(n,'btn_next0'))
    match=re.fullmatch(r'fn_select_brdList\(([1-9][0-9]*)\);return false;\s*',last.attrs.get('onclick',''))
    if not match or int(match[1])!=(total+9)//10 or int(current)>int(match[1]):raise ValueError('NH last-page/count mismatch')
    return board,root,table,int(current),total,int(match[1])


def last_page(html,url,config):return listing_tree(html,url,config)[5]


def parse_listing(html,url,config):
    board,root,table,current,total,final=listing_tree(html,url,config)
    rows=[];seen=set();numbers=[]
    for tr in table.nodes('tr'):
        cells=list(tr.nodes('td'))
        if not cells:continue
        if len(cells)!=5 or not re.fullmatch(r'[1-9][0-9]*',cells[0].clean()):raise ValueError('unverified NH empty/pinned row')
        numbers.append(int(cells[0].clean()))
        if not cls(cells[1],'tit_brdlist'):raise ValueError('NH title cell changed')
        a=one(cells[1].nodes('a'));match=re.fullmatch(r"fn_select_brdView\('([1-9][0-9]*)'\);",a.attrs.get('onclick',''))
        if not match or not a.clean():raise ValueError('invalid NH detail control')
        identifier=match[1]
        if identifier in seen:raise ValueError('duplicate NH row')
        seen.add(identifier)
        target=BASE+'/ecenter/'+board+'/'+board+'View.do?'+urlencode({'intgBsnBlbdGrpC':BOARDS[board],'blbdSqno':identifier})
        rows.append({'source_id':'nh_central:'+board+':'+identifier,'url':target,'title':a.clean(),'date':date(cells[3].clean())})
    expected=list(range(total-(current-1)*10,max(0,total-current*10),-1))
    if numbers!=expected or not rows:raise ValueError('NH row count/order mismatch')
    return rows
