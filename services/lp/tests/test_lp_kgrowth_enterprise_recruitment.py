import base64
import hashlib
import unittest

from services.lp.src import kgrowth_listing
from services.lp.src import lp_kgrowth_enterprise_recruitment as recruitment
from services.lp.tests.test_kgrowth_listing import page


TITLE = '【선정공고】 「정책형 뉴딜펀드」 2022년 1차(기업투자, 인프라) 위탁운용사 선정계획 공고'
SELECTION = {'fund': '정책형 뉴딜펀드', 'round': 1, 'date': '2022-01-07'}


def listing_bundle(*rows):
    markup = page(rows)
    digest = hashlib.sha256(markup.encode()).hexdigest()
    return {'kind': 'lp_institution_history_v1', 'institution_id': 'kgrowth', 'listing_receipts': {
        digest: {'url': kgrowth_listing.LIST_URL, 'html': markup},
    }}


class EnterpriseRecruitmentTests(unittest.TestCase):
    def test_only_the_matching_archived_enterprise_offering_is_selected(self):
        bundle = listing_bundle(('1', '80', TITLE.replace('1차', '2차'), '2022-01-07'),
                                ('2', '81', TITLE, '2022-01-07'))
        row, _, _ = recruitment.listed_recruitment(bundle, SELECTION)
        self.assertEqual(row['source_id'], '81')
        with self.assertRaises(ValueError):
            recruitment.listed_recruitment(bundle, {**SELECTION, 'date': '2022-01-06'})
        duplicate = listing_bundle(('1', '80', TITLE, '2022-01-07'), ('2', '81', TITLE, '2022-01-07'))
        with self.assertRaises(ValueError):
            recruitment.listed_recruitment(duplicate, SELECTION)

    def test_records_denial_and_stops_before_any_file_request(self):
        bundle = listing_bundle(('1', '81', TITLE, '2022-01-07'))
        saved = []
        calls = []

        def deny(url, referer, limit):
            calls.append(url)
            return 403, url, b'denied'

        report = recruitment.capture(bundle, SELECTION, lambda r: saved.append(len(r['responses'])), deny)
        self.assertEqual((len(calls), saved), (1, [0, 1, 1]))
        self.assertEqual(base64.b64decode(report['responses'][0]['raw_base64']), b'denied')
        self.assertTrue(report['holds'])
        self.assertFalse(report['published'])

    def test_follows_only_the_enterprise_pdf_from_the_verified_detail(self):
        bundle = listing_bundle(('1', '81', TITLE, '2022-01-07'))
        detail = (f'<html><body><div class="view_info"><p class="tit">{TITLE}</p><p class="date">2022-01-07</p></div>'
                  '<div class="veiw_contents">기업투자 위탁운용사 선정계획 공고</div>'
                  '<ul class="file_list"><li><a href="down_file.asp?idx=81&amp;SelType=Notice1">'
                  '기업투자(기업투자) 선정계획 공고문.pdf</a></li>'
                  '<li><a href="down_file.asp?idx=81&amp;SelType=Notice2">(인프라) 선정계획 공고문.pdf</a></li>'
                  '</ul></body></html>').encode('cp949')
        calls = []

        def respond(url, referer, limit):
            calls.append((url, referer, limit))
            return 200, url, detail if len(calls) == 1 else b'%PDF-1.4\nfixture\n%%EOF'

        report = recruitment.capture(bundle, SELECTION, lambda _: None, respond)
        self.assertEqual(report['holds'], [])
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1][0].endswith('SelType=Notice1'), calls)
        self.assertEqual(calls[1][1], calls[0][0])
        self.assertEqual(report['database_writes'], 0)
