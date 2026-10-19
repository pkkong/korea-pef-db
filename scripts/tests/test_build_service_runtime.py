"""Deployment packages exclude every sibling app and private configuration."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import build_service_runtime as package
from scripts import deploy_service_runtime as deploy


class ServicePackageTests(unittest.TestCase):
    def test_each_package_contains_exactly_one_app_and_shared_assets(self):
        for service, names in package.FILES.items():
            with self.subTest(service=service), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'package'
                web = package.build(service, root)
                self.assertEqual(sorted(p.name for p in (root / 'services').iterdir()), [service])
                expected = set(names) | {'service_assets.py'} | ({'downloads'} if service == 'gp' else set())
                self.assertEqual({p.name for p in web.iterdir()}, expected)
                self.assertEqual((web / 'service_assets.py').read_bytes(), (package.ROOT / 'services/shared/web/service_assets.py').read_bytes())
                self.assertEqual(json.loads((web / 'vercel.json').read_text())['framework'], 'flask')

    def test_invalid_workbook_cannot_replace_gp_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'invalid.xlsx'
            path.write_text('not an XLSX')
            with self.assertRaises(ValueError):
                package.build('gp', Path(temporary) / 'output', path)

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'sentinel').write_text('keep')
            with self.assertRaises(ValueError):
                package.build('newsletter', root)
            self.assertEqual((root / 'sentinel').read_text(), 'keep')

    def test_runtime_settings_include_only_public_read_credentials(self):
        env = {'SUPABASE_URL': 'https://db.example', 'SUPABASE_PUBLISHABLE_KEY': 'public-read',
               'SUPABASE_SERVICE_ROLE_KEY': 'must-never-send', 'SUPABASE_DB_URL': 'must-never-send'}
        with patch.dict('os.environ', env), patch.object(deploy, 'api', return_value={}) as api:
            deploy.configure_public_env('project')
            rows = api.call_args.args[2]
            keys = {row['key'] for row in rows}
            self.assertEqual(keys, {'SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY', 'SERVICE_RELEASE', 'NEWSLETTER_PUBLIC_URL', 'LP_PUBLIC_URL', 'GP_PUBLIC_URL'})
            self.assertNotIn('must-never-send', json.dumps(rows))

    def test_unrelated_existing_project_is_not_reconfigured(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(deploy, 'api', return_value={'id': 'unrelated', 'framework': 'nextjs', 'rootDirectory': 'other'}) as api:
            with self.assertRaises(RuntimeError):
                deploy.ensure_project('lp')
            self.assertEqual(api.call_count, 1)

    def test_new_project_has_own_root_and_no_git_auto_deploy_dependency(self):
        project = {'id': 'lp-project', 'rootDirectory': 'services/lp/web', 'framework': 'flask'}
        with patch.dict('os.environ', {}, clear=True), patch.object(deploy, 'api', side_effect=[None, project]) as api:
            self.assertEqual(deploy.ensure_project('lp'), project)
            creation = api.call_args.args[2]
            self.assertEqual(creation['rootDirectory'], 'services/lp/web')
            self.assertNotIn('gitRepository', creation)

    def test_cli_failure_does_not_expose_token_in_raised_error(self):
        with patch.dict('os.environ', {'VERCEL_TOKEN': 'PRIVATE-TOKEN-SENTINEL'}), patch.object(deploy.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['vercel', '--token', 'PRIVATE-TOKEN-SENTINEL'])):
            with self.assertRaises(RuntimeError) as failure:
                deploy.run_vercel(['vercel', 'deploy'], {})
            self.assertNotIn('PRIVATE-TOKEN-SENTINEL', str(failure.exception))
            self.assertTrue(failure.exception.__suppress_context__)
