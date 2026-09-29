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
from kgrowth_program_review import reviewed_programs

ROOT = Path(__file__).resolve().parents[3]


def document_hash(document):
    content = {key: value for key, value in document.items() if key != 'checked_at'}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def connect():
    import psycopg
    return psycopg.connect(os.environ['SUPABASE_DB_URL'], connect_timeout=20)


def baseline(conn):
    row = conn.execute('SELECT data FROM lp_program_private.program_state WHERE id=1').fetchone()
    return row[0] if row else json.loads((ROOT/'data/lp_programs_pilot.json').read_text())


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
        if not report.get('requires_review'):
            existing[p['id']] = p
    # Independently re-project approved sources; never trust a candidate payload
    # as permission to introduce a new public program.
    additions, holds = reviewed_programs(report['notices'])
    for p in additions:
        existing[p['id']] = p
    data['programs'] = list(existing.values())
    data['accepted_notices'] = copy.deepcopy(report.get('accepted_notices', current.get('accepted_notices', [])))
    data['tracked_notices'] = copy.deepcopy(report.get('tracked_notices', report['notices']))
    data['candidate_groups'] = copy.deepcopy(report.get('candidate_groups', []))
    data['program_holds'] = holds
    data['as_of'] = str(report['checked_at'])[:10]
    validate(data)
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        build(data, out)
        pages = {p.name:p.read_text() for p in out.glob('*.html')}
    return data, pages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--export-baseline', type=Path)
    parser.add_argument('--collection', type=Path)
    args = parser.parse_args()
    with connect() as conn:
        if args.export_baseline:
            args.export_baseline.write_text(json.dumps(baseline(conn), ensure_ascii=False))
            return
        report = json.loads(args.collection.read_text())
        # One transaction and lock: evidence and public view always agree.
        conn.execute('SELECT pg_advisory_xact_lock(728160921)')
        data, pages = prepare(baseline(conn), report)
        from psycopg.types.json import Jsonb
        stamp = datetime.now(timezone.utc).isoformat()
        run_id = hashlib.sha256((stamp+json.dumps(report,sort_keys=True)).encode()).hexdigest()[:24]
        conn.execute('INSERT INTO lp_program_private.collection_runs(run_id,institution,report) VALUES (%s,%s,%s)', (run_id,'kgrowth',Jsonb(report)))
        for doc in report['notices']:
            digest = document_hash(doc)
            conn.execute('INSERT INTO lp_program_private.documents(source_url,content_hash,document) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (doc['url'],digest,Jsonb(doc)))
        conn.execute('INSERT INTO lp_program_private.program_state(id,data,pages,run_id) VALUES(1,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data,pages=EXCLUDED.pages,run_id=EXCLUDED.run_id,updated_at=now()', (Jsonb(data),Jsonb(pages),run_id))
    print(json.dumps({'run_id':run_id,'programs':len(data['programs']),'notices':len(report['notices']),'review':len(report.get('review',[]))}))

if __name__ == '__main__':
    main()
