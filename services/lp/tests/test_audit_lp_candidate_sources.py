import copy
import hashlib
import unittest

from services.lp.src import audit_lp_candidate_sources as audit

KEXIM_TITLE = '「2026년 사업타당성조사 지원사업」 선정결과 안내'
SEMA_TITLE = '과학기술인공제회 일본주식형펀드 재간접위탁운용사 선정 공고'
SEMA = audit.channels()['sema']


def candidate(institution):
    return {'institution_id': institution, 'id':institution+'-candidate',
            'title':KEXIM_TITLE if institution=='kexim' else SEMA_TITLE,
            'official_url':'https://www.koreaexim.go.kr/HPHKBI039M01/991100?curPage=1' if institution=='kexim' else None,
            'url':'https://api.pe-vc-lp.com/att/untrusted.pdf', 'status':'official_link_to_verify' if institution=='kexim' else 'official_source_needed'}


def receipt():
    html=f'<html><div class="notice-list-item"><a href="/HPHKBI039M01/991100">{KEXIM_TITLE}</a><span>2026-10-01</span></div></html>'
    return {'institution_id':'kexim','url':'https://www.koreaexim.go.kr/HPHKBI039M01?curPage=1',
            'html':html,'sha256':hashlib.sha256(html.encode()).hexdigest()}


