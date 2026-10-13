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
from lp_notice_terms import project_discovered
from lp_joint_terms import discovered_joint_terms
from kgrowth_notice_terms import discovery as discover_growth_terms
from lp_shared_notice_catalog import update_shared_catalog

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
    # Discover and re-extract without trusting the collector's prepared facts.
    # Reviewed source identity/GP history is retained; offering numbers come
    # directly from the current, independently validated attachment text.
    growth_terms, growth_term_holds, growth_candidates = discover_growth_terms(report['notices'])
    verified = {p['id'] for p in additions}
    growth_unlinked = []
    for candidate in growth_candidates:
        program = next((p for p in existing.values() if p['institution_id'] == 'kgrowth'
                        and candidate['url'] in {e['url'] for e in p['events']}), None)
        if program and not program.get('auto_extracted'):
            if program['id'] in verified and not program.get('manual_review_id') and candidate['url'] in growth_terms:
                terms = copy.deepcopy(growth_terms[candidate['url']])
                planned = terms.pop('planned_schedule', [])
                program.update(terms)
                program['schedule_stages'] = [s for s in program.get('schedule_stages', [])
                                              if not (s.get('status') == 'planned' and s.get('source_url') == candidate['url'])] + planned
                program['schedule_stages'].sort(key=lambda s: s['date'])
        else:
            growth_unlinked.append(candidate)
    priority = report.get('priority_sources', {})
    priority_holds = []
    fresh_priority_notices = []
    supporting = {n['url']: copy.deepcopy(n) for n in current.get('supporting_notices', [])}
    projectors = {'ktcu': project_ktcu, 'koreapost': project_post, 'kexim': project_kexim}
    for institution, source in priority.items():
        if institution not in projectors:
            raise ValueError(f'Unknown LP source: {institution}')
        notices = source.get('notices', [])
        priority_holds.extend(source.get('holds', []))
        priority_holds.extend(source.get('supporting_holds', []))
        for related in source.get('supporting_notices', []):
            supporting[related['url']] = copy.deepcopy(related)
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
            notice['attachment_texts'] = {**old_texts, **{url: text for url, text in notice.get('attachment_texts', {}).items() if text.strip()}}
        retained[notice['url']] = notice
    data['priority_notices'] = list(retained.values())
    data['supporting_notices'] = list(supporting.values())
    grouped = {institution: [n for n in data['priority_notices'] if n.get('institution_id') == institution]
               for institution in projectors}
    priority_suggestions = (suggest_ktcu(grouped['ktcu'], existing['ktcu-2026-blind-pef']['title'])
                            + suggest_post(grouped['koreapost']) + suggest_kexim(grouped['kexim']))
    data['link_suggestions'] = link_suggestions(report['notices']) + priority_suggestions
    discovered = (discover_ktcu(grouped['ktcu']) + discover_post(grouped['koreapost'])
                  + discover_kexim(grouped['kexim']))
    official_notices = data['priority_notices'] + data['supporting_notices']
    data['discovery_candidates'] = assess_candidates(discovered, official_notices)
    data['discovery_terms'], joint_holds = discovered_joint_terms(data['discovery_candidates'], official_notices)
    growth_notices = [{**n, 'institution_id': 'kgrowth'} for n in report['notices']]
    # Reassess mixed/unknown legal forms from offering text only, excluding forms.
    from kgrowth_notice_terms import is_offering_text
    growth_scoped = [{**n, 'attachment_texts': {u: t for u, t in n.get('attachment_texts', {}).items()
                                              if is_offering_text(t)}} for n in growth_notices]
    growth_candidates = assess_candidates(growth_unlinked, growth_scoped)
    data['discovery_candidates'].extend(growth_candidates)
    data['kgrowth_offering_terms'] = growth_terms
    data['attachment_coverage'] = copy.deepcopy(report.get('collection_coverage', {}))
    data['extraction_holds'] = growth_term_holds
    automatic, automatic_holds = project_discovered(discovered, official_notices, report['checked_at'])
    growth_automatic, growth_automatic_holds = project_discovered(growth_candidates, growth_scoped, report['checked_at'])
    automatic.extend(growth_automatic)
    automatic_holds.extend(growth_automatic_holds)
    automatic_ids = {p['id'] for p in automatic}
    hold_ids = {h['program_id'] for h in automatic_holds}
    for p in existing.values():
        if p.get('auto_extracted') and p['id'] not in automatic_ids | hold_ids:
            automatic_holds.append({'program_id': p['id'], 'reason': '현재 원문에서 PE 범위 또는 필수 항목 재확인 불가; 기존 공개본 유지'})
    for program in automatic:
        if not existing.get(program['id'], {}).get('manual_review_id'):
            existing[program['id']] = program
    data['programs'] = list(existing.values())
    data['program_holds'] = holds + priority_holds + automatic_holds + joint_holds
    data.update(update_shared_catalog(current, report.get('shared_collection'), report['checked_at']))
    seen_urls = {n['url'] for n in data['discovery_candidates']}
    data['discovery_candidates'].extend(n for n in data['shared_discovery_candidates'] if n['url'] not in seen_urls)
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
    parser.add_argument('--shared-collection', type=Path)
    args = parser.parse_args()
    with connect() as conn:
        if args.export_baseline:
            args.export_baseline.write_text(json.dumps(baseline(conn), ensure_ascii=False))
            return
        report = json.loads(args.collection.read_text())
        if args.priority_collection:
            priority_report = json.loads(args.priority_collection.read_text())
            report['priority_sources'] = priority_report['sources']
        if args.shared_collection:
            report['shared_collection'] = (json.loads(args.shared_collection.read_text()) if args.shared_collection.exists() else
                                          {'notices': [], 'holds': [{'stage': 'listing', 'error': '협회 수집 파일 없음; 이전 자료 유지'}]})
        # One transaction and lock: evidence and public view always agree.
        conn.execute('SELECT pg_advisory_xact_lock(728160921)')
        data, pages = prepare(baseline(conn), report)
        from psycopg.types.json import Jsonb
        stamp = datetime.now(timezone.utc).isoformat()
        run_id = hashlib.sha256((stamp+json.dumps(report,sort_keys=True)).encode()).hexdigest()[:24]
        conn.execute('INSERT INTO lp_program_private.collection_runs(run_id,institution,report) VALUES (%s,%s,%s)', (run_id,'multi_lp' if args.priority_collection else 'kgrowth',Jsonb(report)))
        for doc in report['notices'] + data.get('priority_notices', []) + data.get('supporting_notices', []) + data.get('shared_notices', []):
            digest = document_hash(doc)
            conn.execute('INSERT INTO lp_program_private.documents(source_url,content_hash,document) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (doc['url'],digest,Jsonb(doc)))
        conn.execute('INSERT INTO lp_program_private.program_state(id,data,pages,run_id) VALUES(1,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data,pages=EXCLUDED.pages,run_id=EXCLUDED.run_id,updated_at=now()', (Jsonb(data),Jsonb(pages),run_id))
    print(json.dumps({'run_id':run_id,'programs':len(data['programs']),'program_ids':[p['id'] for p in data['programs']],
                      'notices':len(report['notices']),'review':len(report.get('review',[])),
                      'shared_notices':len(data.get('shared_notices',[])),
                      'shared_institutions':sorted({n['institution_id'] for n in data.get('shared_notices',[])})}))

if __name__ == '__main__':
    main()
