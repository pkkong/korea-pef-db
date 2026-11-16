"""Actual excerpts of the retained 2020 comma-separated fund recruitment.

PDFs 83c976b9…, 741691f2…, 832bc718…, e06ea8e8… were byte/text replayed in
all-attachment-replay.json. Fixtures omit unrelated paragraphs and page markers;
they test text interpretation, not replacement publication evidence. No HTTP.
"""
import copy
import hashlib
import json
import unittest

from services.lp.src.lp_kgrowth_multifund_history import parse_multifund_notice


TECH = '''기술금융 투자펀드(6차) 위탁운용사 선정계획 공고
2020년기술금융투자펀드(6차)위탁운용사선정계획을아래와같이공고합니다.
1.선정개요항목세부내용위탁운용금액및결성목표액ㅇ총625억원이내
성장사다리펀드공동출자자합계결성목표액500억원이내125억원이내625억원1,250억원
선정운용사수및배정금액ㅇ위탁운용금액범위내선정-운용사별로150억원~250억원범위내에서제안
투자기구◦「자본시장과금융투자업에관한법률」에의한전문투자형사모집합투자기구,경영참여형사모집합투자기구및창업벤처전문경영참여형사모집합투자기구
◦「여신전문금융업법」에의한신기술사업투자조합
◦「벤처기업육성에관한특별조치법」에의한한국벤처투자조합
운용사신청자격ㅇ「투자기구」의관련법규에따른펀드결성과업무집행이가능한제안서접수일현재설립된법인
2.출자분야및투자대상□투자대상은법인형태의중소·중견기업및지식재산권(IP)수익화등투자로
투자기간내아래의주목적투자대상에의무투자비율이상을투자하여야함
주목적투자대상ㅇ우수기술평가기업또는지식재산권(IP)수익화등에투자대상금액*의80%이상을투자하여야하며,
①기술가치평가를받은기업에최소결성금액**의30%이상투자②지식재산권수익화등에최소결성금액**의10%이상투자
3.주요출자조건항목내용최소결성금액ㅇ 성장사다리펀드및공동출자자출자금액합산액의2배
2020년4월29일한국성장금융투자운용㈜'''
BANK = '''은행권 스타트업 동행펀드 위탁운용사 선정계획 공고
스타트업이우리나라대표기업으로성장할때까지생애주기전반에성장자금을지원할수있는은행권스타트업동행펀드위탁운용사선정계획을아래와같이공고합니다.
1.선정개요항목내용위탁운용금액◦250억원이내-은행권청년창업재단(지정출자자)50억원이내
-은행권일자리펀드100억원이내/성장사다리펀드100억원이내선정운용사수 ◦1개사
운용사신청자격◦「출자대상투자기구」의관련법규에따른펀드결성과업무집행이가능한제안서접수일현재설립된법인
투자기구◦「자본시장과금융투자업에관한법률」에의한전문투자형사모집합투자기구,경영참여형사모집합투자기구및창업벤처전문경영참여형사모집합투자기구
◦「여신전문금융업법」에의한신기술사업투자조합
◦「중소기업창업지원법」에의한중소기업창업투자조합등
운용사선정방법◦홈페이지공개모집공고를통해출자자가정한절차에따라선정
2.투자대상□투자대상기업은법인형태의국내중소·벤처기업등*(대기업제외)으로
투자기간별아래의주목적투자대상에의무투자비율이상을투자하여야함
주목적투자대상◦업력5년이하또는직전년도매출액10억원이하인중소ㆍ벤처기업에신주인수방식으로투자
3.주요출자조건항목세부내용최 소결 성 금 액◦최소300억원이상
2020년4월29일한국성장금융투자운용㈜'''
FRONT = '''FRONT1펀드위탁운용사선정계획을아래와같이공고합니다.
1.선정개요항목세부내용초기리그일반리그위탁운용금액ㅇ 총90억원-성장사다리펀드60억원-지정출자자30억원
ㅇ 총210억원-성장사다리펀드140억원-지정출자자70억원선정운용사수ㅇ 1개사ㅇ 1개사
출자대상투자기구ㅇ「자본시장과금융투자업에관한법률」에의한전문투자형사모집합투자기구,경영참여형사모집합투자기구,창업․벤처전문경영참여형사모집합투자기구
ㅇ「여신전문금융업법」에의한신기술사업투자조합
ㅇ「벤처기업육성에관한특별조치법」에의한한국벤처투자조합
운용사신청자격ㅇ「출자대상투자기구」의관련법규에따른펀드결성과업무집행이가능한제안서접수일현재설립된법인
운용사선정방법ㅇ FRONT1파트너사로선정된경우우대
FRONT1 펀드 위탁운용사 선정계획 공고
2.출자분야및투자대상□투자대상은법인형태의중소(벤처)·중견기업으로
투자기간내아래의주목적투자대상에의무투자비율이상을투자하여야함
주목적투자대상(모두충족)초기리그일반리그①FRONT1입주(졸업포함)기업및FRONT1프로그램에참여기업에약정총액의60%이상투자
3.주요출자조건항목내용초기리그일반리그최소결성금액ㅇ 120억원ㅇ 300억원
출자비율ㅇ 약정총액의75%이내ㅇ 약정총액의70%이내
2020년4월29일한국성장금융투자운용(주)'''
SEMICONDUCTOR = '''시스템반도체상생펀드 위탁운용사 선정계획 공고
2020년제1차시스템반도체상생펀드위탁운용사선정계획을아래와같이공고합니다.
1.선정개요항목세부내용위탁운용금액o총500억원이내-시스템반도체상생펀드400억원이내-성장사다리펀드100억원이내
선정운용사수o2개사이내* 위탁운용사별 최대 출자금액은 300억원, 200억원임
출자대상투자기구o‘자본시장과금융투자업에관한법률’에의한경영참여형사모집합투자기구,창업벤처전문경영참여형사모집합투자기구및전문투자형사모투자기구등
o‘여신전문금융업법’에의한신기술사업투자조합
o‘중소기업창업지원법’에의한중소기업창업투자조합
운 용 사신청자격o「출자대상투자기구」의관련법규에따른펀드결성과업무집행이가능한제안서접수일현재설립된법인
2.출자분야및투자대상□투자대상은법인형태의국내중소·중견기업*으로
투자기간내아래의주목적투자대상에350억원(펀드별210억원,140억원)이상을주식·주식연계채권등증권투자하여야함
비주목적투자대상ㅇ 반도체응용분야및유관ICT분야국내중소·중견기업
ㅇ 다만,국내반도체생태계활성화에기여할것으로기대되는해외투자*는비주목적투자로서일정범위(약정총액10%)내에서허용
3.주요출자조건항목내용최소결성금액ㅇ 500억원이상(펀드별300억원,200억원)이상
출자금액ㅇ 총500억원이내(펀드별300억원,200억원)
2020년4월29일한국성장금융투자운용(주)'''
TEXTS = [TECH, BANK, FRONT, SEMICONDUCTOR]
HASHES = ['83c976b91f3580104b22650610581c77abde1862c623188ecdf576124cea78b6',
          '741691f20f473f156e13fe831d0f7dcd66dc04d07fd7d6624e2915b267696755',
          '832bc7188a68f0aba636d2d042daf7644f5178b56759b2050306d35814ba4171',
          'e06ea8e8ccabe3ff119a39cd8fc62c1e491fd2977412ef07c5f3f3249ab175dc']


