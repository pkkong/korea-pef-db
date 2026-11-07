import base64
import copy
import io
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from services.lp.src import collect_lp_history_attachments as a
from services.lp.src import collect_lp_history_bodies as b
from services.lp.src import discover_ktcu_history as k
from services.lp.src import lp_history_sources as sources
from services.lp.tests.test_collect_ktcu_program import listing
from services.lp.tests.test_collect_lp_history_bodies import Connection


def fixture():
    history = k.initial('2026-11-07')
    rows = [('92', '2025년 블라인드 PEF 위탁운용사 선정 공고', '2025-03-21', '2'),
            ('91', '2023년 PEF 블라인드 펀드 위탁운용사 선정 공고', '2023-08-11', '1')]
    for term in k.SEARCH_TERMS:
        history['searches'][term] = [k.receipt(term, 1, listing(rows, term=term).encode())]
    history['retained_records'] = []
    def fetch(url):
        row = next(r for r in rows if url == sources.canonical_url(r[0], 'ktcu'))
        href = '/comm/getFile?srvcId=BBSTY1&amp;fileTy=ATTACH&amp;upperNo=abc&amp;fileNo=' + row[0]
        return (f'<html><body><div class="notice-tit"><h3>{row[1]}</h3><span class="date">{row[2]}</span></div>'
                '<div class="notice-cont">공식 출자사업의 원본 공고문을 첨부합니다. 이 자료만으로 국내 PE 범위나 선정사를 추정하지 않습니다.</div>'
                f'<a href="{href}">선정 공고문.hwpx</a><a href="{href}">제안서 양식.hwp</a></body></html>').encode()
    bodies = b.collect(history, None, fetch)
    if bodies['holds']:
        raise AssertionError(bodies['holds'])
    return history, bodies


def attachment(text='공식 출자사업 공고문 원본 본문입니다.'):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('Contents/section0.xml', '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"><hs:p><hs:run><hs:t>' + text + '</hs:t></hs:run></hs:p></hs:sec>')
    return output.getvalue()


class AttachmentEvidenceTests(unittest.TestCase):
    def test_attachment_consumer_matches_real_listing_and_body_artifact_names(self):
        root = Path(__file__).resolve().parents[3] / '.github/workflows'
        workflow = (root / 'collect-lp-history-attachments.yml').read_text()
        for producer, name in ((sources.listing_source('ktcu')['workflow'], sources.listing_source('ktcu')['artifact']),
                               ('collect-lp-history-bodies.yml', 'lp-history-bodies')):
            self.assertIn('          name: ' + name, (root / producer).read_text())
            self.assertIn('          name: ' + name, workflow)
        self.assertIn('group: lp-program-collection', workflow)
        self.assertIn('if: always()', workflow)

    def test_saved_raw_replay_private_append_and_resume_without_http(self):
        h, bodies = fixture()
        original = copy.deepcopy((h, bodies))
        calls = []
        report = a.collect(h, bodies, None, lambda u: calls.append(u) or attachment())
        self.assertEqual(len(calls), 2)
        self.assertTrue(all('/comm/getFile?' in u for u in calls))
        self.assertEqual(a.validate_report(h, bodies, report)['pending_count'], 0)
        self.assertEqual((h, bodies), original)
        conn = Connection()
        first = a.persist(conn, h, bodies, report, wrap_json=lambda x: x)
        again = a.persist(conn, h, bodies, report, wrap_json=lambda x: x)
        self.assertEqual((first['new_document_versions'], again['new_document_versions']), (2, 0))
        self.assertFalse(first['published']); self.assertFalse(first['pe_approval'])
        self.assertEqual(first['before'], first['after'])
        docs = list(conn.documents.values())
        self.assertTrue(all(n['discovery_provenance']['kind'] == 'lp_history_attachment' for n in docs))
        self.assertTrue(all(n['attachment_collection_status'] == 'announcement_only' for n in docs))
        resumed = a.collect(h, bodies, report, lambda u: self.fail('repeat HTTP'))
        self.assertEqual(resumed['batches'][-1]['attachment_requests'], 0)
        self.assertEqual(a.persist(conn, h, bodies, resumed, wrap_json=lambda x: x)['new_document_versions'], 0)

    def test_tampered_text_bytes_source_or_manual_id_fail_before_retention(self):
        h, bodies = fixture()
        r = a.collect(h, bodies, None, lambda u: attachment())
        for field in ('text', 'hash', 'bytes', 'source', 'order', 'extra'):
            bad = copy.deepcopy(r)
            record = bad['records'][0]
            if field == 'text': record['extracted']['text'] = 'changed'
            elif field == 'hash': record['attachment_sha256'] = 'f' * 64
            elif field == 'bytes': record['raw_base64'] = base64.b64encode(attachment('다른 자료')).decode()
            elif field == 'source': record['source_url'] = 'https://evil.example/'
            elif field == 'order': bad['records'].reverse()
            else: record['selected_gps'] = ['invented']
            with self.subTest(field=field), self.assertRaises(ValueError):
                a.persist(Connection(), h, bodies, bad, wrap_json=lambda x: x)
        bad = copy.deepcopy(r); bad['batches'][-1]['planned_ids'] = ['91']
        with self.assertRaises(ValueError): a.persist(Connection(), h, bodies, bad, wrap_json=lambda x: x)
        conn = Connection(); conn.change_public = True
        with self.assertRaisesRegex(ValueError, 'Public state'):
            a.persist(conn, h, bodies, r, wrap_json=lambda x: x)

    def test_failure_preserves_prior_evidence_blocks_resume_and_db(self):
        h, bodies = fixture(); calls = []
        def fetch(url):
            calls.append(url)
            if len(calls) == 2: return b'<html>Access denied</html>'
            return attachment()
        r = a.collect(h, bodies, None, fetch)
        self.assertEqual(len(r['records']), 1); self.assertTrue(r['holds'])
        self.assertTrue(r['failed_response']['raw_base64'])
        with self.assertRaises(ValueError): a.collect(h, bodies, r, fetch)
        with self.assertRaises(ValueError): a.persist(Connection(), h, bodies, r, wrap_json=lambda x: x)

    def test_transport_never_retries_permission_error_or_follows_foreign_redirect(self):
        url = 'https://www.ktcu.or.kr/comm/getFile?srvcId=BBSTY1&fileTy=ATTACH&upperNo=abc&fileNo=91'
        with patch.object(a, 'build_opener') as factory, patch.object(a.time, 'sleep') as sleep:
            factory.return_value.open.side_effect = HTTPError(url, 403, 'Forbidden', {}, None)
            with self.assertRaises(HTTPError): a.fetch_attachment(url)
            self.assertEqual(factory.return_value.open.call_count, 1); sleep.assert_not_called()
        with self.assertRaises(ValueError):
            a.OfficialRedirects().redirect_request(None, None, 302, '', {}, 'https://evil.example/file')


if __name__ == '__main__':
    unittest.main()
