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

class KdbAlternateDnsTests(unittest.TestCase):
    def rows(self):
        return [(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('8.8.8.8',443))]

    def test_only_kdb_typed_ipv4_dns_failure_selects_the_alternate_resolver(self):
        fallback=Mock(return_value=self.rows())
        with patch.object(transport.socket,'getaddrinfo',side_effect=socket.gaierror(8,'DNS unavailable')),patch.object(transport.socket,'socket') as factory:
            result=transport.create_ipv4_connection(('www.kdb.co.kr',443),20,fallback_resolver=fallback)
            self.assertIs(result,factory.return_value)
            self.assertEqual(fallback.call_args.args[:2],('www.kdb.co.kr',443))
            self.assertLessEqual(fallback.call_args.args[2],5)
            factory.return_value.connect.assert_called_once_with(('8.8.8.8',443))
            self.assertLessEqual(factory.return_value.settimeout.call_args.args[0],20)
        for address in [('www.ibk.co.kr',443),('www.kdb.co.kr',444)]:
            with patch.object(transport.socket,'getaddrinfo',side_effect=socket.gaierror(8,'unavailable')):
                with self.assertRaises(socket.gaierror):transport.create_ipv4_connection(address,20,fallback_resolver=fallback)
        self.assertEqual(fallback.call_count,1)

    def test_normal_dns_and_non_transient_errors_never_call_alternate(self):
        fallback=Mock()
        with patch.object(transport.socket,'getaddrinfo',return_value=self.rows()),patch.object(transport.socket,'socket'):
            transport.create_ipv4_connection(('www.kdb.co.kr',443),20,fallback_resolver=fallback)
        for error in [socket.gaierror(socket.EAI_FAIL,'permanent'),PermissionError('denied')]:
            with patch.object(transport.socket,'getaddrinfo',side_effect=error):
                with self.assertRaises(type(error)):transport.create_ipv4_connection(('www.kdb.co.kr',443),20,fallback_resolver=fallback)
        fallback.assert_not_called()

    def test_alternate_failure_or_exhausted_budget_cannot_add_connection_attempt(self):
        fallback=Mock(side_effect=ValueError('alternate DNS unavailable'))
        with patch.object(transport.socket,'getaddrinfo',side_effect=socket.gaierror(8,'unavailable')),patch.object(transport.socket,'socket') as factory:
            with self.assertRaises(ValueError):transport.create_ipv4_connection(('www.kdb.co.kr',443),20,fallback_resolver=fallback)
            factory.assert_not_called()
        fallback.reset_mock()
        with patch.object(transport.socket,'getaddrinfo',side_effect=socket.gaierror(8,'unavailable')),patch.object(transport.time,'monotonic',side_effect=[0,21]):
            with self.assertRaises(TimeoutError):transport.create_ipv4_connection(('www.kdb.co.kr',443),20,fallback_resolver=fallback)
        fallback.assert_not_called()

    def test_alternate_only_changes_socket_resolution_not_https_identity(self):
        fallback=Mock(return_value=self.rows());context=ssl.create_default_context()
        connection=transport.IPv4HTTPSConnection('www.kdb.co.kr',timeout=20,context=context,fallback_resolver=fallback)
        self.assertEqual(connection.host,'www.kdb.co.kr');self.assertIs(connection._context,context)
        self.assertTrue(context.check_hostname);self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        handler=transport.IPv4HTTPSHandler(fallback_resolver=fallback)
        with patch.object(handler,'do_open') as open_request:
            request=Mock();handler.https_open(request)
            factory=open_request.call_args.args[0]
            created=factory('www.kdb.co.kr',timeout=20,context=context)
            self.assertEqual(created.host,'www.kdb.co.kr')
            self.assertIs(created._create_connection.keywords['fallback_resolver'],fallback)

    def test_only_kdb_session_enables_alternate_dns_and_cookie_policy_is_shared(self):
        for issuer in ['kdb','ibk','tp','cu']:
            session=boards.Session(boards.load_configs()[issuer])
            handler=next(h for h in session.ipv4_opener.handlers if isinstance(h,transport.IPv4HTTPSHandler))
            self.assertEqual(hasattr(handler._connection_factory,'keywords'),issuer=='kdb')
            jars=[[h.cookiejar for h in opener.handlers if hasattr(h,'cookiejar')][0] for opener in (session.opener,session.ipv4_opener)]
            self.assertIs(jars[0],jars[1])
        session=boards.Session(boards.load_configs()['kdb'])
        with patch.object(boards,'resolve_kdb_ipv4',return_value=self.rows()) as resolve:
            self.assertEqual(session._resolve_kdb_dns('www.kdb.co.kr',443,5),self.rows())
            resolve.assert_called_once_with('www.kdb.co.kr',443,5)
            self.assertEqual(session.alternate_dns_lookups,1)
