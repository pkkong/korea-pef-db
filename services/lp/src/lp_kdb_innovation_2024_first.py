"""Read only the innovation leagues of the first-round shared KDB notices."""

import re

try:
    from . import lp_kdb_innovation_terms as innovation
    from .lp_kdb_growth_support_2024 import _APPLICATION_HEADER, _RESULT_HEADER, shared_stage
    from .lp_notice_triage import compact
except ImportError:
    import lp_kdb_innovation_terms as innovation
    from lp_kdb_growth_support_2024 import _APPLICATION_HEADER, _RESULT_HEADER, shared_stage
    from lp_notice_triage import compact


def _league_segments(plan):
    return [(s['name'], int(s['manager_count']), s['fund_target_range_krw'][0] // 10**8,
             s['fund_target_total_krw'] // 10**8) for s in plan['segments']]


def _selected(text, segments):
    lines = [compact(line) for line in text.splitlines() if line.strip()]
    if tuple(lines[:7]) != _RESULT_HEADER:
        return []
    leaders = {'소형': '신한', '중형': '산은', '대형': '산은'}
    cursor = 7
    rosters = []
    for league, count, fund, target in segments:
        block = lines[cursor:cursor + 4 + count]
        if (len(block) != 4 + count or block[:3] != [f'혁신산업/{league}({count})', f'{fund:,}', f'(총{target:,})']
                or block[4] != leaders.get(league)):
            return []
        names = [block[3], *block[5:]]
        if not all(re.fullmatch(r'[가-힣]{3,48}', name) for name in names):
            return []
        rosters.append((league, names))
        cursor += len(block)
    remaining = lines[cursor:]
    if not remaining or not remaining[0].startswith('성장지원/대형('):
        return []
    names = [name for _, names in rosters for name in names]
    return rosters if len(set(names)) == len(names) else []


def _application(text, segments):
    table = compact(text)
    if not table.startswith(_APPLICATION_HEADER) or table.count('성장지원대형(') != 1:
        return False
    innovation_rows = table.split('성장지원대형(', 1)[0]
    rows = [
        rf"{'혁신산업' if index == 0 else ''}{league}\({count}\){fund:,}총\({target:,}\)(\d{{1,2}})[가-힣]"
        for index, (league, count, fund, target) in enumerate(segments)
    ]
    matches = [list(re.finditer(row, innovation_rows)) for row in rows]
    if not all(len(row) == 1 for row in matches):
        return False
    observed = [row[0] for row in matches]
    return (all(int(row[1]) >= segment[1] for row, segment in zip(observed, segments))
            and [row.start() for row in observed] == sorted(row.start() for row in observed))


def linked_stages(notices, texts):
    originals = [n for n in notices if innovation.first_recruitment(n)]
    if len(originals) != 1:
        return {}
    original, = originals
    verified = set(texts(original)[1:])
    sources = [(url, raw, original['attachment_hashes'][url])
               for url, raw in original.get('attachment_texts', {}).items()
               if raw in verified and url in original.get('attachment_hashes', {})]
    try:
        plan = innovation.terms(original, sources)
    except ValueError:
        return {}
    if not plan.get('deadline'):
        return {}
    deadline = plan['deadline'][:10]
    segments = _league_segments(plan)
    results = {}
    for notice in notices:
        phase = shared_stage(notice)
        if not phase or notice['date'] < deadline:
            continue
        read = _selected if phase == '선정결과' else _application
        if sum(bool(read(raw, segments)) for raw in texts(notice)[1:]) == 1:
            results[notice['url']] = original
    return results


def result_roster(notice, text, program):
    if shared_stage(notice) != '선정결과' or program.get('asset_scope') != 'PE·VC 공동 모집':
        return []
    return _selected(text, _league_segments(program))
