"""Offline projection boundaries using retained joint-plan excerpts.

The excerpt sources and actual PDF fingerprints are documented in the two
joint-parser suites. These tests synthesize HTML receipts and byte wrappers;
they mock only PDF extraction, never listing/detail/hash/scope validation.
The real retained PDF and capture replay is additionally run offline by Lead.
"""
import base64
import copy
import hashlib
import html
import json
import unittest
from unittest.mock import patch

from services.lp.src import lp_joint_history_projection as projection
from services.lp.src import lp_kgrowth_history_replay as replay
from services.lp.src.lp_program_service import validate
from services.lp.tests.test_lp_kgrowth_history_terms import bundle, notice
from services.lp.tests.test_lp_kgrowth_joint_history import materials, OFFER as MATERIALS
from services.lp.tests.test_lp_kgrowth_newdeal_joint_history import newdeal, OFFER as NEWDEAL


CHECKED = '2026-11-17T00:35:00+00:00'
CAPTURED = '2026-11-16T12:31:00+00:00'
GUIDELINE = '붙임4. 뉴딜 투자가이드라인 상 분야 및 품목(6대 핵심산업 포함).xlsx'


def raw_detail(n, names=None, suffix=''):
    names = names or {}
    links = ''.join(f'<a href="{html.escape(u)}">{html.escape(names.get(u, "file"))}</a>'
                    for u in n['attachments'])
    return (f'<html><body><div class="view_info"><p class="tit">{html.escape(n["title"])}</p>'
            f'<p class="date">{n["date"]}</p></div>'
            f'<div class="veiw_contents">{html.escape(n["body"])}</div>{links}{suffix}</body></html>').encode('cp949')


def fixture(*, retained=True, missing=None, material_text=MATERIALS, newdeal_text=NEWDEAL):
    ns = [materials(material_text), newdeal(newdeal_text)]
    assets, extracted, details, names = {}, {}, {}, {}
    for n in ns:
        for url in n['attachments']:
            raw = ('%PDF synthetic wrapper ' + url).encode()
            sha = hashlib.sha256(raw).hexdigest()
            n['attachment_hashes'][url] = sha
            assets[sha], extracted[raw] = raw, n['attachment_texts'][url]
        if missing and '정책형' in n['title']:
            url = n['attachments'][0].replace('Notice1', 'Notice4')
            n['attachments'].append(url)
            names[url] = GUIDELINE if missing == 'guideline' else '별도 모집계획.pdf'
        raw = raw_detail(n, names)
        details[n['url']] = raw
        n['discovery_provenance']['detail_sha256'] = hashlib.sha256(raw).hexdigest()
        if retained:
            n['discovery_provenance']['detail_response_base64'] = base64.b64encode(raw).decode()
    return bundle(*ns), assets, extracted, details


def run_fixture(b, assets, extracted, *, capture=None, existing=None, checked_at=CHECKED):
    with patch.object(replay, 'kgrowth_attachment_text', side_effect=lambda raw: extracted[raw]), \
            patch.object(replay, 'fetch_detail') as fetch:
        result = projection.review_joint_candidates(b, capture, assets.__getitem__,
                                                    checked_at=checked_at, existing_programs=existing)
        fetch.assert_not_called()
    return result


def by_fund(result, name):
    return next(c for c in result['candidates'] if name in c['identity']['fund'])


def candidate_program(b, assets, extracted):
    return copy.deepcopy(by_fund(run_fixture(b, assets, extracted), '소재')['program'])


