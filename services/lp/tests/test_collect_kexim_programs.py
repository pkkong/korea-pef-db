"""KEXIM board parsing and reviewed-publication safety checks."""
import hashlib
import base64
import copy
import json
import re
import ssl
import socket
import tempfile
import unittest
from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, Mock
from urllib.error import HTTPError, URLError

from services.lp.src import collect_kexim_programs as kexim
from services.lp.tests.test_lp_attachment_text import compound, record, hwpx, section, para, cell


def detail(source_id, title, date, body, attachment_url):
    markup = f'''<h1 class="detail-view-title">{title}</h1>
    <span class="detail-view-info" title="작성일">{date}</span>
    <div class="detail-view-box"><p>{body}</p></div>
    <div class="detail-view-file"><a href="{attachment_url}">공식 결과.pdf</a></div>'''
    return kexim.parse_detail(source_id, markup.encode())


def fixture():
    source1 = detail('1', '2026년 하반기 글로벌 성장펀드 출자사업 공고',
                     '2026.08.31', 'PE 공고', '/comm/getFile?upperNo=1&fileNo=1')
    source2 = detail('2', '2026년 하반기 블라인드펀드 제안서 접수 결과',
                     '2026.09.17', 'PE 접수', '/comm/getFile?upperNo=2&fileNo=1')
    source1['attachment_hashes'] = {source1['attachments'][0]['url']: hashlib.sha256(b'%PDFfirst').hexdigest()}
    source2['attachment_hashes'] = {source2['attachments'][0]['url']: hashlib.sha256(b'%PDFsecond').hexdigest()}
    recipe = {
        'id': 'kexim-test-pe', 'title': '2026 하반기 PE',
        'match_groups': [['2026','하반기','글로벌 성장펀드'], ['2026','하반기','블라인드펀드']],
        'sources': [
            {'source_id': n['source_id'], 'date': n['date'], 'event': e,
             'sha256': n['sha256'], 'attachment_hashes': n['attachment_hashes'], **({'team_count': 2} if e == '접수 현황' else {})}
            for n,e in ((source1,'모집 공고'),(source2,'접수 현황'))
        ],
        'facts': {'commitment_label': {'source_id':'1','attachment_url':source1['attachments'][0]['url'],
                                       'quote':'출자액 100억원','value':'100억원'},
                  'deadline': {'source_id':'1','attachment_url':source1['attachments'][0]['url'],
                               'quote':'9월 16일 16시','value':'2026-09-16T16:00:00+09:00'}},
        'manager_lists': {'applicants': {'중형':['가GP','나GP']}, 'shortlist':{}, 'selected':{}},
        'manager_evidence': {'applicants': {'source_id':'2','attachment_url':source2['attachments'][0]['url'],
                                            'quote':'2개사 제출'}}
    }
    return [source1,source2],recipe


