import unittest
from services.lp.src.lp_institution_notice_terms import extract_terms


class InstitutionTermsTests(unittest.TestCase):
    def notice(self, body, title='국내 PE 블라인드 위탁운용사 선정 공고'):
        return {'url':'https://www.pmaa.or.kr/notice', 'title':title, 'date':'2025-01-01',
                'body':body,'sha256':'a'*64,'attachment_texts':{}}

    def test_pe_vc_totals_and_count_are_independently_reconciled(self):
        n=self.notice('출자 규모 : 총 1,800억원 - PE 부문 (1,200억원) : 각 400억원, 총 3개사 - VC 부문 (600억원) : 각 200억원, 총 3개사', '국내 PE·VC 블라인드 위탁운용사 선정 공고')
        result=extract_terms(n)
        self.assertEqual(result['commitment_amount_krw'],120_000_000_000)
        self.assertEqual(result['manager_count'],3)
        self.assertEqual(result['per_fund_amount_krw'],40_000_000_000)
        self.assertEqual(result['amount_scope'],'pe_only')
        with self.assertRaises(ValueError):
            extract_terms({**n,'body':n['body'].replace('1,800','1,900')})

    def test_blind_and_coinvestment_are_not_summed(self):
        n=self.notice('모집규모 : Buyout·Growth 2,000억원 이내 4개사 / 공동투자 1,500억원 이내 1개사')
        result=extract_terms(n)
        self.assertEqual(result['commitment_label'],'2,000억원 이내')
        self.assertEqual(result['manager_count'],4)
        self.assertTrue(result['extraction_evidence']['blind_allocation'])

    def test_per_fund_limit_is_never_whole_total(self):
        result=extract_terms(self.notice('펀드별 출자금액 : 펀드당 500억원 이내. 선정 운용사 수 - 미정'))
        self.assertEqual(result['per_fund_amount_krw'],50_000_000_000)
        self.assertNotIn('commitment_amount_krw',result)
        self.assertNotIn('manager_count',result)

    def test_conflicting_delivery_cutoff_retains_only_date(self):
        result=extract_terms(self.notice('마감일시: 2025.7.22.(화) 12:00 접수마감 7월22일 12시. 직접제출 : 퀵은 당일 한정(7월22일(화)15시까지 미제출시 접수불가)'))
        self.assertEqual(result['deadline'],'2025-07-22')
        self.assertEqual(result['deadline_precision'],'date')
        self.assertIn('불일치',result['deadline_error'])

    def test_one_digit_day_keeps_the_date_time_boundary(self):
        result=extract_terms(self.notice('제출기한: 2025.7.1 15:00'))
        self.assertEqual(result['deadline'],'2025-07-01T15:00:00+09:00')
        ambiguous=extract_terms(self.notice('제출기한: 2025.7.115:00'))
        self.assertNotIn('deadline',ambiguous)
        self.assertIn('경계',ambiguous['deadline_error'])

    def test_total_count_qualifier_and_labeled_deadline(self):
        result=extract_terms(self.notice('위탁운용금액 : 총 4,000억원 이내. 선정 운용사 수 : 평가결과 상위 4개사 이내. 배정금액 : 1개사별 1,000억원 이하. 제출기한 : 2025년 9월 5일 오후 3시까지'))
        self.assertEqual(result['commitment_label'],'4,000억원 이내')
        self.assertEqual(result['manager_count_label'],'4개사 이내')
        self.assertEqual(result['per_fund_qualifier'],'이내')
        self.assertEqual(result['deadline'],'2025-09-05T15:00:00+09:00')


class CwmaOfferingTermsTests(unittest.TestCase):
    # The labelled rows come from the retained 2023 issuer attachment.
    overview = """1. 선정개요
구    분
사모투자펀드
운용방식
ㆍ블라인드형
선정방식
ㆍ공개모집 공고를 통해 일괄심사방식으로 선정
운용사 수
ㆍ2개사 이내
공제회 약정금액
ㆍ총 600억원(운용사당 300억원) 이내
최소 결성금액
ㆍ1,500억원(공제회 출자비율: 펀드결성총액의 20% 이하)
투자기구
․기관전용사모집합투자기구※ 경영참여 목적 투자를 포함하여 운용하며, 창업·벤처전문사모투자기구 제외
2. 주요 출자조건
"""

    def notice(self, attachment):
        url = 'https://www.cw.or.kr/upload/boardAdmin/offer.hwp'
        return {'institution_id': 'cwma', 'title': '2023년도 대체투자(국내 사모투자펀드) 위탁운용사 선정 공고',
                'url': 'https://www.cw.or.kr/board.do', 'date': '2023-03-03', 'sha256': 'a'*64,
                'body': "제안서 제출기한 : '23.03.17.(금) 11시",
                'attachment_hashes': {url: 'b'*64}, 'attachment_texts': {url: attachment}}

    def test_preserves_whole_pe_limit_and_per_manager_limit(self):
        result = extract_terms(self.notice(self.overview))
        self.assertEqual(result['commitment_amount_krw'], 60_000_000_000)
        self.assertEqual(result['commitment_label'], '600억원 이내')
        self.assertEqual(result['manager_count_label'], '2개사 이내')
        self.assertEqual(result['per_fund_amount_krw'], 30_000_000_000)
        self.assertEqual(result['fund_target_label'], '최소 1,500억원')
        self.assertEqual(result['deadline'], '2023-03-17T11:00:00+09:00')
        self.assertEqual(result['extraction_evidence']['pe_allocation'][0]['sha256'], 'b'*64)

    def test_rejects_inconsistent_total_and_parallel_rows(self):
        for source in (self.overview.replace('600억원', '900억원'),
                       self.overview.replace('운용사 수', '운용사 수\nㆍ3개사 이내\n운용사 수')):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'CWMA'):
                extract_terms(self.notice(source))

    def test_does_not_use_same_terms_for_credit_or_others(self):
        n = self.notice(self.overview)
        self.assertNotIn('commitment_amount_krw',
                         extract_terms({**n, 'title': '국내 선순위 인수금융펀드 위탁운용사 선정계획'}))
        self.assertNotIn('commitment_amount_krw', extract_terms({**n, 'institution_id': 'other'}))


