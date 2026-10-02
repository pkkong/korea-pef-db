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
             patch.object(priority, "suggest_kexim", return_value=[]):
            result = priority.load_kexim_collection(self.path, self.now.isoformat())
        self.assertEqual(result["programs"], [{"id": "verified"}])
        self.assertEqual(result["notices"], [{"source_id": "official"}])

    def test_stale_artifact_is_rejected(self):
        self.write(self.now - timedelta(hours=3))
        with self.assertRaisesRegex(ValueError, "current run"):
            priority.load_kexim_collection(self.path, self.now.isoformat())


if __name__ == "__main__":
    unittest.main()
