import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1]/'src'
sys.path.insert(0,str(SRC))
from publish_lp_programs import prepare, document_hash, clean_database_text, source_index, store_documents, store_public_state, store_collection_report

class PublishContracts(unittest.TestCase):
    def test_complete_report_uses_bounded_utf8_parts_in_same_transaction(self):
        from unittest.mock import Mock
        conn = Mock()
        report = {'body':'한글🙂'*190000,'zero':0,'flag':False,'null':None,'literal':r'\u0000'}
        encoded = json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        with patch('publish_lp_programs.publication_phase'):
            store_collection_report(conn, encoded, 'report-run', 'multi_lp')
        calls = conn.execute.call_args_list
        self.assertIn('ON COMMIT DROP', calls[0].args[0])
        parts = [c.args[1] for c in calls if 'INSERT INTO pg_temp.lp_collection_report_parts' in c.args[0]]
        self.assertGreater(len(parts), 1)
        self.assertEqual([n for n, _ in parts], list(range(len(parts))))
        self.assertTrue(all(len(p.encode('utf-8')) <= 1024*1024 for _, p in parts))
        self.assertEqual(json.loads(''.join(p for _, p in parts)), report)
        self.assertIn("string_agg(payload,'' ORDER BY seq)::jsonb", calls[-1].args[0])
        self.assertEqual(calls[-1].args[1], ('report-run', 'multi_lp'))
        conn.commit.assert_not_called(); conn.pipeline.assert_not_called()

    def test_report_chunk_failure_does_not_reassemble_or_write_public_state(self):
        from unittest.mock import MagicMock
        from publish_lp_programs import publish_prepared
        conn=MagicMock();conn.__enter__.return_value=conn
        parts = []
        def execute(query, params=None):
            if 'INSERT INTO pg_temp.lp_collection_report_parts' in query:
                parts.append(params)
                if len(parts)==2:raise RuntimeError('part failed')
        conn.execute.side_effect=execute
        with patch('publish_lp_programs.connect',return_value=conn), \
             patch('publish_lp_programs.publication_revision',return_value='same'), \
             patch('publish_lp_programs.store_documents') as documents, \
             patch('publish_lp_programs.store_public_state') as state, \
             patch('publish_lp_programs.publication_phase'), self.assertRaisesRegex(RuntimeError,'part failed'):
            publish_prepared({'body':'한'*800000},{},{},'same','multi',wrap_json=lambda x:x)
        documents.assert_not_called();state.assert_not_called();conn.commit.assert_not_called()
        self.assertFalse(any('INSERT INTO lp_program_private.collection_runs' in c.args[0] for c in conn.execute.call_args_list))
        self.assertIs(conn.__exit__.call_args.args[0],RuntimeError)

    def test_invalid_report_number_fails_before_opening_write_connection(self):
        from publish_lp_programs import publish_prepared
        with patch('publish_lp_programs.connect') as connect, self.assertRaises(ValueError):
            publish_prepared({'bad':float('nan')},{},{},'same','multi',wrap_json=lambda x:x)
        connect.assert_not_called()

    def test_source_replay_runs_after_read_connection_is_closed(self):
        from unittest.mock import MagicMock
        from publish_lp_programs import prepare_publication
        conn = MagicMock()
        active = []
        conn.__enter__.side_effect = lambda: active.append(True) or conn
        conn.__exit__.side_effect = lambda *args: active.pop()
        def offline(current, report):
            self.assertFalse(active, 'Source replay must not hold a pooled connection')
            return {'programs': []}, {'index.html': 'valid'}
        with patch('publish_lp_programs.connect', return_value=conn), patch('publish_lp_programs.baseline', return_value={}), \
             patch('publish_lp_programs.publication_revision', return_value=('old', [])), \
             patch('publish_lp_programs.prepare', side_effect=offline), patch('publish_lp_programs.publication_phase'):
            self.assertEqual(prepare_publication({})[2], ('old', []))
        self.assertIn('REPEATABLE READ READ ONLY', conn.execute.call_args_list[0].args[0])

    def test_changed_publication_or_review_cannot_write_prepared_results(self):
        from unittest.mock import MagicMock
        from publish_lp_programs import publish_prepared
        old = (('run1', 'stamp1'), [{'id': 1, 'action': 'hold'}])
        changes = [(('run2', 'stamp2'), old[1]), (('run1', 'stamp2'), old[1]),
                   (old[0], [{'id': 1, 'action': 'approve'}]), (old[0], []),
                   (old[0], old[1] + [{'id': 2, 'action': 'exclude'}])]
        for newer in changes:
            with self.subTest(revision=newer):
                conn = MagicMock()
                conn.__enter__.return_value = conn
                def read_after_lock(_):
                    self.assertIn('pg_advisory_xact_lock', conn.execute.call_args.args[0])
                    return newer
                with patch('publish_lp_programs.connect', return_value=conn), \
                     patch('publish_lp_programs.publication_revision', side_effect=read_after_lock), \
                     patch('publish_lp_programs.publication_phase'), self.assertRaisesRegex(RuntimeError, 'changed during'):
                    publish_prepared({}, {'programs': []}, {}, old, 'multi_lp', wrap_json=lambda value: value)
                self.assertTrue(all(not c.args[0].startswith('INSERT') for c in conn.execute.call_args_list))
                self.assertIn('READ COMMITTED', conn.execute.call_args_list[0].args[0])
                self.assertIs(conn.__exit__.call_args.args[0], RuntimeError)

    def test_prepared_storage_failure_rolls_back_evidence_and_public_state_together(self):
        from unittest.mock import MagicMock
        from publish_lp_programs import publish_prepared
        conn = MagicMock()
        conn.__enter__.return_value = conn
        revision = (('same', 'stamp'), [])
        with patch('publish_lp_programs.connect', return_value=conn), \
             patch('publish_lp_programs.publication_revision', return_value=revision), \
             patch('publish_lp_programs.store_documents', return_value=2), \
             patch('publish_lp_programs.store_public_state', side_effect=RuntimeError('state write failed')), \
             patch('publish_lp_programs.publication_phase'), self.assertRaisesRegex(RuntimeError, 'state write failed'):
            publish_prepared({}, {'programs': []}, {}, revision, 'multi_lp', wrap_json=lambda value: value)
        self.assertIs(conn.__exit__.call_args.args[0], RuntimeError)
        self.assertTrue(any(c.args[0].startswith('INSERT INTO lp_program_private.collection_runs') for c in conn.execute.call_args_list))
        conn.commit.assert_not_called()

    def test_public_payload_preserves_unicode_zero_and_literal_escapes(self):
        from unittest.mock import Mock
        conn = Mock()
        data = {'programs': [{'title': '국내 PE 출자', 'count': 0, 'flag': False, 'source': r'\u0000'}]}
        pages = {'index.html': '<h1>출자사업</h1>'}
        with patch('publish_lp_programs.publication_phase'):
            store_public_state(conn, data, pages, 'new-run')
        query, params = conn.execute.call_args.args
        self.assertIn('%s::jsonb', query)
        self.assertEqual(json.loads(params[0]), data)
        self.assertEqual(json.loads(params[1]), pages)
        self.assertIn('국내 PE', params[0])
        self.assertEqual(params[2], 'new-run')
        conn.commit.assert_not_called()

    def test_invalid_public_number_fails_before_writing_or_committing(self):
        from unittest.mock import Mock
        conn = Mock()
        with patch('publish_lp_programs.publication_phase'), self.assertRaises(ValueError):
            store_public_state(conn, {'amount': float('nan')}, {}, 'bad-run')
        conn.execute.assert_not_called()
        conn.commit.assert_not_called()

    def test_batched_evidence_keeps_versions_and_deduplicates_repeated_receipts(self):
        from unittest.mock import MagicMock
        conn=MagicMock();cursor=conn.cursor.return_value.__enter__.return_value
        first={'url':'https://official.example/1','body':'first','checked_at':'earlier','zero':0,'flag':False,'null':None}
        same=dict(first,checked_at='later')
        changed=dict(first,body='corrected')
        docs=[first,same,changed]+[{'url':f'https://official.example/{i}','body':str(i)} for i in range(2,65)]
        count=store_documents(conn,{'notices':docs},{'shared_notices':[{'url':first['url'],'body':'first','original_notices':[]}]},lambda value:value)
        batches=[json.loads(call.args[1][0]) for call in cursor.execute.call_args_list]
        rows=[row for batch in batches for row in batch]
        self.assertEqual(len(rows),count)
        self.assertEqual(len({(row['source_url'],row['content_hash']) for row in rows}),len(rows))
        self.assertEqual(sum(row['source_url']==first['url'] for row in rows),3)
        self.assertEqual(rows[0]['document'],first)
        self.assertEqual(rows[1]['document'],changed)
        self.assertTrue(all(len(batch)<=25 for batch in batches))
        self.assertLess(cursor.execute.call_count,len(rows))
        cursor.executemany.assert_not_called();conn.pipeline.assert_not_called()
        self.assertFalse(conn.commit.called)
        self.assertTrue(all('AS r(source_url text,content_hash text,document jsonb) WHERE true ON CONFLICT DO NOTHING' in call.args[0] for call in cursor.execute.call_args_list))

    def test_bulk_storage_failure_propagates_without_committing_or_writing_public_state(self):
        from unittest.mock import MagicMock
        conn=MagicMock();cursor=conn.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect=RuntimeError('database write failed')
        with self.assertRaisesRegex(RuntimeError,'database write failed'):
            store_documents(conn,{'notices':[{'url':'https://official.example/1','body':'source'}]}, {},lambda value:value)
        self.assertFalse(conn.commit.called)
        self.assertFalse(conn.execute.called)

    def test_document_batches_bound_utf8_bytes_and_keep_oversized_document_whole(self):
        from unittest.mock import MagicMock
        conn=MagicMock();cursor=conn.cursor.return_value.__enter__.return_value
        docs=[{'url':f'https://official.example/{i}','body':'한'*180000} for i in range(3)]
        docs += [{'url':'https://official.example/large','body':'한'*400000},
                 {'url':'https://official.example/last','body':'end'}]
        store_documents(conn,{'notices':docs},{},lambda _:self.fail('document wrapper must not be used'))
        batches=[json.loads(c.args[1][0]) for c in cursor.execute.call_args_list]
        self.assertEqual([r['document'] for b in batches for r in b],docs)
        self.assertEqual(len(batches),5)
        for call,batch in zip(cursor.execute.call_args_list,batches):
            size=len(call.args[1][0].encode('utf-8'))
            if size>1024*1024:
                self.assertEqual(len(batch),1)
                self.assertEqual(batch[0]['document'],docs[3])
        cursor.executemany.assert_not_called();conn.pipeline.assert_not_called();conn.commit.assert_not_called()

    def test_document_statement_failure_prevents_publication_state_write(self):
        from unittest.mock import MagicMock
        from publish_lp_programs import publish_prepared
        conn=MagicMock();conn.__enter__.return_value=conn
        conn.cursor.return_value.__enter__.return_value.execute.side_effect=RuntimeError('write failed')
        with patch('publish_lp_programs.connect',return_value=conn), \
             patch('publish_lp_programs.publication_revision',return_value='same'), \
             patch('publish_lp_programs.store_public_state') as state, \
             patch('publish_lp_programs.publication_phase'), self.assertRaisesRegex(RuntimeError,'write failed'):
            publish_prepared({'notices':[{'url':'https://official.example/1','zero':0}]}, {}, {}, 'same', 'multi',wrap_json=lambda x:x)
        state.assert_not_called();conn.commit.assert_not_called()
        self.assertIs(conn.__exit__.call_args.args[0],RuntimeError)

    def test_source_index_projects_only_notice_identity_without_writes(self):
        from unittest.mock import Mock
        conn = Mock()
        conn.execute.return_value.fetchall.return_value = [(None, 'official title', 'https://www.kgrowth.or.kr/n?id=1')]
        data = source_index(conn)
        self.assertEqual(set(data['notices'][0]), {'institution_id', 'title', 'url'})
        query = conn.execute.call_args.args[0]
        self.assertTrue(query.startswith('SELECT DISTINCT '))
        self.assertNotIn('SELECT *', query)
        self.assertNotIn('body', query)
        self.assertEqual(conn.execute.call_count, 1)

    def test_nested_original_proof_refresh_is_not_a_content_change(self):
        old={'body':'same','original_notices':[{'body':'same original','checked_at':'before',
             'discovery_provenance':{'listing_html':'old counter','listing_sha256':'first'}}]}
        refreshed=copy.deepcopy(old)
        refreshed['original_notices'][0].update(checked_at='after',discovery_provenance={'listing_html':'new counter','listing_sha256':'next'})
        self.assertEqual(document_hash(old),document_hash(refreshed))
        refreshed['original_notices'][0]['body']='changed amount'
        self.assertNotEqual(document_hash(old),document_hash(refreshed))
    def test_database_text_preserves_amount_boundaries_and_literal_escapes(self):
        raw = {'text': ['100\x00200억원\nPE\t모집', r'\u0000'], 'hash': 'original', 'count': 0}
        value = clean_database_text(raw)
        self.assertEqual(value, {'text': ['100 200억원\nPE\t모집', r'\u0000'], 'hash': 'original', 'count': 0})
        self.assertIn('\x00', raw['text'][0])
        with self.assertRaises(ValueError):
            clean_database_text({'bad\x00field': 'evidence'})

    def test_publication_cleans_incoming_and_retained_evidence(self):
        self.report['notices'][0]['body'] = '원문\x00본문'
        self.data['retained_evidence'] = ['100\x00200억원']
        result, pages = prepare(self.data, self.report)
        self.assertEqual(result['tracked_notices'][0]['body'], '원문 본문')
        self.assertEqual(result['retained_evidence'], ['100 200억원'])
        self.assertNotIn('\\u0000', json.dumps(result))
        self.assertFalse(any('\x00' in page for page in pages.values()))

    def test_identical_document_is_not_versioned_again_for_check_time(self):
        doc = {'body':'same', 'attachment_hashes':{'file':'v1'}, 'checked_at':'first'}
        later = dict(doc, checked_at='later')
        self.assertEqual(document_hash(doc), document_hash(later))
        later['attachment_hashes'] = {'file':'v2'}
        self.assertNotEqual(document_hash(doc), document_hash(later))

    def setUp(self):
        self.data=json.loads((SRC.parents[2]/'data/lp_programs_pilot.json').read_text())
        self.p=next(p for p in self.data['programs'] if p['institution_id']=='kgrowth')
        self.report={'checked_at':'2026-09-21','notices':[{'source_id':'1047','title':'공고','date':'2026-09-21','body':'본문','url':'https://www.kgrowth.or.kr/notice_view.asp?idx=1047'}],'programs':[copy.deepcopy(self.p)]}
    def test_review_preserves_program_and_accepted_fingerprint(self):
        self.data['accepted_notices']=[{'source_id':'1047','sha256':'old'}]
        self.report['accepted_notices']=self.data['accepted_notices']
        self.report['requires_review']=True
        self.report['programs'][0]['title']='UNREVIEWED EDIT'
        result,_=prepare(self.data,self.report)
        self.assertEqual(self.data['accepted_notices'],result['accepted_notices'])
        self.assertNotIn('UNREVIEWED EDIT',[p['title'] for p in result['programs']])

    def test_empty_collection_cannot_erase_pages(self):
        self.report['notices']=[]
        with self.assertRaises(ValueError):prepare(self.data,self.report)
    def test_unreviewed_tracking_survives_publication(self):
        self.report['tracked_notices'] = [{'source_id':'9999','sha256':'new'}]
        self.report['requires_review'] = True
        result,_=prepare(self.data,self.report)
        self.assertEqual(self.report['tracked_notices'], result['tracked_notices'])
    def test_unreviewed_program_cannot_be_published(self):
        self.report['programs'][0]['id']='unreviewed'
        with self.assertRaises(ValueError):prepare(self.data,self.report)
    def test_other_institutions_remain_unchanged(self):
        data,pages=prepare(self.data,self.report)
        before={p['id']:p for p in self.data['programs'] if p['institution_id']!='kgrowth'}
        after={p['id']:p for p in data['programs'] if p['institution_id']!='kgrowth'}
        # Renderer may add page_key to a copy; original input must remain intact.
        for p in after.values():
            for gp in p['selected_gps']:gp.pop('page_key',None)
        self.assertEqual(before,after)
        self.assertEqual(5,len([n for n in pages if n.startswith('program-')]))

    def test_priority_program_comes_from_reprojected_evidence_not_collector_payload(self):
        verified=copy.deepcopy(next(p for p in self.data['programs'] if p['institution_id']=='ktcu'))
        verified['status']='접수 마감'
        self.report['priority_sources']={'ktcu':{'notices':[{'source_id':'61742', 'url':'https://www.ktcu.or.kr/PPW-CSB-000101/61742',
                                                              'date':'2026-09-04','title':'공식 모집','body':'공식 본문'}],
                                                 'programs':[{'id':'unreviewed-ktcu','institution_id':'ktcu'}],
                                                 'holds':[]}}
        with patch('publish_lp_programs.project_ktcu',return_value=([verified],[])):
            data,pages=prepare(self.data,self.report)
        self.assertEqual('접수 마감',next(p for p in data['programs'] if p['id']==verified['id'])['status'])
        self.assertNotIn('unreviewed-ktcu',{p['id'] for p in data['programs']})
        self.assertIn('program-ktcu-2026-blind-pef.html',pages)

    def test_priority_source_failure_keeps_last_published_program(self):
        original=copy.deepcopy(next(p for p in self.data['programs'] if p['institution_id']=='koreapost'))
        self.report['priority_sources']={'koreapost':{'notices':[],'programs':[],
                                                       'holds':[{'program_id':original['id'],'reason':'공식 자료 수집 실패'}]}}
        data,_=prepare(self.data,self.report)
        self.assertEqual(original,next(p for p in data['programs'] if p['id']==original['id']))
        self.assertIn('공식 자료 수집 실패',[hold['reason'] for hold in data['program_holds']])

    def test_new_business_candidates_are_recomputed_from_notices(self):
        notice={'source_id':'114023','url':'https://www.koreaexim.go.kr/HPHKBI039M01/114023',
                'date':'2026-05-11','title':'임상3상 특화펀드 위탁운용사 선정계획 공고',
                'body':'공식 출자 공고'}
        self.report['priority_sources']={'kexim':{'notices':[notice], 'programs':[],
                                                  'discovery_candidates':[{'title':'임의 사업'}],
                                                  'holds':[]}}
        candidate={k:notice[k] for k in ('source_id','url','date','title')}
        candidate['institution_id']='kexim'
        with patch('publish_lp_programs.project_kexim',return_value=([],[])), \
             patch('publish_lp_programs.suggest_kexim',return_value=[]), \
             patch('publish_lp_programs.discover_kexim',return_value=[candidate]):
            data,pages=prepare(self.data,self.report)
        self.assertEqual(1,len(data['discovery_candidates']))
        self.assertEqual(candidate['source_id'],data['discovery_candidates'][0]['source_id'])
        self.assertEqual('unknown',data['discovery_candidates'][0]['scope'])
        self.assertEqual('모집 공고',data['discovery_candidates'][0]['stage'])
        self.assertIn('새 출자공고 후보',pages['review.html'])
        self.assertNotIn('임의 사업',pages['review.html'])

    def test_discovered_notice_survives_listing_age_out_or_source_outage(self):
        notice={'source_id':'0041:352','institution_id':'koreapost',
                'url':'https://www.kpasset.go.kr/board.es?mid=a10510000000&bid=0041&act=view&list_no=352',
                'date':'2026-04-22','title':'우체국예금 해외사모펀드 국내재간접 위탁운용사 안내',
                'body':'공식 후속 공고'}
        self.data['priority_notices']=[notice]
        self.report['priority_sources']={'koreapost':{'notices':[],'programs':[],
                                                       'holds':[{'program_id':'koreapost','reason':'일시적 접속 실패'}]}}
        data,pages=prepare(self.data,self.report)
        self.assertEqual([notice],data['priority_notices'])
        self.assertEqual('0041:352',data['discovery_candidates'][0]['source_id'])
        self.assertIn('우체국예금 해외사모펀드',pages['review.html'])

    def test_same_attachment_keeps_extracted_fund_form_when_ocr_temporarily_fails(self):
        url='https://www.koreaexim.go.kr/HPHKBI039M01/115546'
        document={'source_id':'115546','institution_id':'kexim','url':url,
                  'date':'2026-08-13','title':'2026년 LP성장펀드(Track 1) 출자사업 계획 공고',
                  'body':'공식 공고', 'attachment_hashes':{'official-pdf':'same-bytes'},
                  'attachment_texts':{'official-pdf':'출자 대상 벤처투자조합'}}
        self.data['priority_notices']=[document]
        fresh={key:value for key,value in document.items() if key!='attachment_texts'}
        self.report['priority_sources']={'kexim':{'notices':[fresh], 'programs':[], 'holds':[]}}
        with patch('publish_lp_programs.project_kexim',return_value=([],[])):
            data,_=prepare(self.data,self.report)
        self.assertEqual(document['attachment_texts'],data['priority_notices'][0]['attachment_texts'])
        self.assertEqual('vc_only',data['discovery_candidates'][0]['scope'])

    def test_new_official_program_is_published_without_per_notice_recipe(self):
        from services.lp.tests.test_lp_notice_terms import official, BODY
        notice=official(BODY)
        self.report['priority_sources']={'koreapost':{'notices':[notice], 'holds':[]}}
        data,pages=prepare(self.data,self.report)
        automatic=next(p for p in data['programs'] if p.get('auto_extracted'))
        self.assertEqual('koreapost-2026-domestic-coinvestment',automatic['id'])
        self.assertEqual('2,000억원 이내',automatic['commitment_label'])
        self.assertIn('program-'+automatic['id']+'.html',pages)
        self.assertIn('주목적',pages['program-'+automatic['id']+'.html'])
        # A missing source later preserves the last successful public terms.
        self.report['priority_sources']={'koreapost':{'notices':[], 'holds':[]}}
        later,_=prepare(data,self.report)
        self.assertEqual(automatic,next(p for p in later['programs'] if p['id']==automatic['id']))
        # A conflicting revision is held, rather than overwriting with a guess.
        changed={**notice,'body':notice['body']+'\n투자규모 : 총 3,000억원'}
        self.report['priority_sources']={'koreapost':{'notices':[changed], 'holds':[]}}
        revised,_=prepare(data,self.report)
        self.assertEqual(automatic,next(p for p in revised['programs'] if p['id']==automatic['id']))
        self.assertTrue(any(h['program_id']==automatic['id'] for h in revised['program_holds']))

    def test_growth_repeated_collection_revalidates_and_preserves_last_good(self):
        from services.lp.tests.test_kgrowth_notice_terms import notice, DOCUMENT
        n=notice()
        self.report.update(checked_at='2026-11-13T18:00:00+09:00',notices=[n],
                           offering_terms={n['url']:{'commitment_amount_krw':999}})
        first,pages=prepare(self.data,self.report)
        auto=next(p for p in first['programs'] if p.get('auto_extracted'))
        self.assertEqual(auto['commitment_amount_krw'],24_000_000_000)
        self.assertEqual(auto['status'],'접수 마감')
        self.assertIn('<time>2026-12</time>',pages['program-'+auto['id']+'.html'])
        second,_=prepare(first,self.report)
        repeated=next(p for p in second['programs'] if p['id']==auto['id'])
        self.assertEqual(auto,repeated)
        self.assertFalse(any(h['program_id']==auto['id'] for h in second['program_holds']))
        broken=notice(DOCUMENT.replace('▪ 6개','▪ 7개'))
        self.report['notices']=[broken]
        third,_=prepare(second,self.report)
        self.assertEqual(auto,next(p for p in third['programs'] if p['id']==auto['id']))
        self.assertTrue(any(h['program_id']==auto['id'] for h in third['program_holds']))

    def test_growth_mixed_source_is_reviewed_without_other_bank_parser(self):
        from services.lp.tests.test_kgrowth_notice_terms import notice, DOCUMENT
        n=notice(DOCUMENT.replace('▪ 기관전용 사모집합투자기구','▪ 기관전용 사모집합투자기구, 벤처투자조합'))
        self.report.update(checked_at='2026-11-13',notices=[n])
        data,pages=prepare(self.data,self.report)
        self.assertEqual(len(data['programs']),len(self.data['programs']))
        self.assertEqual(data['discovery_candidates'][0]['scope'],'mixed_legal_forms')
        self.assertIn(n['url'],data['kgrowth_offering_terms'])
        self.assertIn('총 240억원',pages['review.html'])
        self.assertFalse(any('공동사업 조건 추출 보류' in h['reason'] for h in data['program_holds']))

    def test_growth_result_is_connected_by_business_not_notice_id(self):
        from services.lp.tests.test_kgrowth_notice_terms import notice
        n=notice();n['title']='【선정공고】'+n['title']
        result={**n,'source_id':'999999','url':n['url'].replace('76543','999999'),
                           'title':n['title'].replace('【선정공고】','【선정결과】').replace('선정계획','선정결과'),'date':'2026-12-08',
                           'attachment_texts':{},'attachment_documents':{},'attachment_hashes':{}}
        self.report.update(checked_at='2026-12-09',notices=[n,result])
        data,_=prepare(self.data,self.report)
        auto=next(p for p in data['programs'] if p.get('auto_extracted'))
        self.assertEqual(auto['status'],'선정 결과 발표')
        self.assertEqual(auto['selected_gps'],[])
        self.assertIn(result['url'],[e['url'] for e in auto['events']])

    def test_growth_amendment_or_cancellation_holds_the_original_business(self):
        from services.lp.tests.test_kgrowth_notice_terms import notice
        n=notice();n['title']='【선정공고】'+n['title']
        self.report.update(checked_at='2026-11-13',notices=[n])
        first,_=prepare(self.data,self.report)
        auto=next(p for p in first['programs'] if p.get('auto_extracted'))
        for title in (n['title']+'(수정)',n['title'].replace('선정계획 공고','선정계획 취소 공고')):
            amended={**n,'source_id':'888888','url':n['url'].replace('76543','888888'),
                     'title':title,'date':'2026-11-12'}
            self.report['notices']=[n,amended]
            data,_=prepare(first,self.report)
            self.assertEqual([auto['id']],[p['id'] for p in data['programs'] if p.get('auto_extracted')])
            self.assertEqual(auto,next(p for p in data['programs'] if p['id']==auto['id']))
            self.assertTrue(any(h['program_id']==auto['id'] and '변경' in h['reason'] for h in data['program_holds']))

    def test_shared_evidence_is_retained_without_approving_fund_terms(self):
        from services.lp.tests.test_lp_shared_notice_catalog import notice
        self.report['checked_at']='2026-10-13'
        self.report['shared_collection']={'notices':[notice()],'coverage':{'notice_count':1}}
        data,pages=prepare(self.data,self.report)
        self.assertEqual(len(self.data['programs']) + 1,len(data['programs']))
        basic = next(p for p in data['programs'] if p.get('basic_publication'))
        self.assertEqual(basic['institution_id'], 'cu')
        self.assertNotIn('commitment_amount_krw', basic)
        self.assertEqual(basic['selected_gps'], [])
        self.assertEqual(data['shared_notices'][0]['institution_id'],'cu')
        self.assertIn('신협중앙회',pages['review.html'])
        self.assertIn('공고 본문',pages['review.html'])
        self.report['shared_collection']={'notices':[]}
        again,_=prepare(data,self.report)
        self.assertEqual(again['shared_notices'],data['shared_notices'])

    def test_basic_notice_gains_terms_without_changing_url_or_duplicating(self):
        from services.lp.tests.test_lp_notice_terms import official, BODY
        n = official('운용방식: 국내 블라인드 PEF 공개모집', title='2026년 국내 신규전략 PEF 선정 공고')
        n['sha256'] = 'a' * 64
        self.report['priority_sources'] = {'koreapost': {'notices': [n], 'holds': []}}
        first, _ = prepare(self.data, self.report)
        basic = next(p for p in first['programs'] if p.get('basic_publication'))
        self.assertNotIn('commitment_amount_krw', basic)
        n['body'] += '\n' + BODY.replace('공동투자건', '혁신기업')
        self.report['priority_sources']['koreapost']['notices'] = [n]
        second, pages = prepare(first, self.report)
        matches = [p for p in second['programs'] if n['url'] in {e['url'] for e in p['events']}]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['id'], basic['id'])
        self.assertEqual(matches[0]['commitment_amount_krw'], 200_000_000_000)
        self.assertIn('program-' + basic['id'] + '.html', pages)

if __name__=='__main__':unittest.main()
