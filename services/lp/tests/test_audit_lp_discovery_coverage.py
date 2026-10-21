"""Discovery is a gap signal, never a source of public fund facts."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request

from services.lp.src import audit_lp_discovery_coverage as audit

ALIASES = {'ktcu': ['한국교직원공제회', '교직원공제회'], 'kgrowth': ['한국성장금융'], 'ibk': ['IBK기업은행']}
CHANNELS = {'ktcu': {'ktcu.or.kr'}, 'kgrowth': {'kgrowth.or.kr'}, 'ibk': {'ibk.co.kr'}}


def notice(**overrides):
    return {'id': '한국교직원공제회_20261020061013', 'site': '한국교직원공제회',
            'title': '2026년 국내 블라인드 PEF 위탁운용사 선정 공고',
            'url': 'https://api.pe-vc-lp.com/att/ktcu/ktcu_62102.pdf',
            'detected_at': '2026-10-20 06:10:13', 'attachments': ['공고.pdf'], **overrides}


def payload(*rows):
    return {'count': len(rows), 'items': list(rows), 'updated_at': '2099-01-01 00:00:00'}


def compare(*rows, documents=(), aliases=ALIASES):
    return audit.audit_coverage(payload(*rows), documents, aliases=aliases, channels=CHANNELS,
                                observed_at='2026-10-21T01:00:00+00:00')


class DiscoveryCoverageTests(unittest.TestCase):
    def test_mirror_never_infers_original_or_copies_facts(self):
        row = notice(scope='verified_domestic_pe_blind', commitment_amount_krw=999,
                     selected_gps=[{'name': 'Secret GP'}], body='private', deadline='2026-12-01')
        result = compare(row)
        item = result['items'][0]
        self.assertIsNone(item['official_url'])
        self.assertEqual(item['status'], 'official_source_needed')
        self.assertEqual(item['scope'], 'pe_blind_title')
        encoded = json.dumps(result)
        for forbidden in ['attachments', 'commitment_amount_krw', 'selected_gps', 'Secret GP', 'deadline', 'private', 'verified_domestic_pe_blind', 'updated_at']:
            self.assertNotIn(forbidden, encoded)
        self.assertNotIn('ktcu.or.kr', encoded)

    def test_official_host_is_only_a_link_to_verify_not_published(self):
        item = compare(notice(url='https://www.ktcu.or.kr/notice?id=62102'))['items'][0]
        self.assertEqual(item['status'], 'official_link_to_verify')
        self.assertEqual(item['official_url'], item['url'])
        self.assertNotIn('date', item)
        self.assertEqual(item['detected_at'], '2026-10-20 06:10:13')

    def test_unknown_external_or_other_issuer_host_is_not_official(self):
        for url in ['https://ktcu.or.kr.attacker.example/notice', 'https://www.kgrowth.or.kr/notice']:
            item = compare(notice(url=url))['items'][0]
            self.assertEqual(item['status'], 'external_source_unverified')
            self.assertIsNone(item['official_url'])

    def test_normalizes_query_order_retains_ids_blank_and_repeated_values(self):
        a = audit.normalize_url('https://EXAMPLE.org/view?x=2&id=10&x=1&empty=#section')
        b = audit.normalize_url('https://example.org/view?empty=&id=10&x=2&x=1')
        self.assertEqual(a, b)
        self.assertNotEqual(a, audit.normalize_url('https://example.org/view?empty=&id=11&x=2&x=1'))
        self.assertNotEqual(a, audit.normalize_url('https://example.org/view?empty=&id=10&x=1&x=2'))
        self.assertNotEqual(a, audit.normalize_url('http://example.org/view?empty=&id=10&x=2&x=1'))

    def test_known_url_requires_same_institution_and_preserves_ids(self):
        row = notice(url='https://www.ktcu.or.kr/view?x=1&id=2')
        documents = [{'notices': [{'institution_id': 'ktcu', 'title': 'different title', 'url': 'https://www.ktcu.or.kr/view?id=2&x=1'}]}]
        self.assertEqual(compare(row, documents=documents)['items'][0]['known_match'], 'url')
        documents[0]['notices'][0]['institution_id'] = 'ibk'
        self.assertIsNone(compare(row, documents=documents)['items'][0]['known_match'])
        documents[0]['notices'][0]['institution_id'] = 'ktcu'
        documents[0]['notices'][0]['url'] = 'https://www.ktcu.or.kr/view?id=3&x=1'
        self.assertIsNone(compare(row, documents=documents)['items'][0]['known_match'])

    def test_known_program_events_and_nested_notices_inherit_institution(self):
        row = notice(title='2026년 블라인드 PEF (2차) 모집')
        documents = [{'programs': [{'institution_id': 'ktcu', 'title': '사업 제목', 'events': [{'title': '2026년 블라인드 PEF 2차 모집', 'url': 'https://www.ktcu.or.kr/a'}]}]},
                     {'collections': [{'notices': [{'institution_id': 'ktcu', 'title': 'other', 'original_notices': [{'title': 'nested', 'url': 'https://www.ktcu.or.kr/b'}]}]}]}]
        self.assertEqual(compare(row, documents=documents)['items'][0]['known_match'], 'title')
        self.assertIsNone(compare(notice(title='2026년 블라인드 PEF 1차 모집'), documents=documents)['items'][0]['known_match'])
        self.assertEqual(len(audit.extract_known(documents)), 4)

    def test_gp_and_attachment_objects_are_not_known_notices(self):
        document = {'programs': [{'institution_id': 'ktcu', 'title': 'business', 'selected_gps': [{'title': notice()['title'], 'url': notice()['url']}], 'attachments': [{'title': notice()['title'], 'url': notice()['url']}]}]}
        self.assertIsNone(compare(notice(), documents=[document])['items'][0]['known_match'])

    def test_actual_baseline_catalogs_and_source_maps_are_known(self):
        row = notice(url='https://www.ktcu.or.kr/view?id=2')
        records = [
            {'priority_notices': [{'institution_id': 'ktcu', 'title': row['title'], 'url': row['url']}]},
            {'institution_notices': [{'institution_id': 'ktcu', 'title': row['title'], 'url': row['url']}]},
            {'shared_notices': [{'institution_id': 'ktcu', 'title': row['title'], 'url': row['url']}]},
            {'sources': {'ktcu': {'notices': [{'institution_id': 'ktcu', 'title': row['title'], 'url': row['url']}]}}},
            {'programs': [{'institution_id': 'ktcu', 'title': '사업명', 'events': [{'url': row['url'], 'type': '모집 공고'}]}]},
        ]
        for document in records:
            with self.subTest(document=document):
                self.assertEqual(compare(row, documents=[document])['items'][0]['known_match'], 'url')

    def test_official_archive_without_issuer_uses_unique_verified_host_only(self):
        row = notice(site='한국성장금융', url='https://www.kgrowth.or.kr/notice_view.asp?idx=777')
        documents = [{'notices': [{'title': row['title'], 'url': row['url'], 'body': 'not copied'}]}]
        self.assertEqual(compare(row, documents=documents)['items'][0]['known_match'], 'url')
        for url in ['https://api.pe-vc-lp.com/att/kgrowth/777.pdf', 'https://kgrowth.or.kr.attacker.example/?idx=777']:
            documents[0]['notices'][0]['url'] = url
            self.assertIsNone(compare(row, documents=documents)['items'][0]['known_match'])
        ambiguous = {**CHANNELS, 'other': {'kgrowth.or.kr'}}
        self.assertFalse(audit.extract_known({'notices':[{'title': row['title'], 'url':row['url']}]}, ambiguous))

    def test_verified_direct_bank_config_supplies_only_a_host_to_check(self):
        row = notice(site='IBK기업은행', url='https://www.ibk.co.kr/cyber/noticeDetailCyber.ibk?srno=1')
        report = audit.audit_coverage(payload(row))
        self.assertEqual(report['items'][0]['source_status'], 'official_link_to_verify')
        self.assertEqual(report['items'][0]['institution_id'], 'ibk')
        self.assertEqual(compare(notice(url='http://www.ktcu.or.kr/view?id=2'))['items'][0]['source_status'], 'external_source_unverified')

    def test_unknown_site_cannot_claim_issuer_from_title_or_api_fields(self):
        item = compare(notice(site='모르는 기관', title='한국교직원공제회 PEF 모집', institution_id='ktcu'))['items'][0]
        self.assertIsNone(item['institution_id'])
        self.assertEqual(item['status'], 'institution_unknown')
        aliases = {'ktcu': ['공통이름'], 'other': ['공통이름']}
        self.assertEqual(compare(notice(site='공통이름'), aliases=aliases)['items'][0]['status'], 'institution_ambiguous')

    def test_title_only_scope_does_not_accept_claimed_scope(self):
        cases = [('2026 VC 블라인드 모집', 'vc_explicit'), ('벤처펀드 선정', 'vc_explicit'),
                 ('2026 PE/VC 모집', 'mixed_pe_vc'), ('해외 블라인드 PEF 모집', 'outside_policy'),
                 ('국내주식 헤지펀드 선정', 'outside_policy'), ('국내 PD 모집', 'outside_policy'),
                 ('2026 성장펀드 모집', 'scope_unconfirmed')]
        for title, scope in cases:
            item = compare(notice(title=title, scope='pe_blind_title'))['items'][0]
            self.assertEqual(item['scope'], scope, title)

    def test_valid_empty_is_not_malformed(self):
        result = compare()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['summary']['sample_count'], 0)
        for invalid in [[], {}, {'count': True, 'items': []}, {'count': 1, 'items': []}, {'count': 1001, 'items': [notice()] * 1001}]:
            with self.assertRaises(ValueError):
                audit.validate_payload(invalid)

    def test_all_required_fields_and_dates_are_validated(self):
        invalids = [notice(attachments=[{}]), notice(attachments=None), notice(detected_at='2026-02-30 12:00:00'),
                    notice(url='https://user:pass@example.com/a'), notice(url='javascript:alert(1)'), notice(url='https://example.com:444/a')]
        for key in ['id', 'site', 'title', 'url', 'detected_at', 'attachments']:
            row = notice()
            del row[key]
            invalids.append(row)
        for row in invalids:
            with self.assertRaises(ValueError):
                audit.validate_payload(payload(row))

    def test_api_redirect_is_https_and_same_host_only(self):
        handler = audit.DiscoveryRedirect()
        request = Request(audit.API_URL)
        for url in ['http://api.pe-vc-lp.com/announcements', 'https://attacker.example/a', 'https://api.pe-vc-lp.com:80/a', 'https://u:p@api.pe-vc-lp.com/a']:
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, 'Found', {}, url)
        redirected = handler.redirect_request(request, None, 302, 'Found', {}, audit.API_URL + '?v=1')
        self.assertEqual(redirected.full_url, audit.API_URL + '?v=1')

    def test_fetch_single_bounded_get(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def geturl(self): return audit.API_URL
            def read(self, size):
                self.size = size
                return json.dumps(payload()).encode()
        response = Response()
        with patch.object(audit, 'build_opener') as build:
            build.return_value.open.return_value = response
            self.assertEqual(audit.fetch_discovery()['count'], 0)
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, audit.API_URL)
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(build.return_value.open.call_args.kwargs['timeout'], 20)
            self.assertEqual(build.return_value.open.call_count, 1)
            self.assertEqual(response.size, audit.MAX_BYTES + 1)
            response.read = lambda size: b'x' * (audit.MAX_BYTES + 1)
            with self.assertRaises(ValueError): audit.fetch_discovery()

    def test_network_or_schema_error_holds_without_leaking_exception(self):
        for fetch in [lambda: (_ for _ in ()).throw(TimeoutError('private token')), lambda: {}]:
            report = audit.run_audit(fetch=fetch, aliases=ALIASES, channels=CHANNELS)
            self.assertEqual(report['status'], 'error')
            self.assertTrue(report['holds'])
            self.assertEqual(report['items'], [])
            self.assertNotIn('private token', json.dumps(report))

    def test_cli_repeated_collections_and_failure_exit_zero_write_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['baseline', 'collection1', 'collection2']:
                (root / (name + '.json')).write_text('{"notices": []}')
            args = ['--baseline', str(root / 'baseline.json'), '--official-collection', str(root / 'collection1.json'),
                    '--official-collection', str(root / 'collection2.json'), '--output', str(root / 'report.json'), '--markdown', str(root / 'report.md')]
            with patch.object(audit, 'run_audit', return_value=audit.run_audit(fetch=lambda: payload(), aliases=ALIASES, channels=CHANNELS)) as run:
                self.assertEqual(audit.main(args), 0)
                self.assertEqual(len(run.call_args.args[0]), 3)
            with patch.object(audit, 'fetch_discovery', side_effect=TimeoutError()), contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(audit.main(args), 0)
                self.assertIn('WARNING', stderr.getvalue())
            self.assertEqual(json.loads((root / 'report.json').read_text())['status'], 'error')
            self.assertIn('상태: error', (root / 'report.md').read_text())

    def test_markdown_does_not_emit_raw_html_or_table_breaks(self):
        report = compare(notice(title='PEF <script>evil</script>|foo\nbar'))
        text = audit.markdown_report(report)
        self.assertNotIn('<script>', text)
        self.assertIn('\\|foo bar', text)


if __name__ == '__main__':
    unittest.main()
