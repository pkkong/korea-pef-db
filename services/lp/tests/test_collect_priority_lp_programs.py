import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services.lp.src import collect_priority_lp_programs as priority


class MacOSArtifactTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "kexim.json"
        self.now = datetime.now(timezone.utc)

    def write(self, when):
        self.path.write_text(json.dumps({"checked_at": when.isoformat(),
                                         "notices": [{"source_id": "official"}],
                                         "programs": [{"id": "untrusted"}]}))

    def test_current_artifact_is_reprojected_from_notices(self):
        self.write(self.now - timedelta(minutes=2))
        with patch.object(priority, "project_kexim", return_value=([{"id": "verified"}], [])), \
             patch.object(priority, "suggest_kexim", return_value=[]), \
             patch.object(priority, "discover_kexim", return_value=[]):
            result = priority.load_kexim_collection(self.path, self.now.isoformat())
        self.assertEqual(result["programs"], [{"id": "verified"}])
        self.assertEqual(result["notices"], [{"source_id": "official"}])

    def test_ktcu_artifact_is_reprojected_instead_of_trusting_prepared_programs(self):
        self.write(self.now - timedelta(minutes=2))
        seed = {'id': 'ktcu-2026-blind-pef', 'title': 'Existing KTCU program'}
        with patch.object(priority, 'project_ktcu', return_value=([{'id': 'verified-ktcu'}], [])) as project, \
             patch.object(priority, 'suggest_ktcu', return_value=[]), \
             patch.object(priority, 'discover_ktcu', return_value=[{'source_id': 'discovered'}]):
            result = priority.load_ktcu_collection(self.path, self.now.isoformat(), seed)
        project.assert_called_once_with([{'source_id': 'official'}], self.now.isoformat(), seed)
        self.assertEqual(result['programs'], [{'id': 'verified-ktcu'}])
        self.assertEqual(result['discovery_candidates'], [{'source_id': 'discovered'}])

    def test_stale_ktcu_artifact_keeps_an_outage_signal(self):
        self.write(self.now - timedelta(hours=3))
        source = lambda: priority.load_ktcu_collection(self.path, self.now.isoformat(), {'title': 'KTCU'})
        report = priority.collect(checked_at=self.now.isoformat(), collectors={'ktcu': source})
        self.assertIn('current run', report['sources']['ktcu']['error'])
        self.assertEqual(report['sources']['ktcu']['notices'], [])
        self.assertEqual(report['sources']['ktcu']['programs'], [])
        self.assertTrue(report['sources']['ktcu']['holds'])

    def test_stale_artifact_is_rejected(self):
        self.write(self.now - timedelta(hours=3))
        with self.assertRaisesRegex(ValueError, "current run"):
            priority.load_kexim_collection(self.path, self.now.isoformat())

    def test_koreapost_artifact_is_reprojected_and_discovery_retained(self):
        self.write(self.now - timedelta(minutes=2))
        data=json.loads(self.path.read_text())
        coverage={'window_days':365,'date_filter_validation':'echo_confirmed','window_completeness':'not_assessed'}
        data['collection_coverage']=coverage
        self.path.write_text(json.dumps(data))
        discovered=[{"institution_id":"koreapost","source_id":"0041:352"}]
        with patch.object(priority, "project_post", return_value=([{"id": "reviewed-post"}], [])), \
             patch.object(priority, "suggest_post", return_value=[]), \
             patch.object(priority, "discover_post", return_value=discovered):
            result = priority.load_post_collection(self.path, self.now.isoformat())
        self.assertEqual([{"id": "reviewed-post"}], result["programs"])
        self.assertEqual(discovered, result["discovery_candidates"])
        self.assertEqual(coverage,result['collection_coverage'])


if __name__ == "__main__":
    unittest.main()
