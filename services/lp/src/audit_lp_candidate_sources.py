"""Resolve remaining discovery clues on official sources, without publication.

Third-party titles/links select a search only. Official board receipts and
official detail fields supply every retained fact. A missing or ambiguous
source remains unresolved; no selected-notice registry is used.
"""
import argparse
import copy
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

try:
    from . import audit_lp_official_inventory as inventory
    from .audit_lp_discovery_coverage import normalize_title
    from .collect_lp_institution_boards import Session, decode_html, load_configs, adapter
    from .collect_lp_original_notices import parse_original, load_aliases, original_body_hash
    from .discover_lp_original_boards import channels, page_url, listing_links
    from .collect_kexim_programs import parse_detail as parse_kexim
except ImportError:
    import audit_lp_official_inventory as inventory
    from audit_lp_discovery_coverage import normalize_title
    from collect_lp_institution_boards import Session, decode_html, load_configs, adapter
    from collect_lp_original_notices import parse_original, load_aliases, original_body_hash
    from discover_lp_original_boards import channels, page_url, listing_links
    from collect_kexim_programs import parse_detail as parse_kexim


def key_title(title, names):
    for name in sorted(names, key=len, reverse=True):
        title = title.replace(name, '')
    return normalize_title(title)


def official_scope(source):
    """Conservative exclusions from a verified detail body, never a feed title."""
    title, body = source['title'], source['body']
    # A private-equity offer is not excluded because eligibility mentions listed
    # holdings, performance evaluation, or prior feasibility studies.
    if re.search(r'(?<![A-Za-z])PEF?(?![A-Za-z])|기관전용|경영참여형', title + ' ' + body, re.I):
        return 'scope_unconfirmed', None
    if ('사업타당성조사' in title and '지원사업' in title
            and '사업타당성조사 지원사업' in body and '신청기업' in body):
        return 'outside_policy', 'feasibility_study_support'
    if (re.search(r'주식형.*(?:위탁운용사|운용사)', title)
            and re.search(r'투자대상\s*[:：-]?\s*.{0,30}상장\s*주식', body)
            and not re.search(r'비상장|사모펀드|기관전용', body)):
        return 'outside_policy', 'listed_equity_mandate'
    if ('성과평가' in title and re.search(r'성과평가\s*수행을\s*위한\s*평가기관\s*선정', body)
            and '제한경쟁입찰' in body and '계약방법' in body):
        return 'outside_policy', 'performance_evaluation_procurement'
    return 'scope_unconfirmed', None


def sema_identity(url, config):
    p = urlsplit(url); q = parse_qs(p.query)
    if (p.scheme != 'https' or p.hostname != 'www.sema.or.kr' or p.port not in {None, 443}
            or p.username or p.password or p.fragment or p.path != config['detail_path']
            or len(q.get('nttId', [])) != 1 or not re.fullmatch('[0-9]+', q['nttId'][0])):
        raise ValueError('SEMA official detail route or identity mismatch')
    return q['nttId'][0]


def sema_configs():
    primary = channels()['sema']
    result = {primary['listing_url']: primary}
    with (inventory.ROOT / 'data/lp_commitment_sources.csv').open() as stream:
        for row in csv.DictReader(stream):
            if row['lp_code'] != 'sema' or row['is_active'] != '1':
                continue
            url = row['locator']; p = urlsplit(url)
            if (p.scheme != 'https' or p.hostname != 'www.sema.or.kr' or p.port not in {None, 443}
                    or p.username or p.password or p.fragment
                    or not re.fullmatch('/sema/bbs/B[0-9]{7}/list.do', p.path)):
                raise ValueError('Unsupported configured SEMA board')
            result[url] = {**primary, 'listing_url': url, 'detail_path': p.path.replace('/list.do','/view.do')}
    return list(result.values())


