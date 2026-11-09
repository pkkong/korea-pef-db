"""Constructed full HTML/PDF proofs: no network or manually approved notice IDs."""
import base64
import copy
import hashlib
import unittest
from io import BytesIO
from unittest.mock import patch

from services.lp.src import collect_kexim_programs as collector
from services.lp.src import kexim_followup as followup
from services.lp.tests.test_collect_kexim_programs import fixture


def pdf(text):
    """Small real PDF with an explicit Unicode map; no font/renderer dependency."""
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, DictionaryObject, ArrayObject, DecodedStreamObject, NumberObject
    writer = PdfWriter(); page = writer.add_blank_page(width=600, height=800)
    chars = sorted(set(text.replace('\n', '')))
    mapping = ('1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n'
               + str(len(chars)) + ' beginbfchar\n'
               + '\n'.join('<' + c.encode('utf-16-be').hex() + '> <' + c.encode('utf-16-be').hex() + '>' for c in chars)
               + '\nendbfchar')
    unicode_map = DecodedStreamObject(); unicode_map.set_data(mapping.encode())
    cid = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/CIDFontType2'),
                            NameObject('/BaseFont'): NameObject('/Fixture'),
                            NameObject('/CIDSystemInfo'): DictionaryObject({NameObject('/Registry'): NameObject('/Adobe'),
                                NameObject('/Ordering'): NameObject('/Identity'), NameObject('/Supplement'): NumberObject(0)})})
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type0'),
                            NameObject('/BaseFont'): NameObject('/Fixture'), NameObject('/Encoding'): NameObject('/Identity-H'),
                            NameObject('/DescendantFonts'): ArrayObject([writer._add_object(cid)]),
                            NameObject('/ToUnicode'): writer._add_object(unicode_map)})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(('BT /F1 10 Tf 20 750 Td ' + ' 0 -14 Td '.join('<' + line.encode('utf-16-be').hex() + '> Tj' for line in text.split('\n')) + ' ET').encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO(); writer.write(output)
    return output.getvalue()


def base_recipe():
    _, recipe = fixture()
    recipe['title'] = '2026년 하반기 중소중견 글로벌 성장펀드 (PE)'
    recipe['manager_lists'] = {'applicants': {
        '첨단전략 중형': ['중형가운용', '중형나운용', '중형다운용', '중형라운용'],
        '첨단전략 소형': ['소형가운용', '소형나운용', '소형다운용', '소형라운용', '소형마운용']},
        'shortlist': {}, 'selected': {}}
    recipe['sources'][1]['team_count'] = 9
    return recipe


def table_text():
    return ('2026년 하반기 블라인드펀드 출자사업 제안서 심사 결과\n'
            '□ 현장실사 및 제안서 발표 대상 운용사 명단\n'
            '[중소·중견 글로벌 성장펀드]\n'
            '지원분야 수은 출자예정금액 (선정예정 운용사수) 대상 운용사명 (분야별 가나다순)\n'
            '첨단전략 중형 분야 1,000억원 (2개사)\n'
            '중형가운용 중형나운용 중형다운용 중형라운용\n'
            '첨단전략 소형 분야 500억원 (2개사)\n'
            '소형가운용 소형나운용 소형다운용 소형라운용\n'
            '합계 1,500억원 (4개사) 8개사(중형 4, 소형 4)\n'
            '[중소·벤처 초혁신 성장펀드]\n'
            '대형 분야 VC가운용 VC나운용\n'
            '합계 12개사 (대형4, 중형4, 소형4)\n'
            '※ 현장실사 오류 확인시 제안서 발표 대상에서 제외 가능')


def notice(text=None, *, title=None, body=None, date='2026.10.13'):
    title = title or '2026년 하반기 블라인드펀드 출자사업 운용사 제안서 서류심사 결과'
    body = body or '한국수출입은행의 2026년 하반기 블라인드펀드 출자사업 서류심사 결과를 공지합니다. 현장실사 및 제안서 발표 일정은 개별 안내합니다.'
    html = (f'<h1 class="detail-view-title">{title}</h1><span title="작성일">{date}</span>'
            f'<div class="detail-view-box"><p>{body}</p></div>'
            '<div class="detail-view-file"><a href="/comm/getFile?upperNo=3&amp;fileNo=1">공식심사.pdf</a></div>').encode()
    n = collector.parse_detail('3', html)
    n['detail_proof'] = {'kind': followup.DETAIL_KIND, 'raw_base64': base64.b64encode(html).decode(),
                         'sha256': hashlib.sha256(html).hexdigest(), 'byte_length': len(html)}
    n['checked_at'] = '2026-11-09T15:53:00+09:00'
    raw = pdf(text if text is not None else table_text())
    url = n['attachments'][0]['url']
    n['attachment_hashes'] = {url: hashlib.sha256(raw).hexdigest()}
    n['attachment_texts'] = {url: 'legacy layout is not the canonical proof'}
    collector.retain_attachment_proof(n, raw)
    return n


class KeximFollowupTests(unittest.TestCase):
    def test_complete_raw_proofs_add_only_eight_pe_screening_candidates(self):
        recipe = base_recipe(); original = copy.deepcopy(recipe); n = notice(); original_notice = copy.deepcopy(n)
        with patch.object(collector, '_official_fetch', side_effect=AssertionError('No network')):
            result = followup.augment_recipe(recipe, [n], n['checked_at'])
        self.assertEqual(recipe, original)
        self.assertEqual(n, original_notice)
        self.assertEqual(result['manager_lists']['shortlist'], {k: v[:4] for k, v in recipe['manager_lists']['applicants'].items()})
        self.assertEqual(result['manager_lists']['selected'], {})
        self.assertEqual(result['sources'][-1]['team_count'], 8)
        self.assertEqual(result['sources'][-1]['event'], '서류심사 결과')
        for key in recipe:
            if key not in ('sources', 'manager_lists', 'manager_evidence'):
                self.assertEqual(result[key], recipe[key])
        self.assertEqual(result['sources'][:-1], recipe['sources'])
        self.assertEqual(result['manager_lists']['applicants'], recipe['manager_lists']['applicants'])
        self.assertNotIn('VC가운용', str(result['manager_lists']['shortlist']))

    def test_no_candidate_wrong_year_half_business_or_non_screening_is_noop(self):
        recipe = base_recipe()
        for notices in [[], [notice(title='2025년 하반기 블라인드펀드 서류심사 결과')],
                        [notice(title='2026년 상반기 블라인드펀드 서류심사 결과')],
                        [notice(title='2026년 하반기 다른 공동사업 서류심사 결과')],
                        [notice(title='2026년 하반기 블라인드펀드 최종 선정 결과')]]:
            with self.subTest(titles=[n['title'] for n in notices]):
                self.assertEqual(followup.augment_recipe(recipe, notices, '2026-11-09T15:53:00+09:00'), recipe)

    def test_legacy_text_hash_only_is_insufficient(self):
        n = notice()
        for field in ('attachment_proofs', 'detail_proof'):
            bad = copy.deepcopy(n); del bad[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                followup.augment_recipe(base_recipe(), [bad], n['checked_at'])

    def test_changed_raw_body_title_date_and_attachment_membership_rejected(self):
        n = notice(); url = n['attachments'][0]['url']
        def body(x): x['body'] += ' changed'; x['sha256'] = collector.fingerprint(x)
        def title(x): x['title'] += ' 공고'; x['sha256'] = collector.fingerprint(x)
        def date(x): x['date'] = '2026-10-14'; x['sha256'] = collector.fingerprint(x)
        def label(x): x['attachments'][0]['name'] = '다른파일.pdf'
        def raw_body(x): x['detail_proof']['raw_base64'] = base64.b64encode(b'changed').decode()
        def raw_file(x): x['attachment_proofs'][url]['raw_base64'] = base64.b64encode(b'changed').decode()
        def text(x): x['attachment_proofs'][url]['extracted']['text'] += ' forged'
        for mutate in (body, title, date, label, raw_body, raw_file, text):
            bad = copy.deepcopy(n); mutate(bad)
            with self.subTest(mutate=mutate.__name__), self.assertRaises(ValueError):
                followup.augment_recipe(base_recipe(), [bad], n['checked_at'])

    def test_scoped_unknown_names_counts_duplicates_row_swaps_and_vc_rejected(self):
        text = table_text()
        swapped = text.replace('중형가운용', '__TEMP__').replace('소형가운용', '중형가운용').replace('__TEMP__', '소형가운용')
        cases = [text.replace('[중소·중견 글로벌 성장펀드]', '[다른 글로벌 성장펀드]'),
                 text.replace('[중소·벤처 초혁신 성장펀드]', '[다른 사업]'),
                 text.replace('소형라운용', 'VC가운용'),
                 text.replace('소형라운용', '소형가운용'),
                 text.replace('8개사(중형 4, 소형 4)', '9개사(중형 4, 소형 5)'),
                 text.replace('소형라운용', '새운용사'),
                 text.replace('소형라운용', '소형라운용 추가운용사'),
                 swapped,
                 text.replace('첨단전략 중형 분야', '첨단전략 소형 분야'),
                 text.replace('제안서 심사 결과', '제안서 심사 결과 및 최종 선정 결과'),
                 text.replace('2026년 하반기', '2026년 상반기')]
        for idx, bad_text in enumerate(cases):
            n = notice(bad_text)
            with self.subTest(case=idx), self.assertRaises(ValueError):
                followup.augment_recipe(base_recipe(), [n], n['checked_at'])

    def test_multiple_candidates_future_or_pre_application_date_and_body_mismatch_rejected(self):
        n = notice()
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            followup.augment_recipe(base_recipe(), [n, copy.deepcopy(n)], n['checked_at'])
        for value in [notice(date='2026.09.01'), notice(date='2026.11.10'),
                      notice(body='2026년 상반기 블라인드펀드 서류심사 결과 공지'),
                      notice(body='2026년 하반기 다른 공동사업 서류심사 결과 공지'),
                      notice(title='2026년 하반기 블라인드펀드 서류심사 결과 및 최종 선정 결과')]:
            with self.assertRaises(ValueError): followup.augment_recipe(base_recipe(), [value], n['checked_at'])
        with self.assertRaisesRegex(ValueError, 'timezone'):
            followup.augment_recipe(base_recipe(), [n], '2026-11-09T15:53:00')

    def test_existing_final_selection_or_existing_screening_is_never_replaced(self):
        n = notice()
        for stage in ('selected', 'shortlist'):
            recipe = base_recipe(); recipe['manager_lists'][stage] = {'첨단전략 중형': ['기존 검토 명단']}
            before = copy.deepcopy(recipe)
            self.assertEqual(followup.augment_recipe(recipe, [n], n['checked_at']), before)
        recipe = base_recipe(); recipe['sources'].append({'source_id': '8', 'event': '최종 선정'})
        self.assertEqual(followup.augment_recipe(recipe, [n], n['checked_at']), recipe)

    def test_detail_proof_limits_strict_shape_hash_and_timestamp_fields(self):
        n = notice()
        for field, value in [('kind', 'other'), ('byte_length', True), ('sha256', '0' * 64), ('extra', 'untrusted')]:
            bad = copy.deepcopy(n); bad['detail_proof'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): followup.validate_detail_proof(bad)
        with patch.object(followup, 'MAX_DETAIL_BYTES', 4):
            with self.assertRaisesRegex(ValueError, 'size limit'): followup.validate_detail_proof(n)
        self.assertEqual(followup.validate_detail_proof(n)['body'], n['body'])
        bad = copy.deepcopy(n); bad['attachment_hashes']['https://example.invalid/extra.pdf'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'unverified additional'):
            followup.augment_recipe(base_recipe(), [bad], n['checked_at'])


if __name__ == '__main__':
    unittest.main()
