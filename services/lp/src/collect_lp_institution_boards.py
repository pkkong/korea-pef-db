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
import os
import re
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

try:
    from .lp_ipv4_transport import IPv4HTTPSHandler
    from .lp_kdb_dns import resolve_kdb_ipv4
    from .lp_cu_transport import CuDnsError, fetch_cu_ipv4
    from .lp_regional_transport import fetch_kfcc, fetch_cu
    from .lp_transport_errors import transient_dns
    from .collect_shared_lp_notices import decode_html, classify_scope
    from .collect_lp_original_notices import OfficialRedirect, original_body_hash, safe_host
    from .lp_attachment_text import extract_attachment
    from . import lp_board_adapters_mutuals as mutuals, lp_board_adapters_pensions as pensions
    from . import lp_board_adapter_kfcc as kfcc, lp_board_adapters_banks as banks
    from . import lp_board_adapter_pck as pck
    from . import lp_board_adapter_sema as sema
    from . import lp_board_adapter_kfinco as kfinco
    from . import lp_board_adapter_kbiz as kbiz
    from . import lp_board_adapter_moel as moel
    from . import lp_board_adapter_mmaa as mmaa
    from . import lp_board_adapter_geps as geps
    from . import lp_board_adapter_kamco as kamco
except ImportError:
    from lp_ipv4_transport import IPv4HTTPSHandler
    from lp_kdb_dns import resolve_kdb_ipv4
    from lp_cu_transport import CuDnsError, fetch_cu_ipv4
    from lp_regional_transport import fetch_kfcc, fetch_cu
    from lp_transport_errors import transient_dns
    from collect_shared_lp_notices import decode_html, classify_scope
    from collect_lp_original_notices import OfficialRedirect, original_body_hash, safe_host
    from lp_attachment_text import extract_attachment
    import lp_board_adapters_mutuals as mutuals
    import lp_board_adapters_pensions as pensions
    import lp_board_adapter_kfcc as kfcc
    import lp_board_adapters_banks as banks
    import lp_board_adapter_pck as pck
    import lp_board_adapter_sema as sema
    import lp_board_adapter_kfinco as kfinco
    import lp_board_adapter_kbiz as kbiz
    import lp_board_adapter_moel as moel
    import lp_board_adapter_mmaa as mmaa
    import lp_board_adapter_geps as geps
    import lp_board_adapter_kamco as kamco

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / 'data/lp_institution_board_channels.json'
MAX_BYTES = 12 * 1024 * 1024
MAX_DETAILS = 30
FORM = re.compile(r'양식|서식|제안서|제출서류|체크리스트|\.xlsx?$', re.I)

def is_form(name):
    return bool(FORM.search(name) and not re.search(r'공고|모집|선정계획', name))


def load_configs():
    settings = json.loads(CONFIG.read_text())
    configs = {c['institution_id']: {'history_years': settings['history_years'], **c} for c in settings['channels']}
    for c in configs.values():
        if not 1 <= c.get('max_details', MAX_DETAILS) <= 60 or not 1 <= c['history_years'] <= 4:
            raise ValueError('institution discovery budget outside supported limits')
        if c.get('lookback_days') is not None and not 1 <= c['lookback_days'] <= 1461:
            raise ValueError('institution lookback period outside supported limits')
    return configs


def adapter(config):
    institution = config['institution_id']
    if institution in {'kdb', 'ibk'}:
        return banks
    if institution == 'kfcc':
        return kfcc
    if institution == 'pck_pension':
        return pck
    if institution == 'sema':
        return sema
    if institution == 'kbiz':
        return kbiz
    if institution == 'mmaa':
        return mmaa
    if institution == 'geps':
        return geps
    if institution == 'kamco':
        return kamco
    if institution in {'moel_eif', 'moel_iaci'}:
        return moel
    if institution == 'kfinco':
        return kfinco
    if institution in {'poba', 'pmaa'}:
        return mutuals
    if institution in {'tp', 'cu'}:
        return pensions
    raise ValueError('unsupported institution board adapter')


def listing_urls(config):
    if config['institution_id'] in {'kdb', 'ibk'}:
        yield from (request['url'] for request in banks.listing_requests(config))
        return
    parsed = urlsplit(config['listing_url'])
    for search in config['searches']:
        for page in range(1, config['pages'] + 1):
            params = dict(parse_qsl(parsed.query))
            params.update({config['search_param']: search, config['page_param']: str(page)})
            yield urlunsplit(parsed._replace(query=urlencode(params)))


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def listing_receipt_urls(config):
    """Keep captured TP receipts valid after the 100-to-10 row migration.

    This is validation-only: discovery still requests the current configuration.
    Preserve the exact issuer, board, title query and configured page number.
    """
    urls = set(listing_urls(config))
    if config['institution_id'] == 'tp':
        for url in list(urls):
            parsed = urlsplit(url)
            params = dict(parse_qsl(parsed.query))
            if params.get('pageItm') == '10':
                params['pageItm'] = '100'
                urls.add(urlunsplit(parsed._replace(query=urlencode(params))))
    return urls


