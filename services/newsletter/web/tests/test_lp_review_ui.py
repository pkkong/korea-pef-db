import unittest
from unittest.mock import patch
from services.newsletter.web.app import app

class ReviewUITests(unittest.TestCase):
 def test_login_free_read_only_page(self):
  with patch('services.newsletter.web.lp_review_ui.fetch_lp_program_page',return_value={'page_html':'<h1>공고 검토</h1>','run_id':'test'}):
   r=app.test_client().get('/admin/lp')
  self.assertEqual(r.status_code,200)
  self.assertEqual(r.headers['Cache-Control'],'no-store')
  self.assertIn('noindex',r.headers['X-Robots-Tag'])
  self.assertNotIn('로그인',r.get_data(as_text=True))
 def test_missing_data_does_not_expose_private_fallback(self):
  with patch('services.newsletter.web.lp_review_ui.fetch_lp_program_page',side_effect=RuntimeError('PRIVATE SENTINEL')):
   r=app.test_client().get('/admin/lp')
  self.assertEqual(r.status_code,503)
  self.assertNotIn(b'PRIVATE SENTINEL',r.data)
if __name__=='__main__':unittest.main()
