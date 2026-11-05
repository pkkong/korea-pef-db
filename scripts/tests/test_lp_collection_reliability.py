import copy
import datetime as dt
import unittest

from scripts import lp_collection_reliability as m

NOW = dt.datetime(2026, 11, 5, 8, tzinfo=m.UTC)


def run(ident, created, **kwargs):
    return {'id': ident, 'repository': {'full_name': m.REPOSITORY},
            'path': '.github/workflows/'+m.WORKFLOW, 'head_branch': 'main',
            'status': 'completed', 'conclusion': 'success', 'event': 'schedule',
            'created_at': created.isoformat(), 'run_attempt': 1,
            'actor': {'login': 'pkkong'}, **kwargs}


class ReliabilityTests(unittest.TestCase):
    def test_six_expected_weekday_slots_with_grace_and_weekend(self):
        windows = m.expected_windows(NOW)
        self.assertEqual(len(windows), 6)
        self.assertEqual(windows[0], NOW.replace(day=3, hour=0, minute=20))
        self.assertEqual(windows[-1], NOW.replace(hour=6, minute=20))
        saturday = NOW.replace(day=7, hour=12)
        self.assertEqual(m.expected_windows(saturday)[-1], NOW.replace(day=6, hour=6, minute=20))
        before_grace = NOW.replace(hour=7, minute=49)
        self.assertEqual(m.expected_windows(before_grace)[-1].hour, 0)
        with self.assertRaises(m.WatchdogError):
            m.expected_windows(NOW.replace(tzinfo=None))

    def test_only_six_distinct_automatic_successful_slots_pass(self):
        inputs = [run(i+1, due+dt.timedelta(minutes=15)) for i, due in enumerate(m.expected_windows(NOW))]
        before = copy.deepcopy(inputs)
        out = m.assess(NOW, inputs)
        self.assertTrue(out['all_windows_ok'])
        self.assertEqual(out['successful_windows'], 6)
        self.assertEqual(inputs, before)
        # A second success in the same slot does not fill a missing morning.
        inputs[-1]['created_at'] = inputs[-2]['created_at']
        self.assertEqual(m.assess(NOW, inputs)['successful_windows'], 5)

    def test_manual_recovery_and_manual_rerun_do_not_fill_automation_gap(self):
        due = m.expected_windows(NOW)[-1]
        manual = run(1, due, event='workflow_dispatch')
        rerun = run(2, due, run_attempt=2)
        last = m.assess(NOW, [manual, rerun])['windows'][-1]
        self.assertEqual(last['state'], 'manual_only')
        self.assertEqual(last['manual_or_rerun_ids'], [1, 2])
        bot = run(3, due, event='workflow_dispatch', actor={'login': 'github-actions[bot]'})
        self.assertEqual(m.assess(NOW, [bot])['windows'][-1]['state'], 'ok')

    def test_failed_cancelled_and_running_keep_failure_signals(self):
        due = m.expected_windows(NOW)[-1]
        for conclusion in ('failure', 'cancelled', 'timed_out', 'startup_failure'):
            with self.subTest(conclusion=conclusion):
                self.assertEqual(m.assess(NOW, [run(1, due, conclusion=conclusion)])['windows'][-1]['state'], 'failed')
        running = run(1, due, status='in_progress', conclusion=None)
        self.assertEqual(m.assess(NOW, [running])['windows'][-1]['state'], 'running')
        # A successful duplicate must not erase a failed run in the same slot.
        failed = run(2, due, conclusion='failure')
        self.assertEqual(m.assess(NOW, [failed, run(3, due)])['windows'][-1]['state'], 'failed')

    def test_missing_and_unknown_history_differ(self):
        self.assertTrue(all(r['state'] == 'missing' for r in m.assess(NOW, [])['windows']))
        self.assertTrue(all(r['state'] == 'history_incomplete' for r in m.assess(NOW, [], history_complete=False)['windows']))
        due = m.expected_windows(NOW)[-1]
        self.assertEqual(m.assess(NOW, [run(1, due)], history_complete=False)['successful_windows'], 0)

    def test_other_ref_cannot_fill_slot_and_invalid_metadata_fails_closed(self):
        due = m.expected_windows(NOW)[-1]
        self.assertEqual(m.assess(NOW, [run(1, due, head_branch='feature')])['successful_windows'], 0)
        for update in ({'run_attempt': True}, {'actor': {}}, {'repository': {'full_name':'other/repo'}},
                       {'conclusion': 'unknown'}, {'path': '.github/workflows/sibling.yml'}):
            with self.subTest(update=update), self.assertRaises(m.WatchdogError):
                m.assess(NOW, [run(1, due, **update)])

    def test_markdown_is_internal_korean_schedule_evidence(self):
        out = m.markdown(m.assess(NOW, [run(42, m.expected_windows(NOW)[-1])]))
        self.assertIn('1/6', out)
        self.assertIn('11-05 15:20', out)
        self.assertIn('/actions/runs/42', out)
        self.assertIn('수동 복구는 자동 성공에 포함하지 않습니다', out)


if __name__ == '__main__':
    unittest.main()
