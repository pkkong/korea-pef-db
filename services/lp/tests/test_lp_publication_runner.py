import contextlib
import copy
import io
import json
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.lp.src import lp_publication_runner as a


def receipt():
    return {'run_id': 'a' * 24, 'programs': 2, 'program_ids': ['sample-2026-a', 'sample-2026-b'],
            'programs_by_institution': {'sample': 2}, 'notices': 3, 'review': 0,
            'institution_notices': 4, 'institution_validation_errors': 0,
            'institution_institutions': ['sample'], 'shared_notices': 2, 'shared_originals': 1,
            'shared_offering_terms': 1, 'shared_institutions': ['sample']}


class BinaryOutput:
    def __init__(self): self.buffer = io.BytesIO()


class PublicationRunnerTests(unittest.TestCase):
    def supervise(self, code, **options):
        with tempfile.TemporaryDirectory() as directory:
            status_file = Path(directory) / 'status.json'
            status, output = a._supervise([sys.executable, '-c', code], status_file=status_file,
                                          timeout_seconds=options.pop('timeout_seconds', 2), **options)
            self.assertEqual(json.loads(status_file.read_text()), status)
            self.assertEqual(status_file.stat().st_mode & 0o777, 0o600)
            return status, output

    def test_harmless_success_returns_original_receipt_and_safe_phases_only(self):
        value = receipt(); raw = json.dumps(value, ensure_ascii=False).encode()
        phase = {'lp_phase': 'collection_report_parts', 'seconds': 1.25, 'report_bytes': 91222622,
                 'parts': 87, 'token': 'SECRET', 'sql': 'SECRET SQL', 'host': 'private.example'}
        code = ('import json,sys;print(' + repr(json.dumps(value)) + ');'
                'print(' + repr(json.dumps(phase)) + ',file=sys.stderr)')
        status, output = self.supervise(code)
        self.assertTrue(status['success']); self.assertEqual(output, raw + b'\n')
        self.assertEqual(status['last_phase'], 'collection_report_parts')
        self.assertEqual(status['phases'], [{'lp_phase': 'collection_report_parts', 'seconds': 1.25,
                                          'report_bytes': 91222622, 'parts': 87}])
        self.assertNotIn('SECRET', json.dumps(status)); self.assertNotIn('private.example', json.dumps(status))
        self.assertEqual(status['process_attempts'], 1)
        self.assertFalse(status['automatic_retry'])
        self.assertNotIn('database_writes', status)
        self.assertIn('requires_public_verification', status['publication_state'])

    def test_nonzero_secret_output_is_never_returned_or_in_status(self):
        code = 'import sys;print("SECRET_STDOUT");print("Trace SQL HOST TOKEN_SECRET",file=sys.stderr);sys.exit(3)'
        status, output = self.supervise(code)
        self.assertFalse(status['success']); self.assertIsNone(output)
        self.assertEqual(status['returncode'], 3)
        self.assertEqual(status['error_type'], 'ChildProcessError')
        self.assertNotIn('SECRET', json.dumps(status)); self.assertNotIn('SQL', json.dumps(status))
        self.assertEqual(status['publication_state'], 'unknown_requires_readonly_check')
        self.assertEqual(status['process_attempts'], 1)

    @unittest.skipUnless(os.name == 'posix', 'POSIX termination-group semantics')
    def test_timeout_terminates_own_process_group_without_retry(self):
        started = time.monotonic()
        status, output = self.supervise('import time;time.sleep(30)', timeout_seconds=0.15, termination_grace_seconds=0.1)
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(status['timed_out']); self.assertTrue(status['termination']['term_sent'])
        self.assertTrue(status['termination']['process_group']); self.assertFalse(status['success'])
        self.assertIsNone(output); self.assertEqual(status['error_type'], 'TimeoutError')
        self.assertEqual(status['publication_state'], 'unknown_requires_readonly_check')

    @unittest.skipUnless(os.name == 'posix', 'POSIX hard-kill semantics')
    def test_ignored_term_is_hard_killed_after_bounded_grace(self):
        phase = json.dumps({'lp_phase': 'publication_lock', 'seconds': 0.1})
        code = ('import signal,time,sys;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                'print(' + repr(phase) + ',file=sys.stderr,flush=True);time.sleep(30)')
        status, output = self.supervise(code, timeout_seconds=0.2, termination_grace_seconds=0.1)
        self.assertTrue(status['termination']['term_sent']); self.assertTrue(status['termination']['kill_sent'])
        self.assertEqual(status['returncode'], -signal.SIGKILL)
        self.assertEqual(status['last_phase'], 'publication_lock')
        self.assertIsNone(output)

    def test_oversize_stdout_or_stderr_fails_without_echoing_private_bytes(self):
        for stream in ('stdout', 'stderr'):
            code = 'import sys;sys.' + stream + '.write("SECRET"*20000);sys.' + stream + '.flush()'
            status, output = self.supervise(code, termination_grace_seconds=0)
            with self.subTest(stream=stream):
                self.assertFalse(status['success']); self.assertIsNone(output)
                self.assertEqual(status['error_type'], 'OutputLimitExceeded')
                self.assertNotIn('SECRET', json.dumps(status))
                self.assertGreater(status['stdout_bytes_read'] + status['stderr_bytes_read'], a.MAX_OUTPUT_BYTES)

    def test_invalid_or_forged_receipt_fails_even_when_child_returns_zero(self):
        for change in ('extra', 'missing', 'count', 'bool', 'run', 'id', 'duplicate', 'nan'):
            value = copy.deepcopy(receipt())
            if change == 'extra': value['secret'] = 'SECRET'
            elif change == 'missing': del value['run_id']
            elif change == 'count': value['programs_by_institution']['sample'] = 1
            elif change == 'bool': value['notices'] = True
            elif change == 'run': value['run_id'] = 'SECRET'
            elif change == 'id': value['program_ids'][0] = 'private id with spaces'
            elif change == 'duplicate': value['program_ids'][1] = value['program_ids'][0]
            else: value['notices'] = float('nan')
            with self.subTest(change=change), self.assertRaises(ValueError): a.validate_receipt(json.dumps(value).encode())
        status, output = self.supervise('print("SECRET not JSON")')
        self.assertFalse(status['success']); self.assertIsNone(output); self.assertNotIn('SECRET', json.dumps(status))
        with self.assertRaises(ValueError): a.validate_receipt(b'{"run_id":"x","run_id":"y"}')
        with self.assertRaises(ValueError): a.validate_receipt(json.dumps(receipt()).encode() + b'\nSECRET')

    def test_phase_whitelist_drops_raw_stack_unknown_keys_and_nonfinite_counts(self):
        self.assertIsNone(a._phase(b'Traceback: SECRET SQL HOST'))
        self.assertIsNone(a._phase(b'{"lp_phase":"SECRET","seconds":1}'))
        self.assertIsNone(a._phase(b'{"lp_phase":"publication_lock","seconds":NaN}'))
        self.assertIsNone(a._phase(b'{"lp_phase":"evidence_storage","seconds":1,"documents":"SECRET"}'))

    def test_empty_program_or_notice_receipts_are_rejected_other_zero_counts_remain_valid(self):
        for field in ('programs', 'notices'):
            value = receipt(); value[field] = 0
            if field == 'programs':
                value['program_ids'] = []; value['programs_by_institution'] = {}
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'nonempty'):
                a.validate_receipt(json.dumps(value).encode())
        value = receipt()
        for field in ('review', 'institution_notices', 'institution_validation_errors',
                      'shared_notices', 'shared_originals', 'shared_offering_terms'):
            value[field] = 0
        value['institution_institutions'] = []; value['shared_institutions'] = []
        self.assertEqual(a.validate_receipt(json.dumps(value).encode()), value)

    def test_fixed_script_command_and_cli_double_dash_preserve_publisher_arguments(self):
        args = ['--collection', '/tmp/a $(touch should-not-run).json', '--priority-collection', '/tmp/priority.json']
        command = a.publisher_command(args)
        self.assertEqual(command, [sys.executable, str(a.PUBLISHER), *args])
        self.assertEqual(a.publisher_command(['-c', 'SECRET']), [sys.executable, str(a.PUBLISHER), '-c', 'SECRET'])
        output = BinaryOutput(); success = {'success': True}
        with patch.object(a, 'run_publisher', return_value=(success, json.dumps(receipt()).encode() + b'\n')) as run, \
             patch.object(a.sys, 'stdout', output):
            result = a.main(['--status-file', '/tmp/synthetic-status.json', '--timeout-seconds', '480', '--', *args])
        self.assertEqual(result, 0); self.assertEqual(run.call_args.args[0], args)
        self.assertEqual(json.loads(output.buffer.getvalue()), receipt())

    def test_cli_failure_keeps_stdout_empty_and_fixed_command_cannot_be_replaced(self):
        stdout = BinaryOutput(); stderr = io.StringIO()
        with patch.object(a, 'run_publisher', return_value=({'success': False}, None)), \
             patch.object(a.sys, 'stdout', stdout), contextlib.redirect_stderr(stderr):
            code = a.main(['--status-file', '/tmp/synthetic-status.json', '--', '--collection', '/tmp/source.json'])
        self.assertEqual(code, 1); self.assertEqual(stdout.buffer.getvalue(), b'')
        self.assertNotIn('SECRET', stderr.getvalue())
        with patch.object(a, '_supervise', return_value=({}, None)) as supervise:
            a.run_publisher(['--collection', '/tmp/source.json'], status_file='/tmp/synthetic-status.json')
        self.assertEqual(supervise.call_args.args[0][:2], [sys.executable, str(a.PUBLISHER)])

    @unittest.skipUnless(os.name == 'posix', 'POSIX inherited-pipe deadline')
    def test_descendant_cannot_keep_writer_pipes_open_past_deadline(self):
        # The parent exits successfully, but its harmless descendant inherits
        # both pipes. The group deadline still applies; no publication retry.
        grandchild = 'import time;time.sleep(30)'
        code = ('import subprocess,sys;subprocess.Popen([sys.executable,"-c",' + repr(grandchild) + ']);'
                'print(' + repr(json.dumps(receipt())) + ',flush=True)')
        started = time.monotonic()
        status, output = self.supervise(code, timeout_seconds=0.2, termination_grace_seconds=0.1)
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(status['success']); self.assertTrue(status['timed_out']); self.assertIsNone(output)
        self.assertEqual(status['returncode'], 0)

    def test_invalid_timeout_never_starts_child_and_environment_is_inherited_privately(self):
        for timeout in (0, -1, 481, float('nan'), True):
            with tempfile.TemporaryDirectory() as directory, patch.object(a.subprocess, 'Popen') as child:
                status, output = a._supervise(['never'], status_file=Path(directory) / 'status.json', timeout_seconds=timeout)
            self.assertFalse(status['success']); child.assert_not_called()
        env = dict(os.environ); env['LP_RUNNER_TEST_SECRET'] = 'PRIVATE_VALUE'
        code = 'import os,sys;assert os.environ["LP_RUNNER_TEST_SECRET"]=="PRIVATE_VALUE";print(' + repr(json.dumps(receipt())) + ')'
        status, output = self.supervise(code, env=env)
        self.assertTrue(status['success']); self.assertNotIn('PRIVATE_VALUE', json.dumps(status))
        self.assertNotIn(b'PRIVATE_VALUE', output)


if __name__ == '__main__':
    unittest.main()