class JointHistoryProjectionTests(unittest.TestCase):
    def test_newdeal_result_must_follow_the_same_bundle_and_business_round(self):
        source, assets, extracted, _ = fixture()
        raw = json.dumps(source, ensure_ascii=False).encode()
        source_sha = hashlib.sha256(raw).hexdigest()

        def receipt(**refs):
            return json.dumps({'context_bundle_sha256': source_sha, **refs}).encode()

        def sha(content):
            return hashlib.sha256(content).hexdigest()

        listing = receipt()
        followup = receipt(prior_capture_sha256=sha(listing))
        detail = receipt(prior_capture_sha256=sha(listing), followup_capture_sha256=sha(followup))
        linked = {'prior_capture_sha256': sha(listing), 'followup_capture_sha256': sha(followup),
                  'result_capture_sha256': sha(detail)}
        failure = receipt(**linked)
        captures = {'search': listing, 'followup': followup, 'detail': detail, 'failed_pdf': failure,
                    'pdf': receipt(**linked, failed_capture_sha256=sha(failure))}
        proof = {'detail': {'stated_business_year': '2021', 'stated_round': '정시', 'date': '2021-02-26',
                            'title': '정책형 뉴딜펀드 정시 선정 결과'},
                 'source_detail': {'url': 'https://www.kgrowth.or.kr/selection'},
                 'source_pdf': {'checked_at': CHECKED}}
        with patch.object(replay, 'kgrowth_attachment_text', side_effect=lambda pdf: extracted[pdf]), \
             patch('services.lp.src.lp_kgrowth_press_probe.replay_press_result_pdf', return_value=(b'pdf', proof)), \
             patch('services.lp.src.lp_kgrowth_newdeal_joint_history.read_newdeal_growth_result_pdf',
                   return_value={'selected_managers': ['예시운용사']}) as read:
            def reviewed(evidence):
                return projection.review_newdeal_growth_selection(raw, None, assets.__getitem__, evidence, checked_at=CHECKED)

            result = reviewed(captures)
            self.assertEqual(result['track']['key'], 'blind_newdeal_growth')
            self.assertEqual(result['selection']['selected_managers'], ['예시운용사'])
            self.assertFalse(result['publication_ready'])
            self.assertEqual(result['existing_match_status'], 'not_checked')
            program = result['program']
            self.assertEqual(program['status'], '선정 완료')
            self.assertEqual(program['selected_gps'][0]['source_url'], proof['source_detail']['url'])
            self.assertEqual(program['funding_plan']['actual_gp_allocation_krw'], None)
            self.assertNotIn('commitment_amount_krw', program)
            self.assertTrue(program['commitment_label'].startswith('공동 정책출자 예정'))
            with self.assertRaisesRegex(ValueError, '연결 지문 불일치'):
                reviewed({**captures, 'failed_pdf': failure + b' '})
            with patch.dict(proof['detail'], {'stated_round': '수시'}), self.assertRaisesRegex(ValueError, '회차'):
                reviewed(captures)
            read.assert_called_once()

    def test_two_businesses_each_keep_only_two_kdb_blind_tracks(self):
        b, assets, texts, _ = fixture()
        before = copy.deepcopy(b)
        r = run_fixture(b, assets, texts)
        self.assertEqual(len(r['candidates']), 2, r['holds'])
        self.assertEqual(r['holds'], [])
        self.assertTrue(r['source_replay']['raw_replay_complete'])
        self.assertFalse(r['publication_ready'])
        self.assertFalse(r['published'])
        self.assertEqual((r['official_http_requests'], r['database_reads'], r['database_writes']), (0, 0, 0))
        self.assertEqual(b, before)
        for c in r['candidates']:
            self.assertEqual(c['source_document'], next(n for n in b['notices'] if n['url'] == c['source_document']['url']))
            self.assertEqual(c['source_document']['institution_id'], 'kgrowth')
            self.assertEqual(c['target_institution_id'], 'kdb')
            self.assertEqual(c['joint_issuer_institution_ids'], ['kdb', 'kgrowth'])
            self.assertEqual(len(c['tracks']), 2)
            self.assertTrue(all(t['fund_kind'] == 'blind' and t['program_lead_institution_id'] == 'kdb' for t in c['tracks']))
            self.assertTrue(c['minimum_recruitment_evidence_verified'])
            self.assertTrue(c['source_full_replay_complete'])
            self.assertFalse(c['publication_ready'])
            self.assertEqual(c['program']['selected_gps'], [])
            self.assertEqual(c['program']['asset_scope'], 'PE·VC 공동 모집')
            self.assertEqual(c['program']['status'], '접수 마감')
            self.assertEqual(c['program']['checked_at'], c['source_document']['checked_at'])
            validate({'as_of': CHECKED[:10], 'programs': [c['program']]})

    def test_joint_plans_are_not_lp_own_pe_or_actual_allocations(self):
        b, assets, texts, _ = fixture()
        r = run_fixture(b, assets, texts)
        for name, total, own, formation in [('소재', 2100, 300, 3000), ('정책형', 4450, None, 14000)]:
            c = by_fund(r, name)
            self.assertEqual(c['funding_plan']['planned_joint_commitment_total_krw'], total * 10**8)
            self.assertEqual(c['funding_plan']['lead_institution_own_planned_krw'], own * 10**8 if own is not None else None)
            self.assertEqual(c['funding_plan']['planned_formation_target_krw'], formation * 10**8)
            self.assertFalse(c['funding_plan']['pe_annual_own_commitment_eligible'])
            self.assertIsNone(c['funding_plan']['actual_gp_allocation_krw'])
            self.assertNotIn('commitment_amount_krw', c['program'])
            self.assertNotIn('total_commitment_amount_krw', c['program'])
            self.assertIn('공동출자자 모집 계획', c['program']['commitment_label'])
            self.assertTrue(all(t['selected_managers'] == [] for t in c['tracks']))

    def test_year_deadline_domestic_obligations_and_gp_qualification_stay_distinct(self):
        b, assets, texts, _ = fixture()
        r = run_fixture(b, assets, texts)
        new = by_fund(r, '정책형')
        self.assertEqual(new['identity']['year'], '2021')
        self.assertEqual((new['posted_date'], new['issued_date']), ('2020-12-29', '2020-12-29'))
        self.assertEqual(new['program']['events'][0]['date'], '2020-12-29')
        self.assertEqual(new['program']['deadline'], '2021-01-26T16:00:00+09:00')
        self.assertTrue(new['tracks'][1]['pe_only_current_legal_form_observed'])
        self.assertFalse(new['tracks'][0]['pe_only_current_legal_form_observed'])
        self.assertEqual(new['tracks'][1]['strategy']['domestic_sme_min_investment_pct'], 50)
        general, semi = by_fund(r, '소재')['tracks']
        self.assertFalse(general['independent_pe_scope_verified'])
        self.assertNotIn('domestic_sme_semiconductor_min_krw', general['strategy'])
        self.assertTrue(semi['strategy']['obligations_may_overlap'])
        self.assertEqual(semi['strategy']['domestic_sme_semiconductor_min_krw'], 500*10**8)

    def test_missing_advertised_guideline_preserves_full_hold_but_not_core_failure(self):
        b, assets, texts, _ = fixture(missing='guideline')
        r = run_fixture(b, assets, texts)
        self.assertEqual(len(r['candidates']), 2, r['holds'])
        self.assertEqual(len(r['source_replay']['holds']), 1)
        self.assertFalse(r['source_replay']['raw_replay_complete'])
        c = by_fund(r, '정책형')
        self.assertTrue(c['minimum_recruitment_evidence_verified'])
        self.assertFalse(c['source_full_replay_complete'])
        self.assertEqual(len(c['missing_advertised_attachments']), 1)
        self.assertFalse(c['missing_advertised_attachments'][0]['content_read'])
        self.assertIn(GUIDELINE, c['missing_advertised_attachments'][0]['advertised_labels'][0])
        self.assertTrue(by_fund(r, '소재')['source_full_replay_complete'])

    def test_unknown_missing_attachment_does_not_get_a_basic_scope_exception(self):
        b, assets, texts, _ = fixture(missing='unknown')
        r = run_fixture(b, assets, texts)
        self.assertEqual(len(r['candidates']), 1)
        self.assertNotIn('정책형', r['candidates'][0]['identity']['fund'])
        self.assertTrue(any('XLSX' in h['reason'] for h in r['holds']))

    def test_selected_core_bytes_missing_or_corrupt_blocks_that_program(self):
        for bad in ('missing', 'corrupt'):
            with self.subTest(bad=bad):
                b, assets, texts, _ = fixture(missing='guideline')
                n = next(n for n in b['notices'] if '정책형' in n['title'])
                sha = next(iter(n['attachment_hashes'].values()))
                if bad == 'missing':
                    del assets[sha]
                else:
                    assets[sha] = b'corrupt retained bytes'
                r = run_fixture(b, assets, texts)
                self.assertEqual(len(r['candidates']), 1, r['holds'])
                self.assertEqual(r['candidates'][0]['identity']['round'], '2차')
                self.assertTrue(any(h.get('stage') == 'joint_projection' for h in r['holds']))

    def test_changed_extraction_cannot_be_approved_from_hash_metadata(self):
        b, assets, texts, _ = fixture()
        n = b['notices'][0]
        url = n['attachments'][0]
        n['attachment_texts'][url] = n['attachment_texts'][url].replace(
            '운용사신청자격 ◦국내에설립된법인', '운용사신청자격 ◦국내에설립된법인(변조)')
        r = run_fixture(b, assets, texts)
        self.assertEqual(len(r['candidates']), 1)
        self.assertTrue(any('판독문' in h['reason'] for h in r['source_replay']['holds']))

    def test_changed_raw_body_or_unmatched_metadata_fails_closed(self):
        b, assets, texts, _ = fixture()
        b['notices'][0]['body'] += '검증되지 않은 변경'
        r = run_fixture(b, assets, texts)
        self.assertEqual(r['candidates'], [])
        b, assets, texts, _ = fixture()
        n = b['notices'][0]
        n['body'] += '\n검증되지 않은 변경'
        import json
        n['sha256'] = hashlib.sha256(json.dumps([n['title'], n['date'], n['body']], ensure_ascii=False).encode()).hexdigest()
        r = run_fixture(b, assets, texts)
        self.assertEqual(len(r['candidates']), 1)
        self.assertTrue(any('보관 제목' in h['reason'] for h in r['source_replay']['holds']))

    def test_source_institution_cannot_be_rewritten_to_the_destination(self):
        b, assets, texts, _ = fixture()
        b['notices'][0]['institution_id'] = 'kdb'
        self.assertEqual(run_fixture(b, assets, texts)['candidates'], [])

    def test_capture_is_verified_and_new_bytes_do_not_replace_old_fingerprint(self):
        b, assets, texts, raw = fixture(retained=False, missing='guideline')
        for url in raw:
            raw[url] = raw[url].replace(b'</body>', b'<!-- dynamic visits -->\n</body>')
        c = replay.capture_details(b, lambda url: {'raw': raw[url], 'http_status': 200},
                                   checked_at=CAPTURED, review_scope='joint_originals')
        before = copy.deepcopy((b, c))
        r = run_fixture(b, assets, texts, capture=c)
        self.assertEqual(len(r['candidates']), 2, r['holds'])
        for candidate in r['candidates']:
            receipt = candidate['source_replay']['detail']
            self.assertEqual(receipt['kind'], 'recaptured_semantic_match')
            self.assertFalse(receipt['original_bytes_match'])
            self.assertEqual(receipt['original_detail_sha256'], candidate['source_document']['discovery_provenance']['detail_sha256'])
        self.assertEqual((b, c), before)
        for key, value in [('requests', 999), ('bundle_content_sha256', '0'*64)]:
            with self.subTest(key=key):
                tampered = copy.deepcopy(c)
                tampered[key] = value
                self.assertEqual(run_fixture(b, assets, texts, capture=tampered)['candidates'], [])

    def test_missing_detail_cannot_be_replaced_by_readable_attachment(self):
        b, assets, texts, _ = fixture(retained=False)
        r = run_fixture(b, assets, texts)
        self.assertEqual(r['candidates'], [])
        self.assertTrue(any('상세 원본' in h['reason'] for h in r['holds']))

    def test_precomputed_validation_reports_are_not_api_inputs(self):
        b, assets, _, _ = fixture()
        with self.assertRaises(TypeError):
            projection.review_joint_candidates(b, None, assets.__getitem__, checked_at=CHECKED,
                                               source_replay={'raw_replay_complete': True})

    def test_notice_order_and_retrieval_hash_are_not_business_identity(self):
        b, assets, texts, _ = fixture()
        first = run_fixture(b, assets, texts)
        b['notices'].reverse()
        second = run_fixture(b, assets, texts)
        self.assertEqual([c['candidate_id'] for c in first['candidates']], [c['candidate_id'] for c in second['candidates']])
        n = materials()
        other = notice('981', n['title'], n['date'], n['body'], MATERIALS)
        blob = b'%PDF changed source URL wrapper'
        sha = hashlib.sha256(blob).hexdigest()
        other['attachment_hashes'] = {other['attachments'][0]: sha}
        detail = raw_detail(other)
        other['discovery_provenance'].update(detail_sha256=hashlib.sha256(detail).hexdigest(), detail_response_base64=base64.b64encode(detail).decode())
        changed = run_fixture(bundle(other), {sha:blob}, {blob:MATERIALS})
        self.assertEqual(by_fund(first, '소재')['candidate_id'], changed['candidates'][0]['candidate_id'])
        self.assertNotEqual(by_fund(first, '소재')['source_document']['source_id'], changed['candidates'][0]['source_document']['source_id'])

    def test_existing_single_owner_is_reuse_only_and_all_its_facts_survive(self):
        b, assets, texts, _ = fixture()
        existing = candidate_program(b, assets, texts)
        existing['id'] = 'kdb-2021-existing-url'
        existing.update(status='선정 완료', commitment_amount_krw=77, commitment_label='기존 승인 조건')
        result_url = 'https://www.kdb.co.kr/official-result'
        existing['events'].append({'type':'선정 결과','date':'2021-06-01','title':'기존 결과','url':result_url})
        existing['selected_gps'] = [{'name':'기존 검증 운용사','asset_scope':'PE','source_url':result_url}]
        before = copy.deepcopy(existing)
        r = run_fixture(b, assets, texts, existing=[existing])
        c = by_fund(r, '소재')
        self.assertEqual(existing, before)
        self.assertIsNone(c['program'])
        self.assertEqual(c['existing_match_status'], 'reuse_proposed')
        self.assertEqual(c['reuse_proposal']['existing_program'], before)
        self.assertEqual(c['reuse_proposal']['program_id'], before['id'])
        self.assertFalse(c['reuse_proposal']['overwrite_existing_fields'])
        c['reuse_proposal']['existing_program']['selected_gps'].clear()
        self.assertEqual(existing, before)

    def test_legacy_single_source_url_owner_is_reused_without_terms_refresh(self):
        b, assets, texts, _ = fixture()
        p = candidate_program(b, assets, texts)
        p['id'] = 'kdb-legacy'
        for key in ('joint_history_identity', 'joint_history_track_keys', 'source_program_key'):
            p.pop(key)
        c = by_fund(run_fixture(b, assets, texts, existing=[p]), '소재')
        self.assertIsNone(c['program'])
        self.assertEqual(c['reuse_proposal']['existing_program'], p)

    def test_multiple_owners_institution_and_id_conflicts_are_held(self):
        b, assets, texts, _ = fixture()
        p = candidate_program(b, assets, texts)
        for bad in ('multiple', 'institution', 'id'):
            with self.subTest(bad=bad):
                other = copy.deepcopy(p)
                if bad == 'multiple':
                    other['id'] = 'kdb-another-owner'
                    existing = [p, other]
                elif bad == 'institution':
                    other['institution_id'] = 'kgrowth'
                    existing = [other]
                else:
                    other['events'][0]['url'] = 'https://www.kdb.co.kr/different-recruitment'
                    for key in ('source_program_key', 'joint_history_identity'):
                        other.pop(key)
                    existing = [other]
                r = run_fixture(b, assets, texts, existing=existing)
                self.assertEqual(len(r['candidates']), 1)
                self.assertEqual(r['candidates'][0]['identity']['round'], '정시')

    def test_explicit_existing_year_round_or_track_subset_conflicts_are_held(self):
        b, assets, texts, _ = fixture()
        p = candidate_program(b, assets, texts)
        for key, value in [('business_year','2022'), ('business_round','3차'), ('joint_history_track_keys',['일반'])]:
            with self.subTest(key=key):
                changed = {**p, key:value}
                self.assertEqual(len(run_fixture(b, assets, texts, existing=[changed])['candidates']), 1)

    def test_duplicate_existing_ids_cannot_reach_projection(self):
        b, assets, texts, _ = fixture()
        p = candidate_program(b, assets, texts)
        self.assertEqual(run_fixture(b, assets, texts, existing=[p, p])['candidates'], [])

    def test_other_board_same_identity_needs_the_same_decisive_source_evidence(self):
        b, assets, texts, _ = fixture()
        p = candidate_program(b, assets, texts)
        p['id'] = 'kdb-original-board'
        p['events'][0]['url'] = 'https://www.kdb.co.kr/joint-original'
        for key in ('source_program_key', 'joint_history_identity', 'joint_history_track_keys'):
            p.pop(key)
        # The title is a duplicate warning, not permission to invent a second
        # program or claim the two boards contain the same original.
        self.assertEqual(len(run_fixture(b, assets, texts, existing=[p])['candidates']), 1)
        source = b['notices'][0]
        p['extraction_evidence'] = {'joint_plan': {'attachment_sha256': next(iter(source['attachment_hashes'].values()))}}
        c = by_fund(run_fixture(b, assets, texts, existing=[p]), '소재')
        self.assertEqual(c['reuse_proposal']['program_id'], p['id'])
        self.assertEqual(c['reuse_proposal']['existing_program'], p)

    def test_same_source_legacy_title_with_a_different_explicit_round_is_held(self):
        b, assets, texts, _ = fixture()
        p = candidate_program(b, assets, texts)
        for key in ('source_program_key', 'joint_history_identity'):
            p.pop(key)
        p['title'] = p['title'].replace('(2차)', '(3차)')
        self.assertEqual(len(run_fixture(b, assets, texts, existing=[p])['candidates']), 1)

    def test_scope_budget_lead_and_deadline_corruption_never_forms_a_program(self):
        for old, new in [('3,100 5,000','3,200 5,000'),
                         ('주관기관 한국산업은행간접투자금융실','주관기관 한국성장금융간접투자금융실'),
                         ('21일(수)','21일(목)'),
                         ('벤처투자조합','다른기구')]:
            with self.subTest(old=old):
                b, assets, texts, _ = fixture(material_text=MATERIALS.replace(old,new))
                self.assertEqual(run_fixture(b, assets, texts)['candidates'], [])

    def test_consistent_source_budget_changes_are_read_without_fixed_amounts(self):
        materials_changed = MATERIALS.replace(
            '1,100 200 - 1,300 2,000 65%', '1,200 200 - 1,400 2,000 70%').replace(
            '합계 2,400 300 400 3,100 5,000', '합계 2,500 300 400 3,200 5,000').replace(
            '650억원이내(최소결성금액의65%이내)', '700억원이내(최소결성금액의70%이내)')
        newdeal_changed = NEWDEAL.replace('1,75035.0%', '1,80036.0%').replace(
            '초과8755,000', '초과9005,000').replace('7,450', '7,500')
        b, assets, texts, _ = fixture(material_text=materials_changed, newdeal_text=newdeal_changed)
        r = run_fixture(b, assets, texts)
        self.assertEqual(len(r['candidates']), 2, r['holds'])
        self.assertEqual(by_fund(r, '소재')['funding_plan']['planned_joint_commitment_total_krw'], 2200*10**8)
        self.assertEqual(by_fund(r, '정책형')['funding_plan']['planned_joint_commitment_total_krw'], 4500*10**8)

    def test_valid_captures_for_reordered_inputs_keep_the_same_candidate_ids(self):
        b, assets, texts, details = fixture(retained=False)
        first_capture = replay.capture_details(b, lambda url: {'raw':details[url], 'http_status':200},
                                               checked_at=CAPTURED, review_scope='joint_originals')
        first = run_fixture(b, assets, texts, capture=first_capture)
        b['notices'].reverse()
        # Changing a pinned bundle must not weaken the existing capture check.
        self.assertEqual(run_fixture(b, assets, texts, capture=first_capture)['candidates'], [])
        second_capture = replay.capture_details(b, lambda url: {'raw':details[url], 'http_status':200},
                                                checked_at=CAPTURED, review_scope='joint_originals')
        second = run_fixture(b, assets, texts, capture=second_capture)
        self.assertEqual([c['candidate_id'] for c in first['candidates']],
                         [c['candidate_id'] for c in second['candidates']])

    def test_recruitment_amendments_do_not_keep_original_deadline_current(self):
        for word in ('정정','연장','취소'):
            with self.subTest(word=word):
                b, assets, texts, _ = fixture()
                title = materials()['title'].replace('【선정공고】', f'【{word}공고】').replace('선정계획 공고', f'선정계획 {word}공고')
                later = notice('990', title, '2021-04-05', '모집 조건 변경 원문')
                b = bundle(*b['notices'], later)
                r = run_fixture(b, assets, texts)
                self.assertEqual(len(r['candidates']), 1, r['holds'])
                self.assertEqual(r['candidates'][0]['identity']['round'], '정시')
                self.assertTrue(any('후속 모집' in h['reason'] for h in r['holds']))

    def test_unquoted_explicit_same_recruitment_changes_hold_all_three_kinds(self):
        for word in ('정정', '연장', '취소'):
            with self.subTest(word=word):
                b, assets, texts, _ = fixture()
                title = f'2021년 소재·부품·장비 분야 투자 전용 펀드(2차) 위탁운용사 선정계획 {word} 공고'
                change = notice('993', title, '2021-04-05', '해당 모집의 조건을 변경합니다.')
                b = bundle(*(b['notices'] + [change]))
                before = copy.deepcopy(b)
                r = run_fixture(b, assets, texts)
                self.assertEqual(b, before)
                self.assertEqual(len(r['candidates']), 1, r['holds'])
                self.assertEqual(r['candidates'][0]['identity']['round'], '정시')
                self.assertTrue(any(change['url'] in h['reason'] and '같은 펀드·사업연도·회차' in h['reason']
                                    for h in r['holds']))
                self.assertFalse(any(c['program'] and c['program']['deadline'] == '2021-04-21T16:00:00+09:00'
                                     for c in r['candidates']))

    def test_known_family_with_uncertain_keys_holds_without_inheriting_post_year(self):
        titles = [
            '소재·부품·장비 분야 투자 전용 펀드(2차) 위탁운용사 선정계획 연장 공고',
            '2021년 소재·부품·장비 분야 투자 전용 펀드 위탁운용사 선정계획 정정 공고',
            '소재·부품·장비 분야 투자 전용 펀드 위탁운용사 선정계획 취소 공고',
            '2021년·2022년 소재·부품·장비 분야 투자 전용 펀드(2차) 위탁운용사 선정계획 변경 공고',
            '2021년 소재·부품·장비 분야 투자 전용 펀드(2차/3차) 위탁운용사 선정계획 연장 공고',
            '소재·부품·장비 분야 투자 전용 펀드(2차) 위탁운용사 선정계획 연장 공고(접수마감 2022년1월)',
        ]
        for title in titles:
            with self.subTest(title=title):
                b, assets, texts, _ = fixture()
                change = notice('993', title, '2021-04-05',
                                '운용사 자격: 국내 설립 법인. 과거 2022년 3차 사업 운용실적을 기재합니다.')
                b = bundle(*(b['notices'] + [change]))
                r = run_fixture(b, assets, texts)
                self.assertEqual(len(r['candidates']), 1, r['holds'])
                self.assertTrue(any(change['url'] in h['reason'] and '식별 미확인' in h['reason']
                                    for h in r['holds']))

    def test_explicit_different_unquoted_year_round_or_named_round_stays_separate(self):
        titles = [
            '2022년 소재·부품·장비 분야 투자 전용 펀드(2차) 위탁운용사 선정계획 연장 공고',
            '2021년 소재·부품·장비 분야 투자 전용 펀드(3차) 위탁운용사 선정계획 취소 공고',
            '정책형 뉴딜펀드 2021년 수시 위탁운용사 선정계획 정정 공고',
            '정책형 뉴딜펀드 2022년 정시 위탁운용사 선정계획 연장 공고',
            '2021년 「소재·부품·장비 분야 투자 전용 펀드 별도사업(2차)」 위탁운용사 선정계획 변경 공고',
        ]
        for title in titles:
            with self.subTest(title=title):
                b, assets, texts, _ = fixture()
                change = notice('993', title, '2021-04-05', '별개 사업의 모집 조건 변경')
                b = bundle(*(b['notices'] + [change]))
                r = run_fixture(b, assets, texts)
                self.assertEqual(len(r['candidates']), 2, r['holds'])
                self.assertEqual(r['holds'], [])

    def test_uncertain_regular_or_rolling_round_is_held_and_result_changes_are_not_terms(self):
        for suffix in ('정시·수시 위탁운용사 선정계획 연장 공고',
                       '위탁운용사 선정계획 정정 공고'):
            with self.subTest(suffix=suffix):
                b, assets, texts, _ = fixture()
                change = notice('993', '정책형 뉴딜펀드 2021년 ' + suffix,
                                '2021-02-26', '현재 투자기구와 운용사 자격을 안내합니다.')
                b = bundle(*(b['notices'] + [change]))
                r = run_fixture(b, assets, texts)
                self.assertEqual(len(r['candidates']), 1, r['holds'])
                self.assertEqual(r['candidates'][0]['identity']['round'], '2차')
                self.assertTrue(any('식별 미확인' in h['reason'] for h in r['holds']))
        for stage in ('선정 결과 정정 공고', '최종 결과 취소 공고', '접수 결과 변경 공고'):
            with self.subTest(stage=stage):
                b, assets, texts, _ = fixture()
                change = notice('993', '정책형 뉴딜펀드 2021년 정시 위탁운용사 ' + stage,
                                '2021-02-26', '결과는 별도 주관 트랙 원문 검증이 필요합니다.')
                b = bundle(*(b['notices'] + [change]))
                r = run_fixture(b, assets, texts)
                self.assertEqual(len(r['candidates']), 2, r['holds'])
                self.assertTrue(all(c['program']['selected_gps'] == [] for c in r['candidates']))

    def test_qualification_body_cannot_establish_an_unidentified_title_family(self):
        b, assets, texts, _ = fixture()
        change = notice('993', '위탁운용사 신청 자격 정정 공고', '2021-04-05',
                        '소재·부품·장비 분야 투자 전용 펀드 2021년 2차. 국내 설립 법인의 과거 운용 실적.')
        b = bundle(*(b['notices'] + [change]))
        r = run_fixture(b, assets, texts)
        self.assertEqual(len(r['candidates']), 2, r['holds'])

    def test_different_round_or_corrected_result_is_not_a_recruitment_amendment(self):
        b, assets, texts, _ = fixture()
        title = materials()['title'].replace('【선정공고】','【정정공고】').replace('(2차)','(3차)')
        other = notice('991', title, '2021-04-05', '다른 회차 조건 정정')
        result = notice('992', newdeal()['title'].replace('【선정공고】','【선정결과】').replace('선정계획 공고','선정 결과 공고(정정)'), '2021-02-26', '결과 표는 별도 트랙 확인 필요')
        b = bundle(*b['notices'], other, result)
        self.assertEqual(len(run_fixture(b, assets, texts)['candidates']), 2)

    def test_dates_cannot_be_freshened_by_the_review_call(self):
        b, assets, texts, _ = fixture()
        for checked in ('2026-11-15T05:00:00+00:00','2099-01-01T00:00:00+00:00','2026-11-17T00:35:00'):
            with self.subTest(checked=checked):
                self.assertEqual(run_fixture(b, assets, texts, checked_at=checked)['candidates'], [])


if __name__ == '__main__':
    unittest.main()
