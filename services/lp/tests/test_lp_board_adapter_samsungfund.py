"""산재보험기금 OCIO (삼성자산운용) notices: results only, fund named, PE track."""
import copy
import unittest
from urllib.parse import quote

from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src import lp_board_adapter_samsungfund as sam
from services.lp.src.lp_notice_publication import publish_basic_notices

STAMP = '2026-11-15T06:00:00+00:00'
FUND = '산재보험기금'
LIST = f'https://{sam.HOST}{sam.LIST_PATH}?category=ALL&searchText={quote(FUND)}&pageNo='

# Observed on m.samsungfund.com 2026-11-15 (titles, ids, dates and body text verbatim).
ROWS = [
    (244408, '2026년 산재보험기금 대체투자상품(PE) 선정 최종 결과 안내', '2026.08.25', ''),
    (243848, '2026년 산재보험기금 대체투자상품(VC) 선정 최종 결과 안내 ', '2026.08.07', ''),
    (242508, '2026년 산재보험기금 대체투자상품(PEF, VC) 선정 공고', '2026.07.01', 'attach'),
    (234868, '2025년 산재보험기금 하위운용사 유니버스 최종 선정결과 안내', '2025.09.22', 'attach'),
    (232031, '2025년 산재보험기금 대체투자상품(PEF) 선정 최종 결과 안내', '2025.05.14', ''),
    (231270, '2025년 산재보험기금 대체투자상품(PEF) 선정 공고', '2025.04.01', 'attach'),
    (228901, '2024년 산재보험기금 대체투자상품(VC) 선정 최종 결과 안내', '2024.12.16', ''),
    (228616, '2024년 산재보험기금 대체투자상품(크레딧 PEF) 선정 최종 결과 안내 ', '2024.11.29', ''),
    (227748, '2024년 산재보험기금 대체투자상품(PEF, VC) 선정 공고', '2024.10.18', 'attach'),
    (219548, '2023년 산재보험기금 대체투자상품(PEF) 선정 최종 결과 안내', '2023.11.02', ''),
    (209862, '2022년 산재보험기금 대체투자상품(PEF, VC) 선정 최종 결과 안내', '2022.08.04', ''),
    (186808, '2020년 산재보험기금 대체투자상품(PEF) 선정 최종 결과 안내', '2020.12.14', 'attach'),
    (183708, '2020년 산재보험기금 대체투자상품(PEF) 선정 공고', '2020.11.03', 'attach'),
    (162991, '2020년 산재보험기금 하위운용사 유니버스 추가 선정 계획 공고', '2020.01.29', 'attach'),
]
BODIES = {
    244408: '<h3>2026년 산재보험기금 대체투자상품(PE) 선정 최종 결과를 다음과 같이 공지합니다.</h3>\n<h3> </h3>\n'
            '<h3><br>□ 비엔더블유인베스트먼트 에이치앤큐에쿼티파트너스 제네시스프라이빗에쿼티</h3>\n<h3>※ 이상 가나다순</h3>',
    232031: '<p>2025년 산재보험기금 대체투자상품(PEF) 선정 최종 결과를 다음과 같이 공지합니다.</p>\n<p> </p>\n'
            '<p>□ 대형 2개사(제이케이엘파트너스, 프랙시스캐피탈파트너스), 중형 3개사(다올프라이빗에쿼티, '
            '이음프라이빗에쿼티, 케이와이프라이빗에쿼티)</p>\n<p> </p>\n<p>※ 이상 가나다순</p>\n<p>감사합니다.</p>',
    209862: '<p>2022년 산재보험기금 대체투자상품(PEF, VC) 선정 최종 결과를 다음과 같이 공지합니다. <br><br> </p>'
            '<p> □ PEF 3개사: 스카이레이크에쿼티파트너스, 스톤브릿지캐피탈, 아이엠엠프라이빗에쿼티</p>'
            '<p> □ VC 4개사: DSC인베스트먼트, 인터베스트 (이상 대형리그) 뮤렉스파트너스, 위벤처스 (이상 중소형리그)</p>'
            '<p> ※ 이상 가나다순 </p>',
    186808: '<p><span style="color: rgb(0, 0, 0); font-size: 10pt;">2020년 산재보험기금 대체투자상품(PEF) 선정 최종 결과를 '
            '다음과 같이 공지합니다.<br> </span></p><p><span style="color: rgb(0, 0, 0); font-size: 10pt;"> □ PEF 3개사: '
            '스틱인베스트먼트, 아이엠엠인베스트먼트, 어펄마캐피탈</span></p><p> ※ 이상 가나다순 </p>',
}


def fragment(rows):
    items = ''.join(
        f"\n<li>\n\t<a href=\"javascript:goDetail('notice-view.do?no={no}&searchText={FUND}')\">\n"
        f"\t\t<h3 class=\"tit m_title_16-17 {attach}\">\n\t\t\t{title}\n"
        + ('\t\t\t<div class="icon-attach"></div>\n' if attach else '\t\t\t\n')
        + f"\t\t</h3>\n\t\t<span class=\"m_category_13 date\">{day}</span>\n\t</a>\n</li>\n"
        for no, title, day, attach in rows)
    return '\n\n' + items


