import copy
import base64
import hashlib
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from services.lp.src import diagnose_lp_inventory_failures as probe
from services.lp.tests.test_lp_board_adapter_nh import small, fixture


def saved():
    config = probe.inventory.boards.load_configs(include_pending=True)['nh_central']
    plans = probe.inventory.query_plan('nh_central', config, '2025-11-09', '2026-11-08', independent=True)
    queries = [{**p, 'pages': [], 'boundary': 'source_error'} for p in plans]
    queries[0].update(pages=[0], boundary='latest_board_probe')
    holds = [{'institution_id': 'nh_central', 'url': probe.inventory.page_url(
        'nh_central', config, p['term'], 1, '2025-11-09', '2026-11-08', listing_url=p['listing_url']),
        'error': 'saved DNS failure'} for p in plans[1:]]
    return {'as_of': '2026-11-08', 'window': {'start': '2025-11-09', 'end': '2026-11-08', 'days': 365},
            'query_policy': 'independent_v1', 'institutions': [{'institution_id': 'nh_central',
            'status': 'source_error', 'queries': queries}], 'holds': holds}


def empty_response(url):
    term = parse_qs(urlsplit(url).query, keep_blank_values=True)['searchWrd'][0]
    html = small(0, True)
    if '/bid/' in url:
        html = html.replace('/notice/notice', '/bid/bid').replace('000000000012', '000000000019')
    html = html.replace('name="searchWrd" value=""', 'name="searchWrd" value="'+term+'"')
    if term: html = html.replace('<option value="1">', '<option value="1" selected>')
    return html.encode()


def paginated_saved():
    report = saved()
    config = probe.inventory.boards.load_configs(include_pending=True)['nh_central']
    first = report['institutions'][0]['queries'][0]
    url = probe.inventory.page_url('nh_central', config, '', 1, report['window']['start'],
                                    report['window']['end'], listing_url=first['listing_url'])
    html = empty_response(url).decode()
    report['receipts'] = [{'institution_id': 'nh_central', 'url': url, 'html': html,
        'sha256': hashlib.sha256(html.encode()).hexdigest(), 'page': 1, 'row_count': 0}]
    def first_page(url):
        term = parse_qs(urlsplit(url).query, keep_blank_values=True)['searchWrd'][0]
        if '/bid/' in url and term == '펀드':
            return fixture('bid', total=11, term=term).replace('2099.03.04', '2026.10.12').encode()
        return empty_response(url)
    progress = None
    for _ in range(4): progress = probe.diagnose(report, fetch=first_page, resume=progress)
    return report, progress


