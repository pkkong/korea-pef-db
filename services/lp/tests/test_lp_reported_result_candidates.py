import unittest

from services.lp.src.lp_reported_result_candidates import (
    find_candidates,
    institutions_in,
    is_result_report,
    load_aliases,
    render_markdown,
)


def program(pid, inst, name, dates, selected=None):
    return {'id': pid, 'institution_id': inst, 'institution_name': name, 'title': pid,
            'events': [{'date': d} for d in dates], 'selected_gps': selected or []}


def article(day, title, url, publisher='딜사이트'):
    return {'issue_date': day, 'title': title, 'source_url': url, 'normalized_url': url,
            'publisher': publisher, 'summary_text': ''}


class ResultReportWordingTests(unittest.TestCase):
    def test_result_titles(self):
        for title in ('과기공, PEF 위탁운용사에 제네시스PE·어펄마·BNW인베 등 6곳 선정',
                      '총회연금 GP, 크레센도·어펄마·아주IB·스마일게이트 낙점',
                      '[마켓인]군인공제회, 3000억 블라인드펀드 운용사 18곳 확정'):
            self.assertTrue(is_result_report(title), title)

    def test_announcements_and_plans_are_not_results(self):
        for title in ('한국벤처투자, 세컨더리 GP 3곳 뽑는다...750억 출자',
                      '에너지공단, 3500억 규모 재생에너지 펀드 만든다… 母펀드 운용사 선정 착수',
                      '정기출자 앞둔 과기공…외부 평가로 위탁운용사 첫 선정',
                      '초장기 기술투자펀드 운용사 10월 선정…이르면 연내 자금집행 공고'):
            self.assertFalse(is_result_report(title), title)


class InstitutionAliasTests(unittest.TestCase):
    def setUp(self):
        self.aliases = load_aliases()

    def test_press_short_names(self):
        self.assertIn('sema', institutions_in('과기공, PEF 위탁운용사 6곳 선정', self.aliases))
        self.assertIn('pck_pension', institutions_in('총회연금 GP 낙점', self.aliases))
        self.assertIn('kdb', institutions_in('산은 남부권 지역성장펀드 GP 선정', self.aliases))
        self.assertEqual({'moel_iaci'}, institutions_in('산재기금 PE 부문 GP 선정', self.aliases))

    def test_latin_alias_needs_word_boundary(self):
        # "CU" or "TP" inside other words must not identify 신협·사학연금.
        self.assertNotIn('cu', institutions_in('SCUBA 운용사 선정', self.aliases))
        self.assertNotIn('kdb', institutions_in('KDBX 운용사 선정', self.aliases))


class CandidateMatchingTests(unittest.TestCase):
    def setUp(self):
        self.aliases = load_aliases()
        self.programs = [
            program('sema-2026-x', 'sema', '과학기술인공제회', ['2026-08-14']),
            program('mmaa-2026-x', 'mmaa', '군인공제회', ['2026-07-31']),
            program('ibk-2026-x', 'ibk', 'IBK기업은행', ['2026-07-08'], selected=[{'name': 'A'}]),
            program('sema-2023-x', 'sema', '과학기술인공제회', ['2023-08-01']),
        ]
        self.reported = [
            {'program_id': 'sema-2026-x', 'complete': False, 'managers': ['A'],
             'sources': [{'url': 'https://example.com/cited'}]},
            {'program_id': 'mmaa-2026-x', 'complete': True, 'managers': ['B'],
             'sources': [{'url': 'https://example.com/mmaa'}]},
        ]

    def test_groups_new_article_under_partially_reported_program(self):
        result = find_candidates(self.programs, [
            article('2026-11-03', '과기공, PEF 위탁운용사에 제네시스PE 등 6곳 선정', 'https://example.com/new'),
        ], self.reported, self.aliases)
        self.assertEqual(['sema-2026-x'], [c['program_id'] for c in result['candidates']])
        self.assertEqual('보도 기준 결과가 일부만 반영됨', result['candidates'][0]['reason'])

    def test_already_cited_article_is_skipped(self):
        result = find_candidates(self.programs, [
            article('2026-11-03', '과기공, PEF 위탁운용사 6곳 선정', 'https://example.com/cited'),
        ], self.reported, self.aliases)
        self.assertEqual([], result['candidates'])

    def test_program_year_must_be_close_to_article_year(self):
        result = find_candidates(self.programs, [
            article('2026-11-03', '과기공, PEF 위탁운용사 6곳 선정', 'https://example.com/new'),
        ], self.reported, self.aliases)
        self.assertNotIn('sema-2023-x', [c['program_id'] for c in result['candidates']])

    def test_unreported_and_official_programs_are_labelled(self):
        result = find_candidates(self.programs + [program('kbiz-2026-x', 'kbiz', '중소기업중앙회', ['2026-07-10'])], [
            article('2026-10-01', '중기중앙회, 블라인드펀드 운용사 4곳 선정', 'https://example.com/kbiz'),
            article('2026-07-09', 'IBK기업은행, 동행펀드 운용사 6곳 선정', 'https://example.com/ibk'),
        ], self.reported, self.aliases)
        reasons = {c['program_id']: c['reason'] for c in result['candidates']}
        self.assertEqual('결과 미반영', reasons['kbiz-2026-x'])
        self.assertTrue(reasons['ibk-2026-x'].startswith('공식 명단 있음'))
        self.assertEqual('kbiz-2026-x', result['candidates'][0]['program_id'])

    def test_duplicate_urls_count_once_and_unknown_programs_are_listed_separately(self):
        result = find_candidates(self.programs, [
            article('2026-10-16', '군인공제회, 운용사 18곳 선정', 'https://example.com/m2'),
            article('2026-10-16', '군인공제회, 운용사 18곳 선정', 'https://example.com/m2'),
            article('2026-07-10', '국민연금, 벤처펀드 위탁운용사 6곳 선정', 'https://example.com/nps'),
        ], self.reported, self.aliases)
        self.assertEqual(1, len(result['candidates'][0]['articles']))
        self.assertEqual(['nps'], result['unmatched_institution_articles'][0]['institutions'])
        self.assertIn('공개 사업과 연결되지 않은', render_markdown(result, '2026-05-01'))


if __name__ == '__main__':
    unittest.main()
