"""KEXIM board parsing and reviewed-publication safety checks."""
import hashlib
import json
import re
import ssl
import tempfile
import unittest
from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from services.lp.src import collect_kexim_programs as kexim


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


if __name__ == '__main__':
    unittest.main()
