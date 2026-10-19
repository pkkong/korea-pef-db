"""Public notice behavior from retained official documents, including changes."""
import copy
import hashlib
import unittest

from services.lp.src.lp_notice_publication import publish_basic_notices
from services.lp.src.lp_program_detail import render_detail_body

NOW = '2026-10-19T12:00:00+09:00'
PREFIX = '2026년 국내 블라인드 PEF 위탁운용사'


def notice(number=910001, *, title=None, body=None, day='2026-10-01', **fields):
    value = {
        'institution_id': 'kexim',
        'url': 'https://www.koreaexim.go.kr/site/program/board/basicboard/view?boardid=' + str(number),
        'title': title or PREFIX + ' 선정계획 공고',
        'date': day,
        'body': body or '국내 블라인드 PEF 위탁운용사를 공개 모집합니다.',
    }
    value['sha256'] = hashlib.sha256(value['body'].encode()).hexdigest()
    value.update(fields)
    return value


def publish(documents, *, existing=None, now=NOW):
    return publish_basic_notices({'programs': copy.deepcopy(existing or []), 'priority_notices': copy.deepcopy(documents)}, [], now)


class BasicNoticePublicationTests(unittest.TestCase):
    def test_official_pe_recruitment_publishes_without_complete_terms_or_gps(self):
        original = notice()
        programs, holds = publish([original])
        self.assertEqual(len(programs), 1)
        self.assertFalse(holds)
        program = programs[0]
        self.assertEqual(program['title'], original['title'])
        self.assertEqual(program['status'], '모집 공고')
        self.assertEqual(program['events'][0]['url'], original['url'])
        self.assertEqual(program['selected_gps'], [])
        self.assertNotIn('commitment_amount_krw', program)
        self.assertNotIn('primary_investment', program)
        self.assertNotIn('deadline', program)

    def test_basic_detail_has_original_and_schedule_without_empty_gp_section(self):
        program = publish([notice()])[0][0]
        html = render_detail_body(program)
        self.assertIn('진행 일정', html)
        self.assertIn('출자 공고 원문', html)
        self.assertNotIn('id="selection"', html)
        self.assertNotIn('선정 결과 미확인', html)
        self.assertNotIn('주목적</strong>', html)

    def test_explicit_deadline_status_before_and_after_actual_time(self):
        original = notice(body='국내 블라인드 PEF 공개모집. 접수 마감 일시: 2026년 10월 19일 16시 00분')
        for now, expected in [('2026-10-19T15:59:00+09:00', '접수 중'), ('2026-10-19T16:01:00+09:00', '접수 마감')]:
            with self.subTest(now=now):
                programs, holds = publish([original], now=now)
                self.assertFalse(holds)
                self.assertEqual(programs[0]['deadline'], '2026-10-19T16:00:00+09:00')
                self.assertEqual(programs[0]['status'], expected)

    def test_date_only_deadline_does_not_close_at_start_of_day(self):
        original = notice(body='국내 블라인드 PEF 공개모집. 접수 마감일: 2026년 10월 19일')
        for now, expected in [('2026-10-19T23:59:00+09:00', '접수 중'), ('2026-10-20T00:01:00+09:00', '접수 마감')]:
            with self.subTest(now=now):
                programs, holds = publish([original], now=now)
                self.assertFalse(holds)
                self.assertEqual(programs[0]['deadline'], '2026-10-19')
                self.assertEqual(programs[0]['deadline_precision'], 'date')
                self.assertEqual(programs[0]['status'], expected)

    def test_conflicting_deadlines_keep_basic_notice_and_explicit_hold(self):
        original = notice(body='국내 블라인드 PEF 모집. 접수마감일:2026.10.20. 접수마감일:2026.10.22.')
        programs, holds = publish([original])
        self.assertEqual(len(programs), 1)
        self.assertNotIn('deadline', programs[0])
        self.assertEqual(programs[0]['status'], '모집 공고')
        self.assertTrue(any(h['stage'] == 'basic_deadline' for h in holds))

    def test_outside_and_ambiguous_scope_is_not_published(self):
        for title in ('2026년 국내 VC 블라인드 위탁운용사 선정계획 공고',
                      '2026년 해외 PE 블라인드 위탁운용사 선정계획 공고',
                      '2026년 국내 PE VC 블라인드 위탁운용사 선정계획 공고',
                      '2026년 국내 PE 프로젝트 펀드 위탁운용사 선정계획 공고',
                      '2026년 국내 사모펀드 위탁운용사 선정계획 공고'):
            with self.subTest(title=title):
                programs, _ = publish([notice(title=title, body='위탁운용사를 모집합니다.')])
                self.assertEqual(programs, [])

    def test_foreign_host_future_date_or_missing_fingerprint_is_rejected(self):
        for fields in ({'url': 'https://evidence.example/notices/one'}, {'date': '2026-10-20'}, {'sha256': ''}, {'sha256': 'not-a-hash'}):
            with self.subTest(fields=fields):
                programs, holds = publish([notice(**fields)])
                self.assertEqual(programs, [])
                self.assertTrue(any(h['stage'] == 'basic_publication' for h in holds))

    def test_repeated_collection_and_source_outage_preserve_program_and_events(self):
        original = notice()
        first, _ = publish([original])
        second, holds = publish([original], existing=first)
        self.assertEqual(second, first)
        self.assertFalse(holds)
        unavailable, holds = publish([], existing=second)
        self.assertEqual(unavailable, second)
        self.assertFalse(holds)
        self.assertEqual(len(unavailable[0]['events']), 1)

    def test_existing_public_id_and_notice_url_are_retained(self):
        original = notice()
        existing = publish([original])[0]
        existing[0]['id'] = 'existing-public-url'
        programs, _ = publish([original], existing=existing)
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0]['id'], 'existing-public-url')
        self.assertEqual(programs[0]['events'][0]['url'], original['url'])

    def test_sourced_result_advances_stage_without_inventing_gp_names(self):
        original = notice()
        result = notice(910002, title=PREFIX + ' 선정결과', body='운용사 선정 결과를 공고합니다.', day='2026-10-15')
        programs, holds = publish([original, result])
        self.assertFalse(holds)
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0]['status'], '선정 결과 발표')
        self.assertEqual(programs[0]['selected_gps'], [])
        self.assertEqual({e['url'] for e in programs[0]['events']}, {original['url'], result['url']})
        self.assertTrue(any(s['stage'] == 'selection' for s in programs[0]['schedule_stages']))

    def test_different_fund_result_cannot_attach(self):
        original = notice(title='2026년 국내 「수출혁신펀드」 블라인드 PEF 위탁운용사 선정계획 공고')
        unrelated = notice(910002, title='2026년 국내 「산업성장펀드」 블라인드 PEF 위탁운용사 선정결과', day='2026-10-15')
        programs, _ = publish([original, unrelated])
        self.assertEqual(len(programs), 1)
        self.assertEqual([e['url'] for e in programs[0]['events']], [original['url']])

    def test_different_year_result_cannot_attach(self):
        original = notice()
        unrelated = notice(910002, title=PREFIX.replace('2026년', '2025년') + ' 선정결과', day='2026-10-15')
        programs, _ = publish([original, unrelated])
        self.assertEqual(len(programs), 1)
        self.assertEqual([e['url'] for e in programs[0]['events']], [original['url']])

    def test_different_round_result_cannot_attach(self):
        original = notice(title=PREFIX + ' 제1차 선정계획 공고')
        unrelated = notice(910002, title=PREFIX + ' 제2차 선정결과', day='2026-10-15')
        programs, _ = publish([original, unrelated])
        self.assertEqual(len(programs), 1)
        self.assertEqual([e['url'] for e in programs[0]['events']], [original['url']])

    def test_different_track_result_cannot_attach(self):
        original = notice(title=PREFIX + ' 일반매칭 선정계획 공고')
        unrelated = notice(910002, title=PREFIX + ' 루키 선정결과', day='2026-10-15')
        programs, _ = publish([original, unrelated])
        self.assertEqual(len(programs), 1)
        self.assertEqual([e['url'] for e in programs[0]['events']], [original['url']])

    def test_reopening_has_its_own_program_and_does_not_overwrite_first_call(self):
        original = notice()
        reopen = notice(910002, title=PREFIX + ' 선정계획 재공고', day='2026-10-15')
        programs, _ = publish([original, reopen])
        self.assertEqual(len(programs), 2)
        self.assertEqual(len({p['id'] for p in programs}), 2)
        self.assertEqual({tuple(e['url'] for e in p['events']) for p in programs}, {(original['url'],), (reopen['url'],)})

    def test_cancellation_removes_deadline_and_all_old_planned_stages(self):
        original = notice(body='국내 블라인드 PEF 공개모집. 접수마감일:2026.10.30.')
        existing = publish([original])[0]
        existing[0]['schedule_stages'].append({'stage': 'selection', 'label': '선정 예정', 'original_label': '선정 예정', 'date': '2026-11-10', 'precision': 'date', 'status': 'planned', 'source_url': original['url']})
        cancel = notice(910002, title=PREFIX + ' 선정계획 취소공고', body='출자 모집을 취소합니다.', day='2026-10-15')
        programs, _ = publish([original, cancel], existing=existing)
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0]['status'], '모집 취소')
        self.assertNotIn('deadline', programs[0])
        self.assertFalse(any(s['status'] in ('planned', 'announced_deadline') for s in programs[0]['schedule_stages']))
        self.assertIn(cancel['url'], {e['url'] for e in programs[0]['events']})

    def test_amendment_replaces_deadline_and_repeated_run_does_not_duplicate(self):
        original = notice(body='국내 블라인드 PEF 공개모집. 접수마감일:2026.10.20.')
        amendment = notice(910002, title=PREFIX + ' 선정계획 변경공고', body='접수마감일:2026.10.30.', day='2026-10-15')
        existing = publish([original])[0]
        programs, _ = publish([original, amendment], existing=existing)
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0]['id'], existing[0]['id'])
        self.assertEqual(programs[0]['deadline'], '2026-10-30')
        self.assertEqual(programs[0]['deadline_source_url'], amendment['url'])
        repeated, _ = publish([original, amendment], existing=programs)
        self.assertEqual(len(repeated[0]['events']), 2)
        deadlines = [s for s in repeated[0]['schedule_stages'] if s['status'] == 'announced_deadline']
        self.assertEqual([s['date'] for s in deadlines], ['2026-10-30'])
        self.assertEqual(deadlines[0]['source_url'], amendment['url'])

    def test_old_recruitment_does_not_regress_existing_reviewed_selection(self):
        original = notice()
        reviewed = publish([original])[0][0]
        reviewed.pop('basic_publication')
        reviewed['status'] = '선정 완료'
        reviewed['selected_gps'] = [{'name': '검증된운용사', 'source_url': 'https://www.koreaexim.go.kr/site/program/board/basicboard/view?boardid=910099', 'asset_scope': 'PE'}]
        reviewed['events'].append({'date': '2026-10-15', 'type': '최종 선정', 'title': '공식 최종 선정', 'url': reviewed['selected_gps'][0]['source_url']})
        programs, holds = publish([original], existing=[reviewed])
        self.assertFalse(holds)
        self.assertEqual(programs, [reviewed])

    def test_foreign_attachment_cannot_supply_a_deadline(self):
        foreign = 'https://unrelated.example/offering.pdf'
        original = notice(attachment_texts={foreign: '접수마감일:2026.10.30.'}, attachment_hashes={foreign: 'b' * 64}, attachments=[{'url': foreign, 'name': '공고문.pdf'}])
        programs, _ = publish([original])
        self.assertEqual(len(programs), 1)
        self.assertNotIn('deadline', programs[0])

    def test_submission_form_cannot_supply_offering_deadline(self):
        form = 'https://www.koreaexim.go.kr/files/submission-form.pdf'
        original = notice(attachment_texts={form: '접수마감일:2026.10.30.'}, attachment_hashes={form: 'c' * 64}, attachments=[{'url': form, 'name': '제안서 제출 양식.pdf'}])
        programs, _ = publish([original])
        self.assertEqual(len(programs), 1)
        self.assertNotIn('deadline', programs[0])

    def test_official_notice_number_and_evaluation_round_are_not_fund_rounds(self):
        original = notice(title='2026년 국내 블라인드 PEF 위탁운용사 선정 공고 [우정사업본부 공고 제2026-124호]')
        result = notice(910002, title='2026년 국내 블라인드 PEF 위탁운용사 선정 1차 정량평가 결과 안내', day='2026-10-15')
        programs, _ = publish([original, result])
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0]['status'], '1차 심사 결과')

    def test_correction_table_does_not_treat_old_deadline_as_new(self):
        original = notice(body='국내 블라인드 PEF 공개모집. 접수마감일:2026.10.20.')
        amendment = notice(910002, title=PREFIX + ' 선정계획 변경공고', day='2026-10-15',
                           body='당초 접수마감일:2026.10.20. 변경 후:2026.10.30.')
        programs, holds = publish([original, amendment])
        self.assertEqual(programs[0]['status'], '변경 공고')
        self.assertNotIn('deadline', programs[0])
        self.assertTrue(any(h['stage'] == 'basic_deadline' for h in holds))

    def test_month_period_screening_is_after_same_month_submission_deadline(self):
        original = notice(body='국내 블라인드 PEF 공개모집. 접수마감일:2026.10.20.')
        p = publish([original])[0][0]
        p.pop('basic_publication');p['publication_version'] = 1
        p['schedule_stages'].append({'stage':'screening','label':'1차 심사','original_label':'정량평가',
            'date':'2026-10','date_label':'10월 말','precision':'month_period','status':'planned','source_url':original['url']})
        programs, _ = publish([original], existing=[p])
        labels = [s['label'] for s in programs[0]['schedule_stages']]
        self.assertLess(labels.index('접수 마감'), labels.index('1차 심사'))
        self.assertEqual(next(s for s in programs[0]['schedule_stages'] if s['label']=='1차 심사')['date'], '2026-10')

    def test_confirmed_result_replaces_old_planned_stage(self):
        original = notice()
        p = publish([original])[0][0]
        p.pop('basic_publication');p['publication_version'] = 1
        p['schedule_stages'].append({'stage':'screening','label':'1차 심사','original_label':'정량평가',
            'date':'2026-10','precision':'month','status':'planned','source_url':original['url']})
        result = notice(910002, title=PREFIX+' 선정 정량평가 결과 안내', day='2026-10-15')
        programs, _ = publish([original, result], existing=[p])
        stages = [s for s in programs[0]['schedule_stages'] if s['stage']=='screening']
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]['status'], 'confirmed')

    def test_generic_management_purpose_is_not_relabelled_investment_mandate(self):
        from services.lp.tests.test_lp_shared_notice_terms import notice as shared_notice
        n = shared_notice('국내 PE 블라인드 모집\n출자규모: 총 450억원\n운용목적: 기금 수익 제고 및 공동투자 기회 확보')
        programs, _ = publish_basic_notices({'programs': [], 'shared_notices': [n]}, [], NOW)
        self.assertEqual(len(programs), 1)
        self.assertNotIn('primary_investment', programs[0])
        n['body'] = n['body'].replace('운용목적: 기금 수익 제고 및 공동투자 기회 확보', '주목적: 국내 중소기업의 사업확장 및 인수금융 투자')
        programs, _ = publish_basic_notices({'programs': [], 'shared_notices': [n]}, [], NOW)
        self.assertIn('국내 중소기업', programs[0]['primary_investment']['text'])


if __name__ == '__main__':
    unittest.main()