class KeximCollectorTests(unittest.TestCase):
    def test_attachmentless_body_ends_before_adjacent_fund_notice(self):
        page = ('<h1 class="detail-view-title">지원사업 결과</h1><span title="작성일">2026.10.01</span>'
                '<div class="detail-view-box"><p>사업타당성조사 지원사업</p><div>신청기업 안내</div></div>'
                '<div class="detail-view-paging">국내 PE 블라인드펀드 선정 결과</div>')
        n = kexim.parse_detail('123', page)
        self.assertEqual(n['body'], '사업타당성조사 지원사업 신청기업 안내')
        self.assertEqual(n['attachments'], [])
        for invalid in [page.replace('신청기업 안내</div></div>', '신청기업 안내'),
                        page + '<div class="detail-view-box">추가 본문</div>']:
            with self.assertRaises(ValueError):
                kexim.parse_detail('123', invalid)

    def test_existing_attachment_body_fingerprint_is_preserved(self):
        n = detail('123', 'PE 모집', '2026.10.01', '본문 <b>내용</b>', '/comm/getFile?fileNo=1')
        expected = hashlib.sha256(json.dumps(['PE 모집', '2026-10-01', '본문 내용'], ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(n['sha256'], expected)

    def test_verified_cookie_redirect_keeps_original_host(self):
        class Response(BytesIO):
            def geturl(self):
                return 'https://www.koreaexim.go.kr/HPHKBI039M01'
        class Opener:
            def __init__(self):
                self.calls=0
            def open(self, request, timeout):
                self.calls+=1
                if self.calls==1:
                    headers=Message();headers['Location']='/HPHKBI039M01';headers['Set-Cookie']='visit=ok; Path=/'
                    raise HTTPError(request.full_url,302,'Found',headers,None)
                if request.get_header('Cookie')!='visit=ok':
                    raise AssertionError('Official session cookie missing')
                return Response(b'official page')
        opener=Opener()
        with patch.object(kexim,'build_opener',return_value=opener):
            self.assertEqual(kexim._official_fetch('https://www.koreaexim.go.kr/HPHKBI039M01'),b'official page')
        self.assertEqual(opener.calls,2)

    def test_dns_only_recovery_keeps_cookie_redirect_and_pinned_context(self):
        class Response(BytesIO):
            def geturl(self):return kexim.BOARD
        native=Mock();native.open.side_effect=URLError(socket.gaierror(socket.EAI_NONAME,'DNS'))
        headers=Message();headers['Location']='/HPHKBI039M01';headers['Set-Cookie']='visit=ok; Path=/'
        recovered=Mock();recovered.open.side_effect=[HTTPError(kexim.BOARD,302,'redirect',headers,None),Response(b'official')]
        with patch.object(kexim,'build_opener',side_effect=[native,recovered]) as build,patch.object(kexim.time,'sleep'):
            self.assertEqual(kexim._official_fetch(kexim.BOARD),b'official')
            self.assertEqual(build.call_count,2)
            handler=build.call_args_list[1].args[1]
            self.assertIsInstance(handler,kexim.IPv4HTTPSHandler)
            self.assertTrue(handler._context.check_hostname)
            self.assertEqual(handler._context.verify_mode,ssl.CERT_REQUIRED)
            self.assertIs(handler._connection_factory.keywords['fallback_resolver'],kexim.resolve_kexim_ipv4)
            calls=recovered.open.call_args_list
            self.assertTrue(all(call.args[0].full_url==kexim.BOARD for call in calls))
            self.assertEqual(calls[-1].args[0].get_header('Cookie'),'visit=ok')

    def test_tls_http_and_untyped_errors_never_retry_or_select_dns(self):
        for error in (URLError(ssl.SSLCertVerificationError('bad cert')),URLError('name resolution failed'),HTTPError(kexim.BOARD,503,'failure',Message(),None)):
            opener=Mock();opener.open.side_effect=error
            with patch.object(kexim,'build_opener',return_value=opener) as build,patch.object(kexim.time,'sleep') as sleep:
                with self.assertRaises(type(error)):kexim._official_fetch(kexim.BOARD)
                self.assertEqual(build.call_count,1);self.assertEqual(opener.open.call_count,1);sleep.assert_not_called()

    def test_typed_connection_reset_retries_same_opener_without_dns(self):
        class Response(BytesIO):
            def geturl(self):return kexim.BOARD
        for error in (ConnectionResetError(54,'reset'),URLError(ConnectionResetError(54,'reset')),URLError(URLError(ConnectionResetError(54,'reset')))):
            opener=Mock();opener.open.side_effect=[error,Response(b'official')]
            with patch.object(kexim,'build_opener',return_value=opener) as build,patch.object(kexim,'resolve_kexim_ipv4') as dns,patch.object(kexim.time,'sleep') as sleep:
                self.assertEqual(kexim._official_fetch(kexim.BOARD),b'official')
                self.assertEqual(opener.open.call_count,2);self.assertEqual(build.call_count,1)
                sleep.assert_called_once_with(1);dns.assert_not_called()

    def test_repeated_reset_stops_after_three_attempts_without_dns(self):
        opener=Mock();opener.open.side_effect=URLError(ConnectionResetError(54,'reset'))
        with patch.object(kexim,'build_opener',return_value=opener) as build,patch.object(kexim,'resolve_kexim_ipv4') as dns,patch.object(kexim.time,'sleep') as sleep:
            with self.assertRaises(URLError):kexim._official_fetch(kexim.BOARD)
            self.assertEqual(opener.open.call_count,3);self.assertEqual(build.call_count,1)
            self.assertEqual([call.args for call in sleep.call_args_list],[(1,),(2,)])
            dns.assert_not_called()

    def test_dns_recovery_exhaustion_is_three_attempts_without_silent_empty(self):
        opener=Mock();opener.open.side_effect=URLError(socket.gaierror(socket.EAI_NONAME,'DNS'))
        with patch.object(kexim,'build_opener',return_value=opener) as build,patch.object(kexim.time,'sleep'):
            with self.assertRaises(URLError):kexim._official_fetch(kexim.BOARD)
            self.assertEqual(opener.open.call_count,3);self.assertEqual(build.call_count,2)

    def test_pinned_official_ca_chain_has_expected_certificates(self):
        pem=kexim.CA_CHAIN.read_text()
        certs=re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',pem,re.S)
        fingerprints={hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert)).hexdigest() for cert in certs}
        self.assertEqual(fingerprints,{
            '4bcc5e234fe81ede4eaf883aa19c31335b0b26e85e066b9945e4cb6153eb20c2',
            'cb3ccbb76031e5e0138f8dd39a23f9de47ffc35e43c1144cea27d46a5ab1cb5f'})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = Path(self.temp.name) / 'reviews.json'
        self.patch = patch.object(kexim, 'REGISTRY', self.registry)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.temp.cleanup)

    def set_recipe(self, recipe):
        self.registry.write_text(json.dumps([recipe],ensure_ascii=False))

    def test_detail_is_scoped_to_post_and_stable_attachment(self):
        n = detail('115904', '2026년 하반기 글로벌 성장펀드 출자사업 공고',
                   '2026.08.31', '공식 본문', '/comm/getFile?upperNo=115904&amp;fileNo=1')
        self.assertEqual(n['date'],'2026-08-31')
        self.assertEqual(n['body'],'공식 본문')
        self.assertEqual(n['attachments'][0]['url'],
                         'https://www.koreaexim.go.kr/comm/getFile?upperNo=115904&fileNo=1')

    def test_approved_application_and_gp_lists_project(self):
        notices,recipe=fixture();self.set_recipe(recipe)
        programs,holds=kexim.project(notices,'2026-10-03T12:00:00+09:00')
        self.assertFalse(holds)
        self.assertEqual(programs[0]['status'],'접수 마감')
        self.assertEqual(programs[0]['applicants_gps'],['가GP','나GP'])
        self.assertFalse(programs[0]['selected_gps'])
        self.assertEqual(programs[0]['schedule_stages'][1]['status'],'announced_deadline')

    def test_new_result_is_candidate_and_blocks_public_update(self):
        notices,recipe=fixture();self.set_recipe(recipe)
        new=detail('3','2026년 하반기 블라인드펀드 선정 결과',
                   '2026.10.02','새 결과','/comm/getFile?upperNo=3&fileNo=1')
        new['attachment_hashes']={new['attachments'][0]['url']:'new-file-sha'}
        programs,holds=kexim.project(notices+[new],'2026-10-03T12:00:00+09:00')
        self.assertFalse(programs)
        self.assertIn('연결 검토 필요',holds[0]['reason'])
        candidate=kexim.link_suggestions(notices+[new])
        self.assertEqual(candidate[0]['programs'],[{'id':'kexim-test-pe','title':'2026 하반기 PE'}])
        self.assertEqual(candidate[0]['stage'],'최종 선정')

    def test_unmatched_fund_notice_is_a_new_business_candidate(self):
        notices,recipe=fixture();self.set_recipe(recipe)
        other=detail('9','임상3상 특화펀드 위탁운용사 선정계획 공고',
                     '2026.05.11','별도 펀드 공고','/comm/getFile?upperNo=9&fileNo=1')
        programs,holds=kexim.project(notices+[other],'2026-10-03T12:00:00+09:00')
        self.assertEqual([],holds)
        self.assertEqual('kexim-test-pe',programs[0]['id'])
        self.assertEqual([],kexim.link_suggestions(notices+[other]))
        self.assertEqual('9',kexim.discovery_candidates(notices+[other])[0]['source_id'])

    def test_changed_attachment_and_bad_team_count_hold(self):
        notices,recipe=fixture();self.set_recipe(recipe)
        changed=json.loads(json.dumps(notices))
        changed[1]['attachment_hashes'][next(iter(changed[1]['attachment_hashes']))]='changed'
        self.assertFalse(kexim.project(changed,'2026-10-03T12:00:00+09:00')[0])
        recipe['manager_lists']['applicants']['중형'].append('다GP');self.set_recipe(recipe)
        self.assertFalse(kexim.project(notices,'2026-10-03T12:00:00+09:00')[0])

    def test_real_review_registry_separates_pe_from_vc_and_joint_program(self):
        rows=json.loads((kexim.ROOT/'data/kexim_program_reviews.json').read_text())
        self.assertEqual({r['id'] for r in rows},{'kexim-2026-h1-supply-chain-pe',
                         'kexim-2026-h1-regional-growth-pe','kexim-2026-h2-global-growth-pe'})
        h2=next(r for r in rows if r['id'].endswith('h2-global-growth-pe'))
        self.assertEqual(sum(map(len,h2['manager_lists']['applicants'].values())),14)
        self.assertEqual({s['source_id'] for s in h2['sources']},{'115904','116241'})
        self.assertNotIn('115905',{s['source_id'] for r in rows for s in r['sources']})
        self.assertNotIn('116443',{s['source_id'] for r in rows for s in r['sources']})
        self.assertFalse(any(kexim._title_matches(r,'정책금융기관 글로벌 스케일업 협력펀드 선정 결과') for r in rows))
        self.assertTrue(all(not any('per_fund_max_krw' in s for s in r['facts']['segments']['value']) for r in rows))
        for r in rows[:2]:
            selected=r['manager_lists']['selected']
            allocations=r['allocation_evidence']['per_gp_krw']
            self.assertEqual(sum(len(names)*allocations[track] for track,names in selected.items()),
                             r['facts']['commitment_amount_krw']['value'])



