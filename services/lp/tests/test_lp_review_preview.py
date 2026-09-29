import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from lp_review_preview import render_review

class PreviewTests(unittest.TestCase):
 def test_only_official_fields_are_exposed_and_markup_is_escaped(self):
  n={'source_id':'1','title':'<script>bad</script>','body':'public body','date':'2026-09-29','url':'https://www.kgrowth.or.kr/notice_view.asp?idx=1'}
  html=render_review({'as_of':'2026-09-29','programs':[],'review_decisions':['PRIVATE ACTOR']},{'notices':[n],'secret':'PRIVATE REPORT'},{'tracked_notices':[]})
  self.assertNotIn('PRIVATE',html);self.assertNotIn('<script>bad',html)
  self.assertIn('&lt;script&gt;',html)
  self.assertNotIn('로그인',html)
 def test_changed_body_has_previous_and_current_evidence(self):
  n={'source_id':'1','title':'공고','body':'new amount','date':'2026-09-29','url':'https://www.kgrowth.or.kr/notice_view.asp?idx=1'}
  old=dict(n,body='old amount')
  html=render_review({'as_of':'2026-09-29','programs':[]},{'notices':[n]},{'tracked_notices':[old]})
  self.assertIn('원문 변경',html);self.assertIn('-old amount',html);self.assertIn('+new amount',html)
if __name__=='__main__':unittest.main()
