"""Bounded official response receipts for finishing native LP board adapters.

Read only, observed links only, no publication or selected notice identifiers.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
import subprocess
from urllib.error import HTTPError
from urllib.parse import parse_qs, urljoin, urlsplit, urlencode, urlunsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.lp.src.collect_lp_institution_boards import Session,is_form,load_configs,listing_urls,MAX_BYTES,adapter
from services.lp.src.collect_shared_lp_notices import Document,decode_html
from services.lp.src.collect_lp_original_notices import parse_original
from services.lp.src.discover_lp_original_boards import channels,page_url,listing_links
from services.lp.src import lp_board_adapter_mmaa as mmaa


def dns_observation(host, family):
    """Bound the platform resolver probe without changing official transport."""
    code = ('import socket,json,sys;'
            'print(json.dumps(sorted(set(r[4][0] for r in socket.getaddrinfo('
            'sys.argv[1],443,int(sys.argv[2]),socket.SOCK_STREAM)))))')
    try:
        result = subprocess.run([sys.executable, '-c', code, host, str(family)],
                                capture_output=True, text=True, timeout=5, check=False)
        if result.returncode:
            return {'family': family, 'status': 'resolver_error', 'exit_code': result.returncode}
        return {'family': family, 'status': 'ok', 'addresses': json.loads(result.stdout)}
    except subprocess.TimeoutExpired:
        return {'family': family, 'status': 'timeout'}


def diagnostic_targets(configs):
    """Only first GEPS query and first pages of the first two PCK searches."""
    for institution, count in [('geps', 1), ('pck_pension', 2)]:
        config = configs[institution]
        bounded = {**config, 'pages': 1, 'searches': config['searches'][:count]}
        for url in listing_urls(bounded):
            yield institution, config, url


def inspect_recovery(output):
    report = {'mode': 'geps_pck_read_only_transport_diagnostic', 'responses': [], 'holds': [], 'dns': []}
    output.mkdir(parents=True, exist_ok=True)
    total = 0
    def save(raw, institution, label):
        nonlocal total
        if len(raw) > MAX_BYTES or total + len(raw) > 32 * 1024 * 1024:
            raise ValueError('diagnostic response body budget exceeded')
        total += len(raw)
        digest = hashlib.sha256(raw).hexdigest()
        name = institution + '-' + label + '-' + digest[:16] + '.html'
        (output / name).write_bytes(raw)
        return {'file': name, 'sha256': digest, 'bytes': len(raw)}
    try:
        for institution, config, url in diagnostic_targets(load_configs()):
            if institution == 'geps':
                host = urlsplit(config['listing_url']).hostname
                report['dns'] = [dns_observation(host, family) for family in (0, 2)]
            row = {'institution_id': institution, 'url': url, 'attempts': []}
            report['responses'].append(row)
            session = Session(config)
            for transport, opener in [('system', session.opener), ('ipv4', session.ipv4_opener)]:
                original = opener.open
                def observed(request, *args, _open=original, _transport=transport, **kwargs):
                    attempt = {'transport': _transport}
                    row['attempts'].append(attempt)
                    try:
                        response = _open(request, *args, **kwargs)
                        attempt.update(status=response.status, final_url=response.geturl())
                        return response
                    except HTTPError as error:
                        attempt.update(status=error.code, final_url=error.geturl())
                        attempt.update(save(error.read(MAX_BYTES + 1), institution, 'http-error'))
                        raise
                    except Exception as error:
                        attempt['error_type'] = type(error).__name__
                        raise
                opener.open = observed
            try:
                if total >= 32 * 1024 * 1024:
                    raise ValueError('diagnostic body budget exhausted')
                raw = session(url, config['listing_url'])
                row.update(save(raw, institution, 'listing'))
                row['row_count'] = len(adapter(config).parse_listing(decode_html(raw), url, config))
            except Exception as error:
                row['error'] = str(error)
                report['holds'].append({'institution_id': institution, 'url': url, 'error': str(error)})
            row['dns_ipv4_successes'] = session.dns_ipv4_fetches
    finally:
        (output / 'index.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'responses': len(report['responses']), 'holds': report['holds'], 'bytes': total}, ensure_ascii=False))
    if report['holds']:
        raise SystemExit('Official source diagnostic found failures; receipts retained')


def inspect(output, profile="initial"):
    if profile == 'geps_pck_recovery':
        return inspect_recovery(output)
    output.mkdir(parents=True,exist_ok=True)
    report={'mode':'official_read_only_observed_link_inspection','responses':[],'holds':[]}
    cache={};total=0;sessions={}
    def get(institution,url,config,kind):
        nonlocal total
        if url in cache:return cache[url]
        if total>=32*1024*1024:raise ValueError('inspection total body budget exhausted')
        if institution not in sessions:sessions[institution]=Session(config)
        fetch=sessions[institution]
        raw=fetch(url,config['listing_url']);total+=len(raw)
        if total>32*1024*1024:raise ValueError('inspection total body budget exceeded')
        digest=hashlib.sha256(raw).hexdigest();suffix='.html' if raw.lstrip().startswith(b'<') else '.bin'
        filename=institution+'-'+kind+'-'+digest[:16]+suffix
        (output/filename).write_bytes(raw)
        report['responses'].append({'institution_id':institution,'kind':kind,'url':url,'sha256':digest,'file':filename,'bytes':len(raw)})
        cache[url]=raw;return raw
    configs=channels()
    configs['mmaa']={'institution_id':'mmaa','listing_url':'https://www.mmaa.or.kr/web/contents/notice.do',
                     'detail_path':'/web/contents/notice.do','adapter':'href','search_params':{'schM':'list','schFld':'1','schStr':'위탁운용사','viewCount':'10'},'page_param':'page'}
    selected = ['mmaa'] if profile=='mmaa_files' else ['mmaa','kbiz','kamco','geps'] if profile=='followup' else ['mmaa','kbiz','moel_eif','moel_iaci','kamco','geps']
    for institution in selected:
        config=configs[institution];observed={}
        variants=[config]
        if profile in {'followup','mmaa_files'}:
            terms={'mmaa':('schStr',['블라인드','위탁운용사','출자']),'kbiz':('schTxt',['블라인드','zzlpnomatch20261025']),
                   'kamco':('searchTxt',['PEF','블라인드','출자']),
                   'geps':('srchText',['PEF','사모투자','블라인드'])}
            if institution in terms:
                field,words=terms[institution]
                variants=[{**config,'search_params':{**config['search_params'],field:word}} for word in words]
        urls=[page_url(v,page) for v in variants for page in (1,2)]
        for url in urls:
            try:
                html=decode_html(get(institution,url,config,'listing'))
                root=Document(html).root
                response=next(r for r in report['responses'] if r['url']==url)
                response['forms']=[{'attrs':n.attrs,'inputs':[p.attrs for p in n.nodes('input')],
                                    'selects':[{'attrs':p.attrs,'options':[o.attrs|{'label':o.clean()} for o in p.nodes('option')]} for p in n.nodes('select')]} for n in root.nodes('form')][:5]
                response['scripts']=[urljoin(url,n.attrs['src']) for n in root.nodes('script') if n.attrs.get('src')][:30]
                if institution=='kamco':
                    for node in root.nodes('script'):
                        script_url=urljoin(url,node.attrs.get('src',''))
                        if urlsplit(script_url).hostname=='www.kamco.or.kr' and urlsplit(script_url).path.endswith('/EgovFileUtils.js'):
                            get(institution,script_url,config,'script')
                links=mmaa.parse_listing(html,url,config) if institution=='mmaa' else listing_links(html,url,config)
                for row in links:
                    if institution=='mmaa' and parse_qs(urlsplit(row['url']).query).get('schM')!=['view']:continue
                    if re.search(r'펀드|블라인드|출자|운용사|(?<![A-Za-z])PEF?(?![A-Za-z])',row['title'],re.I):observed.setdefault(row['url'],row)
                response['observed_candidates']=list(observed.values())
            except Exception as error:report['holds'].append({'institution_id':institution,'stage':'listing','url':url,'error':str(error)})
        for row in sorted(observed.values(),key=lambda r: (not bool(re.search(r'블라인드|(?<![A-Za-z])PEF?(?![A-Za-z])',r['title'],re.I)),r['title']))[:8]:
            try:
                html=decode_html(get(institution,row['url'],config,'detail'))
                try:
                    if institution=='mmaa':
                        request=mmaa.attachment_request(html,row['url'],config)
                        if request:
                            get(institution,request,config,'attachment_listing')
                    source=parse_original(html,row['url'])
                    next(r for r in report['responses'] if r['url']==row['url'])['parsed']=source
                    for item in source['attachments'][:2]:
                        if not is_form(item['name']) and urlsplit(item['url']).hostname==urlsplit(config['listing_url']).hostname:
                            get(institution,item['url'],config,'attachment')
                except ValueError as error:next(r for r in report['responses'] if r['url']==row['url'])['parse_error']=str(error)
            except Exception as error:report['holds'].append({'institution_id':institution,'stage':'detail','url':row['url'],'error':str(error)})
    (output/'index.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'responses':len(report['responses']),'holds':report['holds'],'bytes':total},ensure_ascii=False))

if __name__=='__main__':
    inspect(Path(sys.argv[1]),sys.argv[2] if len(sys.argv)>2 else 'initial')
