import copy
import unittest
from unittest.mock import MagicMock
from services.lp.src import export_lp_history_index as index


def metadata(**values):
    return {'url':'https://www.kgrowth.or.kr/notice_view.asp?idx=100','institution_id':None,
            'date':'2023-01-01','title':'과거 모집','body_present':True,'source_id':'100',
            'content_hash':'a'*64,'source_sha256':None,'attachment_hashes':{},'event_type':None,**values}


class HistoryIndexTests(unittest.TestCase):
    def connection(self, rows):
        conn=MagicMock()
        def execute(query,params=None):
            cursor=MagicMock()
            if 'SELECT run_id' in query:cursor.fetchone.return_value=('original-public-run',)
            elif query==index.INDEX_SQL:cursor.fetchall.return_value=rows
            return cursor
        conn.execute.side_effect=execute
        return conn

    def export(self, rows, limit=3):
        conn=self.connection(rows)
        return conn,index.export_index(conn,row_limit=limit,channels={'kgrowth':{'kgrowth.or.kr'}},targets={'kgrowth'})

    def test_repeatable_read_only_snapshot_bound_and_metadata_without_hash_invention(self):
        record=metadata();before=copy.deepcopy(record)
        conn,r=self.export([(record,1)])
        self.assertEqual(r['records'][0]['institution_id'],'kgrowth')
        self.assertIsNone(r['records'][0]['source_sha256'])
        self.assertEqual(record,before)
        self.assertEqual(r['snapshot_run_id'],'original-public-run')
        self.assertTrue(r['database_index_complete']);self.assertFalse(r['source_history_complete'])
        calls=conn.execute.call_args_list
        self.assertEqual(calls[0].args[0],'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        self.assertEqual(calls[-1].args,(index.INDEX_SQL,(4,)))
        for forbidden in ('UPDATE ','INSERT ','DELETE ','collection_runs','attachment_bytes','discovery_provenance\''):
            self.assertNotIn(forbidden,' '.join(c.args[0] for c in calls))
        conn.commit.assert_not_called()

    def test_limit_does_not_turn_partial_database_into_complete_history(self):
        _,r=self.export([(metadata(source_id=str(i)),5) for i in range(4)])
        self.assertEqual(r['database_rows'],3);self.assertEqual(r['database_total_rows'],5)
        self.assertFalse(r['database_index_complete']);self.assertFalse(r['source_history_complete'])

    def test_known_private_marker_exposes_no_record_metadata(self):
        _,r=self.export([({'restricted':True},2),(metadata(),2)])
        self.assertEqual(r['restricted_rows_excluded'],1)
        self.assertEqual(r['database_rows'],1)
        self.assertTrue(r['database_index_complete'])
        self.assertNotIn('restricted',r['records'][0])

    def test_shared_host_unknown_and_invalid_declaration_are_not_guessed(self):
        targets,hosts=index.issuer_index({'moel_eif':{'moel.go.kr'},'moel_iaci':{'moel.go.kr'}},
                                        {'moel_eif','moel_iaci'})
        self.assertIsNone(index.resolve_issuer(metadata(url='https://www.moel.go.kr/a'),targets,hosts)[0])
        self.assertIsNone(index.resolve_issuer(metadata(url='https://unlisted.example/a'),targets,hosts)[0])
        self.assertIsNone(index.resolve_issuer(metadata(institution_id='other'),targets,hosts)[0])
        self.assertEqual(index.resolve_issuer(metadata(institution_id='moel_eif'),targets,hosts)[0],'moel_eif')

    def test_empty_database_and_bad_limit_or_count(self):
        _,r=self.export([])
        self.assertEqual(r['database_rows'],0);self.assertTrue(r['database_index_complete'])
        for limit in (0,10001,True):
            with self.assertRaises(ValueError):self.export([],limit)
        with self.assertRaises(ValueError):self.export([(metadata(),0)])
        with self.assertRaises(ValueError):self.export([(metadata(),2)])

    def test_export_metadata_is_accepted_without_fabricating_an_original_hash_or_complete_year(self):
        from services.lp.src.build_lp_history_coverage import build
        _,exported=self.export([(metadata(),1)])
        report=build([{'kind':'database_index','report':exported}],as_of='2026-11-06')
        cell=next(r for r in report['rows'] if r['institution_id']=='kgrowth' and r['year']==2023)
        self.assertEqual(cell['evidence_record_count'],1)
        self.assertEqual(cell['history_completeness'],'UNVERIFIED')
        self.assertIsNone(exported['records'][0]['source_sha256'])
        self.assertNotIn('body',str(exported['records'][0].keys()).replace('body_present',''))


if __name__=='__main__':unittest.main()
