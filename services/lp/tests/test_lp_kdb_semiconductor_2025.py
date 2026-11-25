"""Source-scoped sharing of the 2025 KDB recruitment and result URLs."""

import copy
from unittest.mock import patch

from services.lp.src import lp_history_import_preflight as preflight
from services.lp.src import lp_kdb_semiconductor_2025 as semiconductor
from services.lp.src import lp_notice_publication as publication


STAMP = '2026-11-25T00:00:00+00:00'
FUND = semiconductor.FUND
SHA = '1' * 64
VEHICLES = '기관전용 사모집합투자기구 경영참여 목적에 한함 벤처투자조합'
DEADLINE = '접수일시 2025년 5월 30일(금) 13:00 ~ 16:00'
GENERAL = f'''『{FUND}(일반)』 2025년 위탁운용사 선정계획 공고
블라인드 펀드 프로젝트 펀드 주관기관 한국산업은행, 한국성장금융 한국성장금융
0 총 300억원' • 총 630억원 (이월금액 포함)
- 소부장 300 - 소부장 300, 팹리스 330
선정 1개 300 600 제안금액
산업은행 125억원, IBK혁신성장펀드1호 100억원 반도체 생태계 모펀드 75억원
{VEHICLES}
{DEADLINE} 수시 접수'''
PURPOSE = '국내 중소·중견기업 블라 인드 소부장 기업을 영위하는 기업에 약정총액의 [60%] 이상 투자'
FISCAL = f'''『{FUND}(재정)』 2025년 위탁운용사 선정계획 공고
위탁운용 총액 : 총 850억원 내외
사다리2
기업은행
300
350
100
100
850
재정 산은 사다리2주1) 기은주2)
합계(비율)
300
350
100
100
850(71%)
1,200
1
산은
기업은행 혹은 기업은행 출자 모펀드
{DEADLINE}
{VEHICLES}
목표결성액의 60% 초과결성액의 30% IP를 보유한 기업 100억원 이상'''


def notice(number, date, track, title_suffix, attachments):
    url = f'https://www.kdb.co.kr/official/{number}'
    title = f'「{FUND}({track})」 2025년 위탁운용사 {title_suffix}'
    files = [{'name': name, 'url': f'{url}/{index}'} for index, (name, _) in enumerate(attachments)]
    return {'institution_id': 'kdb', 'source_channel': 'institution_board', 'url': url, 'date': date,
            'title': title, 'body': title, 'sha256': SHA, 'checked_at': STAMP, 'attachments': files,
            'attachment_texts': {file['url']: text for file, (_, text) in zip(files, attachments, strict=True)},
            'attachment_hashes': {file['url']: SHA for file in files}}


def evidence():
    native = f'{VEHICLES} 산업은행 억원 혁신성장펀드 호 억원125, IBK 1 100, 반도체 생태계 모펀드 억원75'
    recruitment = notice(1, '2025-05-13', '일반,재정', '선정계획 공고', [
        (f'붙임1. {FUND}(일반) 2025년 위탁운용사 선정계획 공고.pdf', native),
        (f'붙임2. {FUND}(재정) 2025년 위탁운용사 선정계획 공고.hwp', FISCAL)])
    pages = [{'page': number, 'width': 1000, 'height': 1400, 'text': text,
              'lines': [{'text': line, 'confidence': 1.0, 'bbox': [0.1, 0.2, 0.7, 0.1]}
                        for line in text.splitlines()]} for number, text in enumerate((GENERAL, PURPOSE), 1)]
    recruitment['attachment_ocr'] = {recruitment['attachments'][0]['url']: {
        'engine': 'macos-vision-r3-pdfkit-v1', 'version': 1, 'revision': 3, 'languages': ['ko-KR', 'en-US'],
        'os_version': 'test', 'helper_sha256': '2' * 64, 'input_sha256': SHA, 'input_bytes': 100, 'pages': pages}}
    result = notice(4, '2025-06-25', '일반,재정', '선정 결과', [
        (f'{FUND}(일반,재정) 2025년 위탁운용사 선정결과.pdf',
         f'{FUND} 2025년 위탁운용사 선정 결과\n펀드규모 선정운용사명\n재정 (1) 1,200 엘앤에스벤처캐피탈\n일반 (1) 600 컴퍼니케이파트너스')])
    faq = [notice(number, date, track, '선정 FAQ 게시', [
        (f'{FUND}({track}) 2025년 위탁운용사 선정계획 FAQ.{extension}', '질의응답')])
        for number, date, track, extension in ((2, '2025-05-21', '재정', 'hwp'), (3, '2025-05-22', '일반', 'pdf'))]
    return [recruitment, *faq, result]


def test_split_offerings_keep_both_source_urls_and_exact_rosters_on_replay():
    sources = evidence()
    payload = {'kind': 'lp_history_import_v1', 'checked_at': STAMP, 'notices': sources}
    with patch.object(publication.history_notices, 'validate_history_notice', side_effect=lambda source, _: copy.deepcopy(source)), \
            patch.object(preflight, 'validate_history_notice', side_effect=lambda source, _: copy.deepcopy(source)):
        current = {'programs': [], 'as_of': '2026-11-25'}
        after, report = preflight.proposal(current, payload, STAMP)
        assert report['history_notices_after'] == 4
        assert report['storage_roundtrip_verified']
        p = {program['source_program_key']: program for program in after['programs']}
        general, fiscal = (p[key] for key in semiconductor.KEYS.values())
        assert general['id'] != fiscal['id']
        for program, amount, bank, name, faq_index in (
                (general, 300, 125, '컴퍼니케이파트너스', 2), (fiscal, 850, 350, '엘앤에스벤처캐피탈', 1)):
            assert program['asset_scope'] == 'PE·VC 공동 모집'
            assert program['commitment_amount_krw'] == amount * 10**8
            assert program['contribution_allocations']['한국산업은행'] == bank * 10**8
            assert [gp['name'] for gp in program['selected_gps']] == [name]
            assert program['deadline'] == '2025-05-30T16:00:00+09:00'
            assert [event['url'] for event in program['events']] == [sources[i]['url'] for i in (0, faq_index, 3)]
        replayed, holds = publication.publish_basic_notices(after, [], STAMP)
        assert replayed == after['programs'] and not holds
        repeated, report = preflight.proposal(after, payload, STAMP)
        assert repeated == after and set(report['reused_program_ids']) == {general['id'], fiscal['id']}
        old = {**fiscal, 'id': 'existing-2025-semiconductor', 'source_program_key': 'legacy'}
        programs, holds = publication.publish_basic_notices({**after, 'programs': [old]}, [], STAMP)
        assert programs == [old] and len(holds) == 2


def test_missing_or_different_ocr_cannot_turn_the_general_project_into_the_blind_offer():
    for replacement in (None, '0' * 64):
        sources = evidence()
        receipt = sources[0]['attachment_ocr']
        if replacement:
            next(iter(receipt.values()))['input_sha256'] = replacement
        else:
            receipt.clear()
        with patch.object(publication.history_notices, 'validate_history_notice', side_effect=lambda source, _: source):
            programs, holds = publication.publish_basic_notices({'programs': [], 'history_notices': sources}, [], STAMP)
        assert programs == [] and len(holds) == 1
