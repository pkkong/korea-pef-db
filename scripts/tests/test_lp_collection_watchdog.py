import copy
import datetime as dt
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from scripts import lp_collection_watchdog as w

NOW = dt.datetime(2026, 11, 5, 8, 5, tzinfo=w.UTC)


def run(created='2026-11-05T06:20:00Z', status='completed', name=w.WORKFLOW):
    return {'id': 123, 'repository': {'full_name': w.REPOSITORY},
            'path': '.github/workflows/' + name, 'created_at': created,
            'status': status, 'conclusion': 'failure', 'head_branch': 'main', 'event':'schedule'}


class FakeAPI:
    def __init__(self, collection=None, active=None, jobs=None):
        self.collection = collection or []
        self.active = active or []
        self.calls = []
        self.jobs=jobs if jobs is not None else [{'conclusion':'failure','steps':[{'name':'Collect official sources'}]}]

    def __call__(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        if kwargs.get('dispatch'):
            return None
        if endpoint.endswith('/workflows/'+w.WORKFLOW):
            return {'id':77,'path':'.github/workflows/'+w.WORKFLOW,'state':'active'}
        if '/jobs?' in endpoint:
            return {'total_count':len(self.jobs),'jobs':copy.deepcopy(self.jobs)}
        rows = self.collection if '/workflows/' in endpoint else [
            r for r in self.active if 'status=' + r['status'] + '&' in endpoint]
        return {'total_count': len(rows), 'workflow_runs': copy.deepcopy(rows)}


class WatchdogTests(unittest.TestCase):
    def invoke(self, api, **kwargs):
        args = dict(now=NOW, repository=w.REPOSITORY, ref='refs/heads/main',
                    event='schedule', dry_run=False, api=api)
        args.update(kwargs)
        return w.run_watchdog(**args)

    def test_grace_latest_window_and_weekend(self):
        for text, due in [('2026-11-05T01:49:59+00:00', None),
                          ('2026-11-05T01:50:00+00:00', 0),
                          ('2026-11-05T07:49:59+00:00', 0),
                          ('2026-11-05T07:50:00+00:00', 6),
                          ('2026-11-07T08:00:00+00:00', None)]:
            value = w.due_window(dt.datetime.fromisoformat(text))
            self.assertEqual(value.hour if value else None, due)
        with self.assertRaises(w.WatchdogError):
            w.due_window(NOW.replace(tzinfo=None))

    def test_failed_run_covers_window_and_earliest_boundary(self):
        for stamp, expected in [('2026-11-05T05:50:00Z', 'window_covered'),
                                ('2026-11-05T05:49:59Z', 'missed_start')]:
            self.assertEqual(w.decide(NOW, [run(stamp)], [])['reason'], expected)
        other = run()
        other['head_branch'] = 'feature'
        self.assertEqual(w.decide(NOW, [other], [])['decision'], 'dispatch')
        other=run();other['event']='pull_request'
        self.assertEqual(w.decide(NOW,[other],[])['decision'],'dispatch')

    def test_concurrent_creation_during_api_read_suppresses_duplicate_dispatch(self):
        api=FakeAPI(active=[run(created='2026-11-05T08:05:30Z',status='queued')])
        self.assertEqual(self.invoke(api)['reason'],'source_queue_active')
        self.assertFalse(any(kw for _,kw in api.calls))

    def test_shared_source_workflows_cannot_be_silently_omitted_from_guard(self):
        root=Path(__file__).resolve().parents[2]/'.github/workflows'
        observed={p.name for p in root.iterdir() if p.suffix in {'.yml','.yaml'}
                  if re.search(r'^\s*group:.*\blp-program-collection\b',p.read_text(),re.M)}
        self.assertIn(w.WORKFLOW,observed)
        self.assertFalse(observed-w.SOURCE_WORKFLOWS)

    def test_active_source_queue_skips_even_when_collection_missing(self):
        for status in w.ACTIVE:
            api = FakeAPI(active=[run(status=status, name='inspect-lp-remaining-boards.yml')])
            self.assertEqual(self.invoke(api)['reason'], 'source_queue_active')
            self.assertFalse(any(kw for _, kw in api.calls))

    def test_sibling_workflow_does_not_block_lp_and_disabled_collection_is_respected(self):
        sibling=run(status='in_progress',name='deploy-newsletter-vercel.yml')
        sibling.update(head_branch=None,created_at='unrelated invalid metadata')
        api=FakeAPI(active=[sibling])
        self.assertEqual(self.invoke(api)['decision'],'dispatched')
        sibling['path']='dynamic/pages/pages-build-deployment'
        self.assertEqual(self.invoke(FakeAPI(active=[sibling]))['decision'],'dispatched')
        original=FakeAPI()
        def inactive(endpoint,**kw):
            if endpoint.endswith('/workflows/'+w.WORKFLOW):
                return {'id':77,'path':'.github/workflows/'+w.WORKFLOW,'state':'disabled_manually'}
            return original(endpoint,**kw)
        self.assertEqual(self.invoke(inactive)['reason'],'workflow_inactive')
        self.assertFalse(any(kw for _,kw in original.calls))

    def test_exact_dispatch_once_and_dry_run_never_posts(self):
        api = FakeAPI()
        self.assertEqual(self.invoke(api)['decision'], 'dispatched')
        posts = [(url, kw) for url, kw in api.calls if kw]
        self.assertEqual(posts, [(f'repos/{w.REPOSITORY}/actions/workflows/{w.WORKFLOW}/dispatches', {'dispatch': True})])
        api = FakeAPI()
        self.assertEqual(self.invoke(api, dry_run=True)['decision'], 'would_dispatch')
        self.assertFalse(any(kw for _, kw in api.calls))
        api = FakeAPI(collection=[run()])
        self.assertEqual(self.invoke(api)['reason'], 'window_covered')
        self.assertFalse(any(kw for _, kw in api.calls))

    def test_prior_provider_start_failure_is_not_repeated_in_a_new_window(self):
        old=run(created='2026-10-30T06:20:00Z')
        for jobs in ([],[{'conclusion':'failure','steps':[]}]):
            api=FakeAPI(collection=[old],jobs=jobs)
            self.assertEqual(self.invoke(api)['reason'],'prior_run_did_not_start')
            self.assertFalse(any(kw for _,kw in api.calls))
        api=FakeAPI(collection=[old])
        self.assertEqual(self.invoke(api)['decision'],'dispatched')

    def test_untrusted_context_no_execution(self):
        for change in ({'repository': 'someone/fork'}, {'ref': 'refs/heads/dev'},
                       {'event': 'pull_request'}, {'event': 'pull_request_target'},
                       {'event': 'workflow_run'}):
            api = FakeAPI()
            self.assertEqual(self.invoke(api, **change)['reason'], 'untrusted_context')
            self.assertEqual(api.calls, [])

    def test_invalid_receipts_fail_before_dispatch(self):
        for change in ({'id': True}, {'id': 0}, {'id': '123'},
                       {'repository': {'full_name': 'wrong/repo'}},
                       {'repository': None},
                       {'created_at': '2026-11-05T09:00:00Z'},
                       {'created_at': '2026-11-05T06:20:00'},
                       {'head_branch': None}, {'status': 'unknown'},
                       {'path': '.github/workflows/../evil.yml'}):
            row = run(); row.update(change)
            api = FakeAPI(collection=[row])
            with self.assertRaises(w.WatchdogError):
                self.invoke(api)
            self.assertFalse(any(kw for _, kw in api.calls))

    def test_provider_error_and_pagination_limit_fail_closed(self):
        for payload in ({}, {'total_count': 101, 'workflow_runs': []},
                        {'total_count': 300, 'workflow_runs': [run()] * 100}):
            calls = []
            def api(endpoint, **kw):
                calls.append(kw)
                return payload
            with self.assertRaises(w.WatchdogError):
                self.invoke(api)
            self.assertLessEqual(len(calls), 3)
            self.assertFalse(any(calls))
        with patch.object(w.subprocess, 'run', side_effect=OSError('secret detail')):
            with self.assertRaisesRegex(w.WatchdogError, '^GitHub API unavailable$'):
                self.invoke(w.gh_api)

    def test_cli_transport_exact_ref_and_no_raw_error(self):
        with patch.object(w.subprocess, 'run') as execute:
            execute.return_value.returncode = 0
            execute.return_value.stdout = b''
            w.gh_api(f'repos/{w.REPOSITORY}/actions/workflows/{w.WORKFLOW}/dispatches', dispatch=True)
            self.assertEqual(execute.call_args.args[0][-2:], ['-f', 'ref=main'])
            self.assertEqual(execute.call_args.kwargs['timeout'], 30)
            execute.return_value.returncode = 1
            execute.return_value.stderr = b'secret token'
            with self.assertRaisesRegex(w.WatchdogError, '^GitHub API failed$'):
                w.gh_api('test')


if __name__ == '__main__':
    unittest.main()
