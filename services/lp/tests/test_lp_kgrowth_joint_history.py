"""Joint original 471: source host, program leads and contributors differ.

Retained excerpts of pages 1–3 and 12, PDF SHA256
dc1a8d583dd7b7ffe16019f3cba7087ebcf5c201ecf26cf231c78320fa36b384.
This reduced fixture is not the original PDF or publication approval evidence.
"""
import copy
import unittest

from services.lp.src.lp_kgrowth_history_terms import review_bundle
from services.lp.src.lp_kgrowth_joint_history import parse_materials_joint_notice, _cell_options
from services.lp.src.lp_notice_publication import _rule_valid_name
from services.lp.tests.test_lp_kgrowth_history_terms import notice, bundle


TITLE = '【선정공고】 「소재·부품·장비 분야 투자 전용 펀드(2차)」 위탁운용사 선정계획 공고'
BODY = '''※ 블라인드펀드 제출서류 및 관련 양식 : 한국산업은행 홈페이지 공지사항 참고
※ 프로젝트펀드 문의 : 한국성장금융투자운용 (02-2090-9139)'''
OFFER = '''소재·부품·장비분야 투자 전용 펀드(2차)위탁운용사 선정계획 공고
1. 개요 항목 블라인드펀드 프로젝트펀드 ❶ 일반 ❷ 반도체
출자계획 ◦ 분야별출자계획 (단위:억원)
지원분야 정책출자자 지정출자자 위탁운용금액 최소결성금액 출자 비율주) 정부재정 산업은행
블라인드 ➊일반 1,100 200 - 1,300 2,000 65%
➋반도체 300 100 400 800 1,000 80%
프로젝트 1,000 - - 1,000 2,000 50%
합계 2,400 300 400 3,100 5,000 -
주) 출자 비율 : 지원분야별 위탁운용금액(정책출자자 및 지정출자자) / 최소결성금액
선정운용사수 ◦ 2개사 ◦ 1개사 ◦ 위탁운용금액소진시까지수시접수및선정
최소결성금액 ◦ 펀드별1,000억원 ◦ 제안금액, 출자비율등을감안하여결정
운용사별배정금액 ◦650억원이내(최소결성금액의65%이내)
◦800억원이내(최소결성금액의80%이내) ◦펀드별최대300억원이내(최소결성금액의50%이내)
주관기관 ◦ 한국산업은행 ◦ 한국성장금융투자운용㈜
접수일시 2021년4월21일(수)16:00까지 ◦ 수시접수
2. 블라인드펀드 출자대상투자기구
❶ 일반 ◦「자본시장과금융투자업에관한법률」에의한경영참여형사모집합투자기구,
창업‧벤처전문경영참여형사모집합투자기구등
◦「여신전문금융업법」에의한신기술사업투자조합
◦「벤처투자촉진에관한법률」에의한벤처투자조합
❷ 반도체 ◦「자본시장과금융투자업에관한법률」에의한경영참여형사모집합투자기구,
창업‧벤처전문경영참여형사모집합투자기구등
※(공통사항) 투자기구 변경 요청 가능
운용사신청자격 ◦국내에설립된법인
주목적투자대상및의무투자비율
❶ 일반, ❷ 반도체공통 ◦소재·부품·장비산업관련기업에결성금액의60%이상투자
▪소재·부품·장비관련해외기업인수,지분투자(국내기업해외진출등연계)등
❷ 반도체한정 ◦반도체소재·부품·장비관련국내중소·중견기업에500억원이상투자
◦소재·부품·장비산업관련국내기업의해외진출*지원에100억원이상투자
※ 상기 항목(소재·부품·장비, 반도체, 해외진출)에 각각 해당될 경우 중복 인정
운용사출자금액 ◦약정총액의1%이상
3. 프로젝트펀드 ◦수시접수
4. 접수처및문의방법
구분 블라인드펀드(➊일반,➋반도체) 프로젝트펀드
주관기관 한국산업은행간접투자금융실 한국성장금융투자운용본부
2021년3월31일 한국산업은행 한국성장금융투자운용㈜'''


def materials(text=OFFER, body=BODY):
    return notice('471', TITLE, '2021-04-01', body, text)


