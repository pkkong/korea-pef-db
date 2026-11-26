"""Retain the original enterprise recruitment behind an archived KGrowth listing."""

import base64
from datetime import date, datetime, timezone
import hashlib
from http.cookiejar import CookieJar
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

try:
    from . import kgrowth_listing, lp_kgrowth_history_replay as replay
    from .lp_kgrowth_history_attachment_queue import file_labels, label_kind
except ImportError:
    import kgrowth_listing
    import lp_kgrowth_history_replay as replay
    from lp_kgrowth_history_attachment_queue import file_labels, label_kind


DETAIL_LIMIT = 2_000_000
PDF_LIMIT = 8_000_000


def listed_recruitment(bundle, selection):
    if not isinstance(selection, dict) or set(selection) != {'fund', 'date', 'round'}:
        raise ValueError('기업투자 모집의 펀드·게시일·회차 필요')
    fund, round_number = selection['fund'], selection['round']
    if not isinstance(fund, str) or not re.fullmatch(r'[가-힣A-Za-z0-9 ]{3,40}', fund.strip()):
        raise ValueError('기업투자 모집 펀드명 미확인')
    if type(round_number) is not int or not 1 <= round_number <= 9:
        raise ValueError('기업투자 모집 회차 미확인')
    posted = date.fromisoformat(selection['date'])
    if (posted.isoformat() != selection['date'] or bundle.get('institution_id') != 'kgrowth'
            or bundle.get('kind') != 'lp_institution_history_v1'):
        raise ValueError('성장금융 보존 목록과 모집 게시일 필요')
    pattern = r'(?:【선정공고】|〖선정공고〗)「' + re.escape(''.join(fund.split())) + r'」'
    pattern += rf'{posted.year}년{round_number}차\(기업투자(?:,인프라)?\)위탁운용사선정계획공고'
    matches = {}
    for digest, listing in bundle['listing_receipts'].items():
        if not re.fullmatch(re.escape(kgrowth_listing.LIST_URL) + r'(?:&page=[1-9][0-9]*)?', listing['url']):
            raise ValueError('성장금융 보존 목록 주소 불일치')
        if hashlib.sha256(listing['html'].encode()).hexdigest() != digest:
            raise ValueError('성장금융 보존 목록 지문 불일치')
        for row in kgrowth_listing.parse_listing(listing['html'], listing['url']):
            if row['date'] == posted.isoformat() and re.fullmatch(pattern, ''.join(row['title'].split())):
                if not row['pinned']:
                    matches[(row['source_id'], row['title'], row['date'])] = (row, listing['url'], digest)
    if len(matches) != 1:
        raise ValueError('원목록에 일치하는 기업투자 모집 한 건이 필요')
    return next(iter(matches.values()))


def public_session():
    opener = build_opener(HTTPCookieProcessor(CookieJar()), replay._NoRedirect())

    def fetch(url, referer, limit):
        request = Request(url, headers={'Accept-Encoding': 'identity', 'Referer': referer,
                                        'User-Agent': 'Mozilla/5.0 (LP source verification)'})
        try:
            response = opener.open(request, timeout=25)
        except HTTPError as error:
            response = error
        with response:
            return response.code, response.geturl(), response.read(limit + 1)

    return fetch


def capture(bundle, selection, retain, acquire=None):
    row, listing_url, digest = listed_recruitment(bundle, selection)
    acquire = acquire or public_session()
    report = {'kind': 'lp_kgrowth_enterprise_recruitment_capture_v1', 'row': row,
              'listing_url': listing_url, 'listing_sha256': digest, 'responses': [], 'holds': [],
              'database_writes': 0, 'published': False}

    def request(url, referer, limit):
        checked_at = datetime.now(timezone.utc).isoformat()
        status, final_url, raw = acquire(url, referer, limit)
        observed = raw[:limit]
        item = {'url': url, 'referer': referer, 'final_url': final_url, 'http_status': status,
                'checked_at': checked_at, 'bytes': len(observed), 'truncated': len(raw) > limit,
                'sha256': hashlib.sha256(observed).hexdigest(), 'raw_base64': base64.b64encode(observed).decode()}
        report['responses'].append(item)
        retain(report)
        if status != 200 or final_url != url or not raw or item['truncated']:
            raise ValueError('기업투자 원응답의 상태·주소·크기 불일치')
        return raw, item

    retain(report)
    try:
        raw, detail = request(row['url'], listing_url, DETAIL_LIMIT)
        document = replay.read_body(row['source_id'], raw, 'kgrowth')
        if (document['date'], document['title']) != (row['date'], row['title']):
            raise ValueError('모집 목록과 상세 게시일·제목 불일치')
        labels = file_labels({**document, 'discovery_provenance': {'detail_response_base64': detail['raw_base64'],
                                                                  'detail_response_sha256': detail['sha256']}})
        files = [(url, name) for url, name in labels.items() if '(기업투자)' in ''.join(name.split())
                 and name.lower().endswith('.pdf') and label_kind(name, '모집 공고') == 'recruitment_announcement']
        if len(files) != 1:
            raise ValueError('기업투자 모집 PDF 한 건을 원문 상세에서 식별하지 못함')
        url, name = files[0]
        pdf, _ = request(url, row['url'], PDF_LIMIT)
        if not re.match(rb'%PDF-[12]\.\d[\r\n]', pdf) or not pdf.rstrip().endswith(b'%%EOF'):
            raise ValueError('기업투자 모집의 PDF 경계 미확인')
        report['attachment_name'] = name
    except (OSError, ValueError) as error:
        report['holds'].append(f'{type(error).__name__}: {str(error)[:240]}')
    retain(report)
    return report


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.bundle.stat().st_size > replay.MAX_INPUT_BYTES or args.request.stat().st_size > 4000:
        parser.error('기업투자 원문 요청 크기 상한 초과')
    bundle = json.loads(args.bundle.read_bytes())
    selection = json.loads(args.request.read_bytes())['recruitment']
    args.out.open('x').close()
    report = capture(bundle, selection, lambda value: args.out.write_text(json.dumps(value, ensure_ascii=False)))
    print(json.dumps({'responses': len(report['responses']), 'holds': report['holds']}, ensure_ascii=False))
    return bool(report['holds'])


if __name__ == '__main__':
    raise SystemExit(main())
