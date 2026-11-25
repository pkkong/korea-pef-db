"""Shared result receipts must not create two institutional owners."""

import copy
import hashlib
import json
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from services.lp.src import lp_history_import_preflight as preflight
from services.lp.src import lp_newdeal_history_import as newdeal
from services.lp.src import lp_notice_publication as publication
from services.lp.src.build_lp_history_import import merge


STAMP = '2026-11-25T00:00:00+00:00'
RECRUITMENT = 'https://www.kgrowth.or.kr/notice_view.asp?idx=20&str_type=1&tab=1'
RESULT = 'https://www.kgrowth.or.kr/notice_view.asp?page=2&idx=25&str_type=3&tab=1'


def example():
    identity = {'target_institution_id': 'kdb', 'fund': '정책형뉴딜펀드', 'year': '2021', 'round': '정시'}
    events = [
        {'date': '2020-12-29', 'type': '모집 공고', 'title': '공동 모집', 'url': RECRUITMENT},
        {'date': '2021-02-26', 'type': '선정 결과', 'title': '공동 선정', 'url': RESULT},
    ]
    program = {'id': 'newdeal-test', 'title': '정책형 뉴딜펀드 2021년 정시 · 뉴딜성장형',
               'institution_id': 'kdb', 'joint_history_identity': identity, 'source_program_key': 'joint-identity',
               'events': events, 'status': '선정 완료', 'asset_scope': 'PE',
               'selected_gps': [{'name': '테스트파트너스', 'id': 'test-partners', 'asset_scope': 'PE', 'source_url': RESULT}]}
    notices = [{**e, 'institution_id': 'kgrowth', 'history_import': newdeal.NOTICE_KIND,
                'body': '공동 공식 원문', 'sha256': '1' * 64, 'checked_at': STAMP} for e in events]
    return program, notices


def test_append_preserves_existing_aliases_and_joint_source_owners_on_repeat():
    program, notices = example()
    old = {**copy.deepcopy(program), 'id': 'old-kdb', 'title': '다른 펀드',
           'source_program_key': 'old-key', 'joint_history_identity': None}
    old['events'] = [{**event, 'url': f'https://www.kdb.co.kr/{i}'} for i, event in enumerate(old['events'])]
    old['selected_gps'][0]['source_url'] = old['events'][1]['url']
    current = {'as_of': '2026-11-25', 'programs': [old], 'program_aliases': {'previous-route': 'old-kdb'}}
    payload = {'kind': newdeal.IMPORT_KIND, 'checked_at': STAMP, 'source': {}}
    with patch.object(newdeal, 'project', side_effect=lambda *_: copy.deepcopy((program, notices))), \
            patch.object(preflight, 'validate_history_notice', side_effect=lambda notice, _: notice):
        after, summary = preflight.proposal(current, payload, STAMP)
        assert after['programs'] == [old, program]
        assert after['history_notices'] == notices
        assert after['program_aliases'] == current['program_aliases']
        assert summary['storage_roundtrip_verified']
        repeat, summary = preflight.proposal(after, payload, STAMP)
        assert after == repeat and summary['reused_program_ids'] == [program['id']]


def test_existing_result_url_with_different_query_or_business_title_blocks_import():
    program, notices = example()
    unrelated = {**program, 'id': 'other-id', 'institution_id': 'kgrowth',
                 'title': '검토 결과', 'joint_history_identity': None,
                 'events': [{'url': 'https://kgrowth.or.kr/notice_view.asp?str_type=3&tab=1&idx=25',
                             'date': '2021-02-26', 'type': '선정 결과'}]}
    legacy = {**unrelated, 'institution_id': 'kdb', 'title': '정책형 뉴딜펀드 2021년 위탁운용사',
              'events': [{'url': 'https://www.kdb.co.kr/old', 'date': '2020-12-29', 'type': '모집 공고'}]}
    for old in (unrelated, legacy):
        try:
            newdeal.assert_no_overlap([old], program, notices)
        except ValueError as error:
            assert '겹침' in str(error)
        else:
            raise AssertionError(f'Duplicate accepted: {old}')


