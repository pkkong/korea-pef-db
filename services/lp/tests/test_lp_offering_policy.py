import copy
import unittest
from services.lp.src.lp_notice_publication import _scope
from services.lp.src.lp_offering_policy import procurement_reason
from services.lp.src.audit_lp_candidate_sources import official_scope
from services.lp.src import collect_lp_institution_boards as b
from services.lp.tests import test_lp_board_adapter_nh as nh


class OfferingPolicyTests(unittest.TestCase):
    def test_vendor_procurements_require_matching_official_body_not_a_keyword_alone(self):
        title='새 펀드 미스터리쇼핑 용역 업체선정 입찰공고'
        body='미스터리쇼핑 용역. 사업예산: 1억원. 계약방법: 협상.'
        self.assertEqual(procurement_reason(title,body),'fund_sales_monitoring_procurement')
        self.assertIsNone(procurement_reason(title,'첨부 참조'))
        self.assertIsNone(procurement_reason('국내 PE 블라인드 펀드 운용사 선정',body))
        self.assertIsNone(procurement_reason('국내 PE 블라인드 모집 및 미스터리쇼핑 용역 입찰',body))
        n={'institution_id':'nh_central','title':title,'body':body}
        self.assertEqual(_scope(n),'outside')
        self.assertEqual(official_scope(n),('outside_policy','fund_sales_monitoring_procurement'))
        self.assertEqual(procurement_reason('출자정보지원 재해복구시스템 구축 입찰','공고명: 출자정보지원 재해복구시스템 구축. ICT전략실.'),'it_disaster_recovery_procurement')

    def test_no_download_for_verified_noninvestment_procurement_but_body_proof_is_kept(self):
        config=copy.deepcopy(b.load_configs(include_pending=True)['nh_central']);config.update(listing_urls=[config['listing_url']],searches=['펀드'],pages=1)
        title='2099년 펀드 미스터리쇼핑 용역 업체선정 입찰공고'
        def fetch(url,referer=None):
            if 'FileDown.do' in url:raise AssertionError('noninvestment attachment must not be fetched')
            if 'List.do' in url:
                html=nh.small(1).replace('2099 국내 펀드 운용사 모집',title).replace('name="searchWrd" value=""','name="searchWrd" value="펀드"').replace('<option value="1">','<option value="1" selected>')
            else:
                html=nh.detail().replace('BBSMSTR_000000000019',b.nh.BOARDS['notice']).replace('(은행 )펀드 안내장 제작',title).replace('2099.01.02','2099.03.04').replace('NH농협은행 안내장 제작','미스터리쇼핑 용역. 사업예산: 1억원. 계약방법: 협상.')
            return html.encode()
        report=b.collect({'nh_central':config},lambda _:fetch,'2099-03-05T00:00:00+00:00',retry_failures=False)
        self.assertEqual(report['holds'],[]);self.assertEqual(len(report['notices']),1)
        n=report['notices'][0];self.assertEqual(n['attachment_bytes'],{})
        self.assertEqual(b.validate_notice(n,report['checked_at'],config),n)

    def test_member_contract_is_not_a_central_lp_commitment_and_forms_are_ignored(self):
        url='https://www.nonghyup.com/cmm/fms/FileDown.do?atchFileId=FILE_999999&fileSn=0'
        n={'institution_id':'nh_central','source_channel':'institution_board','url':'https://www.nonghyup.com/ecenter/bid/bidView.do?intgBsnBlbdGrpC=BBSMSTR_000000000019&blbdSqno=90001',
           'title':'국내 PE 블라인드 자산운용사 선정','body':'발주기관: 농협중앙회\n선정유형: 국내 블라인드 PEF.',
           'attachments':[{'url':url,'name':'모집 공고.zip'}],'attachment_hashes':{url:'a'*64},
           'attachment_texts':{url:'농협중앙회가 직접 계약서 체결 및 자금 출자를 진행하지 않음. 개별 회원조합과 자산매각 및 투자 계약을 각각 개별적으로 체결함.'}}
        self.assertEqual(_scope(n),'outside')
        n['attachments'][0]['name']='제안서 양식.hwp'
        self.assertEqual(_scope(n),'pe_blind')


if __name__=='__main__':unittest.main()
