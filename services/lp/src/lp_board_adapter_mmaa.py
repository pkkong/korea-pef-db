"""Pure parsers for MMAA's observed official notice board controls."""
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urljoin
try:
    from .lp_board_adapters_pensions import _Document, _Node, _one, _date
    from .collect_lp_original_notices import parse_original
except ImportError:
    from lp_board_adapters_pensions import _Document, _Node, _one, _date
    from collect_lp_original_notices import parse_original

BASE='https://www.mmaa.or.kr/web/contents/notice.do'


def query(url,detail=False):
    p=urlsplit(url);q=parse_qs(p.query,keep_blank_values=True)
    if (p.scheme!='https' or p.hostname!='www.mmaa.or.kr' or p.port not in {None,443}
            or p.username or p.password or p.fragment or p.path!='/web/contents/notice.do'
            or re.search(r'[\x00-\x20\x7f]',url) or any(len(v)!=1 for v in q.values())):
        raise ValueError('MMAA official notice route mismatch')
    if detail:
        if q.get('schM')!=['view'] or not re.fullmatch(r'[0-9]+',q.get('id',[''])[0]):
            raise ValueError('MMAA observed detail identifier missing')
    elif q.get('schM',['list'])!=['list'] or (q.get('id',[''])!=['']):
        raise ValueError('MMAA list route changed to detail')
    return q


def context(html,url,config,detail=False):
    if config.get('institution_id')!='mmaa':raise ValueError('MMAA institution mismatch')
    query(config['listing_url']);q=query(url,detail)
    if '</html>' not in html.lower() or len(html)>3*1024*1024:raise ValueError('Incomplete MMAA HTML')
    root=_Document(html).root
    if not detail:
        scripts='\n'.join(''.join(c for c in n.children if isinstance(c,str)) for n in root.nodes('script'))
        encoded=_one(re.findall(r'var\s+queryString\s*=\s*("(?:[^"\\]|\\.)*")\s*;',scripts),'MMAA query response')
        echoed=parse_qs(json.loads(encoded).lstrip('&'),keep_blank_values=True)
        for key,default in [('schM','list'),('page','1'),('viewCount','10'),('schFld',''),('schStr','')]:
            if echoed.get(key,[default])!=q.get(key,[default]):raise ValueError('MMAA query/page not echoed')
        form=_one((n for n in root.nodes('form') if n.attrs.get('name')=='listForm'),'MMAA search form')
        term=_one((n for n in form.nodes('input') if n.attrs.get('name')=='schStr'),'MMAA search echo')
        if term.attrs.get('value','')!=q.get('schStr',[''])[0]:raise ValueError('MMAA search echo differs')
        if q.get('schStr',[''])[0] and q.get('schFld')!=['1']:raise ValueError('MMAA search is not title only')
    return root,q


def parse_listing(html,url,config):
    root,q=context(html,url,config)
    table=_one(root.nodes('table','box_boardlist'),'MMAA notice table')
    if [n.clean() for n in table.nodes('th')]!=['번호','제목','첨부','날짜','조회수']:
        raise ValueError('MMAA listing headers changed')
    rows={}
    for tr in table.nodes('tr'):
        cells=[n for n in tr.children if isinstance(n,_Node) and n.tag=='td']
        if not cells:continue
        if len(cells)==1 and cells[0].clean()=='등록 된 데이터가 없습니다.':
            continue
        if len(cells)!=5:raise ValueError('MMAA listing columns/empty result not established')
        a=_one(cells[1].nodes('a'),'MMAA title control')
        call=re.fullmatch(r"\s*fn_goView\('([0-9]+)'(?:,\s*'(inotice)')?\)\s*;?\s*",a.attrs.get('onclick',''))
        if not call or not a.clean():raise ValueError('MMAA title/identity control missing')
        ident,notice=call.groups();pinned=cells[0].clean()=='공지'
        if pinned!=bool(notice):raise ValueError('MMAA notice marker differs')
        if not pinned and q.get('schStr',[''])[0] not in a.clean():raise ValueError('MMAA unrelated title search row')
        target=BASE+'?'+urlencode({'schM':'view','id':ident,**({'notice':notice} if notice else {})})
        row={'source_id':'mmaa:'+ident,'url':target,'title':a.clean(),'date':_date(cells[3].clean()),'pinned':pinned}
        if ident in rows:raise ValueError('MMAA duplicate listed identity')
        rows[ident]=row
    if not rows:raise ValueError('MMAA empty response not established')
    return list(rows.values())


