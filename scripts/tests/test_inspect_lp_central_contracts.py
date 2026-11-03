from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import inspect_lp_central_contracts as m
from services.lp.tests.test_lp_board_adapter_nh import fixture as nh_fixture


def suhyup():
    return '''<html><form name="searchForm" method="post" action="/bbs/suhyup/23/artclList.do"><select name="srchColumn"><option value="sj">제목</option></select></form><form name="pageForm" method="post" action="/bbs/suhyup/23/artclList.do"><input name="layout" value="public-theme"><input name="page" value="1"><input name="srchColumn" value=""><input name="srchWrd" value=""><input name="isViewMine" value="false"></form><table class="board-link-list"><tr><td><a href="/bbs/suhyup/23/99999/artclView.do" onclick="jf_viewArtcl('suhyup','23','99999')">2099년 국내 사모펀드 모집</a></td></tr></table></html>'''


class CentralContractsTests(unittest.TestCase):
    def test_observed_post_searches_and_opaque_theme(self):
        target,fields=m.search_contract(nh_fixture(),m.ROOTS['nh_central'][0],'nh_central')
        self.assertEqual(fields['searchCnd'],'1');self.assertEqual(fields['intgBsnBlbdGrpC'],m.nh.BOARDS['notice'])
        target,fields=m.search_contract(suhyup(),m.ROOTS['suhyup'][0],'suhyup')
        self.assertEqual(target,'https://www.suhyup.co.kr/bbs/suhyup/23/artclList.do')
        self.assertEqual(fields['layout'],'public-theme');self.assertEqual(fields['srchColumn'],'sj')
        with self.assertRaises(ValueError):m.search_contract(suhyup().replace('value="sj"','value="writer"'),m.ROOTS['suhyup'][0],'suhyup')

    def test_arbitrary_observed_notice_ids_and_foreign_controls(self):
        sample=m.samples(nh_fixture(),m.ROOTS['nh_central'][0],'nh_central')[0]
        self.assertEqual(sample['fields']['blbdSqno'],'90011')
        sample=m.samples(suhyup(),m.ROOTS['suhyup'][0],'suhyup')[0]
        self.assertTrue(sample['url'].endswith('/99999/artclView.do'))
        with self.assertRaises(ValueError):m.samples(suhyup().replace('/bbs/suhyup/23/99999/artclView.do','https://evil.invalid/view'),m.ROOTS['suhyup'][0],'suhyup')

    def test_full_injected_receipts_are_bounded_and_preserve_search_fields(self):
        calls=[]
        def fetch(url,fields,parent,limit):
            calls.append((url,fields))
            if 'nonghyup.com' in url:
                board='notice' if '/notice/' in url else 'bid'
                raw=nh_fixture(board).encode() if 'List.do' in url else b'<html>public detail</html>'
            else:raw=suhyup().encode() if 'artclView' not in url else b'<html>public detail</html>'
            return 200,url,raw
        with tempfile.TemporaryDirectory() as folder:
            report=m.inspect(folder,fetch)
            self.assertEqual(report['holds'],[]);self.assertEqual(report['requests'],17)
            self.assertTrue((Path(folder)/'index.json').exists())
        self.assertEqual({fields['searchWrd'] for url,fields in calls if fields and 'searchWrd' in fields},set(m.TERMS))
        self.assertTrue(all(r['sha256'] for r in report['responses']))

    def test_failures_and_request_limit_do_not_create_success(self):
        def fetch(url,fields,parent,limit):return 503,url,b'unavailable'
        with tempfile.TemporaryDirectory() as folder:
            report=m.inspect(folder,fetch)
        self.assertEqual(report['requests'],3);self.assertEqual(len(report['holds']),3)
        with tempfile.TemporaryDirectory() as folder,patch.object(m,'MAX_REQUESTS',1):
            report=m.inspect(folder,fetch)
        self.assertEqual(report['requests'],1);self.assertEqual(len(report['holds']),3)


if __name__=='__main__':unittest.main()
