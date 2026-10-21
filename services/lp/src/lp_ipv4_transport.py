"""IPv4-only DNS recovery using the same HTTPS, cookies and redirect policy."""
import http.client
import socket
from urllib.request import HTTPSHandler


def create_ipv4_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                           source_address=None):
    host, port = address
    last_error = None
    for family, kind, protocol, _, endpoint in socket.getaddrinfo(
            host, port, socket.AF_INET, socket.SOCK_STREAM):
        connection = None
        try:
            connection = socket.socket(family, kind, protocol)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                connection.settimeout(timeout)
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = create_ipv4_connection


class IPv4HTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(IPv4HTTPSConnection, request, context=self._context)
