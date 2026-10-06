"""Transactionally retain official evidence and publish validated LP pages."""
import argparse
import copy
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from lp_program_service import build, validate
from kgrowth_program_review import link_suggestions, reviewed_programs
from lp_review_decisions import apply_decisions
from collect_ktcu_program import project as project_ktcu, link_suggestions as suggest_ktcu, discovery_candidates as discover_ktcu
from collect_koreapost_program import project as project_post, _suggestions as suggest_post, discovery_candidates as discover_post
from collect_kexim_programs import project as project_kexim, link_suggestions as suggest_kexim, discovery_candidates as discover_kexim
from lp_notice_triage import assess_candidates

ROOT = Path(__file__).resolve().parents[3]


def document_hash(document):
    content = {key: value for key, value in document.items() if key != 'checked_at'}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def connect():
    import psycopg
    return psycopg.connect(os.environ['SUPABASE_DB_URL'], connect_timeout=20, prepare_threshold=None)


def baseline(conn):
    row = conn.execute('SELECT data FROM lp_program_private.program_state WHERE id=1').fetchone()
    data = row[0] if row else json.loads((ROOT/'data/lp_programs_pilot.json').read_text())
    data['review_decisions'] = [r[0] for r in conn.execute("SELECT to_jsonb(d) FROM lp_program_private.review_decisions d ORDER BY id").fetchall()]
    return data


def prepare(current, report):
    if not report.get('notices'):
        raise ValueError('Empty collection cannot replace published data')
    data = copy.deepcopy(current)
    updates = report.get('programs', [])
    if not updates:
        raise ValueError('No verified programs; keep existing publication')
    existing = {p['id']: p for p in data['programs']}
    for p in updates:
        if p.get('institution_id') != 'kgrowth' or p['id'] not in existing:
            raise ValueError('Unreviewed program cannot be auto-published')
        if not report.get('requires_review') and not existing[p['id']].get('manual_review_id'):
            existing[p['id']] = p
    # Independently re-project approved sources; never trust a candidate payload
    # as permission to introduce a new public program.
    additions, holds = reviewed_programs(report['notices'], report['checked_at'])
    for p in additions:
        if not existing.get(p['id'], {}).get('manual_review_id'):
            existing[p['id']] = p
    priority = report.get('priority_sources', {})
    priority_holds = []
    fresh_priority_notices = []
    projectors = {'ktcu': project_ktcu, 'koreapost': project_post, 'kexim': project_kexim}
    for institution, source in priority.items():
        if institution not in projectors:
            raise ValueError(f'Unknown LP source: {institution}')
        notices = source.get('notices', [])
        priority_holds.extend(source.get('holds', []))
        if not notices:
            continue
        projected, source_holds = projectors[institution](notices, report['checked_at'])
        priority_holds.extend(source_holds)
        fresh_priority_notices.extend({**n, 'institution_id': institution} for n in notices)
        for program in projected:
            if program['institution_id'] != institution:
                raise ValueError('LP program institution differs from official source')
            if not existing.get(program['id'], {}).get('manual_review_id'):
                existing[program['id']] = program
    data['programs'] = list(existing.values())
    data['accepted_notices'] = copy.deepcopy(report.get('accepted_notices', current.get('accepted_notices', [])))
    data['tracked_notices'] = copy.deepcopy(report.get('tracked_notices', report['notices']))
    data['candidate_groups'] = copy.deepcopy(report.get('candidate_groups', []))
    # A listing may age out a notice or a source may fail temporarily. Keep
    # previously observed official documents until their program is reviewed.
    retained = {n['url']: copy.deepcopy(n) for n in current.get('priority_notices', [])}
    for notice in fresh_priority_notices:
        previous = retained.get(notice['url'])
        if previous and previous.get('attachment_hashes') == notice.get('attachment_hashes'):
            # A transient text-extraction failure must not forget evidence
            # already read from the very same official attachment bytes.
            old_texts = previous.get('attachment_texts', {})
            notice['attachment_texts'] = {**old_texts, **notice.get('attachment_texts', {})}
        retained[notice['url']] = notice
    data['priority_notices'] = list(retained.values())
    grouped = {institution: [n for n in data['priority_notices'] if n.get('institution_id') == institution]
               for institution in projectors}
    priority_suggestions = (suggest_ktcu(grouped['ktcu'], existing['ktcu-2026-blind-pef']['title'])
                            + suggest_post(grouped['koreapost']) + suggest_kexim(grouped['kexim']))
    data['link_suggestions'] = link_suggestions(report['notices']) + priority_suggestions
    discovered = (discover_ktcu(grouped['ktcu']) + discover_post(grouped['koreapost'])
                  + discover_kexim(grouped['kexim']))
    data['discovery_candidates'] = assess_candidates(discovered, data['priority_notices'])
    data['program_holds'] = holds + priority_holds
    apply_decisions(data, report['notices'], current.get('review_decisions', []))
    data['as_of'] = str(report['checked_at'])[:10]
    validate(data)
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        build(data, out)
        pages = {p.name:p.read_text() for p in out.glob('*.html')}
        from lp_review_preview import render_review
        pages['review.html'] = render_review(data, report, current)
    return data, pages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--export-baseline', type=Path)
    parser.add_argument('--collection', type=Path)
    parser.add_argument('--priority-collection', type=Path)
    args = parser.parse_args()
    with connect() as conn:
        if args.export_baseline:
            args.export_baseline.write_text(json.dumps(baseline(conn), ensure_ascii=False))
            return
        report = json.loads(args.collection.read_text())
        if args.priority_collection:
            priority_report = json.loads(args.priority_collection.read_text())
            report['priority_sources'] = priority_report['sources']
        # One transaction and lock: evidence and public view always agree.
        conn.execute('SELECT pg_advisory_xact_lock(728160921)')
        data, pages = prepare(baseline(conn), report)
        from psycopg.types.json import Jsonb
        stamp = datetime.now(timezone.utc).isoformat()
        run_id = hashlib.sha256((stamp+json.dumps(report,sort_keys=True)).encode()).hexdigest()[:24]
        conn.execute('INSERT INTO lp_program_private.collection_runs(run_id,institution,report) VALUES (%s,%s,%s)', (run_id,'multi_lp' if args.priority_collection else 'kgrowth',Jsonb(report)))
        for doc in report['notices'] + data.get('priority_notices', []):
            digest = document_hash(doc)
            conn.execute('INSERT INTO lp_program_private.documents(source_url,content_hash,document) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (doc['url'],digest,Jsonb(doc)))
        conn.execute('INSERT INTO lp_program_private.program_state(id,data,pages,run_id) VALUES(1,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data,pages=EXCLUDED.pages,run_id=EXCLUDED.run_id,updated_at=now()', (Jsonb(data),Jsonb(pages),run_id))
    print(json.dumps({'run_id':run_id,'programs':len(data['programs']),'notices':len(report['notices']),'review':len(report.get('review',[]))}))

if __name__ == '__main__':
    main()
