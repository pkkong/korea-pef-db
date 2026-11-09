import base64
import copy
import hashlib
import html
import unittest
from unittest.mock import patch

from services.lp.src import collect_koreapost_program as collector
from services.lp.src import koreapost_coinvestment_preferred as a
from services.lp.src.lp_attachment_text import extract_attachment
from services.lp.tests.test_kexim_followup import pdf

STAMP = '2026-05-01T00:00:00+09:00'
FAMILY = '우체국예금 국내 공동투자 전략 펀드'
RECRUITMENT_TITLE = '2026년도 ' + FAMILY + ' 위탁운용사 선정 공고(우정사업본부 공고 2026-12호)'
PREFERRED_TITLE = FAMILY + ' 위탁운용사 선정 우선협상대상자 선정 안내'
PDF_TEXT = ('2026년도 ' + FAMILY + ' 위탁운용사 선정 공고\n'
            '투자전략 우정사업본부가 제공하는 국내 공동투자건에 대하여 펀드 약정액의 100% 투자\n'
            '운용방식 블라인드형\n'
            '투자기구 기관전용 사모집합투자기구\n'
            '※ 창업·벤처전문 사모집합투자기구 제외\n'
            '대체투자 목적 투자신탁 가능\n'
            '공동 운용사(Co-GP) 제안 금지\n'
            '선정 운용사 수 총 1개 운용사')


def preferred_body(name='가나다프라이빗에쿼티'):
    return ('ㅇ ' + FAMILY + ' 위탁운용사 우선협상대상자 선정 결과를 다음과 같이 안내드립니다.\n'
            '- 선정 운용사 : ' + name + '\n'
            '- 운용사 실사 및 투자심의회를 거쳐 최종 선정 예정\n'
            'ㅇ 지원해주신 운용사 및 모든 관계자분들께 깊이 감사드립니다.')


def file_url(number='8'):
    return (a.BASE + '/download.es?filename=1234567890.pdf&filenameOrg=notice.pdf&f_path=board'
            '&bid=0041&type=board&bid=0041&list_no=' + number + '&seq=1')


