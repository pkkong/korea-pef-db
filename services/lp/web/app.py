"""Standalone, read-only LP service; other products are navigation links only."""
from __future__ import annotations

import os
import re
import time
from html import escape, unescape
from threading import RLock
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, redirect, request

try:
    from .lp_program_data import PAGE_NAME, fetch_lp_program_page
except ImportError:
    from lp_program_data import PAGE_NAME, fetch_lp_program_page
try:
    from services.shared.web.service_assets import service_css, service_js
except ImportError:
    from service_assets import service_css, service_js

app = Flask(__name__, static_folder=None)
_PAGE_CACHE: dict[str, dict] = {}
_CACHE_LOCK = RLock()
_DEFAULTS = {
    'NEWSLETTER_PUBLIC_URL': 'https://kpef-newsletter.vercel.app',
    'LP_PUBLIC_URL': 'https://kpef-lp.vercel.app',
    'GP_PUBLIC_URL': 'https://kpef-gp.vercel.app',
}


def _public_url(name: str) -> str:
    value = os.environ.get(name, _DEFAULTS[name]).rstrip('/')
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
        return _DEFAULTS[name]
    return value


def rewrite_navigation(html: str) -> str:
    """Adapt only known product links/assets, leaving official evidence untouched."""
    newsletter = _public_url('NEWSLETTER_PUBLIC_URL')
    gp = _public_url('GP_PUBLIC_URL')
    known_hosts = {'kpef-newsletter.vercel.app', 'kpef-lp.vercel.app', 'kpef-gp.vercel.app', urlsplit(newsletter).netloc, urlsplit(gp).netloc, urlsplit(_public_url('LP_PUBLIC_URL')).netloc}

    def rewrite_url(value: str, tag: str, attribute: str) -> str:
        parsed = urlsplit(unescape(value))
        if parsed.scheme and parsed.scheme not in ('http', 'https'):
            return value
        if parsed.netloc and parsed.netloc not in known_hosts:
            return value
        path = parsed.path
        suffix = ('?' + parsed.query if parsed.query else '') + ('#' + parsed.fragment if parsed.fragment else '')
        if tag in ('link', 'script'):
            if path in ('/assets/service.css', '/static/service.css') and attribute == 'href':
                return '/assets/service.css' + suffix
            if path == '/assets/service.js' and attribute == 'src':
                return '/assets/service.js' + suffix
            return value
        if attribute != 'href':
            return value
        if path.startswith('/samples/lp/') and PAGE_NAME.fullmatch(path.rsplit('/', 1)[-1]):
            return '/' + path.rsplit('/', 1)[-1] + suffix
        if parsed.netloc in {'kpef-gp.vercel.app', urlsplit(gp).netloc} and path in ('', '/', '/index.html', '/gps.html'):
            return gp + '/' + suffix
        if path in ('gps.html', '/gps.html', '/gp/', '/gp'):
            return gp + '/' + suffix
        if parsed.netloc and path in ('', '/', '/index.html') and parsed.netloc in {'kpef-newsletter.vercel.app', urlsplit(newsletter).netloc}:
            return newsletter + '/' + suffix
        return value

    def rewrite_tag(match: re.Match) -> str:
        text = match.group(0)
        tag = match.group(1).lower()
        def attr_replace(attr: re.Match) -> str:
            value = rewrite_url(attr.group(3), tag, attr.group(1).lower())
            return attr.group(1) + '=' + attr.group(2) + escape(unescape(value), quote=True) + attr.group(2)
        return re.sub(r'\b(href|src)\s*=\s*([\"\'])(.*?)\2', attr_replace, text, flags=re.I | re.S)
    return re.sub(r'<(a|link|script)\b[^>]*>', rewrite_tag, html, flags=re.I)


def _seconds(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def load_page(filename: str, *, refresh: bool = False) -> dict | None:
    with _CACHE_LOCK:
        now = time.monotonic()
        cached = _PAGE_CACHE.get(filename)
        if cached and not refresh and now < cached['expires_at']:
            return {**cached['page'], 'cache_status': 'fresh'}
        try:
            page = fetch_lp_program_page(filename)
        except Exception:
            if cached and now < cached['expires_at'] + _seconds('LP_PAGE_STALE_IF_ERROR_SECONDS', 3600):
                return {**cached['page'], 'cache_status': 'stale'}
            raise
        if not page:
            _PAGE_CACHE.pop(filename, None)
            return None
        # A new publication invalidates all older in-memory pages.
        if any(entry['page'].get('run_id') != page.get('run_id') for entry in _PAGE_CACHE.values()):
            _PAGE_CACHE.clear()
        _PAGE_CACHE[filename] = {'page': dict(page), 'expires_at': time.monotonic() + _seconds('LP_PAGE_CACHE_SECONDS', 60)}
        return {**page, 'cache_status': 'fresh'}


def serve_page(filename: str):
    if not PAGE_NAME.fullmatch(filename):
        return Response('페이지를 찾을 수 없습니다.', status=404, content_type='text/plain; charset=utf-8')
    headers = {'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff', 'X-Robots-Tag': 'noindex, nofollow'}
    if filename == 'review.html':
        headers.update({'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow', 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY'})
    try:
        page = load_page(filename, refresh=request.args.get('refresh') == '1')
    except Exception:
        app.logger.warning('LP public page unavailable')
        return Response('잠시 후 다시 시도해 주세요.', status=503, headers={**headers, 'Retry-After': '60'}, content_type='text/plain; charset=utf-8')
    if page is None:
        return Response('페이지를 찾을 수 없습니다.', status=404, headers=headers, content_type='text/plain; charset=utf-8')
    headers.update({'X-LP-Data-Source': 'supabase', 'X-LP-Run': page['run_id'], 'X-LP-Cache': page['cache_status']})
    return Response(rewrite_navigation(page['page_html']), headers=headers, content_type='text/html; charset=utf-8')


@app.get('/')
def index():
    return serve_page('index.html')


@app.get('/<filename>')
def public_page(filename: str):
    return serve_page(filename)


@app.get('/samples/lp/<filename>')
def legacy_sample(filename: str):
    return serve_page(filename)


@app.get('/admin/lp')
def legacy_review():
    return redirect('/review.html', code=302)


@app.get('/assets/service.css')
def css_asset():
    return Response(service_css(), content_type='text/css; charset=utf-8', headers={'Cache-Control': 'public, max-age=300'})


@app.get('/assets/service.js')
def js_asset():
    return Response(service_js(), content_type='text/javascript; charset=utf-8', headers={'Cache-Control': 'public, max-age=300'})


@app.get('/health.json')
def health():
    try:
        page = load_page('index.html', refresh=request.args.get('refresh') == '1')
    except Exception:
        page = None
    result = {'service': 'lp', 'release': os.environ.get('SERVICE_RELEASE', 'local'), 'status': 'ok' if page else 'unavailable', 'data_source': 'supabase' if page else 'unavailable'}
    if page:
        result.update({'run_id': page['run_id'], 'stale': page['cache_status'] == 'stale'})
    return jsonify(result), 200 if page else 503, {'Cache-Control': 'no-store'}


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8771)
