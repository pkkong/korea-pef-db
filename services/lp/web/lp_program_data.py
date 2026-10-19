"""Read only the LP service's published pages from Supabase."""
from __future__ import annotations

import json
import os
import re
from urllib.request import Request, urlopen

PAGE_NAME = re.compile(r'(?:index|review|(?:program|institution|selected-gp)-[a-zA-Z0-9_-]+)\.html\Z')


def fetch_lp_program_page(filename: str) -> dict | None:
    if not PAGE_NAME.fullmatch(filename):
        return None
    base = os.environ.get('SUPABASE_URL', '').rstrip('/')
    key = os.environ.get('SUPABASE_PUBLISHABLE_KEY') or os.environ.get('SUPABASE_ANON_KEY')
    if not base or not key:
        raise RuntimeError('LP public reader is not configured')
    req = Request(
        base + '/rest/v1/rpc/lp_program_page',
        data=json.dumps({'page_name': filename}).encode(),
        headers={'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
        method='POST',
    )
    with urlopen(req, timeout=10) as response:
        result = json.loads(response.read())
    if result is None:
        return None
    if not isinstance(result, dict) or not isinstance(result.get('page_html'), str) or not result['page_html']:
        raise ValueError('Invalid LP public page')
    if not isinstance(result.get('run_id'), str) or not result['run_id']:
        raise ValueError('Missing LP publication identifier')
    return result
