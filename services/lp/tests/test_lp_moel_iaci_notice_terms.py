"""Actual 산재보험기금 schedule layouts retained by run 43674085399.

Fixtures keep the relevant offering header/table/submission footnotes only.
Selection dates and unrelated LOC/event times must never become the deadline.
"""
import copy
import unittest

from services.lp.src.lp_moel_iaci_notice_terms import extract_deadline


SAMPLES = {
    2020: ('2020-11-03', '2020년 11월 3일(화)', '11월 18일(수)',
           '* 제안서는 ’20년 11월 18일(수) 14:00~16:00 까지 주간운용사에 제출'),
    2021: ('2021-10-18', '2021년 10월 18일(월)', '11월 4일(목)',
           '* 제안서는 ’21년 11월 4일(목) 14:00~16:00 까지 주간운용사에 제출'),
    # The ministry posted the offering three days after its original announcement.
    2022: ('2022-06-13', '2022년 6월 10일(금)', '6월 24일(금)',
           '* 제안서는 ’22년 6월 24일(금) 14:00~16:00 까지 주간운용사에 제출'),
    2023: ('2023-09-12', '2023년 9월 12일(화)', '9월 26일(화)',
           '* 제안서는 ’23년 9월 26일(화) 14:00부터 16:00까지 주간운용사에 제출'),
    2024: ('2024-10-18', '2024년 10월 18일(금)',
           '11월 5일(화) 09:00∼11:00\n11월 5일(화) 14:00∼16:00',
           '* 제안서는 제안 상품에 따라 상기 일정에 맞추어 주간운용사에 제출'),
    2025: ('2025-04-01', '2025년 4월 1일(화)', '4월 18일(금)\n14:00∼16:00',
           '* 제안서는 제안 상품에 따라 상기 일정에 맞추어 주간운용사에 제출'),
    2026: ('2026-07-01', '2026년 7월 1일(수)',
           '7월 16일(목) 09:00∼11:00\n7월 16일(목) 14:00∼16:00',
           '* 제안서는 제안 상품에 따라 상기 일정에 맞추어 주간운용사에 제출'),
}


def document(year):
    _, announced, reception, note = SAMPLES[year]
    columns = 'PEF\nVC\n' if year in (2024, 2026) else ''
    return (f'{year}년 산재보험기금 대체투자상품 선정 공고\n'
            f'{year}년도 고용노동부 산재보험기금 대체투자상품 선정 계획을 아래와 같이 공고합니다.\n'
            '1. 선정 개요\n□ 투자 유형 : 블라인드 PEF\n'
            '3. 자격 요건\n타기관 출자확약은 8월 20일 16:00까지 추가 제출\n'
            '5. 향후 추진일정(안)\n절 차\n일 정\n' + columns
            + '대체투자상품\n선정 공고\n' + announced + '\n제안서 접수\n'
            + reception + '\n주간운용사 1차 심사\n12월 1일(월)\n'
            '대체투자상품 최종 선정 발표\n12월 20일(토)\n' + note
            + '\n* 상기 일정은 선정 작업 진행에 따라 일부 조정될 수 있음\n'
            '6. 선정결과 통지 및 문의처\n최종 선정 결과는 홈페이지 공고 및 개별 통지 예정')


def notice(year=2026, *, text=None, title=None):
    url = 'https://www.moel.go.kr/common/downloadFile.do?file_seq=10&bbs_seq=20&bbs_id=27&file_ext=hwp'
    track = 'PEF, VC' if year in (2024, 2026) else 'PEF'
    return {'institution_id': 'moel_iaci', 'source_channel': 'institution_board',
            'url': 'https://www.moel.go.kr/info/astmgmt/employ/imchaeBbsView.do?bbs_seq=20',
            'title': title or f'{year}년 산재보험기금 대체투자상품({track}) 선정 공고',
            'date': SAMPLES[year][0], 'sha256': 'a' * 64,
            'body': '산재보험기금 블라인드 PEF 선정 공고. 자세한 사항은 공고문 참조.',
            'attachments': [{'url': url, 'name': f'{year}년 산재보험기금 대체투자상품 선정 공고문.hwp'}],
            'attachment_hashes': {url: 'b' * 64}, 'attachment_texts': {url: text or document(year)}}


