"""Stored 2020/2021 layouts: separate PE/PDF, fund/manager counts and replay holds.

Excerpts observed in the 43673216359 retained bundle (no network in tests):
kgrowth notice 375/395 (2020 II), 489/510 (2021 III). The fixture omits the
unrelated document sections and contact details; it never pretends to be raw
publication evidence.
"""
import copy
import hashlib
import json
import unittest

from services.lp.src.lp_kgrowth_history_terms import review_bundle
from services.lp.src.lp_notice_publication import _rule_valid_name


BASE = 'https://www.kgrowth.or.kr/'
III_OFFER = '''기업구조혁신펀드(Ⅲ) 위탁운용사 선정계획 공고
2021년 기업구조혁신펀드(Ⅲ)(이하 “모펀드”) 위탁운용사 선정계획을 아래와 같이 공고합니다.
1. 선정개요 1-1. 블라인드, 모펀드제안방식 항목 내용
선정운용사수및배정금액 ◦총6개사이내에대하여3,000억원배정
리그 모펀드출자총액 선정운용사수 운용사별배정금액 펀드별최소결성금액 모펀드출자비율
PEF 1,250 2개이내 각750/500 각1,875/1,250 40%이내
PDF 1,000 2개이내 500 1,000 50%이내
PEF(루키) 750 2개이내 375 625 60%이내
소계 3,000 6개이내 총6,375 (단위:억원)
접수일시 2021년6월4일(금)09:00~16:00
1-2. 프로젝트, 운용사제안방식
위탁운용금액및선정방식 ◦약1,510억원에대하여운용사자율제안'''
III_RESULT = '''「기업구조혁신펀드(III)」 위탁운용사 선정 결과를 공지합니다.
<PEF>
엔에이치투자증권 / 오퍼스프라이빗에쿼티
케이티비 프라이빗에쿼티
<PDF>
큐리어스파트너스
화인자산운용
<루키>
유일기술투자
휘트린씨앤디 / 멜론파트너스
* 각 리그별 가나다 순'''
II_OFFER = '''기업구조혁신펀드(Ⅱ) 위탁운용사 선정계획 공고
2020년「기업구조혁신펀드(Ⅱ)」위탁운용사선정계획을아래와같이공고합니다.
1.선정개요 항목 블라인드펀드 프로젝트펀드 PEF PDF
위탁운용금액 ◦총2,006억원이내 ◦총1,503억원이내
·모펀드1,003억원이내 ·지정출자자(예정)주)500억원이내
◦총2,006억원이내(500억원이내부채투자전용)
선정운용사수 ◦3개사이내:제안펀드별500~1,006억원범위에서제안
◦2개사:제안펀드별각751.5억원으로제안 ◦수시접수및선정'''
II_RESULT = '''「기업구조혁신펀드(II)」 위탁운용사 선정 결과를 공지합니다.
<PEF>
운용사명
에버베스트파트너스
하나금융투자
한국투자프라이빗에쿼티
에스지프라이빗에쿼티
화인자산운용
KB인베스트먼트
<PDF>
운용사명
유진자산운용
에스케이에스프라이빗에쿼티
신한금융투자'''


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def notice(ident, title, day, body, attachment=None):
    n = {'source_id': ident, 'institution_id': 'kgrowth', 'source_channel': 'institution_board',
         'url': f'{BASE}notice_view.asp?idx={ident}&str_type=1&tab=1',
         'title': title, 'date': day, 'body': body, 'checked_at': '2026-11-15T06:00:00+00:00',
         'attachments': [], 'attachment_hashes': {}, 'attachment_texts': {},
         'discovery_provenance': {'kind': 'kgrowth_history_2020_v1', 'detail_sha256': 'a' * 64}}
    n['sha256'] = digest(json.dumps([title, day, body], ensure_ascii=False))
    if attachment:
        url = f'{BASE}down_file.asp?idx={ident}&SelType=Notice1'
        n['attachments'] = [url]
        n['attachment_hashes'][url] = 'b' * 64
        n['attachment_texts'][url] = attachment
    return n


def bundle(*notices):
    html = '<html><table>' + ''.join(
        f'<tr><td>{i}</td><td><a href="{n["url"]}">{n["title"]}</a></td><td>{n["date"]}</td></tr>'
        for i, n in enumerate(notices, 1)) + '</table></html>'
    receipt = {'url': BASE + 'notice.asp?str_type=1&tab=1&page=40', 'html': html, 'sha256': digest(html)}
    notices = copy.deepcopy(notices)
    for n in notices:
        n['discovery_provenance']['listing'] = {k: receipt[k] for k in ('url', 'sha256')}
    return {'kind': 'lp_institution_history_v1', 'institution_id': 'kgrowth',
            'listing_receipts': {receipt['sha256']: receipt}, 'notices': list(notices),
            'checked_at': '2026-11-15T06:00:00+00:00'}


