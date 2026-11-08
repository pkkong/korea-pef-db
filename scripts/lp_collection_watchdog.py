"""Detect a missed LP schedule start; never retry an existing failed run."""
import argparse
import datetime as dt
import json
import os
import subprocess

REPOSITORY = 'pkkong/korea-pef-db'
WORKFLOW = 'collect-kgrowth-programs.yml'
ACTIVE = ('queued', 'in_progress', 'waiting', 'pending', 'requested')
SOURCE_WORKFLOWS = frozenset((WORKFLOW, 'recover-lp-publication.yml',
    'inspect-lp-remaining-boards.yml', 'verify-kgrowth-window.yml',
    'verify-pck-board.yml', 'audit-lp-official-inventory.yml',
    'audit-lp-discovery.yml', 'diagnose-lp-board-http.yml',
    'probe-lp-source-region.yml', 'deploy-lp-source-worker.yml',
    'maintain-lp-report-storage.yml', 'inspect-lp-history.yml',
    'discover-lp-history.yml', 'collect-lp-history-bodies.yml',
    'discover-ktcu-history.yml', 'collect-lp-history-attachments.yml',
    'diagnose-lp-inventory-failures.yml', 'prepare-lp-history-publication.yml',
    'publish-lp-history.yml', 'plan-lp-history-attachments.yml'))
UTC = dt.timezone.utc


class WatchdogError(Exception):
    pass


def timestamp(value):
    try:
        result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(UTC)
    except (ValueError, TypeError, AttributeError):
        raise WatchdogError('invalid run timestamp') from None


def due_window(now):
    if now.tzinfo is None:
        raise WatchdogError('timezone required')
    now = now.astimezone(UTC)
    if now.weekday() >= 5:
        return None
    windows = [now.replace(hour=h, minute=20, second=0, microsecond=0)
               for h in (0, 6)]
    return next((w for w in reversed(windows)
                 if now >= w + dt.timedelta(minutes=90)), None)


def workflow_name(run):
    if not isinstance(run,dict):
        raise WatchdogError('invalid run identity')
    path=run.get('path','')
    if isinstance(path,str) and path.startswith('dynamic/'):
        return path  # GitHub-managed Pages jobs do not use the LP source queue.
    if (not isinstance(path,str) or not path.startswith('.github/workflows/')
            or '/' in path[len('.github/workflows/'):] or not path.endswith(('.yml','.yaml'))):
        raise WatchdogError('invalid workflow path')
    return path.rsplit('/',1)[1]


def validate_run(run, now):
    if not isinstance(run, dict) or type(run.get('id')) is not int or run['id'] <= 0:
        raise WatchdogError('invalid run identity')
    repository=run.get('repository')
    if not isinstance(repository,dict) or repository.get('full_name') != REPOSITORY:
        raise WatchdogError('unexpected run repository')
    name=workflow_name(run)
    if not isinstance(run.get('head_branch'), str) or not run['head_branch']:
        raise WatchdogError('invalid run ref')
    if run.get('status') not in (*ACTIVE, 'completed'):
        raise WatchdogError('unknown run status')
    created = timestamp(run.get('created_at'))
    # A new run may be created while the bounded API snapshot is being read.
    # Reject implausible future data, not a legitimate concurrent start.
    if created > now + dt.timedelta(minutes=10):
        raise WatchdogError('future run timestamp')
    return name, created


def decide(now, collection_runs, active_runs):
    due = due_window(now)
    if due is None:
        return {'decision': 'skip', 'reason': 'no_due_window'}
    now = now.astimezone(UTC)
    covered = False
    for run in collection_runs:
        name, created = validate_run(run, now)
        if name != WORKFLOW:
            raise WatchdogError('unexpected collection workflow')
        event = run.get('event')
        if not isinstance(event,str) or not event:
            raise WatchdogError('invalid collection event')
        if (run['head_branch'] == 'main' and event in ('schedule','workflow_dispatch')
                and created >= due - dt.timedelta(minutes=30)):
            covered = True
    for run in active_runs:
        if workflow_name(run) not in SOURCE_WORKFLOWS:
            continue  # Sibling services do not participate in LP source health.
        name, _ = validate_run(run, now)
        if run['status'] not in ACTIVE:
            raise WatchdogError('non-active run in active response')
        if name in SOURCE_WORKFLOWS:
            return {'decision': 'skip', 'reason': 'source_queue_active', 'due': due.isoformat()}
    return {'decision': 'skip' if covered else 'dispatch',
            'reason': 'window_covered' if covered else 'missed_start', 'due': due.isoformat()}


