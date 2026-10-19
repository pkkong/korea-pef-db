"""Legacy product links require no sibling runtime or network access."""
import unittest
from unittest.mock import patch
from services.newsletter.web.app import app


class ServiceLinkTests(unittest.TestCase):
    def test_legacy_links_preserve_paths_and_queries(self):
        routes = {
            '/samples/lp/index.html': 'https://kpef-lp.vercel.app/index.html',
            '/samples/lp/program-example.html': 'https://kpef-lp.vercel.app/program-example.html',
            '/admin/lp': 'https://kpef-lp.vercel.app/review.html',
            '/gps.html': 'https://kpef-gp.vercel.app/gps.html',
            '/gp-2.html': 'https://kpef-gp.vercel.app/gp-2.html',
            '/person-47.html': 'https://kpef-gp.vercel.app/person-47.html',
            '/market.html': 'https://kpef-gp.vercel.app/market.html',
            '/downloads/gp-ranking-datapack-2025ye.xlsx': 'https://kpef-gp.vercel.app/downloads/gp-ranking-datapack-2025ye.xlsx',
        }
        with patch('urllib.request.urlopen', side_effect=AssertionError('no sibling data fetch')):
            for path, target in routes.items():
                with self.subTest(path=path):
                    response = app.test_client().get(path + '?refresh=1')
                    self.assertEqual(response.status_code, 307)
                    self.assertEqual(response.headers['Location'], target + '?refresh=1')

    def test_independent_origins_can_be_configured(self):
        with patch.dict('os.environ', {'LP_PUBLIC_URL': 'https://lp.example', 'GP_PUBLIC_URL': 'https://gp.example'}):
            self.assertEqual(app.test_client().get('/gps.html').headers['Location'], 'https://gp.example/gps.html')
            self.assertEqual(app.test_client().get('/lp-notices.html').headers['Location'], 'https://lp.example/')
