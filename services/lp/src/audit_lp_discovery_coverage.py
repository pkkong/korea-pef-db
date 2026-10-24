#!/usr/bin/env python3
"""Read-only third-party discovery comparison; never a publication input.

Only issuer/title/observed URL evidence is retained. Third-party terms, results,
attachments and detection times cannot supply official facts or publication dates.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from .collect_shared_lp_notices import load_aliases, classify_scope
    from .collect_lp_original_notices import load_channels
except ImportError:
    from collect_shared_lp_notices import load_aliases, classify_scope
    from collect_lp_original_notices import load_channels

ROOT = Path(__file__).resolve().parents[3]
API_URL = 'https://api.pe-vc-lp.com/announcements'
MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 1000
CONTAINERS = {'programs', 'events', 'notices', 'original_notices', 'items',
              'records', 'results', 'collections', 'sources', 'candidates',
              'official_notices', 'collection', 'priority_notices', 'institution_notices', 'shared_notices'}


def normalize_title(value):
    """Exact comparison after typography normalization; retain every digit/word."""
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum())


def normalize_url(value):
    """Conservative URL identity: preserve scheme, path and all query values."""
    if not isinstance(value, str) or not value or re.search(r'[\x00-\x20\x7f]', value):
        raise ValueError('invalid discovery URL')
    p = urlsplit(value)
    if p.scheme not in {'https', 'http'} or not p.hostname or p.username or p.password:
        raise ValueError('invalid discovery URL')
    if p.port not in {None, 80, 443}:
        raise ValueError('invalid discovery URL port')
    host = p.hostname.lower()
    if ':' in host:
        raise ValueError('literal IP source is not an institution host')
    port = p.port
    authority = host if port is None or (p.scheme, port) in {('https', 443), ('http', 80)} else f'{host}:{port}'
    return urlunsplit((p.scheme, authority, p.path or '/', urlencode(sorted(parse_qsl(p.query, keep_blank_values=True), key=lambda pair: pair[0])), ''))


def _api_url(value):
    p = urlsplit(normalize_url(value))
    if p.scheme != 'https' or p.hostname != 'api.pe-vc-lp.com' or p.port not in {None, 443}:
        raise ValueError('discovery redirect must remain on the HTTPS API host')
    return value


class DiscoveryRedirect(HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 1

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _api_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_discovery():
    """One bounded anonymous GET, without cookies, credentials or retries."""
    request = Request(API_URL, headers={'User-Agent': 'LP discovery coverage audit', 'Accept': 'application/json', 'Accept-Encoding': 'identity'})
    with build_opener(DiscoveryRedirect()).open(request, timeout=20) as response:
        _api_url(response.geturl())
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('discovery response exceeds size limit')
        return json.loads(data.decode('utf-8'))


def validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('discovery response must be an object')
    count, items = payload.get('count'), payload.get('items')
    if type(count) is not int or not isinstance(items, list) or count != len(items) or not 0 <= count <= MAX_ITEMS:
        raise ValueError('discovery count/items mismatch or limit exceeded')
    clean = []
    for row in items:
        if not isinstance(row, dict):
            raise ValueError('discovery item must be an object')
        for key, limit in [('id', 512), ('site', 512), ('title', 2048), ('url', 8192), ('detected_at', 64)]:
            value = row.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
                raise ValueError('invalid discovery string field')
        normalize_url(row['url'])
        try:
            datetime.strptime(row['detected_at'], '%Y-%m-%d %H:%M:%S')
        except ValueError as error:
            raise ValueError('invalid discovery detection timestamp') from error
        attachments = row.get('attachments')
        if not isinstance(attachments, list) or len(attachments) > 100 or any(not isinstance(a, str) or len(a) > 2048 for a in attachments):
            raise ValueError('invalid discovery attachment filenames')
        # Ignore every other supplied field, including claimed terms/scope/results.
        clean.append({key: row[key] for key in ('id', 'site', 'title', 'url', 'detected_at')})
    return clean


def load_directory_aliases(root=ROOT):
    """Identify stored directory entities without extending collection scope."""
    result = {}
    with (root/'data/lp_institutions.csv').open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            names = [row['lp_name'], *row.get('aliases', '').split(';')]
            result.setdefault(row['lp_code'], set()).update(name.strip() for name in names if name.strip())
    return result


def _issuer(site, title, aliases):
    normalized = normalize_title(site)
    exact = {code for code, names in aliases.items() if normalized in {normalize_title(n) for n in names}}
    if len(exact) > 1:
        return None, 'ambiguous'
    if len(exact) == 1:
        return next(iter(exact)), 'site_exact'
    # An unknown site label cannot be replaced by a different institution merely
    # mentioned in its headline (for example a delegated/joint fund).
    return None, 'unmatched'


def extract_known(document, channels=None):
    """Extract notice identities only, inheriting issuer through program events."""
    records = []
    channels = load_channels() if channels is None else channels
    hosts = {}
    for institution, official_hosts in channels.items():
        for host in official_hosts:
            hosts.setdefault(host, set()).add(institution)

    def walk(node, institution=None, depth=0):
        if depth > 24:
            raise ValueError('official collection nesting exceeds limit')
        if isinstance(node, list):
            for child in node:
                walk(child, institution, depth + 1)
        elif isinstance(node, dict):
            issuer = node.get('institution_id', institution)
            if not isinstance(issuer, str) or not issuer:
                issuer = None
            title, url = node.get('title'), node.get('url')
            if issuer is None and isinstance(url, str):
                try:
                    parsed = urlsplit(normalize_url(url))
                    candidates = hosts.get(parsed.hostname.removeprefix('www.'),set())
                    if parsed.scheme == 'https' and len(candidates) == 1:
                        issuer = next(iter(candidates))
                except ValueError:
                    pass
            if issuer and (isinstance(title, str) and title.strip() or isinstance(url, str)):
                normalized_url = None
                if isinstance(url, str):
                    try:
                        normalized_url = normalize_url(url)
                    except ValueError:
                        pass
                records.append((issuer, normalize_title(title) if isinstance(title, str) else '', normalized_url))
            for key in CONTAINERS:
                if key in node:
                    if key == 'sources' and isinstance(node[key], dict):
                        for source in node[key].values():
                            walk(source, issuer, depth + 1)
                    else:
                        walk(node[key], issuer, depth + 1)
    walk(document)
    return records


def title_scope(title):
    pe = bool(re.search(r'(?<![A-Za-z])PEF?(?![A-Za-z])|기관전용\s*사모|경영참여형\s*사모', title, re.I))
    vc = bool(re.search(r'(?<![A-Za-z])VC(?![A-Za-z])|벤처|신기술사업투자', title, re.I))
    blind = bool(re.search(r'블라인드|blind', title, re.I))
    outside = classify_scope(title, '') == 'outside' or bool(re.search(r'사모\s*(?:대출|채권)|(?<![A-Za-z])PD(?![A-Za-z])|크레딧|인프라|헤지펀드|부동산', title, re.I))
    scope = 'outside_policy' if outside else 'mixed_pe_vc' if pe and vc else 'vc_explicit' if vc else 'pe_blind_title' if pe and blind else 'scope_unconfirmed'
    return scope, {'pe': pe, 'vc': vc, 'blind': blind}


def audit_coverage(payload, documents=(), *, aliases=None, channels=None, observed_at=None, directory_aliases=None):
    items = validate_payload(payload)
    # Explicitly injected aliases remain a complete test/caller boundary unless
    # the caller also supplies a directory. Production loads both independently.
    use_directory = aliases is None
    aliases = load_aliases() if aliases is None else aliases
    directory_aliases = (load_directory_aliases() if use_directory else {}) if directory_aliases is None else directory_aliases
    outside_aliases = {code: names for code, names in directory_aliases.items() if code not in aliases}
    if channels is None:
        channels = load_channels()
        for channel in json.loads((ROOT/'data/lp_institution_board_channels.json').read_text())['channels']:
            host = urlsplit(channel['listing_url']).hostname.removeprefix('www.')
            channels.setdefault(channel['institution_id'], set()).add(host)
    known = [record for document in documents for record in extract_known(document, channels)]
    urls = {(issuer, url) for issuer, _, url in known if url}
    titles = {(issuer, title) for issuer, title, _ in known if title}
    results = []
    for row in items:
        institution, identity = _issuer(row['site'], row['title'], aliases)
        identified_outside = False
        directory_institution, directory_identity = _issuer(row['site'], row['title'], outside_aliases)
        if identity == 'site_exact' and directory_identity != 'unmatched':
            institution, identity = None, 'ambiguous'
        elif identity == 'unmatched':
            if directory_institution:
                institution = directory_institution
                identity, identified_outside = 'directory_site_exact', True
            elif directory_identity == 'ambiguous':
                identity = 'ambiguous'
        url = normalize_url(row['url'])
        host = urlsplit(url).hostname.removeprefix('www.')
        scope, mentions = title_scope(row['title'])
        if host == 'api.pe-vc-lp.com':
            source_status, official_url = 'official_source_needed', None
        elif institution and urlsplit(url).scheme == 'https' and host in channels.get(institution, set()):
            source_status, official_url = 'official_link_to_verify', row['url']
        else:
            source_status, official_url = 'external_source_unverified', None
        matching = None
        if not identified_outside and institution and (institution, url) in urls:
            matching = 'url'
        elif not identified_outside and institution and (institution, normalize_title(row['title'])) in titles:
            matching = 'title'
        disposition = 'identified_outside_collection' if identified_outside else 'already_known' if matching else 'institution_ambiguous' if identity == 'ambiguous' else 'institution_unknown' if not institution else scope if scope in {'outside_policy', 'vc_explicit', 'mixed_pe_vc'} else source_status
        results.append({**row, 'institution_id': institution, 'identity': identity,
                        'title_mentions': mentions, 'scope': scope, 'source_status': source_status,
                        'official_url': official_url, 'status': disposition, 'known_match': matching})
    return {'status': 'ok', 'source': API_URL, 'observed_at': observed_at or datetime.now(timezone.utc).isoformat(),
            'purpose': 'official_notice_gap_discovery_only', 'items': results, 'holds': [],
            'summary': {'sample_count': len(results), 'by_status': dict(Counter(r['status'] for r in results)),
                        'by_institution': dict(Counter(r['institution_id'] or 'unmatched' for r in results))}}


def run_audit(documents=(), *, fetch=None, **options):
    observed_at = datetime.now(timezone.utc).isoformat()
    try:
        # The receive time is ours; third-party updated_at/detected_at never
        # become official publication dates or a freshness success condition.
        payload = (fetch or fetch_discovery)()
        observed_at = datetime.now(timezone.utc).isoformat()
        return audit_coverage(payload, documents, observed_at=observed_at, **options)
    except Exception as error:
        return {'status': 'error', 'source': API_URL, 'observed_at': observed_at,
                'purpose': 'official_notice_gap_discovery_only', 'items': [],
                'holds': [{'stage': 'discovery_comparison', 'reason': type(error).__name__}],
                'summary': {'sample_count': 0, 'by_status': {}, 'by_institution': {}}}


def markdown_report(report):
    lines = ['# 공식 공고 누락 후보 비교', '', f"상태: {report['status']}", f"수신 시각: {report['observed_at']}", '',
             '비교 결과는 발견 단서이며 공식 공고·모집조건·선정 결과로 공개하지 않습니다.', '',
             '| 기관 | 공고 | 분류 | 발견 링크 |', '| --- | --- | --- | --- |']
    def cell(value):
        return str(value or '').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ').replace('<', '&lt;').replace('>', '&gt;')
    for row in report['items']:
        lines.append('| ' + ' | '.join(cell(row[key]) for key in ('site', 'title', 'status', 'url')) + ' |')
    for hold in report['holds']:
        lines.append(f"\n비교 보류: {cell(hold['reason'])}")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--official-collection', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--markdown', type=Path)
    args = parser.parse_args(argv)
    try:
        documents = [json.loads(p.read_text(encoding='utf-8')) for p in [args.baseline, *args.official_collection]]
        report = run_audit(documents)
    except Exception as error:
        report = run_audit(fetch=lambda: (_ for _ in ()).throw(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown_report(report), encoding='utf-8')
    if report['status'] == 'error':
        print('WARNING: LP discovery comparison held; official collection is unaffected.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
