import socket
import ssl
import unittest
from unittest.mock import MagicMock, Mock, patch
from urllib.error import URLError

from services.lp.src import lp_ipv4_transport as transport
from services.lp.src import collect_lp_institution_boards as boards


class IPv4RecoveryTests(unittest.TestCase):
    def test_resolves_original_hostname_with_ipv4_and_preserves_timeout(self):
        rows=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('192.0.2.10',443))]
        with patch.object(transport.socket,'getaddrinfo',return_value=rows) as resolver,patch.object(transport.socket,'socket') as factory:
            result=transport.create_ipv4_connection(('official.example',443),20)
            resolver.assert_called_once_with('official.example',443,socket.AF_INET,socket.SOCK_STREAM)
            result.settimeout.assert_called_once_with(20)
            result.connect.assert_called_once_with(('192.0.2.10',443))
            self.assertIs(result,factory.return_value)

    def test_failed_socket_is_closed_and_resolver_failure_is_preserved(self):
        rows=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('192.0.2.10',443))]
        with patch.object(transport.socket,'getaddrinfo',return_value=rows),patch.object(transport.socket,'socket') as factory:
            factory.return_value.connect.side_effect=TimeoutError('offline')
            with self.assertRaises(TimeoutError):transport.create_ipv4_connection(('official.example',443),20)
            factory.return_value.close.assert_called_once()
        with patch.object(transport.socket,'getaddrinfo',side_effect=socket.gaierror(8,'DNS unavailable')):
            with self.assertRaises(socket.gaierror):transport.create_ipv4_connection(('official.example',443),20)

    def test_https_retains_hostname_and_verifying_context(self):
        handler=transport.IPv4HTTPSHandler()
        context=handler._context or ssl.create_default_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        connection=transport.IPv4HTTPSConnection('official.example',timeout=20,context=context)
        self.assertEqual(connection.host,'official.example')
        self.assertIs(connection._create_connection,transport.create_ipv4_connection)

    def test_direct_sessions_share_cookie_jar_and_keep_two_attempt_budget(self):
        session=boards.Session(boards.load_configs()['kdb'])
        jars=[[h.cookiejar for h in opener.handlers if hasattr(h,'cookiejar')][0] for opener in (session.opener,session.ipv4_opener)]
        self.assertIs(jars[0],jars[1])
        session.opener=Mock();session.opener.open.side_effect=URLError(socket.gaierror(8,'DNS unavailable'))
        response=MagicMock();response.__enter__.return_value.read.return_value=b'official bytes'
        session.ipv4_opener=Mock();session.ipv4_opener.open.return_value=response
        with patch.object(boards.time,'sleep'):
            self.assertEqual(session('https://www.kdb.co.kr/BOUBUF01R01.jct'),b'official bytes')
        self.assertEqual(session.opener.open.call_count,1)
        self.assertEqual(session.ipv4_opener.open.call_count,1)
        self.assertEqual(session.dns_ipv4_fetches,1)

    def test_ipv4_failure_does_not_add_third_attempt_or_claim_success(self):
        session=boards.Session(boards.load_configs()['kdb'])
        error=URLError(socket.gaierror(8,'DNS unavailable'))
        session.opener=Mock();session.opener.open.side_effect=error
        session.ipv4_opener=Mock();session.ipv4_opener.open.side_effect=error
        with patch.object(boards.time,'sleep'):
            with self.assertRaises(URLError):session('https://www.kdb.co.kr/BOUBUF01R01.jct')
        self.assertEqual(session.opener.open.call_count+session.ipv4_opener.open.call_count,2)
        self.assertEqual(session.dns_ipv4_fetches,0)
