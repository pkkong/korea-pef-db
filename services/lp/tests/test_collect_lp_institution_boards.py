import base64
import copy
import io
import unittest
import zipfile
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
