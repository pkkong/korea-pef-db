"""Replay the unchanged LP report INSERT against dedicated ephemeral PostgreSQL.

No production credentials, source requests, preparation/OCR, publication or
archive-policy changes. Outputs contain only bounded timings/counts/checksums.
"""
import argparse
import copy
import hashlib
import importlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

KIND = 'lp_report_storage_probe_v1'
LOCAL_DSN = 'postgresql://lp_probe:lp_probe@127.0.0.1:5432/lp_report_probe'
MAX_INPUT_BYTES = 150 * 1024 * 1024
SOURCE_FILES = ('kgrowth-collection.json', 'lp-priority-collection.json',
                'lp-shared-collection.json', 'lp-institution-collection.json')


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _stamp(value):
    if not isinstance(value, str):
        raise ValueError('Observation timestamp required')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Observation timezone required')
    return stamp


def local_connection_parameters(dsn):
    if not isinstance(dsn, str) or re.search(r'[\s\\\x00-\x1f\x7f]', dsn):
        raise ValueError('Only the dedicated local probe DSN is allowed')
    p = urlsplit(dsn)
    if (p.scheme != 'postgresql' or p.hostname not in ('localhost', '127.0.0.1')
            or p.port != 5432 or p.path != '/lp_report_probe' or p.query or p.fragment
            or p.username != 'lp_probe' or p.password != 'lp_probe'
            or p.netloc not in ('lp_probe:lp_probe@localhost:5432', 'lp_probe:lp_probe@127.0.0.1:5432')):
        raise ValueError('Only the dedicated local probe DSN is allowed')
    # Fixed loopback hostaddr defeats DNS/service-file/environment fallbacks.
    return {'host': '127.0.0.1', 'hostaddr': '127.0.0.1', 'port': 5432, 'dbname': 'lp_report_probe',
            'user': 'lp_probe', 'password': 'lp_probe', 'sslmode': 'disable', 'connect_timeout': 10,
            'prepare_threshold': None, 'application_name': 'lp-ephemeral-report-probe'}


def validate_provenance(collection, recovery, repository, *, now=None):
    now = now or datetime.now(timezone.utc)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository identity')
    checked = []
    for item, path, events, conclusions in (
        (collection, '.github/workflows/collect-kgrowth-programs.yml', {'schedule', 'workflow_dispatch'}, {'success', 'failure'}),
        (recovery, '.github/workflows/recover-lp-publication.yml', {'workflow_dispatch'}, {'success', 'failure', 'cancelled', 'timed_out'}),
    ):
        if (not isinstance(item, dict) or item.get('repository', {}).get('full_name') != repository
                or item.get('head_repository', {}).get('full_name', repository) != repository
                or item.get('path') != path or item.get('head_branch') != 'main'
                or item.get('event') not in events or item.get('status') != 'completed'
                or item.get('conclusion') not in conclusions or type(item.get('id')) is not int or item['id'] <= 0
                or not re.fullmatch(r'[0-9a-f]{40}', item.get('head_sha', ''))):
            raise ValueError('Untrusted source/recovery workflow provenance')
        created = _stamp(item['created_at'])
        if not timedelta(0) <= now - created <= timedelta(hours=48):
            raise ValueError('Use completed main evidence no older than 48 hours')
        checked.append(created)
    if checked[1] < checked[0] or collection['id'] == recovery['id']:
        raise ValueError('Recovery must follow the source collection')
    return {'collection': {k: collection[k] for k in ('id', 'path', 'head_sha', 'event', 'conclusion', 'created_at')},
            'recovery': {k: recovery[k] for k in ('id', 'path', 'head_sha', 'event', 'conclusion', 'created_at')},
            'repository': repository, 'checked_at': now.isoformat(),
            'dispatch_inputs_assumed_available': False, 'content_binding_required': True}


