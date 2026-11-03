"""Queued, anonymous NPS/CWMA request-contract receipts; no publication decisions."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit, urlencode, unquote
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.lp.src.collect_lp_institution_boards import Session, is_form
from services.lp.src import lp_board_adapter_cwma as cwma
from services.lp.src.collect_shared_lp_notices import Document, decode_html
from scripts.inspect_lp_remaining_boards import PENDING_ROOTS

MAX_REQUESTS = 14
MAX_RESPONSE = 3 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024


def safe_url(url, institution):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.netloc != urlsplit(PENDING_ROOTS[institution]).netloc
            or p.username or p.password or p.fragment
            or re.search(r'[\x00-\x20\\]', url)
            or any(x in {'.', '..'} for x in unquote(p.path).split('/'))):
        raise ValueError('unsafe official diagnostic URL')
    return url


def one(items):
    values = list(items)
    if len(values) != 1:
        raise ValueError('missing or ambiguous observed control')
    return values[0]


def form_fields(root, name, allowed):
    form = one(n for n in root.nodes('form') if n.attrs.get('id') == name or n.attrs.get('name') == name)
    if form.attrs.get('method', '').lower() != 'post':
        raise ValueError('unobserved form method')
    result = {}
    for node in form.nodes('input'):
        key = node.attrs.get('name', '')
        if key not in allowed or key in result or node.attrs.get('type', '').lower() != 'hidden':
            raise ValueError('unrecognized form field')
        result[key] = node.attrs.get('value', '')
    if set(result) != set(allowed):
        raise ValueError('missing form fields')
    return form, result


def contracts(html, url, institution):
    """Return observed POST controls. Detail sample selection is not PE approval."""
    safe_url(url, institution)
    if '</html>' not in html.lower():
        raise ValueError('incomplete listing HTML')
    root = Document(html).root
    if institution == 'nps':
        form, fields = form_fields(root, 'searchForm', {'pstId','hmpgBbsCd','pageIndex','searchGbu','searchText'})
        page_path = one(path for path in re.findall(r'\$\.httpAjax\("([^"\n]+)"\s*,\s*jsonData', html) if '/dlnginstslctnpbanclist/' in path)
        detail_path = one(re.findall(r'form\.action\s*=\s*"([^"\n]+)"', html))
        if page_path != '/impa/dlnginstslctnpbanclist/empty/getOHEF0017M0.do' or detail_path != '/impa/dlnginstslctnpbancdtl/getOHEF0018M0.do':
            raise ValueError('unexpected observed NPS route')
        if not re.search(r'fnc_egov_select_linkPage\(2\)', html) or 'form.submit()' not in html:
            raise ValueError('missing NPS paging or submit control')
        rows = []
        for a in root.nodes('a'):
            match = re.fullmatch(r"javascript:fnc_goBbsDetail\('([A-Z0-9]+)',\s*'([A-Z0-9]+)'\);?", a.attrs.get('href',''))
            if match and re.search(r'국내.*(?:사모|PEF)', a.clean(), re.I):
                rows.append((a.clean(), match.groups()))
        if not rows:
            raise ValueError('no domestic private-fund detail sample')
        title, (pid, board) = rows[0]
        detail_fields = dict(fields, pstId=pid, hmpgBbsCd=board)
        script = one(urljoin(url,n.attrs['src']) for n in root.nodes('script')
                     if urlsplit(n.attrs.get('src','')).path == '/js/common_utils.js')
        return {'page': {'url':safe_url(urljoin(url,page_path),institution), 'fields':{'pageIndex':2,'searchGbu':fields['searchGbu'],'searchText':fields['searchText']}, 'encoding':'json'},
                'detail':{'url':safe_url(urljoin(url,detail_path),institution),'fields':detail_fields,'encoding':'form','title':title},
                'script':safe_url(script,institution)}
    if institution != 'cwma':
        raise ValueError('unsupported institution')
    form, fields = form_fields(root,'menuForm', {'menuNo','contentsNo','boardConfigNo','moveMenu','separator','actionVal','page','boardCategoryNo','boardWriterAddress2','menuLayout','searchValue','searchCategory'})
    pager = one(n for n in root.nodes('div') if n.attrs.get('id') == 'paging')
    paging = []
    for a in pager.nodes('a'):
        match = re.fullmatch(r"javascript:goCategory\('(/board.do\?boardConfigNo=([0-9]+))','([0-9]+)',\s*2,\s*'([0-9]+)'\)", a.attrs.get('href',''))
        if match:paging.append(match.groups())
    link, board, menu, category = one(set(paging))
    for snippet in ('document.menuForm.method = "POST"','document.menuForm.page.value = pageNo','document.menuForm.submit()'):
        if snippet not in html:raise ValueError('missing observed CWMA paging implementation')
    page_fields = dict(fields,boardConfigNo=board,menuNo=menu,page='2',boardCategoryNo=category)
    target=safe_url(urljoin(url,'/board.do'),institution)
    return {'page':{'url':target,'fields':page_fields,'encoding':'form'},
            'detail':cwma_detail(html,url,board,menu,category),
            'board_context':[board,menu,category]}


def cwma_detail(html,url,board,menu,category):
    root=Document(html).root
    view, vf = form_fields(root,'boardViewForm', {'boardConfigNo','menuNo','action','boardNo','pageNo','menuLayout','searchCategory','searchValue','boardCategoryNo'})
    if view.attrs.get('action') != '/board.do' or 'document.boardViewForm.submit()' not in html:
        raise ValueError('unexpected CWMA detail action')
    table = one(n for n in root.nodes('table') if 'board-list' in n.attrs.get('class','').split())
    rows=[]
    for a in table.nodes('a'):
        match=re.fullmatch(r"javascript:goView\('([0-9]+)','([0-9]+)','(view)','([0-9]+)'\)",a.attrs.get('href',''))
        if match and re.search(r'국내.*(?:사모|PEF)',a.clean(),re.I):rows.append((a.clean(),match.groups()))
    if not rows:return None
    title,(db,dm,action,identifier)=rows[0]
    if (db,dm)!=(board,menu) or vf['boardCategoryNo']!=category:raise ValueError('CWMA board mismatch')
    detail_fields=dict(vf,boardConfigNo=db,menuNo=dm,action=action,boardNo=identifier,pageNo='1')
    return {'url':safe_url(urljoin(url,'/board.do'),'cwma'),'fields':detail_fields,'encoding':'form','title':title}


def nps_downloads(html,url,controller):
    # Entire literal function body is verified, never evaluated.
    formula=r'function\s+fncAtchFileDownload\(atchFileId,\s*atchFileSn\)\s*\{\s*let\s+url\s*=\s*"/fileDown.do\?atchFileId="\s*\+\s*atchFileId\s*\+\s*"&atchFileSn="\s*\+\s*atchFileSn\s*;\s*window.open\(url,\s*"_blank"\);\s*\}'
    if not re.search(formula,controller):raise ValueError('unverified NPS download controller')
    root=Document(html).root
    if not any(urlsplit(n.attrs.get('src','')).path=='/js/common_utils.js' for n in root.nodes('script')):
        raise ValueError('missing observed NPS controller script')
    downloads=[]
    for item in root.nodes('div'):
        if 'file-item' not in item.attrs.get('class','').split():continue
        name=one(n.clean() for n in item.nodes('p') if 'a-file' in n.attrs.get('class','').split())
        match=one(re.fullmatch(r"javascript:fncAtchFileDownload\('([A-Z0-9]+)',\s*'([0-9]+)'\);?",a.attrs.get('href','')) for a in item.nodes('a') if 'btn-file-down' in a.attrs.get('class','').split())
        if not match:raise ValueError('malformed NPS file control')
        # RFP bundles may contain forms, but diagnostic stores bytes only.
        if not re.search(r'공고|제안요청|RFP',name,re.I):continue
        target=safe_url(urljoin(url,'/fileDown.do?'+urlencode(dict(zip(('atchFileId','atchFileSn'),match.groups())))),'nps')
        downloads.append({'url':target,'name':name})
    return downloads[:2]


def attachment_controls(html, url, institution):
    """Only literal first-party file links; dynamic controls remain unresolved."""
    root=Document(html).root
    choices=[]; unresolved=[]
    for a in root.nodes('a'):
        label=a.clean(); href=a.attrs.get('href',''); onclick=a.attrs.get('onclick','')
        if not re.search(r'첨부|공고|선정|제안요청|\.pdf|\.hwp|download|filedown',label+' '+href+' '+onclick,re.I):continue
        if is_form(label) or re.search(r'양식|서식|\.zip\b',label+' '+href,re.I):continue
        if not href.startswith(('javascript:', '#')) and href:
            try:target=safe_url(urljoin(url,href),institution)
            except ValueError:target=None
            if target and re.search(r'\.pdf|\.hwpx?|download|filedown',target,re.I) and re.search(r'공고|선정|제안요청|\.pdf|\.hwpx?',label,re.I):
                choices.append({'url':target,'name':label});continue
        if onclick or href.startswith('javascript:'):
            unresolved.append({'label':label[:200],'href':href[:500],'onclick':onclick[:500]})
    unique={item['url']:item for item in choices}
    return {'attachment':next(iter(unique.values()),None),'unresolved_controls':unresolved[:20]}


def inspect(output, fetch=None):
    """fetch(method,url,fields,encoding,limit) is injectable for offline tests."""
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    report={'mode':'pending_contracts_read_only','responses':[],'holds':[]}
    requests=0;total=0;sessions={}
    def capture(iid,kind,url,fields=None,encoding=None,parent=None):
        nonlocal requests,total
        method='POST' if fields is not None else 'GET'
        row={'institution_id':iid,'kind':kind,'url':url,'method':method,'request_fields':fields,'encoding':encoding,'observed_on':parent}
        report['responses'].append(row)
        try:
            safe_url(url,iid)
            if requests>=MAX_REQUESTS or total>=MAX_TOTAL:raise ValueError('request or byte budget exhausted')
            requests+=1;limit=min(MAX_RESPONSE,MAX_TOTAL-total)
            if fetch:status,final,raw=fetch(method,url,fields,encoding,limit)
            else:
                if iid not in sessions:
                    session=Session({'institution_id':iid,'listing_url':PENDING_ROOTS[iid]})
                    for handler in session.opener.handlers:
                        if hasattr(handler,'redirect_request'):
                            original=handler.redirect_request
                            def redirect(req,fp,code,msg,headers,newurl,_original=original,_iid=iid):
                                nonlocal requests
                                safe_url(newurl,_iid)
                                if requests>=MAX_REQUESTS:raise ValueError('redirect budget exhausted')
                                requests+=1
                                return _original(req,fp,code,msg,headers,newurl)
                            handler.redirect_request=redirect
                    sessions[iid]=session
                headers={'User-Agent':'Mozilla/5.0 (LP official contract diagnostic)','Accept-Encoding':'identity'}
                if parent:
                    safe_url(parent,iid)
                    headers['Referer']=parent
                body=None
                if fields is not None:
                    origin=urlsplit(url)
                    headers['Origin']=origin.scheme+'://'+origin.netloc
                    body=(json.dumps(fields,ensure_ascii=False) if encoding=='json' else urlencode(fields)).encode('utf-8')
                    headers['Content-Type']='application/json;' if encoding=='json' else 'application/x-www-form-urlencoded; charset=UTF-8'
                    if encoding=='json':headers['Accept']='application/json'
                request=Request(url,data=body,headers=headers,method=method)
                try:
                    with sessions[iid].opener.open(request,timeout=20) as r:status,final,raw=r.status,r.geturl(),r.read(limit+1)
                except HTTPError as e:status,final,raw=e.code,e.geturl(),e.read(limit+1)
            safe_url(final,iid);row.update(status=status,final_url=final);total+=len(raw)
            if len(raw)>limit:raise ValueError('response budget exceeded')
            sha=hashlib.sha256(raw).hexdigest();name=f'{iid}-{kind}-{sha[:16]}.bin'
            (output/name).write_bytes(raw);row.update(file=name,sha256=sha,bytes=len(raw))
            if status!=200:raise ValueError('official HTTP failure')
            return ('' if kind=='attachment' else decode_html(raw)),final,row
        except Exception as e:
            row['error_type']=type(e).__name__
            report['holds'].append({'institution_id':iid,'kind':kind,'url':url,'error_type':type(e).__name__})
            return None
    for iid in ('nps','cwma'):
        root=capture(iid,'root',PENDING_ROOTS[iid])
        if not root:continue
        html,url,row=root
        try:
            plan=contracts(html,url,iid);row['observed_contracts']=plan
            if plan.get('script'):
                script=capture(iid,'controller',plan['script'],parent=url)
                if not script or not all(s in script[0] for s in ('type        : "POST"','JSON.stringify(data)','application/json;')):
                    raise ValueError('NPS JSON POST controller not confirmed')
            page=plan['page']
            page_result=capture(iid,'page',page['url'],page['fields'],page['encoding'],url)
            if iid=='nps' and re.search(r'fnc_egov_select_linkPage\(3\)',html):
                # Native rolling-year discovery reached a legacy third page.
                # Capture its observed page control without guessing old IDs.
                capture(iid,'legacy_page',page['url'],dict(page['fields'],pageIndex=3),page['encoding'],url)
            if not plan['detail'] and iid=='cwma' and page_result:
                plan['detail']=cwma_detail(page_result[0],page_result[1],*plan['board_context'])
            if not plan['detail']:
                report['holds'].append({'institution_id':iid,'kind':'detail','reason':'no_domestic_private_fund_sample_in_two_pages'})
                continue
            req=plan['detail']
            result=capture(iid,'detail',req['url'],req['fields'],req['encoding'],url)
            if result:
                if iid=='nps':
                    public_url=req['url']+'?'+urlencode({key:req['fields'][key] for key in ('pstId','hmpgBbsCd')})
                    capture(iid,'detail_get',public_url,parent=url)
                else:
                    public_url=req['url']+'?'+urlencode({key:req['fields'][key] for key in (*cwma.BOARD,'action','boardNo')})
                    capture(iid,'detail_get',public_url,parent=url)
                selection=attachment_controls(result[0],result[1],iid)
                downloads=(nps_downloads(result[0],result[1],script[0]) if iid=='nps' else
                           [a for a in cwma.parse_detail(result[0],public_url,{'institution_id':'cwma','listing_url':PENDING_ROOTS['cwma']})['attachments'] if not is_form(a['name'])][:1])
                result[2]['observed_downloads']=dict(selection,downloads=downloads)
                for download in downloads:
                    capture(iid,'attachment',download['url'],parent=result[1])
                if not downloads:
                    report['holds'].append({'institution_id':iid,'kind':'attachment','reason':'no_unambiguous_literal_offering_link','unresolved_controls':selection['unresolved_controls']})

        except Exception as e:
            report['holds'].append({'institution_id':iid,'kind':'contract','error_type':type(e).__name__})
    report.update(requests=requests,bytes=total)
    (output/'index.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=inspect(args.output)
    print(json.dumps({'requests':report['requests'],'bytes':report['bytes'],'holds':len(report['holds'])}))
    if any(h.get('error_type') for h in report['holds']):raise SystemExit(1)

if __name__=='__main__':main()
