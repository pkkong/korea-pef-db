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
 def test_new_result_shows_both_rounds_for_review_without_approving_gp(self):
  notice={'source_id':'9999','title':'【선정결과】「부산 미래산업 전환펀드 2호」 위탁운용사 선정 결과',
          'body':'운용사명\n새운용사','date':'2026-10-02','url':'https://www.kgrowth.or.kr/notice_view.asp?idx=9999',
          'attachment_hashes':{}}
  programs=[{'id':'kgrowth-2026-busan-2','title':'부산 최초','events':[], 'selected_gps':[]},
            {'id':'kgrowth-2026-busan-2-reopen','title':'부산 재공고','events':[], 'selected_gps':[]}]
  html=render_review({'as_of':'2026-10-02','programs':programs},{'notices':[notice]},{'tracked_notices':[]})
  self.assertIn('새 단계 연결 후보',html)
  self.assertIn('차수 확인 필요',html)
  self.assertIn('program-kgrowth-2026-busan-2.html',html)
  self.assertIn('program-kgrowth-2026-busan-2-reopen.html',html)
  self.assertIn('기존 사업 연결 후보',html)
  self.assertNotIn('선정 GP</th>',html)
 def test_priority_institution_result_is_shown_as_candidate_only(self):
  url='https://www.ktcu.or.kr/PPW-CSB-000101/62000'
  notice={'source_id':'62000','institution_id':'ktcu','title':'2026년 블라인드 PEF 선정 결과',
          'body':'미검토 운용사', 'date':'2026-10-30','url':url}
  program={'id':'ktcu-2026-blind-pef','title':'교직원공제회 블라인드 PEF','events':[],'selected_gps':[]}
  suggestion={'source_id':'62000','title':notice['title'],'date':notice['date'],'url':url,
              'stage':'최종 선정','programs':[{'id':program['id'],'title':program['title']}]}
  data={'as_of':'2026-10-30','programs':[program],'priority_notices':[notice],
        'link_suggestions':[suggestion]}
  html=render_review(data,{'notices':[]},{'priority_notices':[]})
  self.assertIn('새 단계 연결 후보',html)
  self.assertIn('program-ktcu-2026-blind-pef.html',html)
  self.assertIn('기존 사업 연결 후보',html)
  self.assertNotIn('선정 GP</th>',html)
if __name__=='__main__':unittest.main()
