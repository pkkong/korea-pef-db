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
    def test_preferred_names_attach_to_their_own_stage_without_final_promotion(self):
        from services.lp.tests.test_collect_koreapost_program import KoreaPostReviewTests
        import services.lp.src.collect_koreapost_program as post
        fixture = KoreaPostReviewTests();fixture.setUp()
        original = {**fixture.notice, 'institution_id':'koreapost'}
        preferred = {**fixture.preferred(), 'institution_id':'koreapost'}
        old = copy.deepcopy(__import__('json').loads(post.REGISTRY.read_text())['program'])
        old['id'] = 'preserved-old-program'
        old['selected_gps'] = []
        programs, holds = publish([original,preferred],existing=[old],now='2026-11-07T00:00:00+09:00')
        p = next(p for p in programs if p['id']==old['id'])
        self.assertEqual(p['preferred_gps'],['가람PE','나래파트너스','다온PE'])
        self.assertEqual(p['status'],'우선협상대상자');self.assertEqual(p['selected_gps'],[])
        self.assertEqual(p['manager_list_sources']['preferred_gps'],preferred['url'])
        self.assertEqual(p['commitment_amount_krw'],old['commitment_amount_krw'])
        self.assertFalse([h for h in holds if h['stage']=='preferred_roster'])
        bad = copy.deepcopy(preferred);bad['body'] += '\n최종 선정 완료';bad['sha256']=post._fingerprint(bad)
        # Changed source must never overwrite an already attached roster.
        result, errors = publish([original,bad],existing=[p],now='2026-11-07T00:00:00+09:00')
        self.assertEqual(next(x for x in result if x['id']==old['id'])['preferred_gps'],p['preferred_gps'])
        self.assertTrue([h for h in errors if h['stage']=='preferred_roster'])

    def test_retained_preferred_event_can_gain_verified_names_without_new_url(self):
        from services.lp.tests.test_koreapost_coinvestment_preferred import evidence
        from services.lp.src.lp_notice_publication import OFFERING_FIELDS
        original, preferred = evidence()
        documents = [{**n, 'institution_id': 'koreapost'} for n in (original, preferred)]
        old = {'id': 'existing-coinvestment', 'institution_id': 'koreapost',
               'institution_name': '우정사업본부', 'title': original['title'],
               'asset_scope': 'PE', 'status': '우선협상대상자', 'selected_gps': [],
               'commitment_amount_krw': 200_000_000_000, 'manager_count': 1,
               'contribution_note': '기존 검증된 출자 조건',
               'events': [{'type': kind, 'url': n['url'], 'title': n['title'], 'date': n['date']}
                          for kind, n in [('모집 공고', original), ('우선협상대상자', preferred)]]}
        programs, holds = publish(documents, existing=[old], now='2026-05-01T00:00:00+09:00')
        self.assertEqual(len(programs), 1)
        current = programs[0]
        self.assertEqual(current['preferred_gps'], ['가나다프라이빗에쿼티'])
        self.assertEqual(current['manager_list_sources']['preferred_gps'], preferred['url'])
        self.assertEqual(current['status'], '우선협상대상자')
        self.assertEqual(current['selected_gps'], [])
        self.assertEqual(current['events'], old['events'])
        for field in ('id', 'title', 'institution_id', 'asset_scope', *OFFERING_FIELDS):
            self.assertEqual(current.get(field), old.get(field), field)
        self.assertFalse([h for h in holds if h['stage'] == 'preferred_roster'])
        # A retained event alone cannot authorize names without the raw proof.
        broken = copy.deepcopy(documents); del broken[1]['detail_proof']
        result, errors = publish(broken, existing=[old], now='2026-05-01T00:00:00+09:00')
        self.assertEqual(result[0], old)
        self.assertTrue([h for h in errors if h['stage'] == 'preferred_roster'])
        changed = {k for k in current if current.get(k) != old.get(k)}
        self.assertEqual(changed, {'preferred_gps', 'manager_list_sources', 'gp_tracks'})
        final = {**old, 'status': '선정 완료', 'selected_gps': [{'name': '검증된최종운용사'}]}
        self.assertEqual(publish(documents, existing=[final], now='2026-05-01T00:00:00+09:00')[0], [final])
        # A curator's explicit lock still prevents automatic refresh.
        locked = {**old, 'manual_review_id': 'explicit-review'}
        self.assertEqual(publish(documents, existing=[locked], now='2026-05-01T00:00:00+09:00')[0], [locked])

    def test_single_track_per_fund_limit_is_visible_without_invented_total(self):
        program = publish([notice()])[0][0]
        program.update(per_fund_amount_krw=50_000_000_000, per_fund_qualifier='이내')
        html = render_detail_body(program)
        self.assertIn('펀드당 출자액</small><strong>500억원 이내', html)
        self.assertNotIn('출자 예정액</small>', html)

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

    def test_closed_basic_detail_keeps_result_gap_visible_without_fabricated_winner(self):
        program = publish([notice()])[0][0]
        program['status'] = '접수 마감'
        html = render_detail_body(program)
        self.assertIn('id="selection"', html)
        self.assertIn('<h2>선정 결과</h2>', html)
        self.assertIn('선정 결과는 아직 확인되지 않았습니다.', html)
        self.assertNotIn('selected-gp-', html)
        self.assertEqual(program['selected_gps'], [])

    def test_result_without_parsed_names_links_its_actual_result_not_recruitment(self):
        program = publish([notice()])[0][0]
        program['status'] = '선정 결과 발표'
        result = {'type': '선정 결과', 'date': '2026-10-20', 'title': '선정 결과',
                  'url': 'https://official.example/results'}
        program['events'].append(result)
        html = render_detail_body(program)
        self.assertIn('id="selection"', html)
        self.assertIn('href="https://official.example/results"', html)
        self.assertIn('선정 결과 원문', html)
        self.assertNotIn('selected-gp-', html)

    def test_cancelled_basic_recruitment_does_not_imply_selection(self):
        program = publish([notice()])[0][0]
        program['status'] = '취소'
        html = render_detail_body(program)
        self.assertNotIn('id="selection"', html)
        self.assertNotIn('선정 결과 미확인', html)

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


