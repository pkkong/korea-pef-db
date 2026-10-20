#!/usr/bin/env python3
"""Discover issuer boards directly and retain replayable official receipts.

No association repost, fixed notice ID, prepared scope or candidate facts grant
publication. The publisher replays these parsers and attachment extraction.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import io
import json
import re
import time
import zipfile
from datetime import date, datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

try:
    from .lp_transport_errors import transient_dns
    from .collect_shared_lp_notices import decode_html, classify_scope
    from .collect_lp_original_notices import OfficialRedirect, original_body_hash, safe_host
    from .lp_attachment_text import extract_attachment
    from . import lp_board_adapters_mutuals as mutuals, lp_board_adapters_pensions as pensions
except ImportError:
    from lp_transport_errors import transient_dns
    from collect_shared_lp_notices import decode_html, classify_scope
    from collect_lp_original_notices import OfficialRedirect, original_body_hash, safe_host
    from lp_attachment_text import extract_attachment
    import lp_board_adapters_mutuals as mutuals
    import lp_board_adapters_pensions as pensions

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / 'data/lp_institution_board_channels.json'
MAX_BYTES = 12 * 1024 * 1024
MAX_DETAILS = 30
FORM = re.compile(r'양식|서식|제안서|제출서류|체크리스트|\.xlsx?$', re.I)

def is_form(name):
    return bool(FORM.search(name) and not re.search(r'공고|모집|선정계획', name))


def load_configs():
    settings = json.loads(CONFIG.read_text())
    return {c['institution_id']: dict(c, history_years=settings['history_years']) for c in settings['channels']}


def adapter(config):
    return mutuals if config['institution_id'] in {'poba', 'pmaa'} else pensions


def listing_urls(config):
    parsed = urlsplit(config['listing_url'])
    for search in config['searches']:
        for page in range(1, config['pages'] + 1):
            params = dict(parse_qsl(parsed.query))
            params.update({config['search_param']: search, config['page_param']: str(page)})
            yield urlunsplit(parsed._replace(query=urlencode(params)))


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _same_host(url, config):
    if urlsplit(url).scheme != 'https' or safe_host(url) != safe_host(config['listing_url']):
        raise ValueError('official institution HTTPS host mismatch')


class Session:
    def __init__(self, config):
        self.config = config
        self.opener = build_opener(OfficialRedirect({safe_host(config['listing_url'])}),
                                   HTTPCookieProcessor(CookieJar()))

    def __call__(self, url, referer=None):
        _same_host(url, self.config)
        headers = {'User-Agent': 'Mozilla/5.0 (LP official board collector)',
                   'Accept-Encoding': 'identity', 'Connection': 'close'}
        if referer:
            headers['Referer'] = referer
        for attempt in range(2):
            try:
                with self.opener.open(Request(url, headers=headers), timeout=20) as response:
                    raw = response.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        raise ValueError('official response exceeds 12 MiB')
                    return raw
            except (TimeoutError, ConnectionError, URLError) as exc:
                # Certificate/HTTP validation failures are not transient retries.
                transient = isinstance(exc, (TimeoutError, ConnectionError))
                if isinstance(exc, HTTPError):
                    transient = exc.code in {408, 429, 500, 502, 503, 504}
                elif isinstance(exc, URLError):
                    transient = transient_dns(exc) or isinstance(exc.reason, (TimeoutError, ConnectionError))
                if attempt or not transient:
                    raise
                time.sleep(1)


def attachment_text(raw, name):
    """Offering ZIPs keep only actual documents, never auxiliary form text."""
    if is_form(name):
        return ''
    result = extract_attachment(raw)
    if result['format'] != 'zip':
        return result['text']
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = archive.infolist()
        if (len(files) > 20 or sum(f.file_size for f in files) > 32 * 1024 * 1024
                or len({f.filename for f in files}) != len(files)):
            raise ValueError('offering ZIP exceeds bounded extraction limits')
        texts = []
        for item in files:
            member_name = item.filename
            if not item.flag_bits & 0x800:
                try:
                    member_name = member_name.encode('cp437').decode('cp949')
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            if item.flag_bits & 1 or item.file_size > MAX_BYTES:
                raise ValueError('encrypted or oversized ZIP document')
            if (is_form(member_name) or item.is_dir()
                    or not re.search(r'\.(pdf|hwp|hwpx)$', member_name, re.I)):
                continue
            # Archives can include useful historical references; only a labelled
            # offering document is evidence about this recruitment.
            if not re.search(r'공고|선정계획|모집', member_name):
                continue
            text = extract_attachment(archive.read(item))['text']
            if text:
                texts.append(text)
        if not texts:
            raise ValueError('offering ZIP has no readable labelled offering document')
        return '\n'.join(texts)


def _html(raw):
    html = decode_html(raw)
    if '</html>' not in html.lower():
        raise ValueError('incomplete official HTML')
    return html


def collect(configs=None, fetch_factory=Session, checked_at=None):
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    result = {'checked_at': checked_at, 'notices': [], 'holds': [], 'coverage': {}}
    for institution, config in (configs or load_configs()).items():
        fetch = fetch_factory(config)
        receipts, candidates = {}, {}
        coverage = {'listing_pages': [], 'detail_count': 0, 'attachment_count': 0}
        result['coverage'][institution] = coverage
        for url in listing_urls(config):
            try:
                html = _html(fetch(url))
                rows = adapter(config).parse_listing(html, url, config)
                receipts[url] = {'url': url, 'html': html, 'sha256': digest(html)}
                coverage['listing_pages'].append({'url': url, 'count': len(rows)})
                for row in rows:
                    if (re.search(r'위탁|운용사|블라인드|PEF?|사모|선정', row['title'], re.I)
                            and classify_scope(row['title'], row['title']) != 'outside'):
                        if row['date'][:4] >= str(int(checked_at[:4]) - config.get('history_years', 4) + 1):
                            candidates.setdefault(row['url'], (row, url))
                        else:
                            coverage['older_rows_skipped'] = coverage.get('older_rows_skipped', 0) + 1
            except Exception as exc:
                result['holds'].append({'institution_id': institution, 'stage': 'institution_listing',
                                        'url': url, 'error': str(exc)})
        ordered = sorted(candidates.values(), key=lambda item: (item[0]['date'], item[0]['url']), reverse=True)
        if len(ordered) > MAX_DETAILS:
            result['holds'].append({'institution_id': institution, 'stage': 'institution_depth',
                                    'error': 'detail budget reached; older candidates retained in listing receipts'})
        for row, listing_url in ordered[:MAX_DETAILS]:
            try:
                html = _html(fetch(row['url'], listing_url))
                detail = adapter(config).parse_detail(html, row['url'], config)
                if detail['date'] != row['date'] or detail['title'] != row['title']:
                    raise ValueError('official listing/detail title or date differs')
                n = {**detail, 'institution_id': institution, 'source_id': row['source_id'],
                     'url': row['url'], 'checked_at': checked_at, 'source_channel': 'institution_board',
                     'discovery_provenance': {'kind': 'institution_board_v1',
                         'listing': receipts[listing_url], 'detail_html': html, 'detail_sha256': digest(html)},
                     'attachment_hashes': {}, 'attachment_texts': {}, 'attachment_bytes': {}}
                n['sha256'] = original_body_hash(n)
                coverage['detail_count'] += 1
                # Unrelated investment boards remain discoverable, but their
                # files cannot qualify the offered PE scope accidentally.
                outside = classify_scope(n['title'], n['title']) in {'outside', 'vc_only'}
                if not outside:
                    for item in n['attachments'][:6]:
                        if is_form(item['name']):
                            continue
                        try:
                            raw = fetch(item['url'], n['url'])
                            text = attachment_text(raw, item['name'])
                            n['attachment_bytes'][item['url']] = base64.b64encode(raw).decode('ascii')
                            n['attachment_hashes'][item['url']] = digest(raw)
                            if text:
                                n['attachment_texts'][item['url']] = text
                            coverage['attachment_count'] += 1
                        except Exception as exc:
                            result['holds'].append({'institution_id': institution, 'stage': 'institution_attachment',
                                                    'url': item['url'], 'notice_url': n['url'], 'error': str(exc)})
                result['notices'].append(validate_notice(n, checked_at, config))
            except Exception as exc:
                result['holds'].append({'institution_id': institution, 'stage': 'institution_detail',
                                        'url': row['url'], 'error': str(exc)})
    return result


def validate_notice(raw, checked_at, config=None):
    n = copy.deepcopy(raw)
    config = config or load_configs()[n['institution_id']]
    if n['institution_id'] != config['institution_id'] or n['source_channel'] != 'institution_board':
        raise ValueError('institution collection identity mismatch')
    _same_host(n['url'], config)
    proof = n['discovery_provenance']
    listing = proof['listing']
    if (proof['kind'] != 'institution_board_v1' or listing['url'] not in set(listing_urls(config))
            or digest(listing['html']) != listing['sha256']
            or digest(proof['detail_html']) != proof['detail_sha256']):
        raise ValueError('institution source receipt mismatch')
    rows = adapter(config).parse_listing(listing['html'], listing['url'], config)
    detail = adapter(config).parse_detail(proof['detail_html'], n['url'], config)
    if not any(all(row[k] == n[k] for k in ('url', 'title', 'date', 'source_id')) for row in rows):
        raise ValueError('notice was not observed on the configured official listing')
    if any(n[k] != detail[k] for k in ('title', 'date', 'body', 'attachments')):
        raise ValueError('notice differs from official detail receipt')
    observed = datetime.fromisoformat(n['checked_at'].replace('Z', '+00:00'))
    limit = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    if (observed.tzinfo is None or limit.tzinfo is None or observed > limit
            or date.fromisoformat(n['date']) > observed.date()):
        raise ValueError('invalid institution notice observation/publication date')
    if not n['body'].strip() or original_body_hash(n) != n['sha256']:
        raise ValueError('invalid official notice body hash')
    observed_attachments = {a['url']: a['name'] for a in detail['attachments']}
    if set(n['attachment_bytes']) != set(n['attachment_hashes']) or not set(n['attachment_texts']) <= set(n['attachment_bytes']):
        raise ValueError('attachment proof maps differ')
    for url, encoded in n['attachment_bytes'].items():
        _same_host(url, config)
        if url not in observed_attachments or len(encoded) > (MAX_BYTES + 2) // 3 * 4:
            raise ValueError('unobserved or oversized institution attachment')
        content = base64.b64decode(encoded, validate=True)
        if digest(content) != n['attachment_hashes'][url]:
            raise ValueError('institution attachment fingerprint mismatch')
        if attachment_text(content, observed_attachments[url]) != n['attachment_texts'].get(url, ''):
            raise ValueError('institution attachment text does not match source bytes')
    return n


def update_catalog(current, incoming, checked_at):
    retained, holds = {}, copy.deepcopy((incoming or {}).get('holds', []))
    for raw in current.get('institution_notices', []) + (incoming or {}).get('notices', []):
        try:
            n = validate_notice(raw, checked_at)
            previous = retained.get(n['url'])
            if (previous and previous['sha256'] == n['sha256']
                    and set(n['attachment_texts']) < set(previous['attachment_texts'])
                    and all(n['attachment_hashes'][u] == previous['attachment_hashes'].get(u)
                            for u in n['attachment_hashes'])):
                continue
            retained[n['url']] = n
        except (ValueError, KeyError, TypeError) as exc:
            holds.append({'stage': 'institution_validation', 'url': raw.get('url'), 'error': str(exc)})
    return {'institution_notices': list(retained.values()), 'institution_collection_holds': holds,
            'institution_collection_coverage': copy.deepcopy((incoming or {}).get('coverage',
                                                            current.get('institution_collection_coverage', {})))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = collect()
    args.output.write_text(json.dumps(result, ensure_ascii=False))
    print(json.dumps({'notices': len(result['notices']), 'holds': len(result['holds']),
                      'coverage': result['coverage']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
