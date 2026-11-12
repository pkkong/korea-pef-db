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

    def selected(self, pid, inst, name, gp_name, key, master=None, event='2026-09-01'):
        p = self.program(pid, '선정 완료', inst, name, '2026-08-01', event=event)
        url = 'https://official.example/result-' + pid
        p['events'].append({'date': event, 'type': '최종 선정', 'title': 'result', 'url': url})
        p['selected_gps'] = [{'name': gp_name, 'id': key, 'master_id': master, 'source_url': url, 'asset_scope': 'PE'}]
        return p

    def test_source_titles_cleaned_and_identical_names_told_apart(self):
        pages = self.render([
            {**self.program('a', '접수 마감', 'k', 'K', '2026-07-01', event='2026-06-10'), 'title': '같은 공고'},
            {**self.program('b', '접수 마감', 'k', 'K', '2026-10-12', event='2026-09-20'), 'title': '같은 공고'},
            {**self.program('c', '접수 마감', 'm', 'M', '2026-08-14'), 'title': '[사업공고] ’26년 군인공제회 「PE」 선정 공고(우정사업본부 공고 2026-33호)'},
        ])
        index = pages['index.html']
        self.assertIn('>같은 공고 · 6월 공고<', index); self.assertIn('>같은 공고 · 9월 공고<', index)
        self.assertIn('>2026년 군인공제회 PE 선정 공고<', index)
        self.assertIn('<h1>2026년 군인공제회 PE 선정 공고</h1><p class="source-title">공고명 [사업공고]', pages['program-c.html'])
        self.assertIn('<title>2026년 군인공제회 PE 선정 공고 · LP</title>', pages['program-c.html'])

    def test_institution_directory_and_merged_manager_history(self):
        pages = self.render([
            self.selected('g1', 'kgrowth', '한국성장금융', '에스지프라이빗에쿼티', '138', master='138'),
            self.selected('x1', 'kexim', '한국수출입은행', '에스지 프라이빗에쿼티', 'kexim-1', event='2026-10-01'),
            self.selected('x2', 'kexim', '한국수출입은행', '다른운용사', 'kexim-2'),
        ])
        self.assertIn('href="institution-directory.html">출자기관 2곳</a>', pages['index.html'])
        directory = pages['institution-directory.html']
        self.assertLess(directory.index('institution-kexim.html'), directory.index('institution-kgrowth.html'))
        self.assertIn('출자사업 2건 · 선정 운용사 2곳', pages['institution-kexim.html'])
        for key in ('138', 'kexim-1'):
            page = pages[f'selected-gp-{key}.html']
            self.assertIn('선정 이력 2건', page)
            self.assertIn('program-g1.html', page); self.assertIn('program-x1.html', page)
        self.assertIn('선정 이력 1건', pages['selected-gp-kexim-2.html'])

    def test_detail_marks_current_step_hides_placeholders_and_has_meta(self):
        p = self.program('s', '접수 마감', 'k', 'K', '2026-10-01')
        p['primary_investment'] = {'text': '별도 투자대상·의무비율 미확인'}
        p['schedule_stages'] = [
            {'stage': 'announcement', 'label': '모집 공고', 'date': '2026-09-01', 'precision': 'date', 'status': 'confirmed', 'source_url': 'https://official.example/s'},
            {'stage': 'application', 'label': '접수 마감', 'date': '2026-10-01', 'precision': 'date', 'status': 'announced_deadline', 'source_url': 'https://official.example/s'},
            {'stage': 'selection', 'label': '최종 선정', 'date': '2026-12-01', 'precision': 'date', 'status': 'planned', 'source_url': 'https://official.example/s'}]
        page = self.render([p])['program-s.html']
        self.assertIn('<li class="done">공고</li><li class="current" aria-current="step">접수</li><li>심사</li><li>선정</li>', page)
        self.assertNotIn('주목적', page); self.assertNotIn('선정 결과 미확인', page)
        self.assertIn('<meta name="description" content="K · s · 접수 마감.', page)
        self.assertIn('<link rel="canonical" href="https://kpef-lp.vercel.app/program-s.html">', page)

    def reported(self, pid, managers=('가PE', '나PE'), complete=True, stage='최종 선정'):
        return {'program_id': pid, 'stage': stage, 'reported_at': '2026-10-15', 'complete': complete,
                'managers': list(managers), 'note': '보도 메모',
                'sources': [{'publisher': '딜사이트', 'title': '기사', 'date': '2026-10-15', 'url': 'https://news.example/1'}]}

    def test_reported_result_labelled_sourced_and_never_over_official(self):
        closed = self.program('r', '접수 마감', 'k', 'K', '2026-09-01')
        official = self.selected('o', 'm', 'M', '공식운용사', 'm-1')
        data_programs = [closed, official]
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            build({'as_of': '2026-11-12', 'programs': data_programs,
                   'reported_results': {'r': self.reported('r', complete=False), 'o': self.reported('o')}}, out)
            index = (out / 'index.html').read_text(); detail = (out / 'program-r.html').read_text()
            official_page = (out / 'program-o.html').read_text()
        self.assertIn('10.15 보도 · 확인 2개사', index)
        self.assertIn('<span class="badge">보도 기준</span>', detail)
        self.assertIn('<li>가PE</li>', detail); self.assertIn('보도로 확인된 일부 운용사입니다.', detail)
        self.assertIn('href="https://news.example/1"', detail); self.assertIn('딜사이트 2026.10.15', detail)
        self.assertNotIn('보도 기준', official_page); self.assertNotIn('가PE', official_page)
        self.assertNotIn('selected-gp-', detail)

    def test_mixed_scope_marked_in_list_and_detail(self):
        p = self.selected('v', 'kgrowth', '한국성장금융', '어떤벤처투자', 'kg-1')
        p['asset_scope'] = '기관전용 사모펀드·벤처·신기술조합'
        pages = self.render([p, self.program('pe', '접수 마감', 'k', 'K', '2026-09-01')])
        self.assertIn('한국성장금융 · PE·VC 공동', pages['index.html'])
        self.assertNotIn('K · PE·VC', pages['index.html'])
        self.assertIn('PE·VC 공동 모집</span>', pages['program-v.html'])
        self.assertIn('벤처캐피탈이 포함될 수 있습니다', pages['program-v.html'])


