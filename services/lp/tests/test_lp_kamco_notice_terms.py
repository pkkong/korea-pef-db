import base64
import copy
import hashlib
import unittest
from services.lp.src.lp_kamco_notice_terms import pe_track, terms

TEXT = '''운용사 선정계획 공고
2. 선정계획 개요
운용방식 ▪ 블라인드 펀드
선정방식 ▪ 공개모집
선정 운용사 ▪ 2개사
출자대상 투자기구 ▪ 자본시장법에 의한 기관전용 사모집합투자기구
- 창업 · 벤처전문 사모집합투자기구 제외
접수일시 ▪ 2029년 8월 21일 09:30 ∼ 16:45
선정결과발표 ▪ 2029년 10월 중(예정)
3. 투자대상
□ 주목적 투자대상 및 의무투자비율
구조개선기업에 약정총액의 65% 이상 투자
□ 기타
4. 주요 출자조건
최소결성금액 ▪ 700억원
공사 출자금액 ▪ 410억원
- 조건
아래 기업에 대한 투자 제한(비주목적 투자 포함)
- 외국기업
- 상호출자제한기업
[붙임1] 제안서 양식
공사 출자금액 ▪ 999억원
'''

def notice(text=TEXT):
    url = 'https://www.kamco.or.kr/cmm/fms/FileDown.do?atchFileId=FILE_777&fileSn=0'
    raw = b'test file bytes'
    return {'institution_id':'kamco','url':'https://www.kamco.or.kr/portal/bbs/view.do?bIdx=777',
        'date':'2029-08-01','sha256':'a'*64,'title':'임의 사업 운용사 선정계획 공고',
        'body':'공고문 참고', 'attachments':[{'url':url,'name':'공고.hwp'}],
        'attachment_bytes':{url:base64.b64encode(raw).decode()},
        'attachment_hashes':{url:hashlib.sha256(raw).hexdigest()}, 'attachment_texts':{url:text}}


class KamcoTermsTests(unittest.TestCase):
    def test_labelled_values_and_forms_isolated(self):
        n=notice();before=copy.deepcopy(n);r=terms(n)
        self.assertTrue(pe_track(n));self.assertEqual(n,before)
        self.assertEqual(r['commitment_amount_krw'],41000000000)
        self.assertEqual(r['manager_count'],2)
        self.assertNotIn('per_fund_amount_krw',r)
        self.assertEqual(r['fund_target_label'],'700억원')
        self.assertEqual(r['deadline'],'2029-08-21T16:45:00+09:00')
        self.assertEqual(r['schedule_stages'][0]['date'],'2029-10')
        self.assertEqual(r['schedule_stages'][0]['status'],'planned')
        self.assertIn('65%',r['primary_investment']['text'])
        self.assertTrue(all(e['sha256'] in n['attachment_hashes'].values() for es in r['extraction_evidence'].values() for e in es))
        one=terms(notice(TEXT.replace('2개사','1개사')))
        self.assertEqual(one['per_fund_amount_krw'],41000000000)

    def test_domestic_and_current_offering_required(self):
        for changed in [TEXT.replace('- 외국기업','- 국내에 설립된 운용사'),
                TEXT.replace('투자 제한(비주목적 투자 포함)','투자 허용(비주목적 투자 포함)'),
                TEXT.replace('- 외국기업','- 외국기업 투자 가능'),
                TEXT.replace('블라인드 펀드','프로젝트 펀드'),
                TEXT.replace('블라인드 펀드','대출형 펀드'),
                TEXT.replace('기관전용 사모집합투자기구','벤처투자조합'),
                '[붙임1] 과거 운용실적\n'+TEXT,
                TEXT.replace('운용방식 ▪ 블라인드 펀드','과거운용실적 ▪ 블라인드 펀드')]:
            with self.subTest(text=changed):
                self.assertFalse(pe_track(notice(changed)))
                with self.assertRaises(ValueError):terms(notice(changed))

    def test_binding_ambiguous_and_invalid_values_fail_closed(self):
        n=notice();u=next(iter(n['attachment_hashes']));n['attachment_hashes'][u]='b'*64
        self.assertFalse(pe_track(n))
        n=notice();n['attachments']=[];self.assertFalse(pe_track(n))
        n=notice();n['institution_id']='other';self.assertFalse(pe_track(n))
        for changed in [TEXT.replace('4. 주요 출자조건','공사 출자금액 ▪ 490억원\n4. 주요 출자조건'),
                         TEXT.replace('09:30 ∼ 16:45','17:30 ∼ 16:45'),
                         TEXT.replace('2개사','0개사'),TEXT.replace('700억원','100억원')]:
            with self.assertRaises(ValueError):terms(notice(changed))
        self.assertNotIn('commitment_amount_krw',terms(notice(TEXT.replace('410억원','410억원 이내'))))

    def test_purpose_display_keeps_mandates_without_limits_or_definitions(self):
        source=TEXT.replace('구조개선기업에 약정총액의 65% 이상 투자',
            '1. 구조개선기업에 약정총액의 65% 이상 투자\n'
            '2. 사후적 구조조정 기업에 약정총액의 35% 이상 투자\n'
            '3. 건별 투자한도는 최소결성금액의 25% 이내로 투자\n'
            '* 구조개선기업 : 별도 법적 정의')
        r=terms(notice(source))
        self.assertEqual(r['primary_investment']['text'],
            '구조개선기업에 약정총액의 65% 이상 투자; 사후적 구조조정 기업에 약정총액의 35% 이상 투자')
        self.assertIn('법적 정의',r['extraction_evidence']['primary_investment'][0]['quote'])
        for changed in [source.replace('65%','101%'),source.replace('65%','0%'),
                        source.replace('사후적 구조조정 기업','구조개선기업')]:
            with self.assertRaises(ValueError):terms(notice(changed))

    def test_other_fund_titles_cannot_borrow_pe_attachment(self):
        for title in ['PF사업장 정상화 지원펀드','구조조정 부동산펀드','대출형 펀드','프로젝트 펀드','VC 펀드']:
            n=notice();n['title']=title
            self.assertFalse(pe_track(n))


if __name__=='__main__':unittest.main()
