import copy
import unittest
from services.lp.src import lp_kbiz_notice_terms as terms
from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src.lp_notice_publication import publish_basic_notices
from services.lp.tests.test_lp_board_adapter_kbiz import HTML,DETAIL

TITLE='2026년도 중소기업중앙회 국내 블라인드 펀드 선정 공고'
BODY=('선정 개요 운용방식 블라인드 형태의 PE·VC 펀드 투자기구 [PE] 자본시장법에 의한 기관전용 사모집합투자기구 '
      '* 경영참여 목적 투자를 포함하여 운용 [VC] 벤처투자조합 '
      '선정 운용사 수 및 배정금액 10개사 내외, 100~800억원 범위 내 출자규모 총 3,000억원 이내 '
      '신청 자격 각 운용사는 매년 1개 부문의 출자사업에만 지원 가능 (PE/VC 공통) '
      '진행 일정 정량평가 및 현장실사 2026.8~9월 기술능력평가(정성, PT) 2026.9월 '
      '내부 승인절차 및 결과통보 2026.9월 제출기한: 2026.7.31(금) 15:00 '
      '메일 제목 예시: [26년/PE 또는 VC 택1] 펀드명')
STAMP='2026-10-26T00:00:00+00:00'


def collection():
    config={**boards.load_configs()['kbiz'],'searches':['블라인드'],'pages':1}
    listing=HTML.replace('국내 PE 펀드 모집',TITLE).replace('value="PE"','value="블라인드"').replace('schTxt=PE','schTxt=블라인드')
    detail=DETAIL.replace('[사업공고] 국내 펀드 모집','[사업공고] '+TITLE)
    start=detail.index('<div class="detail-body">');end=detail.index('<div class="navigation">')
    detail=detail[:start]+'<div class="detail-body">'+BODY+'</div>'+detail[end:]
    detail=detail.replace('선정계획.hwp','제안서 양식.hwp')
    return boards.collect({'kbiz':config},lambda c:lambda url,referer=None:(detail if 'view.do?' in url else listing).encode(),STAMP)


class KbizTrackTests(unittest.TestCase):
    def test_independent_track_publishes_without_shared_allocations(self):
        report=collection();self.assertFalse(report['holds'])
        n=report['notices'][0];result=terms.terms(n)
        self.assertEqual(result['deadline'],'2026-07-31T15:00:00+09:00')
        self.assertEqual(len(result['schedule_stages']),3)
        self.assertEqual(result['schedule_stages'][0]['end_date'],'2026-09')
        for field in ('commitment_amount_krw','manager_count','segments','per_fund_amount_krw'):
            self.assertNotIn(field,result)
        # Use configured fixture pages for replay, preserving production checks.
        from unittest.mock import patch
        config={**boards.load_configs()['kbiz'],'searches':['블라인드'],'pages':1}
        with patch.object(boards,'load_configs',return_value={'kbiz':config}):
            programs,holds=publish_basic_notices({'programs':[],'institution_notices':report['notices']},[],STAMP)
        self.assertFalse(holds);self.assertEqual(len(programs),1)
        self.assertEqual(programs[0]['asset_scope'],'PE');self.assertFalse(programs[0]['selected_gps'])
        self.assertNotIn('commitment_amount_krw',programs[0]);self.assertNotIn('manager_count',programs[0])

    def test_current_pe_and_separate_application_are_both_required(self):
        n={'institution_id':'kbiz','title':TITLE,'body':BODY,'url':'https://www.kbiz.or.kr/example','date':'2026-07-10','sha256':'a'*64}
        self.assertTrue(terms.pe_track(n))
        for body in [BODY.replace('투자기구 [PE]','과거 펀드 [PE]'), BODY.replace('PE 또는 VC 택1','담당자 문의'),
                     BODY.replace('각 운용사는 매년 1개 부문의 출자사업에만 지원 가능 (PE/VC 공통)','운용사 공동 지원')]:
            self.assertFalse(terms.pe_track(dict(n,body=body)))
        self.assertFalse(terms.pe_track(dict(n,title=TITLE+' 외부 평가기관 선정')))
