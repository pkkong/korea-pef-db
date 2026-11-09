"""Replayable KEXIM PE screening evidence, without new scope/GP approval.

Only an already reviewed recipe's applicants can become screening candidates.
The table format must explicitly separate the PE business and venture business;
unknown names, rows, counts or business identity leave the old review hold intact.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import re
from datetime import datetime
from zoneinfo import ZoneInfo

MAX_DETAIL_BYTES = 12 * 1024 * 1024
DETAIL_KIND = 'kexim_detail_body_v1'


def _collector():
    # The collector imports this adapter only when projecting a recipe.
    try:
        from . import collect_kexim_programs
    except ImportError:
        import collect_kexim_programs
    return collect_kexim_programs


def _compact(text):
    return re.sub(r'\s+', '', text)


def _period(title):
    matches = re.findall(r'(20[0-9]{2})년?(상반기|하반기)', _compact(title))
    if len(matches) != 1:
        raise ValueError('KEXIM followup year/half is ambiguous')
    return matches[0]


def _business(text):
    return re.sub(r'[^0-9A-Za-z가-힣]', '', text)


def validate_detail_proof(notice):
    """Replay the complete saved detail HTML; metadata/hash alone is insufficient."""
    proof = notice.get('detail_proof')
    if (not isinstance(proof, dict) or set(proof) != {'kind', 'raw_base64', 'sha256', 'byte_length'}
            or proof.get('kind') != DETAIL_KIND or not isinstance(proof.get('raw_base64'), str)
            or len(proof['raw_base64']) > ((MAX_DETAIL_BYTES + 2) // 3) * 4):
        raise ValueError('KEXIM detail raw proof missing/invalid or exceeds size limit')
    try:
        raw = base64.b64decode(proof['raw_base64'], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('KEXIM detail raw encoding invalid') from error
    if (not raw or len(raw) > MAX_DETAIL_BYTES or type(proof['byte_length']) is not int
            or proof['byte_length'] != len(raw) or hashlib.sha256(raw).hexdigest() != proof['sha256']
            or base64.b64encode(raw).decode('ascii') != proof['raw_base64']):
        raise ValueError('KEXIM detail raw/hash/size mismatch')
    source_id = notice.get('source_id')
    if not isinstance(source_id, str) or not re.fullmatch(r'[1-9][0-9]*', source_id):
        raise ValueError('KEXIM detail source identity invalid')
    parsed = _collector().parse_detail(source_id, raw)
    if any(notice.get(key) != value for key, value in parsed.items()):
        raise ValueError('KEXIM detail body/metadata/attachment mismatch')
    return parsed


def _screening_table(recipe, text):
    """Read names from the isolated PE block, anchored to reviewed applicants."""
    period = _period(recipe['title'])
    business = re.sub(r'20[0-9]{2}년?\s*(상반기|하반기)', '', recipe['title'])
    business = re.sub(r'\(\s*PE\s*\)\s*$', '', business, flags=re.I)
    business = _business(business)
    headings = list(re.finditer(r'\[([^\]]{1,200})\]', text))
    pe = [i for i, h in enumerate(headings) if _business(h[1]) == business]
    if len(pe) != 1 or pe[0] + 1 >= len(headings):
        raise ValueError('KEXIM screening PE/VC business boundary missing/ambiguous')
    index = pe[0]
    next_heading = _business(headings[index + 1][1])
    if '벤처' not in next_heading and 'VC' not in next_heading.upper():
        raise ValueError('KEXIM screening following business is not an isolated venture section')
    header = _compact(text[:headings[index].start()])
    if (_period(header) != period or '블라인드펀드출자사업' not in header
            or '심사결과' not in header or '현장실사' not in header or '제안서발표' not in header
            or any(word in header for word in ('최종선정', '선정결과', '우선협상', '약정', '납입'))):
        raise ValueError('KEXIM screening attachment business/stage header mismatch')
    block = text[headings[index].end():headings[index + 1].start()]
    compact = _compact(block)
    count = list(re.finditer(r'합계.*?([0-9]+)개사\(중형([0-9]+),소형([0-9]+)\)', compact))
    if len(count) != 1:
        raise ValueError('KEXIM screening PE total/track counts missing/ambiguous')
    total, medium, small = map(int, count[0].groups())
    if not (0 < medium <= 100 and 0 < small <= 100 and total == medium + small):
        raise ValueError('KEXIM screening PE counts invalid')
    applicants = recipe.get('manager_lists', {}).get('applicants')
    if not isinstance(applicants, dict) or len(applicants) != 2:
        raise ValueError('KEXIM screening reviewed applicant tracks missing')
    track_by_size = {}
    for size in ('중형', '소형'):
        tracks = [track for track in applicants if size in track]
        if len(tracks) != 1:
            raise ValueError('KEXIM screening reviewed track identity ambiguous')
        track_by_size[size] = tracks[0]
    if len(set(track_by_size.values())) != 2:
        raise ValueError('KEXIM screening reviewed tracks overlap')
    boundaries = {}
    for size, track in track_by_size.items():
        headings = list(re.finditer(re.escape(_compact(track)) + '분야', compact))
        if len(headings) != 1:
            raise ValueError('KEXIM screening track row missing/ambiguous')
        boundaries[size] = headings[0]
    if not (boundaries['중형'].end() < boundaries['소형'].start() < count[0].start()):
        raise ValueError('KEXIM screening official track rows reordered/overlap')
    names = {}
    for track, entries in applicants.items():
        if not isinstance(entries, list) or not entries:
            raise ValueError('KEXIM screening reviewed applicants missing')
        for name in entries:
            if not isinstance(name, str) or not name.strip() or _compact(name) in names:
                raise ValueError('KEXIM screening applicant identity duplicate/invalid')
            names[_compact(name)] = (track, name)
    # Match complete known names longest-first; any remaining unknown roster
    # words are rejected below rather than silently counted as a known GP.
    name_pattern = '|'.join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    matches = list(re.finditer(name_pattern, compact))
    found = [m[0] for m in matches]
    if len(found) != len(set(found)):
        raise ValueError('KEXIM screening duplicate manager occurrence')
    shortlist = {track: [] for track in applicants}
    rows = {'중형': compact[boundaries['중형'].end():boundaries['소형'].start()],
            '소형': compact[boundaries['소형'].end():count[0].start()]}
    for size, row in rows.items():
        track = track_by_size[size]
        for match in re.finditer(name_pattern, row):
            original_track, original = names[match[0]]
            if original_track != track:
                raise ValueError('KEXIM screening official row differs from prior applicant track')
            shortlist[track].append(original)
    expected = {track_by_size['중형']: medium, track_by_size['소형']: small}
    if (len(found) != total or sum(map(len, shortlist.values())) != total
            or any(len(shortlist[track]) != number for track, number in expected.items())):
        raise ValueError('KEXIM screening names/track counts differ from official total')
    residual = re.sub('|'.join(re.escape(name) for name in sorted(names, key=len, reverse=True)), '', compact)
    vocabulary = ['지원분야', '수은출자예정금액', '선정예정운용사수', '대상운용사명',
                  '분야별가나다순', '합계', '억원', '개사', '분야', '중형', '소형']
    vocabulary += [_compact(track).replace('중형', '').replace('소형', '') for track in applicants]
    for word in sorted(set(vocabulary), key=len, reverse=True):
        if word:
            residual = residual.replace(word, '')
    if re.sub(r'[\W0-9_]+', '', residual):
        raise ValueError('KEXIM screening PE table has unparsed names/labels')
    return shortlist, block.strip(), total


def augment_recipe(recipe, notices, checked_at):
    """Return a copied recipe with one proven PE screening followup, or unchanged.

    No candidate is a no-op. An eligible but unproven/ambiguous candidate raises
    ValueError so the caller retains its existing review hold. Final selection,
    allocations, offering conditions and existing recipe evidence are untouched.
    """
    collector = _collector()
    result = copy.deepcopy(recipe)
    lists = recipe.get('manager_lists', {})
    if (lists.get('selected') or lists.get('shortlist')
            or any(source.get('event') in ('최종 선정', '서류심사 결과') for source in recipe.get('sources', []))):
        return result
    if not re.search(r'\(\s*PE\s*\)\s*$', recipe.get('title', ''), re.I):
        return result
    approved = {str(source['source_id']) for source in recipe['sources']}
    candidates = [notice for notice in notices if str(notice.get('source_id')) not in approved
                  and collector._title_matches(recipe, notice.get('title', ''))
                  and collector._stage(notice.get('title', '')) == '서류심사 결과']
    if not candidates:
        return result
    if len(candidates) != 1:
        raise ValueError('KEXIM screening followup candidate is ambiguous')
    notice = candidates[0]
    now = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    if now.tzinfo is None:
        raise ValueError('KEXIM followup checked_at requires timezone')
    period = _period(recipe['title'])
    body = _compact(notice['body'])
    if (_period(notice['title']) != period or _period(notice['body']) != period
            or '서류심사결과' not in body or '블라인드펀드출자사업' not in body
            or any(word in _compact(notice['title']) for word in ('최종선정', '선정결과', '우선협상', '약정', '납입'))):
        raise ValueError('KEXIM screening notice business/period/stage mismatch')
    if (notice['date'] <= max(source['date'] for source in recipe['sources'])
            or notice['date'] > now.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()):
        raise ValueError('KEXIM screening followup date is not a subsequent observed stage')
    validate_detail_proof(notice)
    extracted = collector.validate_attachment_proof(notice)
    if not extracted or extracted['format'] != 'pdf':
        raise ValueError('KEXIM screening complete raw PDF proof required')
    shortlist, quote, total = _screening_table(recipe, extracted['text'])
    url = notice['attachments'][0]['url']
    if set(notice['attachment_hashes']) != {url}:
        raise ValueError('KEXIM screening has unverified additional attachment hashes')
    result['sources'].append({'source_id': notice['source_id'], 'date': notice['date'],
                              'event': '서류심사 결과', 'sha256': notice['sha256'],
                              'attachment_hashes': copy.deepcopy(notice['attachment_hashes']), 'team_count': total})
    result['manager_lists']['shortlist'] = shortlist
    result.setdefault('manager_evidence', {})['shortlist'] = {
        'source_id': notice['source_id'], 'attachment_url': url, 'quote': quote}
    return result
