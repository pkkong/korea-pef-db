"""Replay exact Korea Post domestic coinvestment preferred-bidder evidence.

This is a separate single-manager, pre-final format. It does not change the
ordinary blind-PEF league extractor, approve a final result, or infer amounts.
"""
import base64
import hashlib
import re
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

try:
    from .lp_attachment_text import extract_attachment, MAX_FILE_BYTES
except ImportError:
    from lp_attachment_text import extract_attachment, MAX_FILE_BYTES

MAX_DETAIL_BYTES = 12 * 1024 * 1024
DETAIL_KIND = 'koreapost_detail_body_v1'
FILE_KIND = 'koreapost_attachment_body_v1'
BASE = 'https://www.kpasset.go.kr'


def _collector():
    try:
        from . import collect_koreapost_program
    except ImportError:
        import collect_koreapost_program
    return collect_koreapost_program


def _compact(value):
    return re.sub(r'\s+', '', value)


def _safe_url(url):
    if (not isinstance(url, str) or len(url) > 8192 or re.search(r'[\s\\\x00-\x1f\x7f]', url)
            or re.search(r'%(?![0-9a-fA-F]{2})', url)):
        raise ValueError('Invalid Korea Post proof URL')
    p = urlsplit(url)
    if p.scheme != 'https' or p.netloc != 'www.kpasset.go.kr' or p.fragment or '#' in url:
        raise ValueError('Unexpected Korea Post proof origin')
    return p


def _protected(notice):
    flags = ('restricted', 'closed', 'owner_closed', 'hidden', 'protected')
    provenance = notice.get('discovery_provenance', {})
    body = notice.get('body')
    if not isinstance(provenance, dict) or not isinstance(body, str):
        return True
    return (any(str(notice.get(k, '')).strip().lower() in ('true', '1')
                or str(provenance.get(k, '')).strip().lower() in ('true', '1') for k in flags)
            or str(notice.get('status', '')).strip().lower() in (*flags, 'private', 'error', 'failed')
            or bool(notice.get('error')) or bool(notice.get('attachment_errors'))
            or bool(notice.get('attachment_read_error'))
            or bool(re.search(r'비정상적인접근|로그인이필요|접근권한이없|열람권한이없|접근이제한|비공개게시물', _compact(body))))


