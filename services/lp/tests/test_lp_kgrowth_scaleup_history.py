"""Source excerpts from the retained 2020 joint policy-investor offering.

Notice IDs are fixture provenance, never collector inputs. Attachment SHA:
0c0f34eb56ff7d14d823ab9bff17266d97cd156974cdc971588fc129f138cb21.
"""
import unittest

from services.lp.src.lp_kgrowth_scaleup_history import parse_scaleup_notice
from services.lp.src.lp_kgrowth_history_terms import _identity, review_bundle
from services.lp.src.lp_notice_publication import _rule_valid_name
from services.lp.tests.test_lp_kgrowth_history_terms import notice, bundle, secondary, SECONDARY_OFFER, SECONDARY_RESULT

OFFER = '''2020년 제1차 성장지원펀드 위탁운용사 선정계획 공고
2020년제1차성장지원펀드위탁운용사선정계획을아래와같이공고합니다.
1.선정개요 정책출자자및위탁운용금액○정책출자자위탁운용금액:총8,800억원이내
선정운용사수및배정금액○리그별출자계획(단위:개,억원)
리그정책출자자출자총액선정운용사수정책출자자출자비율펀드별제안규모조성규모
중견2,7002~330%3,000~5,0009,000스케일업성장대형VC1,600240%2,0004,000
일반2,2003~537%이내1,200~2,5006,000스케일업혁신1,820638%이내8004,800
루키480440%3001,200합계8,80017~2025,000
*중견리그는500억원단위,스케일업성장(일반)리그는100억원단위로제안요망
○리그별주관기관:한국산업은행(중견‧스케일업성장‧루키),한국성장금융(스케일업혁신)
출자대상투자기구○‘자본시장과금융투자업에관한법률’에의한경영참여형사모집합투자기구,
창업‧벤처전문경영참여형사모집합투자기구등○‘여신전문금융업법’에의한신기술사업투자조합
○‘중소기업창업지원법’에의한중소기업창업투자조합○‘벤처기업육성에관한특별조치법’에의한한국벤처투자조합등
운용사선정방법○홈페이지공개모집공고등을통해리그별주관기관이정한절차에따라선정
접수일시2020년3월3일(화)(10:00~16:00限)
운용사신청자격○관련법규에따른펀드결성과업무집행이가능하도록국내에설립된법인
루키리그신청자격②블라인드펀드운용규모가약정총액기준500억원미만
2.출자분야□주목적투자분야설정:운용사자율제안
○국내중소‧중견기업*에리그별최소결성금액의50%이상투자
3.주요출자조건항목세부내용운용사출자금액○약정총액의1%이상'''
TITLE = '【선정공고】 2020년 제1차 성장지원펀드 위탁운용사 선정계획 공고'


def fixture(offered=OFFER):
    return notice('329', TITLE, '2020-02-07', '첨부 자료와 같이 선정계획을 공고합니다.', offered)


def read(offered=OFFER):
    return parse_scaleup_notice(fixture(offered))['funds'][0]