def notice(texts=TEXTS, ident='357'):
    title = '【선정공고】 기술금융, 은행권스타트업, FRONT1, 시스템반도체펀드 위탁운용사 선정계획 공고'
    day, body = '2020-04-29', '아래와 같이 위탁운용사 선정계획을 공고합니다.'
    files = [f'https://www.kgrowth.or.kr/down_file.asp?idx={ident}&SelType=Notice{i}' for i in range(1, 6)]
    return {'source_id': ident, 'institution_id': 'kgrowth', 'title': title, 'date': day, 'body': body,
            'url': f'https://www.kgrowth.or.kr/notice_view.asp?idx={ident}&str_type=1&tab=1',
            'sha256': hashlib.sha256(json.dumps([title, day, body], ensure_ascii=False).encode()).hexdigest(),
            'attachments': files, 'attachment_hashes': dict(zip(files, HASHES)),
            'attachment_texts': dict(zip(files, texts))}


def fund(report, stem):
    return next(f for f in report['funds'] if f['identity']['fund'].startswith(stem))


class GrowthMultifundTests(unittest.TestCase):
    def test_full_heading_names_and_explicit_rounds_are_separate(self):
        r = parse_multifund_notice(notice())
        self.assertEqual([(f['identity']['fund'], f['identity']['year'], f['identity']['round']) for f in r['funds']],
            [('FRONT1펀드', '2020', ''), ('기술금융투자펀드', '2020', '6차'),
             ('시스템반도체상생펀드', '2020', '1차'), ('은행권스타트업동행펀드', '2020', '')])
        self.assertEqual(len({f['fund_key'] for f in r['funds']}), 4)
        self.assertFalse(r['publication_ready'])
        self.assertTrue(r['raw_replay_required'])

    def test_technical_common_budget_is_not_growth_only_or_formation_target(self):
        f = fund(parse_multifund_notice(notice()), '기술금융')
        t = f['held_terms']
        self.assertEqual(t['shared_planned_amount_krw'], 62_500_000_000)
        self.assertEqual(t['stated_formation_target_krw'], 125_000_000_000)
        self.assertEqual([p['amount_krw'] for p in t['shared_contributors']], [50_000_000_000, 12_500_000_000])
        self.assertIsNone(t['shared_tracks'][0]['planned_fund_count'])
        self.assertEqual(t['shared_tracks'][0]['proposal_per_manager_min_krw'], 15_000_000_000)
        self.assertEqual(t['shared_tracks'][0]['proposal_per_manager_max_krw'], 25_000_000_000)
        self.assertNotIn('tracks', t)

    def test_bank_budget_and_minimum_fund_size_do_not_swap(self):
        f = fund(parse_multifund_notice(notice()), '은행권')
        t = f['held_terms']
        self.assertEqual(t['shared_planned_amount_krw'], 25_000_000_000)
        self.assertEqual(t['shared_tracks'][0]['minimum_fund_size_krw'], 30_000_000_000)
        self.assertEqual(t['shared_tracks'][0]['planned_fund_count'], 1)
        self.assertEqual(f['scope']['domestic_scope_status'], '국내 투자대상 명시')

    def test_front_leagues_are_common_legal_form_tracks_without_invented_stated_total(self):
        t = fund(parse_multifund_notice(notice()), 'FRONT1')['held_terms']
        self.assertIsNone(t['shared_planned_amount_krw'])
        self.assertEqual([(r['label'], r['amount_krw'], r['minimum_fund_size_krw'], r['lp_ratio_max_pct'])
                          for r in t['shared_tracks']],
                         [('초기리그', 9_000_000_000, 12_000_000_000, 75),
                          ('일반리그', 21_000_000_000, 30_000_000_000, 70)])

    def test_semiconductor_planned_caps_and_overseas_exception_remain_explicit(self):
        f = fund(parse_multifund_notice(notice()), '시스템')
        track = f['held_terms']['shared_tracks'][0]
        self.assertEqual(track['proposed_per_manager_maxima_krw'], [30_000_000_000, 20_000_000_000])
        self.assertEqual(track['primary_investment_minima_krw'], [21_000_000_000, 14_000_000_000])
        self.assertEqual(track['fund_count_basis'], '이내')
        self.assertEqual(f['scope']['domestic_scope_status'], '국내 주목적·해외 비주목적 허용')
        self.assertEqual(f['scope']['overseas_non_primary_max_pct'], 10)

    def test_all_mixed_legal_forms_stay_held_without_gp_rosters_or_pe_totals(self):
        r = parse_multifund_notice(notice())
        for f in r['funds']:
            self.assertTrue(f['scope']['pe_legal_form_observed'])
            self.assertTrue(f['scope']['vc_legal_forms_observed'])
            self.assertFalse(f['scope']['independent_pe_track_verified'])
            self.assertFalse(f['held_terms']['pe_scope_verified'])
            self.assertEqual(f['scope']['blind_status'], '미확인')
            self.assertNotIn('rosters', f)
            self.assertIn('독립 PE', f['held_terms']['scope_hold'])

    def test_every_quote_and_sha_points_to_its_own_retained_attachment(self):
        n = notice(); r = parse_multifund_notice(n)
        for f in r['funds']:
            for e in f['evidence']:
                self.assertIn(e['quote'], n['attachment_texts'][e['attachment_url']])
                self.assertEqual(e['attachment_sha256'], n['attachment_hashes'][e['attachment_url']])
                self.assertEqual(e['source_url'], n['url'])

    def test_advertised_fifth_attachment_is_not_an_invented_fifth_fund(self):
        r = parse_multifund_notice(notice())
        self.assertEqual(r['attachment_coverage']['advertised_count'], 5)
        self.assertEqual(r['attachment_coverage']['retained_hash_count'], 4)
        self.assertEqual(r['attachment_coverage']['retained_text_count'], 4)
        self.assertEqual(len(r['attachment_coverage']['missing_attachment_urls']), 1)
        self.assertEqual(len(r['funds']), 4)
        self.assertTrue(any('내용·펀드명 추정 금지' in h['reason'] for h in r['holds']))

    def test_budget_conflicts_hold_only_affected_fund(self):
        for i, old, new in [(0, '총625억원이내', '총626억원이내'),
                            (1, '(지정출자자)50억원이내', '(지정출자자)51억원이내'),
                            (2, '지정출자자30억원', '지정출자자31억원'),
                            (3, '펀드별210억원,140억원', '펀드별211억원,140억원')]:
            with self.subTest(attachment=i):
                texts = TEXTS.copy(); texts[i] = texts[i].replace(old, new)
                r = parse_multifund_notice(notice(texts))
                self.assertEqual(len(r['funds']), 3)
                self.assertTrue(any('불일치' in h['reason'] for h in r['holds']))

    def test_heading_intro_year_and_round_conflicts_stay_held(self):
        for i, old, new in [(0, '2020년기술금융투자펀드(6차)', '2020년다른펀드(6차)'),
                            (0, '2020년기술금융투자펀드(6차)', '2020년기술금융투자펀드(7차)'),
                            (3, '2020년제1차', '2021년제1차'),
                            (1, '2020년4월29일', '2021년4월29일')]:
            with self.subTest(attachment=i):
                texts = TEXTS.copy(); texts[i] = texts[i].replace(old, new)
                r = parse_multifund_notice(notice(texts))
                self.assertEqual(len(r['funds']), 3)
                self.assertTrue(any('충돌' in h['reason'] for h in r['holds']))

    def test_repeated_front_heading_conflict_is_not_a_new_fund(self):
        texts = TEXTS.copy(); texts[2] = FRONT.replace('FRONT1펀드위탁', '다른펀드위탁', 1)
        r = parse_multifund_notice(notice(texts))
        self.assertEqual(len(r['funds']), 3)
        self.assertTrue(any('머리말' in h['reason'] for h in r['holds']))

    def test_two_budget_tables_cannot_choose_a_preferred_amount(self):
        texts = TEXTS.copy()
        texts[0] += ('위탁운용금액및결성목표액ㅇ총626억원이내'
                     '성장사다리펀드공동출자자합계결성목표액501억원이내125억원이내626억원1,252억원')
        r = parse_multifund_notice(notice(texts))
        self.assertEqual(len(r['funds']), 3)
        self.assertTrue(any('표 미확인' in h['reason'] for h in r['holds']))

    def test_gp_domestic_qualification_does_not_fill_investment_region(self):
        texts = TEXTS.copy()
        texts[2] = FRONT.replace('현재설립된법인', '현재국내에설립된법인')
        f = fund(parse_multifund_notice(notice(texts)), 'FRONT1')
        self.assertEqual(f['scope']['domestic_scope_status'], '국내 투자범위 미확인')

    def test_attachment_order_does_not_change_identity_or_budget(self):
        n = notice(); reversed_n = copy.deepcopy(n)
        reversed_n['attachment_texts'] = dict(reversed(list(n['attachment_texts'].items())))
        self.assertEqual(parse_multifund_notice(n), parse_multifund_notice(reversed_n))

    def test_duplicate_identity_cannot_choose_a_preferred_attachment(self):
        n = notice()
        extra = n['attachments'][-1]
        n['attachment_texts'][extra] = TECH
        n['attachment_hashes'][extra] = HASHES[0]
        r = parse_multifund_notice(n)
        self.assertEqual(len(r['funds']), 3)
        self.assertTrue(any('첨부가 여러 개' in h['reason'] for h in r['holds']))

    def test_changed_notice_id_is_supported_without_id_specific_rules(self):
        self.assertEqual(len(parse_multifund_notice(notice(ident='999'))['funds']), 4)

    def test_unobserved_attachment_changed_body_and_foreign_source_fail(self):
        for mutation in ['unobserved', 'body', 'source']:
            with self.subTest(mutation=mutation):
                n = notice()
                if mutation == 'unobserved': n['attachments'] = n['attachments'][1:]
                elif mutation == 'body': n['body'] += '변경'
                else:
                    old = n['attachments'][-1]
                    n['attachments'][-1] = old.replace('www.kgrowth.or.kr', 'example.com')
                with self.assertRaises(ValueError):
                    parse_multifund_notice(n)

    def test_single_fund_or_non_recruitment_is_unsupported(self):
        for title in ['【선정공고】 「단일 펀드」 위탁운용사 선정계획 공고',
                      '【선정공고】 「핀테크혁신펀드(1차, 블라인드, 모펀드 제안방식)」 위탁운용사 선정계획 공고',
                      '【선정공고】 기술금융, 은행권스타트업, FRONT1, 시스템반도체펀드 출자사업 온라인 설명회',
                      '【선정결과】 기술금융, 은행권스타트업, FRONT1, 시스템반도체 선정 결과']:
            n = notice(); n['title'] = title
            self.assertIsNone(parse_multifund_notice(n))


if __name__ == '__main__':
    unittest.main()
