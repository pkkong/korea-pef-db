"""Keep published program URLs working after a verified duplicate merge.

When two published basic programs turn out to be the same solicitation (an
association repost and the institution's own notice), only one program stays.
The other's public address must not disappear (AGENTS.md: retain existing
URLs), so it becomes an alias page that points to the kept program.

An alias is created only from a `basic_duplicate` hold naming both ids, and
only for an id that was published before. Earlier aliases are carried forward
and re-resolved; an alias is dropped only when its id is a program again.
`data/lp_program_aliases.json` holds reviewed aliases for ids that vanished
before this module existed (each entry names its evidence).
"""
from __future__ import annotations

from html import escape
import json
from pathlib import Path
import re

SEEDS = Path(__file__).resolve().parents[3] / 'data' / 'lp_program_aliases.json'

ID = re.compile(r'[a-z0-9][a-z0-9_-]{0,199}')


def load_seeds(path=SEEDS):
    """Reviewed {old_id: kept_id} entries; a missing file means none."""
    if not path.exists():
        return {}
    entries = json.loads(path.read_text(encoding='utf-8'))['aliases']
    seeds = {}
    for entry in entries:
        old, new = entry['program_id'], entry['kept_program_id']
        if not (ID.fullmatch(old) and ID.fullmatch(new)) or old == new or not entry.get('evidence'):
            raise ValueError('Invalid reviewed program alias')
        seeds[old] = new
    return seeds


def update_aliases(current, programs, holds, seeds=None):
    """Return {old_id: kept_id} for every previously public id that now has no program."""
    published = {p['id'] for p in programs}
    before = {p['id'] for p in current.get('programs', [])}
    links = {old: new for old, new in (current.get('program_aliases') or {}).items()
             if isinstance(old, str) and isinstance(new, str)}
    for old, new in (seeds or {}).items():
        links.setdefault(old, new)
    for hold in holds:
        old, new = hold.get('program_id'), hold.get('kept_program_id')
        if hold.get('stage') == 'basic_duplicate' and old in before | set(links) and new in published:
            links[old] = new
    aliases = {}
    for old in links:
        if old in published or not ID.fullmatch(old):
            continue
        target, seen = links[old], {old}
        while target not in published and target in links and target not in seen:
            seen.add(target)
            target = links[target]
        if target in published:
            aliases[old] = target
    return dict(sorted(aliases.items()))


def missing_published_ids(current, programs, aliases):
    """Previously published ids that would vanish without a program or alias."""
    kept = {p['id'] for p in programs} | set(aliases)
    return sorted(p['id'] for p in current.get('programs', []) if p['id'] not in kept)


def alias_page(old_id, program):
    target = f"program-{program['id']}.html"
    title = escape(str(program.get('title') or program['id']), quote=True)
    institution = escape(str(program.get('institution_name') or ''), quote=True)
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} | 합쳐진 사업</title>
<meta name="robots" content="noindex, follow">
<link rel="canonical" href="{target}">
<meta http-equiv="refresh" content="0; url={target}">
</head><body>
<main data-program-alias="{escape(old_id, quote=True)}">
<p>이 주소의 사업은 같은 공고의 재게시본과 합쳐졌습니다.</p>
<p><a href="{target}">{institution} {title}</a>로 이동합니다.</p>
</main></body></html>
'''


def alias_pages(programs, aliases):
    by_id = {p['id']: p for p in programs}
    return {f'program-{old}.html': alias_page(old, by_id[new]) for old, new in aliases.items()}
