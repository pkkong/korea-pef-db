import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_priority_program_comes_from_reprojected_evidence_not_collector_payload(self):
        verified=copy.deepcopy(next(p for p in self.data['programs'] if p['institution_id']=='ktcu'))
        verified['status']='접수 마감'
        self.report['priority_sources']={'ktcu':{'notices':[{'source_id':'61742', 'url':'https://www.ktcu.or.kr/PPW-CSB-000101/61742',
                                                              'date':'2026-09-04','title':'공식 모집','body':'공식 본문'}],
                                                 'programs':[{'id':'unreviewed-ktcu','institution_id':'ktcu'}],
                                                 'holds':[]}}
        with patch('publish_lp_programs.project_ktcu',return_value=([verified],[])):
            data,pages=prepare(self.data,self.report)
        self.assertEqual('접수 마감',next(p for p in data['programs'] if p['id']==verified['id'])['status'])
        self.assertNotIn('unreviewed-ktcu',{p['id'] for p in data['programs']})
        self.assertIn('program-ktcu-2026-blind-pef.html',pages)

    def test_priority_source_failure_keeps_last_published_program(self):
        original=copy.deepcopy(next(p for p in self.data['programs'] if p['institution_id']=='koreapost'))
        self.report['priority_sources']={'koreapost':{'notices':[],'programs':[],
                                                       'holds':[{'program_id':original['id'],'reason':'공식 자료 수집 실패'}]}}
        data,_=prepare(self.data,self.report)
        self.assertEqual(original,next(p for p in data['programs'] if p['id']==original['id']))
        self.assertIn('공식 자료 수집 실패',[hold['reason'] for hold in data['program_holds']])

if __name__=='__main__':unittest.main()
