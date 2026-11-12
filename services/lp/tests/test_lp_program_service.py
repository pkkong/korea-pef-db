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


class ProgramListPresentation(unittest.TestCase):
    """List wording and order shown to readers; stored statuses stay unchanged."""
    def program(self, pid, status, inst, name, deadline=None, event='2026-10-01', label=None):
        return {'id': pid, 'institution_id': inst, 'institution_name': name, 'title': pid, 'asset_scope': 'PE',
                'status': status, 'deadline': deadline, 'commitment_label': label, 'selected_gps': [],
                'events': [{'date': event, 'type': '모집 공고', 'title': pid, 'url': 'https://official.example/' + pid}]}

    def render(self, programs):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            data = {'as_of': '2026-11-12', 'programs': programs}
            before = copy.deepcopy(data)
            build(data, out)
            self.assertEqual([p['institution_name'] for p in data['programs']],
                             [p['institution_name'] for p in before['programs']])
            return {p.name: p.read_text() for p in out.glob('*.html')}

    def test_open_first_year_shown_and_status_names_unified(self):
        pages = self.render([
            self.program('recent', '서류심사 결과', 'a', 'A', '2026-10-01', event='2026-11-10'),
            self.program('open', '접수 중', 'b', 'B', '2026-11-16T15:00:00+09:00', event='2026-11-01'),
            self.program('old', '접수 마감', 'c', 'C', '2023-08-14T16:00:00+09:00', event='2023-07-20'),
            self.program('done', '선정 결과 발표', 'd', 'D', '2026-03-06', event='2026-04-10'),
        ])
        index = pages['index.html']
        self.assertLess(index.index('program-open.html'), index.index('program-recent.html'))
        self.assertIn('2023.08.14 마감', index)
        self.assertIn('11.16 마감<span class="program-dday" data-lp-dday="2026-11-16">', index)
        self.assertIn('<span class="program-status open">접수 중', index)
        self.assertNotIn('서류심사 결과</', index); self.assertNotIn('선정 결과 발표', index)
        options = index.split('aria-label="진행 상태">', 1)[1].split('</select>', 1)[0]
        self.assertEqual(options.count('<option>'), 4)
        self.assertLess(options.index('접수 중'), options.index('1차 심사 결과'))
        self.assertLess(options.index('1차 심사 결과'), options.index('선정 완료'))
        self.assertIn('class="badge">1차 심사 결과<', pages['program-recent.html'])

    def test_one_institution_name_and_unallocated_total_hidden(self):
        pages = self.render([
            self.program('x', '접수 마감', 'pck', '총회연금재단', '2026-10-29'),
            self.program('y', '접수 마감', 'pck', '대한예수교장로회 총회연금재단', '2026-07-16',
                         label='전체 대체투자 최대 1,000억원 · PE 배정 미확인'),
        ])
        index = pages['index.html']
        self.assertNotIn('대한예수교장로회', index)
        self.assertNotIn('대한예수교장로회', pages['program-y.html'])
        self.assertNotIn('PE 배정 미확인', index)
        self.assertIn('<h1>총회연금재단</h1>', pages['institution-pck.html'])