def resolve(discovery, official_inventory, *, fetch_factory=None, as_of=None, sema_channels=None,
            candidate_limit=20):
    if type(candidate_limit) is not int or not 1 <= candidate_limit <= 20:
        raise ValueError('Candidate limit must be an integer between 1 and 20')
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'mode': 'read_only_official_source_verification',
              'sources': [], 'receipts': [], 'holds': [], 'complete': False, 'remaining_count': 0}
    if discovery.get('status') != 'ok':
        report['holds'].append({'stage': 'discovery', 'reason': 'Discovery comparison unavailable'})
        return report
    candidates = [n for n in discovery['items'] if n['status'] in {'official_link_to_verify', 'official_source_needed'}]
    seen = {(n['institution_id'], n.get('official_url')) for n in candidates}
    for entry in official_inventory.get('institutions', []):
        for row in entry['rows']:
            if (row['relevant'] and row['disposition'] == 'not_in_archive'
                    and row['title_scope'] in {'scope_unconfirmed', 'pe_blind_title', 'mixed_pe_vc'}
                    and (entry['institution_id'], row['url']) not in seen):
                candidates.append({'id': 'inventory:' + row['source_id'], 'institution_id': entry['institution_id'],
                                   'title': row['title'], 'official_url': row['url']})
                seen.add((entry['institution_id'], row['url']))
    candidates = sorted(candidates, key=lambda n: (n['institution_id'], n['id'],
                                                    n.get('official_url') or '', n['title']))
    aliases = load_aliases()
    configs = load_configs()
    cache = {}; sessions = {}; total_bytes = 0
    def get(institution, url, config, kind):
        nonlocal total_bytes
        if url in cache:
            return cache[url]
        if total_bytes >= 20 * 1024 * 1024:
            raise ValueError('Official verification body budget exhausted')
        if institution not in sessions:
            sessions[institution] = (fetch_factory(institution, config) if fetch_factory else
                                      inventory.kexim_fetcher() if institution == 'kexim' else Session(config))
        raw = sessions[institution](url)
        total_bytes += len(raw)
        if total_bytes > 20 * 1024 * 1024:
            raise ValueError('Official verification body budget exceeded')
        html = decode_html(raw)
        report['receipts'].append({'institution_id': institution, 'kind': kind, 'url': url,
                                  'html': html, 'sha256': hashlib.sha256(html.encode()).hexdigest()})
        cache[url] = raw
        return raw
    for position, candidate in enumerate(candidates):
        institution = candidate['institution_id']
        names = aliases.get(institution, [])
        item = {'discovery_id': candidate['id'], 'institution_id': institution, 'discovery_title': candidate['title'],
                'status': 'unresolved', 'official_notice': None, 'classification': 'scope_unconfirmed',
                'candidate': copy.deepcopy(candidate)}
        report['sources'].append(item)
        if position >= candidate_limit:
            item.update(status='pending', reason='candidate_budget')
            report['remaining_count'] += 1
            report['holds'].append({'institution_id': institution, 'discovery_id': candidate['id'],
                                    'stage': 'official_candidate', 'reason': 'candidate_budget'})
            continue
        try:
            if institution == 'kexim' or (institution in configs and (institution != 'sema' or candidate.get('official_url'))):
                config = configs.get(institution, {'institution_id': institution, 'listing_url': inventory.CORE.get(institution)})
                wanted = inventory.notice_key(institution, candidate['official_url']) if candidate.get('official_url') else None
                matches = {}
                for receipt in official_inventory['receipts']:
                    if receipt['institution_id'] != institution:
                        continue
                    if institution == 'kexim':
                        p = urlsplit(receipt['url'])
                        if p.scheme != 'https' or p.hostname != 'www.koreaexim.go.kr' or p.path != '/HPHKBI039M01':
                            raise ValueError('KEXIM official listing receipt route mismatch')
                    if hashlib.sha256(receipt['html'].encode()).hexdigest() != receipt['sha256']:
                        raise ValueError('Official inventory receipt fingerprint mismatch')
                    rows = (inventory.core_rows(institution, receipt['html'], receipt['url']) if institution == 'kexim'
                            else adapter(config).parse_listing(receipt['html'], receipt['url'], config))
                    for row in rows:
                        identity = inventory.notice_key(institution, row['url'])
                        if (wanted is None or identity == wanted) and key_title(row['title'], names) == key_title(candidate['title'], names):
                            matches[identity] = (row, receipt)
                if len(matches) != 1:
                    raise ValueError('Candidate not uniquely observed on official institution listing')
                wanted, (row, receipt) = next(iter(matches.items()))
                report['receipts'].append({**receipt, 'kind': 'listing'})
                raw = get(institution, row['url'], config, 'detail')
                source = (parse_kexim(wanted.split(':')[1], raw) if institution == 'kexim' else
                          dict(adapter(config).parse_detail(decode_html(raw), row['url'], config), url=row['url']))
                if source['date'] != row['date'] or key_title(source['title'], names) != key_title(row['title'], names):
                    raise ValueError('Official listing/detail metadata differs')
            elif institution == 'sema':
                matches = {}
                # A bounded asset/title search, never an attachment URL or ID
                # guessed from the third-party PDF filename.
                terms = ['일본주식', '일본', '재간접'] if '일본' in candidate['title'] else ['블라인드', '위탁운용사']
                for config in sema_configs() if sema_channels is None else sema_channels:
                    for term in terms:
                        query_config = {**config, 'search_params': {**config['search_params'], 'searchWrd': term}}
                        for page in (1, 2):
                            url = page_url(query_config, page)
                            html = decode_html(get(institution, url, config, 'listing'))
                            for row in listing_links(html, url, config):
                                if key_title(row['title'], names) != key_title(candidate['title'], names):
                                    continue
                                ident = sema_identity(row['url'], config)
                                matches.setdefault((config['detail_path'], ident), (row, config))
                if len(matches) != 1:
                    raise ValueError('Candidate not uniquely observed on official SEMA listing')
                row, config = next(iter(matches.values()))
                raw = get(institution, row['url'], config, 'detail')
                source = parse_original(decode_html(raw), row['url'])
                source['url'] = row['url']
                if not source.get('date') or key_title(source['title'], names) != key_title(row['title'], names):
                    raise ValueError('Official SEMA detail title or publication date missing/different')
            else:
                raise ValueError('Official candidate resolver not connected for this institution')
            # Never substitute detection/receive time for the official date.
            end = as_of or datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
            if source['date'] > end:
                raise ValueError('Official candidate has a future publication date')
            source.update(institution_id=institution, checked_at=report['checked_at'], sha256=original_body_hash(source))
            scope, reason = official_scope(source)
            item.update(status='official_source_verified', official_notice=source, classification=scope, scope_reason=reason)
        except (ValueError, KeyError, TypeError, OSError) as error:
            item['reason'] = str(error)
            report['holds'].append({'institution_id': institution, 'stage': 'official_candidate', 'reason': str(error)})
    report['complete'] = all(n['status'] == 'official_source_verified' for n in report['sources'])
    report['summary'] = {'candidates': len(candidates), 'verified': sum(n['status'] == 'official_source_verified' for n in report['sources']),
                         'attempted': min(len(candidates), candidate_limit), 'candidate_limit': candidate_limit,
                         'complete': report['complete'], 'remaining_count': report['remaining_count'],
                         'outside_policy_verified': sum(n['classification'] == 'outside_policy' for n in report['sources']),
                         'scope_unconfirmed': sum(n['classification'] == 'scope_unconfirmed' for n in report['sources']),
                         'unresolved': sum(n['status'] != 'official_source_verified' for n in report['sources'])}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discovery', required=True, type=Path)
    parser.add_argument('--inventory', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--candidate-limit', type=int, default=20)
    args = parser.parse_args()
    report = resolve(json.loads(args.discovery.read_text()), json.loads(args.inventory.read_text()),
                     candidate_limit=args.candidate_limit)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report.get('summary', {'unresolved': len(report['holds'])})))


if __name__ == '__main__':
    main()