class ReportedResultFile(unittest.TestCase):
    def test_repository_file_is_valid_and_sourced(self):
        import json
        from services.lp.src.lp_reported_results import validate_result, DEFAULT_PATH
        data = json.loads(DEFAULT_PATH.read_text())
        ids = [validate_result(r)['program_id'] for r in data['results']]
        self.assertEqual(len(ids), len(set(ids)))

    def test_loader_skips_unknown_invalid_and_official(self):
        import json
        from services.lp.src.lp_reported_results import load_reported_results
        good = {'program_id': 'a', 'stage': '최종 선정', 'reported_at': '2026-10-15', 'complete': True, 'managers': ['X'],
                'sources': [{'publisher': 'P', 'title': 'T', 'date': '2026-10-15', 'url': 'https://n.example/'}]}
        entries = [good, {**good, 'program_id': 'b'}, {**good, 'program_id': 'zz'},
                   {**good, 'program_id': 'c', 'sources': [{**good['sources'][0], 'url': 'http://insecure'}]},
                   {**good, 'program_id': 'd', 'stage': '선정 없음'}]
        programs = [{'id': 'a'}, {'id': 'b', 'selected_gps': [{'name': 'Y'}]}, {'id': 'c'}, {'id': 'd'}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'r.json'; path.write_text(json.dumps({'results': entries}))
            results, holds = load_reported_results(programs, path)
        self.assertEqual(list(results), ['a'])
        self.assertEqual({h['program_id'] for h in holds}, {'b', 'zz', 'c', 'd'})
