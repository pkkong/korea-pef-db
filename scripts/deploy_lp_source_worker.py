"""Deploy the isolated, authenticated official-source Seoul transport; never publish DB data."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import urlopen
from deploy_service_runtime import api

ROOT=Path(__file__).resolve().parents[1]
PROJECT='kpef-lp-source-worker'
WEB='services/lp/collector'
BASE='https://'+PROJECT+'.vercel.app'


def cli(command, environment):
    try:
        result=subprocess.run(command+['--token',os.environ['VERCEL_TOKEN']],env=environment,
            capture_output=True,text=True,timeout=300)
    except subprocess.SubprocessError:
        raise RuntimeError('Source worker deployment command did not complete') from None
    if result.returncode:
        raise RuntimeError('Source worker deployment command failed '+str(result.returncode))
    return result.stdout


def main():
    token=os.environ.get('LP_SOURCE_WORKER_TOKEN','')
    if not token:
        raise RuntimeError('LP source worker credential is required')
    project=api('/v9/projects/'+PROJECT,allow_missing=True)
    if project is None:
        project=api('/v11/projects','POST',{'name':PROJECT,'framework':None,'rootDirectory':WEB,'publicSource':False})
    if project.get('name')!=PROJECT or project.get('rootDirectory')!=WEB or project.get('framework') is not None:
        raise RuntimeError('Refusing to overwrite a different project')
    # This machine-only endpoint has its own mandatory credential. Other public
    # services and their deployment protection are untouched.
    api('/v9/projects/'+project['id'],'PATCH',{'ssoProtection':None})
    release=os.environ['GITHUB_SHA']
    values={'LP_SOURCE_WORKER_TOKEN':token,'SERVICE_RELEASE':release}
    result=api('/v10/projects/'+project['id']+'/env','POST',
        [{'key':key,'value':value,'type':'encrypted','target':['production']} for key,value in values.items()],query={'upsert':'true'})
    if isinstance(result,dict) and result.get('failed'):
        raise RuntimeError('Source worker environment configuration failed')
    with tempfile.TemporaryDirectory(prefix='lp-source-deploy-') as folder:
        root=Path(folder)
        web=root/WEB;web.parent.mkdir(parents=True)
        shutil.copytree(ROOT/WEB,web,ignore=shutil.ignore_patterns('tests','node_modules'))
        (root/'.vercel').mkdir()
        (root/'.vercel/project.json').write_text(json.dumps({'projectId':project['id'],'orgId':project['accountId'],'projectName':PROJECT}))
        environment={**os.environ,'VERCEL_PROJECT_ID':project['id']}
        cli(['vercel','pull','--yes','--environment=production','--cwd',str(root)],environment)
        output=cli(['vercel','deploy','--prod','--yes','--cwd',str(root)],environment)
        urls=[line.strip() for line in output.splitlines() if line.strip().startswith('https://')]
        if not urls or not (urlsplit(urls[-1]).hostname or '').endswith('.vercel.app'):
            raise RuntimeError('Source worker deployment URL unavailable')
        deployment=api('/v13/deployments/'+urlsplit(urls[-1]).hostname)
        if deployment.get('projectId')!=project['id']:
            raise RuntimeError('Source worker deployment identity mismatch')
        aliases=api('/v2/deployments/'+deployment['id']+'/aliases','POST',{'alias':PROJECT+'.vercel.app'})
        if aliases.get('alias')!=PROJECT+'.vercel.app':
            raise RuntimeError('Source worker production alias mismatch')
    for attempt in range(8):
        try:
            with urlopen(BASE+'/api/health',timeout=15) as response:health=json.load(response)
            if health!={'service':'lp-source-worker','region':'icn1','release':release}:
                raise ValueError('Source worker health differs')
            break
        except (OSError,ValueError):
            if attempt==7:raise RuntimeError('Source worker health verification failed') from None
            time.sleep(3)
    sys.path.insert(0,str(ROOT))
    from services.lp.src.lp_regional_transport import fetch_kfcc, fetch_kfinco, fetch_cu
    from services.lp.src.discover_kfinco_originals import LIST_URL, listing
    from services.lp.src.collect_lp_institution_boards import load_configs,listing_urls
    from services.lp.src.lp_board_adapter_kfcc import parse_listing
    from services.lp.src import lp_board_adapters_pensions
    config=load_configs()['kfcc'];url=next(listing_urls(config))
    raw=fetch_kfcc(url,config['listing_url'],token)
    rows=parse_listing(raw.decode('utf-8'),url,config)
    kfinco_raw=fetch_kfinco(LIST_URL,token)
    _,kfinco_rows=listing(kfinco_raw)
    cu_config=load_configs()['cu'];cu_url=next(listing_urls(cu_config))
    cu_raw=fetch_cu(cu_url,cu_config['listing_url'],token)
    cu_rows=lp_board_adapters_pensions.parse_listing(cu_raw.decode('utf-8'),cu_url,cu_config)
    print(json.dumps({'service':'lp-source-worker','region':health['region'],'release':release,
        'url':BASE,'verified_cu_listing_rows':len(cu_rows),'cu_bytes':len(cu_raw),
        'verified_kfinco_listing_rows':len(kfinco_rows),'kfinco_bytes':len(kfinco_raw),
        'verified_listing_rows':len(rows),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}))


if __name__=='__main__':
    main()
