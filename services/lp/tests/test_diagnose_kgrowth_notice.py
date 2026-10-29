import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import diagnose_kgrowth_notice as d


class DiagnosticTests(unittest.TestCase):
    def test_input_rejected_before_transport_or_files(self):
        for value in ('', '0', '01', '-1', '1000000000', '1&x=2', '1\n', 'https://evil.test', '１'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                transport = MagicMock()
                with self.assertRaises(ValueError):
                    d.diagnose(value, Path(folder) / 'out', transport)
                transport.assert_not_called()
                self.assertFalse((Path(folder) / 'out').exists())

    def test_invalid_content_saved_without_changing_parser_contract(self):
        raw = b'<html>error</html>'
        with tempfile.TemporaryDirectory() as folder:
            result = d.diagnose('123', folder, lambda url: (200, url, raw))
            self.assertEqual(result['parse_result'], 'invalid_content')
            self.assertEqual(result['error_type'], 'ValueError')
            self.assertEqual(result['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual((Path(folder) / 'response.html').read_bytes(), raw)
            self.assertEqual(json.loads((Path(folder) / 'metadata.json').read_text()), result)
        with self.assertRaises(ValueError):
            d.parse_notice(123, raw)

    def test_valid_metadata_and_http_failure(self):
        raw = '<div class="view_info"><p class="tit">공고</p><p class="date">2026-10-29</p></div><div class="veiw_contents">본문</div>'.encode('cp949')
        with tempfile.TemporaryDirectory() as folder:
            result = d.diagnose('123', folder, lambda url: (200, url, raw))
            self.assertEqual((result['title'], result['date']), ('공고', '2026-10-29'))
            result = d.diagnose('123', folder, lambda url: (503, url, raw))
            self.assertEqual(result['parse_result'], 'http_error')
            self.assertNotIn('title', result)

    def test_bad_route_and_size_not_saved(self):
        for final, raw in [('https://evil.test/', b'content'), (d.notice_url(123), b'x' * (d.MAX_BYTES + 1))]:
            with self.subTest(final=final), tempfile.TemporaryDirectory() as folder:
                result = d.diagnose('123', folder, lambda url: (200, final, raw))
                self.assertEqual(result['parse_result'], 'transport_error')
                self.assertFalse((Path(folder) / 'response.html').exists())

    def test_transport_bounded_and_redirects_fail_closed(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = d.notice_url(123)
        response.code = 200
        response.read.return_value = b'x' * (d.MAX_BYTES + 1)
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(d, 'build_opener', return_value=opener):
            with self.assertRaises(ValueError):
                d.fetch(d.notice_url(123))
        response.read.assert_called_once_with(d.MAX_BYTES + 1)
        self.assertEqual(opener.open.call_args.kwargs, {'timeout': 25})
        self.assertEqual(opener.open.call_count, 1)
        with self.assertRaises(ValueError):
            d.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test/')

    def test_network_retries_are_bounded_and_errors_redacted(self):
        from urllib.error import URLError
        opener = MagicMock()
        opener.open.side_effect = URLError('sensitive diagnostic detail')
        with tempfile.TemporaryDirectory() as folder, patch.object(d, 'build_opener', return_value=opener), patch.object(d.time, 'sleep'):
            result = d.diagnose('123', folder)
            self.assertEqual(opener.open.call_count, 3)
            self.assertEqual(result['error_type'], 'URLError')
            self.assertNotIn('sensitive', (Path(folder) / 'metadata.json').read_text())


if __name__ == '__main__':
    unittest.main()
