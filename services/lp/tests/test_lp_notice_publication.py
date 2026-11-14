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
    """KDB result tables lose cell borders; names are split only when unambiguous."""
    TABLE = ('< 2026 남부권 지역성장지원펀드 위탁운용사 선정 결과 >지원분야지원 운용사명(가나다순)\n'
             'PE더함파트너스릴슨프라이빗에쿼티\nVC리인베스트먼트원익투자파트너스이앤인베스트먼트')

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
