import base64
import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from services.lp.src import lp_kgrowth_history_attachment_queue as q
from services.lp.src import collect_lp_history_bodies as b
from services.lp.src import discover_lp_history as h
from services.lp.tests.test_discover_lp_history import seed, raw


def fixture(*, limit=3, multiple=False):
    rows = [('6', '801', '공고', '2026-01-01'),
            ('5', '95', '【선정공고】 2025년 펀드 위탁운용사 선정계획 공고', '2025-01-01'),
            ('4', '90', '【선정결과】 2024년 펀드 위탁운용사 선정 결과', '2024-01-01'),
            ('3', '12', '【선정공고】 2023년 펀드 위탁운용사 선정계획 공고', '2023-02-01'),
            ('2', '9', '【선정공고】 2023년 중견기업 펀드 위탁운용사 선정계획 공고', '2023-01-01')]
    history = h.bootstrap(*seed())
    history['receipts'] = [h.receipt(1, raw(rows)), h.receipt(2, raw([('1', '2', '기간 밖', '2022-12-31')]))]
    def fetch(url):
        row = next(r for r in rows if 'idx='+r[1]+'&' in url)
        files = [('Notice3', '위탁운용사 선정 결과.hwp' if row[1] == '90' else '위탁운용사 선정계획 공고문.pdf')]
        if row[1] == '12': files += [('Notice2', '혁신성장 공동기준 미래유망산업 품목.xlsx'), ('Notice1', '위탁운용사 제출서류 및 서식.hwp')]
        if multiple and row[1] == '9': files += [('Notice2', '위탁운용사 선정계획 공고문.hwp')]
        links = ''.join('<li><a href="/down_file.asp?idx='+row[1]+'&amp;SelType='+kind+'"><strong>'+label+'</strong></a></li>' for kind, label in files)
        return ('<html><body><div class="view_info"><p class="tit">'+row[2]+'</p><p class="date">'+row[3]+
                '</p></div><div class="veiw_contents">공식 원문입니다. 세부 공고 및 진행 결과는 첨부자료를 확인하세요.</div>'
                '<ul class="file_list">'+links+'</ul></body></html>').encode('cp949')
    bodies = b.collect(history, None, fetch, limit=limit)
    if bodies['holds']: raise AssertionError(bodies['holds'])
    return history, bodies


