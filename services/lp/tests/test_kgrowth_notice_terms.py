"""Different notice IDs and amounts use the same source-derived rules."""
import unittest

from services.lp.src.kgrowth_notice_terms import extract_offering, discovery

DOCUMENT = '''「테스트 산업지원 펀드」 위탁운용사 선정계획 공고
1. 선정 개요
위탁운용
금액
▪ 테스트 펀드 : 240억원 이내
선정 운용사수
▪ 6개 운용사
신청자격
운용사 AUM 5,000억원, 제안규모 900억원
출자대상 투자기구
▪ 기관전용 사모집합투자기구
운용사 선정방법
종합 평가
접수일시
▪ 2026.11.12.(목) 10:00 ~ 15:30
심사결과 발표
▪ 2026년 12월중
2. 주요 출자조건
출자금액
구 분
운용사 수
펀드당 출자금액
총 출자금액
성장 리그
3개
30억원
240억원
혁신 리그
3개
50억원
주목적 투자
▪ 투자대상 기업은 법인 형태의 국내 중소·중견기업*으로 투자기간 내 아래의 주목적 투자대상(①, ② 모두 충족하여야 함)에 투자
① 중소기업에 모펀드 출자금액 이상을 투자
② 미래산업 기업에 「테스트 펀드」 출자금액의 40% 이상으로 투자비율 운용사 자율 제안
출자조건
수수료 및 운용조건
'''


def notice(text=DOCUMENT):
    url = 'https://www.kgrowth.or.kr/notice_view.asp?idx=76543&str_type=1&tab=1'
    attachment = 'https://www.kgrowth.or.kr/down_file.asp?idx=76543&SelType=Notice1'
    return {'source_id':'76543','institution_id':'kgrowth','title':'「테스트 산업지원 펀드」 위탁운용사 선정계획 공고',
            'date':'2026-10-08','url':url,'body':'붙임 공고문 참고','sha256':'official-body-hash',
            'attachments':[attachment],'attachment_hashes':{attachment:'official-file-hash'},
            'attachment_texts':{attachment:text}, 'attachment_documents':{attachment:{'format':'hwp','text':text,'tables':[]}}}


