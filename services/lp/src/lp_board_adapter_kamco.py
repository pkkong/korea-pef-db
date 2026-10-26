"""Pure KAMCO notice parsing, preserving unresolved dynamic attachments."""
import re
from urllib.parse import urlsplit,urlencode
try:
    from .lp_board_adapter_geps import one,cls,tree,query,date,search
except ImportError:
    from lp_board_adapter_geps import one,cls,tree,query,date,search
BASE='https://www.kamco.or.kr'
def validate(url,config,detail=False):
    if config.get('institution_id')!='kamco':raise ValueError('wrong institution')
    p,q=query(url,'www.kamco.or.kr');c,cq=query(config['listing_url'],'www.kamco.or.kr')
    if c.path!='/portal/bbs/list.do' or p.path!=('/portal/bbs/view.do' if detail else '/portal/bbs/list.do'):raise ValueError('wrong KAMCO route')
    if any(q.get(k)!=v or cq.get(k)!=v for k,v in {'ptIdx':'380','mId':'0701010000'}.items()):raise ValueError('wrong KAMCO board')
    if set(q)-{'ptIdx','mId','page','searchType','searchTxt','bIdx'}:raise ValueError('wrong KAMCO query')
    if detail and not re.fullmatch('[0-9]+',q.get('bIdx','')):raise ValueError('missing KAMCO detail id')
    if not detail and ('bIdx' in q or not q.get('page','1').isdigit()):raise ValueError('wrong KAMCO page')
    return q

def parse_listing(html,url,config):
    q=validate(url,config);root=tree(html);search(root,q,config,('searchType','searchTxt'))
    result=[];seen=set()
    for tr in root.nodes('tr'):
        links=[a for a in tr.nodes('a') if 'goTo.view' in a.attrs.get('onclick','')]
        if not links:continue
        a=one(links);m=re.fullmatch(r"goTo\.view\('list','([0-9]+)','380','0701010000'\);\s*return false;",a.attrs['onclick'])
        if not m:raise ValueError('unknown KAMCO detail control')
        ident=m[1]
        if ident in seen:raise ValueError('duplicate KAMCO notice')
        seen.add(ident);title=a.clean()
        if not title:raise ValueError('missing title')
        result.append({'source_id':'kamco:'+ident,'url':BASE+'/portal/bbs/view.do?'+urlencode({'bIdx':ident,'ptIdx':'380','mId':'0701010000'}),'title':title,'date':date(one(n.clean() for n in tr.nodes('td') if cls(n,'list_date')))})
    tables=[n for n in root.nodes('table') if cls(n,'board-table')]
    empty=any(n.clean()=='등록된 게시물이 없습니다.' for t in tables for n in t.nodes('td'))
    if empty and result:raise ValueError('conflicting KAMCO empty marker')
    if not result:
        count=' '.join(n.clean() for n in root.nodes('li') if cls(n,'board-page-list'))
        if not empty or not re.search(r'전체\s+0건',count) or q.get('page','1')!='1':raise ValueError('unconfirmed KAMCO empty or page overrun')
    last_page(html,url,config);return result

def last_page(html,url,config):
    q=validate(url,config);root=tree(html);search(root,q,config,('searchType','searchTxt'))
    values=[n.clean() for n in root.nodes('li') if cls(n,'board-page-list')]
    text=' '.join(values);m=re.search(r'페이지\s+([0-9]+)\s*/\s*([0-9]+)',text)
    if not m or m[1]!=q.get('page','1') or int(m[2])<int(m[1]):raise ValueError('KAMCO pagination metadata missing or inconsistent')
    return int(m[2])

def parse_detail(html,url,config,*,resolver_script=None):
    q=validate(url,config,True);root=tree(html)
    if one(n.attrs.get('value') for n in root.nodes('input') if n.attrs.get('id')=='bIdx')!=q['bIdx']:raise ValueError('KAMCO detail identity mismatch')
    table=one(n for n in root.nodes('table') if cls(n,'table-view'))
    title=one(n.clean() for n in table.nodes('td') if n.attrs.get('date-label')=='제목')
    published=date(one(n.clean() for n in table.nodes('td') if n.attrs.get('date-label')=='등록일'))
    tbody=one(table.nodes('tbody'));content=one(n for n in tbody.nodes('td') if n.attrs.get('colspan')=='4' and not cls(n,'grey-box'))
    body=content.clean().replace('\x00',' ')
    if not title or not body:raise ValueError('missing KAMCO content')
    unresolved=[]
    for a in root.nodes('a'):
        control=a.attrs.get('onclick','')
        if 'fn_egov_downFile' not in control:continue
        m=re.fullmatch(r"fn_egov_downFile\('(FILE_[0-9]+)','([0-9]+)'\);\s*return false;",control)
        if not m:raise ValueError('unknown KAMCO attachment control')
        unresolved.append({'name':a.clean(),'file_id':m[1],'file_sn':m[2],'resolver_script':BASE+'/common/js/common/EgovFileUtils.js'})
    if any(n.attrs.get('id')=='updateFileList' for n in root.nodes()) and not unresolved:raise ValueError('KAMCO dynamic attachment list unresolved')
    files=[]
    if unresolved and resolver_script is not None:
        if not attachment_request(html,url,config):raise ValueError('unobserved KAMCO resolver')
        _resolver(html,resolver_script)
        files=[{'name':a['name'],'url':BASE+'/cmm/fms/FileDown.do?'+urlencode({'atchFileId':a['file_id'],'fileSn':a['file_sn']})} for a in unresolved]
        unresolved=[]
    return {'title':title,'date':published,'body':body,'attachments':files,
            'dynamic_attachments':bool(unresolved),'unresolved_attachments':unresolved,
            'attachment_holds':[{'reason':'Observed dynamic download control requires official resolver','file_id':a['file_id']} for a in unresolved]}


def attachment_request(html,url,config):
    validate(url,config,True);root=tree(html)
    controls=[n for n in root.nodes('a') if 'fn_egov_downFile' in n.attrs.get('onclick','')]
    if not controls:return None
    links={n.attrs.get('src') for n in root.nodes('script')}
    if '/common/js/common/EgovFileUtils.js' not in links:raise ValueError('KAMCO attachment resolver script not observed')
    return BASE+'/common/js/common/EgovFileUtils.js'


def _resolver(html,script):
    if not isinstance(script,str) or len(script)>200000:raise ValueError('invalid KAMCO resolver script')
    inline=re.findall(r'<script(?:\s[^>]*)?>([\s\S]*?)</script>',html,re.I)
    contexts=re.findall(r'''["']contextPath["']\s*:\s*["']([^"']*)["']''','\n'.join(inline))
    if contexts!=[''] or any(re.search(r'G_CONTEXT_PATH\s*=',v) for v in inline):raise ValueError('KAMCO download context is not verified empty')
    signature='function fn_egov_downFile(atchFileId, fileSn)'
    if script.count(signature)!=1:raise ValueError('KAMCO resolver function differs')
    function=script.split(signature,1)[1].split('/**',1)[0]
    opens=re.findall(r'window\.open\((.*?)\);',function,re.S)
    normalized=[re.sub(r'\s+','',v) for v in opens]
    suffix=' + "/cmm/fms/FileDown.do?atchFileId="+atchFileId+"&fileSn="+fileSn'
    expected=[re.sub(r'\s+','',p+suffix) for p in ('window.G_CONTEXT_PATH','yh.contextPath')]
    if normalized!=expected or 'if(window.G_CONTEXT_PATH != null)' not in function:raise ValueError('KAMCO resolver download formula differs')