class IaciDeadlineTests(unittest.TestCase):
    def test_observed_date_row_and_submission_footnote_2020_to_2023(self):
        expected = {2020: '2020-11-18', 2021: '2021-11-04', 2022: '2022-06-24', 2023: '2023-09-26'}
        for year, day in expected.items():
            with self.subTest(year=year):
                result = extract_deadline(notice(year))
                self.assertEqual(result['deadline'], day + 'T16:00:00+09:00')
                self.assertEqual(result['deadline_precision'], 'datetime')

    def test_inline_reception_window_ends_at_1600_in_2025(self):
        self.assertEqual(extract_deadline(notice(2025))['deadline'], '2025-04-18T16:00:00+09:00')

    def test_joint_pe_vc_columns_use_pef_end_instead_of_start_or_vc_end(self):
        for year, day in ((2024, '2024-11-05'), (2026, '2026-07-16')):
            with self.subTest(year=year):
                self.assertEqual(extract_deadline(notice(year))['deadline'], day + 'T11:00:00+09:00')

    def test_column_order_comes_from_labels(self):
        text = document(2026).replace('PEF\nVC\n', 'VC\nPEF\n').replace(
            SAMPLES[2026][2], '7월 16일(목) 14:00∼16:00\n7월 16일(목) 09:00∼11:00')
        self.assertEqual(extract_deadline(notice(text=text))['deadline'], '2026-07-16T11:00:00+09:00')

    def test_missing_or_duplicate_joint_column_labels_hold_the_deadline(self):
        for columns in ('', 'PEF\nPEF\n', 'VC\n'):
            with self.subTest(columns=columns):
                r = extract_deadline(notice(text=document(2026).replace('PEF\nVC\n', columns)))
                self.assertNotIn('deadline', r)
                self.assertIn('독립 열', r['deadline_error'])

    def test_joint_table_must_have_both_date_rows(self):
        text = document(2026).replace('7월 16일(목) 14:00∼16:00', '')
        r = extract_deadline(notice(text=text))
        self.assertNotIn('deadline', r)
        self.assertIn('행 수', r['deadline_error'])

    def test_day_conflict_between_schedule_and_footnote_is_held(self):
        text = document(2023).replace('’23년 9월 26일(화)', '’23년 9월 27일(수)')
        r = extract_deadline(notice(2023, text=text))
        self.assertNotIn('deadline', r)
        self.assertIn('불일치', r['deadline_error'])

    def test_time_conflict_does_not_preserve_an_earlier_deadline(self):
        text = document(2025).replace(SAMPLES[2025][3],
            '* 제안서는 ’25년 4월 18일(금) 14:00~17:00까지 주간운용사에 제출')
        r = extract_deadline(notice(2025, text=text))
        self.assertNotIn('deadline', r)
        self.assertIn('날짜·시각 불일치', r['deadline_error'])

    def test_missing_source_year_is_not_filled_from_publication_year(self):
        text = document(2025).replace('2025년도', '당해년도').replace('2025년 산재보험기금', '산재보험기금')
        r = extract_deadline(notice(2025, text=text))
        self.assertNotIn('deadline', r)
        self.assertIn('연도 미확인', r['deadline_error'])

    def test_schedule_announcement_needs_its_own_four_digit_year(self):
        text = document(2025).replace('2025년 4월 1일(화)', '4월 1일(화)')
        r = extract_deadline(notice(2025, text=text))
        self.assertNotIn('deadline', r)
        self.assertIn('공고 연도 미확인', r['deadline_error'])

    def test_offering_year_and_schedule_announcement_cannot_conflict(self):
        text = document(2025).replace('2025년 4월 1일(화)', '2026년 4월 1일(수)')
        r = extract_deadline(notice(2025, text=text))
        self.assertNotIn('deadline', r)
        self.assertIn('연도 불일치', r['deadline_error'])

    def test_unrelated_event_times_do_not_complete_date_only_reception(self):
        text = document(2023).replace(SAMPLES[2023][3], '* 온라인 설명회는 14:00~16:00에 개최')
        r = extract_deadline(notice(2023, text=text))
        self.assertEqual((r['deadline'], r['deadline_precision']), ('2023-09-26', 'date'))

    def test_loc_and_selection_dates_do_not_override_reception(self):
        r = extract_deadline(notice(2025))
        self.assertEqual(r['deadline'], '2025-04-18T16:00:00+09:00')
        quotes = ' '.join(q['quote'] for q in r['extraction_evidence']['deadline'])
        self.assertNotIn('타기관 출자확약', quotes)
        self.assertNotIn('최종 선정 발표', quotes)

    def test_invalid_or_reversed_reception_time_is_held(self):
        for reception in ('7월 16일(목) 11:00∼09:00', '7월 16일(목) 09:00∼25:00',
                          '7월 16일(목) 09:00∼11:70', '7월 16일(수) 09:00∼11:00'):
            with self.subTest(reception=reception):
                text = document(2026).replace('7월 16일(목) 09:00∼11:00', reception)
                self.assertNotIn('deadline', extract_deadline(notice(text=text)))

    def test_deadline_before_the_original_notice_is_not_published(self):
        n = notice(2025)
        n['date'] = '2025-04-20'
        r = extract_deadline(n)
        self.assertNotIn('deadline', r)
        self.assertIn('원공고보다 빠름', r['deadline_error'])

    def test_multiple_offering_attachments_must_agree(self):
        n = notice(2025)
        second = n['attachments'][0]['url'] + '&revision=2'
        n['attachments'].append({'url': second, 'name': '다른 공고문.hwp'})
        n['attachment_hashes'][second] = 'c' * 64
        n['attachment_texts'][second] = document(2025).replace('14:00∼16:00', '14:00∼17:00')
        r = extract_deadline(n)
        self.assertNotIn('deadline', r)
        self.assertIn('모집 첨부 사이', r['deadline_error'])

    def test_unobserved_or_unhashed_attachment_is_held(self):
        for key in ('attachments', 'attachment_hashes'):
            with self.subTest(key=key):
                n = notice(2025)
                n[key] = [] if key == 'attachments' else {}
                r = extract_deadline(n)
                self.assertNotIn('deadline', r)
                self.assertIn('지문 누락', r['deadline_error'])

    def test_rfp_form_and_other_fund_cannot_supply_a_deadline(self):
        n = notice(2025)
        n['attachments'][0]['name'] = '산재보험기금 선정 제안요청서(RFP).hwp'
        self.assertEqual(extract_deadline(n), {})
        self.assertEqual(extract_deadline({**notice(), 'institution_id': 'moel_eif'}), {})
        self.assertEqual(extract_deadline(notice(title='2026년 산재보험기금 대체투자상품(VC) 선정 공고')), {})

    def test_results_and_separate_amendments_do_not_create_recruitment_deadlines(self):
        result = notice(title='2026년 산재보험기금 대체투자상품(PEF, VC) 선정 최종 결과 안내')
        self.assertEqual(extract_deadline(result), {})
        for prefix in ('수정공고', '정정', '변경', '연장', '취소', '철회'):
            with self.subTest(prefix=prefix):
                r = extract_deadline(notice(title=f'({prefix}) 2026년 산재보험기금 대체투자상품(PEF, VC) 선정 공고'))
                self.assertNotIn('deadline', r)
                self.assertIn('deadline_error', r)

    def test_duplicate_schedule_sections_are_held(self):
        text = document(2025)
        r = extract_deadline(notice(2025, text=text + '\n' + text))
        self.assertNotIn('deadline', r)
        self.assertIn('누락 또는 중복', r['deadline_error'])

    def test_explicit_common_footnote_cannot_erase_pe_vc_separation(self):
        text = document(2026).replace(SAMPLES[2026][3],
            '* 제안서는 ’26년 7월 16일(목) 14:00~16:00까지 주간운용사에 제출')
        r = extract_deadline(notice(text=text))
        self.assertNotIn('deadline', r)
        self.assertIn('적용 범위 미확인', r['deadline_error'])

    def test_evidence_keeps_exact_offering_text_and_attachment_hash(self):
        n = notice(2023)
        before = copy.deepcopy(n)
        r = extract_deadline(n)
        raw = next(iter(n['attachment_texts'].values()))
        self.assertTrue(r['extraction_evidence']['deadline'])
        for proof in r['extraction_evidence']['deadline']:
            self.assertIn(proof['quote'], raw)
            self.assertEqual(proof['sha256'], 'b' * 64)
            self.assertEqual(proof['source_url'], n['attachments'][0]['url'])
        self.assertEqual(n, before)


if __name__ == '__main__':
    unittest.main()
