"""Boot real public apps without the repository or sibling services present."""
from __future__ import annotations
import os
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DETACHED_CHECK = r'''
import importlib, importlib.abc, json, os, socket, sys, urllib.request
service = sys.argv[1]
adapters = {"newsletter": {"newsletter_data", "newsletter_ui"}, "lp": {"lp_program_data", "lp_review_ui"}, "gp": {"gp_public_data"}}
foreign = set().union(*(names for owner, names in adapters.items() if owner != service))
class NoForeignService(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "services":
            raise ModuleNotFoundError("Repository is not present", name=fullname)
        if fullname.split(".")[0] in foreign:
            raise RuntimeError("Foreign service import: " + fullname)
sys.meta_path.insert(0, NoForeignService())
def no_network(*args, **kwargs):
    raise AssertionError("Detached runtime attempted network access")
socket.create_connection = no_network
urllib.request.urlopen = no_network
os.environ["NEWSLETTER_PUBLIC_URL"] = "https://brief.example.test"
os.environ["LP_PUBLIC_URL"] = "https://lp.example.test"
os.environ["GP_PUBLIC_URL"] = "https://gp.example.test"
fixture_html = """<!doctype html><html><head>
<link rel="stylesheet" href="https://kpef-newsletter.vercel.app/assets/service.css">
<script src="https://kpef-newsletter.vercel.app/assets/service.js"></script>
</head><body>Detached service fixture</body></html>"""
if service == "newsletter":
    data = importlib.import_module("newsletter_data")
    data.load_archive = lambda **kwargs: ([{"reportDate": "2026-10-19", "articles": [{"id": "isolated-article", "title": "Detached newsletter fixture", "url": "https://example.test/article", "section": "Market", "source": "Fixture", "summaryLines": []}]}], "supabase")
elif service == "lp":
    data = importlib.import_module("lp_program_data")
    data.fetch_lp_program_page = lambda filename: {"page_html": fixture_html, "run_id": "isolated-lp", "page_name": filename}
else:
    data = importlib.import_module("gp_public_data")
    data.fetch_active_gp_page = lambda filename: {"page_html": fixture_html, "snapshot_id": "isolated-gp", "reporting_period": "2025Q4", "as_of_date": "2025-12-31", "source_sha256": "f" * 64}
module = importlib.import_module("app")
client = module.app.test_client()
for path in ["/", "/health.json", "/assets/service.css", "/assets/service.js"]:
    response = client.get(path)
    assert response.status_code == 200, (service, path, response.status_code, response.get_data(as_text=True)[:300])
health = client.get("/health.json").get_json()
assert health["service"] == service, health
html = client.get("/").get_data(as_text=True)
assert "https://kpef-newsletter.vercel.app/assets/" not in html, "Remote newsletter asset dependency"
if service == "newsletter":
    for old, target in [("/gps.html", "https://gp.example.test"), ("/samples/lp/index.html", "https://lp.example.test")]:
        response = client.get(old)
        assert response.status_code in {301, 302, 307, 308}, (old, response.status_code)
        assert response.headers["Location"].startswith(target), response.headers["Location"]
print(json.dumps({"service": service, "status": "ok"}))
'''

class ServiceRuntimeIsolationTests(unittest.TestCase):
    def check_detached(self, service: str) -> None:
        with tempfile.TemporaryDirectory(prefix=f"kpef-detached-{service}-") as temporary:
            root = Path(temporary)
            web = REPO_ROOT / "services" / service / "web"
            # Exactly one runtime plus static shared assets. No sibling code.
            for path in web.iterdir():
                if path.is_file() and path.suffix in {".py", ".json", ".txt"}:
                    shutil.copy2(path, root / path.name)
                elif path.is_dir() and path.name == "downloads":
                    shutil.copytree(path, root / path.name)
            shutil.copy2(REPO_ROOT / "services/shared/web/service_assets.py", root / "service_assets.py")
            environment = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "HOME", "TMPDIR"}}
            third_party = importlib.util.find_spec("flask")
            dependency_root = Path(third_party.origin).resolve().parent.parent if third_party and third_party.origin else None
            python_paths = [str(root)]
            if dependency_root and not dependency_root.is_relative_to(REPO_ROOT):
                python_paths.append(str(dependency_root))
            environment["PYTHONPATH"] = os.pathsep.join(python_paths)
            result = subprocess.run([sys.executable, "-c", DETACHED_CHECK, service], cwd=root, env=environment, capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('"status": "ok"', result.stdout)

    def test_newsletter_boots_without_lp_or_gp(self) -> None:
        self.check_detached("newsletter")

    def test_lp_boots_without_newsletter_or_gp(self) -> None:
        self.check_detached("lp")

    def test_gp_boots_without_newsletter_or_lp(self) -> None:
        self.check_detached("gp")

if __name__ == "__main__":
    unittest.main()
