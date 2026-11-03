"""NPS observed public board contracts. No PE scope or publication approval."""
import re
from urllib.parse import urlsplit, parse_qsl, urlencode
try:
    from .collect_shared_lp_notices import Document
    from .lp_board_adapter_geps import one, cls, date
except ImportError:
    from collect_shared_lp_notices import Document
    from lp_board_adapter_geps import one, cls, date

BASE='https://fund.nps.or.kr'
LIST='/impa/dlnginstslctnpbanclist/getOHEF0017M0.do'
PAGE='/impa/dlnginstslctnpbanclist/empty/getOHEF0017M0.do'
DETAIL='/impa/dlnginstslctnpbancdtl/getOHEF0018M0.do'
SCRIPT=BASE+'/js/common_utils.js'


def validate(url,config,detail=False):
    p=urlsplit(url)
    if config.get('institution_id')!='nps' or urlsplit(config['listing_url']).netloc!='fund.nps.or.kr':raise ValueError('wrong NPS config')
    if (p.scheme!='https' or p.netloc!='fund.nps.or.kr' or p.fragment or p.username or p.password or re.search(r'[\x00-\x20\\]',url)):
        raise ValueError('unsafe NPS URL')
    pairs=parse_qsl(p.query,keep_blank_values=True);q=dict(pairs)
    if len(pairs)!=len(q):raise ValueError('duplicate NPS query')
    if detail:
        if p.path!=DETAIL or set(q)!={'pstId','hmpgBbsCd'} or not re.fullmatch(r'ZZ[0-9]{18}',q['pstId']) or not re.fullmatch(r'BS[0-9]{8}',q['hmpgBbsCd']):raise ValueError('invalid NPS detail identity')
    elif p.path!=LIST or set(q)-{'pageIndex','searchGbu','searchText'} or not re.fullmatch(r'[1-9][0-9]{0,3}',q.get('pageIndex','1')) or q.get('searchGbu','') or q.get('searchText',''):
        raise ValueError('unsupported NPS listing request')
    return q


def request_plan(url,config):
    """Logical source URL → observed request; public GET also verified by queued receipts."""
    detail=urlsplit(url).path==DETAIL;q=validate(url,config,detail)
    if detail:
        return {'url':BASE+DETAIL,'method':'POST','encoding':'form','fields':dict(q,pageIndex='1',searchGbu='',searchText='')}
    page=int(q.get('pageIndex','1'))
    if page==1:return {'url':BASE+LIST,'method':'GET','encoding':None,'fields':None}
    return {'url':BASE+PAGE,'method':'POST','encoding':'json','fields':{'pageIndex':page,'searchGbu':'','searchText':''}}


def listing_tree(html,url,config):
    q=validate(url,config)
    if not isinstance(html,str) or len(html)>2_000_000:raise ValueError('invalid NPS HTML size')
    # AJAX pages are observed HTML fragments, not full documents.
    if not html.rstrip().endswith(('</html>','</div>', '<!-- 서브내용 끝 -->')):raise ValueError('incomplete NPS listing')
    root=Document(html).root
    form=one(n for n in root.nodes('form') if n.attrs.get('id')=='searchForm')
    for key,expected in {'pageIndex':q.get('pageIndex','1'),'searchGbu':'','searchText':''}.items():
        if one(n.attrs.get('value','') for n in form.nodes('input') if n.attrs.get('name')==key)!=expected:raise ValueError('NPS page/search echo mismatch')
    table=one(n for n in root.nodes('table') if any('거래기관 선정공고 목록' in c.clean() for c in n.nodes('caption')))
    current=one(n.attrs.get('data-pagenum') for n in root.nodes('a') if cls(n,'num') and cls(n,'current'))
    if current!=q.get('pageIndex','1'):raise ValueError('NPS visible page mismatch')
    total=one(n.clean() for n in root.nodes('span') if cls(n,'total'))
    match=re.fullmatch(r'총\s*([0-9,]+)\s*건',total)
    if not match or int(match[1].replace(',',''))<1:raise ValueError('unverified NPS empty listing')
    return root,table,int(current),int(match[1].replace(',',''))