class DeadlineCaptionTests(unittest.TestCase):
    """고용보험기금 2026: time is given per track after the date."""

    def notice(self, body):
        return {'url': 'https://www.moel.go.kr/x', 'body': body, 'sha256': 's', 'attachment_hashes': {},
                'title': '2026년 고용보험기금 대체투자상품(PEF, VC) 선정 공고', 'date': '2026-08-07',
                'institution_id': 'moel_eif'}

    def test_pe_track_time_after_the_date(self):
        result = extract_terms(self.notice('□ 제안서 접수 마감일: 2026. 8. 20.(목) (PEF 오전 11시까지, VC 오후 4시까지)'))
        self.assertEqual(result['deadline'], '2026-08-20T11:00:00+09:00')
        self.assertEqual(result['deadline_precision'], 'datetime')

    def test_labelled_date_without_time_is_date_only(self):
        result = extract_terms(self.notice('□ 제안서 접수 마감일: 2026. 8. 20.(목)'))
        self.assertEqual((result['deadline'], result['deadline_precision']), ('2026-08-20', 'date'))

    def test_two_labelled_dates_give_no_deadline(self):
        result = extract_terms(self.notice('접수마감일: 2026. 8. 20. 그리고 접수마감일: 2026. 8. 27.'))
        self.assertNotIn('deadline', result)


class IaciScheduleIntegrationTests(unittest.TestCase):
    def notice(self, year=2025):
        from services.lp.tests.test_lp_moel_iaci_notice_terms import notice
        return notice(year)

    def test_schedule_deadline_keeps_other_offering_facts_and_attachment_evidence(self):
        n = self.notice()
        n['body'] += ' 위탁운용금액: 총 2,400억원 이내'
        result = extract_terms(n)
        self.assertEqual(result['deadline'], '2025-04-18T16:00:00+09:00')
        self.assertEqual(result['commitment_amount_krw'], 240_000_000_000)
        self.assertEqual(result['extraction_evidence']['deadline'][0]['source_url'], n['attachments'][0]['url'])

    def test_joint_schedule_uses_pe_closing_time_through_the_publication_term_path(self):
        from services.lp.src.lp_notice_publication import _terms
        result, raw = _terms(self.notice(2024), None, '2026-11-16T00:40:00+00:00')
        self.assertEqual(result['deadline'], '2024-11-05T11:00:00+09:00')
        self.assertEqual(result['deadline_precision'], 'datetime')
        self.assertNotIn('deadline_error', raw)

    def test_conflicting_body_and_table_do_not_fall_back_to_a_generic_date(self):
        n = self.notice()
        n['body'] += ' 접수마감일: 2025. 4. 19. 16:00'
        result = extract_terms(n)
        self.assertNotIn('deadline', result)
        self.assertNotIn('deadline_precision', result)
        self.assertNotIn('deadline', result['extraction_evidence'])
        self.assertIn('불일치', result['deadline_error'])

    def test_cancelled_or_amended_notice_drops_even_an_explicit_generic_deadline(self):
        for label in ('취소', '정정'):
            n = self.notice()
            n['title'] = f'({label}) ' + n['title']
            n['body'] += ' 접수마감일: 2025. 4. 18. 16:00'
            result = extract_terms(n)
            self.assertNotIn('deadline', result)
            self.assertNotIn('deadline_precision', result)
            self.assertIn('deadline_error', result)

    def test_multi_league_plan_uses_all_five_managers_and_keeps_deadline(self):
        from services.lp.tests.test_lp_moel_iaci_notice_terms import ALLOCATION_2025
        n = self.notice()
        n['body'] = ALLOCATION_2025
        result = extract_terms(n)
        self.assertEqual((result['manager_count'], result['commitment_amount_krw']), (5, 240_000_000_000))
        self.assertEqual(result['deadline'], '2025-04-18T16:00:00+09:00')
        self.assertEqual([s['manager_count'] for s in result['segments']], [2, 3])

    def test_validated_association_body_uses_the_same_explicit_league_totals(self):
        from services.lp.src.lp_notice_publication import _terms
        from services.lp.tests.test_lp_moel_iaci_notice_terms import ALLOCATION_2025
        n = self.notice()
        n.update(body=ALLOCATION_2025, source_channel='kvca', url='https://www.kvca.or.kr/Program/invest/listbody.html?po_no=1')
        result, _ = _terms(n, n, '2026-11-16T00:40:00+00:00')
        self.assertEqual((result['manager_count'], result['commitment_amount_krw']), (5, 240_000_000_000))

    def test_allocation_conflict_cannot_fall_back_to_the_first_league_count(self):
        from services.lp.src.lp_notice_publication import _terms
        from services.lp.tests.test_lp_moel_iaci_notice_terms import ALLOCATION_2025
        n = self.notice()
        n['body'] = ALLOCATION_2025.replace('총 2,400억원', '총 2,500억원')
        result, raw = _terms(n, None, '2026-11-16T00:40:00+00:00')
        for field in ('manager_count', 'commitment_amount_krw', 'segments', 'commitment_label'):
            self.assertNotIn(field, result)
        self.assertTrue(raw['allocation_reading_failed'])
        self.assertEqual(result['deadline'], '2025-04-18T16:00:00+09:00')


if __name__ == '__main__':
    unittest.main()
