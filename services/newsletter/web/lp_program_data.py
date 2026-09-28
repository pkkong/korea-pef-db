"""Read the published LP sample from the private collection's public RPC."""
import json
import os
from urllib.request import Request, urlopen


def fetch_lp_program_page(filename):
    base = os.environ.get('SUPABASE_URL', '').rstrip('/')
    key = os.environ.get('SUPABASE_PUBLISHABLE_KEY') or os.environ.get('SUPABASE_ANON_KEY')
    if not base or not key:
        raise RuntimeError('LP public reader is not configured')
    req = Request(base+'/rest/v1/rpc/lp_program_page', data=json.dumps({'page_name':filename}).encode(), headers={'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json'}, method='POST')
    with urlopen(req,timeout=10) as response:
        result = json.loads(response.read())
    return result if isinstance(result,dict) and result.get('page_html') else None
