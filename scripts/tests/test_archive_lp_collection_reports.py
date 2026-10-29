import copy
import hashlib
import io
import json
import unittest
from unittest.mock import MagicMock, Mock, patch
from scripts import archive_lp_collection_reports as m
from services.lp.src import lp_report_archive as a

REPORT={'notices':[{'url':'https://official.example/1','body':'한글'*5000}],'zero':0,'none':None}


def connection():
    conn=MagicMock();conn.__enter__.return_value=conn
    return conn


def snapshot():
    return {'candidate_runs':['old'], 'storage_bytes':0,
            'published':{'run_id':'current','pages_md5':'same'},'reviews':{'md5':'same'},
            'archive_count':1,'rows':[{'run_id':'old','stored_bytes':500,'protected':False},{'run_id':'current','stored_bytes':8000,'protected':True}]}


class MaintenanceContracts(unittest.TestCase):
    def test_automatic_cleanup_runs_even_when_no_new_report_was_archived(self):
        # A failed publication can leave old large row versions without creating
        # another collection run. Retention must still recycle that space.
        result={'after':{'archive_count':91},'results':[]}
        with patch('sys.argv',['maintenance','--mode','archive','--reuse-space']),patch.dict('os.environ',{'SUPABASE_URL':'https://sample-project.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'fake-service','SUPABASE_PUBLISHABLE_KEY':'fake-public'}),patch.object(a,'ArchiveStore'),patch.object(m,'install_archive_guard'),patch.object(m,'archive',return_value=result),patch.object(m,'reclaim',return_value={'cleaned':True}) as cleanup,patch('sys.stdout',new_callable=io.StringIO):
            m.main()
        cleanup.assert_called_once_with(full=False)

    def test_current_run_is_kept_even_outside_latest_three(self):
        conn=connection();conn.execute.side_effect=[Mock(fetchall=lambda:[('new1',),('new2',),('new3',)]),Mock(fetchone=lambda:('current-old',))]
        self.assertEqual(m.protected_runs(conn),{'new1','new2','new3','current-old'})
        with self.assertRaises(m.MaintenanceError):m.protected_runs(conn,0)

    def test_write_lock_precedes_current_and_recent_protection_check(self):
        blob,meta=a.encode_report(REPORT);stub=a.make_stub('old',meta)
        conn=connection()
        def protect(_conn,keep):
            self.assertIn('pg_advisory_xact_lock',conn.execute.call_args.args[0])
            return {'old'}
        with patch.object(m,'connect',return_value=conn),patch.object(m,'protected_runs',side_effect=protect):
            self.assertEqual(m.replace_with_stub('old','12',stub),'protected')
        self.assertFalse(any(c.args[0].startswith('UPDATE') for c in conn.execute.call_args_list))

    def test_changed_row_version_is_not_overwritten(self):
        blob,meta=a.encode_report(REPORT);stub=a.make_stub('old',meta)
        conn=connection();conn.execute.return_value.fetchone.return_value=None
        with patch.object(m,'connect',return_value=conn),patch.object(m,'protected_runs',return_value={'current'}):
            self.assertEqual(m.replace_with_stub('old','12',stub),'changed')
        query,params=conn.execute.call_args.args
        self.assertIn('xmin::text=%s',query);self.assertEqual(params[1:],('old','12'))
        self.assertEqual(json.loads(params[0]),stub)

    def test_upload_and_readback_happen_after_database_connection_closed(self):
        blob,meta=a.encode_report(REPORT);stub=a.make_stub('old',meta)
        conn=connection();active=[]
        conn.__enter__.side_effect=lambda:active.append(True) or conn
        conn.__exit__.side_effect=lambda *args:active.pop()
        conn.execute.return_value.fetchone.return_value=(0,)
        def upload(run,report):
            self.assertFalse(active)
            return stub
        store=Mock(spec=a.ArchiveStore);store.put_verified.side_effect=upload
        before=snapshot()
        with patch.object(m,'inspect',side_effect=[before,copy.deepcopy(before)]),patch.object(m,'read_report',return_value=(REPORT,'12')),patch.object(m,'connect',return_value=conn),patch.object(m,'replace_with_stub',return_value='archived') as replace:
            result=m.archive(store,limit=1)
        self.assertEqual(result['results'][0]['status'],'archived')
        replace.assert_called_once_with('old','12',stub,3)

    def test_failed_or_incorrect_archive_never_replaces_database_source(self):
        blob,meta=a.encode_report(REPORT);stub=a.make_stub('old',meta)
        conn=connection();conn.execute.return_value.fetchone.return_value=(0,)
        for bad in ['failure','wrong_report']:
            store=Mock(spec=a.ArchiveStore)
            if bad=='failure':store.put_verified.side_effect=a.ArchiveError('upload failed')
            else:
                wrong=copy.deepcopy(stub);wrong[a.MARKER]['raw_bytes']+=1;store.put_verified.return_value=wrong
            with self.subTest(case=bad),patch.object(m,'inspect',return_value=snapshot()),patch.object(m,'read_report',return_value=(REPORT,'12')),patch.object(m,'connect',return_value=conn),patch.object(m,'replace_with_stub') as replace,self.assertRaises((a.ArchiveError,m.MaintenanceError)):
                m.archive(store,limit=1)
            replace.assert_not_called()

    def test_storage_budget_failure_keeps_original_before_upload(self):
        conn=connection();conn.execute.return_value.fetchone.return_value=(m.STORAGE_BUDGET,)
        store=Mock(spec=a.ArchiveStore)
        with patch.object(m,'inspect',return_value=snapshot()),patch.object(m,'read_report',return_value=(REPORT,'12')),patch.object(m,'connect',return_value=conn),patch.object(m,'replace_with_stub') as replace,self.assertRaisesRegex(m.MaintenanceError,'budget'):
            m.archive(store,limit=1)
        store.put_verified.assert_not_called();replace.assert_not_called()

    def test_restore_refuses_changed_descriptor_and_preserves_every_other_table(self):
        blob,meta=a.encode_report(REPORT);stub=a.make_stub('old',meta)
        conn=connection();conn.execute.return_value.fetchone.return_value=(stub,'new-revision')
        store=Mock(spec=a.ArchiveStore);store.restore.return_value=REPORT
        with patch.object(m,'inspect',return_value=snapshot()),patch.object(m,'read_report',return_value=(stub,'12')),patch.object(m,'connect',return_value=conn),self.assertRaisesRegex(m.MaintenanceError,'changed'):
            m.restore(store,'old')
        self.assertFalse(any(c.args[0].startswith('UPDATE') for c in conn.execute.call_args_list))
        conn.execute.return_value.fetchone.return_value=(stub,'12')
        with patch.object(m,'inspect',return_value=snapshot()),patch.object(m,'read_report',return_value=(stub,'12')),patch.object(m,'connect',return_value=conn):
            m.restore(store,'old')
        writes=[c for c in conn.execute.call_args_list if c.args[0].startswith('UPDATE')]
        self.assertEqual(len(writes),1);self.assertIn(m.TABLE,writes[0].args[0])
        self.assertEqual(json.loads(writes[0].args[1][0]),REPORT)
        self.assertFalse(any('DELETE' in c.args[0] for c in conn.execute.call_args_list))

    def test_public_archive_access_blocks_source_replacement(self):
        blob,meta=a.encode_report(REPORT);stub=a.make_stub('old',meta)
        conn=connection();conn.execute.return_value.fetchone.return_value=(0,)
        store=Mock(spec=a.ArchiveStore);store.put_verified.return_value=stub;store.assert_private.side_effect=a.ArchiveError('public access possible')
        with patch.object(m,'inspect',return_value=snapshot()),patch.object(m,'read_report',return_value=(REPORT,'12')),patch.object(m,'connect',return_value=conn),patch.object(m,'replace_with_stub') as replace,self.assertRaises(a.ArchiveError):
            m.archive(store,limit=1,public_key='anon')
        replace.assert_not_called()

    def test_private_guard_restricts_only_archive_bucket_and_refuses_unknown_existing_rule(self):
        conn=connection();conn.execute.side_effect=[Mock(fetchone=lambda:(True,)),Mock(fetchone=lambda:(True,)),Mock(fetchone=lambda:(True,)),Mock(fetchone=lambda:None),Mock()]
        with patch.object(m,'connect',return_value=conn):m.install_archive_guard()
        ddl=conn.execute.call_args.args[0]
        self.assertIn('AS RESTRICTIVE',ddl);self.assertIn("bucket_id <> 'lp-collection-reports'",ddl)
        self.assertIn('TO anon,authenticated',ddl)
        conn.reset_mock();conn.execute.side_effect=[Mock(),Mock(),Mock(fetchone=lambda:(True,)),Mock(fetchone=lambda:('PERMISSIVE',['anon'],'true','true','ALL'))]
        with patch.object(m,'connect',return_value=conn),self.assertRaises(m.MaintenanceError):m.install_archive_guard()
        self.assertFalse(any('CREATE POLICY' in c.args[0] for c in conn.execute.call_args_list))

    def test_guard_rejects_update_only_policy_and_disabled_rls(self):
        expression="(bucket_id <> 'lp-collection-reports'::text)"
        for rls,command in [(True,'UPDATE'),(False,'ALL')]:
            conn=connection();conn.execute.side_effect=[Mock(),Mock(),Mock(fetchone=lambda:(rls,)),Mock(fetchone=lambda:('RESTRICTIVE',['anon','authenticated'],expression,expression,command))]
            with patch.object(m,'connect',return_value=conn),self.assertRaises(m.MaintenanceError):m.install_archive_guard()
            self.assertFalse(any('CREATE POLICY' in c.args[0] for c in conn.execute.call_args_list))

    def test_reclaim_rechecks_size_after_session_lock_and_unlocks_on_change(self):
        conn=connection();conn.execute.side_effect=lambda q,*a:Mock(fetchone=lambda:(m.MAX_REWRITE_BYTES+1,1) if 'sum(pg_column_size' in q else (True,))
        with patch.object(m,'inspect',return_value=snapshot()),patch.object(m,'connect',return_value=conn),self.assertRaisesRegex(m.MaintenanceError,'changed before'):
            m.reclaim()
        queries=[c.args[0] for c in conn.execute.call_args_list]
        self.assertFalse(any(q.startswith('VACUUM') for q in queries))
        self.assertTrue(any('pg_advisory_unlock' in q for q in queries))

    def test_routine_reuse_does_not_rewrite_or_delete_the_table(self):
        conn=connection();conn.execute.side_effect=lambda q,*a:Mock(fetchone=lambda:(1000,1) if 'sum(pg_column_size' in q else (True,))
        before=snapshot()
        with patch.object(m,'inspect',side_effect=[before,copy.deepcopy(before)]),patch.object(m,'connect',return_value=conn):m.reclaim(full=False)
        queries=[c.args[0] for c in conn.execute.call_args_list]
        self.assertIn('VACUUM (ANALYZE, TRUNCATE FALSE) '+m.TABLE,queries)
        self.assertIn('VACUUM (ANALYZE, TRUNCATE FALSE) lp_program_private.program_state',queries)
        self.assertIn("SET statement_timeout='180s'",queries)
        self.assertFalse(any('advisory' in q for q in queries))
        self.assertFalse(any('FULL' in q or q.startswith(('DELETE','TRUNCATE')) for q in queries))

    def test_routine_cleanup_failure_closes_session_without_publication_lock(self):
        conn=connection()
        def execute(query,*args):
            if query.startswith('VACUUM'):
                raise RuntimeError('statement timeout')
            return Mock(fetchone=lambda:(1000,1) if 'sum(pg_column_size' in query else (True,))
        conn.execute.side_effect=execute
        with patch.object(m,'inspect',return_value=snapshot()),patch.object(m,'connect',return_value=conn),self.assertRaisesRegex(RuntimeError,'statement timeout'):
            m.reclaim(full=False)
        self.assertFalse(any('advisory' in c.args[0] for c in conn.execute.call_args_list))
        self.assertTrue(conn.__exit__.called)

    def test_routine_cleanup_allows_a_concurrent_publication(self):
        conn=connection();conn.execute.side_effect=lambda q,*a:Mock(fetchone=lambda:(1000,1))
        before=snapshot();after=copy.deepcopy(before);after['published']['run_id']='new-publication'
        with patch.object(m,'inspect',side_effect=[before,after]),patch.object(m,'connect',return_value=conn):
            result=m.reclaim(full=False)
        self.assertTrue(result['concurrent_update'])
        self.assertEqual(result['after']['published']['run_id'],'new-publication')

    def test_reclaim_is_bounded_session_autocommit_and_lp_table_only(self):
        conn=connection();conn.execute.side_effect=lambda q,*a:Mock(fetchone=lambda:(1000,1) if 'sum(pg_column_size' in q else (True,))
        before=snapshot()
        with patch.object(m,'inspect',side_effect=[before,copy.deepcopy(before)]),patch.object(m,'connect',return_value=conn) as factory:
            m.reclaim()
        factory.assert_called_once_with(session=True,autocommit=True)
        queries=[c.args[0] for c in conn.execute.call_args_list]
        self.assertIn('VACUUM (FULL, ANALYZE) '+m.TABLE,queries)
        self.assertFalse(any('program_state' in q for q in queries))
        self.assertIn("SET statement_timeout='180s'",queries)
        self.assertTrue(any('pg_advisory_unlock' in q for q in queries))
        huge=snapshot();huge['rows'][1]['stored_bytes']=m.MAX_REWRITE_BYTES+1
        with patch.object(m,'inspect',return_value=huge),patch.object(m,'connect') as factory,self.assertRaises(m.MaintenanceError):m.reclaim()
        factory.assert_not_called()


if __name__=='__main__':unittest.main()
