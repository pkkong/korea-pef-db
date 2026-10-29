"""Workflow trust and isolation contracts, without Actions or DB calls."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2] / '.github/workflows'


class MaintenanceWorkflowTests(unittest.TestCase):
    def test_completed_trigger_is_narrow_and_uses_trusted_source(self):
        text = (ROOT / 'maintain-lp-report-storage.yml').read_text()
        self.assertIn('workflows: [Collect LP programs, Recover LP publication]', text)
        self.assertIn('types: [completed]', text)
        for guard in ["github.event_name == 'workflow_run'", 'head_repository.full_name == github.repository',
                      "head_branch == 'main'", "fromJSON('[\"schedule\",\"workflow_dispatch\"]')",
                      "fromJSON('[\"Collect LP programs\",\"Recover LP publication\"]')"]:
            self.assertIn(guard, text)
        self.assertNotIn('workflow_run.conclusion', text)
        self.assertIn('actions/checkout@v6\n        with:\n          ref: main', text)
        self.assertNotIn('ref: ${{', text)
        self.assertIn('permissions:\n  contents: read', text)
        self.assertIn('group: lp-program-collection\n  cancel-in-progress: false', text)

    def test_automatic_small_batch_and_manual_defaults_are_separate(self):
        text = (ROOT / 'maintain-lp-report-storage.yml').read_text()
        self.assertIn("&& 'archive' || inputs.mode || 'inspect'", text)
        self.assertIn("&& '5' || inputs.limit || '50'", text)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.run_id || ''", text)
        self.assertIn('timeout-minutes: 45', text)
        self.assertIn('args+=(--reuse-space)', text)
        self.assertIn('"${args[@]}"', text)
        self.assertIn("response.headers.get('X-LP-Run')==published['run_id']", text)
        self.assertIn("response.headers.get('X-LP-Data-Source')=='supabase'", text)

    def test_publication_jobs_keep_outage_signals_without_archive_work(self):
        for filename in ['collect-kgrowth-programs.yml', 'recover-lp-publication.yml']:
            text = (ROOT / filename).read_text()
            with self.subTest(filename=filename):
                self.assertNotIn('archive_lp_collection_reports.py', text)
                self.assertNotIn('report-maintenance.json', text)
                self.assertIn('raise SystemExit', text)
                self.assertIn('if: always()', text)
                self.assertIn('timeout-minutes: 25', text)


if __name__ == '__main__':
    unittest.main()
