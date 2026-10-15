import copy
import unittest
from services.lp.src.collect_lp_original_notices import original_body_hash

from services.lp.src.lp_shared_notice_catalog import update_shared_catalog


def notice():
    return {'url':'https://www.kofia.or.kr/brd/m_212/view.do?seq=999123',
            'source_id':'kofia_212:999123','institution_id':'cu','source_channel':'kofia_212',
            'title':'[신협중앙회] 국내 PEF 블라인드 위탁운용사 선정 공고',
            'date':'2026-10-01','body':'국내 PE 블라인드 공개모집', 'sha256':'a'*64,
            'attachment_hashes':{},'attachment_texts':{}, 'source_provenance':{'reported_issuer':'신협중앙회'}}


class SharedArchiveTests(unittest.TestCase):
    def test_shared_facts_are_reextracted_and_never_trust_prepared_amount(self):
        n=notice();n['body']='국내 PE 블라인드 모집 출자규모: 총 450억원 선정 운용사:1개사 접수 마감:2026.10.12.15:00'
        n['prepared_terms']={'commitment_amount_krw':999999}
        result=update_shared_catalog({}, {'notices':[n]}, '2026-10-14')
        facts=result['shared_offering_terms'][n['url']]
        self.assertEqual(facts['commitment_amount_krw'],45_000_000_000)
        self.assertEqual(result['shared_discovery_candidates'][0]['institution_id'],'cu')
        self.assertNotIn('programs',result)
    def test_inverted_original_dates_are_held_or_marked_as_registration_only(self):
        n=notice();n['source_provenance'].update(claimed_official_date='2026-10-01',application_deadline='2026-09-28',association_registered_at='2026-09-01')
        bad=update_shared_catalog({}, {'notices':[n]}, '2026-10-13')
        self.assertFalse(bad['shared_notices'])
        n['date']='2026-09-01'
        result=update_shared_catalog({}, {'notices':[n]}, '2026-10-13')
        self.assertIn('협회 등록일',result['shared_notices'][0]['date_note'])
        self.assertTrue(result['shared_discovery_candidates'][0]['date_note'])
    def test_prepared_scope_is_not_permission_and_vc_is_not_promoted(self):
        n=notice();n.update(title='[신협중앙회] 국내 VC 모집',body='국내 VC 모집',source_scope='pe_blind')
        result=update_shared_catalog({}, {'notices':[n]}, '2026-10-13')
        self.assertEqual(result['shared_notices'][0]['source_scope'],'vc_only')
        self.assertEqual(result['shared_discovery_candidates'][0]['scope'],'vc_only')

    def test_outage_or_missing_listing_preserves_archive(self):
        first=update_shared_catalog({}, {'notices':[notice()]}, '2026-10-13')
        later=update_shared_catalog(first, {'notices':[], 'holds':[{'stage':'listing','error':'outage'}]}, '2026-10-14')
        self.assertEqual(first['shared_notices'],later['shared_notices'])
        self.assertTrue(later['shared_collection_holds'])
        self.assertEqual(len(later['shared_discovery_candidates']),1)

    def test_invalid_provenance_date_or_issuer_cannot_replace_last_good(self):
        n=notice();first=update_shared_catalog({}, {'notices':[n]}, '2026-10-13')
        for change in ({'sha256':''},{'date':None},{'date':'2026-12-01'},
                       {'institution_id':'kgrowth'}, {'url':'https://api.pe-vc-lp.com/fake?seq=999123'}):
            with self.subTest(change=change):
                result=update_shared_catalog(first, {'notices':[{**n,**change}]}, '2026-10-13')
                self.assertEqual(first['shared_notices'],result['shared_notices'])
                self.assertTrue(result['shared_collection_holds'])

    def test_trusted_old_original_migrates_and_tampered_incoming_keeps_last_good(self):
        n=notice();n.update(institution_id='mmaa',title='2026년 군인공제회 국내 PE 블라인드 선정 공고',body='군인공제회 국내 PE 블라인드 모집')
        n['source_provenance']['reported_issuer']='군인공제회'
        url='https://www.mmaa.or.kr/web/contents/notice.do?schM=view&id=987654'
        n['source_provenance']['original_links']=[{'url':url}]
        original={'institution_id':'mmaa','url':url,'title':n['title'],'body':n['body'],'date':n['date'],
                  'checked_at':'2026-10-14T01:00:00+00:00','sha256':'b'*64,'matched_republication_url':n['url'],
                  'attachments':[],'attachment_hashes':{},'attachment_texts':{}}
        n['original_notices']=[original]
        current={'shared_notices':[n]}
        first=update_shared_catalog(current,{'notices':[]},'2026-10-14T02:00:00+00:00')
        kept=first['shared_notices'][0]['original_notices'][0]
        self.assertEqual(kept['sha256'],original_body_hash(kept))
        self.assertEqual(kept['hash_kind'],'semantic_v1')
        incoming=copy.deepcopy(first['shared_notices'][0])
        incoming['original_notices'][0]['body']+=' 출자규모 999억원'
        second=update_shared_catalog(first,{'notices':[incoming]},'2026-10-14T02:00:00+00:00')
        self.assertEqual(second['shared_notices'][0]['original_notices'],[kept])
        self.assertTrue(second['shared_collection_holds'])
        # An unmarked incoming old-style digest cannot claim the migration path.
        untrusted=update_shared_catalog({}, {'notices':[n]},'2026-10-14T02:00:00+00:00')
        self.assertFalse(untrusted['shared_notices'][0]['original_notices'])

    def test_failed_original_attachment_never_erases_prior_verified_receipt(self):
        n=notice();n.update(institution_id='mmaa',title='2026년 군인공제회 국내 PE 블라인드 선정 공고',body='군인공제회 국내 PE 블라인드 모집')
        n['source_provenance']['reported_issuer']='군인공제회'
        url='https://www.mmaa.or.kr/web/contents/notice.do?schM=view&id=987654';file='https://www.mmaa.or.kr/files/offer.pdf'
        n['source_provenance']['original_links']=[{'url':url}]
        original={'institution_id':'mmaa','url':url,'title':n['title'],'body':n['body'],'date':n['date'],
                  'checked_at':'2026-10-15T01:00:00+00:00','matched_republication_url':n['url'],
                  'attachments':[{'url':file,'name':'모집공고.pdf'}],
                  'attachment_hashes':{file:'c'*64},'attachment_texts':{file:'출자규모: 총 450억원 선정 수:1개사'}}
        original.update(hash_kind='semantic_v1',sha256=original_body_hash(original))
        n['original_notices']=[original]
        first=update_shared_catalog({}, {'notices':[n]}, '2026-10-15T02:00:00+00:00')
        for hashes in ({file:'c'*64},{file:'d'*64},{}):
            incoming=copy.deepcopy(n);incoming['original_notices'][0].update(attachment_hashes=hashes,attachment_texts={})
            result=update_shared_catalog(first,{'notices':[incoming]},'2026-10-15T02:00:00+00:00')
            self.assertEqual(result['shared_notices'][0]['original_notices'],[original])
            self.assertEqual(result['shared_offering_terms'][n['url']]['commitment_amount_krw'],45_000_000_000)
            if hashes!={file:'c'*64}:self.assertTrue(result['shared_collection_holds'])
        incoming=copy.deepcopy(n);updated=incoming['original_notices'][0]
        updated['body']+=' New confirmed source wording';updated.update(sha256=original_body_hash(updated),attachment_texts={})
        result=update_shared_catalog(first,{'notices':[incoming]},'2026-10-15T02:00:00+00:00')
        self.assertEqual(result['shared_notices'][0]['original_notices'],[original])
        self.assertTrue(result['shared_collection_holds'])

    def test_same_attachment_keeps_read_text_but_new_bytes_never_borrow_old(self):
        n=notice();url='https://www.kofia.or.kr/brd/m_212/down.do?seq=999123'
        n.update(title='[신협중앙회] 국내 기업펀드 모집',body='원문 참조',
                 attachment_hashes={url:'same'},attachment_texts={url:'운용방식: 국내 블라인드 PEF 공개모집'})
        first=update_shared_catalog({}, {'notices':[n]}, '2026-10-13')
        empty={**n,'attachment_texts':{}}
        again=update_shared_catalog(first, {'notices':[empty]}, '2026-10-13')
        self.assertEqual(again['shared_notices'][0]['source_scope'],'pe_blind')
        changed={**empty,'attachment_hashes':{url:'changed'}}
        later=update_shared_catalog(first, {'notices':[changed]}, '2026-10-13')
        self.assertEqual(later['shared_notices'][0]['source_scope'],'needs_confirmation')


if __name__=='__main__':unittest.main()
