#!/usr/bin/env python3
"""Preserve LP report evidence in private storage while keeping recent DB reports.

No report rows, source documents, review decisions or published pages are deleted.
Archive uploads and full readback verification happen with no database lease.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOCK = 728160921
TABLE = 'lp_program_private.collection_runs'
MIN_REPORT_BYTES = 4096
STORAGE_BUDGET = 900_000_000  # Leave headroom below the free storage allowance.
MAX_REWRITE_BYTES = 256 * 1024 * 1024


class MaintenanceError(RuntimeError):
    pass


def connect(*, session=False, autocommit=False):
    import psycopg
    options = {}
    if session:
        config = psycopg.conninfo.conninfo_to_dict(os.environ['SUPABASE_DB_URL'])
        host = config.get('host', '')
        if not host.endswith('.pooler.supabase.com') or ',' in host or config.get('port') != '6543':
            raise MaintenanceError('Session maintenance requires the configured Supabase transaction pooler')
        options['port'] = 5432
    return psycopg.connect(os.environ['SUPABASE_DB_URL'], connect_timeout=15,
                          prepare_threshold=None, autocommit=autocommit,
                          application_name='lp-report-storage-maintenance', **options)


def readonly(conn):
    conn.execute('SET TRANSACTION READ ONLY')
    conn.execute("SET LOCAL statement_timeout='30s'")
    conn.execute("SET LOCAL lock_timeout='5s'")


def install_archive_guard():
    # Restrictive policies compose with every existing permissive policy. This
    # protects only the archive bucket; other services' storage stays unchanged.
    with connect() as conn:
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL statement_timeout='10s'")
        rls = conn.execute("SELECT relrowsecurity FROM pg_class WHERE oid='storage.objects'::regclass").fetchone()
        if not rls or rls[0] is not True:
            raise MaintenanceError('Storage row-level security is not enabled')
        row = conn.execute("SELECT permissive,roles,qual,with_check,cmd FROM pg_policies WHERE schemaname='storage' AND tablename='objects' AND policyname='lp_collection_report_archive_guard'").fetchone()
        if not row:
            conn.execute("CREATE POLICY lp_collection_report_archive_guard ON storage.objects AS RESTRICTIVE FOR ALL TO anon,authenticated USING (bucket_id <> 'lp-collection-reports') WITH CHECK (bucket_id <> 'lp-collection-reports')")
        else:
            expected = "bucket_id<>'lp-collection-reports'::text"
            expressions = [None if expr is None else ''.join(expr.split()).replace('(', '').replace(')', '') for expr in row[2:4]]
            if row[0] != 'RESTRICTIVE' or row[4] != 'ALL' or set(row[1]) != {'anon','authenticated'} or expressions != [expected,expected]:
                raise MaintenanceError('Existing archive access guard differs; no permissions changed')


def protected_runs(conn, keep=3):
    if type(keep) is not int or not 3 <= keep <= 20:
        raise MaintenanceError('Keep between three and twenty recent reports')
    ids = {row[0] for row in conn.execute(
        f'SELECT run_id FROM {TABLE} ORDER BY collected_at DESC, run_id DESC LIMIT %s', (keep,)).fetchall()}
    current = conn.execute('SELECT run_id FROM lp_program_private.program_state WHERE id=1').fetchone()
    if current:
        ids.add(current[0])
    return ids


def inspect(keep=3):
    with connect() as conn:
        readonly(conn)
        protected = protected_runs(conn, keep)
        rows = conn.execute(f'SELECT run_id,collected_at,pg_column_size(report) FROM {TABLE} ORDER BY collected_at DESC,run_id DESC LIMIT 5001').fetchall()
        if len(rows) > 5000:
            raise MaintenanceError('Report inventory exceeds bounded inspection size')
        database_bytes, table_bytes = conn.execute(
            f"SELECT pg_database_size(current_database()),pg_total_relation_size('{TABLE}')").fetchone()
        storage_bytes = conn.execute("SELECT COALESCE(sum(CASE WHEN metadata->>'size' ~ '^[0-9]+$' THEN (metadata->>'size')::bigint ELSE 0 END),0) FROM storage.objects").fetchone()[0]
        current = conn.execute("SELECT run_id,updated_at,md5(pages::text),ARRAY(SELECT jsonb_object_keys(pages)) FROM lp_program_private.program_state WHERE id=1").fetchone()
        reviews = conn.execute("SELECT count(*),md5(COALESCE(jsonb_agg(to_jsonb(d) ORDER BY id),'[]'::jsonb)::text) FROM lp_program_private.review_decisions d").fetchone()
        archive_count = conn.execute(f"SELECT count(*) FROM {TABLE} WHERE CASE WHEN pg_column_size(report)<=%s THEN report ? '_lp_report_archive' ELSE false END", (MIN_REPORT_BYTES,)).fetchone()[0]
    inventory = [{'run_id': row[0], 'collected_at': row[1].isoformat(), 'stored_bytes': row[2],
                  'protected': row[0] in protected} for row in rows]
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'database_bytes': int(database_bytes),
            'table_bytes': int(table_bytes), 'storage_bytes': int(storage_bytes), 'archive_count': archive_count, 'rows': inventory,
            'protected_runs': sorted(protected), 'candidate_runs': [row['run_id'] for row in reversed(inventory)
                if not row['protected'] and row['stored_bytes'] > MIN_REPORT_BYTES],
            'published': None if not current else {'run_id': current[0], 'updated_at': current[1].isoformat(),
                'pages_md5': current[2], 'page_names': sorted(current[3])},
            'reviews': {'count': reviews[0], 'md5': reviews[1]}}


def read_report(run_id):
    with connect() as conn:
        readonly(conn)
        row = conn.execute(f'SELECT report,xmin::text FROM {TABLE} WHERE run_id=%s', (run_id,)).fetchone()
    if not row:
        raise MaintenanceError('Requested report does not exist')
    return row


def replace_with_stub(run_id, revision, stub, keep=3):
    from services.lp.src.lp_report_archive import validate_locator
    validate_locator(stub, run_id)
    encoded = json.dumps(stub, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    with connect() as conn:
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL statement_timeout='30s'")
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        if run_id in protected_runs(conn, keep):
            return 'protected'
        row = conn.execute(f'UPDATE {TABLE} SET report=%s::jsonb WHERE run_id=%s AND xmin::text=%s RETURNING run_id',
                           (encoded, run_id, revision)).fetchone()
        return 'archived' if row else 'changed'


def archive(store, *, keep=3, limit=50, public_key=None):
    from services.lp.src.lp_report_archive import is_archive_stub, validate_locator, estimate_report
    if type(limit) is not int or not 1 <= limit <= 100:
        raise MaintenanceError('Archive batch must contain one to one hundred reports')
    before = inspect(keep)
    results = []
    for run_id in before['candidate_runs'][:limit]:
        report, revision = read_report(run_id)
        if is_archive_stub(report):
            continue
        # Compression/HTTP are deliberately outside a pooled database transaction.
        estimate = estimate_report(report)
        with connect() as conn:
            readonly(conn)
            used = conn.execute("SELECT COALESCE(sum(CASE WHEN metadata->>'size' ~ '^[0-9]+$' THEN (metadata->>'size')::bigint ELSE 0 END),0) FROM storage.objects").fetchone()[0]
        if int(used) + int(estimate) > STORAGE_BUDGET:
            raise MaintenanceError('Private archive storage budget would be exceeded; original DB reports retained')
        stub = store.put_verified(run_id, report)
        descriptor = validate_locator(stub, run_id)
        store.assert_private(stub, public_key)
        raw = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if hashlib.sha256(raw).hexdigest() != descriptor['raw_sha256'] or len(raw) != descriptor['raw_bytes']:
            raise MaintenanceError('Archive descriptor differs from the source report')
        status = replace_with_stub(run_id, revision, stub, keep)
        result = {'run_id': run_id, 'status': status, 'raw_bytes': len(raw), 'manifest_bytes': descriptor['gzip_bytes']}
        results.append(result)
        print(json.dumps({'lp_archive_progress': result}), file=sys.stderr, flush=True)
    after = inspect(keep)
    if before['published'] != after['published'] or before['reviews'] != after['reviews']:
        raise MaintenanceError('Public state or review decisions changed during archive operation')
    return {'before': before, 'after': after, 'results': results}


def restore(store, run_id):
    before = inspect()
    from services.lp.src.lp_report_archive import is_archive_stub, validate_locator
    stub, revision = read_report(run_id)
    if not is_archive_stub(stub):
        raise MaintenanceError('Requested report is not an archive descriptor')
    validate_locator(stub, run_id)
    report = store.restore(stub)
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    with connect() as conn:
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL statement_timeout='120s'")
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        row = conn.execute(f'SELECT report,xmin::text FROM {TABLE} WHERE run_id=%s FOR UPDATE', (run_id,)).fetchone()
        if not row or row != (stub, revision):
            raise MaintenanceError('Archive descriptor changed before restoration; no report overwritten')
        conn.execute(f'UPDATE {TABLE} SET report=%s::jsonb WHERE run_id=%s AND xmin::text=%s', (encoded, run_id, revision))
    after = inspect()
    if before['published'] != after['published'] or before['reviews'] != after['reviews'] or len(before['rows']) != len(after['rows']):
        raise MaintenanceError('Public state, review or report inventory changed during restoration')
    return {'before': before, 'after': after, 'restored_run_id': run_id, 'raw_bytes': len(encoded.encode())}


def verify_archives(store, *, limit=100):
    from services.lp.src.lp_report_archive import is_archive_stub, validate_locator
    with connect() as conn:
        readonly(conn)
        rows = conn.execute(f'SELECT run_id,report FROM {TABLE} WHERE pg_column_size(report)<=%s ORDER BY collected_at,run_id LIMIT 5001', (MIN_REPORT_BYTES,)).fetchall()
    if len(rows) > 5000:
        raise MaintenanceError('Archive inventory exceeds bounded verification size')
    archived = [(run_id, report) for run_id, report in rows if is_archive_stub(report)]
    if len(archived) > limit:
        raise MaintenanceError('Increase the bounded verification limit to cover all archives')
    results = []
    for run_id, stub in archived:
        descriptor = validate_locator(stub, run_id)
        restored = store.restore(stub)
        raw = json.dumps(restored, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if hashlib.sha256(raw).hexdigest() != descriptor['raw_sha256']:
            raise MaintenanceError('Restored report checksum mismatch')
        results.append({'run_id': run_id, 'raw_bytes': len(raw)})
    return {'verified': results}


def reclaim(*, full=True):
    before = inspect()
    live_bytes = sum(row['stored_bytes'] for row in before['rows'])
    archived = before['archive_count']
    if not archived or (full and live_bytes > MAX_REWRITE_BYTES):
        raise MaintenanceError('Reclaim requires archived reports and a bounded live table size')
    # VACUUM cannot run in a transaction. A session connection keeps this
    # LP-only maintenance lock/settings for the whole autocommit operation.
    with connect(session=True, autocommit=True) as conn:
        conn.execute("SET lock_timeout='5s'")
        conn.execute("SET statement_timeout='180s'")
        locked = conn.execute('SELECT pg_try_advisory_lock(%s)', (LOCK,)).fetchone()[0]
        if not locked:
            raise MaintenanceError('LP publication or review is active; reclaim skipped')
        try:
            fresh_live, fresh_archived = conn.execute(f"SELECT COALESCE(sum(pg_column_size(report)),0),count(*) FILTER (WHERE CASE WHEN pg_column_size(report)<=%s THEN report ? '_lp_report_archive' ELSE false END) FROM {TABLE}", (MIN_REPORT_BYTES,)).fetchone()
            if not fresh_archived or (full and fresh_live > MAX_REWRITE_BYTES):
                raise MaintenanceError('Report storage changed before the maintenance lock; reclaim skipped')
            command = 'VACUUM (FULL, ANALYZE)' if full else 'VACUUM (ANALYZE)'
            conn.execute(f'{command} {TABLE}')
        finally:
            conn.execute('SELECT pg_advisory_unlock(%s)', (LOCK,))
    after = inspect()
    if before['published'] != after['published'] or before['reviews'] != after['reviews'] or len(before['rows']) != len(after['rows']):
        raise MaintenanceError('Post-maintenance public/review/report inventory differs')
    return {'before': before, 'after': after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['inspect', 'archive', 'verify', 'restore', 'reclaim'], default='inspect')
    parser.add_argument('--keep', type=int, default=3)
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--run-id')
    parser.add_argument('--reuse-space', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.mode == 'inspect':
            result = inspect(args.keep)
        else:
            from services.lp.src.lp_report_archive import ArchiveStore
            store = ArchiveStore(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
            if args.mode == 'archive':
                public_key = os.environ['SUPABASE_PUBLISHABLE_KEY']
                install_archive_guard()
                result = archive(store, keep=args.keep, limit=args.limit, public_key=public_key)
                if args.reuse_space and any(row['status']=='archived' for row in result['results']):
                    result['reuse_space'] = reclaim(full=False)
            elif args.mode == 'reclaim':
                verified = verify_archives(store, limit=args.limit)
                result = reclaim()
                result['verified_count'] = len(verified['verified'])
            elif args.mode == 'verify':
                result = verify_archives(store, limit=args.limit)
            else:
                if not args.run_id:
                    raise MaintenanceError('Restore requires an exact run ID')
                result = restore(store, args.run_id)
        output = {'mode': args.mode, 'status': 'ok', **result}
    except Exception as error:
        output = {'mode': args.mode, 'status': 'error', 'error_type': type(error).__name__}
        if isinstance(error, MaintenanceError) or type(error).__name__ == 'ArchiveError':
            output['reason'] = str(error)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(output, ensure_ascii=False, default=str))
        print(json.dumps(output, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from None
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, default=str))
    print(json.dumps(output, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