def gh_api(endpoint, *, dispatch=False):
    command = ['gh', 'api', '--method', 'POST' if dispatch else 'GET', endpoint]
    if dispatch:
        command += ['-f', 'ref=main']
    try:
        result = subprocess.run(command, capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise WatchdogError('GitHub API unavailable') from None
    if result.returncode or len(result.stdout) > 4 * 1024 * 1024:
        raise WatchdogError('GitHub API failed')
    if dispatch:
        return None
    try:
        return json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise WatchdogError('invalid GitHub API response') from None


def read_runs(endpoint, api):
    rows = []
    for page in (1, 2):
        data = api(f'{endpoint}&per_page=100&page={page}')
        if not isinstance(data, dict) or type(data.get('total_count')) is not int or data['total_count'] < 0:
            raise WatchdogError('invalid run listing')
        batch = data.get('workflow_runs')
        if not isinstance(batch, list) or len(batch) > 100:
            raise WatchdogError('invalid run listing')
        rows.extend(batch)
        if len(batch) < 100:
            if len(rows) < data['total_count']:
                raise WatchdogError('incomplete run listing')
            return rows
    raise WatchdogError('run listing page limit')


def recent_collection_runs(endpoint, api, now):
    # The most recent page is enough to establish whether this window has
    # started and to inspect the latest prior failure, even after a weekend.
    data=api(endpoint+'&per_page=100')
    if not isinstance(data,dict) or type(data.get('total_count')) is not int:
        raise WatchdogError('invalid collection listing')
    rows=data.get('workflow_runs')
    if (not isinstance(rows,list) or data['total_count']<0
            or len(rows)!=min(data['total_count'],100)):
        raise WatchdogError('incomplete collection listing')
    dates=[validate_run(r,now)[1] for r in rows]
    if dates!=sorted(dates,reverse=True):
        raise WatchdogError('unordered collection listing')
    return rows


def prior_start_failed(base, rows, api):
    trusted=[r for r in rows if r['head_branch']=='main' and r.get('event') in ('schedule','workflow_dispatch')]
    if not trusted or trusted[0].get('conclusion')!='failure':
        return False
    jobs=api(f"{base}/runs/{trusted[0]['id']}/jobs?filter=latest&per_page=100")
    if (not isinstance(jobs,dict) or type(jobs.get('total_count')) is not int
            or not isinstance(jobs.get('jobs'),list) or jobs['total_count']!=len(jobs['jobs'])
            or jobs['total_count']>100):
        raise WatchdogError('invalid prior job evidence')
    if not jobs['jobs']:
        return True
    for job in jobs['jobs']:
        if not isinstance(job,dict) or not isinstance(job.get('steps'),list):
            raise WatchdogError('invalid prior job evidence')
        if job.get('conclusion')=='failure' and not job['steps']:
            return True  # Provider/start failures require investigation, not repeated dispatches.
    return False


def run_watchdog(*, now, repository, ref, event, dry_run=True, api=gh_api):
    if repository != REPOSITORY or ref != 'refs/heads/main' or event not in ('schedule', 'workflow_dispatch'):
        return {'decision': 'skip', 'reason': 'untrusted_context'}
    if due_window(now) is None:
        return {'decision': 'skip', 'reason': 'no_due_window'}
    base = f'repos/{REPOSITORY}/actions'
    collection = recent_collection_runs(f'{base}/workflows/{WORKFLOW}/runs?branch=main',api,now)
    active = []
    for status in ACTIVE:
        active.extend(read_runs(f'{base}/runs?status={status}', api))
    decision = decide(now, collection, active)
    if decision['decision'] == 'dispatch':
        if prior_start_failed(base,collection,api):
            return {'decision':'skip','reason':'prior_run_did_not_start','due':decision['due']}
        workflow=api(f'{base}/workflows/{WORKFLOW}')
        if (not isinstance(workflow,dict) or type(workflow.get('id')) is not int
                or workflow['id']<=0 or workflow.get('path')!='.github/workflows/'+WORKFLOW
                or not isinstance(workflow.get('state'),str)):
            raise WatchdogError('invalid collection workflow')
        if workflow['state']!='active':
            return {'decision':'skip','reason':'workflow_inactive','due':decision['due']}
        if dry_run:
            decision['decision'] = 'would_dispatch'
        else:
            api(f'{base}/workflows/{WORKFLOW}/dispatches', dispatch=True)
            decision['decision'] = 'dispatched'
    return decision


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', choices=('true', 'false'), default='true')
    args = parser.parse_args()
    try:
        decision = run_watchdog(now=dt.datetime.now(UTC),
            repository=os.environ.get('GITHUB_REPOSITORY'), ref=os.environ.get('GITHUB_REF'),
            event=os.environ.get('GITHUB_EVENT_NAME'), dry_run=args.dry_run == 'true')
    except WatchdogError:
        print(json.dumps({'decision': 'error', 'reason': 'verification_failed'}))
        return 1
    print(json.dumps(decision, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
