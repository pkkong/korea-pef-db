import copy
import unittest
from services.lp.src.lp_program_detail import planned_until, render_detail_body
from services.lp.src.lp_program_service import validate, assert_selected_gp_history


def program():
    url='https://official.example/announcement'
    return {'id':'fund-2026','institution_id':'fund','institution_name':'출자기관',
            'title':'PE 블라인드 모집','asset_scope':'PE','status':'접수 마감',
            'events':[{'type':'모집 공고','date':'2026-09-01','title':'모집','url':url}],
            'selected_gps':[], 'schedule_stages':[{'stage':'selection','label':'최종 선정',
                'original_label':'최종 선정','date':None,'date_label':'2026년 10월 말',
                'precision':'month_end','status':'planned','source_url':url}],
            'gp_stage_note':'최종 선정 GP는 개별 통보 예정입니다.'}


class ProgramDetailTests(unittest.TestCase):
    def test_vague_plans_use_conservative_end_and_never_fabricate_an_event_date(self):
        for event, expected in [
            ({'date_label':'2024년 2월 말'},'2024-02-29'),
            ({'date_label':'2026년 10월 초'},'2026-10-31'),
            ({'date_label':'2026년 9월 말 ~ 10월 초'},'2026-10-31'),
            ({'date':'2026-09','date_label':'2026년 9월 말 ~ 10월 초'},'2026-10-31'),
            ({'date':'2026-10-01','precision':'month_period'},'2026-10-31'),
            ({'date':'2026-10-04T15:00:00+09:00','precision':'datetime'},'2026-10-04'),
            ({'date_label':'선정 통보 후 3개월'},None),
            ({'date_label':'10월 말'},None),
            ({'date_label':'2026년 12월 ~ 1월'},None),
            ({'date_label':'2026년 13월'},None),
            ({'date':'2026-02-30'},None)]:
            with self.subTest(event=event):self.assertEqual(planned_until(event),expected)

    def test_elapsed_plan_and_individual_notification_are_not_claimed_final_results(self):
        p=program();before=copy.deepcopy(p)
        current=render_detail_body(p,'2026-10-31')
        later=render_detail_body(p,'2026-11-01')
        self.assertNotIn('>예정일 경과<',current)
        self.assertIn('>예정일 경과<',later)
        self.assertIn('2026년 10월 말',later)
        self.assertNotIn('<time>2026-10-31',later)
        self.assertIn('선정 명단은 아직 확인되지 않았습니다',later)
        self.assertNotIn('개별 통보 예정입니다.',later)
        self.assertIn('data-lp-plan-until="2026-10-31"',later)
        self.assertIn("timeZone:'Asia/Seoul'",later)
        self.assertEqual(p,before);self.assertEqual(p['selected_gps'],[])
        self.assertNotIn('선정 완료',later)

    def test_recorded_selection_keeps_old_plan_as_history_without_overdue_warning(self):
        p=program();p['events'].append({'type':'최종 선정','date':'2026-11-02','title':'선정','url':'https://official.example/result'})
        html=render_detail_body(p,'2026-11-07')
        self.assertIn('공고상 예정',html)
        self.assertNotIn('data-lp-plan-until=',html)

    def test_screening_roster_does_not_imply_final_selection_or_nonpublication(self):
        p=program();p.update(status='서류심사 결과',shortlisted_gps=['운용사A','운용사B'])
        p['events'].append({'type':'서류심사 결과','date':'2026-10-13','title':'서류심사','url':'https://official.example/screening'})
        html=render_detail_body(p,'2026-11-09')
        self.assertIn('서류심사 통과 2개 팀입니다.',html)
        self.assertIn('최종 선정 명단은 아직 확인되지 않았습니다.',html)
        self.assertNotIn('미공개',html)
        self.assertEqual(html.count('href="https://official.example/screening"'),2)
        self.assertEqual(p['selected_gps'],[])

    def test_preferred_roster_is_separate_sourced_and_preserved(self):
        p=program();p['status']='우선협상대상자'
        url='https://official.example/preferred'
        p['events'].append({'type':'우선협상대상자','date':'2026-10-23','title':'우선협상','url':url})
        p.update(preferred_gps=['일반운용사','루키운용사'],gp_tracks={'일반운용사':'일반리그','루키운용사':'루키리그'},
                 manager_list_sources={'preferred_gps':url})
        validate({'as_of':'2026-11-07','programs':[p]})
        html=render_detail_body(p,'2026-11-07')
        self.assertIn('우선협상대상자</h3>',html);self.assertIn('루키리그',html)
        self.assertIn('우선협상 결과 원문',html);self.assertEqual(p['selected_gps'],[])
        self.assertEqual(html.split('<section id="selection">')[1].count('우선협상 결과 원문'),1)
        self.assertIn('최종 선정 명단은 아직 확인되지 않았습니다',html)
        with self.assertRaises(ValueError):
            bad=copy.deepcopy(p);bad['manager_list_sources']['preferred_gps']='https://official.example/unrelated'
            validate({'as_of':'2026-11-07','programs':[bad]})
        for key in ('preferred_gps','manager_list_sources'):
            bad=copy.deepcopy(p);bad.pop(key)
            with self.subTest(key=key),self.assertRaises(ValueError):assert_selected_gp_history([p],[bad])


if __name__=='__main__':unittest.main()


class AnnouncedResultWithoutNames(unittest.TestCase):
    def test_announced_result_points_to_source_instead_of_unconfirmed(self):
        p = {'id': 'x', 'institution_id': 'kdb', 'institution_name': 'KDB', 'title': 't', 'asset_scope': 'PE',
             'status': '선정 결과 발표', 'selected_gps': [], 'basic_publication': True,
             'events': [{'date': '2026-05-07', 'type': '모집 공고', 'title': 'a', 'url': 'https://o.example/a'},
                        {'date': '2026-07-29', 'type': '선정 결과', 'title': 'b', 'url': 'https://o.example/b'}]}
        html = render_detail_body(p, '2026-11-12')
        self.assertIn('선정 결과가 발표됐습니다', html)
        self.assertNotIn('아직 확인되지 않았습니다', html)
        self.assertIn('https://o.example/b', html)
