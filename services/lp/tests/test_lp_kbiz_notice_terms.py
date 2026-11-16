import copy
import unittest
from services.lp.src import lp_kbiz_notice_terms as terms
from services.lp.src import collect_lp_institution_boards as boards
from services.lp.src.lp_notice_publication import publish_basic_notices
from services.lp.tests.test_lp_board_adapter_kbiz import HTML,DETAIL

TITLE='2026년도 중소기업중앙회 국내 블라인드 펀드 선정 공고'
BODY=('선정 개요 운용방식 블라인드 형태의 PE·VC 펀드 투자기구 [PE] 자본시장법에 의한 기관전용 사모집합투자기구 '
      '* 경영참여 목적 투자를 포함하여 운용 [VC] 벤처투자조합 '
      '선정 운용사 수 및 배정금액 10개사 내외, 100~800억원 범위 내 출자규모 총 3,000억원 이내 '
      '신청 자격 각 운용사는 매년 1개 부문의 출자사업에만 지원 가능 (PE/VC 공통) '
      '진행 일정 정량평가 및 현장실사 2026.8~9월 기술능력평가(정성, PT) 2026.9월 '
      '내부 승인절차 및 결과통보 2026.9월 제출기한: 2026.7.31(금) 15:00 '
      '메일 제목 예시: [26년/PE 또는 VC 택1] 펀드명')
STAMP='2026-10-26T00:00:00+00:00'

# Offering-body excerpts from the retained 2020–2023 notices. GP eligibility,
# VC budgets and historic fund sizes deliberately remain present as decoys.
HISTORICAL = {
    2020: ('2020-07-30', '2020-08-13', '목', 2000,
           [('일반(기거래운용사)', 1400, 4), ('신규', 600, 2)]),
    2021: ('2021-07-01', '2021-07-21', '수', 2600,
           [('일반', 2400, 8), ('루키', 200, 2)]),
    2022: ('2022-08-09', '2022-08-26', '금', 2600,
           [('일반', 2400, 6), ('루키', 200, 2)]),
    2023: ('2023-07-27', '2023-08-17', '목', 2600,
           [('대형', 1300, 2), ('중형', 900, 2), ('소형', 400, 2)]),
}


def historical_notice(year):
    posted, end, weekday, amount, rows = HISTORICAL[year]
    mixed = year in (2020, 2021)
    asset = 'PE∙VC' if mixed else 'PE'
    title = f'{year}년 중소기업중앙회(노란우산) 국내 블라인드 {asset}펀드 모집 공고'
    if year == 2020:
        title = '[PE∙VC펀드 공고] 중소기업중앙회(노란우산공제) 국내 PE∙VC펀드 모집 공고'
    legal = ('경영참여형 사모집합투자기구' if mixed else
             '기관전용 사모집합투자기구 * 경영참여 목적 투자를 포함하여 운용')
    pe_heading = '[PE 펀드] - ' if year != 2023 else ''
    vc_legal = ('∙ [VC 펀드] - 벤처투자조합 - 신기술사업투자조합 '
                '- 창업‧벤처전문 경영참여형 사모집합투자기구 등 ' if mixed else '')
    vc_amount = ('∙ [VC 펀드] : 총 1,200억원 이내 - 일반 : 총 1,100억원 이내 (8개사 이내) '
                 '- 루키 : 총 100억원 이내 (2개사 이내) ' if mixed else '')
    league_rows = ' '.join(f'- {name} : 총 {value:,}억원 이내 ({count}개사 이내)' for name, value, count in rows)
    choice = '제안 운용사는 1개 분야에만 자율적으로 지원 가능' if year != 2022 else ''
    y, mo, day = map(int, end.split('-'))
    body = (f'{year}년 중소기업중앙회(노란우산) 국내 블라인드 {asset}펀드 선정 계획을 아래와 같이 공고합니다. '
            f'1. 선정 주요 기준 구분 내용 운용방식 ∙ 블라인드 형태의 {asset}펀드 '
            '운용사 소재지 ∙ 국내 (해외 GP의 경우 제안서 접수일 이전에 국내 법인이 존재하는 경우) '
            f'투자기구 ∙ {pe_heading}자본시장법에 의한 {legal} {vc_legal}'
            f'출자금액 ∙ [PE 펀드] : 총 {amount:,}억원 이내 {league_rows} {vc_amount}'
            '신청 자격 ∙ [공통] 국내 전문투자자로부터 투자가 확약된 경우 '
            '루키 운용사 기존 블라인드 펀드 운용규모 500억원 이하 '
            '펀드별 배정금액 ∙ 최대출자자 출자금액 이하로 운용사에서 자율적으로 제안 '
            f'기타 ∙ {choice} 2. 선정 절차 및 일정 '
            f'선정 일정 \'{str(y)[2:]}. {mo}. {day}({weekday}) 제안서 접수 마감 오후 5시까지 접수분에 한함 '
            f'3. 제출 서류 및 기한 ㅇ 제출 서류 - 국내 블라인드 펀드 제안서 '
            f'ㅇ 기한 : {y}년 {mo}월 {day}일({weekday}) 오후 5시 (우편의 경우 본회 도착일 기준) '
            '4. 문의 및 접수처')
    return {'institution_id': 'kbiz', 'title': title, 'body': body, 'date': posted,
            'url': 'https://www.kbiz.or.kr/ko/contents/bbs/view.do?seq=123&topFixYn=N&mnSeq=211',
            'sha256': 'a' * 64, 'attachments': [], 'attachment_texts': {}, 'attachment_hashes': {}}


