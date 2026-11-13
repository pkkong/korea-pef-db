"""Bound the fixed LP publisher process without changing its transaction.

Child output is private and bounded. Only a validated successful receipt reaches
stdout; failures need a read-only publication-state check before another action.
"""
import argparse
import json
import math
import os
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

PUBLISHER = Path(__file__).resolve().with_name('publish_lp_programs.py')
MAX_TIMEOUT_SECONDS = 900
MAX_GRACE_SECONDS = 10
MAX_OUTPUT_BYTES = 64 * 1024
KIND = 'lp_publication_process_status_v1'
PHASE_COUNTS = {
    'gp_profile_contract': {'profiles'},
    'gp_profile_contract_unavailable': set(),
    'gp_profile_contract_previous': {'profiles'},
    'source_validation_and_pages': {'programs'},
    'collection_report_serialization': {'report_bytes'},
    'collection_report_archive': {'report_bytes', 'manifest_bytes'},
    'collection_report_archive_fallback': set(),
    'publication_lock': set(),
    'collection_report_parts': {'report_bytes', 'parts'},
    'collection_report_storage': set(),
    'evidence_storage': {'documents'},
    'public_payload_serialization_started': set(),
    'public_payload_serialization': {'data_bytes', 'pages_bytes'},
    'public_state_storage': set(),
}


class OutputLimitExceeded(ValueError):
    pass


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _json_load(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON fields')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Non-finite JSON value')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def publisher_command(arguments):
    if (not isinstance(arguments, (list, tuple)) or not arguments or len(arguments) > 32
            or any(not isinstance(a, str) or '\0' in a or len(a) > 8192 for a in arguments)
            or sum(len(a.encode('utf-8')) for a in arguments) > 32768):
        raise ValueError('Invalid publisher arguments')
    # Arguments occur after the fixed script, never in Python's option position.
    return [sys.executable, str(PUBLISHER), *arguments]


