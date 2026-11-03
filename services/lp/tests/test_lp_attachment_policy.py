import copy
import unittest

from services.lp.src.lp_attachment_policy import is_submission_form
from services.lp.src.lp_institution_notice_terms import extract_terms
from services.lp.src.lp_notice_publication import _scope, _texts


class AttachmentPolicyTests(unittest.TestCase):
    def test_decorative_notice_label_does_not_turn_forms_into_offerings(self):
        for name in ('(공고)출자 제안서류 및 서식.hwp', '[공고] 제안서 양식.xlsx',
                     '2-2. 제안서(한글).hwp'):
            self.assertTrue(is_submission_form(name), name)
        for name in ('(공고)상생펀드_공고안.hwp', '공고문 및 제출서류 안내.pdf',
                     '(공고)제안서 요청서.pdf', '기업지원펀드 제안서 요청 공고.hwp'):
            self.assertFalse(is_submission_form(name), name)

    def test_archived_forms_cannot_supply_scope_amount_or_deadline(self):
        url='https://www.ibk.co.kr/common/download.ibk?file=form'
        n={'institution_id':'ibk','source_channel':'institution_board',
           'url':'https://www.ibk.co.kr/cyber/noticeDetailCyber.ibk?srno=900001',
           'title':'출자사업 공고','date':'2026-10-01','body':'사업 계획을 공고합니다.',
           'sha256':'a'*64,'attachments':[{'url':url,'name':'(공고)출자 제안서류 및 서식.hwp'}],
           'attachment_hashes':{url:'b'*64},
           'attachment_texts':{url:'국내 PE 블라인드 펀드. 위탁운용금액: 총 9,000억원. 선정 운용사 수: 9개사. 제출기한: 2026.10.30 15:00'}}
        before=copy.deepcopy(n)
        self.assertEqual(_texts(n),[n['body']])
        self.assertNotEqual(_scope(n),'pe_blind')
        terms=extract_terms(n)
        self.assertNotIn('commitment_amount_krw',terms)
        self.assertNotIn('manager_count',terms)
        self.assertNotIn('deadline',terms)
        self.assertEqual(n,before, 'Archived proof maps must remain untouched')
        n['attachments'][0]['name']='출자사업 공고문.hwp'
        self.assertEqual(len(_texts(n)),2)
        self.assertEqual(extract_terms(n)['commitment_amount_krw'],900_000_000_000)


if __name__ == '__main__':
    unittest.main()