class GrowthHistoricalFileQueueTests(unittest.TestCase):
    def test_plan_workflow_uses_trusted_artifacts_without_service_secrets(self):
        root = Path(__file__).resolve().parents[3] / '.github/workflows'
        text = (root / 'plan-lp-history-attachments.yml').read_text()
        self.assertIn('group: lp-program-collection', text)
        self.assertIn("run['conclusion']=='success'", text)
        self.assertNotIn('secrets.', text)
        for producer, artifact in (('discover-lp-history.yml', 'lp-history-listings'),
                                   ('collect-lp-history-bodies.yml', 'lp-history-bodies')):
            self.assertIn('          name: '+artifact, text)
            self.assertIn('          name: '+artifact, (root / producer).read_text())

    def test_partial_bodies_entities_labels_stages_and_distinct_reference_exclusion(self):
        history, bodies = fixture(); before = copy.deepcopy((history, bodies))
        result = q.plan(history, bodies)
        self.assertEqual((history, bodies), before)
        self.assertEqual(result['body_pending'], 1)
        self.assertEqual(result['eligible_files'], 3)
        self.assertEqual([r['source_id'] for r in result['rows']], ['9', '12', '90'])
        self.assertEqual(result['rows'][-1]['stage'], '선정 결과')
        self.assertTrue(all('SelType=Notice3' in r['attachment_url'] for r in result['rows']))
        self.assertEqual({r['reason'] for r in result['excluded']}, {'investment_reference', 'submission_template'})
        self.assertEqual(result['holds'], [])
        self.assertEqual(result['official_http_requests'], 0)
        self.assertFalse(result['pe_approval']); self.assertFalse(result['selected_gp_approval'])

    def test_prefix_receipts_resume_and_appended_later_body_without_manual_ids(self):
        history, partial = fixture()
        row = q.plan(history, partial)['rows'][0]
        completed = [{**row, 'attachment_sha256': 'a'*64}]
        self.assertEqual(q.plan(history, partial, completed)['rows'][0]['source_id'], '12')
        history, full = fixture(limit=4)
        self.assertEqual(q.plan(history, full, completed)['pending_files'], 3)
        for receipts in (completed*2, [{**row, 'source_id': '12', 'attachment_sha256': 'a'*64}],
                         [{**row, 'attachment_sha256': 'bad'}], [None]):
            with self.assertRaises(ValueError): q.plan(history, full, receipts)

    def test_raw_body_label_mutation_and_forged_attachment_list_fail(self):
        history, bodies = fixture()
        first = q.plan(history, bodies)['rows'][0]
        completed = [{**first, 'attachment_sha256': 'a'*64}]
        for change in ('bytes', 'declared_urls', 'raw_label', 'unsupported_link'):
            changed = copy.deepcopy(bodies); n = changed['documents'][0]; proof = n['discovery_provenance']
            if change == 'bytes': proof['detail_response_sha256'] = '0'*64
            elif change == 'declared_urls': n['attachments'].append(n['attachments'][0]+'&extra=1')
            else:
                data = base64.b64decode(proof['detail_response_base64'])
                if change == 'raw_label': data = data.replace('공고문.pdf'.encode('cp949'), '공고문 수정.pdf'.encode('cp949'))
                else: data = data.replace(b'</ul>', b'<li><a href="/reference.pdf">reference.pdf</a></li></ul>')
                proof['detail_response_base64'] = base64.b64encode(data).decode(); proof['detail_response_sha256'] = hashlib.sha256(data).hexdigest()
            with self.subTest(change=change), self.assertRaises(ValueError):
                q.plan(history, changed, completed)

    def test_conflicting_primary_files_hold_the_notice_and_keep_other_work_visible(self):
        history, bodies = fixture(multiple=True)
        result = q.plan(history, bodies)
        self.assertEqual(result['holds'][0]['reason'], 'multiple_primary_files')
        self.assertEqual(result['holds'][0]['candidate_count'], 2)
        self.assertNotIn('9', [r['source_id'] for r in result['rows']])
        self.assertEqual(result['eligible_files'], 2)

    def test_strict_file_url_identity_and_limit(self):
        base = 'https://www.kgrowth.or.kr/down_file.asp?idx=9&SelType=Notice3'
        self.assertEqual(q.validate_url(base, '9'), base)
        for url in (base.replace('https:', 'http:'), base.replace('www.kgrowth.or.kr', 'evil.example'),
                    base.replace('www.kgrowth.or.kr', 'user@www.kgrowth.or.kr'), base+'#fragment',
                    base+'&idx=9', base+'&extra=1', base.replace('idx=9', 'idx=8'),
                    base.replace('Notice3', 'Notice0'), base.replace('Notice3', 'Notice3%0a')):
            with self.subTest(url=url), self.assertRaises(ValueError): q.validate_url(url, '9')
        for limit in (0, 5, True):
            with self.assertRaises(ValueError): q.plan(*fixture(), limit=limit)

    def test_unknown_labels_are_held_and_reference_sheets_are_not_blank_forms(self):
        self.assertEqual(q.label_kind('업종 공동기준.xlsx', '모집 공고'), 'investment_reference')
        self.assertEqual(q.label_kind('관련 설명.pdf', '모집 공고'), 'unconfirmed')
        self.assertEqual(q.label_kind('선정계획 FAQ.hwp', '모집 공고'), 'faq')

    def test_recruitment_words_do_not_promote_templates_or_ambiguous_combined_files(self):
        for label in ('선정 공고문 제안서 양식.hwp', '위탁운용사 선정계획 공고 제안서 양식.hwpx', '공고문 동의서.docx'):
            with self.subTest(label=label):
                self.assertEqual(q.label_kind(label, '모집 공고'), 'submission_template')
        for label in ('선정계획 공고 및 제출서류 및 서식.hwp', '선정계획 공고문 및 주목적 투자분야.pdf'):
            with self.subTest(label=label):
                self.assertEqual(q.label_kind(label, '모집 공고'), 'unconfirmed')


if __name__ == '__main__':
    unittest.main()
