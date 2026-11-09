import copy
import unittest
from unittest.mock import MagicMock
from services.lp.src.audit_lp_result_gaps import audit, export


def index():
    return {'kind':'lp_document_index_v1','database_index_complete':True,'row_limit':100,
            'database_rows':1,'records':[{'url':'https://official.example/result'}],
            'checked_at':'2026-11-09T13:54:51Z','snapshot_run_id':'published'}


def program():
    return {'id':'example','institution_id':'lp','status':'접수 마감',
            'deadline':'2026-09-16T16:00:00+09:00','selected_gps':[],
            'events':[{'type':'모집 공고','url':'https://official.example/notice'}]}


class ResultGapAuditTests(unittest.TestCase):
    def run_audit(self, programs, idx=None):
        return audit(programs, idx or index(), run_id='published', as_of='2026-11-09')

    def test_past_deadline_is_unconfirmed_and_never_closed_or_unpublished(self):
        p=program();before=copy.deepcopy(p);r=self.run_audit([p]);row=r['rows'][0]
        self.assertEqual(row['gap'],'deadline_passed_result_unconfirmed')
        self.assertTrue(row['deadline_passed']);self.assertFalse(row['unpublished_claim'])
        self.assertEqual(p,before);self.assertFalse(r['raw_source_rosters_replayed'])
        self.assertFalse(r['browser_names_verified'])

    def test_deadline_day_uses_korea_time(self):
        p=program();p['deadline']='2026-11-08T23:00:00+00:00'
        self.assertFalse(self.run_audit([p])['rows'][0]['deadline_passed'])
        p['deadline']='2026-11-08T14:59:00+00:00'
        self.assertTrue(self.run_audit([p])['rows'][0]['deadline_passed'])

    def test_screening_preferred_and_final_are_distinct(self):
        for key,expected in [('shortlisted_gps','screening_only_final_unconfirmed'),
                             ('preferred_gps','preferred_only_final_unconfirmed')]:
            p=program();p[key]=['manager'];self.assertEqual(self.run_audit([p])['rows'][0]['gap'],expected)
        p=program();p['events'].append({'type':'최종 선정','url':'https://official.example/result'})
        self.assertEqual(self.run_audit([p])['rows'][0]['gap'],'stored_result_roster_not_in_public_model')
        p['events'][-1]['url']='https://official.example/other'
        self.assertEqual(self.run_audit([p])['rows'][0]['gap'],'result_source_not_in_retained_index')

    def test_model_names_are_not_claimed_browser_verified_or_exported(self):
        p=program();p['events'].append({'type':'최종 선정','url':'https://official.example/result'})
        p['selected_gps']=[{'name':'Official Manager','source_url':'https://official.example/result'}]
        r=self.run_audit([p]);self.assertEqual(r['rows'][0]['gap'],'model_roster_present_ui_not_rechecked')
        self.assertEqual(r['rows'][0]['manager_counts']['selected_gps'],1)
        self.assertNotIn('Official Manager',str(r))
        p['selected_gps'][0].pop('source_url')
        self.assertEqual(self.run_audit([p])['rows'][0]['gap'],'selected_roster_source_gap')
        p['events'].pop()
        self.assertEqual(self.run_audit([p])['rows'][0]['gap'],'selection_event_link_gap')

    def test_partial_stale_or_duplicate_input_is_rejected(self):
        for values in ({'database_index_complete':False},{'snapshot_run_id':'old'}):
            i=index();i.update(values)
            with self.assertRaises(ValueError):self.run_audit([program()],i)
        with self.assertRaises(ValueError):self.run_audit([program(),program()])
        p=program();p['deadline']='2026년 10월 말'
        with self.assertRaises(ValueError):self.run_audit([p])

    def test_read_only_query_selects_no_private_state_or_mutation(self):
        conn=MagicMock();conn.execute.return_value.fetchone.return_value=('published',[program()])
        r=export(conn,index(),as_of='2026-11-09');self.assertEqual(r['programs'],1)
        calls=[x.args[0] for x in conn.execute.call_args_list]
        self.assertIn('READ ONLY',calls[0]);self.assertIn("data->'programs'",calls[-1])
        self.assertNotIn('SELECT data ',calls[-1])
        self.assertFalse(any(word in ' '.join(calls) for word in ('UPDATE','INSERT','DELETE','review_decisions','_lp_state_evidence')))
        conn.commit.assert_not_called()


if __name__=='__main__':unittest.main()
