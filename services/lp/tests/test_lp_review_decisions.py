import copy
import json
import sys
import unittest
from pathlib import Path
SRC=Path(__file__).resolve().parents[1]/'src'
sys.path.insert(0,str(SRC))
from lp_review_decisions import apply_decisions
from kgrowth_program_review import project,recipes

class ReviewDecisionTests(unittest.TestCase):
 def setUp(self):
  self.notices=json.loads((Path(__file__).parent/'fixtures/kgrowth_kculture.json').read_text())
  self.program=project(recipes()[0],self.notices)
  self.decision={'id':1,'source_id':'1120','action':'approve','evidence':copy.deepcopy(self.notices),'program':self.program}
 def test_approved_program_is_published(self):
  data=apply_decisions({'programs':[]},self.notices,[self.decision])
  self.assertEqual(data['programs'][0]['manual_review_id'],1)
  self.assertEqual(data['review_outcomes'][0]['status'],'published')
 def test_changed_evidence_preserves_previous(self):
  old=copy.deepcopy(self.program);old['title']='existing'
  self.notices[0]['body']='changed'
  data=apply_decisions({'programs':[old]},self.notices,[self.decision])
  self.assertEqual(data['programs'][0]['title'],'existing')
  self.assertEqual(data['review_outcomes'][0]['status'],'needs_review')
 def test_latest_hold_prevents_pending_approval(self):
  hold=dict(self.decision,id=2,action='hold',program=None)
  data=apply_decisions({'programs':[]},self.notices,[self.decision,hold])
  self.assertFalse(data['programs'])
 def test_wrong_event_source_rejected(self):
  self.program['events'][0]['url']='https://other.example'
  data=apply_decisions({'programs':[]},self.notices,[self.decision])
  self.assertFalse(data['programs'])
  self.assertEqual(data['review_outcomes'][0]['status'],'needs_review')
 def test_other_institution_rejected(self):
  self.program['institution_id']='other'
  self.assertFalse(apply_decisions({'programs':[]},self.notices,[self.decision])['programs'])
if __name__=='__main__':unittest.main()
