import copy
import unittest
from services.lp.src import discover_lp_history as history
from services.lp.src import lp_history_body_queue as queue
from services.lp.tests.test_discover_lp_history import seed, raw


def state():
    s=history.bootstrap(*seed())
    s['receipts']=[history.receipt(1,raw([('6','801','공고','2026-01-01'),
        ('5','95','새 공고','2025-01-01'),('4','90','중간 공고','2024-01-01'),
        ('3','12','옛 공고','2023-01-01'),('2','9','다른 공고','2023-01-01')])),
        history.receipt(2,raw([('1','2','기간 밖','2022-12-31')]))]
    return s


def doc(ident='9',title='다른 공고',day='2023-01-01',body='공식 본문'):
    n={'source_id':ident,'url':queue.canonical_url(ident),'title':title,'date':day,'body':body}
    n['sha256']=queue.fingerprint(n);return n


class BodyQueueTests(unittest.TestCase):
    def test_sorted_capped_retained_and_immutable(self):
        s=state();before=copy.deepcopy(s)
        result=queue.plan(s,limit=2)
        self.assertEqual([n['source_id'] for n in result['rows']],['9','12'])
        self.assertEqual(result['pending_count'],4)
        self.assertEqual(result['retained_body_observed'],1)
        self.assertEqual(result['attachment_completion'],'not_assessed')
        self.assertFalse(result['source_history_complete'])
        self.assertEqual(s,before)
    def test_completed_and_identical_duplicates_skip_once(self):
        n=doc(title='다른  공고');before=copy.deepcopy(n)
        result=queue.plan(state(),[n,n])
        self.assertEqual(result['pending_count'],3)
        self.assertEqual(result['validated_body_completed'],1)
        self.assertEqual(result['new_validated_body_completed'],1)
        self.assertEqual(n,before)
        n2=doc(body='변경된 본문')
        with self.assertRaises(ValueError):queue.plan(state(),[n,n2])
    def test_zero_width_space_in_listing_title_matches_detail_title(self):
        # Korea Growth idx 855: the list shows '」\u200b 위탁', the detail page '」 위탁'.
        s=state()
        s['receipts'][0]=history.receipt(1,raw([('6','801','공고','2026-01-01'),
            ('5','95','새 공고','2025-01-01'),('4','90','중간 공고','2024-01-01'),
            ('3','12','옛 공고','2023-01-01'),('2','9','「다른」&#8203; 공고','2023-01-01')]))
        result=queue.plan(s,[doc(title='「다른」 공고')])
        self.assertEqual(result['validated_body_completed'],1)
    def test_invalid_completion_never_silently_skipped(self):
        for change in ({'url':'https://evil.test/'},{'source_id':'777'}, {'body':''},
                       {'sha256':'a'*64},{'date':'2024-01-01'},{'title':'다른 사업'},
                       {'restricted':True},{'owner_closed':True},{'reason':'owner_closed'},
                       {'institution_id':'other'},{'source_id':True}):
            n=doc();n.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):queue.plan(state(),[n])
    def test_exact_submission_category_is_listing_only(self):
        s=state()
        s['receipts'][0]=history.receipt(1,raw([
            ('6','801','공고','2026-01-01'),
            ('5','95','【제출서식】 펀드 제안서','2025-01-01'),
            ('4','90','모집 공고 및 제출서식','2024-01-01'),
            ('3','12','모집 【제출서식】 안내','2023-01-01'),
            ('2','9','제출서식 관련 공고','2023-01-01')]))
        before=copy.deepcopy(s)
        original_rows=history.summary(s)['rows']
        result=queue.plan(s)
        self.assertEqual(result['submission_forms_listing_only'],1)
        self.assertEqual(result['body_rows_in_scope'],4)
        self.assertEqual(result['pending_count'],3)
        self.assertEqual([r['source_id'] for r in result['rows']],['9','12','90'])
        self.assertEqual(history.summary(s)['rows'],original_rows)
        self.assertEqual(s,before)

    def test_limit_and_listing_proof_required(self):
        for limit in (0,5,True):
            with self.assertRaises(ValueError):queue.plan(state(),limit=limit)
        s=history.bootstrap(*seed())
        with self.assertRaises(ValueError):queue.plan(s)
        s=state();s['receipts'][0]['sha256']='0'*64
        with self.assertRaises(ValueError):queue.plan(s)
        s=state();s['holds']=[{'reason':'blocked'}]
        with self.assertRaises(ValueError):queue.plan(s)


if __name__=='__main__':unittest.main()
