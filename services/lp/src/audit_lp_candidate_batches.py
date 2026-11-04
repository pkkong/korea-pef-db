"""Verify every observed candidate in bounded batches, retaining replayable progress.

This is read-only. A checkpoint supplies receipt HTML, never approval or facts.
The workflow verifies artifact provenance before allowing a previous checkpoint.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

try:
    from . import audit_lp_candidate_sources as sources
except ImportError:
    import audit_lp_candidate_sources as sources


def input_fingerprint(discovery, official_inventory, as_of):
    # Replaying the same saved lists adds only this operating annotation.
    inventory = {k: v for k, v in official_inventory.items() if k != 'classification_replay_of'}
    encoded = json.dumps({'discovery': discovery, 'inventory': inventory, 'as_of': as_of},
                         sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def resume_cache(resume, fingerprint):
    if resume.get('batch_version') != 1 or resume.get('input_sha256') != fingerprint:
        raise ValueError('Candidate checkpoint does not match the saved discovery and official inventory')
    cache = {}; size = 0
    for receipt in resume.get('receipts', []):
        if (receipt.get('kind') not in {'listing', 'detail'}
                or not all(isinstance(receipt.get(k), str) for k in ('institution_id', 'url', 'html', 'sha256'))):
            raise ValueError('Candidate checkpoint receipt is malformed')
        raw = receipt['html'].encode()
        if hashlib.sha256(raw).hexdigest() != receipt['sha256']:
            raise ValueError('Candidate checkpoint receipt fingerprint mismatch')
        key = (receipt['institution_id'], receipt['kind'], receipt['url'])
        if key in cache and cache[key] != raw:
            raise ValueError('Candidate checkpoint has conflicting receipts')
        if key not in cache:
            size += len(raw)
            # Includes the existing inventory's listing receipts (32 MiB)
            # plus fetched HTML, whose UTF-8 replay can exceed its wire size.
            # Fresh network requests still share the original 20 MiB limit.
            if size > 64 * 1024 * 1024:
                raise ValueError('Candidate checkpoint receipt cache exceeds safety budget')
            cache[key] = raw
    return cache


def run_batches(discovery, official_inventory, *, batch_size=20, fetch_factory=None,
                as_of=None, sema_channels=None, resume=None, checkpoint=None):
    if type(batch_size) is not int or not 1 <= batch_size <= 20:
        raise ValueError('Batch size must be an integer between 1 and 20')
    as_of = as_of or official_inventory.get('as_of')
    fingerprint = input_fingerprint(discovery, official_inventory, as_of)
    context = {'cache': resume_cache(resume, fingerprint) if resume is not None else {},
               'sessions': {}, 'network_bytes': 0}
    candidates = sources.candidates_for(discovery, official_inventory) if discovery.get('status') == 'ok' else []
    report = {'batch_version': 1, 'input_sha256': fingerprint,
              'checked_at': datetime.now(timezone.utc).isoformat(),
              'mode': 'read_only_official_source_verification', 'batches': [],
              'sources': [{'discovery_id': n['id'], 'institution_id': n['institution_id'],
                           'discovery_title': n['title'], 'candidate': copy.deepcopy(n),
                           'status': 'pending', 'reason': 'awaiting_batch',
                           'classification': 'scope_unconfirmed', 'official_notice': None}
                          for n in candidates],
              'receipts': [], 'holds': [], 'complete': False, 'remaining_count': len(candidates)}
    if discovery.get('status') != 'ok':
        report['holds'].append({'stage': 'discovery', 'reason': 'Discovery comparison unavailable'})

    def save():
        items = report['sources']
        attempted = sum(n['status'] != 'pending' for n in items)
        report['remaining_count'] = len(items) - attempted
        report['complete'] = discovery.get('status') == 'ok' and all(n['status'] == 'official_source_verified' for n in items)
        report['summary'] = {'candidates': len(items), 'attempted': attempted,
                             'verified': sum(n['status'] == 'official_source_verified' for n in items),
                             'unresolved': sum(n['status'] != 'official_source_verified' for n in items),
                             'outside_policy_verified': sum(n['classification'] == 'outside_policy' for n in items),
                             'scope_unconfirmed': sum(n['classification'] == 'scope_unconfirmed' for n in items),
                             'remaining_count': report['remaining_count'], 'complete': report['complete'],
                             'batch_size': batch_size, 'batch_count': len(report['batches']),
                             'network_bytes': context['network_bytes'],
                             'source_errors': sum(n.get('failure_kind') in {'source_error', 'budget_error', 'evidence_error'} for n in items)
                                              + int(discovery.get('status') != 'ok')}
        if checkpoint:
            checkpoint(copy.deepcopy(report))

    save()  # Preserve every unattempted candidate before the first request.
    receipt_keys = set()
    for start in range(0, len(candidates), batch_size):
        chunk = candidates[start:start + batch_size]
        # The resolver still replays the official lists for each candidate.
        # Disable automatic inventory augmentation only because the complete
        # deterministic queue above already includes those inventory candidates.
        batch_discovery = {'status': 'ok', 'items': [dict(n, status=n.get('status', 'official_link_to_verify')) for n in chunk]}
        before_bytes = context['network_bytes']
        batch = sources.resolve(batch_discovery, {'receipts': official_inventory['receipts']},
                                fetch_factory=fetch_factory, as_of=as_of, sema_channels=sema_channels,
                                candidate_limit=batch_size, _context=context)
        if len(batch['sources']) != len(chunk):
            raise ValueError('Candidate batch changed the queued candidate count')
        for original, result in zip(chunk, batch['sources']):
            if (result['discovery_id'], result['institution_id'], result['discovery_title']) != (original['id'], original['institution_id'], original['title']):
                raise ValueError('Candidate batch changed a queued discovery connection')
            result['candidate'] = copy.deepcopy(original)
        report['sources'][start:start + len(chunk)] = batch['sources']
        report['holds'].extend(batch['holds'])
        for receipt in batch['receipts']:
            key = (receipt['institution_id'], receipt['kind'], receipt['url'], receipt['sha256'])
            if key not in receipt_keys:
                report['receipts'].append(receipt); receipt_keys.add(key)
        report['batches'].append({'index': len(report['batches']) + 1, 'start': start, 'count': len(chunk),
                                  'verified': batch['summary']['verified'],
                                  'network_bytes': context['network_bytes'] - before_bytes})
        save()
    return report


def atomic_checkpoint(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discovery', required=True, type=Path)
    parser.add_argument('--inventory', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--batch-size', type=int, default=20)
    args = parser.parse_args()
    report = run_batches(json.loads(args.discovery.read_text()), json.loads(args.inventory.read_text()),
                         batch_size=args.batch_size,
                         resume=json.loads(args.resume.read_text()) if args.resume else None,
                         checkpoint=lambda report: atomic_checkpoint(args.output, report))
    print(json.dumps(report['summary'], ensure_ascii=False))


if __name__ == '__main__':
    main()