def test_daily_publisher_keeps_existing_track_and_does_not_reinterpret_joint_notices():
    program, sources = example()
    data = {'programs': [program], 'history_notices': sources}
    with patch.object(publication.history_notices, 'validate_history_notice', side_effect=lambda notice, _: notice):
        assert publication.publish_basic_notices(data, [], STAMP) == ([program], [])


def test_joint_proof_requires_pinned_workflow_and_cannot_supply_prepared_facts():
    source = {'kind': newdeal.BUNDLE_KIND, 'institution_id': 'kdb'}
    payload = {'kind': newdeal.IMPORT_KIND, 'checked_at': STAMP, 'source': source}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    sha = hashlib.sha256(raw).hexdigest()
    assert preflight.build_pinned_import(source, [], STAMP, sha)[1] == raw
    with TemporaryDirectory() as tmp:
        collection, candidate = Path(tmp) / 'collection.json', Path(tmp) / 'candidate.json'
        collection.write_bytes(b'{"notices":[]}')
        candidate.write_bytes(raw)
        assert merge(collection, candidate, sha) == 0
        assert collection.read_bytes() == b'{"notices":[]}'
    try:
        preflight.proposal({'programs': [], 'as_of': '2026-11-25'}, {**payload, 'program': example()[0]}, STAMP)
    except ValueError as error:
        assert '형식' in str(error)
    else:
        raise AssertionError('Prepared program facts entered the joint-source import')


def test_faq_publication_changes_only_the_confirmed_stage_and_is_idempotent():
    program, notices = example()
    program.update(deadline='2021-01-26T16:00:00+09:00', commitment_label='2,700억원 예정')
    publication._refresh(program, [], STAMP)
    faq = {'date': '2021-01-19', 'type': '질의응답', 'title': '정책형 뉴딜펀드 기업투자 FAQ 추가',
           'url': 'https://www.kgrowth.or.kr/notice_view.asp?idx=21&str_type=1&tab=1'}
    receipt = {**notices[0], 'url': faq['url'], 'date': '2021-01-06', 'event_type': '질의응답'}
    current = {'as_of': '2026-11-25', 'programs': [program], 'history_notices': notices,
               'program_aliases': {'existing-alias': program['id']}}
    payload = {'kind': newdeal.FOLLOWUP_IMPORT_KIND, 'checked_at': STAMP, 'source': {}}
    with patch.object(newdeal, 'project_followup', return_value=(program['id'], faq, receipt)), \
            patch.object(preflight, 'validate_history_notice', side_effect=lambda notice, _: notice):
        after, summary = preflight.proposal(current, payload, STAMP)
        assert summary['new_programs'] == [] and summary['updated_programs'] == [{'id': program['id'], 'added_event': faq}]
        assert len(after['programs']) == 1
        updated = after['programs'][0]
        assert updated['events'][1] == faq
        assert [stage for stage in updated['schedule_stages'] if stage['stage'] != 'faq'] == program['schedule_stages']
        assert updated['selected_gps'] == program['selected_gps']
        assert after['program_aliases'] == current['program_aliases']
        assert after['history_notices'] == [*notices, receipt]
        repeat, repeated = preflight.proposal(after, payload, STAMP)
        assert repeat == after and repeated['updated_programs'] == []
        for field, value in (('deadline', '2021-01-27T16:00:00+09:00'), ('commitment_label', '2,800억원')):
            bad = copy.deepcopy(after)
            bad['programs'][0][field] = value
            try:
                preflight._assert_preserved(current, bad, summary['updated_programs'])
            except ValueError as error:
                assert '기존 공개 사업' in str(error)
            else:
                raise AssertionError(f'An FAQ changed {field}')


def test_faq_date_comes_from_the_corporate_revision_and_checks_weekday():
    body = "※ '21.1.19(화)에 기업투자 FAQ 및 붙임4를 추가하여 첨부하였으니 참고하시기 바랍니다. " \
           "'21.10.28(목)에 붙임5(프로젝트펀드 FAQ)를 추가하여 첨부하였으니 참고하시기 바랍니다."
    assert newdeal._faq_date(body) == '2021-01-19'
    try:
        newdeal._faq_date(body.replace('(화)', '(금)'))
    except ValueError as error:
        assert '요일' in str(error)
    else:
        raise AssertionError('A mismatched weekday was accepted')
