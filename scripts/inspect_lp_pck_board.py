"""Bounded read-only PCK board inspection; follow observed notice links only."""
import hashlib
import json
from pathlib import Path
import re
import sys
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.lp.src.collect_lp_institution_boards import Session
from services.lp.src.collect_shared_lp_notices import decode_html
from services.lp.src.lp_board_adapters_pensions import _Document


def main():
    root = Path(__file__).resolve().parents[1]
    row = next(x for x in json.loads((root / 'data/lp_blind_contest_screening_pensions.json').read_text())['institutions']
               if x['institution_id'] == 'pck_pension')
    listing = row['official_listing_url']
    fetch = Session({'institution_id': 'pck_pension', 'listing_url': listing})
    folder = Path('/tmp/lp-pck-inspection'); folder.mkdir(exist_ok=True)
    report = {'receipts': [], 'detail_urls': []}
    def keep(url):
        p = urlsplit(url); q = parse_qs(p.query)
        if (p.scheme != 'https' or p.hostname != 'www.pension.or.kr' or p.port not in {None, 443}
                or p.path not in {'/modu/s_board/list.asp', '/modu/s_board/read.asp'}
                or q.get('board_seq') != ['1'] or q.get('board_sub_seq') != ['1']):
            raise ValueError('Unexpected PCK board route')
        raw = fetch(url, listing)
        html = decode_html(raw)
        digest = hashlib.sha256(raw).hexdigest()
        name = str(len(report['receipts']) + 1).zfill(2) + '-' + digest[:12] + '.html'
        (folder / name).write_text(html)
        report['receipts'].append({'url': url, 'sha256': digest, 'file': name})
        return _Document(html).root
    details = {}
    for term in ('', '위탁', '출자'):
        p = urlsplit(listing); q = dict(parse_qs(p.query)); q = {k: v[0] for k, v in q.items()}
        q.update(search_select='subject', search_text=term, page='1')
        for a in keep(urlunsplit(p._replace(query=urlencode(q)))).nodes('a', 'sboard_list_sbj'):
            if re.search('위탁|운용사|출자', a.clean()) and not re.search('채용', a.clean()):
                target = urljoin(listing, a.attrs.get('href', ''))
                query = parse_qs(urlsplit(target).query)
                cells = [n for n in a.parent.parent.children if getattr(n, 'tag', None) == 'td']
                stamp = cells[3].clean()
                if stamp[:4].isdigit() and int(stamp[:4]) >= datetime.now(timezone.utc).year - 3:
                    if query.get('board_seq') != ['1'] or query.get('board_sub_seq') != ['1'] or len(query.get('seq', [])) != 1:
                        raise ValueError('Observed PCK notice board mismatch')
                    canonical = urlunsplit(urlsplit(target)._replace(query=urlencode({k: query[k][0] for k in ('board_seq', 'board_sub_seq', 'seq')})))
                    details[canonical] = stamp
    report['detail_urls'] = sorted(details, key=lambda u: (details[u], u), reverse=True)
    report['detail_limit_reached'] = len(details) > 12
    for url in report['detail_urls'][:12]:
        keep(url)
    (folder / 'inspection.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'listing_pages': 3, 'details': len(details), 'receipts': len(report['receipts'])}))


if __name__ == '__main__':
    main()
