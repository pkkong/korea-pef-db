"""CWMA observed board contracts; no date-window or PE scope decisions."""
import re
from urllib.parse import urlsplit, parse_qsl, urlencode
try:
    from .collect_shared_lp_notices import Document
    from .lp_board_adapter_geps import one, cls, date
except ImportError:
    from collect_shared_lp_notices import Document
    from lp_board_adapter_geps import one, cls, date

BASE='https://www.cw.or.kr'
BOARD={'boardConfigNo':'29','menuNo':'248','boardCategoryNo':'66'}


def validate(url,config,detail=False):
    p=urlsplit(url)
    if config.get('institution_id')!='cwma':raise ValueError('wrong CWMA institution')
    c=urlsplit(config['listing_url'])
    if c.scheme!='https' or c.netloc!='www.cw.or.kr' or c.path!='/board.do':raise ValueError('wrong CWMA configured channel')
    if (p.scheme!='https' or p.netloc!='www.cw.or.kr' or p.path!='/board.do'
            or p.fragment or p.username or p.password or re.search(r'[\x00-\x20\\]',url)):
        raise ValueError('unsafe CWMA URL')
    pairs=parse_qsl(p.query,keep_blank_values=True);q=dict(pairs)
    if len(pairs)!=len(q) or any(q.get(k)!=v for k,v in BOARD.items()):raise ValueError('wrong CWMA board')
    if detail:
        if set(q)!=set(BOARD)|{'action','boardNo'} or q['action']!='view' or not re.fullmatch(r'[1-9][0-9]*',q['boardNo']):raise ValueError('invalid CWMA detail identity')
    elif set(q)-set(BOARD)-{'page','searchValue'} or not re.fullmatch(r'[1-9][0-9]{0,3}',q.get('page','1')) or q.get('searchValue',''):
        raise ValueError('unsupported CWMA listing query')
    return q


def request_plan(url,config):
    """Logical detail links identify observed forms; public GET is unverified."""
    detail=dict(parse_qsl(urlsplit(url).query)).get('action')=='view'
    q=validate(url,config,detail)
    if detail:
        fields=dict(q,pageNo='1',menuLayout=' ',searchCategory='',searchValue='')
        return {'url':BASE+'/board.do','method':'POST','encoding':'form','fields':fields}
    if q.get('page','1')=='1':return {'url':BASE+'/board.do?'+urlencode(BOARD),'method':'GET','encoding':None,'fields':None}
    fields=dict(BOARD,page=q['page'],contentsNo='',moveMenu='',separator='',actionVal='',boardWriterAddress2='',menuLayout='category_tabLayout',searchValue='',searchCategory='')
    return {'url':BASE+'/board.do','method':'POST','encoding':'form','fields':fields}


def tree(html):
    if not isinstance(html,str) or len(html)>2_000_000 or '</html>' not in html.lower():raise ValueError('incomplete CWMA HTML')
    return Document(html).root


def listing_tree(html,url,config):
    q=validate(url,config);root=tree(html)
    form=one(n for n in root.nodes('form') if n.attrs.get('id')=='boardAdmin')
    if form.attrs.get('action')!='/board.do' or form.attrs.get('method','').lower()!='post':raise ValueError('unexpected CWMA search form')
    for key,value in dict(BOARD,searchValue='').items():
        if one(n.attrs.get('value','') for n in form.nodes('input') if n.attrs.get('name')==key)!=value:raise ValueError('CWMA board/search echo mismatch')
    table=one(n for n in root.nodes('table') if cls(n,'board-list'))
    headers=[n.clean() for n in table.nodes('th')]
    if headers!=['번호','분류','제목','작성자','등록일','조회수']:raise ValueError('unrecognized CWMA table columns')
    pager=one(n for n in root.nodes('div') if n.attrs.get('id')=='paging' and cls(n,'pagination'))
    current=one(n.clean() for n in pager.nodes('strong'))
    if current!=q.get('page','1'):raise ValueError('CWMA visible page mismatch')
    last=one(n for n in pager.nodes('a') if n.attrs.get('title')=='마지막페이지')
    pages=[]
    for a in pager.nodes('a'):
        href=a.attrs.get('href','')
        if not href:continue
        m=re.fullmatch(r"javascript:goCategory\('/board.do\?boardConfigNo=29','248',\s*([1-9][0-9]*),\s*'66'\)",href)
        if not m:raise ValueError('invalid CWMA pagination route')
        pages.append(int(m[1]))
    if last.attrs.get('href'):
        m=re.fullmatch(r"javascript:goCategory\('/board.do\?boardConfigNo=29','248',\s*([1-9][0-9]*),\s*'66'\)",last.attrs['href'])
        if not m:raise ValueError('invalid CWMA final page')
        final=int(m[1])
    else:
        final=int(current)
        if pages and max(pages)>final:raise ValueError('CWMA final-page contradiction')
    if int(current)>final or any(p>final for p in pages):raise ValueError('CWMA page overrun')
    return root,table,int(current),final


def last_page(html,url,config):
    return listing_tree(html,url,config)[3]


