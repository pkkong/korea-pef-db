"""Reuse one bounded, raw-verified screening capture without official HTTP."""
from __future__ import annotations

import base64
import copy
import hashlib

try:
    from . import collect_kexim_programs as k
    from .kexim_followup import augment_recipe
except ImportError:
    import collect_kexim_programs as k
    from kexim_followup import augment_recipe


def reuse_stage_evidence(source: dict, notice: dict, raw_detail: bytes,
                         raw_attachment: bytes) -> tuple[dict, dict]:
    """Keep the original collection intact except this same-source proof upgrade."""
    if source.get('error') or not source.get('notices'):
        raise ValueError('Cannot upgrade a failed or empty KEXIM source')
    ident = str(notice.get('source_id', ''))
    previous = [n for n in source['notices'] if str(n.get('source_id')) == ident]
    if len(previous) != 1 or ident in k._approved_source_ids():
        raise ValueError('Exactly one existing unreviewed source is required')
    if k._stage(notice.get('title', '')) != '서류심사 결과':
        raise ValueError('Only a screening proof may be reused')
    for field in ('source_id', 'url', 'title', 'date', 'body', 'attachments', 'sha256', 'attachment_hashes'):
        if previous[0].get(field) != notice.get(field):
            raise ValueError('Retained KEXIM source changed: '+field)
    parsed = k.parse_detail(ident, raw_detail)
    if any(notice.get(field) != value for field, value in parsed.items()):
        raise ValueError('Detail response differs from retained fields')
    expected = copy.deepcopy(parsed)
    k.retain_detail_proof(expected, raw_detail)
    if notice.get('detail_proof') != expected['detail_proof']:
        raise ValueError('Detail raw proof differs from retained response')
    url = notice['attachments'][0]['url']
    decoded = k.validate_attachment_proof(notice, url)
    if decoded is None or decoded['format'] != 'pdf':
        raise ValueError('A readable complete PDF is required')
    proof = notice['attachment_proofs'][url]
    if (base64.b64decode(proof['raw_base64'], validate=True) != raw_attachment
            or hashlib.sha256(raw_attachment).hexdigest() != notice['attachment_hashes'][url]):
        raise ValueError('Attachment response differs from retained proof')
    # No user-picked source approval: the ordinary automatic adapter must prove
    # one existing business identity and isolate its prior applicant PE tracks.
    recipes = [r for r in k._recipes() if k._title_matches(r, notice['title'])]
    if len(recipes) != 1:
        raise ValueError('Ambiguous or unmatched existing screening business')
    checked_at = source['checked_at']
    upgraded_notices = [copy.deepcopy(notice if str(n['source_id']) == ident else n)
                        for n in source['notices']]
    augmented = augment_recipe(recipes[0], upgraded_notices, checked_at)
    if not any(str(s['source_id']) == ident for s in augmented['sources']):
        raise ValueError('Automatic adapter did not accept the screening evidence')
    before, _ = k.project(source['notices'], checked_at)
    after, holds = k.project(upgraded_notices, checked_at)
    by_id = {p['id']: p for p in after}
    target = by_id.get(recipes[0]['id'])
    if (not target or not target.get('shortlisted_gps') or target.get('selected_gps')
            or target.get('status') != '서류심사 결과'):
        raise ValueError('Screening did not project as screening only')
    for old in before:
        if old['id'] != target['id'] and by_id.get(old['id']) != old:
            raise ValueError('Unrelated KEXIM business changed')
    upgraded = copy.deepcopy(source)
    upgraded.update(notices=upgraded_notices, programs=after, holds=holds,
                    link_suggestions=k.link_suggestions(upgraded_notices),
                    discovery_candidates=k.discovery_candidates(upgraded_notices))
    receipt = {'program_id': target['id'], 'source_id': ident,
               'screening_count': len(target['shortlisted_gps']),
               'source_url': notice['url'], 'official_http_requests': 0,
               'selected_gp_additions': 0}
    return upgraded, receipt
