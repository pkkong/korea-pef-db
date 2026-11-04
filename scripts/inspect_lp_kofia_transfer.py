"""At most seven queued public response receipts; no DB, cookies, or publication."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit, parse_qsl
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.lp.src.collect_shared_lp_notices import _complete_html, parse_listing

CASES=(('kofia_17','identity'),('kofia_17','compressed'),('kofia_212','identity'))
ROOT='https://www.kofia.or.kr/brd/m_{}/list.do'
MAX_BYTES=3*1024*1024
MAX_REQUESTS=7


def safe_listing(url, channel, page=None):
    p=urlsplit(url)
    if (p.scheme!='https' or p.netloc!='www.kofia.or.kr' or p.fragment
            or p.path!=urlsplit(ROOT.format(channel.split('_')[1])).path
            or p.username or p.password or any(ord(c)<33 for c in url) or '\\' in url):
        raise ValueError('unapproved official listing URL')
    pairs=parse_qsl(p.query,keep_blank_values=True);query=dict(pairs)
    if len(query)!=len(pairs) or (page is not None and query.get('page')!=str(page)):
        raise ValueError('ambiguous official pagination')
    return url


def inspect(output,run=subprocess.run):
    output=Path(output);output.mkdir(parents=True,exist_ok=True);rows=[];observed_pages=None;parent=None
    def capture(channel,encoding,url,name,http='1.1',observed_on=None):
        safe_listing(url,channel)
        if len(rows)>=MAX_REQUESTS:raise ValueError('diagnostic request limit')
        body=output/(name+'.html');headers=output/(name+'.headers.tmp')
        # A reused output directory must not turn a missing transfer into old bytes.
        body.unlink(missing_ok=True);headers.unlink(missing_ok=True)
        command=['curl','--disable','--fail','--silent','--show-error','--http'+http,
                 '--user-agent','Mozilla/5.0 (LP public notice collector)',
                 '--header','Connection: close','--max-time','25','--max-filesize',str(MAX_BYTES),
                 '--proto','=https','--proto-redir','=https','--output',str(body),
                 '--dump-header',str(headers),'--write-out','%{http_code}']
        command+=['--compressed'] if encoding=='compressed' else ['--header','Accept-Encoding: identity']
        row={'source_channel':channel,'encoding':encoding,'http_version':http,'url':url,
             'observed_on':observed_on,'transport_ok':False,'complete_html':False,'usable_listing':False}
        rows.append(row);pages={}
        try:
            try:
                result=run(command+[url],capture_output=True,timeout=30,check=False)
                row.update(curl_exit=result.returncode,status=result.stdout.decode('ascii').strip())
                row['transport_ok']=result.returncode==0 and row['status']=='200'
            except (OSError,ValueError,subprocess.SubprocessError) as error:
                row['error_type']=type(error).__name__
            raw=b''
            if body.exists():
                with body.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:
                body.unlink(missing_ok=True)
                raise ValueError('diagnostic response byte limit')
            row.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            if body.exists():row['file']=body.name
            # Keep framing metadata only; never persist cookies or opaque headers.
            metadata={}
            if headers.exists():
                with headers.open(errors='replace') as stream:header_text=stream.read(64*1024)
                for line in header_text.splitlines():
                    key,separator,value=line.partition(':')
                    if separator and key.lower() in {'content-length','transfer-encoding','content-encoding','content-type','connection'}:
                        metadata[key.lower()]=value.strip()[:200]
            row['headers']=metadata
            try:html=_complete_html(raw,'diagnostic listing');row['complete_html']=True
            except ValueError:html=None
            if html is not None:
                try:
                    found,pages=parse_listing(html,url,channel)
                    row['row_count']=len(found)
                    row['usable_listing']=row['transport_ok'] and bool(found)
                except ValueError as error:row['parse_error_type']=type(error).__name__
        except (OSError,ValueError) as error:
            row['error_type']=type(error).__name__;row['usable_listing']=False
        finally:headers.unlink(missing_ok=True)
        return row,pages

    for channel,encoding in CASES:
        url=ROOT.format(channel.split('_')[1])
        row,pages=capture(channel,encoding,url,channel+'-'+encoding)
        if channel=='kofia_17' and observed_pages is None and row['usable_listing']:
            observed_pages={}
            parent={'url':url,'sha256':row['sha256'],'file':row['file']}
            for number in (2,3):
                if number not in pages:continue
                try:observed_pages[number]=safe_listing(pages[number],channel,number)
                except ValueError:row.setdefault('pagination_holds',[]).append({'page':number,'reason':'unsafe_or_ambiguous_observed_link'})
    for number,url in sorted((observed_pages or {}).items()):
        for http in ('1.1','1.0'):
            capture('kofia_17','identity',url,f'kofia_17-page{number}-identity-http{http}',http, parent)
    report={'mode':'kofia_transfer_read_only','requests':len(rows),'max_requests':MAX_REQUESTS,'responses':rows}
    (output/'index.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    report=inspect(parser.parse_args().output)
    print(json.dumps(report,ensure_ascii=False))
