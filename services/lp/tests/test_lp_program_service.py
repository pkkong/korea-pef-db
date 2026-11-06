"""Prevent result attribution across programs and fabricated completion."""
import copy
import tempfile
import unittest
from pathlib import Path
from html.parser import HTMLParser
from services.lp.src.lp_program_service import validate, build, assert_selected_gp_history

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]
    def handle_starttag(self, tag, attrs):
        if tag=='a': self.links.extend(v for k,v in attrs if k=='href' and not v.startswith('https://'))

class ProgramContracts(unittest.TestCase):
    def setUp(self):
        self.data={'as_of':'2026-09-13','programs':[{'id':'fund-2026','institution_id':'fund','institution_name':'Fund','title':'PE selection','asset_scope':'PE','status':'선정 완료','events':[{'date':'2026-08-25','type':'최종 선정','title':'Result','url':'https://official.example/result'}],'selected_gps':[{'name':'GP','master_id':'240','asset_scope':'PE','source_url':'https://official.example/result'}]}]}
    def test_unrelated_result_cannot_support_selected_gp(self):
        self.data['programs'][0]['selected_gps'][0]['source_url']='https://official.example/other-program'
        with self.assertRaises(ValueError): validate(self.data)
    def test_completed_without_selection_rejected(self):
        self.data['programs'][0]['selected_gps']=[]
        with self.assertRaises(ValueError): validate(self.data)
    def test_future_event_rejected(self):
        self.data['programs'][0]['events'][0]['date']='2026-09-14'
        with self.assertRaises(ValueError): validate(self.data)
    def test_program_institution_gp_links_resolve(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder); build(copy.deepcopy(self.data),out)
            for page in out.glob('*.html'):
                parser=Links();parser.feed(page.read_text())
                for href in parser.links:self.assertTrue((out/href).is_file(),f'{page.name}: {href}')
            self.assertIn('program-fund-2026.html',(out/'selected-gp-240.html').read_text())

    def test_preservation_allows_validated_additions_without_replacing_history(self):
        old=copy.deepcopy(self.data['programs']);new=copy.deepcopy(old)
        new[0]['selected_gps'].append({'id':'source-derived','name':'New sourced GP','asset_scope':'PE',
                                     'source_url':old[0]['events'][0]['url']})
        validate({'as_of':self.data['as_of'],'programs':new})
        assert_selected_gp_history(old,new)
        old[0]['selected_gps']=[]
        assert_selected_gp_history(old,new)

    def test_preservation_rejects_changed_or_removed_name_source_and_scope(self):
        old=copy.deepcopy(self.data['programs'])
        for key in ('name','source_url','asset_scope','master_id'):
            new=copy.deepcopy(old);new[0]['selected_gps'][0][key]='changed'
            with self.subTest(key=key),self.assertRaises(ValueError):assert_selected_gp_history(old,new)
        new=copy.deepcopy(old);new[0]['selected_gps']=[]
        with self.assertRaises(ValueError):assert_selected_gp_history(old,new)
        with self.assertRaises(ValueError):assert_selected_gp_history(old,[])

if __name__=='__main__': unittest.main()
