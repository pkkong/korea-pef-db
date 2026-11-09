"""Read-only accounting of expected LP runs; manual recovery is not automation success."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path

try:
    from .lp_collection_watchdog import (
        ACTIVE, REPOSITORY, UTC, WORKFLOW, WatchdogError, gh_api,
        recent_collection_runs, timestamp, validate_run,
    )
except ImportError:
    from lp_collection_watchdog import (
        ACTIVE, REPOSITORY, UTC, WORKFLOW, WatchdogError, gh_api,
        recent_collection_runs, timestamp, validate_run,
    )


def expected_windows(now, count=6):
    if now.tzinfo is None or type(count) is not int or not 1 <= count <= 20:
        raise WatchdogError('invalid reliability window')
    now = now.astimezone(UTC)
    windows = []
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    while len(windows) < count:
        if day.weekday() < 5:
            for hour in (6, 0):
                due = day.replace(hour=hour, minute=20)
                if now >= due + dt.timedelta(minutes=90):
                    windows.append(due)
                    if len(windows) == count:
                        break
        day -= dt.timedelta(days=1)
    return list(reversed(windows))


def assess(now, runs, *, history_complete=True):
    windows = expected_windows(now)
    observed = []
    for run in runs:
        name, created = validate_run(run, now)
        if name != WORKFLOW:
            raise WatchdogError('unexpected reliability workflow')
        if run['head_branch'] != 'main':
            continue
        attempt = run.get('run_attempt')
        if type(attempt) is not int or attempt < 1:
            raise WatchdogError('invalid run attempt')
        actor = run.get('actor')
        if not isinstance(actor, dict) or not isinstance(actor.get('login'), str):
            raise WatchdogError('invalid run actor')
        automatic = (attempt == 1 and (run.get('event') == 'schedule' or
            (run.get('event') == 'workflow_dispatch' and actor['login'] == 'github-actions[bot]'
             and run.get('display_title') == 'LP scheduled_watchdog')))
        if run['status'] == 'completed' and run.get('conclusion') not in {
                'success', 'failure', 'cancelled', 'timed_out', 'action_required',
                'neutral', 'skipped', 'stale', 'startup_failure'}:
            raise WatchdogError('invalid run conclusion')
        observed.append((run, created, automatic))
    oldest = min((created for _, created, _ in observed), default=now)
    rows = []
    for due in windows:
        # At 30 minutes before the next scheduled time a new slot starts.
        next_due = (due.replace(hour=6) if due.hour == 0 else
                    (due + dt.timedelta(days=1)).replace(hour=0))
        start, end = due - dt.timedelta(minutes=30), next_due - dt.timedelta(minutes=30)
        matches = [(run, automatic) for run, created, automatic in observed if start <= created < end]
        automatic = [run for run, auto in matches if auto]
        if not history_complete and oldest > start:
            state = 'history_incomplete'
        elif not automatic:
            state = 'manual_only' if matches else 'missing'
        elif any(run['status'] == 'completed' and run['conclusion'] != 'success' for run in automatic):
            state = 'failed'
        elif any(run['status'] in ACTIVE for run in automatic):
            state = 'running'
        else:
            state = 'ok'
        rows.append({'due': due.isoformat(), 'state': state,
                     'automatic_run_ids': [r['id'] for r in automatic],
                     'manual_or_rerun_ids': [r['id'] for r, auto in matches if not auto]})
    successful = sum(row['state'] == 'ok' for row in rows)
    return {'checked_at': now.astimezone(UTC).isoformat(), 'required_windows': 6,
            'successful_windows': successful, 'all_windows_ok': successful == 6,
            'windows': rows,
            'meaning': 'Recent scheduled operation, not market recall or current-release acceptance; manual runs do not fill automation gaps.'}


def markdown(report):
    labels = {'ok': '성공', 'failed': '실패', 'running': '실행 중', 'missing': '시작 기록 없음',
              'manual_only': '수동 실행만 확인', 'history_incomplete': '실행 이력 부족'}
    lines = ['## LP 최근 자동 운영', '',
             f"최근 6회 예정 수집 중 성공 확인: **{report['successful_windows']}/6**", '',
             '| 예정 시각(KST) | 결과 | 자동 실행 | 수동·재실행 |', '|---|---|---|---|']
    kst = dt.timezone(dt.timedelta(hours=9))
    for row in report['windows']:
        due = timestamp(row['due']).astimezone(kst).strftime('%m-%d %H:%M')
        link = lambda ident: f'[{ident}](https://github.com/{REPOSITORY}/actions/runs/{ident})'
        lines.append(f"| {due} | {labels[row['state']]} | " +
                     ', '.join(map(link, row['automatic_run_ids'])) + ' | ' +
                     ', '.join(map(link, row['manual_or_rerun_ids'])) + ' |')
    lines += ['', '수동 복구는 자동 성공에 포함하지 않습니다. 시장 수집률이나 최신 코드의 검증 완료율이 아닙니다.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--markdown', type=Path, required=True)
    args = parser.parse_args()
    if (os.environ.get('GITHUB_REPOSITORY') != REPOSITORY or
            os.environ.get('GITHUB_REF') != 'refs/heads/main' or
            os.environ.get('GITHUB_EVENT_NAME') not in {'schedule', 'workflow_dispatch'}):
        raise WatchdogError('untrusted reliability context')
    now = dt.datetime.now(UTC)
    runs = recent_collection_runs(f'repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs?branch=main', gh_api, now)
    # A full page can be truncated. Missing older history must not become success.
    report = assess(now, runs, history_complete=len(runs) < 100)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    args.markdown.write_text(markdown(report))
    print(json.dumps({'successful_windows': report['successful_windows'], 'required_windows': 6}))


if __name__ == '__main__':
    main()
