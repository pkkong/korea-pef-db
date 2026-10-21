"""Authenticated LP-only byte transport for the observed KFCC runner block.

The service runs in Seoul and allows only fixed official KFCC board/file routes.
Its response is still reparsed and validated by the ordinary issuer collector.
"""
import hashlib
import json
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

WORKER = 'https://kpef-lp-source-worker.vercel.app/api/fetch'
MAX_BYTES = 3 * 1024 * 1024


def official_url(url):
    if not isinstance(url, str) or len(url) > 8192:
        raise ValueError('invalid KFCC transport URL')
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname != 'www.kfcc.co.kr' or p.username or p.password
            or p.port not in {None, 443} or p.fragment):
        raise ValueError('regional transport accepts only the official KFCC HTTPS host')
    path = unquote(unquote(p.path))
    if any(part in {'.', '..'} for part in path.split('/')) or '\\' in path:
        raise ValueError('unsafe KFCC transport path')
    if path not in {'/mgNotice/mgNoticeList.do', '/mgNotice/mgNoticeDetail.do'} and not path.startswith('/upload/neoboard/A01/'):
        raise ValueError('unsupported KFCC transport route')
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('regional transport redirect rejected')


def fetch_kfcc(url, referer, token):
    official_url(url)
    if referer:
        official_url(referer)
    if not isinstance(token, str) or not token or len(token) > 512:
        raise ValueError('regional transport token unavailable')
    payload = {'url': url}
    if referer:
        payload['referer'] = referer
    request = Request(WORKER, method='POST', data=json.dumps(payload).encode(),
                      headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/json',
                               'Accept-Encoding': 'identity'})
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(MAX_BYTES + 1)
            if not raw or len(raw) > MAX_BYTES:
                raise ValueError('regional response empty or oversized')
            if response.headers.get('X-LP-Source-Region') != 'icn1':
                raise ValueError('regional response location mismatch')
            if response.headers.get('X-LP-Upstream-SHA256') != hashlib.sha256(raw).hexdigest():
                raise ValueError('regional response hash mismatch')
            return raw
    except HTTPError as error:
        raise ValueError('regional KFCC source unavailable HTTP '+str(error.code)) from None