def detail(number, title, date, body, attachments=()):
    raw = ('<p class="title">' + html.escape(title) + '</p><th>작성일시</th><td>' + date + '</td>'
           '<td colspan="4" class="tb_contents">'
           + ''.join('<p>' + html.escape(line) + '</p>' for line in body.splitlines()) + '</td>'
           + ''.join('<a href="' + html.escape(url, quote=True) + '">첨부파일</a>' for url in attachments)).encode()
    notice = collector._detail(number, raw)
    notice['detail_proof'] = {'kind': a.DETAIL_KIND, 'raw_base64': base64.b64encode(raw).decode(),
                              'byte_length': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    return notice


def evidence(*, text=PDF_TEXT, title=RECRUITMENT_TITLE, body=None, preferred_title=PREFERRED_TITLE,
             preferred_date='2026-04-21', preferred_text=None, url=None):
    url = url or file_url()
    source = detail('8', title, '2026-03-23', body or ('2026년도 ' + FAMILY + ' 위탁운용사 선정계획을 공고합니다.'), [url])
    raw = pdf(text)
    digest = hashlib.sha256(raw).hexdigest()
    source['attachment_hashes'] = {url: digest}
    source['attachment_texts'] = {url: 'legacy extraction may differ in whitespace'}
    source['attachment_proofs'] = {url: {'kind': a.FILE_KIND, 'raw_base64': base64.b64encode(raw).decode(),
                                       'sha256': digest, 'byte_length': len(raw), 'pdf_reader_version': '6.10.0',
                                       'extracted': extract_attachment(raw)}}
    preferred = detail('9', preferred_title, preferred_date, preferred_text or preferred_body())
    preferred['attachment_hashes'] = {}; preferred['attachment_texts'] = {}
    return source, preferred


class CoinvestmentPreferredTests(unittest.TestCase):
    def test_full_raw_html_and_pdf_replay_one_preferred_not_final(self):
        source, preferred = evidence(); before = copy.deepcopy((source, preferred))
        with patch.object(collector, '_get', side_effect=AssertionError('No HTTP')):
            result = a.extract_preferred(source, preferred, checked_at=STAMP)
        self.assertEqual(result, {'event': {'type': '우선협상대상자', 'date': preferred['date'],
                                         'title': preferred['title'], 'url': preferred['url']},
                                  'rosters': [{'league': '국내 공동투자 전략', 'names': ['가나다프라이빗에쿼티'],
                                               'source_url': preferred['url'], 'source_sha256': preferred['sha256']}],
                                  'preferred_gps': ['가나다프라이빗에쿼티'], 'source_url': preferred['url']})
        self.assertNotIn('selected_gps', result); self.assertNotIn('commitment_amount_krw', result)
        self.assertEqual((source, preferred), before)
        self.assertNotRegex(preferred['title'], r'20[0-9]{2}')

    def test_missing_proofs_old_text_only_and_raw_metadata_tamper_fail(self):
        original = evidence(); url = original[0]['attachments'][0]
        for change in ('source_detail', 'preferred_detail', 'file', 'file_raw', 'file_sha', 'canonical', 'body', 'title', 'date', 'name', 'source_id', 'extra_proof'):
            source, preferred = copy.deepcopy(original)
            if change == 'source_detail': del source['detail_proof']
            elif change == 'preferred_detail': del preferred['detail_proof']
            elif change == 'file': del source['attachment_proofs']
            elif change == 'file_raw': source['attachment_proofs'][url]['raw_base64'] = base64.b64encode(b'changed').decode()
            elif change == 'file_sha': source['attachment_hashes'][url] = '0' * 64
            elif change == 'canonical': source['attachment_proofs'][url]['extracted']['text'] += 'forged'
            elif change == 'body': preferred['body'] += 'changed'; preferred['sha256'] = collector._fingerprint(preferred)
            elif change == 'title': preferred['title'] += 'changed'; preferred['sha256'] = collector._fingerprint(preferred)
            elif change == 'date': preferred['date'] = '2026-04-20'; preferred['sha256'] = collector._fingerprint(preferred)
            elif change == 'name': source['attachments'][0] += '&seq=2'
            elif change == 'source_id': preferred['source_id'] = '0041:10'
            else: preferred['detail_proof']['approval'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                a.extract_preferred(source, preferred, checked_at=STAMP)

    def test_exact_source_urls_download_queries_and_safe_duplicate_bid(self):
        good = file_url()
        urls = [good.replace('https:', 'http:'), good.replace('www.kpasset.go.kr', 'www.kpasset.go.kr:443'),
                good.replace('www.kpasset.go.kr', 'user@www.kpasset.go.kr'), good + '#fragment',
                good + '\r\n', good + '&seq=1', good + '&unknown=1', good.replace('list_no=8', 'list_no=9'),
                good.replace('&bid=0041&type', '&bid=0042&type'), good.replace('filename=', 'filename=%'),
                good.replace('filenameOrg=notice.pdf', 'filenameOrg=notice%0a.pdf'),
                good.replace('f_path=board', 'f_path=other')]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError): a._download_url(url, '0041:8')
        self.assertEqual(a._download_url(good, '0041:8'), good)
        single = good.replace('&bid=0041&type=board&bid=0041', '&bid=0041&type=board')
        self.assertEqual(a._download_url(single, '0041:8'), single)
        source, preferred = evidence()
        for url in (preferred['url'] + '&bid=0041', preferred['url'] + '\n', preferred['url'].replace('https:', 'http:')):
            bad = copy.deepcopy(preferred); bad['url'] = url
            with self.assertRaises(ValueError): a.extract_preferred(source, bad, checked_at=STAMP)

    def test_wrong_family_year_phase_future_and_pending_approval_are_rejected(self):
        cases = [dict(preferred_title=PREFERRED_TITLE.replace('국내', '해외')),
                 dict(preferred_title=PREFERRED_TITLE.replace('우선협상대상자', '최종')),
                 dict(preferred_title='2025년도 ' + PREFERRED_TITLE),
                 dict(preferred_date='2025-04-21'), dict(preferred_date='2026-03-20'), dict(preferred_date='2026-05-02'),
                 dict(preferred_text=preferred_body().replace('최종 선정 예정', '최종 선정 완료')),
                 dict(preferred_text=preferred_body().replace('투자심의회', '협의')),
                 dict(preferred_text=preferred_body().replace('국내 공동투자', '국내 다른투자')),
                 dict(title=RECRUITMENT_TITLE.replace('2026년도', '2025년도'))]
        for kwargs in cases:
            source, preferred = evidence(**kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                a.extract_preferred(source, preferred, checked_at=STAMP)
        source, preferred = evidence()
        with self.assertRaisesRegex(ValueError, 'timezone'): a.extract_preferred(source, preferred, checked_at='2026-05-01T00:00:00')
        # KST date, not the UTC calendar date, controls future notices.
        result = a.extract_preferred(source, preferred, checked_at='2026-04-20T15:00:00+00:00')
        self.assertEqual(result['event']['date'], '2026-04-21')

    def test_pdf_scope_single_manager_and_same_business_are_required(self):
        for text in (PDF_TEXT.replace('블라인드형', '프로젝트형'),
                     PDF_TEXT.replace('국내 공동투자건', '해외 공동투자건'),
                     PDF_TEXT.replace('펀드 약정액의 100%', '펀드 약정액의 10%'),
                     PDF_TEXT.replace('기관전용 사모집합투자기구', '벤처투자조합'),
                     PDF_TEXT.replace('창업·벤처전문 사모집합투자기구 제외', '창업·벤처전문 사모집합투자기구 가능'),
                     PDF_TEXT.replace('Co-GP) 제안 금지', 'Co-GP) 제안 가능'),
                     PDF_TEXT.replace('총 1개 운용사', '총 2개 운용사'),
                     PDF_TEXT.replace('국내 공동투자', '해외 공동투자'),
                     PDF_TEXT.replace('2026년도', '2025년도')):
            source, preferred = evidence(text=text)
            with self.subTest(text=text), self.assertRaises(ValueError): a.extract_preferred(source, preferred, checked_at=STAMP)

    def test_multiple_or_unparsed_names_attachments_and_protection_fail_closed(self):
        for name in ('가운용, 나운용', '가운용-나운용', '가운용 및 나운용', '가운용 외 1개사', '가운용/나운용'):
            source, preferred = evidence(preferred_text=preferred_body(name))
            with self.subTest(name=name), self.assertRaises(ValueError): a.extract_preferred(source, preferred, checked_at=STAMP)
        for body in (preferred_body() + '\n- 선정 운용사 : 두번째운용', preferred_body() + '\n- 두번째운용',
                     preferred_body() + '\n조건부 선정', preferred_body() + '\n로그인이 필요합니다'):
            source, preferred = evidence(preferred_text=body)
            with self.assertRaises(ValueError): a.extract_preferred(source, preferred, checked_at=STAMP)
        source, preferred = evidence()
        for flags in ({'status': ' PRIVATE '}, {'restricted': True}, {'attachment_read_error': 'failed'}, {'attachment_proofs': {'unexpected': {}}}):
            bad = {**copy.deepcopy(preferred), **flags}
            with self.subTest(flags=flags), self.assertRaises(ValueError): a.extract_preferred(source, bad, checked_at=STAMP)
        source, preferred = evidence(body='2026년도 ' + FAMILY + ' 선정계획 공고. 로그인이 필요합니다.')
        with self.assertRaisesRegex(ValueError, 'Protected'): a.extract_preferred(source, preferred, checked_at=STAMP)

    def test_proof_size_encoding_and_pdf_reader_version_limits(self):
        source, preferred = evidence(); url = source['attachments'][0]
        with patch.object(a, 'MAX_DETAIL_BYTES', 4), self.assertRaises(ValueError): a.extract_preferred(source, preferred, checked_at=STAMP)
        with patch.object(a, 'MAX_FILE_BYTES', 4), self.assertRaises(ValueError): a.extract_preferred(source, preferred, checked_at=STAMP)
        for field, value in [('byte_length', True), ('raw_base64', '%%%'), ('pdf_reader_version', 'other'), ('kind', 'other')]:
            bad = copy.deepcopy(source); bad['attachment_proofs'][url][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): a.extract_preferred(bad, preferred, checked_at=STAMP)


if __name__ == '__main__':
    unittest.main()