def _same_host(url, config):
    if urlsplit(url).scheme != 'https' or safe_host(url) != safe_host(config['listing_url']):
        raise ValueError('official institution HTTPS host mismatch')


class Session:
    def __init__(self, config):
        self.config = config
        self.regional_fetches = 0
        self.native_ipv4_fetches = 0
        self.dns_ipv4_fetches = 0
        self.alternate_dns_lookups = 0
        cookies = CookieJar()
        self.opener = build_opener(OfficialRedirect({safe_host(config['listing_url'])}),
                                   HTTPCookieProcessor(cookies))
        self.ipv4_opener = build_opener(OfficialRedirect({safe_host(config['listing_url'])}),
                                        HTTPCookieProcessor(cookies), IPv4HTTPSHandler(
                                            fallback_resolver=self._resolve_kdb_dns if config['institution_id'] == 'kdb' else None))

    def _resolve_kdb_dns(self, host, port, timeout):
        rows = resolve_kdb_ipv4(host, port, timeout)
        self.alternate_dns_lookups += 1
        return rows

    def __call__(self, url, referer=None):
        _same_host(url, self.config)
        if self.config['institution_id'] == 'kfinco':
            try:
                from .discover_kfinco_originals import native_tls_fetch, _fetch_with_retry
            except ImportError:
                from discover_kfinco_originals import native_tls_fetch, _fetch_with_retry
            if not hasattr(self, '_kfinco_retry_budget'):
                self._kfinco_retry_budget = [4]
            request_url = kfinco.detail_request(url) if urlsplit(url).path.startswith('/pr/notice/detail/') else url
            return _fetch_with_retry(native_tls_fetch, request_url, self._kfinco_retry_budget)
        headers = {'User-Agent': 'Mozilla/5.0 (LP official board collector)',
                   'Accept-Encoding': 'identity', 'Connection': 'close'}
        if referer:
            headers['Referer'] = referer
        native_ipv4 = False
        dns_ipv4 = False
        for attempt in range(2):
            if native_ipv4:
                try:
                    raw = fetch_cu_ipv4(url, referer)
                except CuDnsError:
                    token = os.environ.get('LP_SOURCE_WORKER_TOKEN', '')
                    if not token:
                        raise
                    # Only the first typed resolver failure and curl exit 6
                    # permit one regional request after two direct attempts.
                    raw = fetch_cu(url, referer, token)
                    self.regional_fetches += 1
                    return raw
                self.native_ipv4_fetches += 1
                return raw
            try:
                opener = self.ipv4_opener if dns_ipv4 else self.opener
                with opener.open(Request(url, headers=headers), timeout=20) as response:
                    raw = response.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        raise ValueError('official response exceeds 12 MiB')
                    if dns_ipv4:
                        self.dns_ipv4_fetches += 1
                    return raw
            except (TimeoutError, ConnectionError, URLError) as exc:
                # Certificate/HTTP validation failures are not transient retries.
                transient = isinstance(exc, (TimeoutError, ConnectionError))
                if isinstance(exc, HTTPError):
                    token = os.environ.get('LP_SOURCE_WORKER_TOKEN', '')
                    if (self.config['institution_id'] == 'kfcc' and exc.code == 400 and token
                            and b'Request Blocked' in exc.read(4096)):
                        raw = fetch_kfcc(url, referer, token)
                        self.regional_fetches += 1
                        return raw
                    transient = exc.code in {408, 429, 500, 502, 503, 504}
                elif isinstance(exc, URLError):
                    transient = transient_dns(exc) or isinstance(exc.reason, (TimeoutError, ConnectionError))
                # Use the existing second direct attempt; CU DNS may then use one regional request.
                # An ordinary timeout/HTTP/TLS/content error cannot select it.
                native_ipv4 = self.config['institution_id'] == 'cu' and transient_dns(exc)
                dns_ipv4 = transient_dns(exc) and not native_ipv4
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
                    or not re.search(r'\.(pdf|hwp|hwpx|docx)$', member_name, re.I)):
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


def _detail(html, url, config, resolution=None):
    parser = adapter(config)
    request = getattr(parser, 'attachment_request', lambda *a: None)(html, url, config)
    kwargs = {}
    if resolution is not None:
        kind = 'attachment_listing' if config['institution_id']=='mmaa' else 'resolver_script'
        if (not request or set(resolution) != {'url','text','sha256','kind'}
                or resolution['url'] != request or resolution['kind'] != kind
                or digest(resolution['text']) != resolution['sha256']):
            raise ValueError('Official attachment resolver receipt mismatch')
        _same_host(request, config)
        kwargs[kind] = resolution['text']
    return parser.parse_detail(html, url, config, **kwargs)


