import socket
import ssl
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from services.lp.src import collect_lp_original_notices as original
from services.lp.src import collect_shared_lp_notices as shared
from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src import discover_kfinco_originals as kfinco
from services.lp.src.lp_transport_errors import transient_dns

URL='https://www.geps.or.kr/notiCommunication_notice_center'


class ResolverRecoveryTests(unittest.TestCase):
    def error(self):
        return URLError(socket.gaierror(8,'nodename nor servname provided, or not known'))

    def test_original_dns_recovers_whole_response_without_bypassing_verification(self):
        with patch.object(original,'fetch_bytes_once',side_effect=[self.error(),b'complete']) as fetch, patch.object(original.time,'sleep') as sleep:
            self.assertEqual(original.fetch_bytes(URL),b'complete')
            self.assertEqual(fetch.call_count,2)
            sleep.assert_called_once_with(1)
            self.assertEqual(fetch.call_args.kwargs,{'ssl_context':None})

    def test_permanent_original_dns_failure_is_still_bounded_and_reported(self):
        with patch.object(original,'fetch_bytes_once',side_effect=self.error()) as fetch, patch.object(original.time,'sleep'):
            with self.assertRaises(URLError):
                original.fetch_bytes(URL)
            self.assertEqual(fetch.call_count,3)

    def test_certificate_host_content_and_http_errors_are_not_dns_retries(self):
        for error in [URLError(ssl.SSLCertVerificationError('untrusted')), ValueError('host mismatch'), ValueError('size limit'), HTTPError(URL,404,'missing',{},None)]:
            with self.subTest(error=error), patch.object(original,'fetch_bytes_once',side_effect=error) as fetch, patch.object(original.time,'sleep') as sleep:
                with self.assertRaises(type(error)):
                    original.fetch_bytes(URL)
                self.assertEqual(fetch.call_count,1)
                sleep.assert_not_called()
                self.assertFalse(transient_dns(error))

    def test_association_dns_uses_existing_shared_retry_budget(self):
        budget=shared._FetchRetryBudget()
        with patch.object(shared,'_fetch_bytes_once',side_effect=[self.error(),b'complete']) as fetch, patch.object(shared.time,'sleep'):
            self.assertEqual(shared.fetch_bytes(shared.CHANNELS['kofia_17'],retry_budget=budget),b'complete')
            self.assertEqual(fetch.call_count,2)
            self.assertEqual(budget.remaining,3)

    def test_direct_board_session_recovers_dns_in_existing_two_attempt_limit(self):
        session=boards.Session(boards.load_configs()['tp'])
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'complete'
        with patch.object(session.opener,'open',side_effect=[self.error(),response]) as fetch, patch.object(boards.time,'sleep'):
            self.assertEqual(session('https://www.tp.or.kr/tp-kr/bbs/i-151/list.do'),b'complete')
            self.assertEqual(fetch.call_count,2)

    def test_kfinco_owns_one_budget_without_nested_original_retries(self):
        self.assertIs(kfinco.fetch_bytes,original.fetch_bytes_once)
        self.assertTrue(transient_dns(URLError(socket.gaierror(socket.EAI_AGAIN,'try again'))))
        self.assertFalse(transient_dns(URLError('DNS-like text is not a resolver exception')))


if __name__=='__main__':
    unittest.main()
