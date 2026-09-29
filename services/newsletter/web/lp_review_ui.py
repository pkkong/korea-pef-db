"""Private LP review shell. Data and mutations require a verified reviewer JWT."""
import json
import os
from pathlib import Path
from flask import Blueprint, Response

review = Blueprint('lp_review', __name__)
ROOT = Path(__file__).parent

@review.get('/admin/lp')
def index():
    config={'url':os.environ.get('SUPABASE_URL',''),'key':os.environ.get('SUPABASE_PUBLISHABLE_KEY') or os.environ.get('SUPABASE_ANON_KEY','')}
    body=(ROOT/'lp_review.html').read_text().replace('__CONFIG__',json.dumps(config).replace('<','\\u003c'))
    return Response(body,headers={'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY'},content_type='text/html; charset=utf-8')

@review.get('/admin/lp.js')
def script():
    return Response((ROOT/'lp_review.js').read_text(),content_type='application/javascript',headers={'Cache-Control':'no-store'})
