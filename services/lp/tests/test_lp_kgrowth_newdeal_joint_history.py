"""Retained 2021 regular enterprise plan, PDF eeaa48ab… (pages 1–3,5,9,12–13).

These source excerpts omit unrelated fee/GP/strategy detail. They are parser
fixtures, not replacement raw evidence or approval to publish hosted KDB funds.
"""
import copy
import unittest

from services.lp.src.lp_kgrowth_newdeal_joint_history import parse_newdeal_joint_notice
from services.lp.tests.test_lp_kgrowth_history_terms import notice


TITLE = '【선정공고】 「정책형 뉴딜펀드」 2021년 정시 위탁운용사 선정계획 공고'
BODY = '''첨부한 자료와 같이 「정책형 뉴딜펀드」 2021년 정시 위탁운용사 선정계획을 공고합니다.
○ 한국산업은행 주관사업인 투자제안형(제안규모 1,200억원 초과 블라인드펀드), 뉴딜성장형은 한국산업은행 홈페이지(공지사항) 참고'''
OFFER = '''『정책형 뉴딜펀드』2021년 정시(기업투자) 선정계획 공고
정책형뉴딜펀드2021년정시(기업투자)위탁운용사선정계획을아래와같이공고합니다.
1.개요항목세부내용정책출자자위탁운용금액○정책출자자위탁운용금액:7,450억원내외
분야별출자계획○분야별출자계획(단위:억원)
지원분야정책출자자펀드별제안규모펀드별주1)최대출자액조성목표주관기관주2)출자총액비율주1)
블라인드➊투자제안형2,10035.0%500~1,2004206,000성장1,75035.0%1,200초과8755,000산은
➋뉴딜성장형2,70030.0%1,500이상1,5009,000산은프로젝트➌투자제안형90045.0%100이상-2,000성장합계7,45022,000
주1)조성목표,정책출자비율및최대출자액은선정된운용사의제안규모,정책출자비율선택등에따라달라질수있음
주2)‘산은’은한국산업은행,‘성장’은한국성장금융투자운용㈜을의미
접수일시2021년1월26일(화)16:00까지
2.블라인드펀드가.기본항목항목세부내용
출자대상투자기구❶ 투자제안형○‘자본시장과금융투자업에관한법률’에의한경영참여형사모집합투자기구,창업‧벤처전문경영참여형사모집합투자기구
○‘여신전문금융업법’에의한신기술사업투자조합○‘벤처투자촉진에관한법률’에의한벤처투자조합
○상기와유사한목적의국내외집합투자기구,투자조합포함
❷ 뉴딜성장형○‘자본시장과금융투자업에관한법률’에의한경영참여형사모집합투자기구
※(공통사항)선정된위탁운용사는관련법규의신설‧변경등의사유로투자기구의변경을요청할수있음
운용사신청자격○제안서접수일현재「출자대상투자기구」의관련법규에따른펀드결성과업무집행이가능하도록국내에설립된법인
나.출자분야항목세부내용주목적투자비율➊투자제안형, ➋뉴딜성장형공통
○뉴딜투자가이드라인*상40개분야에목표결성금액의[60%]이상투자
*40개분야및200개세부품목은별도엑셀파일참고
○국내중소‧중견기업*에목표결성금액의[50%]이상투자
➊ 투자제안형한정○운용사가⑴,⑵중하나를주목적투자분야로선택
다.주요출자조건○약정총액의1%이상
정책출자자(정부재정,한국산업은행,성장사다리펀드)앞배분되는금액
3.프로젝트펀드(➌ 투자제안형분야)가.기본항목
접수일시○수시접수심사결과발표○수시선정
4.선정우대항목(블라인드펀드에한함)
7.선정절차및일정□선정일정일자내용비고2021.1.26(화)제안서접수10:00~16:00
2021.2월말최종선정개별통지
8.접수처및문의방법
구분➊투자제안형(1,200억원초과),➋뉴딜성장형➊투자제안형(1,200억원이하),➌투자제안형(프로젝트)
주관기관한국산업은행간접투자금융실한국성장금융투자운용본부
2020년12월29일한국산업은행한국성장금융투자운용'''


def newdeal(text=OFFER, body=BODY, title=TITLE, ident='443'):
    return notice(ident, title, '2020-12-29', body, text)


