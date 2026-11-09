"""A retained diagnostic cannot silently replace source identity or public facts."""
import base64
import copy
import hashlib
import unittest
from unittest.mock import patch

from services.lp.src import collect_kexim_programs as k
from services.lp.src import reuse_kexim_stage_evidence as reuse


class ReuseKeximStageEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.raw = b'%PDF retained screening bytes'
        self.body = b'''<h1 class="detail-view-title">2026 screening</h1>
        <span title="\xec\x9e\x91\xec\x84\xb1\xec\x9d\xbc">2026.10.13</span>
        <div class="detail-view-box">screening</div>
        <div class="detail-view-file"><a href="/comm/getFile?upperNo=909&fileNo=1">screening.pdf</a></div>'''
        self.notice = k.parse_detail('909', self.body)
        k.retain_detail_proof(self.notice, self.body)
        url = self.notice['attachments'][0]['url']
        self.notice['attachment_hashes'] = {url: hashlib.sha256(self.raw).hexdigest()}
        old = copy.deepcopy(self.notice)
        del old['detail_proof']
        self.source = {'checked_at': '2026-11-09T06:53:02Z', 'notices': [old], 'holds': ['old hold']}
        self.notice['attachment_proofs'] = {url: {'raw_base64': base64.b64encode(self.raw).decode()}}
        self.recipe = {'id': 'existing-pe', 'sources': []}
        self.other = {'id': 'other', 'selected_gps': [{'name': 'Preserved GP'}]}
        self.target = {'id': 'existing-pe', 'shortlisted_gps': ['A'], 'selected_gps': [], 'status': '서류심사 결과'}
        self.stack = []
        for name, kwargs in (
            ('_approved_source_ids', {'return_value': set()}),
            ('_stage', {'return_value': '서류심사 결과'}),
            ('_recipes', {'return_value': [self.recipe]}),
            ('_title_matches', {'return_value': True}),
            ('validate_attachment_proof', {'return_value': {'format': 'pdf'}}),
            ('project', {'side_effect': [([self.other], []), ([self.other, self.target], [])]}),
            ('link_suggestions', {'return_value': []}),
            ('discovery_candidates', {'return_value': []}),
        ):
            item = patch.object(k, name, **kwargs); item.start(); self.stack.append(item)
        item = patch.object(reuse, 'augment_recipe', return_value={'sources': [{'source_id': '909'}]})
        item.start(); self.stack.append(item)
        self.addCleanup(lambda: [p.stop() for p in reversed(self.stack)])

    def run_reuse(self):
        return reuse.reuse_stage_evidence(self.source, self.notice, self.body, self.raw)

    def test_only_same_source_proof_is_upgraded_without_mutating_input(self):
        original = copy.deepcopy(self.source)
        result, receipt = self.run_reuse()
        self.assertEqual(self.source, original)
        self.assertEqual(result['notices'][0], self.notice)
        self.assertEqual(result['programs'][0], self.other)
        self.assertEqual(receipt['official_http_requests'], 0)
        self.assertEqual(receipt['selected_gp_additions'], 0)

    def test_changed_collected_identity_or_hash_is_held(self):
        for field in ('date', 'title', 'body', 'url', 'attachment_hashes', 'attachments', 'sha256'):
            with self.subTest(field=field):
                original = copy.deepcopy(self.notice[field]); self.notice[field] = 'changed'
                with self.assertRaises(ValueError): self.run_reuse()
                self.notice[field] = original

    def test_actual_detail_bytes_required(self):
        self.body = self.body.replace(b'screening</div>', b'changed</div>')
        with self.assertRaises(ValueError): self.run_reuse()

    def test_raw_detail_proof_cannot_be_substituted(self):
        self.notice['detail_proof']['raw_base64'] = base64.b64encode(b'other response').decode()
        with self.assertRaises(ValueError): self.run_reuse()

    def test_actual_attachment_bytes_required(self):
        self.raw += b'changed'
        with self.assertRaises(ValueError): self.run_reuse()

    def test_final_or_unreadable_file_never_reuses(self):
        k._stage.return_value = '최종 선정'
        with self.assertRaises(ValueError): self.run_reuse()
        k._stage.return_value = '서류심사 결과'
        k.validate_attachment_proof.return_value = None
        with self.assertRaises(ValueError): self.run_reuse()

    def test_failed_source_or_duplicate_identity_is_held(self):
        self.source['error'] = 'failed'
        with self.assertRaises(ValueError): self.run_reuse()
        del self.source['error']
        self.source['notices'] *= 2
        with self.assertRaises(ValueError): self.run_reuse()

    def test_unrelated_selected_history_cannot_change(self):
        k.project.side_effect = [([self.other], []), ([{'id': 'other'}, self.target], [])]
        with self.assertRaises(ValueError): self.run_reuse()

    def test_target_cannot_gain_final_selection(self):
        self.target['selected_gps'] = [{'name': 'A'}]
        with self.assertRaises(ValueError): self.run_reuse()

    def test_ambiguous_or_unaccepted_business_is_held(self):
        k._recipes.return_value *= 2
        with self.assertRaises(ValueError): self.run_reuse()
        k._recipes.return_value = [self.recipe]
        reuse.augment_recipe.return_value = {'sources': []}
        with self.assertRaises(ValueError): self.run_reuse()


if __name__ == '__main__':
    unittest.main()
