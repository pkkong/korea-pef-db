import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from services.lp.src import collect_lp_history_bodies as h
from services.lp.tests.test_lp_history_body_queue import state
from services.lp.src.lp_history_body_queue import plan


def detail(row, body='공식 본문', attachment=False):
    link='<a href="down_file.asp?idx='+row['source_id']+'">첨부</a>' if attachment else ''
    return (f'<html><body><div class="view_info"><p class="tit">{row["title"]}</p>'
            f'<p class="date">{row["date"]}</p></div><div class="veiw_contents">{body}</div>{link}</body></html>').encode('cp949')


class Result:
    def __init__(self,rows): self.rows=rows
    def fetchone(self): return self.rows[0]
    def fetchall(self): return self.rows


class Cursor:
    def __init__(self,conn): self.conn=conn
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,sql,args):
        if not sql.startswith('INSERT INTO lp_program_private.documents'):
            raise AssertionError('Unexpected write')
        for row in json.loads(args[0]):
            self.conn.documents.setdefault((row['source_url'],row['content_hash']),row['document'])


class Connection:
    def __init__(self): self.documents={};self.guards=0;self.change_public=False
    def cursor(self): return Cursor(self)
    def execute(self,sql,args=None):
        if sql.startswith('SELECT run_id,md5'):
            self.guards+=1
            return Result([('run','state','changed' if self.change_public and self.guards>1 else 'pages')])
        if sql.startswith('SELECT count(*),md5'): return Result([(0,'reviews')])
        if sql.startswith('SELECT count(*) FROM lp_program_private.documents'): return Result([(len(self.documents),)])
        if sql.startswith('SELECT source_url,content_hash'): return Result([k for k in self.documents if k[0] in args[0]])
        if sql.startswith(('SET ','SELECT pg_advisory_xact_lock')): return Result([])
        raise AssertionError('Unexpected SQL: '+sql)


class HistoricalBodyTests(unittest.TestCase):
    def prepare(self):
        s=state();rows=plan(s)['rows'];calls=[]
        def fetch(url):
            calls.append(url)
            row=next(r for r in rows if r['url']==url)
            return detail(row,attachment=True)
        return s,fetch,calls

    def test_collects_oldest_four_with_raw_proof_and_never_fetches_attachments(self):
        s,fetch,calls=self.prepare();before=copy.deepcopy(s)
        report=h.collect(s,None,fetch)
        self.assertEqual(len(calls),4);self.assertTrue(all('notice_view.asp?' in u for u in calls))
        self.assertEqual(report['batches'][0]['new_ids'],['9','12','90','95'])
        self.assertEqual(report['batches'][0]['attachment_requests'],0)
        self.assertTrue(all(n['attachment_collection_status']=='pending' for n in report['documents']))
        self.assertEqual(h.validate_report(s,report)['pending_count'],0)
        resumed=h.collect(s,report,lambda u:self.fail('completed body must not be fetched again'))
        self.assertEqual(resumed['batches'][-1]['detail_requests'],0);self.assertEqual(s,before)

    def test_bad_raw_hash_body_date_and_title_fail_independent_replay(self):
        s,fetch,_=self.prepare();report=h.collect(s,None,fetch)
        for change in ('hash','body','date','title','unknown'):
            bad=copy.deepcopy(report);doc=bad['documents'][0]
            if change=='hash': doc['discovery_provenance']['detail_response_sha256']='a'*64
            elif change=='unknown':doc['selected_gps']=['made up']
            else:doc[change]='changed'
            with self.subTest(change=change),self.assertRaises(ValueError):h.validate_report(s,bad)

    def test_failed_source_keeps_completed_evidence_and_blocks_database_write(self):
        s,fetch,_=self.prepare();calls=[]
        def fail(url):
            calls.append(url)
            if len(calls)>1:raise TimeoutError('bounded failure')
            return fetch(url)
        report=h.collect(s,None,fail)
        self.assertEqual(len(report['documents']),1);self.assertTrue(report['holds'])
        with self.assertRaises(ValueError): h.persist(Connection(),s,report,wrap_json=lambda x:x)
        for raw in (b'<html>partial',detail(plan(s)['rows'][0],body='열람 권한이 없습니다')):
            with self.assertRaises(ValueError):h.read_body('9',raw)

    def test_retention_is_idempotent_and_preserves_public_state(self):
        s,fetch,_=self.prepare();report=h.collect(s,None,fetch);conn=Connection()
        first=h.persist(conn,s,report,wrap_json=lambda x:x)
        second=h.persist(conn,s,report,wrap_json=lambda x:x)
        self.assertEqual(first['new_document_versions'],4);self.assertEqual(second['new_document_versions'],0)
        self.assertEqual(first['before'],first['after']);self.assertFalse(first['published'])
        stored=list(conn.documents.values())
        legacy=copy.deepcopy(stored[0]);del legacy['discovery_provenance']
        cached=h.collect(s,None,lambda u:self.fail('existing database body must be reused'),
                         cached_documents=[legacy]+stored)
        self.assertEqual(cached['batches'][-1]['detail_requests'],0)
        self.assertEqual(len(cached['batches'][-1]['reused_database_ids']),4)
        cached_retention=h.persist(conn,s,cached,wrap_json=lambda x:x)
        self.assertEqual(cached_retention['new_document_versions'],0)
        self.assertEqual(cached_retention['reused_database_documents'],4)
        conn=Connection();conn.change_public=True
        with self.assertRaisesRegex(ValueError,'Public state'):h.persist(conn,s,report,wrap_json=lambda x:x)
        bad=copy.deepcopy(report);bad['batches'][-1]['planned_ids']=[]
        with self.assertRaises(ValueError):h.persist(Connection(),s,bad,wrap_json=lambda x:x)


if __name__=='__main__':unittest.main()
