import json
import unittest
from services.lp.src.lp_board_adapter_kfinco import parse_listing,parse_detail,last_page,detail_request
from services.lp.src.discover_kfinco_originals import LIST_URL,BASE

CONFIG={'institution_id':'kfinco','listing_url':LIST_URL}
CODE='NT20990101010101'
def row(ident=CODE,date='2026-09-30',title='2026년 국내 사모투자 위탁운용사 선정 계획 공고'):
    return {'ntCode':ident,'ntDate':date,'ntTitle':title,'closed':0,'noticeAttachModelList':[]}
def listing(rows,total=None):return json.dumps({'success':True,'list':rows,'totalCount':len(rows) if total is None else total})
def detail(r,body='<p>공식 공고 본문입니다.</p>'):return json.dumps({'success':True,'detail':{**r,'ntContent':body}})
def public(ident=CODE):return BASE+'/pr/notice/detail/'+ident

class KfincoAdapterTests(unittest.TestCase):
    def test_diagnostic_retains_only_safe_identifiers_and_closed_flags(self):
        from services.lp.src.lp_board_adapter_kfinco import diagnostic_listing_metadata
        rows=[{**row(),'closed':1,'ntContent':'PRIVATE','noticeAttachModelList':[{'secret':'PRIVATE'}]},
              {**row('NT20990202020202'),'closed':0}]
        report=diagnostic_listing_metadata(listing(rows))
        self.assertEqual([r['closed'] for r in report['rows']],[1,0])
        self.assertEqual(report['total_count'],2)
        self.assertNotIn('PRIVATE',json.dumps(report))
        self.assertNotIn('ntTitle',json.dumps(report))
        self.assertEqual(set(report['rows'][0]),{'row','source_id','closed_type','closed'})

    def test_diagnostic_does_not_echo_malformed_private_values(self):
        from services.lp.src.lp_board_adapter_kfinco import diagnostic_listing_metadata
        r={**row(),'ntCode':'PRIVATE','closed':'PRIVATE'}
        report=diagnostic_listing_metadata(listing([r]))
        self.assertNotIn('PRIVATE',json.dumps(report))
        self.assertEqual(report['rows'][0]['closed_type'],'str')
        del r['closed']
        self.assertEqual(diagnostic_listing_metadata(listing([r]))['rows'][0]['closed_type'],'missing')
        with self.assertRaises(ValueError):diagnostic_listing_metadata('{"success":false}')

    def test_arbitrary_observed_id_public_url_and_request_mapping(self):
        found=parse_listing(listing([row()]),LIST_URL,CONFIG)[0]
        self.assertEqual(found['source_id'],'kfinco:'+CODE)
        self.assertEqual(found['url'],public())
        self.assertEqual(detail_request(found['url']),BASE+'/api/pr/notice/detail/'+CODE)
        self.assertEqual(parse_detail(detail(row()),public(),CONFIG)['body'],'공식 공고 본문입니다.')

    def test_separate_june_and_september_titles_and_unrelated_scope_preserved(self):
        rows=[row(),row('NT20990202020202','2026-06-18'),row('NT20990303030303','2026-07-01','국내주식 또는 해외주식 위탁운용사 선정 공고')]
        parsed=parse_listing(listing(rows),LIST_URL,CONFIG)
        self.assertEqual(len(parsed),3)
        self.assertEqual(len({n['source_id'] for n in parsed}),3)
        for r in rows:self.assertEqual(parse_detail(detail(r),public(r['ntCode']),CONFIG)['title'],r['ntTitle'])

    def test_empty_and_depth_without_inventing_next_page(self):
        self.assertEqual(parse_listing(listing([]),LIST_URL,CONFIG),[])
        self.assertEqual(last_page(listing([]),LIST_URL,CONFIG),1)
        rows=[row('NT20990101'+str(i).zfill(6)) for i in range(10)]
        self.assertEqual(last_page(listing(rows,11),LIST_URL,CONFIG),2)
        with self.assertRaises(ValueError):parse_listing(listing(rows),LIST_URL.replace('page=1','page=2'),CONFIG)
        with self.assertRaises(ValueError):parse_listing(listing(rows[:1],3),LIST_URL,CONFIG)

    def test_malformed_metadata_and_closed_are_explicit_errors(self):
        for r in [{**row(),'ntCode':'NT1'},{**row(),'ntDate':'2026-02-30'},{**row(),'ntTitle':''},{**row(),'closed':False}]:
            with self.assertRaises(ValueError):parse_listing(listing([r]),LIST_URL,CONFIG)
        with self.assertRaises(ValueError):parse_listing(listing([row(),row()]),LIST_URL,CONFIG)
        with self.assertRaises(ValueError):parse_detail(detail(row('NT20990202020202')),public(),CONFIG)
        with self.assertRaises(ValueError):parse_detail(detail(row(),'<script>not a notice</script>'),public(),CONFIG)

    def test_mixed_and_all_closed_preserve_slots_without_private_metadata(self):
        from services.lp.src.lp_board_adapter_kfinco import listing_parts,listing_receipt,RestrictedNotice
        closed={**row('NT20990202020202'),'closed':1,'ntTitle':'PRIVATE','ntContent':'PRIVATE'}
        raw=listing([row(),closed])
        opened,holds,count,total=listing_parts(raw,LIST_URL,CONFIG)
        self.assertEqual((len(opened),len(holds),count,total),(1,1,2,2))
        self.assertEqual(set(holds[0]),{'source_id','url','reason'})
        receipt=listing_receipt(raw,LIST_URL,CONFIG)
        self.assertNotIn('PRIVATE',receipt)
        self.assertEqual(parse_listing(receipt,LIST_URL,CONFIG),opened)
        self.assertEqual(parse_listing(listing([closed]),LIST_URL,CONFIG),[])
        self.assertEqual(last_page(listing([closed]),LIST_URL,CONFIG),1)
        with self.assertRaises(RestrictedNotice):parse_detail(detail(closed),public(closed['ntCode']),CONFIG)
        with self.assertRaises(ValueError):parse_listing(listing([row(),{**closed,'ntCode':CODE}]),LIST_URL,CONFIG)
        with self.assertRaises(ValueError):parse_listing(listing([closed],2),LIST_URL,CONFIG)
        for flag in (None,True,False,'1',2,-1,1.0):
            with self.subTest(flag=flag),self.assertRaises(ValueError):
                parse_listing(listing([{**row(),'closed':flag}]),LIST_URL,CONFIG)
        missing=row();del missing['closed']
        with self.assertRaises(ValueError):parse_listing(listing([missing]),LIST_URL,CONFIG)

    def test_foreign_query_and_encoded_traversal_rejected(self):
        for url in [public().replace('www.kfinco.co.kr','evil.test'),public()+'?x=1',public()+'#x',public().replace('/pr/','/private/../pr/'),public().replace('/pr/','/%70r/')]:
            with self.assertRaises(ValueError):detail_request(url)
        for url in [LIST_URL+'&page=1',LIST_URL.replace('size=10','size=100'),LIST_URL.replace('https:','http:')]:
            with self.assertRaises(ValueError):parse_listing(listing([]),url,CONFIG)
        with self.assertRaises(ValueError):parse_listing(listing([]),LIST_URL,{**CONFIG,'institution_id':'other'})

    def test_official_attachments_and_forms(self):
        a={'ntCode':CODE,'filepath':'/pds/notice/2026-09','filenameSave':'abc.hwp','filenameOriginal':'선정 공고문.hwp'}
        r={**row(),'noticeAttachModelList':[a,{'filenameOriginal':'양식.zip'}]}
        files=parse_detail(detail(r),public(),CONFIG)['attachments'];self.assertEqual(len(files),1)
        self.assertIn('/util/download?filePath=',files[0]['url'])
        r['noticeAttachModelList'][0]={**a,'filepath':'/pds/notice/2026-09/../private'}
        with self.assertRaises(ValueError):parse_detail(detail(r),public(),CONFIG)

if __name__=='__main__':unittest.main()
