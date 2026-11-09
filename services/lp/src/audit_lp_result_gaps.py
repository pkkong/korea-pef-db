"""Read-only result/roster gaps in the published LP model and retained metadata.

Past deadlines never prove a business ended. A missing name is unconfirmed,
not unpublished. This audit distinguishes model gaps; it does not read raw
attachments or certify that a browser rendered every known manager name.
"""
import argparse
from collections import Counter
from datetime import date, datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from .build_lp_history_coverage import validate_index, valid_url
except ImportError:
    from build_lp_history_coverage import validate_index, valid_url

FINAL = frozenset(('최종 선정', '선정 결과', '선정결과', 'final_selection', 'selection_result'))
MAX_PROGRAMS = 500


def audit(programs, index, *, run_id, as_of):
    validate_index(index)
    if not index['database_index_complete'] or index['snapshot_run_id'] != run_id:
        raise ValueError('Complete matching metadata snapshot required')
    today = date.fromisoformat(as_of)
    if not isinstance(programs, list) or len(programs) > MAX_PROGRAMS:
        raise ValueError('Published program count/type exceeds audit bounds')
    stored = {r['url'] for r in index['records']}
    rows, ids = [], set()
    for p in programs:
        ident = p['id']
        if not isinstance(ident, str) or ident in ids:
            raise ValueError('Duplicate/invalid published program identity')
        ids.add(ident)
        events = p['events']
        final = [e for e in events if e['type'] in FINAL]
        rosters = {key: p.get(key, []) for key in ('selected_gps', 'shortlisted_gps', 'preferred_gps', 'applicants_gps')}
        if any(not isinstance(v, list) for v in rosters.values()):
            raise ValueError('Invalid manager roster type')
        if any(not isinstance(g, dict) or not isinstance(g.get('name'), str) or not g['name'].strip()
               for g in rosters['selected_gps']):
            raise ValueError('Invalid selected manager record')
        selected = len(rosters['selected_gps'])
        event_urls = {e['url'] for e in events}
        missing_sources = sum(not valid_url(g.get('source_url')) or g.get('source_url') not in event_urls
                              for g in rosters['selected_gps'])
        final_urls = sorted({e['url'] for e in final})
        if any(not valid_url(u) for u in final_urls):
            raise ValueError('Invalid recorded result source URL')
        retained = sum(u in stored for u in final_urls)
        deadline_passed = False
        deadline = p.get('deadline')
        if deadline:
            # Exact ISO deadlines only. Coarse planned stages are never dates.
            try:
                parsed = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
                deadline_passed = (parsed.astimezone(ZoneInfo('Asia/Seoul')).date() if parsed.tzinfo else parsed.date()) < today
            except (ValueError, TypeError, AttributeError):
                raise ValueError('Invalid exact published deadline') from None
        if selected and not final:
            gap = 'selection_event_link_gap'
        elif selected and missing_sources:
            gap = 'selected_roster_source_gap'
        elif final and not selected:
            gap = ('stored_result_roster_not_in_public_model' if retained
                   else 'result_source_not_in_retained_index')
        elif selected:
            gap = 'model_roster_present_ui_not_rechecked'
        elif rosters['preferred_gps']:
            gap = 'preferred_only_final_unconfirmed'
        elif rosters['shortlisted_gps']:
            gap = 'screening_only_final_unconfirmed'
        elif deadline_passed:
            gap = 'deadline_passed_result_unconfirmed'
        else:
            gap = 'result_not_confirmed_by_model'
        rows.append({'program_id': ident, 'institution_id': p['institution_id'],
                     'status': p['status'], 'deadline_passed': deadline_passed,
                     'result_event_count': len(final), 'result_source_urls': final_urls,
                     'result_source_urls_in_index': retained,
                     'manager_counts': {k: len(v) for k, v in rosters.items()},
                     'selected_manager_missing_source_count': missing_sources,
                     'gap': gap, 'unpublished_claim': False})
    return {'kind': 'lp_result_gap_audit_v1', 'as_of': as_of, 'run_id': run_id,
            'database_index_checked_at': index['checked_at'], 'programs': len(rows),
            'counts': dict(Counter(r['gap'] for r in rows)), 'rows': rows,
            'official_http_requests': 0, 'database_writes': 0,
            'raw_source_rosters_replayed': False, 'browser_names_verified': False,
            'scope': 'Published program model versus complete retained metadata; not market coverage, source absence, or a claim of nonpublication.'}


def export(conn, index, *, as_of):
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    conn.execute("SET LOCAL statement_timeout='120s'")
    # Programs are plain public model fields; compressed private evidence,
    # attachment bytes, raw bodies and reviewer decisions are never selected.
    row = conn.execute("SELECT run_id,data->'programs' FROM lp_program_private.program_state WHERE id=1").fetchone()
    if not row:
        raise ValueError('No published LP model')
    return audit(row[1], index, run_id=row[0], as_of=as_of)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-index', type=Path, required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.database_index.stat().st_size > 16 * 1024 * 1024:
        raise SystemExit('Metadata index exceeds audit limit')
    index = json.loads(args.database_index.read_text())
    try:
        import psycopg
        with psycopg.connect(os.environ.get('LP_SUPABASE_DB_URL') or os.environ['SUPABASE_DB_URL'],
                              connect_timeout=20, prepare_threshold=None,
                              application_name='lp-result-gap-audit') as conn:
            report = export(conn, index, as_of=args.as_of)
    except Exception as error:
        raise SystemExit('Read-only LP result audit failed: '+type(error).__name__) from None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False))
    print(json.dumps({'programs': report['programs'], 'counts': report['counts'], 'official_http_requests': 0, 'database_writes': 0}))


if __name__ == '__main__':
    main()
