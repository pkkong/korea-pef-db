"""One bounded native IPv4 attempt after CU's system resolver fails.

Keep the official hostname for DNS, SNI and certificate checks. No fixed IP,
third-party proxy, redirect following or curl configuration file is used.
"""
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit

MAX_BYTES = 12 * 1024 * 1024
ROUTES = {'/cu/na/ntt/selectNttList.do', '/cu/na/ntt/selectNttInfo.do',
          '/common/nttFileDownload.do'}


class CuDnsError(ValueError):
    """Native curl could not resolve the official CU hostname (exit 6 only)."""


def official_url(url):
    if not isinstance(url, str) or len(url) > 8192:
        raise ValueError('invalid CU transport URL')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'www.cu.co.kr'
            or parsed.username or parsed.password or parsed.fragment
            or parsed.port not in {None, 443} or unquote(parsed.path) not in ROUTES):
        raise ValueError('native CU transport accepts only official HTTPS routes')
    return url


def fetch_cu_ipv4(url, referer=None):
    official_url(url)
    if referer:
        official_url(referer)
    with tempfile.TemporaryDirectory(prefix='lp-cu-source-') as folder:
        body = Path(folder) / 'body'
        command = ['curl', '--disable', '--ipv4', '--http1.1', '--fail', '--silent',
                   '--show-error', '--retry', '0', '--max-time', '20',
                   '--max-filesize', str(MAX_BYTES), '--proto', '=https',
                   '--proto-redir', '=https', '--user-agent',
                   'Mozilla/5.0 (LP official board collector)', '--header',
                   'Accept-Encoding: identity', '--header', 'Connection: close',
                   '--output', str(body), '--write-out', '%{http_code}']
        if referer:
            command += ['--referer', referer]
        command += [url]
        try:
            result = subprocess.run(command, capture_output=True, timeout=25)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError('native CU transport did not complete') from None
        if result.returncode == 6:
            raise CuDnsError('native CU transport failed (curl exit 6)')
        if result.returncode:
            raise ValueError(f'native CU transport failed (curl exit {result.returncode})')
        if result.stdout != b'200':
            raise ValueError('native CU transport requires HTTP 200 without redirects')
        with body.open('rb') as response:
            raw = response.read(MAX_BYTES + 1)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError('native CU response empty or exceeds 12 MiB')
        return raw