def collect(configs=None, fetch_factory=Session, checked_at=None):
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    result = {'checked_at': checked_at, 'notices': [], 'holds': [], 'coverage': {}}
    shared_listings = {}
    resolver_cache = {}
    for institution, config in (configs or load_configs()).items():
        fetch = fetch_factory(config)
        receipts, candidates = {}, {}
        coverage = {'listing_pages': [], 'detail_count': 0, 'attachment_count': 0,
                    'history_years': config.get('history_years', 4)}
        result['coverage'][institution] = coverage
        stopped_searches = set()
        seen_by_search = {}
        cutoff = None
        if config.get('lookback_days'):
            observed_day = datetime.fromisoformat(checked_at.replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Seoul')).date()
            cutoff = (observed_day - timedelta(days=config['lookback_days'] - 1)).isoformat()
            coverage.update(lookback_days=config['lookback_days'], window_start=cutoff, window_end=observed_day.isoformat())
        for url in listing_urls(config):
            search = parse_qsl(urlsplit(url).query)
            search = next((value for key, value in search if key == config.get('search_param')), '')
            if search in stopped_searches:
                continue
            try:
                if institution in {'moel_eif', 'moel_iaci'} and url in shared_listings:
                    raw = shared_listings[url]
                else:
                    raw = fetch(url, config['listing_url'])
                    if institution in {'moel_eif', 'moel_iaci'}:
                        shared_listings[url] = raw
                html = raw.decode('utf-8') if institution == 'kdb' or config.get('response_format') == 'json' else _html(raw)
                rows = adapter(config).parse_listing(html, url, config)
                receipts[url] = {'url': url, 'html': html, 'sha256': digest(html)}
                coverage['listing_pages'].append({'url': url, 'count': len(rows)})
                if config.get('lookback_days'):
                    seen = seen_by_search.setdefault(search, set())
                    identities = {row['source_id'] for row in rows}
                    if rows and not identities - seen:
                        raise ValueError(institution + ' listing repeated before observed history boundary')
                    seen.update(identities)
                    current_page = int(dict(parse_qsl(urlsplit(url).query))[config['page_param']])
                    final_page = adapter(config).last_page(html, url, config)
                    regular = [row for row in rows if not row.get('pinned')]
                    older = cutoff and regular and all(row['date'] < cutoff for row in regular)
                    if current_page == final_page or older:
                        stopped_searches.add(search)
                        coverage.setdefault('listing_boundaries', []).append({'search': search, 'page': current_page,
                            'boundary': 'observed_older_page' if older else 'observed_final_page'})
                    elif current_page == config['pages']:
                        result['holds'].append({'institution_id': institution, 'stage': 'institution_depth',
                                               'error': institution + ' configured listing limit reached before history boundary'})
                if institution == 'pck_pension':
                    current_page = int(dict(parse_qsl(urlsplit(url).query))[config['page_param']])
                    final_page = pck.last_page(html, url, config)
                    regular = [row for row in rows if not row.get('pinned')]
                    oldest_year = str(int(checked_at[:4]) - config.get('history_years', 4) + 1)
                    older = regular and all(row['date'][:4] < oldest_year for row in regular)
                    if current_page == final_page or older:
                        stopped_searches.add(search)
                        coverage.setdefault('listing_boundaries', []).append({'search': search, 'page': current_page,
                            'boundary': 'observed_older_page' if older else 'observed_final_page'})
                    elif current_page == config['pages']:
                        result['holds'].append({'institution_id': institution, 'stage': 'institution_depth',
                                               'error': 'PCK configured listing limit reached before history boundary'})
                for row in rows:
                    if 'institution_id' in row and row['institution_id'] != institution:
                        continue
                    if (re.search(r'위탁|운용사|블라인드|PEF?|사모|선정', row['title'], re.I)
                            and classify_scope(row['title'], row['title']) != 'outside'):
                        if (row['date'] >= cutoff if cutoff else row['date'][:4] >= str(int(checked_at[:4]) - config.get('history_years', 4) + 1)):
                            key = row['source_id'] if config.get('lookback_days') else row['url']
                            previous = candidates.get(key)
                            if previous and any(previous[0][k] != row[k] for k in ('title', 'date')):
                                raise ValueError('Conflicting official listing identity metadata')
                            candidates.setdefault(key, (row, url))
                        else:
                            coverage['older_rows_skipped'] = coverage.get('older_rows_skipped', 0) + 1
            except Exception as exc:
                if config.get('lookback_days'):
                    stopped_searches.add(search)
                result['holds'].append({'institution_id': institution, 'stage': 'institution_listing',
                                        'url': url, 'error': str(exc)})
        ordered = sorted(candidates.values(), key=lambda item: (item[0]['date'], item[0]['url']), reverse=True)
        limit = config.get('max_details', MAX_DETAILS)
        coverage['candidate_count'] = len(ordered)
        coverage['detail_budget'] = limit
        if len(ordered) > limit:
            result['holds'].append({'institution_id': institution, 'stage': 'institution_depth',
                                    'error': 'detail budget reached; older candidates retained in listing receipts'})
        for row, listing_url in ordered[:limit]:
            try:
                raw = fetch(row['url'], listing_url)
                html = raw.decode('utf-8') if config.get('response_format') == 'json' else _html(raw)
                resolution = None
                request = getattr(adapter(config), 'attachment_request', lambda *a: None)(html, row['url'], config)
                if request:
                    try:
                        _same_host(request, config)
                        if request not in resolver_cache:
                            text = decode_html(fetch(request, row['url']))
                            resolver_cache[request] = {'url':request,'text':text,'sha256':digest(text),
                                'kind':'attachment_listing' if institution=='mmaa' else 'resolver_script'}
                        resolution = resolver_cache[request]
                    except Exception as error:
                        result['holds'].append({'institution_id':institution,'stage':'institution_attachment_discovery',
                                                'notice_url':row['url'],'url':request,'error':str(error)})
                detail = _detail(html, row['url'], config, resolution)
                titles_match = getattr(adapter(config), 'titles_match', lambda a,b: a==b)
                if detail['date'] != row['date'] or not titles_match(row['title'], detail['title']):
                    raise ValueError('official listing/detail title or date differs')
                n = {**detail, 'institution_id': institution, 'source_id': row['source_id'],
                     'url': row['url'], 'checked_at': checked_at, 'source_channel': 'institution_board',
                     'discovery_provenance': {'kind': 'institution_board_v1',
                         'listing': receipts[listing_url], 'detail_html': html, 'detail_sha256': digest(html)},
                     'attachment_hashes': {}, 'attachment_texts': {}, 'attachment_bytes': {}}
                if resolution is not None:
                    n['discovery_provenance']['attachment_resolution'] = resolution
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
        coverage['regional_fetch_count'] = getattr(fetch, 'regional_fetches', 0)
        coverage['native_ipv4_fetch_count'] = getattr(fetch, 'native_ipv4_fetches', 0)
        coverage['dns_ipv4_fetch_count'] = getattr(fetch, 'dns_ipv4_fetches', 0)
        coverage['alternate_dns_lookup_count'] = getattr(fetch, 'alternate_dns_lookups', 0)
    return result


def validate_notice(raw, checked_at, config=None):
    n = copy.deepcopy(raw)
    config = config or load_configs()[n['institution_id']]
    if n['institution_id'] != config['institution_id'] or n['source_channel'] != 'institution_board':
        raise ValueError('institution collection identity mismatch')
    _same_host(n['url'], config)
    proof = n['discovery_provenance']
    listing = proof['listing']
    if (proof['kind'] != 'institution_board_v1' or listing['url'] not in listing_receipt_urls(config)
            or digest(listing['html']) != listing['sha256']
            or digest(proof['detail_html']) != proof['detail_sha256']):
        raise ValueError('institution source receipt mismatch')
    rows = adapter(config).parse_listing(listing['html'], listing['url'], config)
    if config.get('lookback_days'):
        adapter(config).last_page(listing['html'], listing['url'], config)
    detail = _detail(proof['detail_html'], n['url'], config, proof.get('attachment_resolution'))
    titles_match = getattr(adapter(config), 'titles_match', lambda a,b: a==b)
    if not any(all(row[k] == n[k] for k in ('url', 'date', 'source_id')) and titles_match(row['title'], n['title']) for row in rows):
        raise ValueError('notice was not observed on the configured official listing')
    if any(n[k] != detail[k] for k in ('title', 'date', 'body', 'attachments')):
        raise ValueError('notice differs from official detail receipt')
    if n['institution_id'] == 'pck_pension' and n.get('related_notice_urls', []) != detail['related_notice_urls']:
        raise ValueError('PCK related notice links differ from official body receipt')
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
    parser.add_argument('--institution', choices=sorted(load_configs()), help='Verify one configured institution without publication')
    args = parser.parse_args()
    result = collect({args.institution: load_configs()[args.institution]} if args.institution else None)
    args.output.write_text(json.dumps(result, ensure_ascii=False))
    print(json.dumps({'notices': len(result['notices']), 'holds': len(result['holds']),
                      'coverage': result['coverage']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
