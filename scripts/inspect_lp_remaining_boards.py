"""Bounded official response receipts for finishing native LP board adapters.

Read only, observed links only, no publication or selected notice identifiers.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urljoin, urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.lp.src.collect_lp_institution_boards import Session,is_form
from services.lp.src.collect_shared_lp_notices import Document,decode_html
from services.lp.src.collect_lp_original_notices import parse_original
from services.lp.src.discover_lp_original_boards import channels,page_url,listing_links


def inspect(output):
    output.mkdir(parents=True,exist_ok=True)
    report={'mode':'official_read_only_observed_link_inspection','responses':[],'holds':[]}
    cache={};total=0;sessions={}
    def get(institution,url,config,kind):
        nonlocal total
        if url in cache:return cache[url]
        if total>=32*1024*1024:raise ValueError('inspection total body budget exhausted')
        fetch=sessions.setdefault(institution,Session(config))
        raw=fetch(url,config['listing_url']);total+=len(raw)
        if total>32*1024*1024:raise ValueError('inspection total body budget exceeded')
        digest=hashlib.sha256(raw).hexdigest();suffix='.html' if raw.lstrip().startswith(b'<') else '.bin'
        filename=institution+'-'+kind+'-'+digest[:16]+suffix
        (output/filename).write_bytes(raw)
        report['responses'].append({'institution_id':institution,'kind':kind,'url':url,'sha256':digest,'file':filename,'bytes':len(raw)})
        cache[url]=raw;return raw
    configs=channels()
    configs['mmaa']={'institution_id':'mmaa','listing_url':'https://www.mmaa.or.kr/web/contents/notice.do',
                     'detail_path':'/web/contents/notice.do','adapter':'href','search_params':{},'page_param':'page'}
    for institution in ['mmaa','kbiz','moel_eif','moel_iaci','kamco','geps']:
        config=configs[institution];observed={}
        for page in range(1,2 if institution=='mmaa' else 3):
            url=config['listing_url'] if institution=='mmaa' else page_url(config,page)
            try:
                html=decode_html(get(institution,url,config,'listing'))
                root=Document(html).root
                response=report['responses'][-1]
                response['forms']=[{'attrs':n.attrs,'inputs':[p.attrs for p in n.nodes('input')],
                                    'selects':[{'attrs':p.attrs,'options':[o.attrs|{'label':o.clean()} for o in p.nodes('option')]} for p in n.nodes('select')]} for n in root.nodes('form')][:5]
                response['scripts']=[urljoin(url,n.attrs['src']) for n in root.nodes('script') if n.attrs.get('src')][:30]
                for row in listing_links(html,url,config):
                    if institution=='mmaa' and parse_qs(urlsplit(row['url']).query).get('schM')!=['view']:continue
                    if re.search(r'블라인드|출자|운용사|(?<![A-Za-z])PEF?(?![A-Za-z])',row['title'],re.I):observed.setdefault(row['url'],row)
                response['observed_candidates']=list(observed.values())
            except Exception as error:report['holds'].append({'institution_id':institution,'stage':'listing','url':url,'error':str(error)})
        for row in list(observed.values())[:6]:
            try:
                html=decode_html(get(institution,row['url'],config,'detail'))
                try:
                    source=parse_original(html,row['url'])
                    report['responses'][-1]['parsed']=source
                    for item in source['attachments'][:2]:
                        if not is_form(item['name']) and urlsplit(item['url']).hostname==urlsplit(config['listing_url']).hostname:
                            get(institution,item['url'],config,'attachment')
                except ValueError as error:report['responses'][-1]['parse_error']=str(error)
            except Exception as error:report['holds'].append({'institution_id':institution,'stage':'detail','url':row['url'],'error':str(error)})
    (output/'index.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'responses':len(report['responses']),'holds':report['holds'],'bytes':total},ensure_ascii=False))

if __name__=='__main__':
    inspect(Path(sys.argv[1]))
