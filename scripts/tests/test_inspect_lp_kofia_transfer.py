from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts import inspect_lp_kofia_transfer as m


class KofiaTransferTests(unittest.TestCase):
    def test_bounded_cases_preserve_failed_bytes_and_filter_headers(self):
        calls=[]
        def run(command,**kwargs):
            calls.append(command)
            Path(command[command.index('--output')+1]).write_bytes(b'<html>public response</html>')
            Path(command[command.index('--dump-header')+1]).write_text('Content-Length: 100\nSet-Cookie: PRIVATE\nContent-Type: text/html\n')
            return subprocess.CompletedProcess(command,18,b'200',b'partial')
        with tempfile.TemporaryDirectory() as folder:
            result=m.inspect(folder,run)
            self.assertEqual(len(result['responses']),3)
            self.assertTrue(all(r['curl_exit']==18 and r['complete_html'] for r in result['responses']))
            self.assertFalse(list(Path(folder).glob('*.tmp')))
        self.assertNotIn('PRIVATE',str(result))
        self.assertTrue(all(c[-1].startswith('https://www.kofia.or.kr/brd/m_') for c in calls))
        self.assertEqual(sum('--compressed' in c for c in calls),1)
        self.assertTrue(all('--location' not in c for c in calls))

    def test_partial_html_and_transfer_failure_remain_distinct(self):
        def run(command,**kwargs):
            Path(command[command.index('--output')+1]).write_bytes(b'<html>truncated')
            return subprocess.CompletedProcess(command,18,b'200',b'partial')
        with tempfile.TemporaryDirectory() as folder:
            result=m.inspect(folder,run)
        self.assertTrue(all(not r['complete_html'] and r['curl_exit']==18 for r in result['responses']))

    def test_timeout_is_recorded_without_diagnostics_or_stopping_other_cases(self):
        def run(*args,**kwargs):raise subprocess.TimeoutExpired('PRIVATE',30)
        with tempfile.TemporaryDirectory() as folder:result=m.inspect(folder,run)
        self.assertEqual(len(result['responses']),3)
        self.assertNotIn('PRIVATE',str(result))
        self.assertTrue(all(r['error_type']=='TimeoutExpired' for r in result['responses']))


if __name__=='__main__':unittest.main()
