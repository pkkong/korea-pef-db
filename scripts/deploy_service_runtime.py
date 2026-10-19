"""Deploy one isolated Vercel project with its own app and public read settings.

Credentials stay in process environment; never emit API bodies or secret values.
No service data is migrated or published by this deployment operation.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit, quote
from urllib.request import Request, urlopen
try:
    from .build_service_runtime import build, validate_data_pack, DATA_PACK
except ImportError:
    from build_service_runtime import build, validate_data_pack, DATA_PACK

DEFAULTS = {
    'newsletter': 'https://kpef-newsletter.vercel.app',
    'lp': 'https://kpef-lp.vercel.app',
    'gp': 'https://kpef-gp.vercel.app',
}


def api(path, method='GET', payload=None, *, allow_missing=False, query=None):
    parameters = dict(query or {})
    owner = os.environ['VERCEL_ORG_ID']
    if owner.startswith('team_'):
        parameters['teamId'] = owner
    url = 'https://api.vercel.com' + path + ('?' + urlencode(parameters) if parameters else '')
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Authorization': 'Bearer ' + os.environ['VERCEL_TOKEN'], 'Content-Type': 'application/json'}, method=method)
    try:
        with urlopen(request, timeout=45) as response:
            return json.load(response)
    except HTTPError as error:
        if allow_missing and error.code == 404:
            return None
        # Provider error bodies may contain submitted values; do not print them.
        raise RuntimeError(f'Vercel API {method} {path.split("?")[0]} failed with HTTP {error.code}') from None


def ensure_project(service):
    name = 'kpef-' + service
    configured = os.environ.get('VERCEL_PROJECT_ID') if service == 'newsletter' else os.environ.get(service.upper() + '_VERCEL_PROJECT_ID')
    project = api('/v9/projects/' + quote(configured or name, safe=''), allow_missing=not bool(configured))
    root = f'services/{service}/web'
    if project is None:
        project = api('/v11/projects', 'POST', {'name': name, 'framework': 'flask', 'rootDirectory': root, 'publicSource': False})
    if project.get('rootDirectory') != root or project.get('framework') != 'flask':
        raise RuntimeError('Project settings differ from the expected isolated service root; refusing to overwrite another project')
    return project


def configure_public_env(project_id):
    values = {'SUPABASE_URL': os.environ['SUPABASE_URL'], 'SUPABASE_PUBLISHABLE_KEY': os.environ['SUPABASE_PUBLISHABLE_KEY']}
    values['SERVICE_RELEASE'] = os.environ.get('GITHUB_SHA') or os.environ.get('SERVICE_RELEASE', 'manual')
    for service, default in DEFAULTS.items():
        values[service.upper() + '_PUBLIC_URL'] = os.environ.get(service.upper() + '_PUBLIC_URL', default)
    payload = [{'key': key, 'value': value, 'type': 'encrypted', 'target': ['production']} for key, value in values.items()]
    result = api('/v10/projects/' + project_id + '/env', 'POST', payload, query={'upsert': 'true'})
    if isinstance(result, dict) and result.get('failed'):
        raise RuntimeError('Unable to configure all public service settings')


def verify(service, base, *, attempts=12, expected_release=None):
    for attempt in range(attempts):
        try:
            with urlopen(base.rstrip('/') + '/health.json?refresh=1', timeout=25) as response:
                health = json.load(response)
            if health.get('service') != service or health.get('status') not in {'ok', 'degraded'}:
                raise ValueError('Unexpected own-service health response')
            if expected_release and health.get('release') != expected_release:
                raise ValueError('Production alias still serves a different deployment')
            with urlopen(base.rstrip('/') + '/assets/service.css', timeout=15) as response:
                if response.status != 200 or b'.bottom-nav' not in response.read():
                    raise ValueError('Local presentation assets unavailable')
            return health
        except (OSError, ValueError):
            if attempt == attempts - 1:
                raise RuntimeError(f'{service} public verification failed') from None
            time.sleep(5)


def run_vercel(command, environment):
    try:
        subprocess.run(command + ['--token', os.environ['VERCEL_TOKEN']], env=environment, check=True)
    except subprocess.CalledProcessError as error:
        # The original exception contains argv, including the token.
        raise RuntimeError(f'Vercel {command[1]} failed with exit code {error.returncode}') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', choices=DEFAULTS, required=True)
    parser.add_argument('--gp-data-pack', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--inspect-only', action='store_true')
    args = parser.parse_args()
    base = os.environ.get(args.service.upper() + '_PUBLIC_URL', DEFAULTS[args.service])
    if args.inspect_only:
        identity = os.environ.get('VERCEL_PROJECT_ID') if args.service == 'newsletter' else 'kpef-' + args.service
        project = api('/v9/projects/' + quote(identity or 'kpef-newsletter', safe=''), allow_missing=True)
        fields = {'name': project.get('name'), 'rootDirectory': project.get('rootDirectory'), 'framework': project.get('framework'), 'git_linked': bool(project.get('link'))} if project else {'exists': False}
        print(json.dumps({'service': args.service, **fields}))
        return
    if args.verify_only:
        print(json.dumps(verify(args.service, base)))
        return
    for key in ['VERCEL_TOKEN', 'VERCEL_ORG_ID', 'SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY']:
        if not os.environ.get(key):
            raise RuntimeError(f'{key} is required')
    project = ensure_project(args.service)
    configure_public_env(project['id'])
    with tempfile.TemporaryDirectory(prefix='kpef-isolated-deploy-') as temporary:
        root = Path(temporary)
        workbook = args.gp_data_pack
        staging = root / 'source'
        web = build(args.service, staging, workbook)
        environment = {**os.environ, 'VERCEL_PROJECT_ID': project['id']}
        # Only the target service exists in the uploaded directory. Project
        # Root Directory settings remain unchanged, including the existing app.
        commands = [
            ['vercel', 'pull', '--yes', '--environment=production', '--cwd', str(staging)],
            ['vercel', 'deploy', '--prod', '--yes', '--cwd', str(staging)],
        ]
        for command in commands:
            run_vercel(command, environment)
        release = os.environ.get('GITHUB_SHA') or os.environ.get('SERVICE_RELEASE', 'manual')
        health = verify(args.service, base, expected_release=release)
        print(json.dumps({'service': args.service, 'url': base, 'health': health, 'project': project['name']}))


if __name__ == '__main__':
    main()
