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
print(json.dumps({'canonical':canonical,'old':payload(True),'new':payload(False)},ensure_ascii=False))
`], {cwd:root,encoding:'utf8'});
assert.equal(python.status, 0, python.stderr);
const fixture=JSON.parse(python.stdout);
const db=new PGlite({extensions:{pgcrypto}});
let checks=0;
async function check(name,fn){await fn();checks++;console.log(`PASS ${name}`)}
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
 CREATE SCHEMA storage; CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);`);
const migrations=['20260616090000_newsletter_read_model.sql','20260903090000_newsletter_canonical_collection.sql',
 '20260906090000_newsletter_atomic_sync.sql','20260828100000_fss_people_canonical_data.sql','20260906100000_gp_canonical_safe_publish.sql'];
for(const name of migrations) await db.exec(fs.readFileSync(path.join(root,'services/newsletter/supabase/migrations',name),'utf8'));
// Applying new migrations again must preserve already installed objects.
for(const name of migrations.filter(x=>x.startsWith('20260906')))await db.exec(fs.readFileSync(path.join(root,'services/newsletter/supabase/migrations',name),'utf8'));
async function stage(model,payload){
 const id=randomUUID(), counts={};
 for(const [table,rows] of Object.entries(payload)){
  counts[table]=rows.length;
  for(let i=0;i<rows.length;i++)await db.query('INSERT INTO newsletter_sync_parts(sync_id,model,table_name,part_no,rows) VALUES ($1,$2,$3,$4,$5)',[id,model,table,i,JSON.stringify([rows[i]])]);
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
await db.close();
console.log(`${checks} PostgreSQL integration checks passed`);