def detail(no, title=None, day=None, files=()):
    row = next(r for r in ROWS if r[0] == no)
    title, day = title or row[1].strip(), day or row[2]
    downloads = ''.join(
        f'<div class="download-wrap"><a href="/fund/download.do?fileSeq={no}&fileNo={k}" class="btn" download="">'
        f'<span class="txt  m_title_14 ">{name}</span><img src="/assets/icons/basic/download.svg" alt=""></a></div>'
        for k, name in enumerate(files, 1))
    return ('<!DOCTYPE html>\n<html lang="ko"><head><meta charset="UTF-8"><title>' + title + ' | 공지사항 | 삼성자산운용</title>'
            '</head><body><main class=" main notice-view-wrap "><div class="viewer show download"><div class="container-m">'
            '<div class="viewer-title-wrap"><h2 class="tit m_headline_24-36">' + title + '</h2>'
            '<p class="date m_date_11-12">' + day + '</p></div><div class="viewer-content-wrap">'
            '<div class="con con-textarea">' + BODIES.get(no, '<p>본문</p>') + '</div>'
            + (f'<div class="con con-download-wrap"><h3 class="m_title_18 download-tit">첨부파일</h3>{downloads}</div>' if files else '')
            + '</div><div class="bt-detail"><a href="notice.do">목록보기</a></div></div></div></main></body></html>')


def config():
    return boards.load_configs()['moel_iaci_ocio']


class SamsungFundAdapterTests(unittest.TestCase):
    def test_channel_is_a_second_board_of_the_fund(self):
        c = config()
        self.assertEqual((c['institution_id'], c['channel_id'], c['since']), ('moel_iaci', 'moel_iaci_ocio', '2020-01-01'))
        self.assertIs(boards.adapter(c), sam)
        self.assertIs(boards.adapter(boards.load_configs()['moel_iaci']).__name__.endswith('moel'), True)
        self.assertEqual(list(boards.listing_urls(c))[0], LIST + '1')

    def test_listing_keeps_only_the_funds_pe_results(self):
        rows = sam.parse_listing(fragment(ROWS[:10]), LIST + '1', config())
        self.assertEqual(len(rows), 10)
        kept = [r['title'] for r in rows if r['institution_id'] == 'moel_iaci']
        self.assertEqual(kept, ['2026년 산재보험기금 대체투자상품(PE) 선정 최종 결과 안내',
                                '2025년 산재보험기금 대체투자상품(PEF) 선정 최종 결과 안내',
                                '2024년 산재보험기금 대체투자상품(크레딧 PEF) 선정 최종 결과 안내',
                                '2023년 산재보험기금 대체투자상품(PEF) 선정 최종 결과 안내'])
        self.assertEqual(rows[0]['url'], f'https://{sam.HOST}{sam.DETAIL_PATH}?no=244408')
        self.assertEqual(rows[0]['source_id'], 'moel_iaci:samsungfund:244408')
        self.assertEqual(sam.last_page(fragment(ROWS[:10]), LIST + '1', config()), 2)
        self.assertEqual(sam.last_page(fragment(ROWS[10:]), LIST + '2', config()), 2)
        self.assertEqual(sam.parse_listing('\n\n', LIST + '3', config()), [])

    def test_listing_rejects_other_searches_links_and_documents(self):
        with self.assertRaises(ValueError):
            sam.parse_listing(fragment(ROWS[:1]), LIST.replace(quote(FUND), quote('고용보험기금')) + '1', config())
        with self.assertRaises(ValueError):
            sam.parse_listing(fragment(ROWS[:1]).replace("javascript:goDetail", "https://evil.example/"), LIST + '1', config())
        with self.assertRaises(ValueError):
            sam.parse_listing('<html>' + fragment(ROWS[:1]) + '</html>', LIST + '1', config())
        with self.assertRaises(ValueError):
            sam.parse_listing(fragment(ROWS[:1]), LIST.replace(sam.HOST, 'www.samsungfund.com') + '1', config())

    def test_detail_body_and_attachments(self):
        url = f'https://{sam.HOST}{sam.DETAIL_PATH}?no=186808'
        d = sam.parse_detail(detail(186808, files=['2020 하반기 대체투자상품 선정 최종 안내.hwp', '개인정보 동의서.hwp']),
                             url, config())
        self.assertEqual(d['date'], '2020-12-14')
        self.assertIn('□ PEF 3개사: 스틱인베스트먼트, 아이엠엠인베스트먼트, 어펄마캐피탈', d['body'])
        self.assertEqual(d['attachments'], [{'name': '2020 하반기 대체투자상품 선정 최종 안내.hwp',
                                             'url': f'https://{sam.HOST}/fund/download.do?fileSeq=186808&fileNo=1'}])
        with self.assertRaises(ValueError):  # a file of another notice
            sam.parse_detail(detail(186808, files=['x.hwp']).replace('fileSeq=186808', 'fileSeq=1'), url, config())
        with self.assertRaises(ValueError):  # the OCIO's own business
            sam.parse_detail(detail(186808, title='삼성자산운용 디지털마케팅 대행사 선정 공고'), url, config())


