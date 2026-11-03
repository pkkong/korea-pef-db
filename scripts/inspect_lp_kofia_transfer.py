"""Three queued public response receipts; no DB, cookies, or publication."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.lp.src.collect_shared_lp_notices import _complete_html, parse_listing

CASES=(('kofia_17','identity'),('kofia_17','compressed'),('kofia_212','identity'))
ROOT='https://www.kofia.or.kr/brd/m_{}/list.do'
MAX_BYTES=3*1024*1024


def inspect(output,run=subprocess.run):
    output=Path(output);output.mkdir(parents=True,exist_ok=True);rows=[]
    for channel,encoding in CASES:
        url=ROOT.format(channel.split('_')[1]);name=channel+'-'+encoding
        body=output/(name+'.html');headers=output/(name+'.headers.tmp')
        command=['curl','--disable','--fail','--silent','--show-error','--http1.1',
                 '--user-agent','Mozilla/5.0 (LP public notice collector)',
                 '--header','Connection: close','--max-time','25','--max-filesize',str(MAX_BYTES),
                 '--proto','=https','--proto-redir','=https','--output',str(body),
                 '--dump-header',str(headers),'--write-out','%{http_code}']
        command+=['--compressed'] if encoding=='compressed' else ['--header','Accept-Encoding: identity']
        row={'source_channel':channel,'encoding':encoding,'url':url};rows.append(row)
        try:
            result=run(command+[url],capture_output=True,timeout=30,check=False)
            raw=body.read_bytes() if body.exists() else b''
            if len(raw)>MAX_BYTES:raise ValueError('diagnostic response byte limit')
            row.update(curl_exit=result.returncode,status=result.stdout.decode('ascii').strip(),
                       bytes=len(raw),file=body.name,sha256=hashlib.sha256(raw).hexdigest())
            # Keep framing metadata only; no Set-Cookie or other opaque headers.
            metadata={}
            if headers.exists():
                for line in headers.read_text(errors='replace').splitlines():
                    key,separator,value=line.partition(':')
                    if separator and key.lower() in {'content-length','transfer-encoding','content-encoding','content-type','connection'}:
                        metadata[key.lower()]=value.strip()[:200]
            row['headers']=metadata
            try:
                html=_complete_html(raw,'diagnostic listing')
                found,_=parse_listing(html,url,channel)
                row.update(complete_html=True,row_count=len(found))
            except ValueError:row.update(complete_html=False)
        except (OSError,ValueError,subprocess.SubprocessError) as error:row['error_type']=type(error).__name__
        finally:headers.unlink(missing_ok=True)
    report={'mode':'kofia_transfer_read_only','responses':rows}
    (output/'index.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    report=inspect(parser.parse_args().output)
    print(json.dumps(report,ensure_ascii=False))
