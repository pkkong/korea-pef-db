import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from scripts.inspect_lp_remaining_boards import pending_links, inspect_pending, PENDING_ROOTS


class PendingBoardTests(unittest.TestCase):
    def test_observed_menu_selection_keeps_board_parameters_and_rejects_details(self):
        html='''<html><a href="/board.do?menuNo=248&boardConfigNo=29">선정공고 자산운용</a>
        <a href="https://evil.example/notice">공지</a><a href="/board.do?boardNo=123">공고</a>
        <a href="/file.pdf">입찰</a><a href="/board.do?action=view">선정</a>
        <a href="javascript:go()">공지</a><a href="/notice">공지사항</a>
        <a href="/third">입찰</a><a href="/board.do?type=view">공지</a></html>'''
        links=pending_links(html,PENDING_ROOTS['cwma'],'cwma')
        self.assertEqual([r['url'] for r in links['menus']],
            ['https://www.cw.or.kr/board.do?menuNo=248&boardConfigNo=29','https://www.cw.or.kr/notice'])
        self.assertEqual(links['scripts'],[])

    def test_nps_scripts_first_party_and_bounded(self):
        html=''.join('<script src="'+url+'"></script>' for url in
            ['/jquery.js','/board.js','/ohef.js','/fourth.js','https://evil.example/x.js','http://fund.nps.or.kr/x.js'])
        selected=pending_links(html,PENDING_ROOTS['nps'],'nps')
        self.assertEqual(selected['scripts'],['https://fund.nps.or.kr/board.js','https://fund.nps.or.kr/ohef.js'])
        self.assertEqual(pending_links(html,PENDING_ROOTS['cwma'],'cwma')['scripts'],[])

    def test_max_four_roots_eight_menus_two_scripts_and_hash_receipts(self):
        calls=[]
        html='<html><a href="/notice">공지</a><a href="/bid">입찰</a><a href="/third">선정</a><script src="/board.js"></script><script src="/ohef.js"></script></html>'.encode()
        # Use UTF-8 fixtures explicitly; requests are all injected, no network.
        def fetch(url,limit):
            calls.append(url);self.assertLessEqual(limit,3*1024*1024)
            return 200,url,html
        with tempfile.TemporaryDirectory() as folder:
            report=inspect_pending(Path(folder),fetch)
            self.assertEqual(len(calls),14)
            self.assertEqual(len(calls),len(set(calls)))
            for row in report['responses']:
                raw=(Path(folder)/row['file']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),row['sha256'])

    def test_oversize_cross_origin_and_http_errors_are_retained_failures(self):
        for mode in ['size','origin','http']:
            def fetch(url,limit):
                if mode=='size':return 200,url,b'x'*(limit+1)
                if mode=='origin':return 200,'https://evil.example/',b'body'
                return 503,url,b'public unavailable'
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(SystemExit):inspect_pending(Path(folder),fetch)
                report=json.loads((Path(folder)/'index.json').read_text())
                self.assertEqual(report['requests'],4)
                self.assertEqual(len(report['holds']),4)
                self.assertTrue(all(r['kind']=='root' for r in report['responses']))


if __name__=='__main__':unittest.main()
