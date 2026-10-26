"""LP runtime independence, public-link adaptation and failure isolation."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

web = importlib.import_module('services.lp.web.app')
reader = importlib.import_module('services.lp.web.lp_program_data')


class LPWebRuntimeTests(unittest.TestCase):
    def setUp(self):
        web.app.config['TESTING'] = True
        self.client = web.app.test_client()
        web._PAGE_CACHE.clear()
        self.page = {'page_html': '<h1>출자사업</h1>', 'run_id': 'lp-test-run'}

    def tearDown(self):
        web._PAGE_CACHE.clear()

    def test_only_own_pages_and_assets_are_needed(self):
        with patch.object(web, 'fetch_lp_program_page', return_value=self.page) as fetch:
            for path in ('/', '/index.html', '/program-sample.html', '/samples/lp/program-sample.html'):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['X-LP-Run'], 'lp-test-run')
                self.assertEqual(response.headers['X-Robots-Tag'], 'index, follow')
            self.assertEqual(self.client.get('/health.json').json['service'], 'lp')
            self.assertEqual(self.client.get('/assets/service.css').status_code, 200)
            self.assertEqual(self.client.get('/assets/service.js').status_code, 200)
            self.assertEqual(fetch.call_count, 2)

    def test_review_and_error_responses_stay_out_of_search(self):
        with patch.object(web, 'fetch_lp_program_page', return_value=self.page):
            for path in ('/review.html', '/samples/lp/review.html'):
                response = self.client.get(path)
                self.assertIn('noindex', response.headers['X-Robots-Tag'])
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
                self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        with patch.object(web, 'fetch_lp_program_page', return_value=None):
            for path in ('/program-missing.html', '/unknown.html', '/admin/missing'):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertIn('noindex', response.headers['X-Robots-Tag'])
        with patch.object(web, 'fetch_lp_program_page', side_effect=TimeoutError):
            self.assertIn('noindex', self.client.get('/').headers['X-Robots-Tag'])
        self.assertIn('noindex', self.client.post('/review.html').headers['X-Robots-Tag'])

    def test_robots_and_assets_do_not_require_the_database(self):
        with patch.object(web, 'fetch_lp_program_page', side_effect=TimeoutError) as fetch:
            response = self.client.get('/robots.txt')
            self.assertEqual(response.status_code, 200)
            self.assertIn('Allow: /\n', response.text)
            for path in ('/review.html', '/samples/lp/review.html', '/admin/', '/health.json'):
                self.assertIn('Disallow: ' + path + '\n', response.text)
            self.assertEqual(self.client.get('/assets/service.css').status_code, 200)
            fetch.assert_not_called()

    def test_reader_failure_is_contained_and_assets_keep_working(self):
        with patch.object(web, 'fetch_lp_program_page', side_effect=RuntimeError('PRIVATE SENTINEL')):
            response = self.client.get('/')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('SENTINEL', response.text)
            self.assertEqual(self.client.get('/health.json').status_code, 503)
            self.assertEqual(self.client.get('/assets/service.css').status_code, 200)
            self.assertEqual(self.client.get('/assets/service.js').status_code, 200)

    def test_stale_last_good_is_kept_only_after_failed_refresh(self):
        with patch.object(web, 'fetch_lp_program_page', return_value=self.page):
            self.assertEqual(self.client.get('/').status_code, 200)
        with patch.object(web, 'fetch_lp_program_page', side_effect=TimeoutError):
            response = self.client.get('/?refresh=1')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['X-LP-Cache'], 'stale')
        with patch.object(web, 'fetch_lp_program_page', return_value=None):
            self.assertEqual(self.client.get('/?refresh=1').status_code, 404)
        with patch.object(web, 'fetch_lp_program_page', side_effect=TimeoutError):
            self.assertEqual(self.client.get('/').status_code, 503)

    def test_new_publication_discards_old_cached_pages(self):
        with patch.object(web, 'fetch_lp_program_page', return_value=self.page):
            self.client.get('/')
        with patch.object(web, 'fetch_lp_program_page', return_value={**self.page, 'run_id': 'next-run'}):
            self.client.get('/program-next.html')
        self.assertNotIn('index.html', web._PAGE_CACHE)

    def test_known_links_are_rewritten_but_evidence_is_unchanged(self):
        html = '''<link rel="stylesheet" href="https://kpef-newsletter.vercel.app/assets/service.css">
<a href="https://kpef-newsletter.vercel.app/">브리프</a>
<a href="https://kpef-newsletter.vercel.app/gps.html">GP</a>
<a href="https://kpef-gp.vercel.app/">GP 독립</a>
<a href="/samples/lp/program-example.html">사업</a>
<a href="https://www.ktcu.or.kr/gps.html">기관 원문</a>
<a href="https://www.ktcu.or.kr/?a=1&amp;b=2">공고</a>'''
        with patch.dict(os.environ, {'NEWSLETTER_PUBLIC_URL': 'https://brief.example', 'GP_PUBLIC_URL': 'https://gp.example'}):
            result = web.rewrite_navigation(html)
        self.assertIn('href="/assets/service.css"', result)
        self.assertIn('href="https://brief.example/"', result)
        self.assertIn('href="https://gp.example/"', result)
        self.assertIn('href="/program-example.html"', result)
        self.assertIn('href="https://www.ktcu.or.kr/gps.html"', result)
        self.assertIn('href="https://www.ktcu.or.kr/?a=1&amp;b=2"', result)

    def test_review_is_read_only_and_legacy_route_redirects(self):
        self.assertEqual(self.client.get('/admin/lp').location, '/review.html')
        with patch.object(web, 'fetch_lp_program_page', return_value=self.page):
            response = self.client.get('/review.html')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.post('/review.html').status_code, 405)
        self.assertEqual(self.client.get('/unknown.html').status_code, 404)
        self.assertEqual(self.client.get('/gps.html').status_code, 404)

    def test_reader_only_calls_own_rpc_with_public_key(self):
        from io import BytesIO
        with patch.dict(os.environ, {'SUPABASE_URL': 'https://db.example', 'SUPABASE_PUBLISHABLE_KEY': 'public-test-key'}):
            with patch.object(reader, 'urlopen', return_value=BytesIO(json.dumps(self.page).encode())) as fetch:
                self.assertEqual(reader.fetch_lp_program_page('index.html'), self.page)
        req = fetch.call_args.args[0]
        self.assertEqual(req.full_url, 'https://db.example/rest/v1/rpc/lp_program_page')
        self.assertEqual(json.loads(req.data), {'page_name': 'index.html'})
        with patch.object(reader, 'urlopen') as fetch:
            self.assertIsNone(reader.fetch_lp_program_page('../index.html'))
            fetch.assert_not_called()

    def test_detached_flat_deploy_imports_without_other_products(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name in ('app.py', 'lp_program_data.py'):
                shutil.copy(root / 'services/lp/web' / name, target / name)
            shutil.copy(root / 'services/shared/web/service_assets.py', target / 'service_assets.py')
            code = '''import sys
import app
assert not any(n.startswith(('services.newsletter','services.gp')) for n in sys.modules)
client = app.app.test_client()
assert client.get('/assets/service.css').status_code == 200
assert client.get('/assets/service.js').status_code == 200
'''
            environment = {k:v for k,v in os.environ.items() if k != 'PYTHONPATH'}
            dependency = importlib.util.find_spec('flask')
            dependency_root = Path(dependency.origin).resolve().parent.parent
            self.assertFalse(dependency_root.is_relative_to(root))
            environment['PYTHONPATH'] = str(target) + os.pathsep + str(dependency_root)
            result = subprocess.run([sys.executable, '-c', code], cwd=directory, capture_output=True, text=True, env=environment)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
