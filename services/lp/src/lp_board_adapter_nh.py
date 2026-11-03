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
    """Observed listing form; public detail GET verified against both POST boards."""
    detail=urlsplit(url).path.endswith('View.do');board,q=validate(url,config,detail)
    fields={'intgBsnBlbdGrpC':BOARDS[board],'pageIndex':'1','blbdSqno':'','searchCnd':'0','searchWrd':''}
    fields.update(q)
    if detail:return {'url':url,'method':'GET','encoding':None,'fields':None}
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
    pager=one(n for n in root.nodes('div') if cls(n,'page'))
    current=one(n.clean() for n in pager.nodes('button') if cls(n,'on'))
    if current!=q.get('pageIndex','1'):raise ValueError('NH visible page mismatch')
    last_controls=[n for n in pager.nodes('button') if cls(n,'btn_next0')]
    if total<=10:
        buttons=list(pager.nodes('button'))
        if current!='1' or len(buttons)!=1 or not cls(buttons[0],'on') or buttons[0].attrs.get('onclick'):
            raise ValueError('NH single-page controls mismatch')
        empty=[n for n in table.nodes('span') if cls(n,'exclam') and n.clean()=='검색된 결과가 없습니다.']
        if total==0:
            cells=list(table.nodes('td'))
            if len(empty)!=1 or len(cells)!=1 or cells[0].attrs.get('colspan')!='5' or cells[0].clean()!='검색된 결과가 없습니다.':
                raise ValueError('NH zero-result marker mismatch')
        elif empty:raise ValueError('NH contradictory empty marker')
        return board,root,table,1,total,1
    if not last_controls and total<=100:
        final=(total+9)//10
        buttons=list(pager.nodes('button'))
        if [b.clean() for b in buttons]!=[str(x) for x in range(1,final+1)]:raise ValueError('NH compact pager sequence mismatch')
        for b in buttons:
            if b.clean()==current:
                if b.attrs.get('onclick'):raise ValueError('NH current page control mismatch')
            elif not re.fullmatch(r'fn_select_brdList\('+b.clean()+r'\);return false;\s*',b.attrs.get('onclick','')):
                raise ValueError('NH compact pager action mismatch')
        return board,root,table,int(current),total,final
    last=one(last_controls)
    match=re.fullmatch(r'fn_select_brdList\(([1-9][0-9]*)\);return false;\s*',last.attrs.get('onclick',''))
    if not match or int(match[1])!=(total+9)//10 or int(current)>int(match[1]):raise ValueError('NH last-page/count mismatch')
    return board,root,table,int(current),total,int(match[1])


def last_page(html,url,config):return listing_tree(html,url,config)[5]


def parse_listing(html,url,config):
    board,root,table,current,total,final=listing_tree(html,url,config)
    if total==0:return []
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


def parse_detail(html,url,config):
    board,q=validate(url,config,True)
    if not isinstance(html,str) or len(html)>2_000_000 or '</html>' not in html.lower():raise ValueError('incomplete NH detail HTML')
    root=Document(html).root
    form=one(n for n in root.nodes('form') if n.attrs.get('id')=='frm')
    if form.attrs.get('method','').lower()!='post' or one(n.attrs.get('value') for n in form.nodes('input') if n.attrs.get('name')=='intgBsnBlbdGrpC')!=BOARDS[board]:raise ValueError('NH detail group mismatch')
    view=one(n for n in root.nodes('div') if cls(n,'viewbox'))
    titlebox=one(n for n in view.nodes('div') if cls(n,'view_tit'))
    title=one(n.clean() for n in titlebox.nodes('h4'))
    published=date(one(n.clean() for n in titlebox.nodes('dd') if n.attrs.get('title')=='등록일'))
    body=one(n.clean() for n in view.nodes('div') if cls(n,'view_cont')).replace('\x00',' ')
    if not title or not body:raise ValueError('NH missing article content')
    departments=[n.clean() for n in titlebox.nodes('dd') if n.attrs.get('title')=='담당부서']
    if len(departments)>1:raise ValueError('NH ambiguous article department')
    result={'title':title,'date':published,'body':body,'attachments':[],
            'article_department':departments[0] if departments else None}
    files=[n for n in view.nodes('div') if cls(n,'view_file')]
    if files:
        files=one(files)
        # Exact inline official formula; never execute JS or guess a download ID.
        controller=one(re.findall(r'function\s+fn_egov_downFile\(atchFileId,\s*fileSn\)\s*\{([^}]+)\}',html))
        formula='"/cmm/fms/FileDown.do?atchFileId="+atchFileId+"&fileSn="+fileSn+""'
        if not re.fullmatch(r'\s*window\.open\(' + re.escape(formula) + r',\s*"_self",\s*"[^"\n]*"\);\s*return false;\s*',controller):raise ValueError('NH unverified download formula')
        for a in files.nodes('a'):
            match=re.fullmatch(r"javascript:fn_egov_downFile\('(FILE_[0-9]+)','([0-9]+)'\)",a.attrs.get('onclick',''))
            if not match or not a.clean():raise ValueError('NH invalid attachment control')
            target=BASE+'/cmm/fms/FileDown.do?'+urlencode(dict(zip(('atchFileId','fileSn'),match.groups())))
            if any(x['url']==target for x in result['attachments']):raise ValueError('NH duplicate attachment')
            result['attachments'].append({'url':target,'name':a.clean()})
        if not result['attachments']:raise ValueError('NH empty unresolved file widget')
    result['issuer_evidence']=issuer_evidence(result)
    return result


def issuer_evidence(detail):
    """Article-local issuer gate. Portal ownership and department alone prove none."""
    title=detail.get('title','');body=detail.get('body','')
    for marker,name in ((r'^\(\s*은행\s*\)','NH농협은행'),(r'^\(\s*증권\s*\)','NH투자증권')):
        match=re.search(marker,title)
        if match:return {'status':'affiliate','name':name if name in body else None,'quote':match[0],'location':'title'}
    for name in ('NH농협은행','NH투자증권','농협생명','농협손해보험'):
        if body.lstrip('□ •').startswith(name):return {'status':'affiliate','name':name,'quote':name,'location':'body'}
    match=re.search(r'(?:발주기관|공고기관|출자기관)\s*[:：]\s*농협중앙회(?:\s|$)',body)
    if match:return {'status':'central_explicit','name':'농협중앙회','quote':match[0].strip(),'location':'body'}
    return {'status':'needs_confirmation','name':None,'quote':None,'location':None}
