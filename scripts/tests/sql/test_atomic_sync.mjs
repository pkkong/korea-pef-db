// PostgreSQL 17 (WASM) integration tests: real constraints, functions and rollback.
// No live Supabase credentials, database files, or production writes are used.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { PGlite } from '@electric-sql/pglite';
import { pgcrypto } from '@electric-sql/pglite/contrib/pgcrypto';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const python = spawnSync(process.env.PYTHON_EXECUTABLE || 'python3', ['-c', `
import json,runpy,tempfile
from pathlib import Path
from copy import deepcopy
from services.newsletter.src import sync_newsletter_canonical_supabase as news
from services.gp.src import sync_fss_canonical_supabase as gp
n=runpy.run_path('services/newsletter/tests/test_canonical_supabase.py')
with tempfile.TemporaryDirectory() as temp:
 p=Path(temp)/'sample.sqlite';n['seed_database'](p);canonical=news.prepare_payload(p)
f=runpy.run_path('services/gp/tests/test_restore_fss_canonical_supabase.py')
def payload(extra):
 tables={s.supabase_table:f['_rows'](s.supabase_table) for s in gp.FSS_TABLES}
 if extra:
  other=deepcopy(tables['fss_gp_houses'][0]);other.update(gp_id=2,gp_name='Merged-away',gp_name_norm='merged-away');tables['fss_gp_houses'].append(other)
 snapshot=f['_snapshot']();snapshot['status']='staged'
 gp._version_fss_snapshot(snapshot,tables,{'registry_sha256':'sample','alias_rules_sha256':str(extra)})
 people={s.supabase_table:f['_rows'](s.supabase_table) for s in gp.PEOPLE_TABLES}
 state={'state_key':True,'fss_snapshot_id':snapshot['snapshot_id'],'source_hash':gp._person_source_hash(people)}
 return {'snapshot':snapshot,'tables':tables,'people':people,'state':state}
import sys
from unittest.mock import MagicMock
sys.path.insert(0,str(Path('services/lp/src').resolve()))
from publish_lp_programs import store_documents, store_collection_report
base={'url':'https://example.test/lp/a','title':'한국 공고','zero':0,'flag':False,'optional':None,'literal':chr(92)+'u0000','checked_at':'first'}
def lp_queries(docs):
 conn=MagicMock();cursor=conn.cursor.return_value.__enter__.return_value
 store_documents(conn,{'notices':docs},{},lambda value:value)
 return [{'sql':call.args[0],'params':list(call.args[1])} for call in cursor.execute.call_args_list]
lp_documents={'versions':lp_queries([base,{**base,'checked_at':'second'},{**base,'title':'변경 공고'}]),
 'rollback':lp_queries([{'url':'https://example.test/lp/new/'+str(i),'value':i} for i in range(25)]+[{'url':None,'value':'invalid'}]),'base':base}
lp_report_value={'text':'한😀abc'*150000,'zero':0,'false':False,'null':None,'literal':chr(92)+'u0000'}
lp_report_json=json.dumps(lp_report_value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
report_conn=MagicMock()
store_collection_report(report_conn,lp_report_json,'lp-chunk-test','kgrowth')
lp_report={'value':lp_report_value,'queries':[{'sql':c.args[0],'params':list(c.args[1]) if len(c.args)>1 else []} for c in report_conn.execute.call_args_list]}
print(json.dumps({'canonical':canonical,'old':payload(True),'new':payload(False),'lp_documents':lp_documents,'lp_report':lp_report},ensure_ascii=False))
`], {cwd:root,encoding:'utf8',maxBuffer:16*1024*1024});
assert.equal(python.status, 0, python.stderr);
const fixture=JSON.parse(python.stdout);
const db=new PGlite({extensions:{pgcrypto}});
let checks=0;
async function check(name,fn){await fn();checks++;console.log(`PASS ${name}`)}
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
 CREATE SCHEMA storage; CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);`);
const migrations=['20260616090000_newsletter_read_model.sql','20260903090000_newsletter_canonical_collection.sql',
 '20260906090000_newsletter_atomic_sync.sql','20261008090000_newsletter_sync_linear_validation.sql','20260828100000_fss_people_canonical_data.sql','20260906100000_gp_canonical_safe_publish.sql','20260907110000_gp_people_safeupdate_predicate.sql'];
for(const name of migrations) await db.exec(fs.readFileSync(path.join(root,'services/newsletter/supabase/migrations',name),'utf8'));
// Applying new migrations again must preserve already installed objects.
for(const name of migrations.filter(x=>x>='20260906'))await db.exec(fs.readFileSync(path.join(root,'services/newsletter/supabase/migrations',name),'utf8'));
async function stage(model,payload){
 const id=randomUUID(), counts={};
 for(const [table,rows] of Object.entries(payload)){
  counts[table]=rows.length;
  for(let i=0;i<rows.length;i+=100)await db.query('INSERT INTO newsletter_sync_parts(sync_id,model,table_name,part_no,rows) VALUES ($1,$2,$3,$4,$5)',[id,model,table,i/100,JSON.stringify(rows.slice(i,i+100))]);
 }
 return {id,model,counts};
}
async function commit(s){return (await db.query('SELECT publish_newsletter_sync($1,$2,$3) result',[s.id,s.model,JSON.stringify(s.counts)])).rows[0].result}
async function rows(table){return (await db.query(`SELECT * FROM ${table} ORDER BY 1,2`)).rows}
const publicPayload={issues:[{issue_date:'2026-09-05',article_count:1},{issue_date:'2026-09-04',article_count:0}],articles:[{normalized_url:'https://example.com/a',source_url:'https://example.com/a',title:'Old'}],issue_articles:[{issue_date:'2026-09-05',normalized_url:'https://example.com/a',rank:0,section_order:0}],tags:[{normalized_url:'https://example.com/a',tag_type:'section',tag_value:'GP',tag_source:'archive'}],entities:[]};
await check('public publication preserves zero sections and empty issue',async()=>{
 const s=await stage('public',publicPayload);assert.deepEqual(await commit(s),s.counts);
 assert.equal((await rows('newsletter_issues')).length,2);
 assert.equal((await rows('newsletter_public_issue_articles'))[0].section_order,0);
 assert.deepEqual(await commit(s),s.counts); // lost HTTP response retry
});
await check('public late failure rolls back deletion, content update, and links',async()=>{
 const before=await rows('newsletter_public_issue_articles');const tags=await rows('newsletter_article_tags');
 const p=structuredClone(publicPayload);p.articles[0].title='New';p.tags[0].tag_type=null;
 await assert.rejects(commit(await stage('public',p)),/not-null/);
 assert.deepEqual(await rows('newsletter_public_issue_articles'),before);assert.deepEqual(await rows('newsletter_article_tags'),tags);
});
await check('incomplete staging never modifies public data',async()=>{
 const s=await stage('public',publicPayload);s.counts.articles++;
 await assert.rejects(commit(s),/Incomplete/);assert.equal((await rows('newsletter_articles'))[0].title,'Old');
});
await check('public count mismatch rolls back all issue changes',async()=>{
 const p=structuredClone(publicPayload);p.issues[0].article_count=7;
 await assert.rejects(commit(await stage('public',p)),/count mismatch/);
 assert.equal((await db.query("SELECT article_count FROM newsletter_issues WHERE issue_date='2026-09-05'")).rows[0].article_count,1);
});
await check('canonical roundtrip persists typed private rows and links',async()=>{
 await commit(await stage('canonical',fixture.canonical));
 assert.equal((await rows('newsletter_canonical_documents'))[0].title,'테스트 기사');
 assert.equal((await rows('newsletter_canonical_tags')).length,1);
});
await check('canonical late link error preserves old documents, tags and entities',async()=>{
 const before=await rows('newsletter_canonical_documents');const tags=await rows('newsletter_canonical_tags');const entities=await rows('newsletter_canonical_entity_links');
 const p=structuredClone(fixture.canonical);p.newsletter_canonical_documents[0].title='Changed';p.newsletter_canonical_entity_links[0].entity_ref=null;
 await assert.rejects(commit(await stage('canonical',p)),/not-null/);
 assert.deepEqual(await rows('newsletter_canonical_documents'),before);assert.deepEqual(await rows('newsletter_canonical_tags'),tags);assert.deepEqual(await rows('newsletter_canonical_entity_links'),entities);
});
await check('canonical partial payload preserves untouched document links',async()=>{
 const p=Object.fromEntries(Object.keys(fixture.canonical).map(k=>[k,[]]));
 await commit(await stage('canonical',p));assert.equal((await rows('newsletter_canonical_tags')).length,1);
});
await check('canonical orphan and null document links roll back all writes',async()=>{
 const before=await rows('newsletter_canonical_documents'),tags=await rows('newsletter_canonical_tags'),entities=await rows('newsletter_canonical_entity_links');
 for(const missingId of [999999,null]){
  const p=structuredClone(fixture.canonical);p.newsletter_canonical_documents[0].title='Must roll back';
  p.newsletter_canonical_tags.push({...p.newsletter_canonical_tags[0],tag_id:999999,news_id:missingId});
  const s=await stage('canonical',p);
  await assert.rejects(commit(s),/outside this sync/);
  assert.deepEqual(await rows('newsletter_canonical_documents'),before);
  assert.deepEqual(await rows('newsletter_canonical_tags'),tags);
  assert.deepEqual(await rows('newsletter_canonical_entity_links'),entities);
  assert.equal((await db.query('SELECT count(*)::int n FROM newsletter_sync_receipts WHERE sync_id=$1',[s.id])).rows[0].n,0);
 }
});
function historyPayload(count){
 const p=Object.fromEntries(Object.keys(fixture.canonical).map(k=>[k,[]]));
 const template=fixture.canonical.newsletter_canonical_documents[0];
 for(let i=0;i<count;i++){
  const news_id=10000+i;
  p.newsletter_canonical_documents.push({...template,news_id,source_url:`https://example.com/history/${i}`,normalized_source_url:`https://example.com/history/${i}`,body_text:'An article body with deal and fund information. '.repeat(100),raw_payload:{feed_item:{description:'Original feed context. '.repeat(100)}}});
  for(let j=0;j<3;j++)p.newsletter_canonical_tags.push({tag_id:10000+i*3+j,news_id,tag_type:'topic',tag_value:`topic-${j}`,tag_source:'taxonomy'});
 }
 return p;
}
await check('canonical 2000 documents and 6000 tags commit and replay safely',async()=>{
 const p=historyPayload(2000),s=await stage('canonical',p),started=performance.now();
 assert.deepEqual(await commit(s),s.counts);
 console.log(`INFO canonical 2000 document / 6000 tag commit: ${Math.round(performance.now()-started)} ms`);
 assert.equal((await db.query('SELECT count(*)::int n FROM newsletter_canonical_documents')).rows[0].n,2001);
 assert.equal((await db.query('SELECT count(*)::int n FROM newsletter_canonical_tags')).rows[0].n,6001);
 assert.equal((await db.query('SELECT count(*)::int n FROM newsletter_sync_parts WHERE sync_id=$1',[s.id])).rows[0].n,0);
 assert.deepEqual(await commit(s),s.counts);
 await assert.rejects(commit({...s,counts:{...s.counts,newsletter_canonical_tags:6001}}),/receipt does not match/);
});
await check('canonical membership decodes document IDs once with a hash join',async()=>{
 const p=historyPayload(2000);
 const result=await db.query(`EXPLAIN (ANALYZE, FORMAT JSON)
 WITH document_ids AS MATERIALIZED (
  SELECT d.news_id FROM jsonb_to_recordset($1::jsonb) AS d(news_id BIGINT)
 ), link_ids AS (
  SELECT t.news_id FROM jsonb_to_recordset($2::jsonb) AS t(news_id BIGINT)
  UNION ALL SELECT e.news_id FROM jsonb_to_recordset($3::jsonb) AS e(news_id BIGINT)
 ) SELECT 1 FROM link_ids links LEFT JOIN document_ids documents USING (news_id)
 WHERE documents.news_id IS NULL`,[JSON.stringify(p.newsletter_canonical_documents),JSON.stringify(p.newsletter_canonical_tags),'[]']);
 const plan=result.rows[0]['QUERY PLAN'][0],nodes=[];
 function walk(node){nodes.push(node);for(const child of node.Plans||[])walk(child)}walk(plan.Plan);
 assert.ok(nodes.some(n=>n['Node Type']==='Hash Join'),JSON.stringify(plan));
 const documentScan=nodes.find(n=>n['Node Type']==='Function Scan'&&n.Alias==='d');
 assert.equal(documentScan['Actual Loops'],1);
 assert.equal(documentScan['Actual Rows'],2000);
 console.log(`INFO membership plan: document scan once; hash join; ${plan['Execution Time']} ms`);
});
await check('canonical changed-document sync retains untouched history and entities',async()=>{
 const before=(await db.query('SELECT * FROM newsletter_canonical_documents WHERE news_id=10001')).rows;
 const beforeTags=(await db.query('SELECT * FROM newsletter_canonical_tags WHERE news_id=10001 ORDER BY tag_id')).rows;
 const beforeEntities=await rows('newsletter_canonical_entity_links');
 const p=historyPayload(1);p.newsletter_canonical_documents[0].title='Updated existing document';
 p.newsletter_canonical_tags=p.newsletter_canonical_tags.slice(0,1);
 await commit(await stage('canonical',p));
 assert.equal((await db.query('SELECT title FROM newsletter_canonical_documents WHERE news_id=10000')).rows[0].title,'Updated existing document');
 assert.equal((await db.query('SELECT count(*)::int n FROM newsletter_canonical_tags WHERE news_id=10000')).rows[0].n,1);
 assert.deepEqual((await db.query('SELECT * FROM newsletter_canonical_documents WHERE news_id=10001')).rows,before);
 assert.deepEqual((await db.query('SELECT * FROM newsletter_canonical_tags WHERE news_id=10001 ORDER BY tag_id')).rows,beforeTags);
 assert.deepEqual(await rows('newsletter_canonical_entity_links'),beforeEntities);
});
await check('canonical links to existing history outside this sync cannot change data',async()=>{
 const before=(await db.query('SELECT * FROM newsletter_canonical_documents WHERE news_id=41')).rows;
 const historyTags=(await db.query('SELECT * FROM newsletter_canonical_tags WHERE news_id=10001 ORDER BY tag_id')).rows;
 const p=structuredClone(fixture.canonical);p.newsletter_canonical_documents[0].title='Must roll back';
 p.newsletter_canonical_tags.push({...p.newsletter_canonical_tags[0],tag_id:999998,news_id:10001});
 await assert.rejects(commit(await stage('canonical',p)),/outside this sync/);
 assert.deepEqual((await db.query('SELECT * FROM newsletter_canonical_documents WHERE news_id=41')).rows,before);
 assert.deepEqual((await db.query('SELECT * FROM newsletter_canonical_tags WHERE news_id=10001 ORDER BY tag_id')).rows,historyTags);
});
await check('newsletter performance migration reapplies without changing published data',async()=>{
 const beforeDocuments=(await db.query('SELECT count(*)::int n FROM newsletter_canonical_documents')).rows;
 const beforeTags=(await db.query('SELECT count(*)::int n FROM newsletter_canonical_tags')).rows;
 const beforePublic=await rows('newsletter_public_issue_articles');
 await db.exec(fs.readFileSync(path.join(root,'services/newsletter/supabase/migrations/20261008090000_newsletter_sync_linear_validation.sql'),'utf8'));
 assert.deepEqual((await db.query('SELECT count(*)::int n FROM newsletter_canonical_documents')).rows,beforeDocuments);
 assert.deepEqual((await db.query('SELECT count(*)::int n FROM newsletter_canonical_tags')).rows,beforeTags);
 assert.deepEqual(await rows('newsletter_public_issue_articles'),beforePublic);
 const p=Object.fromEntries(Object.keys(fixture.canonical).map(k=>[k,[]])),s=await stage('canonical',p);
 assert.deepEqual(await commit(s),s.counts);assert.deepEqual(await commit(s),s.counts);
});
await check('anonymous callers cannot publish or read staging',async()=>{
 await db.exec('SET ROLE anon');
 try{await assert.rejects(db.query('SELECT publish_newsletter_sync($1,$2,$3)',[randomUUID(),'public','{}']),/permission denied/);
 await assert.rejects(db.query('SELECT * FROM newsletter_sync_parts'),/permission denied/);
 }finally{await db.exec('RESET ROLE')}
});
async function stageFss(p){
 await db.query('INSERT INTO fss_canonical_snapshots SELECT * FROM jsonb_populate_record(NULL::fss_canonical_snapshots,$1)',[JSON.stringify({...p.snapshot,created_at:'2026-09-06',updated_at:'2026-09-06'})]);
 for(const [table,entries] of Object.entries(p.tables))if(entries.length)await db.query(`INSERT INTO ${table} SELECT * FROM jsonb_populate_recordset(NULL::${table},$1)`,[JSON.stringify(entries)]);
}
async function replacePeople(p,publish=true){return db.query('SELECT replace_people_canonical($1,$2,$3)',[JSON.stringify(p.people),JSON.stringify(p.state),publish?p.snapshot.snapshot_id:null])}
await check('FSS Python content digests agree with PostgreSQL typed records',async()=>{
 await stageFss(fixture.old);await replacePeople(fixture.old);
 assert.equal((await rows('fss_canonical_snapshots'))[0].status,'published');
});
await check('People late foreign-key failure rolls back all tables and state',async()=>{
 const before=await rows('people_persons'),roles=await rows('people_roles'),state=await rows('people_data_state');
 const p=structuredClone(fixture.old);p.people.people_persons[0].person_name_ko='Changed';p.people.people_roles[0].person_id=999;
 await assert.rejects(replacePeople(p,false),/foreign key/);
 assert.deepEqual(await rows('people_persons'),before);assert.deepEqual(await rows('people_roles'),roles);assert.deepEqual(await rows('people_data_state'),state);
});
await check('FSS partial upload fails publication and preserves previous People',async()=>{
 const p=structuredClone(fixture.new);await stageFss(p);
 await db.query('DELETE FROM fss_fund_events WHERE snapshot_id=$1',[p.snapshot.snapshot_id]);
 p.people.people_persons[0].person_name_ko='Changed';const before=await rows('people_persons');
 await assert.rejects(replacePeople(p),/manifest mismatch/);
 assert.deepEqual(await rows('people_persons'),before);
 assert.equal((await rows('fss_canonical_snapshots')).find(x=>x.snapshot_id===fixture.old.snapshot.snapshot_id).status,'published');
 await db.query('INSERT INTO fss_fund_events SELECT * FROM jsonb_populate_recordset(NULL::fss_fund_events,$1)',[JSON.stringify(p.tables.fss_fund_events)]);
});
await check('corrected same-source snapshot drops removed GP without changing history',async()=>{
 assert.notEqual(fixture.new.snapshot.snapshot_id,fixture.old.snapshot.snapshot_id);
 await replacePeople(fixture.new);await replacePeople(fixture.new); // idempotent retry
 const gp=await rows('fss_gp_houses');assert.equal(gp.filter(x=>x.snapshot_id===fixture.new.snapshot.snapshot_id).length,1);
 assert.equal(gp.filter(x=>x.snapshot_id===fixture.old.snapshot.snapshot_id).length,2);
 assert.equal((await rows('fss_canonical_snapshots')).find(x=>x.snapshot_id===fixture.old.snapshot.snapshot_id).status,'retired');
});
await check('published and retired FSS rows cannot be mutated',async()=>{
 for(const p of [fixture.old,fixture.new]){
  await assert.rejects(db.query('UPDATE fss_gp_houses SET gp_name=$1 WHERE snapshot_id=$2',['Tampered',p.snapshot.snapshot_id]),/immutable/);
  await assert.rejects(db.query('DELETE FROM fss_gp_houses WHERE snapshot_id=$1',[p.snapshot.snapshot_id]),/immutable/);
 }
});
await check('People cannot be overwritten from a retired FSS source',async()=>{
 const before=await rows('people_persons');await assert.rejects(replacePeople(fixture.old,false),/current published/);assert.deepEqual(await rows('people_persons'),before);
});
// Exercise the exact publisher statement and serialized parameters, not a SQL copy.
await db.exec(fs.readFileSync(path.join(root,'services/lp/supabase/migrations/20260921090000_lp_program_collection.sql'),'utf8'));
async function lpExecute(batch){
 assert.equal((batch.sql.match(/%s/g)||[]).length,1);
 return db.query(batch.sql.replace('%s','$1'),batch.params);
}
await check('LP actual document SQL preserves values, versions and idempotent replay',async()=>{
 for(const batch of fixture.lp_documents.versions)await lpExecute(batch);
 const first=(await db.query('SELECT source_url,content_hash,document FROM lp_program_private.documents ORDER BY content_hash')).rows;
 assert.equal(first.length,2);
 assert.deepEqual(first.find(r=>r.document.title==='한국 공고').document,fixture.lp_documents.base);
 const changed=first.find(r=>r.document.title==='변경 공고').document;
 assert.equal(changed.zero,0);assert.equal(changed.flag,false);assert.equal(changed.optional,null);
 assert.equal(changed.literal,fixture.lp_documents.base.literal);
 for(const batch of fixture.lp_documents.versions)await lpExecute(batch);
 assert.deepEqual((await db.query('SELECT source_url,content_hash,document FROM lp_program_private.documents ORDER BY content_hash')).rows,first);
});
await check('LP later invalid document batch rolls back earlier batch and public state',async()=>{
 await db.query("INSERT INTO lp_program_private.collection_runs(run_id,institution,report) VALUES ('lp-test','kgrowth','{}')");
 await db.query("INSERT INTO lp_program_private.program_state(id,data,pages,run_id) VALUES (1,'{}','{\"index.html\":\"preserved\"}','lp-test')");
 const before=(await db.query('SELECT * FROM lp_program_private.documents ORDER BY content_hash')).rows;
 const state=(await db.query('SELECT * FROM lp_program_private.program_state')).rows;
 assert.equal(fixture.lp_documents.rollback.length,2);
 await db.exec('BEGIN');
 await lpExecute(fixture.lp_documents.rollback[0]);
 await db.query("UPDATE lp_program_private.program_state SET pages='{\"index.html\":\"uncommitted\"}'");
 await assert.rejects(lpExecute(fixture.lp_documents.rollback[1]),/null value.*source_url|not-null constraint/i);
 await db.exec('ROLLBACK');
 assert.deepEqual((await db.query('SELECT * FROM lp_program_private.documents ORDER BY content_hash')).rows,before);
 assert.deepEqual((await db.query('SELECT * FROM lp_program_private.program_state')).rows,state);
});
await check('LP raw document evidence remains inaccessible to anon',async()=>{
 await db.exec('SET ROLE anon');
 try {await assert.rejects(db.query('SELECT document FROM lp_program_private.documents'),/permission denied/);}
 finally {await db.exec('RESET ROLE');}
});
async function lpReportExecute(batch){
 let index=0;const sql=batch.sql.replace(/%s/g,()=>'$'+(++index));
 assert.equal(index,batch.params.length);
 return db.query(sql,batch.params);
}
await check('LP actual chunked report SQL preserves multibyte JSON and drops temp state',async()=>{
 const chunks=fixture.lp_report.queries.filter(q=>q.sql.startsWith('INSERT INTO pg_temp.'));
 assert.ok(chunks.length>=2,'Large UTF-8 fixture must cross a chunk boundary');
 for(const q of chunks)assert.ok(Buffer.byteLength(q.params[1],'utf8')<=1024*1024);
 await db.exec('BEGIN');
 for(const batch of fixture.lp_report.queries)await lpReportExecute(batch);
 assert.deepEqual((await db.query("SELECT report FROM lp_program_private.collection_runs WHERE run_id='lp-chunk-test'")).rows[0].report,fixture.lp_report.value);
 await db.exec('COMMIT');
 assert.equal((await db.query("SELECT to_regclass('pg_temp.lp_collection_report_parts') AS name")).rows[0].name,null);
});
await check('LP chunked report and later document/state changes roll back together',async()=>{
 const before=(await db.query('SELECT * FROM lp_program_private.collection_runs ORDER BY run_id')).rows;
 const docs=(await db.query('SELECT * FROM lp_program_private.documents ORDER BY content_hash')).rows;
 const state=(await db.query('SELECT * FROM lp_program_private.program_state')).rows;
 await db.exec('BEGIN');
 for(const batch of fixture.lp_report.queries){
  const copy={sql:batch.sql,params:batch.params.map(v=>v==='lp-chunk-test'?'lp-rollback-test':v)};
  await lpReportExecute(copy);
 }
 await lpExecute(fixture.lp_documents.rollback[0]);
 await db.query("UPDATE lp_program_private.program_state SET run_id='lp-rollback-test',pages='{\"index.html\":\"uncommitted\"}'");
 await assert.rejects(lpExecute(fixture.lp_documents.rollback[1]),/null value.*source_url|not-null constraint/i);
 await db.exec('ROLLBACK');
 assert.deepEqual((await db.query('SELECT * FROM lp_program_private.collection_runs ORDER BY run_id')).rows,before);
 assert.deepEqual((await db.query('SELECT * FROM lp_program_private.documents ORDER BY content_hash')).rows,docs);
 assert.deepEqual((await db.query('SELECT * FROM lp_program_private.program_state')).rows,state);
 assert.equal((await db.query("SELECT to_regclass('pg_temp.lp_collection_report_parts') AS name")).rows[0].name,null);
});
await check('LP archived report input remains private after chunked insertion',async()=>{
 await db.exec('SET ROLE anon');
 try {await assert.rejects(db.query('SELECT report FROM lp_program_private.collection_runs'),/permission denied/);}
 finally {await db.exec('RESET ROLE');}
});
await db.close();
console.log(`${checks} PostgreSQL integration checks passed`);