def parse_listing(html,url,config):
    root,table,current,final=listing_tree(html,url,config)
    result=[];numbers=[];seen=set()
    for tr in table.nodes('tr'):
        cells=list(tr.nodes('td'))
        if not cells:continue
        if len(cells)!=6 or not re.fullmatch(r'[1-9][0-9]*',cells[0].clean()):raise ValueError('unverified CWMA empty or pinned row')
        numbers.append(int(cells[0].clean()))
        if cells[1].clean()!='선정공고(자산운용)':raise ValueError('wrong CWMA category row')
        a=one(cells[2].nodes('a'));m=re.fullmatch(r"javascript:goView\('29','248','view','([1-9][0-9]*)'\)",a.attrs.get('href',''))
        if not m or not a.clean():raise ValueError('invalid CWMA detail control')
        identity=m[1]
        if identity in seen:raise ValueError('duplicate CWMA row')
        seen.add(identity)
        result.append({'source_id':'cwma:'+identity,'url':BASE+'/board.do?'+urlencode(dict(BOARD,action='view',boardNo=identity)), 'title':a.clean(),'date':date(cells[4].clean())})
    if not result:raise ValueError('CWMA empty response lacks verified marker')
    if numbers!=list(range(numbers[0],numbers[0]-len(numbers),-1)):raise ValueError('CWMA row sequence mismatch')
    total=numbers[0]+10*(current-1)
    if (total+9)//10!=final or len(result)!=min(10,total-10*(current-1)):raise ValueError('CWMA page/count mismatch')
    return result


def parse_detail(html,url,config):
    """Parse witnessed POST detail and inline DEXT5 file records, without JS."""
    import json
    from datetime import datetime
    validate(url,config,True);root=tree(html)
    table=one(n for n in root.nodes('table') if cls(n,'board-view'))
    title=one(n.clean() for n in table.nodes('th') if cls(n,'subject'))
    caption=one(n.clean() for n in table.nodes('caption'))
    if not title or caption!='['+title+'] 게시물의 등록 내용을 보여줍니다.':raise ValueError('CWMA detail title mismatch')
    dates=[];attachment_cells=[]
    for tr in table.nodes('tr'):
        cells=[x for x in tr.children if getattr(x,'tag',None) in {'th','td'}]
        for index,cell in enumerate(cells):
            if cell.tag!='th' or cell.clean() not in {'작성일','첨부파일'}:continue
            if index+1>=len(cells) or cells[index+1].tag!='td':raise ValueError('CWMA missing labelled value')
            if cell.clean()=='작성일':dates.append(cells[index+1].clean())
            else:attachment_cells.append(cells[index+1])
    stamp=one(dates)
    if not re.fullmatch(r'20[0-9]{2}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}',stamp):raise ValueError('invalid CWMA publication timestamp')
    datetime.fromisoformat(stamp)
    body=one(n.clean() for n in table.nodes('td') if cls(n,'content')).replace('\x00',' ')
    if not body:raise ValueError('empty CWMA detail body')
    result={'title':title,'date':date(stamp[:10]),'body':body,'attachments':[]}
    cell=one(attachment_cells)
    scripts=[''.join(x for x in n.children if isinstance(x,str)) for n in cell.nodes('script')]
    scripts=[s for s in scripts if 'fileList' in s]
    if not scripts:
        result['unresolved_attachments']=True
        return result
    script=one(scripts)
    formula=r"DEXT5UPLOAD\.AddUploadedFile\(temp2\[0\],\s*temp2\[2\],\s*'https://'\s*\+\s*location\.host\s*\+\s*temp2\[3\],\s*temp2\[4\],\s*temp2\[5\],\s*temp2\[6\]\);"
    if not re.search(formula,script) or not all(s in script for s in ('fileList.split("|", 20)','temp1[i].split("^", 20)',"var fileList = '';")):
        result['unresolved_attachments']=True
        return result
    literals=re.findall(r'fileList\s*\+=\s*("(?:[^"\\]|\\.)*")\s*;',script)
    if len(literals)!=len(re.findall(r'fileList\s*\+=',script)):raise ValueError('nonliteral CWMA file data')
    joined=''.join(json.loads(value) for value in literals)
    for old,new in (('&amp;','&'),('&#039;','`'),('&#39;',"'"),('&#40;','('),('&#41;',')')):joined=joined.replace(old,new)
    if not joined:return result  # observed explicitly empty fileList, not an unknown widget
    records=joined.split('|')
    if len(records)>20:raise ValueError('CWMA file list exceeds observed bound')
    seen=set()
    for record in records:
        fields=record.split('^')
        if len(fields)!=7:raise ValueError('invalid CWMA file record')
        file_id,stored,name,path,size,display,widget=fields
        if (not re.fullmatch(r'[1-9][0-9]*',file_id) or not re.fullmatch(r'[1-9][0-9]*',size)
                or not re.fullmatch(r'[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}\.(?:pdf|hwp|hwpx|zip|xlsx?|docx?|pptx?)',stored)
                or not re.fullmatch(r'/upload/boardAdmin/20[0-9]{2}/(?:0[1-9]|1[0-2])/'+re.escape(stored),path)
                or not name or name!=display or widget!='upload1' or re.search(r'[\x00-\x1f]',name)):
            raise ValueError('unsafe or inconsistent CWMA file record')
        target=BASE+path
        if target in seen:raise ValueError('duplicate CWMA attachment')
        seen.add(target);result['attachments'].append({'url':target,'name':name})
    return result
