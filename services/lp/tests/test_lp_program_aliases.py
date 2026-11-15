import unittest

import json
import tempfile
from pathlib import Path

from services.lp.src.lp_program_aliases import alias_pages, load_seeds, missing_published_ids, update_aliases


def program(pid, title='2026년 국내 PE·VC 블라인드 펀드 선정계획 공고'):
    return {'id': pid, 'title': title, 'institution_name': '과학기술인공제회'}


def duplicate(old, new):
    return {'stage': 'basic_duplicate', 'program_key': old, 'program_id': old, 'kept_program_id': new,
            'reason': f'같은 출자사업의 재게시 공고: {new}로 합침'}


class ProgramAliasTests(unittest.TestCase):
    def test_published_duplicate_becomes_an_alias_of_the_kept_program(self):
        current = {'programs': [program('sema-2026-own'), program('sema-2026-repost')]}
        programs = [program('sema-2026-own')]
        aliases = update_aliases(current, programs, [duplicate('sema-2026-repost', 'sema-2026-own')])
        self.assertEqual(aliases, {'sema-2026-repost': 'sema-2026-own'})
        self.assertEqual(missing_published_ids(current, programs, aliases), [])
        page = alias_pages(programs, aliases)['program-sema-2026-repost.html']
        self.assertIn('url=program-sema-2026-own.html', page)
        self.assertIn('rel="canonical" href="program-sema-2026-own.html"', page)

    def test_never_published_duplicate_needs_no_alias(self):
        current = {'programs': [program('sema-2026-own')]}
        programs = [program('sema-2026-own')]
        self.assertEqual(update_aliases(current, programs, [duplicate('sema-2026-new-repost', 'sema-2026-own')]), {})

    def test_vanished_program_without_a_duplicate_hold_is_reported_not_aliased(self):
        current = {'programs': [program('a-2026-x'), program('a-2026-y')]}
        programs = [program('a-2026-x')]
        aliases = update_aliases(current, programs, [])
        self.assertEqual(aliases, {})
        self.assertEqual(missing_published_ids(current, programs, aliases), ['a-2026-y'])

    def test_earlier_aliases_are_carried_and_resolved_through_later_merges(self):
        current = {'programs': [program('a-2026-b')], 'program_aliases': {'a-2026-a': 'a-2026-b'}}
        programs = [program('a-2026-c')]
        aliases = update_aliases(current, programs, [duplicate('a-2026-b', 'a-2026-c')])
        self.assertEqual(aliases, {'a-2026-a': 'a-2026-c', 'a-2026-b': 'a-2026-c'})

    def test_alias_is_dropped_when_its_id_is_a_program_again_or_its_target_is_gone(self):
        current = {'programs': [], 'program_aliases': {'a-2026-a': 'a-2026-b', 'a-2026-z': 'a-2026-gone'}}
        aliases = update_aliases(current, [program('a-2026-a'), program('a-2026-b')], [])
        self.assertEqual(aliases, {})

    def test_reviewed_seed_restores_an_id_merged_before_aliases_existed(self):
        current = {'programs': [program('sema-2026-own')]}
        seeds = {'sema-2026-repost': 'sema-2026-own', 'sema-2026-other': 'sema-2026-gone'}
        self.assertEqual(update_aliases(current, [program('sema-2026-own')], [], seeds), {'sema-2026-repost': 'sema-2026-own'})

    def test_repository_seed_file_is_valid_and_seeds_need_evidence(self):
        self.assertEqual(load_seeds()['sema-2026-9a8767587e5612d3'], 'sema-2026-b9d11f3a1eb1f6b4')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'aliases.json'
            path.write_text(json.dumps({'aliases': [{'program_id': 'a-2026-x', 'kept_program_id': 'a-2026-y'}]}))
            with self.assertRaises(ValueError):
                load_seeds(path)
            self.assertEqual(load_seeds(Path(folder) / 'none.json'), {})

    def test_alias_page_escapes_titles(self):
        page = alias_pages([program('a-2026-b', '<script>x</script>')], {'a-2026-a': 'a-2026-b'})['program-a-2026-a.html']
        self.assertNotIn('<script>x', page)


if __name__ == '__main__':
    unittest.main()
