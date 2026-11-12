"""Press-reported LP selection results, shown only where no official result exists.

Policy (user decision 2026-11-12): when an LP does not publish its selection
result, reader-facing pages may show results reported by the press, always
labelled as 보도 기준 and always with the source articles. Official selected or
preferred-bidder rosters take precedence and hide the reported result. Only
managers named in the cited articles are listed; partial lists are marked.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[3] / 'data' / 'lp_reported_results.json'
STAGES = {'최종 선정', '우선협상대상자', '선정 없음'}


def _valid_date(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def validate_result(result):
    """Return a cleaned result or raise ValueError for an unusable entry."""
    if not isinstance(result, dict) or not re.fullmatch(r'[a-z0-9_-]+', str(result.get('program_id', ''))):
        raise ValueError('reported result needs a program ID')
    if result.get('stage') not in STAGES or not _valid_date(result.get('reported_at')):
        raise ValueError('reported result needs a known stage and report date')
    managers = result.get('managers')
    if (not isinstance(managers, list) or any(not isinstance(m, str) or not m.strip() for m in managers)
            or len(set(managers)) != len(managers)):
        raise ValueError('reported managers must be distinct names')
    if (result['stage'] == '선정 없음') != (not managers):
        raise ValueError('only a no-selection outcome may omit managers')
    sources = result.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError('reported result needs at least one source')
    for source in sources:
        if (not isinstance(source, dict) or not str(source.get('url', '')).startswith('https://')
                or not str(source.get('publisher', '')).strip() or not str(source.get('title', '')).strip()
                or not _valid_date(source.get('date'))):
            raise ValueError('every source needs publisher, title, date and https URL')
    if not isinstance(result.get('complete'), bool):
        raise ValueError('reported result must state whether the list is complete')
    keep = ('program_id', 'stage', 'reported_at', 'complete', 'managers', 'note', 'scope_note', 'sources')
    return {k: result[k] for k in keep if k in result}


def load_reported_results(programs, path=DEFAULT_PATH):
    """Map program ID -> reported result for programs without official names.

    Unknown programs and invalid entries are skipped (returned as holds) so a
    review mistake never blocks the official publication.
    """
    try:
        raw = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}, []
    known = {p['id']: p for p in programs}
    results, holds = {}, []
    for entry in raw.get('results', []):
        try:
            result = validate_result(entry)
        except ValueError as error:
            holds.append({'program_id': str(entry.get('program_id', '')) if isinstance(entry, dict) else '',
                          'reason': str(error)})
            continue
        program = known.get(result['program_id'])
        if program is None:
            holds.append({'program_id': result['program_id'], 'reason': 'program not published'})
        elif program.get('selected_gps') or program.get('preferred_gps'):
            holds.append({'program_id': result['program_id'], 'reason': 'official result exists'})
        elif result['program_id'] in results:
            holds.append({'program_id': result['program_id'], 'reason': 'duplicate entry'})
        else:
            results[result['program_id']] = result
    return results, holds
