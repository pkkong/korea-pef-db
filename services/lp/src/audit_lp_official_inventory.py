"""Read-only rolling-year official listing inventory, never publication approval.

Keep every fetched listing, including pages with no selected detail. Observed
query boundaries and archive/public matches are evidence, not market recall.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

try:
    from . import collect_lp_institution_boards as boards
    from .audit_lp_discovery_coverage import extract_known, title_scope
    from .lp_board_adapters_pensions import _Document
    from .lp_notice_triage import notice_stage
except ImportError:
    import collect_lp_institution_boards as boards
    from audit_lp_discovery_coverage import extract_known, title_scope
    from lp_board_adapters_pensions import _Document
    from lp_notice_triage import notice_stage

ROOT = Path(__file__).resolve().parents[3]
CORE = {
    'kgrowth': 'https://www.kgrowth.or.kr/notice.asp?str_type=1&tab=1',
    'ktcu': 'https://www.ktcu.or.kr/PPW-CSB-000101',
    'koreapost': 'https://www.kpasset.go.kr/board.es?mid=a10510000000&bid=0041',
    'kexim': 'https://www.koreaexim.go.kr/HPHKBI039M01',
}
HOSTS = {'kgrowth':'kgrowth.or.kr','ktcu':'ktcu.or.kr','koreapost':'kpasset.go.kr',
         'kexim':'koreaexim.go.kr','poba':'poba.or.kr','pmaa':'pmaa.or.kr',
         'tp':'tp.or.kr','cu':'cu.co.kr','kfcc':'kfcc.co.kr','kdb':'kdb.co.kr','ibk':'ibk.co.kr'}


def window(as_of):
    end = date.fromisoformat(as_of)
    return (end-timedelta(days=364)).isoformat(), end.isoformat()


def notice_key(institution, url):
    """Use validated official route/identifier; ignore pagination presentation."""
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname not in {HOSTS.get(institution), 'www.'+HOSTS.get(institution,'')}
            or p.username or p.password or p.port not in {None,443}):
        raise ValueError('official notice identity host mismatch')
    q = parse_qs(p.query, keep_blank_values=True)
    query_routes = {'kgrowth':('/notice_view.asp','idx'), 'koreapost':('/board.es','list_no'),
                    'poba':('/bbs/selectNttDetail','sechBbstSeq'),
                    'pmaa':('/www/1461128463820/bbs.do','bbsIdx'),
                    'tp':('/tp-kr/bbs/i-151/detail.do','ntt_sn'),
                    'cu':('/cu/na/ntt/selectNttInfo.do','nttSn'),
                    'kfcc':('/mgNotice/mgNoticeDetail.do','no'),
                    'ibk':('/cyber/noticeDetailCyber.ibk','srno')}
    if institution in {'ktcu','kexim'}:
        prefix='/PPW-CSB-000101/' if institution=='ktcu' else '/HPHKBI039M01/'
        ident=p.path[len(prefix):] if p.path.startswith(prefix) else ''
    elif institution=='kdb':
        if p.path!='/BOUBUF02N00.act' or len(q.get('_PARM_DATA',[]))!=1:
            raise ValueError('invalid KDB notice identity')
        payload=json.loads(q['_PARM_DATA'][0])
        if payload.get('ITR_BLB_ID')!='STD119' or payload.get('FIRST_MENU_ID','CHBIPR23N00')!='CHBIPR23N00':raise ValueError('KDB board mismatch')
        ident=payload.get('ITR_NAC_ID_MNG_SNO','')
    else:
        route,field=query_routes.get(institution,('',''))
        if p.path!=route or len(q.get(field,[]))!=1:raise ValueError('invalid official notice route')
        if institution=='koreapost' and q.get('bid')!=['0041']:raise ValueError('Korea Post board mismatch')
        if institution=='ibk' and q.get('pageId')!=['IR03010400']:raise ValueError('IBK board mismatch')
        expected={'poba':{'sechBbsSeq':'10'},'cu':{'bbsId':'1020','mi':'100007'},
                  'kgrowth':{'str_type':'1','tab':'1'},'pmaa':{'type':'view'}}
        for board_field,value in expected.get(institution,{}).items():
            if board_field in q and q[board_field]!=[value]:raise ValueError('official notice board mismatch')
        ident=q[field][0]
    if not isinstance(ident,str) or not ident.isdigit():raise ValueError('invalid official notice identifier')
    return institution+':'+ident


def _date(text):
    values={date(*map(int,m)).isoformat() for m in re.findall(r'(?<!\d)(20\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})(?!\d)',text)}
    if len(values)!=1:raise ValueError('missing or conflicting listing date')
    return values.pop()


def core_rows(institution, html, url):
    if '</html>' not in html.lower():raise ValueError('incomplete official listing')
    root=_Document(html).root
    nodes=root.nodes('li') if institution=='ktcu' else root.nodes('div','notice-list-item') if institution=='kexim' else root.nodes('tr')
    rows=[]
    if institution=='koreapost':
        q=parse_qs(urlsplit(url).query)
        for key in ('keySDate','keyEDate'):
            inputs=[n.attrs.get('value') for n in root.nodes('input') if n.attrs.get('name',n.attrs.get('id'))==key]
            if q.get(key) and (len(q[key])!=1 or not inputs or any(value!=q[key][0] for value in inputs)):
                raise ValueError('Korea Post date filter not echoed')
    for node in nodes:
        anchor=None;target=None
        for a in node.nodes('a'):
            href=a.attrs.get('href','')
            if institution=='ktcu':
                m=re.fullmatch(r"javascript:fn_view\('(\d+)'\);?",href)
                if m:target='https://www.ktcu.or.kr/PPW-CSB-000101/'+m[1]
            else:
                candidate=urljoin(url,href)
                try:notice_key(institution,candidate);target=candidate
                except (ValueError,KeyError,TypeError):continue
            if target:anchor=a;break
        if anchor is None:continue
        stamp=_date(node.clean())
        title=anchor.attrs.get('title') or anchor.clean()
        if not title:raise ValueError('missing listing title')
        num=next((n.clean() for n in node.nodes('span','num')), '')
        if institution=='kgrowth':
            cells=[n for n in node.children if getattr(n,'tag',None)=='td']
            num=cells[0].clean() if cells else ''
        pinned=(not num.isdigit()) if institution in {'kgrowth','ktcu'} else (institution=='kexim' and any(n.attrs.get('alt')=='공지' for n in node.nodes('img')))
        rows.append({'source_id':notice_key(institution,target),'title':title,'date':stamp,'url':target,'pinned':pinned})
    if not rows:
        if institution=='ktcu':containers=[n for n in root.nodes('ul') if n.attrs.get('id')=='ulList']
        elif institution=='kexim':containers=list(root.nodes('div','notice-list'))
        else:
            containers=[n for n in root.nodes('table') if {'제목','첨부'}.issubset({h.clean() for h in n.nodes('th')})]
        empty_pattern=r'(?:등록된|검색된|조회된)\s*(?:게시물|게시글|자료|내용|결과)(?:이|가)?\s*없'
        if not containers or not all(re.search(empty_pattern,n.clean()) for n in containers):
            raise ValueError('not a confirmed empty official listing')
    return rows


def _query(url, values):
    p=urlsplit(url);q=dict(parse_qsl(p.query,keep_blank_values=True));q.update(values)
    return urlunsplit(p._replace(query=urlencode(q)))


def core_last_page(institution, html, url):
    if institution=='koreapost':
        try:from .collect_koreapost_program import _listing_last_page
        except ImportError:from collect_koreapost_program import _listing_last_page
        return _listing_last_page(html,url)
    if institution!='ktcu':return None
    root=_Document(html).root
    matches={tuple(map(int,m.groups())) for n in root.nodes('div','sort-tit')
             if (m:=re.fullmatch(r'총\s*([\d,]+)\s*건\s*\(\s*(\d+)\s*/\s*(\d+)\s*페이지\s*\)',n.clean().replace(',','')))}
    if not matches:return None
    if len(matches)!=1:raise ValueError('conflicting KTCU page count')
    total,current,last=matches.pop()
    requested=int(parse_qs(urlsplit(url).query).get('curPage',['1'])[0])
    if current!=requested or last<1 or current<1 or total<0:raise ValueError('invalid KTCU page count')
    return last


def streams(institution, config, start, end):
    if institution in CORE:
        return ['PEF','블라인드'] if institution=='ktcu' else ['']
    return config.get('searches',config.get('search_terms',[]))


def page_url(institution, config, term, page, start, end):
    if institution=='kgrowth':return _query(CORE[institution],{'page':page})
    if institution=='ktcu':return _query(CORE[institution],{'srchKey':'sj','srchText':term,'curPage':page})
    if institution=='koreapost':return _query(CORE[institution],{'keySDate':start,'keyEDate':end,'nPage':page})
    if institution=='kexim':return _query(CORE[institution],{'curPage':page})
    if institution in {'kdb','ibk'}:
        request=boards.banks.listing_requests({**config,'pages':1,'search_terms':[term]})[0]['url']
        if institution=='ibk':return _query(request,{'pageNum':page})
        p=urlsplit(request);payload=json.loads(parse_qs(p.query)['_JSON_'][0]);payload['HEADER_STD_WEB']['REQ_PAGE_NO']=page
        return _query(request,{'_JSON_':json.dumps(payload,ensure_ascii=False)})
    return _query(config['listing_url'],{config['search_param']:term,config['page_param']:page})


def kexim_fetcher():
    try:from .collect_kexim_programs import _official_fetch
    except ImportError:from collect_kexim_programs import _official_fetch
    cookies={}
    return lambda url:_official_fetch(url,cookies)


def known_keys(documents):
    result=set()
    for document in documents:
        for institution,_,url in extract_known(document):
            if url:
                try:result.add(notice_key(institution,url))
                except (ValueError,TypeError,KeyError):pass
    return result


def audit(baseline, archived=(), *, as_of=None, max_pages=20, page_budget=100,
          configs=None, scope=None, fetch_factory=None):
    as_of=as_of or datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    start,end=window(as_of)
    if not 1<=max_pages<=20 or not 1<=page_budget<=200:raise ValueError('inventory safety budget invalid')
    configs=boards.load_configs() if configs is None else configs
    scope=json.loads((ROOT/'data/lp_blind_contest_scope.json').read_text()) if scope is None else scope
    public=known_keys([{'programs':baseline.get('programs',[])}]);stored=known_keys([baseline,*archived])
    report={'as_of':as_of,'window':{'start':start,'end':end,'days':365},'purpose':'Read-only official discovery audit; no publication or market recall claim',
            'market_recall':None,'institutions':[],'receipts':[],'holds':[]}
    names={}
    for path in (ROOT/'data').glob('lp_blind_contest_screening_*.json'):
        names.update({n['institution_id']:n['name'] for n in json.loads(path.read_text()).get('institutions',[])})
    remaining=page_budget;body_bytes=0
    targets=list(dict.fromkeys(scope['confirmed_institution_ids']+scope['priority_verification_ids']))
    for institution in targets:
        config=configs.get(institution) or ({'institution_id':institution,'listing_url':CORE[institution]} if institution in CORE else None)
        entry={'institution_id':institution,'name':names.get(institution,institution),'role':'confirmed' if institution in scope['confirmed_institution_ids'] else 'verification',
               'status':'inventory_not_connected','query_scope':'configured_title_queries' if institution not in {'kgrowth','koreapost','kexim'} else 'board_listing',
               'queries':[],'rows':[],'counts':None,'market_recall':None}
        report['institutions'].append(entry)
        if config is None:continue
        if fetch_factory:fetch=fetch_factory(institution,config)
        elif institution=='kexim':fetch=kexim_fetcher()
        else:
            session=boards.Session(config)
            fetch=lambda url,s=session,c=config:s(url,c['listing_url'])
        observed={};failed=False
        for term in streams(institution,config,start,end):
            query={'term':term,'pages':[],'boundary':'page_limit','minimum_date':None,'maximum_date':None}
            entry['queries'].append(query);seen=set();oldest=None;newest=None
            for page in range(1,max_pages+1):
                if remaining==0:query['boundary']='global_page_budget';break
                url=page_url(institution,config,term,page,start,end);remaining-=1
                try:
                    raw=fetch(url);body_bytes+=len(raw)
                    if body_bytes>32*1024*1024:
                        remaining=0
                        raise ValueError('inventory total body budget exceeded')
                    html=raw.decode('utf-8') if institution=='kdb' else boards.decode_html(raw)
                    receipt={'institution_id':institution,'term':term,'page':page,'url':url,'html':html,
                             'sha256':hashlib.sha256(html.encode()).hexdigest(),'row_count':None}
                    report['receipts'].append(receipt);query['pages'].append(len(report['receipts'])-1)
                    rows=core_rows(institution,html,url) if institution in CORE else boards.adapter(config).parse_listing(html,url,config)
                    receipt['row_count']=len(rows)
                    ids={notice_key(institution,row['url']) for row in rows}
                    if rows and not ids-seen:query['boundary']='repeated_page';break
                    seen.update(ids)
                    for row in rows:
                        stamp=date.fromisoformat(row['date']).isoformat()
                        oldest=min(oldest or stamp,stamp);newest=max(newest or stamp,stamp)
                        if start<=stamp<=end:
                            key=notice_key(institution,row['url']);item={**row,'source_id':key}
                            if key in observed and any(observed[key][k]!=item[k] for k in ('title','date')):raise ValueError('conflicting official listing metadata')
                            observed[key]=item
                    regular=[row for row in rows if not row.get('pinned')]
                    if not rows:query['boundary']='confirmed_empty';break
                    if institution in CORE:
                        last_page=core_last_page(institution,html,url)
                        if last_page is not None and page==last_page:query['boundary']='observed_final_page';break
                    if regular and all(row['date']<start for row in regular):query['boundary']='observed_older_page';break
                except Exception as error:
                    query['boundary']='source_error';failed=True
                    report['holds'].append({'institution_id':institution,'url':url,'error':str(error)})
                    break
            query.update(minimum_date=oldest,maximum_date=newest)
        for key,row in observed.items():
            scope_label,_=title_scope(row['title']);stage=notice_stage(row['title'])
            relevant=bool(re.search(r'펀드|출자|블라인드|운용사|사모|(?<![A-Za-z])PEF?(?![A-Za-z])',row['title'],re.I))
            disposition='public_linked' if key in public else 'archived_unpublished' if key in stored else 'not_in_archive'
            entry['rows'].append({k:row[k] for k in ('source_id','date','title','url')}|{'title_scope':scope_label,'stage':stage,'relevant':relevant,'disposition':disposition})
        entry['rows'].sort(key=lambda r:(r['date'],r['source_id']),reverse=True)
        entry['status']='source_error' if failed else 'query_limit' if any(q['boundary'] in {'page_limit','repeated_page','global_page_budget'} for q in entry['queries']) else 'observed_query_boundary'
        entry['counts']={'observed_recent_rows':len(observed),'relevant_rows':sum(r['relevant'] for r in entry['rows']),
                         'unarchived_relevant':sum(r['relevant'] and r['disposition']=='not_in_archive' for r in entry['rows']),
                         'explicit_pe_blind_unarchived':sum(r['disposition']=='not_in_archive' and r['title_scope']=='pe_blind_title' for r in entry['rows']),
                         'by_disposition':dict(Counter(r['disposition'] for r in entry['rows']))}
        if not any(report['receipts'][i]['row_count'] is not None for q in entry['queries'] for i in q['pages']):
            entry['counts']=None
    report['summary']={'institutions':len(targets),'audited':sum(e['counts'] is not None for e in report['institutions']),
                       'unconnected':sum(e['status']=='inventory_not_connected' for e in report['institutions']),
                       'unmeasured':sum(e['counts'] is None for e in report['institutions']),'pages':len(report['receipts']),
                       'source_errors':len(report['holds']),'unarchived_relevant':sum((e['counts'] or {}).get('unarchived_relevant',0) for e in report['institutions'])}
    candidates=[r for e in report['institutions'] for r in e['rows'] if r['relevant'] and r['disposition']=='not_in_archive']
    report['summary']['unarchived_by_title_scope']=dict(Counter(r['title_scope'] for r in candidates))
    return report


def markdown(report):
    lines=['# 최근 365일 공식 공고 대조',f"기간: {report['window']['start']} ~ {report['window']['end']}",'',
           '공식 목록에서 관측한 자료를 보관 자료·공개 원문 링크와 비교했습니다. 검색어·페이지 상한·미연결 기관과 범위 미확인 자료가 있어 전체 시장 수집률은 계산하지 않습니다. 누락 후보를 자동 공개하지 않습니다.','',
           '자료 수는 사업 수가 아닙니다. 서로 다른 기관의 공동사업 공고도 이 목록에서는 각 공식 문서로 구분합니다.','',
           '| 기관 | 검색 범위 | 탐색 상태 | 기간 내 목록 | 보관에 없는 관련 자료 |','| --- | --- | --- | ---: | ---: |']
    labels={'inventory_not_connected':'공식 목록 대조 미연결','observed_query_boundary':'조회 경계 확인','query_limit':'조회 한도/반복 확인 필요','source_error':'접속/판독 오류'}
    for e in report['institutions']:
        c=e['counts'];search='게시판 목록' if e['query_scope']=='board_listing' else '설정 검색어'
        lines.append(f"| {e['name']} | {search} | {labels[e['status']]} | {c['observed_recent_rows'] if c else '미측정'} | {c['unarchived_relevant'] if c else '미측정'} |")
    scopes=report['summary']['unarchived_by_title_scope']
    lines+=['','## 원문 판독 대상',
            f"보관에 없는 제목 후보: PE 블라인드 명시 {scopes.get('pe_blind_title',0)}건, 범위 미확인 {scopes.get('scope_unconfirmed',0)}건, PE/VC 혼합 {scopes.get('mixed_pe_vc',0)}건. 제목상 범위 외 {scopes.get('outside_policy',0)}건과 VC {scopes.get('vc_explicit',0)}건은 아래에서 제외했습니다. 전체 목록은 JSON에 보존합니다.",
            '국내 PE 블라인드 모집 여부·재공고·후속 단계는 공식 본문 확인이 필요하며 확정 누락 사업 수가 아닙니다.','']
    for e in report['institutions']:
        for r in e['rows']:
            if r['relevant'] and r['disposition']=='not_in_archive' and r['title_scope'] not in {'outside_policy','vc_explicit'}:
                title=r['title'].replace('[','(').replace(']',')').replace('|',' ')
                lines.append(f"- {e['name']} · {r['date']} · {r['stage']} · [{title}]({r['url']})")
    if report['holds']:lines+=['','접속/판독 실패가 있는 기관은 0건으로 해석하지 않습니다.']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--archive',type=Path,action='append',default=[])
    parser.add_argument('--as-of')
    parser.add_argument('--max-pages',type=int,default=20)
    parser.add_argument('--page-budget',type=int,default=100)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--markdown',type=Path,required=True)
    args=parser.parse_args()
    report=audit(json.loads(args.baseline.read_text()),[json.loads(p.read_text()) for p in args.archive],as_of=args.as_of,max_pages=args.max_pages,page_budget=args.page_budget)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.markdown.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');args.markdown.write_text(markdown(report))
    print(json.dumps(report['summary'],ensure_ascii=False))


if __name__=='__main__':main()
