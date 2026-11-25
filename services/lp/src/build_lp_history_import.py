"""Build and apply the one-time 2020+ history import (user approval 2026-11-15).

build  (offline, reviewed): keep the notices of programs the publication code forms,
       exclude live programs by identity when available, drop attachment bytes and
       validate the retained notices with lp_history_notices.validate_history_notice.
merge  (daily board job): add a pinned import file to the institution collection as
       `history_import`; the publisher validates again and retains them in state.
"""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import lp_history_notices as history  # noqa: E402
from lp_notice_publication import publish_basic_notices  # noqa: E402

MAX_IMPORT_BYTES = 40 * 1024 * 1024


def _bundle_notices(directory):
    notices = []
    for path in sorted(Path(directory).glob('*.json')):
        if path.name in ('summary.json',):
            continue
        bundle = json.loads(path.read_text())
        if bundle.get('kind') != 'lp_institution_history_v1' or bundle['institution_id'] == 'kgrowth':
            continue
        for raw in bundle['notices']:
            n = copy.deepcopy(raw)
            receipt = bundle['listing_receipts'][n['discovery_provenance']['listing']['sha256']]
            n['discovery_provenance']['listing'] = receipt
            n['attachment_bytes'] = {}
            n['history_import'] = history.KIND
            notices.append(n)
    return notices


def build(bundles, live_events, checked_at, exclude_titles=(), *, live_programs=()):
    notices = _bundle_notices(bundles)
    validated, rejected = [], []
    for n in notices:
        try:
            validated.append(history.validate_history_notice(n, checked_at))
        except (ValueError, KeyError, TypeError) as exc:
            rejected.append({'url': n['url'], 'error': str(exc)[:200]})
    programs, holds = publish_basic_notices({'programs': [], 'history_notices': validated}, [], checked_at)
    # The offline CLI can still take a date-only list. The operating check has
    # the full program records, so unrelated lifecycle events on one day may coexist.
    live_dates = {(e['institution_id'], e['date']) for e in live_events}
    live_keys = {(p['institution_id'], p['source_program_key']) for p in live_programs if p.get('source_program_key')}
    live_recruitments = {(p['institution_id'], e['url']) for p in live_programs for e in p['events']
                         if e['type'] == '모집 공고'}
    keep, skipped = set(), []
    for p in programs:
        dates = {(p['institution_id'], e['date']) for e in p.get('events', [])}
        recruitments = {(p['institution_id'], e['url']) for e in p['events'] if e['type'] == '모집 공고'}
        if ((p['institution_id'], p.get('source_program_key')) in live_keys
                or recruitments & live_recruitments or dates & live_dates):
            skipped.append({'program': p['title'], 'reason': 'overlaps a live program'})
        elif any(word in p['title'] for word in exclude_titles):
            skipped.append({'program': p['title'], 'reason': 'excluded after review'})
        else:
            keep.update(e['url'] for e in p.get('events', []))
    selected = [n for n in validated if n['url'] in keep]
    return {'kind': 'lp_history_import_v1', 'checked_at': checked_at, 'notices': selected}, {
        'bundle_notices': len(notices), 'validated': len(validated), 'rejected': rejected,
        'programs_formed': len(programs), 'skipped_programs': skipped,
        'programs_imported': len(programs) - len(skipped), 'notices_imported': len(selected),
        'publication_holds': len(holds)}


def merge(collection_path, import_path, expected_sha256):
    raw = Path(import_path).read_bytes()
    if len(raw) > MAX_IMPORT_BYTES or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('history import file differs from the reviewed request')
    payload = json.loads(raw)
    if payload.get('kind') in {history.JOINT_IMPORT_KIND, history.JOINT_FOLLOWUP_IMPORT_KIND,
                               history.JOINT_STAGES_IMPORT_KIND}:
        # This import requires a separately verified operating snapshot.
        return 0
    if payload.get('kind') != 'lp_history_import_v1':
        raise ValueError('unexpected history import kind')
    collection = json.loads(Path(collection_path).read_text())
    collection['history_import'] = {'notices': payload['notices'], 'sha256': expected_sha256}
    Path(collection_path).write_text(json.dumps(collection, ensure_ascii=False))
    return len(payload['notices'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build')
    b.add_argument('--bundles', type=Path, required=True)
    b.add_argument('--live-events', type=Path, required=True)
    b.add_argument('--checked-at', required=True)
    b.add_argument('--exclude-title', action='append', default=[])
    b.add_argument('--out', type=Path, required=True)
    m = sub.add_parser('merge')
    m.add_argument('--collection', type=Path, required=True)
    m.add_argument('--import-file', type=Path, required=True)
    m.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if args.command == 'build':
        payload, summary = build(args.bundles, json.loads(args.live_events.read_text()), args.checked_at,
                                 args.exclude_title)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
        args.out.write_bytes(encoded)
        print(json.dumps({**summary, 'bytes': len(encoded), 'sha256': hashlib.sha256(encoded).hexdigest()},
                         ensure_ascii=False, indent=1))
    else:
        print(json.dumps({'history_notices_merged': merge(args.collection, args.import_file, args.sha256)}))


if __name__ == '__main__':
    main()
