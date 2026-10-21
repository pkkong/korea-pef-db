"""Probe fixed public LP sources from a temporary Seoul function, then remove it.

No public app, database, schedule, plan or billing configuration is modified.
Deployment credentials stay in environment. The ephemeral function requires a
random token and accepts no target URL from callers.
"""
import argparse
import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

PROJECT = 'kpef-lp-source-probe'
SOURCE = r'''
const crypto = require('node:crypto');
module.exports = async (req, res) => {
  if (req.method !== 'GET' || !process.env.SOURCE_PROBE_TOKEN || req.headers.authorization !== 'Bearer '+process.env.SOURCE_PROBE_TOKEN) return res.status(401).end();
  const targets = [
    ['kfcc','https://www.kfcc.co.kr/mgNotice/mgNoticeList.do?schType=subject&schValue='+encodeURIComponent('위탁')+'&pageNo=1'],
    ['kfinco','https://www.kfinco.co.kr/api/pr/notice/list?page=1&size=10&searchKeyword='+encodeURIComponent('위탁운용사')]
  ];
  const results = [];
  for (const [source,url] of targets) {
    try {
      const response = await fetch(url,{redirect:'error',headers:{'User-Agent':'Mozilla/5.0'},signal:AbortSignal.timeout(20000)});
      const reader=response.body.getReader(); const chunks=[]; let size=0;
      while (true) {const {done,value}=await reader.read(); if(done)break; size+=value.length; if(size>512000){await reader.cancel();throw Error('probe response exceeds bound');} chunks.push(Buffer.from(value));}
      const raw=Buffer.concat(chunks); const body=raw.toString('utf8');
      let officialShape=false;
      if(source==='kfcc')officialShape=/name=["']brdForm/.test(body)&&body.includes('magazine')&&body.includes('fnDetail');
      else {try{const data=JSON.parse(body);officialShape=data.success===true&&Array.isArray(data.list);}catch{}}
      results.push({source,url,status:response.status,bytes:size,officialShape,sha256:crypto.createHash('sha256').update(raw).digest('hex'),errorExcerpt:response.ok?null:body.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').slice(0,200)});
    } catch(error) {results.push({source,error:String(error.cause?.code||error.name)});}
  }
  res.setHeader('Cache-Control','no-store');
  return res.json({region:process.env.VERCEL_REGION,results});
};
'''


def api(path, method='GET', data=None):
    owner=os.environ['VERCEL_ORG_ID']
    query='?'+urlencode({'teamId':owner}) if owner.startswith('team_') else ''
    req=Request('https://api.vercel.com'+path+query, method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization':'Bearer '+os.environ['VERCEL_TOKEN'],'Content-Type':'application/json'})
    try:
        with urlopen(req,timeout=40) as response:
            raw=response.read()
            return json.loads(raw) if raw else None
    except HTTPError as error:
        raise RuntimeError('Vercel '+method+' failed HTTP '+str(error.code)) from None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    project=None
    report={'status':'error','region_requested':'icn1'}
    try:
        # Never reuse or overwrite an existing project with this name.
        project=api('/v11/projects','POST',{'name':PROJECT,'framework':None,'publicSource':False})
        token=secrets.token_urlsafe(32)
        api('/v10/projects/'+project['id']+'/env','POST',
            [{'key':'SOURCE_PROBE_TOKEN','value':token,'type':'encrypted','target':['production']}])
        with tempfile.TemporaryDirectory(prefix='lp-seoul-probe-') as folder:
            root=Path(folder);(root/'api').mkdir()
            (root/'api/probe.js').write_text(SOURCE)
            (root/'package.json').write_text(json.dumps({'private':True}))
            (root/'vercel.json').write_text(json.dumps({'regions':['icn1'],'git':{'deploymentEnabled':False}}))
            subprocess.run(['node','--check',str(root/'api/probe.js')],check=True,capture_output=True)
            env={**os.environ,'VERCEL_PROJECT_ID':project['id']}
            result=subprocess.run(['vercel','deploy','--prod','--yes','--cwd',str(root),'--token',os.environ['VERCEL_TOKEN']],
                env=env,capture_output=True,text=True,timeout=240)
            if result.returncode:
                raise RuntimeError('Temporary deployment failed with exit '+str(result.returncode))
            urls=[line.strip() for line in result.stdout.splitlines() if line.strip().startswith('https://')]
            if not urls or not (urlsplit(urls[-1]).hostname or '').endswith('.vercel.app'):
                raise RuntimeError('Temporary deployment URL missing')
            deployed=api('/v9/projects/'+project['id'])
            aliases=deployed.get('targets',{}).get('production',{}).get('alias',[])
            host=next((a for a in aliases if isinstance(a,str) and a.startswith(PROJECT+'.') and a.endswith('.vercel.app')),None)
            if not host:
                raise RuntimeError('Verified production alias missing')
            url='https://'+host+'/api/probe'
            for attempt in range(3):
                try:
                    with urlopen(Request(url,headers={'Authorization':'Bearer '+token}),timeout=55) as response:
                        report.update(json.load(response),status='measured')
                    break
                except (OSError,ValueError) as error:
                    if isinstance(error,HTTPError):report['probe_http_status']=error.code
                    if isinstance(error,HTTPError) and error.code in {401,403}:
                        raise RuntimeError('Temporary probe access failed HTTP '+str(error.code)) from None
                    if attempt==2:raise RuntimeError('Temporary regional probe unavailable') from None
                    time.sleep(3)
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
        # Never include subprocess argv, provider bodies or credential values.
        report['error']=str(error) if isinstance(error,RuntimeError) else type(error).__name__
    finally:
        if project:
            try:
                api('/v9/projects/'+project['id'],'DELETE')
                report['temporary_project_removed']=True
            except RuntimeError:
                report['temporary_project_removed']=False
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False))
    if report['status']!='measured' or not report.get('temporary_project_removed'):
        raise SystemExit(1)


if __name__=='__main__':
    main()