class KeximRollingWindowTests(unittest.TestCase):
    def test_actual_publication_dates_bound_discovery_not_business_title_year(self):
        # 2026 business recruitment can be announced in November 2025.
        rows=[{'link':kexim.BOARD+'/'+ident,'announced_date':stamp,'title':title}
              for ident,stamp,title in [
                  ('981','2025-11-01','2026 상반기 공급망 펀드 공고'),
                  ('982','2025-10-31','펀드 공고'),
                  ('983','2026-10-31','연도 없는 펀드 공고'),
                  ('984','2026-11-01','미래 펀드 공고')]]
        calls=[]
        def fetch(url):
            calls.append(url)
            return b'official fixture'
        def parsed(ident,raw):
            return {'source_id':ident,'url':kexim.BOARD+'/'+ident,'title':'공식 펀드',
                    'date':'2024-01-01' if ident=='985' else next(r['announced_date'] for r in rows if r['link'].endswith('/'+ident)),
                    'body':'공식 본문','attachments':[]}
        with patch.object(kexim,'extract_kexim_notice_rows',return_value=rows), \
             patch.object(kexim,'_approved_source_ids',return_value={'985'}), \
             patch.object(kexim,'parse_detail',side_effect=parsed), \
             patch.object(kexim,'project',return_value=([],[])), \
             patch.object(kexim,'discovery_candidates',return_value=[]), \
             patch.object(kexim,'link_suggestions',return_value=[]), \
             patch('services.lp.src.collect_kdb_related.collect_related',return_value=([],[])):
            # UTC October 30 already means October 31 in Seoul.
            report=kexim.collect('2026-10-30T16:00:00+00:00',fetch=fetch)
        self.assertEqual({n['source_id'] for n in report['notices']},{'981','983','985'})
        self.assertEqual(len([u for u in calls if '?curPage=' in u]),8)
        self.assertNotIn(kexim.BOARD+'/982',calls)
        self.assertNotIn(kexim.BOARD+'/984',calls)
        self.assertIn(kexim.BOARD+'/985',calls)

    def test_timestamp_without_timezone_fails_before_official_request(self):
        from unittest.mock import Mock
        fetch=Mock()
        with self.assertRaisesRegex(ValueError,'timezone'):
            kexim.collect('2026-10-31T00:00:00',fetch=fetch)
        fetch.assert_not_called()