def parse(text=OFFER, body=BODY):
    return parse_newdeal_joint_notice(newdeal(text, body))


class NewdealJointRecruitmentTests(unittest.TestCase):
    def test_source_host_joint_issuers_and_four_track_leads_are_separate(self):
        n = newdeal()
        before = copy.deepcopy(n)
        r = parse_newdeal_joint_notice(n)
        self.assertEqual(n, before)
        self.assertEqual(r['identity'], {'fund': '정책형뉴딜펀드', 'year': '2021', 'round': '정시'})
        self.assertEqual(r['source_host_institution_id'], 'kgrowth')
        self.assertEqual(r['joint_issuer_institution_ids'], ['kdb', 'kgrowth'])
        self.assertEqual([t['program_lead_institution_id'] for t in r['tracks']], ['kgrowth', 'kdb', 'kdb', 'kgrowth'])
        self.assertEqual((r['issued_date'], r['posted_date']), ('2020-12-29', '2020-12-29'))
        self.assertEqual(r['terms_status'], 'original_recruitment_plan')

    def test_policy_plan_and_formation_target_are_reconciled_separately(self):
        r = parse()
        self.assertEqual(r['planned_commitment_total_krw'], 7450 * 10**8)
        self.assertEqual(r['planned_formation_total_krw'], 22000 * 10**8)
        self.assertEqual([t['planned_commitment_total_krw'] for t in r['tracks']], [2100*10**8, 1750*10**8, 2700*10**8, 900*10**8])
        self.assertEqual([t['planned_formation_total_krw'] for t in r['tracks']], [6000*10**8, 5000*10**8, 9000*10**8, 2000*10**8])
        self.assertEqual([t['planned_per_fund_commitment_max_krw'] for t in r['tracks']], [420*10**8, 875*10**8, 1500*10**8, None])
        self.assertIsNone(r['planned_contributions_krw'])
        self.assertTrue(all(t['lead_institution_own_capital_krw'] is None for t in r['tracks']))
        self.assertEqual(r['named_policy_capital_participants'], ['정부재정', '한국산업은행', '성장사다리펀드'])

    def test_at_most_and_above_boundary_do_not_overlap(self):
        small, large, growth, project = parse()['tracks']
        self.assertEqual((small['proposal_size_min_krw'], small['proposal_size_max_krw']), (500*10**8, 1200*10**8))
        self.assertTrue(small['proposal_size_min_inclusive'])
        self.assertEqual(large['proposal_size_min_krw'], 1200*10**8)
        self.assertFalse(large['proposal_size_min_inclusive'])
        self.assertIsNone(large['proposal_size_max_krw'])
        self.assertEqual(growth['proposal_size_min_krw'], 1500*10**8)
        self.assertEqual(project['fund_kind'], 'project')

    def test_current_legal_forms_and_domestic_obligation_are_scoped(self):
        tracks = parse()['tracks']
        self.assertEqual([t['pe_only_current_legal_form_observed'] for t in tracks], [False, False, True, False])
        self.assertEqual(tracks[2]['strategy']['domestic_sme_min_investment_pct'], 50)
        self.assertEqual(tracks[2]['strategy']['newdeal_min_investment_pct'], 60)
        self.assertEqual(tracks[2]['strategy']['obligation_basis'], '목표결성금액')
        self.assertNotIn('strategy', tracks[3])
        self.assertTrue(all(not t['publication_ready'] for t in tracks))

    def test_gp_names_and_fund_counts_are_not_invented_from_budgets(self):
        r = parse()
        self.assertTrue(all(t['planned_fund_count'] is None and t['selected_managers'] == [] for t in r['tracks']))
        self.assertFalse(r['publication_ready'])
        self.assertFalse(r['detail_raw_replayed'])
        self.assertFalse(r['attachment_bytes_replayed'])
        self.assertNotIn('명단이 없음', str(r))

    def test_fixed_blind_deadline_does_not_become_project_deadline(self):
        r = parse()
        self.assertEqual([t['deadline'] for t in r['tracks']], ['2021-01-26T16:00:00+09:00']*3 + [''])
        self.assertEqual(r['tracks'][3]['reception'], '수시접수·수시선정')

    def test_all_evidence_is_an_exact_source_quote_with_original_sha(self):
        n = newdeal()
        r = parse_newdeal_joint_notice(n)
        url = n['attachments'][0]
        for e in r['evidence'].values():
            self.assertIn(e['quote'], OFFER)
            self.assertEqual(e['attachment_url'], url)
            self.assertEqual(e['attachment_sha256'], n['attachment_hashes'][url])
        self.assertEqual(r['board_attribution_evidence']['quote'], BODY)

    def test_consistently_changed_plan_is_read_instead_of_forcing_original_numbers(self):
        changed = (OFFER.replace('90045.0%100이상-2,000', '99045.0%100이상-2,200')
                         .replace('합계7,45022,000', '합계7,54022,200')
                         .replace('위탁운용금액:7,450억원', '위탁운용금액:7,540억원'))
        r = parse(changed)
        self.assertEqual(r['planned_commitment_total_krw'], 7540*10**8)
        self.assertEqual(r['planned_formation_total_krw'], 22200*10**8)
        self.assertEqual(r['tracks'][3]['planned_commitment_total_krw'], 990*10**8)

    def test_consistently_changed_boundary_is_not_a_hidden_1200_constant(self):
        r = parse(OFFER.replace('1,200', '1,300'), BODY.replace('1,200', '1,300'))
        self.assertEqual(r['tracks'][0]['proposal_size_max_krw'], 1300*10**8)
        self.assertEqual(r['tracks'][1]['proposal_size_min_krw'], 1300*10**8)

    def test_changed_amount_totals_ratios_and_impossible_cap_fail_closed(self):
        for old, new in [('위탁운용금액:7,450억원', '위탁운용금액:7,451억원'),
                         ('합계7,45022,000', '합계7,45122,000'),
                         ('합계7,45022,000', '합계7,45022,001'),
                         ('90045.0%', '90145.0%'), ('2,70030.0%', '2,70031.0%'),
                         ('1,2004206,000', '1,2004216,000'), ('1,5009,000산은', '1009,000산은')]:
            with self.subTest(old=old):
                with self.assertRaises(ValueError):
                    parse(OFFER.replace(old, new))

    def test_oversized_numeric_cell_is_held_before_unbounded_splitting(self):
        with self.assertRaises(ValueError):
            parse(OFFER.replace('2,10035.0%', '9'*120 + '.0%'))

    def test_track_lead_body_referral_and_alias_contamination_fail_closed(self):
        variants = [OFFER.replace('4206,000성장', '4206,000산은'),
                    OFFER.replace('주관기관한국산업은행간접투자금융실한국성장금융투자운용본부',
                                  '주관기관한국성장금융투자운용본부한국산업은행간접투자금융실'),
                    OFFER.replace('‘산은’은한국산업은행', '‘산은’은한국성장금융')]
        for text in variants:
            with self.subTest(text=text[-180:]):
                with self.assertRaises(ValueError): parse(text)
        with self.assertRaises(ValueError): parse(body=BODY.replace('한국산업은행 주관사업', '한국성장금융 주관사업'))

    def test_size_cutoff_conflicts_across_tables_and_post_are_rejected(self):
        for text, body in [(OFFER.replace('500~1,200', '500~1,300'), BODY),
                           (OFFER.replace('35.0%1,200초과', '35.0%1,300초과'), BODY),
                           (OFFER.replace('(1,200억원이하)', '(1,300억원이하)'), BODY),
                           (OFFER, BODY.replace('1,200', '1,300'))]:
            with self.subTest(body=body):
                with self.assertRaises(ValueError): parse(text, body)

    def test_vc_contamination_in_growth_or_missing_proposal_vc_does_not_promote_scope(self):
        for text in [OFFER.replace('기구\n※(공통사항)', '기구○벤처투자조합\n※(공통사항)'),
                     OFFER.replace('에의한벤처투자조합', '에의한기타조합')]:
            with self.subTest(text=text[700:1100]):
                with self.assertRaises(ValueError): parse(text)

    def test_domestic_gp_qualification_cannot_replace_current_domestic_investment(self):
        with self.assertRaises(ValueError):
            parse(OFFER.replace('○국내중소‧중견기업', '○해외중소‧중견기업'))

    def test_date_calendar_weekday_time_and_issue_order_conflicts_fail(self):
        for text in [OFFER.replace('2021년1월26일(화)', '2021년1월26일(월)'),
                     OFFER.replace('2021.1.26(화)', '2021.1.27(수)'),
                     OFFER.replace('16:00까지', '17:00까지'),
                     OFFER.replace('10:00~16:00', '17:00~16:00'),
                     OFFER.replace('2021년1월26일(화)', '2020년1월26일(일)'),
                     OFFER.replace('2021년1월26일(화)', '2021년2월30일(화)'),
                     OFFER.replace('2020년12월29일', '2021년1월1일')]:
            with self.subTest(text=text[-160:]):
                with self.assertRaises(ValueError): parse(text)

    def test_missing_reception_time_is_not_filled_from_another_event(self):
        text = OFFER.replace('16:00까지', '까지').replace('10:00~16:00', '')
        text += '\n출자설명회2021년1월6일(수)16:00'
        with self.assertRaises(ValueError): parse(text)

    def test_citizen_and_infra_attachments_are_not_enterprise_budget_rows(self):
        n = newdeal()
        for suffix, document in [('2', '국민참여'), ('3', '인프라')]:
            url = n['attachments'][0].replace('Notice1', 'Notice'+suffix)
            n['attachments'].append(url)
            n['attachment_hashes'][url] = 'c'*64
            n['attachment_texts'][url] = OFFER.replace('(기업투자)', '('+document+')')
        r = parse_newdeal_joint_notice(n)
        self.assertEqual(r['planned_commitment_total_krw'], 7450*10**8)
        self.assertEqual(len(r['other_retained_attachment_urls']), 2)
        with self.assertRaises(ValueError): parse(OFFER.replace('(기업투자)', '(국민참여)'))

    def test_duplicate_enterprise_attachments_or_tables_cannot_choose_first(self):
        n = newdeal()
        url = n['attachments'][0].replace('Notice1', 'Notice2')
        n['attachments'].append(url)
        n['attachment_hashes'][url] = 'c'*64
        n['attachment_texts'][url] = OFFER
        with self.assertRaises(ValueError): parse_newdeal_joint_notice(n)
        table = OFFER.split('지원분야정책출자자', 1)[1].split('주1)조성목표', 1)[0]
        with self.assertRaises(ValueError): parse(OFFER + '지원분야정책출자자' + table + '주1)')

    def test_wrong_fund_year_and_non_regular_or_amended_title_stay_unsupported(self):
        for title in [TITLE.replace('2021년', '2022년')]:
            with self.assertRaises(ValueError): parse_newdeal_joint_notice(newdeal(title=title))
        with self.assertRaises(ValueError): parse(OFFER.replace('정책형 뉴딜펀드', '다른 펀드'))
        for title in [TITLE.replace('정시', '수시'), TITLE + '(정정)', TITLE.replace('선정계획 공고', '선정계획 취소 공고'),
                      '【선정결과】 「정책형 뉴딜펀드」 2021년 정시 위탁운용사 선정 결과(정정)']:
            self.assertIsNone(parse_newdeal_joint_notice(newdeal(title=title)))

    def test_original_host_and_retained_attachment_provenance_are_required(self):
        for mutation in ['host', 'unobserved', 'hash', 'foreign_url']:
            with self.subTest(mutation=mutation):
                n = newdeal()
                if mutation == 'host': n['institution_id'] = 'kdb'
                elif mutation == 'unobserved': n['attachments'] = []
                elif mutation == 'hash': n['attachment_hashes'][n['attachments'][0]] = 'invalid'
                else: n['attachments'].append(n['attachments'][0].replace('www.kgrowth.or.kr', 'example.com'))
                with self.assertRaises(ValueError): parse_newdeal_joint_notice(n)

    def test_no_notice_id_branch_and_whitespace_or_integer_ratio_variants_work(self):
        n = newdeal(text=OFFER.replace('35.0%', '35%').replace('지원분야정책출자자', '지원분야 \n 정책출자자'), ident='999')
        r = parse_newdeal_joint_notice(n)
        self.assertEqual(r['source_id'], '999')
        self.assertEqual(r['planned_commitment_total_krw'], 7450*10**8)


if __name__ == '__main__':
    unittest.main()