def validate_receipt(raw):
    if not isinstance(raw, bytes) or not raw.strip() or len(raw) > MAX_OUTPUT_BYTES:
        raise ValueError('Bounded publisher success receipt required')
    value = _json_load(raw.decode('utf-8'))
    counts = {'programs', 'notices', 'review', 'institution_notices', 'institution_validation_errors',
              'shared_notices', 'shared_originals', 'shared_offering_terms'}
    keys = counts | {'run_id', 'program_ids', 'programs_by_institution', 'institution_institutions', 'shared_institutions'}
    if (not isinstance(value, dict) or set(value) != keys or not isinstance(value.get('run_id'), str)
            or not re.fullmatch('[0-9a-f]{24}', value['run_id'])):
        raise ValueError('Unexpected publisher success receipt fields')
    if any(type(value[k]) is not int or not 0 <= value[k] <= 10_000_000 for k in counts):
        raise ValueError('Invalid publisher receipt counts')
    if value['programs'] < 1 or value['notices'] < 1:
        raise ValueError('Publisher receipt must retain nonempty programs and notices')
    ids = value['program_ids']
    if (not isinstance(ids, list) or len(ids) != value['programs'] or len(ids) > 10000
            or any(not isinstance(v, str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,199}', v) for v in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('Invalid publisher program identities')
    distribution = value['programs_by_institution']
    if (not isinstance(distribution, dict) or len(distribution) > 100
            or any(not isinstance(k, str) or not re.fullmatch('[a-z][a-z0-9_]{0,79}', k)
                   or type(v) is not int or not 0 <= v <= value['programs'] for k, v in distribution.items())
            or sum(distribution.values()) != value['programs']):
        raise ValueError('Publisher institution counts differ')
    for key in ('institution_institutions', 'shared_institutions'):
        values = value[key]
        if (not isinstance(values, list) or len(values) > 100
                or any(not isinstance(v, str) or not re.fullmatch('[a-z][a-z0-9_]{0,79}', v) for v in values)
                or values != sorted(set(values))):
            raise ValueError('Invalid receipt institution identities')
    return value


def _phase(line):
    try:
        value = _json_load(line.decode('utf-8'))
        name = value.get('lp_phase') if isinstance(value, dict) else None
        seconds = value.get('seconds') if isinstance(value, dict) else None
        if (not isinstance(name, str) or name not in PHASE_COUNTS
                or type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 100000):
            return None
        result = {'lp_phase': name, 'seconds': seconds}
        for key in PHASE_COUNTS[name]:
            count = value.get(key)
            if type(count) is not int or not 0 <= count <= 2**53:
                return None
            result[key] = count
        return result
    except (ValueError, TypeError, UnicodeError):
        return None


def _save(path, status):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(status, output, ensure_ascii=False, allow_nan=False)
    temporary.replace(path)


def _supervise(command, *, status_file, timeout_seconds, termination_grace_seconds=5, env=None):
    """Private test seam; the CLI can only obtain command via publisher_command."""
    status = {'kind': KIND, 'success': False, 'started_at': _stamp(), 'finished_at': None,
              'timeout_seconds': timeout_seconds if type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds) else None,
              'timed_out': False, 'error_type': None,
              'returncode': None, 'last_phase': None, 'phases': [], 'process_attempts': 0,
              'automatic_retry': False, 'parent_database_connections': 0, 'parent_official_http_requests': 0,
              'publication_state': 'unknown_requires_readonly_check', 'stdout_bytes_read': 0, 'stderr_bytes_read': 0,
              'termination': {'process_group': os.name == 'posix', 'term_sent': False, 'kill_sent': False}}
    process = None; receipt = None
    def emit(): _save(status_file, status)
    def stop(sig):
        try:
            if os.name == 'posix': os.killpg(process.pid, sig)
            elif sig == signal.SIGTERM: process.terminate()
            else: process.kill()
            return True
        except ProcessLookupError:
            return False
        except OSError as error:
            # A group can disappear between TERM and KILL. Keep the original
            # failure and try only the still-owned process, without raw errors.
            status['termination']['signal_error_type'] = type(error).__name__
            if process.poll() is None:
                try:
                    process.send_signal(sig)
                    status['termination']['process_only_fallback'] = True
                    return True
                except OSError:
                    pass
            return False
    try:
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS
                or type(termination_grace_seconds) not in (int, float) or not math.isfinite(termination_grace_seconds)
                or not 0 <= termination_grace_seconds <= MAX_GRACE_SECONDS):
            raise ValueError('Invalid bounded process timeout')
        emit()
        with tempfile.TemporaryDirectory(prefix='lp-writer-private-') as private:
            with open(Path(private) / 'stdout', 'w+b') as stdout, open(Path(private) / 'stderr', 'w+b') as stderr:
                os.chmod(stdout.name, 0o600); os.chmod(stderr.name, 0o600)
                status['process_attempts'] = 1
                started = time.monotonic()
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           env=env, shell=False, close_fds=True, start_new_session=(os.name == 'posix'))
                emit()
                stderr_pending = b''; failure = None; term_at = None; kill_at = None
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ, ('stdout', stdout))
                    selector.register(process.stderr, selectors.EVENT_READ, ('stderr', stderr))
                    while selector.get_map() or process.poll() is None:
                        now = time.monotonic()
                        if failure is None and now - started >= timeout_seconds:
                            failure = 'TimeoutError'; status['timed_out'] = True
                        if failure is not None and term_at is None:
                            status['error_type'] = failure
                            status['termination']['term_sent'] = stop(signal.SIGTERM)
                            term_at = now; emit()
                        if term_at is not None and now - term_at >= termination_grace_seconds and kill_at is None:
                            status['termination']['kill_sent'] = stop(signal.SIGKILL)
                            kill_at = now; emit()
                        if kill_at is not None and now - kill_at >= 1:
                            break  # A stuck kernel/pipe cannot extend the parent deadline.
                        for key, _ in selector.select(timeout=0.05):
                            label, target = key.data
                            remaining = MAX_OUTPUT_BYTES - status['stdout_bytes_read'] - status['stderr_bytes_read']
                            raw = os.read(key.fileobj.fileno(), min(8192, max(1, remaining + 1)))
                            if not raw:
                                selector.unregister(key.fileobj); key.fileobj.close(); continue
                            status[label + '_bytes_read'] += len(raw)
                            if remaining >= 0: target.write(raw[:remaining + 1])
                            if label == 'stderr' and remaining >= 0:
                                stderr_pending += raw[:remaining + 1]
                                while b'\n' in stderr_pending:
                                    line, stderr_pending = stderr_pending.split(b'\n', 1)
                                    phase = _phase(line)
                                    if phase:
                                        status['phases'].append(phase); status['last_phase'] = phase['lp_phase']; emit()
                            if status['stdout_bytes_read'] + status['stderr_bytes_read'] > MAX_OUTPUT_BYTES:
                                failure = 'OutputLimitExceeded'
                        if process.poll() is not None and not selector.get_map():
                            break
                    if stderr_pending:
                        phase = _phase(stderr_pending)
                        if phase: status['phases'].append(phase); status['last_phase'] = phase['lp_phase']
                for pipe in (process.stdout, process.stderr):
                    if not pipe.closed: pipe.close()
                try: process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    stop(signal.SIGKILL)
                status['returncode'] = process.poll()
                if failure is not None: status['error_type'] = failure
                elif status['returncode'] != 0: status['error_type'] = 'ChildProcessError'
                else:
                    stdout.seek(0); raw = stdout.read(MAX_OUTPUT_BYTES + 1)
                    validated = validate_receipt(raw)
                    receipt = raw.strip() + b'\n'
                    status.update(success=True, publication_state='publisher_reported_success_requires_public_verification',
                                  publisher_run_id=validated['run_id'], programs=validated['programs'])
    except Exception as error:
        status['error_type'] = type(error).__name__
        if process is not None and process.poll() is None:
            status['termination']['kill_sent'] = stop(signal.SIGKILL)
            try: process.wait(timeout=1)
            except subprocess.TimeoutExpired: pass
        if process is not None: status['returncode'] = process.poll()
        if process is not None:
            for pipe in (process.stdout, process.stderr):
                if pipe is not None and not pipe.closed: pipe.close()
    status['finished_at'] = _stamp(); emit()
    return status, receipt


def run_publisher(arguments, *, status_file, timeout_seconds=840, termination_grace_seconds=5):
    return _supervise(publisher_command(arguments), status_file=status_file, timeout_seconds=timeout_seconds,
                      termination_grace_seconds=termination_grace_seconds)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status-file', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=float, default=840)
    options, arguments = parser.parse_known_args(argv)
    if arguments[:1] == ['--']: arguments = arguments[1:]
    try:
        status, receipt = run_publisher(arguments, status_file=options.status_file, timeout_seconds=options.timeout_seconds)
    except Exception:
        # Argument text and environment may contain secrets; do not echo either.
        status = {'kind': KIND, 'success': False, 'error_type': 'InvalidPublisherArguments',
                  'publication_state': 'unknown_requires_readonly_check', 'automatic_retry': False}
        _save(options.status_file, status); receipt = None
    if status['success']:
        sys.stdout.buffer.write(receipt); sys.stdout.buffer.flush(); return 0
    print('LP publisher did not complete; inspect status metadata and check publication read-only before any retry.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