def last_page(html,url,config):
    root,table,current,total=listing_tree(html,url,config)
    last=(total+9)//10
    controls=[n for n in root.nodes('a') if cls(n,'last') and cls(n,'page')]
    if controls:
        n=one(controls)
        if n.attrs.get('data-pagenum')!=str(last) or not re.search(r'fnc_egov_select_linkPage\('+str(last)+r'\)',n.attrs.get('onclick','')):raise ValueError('NPS last page mismatch')
    elif current!=last:raise ValueError('missing NPS last-page control')
    if current>last:raise ValueError('NPS page overrun')
    return last


def parse_listing(html,url,config):
    root,table,current,total=listing_tree(html,url,config);last_page(html,url,config)
    rows=[];seen=set()
    for tr in table.nodes('tr'):
        cells=list(tr.nodes('td'))
        if not cells:continue
        a=one(a for cell in cells if cls(cell,'title') for a in cell.nodes('a'))
        match=re.fullmatch(r"javascript:fnc_goBbsDetail\('(ZZ[0-9]{18})',\s*'(BS[0-9]{8})'\);?",a.attrs.get('href',''))
        if not match or not a.clean():raise ValueError('invalid NPS row')
        pid,board=match.groups();target=BASE+DETAIL+'?'+urlencode({'pstId':pid,'hmpgBbsCd':board})
        if target in seen:raise ValueError('duplicate NPS row')
        seen.add(target)
        rows.append({'source_id':'nps:'+board+':'+pid,'url':target,'title':a.clean(),'date':date(one(c.clean() for c in cells if cls(c,'date')))})
    if len(rows)!=min(10,total-(current-1)*10):raise ValueError('NPS row count mismatch')
    return rows


def attachment_request(html,url,config):
    validate(url,config,True);root=Document(html).root
    if not any('fncAtchFileDownload(' in a.attrs.get('href','') for a in root.nodes('a')):return None
    if not any(n.attrs.get('src')=='/js/common_utils.js' for n in root.nodes('script')):raise ValueError('missing NPS file controller link')
    return SCRIPT


def parse_detail(html,url,config,*,resolver_script=None):
    validate(url,config,True)
    if len(html)>2_000_000 or '</html>' not in html.lower():raise ValueError('incomplete NPS detail')
    root=Document(html).root
    view=one(n for n in root.nodes('div') if cls(n,'data-view-wrap'))
    title=one(n.clean() for n in view.nodes('strong') if cls(n,'view-title'))
    published=date(one(one(s.clean() for s in li.nodes('span') if cls(s,'data')) for li in view.nodes('li') if any(cls(s,'label') and s.clean()=='등록일' for s in li.nodes('span'))))
    body=one(n.clean() for n in view.nodes('div') if cls(n,'data-view-contents'))
    info=[n.clean() for n in view.nodes('div') if cls(n,'view-info-table')]
    if not title or not body:raise ValueError('missing NPS content')
    result={'title':title,'date':published,'body':'\n'.join(info+[body]).replace('\x00',' '),'attachments':[]}
    if attachment_request(html,url,config):
        if resolver_script is None:
            result['unresolved_attachments']=True
            return result
        formula=r'function\s+fncAtchFileDownload\(atchFileId,\s*atchFileSn\)\s*\{\s*let\s+url\s*=\s*"/fileDown.do\?atchFileId="\s*\+\s*atchFileId\s*\+\s*"&atchFileSn="\s*\+\s*atchFileSn\s*;\s*window.open\(url,\s*"_blank"\);\s*\}'
        if not re.search(formula,resolver_script):raise ValueError('unverified NPS file controller')
        for item in view.nodes('div'):
            if not cls(item,'file-item'):continue
            name=one(n.clean() for n in item.nodes('p') if cls(n,'a-file'))
            a=one(a for a in item.nodes('a') if cls(a,'btn-file-down'))
            m=re.fullmatch(r"javascript:fncAtchFileDownload\('(FL[0-9]+)',\s*'([1-9][0-9]*)'\);?",a.attrs.get('href',''))
            if not m or not name:raise ValueError('invalid NPS file control')
            target=BASE+'/fileDown.do?'+urlencode(dict(zip(('atchFileId','atchFileSn'),m.groups())))
            if any(f['url']==target for f in result['attachments']):raise ValueError('duplicate NPS attachment')
            result['attachments'].append({'url':target,'name':name})
    return result
