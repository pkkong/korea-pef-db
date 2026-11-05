from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts import inspect_lp_kofia_transfer as m


class KofiaTransferTests(unittest.TestCase):
    def test_compressed_pagination_keeps_observed_urls_and_request_cap(self):
        root=b'<html><table><tr><td><a href="view.do?seq=987654">Synthetic notice</a></td></tr></table><a href="list.do?page=2">2</a><a href="list.do?page=3">3</a></html>'
        calls=[]
        def run(command,**kwargs):
            calls.append(command)
            Path(command[command.index('--output')+1]).write_bytes(root)
            return subprocess.CompletedProcess(command,0,b'200',b'')
        with tempfile.TemporaryDirectory() as folder:
            result=m.inspect(folder,run,page_encoding='compressed')
        self.assertEqual(len(calls),7)
        self.assertTrue(all('--compressed' in c and 'Accept-Encoding: identity' not in c for c in calls[3:]))
        self.assertTrue(all(r['encoding']=='compressed' and r['usable_listing'] for r in result['responses'][3:]))
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            m.inspect(folder,run,page_encoding='other')

    def test_observed_pages_compare_two_framings_with_seven_request_cap(self):
        calls=[]
        root=b'<html><table><tr><td><a href="view.do?seq=987654">Synthetic notice</a></td></tr></table><a href="list.do?page=2&srchWord=observed">2</a><a href="list.do?page=3&srchWord=observed">3</a><a href="list.do?page=4">4</a></html>'
        def run(command,**kwargs):
            calls.append(command)
            Path(command[command.index('--output')+1]).write_bytes(root)
            return subprocess.CompletedProcess(command,0,b'200',b'')
        with tempfile.TemporaryDirectory() as folder:
            result=m.inspect(folder,run)
        self.assertEqual(len(calls),7);self.assertEqual(result['requests'],7)
        extra=result['responses'][3:]
        self.assertEqual([r['http_version'] for r in extra],['1.1','1.0','1.1','1.0'])
        self.assertTrue(all(r['encoding']=='identity' and r['usable_listing'] for r in extra))
        self.assertTrue(all(r['observed_on']['sha256']==result['responses'][0]['sha256'] for r in extra))
        self.assertEqual([r['url'] for r in extra],[m.ROOT.format('17')+'?page=2&srchWord=observed']*2+[m.ROOT.format('17')+'?page=3&srchWord=observed']*2)
        for command in calls:
            self.assertEqual(command[:2],['curl','--disable'])
            self.assertEqual(command[command.index('--max-time')+1],'25')
            self.assertNotIn('--insecure',command);self.assertNotIn('--location',command)

    def test_failed_complete_root_cannot_authorize_pagination(self):
        root=b'<html><table><tr><td><a href="view.do?seq=77">notice</a></td></tr></table><a href="list.do?page=2">2</a></html>'
        def run(command,**kwargs):
            Path(command[command.index('--output')+1]).write_bytes(root)
            return subprocess.CompletedProcess(command,18,b'200',b'')
        with tempfile.TemporaryDirectory() as folder:result=m.inspect(folder,run)
        self.assertEqual(result['requests'],3)
        self.assertTrue(all(r['complete_html'] and not r['usable_listing'] for r in result['responses']))

    def test_first_successful_root_only_and_foreign_or_duplicate_page_rejected(self):
        calls=[]
        root=b'<html><table><tr><td><a href="view.do?seq=77">notice</a></td></tr></table><a href="https://evil.invalid/brd/m_17/list.do?page=2">2</a><a href="list.do?page=3&page=99">3</a></html>'
        def run(command,**kwargs):
            calls.append(command)
            Path(command[command.index('--output')+1]).write_bytes(root)
            return subprocess.CompletedProcess(command,0,b'200',b'')
        with tempfile.TemporaryDirectory() as folder:result=m.inspect(folder,run)
        self.assertEqual(len(calls),3)
        self.assertEqual(result['responses'][0]['pagination_holds'][0]['page'],3)
        for url in ('http://www.kofia.or.kr/brd/m_17/list.do?page=2','https://www.kofia.or.kr:443/brd/m_17/list.do?page=2','https://www.kofia.or.kr/brd/m_212/list.do?page=2'):
            with self.assertRaises(ValueError):m.safe_listing(url,'kofia_17',2)

    def test_timeout_retains_partial_bytes_without_authorizing_pages(self):
        def run(command,**kwargs):
            Path(command[command.index('--output')+1]).write_bytes(b'<html>partial')
            raise subprocess.TimeoutExpired('PRIVATE',30)
        with tempfile.TemporaryDirectory() as folder:
            result=m.inspect(folder,run)
            self.assertEqual(result['requests'],3)
            self.assertTrue(all(r['bytes']==13 and not r['transport_ok'] and not r['complete_html'] for r in result['responses']))
            self.assertTrue(all((Path(folder)/r['file']).exists() for r in result['responses']))

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
