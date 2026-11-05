import copy
import io
import zipfile
from unittest.mock import patch
import unittest

from services.lp.src.lp_attachment_policy import is_submission_form, is_submission_form_v2
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

    def test_terminal_templates_override_reused_business_title_only(self):
        prefix = '붙임2-2. 『2026 회수시장 지원 세컨더리 펀드』 위탁운용사 선정(재공고) '
        for suffix in ('제출서류 및 서식(엑셀양식).xlsx',
                       '제출서류 및 서식(한글양식).hwp',
                       '제안서류 및 양식(Word).docx'):
            name = prefix + suffix
            self.assertFalse(is_submission_form_v2(name), name)
            self.assertTrue(is_submission_form(name), name)
        for name in ('선정계획 공고 제출서류 및 서식(엑셀양식).xlsx',):
            self.assertTrue(is_submission_form(name))
            self.assertFalse(is_submission_form_v2(name))
        for name in ('공고문 및 제출서류 안내.pdf', '모집요강 및 제출서류.pdf',
                     '공고문 및 제출서류 및 서식.pdf', '모집 공고 및 양식.zip',
                     '선정계획 공고 제안요청서(RFP).hwp',
                     prefix + '제출서류 및 서식 안내.hwp',
                     prefix + '운용자료.xlsx'):
            self.assertFalse(is_submission_form(name), name)
            self.assertEqual(is_submission_form(name), is_submission_form_v2(name))

    def test_rfp_title_does_not_override_actual_template_heading(self):
        from services.lp.src import collect_lp_institution_boards as boards
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            z.writestr('제안요청서(RFP).hwp',b'form')
            z.writestr('별도 엑셀 양식.xlsx',b'xlsx')
        raw=out.getvalue()
        def extract(value):
            return {'format':'zip','text':''} if value==raw else {'format':'hwp','text':'국민연금 펀드 제안서 양식\n[벤처]\n기관전용 PEF 9,000억원 예시'}
        with patch.object(boards,'extract_attachment',side_effect=extract):
            self.assertEqual(boards.attachment_text(raw,'공식 RFP.zip',extraction_version=2),'')
            with self.assertRaisesRegex(ValueError,'no readable labelled'):
                boards.attachment_text(raw,'공식 RFP.zip')
        for version in (True,3):
            with self.assertRaises(ValueError):boards.attachment_text(raw,'RFP.zip',extraction_version=version)

    def test_archived_forms_cannot_supply_scope_amount_or_deadline(self):
        url='https://www.ibk.co.kr/common/download.ibk?file=form'
        n={'institution_id':'ibk','source_channel':'institution_board',
           'url':'https://www.ibk.co.kr/cyber/noticeDetailCyber.ibk?srno=900001',
           'title':'출자사업 공고','date':'2026-10-01','body':'사업 계획을 공고합니다.',
           'sha256':'a'*64,'attachments':[{'url':url,'name':'위탁운용사 선정(재공고) 제출서류 및 서식(한글양식).hwp'}],
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
