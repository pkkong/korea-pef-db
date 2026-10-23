import io
import os
from pathlib import Path
import socket
import ssl
import subprocess
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src import lp_cu_transport as native

URL = 'https://www.cu.co.kr/cu/na/ntt/selectNttList.do?bbsId=1020&searchValue=PE'


class NativeCuTransportTests(unittest.TestCase):
    def run_response(self, raw=b'complete official bytes', status=b'200', code=0):
        def run(command, **kwargs):
            Path(command[command.index('--output') + 1]).write_bytes(raw)
            return subprocess.CompletedProcess(command, code, status, b'not logged')
        return run

    def test_native_request_keeps_hostname_tls_limits_and_exact_bytes(self):
        raw = b'\xd0\xcf\x11\xe0official attachment'
        with patch.object(native.subprocess, 'run', side_effect=self.run_response(raw)) as run:
            self.assertEqual(native.fetch_cu_ipv4(URL, URL), raw)
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ['curl', '--disable', '--ipv4'])
            self.assertEqual(command[-1], URL)
            self.assertEqual(command[command.index('--referer') + 1], URL)
            for forbidden in ['--insecure', '-k', '--resolve', '--connect-to', '--location', '-L']:
                self.assertNotIn(forbidden, command)
            self.assertEqual(command[command.index('--retry') + 1], '0')
            self.assertEqual(command[command.index('--proto') + 1], '=https')
            self.assertEqual(command[command.index('--max-filesize') + 1], str(native.MAX_BYTES))
            self.assertEqual(run.call_args.kwargs['timeout'], 25)

    def test_foreign_hosts_credentials_ports_routes_and_referers_never_connect(self):
        invalid = [URL.replace('https:', 'http:'), URL.replace('www.cu.co.kr', 'evil.example'),
                   URL.replace('www.cu.co.kr', 'user:password@www.cu.co.kr'),
                   URL.replace('www.cu.co.kr', 'www.cu.co.kr:444'),
                   URL.replace('/cu/na/ntt/selectNttList.do', '/private'), URL+'#fragment']
        with patch.object(native.subprocess, 'run') as run:
            for url in invalid:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    native.fetch_cu_ipv4(url)
            with self.assertRaises(ValueError):native.fetch_cu_ipv4(URL, 'https://evil.example/')
            run.assert_not_called()

    def test_redirect_http_certificate_dns_and_size_failures_cannot_succeed(self):
        scenarios = [(b'body', b'302', 0), (b'body', b'404', 22),
                     (b'body', b'000', 60), (b'body', b'000', 6),
                     (b'', b'200', 0), (b'x'*(native.MAX_BYTES+1), b'200', 0)]
        for raw, status, code in scenarios:
            with self.subTest(status=status,code=code), patch.object(native.subprocess, 'run', side_effect=self.run_response(raw,status,code)):
                with self.assertRaises(ValueError):native.fetch_cu_ipv4(URL)

    def test_native_timeout_or_missing_executable_is_bounded(self):
        for error in [subprocess.TimeoutExpired('curl',25), FileNotFoundError('curl')]:
            with patch.object(native.subprocess,'run',side_effect=error) as run:
                with self.assertRaisesRegex(ValueError,'did not complete'):native.fetch_cu_ipv4(URL)
                self.assertEqual(run.call_count,1)

    def session(self, error, institution='cu'):
        session=boards.Session(boards.load_configs()[institution])
        session.opener=Mock();session.opener.open.side_effect=error
        return session

    def test_cu_dns_uses_native_in_existing_second_attempt_only(self):
        session=self.session(URLError(socket.gaierror(8,'resolver unavailable')))
        with patch.object(boards,'fetch_cu_ipv4',return_value=b'official') as fetch, patch.object(boards,'fetch_cu') as regional, patch.object(boards.time,'sleep'):
            self.assertEqual(session(URL,URL),b'official')
            self.assertEqual(session.opener.open.call_count,1)
            fetch.assert_called_once_with(URL,URL)
            self.assertEqual(session.native_ipv4_fetches,1)
            regional.assert_not_called()

    def test_failed_native_recovery_is_reported_without_third_attempt(self):
        session=self.session(URLError(socket.gaierror(8,'resolver unavailable')))
        with patch.object(boards,'fetch_cu_ipv4',side_effect=ValueError('native unavailable')) as fetch, patch.object(boards.time,'sleep'):
            with self.assertRaisesRegex(ValueError,'native unavailable'):session(URL)
            self.assertEqual(session.opener.open.call_count,1)
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(session.native_ipv4_fetches,0)

    def test_http_tls_timeout_and_other_institutions_do_not_select_cu_native(self):
        errors=[HTTPError(URL,400,'bad',{},io.BytesIO(b'blocked')),
                URLError(ssl.SSLCertVerificationError('certificate')),
                URLError(TimeoutError('timeout'))]
        for error in errors:
            session=self.session(error)
            with patch.object(boards,'fetch_cu_ipv4') as fetch, patch.object(boards.time,'sleep'):
                with self.assertRaises(type(error)):session(URL)
                fetch.assert_not_called()
        session=self.session(URLError(socket.gaierror(8,'resolver unavailable')),'tp')
        with patch.object(session.ipv4_opener,'open',side_effect=URLError(socket.gaierror(8,'resolver unavailable'))) as ipv4,patch.object(boards,'fetch_cu_ipv4') as fetch,patch.object(boards.time,'sleep'):
            with self.assertRaises(URLError):session('https://www.tp.or.kr/tp-kr/bbs/i-151/list.do')
            self.assertEqual(session.opener.open.call_count+ipv4.call_count,2)
            fetch.assert_not_called()

    def test_only_native_exit_six_has_typed_dns_error(self):
        for code in [6, 22, 28, 35, 60]:
            with patch.object(native.subprocess, 'run', side_effect=self.run_response(status=b'000', code=code)):
                with self.assertRaises(ValueError) as caught:
                    native.fetch_cu_ipv4(URL)
                self.assertEqual(isinstance(caught.exception, native.CuDnsError), code == 6)

    def test_two_dns_failures_use_seoul_once_and_count_only_success(self):
        session = self.session(URLError(socket.gaierror(8, 'resolver unavailable')))
        with patch.dict(os.environ, {'LP_SOURCE_WORKER_TOKEN': 'test-token'}), \
                patch.object(boards, 'fetch_cu_ipv4', side_effect=native.CuDnsError('native CU transport failed (curl exit 6)')) as direct, \
                patch.object(boards, 'fetch_cu', return_value=b'official') as regional, \
                patch.object(boards.time, 'sleep'):
            self.assertEqual(session(URL, URL), b'official')
            self.assertEqual(session.opener.open.call_count, 1)
            direct.assert_called_once_with(URL, URL)
            regional.assert_called_once_with(URL, URL, 'test-token')
            self.assertEqual(session.native_ipv4_fetches, 0)
            self.assertEqual(session.regional_fetches, 1)

    def test_missing_token_and_non_dns_native_errors_never_use_seoul(self):
        for token, error in [('', native.CuDnsError('exit 6')),
                             ('test-token', ValueError('native CU transport failed (curl exit 6)')),
                             ('test-token', ValueError('curl exit 60'))]:
            session = self.session(URLError(socket.gaierror(8, 'resolver unavailable')))
            with patch.dict(os.environ, {'LP_SOURCE_WORKER_TOKEN': token}), \
                    patch.object(boards, 'fetch_cu_ipv4', side_effect=error), \
                    patch.object(boards, 'fetch_cu') as regional, patch.object(boards.time, 'sleep'):
                with self.assertRaises(ValueError): session(URL)
                regional.assert_not_called()
                self.assertEqual(session.regional_fetches, 0)

    def test_seoul_failure_is_visible_without_more_attempts(self):
        session = self.session(URLError(socket.gaierror(8, 'resolver unavailable')))
        with patch.dict(os.environ, {'LP_SOURCE_WORKER_TOKEN': 'test-token'}), \
                patch.object(boards, 'fetch_cu_ipv4', side_effect=native.CuDnsError('exit 6')) as direct, \
                patch.object(boards, 'fetch_cu', side_effect=ValueError('regional unavailable')) as regional, \
                patch.object(boards.time, 'sleep'):
            with self.assertRaisesRegex(ValueError, 'regional unavailable'): session(URL)
            self.assertEqual(session.opener.open.call_count, 1)
            self.assertEqual(direct.call_count, 1)
            self.assertEqual(regional.call_count, 1)
            self.assertEqual(session.regional_fetches, 0)


if __name__=='__main__':unittest.main()