class JointOriginalReviewTests(unittest.TestCase):
    def test_source_host_and_two_blind_leads_remain_distinct(self):
        n = materials()
        before = copy.deepcopy(n)
        p = parse_materials_joint_notice(n)
        self.assertEqual(n, before)
        self.assertEqual(p['source_host_institution_id'], 'kgrowth')
        self.assertEqual([t['program_lead_institution_id'] for t in p['tracks']], ['kdb', 'kdb', 'kgrowth'])
        self.assertEqual(p['joint_issuer_institution_ids'], ['kdb', 'kgrowth'])
        self.assertEqual(p['source_url'], n['url'])
        self.assertEqual((p['issued_date'], p['posted_date']), ('2021-03-31', '2021-04-01'))
        self.assertFalse(p['publication_ready'])

    def test_joint_amount_is_not_the_lead_institution_contribution(self):
        p = parse_materials_joint_notice(materials())
        general, semiconductor, project = p['tracks']
        self.assertEqual(p['planned_commitment_total_krw'], 3100 * 10**8)
        self.assertEqual([t['planned_commitment_total_krw'] for t in p['tracks']], [1300*10**8, 800*10**8, 1000*10**8])
        self.assertEqual(semiconductor['planned_contributions_krw'], {'정부재정': 300*10**8, '한국산업은행': 100*10**8, '지정출자자': 400*10**8})
        self.assertEqual(general['planned_contributions_krw']['한국산업은행'], 200*10**8)
        self.assertEqual(project['planned_contributions_krw']['한국산업은행'], 0)
        self.assertEqual(semiconductor['planned_formation_total_krw'], 1000*10**8)
        self.assertEqual(general['planned_per_fund_commitment_max_krw'], 650*10**8)
        self.assertEqual(general['planned_fund_count'], 2)
        self.assertTrue(all(t['selected_managers'] == [] for t in p['tracks']))

    def test_strategy_amounts_and_overlapping_obligations_are_not_lp_commitments(self):
        general, semiconductor, project = parse_materials_joint_notice(materials())['tracks']
        self.assertEqual(semiconductor['strategy']['domestic_sme_semiconductor_min_krw'], 500*10**8)
        self.assertEqual(semiconductor['strategy']['domestic_company_overseas_expansion_min_krw'], 100*10**8)
        self.assertTrue(semiconductor['strategy']['obligations_may_overlap'])
        self.assertNotIn('domestic_sme_semiconductor_min_krw', general['strategy'])
        self.assertFalse(general['independent_pe_scope_verified'])
        self.assertFalse(semiconductor['independent_pe_scope_verified'])
        self.assertEqual(general['deadline'], '2021-04-21T16:00:00+09:00')
        self.assertEqual(project['deadline'], '')
        self.assertEqual(project['fund_kind'], 'project')

    def test_quotes_and_source_hashes_stay_replayable(self):
        n = materials()
        p = parse_materials_joint_notice(n)
        url = n['attachments'][0]
        for e in p['evidence'].values():
            self.assertIn(e['quote'], OFFER)
            self.assertEqual(e['attachment_sha256'], n['attachment_hashes'][url])
            self.assertEqual(e['sha256'], n['sha256'])
        self.assertFalse(p['detail_raw_replayed'])
        self.assertFalse(p['attachment_bytes_replayed'])
        self.assertEqual(p['terms_status'], 'original_recruitment_plan')

    def test_merged_overview_alone_cannot_assign_leads(self):
        text = OFFER.replace('구분 블라인드펀드(➊일반,➋반도체) 프로젝트펀드\n주관기관 한국산업은행간접투자금융실 한국성장금융투자운용본부', '')
        with self.assertRaisesRegex(ValueError, '접수처'):
            parse_materials_joint_notice(materials(text))

    def test_missing_or_reversed_merged_columns_are_rejected(self):
        columns = '항목 블라인드펀드 프로젝트펀드 ❶ 일반 ❷ 반도체'
        for changed in ('항목', '항목 프로젝트펀드 블라인드펀드 ❶ 일반 ❷ 반도체'):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, '열 머리말'):
                parse_materials_joint_notice(materials(OFFER.replace(columns, changed)))

    def test_conflicting_institution_proofs_fail_closed(self):
        for text, body in (
            (OFFER.replace('주관기관 ◦ 한국산업은행 ◦ 한국성장금융투자운용㈜', '주관기관 ◦ 한국성장금융투자운용㈜ ◦ 한국산업은행'), BODY),
            (OFFER, BODY.replace('프로젝트펀드 문의 : 한국성장금융투자운용', '프로젝트펀드 문의 : 한국산업은행')),
            (OFFER.replace('2021년3월31일 한국산업은행 한국성장금융투자운용㈜', '2021년3월31일 한국성장금융투자운용㈜'), BODY)):
            with self.subTest(text=text[-100:], body=body), self.assertRaises(ValueError):
                parse_materials_joint_notice(materials(text, body))

    def test_changed_source_institution_is_not_accepted(self):
        n = materials()
        n['institution_id'] = 'kdb'
        with self.assertRaisesRegex(ValueError, '게시기관'):
            parse_materials_joint_notice(n)

    def test_budget_components_totals_and_ratios_must_reconcile(self):
        for old, new in [('300 100 400 800', '300 100 500 800'),
                         ('3,100 5,000', '3,200 5,000'),
                         ('2,000 65%', '2,000 60%'),
                         ('2,400 300 400', '2,300 400 400')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                parse_materials_joint_notice(materials(OFFER.replace(old, new)))

    def test_allocation_caps_and_planned_counts_must_reconcile(self):
        for old, new in [('650억원', '600억원'), ('◦ 2개사', '◦ 3개사'),
                         ('펀드별1,000억원', '펀드별900억원')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                parse_materials_joint_notice(materials(OFFER.replace(old, new)))

    def test_multiple_budget_tables_never_pick_the_first(self):
        start = OFFER.index('지원분야 정책출자자')
        end = OFFER.index('주) 출자 비율') + 2
        repeated = OFFER.replace('4. 접수처및문의방법', OFFER[start:end] + '\n4. 접수처및문의방법')
        with self.assertRaisesRegex(ValueError, '단일'):
            parse_materials_joint_notice(materials(repeated))

    def test_dates_are_not_interchangeable_or_guessed(self):
        for old, new in [('3월31일', '4월2일'), ('2021년3월31일', '2020년3월31일'),
                         ('21일(수)', '21일(목)'), ('16:00까지', '오후까지')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                parse_materials_joint_notice(materials(OFFER.replace(old, new)))

    def test_distinct_round_and_missing_or_duplicate_original_are_held(self):
        with self.assertRaisesRegex(ValueError, '회차'):
            parse_materials_joint_notice(materials(OFFER.replace('펀드(2차)', '펀드(3차)')))
        n = materials()
        with self.assertRaises(ValueError):
            parse_materials_joint_notice(materials('관련 서식만 있음'))
        second = n['attachments'][0].replace('Notice1', 'Notice2')
        n['attachments'].append(second)
        n['attachment_texts'][second] = OFFER
        n['attachment_hashes'][second] = 'c' * 64
        with self.assertRaisesRegex(ValueError, '여러 개'):
            parse_materials_joint_notice(n)

    def test_current_legal_forms_and_overlap_rule_are_required(self):
        for old, new in [('창업‧벤처전문경영참여형사모집합투자기구등', ''),
                         ('각각 해당될 경우 중복 인정', '중복 불가')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                parse_materials_joint_notice(materials(OFFER.replace(old, new)))

    def test_joint_review_never_increases_kgrowth_pe_or_roster_counts(self):
        p = review_bundle(bundle(materials()), valid_name=_rule_valid_name)
        self.assertEqual(p['metadata_check']['errors'], [])
        self.assertEqual(p['summary']['parsed_joint_offerings'], 1)
        self.assertEqual(p['summary']['parsed_pe_offerings'], 0)
        self.assertEqual(p['summary']['parsed_pe_roster_tracks'], 0)
        self.assertEqual(p['joint_holds'], [])
        self.assertIsNone(p['groups'][0]['offering'])
        bad = review_bundle(bundle(materials(OFFER.replace('3,100 5,000', '3,200 5,000'))), valid_name=_rule_valid_name)
        self.assertEqual(bad['joint_offerings'], [])
        self.assertTrue(bad['joint_holds'])

    def test_unsupported_title_and_unbounded_numeric_cells_do_not_slip_through(self):
        n = materials()
        n['title'] = '사업 소개자료'
        self.assertIsNone(parse_materials_joint_notice(n))
        with self.assertRaisesRegex(ValueError, '상한'):
            _cell_options('9' * 90, 6)


if __name__ == '__main__':
    unittest.main()