def _raw(proof, kind, limit, extra=()):
    required = {'kind', 'raw_base64', 'sha256', 'byte_length', *extra}
    if (not isinstance(proof, dict) or set(proof) != required or proof.get('kind') != kind
            or not isinstance(proof.get('raw_base64'), str)
            or len(proof['raw_base64']) > ((limit + 2) // 3) * 4):
        raise ValueError('Missing/invalid Korea Post raw proof or size limit exceeded')
    try:
        raw = base64.b64decode(proof['raw_base64'], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('Korea Post raw encoding invalid') from error
    if (not raw or len(raw) > limit or type(proof['byte_length']) is not int
            or len(raw) != proof['byte_length'] or hashlib.sha256(raw).hexdigest() != proof['sha256']
            or base64.b64encode(raw).decode('ascii') != proof['raw_base64']):
        raise ValueError('Korea Post raw size/hash mismatch')
    return raw


def validate_detail_proof(notice):
    if not isinstance(notice, dict) or _protected(notice):
        raise ValueError('Protected or invalid Korea Post source')
    source_id = notice.get('source_id', '')
    match = re.fullmatch(r'0041:([1-9][0-9]*)', source_id) if isinstance(source_id, str) else None
    expected = f'{BASE}/board.es?mid=a10510000000&bid=0041&act=view&list_no={match[1]}' if match else None
    if (not match or notice.get('url') != expected
            or notice.get('institution_id', 'koreapost') != 'koreapost'):
        raise ValueError('Korea Post detail source identity differs')
    _safe_url(notice['url'])
    raw = _raw(notice.get('detail_proof'), DETAIL_KIND, MAX_DETAIL_BYTES)
    parsed = _collector()._detail(match[1], raw)
    if any(notice.get(key) != value for key, value in parsed.items()):
        raise ValueError('Korea Post detail differs from exact retained HTML')
    datetime.strptime(parsed['date'], '%Y-%m-%d')
    return parsed


def _download_url(url, source_id):
    p = _safe_url(url)
    if p.path != '/download.es':
        raise ValueError('Unexpected Korea Post attachment route')
    pairs = parse_qsl(p.query, keep_blank_values=True, strict_parsing=True)
    if any(re.search(r'[\\\x00-\x1f\x7f]', key + value) for key, value in pairs):
        raise ValueError('Korea Post attachment query contains encoded control characters')
    query = {}
    for key, value in pairs:
        query.setdefault(key, []).append(value)
    keys = {'filename', 'filenameOrg', 'f_path', 'bid', 'type', 'list_no', 'seq'}
    if (set(query) != keys or any(len(values) != 1 for key, values in query.items() if key != 'bid')
            or not 1 <= len(query['bid']) <= 2 or set(query['bid']) != {'0041'}
            or query['f_path'] != ['board'] or query['type'] != ['board']
            or query['list_no'] != [source_id.split(':')[1]]
            or not re.fullmatch(r'[1-9][0-9]*', query['seq'][0])
            or not re.fullmatch(r'[1-9][0-9]*\.pdf', query['filename'][0], re.I)
            or not query['filenameOrg'][0].lower().endswith('.pdf')):
        raise ValueError('Korea Post attachment source/query differs')
    return url


def validate_attachment_proof(notice):
    attachments = notice.get('attachments')
    if not isinstance(attachments, list) or not attachments:
        raise ValueError('Korea Post first recruitment PDF missing')
    url = _download_url(attachments[0], notice['source_id'])
    proofs = notice.get('attachment_proofs')
    if not isinstance(proofs, dict) or set(proofs) != {url}:
        raise ValueError('Korea Post first attachment raw proof missing/ambiguous')
    proof = proofs[url]
    raw = _raw(proof, FILE_KIND, MAX_FILE_BYTES, ('pdf_reader_version', 'extracted'))
    if (not raw.startswith(b'%PDF') or proof['pdf_reader_version'] != '6.10.0'
            or not isinstance(notice.get('attachment_hashes'), dict)
            or notice['attachment_hashes'].get(url) != proof['sha256']):
        raise ValueError('Korea Post PDF source/hash/reader differs')
    import pypdf
    if pypdf.__version__ != '6.10.0':
        raise ValueError('Korea Post PDF replay requires pypdf 6.10.0')
    extracted = extract_attachment(raw)
    if extracted['format'] != 'pdf' or extracted != proof['extracted']:
        raise ValueError('Korea Post PDF canonical body differs from raw replay')
    return extracted


def extract_preferred(recruitment, preferred, *, checked_at):
    """Return the existing roster shape after complete offline source replay."""
    validate_detail_proof(recruitment); validate_detail_proof(preferred)
    stamp = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Korea Post preferred checked_at requires timezone')
    today = stamp.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
    if (not recruitment['date'] < preferred['date'] <= today
            or recruitment['date'][:4] != preferred['date'][:4]):
        raise ValueError('Korea Post preferred date/year is outside recruitment sequence')
    title = _compact(recruitment['title'])
    match = re.fullmatch(r'(20[0-9]{2})년도?((?:우체국예금|우체국금융|우정사업본부)국내공동투자전략펀드)'
                         r'위탁운용사선정공고(?:\(우정사업본부공고(?:제)?20[0-9]{2}-[0-9]+호\))?', title)
    if not match or match[1] != recruitment['date'][:4]:
        raise ValueError('Unsupported Korea Post coinvestment recruitment identity/year')
    year, family = match.groups()
    years = re.findall(r'20[0-9]{2}', recruitment['title'] + recruitment['body'] + preferred['title'] + preferred['body'])
    if set(years) != {year}:
        raise ValueError('Korea Post source years conflict')
    if (_compact(preferred['title']) != family + '위탁운용사선정우선협상대상자선정안내'
            or family not in _compact(recruitment['body']) or family not in _compact(preferred['body'])):
        raise ValueError('Korea Post preferred business/stage identity differs')
    forbidden = r'정정|수정|변경|취소|재공고|해외|외국|VC|벤처|조건부|예비대상|최종선정(?:완료|확정|결과)|비공개|로그인이필요|접근권한이없'
    if re.search(forbidden, _compact(preferred['title'] + preferred['body']), re.I):
        raise ValueError('Changed/protected/final/foreign preferred notice is unsupported')
    if any(preferred.get(k) for k in ('attachments', 'attachment_hashes', 'attachment_texts', 'attachment_proofs')):
        raise ValueError('Preferred roster must be the complete attachment-free body')
    pdf = _compact(validate_attachment_proof(recruitment)['text'])
    heading = re.search(r'(20[0-9]{2})년도?((?:우체국예금|우체국금융|우정사업본부)국내공동투자전략펀드)위탁운용사선정공고', pdf[:1000])
    counts = re.findall(r'선정운용사(?:수)?[)\-:：]*총([0-9]+)개운용사', pdf)
    if (not heading or heading.groups() != (year, family) or '블라인드형' not in pdf
            or '우정사업본부가제공하는국내공동투자건' not in pdf or '펀드약정액의100%' not in pdf
            or '기관전용사모집합투자기구' not in pdf
            or not re.search(r'창업[·ㆍ]?벤처전문사모집합투자기구제외', pdf)
            or not re.search(r'공동운용사\(co-gp\)제안금지', pdf, re.I)
            or not counts or set(counts) != {'1'}):
        raise ValueError('Korea Post PDF does not prove the same single domestic blind PE offering')
    body = _compact(preferred['body'])
    if not re.search(r'운용사실사및투자심의회를거쳐최종선정예정', body):
        raise ValueError('Korea Post preferred result lacks explicit pending final approval')
    lines = [line.strip() for line in preferred['body'].splitlines() if line.strip()]
    rows = [re.fullmatch(r'[-•ㅇ]?\s*선정\s*운용사\s*[:：]\s*(.+?)\s*', line) for line in lines]
    names = [m[1].strip() for m in rows if m]
    if (len(names) != 1 or not re.fullmatch(r'[가-힣A-Za-z][가-힣A-Za-z0-9 .·()]{0,79}', names[0])
            or re.search(r'및|외\s*[0-9]|공동|co.?gp', names[0], re.I)
            or sum('선정운용사' in _compact(line) for line in lines) != 1):
        raise ValueError('Korea Post single preferred manager row is ambiguous')
    intro = family + '위탁운용사우선협상대상자선정결과를다음과같이안내드립니다'
    pending = '운용사실사및투자심의회를거쳐최종선정예정'
    thanks = '지원해주신운용사및모든관계자분들께깊이감사드립니다'
    prose = []
    for line, row in zip(lines, rows):
        if row:
            continue
        value = _compact(re.sub(r'^[-•ㅇ]\s*', '', line)).rstrip('.')
        if value not in (intro, pending, thanks):
            raise ValueError('Korea Post preferred body has unparsed rows')
        prose.append(value)
    if prose.count(intro) != 1 or prose.count(pending) != 1 or prose.count(thanks) > 1:
        raise ValueError('Korea Post preferred body phase is ambiguous')
    source = preferred['url']
    return {'event': {'type': '우선협상대상자', 'date': preferred['date'], 'title': preferred['title'], 'url': source},
            'rosters': [{'league': '국내 공동투자 전략', 'names': names, 'source_url': source, 'source_sha256': preferred['sha256']}],
            'preferred_gps': names, 'source_url': source}