class OfferingTests(unittest.TestCase):
    def test_labeled_amounts_totals_deadline_and_original_provenance(self):
        n=notice(); facts=extract_offering(n)
        self.assertEqual(facts['commitment_amount_krw'],24_000_000_000)
        self.assertEqual(facts['manager_count_label'],'6개사')
        self.assertEqual([s['per_fund_amount_krw'] for s in facts['segments']],[3_000_000_000,5_000_000_000])
        self.assertEqual(sum(s['amount_krw'] for s in facts['segments']),facts['commitment_amount_krw'])
        self.assertEqual(facts['deadline'],'2026-11-12T15:30:00+09:00')
        self.assertEqual(facts['planned_schedule'][0]['date'],'2026-12')
        self.assertEqual(facts['planned_schedule'][0]['precision'],'month')
        for evidence in facts['extraction_evidence'].values():
            self.assertIn(evidence['quote'],DOCUMENT)
            self.assertEqual(evidence['attachment_url'],n['attachments'][0])
            self.assertEqual(evidence['sha256'],'official-file-hash')

    def test_proposal_examples_do_not_change_amount_or_legal_scope(self):
        n=notice();url='https://www.kgrowth.or.kr/down_file.asp?idx=76543&SelType=Notice2'
        form=DOCUMENT.replace('위탁운용사 선정계획 공고','출자신청 제출서류 및 관련서식')
        n['attachment_hashes'][url]='form-hash'
        n['attachment_texts'][url]=form.replace('240억원','990억원').replace('기관전용 사모집합투자기구','벤처투자조합')
        terms,holds,candidates=discovery([n])
        self.assertEqual(terms[n['url']]['commitment_amount_krw'],24_000_000_000)
        self.assertEqual(candidates[0]['scope'],'pe_eligible')
        self.assertFalse(holds)

    def test_ambiguous_ratio_never_becomes_fixed_investment_percentage(self):
        facts=extract_offering(notice())
        self.assertNotIn('40%',str(facts['primary_investment']))
        self.assertIn('미래산업 기업 투자',facts['primary_investment']['items'])
        self.assertTrue(facts['extraction_warnings'])
        self.assertIn('40%',facts['extraction_evidence']['주목적']['quote'])
        self.assertEqual(len(facts['primary_investment']['items']),3)

    def test_amount_count_or_column_mismatch_holds_instead_of_guessing(self):
        for text in (DOCUMENT.replace('▪ 6개','▪ 7개'),DOCUMENT.replace('30억원','40억원'),
                     DOCUMENT.replace('총 출자금액','펀드 최소결성금액'),DOCUMENT.replace('240억원','250억원'),
                     DOCUMENT.replace('15:30','09:30'), DOCUMENT.replace('240억원','240.5억원')):
            with self.subTest(text=text):
                terms,holds,_=discovery([notice(text)])
                self.assertFalse(terms)
                self.assertTrue(holds)

    def test_changed_notice_is_held_and_mixed_scope_is_retained(self):
        n=notice(DOCUMENT.replace('▪ 기관전용 사모집합투자기구','▪ 기관전용 사모집합투자기구, 벤처투자조합'))
        terms,_,candidates=discovery([n])
        self.assertEqual(candidates[0]['scope'],'mixed_legal_forms')
        self.assertTrue(terms)
        n['title']+=' 변경 공고'
        terms,holds,_=discovery([n])
        self.assertFalse(terms)
        self.assertIn('기존 사업',holds[0]['reason'])

    def test_corrupt_evidence_or_duplicate_offering_attachment_rejected(self):
        n=notice();n['attachment_hashes']={}
        with self.assertRaises(ValueError):extract_offering(n)
        n=notice();url='https://www.kgrowth.or.kr/down_file.asp?idx=76543&SelType=Notice2'
        n['attachment_texts'][url]=DOCUMENT;n['attachment_hashes'][url]='different-file'
        with self.assertRaisesRegex(ValueError,'여러 개'):extract_offering(n)

    def test_different_id_and_amount_use_same_rules(self):
        n=notice(DOCUMENT.replace('240억원','480억원').replace('30억원','60억원').replace('50억원','100억원'))
        n['source_id']='998877'
        self.assertEqual(extract_offering(n)['commitment_amount_krw'],48_000_000_000)

    def test_tracks_are_distinct_but_lifecycle_shares_business_identity(self):
        from services.lp.src.lp_notice_triage import program_key
        n=notice()
        general={**n,'title':'「테스트 산업지원 펀드」 일반매칭 위탁운용사 선정계획 공고'}
        local={**n,'title':'「테스트 산업지원 펀드」 지역전용 위탁운용사 선정계획 공고'}
        result={**general,'title':'「테스트 산업지원 펀드」 일반매칭 위탁운용사 선정결과 공고'}
        changed={**general,'title':'「테스트 산업지원 펀드」 일반매칭 위탁운용사 선정계획 변경 공고'}
        self.assertNotEqual(program_key(general),program_key(local))
        self.assertEqual(program_key(general),program_key(result))
        self.assertEqual(program_key(general),program_key(changed))
        for prefix,stage in (('【선정공고】','선정계획 공고'),('【접수현황】','접수현황'),
                             ('【선정결과】','선정결과 공고'),('【변경공고】','선정계획 변경 공고'),
                             ('【취소공고】','선정계획 취소 공고'),('【선정공고】','선정계획 공고(수정)')):
            actual={**general,'title':prefix+general['title'].replace('선정계획 공고',stage)}
            self.assertEqual(program_key(general),program_key(actual),actual['title'])


if __name__=='__main__':unittest.main()
