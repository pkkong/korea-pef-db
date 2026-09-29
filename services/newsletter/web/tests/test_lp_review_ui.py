import os,unittest
from unittest.mock import patch
from services.newsletter.web.app import app

class ReviewUITests(unittest.TestCase):
 def test_shell_never_contains_private_data_or_service_key(self):
  with patch.dict(os.environ,{'SUPABASE_URL':'https://example.supabase.co','SUPABASE_PUBLISHABLE_KEY':'public-key','SUPABASE_SERVICE_ROLE_KEY':'PRIVATE-SENTINEL'}):
   response=app.test_client().get('/admin/lp')
  self.assertEqual(response.status_code,200)
  self.assertEqual(response.headers['Cache-Control'],'no-store')
  self.assertIn('noindex',response.headers['X-Robots-Tag'])
  self.assertNotIn(b'PRIVATE-SENTINEL',response.data)
  self.assertIn(b'public-key',response.data)
 def test_config_does_not_break_out_of_script(self):
  with patch.dict(os.environ,{'SUPABASE_URL':'</script><script>alert(1)</script>'}):
   html=app.test_client().get('/admin/lp').get_data(as_text=True)
  self.assertNotIn('</script><script>alert(1)',html)
if __name__=='__main__':unittest.main()
