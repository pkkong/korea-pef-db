import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.parse import parse_qs, urlsplit

from scripts import inspect_lp_remaining_boards as inspection


class RecoveryDiagnosticTests(unittest.TestCase):
    def test_targets_only_configured_first_pages(self):
        configs = inspection.load_configs()
        targets = list(inspection.diagnostic_targets(configs))
        self.assertEqual([r[0] for r in targets], ['geps', 'pck_pension', 'pck_pension'])
        for institution, config, url in targets:
            q = parse_qs(urlsplit(url).query)
            self.assertEqual(q[config['page_param']], ['1'])
            self.assertIn(q[config['search_param']][0], configs[institution]['searches'][:2])

    def test_pck_kamco_profile_uses_only_registered_board_first_pages(self):
        configs = inspection.load_configs()
        targets = list(inspection.diagnostic_targets(configs, 'pck_kamco_recovery'))
        self.assertEqual([r[0] for r in targets], ['pck_pension', 'pck_pension', 'kamco'])
        for institution, config, url in targets:
            self.assertEqual(parse_qs(urlsplit(url).query)[config['page_param']], ['1'])

    def test_dns_probe_is_bounded_and_never_exposes_stderr(self):
        with patch.object(inspection.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 1, '', 'private diagnostics')
            result = inspection.dns_observation('www.geps.or.kr', 2)
            self.assertEqual(result['status'], 'resolver_error')
            self.assertNotIn('private', str(result))
            self.assertEqual(run.call_args.kwargs['timeout'], 5)
            run.side_effect = subprocess.TimeoutExpired('resolver', 5)
            self.assertEqual(inspection.dns_observation('www.geps.or.kr', 0)['status'], 'timeout')

    def test_failures_are_retained_and_exit_unsuccessfully(self):
        session = MagicMock()
        session.side_effect = TimeoutError('official request timed out')
        session.dns_ipv4_fetches = 0
        with tempfile.TemporaryDirectory() as folder, patch.object(inspection, 'Session', return_value=session), \
                patch.object(inspection, 'dns_observation', return_value={'status': 'timeout'}):
            with self.assertRaises(SystemExit):
                inspection.inspect_recovery(Path(folder))
            report = json.loads((Path(folder) / 'index.json').read_text())
            self.assertEqual(len(report['holds']), 3)
            self.assertEqual(session.call_count, 3)


if __name__ == '__main__':
    unittest.main()