def last_page(html,url,config):
    root,q=context(html,url,config)
    pager=_one(root.nodes('div','paging'),'MMAA pager')
    current=_one(pager.nodes('a','active'),'MMAA active page').clean()
    if current!=q.get('page',['1'])[0]:raise ValueError('MMAA active page differs from request')
    last_controls=list(pager.nodes('a','nextAll'))
    if not last_controls:
        summaries=[n.clean() for box in root.nodes('div','no-srch') for n in box.nodes('p')]
        summary=_one(summaries,'MMAA total/page summary')
        count=re.fullmatch(r'총\s*([0-9,]+)\s*건\s*Page\s*:\s*([0-9]+)\s*/\s*([0-9]+)',summary)
        if not count or count[2]!=current:
            raise ValueError('MMAA short pager summary differs')
        total=int(count[1].replace(',',''));last=int(count[3]);size=int(q.get('viewCount',['10'])[0])
        controls=list(pager.nodes('a'))
        values=[int(n.clean()) for n in controls if n.clean().isdigit()]
        if (size not in {10,30,50,100} or last!=max(1,(total+size-1)//size)
                or not 1<=last<=10 or values!=list(range(1,last+1))):
            raise ValueError('MMAA short pager count/range differs')
        for n in controls:
            if n.clean()!=current and n.attrs.get('onclick')!='fn_egov_link_page('+n.clean()+'); return false;':
                raise ValueError('MMAA short page control differs')
        return last
    last=_one(last_controls,'MMAA last page')
    match=re.fullmatch(r'fn_egov_link_page\(([0-9]+)\); return false;',last.attrs.get('onclick',''))
    if not match or int(match[1])<int(current):raise ValueError('MMAA invalid last page control')
    return int(match[1])


def parse_detail(html,url,config,*,attachment_listing=None):
    context(html,url,config,True)
    source=parse_original(html,url)
    if not source.get('date') or not source['body']:raise ValueError('MMAA detail metadata/body missing')
    # Dynamic files remain explicitly visible until their official resolver is
    # independently supported; do not invent a download URL or notice ID.
    if attachment_listing is not None:
        request=attachment_request(html,url,config)
        if not request or len(attachment_listing)>2_000_000:raise ValueError('MMAA unobserved or oversized file list')
        files=json.loads(attachment_listing)
        if not isinstance(files,list) or len(files)>50:raise ValueError('MMAA file list format/limit differs')
        expected=parse_qs(urlsplit(request).query)['fileId'][0]
        observed=set();attachments=[]
        for item in files:
            if not isinstance(item,dict):raise ValueError('MMAA file record differs')
            ident=item.get('fileIdx','');name=item.get('fileName','')
            if (item.get('fileId')!=expected or type(item.get('result')) is not int or item['result']!=1
                    or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',ident) or ident in observed
                    or not isinstance(name,str) or not name.strip() or len(name)>500
                    or item.get('downloadPath')!='/afile/fileDownload/'+ident):
                raise ValueError('MMAA file identity or observed download path differs')
            observed.add(ident)
            attachments.append({'name':name,'url':urljoin(BASE,item['downloadPath'])})
        source.update(attachments=attachments,dynamic_attachments=False)
    source.update(source_id='mmaa:'+query(url,True)['id'][0],url=url)
    return source


def attachment_request(html,url,config):
    root,_=context(html,url,config,True)
    boxes=[n for n in root.nodes('div') if n.attrs.get('data-ax5uploader')]
    if not boxes:return None
    box=_one(boxes,'MMAA attachment box')
    fields={n.attrs.get('name'):n.attrs.get('value') for n in box.nodes('input')}
    ident=fields.get('fileId','')
    if fields.get('useSecurity')!='false' or fields.get('uploadMode')!='db' or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',ident):
        raise ValueError('MMAA files are protected or identity is unsupported')
    if not re.search(r'url:\s*"/afile/fileList.do"\s*,\s*data:"fileId='+re.escape(ident)+r'"',html):
        raise ValueError('MMAA attachment request differs from observed file box')
    return 'https://www.mmaa.or.kr/afile/fileList.do?'+urlencode({'fileId':ident})


def titles_match(left,right):
    return left.translate(str.maketrans({'’':"'",'‘':"'"})).strip()==right.translate(str.maketrans({'’':"'",'‘':"'"})).strip()
