import copy
from urllib.parse import parse_qs,urlsplit
from unittest.mock import MagicMock
import unittest
from services.lp.src import collect_lp_institution_boards as b
from services.lp.src.lp_notice_publication import _scope
from services.lp.tests import test_lp_board_adapter_nh as nh
from services.lp.tests import test_lp_board_adapter_suhyup as sh

STAMP='2099-03-05T00:00:00+00:00'


class CentralCollectionTests(unittest.TestCase):
    def test_pending_sources_are_explicit_opt_in_and_not_a_scheduled_rollout(self):
        active=b.load_configs();all_configs=b.load_configs(include_pending=True)
        self.assertNotIn('nh_central',active);self.assertNotIn('suhyup',active)
        self.assertIn('nh_central',all_configs);self.assertIn('suhyup',all_configs)

    def test_nh_two_boards_finish_their_own_search_stream_and_replay(self):
        config=copy.deepcopy(b.load_configs(include_pending=True)['nh_central'])
        config.update(searches=['운용사'],pages=3)
        calls=[]
        def fetch(url,referer=None):
            calls.append(url);board='notice' if '/notice/' in url else 'bid'
            if 'List.do' in url:
                html=nh.fixture(board,total=1,term='운용사')
                return html.replace('<button class="btn_next0" onclick="fn_select_brdList(1);return false; ">마지막</button>','').encode()
            return nh.detail().replace('BBSMSTR_000000000019',b.nh.BOARDS[board]).replace('(은행 )펀드 안내장 제작','2099 국내 펀드 운용사 모집').replace('2099.01.02','2099.03.04').replace('공고.zip','제안서 양식.zip').encode()
        result=b.collect({'nh_central':config},lambda _:fetch,STAMP,retry_failures=False)
        self.assertEqual(result['holds'],[]);self.assertEqual(len(result['notices']),2)
        self.assertEqual(len([u for u in calls if 'List.do' in u]),2)
        self.assertEqual(len(result['coverage']['nh_central']['listing_boundaries']),2)
        for n in result['notices']:
            self.assertEqual(b.validate_notice(n,STAMP,config),n)
            forged=copy.deepcopy(n);forged['issuer_evidence']['status']='central_explicit'
            with self.assertRaises(ValueError):b.validate_notice(forged,STAMP,config)

    def test_suhyup_collector_normalizes_badges_and_retains_observed_public_links(self):
        config=copy.deepcopy(b.load_configs(include_pending=True)['suhyup']);config.update(searches=['운용사'],pages=3)
        calls=[]
        def fetch(url,referer=None):
            calls.append(url)
            return (sh.detail().replace('모집 공고.hwp','제안서 양식.hwp') if 'artclView.do' in url else sh.listing(total=1,term='운용사')).encode()
        result=b.collect({'suhyup':config},lambda _:fetch,STAMP,retry_failures=False)
        self.assertEqual(result['holds'],[]);self.assertEqual(len(result['notices']),1)
        self.assertEqual(len(calls),2)
        self.assertEqual(b.validate_notice(result['notices'][0],STAMP,config),result['notices'][0])

    def test_suhyup_public_form_bootstrap_once_then_post_and_file_get(self):
        config=b.load_configs(include_pending=True)['suhyup'];session=b.Session(config);session.opener=MagicMock()
        response=session.opener.open.return_value.__enter__.return_value
        response.read.side_effect=[sh.listing(total=1).encode(),b'page1',b'page2',b'file']
        url=next(b.listing_urls(config));session(url)
        session(url.replace('page=1','page=2'));session(b.suhyup.BASE+'/bbs/suhyup/23/88001/download.do')
        requests=[call.args[0] for call in session.opener.open.call_args_list]
        self.assertEqual([r.get_method() for r in requests],['GET','POST','POST','GET'])
        fields=[parse_qs(r.data.decode(),keep_blank_values=True) for r in requests[1:3]]
        self.assertEqual(fields[0]['layout'],['observed-public-theme'])
        self.assertEqual(fields[0]['page'],['1']);self.assertEqual(fields[1]['page'],['2'])
        self.assertEqual(fields[0]['srchColumn'],['sj'])

    def test_nh_portal_footer_or_forged_flag_cannot_publish_an_affiliate_as_central(self):
        n={'institution_id':'nh_central','source_channel':'institution_board','title':'국내 PE 블라인드 펀드 위탁운용사 모집',
           'body':'선정유형: 국내 블라인드 PEF. NH농협은행 안내자료.',
           'issuer_evidence':{'status':'central_explicit'}}
        self.assertEqual(_scope(n),'needs_confirmation')
        n['body']='발주기관: 농협중앙회\n선정유형: 국내 블라인드 PEF.'
        self.assertEqual(_scope(n),'pe_blind')
        n['body']='안내문 하단에 농협중앙회라고 표시. 선정유형: 국내 블라인드 PEF.'
        self.assertEqual(_scope(n),'needs_confirmation')
        n.update(institution_id='suhyup',title='수협은행 국내 PE 블라인드 공고')
        self.assertEqual(_scope(n),'outside')


if __name__=='__main__':unittest.main()
