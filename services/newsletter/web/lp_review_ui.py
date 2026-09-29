"""Login-free, read-only review of official public announcements."""
from flask import Blueprint,Response
try:
    from .lp_program_data import fetch_lp_program_page
except ImportError:
    from lp_program_data import fetch_lp_program_page

review=Blueprint('lp_review',__name__)

@review.get('/admin/lp')
def index():
    try:
        page=fetch_lp_program_page('review.html')
    except Exception:
        page=None
    headers={'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY'}
    if not page:
        return Response('검토 자료를 준비하고 있습니다. 잠시 후 다시 확인해 주세요.',status=503,headers=headers,content_type='text/plain; charset=utf-8')
    return Response(page['page_html'],headers=headers,content_type='text/html; charset=utf-8')