class FailedInventoryDiagnosticTests(unittest.TestCase):
    def test_only_two_failed_queries_are_selected_healthy_query_untouched(self):
        report = saved(); before = copy.deepcopy(report)
        plan = probe.failure_plan(report)
        self.assertEqual(plan['failed_queries'], 7)
        self.assertEqual(plan['unprobed_queries'], 5)
        self.assertEqual([r['term'] for r in plan['requests']], ['운용사', '펀드'])
        self.assertEqual(report, before)

    def test_recovered_response_is_parsed_without_changing_audit_or_approving_business(self):
        report = saved(); before = copy.deepcopy(report); calls = []
        def fetch(url):
            term = parse_qs(urlsplit(url).query)['searchWrd'][0]; calls.append(term)
            return small(0, True).replace('name="searchWrd" value=""', 'name="searchWrd" value="'+term+'"').replace('<option value="1">', '<option value="1" selected>').encode()
        result = probe.diagnose(report, fetch=fetch)
        self.assertEqual(calls, ['운용사', '펀드'])
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(all(r['row_count'] == 0 and len(r['sha256']) == 64 for r in result['results']))
        self.assertFalse(result['audit_recovered']); self.assertFalse(result['publication'])
        self.assertEqual(result['original_audit_holds'], before['holds'])
        self.assertEqual(report, before)

    def test_first_outage_stops_other_query_attempts(self):
        fetch = Mock(side_effect=OSError('DNS still unavailable'))
        result = probe.diagnose(saved(), fetch=fetch)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['attempted_queries'], 1)
        self.assertEqual(result['unprobed_queries'], 6)

    def test_resume_reuses_verified_bytes_and_finishes_without_duplicate_requests(self):
        report = saved(); calls = []
        def fetch(url):
            self.assertNotIn(url, calls); calls.append(url)
            return empty_response(url)
        first = probe.diagnose(report, fetch=fetch)
        second = probe.diagnose(report, fetch=fetch, resume=first)
        self.assertEqual(second['reused_queries'], 2)
        self.assertEqual(second['new_queries'], 2)
        self.assertEqual(second['unprobed_queries'], 3)
        third = probe.diagnose(report, fetch=fetch, resume=second)
        final = probe.diagnose(report, fetch=fetch, resume=third)
        no_network = Mock(side_effect=AssertionError('completed requests must not repeat'))
        repeated = probe.diagnose(report, fetch=no_network, resume=final)
        self.assertEqual(len(calls), 7)
        self.assertEqual(final['new_queries'], 1)
        self.assertEqual(repeated['new_queries'], 0)
        self.assertEqual(repeated['unprobed_queries'], 0)
        self.assertEqual(repeated['results'], final['results'])
        self.assertFalse(repeated['audit_recovered'])
        no_network.assert_not_called()

    def test_changed_response_or_failed_progress_cannot_be_retried_via_resume(self):
        report = saved(); prior = probe.diagnose(report, fetch=empty_response)
        for mutate in [lambda p: p.update(status='error'),
                       lambda p: p['results'][0].update(sha256='0'*64),
                       lambda p: p['results'].reverse(),
                       lambda p: p.update(inventory_sha256='0'*64),
                       lambda p: p['results'][0].update(row_count=10)]:
            bad = copy.deepcopy(prior); mutate(bad); fetch = Mock()
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                probe.diagnose(report, fetch=fetch, resume=bad)
            fetch.assert_not_called()

    def test_invalid_or_unobserved_targets_fail_before_http(self):
        mutations = [lambda r: r['holds'][0].update(url='https://evil.invalid/'),
                     lambda r: r['institutions'][0]['queries'][1].update(term='manual'),
                     lambda r: r['institutions'][0]['queries'][1].update(pages=[1]),
                     lambda r: r['window'].update(start='2023-01-01'),
                     lambda r: r['holds'].append(dict(r['holds'][0]))]
        for mutate in mutations:
            report = saved(); mutate(report); fetch = Mock()
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                probe.diagnose(report, fetch=fetch)
            fetch.assert_not_called()
        for limit in (0, 3, True):
            with self.assertRaises(ValueError): probe.failure_plan(saved(), limit=limit)

    def test_incomplete_html_is_failure_not_zero_notices(self):
        result = probe.diagnose(saved(), fetch=lambda _: b'<html>truncated')
        self.assertEqual(result['status'], 'error')
        self.assertNotIn('row_count', result['results'][0])
        self.assertEqual(hashlib.sha256(base64.b64decode(result['results'][0]['raw_base64'])).hexdigest(),
                         result['results'][0]['sha256'])

    def test_followup_is_discovered_from_cached_pager_and_complete_replay_is_zero_http(self):
        report, diagnostic = paginated_saved(); calls = []
        def fetch(url):
            calls.append(url)
            self.assertEqual(parse_qs(urlsplit(url).query)['pageIndex'], ['2'])
            self.assertIn('/bid/', url)
            return fixture('bid', page=2, total=11, term='펀드').replace('2099.03.04', '2026.10.12').encode()
        plan = probe.recover_boundaries(report, diagnostic, fetch=Mock(), plan_only=True)
        self.assertEqual(len(plan['pending_urls']), 1)
        self.assertEqual(plan['new_queries'], 0)
        result = probe.recover_boundaries(report, diagnostic, fetch=fetch)
        self.assertEqual(len(calls), 1)
        self.assertTrue(result['nh_listing_boundaries_complete'])
        self.assertFalse(result['audit_recovered']); self.assertFalse(result['archive_comparison_performed'])
        never = Mock(side_effect=AssertionError('no repeated source HTTP'))
        repeated = probe.recover_boundaries(report, result, fetch=never)
        never.assert_not_called()
        self.assertEqual(repeated['new_queries'], 0)
        self.assertEqual(repeated['followups'], result['followups'])

    def test_followup_changed_pagination_and_source_outage_remain_failures(self):
        report, diagnostic = paginated_saved()
        for fetch in [Mock(side_effect=OSError('still unavailable')),
                      lambda _: fixture('bid', page=2, total=12, term='펀드').replace('2099.03.04', '2026.10.12').encode()]:
            failed = probe.recover_boundaries(report, diagnostic, fetch=fetch)
            self.assertEqual(failed['status'], 'error')
            self.assertEqual(failed['new_queries'], 1)
            self.assertFalse(failed['nh_listing_boundaries_complete'])
            never = Mock()
            with self.assertRaises(ValueError): probe.recover_boundaries(report, failed, fetch=never)
            never.assert_not_called()

    def test_followup_does_not_fetch_when_healthy_receipt_or_diagnostic_is_changed(self):
        report, diagnostic = paginated_saved(); report['receipts'][0]['sha256'] = '0'*64
        never = Mock()
        with self.assertRaises(ValueError): probe.recover_boundaries(report, diagnostic, fetch=never)
        never.assert_not_called()


if __name__ == '__main__':
    unittest.main()
