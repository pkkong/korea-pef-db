import unittest
from unittest.mock import patch
from services.newsletter.web.app import app

class LPReaderContracts(unittest.TestCase):
    def test_published_page_is_used(self):
        with patch('services.newsletter.web.lp_program_data.fetch_lp_program_page',return_value={'page_html':'new page','run_id':'abc'}):
            r=app.test_client().get('/samples/lp/index.html')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers['X-LP-Data-Source'],'supabase')
    def test_error_never_falls_back_to_old_sample(self):
        with patch('services.newsletter.web.lp_program_data.fetch_lp_program_page',side_effect=TimeoutError):
            r=app.test_client().get('/samples/lp/index.html')
        self.assertEqual(r.status_code,503)
    def test_missing_page_is_404(self):
        with patch('services.newsletter.web.lp_program_data.fetch_lp_program_page',return_value=None):
            r=app.test_client().get('/samples/lp/index.html')
        self.assertEqual(r.status_code,404)

if __name__=='__main__':unittest.main()
