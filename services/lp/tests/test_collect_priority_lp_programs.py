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
