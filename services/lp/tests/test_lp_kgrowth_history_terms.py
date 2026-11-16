"""Stored 2020/2021 layouts: separate PE/PDF, fund/manager counts and replay holds.

Excerpts observed in the 43673216359 retained bundle (no network in tests):
375/395 (2020 II), 489/510 (2021 III), 619/634 (secondary), 547/571 (reorganization).
The latter PDF SHA256 values are 0d3021dc308ed5165a5fc8716da6b3f92c394a0163fbe872ca53dbb48cff7504
and 6385f7f71faafbdec92a7ec26d356ba797d0c8bbdaa93b9732449c9604384564. The fixture omits the
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
SECONDARY_OFFER = '''『LP지분 세컨더리 펀드(4차)』 선정계획 공고
2022년LP지분세컨더리펀드위탁운용사선정계획을아래와같이공고합니다.
1.선정개요항목세부내용위탁운용금액ㅇ 200억원이내(성장사다리펀드200억원)
선정운용사수분야선정 운용사 수운용사별 출자금액최소결성금액출자비율
앵커1개150억원250 억원60% 이하매칭1개50억원150 억원33% 이하
출자대상투자기구
ㅇ ‘자본시장과금융투자업에관한법률’에의한일반사모집합투자기구및기관전용사모집합투자기구
ㅇ ‘벤처투자촉진에관한법률’에의한벤처투자조합
ㅇ ‘여신전문금융업법’에의한신기술사업투자조합
운 용 사신청자격ㅇ ‘출자대상투자기구’의관련법규에따른펀드결성과업무집행이가능한제안서접수일현재설립된법인
접수일시ㅇ 신청기간:공고일이후부터소진시까지ㅇ 접수일시:신청기간내매월마지막영업일에접수
* 신청기간 내 위탁운용금액 소진 완료 시, 잔여 신청기간에도 불구하고 조기 마감
2.출자분야및투자대상□투자대상은중소·중견기업및사모펀드의LP지분으로,
투자기간내아래의주목적투자대상에아래의의무투자비율또는의무투자금액이상을투자하여야함
주목적투자대상및의무투자비율ㅇ 타사모펀드1)LP지분인수등기존사모펀드LP의출자지분을유동화하는다양한방식2)의거래에,
-(앵커)약정총액의70%이상투자-(매칭)모펀드출자금액의1.5배이상투자
1) 펀드의 투자금액 기준, 국내 중소·중견기업 비중이 70% 이상인 일반 또는 기관전용 사모집합투자기구,
한국벤처투자조합, 중소기업창업투자조합, 신기술사업투자조합 등
3.주요출자조건항목내용운용사출자금액ㅇ 약정총액의1%이상'''
SECONDARY_RESULT = '''「LP지분 세컨더리 펀드(4차)」 위탁운용사 선정 결과(6월말 접수분)를 공지합니다.
분야
운용사명
앵커
메타인베스트먼트
매칭
위벤처스
아울러, 금번 「LP지분 세컨더리 펀드(4차)」 출자사업의 위탁운용금액 소진이 완료되어,
잔여 신청 기간에도 불구하고 출자사업을 조기에 마감함을 알려드립니다.'''
REORGANIZATION_OFFER = '''사업재편펀드 위탁운용사 선정계획 공고
2021년『사업재편펀드』의위탁운용사선정계획을아래와같이공고합니다.
1.선정개요항목세부내용위탁운용금액및선정운용사수ㅇ 총500억원이상
선정운용사수출자금액최소결성금액1개사250억원* 500억원*
공동출자자:성장사다리펀드180억원,한국산업기술진흥원70억원출자
출자대상투자기구
ㅇ「자본시장과금융투자업에관한법률」에의한일반사모집합투자지구
ㅇ「자본시장과금융투자업에관한법률」에의한기관전용사모집합투자기구
ㅇ「여신전문금융업법」에의한신기술사업투자조합
ㅇ「벤처투자촉진에관한법률」에의한벤처투자조합
운용사신청자격ㅇ「출자대상투자기구」의관련법규에따른펀드결성과업무집행이가능한국내에설립된법인
접수일시ㅇ 2021년11월22일(월)(16:00限)
2.출자분야및투자대상□법인형태의국내중소·중견기업(상호출자제한기업집단소속기업제외)
주목적투자대상및의무투자비율ㅇ아래①,②을모두충족하여야함주3)
①사업재편기업에최소결성금액의60%이상투자주1)②사업재편승인기업에최소결성금액의30%이상투자주2)
주3)단일투자건의주목적투자대상중복적용가능
3.주요출자조건항목내용최소결성금액ㅇ 500억원이상
출자자제한ㅇ 출자자는국내기관투자자및법인이원칙
6.선정절차및일정□선정일정일자내용비고2021.11.22(월)제안서접수10:00~16:00
2021.12월중심사결과발표개별통지'''


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


def secondary(offered=SECONDARY_OFFER, result=SECONDARY_RESULT):
    return bundle(
        notice('619', '【선정공고】「LP지분 세컨더리 펀드(4차)」 위탁운용사 선정계획 공고',
               '2022-05-23', '첨부와 같이 선정계획을 공고합니다.', offered),
        notice('634', '【선정결과】 「LP지분 세컨더리 펀드(4차)」 위탁운용사 선정 결과_(6월말 접수분) 및 조기 마감 안내',
               '2022-07-19', result))


def reorganization(offered=REORGANIZATION_OFFER):
    return bundle(
        notice('547', '【선정공고】 「사업재편펀드」 위탁운용사 선정계획 공고',
               '2021-11-01', '첨부와 같이 선정계획을 공고합니다.', offered),
        notice('571', '【선정결과】 「사업재편펀드」 위탁운용사 선정 결과',
               '2021-12-17', '「사업재편펀드」 위탁운용사 선정 결과를 공지합니다.\n운용사명\n세븐브릿지프라이빗에쿼티(주)'))


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


class GrowthMixedHistoryReviewTests(unittest.TestCase):
    def test_anchor_matching_keeps_shared_amounts_out_of_pe_tracks(self):
        r = review(secondary())
        g = r['groups'][0]
        held = g['held_offering']
        self.assertIsNone(g['offering'])
        self.assertNotIn('tracks', held)
        self.assertEqual(g['rosters'], [])
        self.assertEqual(r['summary']['parsed_offerings'], 0)
        self.assertEqual(r['summary']['parsed_pe_offerings'], 0)
        self.assertEqual(r['summary']['parsed_mixed_offerings'], 1)
        self.assertEqual(held['shared_planned_amount_krw'], 20_000_000_000)
        self.assertEqual([(t['label'], t['amount_krw'], t['minimum_fund_size_krw'], t['lp_ratio_max_pct'])
                          for t in held['shared_tracks']],
                         [('앵커', 15_000_000_000, 25_000_000_000, 60), ('매칭', 5_000_000_000, 15_000_000_000, 33)])
        self.assertFalse(held['pe_scope_verified'])
        self.assertFalse(held['blind_track_observed'])
        self.assertTrue(any('독립 PE' in h['reason'] for h in g['holds']))

    def test_underlying_domestic_condition_and_ratio_denominators_are_separate(self):
        p = review(secondary())['groups'][0]['held_offering']
        self.assertFalse(p['domestic_investment_verified'])
        self.assertEqual(p['strategy']['target_fund_domestic_sme_min_pct'], 70)
        self.assertEqual(p['shared_tracks'][0]['investment_obligation'], {'min_pct': 70, 'basis': '약정총액'})
        self.assertEqual(p['shared_tracks'][1]['investment_obligation'], {'min_multiple': '1.5', 'basis': '모펀드 출자금액'})

    def test_exhaustion_schedule_and_early_close_have_no_invented_deadline(self):
        p = review(secondary())['groups'][0]['held_offering']
        self.assertEqual(p['deadline'], '')
        self.assertEqual(p['deadline_kind'], 'budget_exhaustion')
        self.assertEqual(p['application_cadence'], 'monthly_last_business_day')
        self.assertEqual(p['closure_event']['kind'], 'early_close')
        self.assertEqual(p['closure_event']['notice_date'], '2022-07-19')
        self.assertEqual(p['closure_event']['actual_deadline'], '')
        self.assertIn(p['closure_event']['evidence']['quote'], SECONDARY_RESULT)

    def test_exhaustion_announcement_without_early_close_does_not_imply_closure(self):
        p = review(secondary(result=SECONDARY_RESULT.split('아울러,')[0]))['groups'][0]['held_offering']
        self.assertNotIn('closure_event', p)
        self.assertEqual(p['deadline'], '')

    def test_shared_table_amount_conflicts_are_held_without_partial_fields(self):
        for offered in (SECONDARY_OFFER.replace('ㅇ 200억원이내', 'ㅇ 201억원이내'),
                        SECONDARY_OFFER.replace('성장사다리펀드200억원', '성장사다리펀드201억원'),
                        SECONDARY_OFFER.replace('앵커1개', '앵커2개'),
                        REORGANIZATION_OFFER.replace('한국산업기술진흥원70억원', '한국산업기술진흥원71억원'),
                        REORGANIZATION_OFFER.replace('최소결성금액ㅇ 500억원이상', '최소결성금액ㅇ 501억원이상'),
                        REORGANIZATION_OFFER.replace('총500억원이상', '총501억원이상')):
            with self.subTest(offered=offered[:150]):
                r = review(secondary(offered) if offered.startswith('『LP') else reorganization(offered))
                g = r['groups'][0]
                self.assertIsNone(g['held_offering'])
                self.assertIsNone(g['offering'])
                self.assertTrue(any('불일치' in h['reason'] for h in g['holds']))

    def test_reorganization_lp_commitment_is_not_minimum_fund_size(self):
        p = review(reorganization())['groups'][0]['held_offering']
        self.assertEqual(p['shared_planned_amount_krw'], 25_000_000_000)
        self.assertEqual(p['shared_tracks'][0]['minimum_fund_size_krw'], 50_000_000_000)
        self.assertEqual(sum(c['amount_krw'] for c in p['shared_contributors']), 25_000_000_000)
        self.assertEqual(p['strategy']['obligation_basis'], '최소결성금액')
        self.assertEqual(p['strategy']['reorganization_min_pct'], 60)
        self.assertEqual(p['strategy']['approved_reorganization_min_pct'], 30)
        self.assertTrue(p['strategy']['overlap_permitted'])

    def test_current_domestic_target_does_not_authorize_mixed_legal_forms_as_pe(self):
        g = review(reorganization())['groups'][0]
        self.assertTrue(g['held_offering']['domestic_investment_verified'])
        self.assertFalse(g['held_offering']['pe_scope_verified'])
        self.assertIsNone(g['offering'])
        self.assertEqual(g['rosters'], [])

    def test_gp_and_lp_domestic_qualifications_are_not_current_investment_scope(self):
        offered = REORGANIZATION_OFFER.replace('법인형태의국내중소·중견기업', '법인형태의중소·중견기업')
        p = review(reorganization(offered))['groups'][0]['held_offering']
        self.assertFalse(p['domestic_investment_verified'])

    def test_mixed_current_foreign_scope_and_legal_form_changes_are_not_pe_approval(self):
        offered = REORGANIZATION_OFFER.replace('주목적투자대상및의무투자비율', '해외기업에도투자가능\n주목적투자대상및의무투자비율')
        p = review(reorganization(offered))['groups'][0]['held_offering']
        self.assertFalse(p['domestic_investment_verified'])
        offered = REORGANIZATION_OFFER.replace('기관전용사모집합투자기구', '일반사모집합투자기구')
        g = review(reorganization(offered))['groups'][0]
        self.assertIsNone(g['offering'])
        self.assertIsNone(g['held_offering'])
        self.assertTrue(any('혼합 투자기구' in h['reason'] for h in g['holds']))

    def test_fixed_deadline_checks_both_rows_and_real_calendar(self):
        p = review(reorganization())['groups'][0]['held_offering']
        self.assertEqual(p['deadline'], '2021-11-22T16:00:00+09:00')
        for offered in (REORGANIZATION_OFFER.replace('2021.11.22(월)', '2021.11.23(화)'),
                        REORGANIZATION_OFFER.replace('10:00~16:00', '10:00~17:00'),
                        REORGANIZATION_OFFER.replace('2021년11월22일(월)', '2021년11월22일(화)'),
                        REORGANIZATION_OFFER.replace('11월22일(월)', '2월30일(월)').replace('11.22(월)', '2.30(월)'),
                        REORGANIZATION_OFFER.replace('2021년11월22일', '2022년11월22일')):
            with self.subTest(offered=offered[-150:]):
                g = review(reorganization(offered))['groups'][0]
                p = g['held_offering']
                if p is None:
                    self.assertTrue(any('펀드명·연도' in h['reason'] for h in g['holds']))
                    continue
                self.assertEqual(p['deadline'], '')
                self.assertIn('deadline_error', p)
                self.assertEqual(p['shared_planned_amount_krw'], 25_000_000_000)

    def test_other_event_time_does_not_fill_missing_reception_time(self):
        offered = REORGANIZATION_OFFER.replace('(16:00限)', '').replace('10:00~16:00', '')
        offered += '\n출자설명회 2021년11월2일(화) 16:00'
        p = review(reorganization(offered))['groups'][0]['held_offering']
        self.assertEqual(p['deadline'], '')
        self.assertIn('deadline_error', p)

    def test_all_shared_fields_have_retained_document_quotes_and_fingerprint(self):
        for b, offered in [(secondary(), SECONDARY_OFFER), (reorganization(), REORGANIZATION_OFFER)]:
            p = review(b)['groups'][0]['held_offering']
            for key, value in p.items():
                if key == 'evidence' or key.endswith('_evidence'):
                    self.assertIn(value['quote'], offered)
                    self.assertEqual(value['attachment_sha256'], 'b' * 64)

    def test_shared_result_names_are_not_sent_to_pe_name_reader(self):
        def reject_name(_):
            self.fail('혼합 모집의 GP 이름 판독은 지원하지 않음')
        for b in [secondary(), reorganization()]:
            r = review_bundle(b, valid_name=reject_name)
            self.assertEqual(r['groups'][0]['rosters'], [])

    def test_amendment_or_cancellation_does_not_reuse_original_deadline(self):
        for kind in ['정정', '취소']:
            b = reorganization()
            n = b['notices'][0]
            n['title'] = n['title'].replace('선정공고', kind + '공고').replace('선정계획 공고', kind + ' 공고')
            b = bundle(n)
            n = b['notices'][0]
            n['sha256'] = digest(json.dumps([n['title'], n['date'], n['body']], ensure_ascii=False))
            r = review(b)
            self.assertTrue(all(g['offering'] is None and g['held_offering'] is None for g in r['groups']))

    def test_later_change_holds_current_terms_and_retains_original_evidence(self):
        for kind in ['정정', '연장', '취소']:
            for b in [reorganization(), secondary()]:
                with self.subTest(kind=kind, fund=b['notices'][0]['title']):
                    original = b['notices'][0]
                    fund = '사업재편펀드' if '사업재편' in original['title'] else 'LP지분 세컨더리 펀드(4차)'
                    day = '2021-11-15' if '사업재편' in fund else '2022-06-01'
                    changed = notice('999', f'【{kind}공고】 「{fund}」 위탁운용사 선정계획 {kind} 공고',
                                     day, f'「{fund}」 출자금액 및 모집일정을 {kind}합니다.')
                    r = review(bundle(*b['notices'], changed))
                    self.assertEqual(len(r['groups']), 1)
                    g = r['groups'][0]
                    held = g['held_offering']
                    self.assertEqual(held['terms_status'], '변경·취소 검토')
                    self.assertEqual(held['deadline'], '')
                    self.assertEqual(held['shared_tracks'], [])
                    self.assertNotIn('shared_planned_amount_krw', held)
                    old = held['original_recruitment_terms']
                    self.assertTrue(old['shared_tracks'])
                    self.assertIn(old['evidence']['quote'], next(iter(original['attachment_texts'].values())))
                    if '사업재편' in fund:
                        self.assertEqual(old['deadline'], '2021-11-22T16:00:00+09:00')
                        self.assertEqual(old['shared_planned_amount_krw'], 25_000_000_000)
                    self.assertEqual(held['change_notices'][0]['source_url'], changed['url'])
                    self.assertTrue(any(changed['url'] in h.get('source_urls', []) for h in g['holds']))
                    self.assertIsNone(g['offering'])
                    self.assertEqual(g['rosters'], [])

    def test_another_round_change_does_not_supersede_this_recruitment(self):
        b = reorganization()
        changed = notice('999', '【연장공고】 「사업재편펀드」 2차 위탁운용사 선정계획 연장 공고',
                         '2021-11-15', '2차 모집일정을 연장합니다.')
        r = review(bundle(*b['notices'], changed))
        self.assertEqual(len(r['groups']), 2)
        original = next(g for g in r['groups'] if g['identity']['round'] == '')
        self.assertEqual(original['held_offering']['deadline'], '2021-11-22T16:00:00+09:00')
        self.assertNotIn('original_recruitment_terms', original['held_offering'])

    def test_shared_layout_still_rejects_wrong_fund_year_and_attachment_metadata(self):
        for offered in (SECONDARY_OFFER.replace('『LP지분 세컨더리 펀드(4차)』', '『다른 펀드』')
                                      .replace('2022년LP지분세컨더리펀드', '2022년다른펀드'),
                        SECONDARY_OFFER.replace('2022년', '2021년')):
            r = review(secondary(offered))
            self.assertIsNone(r['groups'][0]['held_offering'])
            self.assertTrue(any('펀드명·연도' in h['reason'] for h in r['groups'][0]['holds']))
        b = secondary()
        b['notices'][0]['attachment_hashes'] = {}
        r = review(b)
        self.assertEqual(len(r['metadata_check']['errors']), 1)
        self.assertEqual(r['summary']['parsed_mixed_offerings'], 0)


if __name__ == '__main__':
    unittest.main()