def iii(*, result=III_RESULT, result_title=None, offer_title=None, offered=III_OFFER):
    return bundle(
        notice('489', offer_title or '【선정공고】 「기업구조혁신펀드(III)」 위탁운용사 선정계획 공고',
               '2021-05-17', '첨부와 같이 위탁운용사 선정계획을 공고합니다.', offered),
        notice('510', result_title or '【선정결과】 「기업구조혁신펀드(III)」 위탁운용사 선정 결과',
               '2021-06-28', result))


def review(b, *, known=()):
    return review_bundle(b, valid_name=_rule_valid_name, known_gp_names=known)


class GrowthHistoryReviewTests(unittest.TestCase):
    def test_observed_three_track_table_excludes_pdf_budget(self):
        r = review(iii())
        self.assertEqual(r['metadata_check']['errors'], [])
        p = r['groups'][0]
        self.assertEqual([(t['label'], t['amount_krw'], t['planned_fund_count']) for t in p['offering']['tracks']],
                         [('PEF', 125_000_000_000, 2), ('PEF(루키)', 75_000_000_000, 2)])
        self.assertEqual(p['offering']['excluded_tracks'][0]['amount_krw'], 100_000_000_000)
        self.assertFalse(p['offering']['domestic_investment_verified'])
        self.assertIn(p['offering']['evidence']['quote'], III_OFFER)

    def test_co_gp_team_is_one_fund_and_two_managers(self):
        p = review(iii())['groups'][0]
        self.assertEqual([(r['label'], r['fund_count'], r['manager_count']) for r in p['rosters']], [('PEF', 2, 3)])
        self.assertEqual(p['rosters'][0]['teams'][0],
                         {'managers': ['엔에이치투자증권', '오퍼스프라이빗에쿼티'], 'co_gp': True})
        self.assertEqual(p['rosters'][0]['teams'][1]['managers'], ['케이티비 프라이빗에쿼티'])
        self.assertNotIn('큐리어스파트너스', json.dumps(p['rosters'], ensure_ascii=False))

    def test_unrecognized_name_holds_its_whole_explicit_track(self):
        p = review(iii())['groups'][0]
        self.assertEqual([r['label'] for r in p['rosters']], ['PEF'])
        self.assertTrue(any(h.get('track') == 'PEF(루키)' and '이름' in h['reason'] for h in p['holds']))

    def test_only_verified_known_name_can_complete_rookie_track(self):
        p = review(iii(), known={'휘트린씨앤디'})['groups'][0]
        self.assertEqual([(r['label'], r['fund_count'], r['manager_count']) for r in p['rosters']],
                         [('PEF', 2, 3), ('PEF(루키)', 2, 3)])

    def test_2020_six_pef_result_rows_do_not_become_three_blind_funds(self):
        b = bundle(notice('375', '【선정공고】 「기업구조혁신펀드(II)」 위탁운용사 선정계획 공고',
                          '2020-06-05', '첨부와 같이 선정계획을 공고합니다.', II_OFFER),
                   notice('395', '【선정결과】 「기업구조혁신펀드(II)」 위탁운용사 선정 결과',
                          '2020-07-30', II_RESULT))
        p = review(b)['groups'][0]
        self.assertEqual(p['offering']['tracks'][0]['planned_fund_count'], 3)
        self.assertEqual(p['offering']['tracks'][0]['amount_krw'], 200_600_000_000)
        self.assertEqual(p['rosters'], [])
        self.assertTrue(any('행 수 불일치' in h['reason'] for h in p['holds']))

    def test_changed_total_cannot_create_partial_budget(self):
        r = review(iii(offered=III_OFFER.replace('3,000억원배정', '3,001억원배정')))
        self.assertIsNone(r['groups'][0]['offering'])
        self.assertEqual(r['groups'][0]['rosters'], [])
        self.assertTrue(any('합계 불일치' in h['reason'] for h in r['groups'][0]['holds']))

    def test_result_year_and_round_are_not_matched_by_proximity(self):
        for title in ('【선정결과】 「기업구조혁신펀드(III)」 2022년 위탁운용사 선정 결과',
                      '【선정결과】 「기업구조혁신펀드(II)」 위탁운용사 선정 결과',
                      '【선정결과】 「기업구조혁신펀드(III)」 2차 위탁운용사 선정 결과'):
            with self.subTest(title=title):
                r = review(iii(result_title=title))
                self.assertEqual(len(r['groups']), 2)
                self.assertTrue(all(not p['rosters'] for p in r['groups']))

    def test_bracketed_selection_word_does_not_turn_screening_into_final(self):
        r = review(iii(result_title='【선정결과】 「기업구조혁신펀드(III)」 위탁운용사 선정 1차 심사 결과'))
        self.assertEqual(len(r['groups']), 1)
        self.assertEqual(r['groups'][0]['rosters'], [])

    def test_two_recruitments_cannot_share_one_result(self):
        original = iii()
        second = copy.deepcopy(original['notices'][0])
        second.update(source_id='490', url=f'{BASE}notice_view.asp?idx=490&str_type=1&tab=1')
        second.update(attachments=[], attachment_hashes={}, attachment_texts={})
        b = bundle(*original['notices'], second)
        r = review(b)
        self.assertIsNone(r['groups'][0]['offering'])
        self.assertEqual(r['groups'][0]['rosters'], [])

    def test_altered_body_is_excluded_by_stored_fingerprint(self):
        b = iii()
        b['notices'][1]['body'] = III_RESULT.replace('오퍼스프라이빗에쿼티', '다른파트너스')
        r = review(b)
        self.assertEqual(len(r['metadata_check']['errors']), 1)
        self.assertIn('본문 지문', r['metadata_check']['errors'][0]['reason'])
        self.assertEqual(r['groups'][0]['rosters'], [])

    def test_changed_listing_html_fails_before_parsing(self):
        b = iii()
        next(iter(b['listing_receipts'].values()))['html'] += '<!--changed-->'
        with self.assertRaisesRegex(ValueError, '목록.*지문'):
            review(b)

    def test_attachment_must_have_been_observed_on_same_notice(self):
        b = iii()
        n = b['notices'][0]
        previous = next(iter(n['attachment_texts']))
        altered = previous.replace('idx=489', 'idx=510')
        n['attachments'] = [altered]
        n['attachment_hashes'] = {altered: n['attachment_hashes'][previous]}
        n['attachment_texts'] = {altered: n['attachment_texts'][previous]}
        r = review(b)
        self.assertEqual(len(r['metadata_check']['errors']), 1)
        self.assertEqual(r['summary']['parsed_offerings'], 0)

    def test_missing_result_heading_is_held_without_crashing_the_bundle(self):
        r = review(iii(result=III_RESULT.replace('<PEF>', '<일반>')))
        p = r['groups'][0]
        self.assertEqual(p['rosters'], [])
        self.assertTrue(any('구분 미확인' in h['reason'] for h in p['holds']))

    def test_unrecognized_result_proviso_is_not_silently_discarded(self):
        r = review(iii(result=III_RESULT.replace('* 각 리그별 가나다 순', '* 선정 예정이며 추가 심사 후 확정')))
        p = r['groups'][0]
        self.assertEqual(p['rosters'], [])
        self.assertTrue(any('추가 주석' in h['reason'] for h in p['holds']))

    def test_repeated_manager_is_not_accepted_as_multiple_funds(self):
        r = review(iii(result=III_RESULT.replace('케이티비 프라이빗에쿼티', '오퍼스프라이빗에쿼티')))
        self.assertEqual(r['groups'][0]['rosters'], [])
        self.assertTrue(any('중복' in h['reason'] for h in r['groups'][0]['holds']))

    def test_mixed_legal_forms_do_not_authorize_an_independent_pe_track(self):
        offered = ('사회투자펀드 위탁운용사 선정계획 공고 출자대상투자기구 '
                   '경영참여형사모집합투자기구, 벤처투자조합, 신기술사업투자조합 '
                   '위탁운용금액 총300억원 선정운용사수 3개사')
        r = review(iii(offered=offered))
        self.assertEqual(r['summary']['parsed_offerings'], 0)
        self.assertTrue(any('독립 PE' in h['reason'] for h in r['groups'][0]['holds']))

    def test_unicode_roman_numeral_keeps_same_fund_identity(self):
        r = review(iii(offer_title='【선정공고】 「기업구조혁신펀드(Ⅲ)」 위탁운용사 선정계획 공고'))
        self.assertEqual(len(r['groups']), 1)
        self.assertEqual(r['groups'][0]['identity']['fund'], '기업구조혁신펀드(III)')

    def test_wrong_fund_or_year_in_attached_offering_stays_held(self):
        for offered in (III_OFFER.replace('기업구조혁신펀드', '다른펀드'),
                        III_OFFER.replace('2021년', '2022년')):
            with self.subTest(offered=offered[:80]):
                r = review(iii(offered=offered))
                self.assertIsNone(r['groups'][0]['offering'])
                self.assertEqual(r['groups'][0]['rosters'], [])
                self.assertTrue(any('펀드명·연도' in h['reason'] for h in r['groups'][0]['holds']))

    def test_even_complete_reading_requires_raw_and_domestic_scope_replay(self):
        r = review(iii(), known={'휘트린씨앤디'})
        self.assertFalse(r['publication_ready'])
        self.assertTrue(r['raw_replay_required'])
        self.assertFalse(r['metadata_check']['detail_raw_present'])
        self.assertFalse(r['metadata_check']['attachment_bytes_present'])
        self.assertTrue(any('원본 재생' in h['reason'] for h in r['groups'][0]['holds']))


if __name__ == '__main__':
    unittest.main()
