"""Read-only metadata inventory of LP's retained documents; no origin HTTP."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

try:
    from .collect_lp_original_notices import load_channels
except ImportError:
    from collect_lp_original_notices import load_channels

ROOT = Path(__file__).resolve().parents[3]
MAX_ROWS = 10000
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
# Never transfer body, listing/detail HTML, contact fields, or attachment bytes.
INDEX_SQL = """
SELECT CASE WHEN document->>'owner_closed' IN ('1','true')
                 OR document->>'restricted' IN ('1','true')
                 OR document#>>'{discovery_provenance,owner_closed}' IN ('1','true')
            THEN jsonb_build_object('restricted',true)
            ELSE jsonb_build_object(
                'institution_id',document->>'institution_id',
                'url',source_url,'content_hash',content_hash,
                'date',document->>'date','title',document->>'title',
                'source_id',document->>'source_id',
                'source_sha256',document->>'sha256',
                'body_present',COALESCE(jsonb_typeof(document->'body')='string'
                                       AND btrim(document->>'body')<>'',false),
                'attachment_hashes',COALESCE(document->'attachment_hashes','{}'::jsonb),
                'event_type',document->>'event_type') END,
       count(*) OVER ()
FROM lp_program_private.documents
ORDER BY source_url,content_hash
LIMIT %s
"""


def issuer_index(channels=None, targets=None):
    if channels is None:
        channels = load_channels()
    if targets is None:
        scope = json.loads((ROOT/'data/lp_blind_contest_scope.json').read_text())
        targets = set(scope['confirmed_institution_ids'] + scope['priority_verification_ids'])
    hosts = defaultdict(set)
    for iid, values in channels.items():
        if iid in targets:
            for host in values:
                hosts[host.lower().removeprefix('www.')].add(iid)
    return set(targets), hosts


def resolve_issuer(record, targets, hosts):
    declared = record.get('institution_id')
    if declared is not None:
        return (declared, 'declared') if declared in targets else (None, 'unrecognized_declared')
    try:
        host = (urlsplit(record['url']).hostname or '').lower().removeprefix('www.')
    except (ValueError, TypeError):
        return None, 'unknown_host'
    matches = hosts.get(host, set())
    return (next(iter(matches)), 'unique_configured_host') if len(matches) == 1 else (None, 'unknown_or_shared_host')


def export_index(conn, *, row_limit=MAX_ROWS, channels=None, targets=None):
    if type(row_limit) is not int or not 1 <= row_limit <= MAX_ROWS:
        raise ValueError('LP history index row limit outside supported range')
    targets, hosts = issuer_index(channels, targets)
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    conn.execute("SET LOCAL statement_timeout='120s'")
    state = conn.execute('SELECT run_id FROM lp_program_private.program_state WHERE id=1').fetchone()
    rows = conn.execute(INDEX_SQL, (row_limit + 1,)).fetchall()
    total = rows[0][1] if rows else 0
    if type(total) is not int or total < 0 or len(rows) != min(total, row_limit + 1):
        raise ValueError('LP document metadata count is inconsistent')
    records, resolutions, excluded = [], Counter(), 0
    for metadata, _ in rows[:row_limit]:
        if metadata.get('restricted') is True:
            excluded += 1
            continue
        iid, method = resolve_issuer(metadata, targets, hosts)
        record = dict(metadata)
        record['institution_id'] = iid
        records.append(record)
        resolutions[method] += 1
    return {'kind':'lp_document_index_v1', 'checked_at':datetime.now(timezone.utc).isoformat(),
            'snapshot_run_id':state[0] if state else None,
            'database_index_complete':total <= row_limit, 'row_limit':row_limit,
            'database_rows':len(records), 'database_total_rows':total,
            'scanned_rows':min(len(rows),row_limit), 'restricted_rows_excluded':excluded,
            'issuer_resolution_counts':dict(resolutions), 'records':records,
            'record_scope':'All retained LP document source types and versions, including reposts; not PE businesses.',
            'validation':'metadata_only_no_source_replay', 'source_history_complete':False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--row-limit', type=int, default=MAX_ROWS)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        import psycopg
        with psycopg.connect(os.environ.get('LP_SUPABASE_DB_URL') or os.environ['SUPABASE_DB_URL'],
                              connect_timeout=20, prepare_threshold=None,
                              application_name='lp-history-index') as conn:
            report = export_index(conn, row_limit=args.row_limit)
        payload = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        if len(payload.encode()) > MAX_OUTPUT_BYTES:
            raise ValueError('LP metadata exceeds output size limit')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
        print(json.dumps({k:report[k] for k in ('database_index_complete','database_rows','database_total_rows',
                                                'restricted_rows_excluded','snapshot_run_id')}))
    except Exception as error:
        # A connection error must not print credentials, DSNs, or document values.
        raise SystemExit('LP read-only metadata index failed: '+type(error).__name__) from None


if __name__ == '__main__':
    main()