def collection():
    config={**boards.load_configs()['kbiz'],'searches':['블라인드'],'pages':1}
    listing=HTML.replace('국내 PE 펀드 모집',TITLE).replace('value="PE"','value="블라인드"').replace('schTxt=PE','schTxt=블라인드')
    detail=DETAIL.replace('[사업공고] 국내 펀드 모집','[사업공고] '+TITLE)
    start=detail.index('<div class="detail-body">');end=detail.index('<div class="navigation">')
    detail=detail[:start]+'<div class="detail-body">'+BODY+'</div>'+detail[end:]
    detail=detail.replace('선정계획.hwp','제안서 양식.hwp')
    return boards.collect({'kbiz':config},lambda c:lambda url,referer=None:(detail if 'view.do?' in url else listing).encode(),STAMP)


class KbizTrackTests(unittest.TestCase):
    def test_independent_track_publishes_without_shared_allocations(self):
        report=collection();self.assertFalse(report['holds'])
        n=report['notices'][0];result=terms.terms(n)
        self.assertEqual(result['deadline'],'2026-07-31T15:00:00+09:00')
        self.assertEqual(len(result['schedule_stages']),3)
        self.assertEqual(result['schedule_stages'][0]['end_date'],'2026-09')
        for field in ('commitment_amount_krw','manager_count','segments','per_fund_amount_krw'):
            self.assertNotIn(field,result)
        # Use configured fixture pages for replay, preserving production checks.
        from unittest.mock import patch
        config={**boards.load_configs()['kbiz'],'searches':['블라인드'],'pages':1}
        with patch.object(boards,'load_configs',return_value={'kbiz':config}):
            programs,holds=publish_basic_notices({'programs':[],'institution_notices':report['notices']},[],STAMP)
        self.assertFalse(holds);self.assertEqual(len(programs),1)
        self.assertEqual(programs[0]['asset_scope'],'PE');self.assertFalse(programs[0]['selected_gps'])
        self.assertNotIn('commitment_amount_krw',programs[0]);self.assertNotIn('manager_count',programs[0])
        # The joint PE·VC budget is shown as a labelled figure, never as this track's number.
        self.assertEqual(programs[0]['commitment_label'],'총 3,000억원 이내 (PE·VC 합계)')

    def test_current_pe_and_separate_application_are_both_required(self):
        n={'institution_id':'kbiz','title':TITLE,'body':BODY,'url':'https://www.kbiz.or.kr/example','date':'2026-07-10','sha256':'a'*64}
        self.assertTrue(terms.pe_track(n))
        for body in [BODY.replace('투자기구 [PE]','과거 펀드 [PE]'), BODY.replace('PE 또는 VC 택1','담당자 문의'),
                     BODY.replace('각 운용사는 매년 1개 부문의 출자사업에만 지원 가능 (PE/VC 공통)','운용사 공동 지원')]:
            self.assertFalse(terms.pe_track(dict(n,body=body)))
        self.assertFalse(terms.pe_track(dict(n,title=TITLE+' 외부 평가기관 선정')))

    def test_old_joint_notice_uses_current_body_blind_scope_and_separate_pe_legal_row(self):
        n = historical_notice(2020)
        self.assertNotIn('블라인드', n['title'])
        self.assertTrue(terms.pe_track(n))
        result = terms.terms(n)
        self.assertEqual((result['commitment_amount_krw'], result['manager_count']), (200_000_000_000, 6))
        self.assertEqual(result['commitment_label'], '2,000억원 이내')
        self.assertEqual([s['name'] for s in result['segments']], ['일반(기거래운용사)', '신규'])

    def test_historical_pe_budgets_counts_and_1700_deadlines(self):
        for year, (_, day, _, amount, rows) in HISTORICAL.items():
            with self.subTest(year=year):
                n = historical_notice(year)
                before = copy.deepcopy(n)
                r = terms.terms(n)
                self.assertEqual(r['amount_scope'], 'pe_only')
                self.assertEqual(r['commitment_amount_krw'], amount * 100_000_000)
                self.assertEqual(r['manager_count'], sum(row[2] for row in rows))
                self.assertEqual(r['deadline'], day + 'T17:00:00+09:00')
                self.assertEqual(r['deadline_precision'], 'datetime')
                self.assertEqual(r['manager_count_label'], f'{sum(row[2] for row in rows)}개사 이내')
                self.assertNotIn('per_fund_amount_krw', r)
                if year in (2020, 2021):
                    self.assertNotIn('total_commitment_amount_krw', r)
                else:
                    self.assertEqual(r['total_commitment_amount_krw'], r['commitment_amount_krw'])
                self.assertTrue(all('per_fund_amount_krw' not in s for s in r['segments']))
                for proofs in r['extraction_evidence'].values():
                    for proof in proofs:
                        self.assertIn(proof['quote'], n['body'])
                        self.assertEqual(proof['sha256'], n['sha256'])
                self.assertEqual(n, before)

    def test_pe_only_offering_does_not_require_a_choice_between_pe_and_vc(self):
        n = historical_notice(2022)
        self.assertNotIn('1개 분야에만', n['body'])
        self.assertNotIn('VC', n['body'])
        self.assertTrue(terms.pe_track(n))
        self.assertEqual(terms.terms(n)['manager_count'], 8)

    def test_old_joint_notice_needs_separate_legal_row_and_application_field(self):
        n = historical_notice(2021)
        for changed in (
                n['body'].replace('[PE 펀드] - 자본시장법에 의한 경영참여형 사모집합투자기구',
                                  '[PE 펀드] - 벤처투자조합'),
                n['body'].replace('제안 운용사는 1개 분야에만 자율적으로 지원 가능', '운용사 공동 지원'),
                n['body'].replace('투자기구 ∙ [PE 펀드]', '과거운용실적 ∙ [PE 펀드]')):
            with self.subTest(body=changed[:150]):
                self.assertFalse(terms.pe_track(dict(n, body=changed)))

    def test_gp_location_or_past_blind_funds_cannot_supply_current_offering_scope(self):
        n = historical_notice(2021)
        for changed in (n['body'].replace('국내 블라인드 PE∙VC펀드 선정 계획', 'PE∙VC펀드 선정 계획'),
                        n['body'].replace('운용방식 ∙ 블라인드 형태', '과거운용실적 ∙ 블라인드 형태')):
            self.assertFalse(terms.pe_track(dict(n, body=changed)))

    def test_pe_budget_and_count_are_independent_of_vc_and_old_gp_size(self):
        n = historical_notice(2021)
        changed = n['body'].replace('총 1,200억원', '총 9,900억원').replace('운용규모 500억원', '운용규모 50,000억원')
        r = terms.terms(dict(n, body=changed))
        self.assertEqual((r['commitment_amount_krw'], r['manager_count']), (260_000_000_000, 10))
        self.assertNotIn('per_fund_amount_krw', r)
        self.assertTrue(all('VC' not in e['quote'] and '9,900' not in e['quote']
                            for e in r['extraction_evidence']['pe_allocation']))

    def test_bad_old_joint_budget_retains_shared_budget_guard(self):
        n = historical_notice(2021)
        for changed in (n['body'].replace('총 2,400억원', '총 2,300억원'),
                        n['body'].replace('총 2,600억원', '총 2,60억원'),
                        n['body'].replace('- 일반 : 총 2,400억원 이내 (8개사 이내)',
                                          '- 일반 : 총 2,400억원 이내 (0개사 이내)')):
            with self.subTest(body=changed[:150]):
                r = terms.terms(dict(n, body=changed))
                self.assertEqual(r['amount_scope'], 'pe_track_without_allocation')
                self.assertIn('allocation_error', r)
                for field in ('commitment_amount_krw', 'manager_count', 'segments', 'per_fund_amount_krw'):
                    self.assertNotIn(field, r)

    def test_no_pe_labelled_budget_never_becomes_a_joint_pe_only_number(self):
        n = historical_notice(2021)
        start = n['body'].index('출자금액')
        end = n['body'].index('신청 자격')
        changed = n['body'][:start] + '출자금액 총 3,800억원 이내 ' + n['body'][end:]
        r = terms.terms(dict(n, body=changed))
        self.assertEqual(r['amount_scope'], 'pe_track_without_allocation')
        self.assertNotIn('commitment_amount_krw', r)
        self.assertNotIn('manager_count', r)

    def test_historical_deadline_conflict_keeps_verified_budget_but_no_date(self):
        n = historical_notice(2021)
        changed = n['body'].replace("'21. 7. 21(수)", "'21. 7. 22(목)")
        r = terms.terms(dict(n, body=changed))
        self.assertEqual(r['commitment_amount_krw'], 260_000_000_000)
        self.assertNotIn('deadline', r)
        self.assertIn('deadline_error', r)

    def test_invalid_or_past_historical_deadline_is_not_repaired_by_inference(self):
        n = historical_notice(2023)
        for changed in (n['body'].replace('17일(목)', '17일(수)'),
                        n['body'].replace('오후 5시', '오후 15시')):
            r = terms.terms(dict(n, body=changed))
            self.assertNotIn('deadline', r)
            self.assertIn('deadline_error', r)
        r = terms.terms(dict(n, date='2023-08-20'))
        self.assertNotIn('deadline', r)
        self.assertIn('deadline_error', r)

    def test_historical_offering_body_cannot_be_reused_for_another_year_or_stage(self):
        n = historical_notice(2023)
        for title in (n['title'].replace('2023년', '2022년'), n['title'] + ' 선정 결과',
                      n['title'] + ' 외부 평가기관 선정'):
            self.assertFalse(terms.pe_track(dict(n, title=title)))
        self.assertFalse(terms.pe_track(dict(n, body=n['body'].replace('중소기업중앙회', '다른기관'))))

    def test_source_receipt_path_forms_old_joint_pe_program_without_joint_budget(self):
        from unittest.mock import patch
        for joint_only_budget in (False, True):
            with self.subTest(joint_only_budget=joint_only_budget):
                n = historical_notice(2020)
                if joint_only_budget:
                    start, end = n['body'].index('출자금액'), n['body'].index('신청 자격')
                    n['body'] = n['body'][:start] + '출자금액 총 3,200억원 이내 ' + n['body'][end:]
                config = {**boards.load_configs()['kbiz'], 'searches': ['PE'], 'pages': 1}
                listing = HTML.replace('국내 PE 펀드 모집', n['title']).replace('2026.07.10', n['date'].replace('-', '.'))
                detail = DETAIL.replace('[사업공고] 국내 펀드 모집', n['title']).replace('2026.07.10', n['date'].replace('-', '.'))
                start, end = detail.index('<div class="detail-body">'), detail.index('<div class="navigation">')
                detail = detail[:start] + '<div class="detail-body">' + n['body'] + '</div>' + detail[end:]
                detail = detail.replace('선정계획.hwp', '제안서 양식.hwp')
                checked = '2020-12-31T00:00:00+00:00'
                report = boards.collect({'kbiz': config}, lambda c: lambda url, referer=None:
                                        (detail if 'view.do?' in url else listing).encode(), checked)
                self.assertEqual(report['holds'], [])
                with patch.object(boards, 'load_configs', return_value={'kbiz': config}):
                    programs, holds = publish_basic_notices({'programs': [], 'institution_notices': report['notices']}, [], checked)
                self.assertEqual(holds, [])
                self.assertEqual(len(programs), 1)
                if joint_only_budget:
                    self.assertNotIn('commitment_amount_krw', programs[0])
                    self.assertNotIn('manager_count', programs[0])
                    self.assertIn('PE·VC 합계', programs[0]['commitment_label'])
                else:
                    self.assertEqual(programs[0]['commitment_amount_krw'], 200_000_000_000)
                    self.assertEqual(programs[0]['manager_count'], 6)
                self.assertEqual(programs[0]['deadline'], '2020-08-13T17:00:00+09:00')
                self.assertEqual(programs[0]['selected_gps'], [])
