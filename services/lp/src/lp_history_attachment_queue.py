"""Offline announcement-file priority only; never approves investment scope."""
import copy
import re
from urllib.parse import urlsplit, parse_qsl

try:
    from .collect_lp_history_bodies import validate_report
    from .lp_history_sources import institution
except ImportError:
    from collect_lp_history_bodies import validate_report
    from lp_history_sources import institution


def validate_url(url):
    if not isinstance(url, str) or re.search(r'[\s\x00-\x1f\x7f]', url):
        raise ValueError('Invalid announcement URL')
    p = urlsplit(url)
    if (p.scheme != 'https' or p.netloc != 'www.ktcu.or.kr'
            or p.path != '/comm/getFile' or p.fragment or '#' in url
            or re.search(r'%(?![0-9a-fA-F]{2})', p.query)):
        raise ValueError('Invalid announcement URL')
    pairs = parse_qsl(p.query, keep_blank_values=True, strict_parsing=True)
    q = dict(pairs)
    if (len(pairs) != 4 or set(q) != {'srvcId', 'fileTy', 'upperNo', 'fileNo'}
            or q['srvcId'] != 'BBSTY1' or q['fileTy'] != 'ATTACH'
            or any(not q[k].strip() or re.search(r'[\s\x00-\x1f\x7f]', q[k])
                   for k in ('upperNo', 'fileNo'))):
        raise ValueError('Invalid announcement query')
    return url


def plan(history, body_report, completed=(), *, limit=4):
    if type(limit) is not int or not 1 <= limit <= 4:
        raise ValueError('Attachment queue limit must be between 1 and 4')
    if institution(history) != 'ktcu':
        raise ValueError('KTCU history required')
    validate_report(copy.deepcopy(history), copy.deepcopy(body_report))
    if body_report.get('holds'):
        raise ValueError('Unblocked body report required')
    eligible = {}
    holds = []
    priority = deferred = forms = 0
    dates = {}
    for n in body_report['documents']:
        if not (re.search('PEF', n['title'], re.I) and '블라인드' in n['title']):
            deferred += 1
            continue
        priority += 1
        candidates = []
        for a in n['attachments']:
            name = a['name']
            if re.search(r'제안서\s*양식|동의서', name):
                forms += 1
            elif '공고문' in name:
                candidates.append(a)
        if len(candidates) != 1:
            holds.append({'source_id': n['source_id'], 'source_url': n['url'],
                          'reason': 'missing_announcement' if not candidates else 'ambiguous_announcement',
                          'candidate_count': len(candidates)})
            continue
        a = candidates[0]
        try:
            validate_url(a['url'])
        except ValueError:
            holds.append({'source_id': n['source_id'], 'source_url': n['url'],
                          'reason': 'invalid_attachment_url'})
            continue
        eligible[n['source_id']] = {
            'institution_id': 'ktcu', 'source_id': n['source_id'], 'source_url': n['url'],
            'body_sha256': n['sha256'], 'attachment_name': a['name'], 'attachment_url': a['url']}
        dates[n['source_id']] = n['date']
    done = set()
    for receipt in completed:
        if not isinstance(receipt, dict):
            raise ValueError('Invalid completed attachment receipt')
        ident = receipt.get('source_id')
        if not isinstance(ident, str) or ident not in eligible or ident in done:
            raise ValueError('Unknown or duplicate completed attachment')
        if (any(receipt.get(k) != v for k, v in eligible[ident].items())
                or not isinstance(receipt.get('attachment_sha256'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', receipt['attachment_sha256'])):
            raise ValueError('Completed attachment identity/hash mismatch')
        done.add(ident)
    pending = sorted(set(eligible) - done, key=lambda ident: (dates[ident], int(ident)))
    return {'institution_id': 'ktcu', 'window': copy.deepcopy(history['window']),
            'priority_count': priority, 'pending_count': len(pending), 'deferred_count': deferred,
            'completed_count': len(done), 'skipped_forms_count': forms,
            'planned_count': min(limit, len(pending)),
            'rows': [eligible[ident] for ident in pending[:limit]], 'holds': holds,
            'pe_approval': False, 'source_history_complete': False}
