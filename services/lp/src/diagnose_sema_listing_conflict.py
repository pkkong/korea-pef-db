"""Capture one registered failed SEMA listing before replaying its unchanged parser.

This read-only diagnosis neither repairs the parent run nor approves publication.
Only the existing institution Session performs production HTTP (20s/2 attempts).
"""
import argparse
import base64
import copy
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.error import HTTPError

try:
    from . import collect_lp_institution_boards as boards
    from . import lp_board_adapter_sema as sema
except ImportError:
    import collect_lp_institution_boards as boards
    import lp_board_adapter_sema as sema

KIND = 'sema_listing_conflict_diagnostic_v1'
CONFLICT = 'SEMA conflicting duplicate notice'
MAX_INPUT_BYTES = 150 * 1024 * 1024
MAX_RESPONSE_BYTES = boards.MAX_BYTES
MAX_OCCURRENCES = 200


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _parent_hash(parent):
    raw = json.dumps(parent, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('Parent collection exceeds size limit')
    return _hash(raw)


def _selection(parent):
    if not isinstance(parent, dict) or not isinstance(parent.get('holds'), list):
        raise ValueError('Collection failure report required')
    digest = _parent_hash(parent)
    holds = [h for h in parent['holds'] if isinstance(h, dict) and h.get('institution_id') == 'sema']
    if (len(holds) != 1 or holds[0].get('stage') != 'institution_listing'
            or holds[0].get('error') != CONFLICT):
        raise ValueError('Exactly one current SEMA duplicate-listing failure required')
    config = boards.load_configs()['sema']
    url = holds[0].get('url')
    # Exact regeneration rejects foreign hosts, extra/duplicate query parameters,
    # nonconfigured searches/pages, encoded aliases, ports and authentication.
    if not isinstance(url, str) or url not in set(boards.listing_urls(config)):
        raise ValueError('Failure URL is not an exact registered SEMA request')
    return config, url, digest


def _serialize(node):
    if isinstance(node, str):
        return escape(node, quote=False)
    content = ''.join(_serialize(child) for child in node.children)
    if not node.tag:
        return content
    attrs = ''.join(' ' + key + ('' if value is None else '="' + escape(value, quote=True) + '"')
                    for key, value in node.attrs.items())
    start = '<' + node.tag + attrs + '>'
    if node.tag in {'br', 'img', 'hr', 'meta', 'link', 'input', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'col'}:
        return start
    return start + content + '</' + node.tag + '>'


def _occurrences(html, url, config):
    """Replay each original parsed DOM row with the unchanged official adapter.

    There is no separate permissive title/date parser. The full source context
    is checked first, then other data rows are removed in independent copies.
    """
    root, _ = sema._context(html, url, config)
    table = sema._one(root.nodes('table', 'dataTbl'), 'SEMA diagnostic table')
    data_rows = [row for row in table.nodes('tr')
                 if any(isinstance(child, sema._Node) and child.tag == 'td' for child in row.children)]
    if len(data_rows) > MAX_OCCURRENCES:
        raise ValueError('SEMA diagnostic occurrence budget exceeded')
    occurrences, empty_rows = [], 0
    for position in range(len(data_rows)):
        isolated = copy.deepcopy(root)
        copied_table = sema._one(isolated.nodes('table', 'dataTbl'), 'SEMA diagnostic table')
        copied_rows = [row for row in copied_table.nodes('tr')
                       if any(isinstance(child, sema._Node) and child.tag == 'td' for child in row.children)]
        for index, row in enumerate(copied_rows):
            if index != position:
                row.parent.children.remove(row)
        parsed = sema.parse_listing(_serialize(isolated), url, config)
        if not parsed:
            empty_rows += 1
        elif len(parsed) == 1:
            occurrences.append({'position': position, **parsed[0]})
        else:
            raise ValueError('SEMA isolated row yielded multiple identities')
    grouped = defaultdict(list)
    for row in occurrences:
        grouped[row['source_id']].append(row)
    duplicates = []
    for ident, rows in grouped.items():
        if len(rows) < 2:
            continue
        fields = [key for key in ('url', 'title', 'date', 'pinned')
                  if any(row[key] != rows[0][key] for row in rows[1:])]
        duplicates.append({'source_id': ident, 'occurrences': rows, 'differing_fields': fields})
    return {'method': 'unchanged_adapter_per_isolated_source_dom_row', 'source_data_rows': len(data_rows),
            'empty_rows': empty_rows, 'occurrences': occurrences, 'duplicates': duplicates}


def _parse(raw, url, config, truncated=False, http_status=200):
    if http_status != 200:
        return {'status': 'not_parsed', 'error_code': 'http_error', 'http_status': http_status}
    if truncated:
        return {'status': 'not_parsed', 'error_code': 'response_size_limit'}
    try:
        html = boards._html(raw)
    except (ValueError, UnicodeError):
        return {'status': 'invalid_content', 'error_code': 'incomplete_or_unreadable_html'}
    compact = re.sub(r'\s+', '', html)
    if any(marker in compact for marker in ('로그인이필요', '열람권한이없', '접근권한이없', '비공개게시물', '접근이제한')):
        return {'status': 'invalid_content', 'error_code': 'protected_or_unavailable'}
    try:
        rows = sema.parse_listing(html, url, config)
    except (ValueError, UnicodeError) as error:
        code = 'conflicting_duplicate_notice' if str(error) == CONFLICT else 'invalid_listing'
        result = {'status': 'parser_error', 'error_code': code}
        if code == 'conflicting_duplicate_notice':
            try:
                result['occurrence_analysis'] = _occurrences(html, url, config)
            except (ValueError, UnicodeError):
                result['occurrence_analysis'] = {'status': 'not_available', 'error_code': 'strict_row_replay_failed'}
        return result
    try:
        last = sema.last_page(html, url, config)
    except (ValueError, UnicodeError):
        return {'status': 'parser_error', 'error_code': 'invalid_page_boundary', 'rows': rows}
    return {'status': 'parsed', 'rows': rows, 'last_page': last, 'confirmed_empty': not rows}


def _result(checked_at=None):
    return {'kind': KIND, 'checked_at': checked_at or datetime.now(timezone.utc).isoformat(),
            'institution_id': 'sema', 'parent_report_sha256': None, 'failed_url': None,
            'logical_requests': 0, 'transport_attempts': 'not_measured',
            'transport_policy': 'existing_institution_Session_20_seconds_max_2_attempts',
            'response': None, 'parser': {'status': 'not_attempted'}, 'success': False, 'errors': [],
            'previous_failure_resolved': False, 'audit_recovered': False,
            'database_writes': 0, 'published': False, 'pe_approval': False, 'selected_gp_approval': False}


def diagnose(report, fetch=None, *, checked_at=None, on_receipt=None):
    """Select and capture at most one request; optional checkpoint precedes parsing.

    Injected fetch receives the automatically selected URL and returns bytes.
    CLI uses on_receipt to atomically save raw evidence before calling a parser.
    """
    result = _result(checked_at)
    try:
        stamp = datetime.fromisoformat(result['checked_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Timezone required')
        config, url, parent_sha = _selection(report)
        result.update(parent_report_sha256=parent_sha, failed_url=url)
        if fetch is None:
            session = boards.Session(config)
            get = lambda target: session(target, config['listing_url'])
        else:
            get = fetch
        result['logical_requests'] = 1
        http_status = 200
        try:
            raw = get(url)
        except HTTPError as error:
            if error.geturl() != url:
                raise ValueError('Unexpected failed SEMA response route') from None
            # Reading the already-open rejected response adds no HTTP request.
            raw = error.read(MAX_RESPONSE_BYTES + 1)
            http_status = error.code
        if not isinstance(raw, bytes):
            raise TypeError('Byte response required')
        prefix = raw[:MAX_RESPONSE_BYTES]
        result['response'] = {'url': url, 'bytes': len(prefix), 'sha256': _hash(prefix),
                              'raw_base64': base64.b64encode(prefix).decode('ascii'),
                              'truncated': len(raw) > MAX_RESPONSE_BYTES, 'http_status': http_status}
        # This is assigned/checkpointed before _html, DOM or source-row parsing.
        if on_receipt is not None:
            on_receipt(copy.deepcopy(result))
        result['parser'] = _parse(prefix, url, config, result['response']['truncated'], http_status)
        result['success'] = result['parser']['status'] == 'parsed'
    except Exception as error:
        # Do not persist exception messages, response headers, cookies or secrets.
        result['errors'].append({'type': type(error).__name__,
                                  'code': 'invalid_input' if result['logical_requests'] == 0 else 'capture_failed'})
    return result


def verify(result, parent):
    """Replay saved raw bytes with current code, without invoking any transport."""
    config, url, parent_sha = _selection(parent)
    if (not isinstance(result, dict) or set(result) != set(_result()) or result['kind'] != KIND
            or result['institution_id'] != 'sema' or result['parent_report_sha256'] != parent_sha
            or result['failed_url'] != url or type(result['logical_requests']) is not int
            or result['logical_requests'] != 1 or result['transport_attempts'] != 'not_measured'):
        raise ValueError('SEMA diagnostic identity/parent mismatch')
    stamp = datetime.fromisoformat(result['checked_at'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('SEMA diagnostic observation time missing timezone')
    base = _result()
    for key in ('transport_policy', 'previous_failure_resolved', 'audit_recovered', 'database_writes',
                'published', 'pe_approval', 'selected_gp_approval'):
        if result[key] != base[key]:
            raise ValueError('SEMA diagnostic approval/transport claim differs')
    response = result['response']
    if response is None:
        if result['parser'] != {'status': 'not_attempted'} or result['success'] is not False or not result['errors']:
            raise ValueError('Uncaptured SEMA diagnostic cannot claim success')
        return copy.deepcopy(result['parser'])
    if (not isinstance(response, dict) or set(response) != {'url', 'bytes', 'sha256', 'raw_base64', 'truncated', 'http_status'}
            or response['url'] != url or type(response['truncated']) is not bool
            or type(response['http_status']) is not int or not 100 <= response['http_status'] <= 599
            or type(response['bytes']) is not int or not isinstance(response['raw_base64'], str)
            or len(response['raw_base64']) > (MAX_RESPONSE_BYTES + 2) // 3 * 4):
        raise ValueError('SEMA diagnostic raw response metadata differs')
    raw = base64.b64decode(response['raw_base64'], validate=True)
    if (len(raw) != response['bytes'] or len(raw) > MAX_RESPONSE_BYTES or _hash(raw) != response['sha256']
            or (response['truncated'] and len(raw) != MAX_RESPONSE_BYTES)):
        raise ValueError('SEMA diagnostic response hash/size differs')
    parsed = _parse(raw, url, config, response['truncated'], response['http_status'])
    if (result['parser'] != parsed or result['success'] is not (parsed['status'] == 'parsed') or result['errors']):
        raise ValueError('SEMA diagnostic parser result differs from raw response')
    return parsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / 'listing-conflict.json'
    def save(result):
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False))
        temporary.replace(target)
    try:
        if args.collection.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError('Collection input exceeds size limit')
        parent = json.loads(args.collection.read_text())
        result = diagnose(parent, on_receipt=save)
    except Exception as error:
        result = _result()
        result['errors'] = [{'type': type(error).__name__, 'code': 'invalid_input'}]
    save(result)
    print(json.dumps({k: result[k] for k in ('kind', 'success', 'logical_requests')}))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