class KeximAttachmentProofTests(unittest.TestCase):
    def notice(self, raw):
        n = detail('9', '공식 펀드 선정 결과', '2026.11.01', '공식 본문',
                   '/comm/getFile?srvcId=BBSTY1&upperNo=9&fileTy=ATTACH&fileNo=1')
        n['checked_at'] = '2026-11-09T06:53:02+00:00'
        n['attachment_texts'] = {}
        n['attachment_hashes'] = {n['attachments'][0]['url']: hashlib.sha256(raw).hexdigest()}
        return n

    def collect_one(self, raw, approved=False):
        n = self.notice(raw)
        file_url = n['attachments'][0]['url']
        calls = []
        def fetch(url):
            calls.append(url)
            if '?curPage=' in url:
                return b'listing'
            if url == n['url']:
                return b'detail'
            if url == file_url:
                return raw
            raise AssertionError('Unexpected request')
        row = {'link': n['url'], 'announced_date': n['date'], 'title': n['title']}
        original = {k: copy.deepcopy(v) for k, v in n.items() if k not in ('attachment_hashes', 'attachment_texts', 'checked_at')}
        with patch.object(kexim, 'extract_kexim_notice_rows', return_value=[row]), \
             patch.object(kexim, '_approved_source_ids', return_value={'9'} if approved else set()), \
             patch.object(kexim, 'parse_detail', return_value=original), \
             patch.object(kexim, 'project', return_value=([], [])), \
             patch.object(kexim, 'discovery_candidates', return_value=[]), \
             patch.object(kexim, 'link_suggestions', return_value=[]), \
             patch.object(kexim, '_official_fetch', side_effect=AssertionError('No network')), \
             patch('services.lp.src.collect_kdb_related.collect_related', return_value=([], [])):
            report = kexim.collect(n['checked_at'], fetch=fetch)
        self.assertEqual(calls.count(file_url), 1)
        self.assertEqual(len(calls), kexim.PAGES + 2)
        self.assertEqual(report['programs'], [])
        return report['notices'][0]

    def test_unapproved_full_hwp_body_not_preview_is_retained_and_replayed(self):
        raw = compound([record('중형 공식 운용사\r'), record('소형 공식 운용사\r')],
                       preview='가짜 선정자 미리보기')
        n = self.collect_one(raw)
        decoded = kexim.validate_attachment_proof(n)
        self.assertEqual(decoded, {'format': 'hwp', 'text': '중형 공식 운용사\n소형 공식 운용사', 'tables': []})
        url = n['attachments'][0]['url']
        proof = n['attachment_proofs'][url]
        self.assertEqual(base64.b64decode(proof['raw_base64'], validate=True), raw)
        self.assertEqual(n['attachment_texts'][url], decoded['text'])
        self.assertNotIn('가짜', decoded['text'])
        self.assertNotIn('selected_gps', n)

    def test_hwpx_complete_sections_and_original_table_are_retained(self):
        table = '<hp:tbl rowCnt="1" colCnt="2"><hp:tr>' + cell('중형', 0, 0) + cell('공식 명단', 0, 1) + '</hp:tr></hp:tbl>'
        raw = hwpx([section(para('공식 결과') + table), section(para('후속 유의사항'))],
                   {'Preview/PrvText.txt': '가짜 결과'})
        n = self.collect_one(raw)
        value = kexim.validate_attachment_proof(n)
        self.assertEqual(value['format'], 'hwpx')
        self.assertEqual(value['tables'], [[['중형', '공식 명단']]])
        self.assertEqual(value['text'], '공식 결과\n중형\t공식 명단\n후속 유의사항')

    def test_raw_hash_extraction_source_membership_and_failure_tamper_rejected(self):
        n = self.collect_one(hwpx([section(para('공식 본문'))]))
        url = n['attachments'][0]['url']
        def raw_bad(x): x['attachment_proofs'][url]['raw_base64'] = base64.b64encode(b'changed').decode()
        def hash_bad(x): x['attachment_hashes'][url] = '0' * 64
        def text_bad(x): x['attachment_proofs'][url]['extracted']['text'] = '가짜'
        def table_bad(x): x['attachment_proofs'][url]['extracted']['tables'] = [[['가짜']]]
        def source_bad(x): x['source_id'] = '10'
        def notice_url_bad(x): x['url'] = kexim.BOARD + '/10'
        def title_bad(x): x['title'] = '다른 제목'
        def body_bad(x): x['body'] += 'changed'
        def name_bad(x): x['attachments'][0]['name'] = 'other.hwp'
        def consumer_bad(x): x['attachment_texts'][url] = '가짜'
        def identity_bad(x): x['attachment_proofs'][url]['notice_url'] = kexim.BOARD + '/10'
        for mutate in (raw_bad, hash_bad, text_bad, table_bad, source_bad, notice_url_bad, title_bad, body_bad, name_bad, consumer_bad, identity_bad):
            value = copy.deepcopy(n); mutate(value)
            with self.subTest(mutate=mutate.__name__), self.assertRaises(ValueError):
                kexim.validate_attachment_proof(value)
        legacy = copy.deepcopy(n); del legacy['attachment_proofs']
        with self.assertRaisesRegex(ValueError, 'missing'):
            kexim.validate_attachment_proof(legacy)

    def test_failed_unsupported_protected_empty_files_keep_raw_and_replay_failure(self):
        cases = [b'<script>alert("restricted")</script>', b'',
                 compound([record('Protected')], flags=2),
                 compound([record('Preview only')], body=False),
                 hwpx([section(para(''))])]
        for raw in cases:
            with self.subTest(size=len(raw)):
                n = self.collect_one(raw)
                url = n['attachments'][0]['url']
                proof = n['attachment_proofs'][url]
                self.assertIsNone(kexim.validate_attachment_proof(n))
                self.assertEqual(base64.b64decode(proof['raw_base64'], validate=True), raw)
                self.assertEqual(proof['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertFalse(n['attachment_texts'])
                self.assertTrue(n['attachment_read_error'])
                value = copy.deepcopy(n); value['attachment_proofs'][url]['error_code'] = None
                with self.assertRaises(ValueError): kexim.validate_attachment_proof(value)

    def test_raw_size_and_encoded_size_limits_fail_before_decoding(self):
        n = self.notice(b'12345')
        with patch.object(kexim, 'MAX_FILE_BYTES', 4), patch.object(kexim, 'extract_attachment') as decoder:
            with self.assertRaisesRegex(ValueError, 'size limit'):
                kexim.retain_attachment_proof(n, b'12345')
            decoder.assert_not_called()
        n = self.collect_one(hwpx([section(para('Body'))]))
        with patch.object(kexim, 'MAX_FILE_BYTES', 4), patch.object(kexim, 'extract_attachment') as decoder:
            with self.assertRaisesRegex(ValueError, 'size limit'): kexim.validate_attachment_proof(n)
            decoder.assert_not_called()

    def test_only_exact_first_official_same_notice_file_can_have_proof(self):
        raw = hwpx([section(para('Body'))])
        for bad in ['http://www.koreaexim.go.kr/comm/getFile?upperNo=9&fileNo=1',
                    'https://www.koreaexim.go.kr:443/comm/getFile?upperNo=9&fileNo=1',
                    'https://evil.example/comm/getFile?upperNo=9&fileNo=1',
                    'https://www.koreaexim.go.kr/comm/getFile?upperNo=10&fileNo=1',
                    'https://www.koreaexim.go.kr/comm/getFile?upperNo=9&upperNo=9&fileNo=1',
                    'https://www.koreaexim.go.kr/comm/getFile?upperNo=9&fileNo=1&fileNo=1',
                    'https://www.koreaexim.go.kr/comm/getFile?upperNo=9&fileNo=1&srvcId=BBSTY1&srvcId=BBSTY1',
                    'https://www.koreaexim.go.kr/comm/getFile?upperNo=9&fileNo=1&srvcId=OTHER',
                    'https://www.koreaexim.go.kr/comm/getFile?upperNo=9&fileNo=1&fileTy=OTHER',
                    'https://www.koreaexim.go.kr/comm/getFile?upperNo=9&fileNo=1&unknown=1',
                    'https://www.koreaexim.go.kr/comm/getFile?upperNo=9&fileNo=1\r\n',
                    'https://www.koreaexim.go.kr/comm/getFile?upperNo=9&fileNo= 1']:
            n = self.notice(raw); n['attachments'][0]['url'] = bad
            n['attachment_hashes'] = {bad: hashlib.sha256(raw).hexdigest()}
            with self.subTest(url=bad), self.assertRaises(ValueError): kexim.retain_attachment_proof(n, raw)
        minimal = self.notice(raw)
        minimal_url = kexim.BASE + '/comm/getFile?upperNo=9&fileNo=1'
        minimal['attachments'][0]['url'] = minimal_url
        minimal['attachment_hashes'] = {minimal_url: hashlib.sha256(raw).hexdigest()}
        kexim.retain_attachment_proof(minimal, raw)
        self.assertEqual(kexim.validate_attachment_proof(minimal)['format'], 'hwpx')
        n = self.notice(raw); first = n['attachments'][0]['url']
        n['attachments'].append({'url': first.replace('fileNo=1', 'fileNo=2'), 'name': 'second.hwp'})
        kexim.retain_attachment_proof(n, raw)
        with self.assertRaises(ValueError): kexim.validate_attachment_proof(n, n['attachments'][1]['url'])

    def test_pdf_canonical_body_is_separate_from_legacy_layout_or_ocr(self):
        # A real simple PDF: reader parsing and raw replay use the pinned
        # canonical extractor; the existing platform-dependent view stays separate.
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter(); page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 10 100 Td (Official result body) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        output = BytesIO(); writer.write(output); raw = output.getvalue()
        with patch.object(kexim, '_pdf_text', return_value='legacy layout/OCR text') as legacy:
            n = self.collect_one(raw)
        legacy.assert_called_once_with(raw)
        decoded = kexim.validate_attachment_proof(n)
        self.assertEqual(decoded['text'], 'Official result body')
        self.assertEqual(n['attachment_texts'][n['attachments'][0]['url']], 'legacy layout/OCR text')
        self.assertEqual(n['attachment_proofs'][n['attachments'][0]['url']]['pdf_reader_version'], '6.10.0')

    def test_approved_hash_review_path_is_unchanged(self):
        with patch.object(kexim, 'extract_attachment', side_effect=AssertionError('Approved source must stay unchanged')), \
             patch.object(kexim, '_pdf_text', side_effect=AssertionError('Approved PDF has curated facts')):
            n = self.collect_one(b'%PDFreviewed-source', approved=True)
        self.assertNotIn('attachment_proofs', n)
        self.assertFalse(n['attachment_texts'])
        self.assertEqual(next(iter(n['attachment_hashes'].values())), hashlib.sha256(b'%PDFreviewed-source').hexdigest())

    def test_failed_canonical_pdf_keeps_legacy_preview_without_promoting_proof(self):
        from pypdf import PdfWriter
        writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
        empty = BytesIO(); writer.write(empty)
        writer.encrypt('private-password')
        protected = BytesIO(); writer.write(protected)
        for raw, expected_error in [(empty.getvalue(), 'attachment_body_unreadable'),
                                    (protected.getvalue(), 'protected_attachment')]:
            with self.subTest(error=expected_error), patch.object(kexim, '_pdf_text', return_value='legacy preview preserved') as legacy:
                n = self.collect_one(raw)
            legacy.assert_called_once_with(raw)
            self.assertEqual(n['attachment_texts'][n['attachments'][0]['url']], 'legacy preview preserved')
            self.assertEqual(n['attachment_read_error'], expected_error)
            self.assertIsNone(kexim.validate_attachment_proof(n))
        with patch.object(kexim, '_pdf_text', side_effect=RuntimeError('legacy failure')):
            n = self.collect_one(empty.getvalue())
        self.assertEqual(n['attachment_read_error'], 'attachment_body_unreadable')
        self.assertIsNone(kexim.validate_attachment_proof(n))

    def test_pdf_reader_version_is_explicit_and_mismatch_retains_failed_raw(self):
        import pypdf
        writer = pypdf.PdfWriter(); writer.add_blank_page(width=100, height=100)
        output = BytesIO(); writer.write(output); raw = output.getvalue()
        with patch.object(pypdf, '__version__', 'unexpected-version'), \
             patch.object(kexim, '_pdf_text', return_value='legacy preview'), \
             patch.object(kexim, 'extract_attachment', side_effect=AssertionError('Wrong reader must not decode')):
            n = self.collect_one(raw)
            self.assertEqual(n['attachment_read_error'], 'pdf_reader_version_mismatch')
            self.assertIsNone(kexim.validate_attachment_proof(n))
        # Replaying with a different decoder/version never certifies the old
        # observation as successful or silently rewrites its failure.
        with self.assertRaisesRegex(ValueError, 'decoded body mismatch'):
            kexim.validate_attachment_proof(n)

    def test_failed_proof_hold_is_rederived_by_priority_load_and_health(self):
        from services.lp.src.collect_priority_lp_programs import load_kexim_collection
        from services.lp.src.build_lp_collection_health import hold_counts
        failed = self.collect_one(compound([record('Protected')], flags=2))
        reviewed, recipe = fixture()
        timestamp = failed['checked_at']
        with patch.object(kexim, '_recipes', return_value=[recipe]):
            baseline, baseline_holds = kexim.project(reviewed, timestamp)
            programs, holds = kexim.project(reviewed + [failed], timestamp)
            self.assertEqual(programs, baseline)
            self.assertEqual(baseline_holds, [])
            self.assertEqual(len(holds), 1)
            expected = {'stage': 'institution_attachment_text', 'institution_id': 'kexim',
                        'source_id': '9', 'url': failed['url'],
                        'attachment_url': failed['attachments'][0]['url'],
                        'reason': 'protected_attachment', 'error': 'protected_attachment'}
            self.assertEqual(holds[0], expected)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'kexim.json'
                # Explicitly omit collector holds: loading must reproduce them
                # from raw proof instead of losing the operational failure.
                path.write_text(json.dumps({'checked_at': timestamp, 'notices': reviewed + [failed], 'holds': []}))
                loaded = load_kexim_collection(path, timestamp)
            self.assertEqual(loaded['programs'], baseline)
            self.assertEqual(loaded['holds'], holds)
        counts = hold_counts(loaded['holds'])
        self.assertEqual(counts['attachment_holds'], 1)
        self.assertEqual(counts['review_holds'], 0)
        self.assertEqual(counts['source_errors'], 0)

    def test_invalid_proof_is_a_hold_and_hash_only_legacy_is_not(self):
        good = self.collect_one(hwpx([section(para('Official body'))]))
        reviewed, recipe = fixture()
        url = good['attachments'][0]['url']
        for invalid in (None, {}, {'raw_base64': 'forged'}):
            bad = copy.deepcopy(good); bad['attachment_proofs'] = invalid
            with self.subTest(invalid=invalid), patch.object(kexim, '_recipes', return_value=[recipe]):
                programs, holds = kexim.project(reviewed + [bad], good['checked_at'])
                self.assertEqual(len(programs), 1)
                self.assertEqual(holds[0]['error'], 'attachment_proof_invalid')
        bad = copy.deepcopy(good); bad['attachment_proofs'][url]['extracted']['text'] = 'forged'
        with patch.object(kexim, '_recipes', return_value=[recipe]):
            self.assertEqual(kexim.project(reviewed + [bad], good['checked_at'])[1][0]['error'], 'attachment_proof_invalid')
            for field in ('source_id', 'attachments', 'attachment_hashes'):
                bad = copy.deepcopy(good); del bad[field]
                with self.subTest(field=field):
                    programs, holds = kexim.project(reviewed + [bad], good['checked_at'])
                    self.assertEqual(len(programs), 1)
                    self.assertEqual(holds[0]['error'], 'attachment_proof_invalid')
            self.assertEqual(kexim.project(reviewed + [good], good['checked_at'])[1], [])
            legacy = copy.deepcopy(good); del legacy['attachment_proofs']
            self.assertEqual(kexim.project(reviewed + [legacy], good['checked_at'])[1], [])

    def test_transport_read_is_bounded_without_retrying_content_failure(self):
        class Response(BytesIO):
            def geturl(self): return kexim.BOARD
        opener = Mock(); response = Response(b'12345'); opener.open.return_value = response
        with patch.object(kexim, 'MAX_FILE_BYTES', 4), patch.object(kexim, 'build_opener', return_value=opener), \
             patch.object(kexim.time, 'sleep') as sleep:
            with self.assertRaisesRegex(ValueError, 'size limit'): kexim._official_fetch(kexim.BOARD)
        self.assertEqual(opener.open.call_count, 1)
        sleep.assert_not_called()

if __name__ == '__main__':
    unittest.main()
