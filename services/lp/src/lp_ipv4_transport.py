"""IPv4-only DNS recovery using the same HTTPS, cookies and redirect policy."""
import http.client
import socket
import time
from functools import partial

try:
    from .lp_transport_errors import transient_dns
except ImportError:
    from lp_transport_errors import transient_dns
from urllib.request import HTTPSHandler


def create_ipv4_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                           source_address=None, *, fallback_resolver=None):
    host, port = address
    last_error = None
    started = time.monotonic()
    fallback_used = False
    try:
        rows = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror as error:
        if (fallback_resolver is None or host != 'www.kdb.co.kr' or port != 443
                or not transient_dns(error)):
            raise
        remaining = timeout - (time.monotonic() - started) if isinstance(timeout, (int, float)) else 20
        if remaining <= 0:
            raise TimeoutError('official connection DNS budget exhausted') from None
        rows = fallback_resolver(host, port, min(5, remaining))
        fallback_used = True
    for family, kind, protocol, _, endpoint in rows:
        connection = None
        try:
            connection = socket.socket(family, kind, protocol)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                remaining = timeout
                if fallback_used and isinstance(timeout, (int, float)):
                    remaining -= time.monotonic() - started
                    if remaining <= 0:
                        raise TimeoutError('official connection DNS budget exhausted')
                connection.settimeout(remaining)
            if source_address:
                connection.bind(source_address)
            connection.connect(endpoint)
            return connection
        except OSError as error:
            last_error = error
            if connection is not None:
                connection.close()
    if last_error is not None:
        raise last_error
    raise OSError('IPv4 resolver returned no addresses')


class IPv4HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, fallback_resolver=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = (create_ipv4_connection if fallback_resolver is None
                                   else partial(create_ipv4_connection, fallback_resolver=fallback_resolver))


class IPv4HTTPSHandler(HTTPSHandler):
    def __init__(self, *args, fallback_resolver=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._connection_factory = (IPv4HTTPSConnection if fallback_resolver is None
                                    else partial(IPv4HTTPSConnection, fallback_resolver=fallback_resolver))

    def https_open(self, request):
        return self.do_open(self._connection_factory, request, context=self._context)
