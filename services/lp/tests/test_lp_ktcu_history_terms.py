import base64
import copy
import hashlib
import unittest
from unittest.mock import patch

from services.lp.src import lp_ktcu_history_terms as terms
from services.lp.src.collect_ktcu_program import parse_notice

TEXT = '''2025년 한국교직원공제회
블라인드 PEF 위탁운용사 선정 공고문
본회 출자 규모 • 총 7,000억원 이내
선정 운용사 수 • 총 10개 사 이내
펀드 운용방식 • 블라인드형
투자기구 • 기관전용 사모집합투자기구(PEF)
선정 운용사 수 • 총 10개 사 이내
운용조건 • 펀드 규모의 70% 이상을 국내 소재 기업에 투자
선정 일정
3월 21일 블라인드 PEF 위탁운용사 선정 공고 본회 홈페이지 공고
4월 4일 제안서 접수 마감 직접 제출 등
4월 초 ~ 4월 중 1차 심사 및 2차 심사 대상 선정 대상자 개별 통보
4월 말 현장 실사 및 2차 심사
5월 중 위탁운용사 최종 선정 개별 통보
※ 상기 일정은 변동될 수 있음
접수 마감 : 4월 4일 15시까지 제출
'''


def notice():
    return {'title': '2025년 한국교직원공제회 블라인드 PEF 위탁운용사 선정 공고',
        'date': '2025-03-21', 'url': 'https://www.ktcu.or.kr/PPW-CSB-000101/123',
        'institution_id': 'ktcu'}


class KtcuHistoricalTermsTests(unittest.TestCase):
    def test_budget_count_closing_and_coarse_plans_keep_evidence_and_limits(self):
        n = notice(); result = terms.parse_offering(n, TEXT, n['url'], 'a'*64)
        self.assertEqual(result['commitment_amount_krw'], 700_000_000_000)
        self.assertEqual(result['commitment_label'], '7,000억원 이내')
        self.assertEqual(result['manager_count_label'], '10개사 이내')
        self.assertEqual(result['deadline'], '2025-04-04T15:00:00+09:00')
        self.assertEqual([s['date_label'] for s in result['planned_schedule']],
            ['2025년 4월 초 ~ 4월 중', '2025년 4월 말', '2025년 5월 중'])
        self.assertTrue(all(s['status'] == 'planned' and s['precision'] == 'period' for s in result['planned_schedule']))
        self.assertEqual(result['primary_investment']['text'], '펀드 규모의 70% 이상을 국내 소재 기업에 투자')
        self.assertNotIn('selected_gps', result)
        self.assertNotIn('per_fund_amount_krw', result)

    def test_year_is_anchored_by_document_and_announcement_not_notice_ids(self):
        n = notice(); n.update(date='2024-03-21', title=n['title'].replace('2025', '2024'),
                              url=n['url'].replace('/123', '/987'))
        result = terms.parse_offering(n, TEXT.replace('2025', '2024'), n['url'], 'b'*64)
        self.assertTrue(result['deadline'].startswith('2024-04-04'))
        for text in [TEXT, TEXT.replace('3월 21일', '3월 22일').replace('2025', '2024')]:
            with self.assertRaises(ValueError): terms.parse_offering(n, text, n['url'], 'b'*64)

    def test_conflicts_missing_domestic_mandate_and_reversed_plans_are_held(self):
        for text in [TEXT+'선정 운용사 수 총 8개 사 이내',
                     TEXT.replace('접수 마감 : 4월 4일', '접수 마감 : 4월 5일'),
                     TEXT.replace('4월 초 ~ 4월 중', '4월 말 ~ 4월 초'),
                     TEXT.replace('펀드 규모의 70% 이상을 국내 소재 기업에 투자', '사무소 소재지가 국내인 운용사'),
                     TEXT.replace('7,000억원', '7,00억원')]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                terms.parse_offering(notice(), text, notice()['url'], 'a'*64)

    def test_original_detail_and_file_proofs_must_match_before_text_is_used(self):
        url = '/comm/getFile?srvcId=BBSTY1&upperNo=YWJjZA%3d%3d&fileTy=ATTACH&fileNo=ZWZnaA%3d%3d'
        raw = ('<html><body><div class="notice-cont"><p>공식 모집 공고의 제안서 접수 및 첨부 조건에 대한 상세 안내입니다.</p></div>'
               '<div class="notice-tit"><h3>'+notice()['title']+'</h3><span class="date">2025-03-21</span></div>'
               '<a href="'+url+'">공고문.hwp</a></body></html>').encode()
        n = {**parse_notice('123', raw), 'institution_id': 'ktcu'}
        file = b'file-reader-fixture'; digest = hashlib.sha256(file).hexdigest(); attachment = n['attachments'][0]['url']
        extracted = {'format': 'hwp', 'text': TEXT}
        n.update(attachment_hashes={attachment: digest}, attachment_texts={attachment: TEXT}, discovery_provenance={
            'kind': 'lp_history_attachment', 'detail_response_base64': base64.b64encode(raw).decode(),
            'detail_response_sha256': hashlib.sha256(raw).hexdigest(), 'attachment_evidence': {
                'institution_id': 'ktcu', 'source_id': '123', 'source_url': n['url'], 'body_sha256': n['sha256'],
                'attachment_url': attachment, 'attachment_name': '공고문.hwp',
                'raw_base64': base64.b64encode(file).decode(), 'attachment_sha256': digest, 'extracted': extracted}})
        with patch.object(terms, 'read_attachment', return_value=extracted):
            self.assertEqual(terms.extract_offering(n)['manager_count'], 10)
            for change in [lambda x: x.update(body=x['body']+'변조'),
                           lambda x: x['attachment_texts'].update({attachment: TEXT+'변조'}),
                           lambda x: x['discovery_provenance'].update(detail_response_sha256='0'*64)]:
                altered = copy.deepcopy(n); change(altered)
                with self.assertRaises(ValueError): terms.extract_offering(altered)


if __name__ == '__main__': unittest.main()