class SamsungFundCollectionTests(unittest.TestCase):
    def fetch(self, url, referer=None):
        if sam.LIST_PATH in url:
            page = int(url.rsplit('=', 1)[1])
            return fragment(ROWS[(page - 1) * 10: page * 10]).encode()
        no = int(url.rsplit('=', 1)[1])
        if 'download.do' in url:
            return b'not a parsed attachment'
        return detail(no).encode()

    def test_collects_results_since_2020_and_stops_at_the_empty_page(self):
        report = boards.collect({'moel_iaci_ocio': config()}, fetch_factory=lambda c: self.fetch,
                                checked_at=STAMP, retry_failures=False)
        self.assertEqual([h for h in report['holds'] if h['stage'] != 'institution_attachment'], [])
        titles = sorted(n['title'] for n in report['notices'])
        self.assertEqual(len(titles), 6)
        self.assertTrue(all('결과' in t for t in titles))
        n = next(n for n in report['notices'] if n['url'].endswith('244408'))
        self.assertEqual((n['institution_id'], n['channel_id']), ('moel_iaci', 'moel_iaci_ocio'))
        self.assertEqual(boards.validate_notice(n, STAMP)['url'], n['url'])  # config found by channel
        self.assertEqual(report['coverage']['moel_iaci_ocio']['since'], '2020-01-01')
        forged = copy.deepcopy(n)
        del forged['channel_id']
        with self.assertRaises((ValueError, KeyError)):
            boards.validate_notice(forged, STAMP)

    def test_channel_holds_name_the_fund_and_retry_the_channel(self):
        def broken(url, referer=None):
            if sam.LIST_PATH in url:
                raise OSError('connection reset')
            return self.fetch(url, referer)
        attempts = []
        def factory(c):
            attempts.append(c.get('channel_id'))
            return broken
        report = boards.collect({'moel_iaci_ocio': config()}, fetch_factory=factory, checked_at=STAMP)
        self.assertEqual(attempts, ['moel_iaci_ocio', 'moel_iaci_ocio'])
        self.assertTrue(report['holds'])
        self.assertTrue(all((h['institution_id'], h['channel_id']) == ('moel_iaci', 'moel_iaci_ocio') for h in report['holds']))
        self.assertEqual(report['retry_history'][0]['institution_id'], 'moel_iaci_ocio')
        self.assertTrue(report['retry_history'][0]['previous_holds'])

    def test_result_attaches_to_the_funds_own_recruitment_with_its_roster(self):
        from services.lp.tests import test_lp_board_adapter_moel as moel_fx
        recruitment = '2025년 산재보험기금 대체투자상품(PEF) 선정 공고'
        moel_config = {**boards.load_configs()['moel_iaci'], 'pages': 1}
        body = ('산재보험기금 주간운용사인 삼성자산운용에서 2025년 산재보험기금 대체투자상품 선정계획을 공고하였음을 '
                '알려드립니다. ○ 선정유형: 블라인드 PEF ○ 투자금액: 총 2,400억원 (대형 1,200억원(2건), 중형 1,200억원(3건) 선정 예정)')
        listing = moel_fx.listing(rows=[moel_fx.row(moel_fx.IACI_ID, recruitment, '2025.04.01')])
        page = moel_fx.detail(moel_fx.IACI_ID, recruitment, body=body, files=False).replace('2026.08.07', '2025.04.01')

        def moel_fetch(url, referer=None):
            return (page if 'imchaeBbsView' in url else listing).encode()
        own = boards.collect({'moel_iaci': moel_config}, fetch_factory=lambda c: moel_fetch,
                             checked_at='2025-06-01T06:00:00+00:00', retry_failures=False)
        self.assertEqual(len(own['notices']), 1, own['holds'])
        ocio = boards.collect({'moel_iaci_ocio': config()}, fetch_factory=lambda c: self.fetch,
                              checked_at=STAMP, retry_failures=False)
        notices = own['notices'] + [n for n in ocio['notices'] if n['url'].endswith('232031')]
        programs, holds = publish_basic_notices({'programs': [], 'institution_notices': notices}, [], STAMP)
        self.assertEqual(len(programs), 1, holds)
        p = programs[0]
        self.assertEqual(p['status'], '선정 완료')
        self.assertEqual([g['name'] for g in p['selected_gps']],
                         ['제이케이엘파트너스', '프랙시스캐피탈파트너스', '다올프라이빗에쿼티', '이음프라이빗에쿼티', '케이와이프라이빗에쿼티'])
        self.assertTrue(all(g['source_url'].startswith(f'https://{sam.HOST}') for g in p['selected_gps']))


if __name__ == '__main__':
    unittest.main()