class GrowthSupportHistoryTests(unittest.TestCase):
    def test_owned_league_is_policy_sum_not_8800_or_kgrowth_alone(self):
        p = read()
        self.assertEqual(p['identity'], {'fund': '성장지원펀드(스케일업혁신리그)', 'year': '2020', 'round': '1차'})
        held = p['held_terms']
        self.assertEqual(held['shared_planned_amount_krw'], 182_000_000_000)
        self.assertEqual(held['policy_investor_total_krw'], 880_000_000_000)
        self.assertEqual(len(held['excluded_other_leagues']), 4)
        self.assertEqual(sum(r['amount_krw'] for r in held['excluded_other_leagues']), 698_000_000_000)
        self.assertIn('단독 출자 아님', held['amount_basis'])
        self.assertEqual((held['shared_tracks'][0]['planned_fund_count_min'],
                          held['shared_tracks'][0]['planned_fund_count_max']), (6, 6))
        self.assertFalse(held['pe_scope_verified'])
        self.assertFalse(held['blind_track_observed'])  # old GP fund size is not current scope

    def test_budget_count_and_formation_must_all_reconcile(self):
        for old, new in [('총8,800억원', '총8,801억원'), ('1,820638%', '1,821638%'),
                         ('합계8,80017~2025,000', '합계8,80017~2125,000'),
                         ('8004,800', '8004,801')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                read(OFFER.replace(old, new))

    def test_other_lead_or_missing_mixed_legal_forms_is_held(self):
        for old, new in [('한국성장금융(스케일업혁신)', '한국성장금융(루키)'),
                         ('한국벤처투자조합', '다른기구')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                read(OFFER.replace(old, new))

    def test_actual_domestic_investment_is_distinct_from_gp_eligibility(self):
        self.assertTrue(read()['held_terms']['domestic_investment_verified'])
        changed = OFFER.replace('국내중소‧중견기업*에', '중소‧중견기업*에')
        self.assertFalse(read(changed)['held_terms']['domestic_investment_verified'])

    def test_calendar_and_reception_end_time_are_checked(self):
        self.assertEqual(read()['held_terms']['deadline'], '2020-03-03T16:00:00+09:00')
        for old, new in [('3월3일(화)', '3월3일(수)'), ('10:00~16:00', '16:00~10:00')]:
            self.assertEqual(read(OFFER.replace(old, new))['held_terms']['deadline'], '')

    def test_wrong_year_round_or_multiple_originals_do_not_join(self):
        for offered in [OFFER.replace('2020년', '2021년'), OFFER.replace('제1차', '제2차')]:
            with self.assertRaises(ValueError):
                read(offered)
        n = fixture()
        url = next(iter(n['attachment_texts']))
        second = url.replace('Notice1', 'Notice2')
        n['attachment_texts'][second] = OFFER
        n['attachment_hashes'][second] = 'c' * 64
        n['attachments'].append(second)
        with self.assertRaises(ValueError):
            parse_scaleup_notice(n)

    def test_source_quote_and_attachment_fingerprint_preserved(self):
        p = read()['held_terms']
        for field in ['evidence', 'lead_evidence', 'legal_scope_evidence', 'strategy_evidence', 'deadline_evidence']:
            self.assertIn(p[field]['quote'], OFFER)
            self.assertEqual(p[field]['attachment_sha256'], 'b' * 64)

    def test_prefix_inline_and_suffix_rounds_have_one_key_without_roman_merge(self):
        base = {'date': '2020-02-07'}
        keys = [_identity({**base, 'title': title}) for title in [
            '2020년 제1차 「성장지원펀드」 위탁운용사 선정 결과',
            '2020년 제 1 차 「성장지원펀드」 위탁운용사 선정 결과',
            '2020년 「성장지원펀드(1차)」 위탁운용사 선정 결과',
            '2020년 「성장지원펀드1차」 위탁운용사 선정 결과',
            '2020년 「성장지원펀드」 위탁운용사 선정계획 공고(제1차)']]
        self.assertEqual(keys, [keys[0]] * 5)
        roman = _identity({**base, 'title': '「기업구조혁신펀드(III)」 위탁운용사 선정 결과'})
        self.assertEqual(roman['fund'], '기업구조혁신펀드(III)')
        with self.assertRaises(ValueError):
            _identity({**base, 'title': '제2차 「성장지원펀드(1차)」 위탁운용사 선정 결과'})

    def test_different_postposed_rounds_do_not_collapse_to_empty_round(self):
        for suffix in ('제{}차', '제 {} 차'):
            values = [_identity({'date': '2021-01-01', 'title':
                       '「은행권일자리펀드」 위탁운용사 선정계획 공고(' + suffix.format(n) + ')'}) for n in (3, 4)]
            self.assertEqual([v['round'] for v in values], ['3차', '4차'])

    def test_offering_and_screening_and_result_share_sourced_identity_but_no_pe_roster(self):
        final = notice('354', '【선정결과】 2020년 제1차 『성장지원펀드(스케일업 혁신리그)』 위탁운용사 선정 결과',
                       '2020-04-28', '성장지원펀드 선정 결과를 공지합니다.\n운용사명\n네오플럭스')
        screening = notice('352', '【선정결과】 2020년 제1차 「성장지원펀드(스케일업 혁신리그)」 1차 심사 결과',
                           '2020-04-08', '1차 심사 통과 펀드수 : 11개')
        def no_pe_name(_):
            self.fail('혼합 정책출자 계획의 명단을 PE 명단으로 읽으면 안 됨')
        r = review_bundle(bundle(fixture(), screening, final), valid_name=no_pe_name)
        self.assertEqual(len(r['groups']), 1)
        self.assertEqual(len(r['groups'][0]['notices']), 3)
        self.assertIsNone(r['groups'][0]['offering'])
        self.assertFalse(r['groups'][0]['rosters'])
        self.assertEqual(r['summary']['parsed_mixed_offerings'], 1)
        self.assertFalse(r['publication_ready'])

    def test_source_ids_do_not_select_the_supported_layout(self):
        another_id = notice('999', TITLE, '2020-02-07', '첨부 선정계획을 공고합니다.', OFFER)
        r = review_bundle(bundle(another_id), valid_name=_rule_valid_name)
        self.assertEqual(r['summary']['parsed_mixed_offerings'], 1)
        self.assertEqual(r['groups'][0]['held_offering']['shared_planned_amount_krw'], 182_000_000_000)

    def test_other_year_or_round_results_do_not_attach_to_this_league(self):
        for prefix in ('2020년 제2차', '2021년 제1차'):
            final = notice('354', f'【선정결과】 {prefix} 「성장지원펀드(스케일업 혁신리그)」 위탁운용사 선정 결과',
                           '2021-04-28', '선정 결과를 공지합니다.\n운용사명\n네오플럭스')
            r = review_bundle(bundle(fixture(), final), valid_name=_rule_valid_name)
            self.assertEqual(len(r['groups']), 2)
            held = next(g for g in r['groups'] if g['held_offering'])
            self.assertEqual(len(held['notices']), 1)

    def test_numeric_round_normalization_still_checks_attachment_and_closure_round(self):
        b = secondary(SECONDARY_OFFER.replace('(4차)', '(3차)'))
        r = review_bundle(b, valid_name=_rule_valid_name)
        self.assertIsNone(r['groups'][0]['held_offering'])
        self.assertTrue(any('회차' in h['reason'] for h in r['groups'][0]['holds']))
        b = secondary(result=SECONDARY_RESULT.replace('(4차)', '(3차)'))
        r = review_bundle(b, valid_name=_rule_valid_name)
        self.assertNotIn('closure_event', r['groups'][0]['held_offering'])
        self.assertTrue(any('펀드명' in h['reason'] for h in r['groups'][0]['holds']))


if __name__ == '__main__':
    unittest.main()