def _load(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_INPUT_BYTES:
        raise ValueError('Source input exceeds bounded byte limit')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Source report must be an object')
    _json(value)
    return value


def validate_bundles(original, recovery):
    """Bind a recovery to its source by immutable content, not dispatch inputs.

    Only raw-proof additions may replace a missing legacy preview: deletion of
    an old preview needs the same original file hash, actual retained bytes and
    a nonempty canonical extraction. This is benchmark lineage, not PE approval.
    """
    if set(original) != set(SOURCE_FILES) or set(recovery) != set(SOURCE_FILES) - {'kgrowth-collection.json'}:
        raise ValueError('Exact original/recovery input bundle required')
    decoded_original = {name: _load(raw) for name, raw in original.items()}
    decoded_recovery = {name: _load(raw) for name, raw in recovery.items()}
    for name in ('lp-shared-collection.json', 'lp-institution-collection.json'):
        if original[name] != recovery[name]:
            raise ValueError('Recovery issuer/shared bytes differ from the original collection')
    left, right = (x['lp-priority-collection.json'] for x in (decoded_original, decoded_recovery))
    if (left.get('checked_at') != right.get('checked_at') or not isinstance(left.get('sources'), dict)
            or not isinstance(right.get('sources'), dict) or set(left['sources']) != set(right['sources'])):
        raise ValueError('Recovery priority identity/time differs')
    _stamp(left['checked_at'])
    deleted_previews = 0; notices = 0
    core = ('source_id', 'url', 'title', 'date', 'body', 'sha256', 'attachments', 'attachment_hashes')
    for institution, source in left['sources'].items():
        target = right['sources'][institution]
        if (source.get('checked_at') != target.get('checked_at') or not isinstance(source.get('notices'), list)
                or not isinstance(target.get('notices'), list) or len(source['notices']) != len(target['notices'])):
            raise ValueError('Recovery priority source sequence differs')
        seen = set()
        for old, new in zip(source['notices'], target['notices']):
            if not isinstance(old, dict) or not isinstance(new, dict) or any(old.get(k) != new.get(k) for k in core):
                raise ValueError('Recovery notice core/source/file hash differs')
            enrichment = {'detail_proof', 'attachment_proofs', 'attachment_texts', 'checked_at'}
            if any(old.get(k) != new.get(k) for k in (set(old) | set(new)) - enrichment):
                raise ValueError('Recovery changed a non-proof notice field')
            for key in ('detail_proof', 'attachment_proofs'):
                if key in old and old[key] != new.get(key):
                    raise ValueError('Existing raw proof cannot be replaced')
            if old.get('checked_at') != new.get('checked_at'):
                _stamp(new.get('checked_at'))
                if not any(isinstance(p, dict) and p.get('checked_at') == new['checked_at']
                           for p in new.get('attachment_proofs', {}).values()):
                    raise ValueError('Changed notice observation lacks matching retained raw proof')
            identity = (str(old.get('source_id')), old.get('url'))
            if identity in seen: raise ValueError('Duplicate priority notice identity')
            seen.add(identity); notices += 1
            a, b = old.get('attachment_texts', {}), new.get('attachment_texts', {})
            if not isinstance(a, dict) or not isinstance(b, dict) or set(b) - set(a) or any(a[k] != v for k, v in b.items()):
                raise ValueError('Recovery cannot add/change legacy attachment text')
            for url in set(a) - set(b):
                proof = new.get('attachment_proofs', {}).get(url)
                expected_hash = old.get('attachment_hashes', {}).get(url)
                links = {item.get('url') if isinstance(item, dict) else item for item in old.get('attachments', [])}
                if (url not in links or not isinstance(proof, dict) or proof.get('sha256') != expected_hash
                        or not isinstance(proof.get('raw_base64'), str)
                        or len(proof['raw_base64']) > (25 * 1024 * 1024 + 2) // 3 * 4
                        or not isinstance(proof.get('extracted'), dict)
                        or not isinstance(proof['extracted'].get('text'), str) or not proof['extracted']['text'].strip()):
                    raise ValueError('Removed preview lacks same-file retained raw proof')
                import base64
                raw = base64.b64decode(proof['raw_base64'], validate=True)
                if (not raw or len(raw) > 25 * 1024 * 1024 or _sha(raw) != expected_hash
                        or base64.b64encode(raw).decode('ascii') != proof['raw_base64']):
                    raise ValueError('Removed preview raw/file hash mismatch')
                deleted_previews += 1
    collection = decoded_original['kgrowth-collection.json']
    if not isinstance(collection.get('notices'), list) or not collection['notices']:
        raise ValueError('Original growth collection is empty')
    _stamp(collection['checked_at'])
    return {'files': {name: {'original_bytes': len(original[name]), 'original_sha256': _sha(original[name]),
                            **({'recovery_bytes': len(recovery[name]), 'recovery_sha256': _sha(recovery[name])} if name in recovery else {})}
                      for name in SOURCE_FILES},
            'priority_notice_cores_matched': notices, 'deleted_legacy_previews_with_same_raw_file': deleted_previews,
            'source_inputs_unchanged': True, 'binding': 'issuer/shared exact bytes and priority original notice/file identities'}


def _publisher():
    # Imports definitions only. Never call prepare, connect, or publish.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    return importlib.import_module('publish_lp_programs')


def reconstruct_report(original, recovery, *, checked_at):
    validate_bundles(original, recovery)
    _stamp(checked_at)
    report = _load(original['kgrowth-collection.json'])
    report['priority_sources'] = _load(recovery['lp-priority-collection.json'])['sources']
    for name in ('shared', 'institution'):
        report[name + '_collection'] = _load(recovery['lp-' + name + '-collection.json'])
    report['collection_checked_at'] = report['checked_at']
    report['checked_at'] = checked_at
    return _publisher().clean_database_text(report)


def run_probe(report, *, dsn=LOCAL_DSN, connect=None, on_metadata=None, container_memory_limit=None):
    metadata = {'kind': KIND, 'success': False, 'stage': 'preflight', 'phases': [], 'error_type': None,
                'production_database_connections': 0, 'official_http_requests': 0, 'published': False,
                'pe_approval': False, 'selected_gp_approval': False,
                'environment': 'dedicated ephemeral PostgreSQL; not proof of production outage/capacity',
                'container_memory_limit_bytes': container_memory_limit}
    def emit():
        if on_metadata: on_metadata(copy.deepcopy(metadata))
    def stage(name, started, **counts):
        metadata['stage'] = name
        metadata['phases'].append({'phase': name, 'seconds': round(time.monotonic() - started, 4), **counts})
        emit()
    try:
        parameters = local_connection_parameters(dsn)
        metadata['local_target_verified'] = True; emit()
        if not isinstance(report, dict): raise ValueError('Probe report must be an object')
        if container_memory_limit is not None and (type(container_memory_limit) is not int or not 0 < container_memory_limit <= 512 * 1024 * 1024):
            raise ValueError('Ephemeral container memory cap must be at most 512 MiB')
        started = time.monotonic(); encoded = _json(report)
        if len(encoded) > MAX_INPUT_BYTES: raise ValueError('Probe report exceeds bounded size')
        metadata.update(report_bytes=len(encoded), report_sha256=_sha(encoded), top_level_fields=len(report))
        stage('serialization', started)
        if connect is None:
            import psycopg
            connect = psycopg.connect
        publisher = _publisher()
        started = time.monotonic(); metadata['stage'] = 'connect'; emit()
        with connect(**parameters) as conn:
            stage('connected', started)
            identity = conn.execute('SELECT current_database(),current_user').fetchone()
            if identity != ('lp_report_probe', 'lp_probe'):
                raise ValueError('Unexpected ephemeral database identity')
            conn.execute("SET LOCAL statement_timeout='120s'")
            conn.execute("SET LOCAL lock_timeout='20s'")
            conn.execute("SET LOCAL idle_in_transaction_session_timeout='300s'")
            settings = conn.execute("SELECT name,setting,unit FROM pg_settings WHERE name IN "
                                    "('server_version','server_version_num','shared_buffers','work_mem','maintenance_work_mem',"
                                    "'max_connections','statement_timeout','lock_timeout') ORDER BY name").fetchall()
            metadata['postgres_settings'] = [{'name': n, 'setting': value, 'unit': unit} for n, value, unit in settings]
            if not any(n == 'server_version_num' and str(value).startswith('17') for n, value, unit in settings):
                raise ValueError('PostgreSQL 17 is required for this bounded probe')
            started = time.monotonic()
            conn.execute('CREATE SCHEMA lp_program_private')
            conn.execute('CREATE TABLE lp_program_private.collection_runs '
                         '(run_id text PRIMARY KEY,institution text NOT NULL,collected_at timestamptz NOT NULL DEFAULT now(),report jsonb NOT NULL)')
            stage('ephemeral_schema', started)
            previous = publisher.publication_phase
            try:
                publisher.publication_phase = stage
                publisher.store_collection_report(conn, encoded.decode('utf-8'), 'lp-report-storage-probe', 'probe_only')
            finally:
                publisher.publication_phase = previous
            started = time.monotonic(); metadata['stage'] = 'readback'; emit()
            stored = conn.execute('SELECT report FROM lp_program_private.collection_runs WHERE run_id=%s', ('lp-report-storage-probe',)).fetchone()
            count = conn.execute('SELECT count(*) FROM lp_program_private.collection_runs').fetchone()[0]
            if stored is None or count != 1 or _json(stored[0]) != encoded:
                raise ValueError('Ephemeral report full canonical readback differs')
            metadata.update(readback_sha256=_sha(_json(stored[0])), rows=count, canonical_readback_equal=True)
            stage('readback_verified', started)
            metadata['stage'] = 'commit'; emit()
        metadata.update(success=True, stage='complete')
    except Exception as error:
        metadata['error_type'] = type(error).__name__
        code = getattr(error, 'sqlstate', None)
        if isinstance(code, str) and re.fullmatch('[0-9A-Z]{5}', code): metadata['sqlstate'] = code
    emit()
    return metadata


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original-dir', type=Path, required=True)
    p.add_argument('--recovery-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--dsn', default=LOCAL_DSN)
    p.add_argument('--container-memory-limit', type=int)
    args = p.parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    def save(value):
        target = args.output_dir / 'probe.json'; temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False)); temp.replace(target)
    try:
        local_connection_parameters(args.dsn)  # Before any source loading/import.
        def read(directory, name):
            path = directory / name
            if path.stat().st_size > MAX_INPUT_BYTES: raise ValueError('Probe input size exceeded')
            return path.read_bytes()
        original = {name: read(args.original_dir, name) for name in SOURCE_FILES}
        recovery = {name: read(args.recovery_dir, name) for name in SOURCE_FILES if name != 'kgrowth-collection.json'}
        binding = validate_bundles(original, recovery)
        report = reconstruct_report(original, recovery, checked_at=datetime.now(timezone.utc).isoformat())
        def emit(value): save({**value, 'source_binding': binding})
        result = run_probe(report, dsn=args.dsn, on_metadata=emit, container_memory_limit=args.container_memory_limit)
    except Exception as error:
        result = {'kind': KIND, 'success': False, 'stage': 'input_validation', 'error_type': type(error).__name__,
                  'production_database_connections': 0, 'official_http_requests': 0, 'published': False}
        save(result)
    print(json.dumps({k: result[k] for k in ('kind', 'success', 'stage', 'error_type')}))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
