import copy
import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
from services.lp.src.build_lp_history_coverage import build, markdown


def notice(**changes):
    row={'institution_id':'kdb','url':'https://www.kdb.co.kr/public?id=987654',
         'date':'2023-01-01','title':'공식 공고','body':'공식 본문','sha256':'a'*64,
         'attachment_hashes':{'https://www.kdb.co.kr/file?id=42':'b'*64}}
    row.update(changes);return row


def source(rows,kind='institution',**other):
    return {'kind':kind,'report':{'checked_at':'2026-11-06T00:00:00Z','notices':rows,**other}}


def row(report,iid='kdb',year=2023):
    return next(r for r in report['rows'] if r['institution_id']==iid and r['year']==year)


class HistoryCoverageTests(unittest.TestCase):
    def test_default_names_need_only_tracked_registries(self):
        scope={'confirmed_institution_ids':['kdb'], 'priority_verification_ids':[]}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir()
            (root/'data/lp_institutions.csv').write_text('lp_code,lp_name\nkdb,산업은행\n')
            (root/'data/lp_blind_contest_screening_test.json').write_text(json.dumps(
                {'institutions':[{'institution_id':'kdb','name':'한국산업은행'}]}))
            with patch('services.lp.src.build_lp_history_coverage.ROOT',root):
                r=build([source([notice()])],as_of='2026-11-06',scope=scope)
            self.assertEqual(row(r)['name'],'한국산업은행')
            self.assertFalse((root/'data/lp_directory_review.json').exists())
        with self.assertRaisesRegex(ValueError,'invalid coverage map'):
            build([source([],coverage=[])],as_of='2026-11-06')

    def test_24_year_grid_no_supabase_or_market_claim(self):
        r=build([],as_of='2026-11-06')
        self.assertEqual(len(r['rows']),24*4)
        self.assertTrue(all(v['evidence_record_count'] is None for v in r['rows']))
        self.assertEqual(r['history_completeness'],'UNVERIFIED')
        self.assertIn('전체 DB',markdown(r))
        self.assertNotIn('percentage',str(r))

    def test_deduplicate_versions_and_hash_pairs_without_mutation(self):
        n=notice();new=notice(body='변경된 본문',sha256='c'*64)
        inputs=[source([n]),source([new,n])];before=copy.deepcopy(inputs)
        r=build(inputs,as_of='2026-11-06')
        self.assertEqual(row(r)['evidence_record_count'],1)
        self.assertEqual(row(r)['attachment_hash_pair_count'],1)
        self.assertEqual(inputs,before)
        self.assertEqual(row(r)['observed_min_date'],'2023-01-01')

    def test_inclusive_dates_and_outside(self):
        ns=[notice(date=d,url='https://www.kdb.co.kr/public?id='+str(i)) for i,d in enumerate(
            ['2022-12-31','2023-01-01','2026-11-06','2026-11-07'])]
        r=build([source(ns)],as_of='2026-11-06')
        self.assertEqual(row(r)['evidence_record_count'],1)
        self.assertEqual(row(r,year=2026)['evidence_record_count'],1)
        self.assertEqual(next(x for x in r['institution_exclusions'] if x['institution_id']=='kdb')['out_of_window'],2)

    def test_date_conflict_never_silently_selects_year(self):
        r=build([source([notice(),notice(date='2024-02-01')])],as_of='2026-11-06')
        self.assertEqual(row(r)['evidence_record_count'],0)
        self.assertEqual(row(r,year=2024)['evidence_record_count'],0)
        conflict=next(x for x in r['issues'] if x['kind']=='publication_date_conflict')
        self.assertEqual(conflict['dates'],['2023-01-01','2024-02-01'])

    def test_inheritance_and_supporting_dedup(self):
        n=notice();n.pop('institution_id')
        g=source([n],kind='growth')
        p={'kind':'priority','report':{'sources':{'kexim':{'notices':[n],'supporting_notices':[{**n,'institution_id':'kexim'}]}}}}
        r=build([g,p],as_of='2026-11-06')
        self.assertEqual(row(r,'kgrowth')['evidence_record_count'],1)
        self.assertEqual(row(r,'kexim')['evidence_record_count'],1)
        self.assertIsNone(row(r,'ktcu')['evidence_record_count'])
        r=build([source([notice()],kind='growth')],as_of='2026-11-06')
        self.assertEqual(row(r,'kgrowth')['evidence_record_count'],0)
        self.assertEqual(r['issues'][0]['kind'],'invalid_issuer')

    def test_cross_issuer_support_uses_declared_issuer_and_deduplicates(self):
        n=notice()
        priority={'kind':'priority','report':{'sources':{'kexim':{
            'notices':[n], 'supporting_notices':[n, {k:v for k,v in n.items() if k!='institution_id'}]}}}}
        r=build([priority,source([n])],as_of='2026-11-06')
        self.assertEqual(row(r,'kdb')['evidence_record_count'],1)
        self.assertEqual(row(r,'kdb')['attachment_hash_pair_count'],1)
        self.assertEqual(row(r,'kexim')['evidence_record_count'],0)
        self.assertEqual(sum(i['kind']=='invalid_issuer' for i in r['issues']),2)

    def test_unverified_invalid_and_provided_zero_distinct(self):
        records=[notice(body=''),notice(url='https://u:p@www.kdb.co.kr/a'),
                 notice(date='2023-02-30'),notice(sha256='bad'),notice(title='')]
        r=build([source(records,coverage={'ibk':{'detail_count':0}})],as_of='2026-11-06')
        self.assertEqual(row(r)['evidence_record_count'],0)
        self.assertEqual(row(r,'ibk')['evidence_record_count'],0)
        self.assertIsNone(row(r,'nps')['evidence_record_count'])
        self.assertTrue({'invalid_date','invalid_url','unverified_record'} <= {x['kind'] for x in r['issues']})
        self.assertEqual(r['validation'],'structural_only_no_source_replay')

    def test_invalid_attachment_pair_does_not_inflate_count(self):
        r=build([source([notice(attachment_hashes={'https://www.kdb.co.kr/a':'broken'})])],as_of='2026-11-06')
        self.assertEqual(row(r)['attachment_hash_pair_count'],0)
        self.assertEqual(r['issues'][0]['kind'],'invalid_attachment_hash_pair')
        with self.assertRaises(ValueError):build([],as_of='2022-01-01')


if __name__=='__main__':unittest.main()
