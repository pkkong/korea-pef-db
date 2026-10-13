"""Discover issuer candidates from public indexes, without approving notices.

Third-party titles are discovery leads only. Official PE/blind recruitment
evidence belongs in lp_blind_contest_screening.json. No third-party JavaScript
is executed; JSON5 decodes literal arrays. This is a research CLI, not a public
publisher or a replacement for official-board collectors.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

SITE = 'https://pe-vc-lp.com/'
BOARD = 'https://api.pe-vc-lp.com/announcements'


def fetch(url):
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': SITE})
    with urlopen(request, timeout=25) as response:
        return response.read()


def literal_array(html, name):
    import json5
    match = re.search(r'\bconst\s+' + re.escape(name) + r'\s*=\s*\[', html)
    if not match:
        raise ValueError(f'Missing public index: {name}')
    start, depth, quote, escaped = match.end()-1, 0, None, False
    for index in range(start, len(html)):
        char = html[index]
        if quote:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
        elif char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
            if depth == 0:
                return json5.loads(html[start:index+1])
    raise ValueError(f'Incomplete public index: {name}')


def discover(html, board):
    indexes = {
        'contests': literal_array(html, 'CONTEST_DEFAULT'),
        'pinned': literal_array(html, 'PINNED_ANNOUNCEMENTS'),
        'analysis': literal_array(html, 'SAMPLE_DATA'),
        'board': board['items'],
    }
    issuers = {}
    for kind, records in indexes.items():
        for record in records:
            name = record.get('lp') or record.get('site')
            if not name:
                continue
            title = record.get('nm') or record.get('title') or record.get('fullName') or ''
            # Preserve all issuers, including VC-only ones, so screening can
            # explain exclusions instead of silently hiding them.
            lead = {'index': kind, 'title': title,
                    'date': record.get('date') or record.get('pubDate') or record.get('detected_at'),
                    'url': record.get('url'), 'third_party': True,
                    'pe_title_hint': bool(re.search(r'PEF|\bPE\b|사모', title, re.I)),
                    'blind_title_hint': '블라인드' in title}
            issuers.setdefault(name, []).append(lead)
    return {'source_urls': [SITE, BOARD],
            'index_counts': {kind: len(records) for kind, records in indexes.items()},
            'issuers': [{'name': name, 'leads': leads} for name, leads in sorted(issuers.items())],
            'source_note': 'Third-party leads are not official recruitment evidence or a notice allowlist.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--html', type=Path)
    parser.add_argument('--board', type=Path)
    args = parser.parse_args()
    raw_html = args.html.read_bytes() if args.html else fetch(SITE)
    raw_board = args.board.read_bytes() if args.board else fetch(BOARD)
    result = discover(raw_html.decode('utf-8'), json.loads(raw_board))
    result['source_hashes'] = {SITE: hashlib.sha256(raw_html).hexdigest(),
                               BOARD: hashlib.sha256(raw_board).hexdigest()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'index_counts': result['index_counts'], 'issuers': len(result['issuers'])}))


if __name__ == '__main__':
    main()
