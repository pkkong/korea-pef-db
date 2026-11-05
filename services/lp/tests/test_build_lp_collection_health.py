import copy
import unittest
from services.lp.src.build_lp_collection_health import build_report, markdown

STAMP = '2026-11-05T01:00:00+00:00'


def direct(count=0, holds=None):
    return {'checked_at': STAMP, 'notices': [{'institution_id': 'kdb', 'body': 'old private payload'}],
            'coverage': {'kdb': {'listing_pages': [{'count': 0}], 'detail_count': count, 'attachment_count': 0}},
            'holds': holds or []}


def rows(**kwargs):
    return {r['institution_id']: r for r in build_report(**kwargs)['institutions']}


class CollectionHealthTests(unittest.TestCase):
    def test_target24_daily22_weekly2_missing_not_ok(self):
        report = build_report()
        self.assertEqual(report['target_count'], 24)
        self.assertEqual(sum(r['frequency'] == 'daily' for r in report['institutions']), 22)
        self.assertEqual({r['institution_id'] for r in report['institutions'] if r['source_health'] == 'weekly_only'}, {'nh_central','suhyup'})
        self.assertFalse(any(r['source_health'] == 'ok' for r in report['institutions']))

    def test_observed_zero_is_not_missing_or_publication_failure(self):
        out = rows(institution=direct(), publication={'programs_by_institution': {'kdb': 0}})
        self.assertEqual(out['kdb']['source_health'], 'ok')
        self.assertEqual(out['kdb']['body_count'], 0)
        self.assertEqual(out['kdb']['publication_availability'], 'none')
        self.assertIsNone(out['ibk']['body_count'])
        self.assertEqual(out['ibk']['source_health'], 'not_observed')
        self.assertIsNone(out['ibk']['public_program_count'])

    def test_source_failure_does_not_reuse_old_notices_as_success(self):
        d = direct(holds=[{'institution_id':'kdb','stage':'institution_listing','error':'secret URL'}])
        d['coverage'] = {}
        r = rows(institution=d)['kdb']
        self.assertEqual(r['source_health'], 'error')
        self.assertEqual(r['source_errors'], 1)
        self.assertIsNone(r['body_count'])

    def test_holds_separate_and_global_not_discarded(self):
        holds = [{'institution_id':'kdb','stage':stage} for stage in
                 ['institution_attachment','institution_restricted','institution_depth','unexpected']]
        holds += [{'error':'private content', 'url':'https://private.example'}, {'institution_id':'unknown','stage':'institution_detail'}]
        d = direct(2, holds)
        before = copy.deepcopy(d)
        report = build_report(institution=d)
        r = next(r for r in report['institutions'] if r['institution_id']=='kdb')
        self.assertEqual([r[k] for k in ('source_errors','attachment_holds','restricted_holds','unknown_holds')], [1,1,1,1])
        self.assertEqual(len(report['global_issues']), 2)
        self.assertNotIn('private', str(report))
        self.assertNotIn('https://', markdown(report))
        self.assertEqual(d, before)

    def test_priority_supporting_notices_are_not_added_to_body_count(self):
        n = {'url':'private_url','body':'not emitted','attachment_hashes':{'file':'a'*64}}
        source = {'checked_at':STAMP,'notices':[n], 'supporting_notices':[n],
                  'holds':[{'program_id':'program','reason':'GP review'}]}
        r = rows(priority={'sources':{'kexim':source}})['kexim']
        self.assertEqual(r['source_health'],'ok')
        self.assertEqual((r['body_count'],r['supporting_body_count'],r['stored_attachment_count']), (1,1,1))
        self.assertEqual(r['source_errors'],0)
        self.assertEqual(r['review_holds'],1)
        source['error'] = 'fetch failed'
        self.assertEqual(rows(priority={'sources':{'kexim':source}})['kexim']['source_health'],'error')

    def test_growth_missing_and_unavailable_deduplicated_not_review(self):
        g = {'checked_at':STAMP,'notices':[], 'review':[{}], 'extraction_holds':[{}],
             'collection_coverage':{'listing_urls':['private'], 'fetched_count':0,
                 'missing_source_ids':['77'], 'unavailable_notices':[{'source_id':'77','reason':'official_detail_empty'}],
                 'attachments':[{'readable':False,'reason':''},{'readable':False,'reason':'decode failure'}]}}
        r = rows(growth=g)['kgrowth']
        self.assertEqual(r['source_errors'],1)
        self.assertEqual(r['attachment_holds'],1)
        self.assertEqual(r['review_holds'],2)
        self.assertEqual(r['body_count'],0)
        self.assertEqual(r['source_health'],'error')
        g['collection_coverage'].update(missing_source_ids=[],unavailable_notices=[])
        self.assertEqual(rows(growth=g)['kgrowth']['source_health'],'ok')

    def test_public_counts_strict_nonnegative_integer(self):
        for bad in (-1, True, '2', None):
            with self.assertRaises(ValueError):
                build_report(publication={'programs_by_institution':{'kdb':bad}})

    def test_complete_public_counts_distinguish_zero_from_missing_old_summary(self):
        p = {'programs': 2, 'run_id': 'run', 'programs_by_institution': {'ktcu': 2}}
        out = rows(publication=p)
        self.assertEqual(out['kdb']['public_program_count'], 0)
        self.assertEqual(out['kdb']['publication_availability'], 'none')
        self.assertIsNone(rows(publication={'programs': 2})['kdb']['public_program_count'])
        with self.assertRaisesRegex(ValueError, 'total'):
            build_report(publication={**p, 'programs': 3})

    def test_complete_official_empty_template_remains_visible_without_fetch_error(self):
        g = {'checked_at': STAMP, 'notices': [], 'collection_coverage': {
            'listing_urls': ['listing'], 'fetched_count': 0, 'missing_source_ids': [],
            'unavailable_notices': [{'source_id':'77', 'reason':'official_detail_empty',
                                    'response_sha256':'b'*64, 'response_size':9000}]}}
        row = rows(growth=g)['kgrowth']
        self.assertEqual(row['source_health'], 'ok')
        self.assertEqual(row['unavailable_notice_holds'], 1)
        self.assertEqual(row['source_errors'], 0)
        g['collection_coverage']['date_discovery'] = {'complete': False}
        self.assertEqual(rows(growth=g)['kgrowth']['source_health'], 'error')

    def test_association_failure_or_absence_cannot_look_like_all_sources_ok(self):
        scope = {'confirmed_institution_ids':['kdb'], 'priority_verification_ids':[]}
        args = {'institution': direct(), 'scope':scope, 'channels':[{'institution_id':'kdb'}]}
        self.assertFalse(build_report(**args)['all_collection_sources_ok'])
        self.assertFalse(build_report(**args, shared={'coverage':{'channel_pages':{}}})['all_collection_sources_ok'])
        shared = {'coverage': {'channel_pages': {c:{'pages':[{'status':'ok'}]}
                   for c in ('kvca','kofia_212','kofia_17')}}, 'holds': []}
        self.assertTrue(build_report(**args, shared=shared)['all_collection_sources_ok'])
        shared['holds'] = [{'stage':'listing', 'error':'failure'}]
        self.assertFalse(build_report(**args, shared=shared)['all_collection_sources_ok'])
        shared['holds'] = [{'stage':'attachment', 'error':'decode'}]
        out = build_report(**args, shared=shared)
        self.assertTrue(out['all_collection_sources_ok'])
        self.assertEqual(out['association']['attachment_holds'], 1)


if __name__ == '__main__':
    unittest.main()
