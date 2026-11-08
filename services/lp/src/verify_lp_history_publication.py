"""Read-only verification of historical additions on the public LP runtime."""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen


def read_public(path):
    for attempt in range(3):
        try:
            with urlopen('https://kpef-lp.vercel.app/'+path, timeout=30) as response:
                return response.read().decode(), {k.lower(): v for k, v in response.headers.items()}
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)


def verify(published, read=read_public):
    if not published['published']:
        return {'published': False, 'reason': 'no_new_verified_programs'}
    def page(path):
        html, headers = read(path)
        if headers.get('x-lp-data-source') != 'supabase' or headers.get('x-lp-run') != published['run_id']:
            raise ValueError('Unexpected public data source/run: '+path)
        return html, headers
    for ident in published['program_ids']:
        html, _ = page('program-'+ident+'.html?refresh=1')
        if '진행 일정' not in html:
            raise ValueError('Missing public timeline: '+ident)
    for program in published['new_programs']:
        html, _ = page('program-'+program['id']+'.html')
        if program['selected_gps']:
            raise ValueError('Recruitment cannot supply a final GP roster')
        for field in ('commitment_label', 'manager_count_label'):
            if program.get(field) and program[field] not in html:
                raise ValueError('Missing public offering field: '+field)
        # The UI intentionally shows minute precision, while storage retains
        # ISO seconds and the source timezone. Compare the actual <time> label.
        deadline = datetime.fromisoformat(program['deadline']).strftime('%Y-%m-%d %H:%M')
        if '<time>'+deadline+'</time>' not in html:
            raise ValueError('Missing or changed public closing time')
        planned = sum(s.get('status') == 'planned' for s in program.get('schedule_stages', []))
        if html.count('>예정일 경과<') != planned:
            raise ValueError('Historical plans must not appear as future confirmed progress')
    html, headers = page('index.html?refresh=1')
    if headers.get('x-robots-tag') != 'index, follow' or not all(
            'program-'+p+'.html' in html for p in published['new_program_ids']):
        raise ValueError('Historical addition missing from public index')
    _, headers = page('review.html?refresh=1')
    if (headers.get('x-robots-tag') != 'noindex, nofollow' or headers.get('cache-control') != 'no-store'
            or headers.get('x-frame-options') != 'DENY'):
        raise ValueError('Review access boundaries changed')
    health = json.loads(read('health.json?refresh=1')[0])
    if (health.get('status') != 'ok' or health.get('data_source') != 'supabase'
            or health.get('stale') is not False or health.get('run_id') != published['run_id']):
        raise ValueError('Public health or publication run mismatch')
    return {'run_id': published['run_id'], 'verified_programs': len(published['program_ids']),
            'new_program_ids': published['new_program_ids'], 'access_boundaries_verified': True, 'health': health}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(json.loads(args.publication.read_text()))
    args.output.write_text(json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
