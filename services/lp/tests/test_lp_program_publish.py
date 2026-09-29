import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]/'src'
sys.path.insert(0,str(SRC))
from publish_lp_programs import prepare, document_hash

class PublishContracts(unittest.TestCase):
    def test_identical_document_is_not_versioned_again_for_check_time(self):
        doc = {'body':'same', 'attachment_hashes':{'file':'v1'}, 'checked_at':'first'}
        later = dict(doc, checked_at='later')
        self.assertEqual(document_hash(doc), document_hash(later))
        later['attachment_hashes'] = {'file':'v2'}
        self.assertNotEqual(document_hash(doc), document_hash(later))

    def setUp(self):
        self.data=json.loads((SRC.parents[2]/'data/lp_programs_pilot.json').read_text())
        self.p=next(p for p in self.data['programs'] if p['institution_id']=='kgrowth')
        self.report={'checked_at':'2026-09-21','notices':[{'source_id':'1047','title':'공고','date':'2026-09-21','body':'본문','url':'https://www.kgrowth.or.kr/notice_view.asp?idx=1047'}],'programs':[copy.deepcopy(self.p)]}
    def test_review_preserves_program_and_accepted_fingerprint(self):
        self.data['accepted_notices']=[{'source_id':'1047','sha256':'old'}]
        self.report['accepted_notices']=self.data['accepted_notices']
        self.report['requires_review']=True
        self.report['programs'][0]['title']='UNREVIEWED EDIT'
        result,_=prepare(self.data,self.report)
        self.assertEqual(self.data['accepted_notices'],result['accepted_notices'])
        self.assertNotIn('UNREVIEWED EDIT',[p['title'] for p in result['programs']])

    def test_empty_collection_cannot_erase_pages(self):
        self.report['notices']=[]
        with self.assertRaises(ValueError):prepare(self.data,self.report)
    def test_unreviewed_tracking_survives_publication(self):
        self.report['tracked_notices'] = [{'source_id':'9999','sha256':'new'}]
        self.report['requires_review'] = True
        result,_=prepare(self.data,self.report)
        self.assertEqual(self.report['tracked_notices'], result['tracked_notices'])
    def test_unreviewed_program_cannot_be_published(self):
        self.report['programs'][0]['id']='unreviewed'
        with self.assertRaises(ValueError):prepare(self.data,self.report)
    def test_other_institutions_remain_unchanged(self):
        data,pages=prepare(self.data,self.report)
        before={p['id']:p for p in self.data['programs'] if p['institution_id']!='kgrowth'}
        after={p['id']:p for p in data['programs'] if p['institution_id']!='kgrowth'}
        # Renderer may add page_key to a copy; original input must remain intact.
        for p in after.values():
            for gp in p['selected_gps']:gp.pop('page_key',None)
        self.assertEqual(before,after)
        self.assertEqual(5,len([n for n in pages if n.startswith('program-')]))

if __name__=='__main__':unittest.main()
