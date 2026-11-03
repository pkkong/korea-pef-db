"""Bounded NH/Suhyup title-search receipts; no DB or publication decisions."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, urlsplit, parse_qsl
from urllib.request import Request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.lp.src.collect_lp_institution_boards import Session
from services.lp.src.collect_shared_lp_notices import Document,decode_html
from services.lp.src import lp_board_adapter_nh as nh
from services.lp.src.lp_attachment_policy import is_submission_form

ROOTS={'nh_central':[nh.BASE+'/ecenter/'+b+'/'+b+'List.do' for b in nh.BOARDS],
       'suhyup':['https://www.suhyup.co.kr/suhyup/223/subview.do']}
TERMS=('펀드','운용사','출자')
MAX_REQUESTS=24
MAX_TOTAL=32*1024*1024
MAX_RESPONSE=12*1024*1024


def safe(url,iid):
    p=urlsplit(url);host=urlsplit(ROOTS[iid][0]).netloc
    if (p.scheme!='https' or p.netloc!=host or p.fragment or p.username or p.password
            or re.search(r'[\x00-\x20\\]',url)):
        raise ValueError('unapproved official source URL')
    return url


def one(items):
    values=list(items)
    if len(values)!=1:raise ValueError('missing or ambiguous form control')
    return values[0]


def search_contract(html,url,iid):
    root=Document(html).root
    form=one(n for n in root.nodes('form') if n.attrs.get('id')=='frm') if iid=='nh_central' else one(n for n in root.nodes('form') if n.attrs.get('name')=='pageForm')
    if form.attrs.get('method','').lower()!='post':raise ValueError('unobserved search method')
    target=safe(urljoin(url,form.attrs.get('action','')),iid)
    fields={}
    allowed=({'intgBsnBlbdGrpC','pageIndex','blbdSqno','searchWrd'} if iid=='nh_central' else
             {'layout','page','srchColumn','srchWrd','bbsClSeq','bbsOpenWrdSeq','rgsBgndeStr','rgsEnddeStr','isViewMine'})
    for node in form.nodes('input'):
        name=node.attrs.get('name')
        if not name:continue
        if name not in allowed or name in fields:raise ValueError('unexpected search field')
        fields[name]=node.attrs.get('value','')
    if iid=='nh_central':
        board,_=nh.validate(url,{'institution_id':iid})
        if fields.get('intgBsnBlbdGrpC')!=nh.BOARDS[board]:raise ValueError('NH group mismatch')
        select=one(n for n in form.nodes('select') if n.attrs.get('name')=='searchCnd')
        if one(n.attrs.get('value') for n in select.nodes('option') if n.clean()=='제목')!='1':raise ValueError('NH title search changed')
        fields.update(searchCnd='1',pageIndex='1',blbdSqno='')
    else:
        search=one(n for n in root.nodes('form') if n.attrs.get('name')=='searchForm')
        select=one(n for n in search.nodes('select') if n.attrs.get('name')=='srchColumn')
        if one(n.attrs.get('value') for n in select.nodes('option') if n.clean()=='제목')!='sj':raise ValueError('Suhyup title search changed')
        if urlsplit(target).path!='/bbs/suhyup/23/artclList.do' or fields.get('isViewMine')!='false':raise ValueError('wrong public Suhyup board')
        fields.update(srchColumn='sj',page='1')
    return target,fields


def samples(html,url,iid,*,format_only=False):
    root=Document(html).root;result=[]
    if iid=='nh_central':
        board,_=nh.validate(url,{'institution_id':iid})
        table=one(n for n in root.nodes('table') if 'list' in n.attrs.get('class','').split())
    else:table=one(n for n in root.nodes('table') if 'board-link-list' in n.attrs.get('class','').split())
    for a in table.nodes('a'):
        title=a.clean()
        if not format_only and not re.search(r'펀드|운용사|출자|PEF?|사모',title,re.I):continue
        if iid=='nh_central':
            match=re.fullmatch(r"fn_select_brdView\('([1-9][0-9]*)'\);",a.attrs.get('onclick',''))
            if not match:continue
            target=nh.BASE+'/ecenter/'+board+'/'+board+'View.do'
            query={'intgBsnBlbdGrpC':nh.BOARDS[board],'blbdSqno':match[1]}
            nh.validate(target+'?'+urlencode(query),{'institution_id':iid},True)
            result.append({'title':title,'url':target,'fields':query,'public_url':target+'?'+urlencode(query)})
        else:
            target=safe(urljoin(url,a.attrs.get('href','')),iid)
            if not re.fullmatch(r'/bbs/suhyup/23/[1-9][0-9]*/artclView\.do',urlsplit(target).path):continue
            result.append({'title':title,'url':target,'fields':None,'public_url':target})
    return result


def inspect(output,fetch=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    report={'mode':'central_contracts_read_only','responses':[],'holds':[]};sessions={};count=0;total=0
    def get(iid,kind,url,fields=None,parent=None):
        nonlocal count,total
        row={'institution_id':iid,'kind':kind,'url':url,'method':'POST' if fields is not None else 'GET','fields':fields,'observed_on':parent}
        report['responses'].append(row)
        try:
            safe(url,iid)
            if count>=MAX_REQUESTS or total>=MAX_TOTAL:raise ValueError('diagnostic budget exhausted')
            count+=1;limit=min(MAX_RESPONSE,MAX_TOTAL-total)
            if fetch:status,final,raw=fetch(url,fields,parent,limit)
            else:
                if iid not in sessions:
                    sessions[iid]=Session({'institution_id':iid,'listing_url':ROOTS[iid][0]})
                    for handler in sessions[iid].opener.handlers:
                        if hasattr(handler,'redirect_request'):
                            original=handler.redirect_request
                            def redirect(req,fp,code,msg,headers,newurl,_original=original,_iid=iid):
                                nonlocal count
                                safe(newurl,_iid)
                                if count>=MAX_REQUESTS:raise ValueError('redirect request budget exhausted')
                                count+=1
                                return _original(req,fp,code,msg,headers,newurl)
                            handler.redirect_request=redirect
                headers={'User-Agent':'Mozilla/5.0 (LP official contract diagnostic)','Accept-Encoding':'identity'}
                if parent:headers['Referer']=safe(parent,iid)
                if fields is not None:headers.update({'Origin':'https://'+urlsplit(url).netloc,'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'})
                request=Request(url,data=urlencode(fields).encode() if fields is not None else None,headers=headers)
                try:
                    with sessions[iid].opener.open(request,timeout=20) as response:status,final,raw=response.status,response.geturl(),response.read(limit+1)
                except HTTPError as error:status,final,raw=error.code,error.geturl(),error.read(limit+1)
            safe(final,iid);total+=len(raw);row.update(status=status,final_url=final)
            if len(raw)>limit:raise ValueError('response byte limit')
            sha=hashlib.sha256(raw).hexdigest();name=iid+'-'+kind+'-'+sha[:16]+'.bin'
            (output/name).write_bytes(raw);row.update(file=name,bytes=len(raw),sha256=sha)
            if status!=200:raise ValueError('official HTTP failure')
            return raw if kind=='attachment' else decode_html(raw)
        except Exception as error:
            row['error_type']=type(error).__name__;report['holds'].append({'institution_id':iid,'kind':kind,'url':url,'error_type':type(error).__name__})
    for iid,roots in ROOTS.items():
        for url in roots:
            html=get(iid,'root',url)
            if html is None:continue
            try:
                target,fields=search_contract(html,url,iid);found={}
                for term in TERMS:
                    query=dict(fields,**({'searchWrd':term} if iid=='nh_central' else {'srchWrd':term}))
                    body=get(iid,'search',target,query,url)
                    if body is None:continue
                    for sample in samples(body,url,iid):found.setdefault(sample['public_url'],sample)
                ranked=sorted(found.values(),key=lambda n:(not bool(re.search(r'PEF?|사모|위탁운용사',n['title'],re.I)),n['title']))
                if not ranked:
                    report['holds'].append({'institution_id':iid,'kind':'sample','url':url,'reason':'no_matching_title_in_first_search_pages'})
                    ranked=samples(html,url,iid,format_only=True)[:1]
                    if not ranked:continue
                    report['holds'][-1]['public_format_sample_only']=True
                sample=ranked[0]
                body=get(iid,'detail',sample['url'],sample['fields'],url)
                if body is None:continue
                if sample['fields'] is not None:get(iid,'detail_get',sample['public_url'],parent=url)
                controls=[];downloads=[]
                for a in Document(body).root.nodes('a'):
                    label=a.clean();href=a.attrs.get('href','');onclick=a.attrs.get('onclick','')
                    if not re.search(r'공고|선정|제안요청|다운로드|\.pdf|\.hwp|fileDown|download',label+' '+href+' '+onclick,re.I):continue
                    if is_submission_form(label):continue
                    if href and not href.startswith(('#','javascript:')):
                        try:link=safe(urljoin(sample['public_url'],href),iid)
                        except ValueError:continue
                        if re.search(r'\.pdf|\.hwpx?|fileDown|download',link,re.I):downloads.append({'url':link,'name':label})
                    elif onclick or href.startswith('javascript:'):controls.append({'name':label,'href':href,'onclick':onclick})
                report['responses'][-1]['observed_attachment_controls']=controls[:15]
                for item in list({d['url']:d for d in downloads}.values())[:1]:get(iid,'attachment',item['url'],parent=sample['public_url'])
            except Exception as error:report['holds'].append({'institution_id':iid,'kind':'contract','url':url,'error_type':type(error).__name__})
    report.update(requests=count,bytes=total)
    (output/'index.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    report=inspect(parser.parse_args().output)
    print(json.dumps({'requests':report['requests'],'bytes':report['bytes'],'holds':report['holds']},ensure_ascii=False))
    if any(h.get('error_type') for h in report['holds']):raise SystemExit(1)
