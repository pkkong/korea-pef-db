"""Authenticated LP-only byte transport for observed official-source runner blocks.

The service runs in Seoul and allows only fixed official KFCC/KFINCO/CU routes.
Its response is still reparsed and validated by the ordinary issuer collector.
"""
import hashlib
import json
import re
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit, parse_qsl
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
    return _fetch(url, referer, token, 'KFCC')

def _fetch(url, referer, token, institution):
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
        reason = ''
        try:
            detail = json.loads(error.read(1024))
            if isinstance(detail, dict) and detail.get('error') in {
                    'source_fetch_failed', 'upstream_status', 'source_too_large',
                    'invalid_source_url', 'unauthorized'}:
                reason = ' ('+detail['error']+')'
        except (ValueError, OSError):
            pass
        raise ValueError('regional '+institution+' source unavailable HTTP '+str(error.code)+reason) from None


def kfinco_url(url):
    if not isinstance(url,str) or len(url)>8192 or re.search(r'[\x00-\x20\x7f\\#]',url):
        raise ValueError('invalid KFINCO transport URL')
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname!='www.kfinco.co.kr' or p.username or p.password or p.port not in {None,443} or p.fragment:
        raise ValueError('regional transport accepts only official KFINCO HTTPS')
    pairs=parse_qsl(p.query,keep_blank_values=True,strict_parsing=True)
    q=dict(pairs)
    if len(q)!=len(pairs):raise ValueError('duplicate KFINCO query keys')
    if p.path=='/api/pr/notice/list':
        if q!={'page':'1','size':'10','searchKeyword':'위탁운용사'}:raise ValueError('unsupported KFINCO listing query')
    elif re.fullmatch(r'/api/pr/notice/detail/NT[0-9]{14}',p.path):
        if q:raise ValueError('unsupported KFINCO detail query')
    elif p.path=='/util/download':
        if set(q)!={'filePath','downloadName'}:raise ValueError('unsupported KFINCO attachment query')
        if not re.fullmatch(r'/pds/notice/[0-9]{4}-[0-9]{2}/[A-Za-z0-9_-]+\.(?:hwp|hwpx|pdf)',q['filePath'],re.I):
            raise ValueError('unsafe KFINCO attachment path')
        name=q['downloadName']
        if not name or len(name)>255 or '..' in name or re.search(r'[%/\\\x00-\x1f\x7f?#:]',name) or not re.search(r'\.(?:hwp|hwpx|pdf)$',name,re.I):
            raise ValueError('unsafe KFINCO attachment filename')
    else:raise ValueError('unsupported KFINCO transport route')
    return url


def fetch_kfinco(url,token):
    kfinco_url(url)
    if isinstance(token,str) and re.search(r'[\x00-\x20\x7f]',token):raise ValueError('invalid regional token')
    try:
        return _fetch(url,None,token,'KFINCO')
    except ValueError:
        raise
    except Exception:
        raise ValueError('regional KFINCO transport unavailable') from None


def cu_url(url, referer=False):
    """Allow only CU board 1020 and its discovered notice/download routes."""
    if (not isinstance(url, str) or len(url) > 4096
            or re.search(r'[\x00-\x20\x7f\\#]', url)):
        raise ValueError('invalid CU regional URL')
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname != 'www.cu.co.kr' or p.username or p.password
            or p.port not in {None, 443} or p.fragment):
        raise ValueError('regional transport accepts only official CU HTTPS')
    if '%' in p.path or any(part in {'.', '..'} for part in p.path.split('/')):
        raise ValueError('unsafe CU regional path')
    pairs = parse_qsl(p.query, keep_blank_values=True, strict_parsing=True)
    q = dict(pairs)
    if len(q) != len(pairs):
        raise ValueError('duplicate CU query keys')
    if p.path == '/cu/na/ntt/selectNttList.do':
        base = {'bbsId': '1020', 'mi': '100007', 'searchType': 'sj', 'listCo': '50'}
        if referer and q == base:
            return url
        if (set(q) != set(base) | {'searchValue', 'currPage'}
                or any(q.get(k) != v for k, v in base.items())
                or q.get('searchValue') not in {'블라인드', '위탁운용사'}
                or not re.fullmatch(r'[1-9][0-9]{0,3}', q.get('currPage', ''))
                or int(q['currPage']) > 1000):
            raise ValueError('unsupported CU listing query')
    elif p.path == '/cu/na/ntt/selectNttInfo.do':
        if (set(q) not in ({'nttSn', 'mi'}, {'nttSn', 'mi', 'bbsId'})
                or q.get('mi') != '100007' or q.get('bbsId', '1020') != '1020'
                or not re.fullmatch(r'[0-9]{1,12}', q.get('nttSn', ''))):
            raise ValueError('unsupported CU detail query')
    elif p.path == '/common/nttFileDownload.do' and not referer:
        if set(q) != {'fileKey'} or not re.fullmatch(r'[0-9a-fA-F]{32}', q.get('fileKey', '')):
            raise ValueError('unsupported CU attachment query')
    else:
        raise ValueError('unsupported CU regional route')
    return url


def fetch_cu(url, referer, token):
    cu_url(url)
    if referer:
        cu_url(referer, referer=True)
    if isinstance(token, str) and re.search(r'[\x00-\x20\x7f]', token):
        raise ValueError('invalid regional token')
    try:
        return _fetch(url, referer, token, 'CU')
    except ValueError:
        raise
    except Exception:
        raise ValueError('regional CU transport unavailable') from None
