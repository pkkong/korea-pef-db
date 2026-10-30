import base64
import copy
import io
import unittest
import zipfile
from urllib.error import HTTPError
from unittest.mock import patch, Mock
from urllib.parse import parse_qs, urlsplit
from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src.lp_notice_publication import publish_basic_notices
from services.lp.tests.test_lp_board_adapters_pensions import TP_LIST, TP_DETAIL, TP_URL

STAMP = '2026-10-20T06:00:00+00:00'


class InstitutionCollectionTests(unittest.TestCase):
    def collect(self, title=None):
        config = boards.load_configs()['tp']
        detail = TP_DETAIL.replace('선정 공고.zip', '제안서 양식.zip')
        listing = TP_LIST
        if title:
            from services.lp.tests.test_lp_board_adapters_pensions import TP_TITLE
            listing, detail = [s.replace(TP_TITLE, title) for s in (listing, detail)]
        listing, detail = ['<html>'+s+'</html>' for s in (listing, detail)]
        def fetch(url, referer=None):
            return (detail if 'detail.do?' in url else listing).encode()
        return boards.collect({'tp': config}, fetch_factory=lambda c: fetch, checked_at=STAMP)

    def test_kfinco_closed_rows_never_requested_or_retained_as_fresh_evidence(self):
        import json
        from services.lp.tests.test_lp_board_adapter_kfinco import row,listing,detail,public
        config=boards.load_configs()['kfinco']
        opened=[row('NT20990101'+str(i).zfill(6)) for i in range(3)]
        closed={**row('NT20990202020202'),'closed':1,'ntTitle':'PRIVATE','ntContent':'PRIVATE'}
        calls=[]
        def fetch(url,referer=None):
            calls.append(url)
            if '/api/pr/notice/list' in url:return listing(opened+[closed]).encode()
            match=next((r for r in opened if public(r['ntCode'])==url),None)
            self.assertIsNotNone(match,'Closed detail must never be requested')
            return detail(match).encode()
        original={'checked_at':STAMP,'notices':[],'coverage':{'kfinco':{}},
                  'holds':[{'institution_id':'kfinco','stage':'institution_listing','error':'prior restriction'}]}
        result=boards.retry_failed_sources(original,{'kfinco':config},lambda c:fetch,checked_at=STAMP)
        self.assertEqual(len(result['notices']),3)
        self.assertEqual(len(result['holds']),1)
        self.assertEqual(result['holds'][0]['stage'],'institution_restricted')
        self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertNotIn(public(closed['ntCode']),calls)
        self.assertEqual(result['coverage']['kfinco']['listing_pages'][0]['raw_count'],4)
        for notice in result['notices']:
            self.assertEqual(boards.validate_notice(notice,STAMP,config),notice)
        self.assertEqual(original['holds'][0]['stage'],'institution_listing')
        factory=Mock()
        self.assertIs(boards.retry_failed_sources(result,{'kfinco':config},factory),result)
        factory.assert_not_called()

    def test_kfinco_all_closed_and_closing_between_listing_and_detail(self):
        import json
        from services.lp.tests.test_lp_board_adapter_kfinco import row,listing,detail
        config=boards.load_configs()['kfinco']
        closed={**row(),'closed':1,'ntTitle':'PRIVATE','ntContent':'PRIVATE'}
        fetch=Mock(return_value=listing([closed]).encode())
        result=boards.collect({'kfinco':config},lambda c:fetch,checked_at=STAMP)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(result['notices'],[])
        self.assertEqual(result['holds'][0]['stage'],'institution_restricted')
        self.assertEqual(result['coverage']['kfinco']['listing_pages'][0]['raw_count'],1)
        def changed_fetch(url,referer=None):
            return (listing([row()]) if '/api/pr/notice/list' in url else detail(closed)).encode()
        changed=boards.collect({'kfinco':config},lambda c:changed_fetch,checked_at=STAMP)
        self.assertEqual(changed['notices'],[])
        self.assertEqual(changed['holds'][0]['stage'],'institution_restricted')
        self.assertNotIn('PRIVATE',json.dumps(changed))
        self.assertNotIn('retry_history',changed)

    def test_observed_official_maintenance_is_retained_without_repeated_searches(self):
        config = boards.load_configs()['kamco']
        fetch = Mock(side_effect=HTTPError('https://www.kamco.or.kr/error/system_work.html', 404, 'Not found', {}, None))
        factory = Mock(return_value=fetch)
        result = boards.collect({'kamco': config}, fetch_factory=factory, checked_at=STAMP)
        fetch.assert_called_once()
        factory.assert_called_once()
        self.assertEqual(result['notices'], [])
        self.assertEqual(result['holds'][0]['failure_kind'], 'official_maintenance')
        self.assertEqual(result['holds'][0]['http_status'], 404)
        self.assertNotIn('retry_history', result)

    def test_failed_issuer_is_retried_with_independently_validated_evidence(self):
        config = boards.load_configs()['tp']
        original = {'checked_at': STAMP, 'notices': [], 'coverage': {'tp': {}},
                    'holds': [{'institution_id': 'tp', 'stage': 'institution_listing', 'error': 'bad temporary page'}]}
        detail = TP_DETAIL.replace('선정 공고.zip', '제안서 양식.zip')
        def fetch(url, referer=None):
            return ('<html>' + (detail if 'detail.do?' in url else TP_LIST) + '</html>').encode()
        result = boards.retry_failed_sources(original, {'tp': config}, lambda c: fetch, checked_at=STAMP)
        self.assertFalse(result['holds'])
        self.assertEqual(len(result['notices']), 1)
        self.assertEqual(boards.validate_notice(result['notices'][0], STAMP), result['notices'][0])
        self.assertEqual(result['retry_history'][0]['previous_holds'], original['holds'])
        self.assertNotIn('retry_history', original)

    def test_repeated_issuer_failure_remains_visible_without_recursive_retries(self):
        config = boards.load_configs()['tp']
        original = {'checked_at': STAMP, 'notices': [], 'coverage': {'tp': {}},
                    'holds': [{'institution_id': 'tp', 'stage': 'institution_listing', 'error': 'first error'}]}
        def fetch(url, referer=None):
            raise HTTPError(url, 404, 'Missing', {}, None)
        factory = Mock(return_value=fetch)
        result = boards.retry_failed_sources(original, {'tp': config}, factory, checked_at=STAMP)
        factory.assert_called_once()
        self.assertTrue(result['holds'])
        self.assertTrue(all(h['stage'] == 'institution_listing' for h in result['holds']))
        self.assertEqual(result['notices'], [])
        self.assertEqual(len(result['retry_history']), 1)

    def test_retry_budget_does_not_expand_across_a_widespread_outage(self):
        ids = ['tp', 'cu', 'pck_pension']
        configs = {i: boards.load_configs()[i] for i in ids}
        original = {'checked_at': STAMP, 'notices': [], 'coverage': {i: {} for i in ids},
                    'holds': [{'institution_id': i, 'stage': 'institution_listing', 'error': 'offline'} for i in ids]}
        result = {'checked_at': STAMP, 'notices': [], 'coverage': {i: {} for i in ids[:2]}, 'holds': []}
        with patch.object(boards, 'collect', return_value=result) as retry:
            recovered = boards.retry_failed_sources(original, configs, checked_at=STAMP)
        self.assertEqual(list(retry.call_args.args[0]), ids[:2])
        self.assertFalse(retry.call_args.kwargs['retry_failures'])
        self.assertEqual([h['institution_id'] for h in recovered['holds']], ['pck_pension'])
        self.assertEqual(len(recovered['retry_history']), 2)

    def test_discovery_replays_actual_listing_and_detail_without_fixed_ids(self):
        report = self.collect()
        self.assertFalse(report['holds'])
        self.assertEqual(len(report['notices']), 1)
        notice = report['notices'][0]
        self.assertEqual(notice['date'], '2023-07-24')
        self.assertEqual(boards.validate_notice(notice, STAMP), notice)
        programs, holds = publish_basic_notices({'programs': [], 'institution_notices': report['notices']}, [], STAMP)
        self.assertEqual(len(programs), 1)
        self.assertIn('-2023-', programs[0]['id'])
        self.assertEqual(programs[0]['status'], '접수 마감')
        again, _ = publish_basic_notices({'programs': programs, 'institution_notices': report['notices']}, [], STAMP)
        self.assertEqual([p['id'] for p in programs], [p['id'] for p in again])

    def test_tp_title_search_survives_official_100_row_server_error(self):
        # Observed 2026-10-22: title search + pageItm=100 returned HTTP500;
        # the same official title search with pageItm=10 returned valid rows.
        config = boards.load_configs()['tp']
        calls = []
        detail = TP_DETAIL.replace('선정 공고.zip', '제안서 양식.zip')
        def fetch(url, referer=None):
            calls.append(url)
            if 'list.do?' in url:
                query = parse_qs(urlsplit(url).query)
                self.assertEqual(query['searchCondition'], ['1'])
                self.assertEqual(query['searchKeyword'], ['위탁운용사'])
                if int(query['pageItm'][0]) > 10:
                    raise HTTPError(url, 500, 'Internal Server Error', {}, None)
            return ('<html>'+(detail if 'detail.do?' in url else TP_LIST)+'</html>').encode()
        report = boards.collect({'tp': config}, fetch_factory=lambda c: fetch, checked_at=STAMP)
        self.assertFalse(report['holds'])
        self.assertEqual(len(report['notices']), 1)
        self.assertEqual(boards.validate_notice(report['notices'][0], STAMP), report['notices'][0])
        self.assertTrue(any('detail.do?' in url for url in calls))

    def test_tp_page_size_migration_retains_verified_history_without_false_errors(self):
        incoming = self.collect()
        previous = copy.deepcopy(incoming['notices'][0])
        listing = previous['discovery_provenance']['listing']
        listing['url'] = listing['url'].replace('pageItm=10&', 'pageItm=100&')
        self.assertEqual(boards.validate_notice(previous, STAMP), previous)
        merged = boards.update_catalog({'institution_notices': [previous]}, incoming, STAMP)
        self.assertFalse(merged['institution_collection_holds'])
        self.assertEqual(len(merged['institution_notices']), 1)
        self.assertIn('pageItm=10&', merged['institution_notices'][0]['discovery_provenance']['listing']['url'])
        for old,new in [('searchCondition=1','searchCondition=2'), ('searchKeyword=','searchKeyword=forged'), ('pageItm=100','pageItm=999'),
                        ('pageIndex=1','pageIndex=999'), ('www.tp.or.kr','evil.example')]:
            forged = copy.deepcopy(previous)
            forged['discovery_provenance']['listing']['url'] = listing['url'].replace(old,new)
            with self.subTest(replacement=new), self.assertRaises(ValueError):
                boards.validate_notice(forged, STAMP)
        forged = copy.deepcopy(previous)
        forged['discovery_provenance']['listing']['html'] += 'modified'
        with self.assertRaises(ValueError):boards.validate_notice(forged, STAMP)

    def test_forged_detail_listing_date_host_or_future_receipt_fails(self):
        original = self.collect()['notices'][0]
        mutations = [lambda n: n.update(body='국내 PE 블라인드 위조 본문'),
                     lambda n: n.update(date='2026-01-01'),
                     lambda n: n.update(url=n['url'].replace('tp.or.kr', 'other.example')),
                     lambda n: n.update(checked_at='2026-10-21T00:00:00+00:00'),
                     lambda n: n['discovery_provenance']['listing'].update(html='<html>forged</html>')]
        for mutate in mutations:
            n = copy.deepcopy(original)
            mutate(n)
            with self.assertRaises((ValueError, KeyError)):
                boards.validate_notice(n, STAMP)

    def test_missing_or_invalid_source_does_not_erase_verified_archive(self):
        report = self.collect()
        current = boards.update_catalog({}, report, STAMP)
        bad = copy.deepcopy(report)
        bad['notices'][0]['body'] = 'forged'
        data = boards.update_catalog(current, bad, STAMP)
        self.assertEqual(data['institution_notices'], current['institution_notices'])
        self.assertTrue(data['institution_collection_holds'])
        self.assertEqual(boards.update_catalog(current, None, STAMP)['institution_notices'], current['institution_notices'])

    def test_attachments_must_be_observed_and_reproducible_from_bytes(self):
        n = self.collect()['notices'][0]
        url = n['attachments'][0]['url']
        n['attachment_hashes'][url] = '0'*64
        n['attachment_bytes'][url] = base64.b64encode(b'fake').decode()
        with self.assertRaises(ValueError):
            boards.validate_notice(n, STAMP)
        n['attachment_hashes'] = {}
        with self.assertRaises(ValueError):
            boards.validate_notice(n, STAMP)

    def test_vc_only_notice_cannot_use_historical_pe_references(self):
        report = self.collect('2023년 사학연금 국내 VC 블라인드펀드 위탁운용사 선정 공고')
        programs, _ = publish_basic_notices({'programs': [], 'institution_notices': report['notices']}, [], STAMP)
        self.assertFalse(programs)

    def test_malformed_response_is_failure_and_valid_empty_is_zero(self):
        config = boards.load_configs()['tp']
        for html, expect in [('<html>error</html>', True), ('<html><form id="frmBbs"><div class="no-data">공지사항 데이터가 없습니다.</div></form></html>', False)]:
            report = boards.collect({'tp': config}, lambda c: lambda *args: html.encode(), STAMP)
            self.assertEqual(bool(report['holds']), expect)
            self.assertFalse(report['notices'])

    def test_zip_forms_are_not_offering_documents(self):
        self.assertTrue(boards.is_form('2-2. 제안서(한글).hwp'))
        self.assertTrue(boards.is_form('제안서_액셀.xlsx'))
        self.assertFalse(boards.is_form('1. 공고문 및 제출서류 안내.pdf'))
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('제안서 양식.hwp', 'fake')
        with self.assertRaisesRegex(ValueError, 'no readable labelled offering'):
            boards.attachment_text(output.getvalue(), '선정 공고.zip')

    def test_source_failure_is_reported_with_institution(self):
        config = boards.load_configs()['tp']
        def fail(*args):
            raise TimeoutError('offline')
        report = boards.collect({'tp':config},lambda c:fail,STAMP)
        self.assertEqual(report['holds'][0]['institution_id'],'tp')
        self.assertEqual(report['holds'][0]['stage'],'institution_listing')
        self.assertEqual(report['coverage']['tp']['detail_count'],0)


if __name__ == '__main__':
    unittest.main()