class KdbResultRosterTests(unittest.TestCase):
    def test_secondary_fund_replay_corrects_scope_and_keeps_existing_selection(self):
        from services.lp.src.lp_notice_publication import _terms

        title = '『2026 회수시장 지원 세컨더리 펀드』 위탁운용사'
        vehicles = ('출자대상 투자기구 ○「벤처투자촉진에 관한 법률」에 의한 벤처투자조합 '
                    '○「여신전문금융업법」에 의한 신기술사업투자조합 '
                    '○「자본시장과 금융투자업에 관한 법률」에 의한 기관전용사모집합투자기구 '
                    '※선정된 위탁운용사는 관련 법규에 따릅니다.')
        header = '분야별 출자계획 ○ 출자계획 분야 산은출자금액 산은출자비율 '

        def kdb(number, day, suffix, text):
            url = f'https://www.kdb.co.kr/secondary-plan/{number}'
            pdf = f'{url}.pdf'
            return notice(title=title + suffix, url=url, day=day, institution_id='kdb', source_channel='institution_board',
                          attachment_texts={pdf: text}, attachment_hashes={pdf: hashlib.sha256(text.encode()).hexdigest()})

        first_title = ' 선정계획 공고'
        first_pdf = (title + first_title + '\n위탁운용금액 : 총 1,200억원*위탁운용금액은 조정될 수 있으며\n' + header
                     + '펀드별 목표결성금액 선정운용사 수 조성목표 중형 900억원 30.0% 1,500억원 2개 3,000억원 '
                     '소형 300억원 30.0% 1,000억원 1개 1,000억원 합계 1,200억원 30.0% - 3개 4,000억원 '
                     '*산은출자금액은 펀드별 목표결성금액의 30%를 초과할 수 없음\n'
                     '접수일시○2026년 5월 29일(금)10:00~15:00 접수방법○제출서류\n' + vehicles)
        small_title = '(소형) 선정계획 재공고'
        small_pdf = (title + small_title + '\n위탁운용금액: 총 300억원*위탁운용금액은 조정될 수 있으며\n' + header
                     + '목표결성금액 선정운용사 수 소형 300억원 30.0% 1,000억원 1개 *산은출자금액은 '
                     '목표결성금액의30%를 초과할 수 없음 ○ʹ26.4.30자 공고한 『2026회수시장지원세컨더리펀드』 '
                     '출자사업에 지원하였던 위탁운용사의 재지원 가능\n'
                     '접수일시 및 접수처○2026년 7월 27일(월)09:30~14:00○접수처:한국산업은행 본점\n' + vehicles)
        recruit = kdb(1, '2026-04-30', first_title, first_pdf)
        small = kdb(2, '2026-07-08', small_title, small_pdf)
        final = kdb(3, '2026-06-30', ' 선정 결과', '<위탁운용사 선정 결과>지원분야 선정 운용사명(가나다순)\n'
                    '중형 아이엠엠인베스트먼트엘비인베스트먼트')
        documents = [recruit, small, final]
        baseline, holds = publish(documents)
        self.assertFalse(holds)
        self.assertEqual(len(baseline), 2)
        for p in baseline:
            p['asset_scope'] = 'PE'
            for g in p['selected_gps']:
                g['asset_scope'] = 'PE'
        updated, holds = publish(documents[::-1], existing=baseline)
        self.assertFalse(holds)
        self.assertEqual({p['id'] for p in baseline}, {p['id'] for p in updated})
        for p, old in zip(sorted(updated, key=lambda x: x['id']), sorted(baseline, key=lambda x: x['id'])):
            self.assertEqual(p['asset_scope'], 'PE·VC 공동 모집')
            self.assertEqual(p['events'], old['events'])
            self.assertEqual(p['selected_gps'], old['selected_gps'])
            self.assertEqual(p['commitment_amount_krw'], old['commitment_amount_krw'])
        first = next(p for p in updated if p['selected_gps'])
        self.assertEqual(first['commitment_label'], '1,200억원 (PE·VC 합계)')
        self.assertEqual(first['deadline'], '2026-05-29T15:00:00+09:00')
        self.assertEqual(first['gp_tracks'], {'아이엠엠인베스트먼트': '중형', '엘비인베스트먼트': '중형'})
        reopened = next(p for p in updated if not p['selected_gps'])
        self.assertEqual(reopened['commitment_label'], '300억원 (PE·VC 합계)')
        self.assertEqual(reopened['deadline'], '2026-07-27T14:00:00+09:00')
        self.assertEqual(reopened['commitment_detail'], '4월 30일 공고의 소형 분야 재모집')
        self.assertIn('소형 분야 재모집', render_detail_body(reopened))
        for broken in (first_pdf.replace('900억원', '800억원'), first_pdf.replace(vehicles, ''),
                       first_pdf.replace(title, '다른 펀드 모집')):
            terms, raw = _terms(kdb(1, '2026-04-30', first_title, broken), None, NOW)
            self.assertTrue(raw['allocation_reading_failed'])
            self.assertNotIn('commitment_amount_krw', terms)

    @staticmethod
    def recovery_market_documents():
        fund = '회수시장 활성화 지원 펀드'
        title = f'『{fund}』 위탁운용사 '
        plan = (
            '위탁운용금액: 총 1,500억원 이내\n'
            '분야별 출자계획 ○ 출자계획 분야 산은출자금액 산은출자비율 펀드별 목표결성금액(최소결성규모) '
            '선정운용사 수 조성목표 회수시장 활성화 M&A 900억원 30.0% 500억원 이상 2,000억원 이하 자율제안 '
            '6개사 이내 3,000억원 세컨더리 600억원 30.0% 1,000억원 2개사 2,000억원 '
            '합계 1,500억원 30.0% - - 5,000억원 *산은출자금액은 펀드별 목표결성금액의 30%를 초과할 수 없음\n'
            '출자대상 투자기구 ○ 기관전용 사모집합투자기구 ○ 벤처투자조합 ※ 선정된 위탁운용사는 확인\n'
            '접수일시 ○ 2025년 1월 22일(수) 10:00~15:00 접수방법 ○ 제출서류\n'
            '선정일정 일자 내용 비고 2025.1.22(수) 제안서 접수 10:00~15:00 2025.2월 중 최종 선정'
        )
        papers = [
            ('2024-12-20', '선정계획 공고', plan),
            ('2025-01-06', '선정 FAQ 게시', f'「{fund}」 위탁운용사 선정계획 FAQ\n2025.1.6.'),
            ('2025-01-24', '제안서 접수결과', f'「{fund}」 위탁운용사 접수 현황(단위 : 억원) 지원분야(지원규모) 조성목표'),
            ('2025-02-12', '선정 서류심사 결과', f'<{fund} 출자사업 서류심사 통과 운용사> 지원분야 지원 운용사명(가나다순)'),
            ('2025-02-25', '선정 결과', f'<{fund} 위탁운용사 선정 결과> 지원분야 선정 운용사명(가나다순)\n'
             'M&A 나우아이비캐피탈헬리오스프라이빗에쿼티\n세컨더리 우리벤처파트너스티에스인베스트먼트'),
        ]
        notices = []
        for number, (day, phase, text) in enumerate(papers):
            url = f'https://www.kdb.co.kr/recovery-market/{number}'
            attachment = f'{url}.pdf'
            body = f'{title}{phase}를 첨부파일과 같이 공고합니다.'
            if phase == '선정 결과':
                body = '2025년 ' + body
            notices.append(notice(title=title + phase, body=body, day=day, url=url, institution_id='kdb',
                                  source_channel='institution_board', attachment_texts={attachment: text},
                                  attachment_hashes={attachment: hashlib.sha256(text.encode()).hexdigest()}))
        return notices

    def test_recovery_market_keeps_recruitment_year_url_and_official_final_roster(self):
        from services.lp.src.lp_program_detail import standardized_schedule

        documents = self.recovery_market_documents()
        baseline, holds = publish(documents[:1])
        self.assertFalse(holds)
        baseline[0]['id'] = 'existing-recovery-market'
        programs, holds = publish(documents, existing=baseline)
        self.assertFalse(holds)
        self.assertEqual(programs, publish(documents[::-1], existing=baseline)[0])
        program, = programs
        self.assertEqual(program['id'], 'existing-recovery-market')
        self.assertTrue(program['source_program_key'].startswith('kdb:2024:'))
        self.assertEqual([e['url'] for e in program['events']], [n['url'] for n in documents])
        self.assertEqual(program['deadline'], '2025-01-22T15:00:00+09:00')
        self.assertEqual(program['commitment_amount_krw'], 150_000_000_000)
        self.assertEqual(program['asset_scope'], 'PE·VC 공동 모집')
        self.assertEqual(program['status'], '선정 완료')
        self.assertIn('질의응답', standardized_schedule(program['schedule_stages']))
        self.assertEqual(program['gp_tracks'], {
            '나우아이비캐피탈': 'M&A', '헬리오스프라이빗에쿼티': 'M&A',
            '우리벤처파트너스': '세컨더리', '티에스인베스트먼트': '세컨더리',
        })
        self.assertTrue(all(gp['source_url'] == documents[-1]['url'] for gp in program['selected_gps']))

    def test_recovery_market_holds_ambiguous_or_conflicting_stages_and_amounts(self):
        from services.lp.src.lp_notice_publication import _terms
        original, faq, receipt, screening, final = self.recovery_market_documents()
        pdf, text = next(iter(original['attachment_texts'].items()))
        wrong_plan = {**original, 'attachment_texts': {pdf: text.replace('2025.1.22', '2025.1.23')}}
        wrong_year = {**final, 'body': final['body'].replace('2025년', '2026년')}
        other_offer = {**original, 'url': original['url'] + '-another', 'date': '2024-12-23'}
        for documents, excluded in [
            ([wrong_plan, faq, receipt, screening, final], 4),
            ([original, faq, receipt, screening, wrong_year], 1),
            ([original, other_offer, faq, receipt, screening, final], 4),
            ([original, receipt, {**screening, 'date': '2025-02-26'}, final], 3),
        ]:
            programs, holds = publish(documents)
            self.assertEqual(sum(h['stage'] == 'basic_stage_link' for h in holds), excluded)
            self.assertTrue(all(not p['selected_gps'] for p in programs))
        corrupt_table = {**original, 'attachment_texts': {pdf: text.replace('600억원', '650억원')}}
        terms, details = _terms(corrupt_table, None, NOW)
        self.assertTrue(details['allocation_reading_failed'])
        self.assertNotIn('commitment_amount_krw', terms)

    """KDB result tables lose cell borders; names are split only when unambiguous."""
    TABLE = ('< 2026 남부권 지역성장지원펀드 위탁운용사 선정 결과 >지원분야지원 운용사명(가나다순)\n'
             'PE더함파트너스릴슨프라이빗에쿼티\nVC리인베스트먼트원익투자파트너스이앤인베스트먼트')

    def test_explicit_reannouncement_separates_business_round_and_reads_joint_plan(self):
        from services.lp.src.lp_kdb_policy_reopen import result_roster
        from services.lp.src.lp_notice_publication import _identity, _scope, _terms
        fund = '혁신성장펀드(혁신산업펀드)'
        title = '『' + fund + '』 2024년 2차 '
        table = ('정책출자자 위탁운용 총액 : 총 370억원 내외\n(단위: 억원)\n정책출자자\n합계\n'
                 '정부재정(재정모펀드)\n한국산업은행\n성장사다리펀드2\n115\n155\n100\n370\n* 출자자별 승인\n'
                 '재정\n산은\n사다리2\n합계(비율)\n115\n155\n100\n370(37%)\n1\n1,000\n산은\n')
        legal = '출자대상투자기구○기관전용사모집합투자기구○벤처투자조합※선정된위탁운용사 허용'
        body = table + '접수일시○2025년5월29일(목)13:00~16:00접수방법○접수\n' + legal
        notice = {'title': title + '위탁운용사 선정계획 (재)공고', 'institution_id': 'kdb', 'date': '2025-05-14',
                  'body': body, 'sha256': 'a' * 64, 'url': 'https://www.kdb.co.kr/offer', 'source_channel': 'institution_board'}
        key = _identity(notice)
        final = {**notice, 'title': title + '(재공고) 자펀드 위탁운용사 선정 결과'}
        self.assertEqual(key, _identity(final))
        self.assertNotEqual(key, _identity({**final, 'title': final['title'].replace('(재공고)', '')}))
        self.assertNotEqual(key, _identity({**final, 'title': final['title'].replace('2024년', '2025년')}))
        self.assertEqual(_scope(notice), 'mixed_pe_blind')
        offering, raw = _terms(notice, None, NOW)
        self.assertEqual(raw['amount_scope'], 'combined')
        self.assertEqual(offering['contribution_allocations']['한국산업은행'], 155 * 10**8)
        self.assertEqual(offering['commitment_amount_krw'], 370 * 10**8)
        self.assertEqual(offering['deadline'], '2025-05-29T16:00:00+09:00')
        broken, raw = _terms({**notice, 'body': body.replace('\n155\n', '\n150\n', 1)}, None, NOW)
        self.assertTrue(raw['allocation_reading_failed'])
        self.assertNotIn('commitment_amount_krw', broken)
        program = {**offering, 'source_program_key': key, 'asset_scope': 'PE·VC 공동 모집'}
        roster = f'< {fund} 2024년 2차(재공고) 위탁운용사 선정 결과 >펀드규모선정 운용사명1,000억원인터베스트'
        self.assertEqual(result_roster(final, roster, program), [('공동 모집', ['인터베스트'])])
        for altered in (roster.replace('2024년', '2025년'), roster.replace('1,000억원', '2,000억원'),
                        roster + '\n2,000억원다른파트너스'):
            self.assertEqual(result_roster(final, altered, program), [])

    def test_entrusted_subfund_keeps_contributor_and_manager_roles_separate(self):
        from services.lp.src.lp_kdb_nuclear_terms import result_roster
        from services.lp.src.lp_notice_publication import _identity, _terms, split_glued_names
        title = '『원전산업성장펀드』 자펀드 위탁운용사 '
        table = ('위탁운용 총액: 총 700억원\n(단위: 억원)\n정책출자자\n지정출자자\n합 계\n'
                 '재정\n(원전산업성장펀드1호)\n한국산업은행\n한국수력원자력\n(원전산업성장펀드2호)\n'
                 '350\n50\n300\n700\n* 출자자별 승인\n'
                 '조성목표\n선정\n운용사수\n출자비율\n주관기관\n자율제안*\n1,000\n1~2\n70% 이내\n신한자산운용\n')
        body = (table + '접수일시○2025년6월5일(목)13:00~16:00(신한자산운용앞제출)접수방법○접수\n'
                '출자대상투자기구○기관전용사모집합투자기구○벤처투자조합※선정된위탁운용사 허용')
        notice = {'title': title + '선정계획 공고', 'institution_id': 'kdb', 'date': '2025-05-22',
                  'body': body, 'sha256': 'a'*64, 'url': 'https://www.kdb.co.kr/offer', 'source_channel': 'institution_board'}
        terms, raw = _terms(notice, None, NOW)
        self.assertEqual(raw['amount_scope'], 'combined')
        self.assertEqual(terms['commitment_amount_krw'], 700 * 10**8)
        self.assertEqual(terms['contribution_allocations']['한국산업은행'], 50 * 10**8)
        self.assertIn('주관기관은 신한자산운용', terms['contribution_note'])
        self.assertEqual(terms['deadline'], '2025-06-05T16:00:00+09:00')
        final = {**notice, 'title': title + '선정 결과'}
        parent = {**final, 'title': final['title'].replace('자펀드', '모펀드')}
        self.assertEqual(_identity(notice), _identity(final))
        self.assertNotEqual(_identity(notice), _identity(parent))
        page = ('<원전산업성장펀드 자펀드 위탁운용사 선정 결과> (단위 : 억원, 개)운용사 수펀드규모'
                '지원 운용사명 (가나다순)\n2500(총 1,000)브이엘인베스트먼트인라이트벤처스')
        program = {**terms, 'asset_scope': 'PE·VC 공동 모집'}
        self.assertEqual(result_roster(final, page, program, split_glued_names),
                         [('공동 모집', ['브이엘인베스트먼트', '인라이트벤처스'])])
        self.assertEqual(result_roster(parent, page, program, split_glued_names), [])
        self.assertEqual(result_roster(final, page.replace('1,000', '900'), program, split_glued_names), [])
        broken, raw = _terms({**notice, 'body': body.replace('\n50\n', '\n51\n')}, None, NOW)
        self.assertTrue(raw['allocation_reading_failed'])
        self.assertNotIn('commitment_amount_krw', broken)

    def test_media_technology_terms_reconcile_joined_cells_and_bind_only_matching_result(self):
        from services.lp.src.lp_kdb_media_terms import result_roster
        from services.lp.src.lp_notice_publication import _identity, _scope, _terms, split_glued_names
        title = '「K-콘텐츠·미디어 전략펀드」 위탁운용사 '
        allocation = ('모펀드및지정출자자(한국산업은행)위탁운용금액:총400억원이내(단위:억원)'
                      '모펀드지정출자자(한국산업은행)합 계정부 재정(재정모펀드)비재정모펀드16040200400')
        plan = ('분야별 출자계획◦출자계획(단위:개,억원)지원 분야출자금액출자비율펀드별 목표결성금액선정운용사수'
                '조성목표 주관 기관재정비재정산은기술심화(블라인드펀드)1604020040%이내50021,000산은◦')
        body = (allocation + plan + '접수일시○2025년4월30일(수)13:30~16:30접수방법○'
                '출자대상투자기구◦기관전용사모집합투자기구◦벤처투자조합※선정된위탁운용사 허용')
        notice = {'title': title + '선정계획 공고', 'institution_id': 'kdb', 'date': '2025-04-16',
                  'body': body, 'sha256': 'a'*64, 'url': 'https://www.kdb.co.kr/offer', 'source_channel': 'institution_board'}
        self.assertEqual(_scope(notice), 'mixed_pe_blind')
        terms, raw = _terms(notice, None, NOW)
        self.assertEqual(raw['amount_scope'], 'combined')
        self.assertEqual(terms['commitment_label'], '공동 위탁운용 예정 400억원 이내')
        self.assertEqual(terms['contribution_allocations'],
                         {'정부재정': 160 * 10**8, '비재정모펀드': 40 * 10**8, '한국산업은행': 200 * 10**8})
        self.assertEqual(terms['deadline'], '2025-04-30T16:30:00+09:00')
        self.assertEqual(terms['fund_target_label'], '1,000억원')
        broken, raw = _terms({**notice, 'body': body.replace('16040200400', '16040200401')}, None, NOW)
        self.assertTrue(raw['allocation_reading_failed'])
        self.assertNotIn('commitment_amount_krw', broken)
        invalid_date, raw = _terms({**notice, 'body': body.replace('4월30일', '4월31일')}, None, NOW)
        self.assertIn('deadline_error', raw)
        self.assertNotIn('deadline', invalid_date)
        self.assertIn('commitment_amount_krw', invalid_date)

        final_title = '『K-콘텐츠 미디어 전략펀드』 위탁운용사 선정 결과'
        final = {**notice, 'title': final_title}
        self.assertEqual(_identity(notice), _identity(final))
        program = {**terms, 'asset_scope': 'PE·VC 공동 모집'}
        result = (final_title + '지원분야(운용사 수) 펀드규모(억원) 선정 운용사명 (가나다순) '
                  '기술심화 (2) 500(총 1,000) 에스비파트너스 유니온투자파트너스')
        self.assertEqual(result_roster(final, result, program, split_glued_names),
                         [('기술심화', ['에스비파트너스', '유니온투자파트너스'])])
        for wrong in (result.replace('기술심화', 'IP'), result.replace('500', '600'), result.replace('선정 결과', '서류심사 결과')):
            self.assertEqual(result_roster(final, wrong, program, split_glued_names), [])

        prior_attachment = 'https://www.kdb.co.kr/prior-rfp'
        current_attachment = 'https://www.kdb.co.kr/current-rfp'
        result_attachment = 'https://www.kdb.co.kr/result-rfp'
        first_plan = ('분야별 출자계획\n기술\n심화\n160\n40\n200\n40%이내\n1,000\n1\n1,000\n산은\n프로젝트펀드주3)\n'
                      '주1) ‘성장’은 한국성장금융투자운용㈜, ‘산은’은 한국산업은행을 의미\n'
                      '블라인드 펀드\nIP확보\n성장금융\n2025년 3월 5일(수) 13:00~16:00까지\n2025년 4월 내\n'
                      '기술심화\n산업은행\n프로젝트 펀드\n'
                      '출자대상투자기구○기관전용사모집합투자기구○벤처투자조합※선정된위탁운용사 허용')
        prior = {**notice, 'url': 'https://www.kdb.co.kr/prior', 'date': '2025-02-12',
                 'attachment_hashes': {prior_attachment: 'b'*64}, 'attachment_texts': {prior_attachment: first_plan}}
        current = {**notice, 'body': '전략펀드 기술심화 분야의 새로운 모집 조건을 공고합니다.',
                   'attachment_hashes': {current_attachment: 'c'*64}, 'attachment_texts': {current_attachment: body}}
        result_notice = {**final, 'url': 'https://www.kdb.co.kr/final', 'date': '2025-05-27',
                         'attachment_hashes': {result_attachment: 'd'*64}, 'attachment_texts': {result_attachment: result}}

        def publish_replayed(notices):
            from unittest.mock import patch
            with patch('services.lp.src.lp_notice_publication.validate_institution_notice', side_effect=lambda n, _: n):
                skips = []
                programs, holds = publish_basic_notices({'programs': [], 'institution_notices': notices}, [], NOW, skips)
                return programs, holds + skips

        for notices in ([prior, current, result_notice], [result_notice, current, prior]):
            public, holds = publish_replayed(notices)
            self.assertTrue(public, holds)
            only, = public
            self.assertFalse(holds)
            self.assertEqual([e['type'] for e in only['events']], ['최초 모집 공고', '모집 공고', '선정 결과'])
            self.assertEqual(only['deadline'], '2025-04-30T16:30:00+09:00')
            self.assertEqual(only['commitment_amount_krw'], 400 * 10**8)
            self.assertEqual(len(only['selected_gps']), 2)
            self.assertEqual(only['extraction_evidence']['prior_media_recruitment'][0]['source_url'], prior_attachment)
        wrong_prior = {**prior, 'attachment_texts': {prior_attachment: first_plan.replace('\n160\n40\n200\n', '\n160\n40\n190\n')}}
        self.assertEqual(publish_replayed([wrong_prior, current])[0], [])

    def test_innovation_three_leagues_keep_plan_contributions_and_cogp_distinct(self):
        from services.lp.src.lp_kdb_innovation_terms import result_roster
        from services.lp.src.lp_notice_publication import _attach_result_roster, _identity, _terms, split_glued_names
        fund = '혁신성장펀드(혁신산업펀드)'
        header = f'『{fund}』 2025년 위탁운용사 '
        cap = ('정책출자자 위탁운용 총액 : 총 4,800억원 내외\n(단위: 억원)\n정책출자자\n합 계\n'
               '정부재정(재정모펀드)\n한국산업은행\n성장사다리펀드2\n2,000\n2,300\n500\n4,800\n* 출자자별 승인\n')
        plan = ('재정\n산은\n사다리2\n합계(비율)\n'
                '소 형\n(자율제안)\n540\n190\n320\n1,050(35%)\n750~1,000\n3~4\n3,000\n신한\n'
                '중 형\n(자율제안)\n1,105\n1,535\n180\n2,820(31%)\n2,000~3,000\n3~5\n9,000\n산은\n'
                'M&A\n355\n575\n-\n930(31%)\n3,000\n1\n3,000\n'
                '합 계\n2,000\n2,300\n500\n4,800(32%)\n-\n7~10\n15,000\n')
        body = (cap + plan + '중형·M&A\n소형\n주관기관\n한국산업은행\n(정책펀드금융실)\n신한자산운용\n(특별자산운용실)\n'
                '접수일시\n○ 2025년 4월 14일(월) 13:00 ~ 16:00 (분야별 주관기관 앞 제출)\n접수방법\n○ 접수\n'
                '출자대상투자기구○기관전용사모집합투자기구○벤처투자조합※선정된위탁운용사 허용')
        original = {'title': header + '선정계획 공고', 'institution_id': 'kdb', 'date': '2025-03-31',
                    'body': body, 'sha256': 'a'*64, 'url': 'https://www.kdb.co.kr/offer', 'source_channel': 'institution_board'}
        terms, raw = _terms(original, None, NOW)
        self.assertEqual(raw['amount_scope'], 'combined')
        self.assertEqual(terms['commitment_amount_krw'], 4_800 * 10**8)
        self.assertEqual(terms['contribution_allocations']['한국산업은행'], 2_300 * 10**8)
        self.assertEqual(terms['deadline'], '2025-04-14T16:00:00+09:00')
        self.assertEqual([s['amount_krw']//10**8 for s in terms['segments']], [1_050, 2_820, 930])
        self.assertIn('중형·M&A는 한국산업은행', terms['contribution_note'])
        broken, raw = _terms({**original, 'body': body.replace('\n575\n', '\n570\n')}, None, NOW)
        self.assertTrue(raw['allocation_reading_failed'])
        self.assertNotIn('commitment_amount_krw', broken)

        final = {**original, 'title': header + '선정 결과'}
        reopened = {**original, 'title': f'『{fund}』 2024년 2차 위탁운용사 선정계획 (재)공고'}
        self.assertEqual(_identity(original), _identity(final))
        self.assertNotEqual(_identity(original), _identity(reopened))
        report = (f'< {fund} 2025년 위탁운용사 선정 결과 > (단위 : 억원, 개) 지원분야(운용사 수) 펀드규모 선정 운용사명 (가나다순)\n'
                  '소형 (3)750~1,000(총 3,000)아이엠엠인베스트먼트에이치비인베스트먼트프리미어파트너스\n'
                  '중형 (4)2,000~3,000(총 9,000)에스브이인베스트먼트에스케이에스프라이빗에쿼티'
                  '우리프라이빗에퀴티자산운용/엔에이치투자증권(Co-GP)케이투인베스트먼트파트너스\n'
                  'M&A (1)3,000(총 3,000)이음프라이빗에쿼티')
        program = {**terms, 'asset_scope': 'PE·VC 공동 모집'}
        roster = result_roster(final, report, program, split_glued_names)
        self.assertEqual(sum(len(names) for _, names in roster), 9)
        self.assertIn(('중형 · 공동운용', ['우리프라이빗에퀴티자산운용', '엔에이치투자증권']), roster)
        for wrong in (report.replace('(Co-GP)', ''), report.replace('중형 (4)', '중형 (5)'),
                      report.replace('2025년', '2024년'), report.replace('(총 9,000)', '(총 8,000)')):
            self.assertEqual(result_roster(final, wrong, program, split_glued_names), [])
        incomplete = {**final, 'attachment_texts': {'https://www.kdb.co.kr/fileView':
                       '선정 운용사명(가나다순)\n소형아이엠엠인베스트먼트'}}
        program['institution_id'] = 'kdb'
        _attach_result_roster(program, [incomplete], [])
        self.assertNotIn('selected_gps', program)

    def test_growth_support_two_leagues_and_bank_cogp_keep_actual_teams(self):
        from services.lp.src.lp_notice_publication import _attach_result_roster, _terms
        title = '『혁신성장펀드(성장지원펀드)』 2025년 위탁운용사 '
        cap = ('정책출자자 위탁운용 총액 : 총 4,700억원 내외\n(단위: 억원)\n정책출자자\n합 계\n'
               '정부재정(재정모펀드)\n한국산업은행\n1,000\n3,700\n4,700\n* 출자자별 승인\n')
        table = ('재정\n산은\n합계(비율)\n'
                 '중 형\n600\n400\n1,000(33%)\n1,500\n2\n3,000\n우리\n'
                 '대 형\n(자율제안)\n400\n3,300\n3,700(31%)\n3,000~5,000\n3~4\n12,000\n산은\n'
                 '합 계\n1,000\n3,700\n4,700(31%)\n-\n5~6\n15,000\n')
        body = (cap + table + '대형\n중형\n주관기관\n한국산업은행\n(정책펀드금융실)\n우리자산운용\n(신성장기업투자실)\n'
                '접수일시○2025년3월5일(수)13:00~16:00접수방법○접수\n'
                '출자대상투자기구○기관전용사모집합투자기구○벤처투자조합※선정된위탁운용사 허용')
        notice = {'institution_id': 'kdb', 'title': title + '선정계획 공고', 'date': '2025-02-17',
                  'url': 'https://www.kdb.co.kr/growth-plan', 'source_channel': 'institution_board', 'sha256': 'a'*64, 'body': body}
        terms, raw = _terms(notice, None, NOW)
        self.assertEqual(raw['amount_scope'], 'combined')
        self.assertEqual(terms['contribution_allocations'], {'정부재정': 1_000 * 10**8, '한국산업은행': 3_700 * 10**8})
        self.assertEqual(terms['deadline'], '2025-03-05T16:00:00+09:00')
        self.assertEqual(terms['manager_count_label'], '5~6개 팀')
        self.assertIn('중형은 우리자산운용', terms['contribution_note'])
        broken, raw = _terms({**notice, 'body': body.replace('\n3,300\n', '\n3,301\n')}, None, NOW)
        self.assertTrue(raw['allocation_reading_failed'])
        self.assertNotIn('commitment_amount_krw', broken)
        attachment = 'https://www.kdb.co.kr/growth-result.pdf'
        text = ('<혁신성장펀드(성장지원펀드) 2025년 위탁운용사 선정 결과> (단위:억원,개)'
                '지원분야(운용사 수) 펀드규모 선정 운용사명(가나다순)\n'
                '중형 (2)1,500(총 3,000)노앤파트너스키움프라이빗에쿼티/중소기업은행(Co-GP)\n'
                '대형 (3)3,000~5,000(총 12,000)아주아이비투자원익투자파트너스케이스톤파트너스')
        final = {**notice, 'title': title + '선정 결과', 'date': '2025-03-31', 'url': 'https://www.kdb.co.kr/growth-result',
                 'attachment_texts': {attachment: text}, 'attachment_hashes': {attachment: 'b'*64}}
        program = {**terms, 'institution_id': 'kdb', 'asset_scope': 'PE·VC 공동 모집', 'selected_gps': [], 'status': '선정 결과 발표'}
        for bad in (text.replace('(Co-GP)', ''), text.replace('대형 (3)', '대형 (4)'), text.replace('성장지원펀드', '혁신산업펀드')):
            _attach_result_roster(program, [{**final, 'attachment_texts': {attachment: bad}}], [])
            self.assertEqual(program['selected_gps'], [])
        _attach_result_roster(program, [final], [])
        self.assertEqual(len(program['selected_gps']), 6)
        self.assertEqual(program['status'], '선정 완료')
        self.assertEqual({name for name, track in program['gp_tracks'].items() if track == '중형 · 공동운용'},
                         {'키움프라이빗에쿼티', '중소기업은행'})

    def test_split_glued_names(self):
        from services.lp.src.lp_notice_publication import split_glued_names
        self.assertEqual(['아이엠엠인베스트먼트', '엘비인베스트먼트'], split_glued_names('아이엠엠인베스트먼트엘비인베스트먼트'))
        self.assertEqual(['스카이레이크에쿼티파트너스', '에이티넘인베스트먼트'],
                         split_glued_names('스카이레이크에쿼티파트너스에이티넘인베스트먼트'))
        self.assertEqual(['미래에셋벤처투자/브레인자산운용'], split_glued_names('미래에셋벤처투자/브레인자산운용 (Co-GP)'))
        # Two readings (one long name or two names) without a known name: no answer.
        self.assertIsNone(split_glued_names('스마일게이트인베스트먼트파트너스인베스트먼트'))
        self.assertEqual(['스마일게이트인베스트먼트', '파트너스인베스트먼트'],
                         split_glued_names('스마일게이트인베스트먼트파트너스인베스트먼트', {'파트너스인베스트먼트'}))
        self.assertIsNone(split_glued_names('컴퍼니케이파트너스'))
        self.assertEqual(['컴퍼니케이파트너스'], split_glued_names('컴퍼니케이파트너스', {'컴퍼니케이파트너스'}))

    def test_mixed_table_keeps_only_the_pe_field(self):
        from services.lp.src.lp_notice_publication import kdb_result_roster
        self.assertEqual([('PE', ['더함파트너스', '릴슨프라이빗에쿼티'])], kdb_result_roster(self.TABLE))
        self.assertEqual([('중형', ['아이엠엠인베스트먼트', '엘비인베스트먼트'])], kdb_result_roster(
            '<결과>\n지원분야선정 운용사명 (가나다순)중형아이엠엠인베스트먼트엘비인베스트먼트'))
        self.assertEqual([], kdb_result_roster('지원분야운용사AI·IP노틱인베스트먼트(주)'))
        self.assertEqual([], kdb_result_roster('운용사명(가나다순)\n중형이름모를곳'))

    def test_kdb_joint_vehicles_keep_combined_budget_and_end_of_reception_window(self):
        from services.lp.src.lp_institution_notice_terms import kdb_joint_size_offering
        from services.lp.src.lp_notice_publication import _scope, _terms
        url = 'https://www.kdb.co.kr/program'
        file = 'https://www.kdb.co.kr/offering.pdf'
        cell = ('출자대상투자기구\n○「자본시장과금융투자업에관한법률」에의한기관전용사모집합투자기구* '
                '*경영참여목적에한함○「자본시장과금융투자업에관한법률」에의한창업·벤처전문사모집합투자기구'
                '○「여신전문금융업법」에의한신기술사업투자조합○「벤처투자촉진에관한법률」에의한벤처투자조합'
                '※선정된위탁운용사는관련법규에따라협의')
        overview = ('분야별출자계획○출자계획분야산은출자금액산은출자비율펀드별목표결성금액선정운용사수조성목표'
                    '중형600억원30.0%2,000억원1개2,000억원소형900억원30.0%750 또는 1,000억원(운용사 자율선택)'
                    '3~4개3,000억원합계1,500억원30.0%-4~5개5,000억원')
        purpose = ('주목적투자대상및의무투자비율□아래①과②를모두충족하여야함'
                   '①➊AI인프라,➋AI모델,➌AI응용서비스,➍AI전환(AIX)등AI밸류체인에목표결성금액의[60%]이상투자'
                   '※AI밸류체인관련분야②중소․중견기업에약정총액의60%이상투자산은출자비율')
        pdf = ('위탁운용금액○위탁운용금액:총1,500억원 접수일시○2025년7월25일(금)10:00~15:00접수방법○제출서류\n'
               + overview + '\n' + cell + '\n' + purpose)
        notice = {'institution_id': 'kdb', 'source_channel': 'institution_board', 'date': '2025-06-27',
                  'title': '2025 AI 코리아 펀드 위탁운용사 선정계획 공고', 'body': '첨부파일 참고',
                  'url': url, 'sha256': 'a' * 64, 'attachments': [{'name': '선정계획.pdf', 'url': file}],
                  'attachment_hashes': {file: 'b' * 64}, 'attachment_texts': {file: pdf}}
        self.assertEqual(_scope(notice), 'mixed_pe_blind')
        terms, raw = _terms(notice, None, NOW)
        self.assertEqual(raw['amount_scope'], 'combined')
        self.assertEqual(terms['commitment_amount_krw'], 1_500 * 10**8)
        self.assertEqual(terms['deadline'], '2025-07-25T15:00:00+09:00')
        self.assertEqual([s['amount_krw'] for s in terms['segments']], [600 * 10**8, 900 * 10**8])
        self.assertEqual(terms['manager_count_label'], '4~5개사')
        self.assertEqual(terms['primary_investment']['items'],
                         ['목표결성금액의 60% 이상을 AI 밸류체인에 투자', '약정총액의 60% 이상을 중소·중견기업에 투자'])
        notice['attachment_texts'][file] = pdf.replace('소형900억원', '소형901억원')
        self.assertNotIn('segments', _terms(notice, None, NOW)[0])
        self.assertFalse(kdb_joint_size_offering(pdf.replace('출자대상투자기구', '과거투자기구')))
        self.assertFalse(kdb_joint_size_offering(pdf.replace('※선정된위탁운용사', '※과거운용사')))
        self.assertFalse(kdb_joint_size_offering(pdf.replace(overview, '')))

    def test_kdb_size_roster_handles_a_wrapped_cell_and_legal_form_markers(self):
        from services.lp.src.lp_notice_publication import kdb_result_roster
        table = ('<2025 AI 코리아 펀드 위탁운용사 선정 결과>지원분야선정 운용사명 (가나다순)'
                 '중형스톤브릿지벤처스(주)\n소형\n'
                 '스틱벤처스(주)위벤처스(유)(주)코오롱인베스트먼트키움인베스트먼트(주)')
        self.assertEqual(kdb_result_roster(table), [('중형', ['스톤브릿지벤처스']),
                         ('소형', ['스틱벤처스', '위벤처스', '코오롱인베스트먼트', '키움인베스트먼트'])])
        self.assertEqual(kdb_result_roster(table.rsplit('\n', 1)[0]), [])
        self.assertEqual(kdb_result_roster(table + '\n다른칸자료'), [])
        self.assertEqual(kdb_result_roster(table.replace('선정 운용사명', '지원 운용사명')), [])

    def test_kdb_separate_pe_strategies_use_their_own_budget(self):
        from services.lp.src.lp_institution_notice_terms import extract_terms
        header = ('분야별출자계획○출자계획분야산은출자금액산은출자비율펀드별목표결성금액(최소결성규모)선정운용사수조성목표')
        rows = ('VC300억원28.6%350억원3개1,050억원PE신산업투자350억원29.2%1,200억원1개1,200억원'
                '사업재편350억원29.2%1,200억원1개1,200억원합계1,000억원--5개3,450억원')
        policy = ('○PE펀드 ①[신산업투자]신산업을 영위하는 남부권 지역 중소·중견기업에 당행 출자금의 1배수* 이상 투자 '
                  '②[사업재편]남부권 지역 중소·중견기업의 사업재편에 당행 출자금의 1배수* 이상 투자 '
                  '*단, 동남권 지역 기업에 0.3배수 이상 및 서남권 지역 기업에 0.3배수 이상 투자하여야 함')
        body = '위탁운용금액: 총 1,000억원 이내 ' + header + rows + ' 접수일시 ○ 2025년 8월 1일(금) 10:00 ~ 15:00 접수방법 ○ 제출' + policy
        notice = {'institution_id': 'kdb', 'title': '2025년 남부권 지역성장지원펀드 선정계획 공고',
                  'url': 'https://www.kdb.co.kr/program', 'date': '2025-06-20', 'body': body, 'sha256': 'a' * 64}
        terms = extract_terms(notice)
        self.assertEqual(terms['commitment_amount_krw'], 700 * 10**8)
        self.assertEqual(terms['total_commitment_amount_krw'], 1_000 * 10**8)
        self.assertEqual(terms['manager_count'], 2)
        self.assertEqual([s['amount_krw'] for s in terms['segments']], [350 * 10**8, 350 * 10**8])
        self.assertEqual(terms['deadline'], '2025-08-01T15:00:00+09:00')
        self.assertIn('서남권 기업', terms['primary_investment']['items'][-1])
        for change in (body.replace('사업재편350억원', '사업재편351억원'), body.replace('총 1,000억원 이내', '총 1,100억원 이내')):
            held = extract_terms({**notice, 'body': change})
            self.assertTrue(held['allocation_reading_failed'])
            self.assertNotIn('commitment_amount_krw', held)

    def test_result_attachment_becomes_pe_selection(self):
        from services.lp.src.lp_notice_publication import _attach_result_roster
        from services.lp.src.lp_program_service import validate
        p = {'id': 'kdb-2026-x', 'institution_id': 'kdb', 'institution_name': '한국산업은행', 'title': 't',
             'asset_scope': 'PE·VC 공동 모집', 'status': '선정 결과 발표', 'selected_gps': [],
             'events': [{'date': '2026-05-07', 'type': '모집 공고', 'title': 'a', 'url': 'https://www.kdb.co.kr/a'},
                        {'date': '2026-07-29', 'type': '선정 결과', 'title': 'b', 'url': 'https://www.kdb.co.kr/b'}]}
        attachment = 'https://www.kdb.co.kr/fileView?groupId=1'
        result = {'institution_id': 'kdb', 'title': '『2026 남부권 지역성장지원펀드』 위탁운용사 선정 결과', 'date': '2026-07-29',
                  'url': 'https://www.kdb.co.kr/b', 'body': '선정 결과를 첨부파일과 같이 공고합니다.',
                  'attachment_texts': {attachment: self.TABLE}, 'attachment_hashes': {attachment: 'a' * 64},
                  'attachments': [{'name': '선정결과.hwp', 'url': attachment}]}
        holds = []
        _attach_result_roster(p, [result], holds)
        self.assertEqual(['더함파트너스', '릴슨프라이빗에쿼티'], [g['name'] for g in p['selected_gps']])
        self.assertEqual({'PE'}, {g['asset_scope'] for g in p['selected_gps']})
        self.assertTrue(all(g['id'].startswith('kdb-') for g in p['selected_gps']))
        self.assertEqual('선정 완료', p['status'])
        validate({'as_of': '2026-11-12', 'programs': [p]})


class RepostDuplicateTests(unittest.TestCase):
    """An association repost and the institution's own notice are one solicitation."""

    def program(self, pid, url, title, deadline='2026-09-07T16:00:00+09:00', amount=270000000000, extra_events=()):
        return {'id': pid, 'institution_id': 'sema', 'title': title, 'basic_publication': True,
                'deadline': deadline, 'commitment_amount_krw': amount, 'source_program_key': pid,
                'events': [{'url': url, 'date': '2026-08-14', 'type': '모집 공고', 'title': title}, *extra_events]}

    def test_repost_merges_into_the_institutions_own_program(self):
        from services.lp.src.lp_notice_publication import merge_reposted_duplicates
        own = self.program('sema-2026-b9d1', 'https://www.sema.or.kr/sema/bbs/view.do?nttId=1', '2026년 국내 PE·VC 블라인드 펀드 선정계획 공고')
        repost = self.program('sema-2026-9a87', 'https://www.kvca.or.kr/Program/invest/listbody.html?po_no=896',
                              '[과학기술인공제회] 2026년 국내 PE·VC 블라인드 펀드 선정 공고',
                              extra_events=[{'url': 'https://www.kvca.or.kr/x', 'date': '2026-10-01', 'type': '선정 결과'}])
        holds = []
        merged = merge_reposted_duplicates([repost, own], holds)
        self.assertEqual([p['id'] for p in merged], ['sema-2026-b9d1'])
        self.assertEqual([e['type'] for e in merged[0]['events']], ['모집 공고', '선정 결과'])
        self.assertEqual(holds[0]['stage'], 'basic_duplicate')
        self.assertEqual((holds[0]['program_id'], holds[0]['kept_program_id']), ('sema-2026-9a87', 'sema-2026-b9d1'))

    def test_different_rounds_are_not_merged(self):
        from services.lp.src.lp_notice_publication import merge_reposted_duplicates
        june = self.program('a', 'https://www.sema.or.kr/1', '2026년 국내 블라인드 펀드 선정 공고', deadline='2026-07-01')
        september = self.program('b', 'https://www.sema.or.kr/2', '2026년 국내 블라인드 펀드 선정 공고', deadline='2026-10-12')
        reviewed = {**self.program('c', 'https://www.kvca.or.kr/3', '2026년 국내 블라인드 펀드 선정 공고', deadline='2026-07-01'), 'basic_publication': False}
        self.assertEqual(len(merge_reposted_duplicates([june, september, reviewed], [])), 3)


class StageNoticeIdentityTests(unittest.TestCase):
    """KDB drops 『』 on result notices; they must still join the round's announcement."""

    def test_quoted_and_unquoted_fund_names_share_one_identity(self):
        from services.lp.src.lp_notice_publication import _identity
        def key(title):
            return _identity({'title': title, 'institution_id': 'kdb', 'date': '2026-05-01'})
        announce = key('『국민성장펀드(간접투자분야) 정책성펀드』 2026년 1차 위탁운용사 선정계획 공고')
        self.assertEqual(key('국민성장펀드(간접투자분야) 정책성펀드 2026년 1차 위탁운용사 선정 결과'), announce)
        self.assertEqual(key('국민성장펀드(간접투자분야) 정책성펀드 2026년 1차 위탁운용사 선정 서류심사 결과'), announce)
        self.assertNotEqual(key('『국민성장펀드(간접투자분야) 정책성펀드』 2026년 2차 위탁운용사 선정계획 공고'), announce)



class MinimumFundSizeTests(unittest.TestCase):
    """Minimum fund size from explicit notice wording; ambiguous wording gives nothing."""

    def size(self, body):
        from services.lp.src.lp_notice_publication import minimum_fund_size
        return minimum_fund_size({'body': body, 'url': 'https://example.or.kr/n', 'sha256': 'a' * 64}).get('fund_target_label')

    def test_explicit_minimum(self):
        self.assertEqual(self.size('펀드별 결성 규모 - 최소 결성규모 3,500억원 이상 선정 운용사 수'), '최소 3,500억원')
        self.assertEqual(self.size('운용 방식 ‧ 블라인드 최소결성규모 ‧ 2,000억원 공동투자제안'), '최소 2,000억원')

    def test_range(self):
        self.assertEqual(self.size('Buyout, Growth 전략의 펀드별 결성 규모는 최소 1,000억원 ~ 최대 5,000억원 제한'), '1,000억~5,000억원')

    def test_vc_section_minimum_is_skipped_and_pe_labelled(self):
        body = ('최소결성규모 ㆍ최소 펀드 결성규모 : 3,000억원 이상 투자기구 ㆍ‘자본시장과 금융투자업에 관한 법률’에 의한 기관전용 사모집합투자기구 '
                '최소결성규모 ㆍ최소 펀드 결성규모 : 1,000억원 이상 투자기구 ㆍ‘벤처투자 촉진에 관한 법률’에 의한 벤처투자조합')
        self.assertEqual(self.size(body), '최소 3,000억원 (PE)')

    def test_side_by_side_columns_and_leagues_give_nothing(self):
        self.assertIsNone(self.size('최소 펀드 결성 규모 1,000억원 이상 500억원 이상 최소 투자확약서 규모'))
        self.assertIsNone(self.size('제안대상 펀드의 최소결성규모~최대결성규모 - 대형리그 : 7,000억원 이상 ~ 제한없음 - 중형 이하 리그 : 1,000억원 이상'))
        self.assertIsNone(self.size('최소 결성규모 1,000억원 이상 ... 다른 곳의 최소 결성규모 2,000억원 이상'))

    def test_proposal_fund_and_overview_wording(self):
        self.assertEqual(self.size('위탁운용사로 선정된 기관 중 제안펀드 결성 규모가 5,000억원 이상으로 30% 이상'), '최소 5,000억원')
        self.assertEqual(self.size('[블라인드형] 누적운용규모 3,000억원 이상이면서 제안펀드 결성규모 1,000억원 이상(VC는 700억원 이상) '
                                   '나) [인프라 프로젝트형] 제안펀드 결성규모 500억원 이상'), '최소 1,000억원')
        self.assertEqual(self.size('조합 약정 금액 총 300억원 펀드 규모 5,000억원 이상 투자 부문 ... 예상펀드규모 및 출자자'), '최소 5,000억원')
        self.assertIsNone(self.size('최종 펀드 결성규모의 15% 이내'))


class HistoryScopeAndHeadlineTests(unittest.TestCase):
    """2020+ history: 산재보험기금 PEF notices, investment-amount headlines, development funds."""

    def notice(self, title, body, institution='moel_iaci'):
        return {'title': title, 'body': body, 'url': 'https://www.moel.go.kr/x', 'sha256': 'a' * 64,
                'institution_id': institution, 'source_channel': 'institution_board', 'date': '2022-06-13',
                'attachments': [], 'attachment_texts': {}, 'attachment_hashes': {}}

    def test_investment_amount_headline_with_manager_count(self):
        from services.lp.src.lp_notice_publication import headline_amount
        result = headline_amount(self.notice('2022년 산재보험기금 대체투자상품(PEF) 선정 공고',
                                             '□ 선정 유형 : 블라인드 PEF □ 투자 금액 : 총 1,500억원 (3건 선정 예정)'))
        self.assertEqual((result['commitment_label'], result['manager_count']), ('총 1,500억원', 3))

    def test_moel_iaci_explicit_pef_notice_is_pe_scope(self):
        from services.lp.src.lp_notice_publication import _scope
        n = self.notice('2022년 산재보험기금 대체투자상품(PEF) 선정 공고',
                        '선정 유형 : 블라인드 PEF 경영참여형사모집합투자기구(PEF) 상품')
        self.assertIn(_scope(n), ('pe_blind', 'mixed_pe_blind'))

    def test_development_blind_fund_is_outside(self):
        from services.lp.src.lp_notice_publication import _scope
        n = self.notice('군인공제회 국내 개발 블라인드 펀드 선정 계획 공고', '블라인드 펀드 PEF', institution='mmaa')
        self.assertEqual(_scope(n), 'outside')

    def test_pe_section_total_when_pe_and_vc_are_set_out_separately(self):
        from services.lp.src.lp_notice_publication import headline_amount
        body = ('1. PE 선정개요 구분 내용 출자규모 : 총 1500억 원 이내 운용사당 약정규모 300억 원 '
                '2. VC 선정개요 구분 내용 출자규모 : 총 900억원 이내')
        result = headline_amount(self.notice('2022년 PE·VC 블라인드펀드 정기출자 시행 공고', body, institution='sema'))
        self.assertEqual((result['commitment_label'], result['amount_scope']), ('PE 부문 1,500억원 이내', 'pe_only'))

    def test_repeated_table_caption_does_not_open_a_second_pe_section(self):
        from services.lp.src.lp_notice_publication import _pe_section
        body = ('1. PE 부문 선정개요 출자규모 : 총 1,200억원 2. VC 부문 선정개요 PE 부문 선정개요 - 구분 출자규모 : 총 600억원')
        sections = _pe_section(self.notice('x', body, institution='sema'))
        self.assertEqual(len(sections), 1)
        self.assertNotIn('600', sections[0])

    def test_listed_securities_mandates_never_join_the_pe_track(self):
        from services.lp.src.lp_notice_publication import _scope
        n = self.notice('[공고] 과학기술인공제회 국내 Pre-IPO 위탁운용사 선정 공고',
                        '투자 방식 : 직접 및 재간접(펀드, PE, VC, 신기사 등)', institution='sema')
        self.assertNotIn(_scope(n), ('pe_blind', 'mixed_pe_blind'))
        n = self.notice('[과학기술인공제회] 국내 Active주식(일반주식)형 위탁운용사 선정 공고', 'PE VC 블라인드', institution='sema')
        self.assertNotIn(_scope(n), ('pe_blind', 'mixed_pe_blind'))

    def test_fund_total_eligibility_is_a_minimum_fund_size(self):
        from services.lp.src.lp_notice_publication import minimum_fund_size
        n = self.notice('x', '제안 펀드 요건 운용 규모 펀드별 결성총액 1,500억원 이상 타기관 출자확약')
        self.assertEqual(minimum_fund_size(n)['fund_target_label'], '최소 1,500억원')


class OrphanResultLinkTests(unittest.TestCase):
    """Results whose titles drop the institution name, or name nothing specific, still join their round."""

    def n(self, title, day, body='', institution='geps', url_id='1'):
        return {'title': title, 'date': day, 'body': body, 'institution_id': institution,
                'url': f'https://www.geps.or.kr/{url_id}', 'sha256': 'a' * 64, 'source_channel': 'institution_board',
                'attachments': [], 'attachment_texts': {}, 'attachment_hashes': {}}

    def test_result_without_institution_name_joins_by_title(self):
        from services.lp.src.lp_notice_publication import _identity, _merge_orphan_results
        a = self.n('2024년 공무원연금공단 국내 사모대체 블라인드펀드(PEF) 위탁운용사 선정', '2024-05-21', '블라인드 PEF')
        r = self.n('2024년 국내 사모대체 블라인드펀드(PEF) 위탁운용사 선정 결과 공고', '2024-06-28', url_id='2')
        groups = {_identity(a): [a], _identity(r): [r]}
        _merge_orphan_results(groups)
        self.assertEqual(len(groups), 1)
        self.assertEqual(r['stage_link'], 'title_without_institution_name')

    def test_generic_result_title_needs_a_single_pe_round_in_the_window(self):
        from services.lp.src.lp_notice_publication import _generic_result_title
        self.assertTrue(_generic_result_title(self.n('총회연금재단 2026 위탁운용사 최종 선정 결과 공지', '2026-08-11', institution='pck_pension')))
        self.assertFalse(_generic_result_title(self.n('총회연금재단 2025 위탁운용사 최종 선정 결과 공지', '2026-08-11', institution='pck_pension')))
        self.assertFalse(_generic_result_title(self.n('2026년 국내 「산업성장펀드」 블라인드 PEF 위탁운용사 선정결과', '2026-10-15')))


class LargeLpPeTrackTests(unittest.TestCase):
    """User decision 2026-11-12: large LPs' PE tracks are published, joint scope labelled."""
    BODY = ('투자기구: 기관전용 사모집합투자기구, 벤처투자조합, 신기술사업투자조합\n'
            '총 출자금액 1,000억원 이내\n접수마감: 2026.10.20(화) 16:00')

    def kdb(self, number, title, body=None, day='2026-10-01'):
        return notice(number, title=title, body=body or self.BODY, day=day, institution_id='kdb',
                      url=f'https://www.kdb.co.kr/notice/{number}')

    def test_policy_fund_pe_track_published_as_joint_scope(self):
        from services.lp.src.lp_notice_publication import _scope
        n = self.kdb(1, '『2026 남부권 지역성장지원펀드』위탁운용사 선정계획 공고')
        self.assertEqual(_scope(n), 'mixed_pe_blind')
        programs, holds = publish([n])
        p = next(p for p in programs if p['institution_id'] == 'kdb')
        self.assertEqual(p['asset_scope'], 'PE·VC 공동 모집')
        if p.get('commitment_label'):
            self.assertIn('PE·VC 합계', p['commitment_label'])

    def test_same_rule_does_not_open_other_institutions_or_fund_of_funds(self):
        from services.lp.src.lp_notice_publication import _scope
        other = notice(2, title='2026년 대체투자 위탁운용사 선정 공고', body=self.BODY)
        self.assertEqual(_scope(other), 'needs_confirmation')
        fof = self.kdb(3, '『지역활성화 투자 펀드』 2026년 모펀드 위탁운용사 선정계획 공고')
        self.assertNotIn(_scope(fof), ('pe_blind', 'mixed_pe_blind'))
        venture = self.kdb(4, '『2026 벤처 펀드』 위탁운용사 선정계획 공고', body='투자기구: 벤처투자조합')
        self.assertNotIn(_scope(venture), ('pe_blind', 'mixed_pe_blind'))

    def test_joint_or_already_published_fund_is_not_duplicated(self):
        existing = {'id': 'kgrowth-2026-kculture-valueup', 'institution_id': 'kgrowth', 'institution_name': '한국성장금융',
                    'title': '「2026 K-컬처 밸류업 펀드」 위탁운용사 선정계획', 'asset_scope': 'PE', 'status': '선정 완료',
                    'selected_gps': [], 'events': [{'date': '2026-07-22', 'type': '모집 공고', 'title': 't', 'url': 'https://www.kgrowth.or.kr/1'}]}
        programs, holds = publish([self.kdb(5, '『K-컬처 밸류업 펀드』 위탁운용사 선정계획 공고')], existing=[existing])
        self.assertFalse([p for p in programs if p['institution_id'] == 'kdb'])
        self.assertTrue([h for h in holds if '이미 공개' in h.get('reason', '')])


class IbkResultRosterTests(unittest.TestCase):
    BODY = ('「글로벌 협력펀드」 위탁운용사 선정 결과를 아래와 같이 공지합니다. □ 대 형 ㅇ 운용사명(가나다순) '
            '- 가나인베스트먼트-다라크레딧 □ 중 형 ㅇ 운용사명(가나다순) - 마바인베스트먼트 - 사아파트너스 '
            '문의 : 중소기업은행 정책출자팀(innovest@ibk.co.kr/02-729-7112)')

    def program(self):
        return {'id': 'ibk-2026-x', 'institution_id': 'ibk', 'institution_name': 'IBK기업은행', 'title': 't',
                'asset_scope': 'PE', 'status': '선정 결과 발표', 'selected_gps': [],
                'events': [{'date': '2026-09-07', 'type': '모집 공고', 'title': 'a', 'url': 'https://www.ibk.co.kr/a'},
                           {'date': '2026-11-04', 'type': '선정 결과', 'title': 'b', 'url': 'https://www.ibk.co.kr/b'}]}

    def test_official_body_roster_becomes_selected_managers_with_leagues(self):
        from services.lp.src.lp_notice_publication import _attach_result_roster
        from services.lp.src.lp_program_service import validate
        p, holds = self.program(), []
        result = {'institution_id': 'ibk', 'title': '「글로벌 협력펀드」 위탁운용사 선정 결과', 'date': '2026-11-04',
                  'url': 'https://www.ibk.co.kr/b', 'body': self.BODY}
        _attach_result_roster(p, [result], holds)
        self.assertEqual([g['name'] for g in p['selected_gps']], ['가나인베스트먼트-다라크레딧', '마바인베스트먼트', '사아파트너스'])
        self.assertEqual(p['gp_tracks']['마바인베스트먼트'], '중형')
        self.assertEqual(p['status'], '선정 완료')
        validate({'as_of': '2026-11-12', 'programs': [p]})

    def test_unstructured_or_other_institution_body_adds_nothing(self):
        from services.lp.src.lp_notice_publication import _attach_result_roster
        p, holds = self.program(), []
        _attach_result_roster(p, [{'institution_id': 'ibk', 'title': '위탁운용사 선정 결과', 'date': '2026-11-04',
                                   'url': 'https://www.ibk.co.kr/b', 'body': '선정 결과를 첨부파일과 같이 공고합니다.'}], holds)
        self.assertEqual(p['selected_gps'], []); self.assertEqual(p['status'], '선정 결과 발표')
        other = {**self.program(), 'institution_id': 'kdb'}
        _attach_result_roster(other, [{'institution_id': 'kdb', 'title': '위탁운용사 선정 결과', 'date': '2026-11-04',
                                       'url': 'https://www.ibk.co.kr/b', 'body': self.BODY}], holds)
        self.assertEqual(other['selected_gps'], [])


class HeadlineAmountTests(unittest.TestCase):
    """The budget line of a notice fills an amount the term parsers missed, with its quote."""

    def notice(self, body, institution='moel_eif'):
        return {'url': 'https://www.moel.go.kr/1', 'sha256': 'a' * 64, 'body': body, 'title': 't',
                'institution_id': institution, 'source_channel': 'institution_board'}

    def test_pe_share_next_to_the_total_wins(self):
        from services.lp.src.lp_notice_publication import headline_amount
        result = headline_amount(self.notice('□ 선정 규모: 총 1,200억원 (PEF 600억원(2건), VC 600억원(3건) 선정'))
        self.assertEqual((result['commitment_amount_krw'], result['commitment_label'], result['manager_count'], result['amount_scope']),
                         (60_000_000_000, 'PE 부문 600억원', 2, 'pe_only'))
        self.assertEqual(result['extraction_evidence']['commitment'][0]['quote'], '선정규모:총1,200억원(PEF600억원(2건)')

    def test_single_total_with_qualifier(self):
        from services.lp.src.lp_notice_publication import headline_amount
        ibk = headline_amount(self.notice('주요 내용 (출자 금액) 총 1,200억원 이내 - 지원 분야별 출자비율 상이'))
        self.assertEqual((ibk['commitment_label'], ibk['amount_scope']), ('총 1,200억원 이내', 'combined'))
        kbiz = headline_amount(self.notice('배정금액 ∙ 10 개사 내외 , 100~800 억원 범위 내 출자규모 ∙ 총 3 ,000 억원 이내 신청 자격'))
        self.assertEqual(kbiz['commitment_amount_krw'], 300_000_000_000)

    def test_conflicting_totals_and_placeholders_give_nothing(self):
        from services.lp.src.lp_notice_publication import headline_amount
        self.assertEqual(headline_amount(self.notice('출자규모 총 3,000억원 이내 / 출자규모 총 2,000억원')), {})
        self.assertEqual(headline_amount(self.notice('4. 펀드결성규모 총 ○○○○억원')), {})

if __name__ == '__main__':
    unittest.main()