class CandidateSourceTests(unittest.TestCase):
    def test_inventory_unknowns_are_resolved_without_manual_notice_selection(self):
        from services.lp.tests.test_lp_board_adapters_banks import IBK_LIST,IBK_HTML,IBK_URL
        config=audit.load_configs()['ibk'];url=audit.inventory.page_url('ibk',config,'펀드',1,'2025-10-26','2026-10-25')
        html=IBK_LIST+'</html>';row=audit.adapter(config).parse_listing(html,url,config)[0]
        row.update(relevant=True,disposition='not_in_archive',title_scope='scope_unconfirmed')
        source={'receipts':[{'institution_id':'ibk','url':url,'html':html,'sha256':hashlib.sha256(html.encode()).hexdigest()}],
                'institutions':[{'institution_id':'ibk','rows':[row]}]}
        calls=[]
        def fetch(url):calls.append(url);return IBK_HTML.encode()
        r=audit.resolve({'status':'ok','items':[]},source,fetch_factory=lambda *a:fetch,as_of='2026-10-25')
        self.assertFalse(r['holds']);self.assertEqual(calls,[IBK_URL]);self.assertEqual(r['summary']['verified'],1)
        self.assertEqual(r['sources'][0]['classification'],'scope_unconfirmed')

    def run_audit(self, candidate_row, fetch, receipts=None, **kw):
        return audit.resolve({'status':'ok','items':[candidate_row]}, {'receipts': receipts or []},
                             fetch_factory=lambda *args: fetch, as_of='2026-10-25',sema_channels=[SEMA],**kw)

    def test_kexim_source_must_be_observed_on_hash_validated_official_listing(self):
        detail=(f'<h1 class="detail-view-title">{KEXIM_TITLE}</h1><span title="작성일">2026.10.01</span>'
                '<div class="detail-view-box">사업타당성조사 지원사업의 선정 결과를 안내합니다.<div class="detail-view-file"></div>')
        calls=[]
        def fetch(url):calls.append(url);return detail.encode()
        report=self.run_audit(candidate('kexim'),fetch,[receipt()])
        self.assertEqual(report['summary']['verified'],1);self.assertFalse(report['holds'])
        self.assertEqual(report['sources'][0]['official_notice']['date'],'2026-10-01')
        self.assertEqual(len(calls),1)
        for receipts in [[],[dict(receipt(),sha256='forged')]]:
            calls.clear();r=self.run_audit(candidate('kexim'),fetch,receipts)
            self.assertTrue(r['holds']);self.assertFalse(calls)

    def test_missing_source_or_wrong_official_board_is_not_scope_exclusion(self):
        c=candidate('kexim');c['official_url']=c['official_url'].replace('koreaexim.go.kr','evil.example')
        r=self.run_audit(c,lambda u:self.fail('unexpected request'),[receipt()])
        self.assertTrue(r['holds']);self.assertEqual(r['sources'][0]['classification'],'scope_unconfirmed')

    def test_sema_search_uses_official_links_without_guessing_third_party_pdf_id(self):
        link='/sema/bbs/B0000022/view.do?nttId=997755&menuNo=200017'
        listing=f'<html><a href="{link}">{SEMA_TITLE}</a></html>'
        detail=(f'<html><div class="view_tit">{SEMA_TITLE}</div><table><tr><th>등록일</th><td>2026-08-20</td></tr></table>'
                '<div class="b_content">과학기술인공제회 일본주식형펀드 운용사를 공개 모집합니다. 일본 상장주식을 투자대상으로 합니다.</div></html>')
        calls=[]
        def fetch(url):
            self.assertTrue(url.startswith('https://www.sema.or.kr/'));calls.append(url)
            return (detail if 'view.do?' in url else listing).encode()
        r=self.run_audit(candidate('sema'),fetch)
        self.assertEqual(r['summary']['verified'],1);self.assertFalse(r['holds'])
        self.assertIn('nttId=997755',r['sources'][0]['official_notice']['url'])
        self.assertEqual(r['sources'][0]['official_notice']['date'],'2026-08-20')
        self.assertEqual(sum('view.do?' in u for u in calls),1)

    def test_same_title_multiple_sources_remains_ambiguous(self):
        links=''.join(f'<a href="/sema/bbs/B0000022/view.do?nttId={i}">{SEMA_TITLE}</a>' for i in [1,2])
        r=self.run_audit(candidate('sema'),lambda u:('<html>'+links+'</html>').encode())
        self.assertEqual(r['summary']['verified'],0);self.assertTrue(r['holds'])
        self.assertFalse(any(x['kind']=='detail' for x in r['receipts']))

    def test_wrong_sema_board_or_duplicate_identifier_is_rejected(self):
        for url in ['https://www.sema.or.kr/sema/bbs/B0000024/view.do?nttId=1',
                    'https://www.sema.or.kr/sema/bbs/B0000022/view.do?nttId=1&nttId=2']:
            with self.subTest(url=url),self.assertRaises(ValueError):audit.sema_identity(url,SEMA)

    def test_source_failure_and_missing_publication_date_do_not_become_outside(self):
        def fail(url):raise TimeoutError('source unavailable')
        r=self.run_audit(candidate('sema'),fail)
        self.assertTrue(r['holds']);self.assertIsNone(r['sources'][0]['official_notice'])

    def test_discovery_unavailability_and_budget_never_mean_complete(self):
        r=audit.resolve({'status':'error'},{'receipts':[]},fetch_factory=lambda *a:self.fail('unexpected fetch'))
        self.assertTrue(r['holds'])
        with self.assertRaises(ValueError):audit.resolve({'status':'ok','items':[candidate('sema')]*21},{'receipts':[]})

    def test_body_budget_exhaustion_blocks_later_candidate_network_requests(self):
        first=candidate('kexim');second=copy.deepcopy(first)
        second.update(id='other-candidate',official_url=second['official_url'].replace('991100','991101'),title=KEXIM_TITLE+' 추가')
        other=receipt();other['html']=other['html'].replace('991100','991101').replace(KEXIM_TITLE,second['title'])
        other['sha256']=hashlib.sha256(other['html'].encode()).hexdigest()
        calls=[]
        def fetch(url):calls.append(url);return b'x'*(20*1024*1024+1)
        r=audit.resolve({'status':'ok','items':[first,second]},{'receipts':[receipt(),other]},fetch_factory=lambda *a:fetch)
        self.assertEqual(len(calls),1);self.assertEqual(len(r['holds']),2)
