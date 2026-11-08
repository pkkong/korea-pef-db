"""Read single-track KTCU offering terms from retained historical file bytes."""
import base64
from datetime import date, datetime
import hashlib
import re

try:
    from .collect_lp_history_bodies import read_body
    from .collect_lp_history_attachments import read_attachment
    from .collect_shared_lp_notices import classify_scope
    from .lp_history_sources import canonical_url
    from .lp_history_attachment_queue import validate_url
    from .lp_notice_triage import compact, notice_stage
except ImportError:
    from collect_lp_history_bodies import read_body
    from collect_lp_history_attachments import read_attachment
    from collect_shared_lp_notices import classify_scope
    from lp_history_sources import canonical_url
    from lp_history_attachment_queue import validate_url
    from lp_notice_triage import compact, notice_stage


def _one(values, field):
    values = set(values)
    if len(values) != 1:
        raise ValueError('KTCU '+field+' missing or conflicting')
    return next(iter(values))


def verified_text(notice):
    proof = notice.get('discovery_provenance', {})
    if (notice.get('institution_id') != 'ktcu' or proof.get('kind') != 'lp_history_attachment'
            or notice['url'] != canonical_url(notice['source_id'], 'ktcu')):
        raise ValueError('Typed KTCU historical offering proof required')
    raw = base64.b64decode(proof['detail_response_base64'], validate=True)
    if len(raw) > 12*1024*1024 or hashlib.sha256(raw).hexdigest() != proof['detail_response_sha256']:
        raise ValueError('KTCU historical detail response changed')
    parsed = read_body(notice['source_id'], raw, 'ktcu')
    if any(parsed[k] != notice.get(k) for k in parsed):
        raise ValueError('KTCU notice differs from original detail bytes')
    record = proof['attachment_evidence']
    if (record['institution_id'] != 'ktcu' or record['source_id'] != notice['source_id']
            or record['source_url'] != notice['url'] or record['body_sha256'] != notice['sha256']):
        raise ValueError('KTCU file and original notice identity differ')
    url = record['attachment_url']; validate_url(url)
    if not any(a['url'] == url and a['name'] == record['attachment_name'] for a in parsed['attachments']):
        raise ValueError('KTCU announcement file was not linked by the original')
    raw_file = base64.b64decode(record['raw_base64'], validate=True)
    if len(raw_file) > 12*1024*1024 or hashlib.sha256(raw_file).hexdigest() != record['attachment_sha256']:
        raise ValueError('KTCU announcement bytes changed')
    extracted = read_attachment(raw_file)
    if (extracted != record['extracted'] or notice.get('attachment_hashes') != {url: record['attachment_sha256']}
            or notice.get('attachment_texts') != {url: extracted['text']}):
        raise ValueError('KTCU announcement text differs from retained bytes')
    return extracted['text'], url, record['attachment_sha256']


def parse_offering(notice, raw, source_url, digest):
    """A labeled single-track table; relative dates require a matched year anchor."""
    if notice_stage(notice['title']) != '모집 공고' or classify_scope(notice['title'], raw) != 'pe_blind':
        raise ValueError('Verified domestic PE blind recruitment required')
    text = compact(raw)
    cover = re.match(r'(20\d{2})년한국교직원공제회블라인드pef위탁운용사선정공고문', text)
    if not cover or notice['date'][:4] != cover[1] or cover[1] not in notice['title']:
        raise ValueError('KTCU offering year anchor missing or conflicting')
    year = int(cover[1]); evidence = {}
    def remember(field, quote):
        evidence[field] = [{'source_url': source_url, 'sha256': digest, 'quote': quote}]
    def match(pattern, field, section=text):
        found = list(re.finditer(pattern, section))
        value = _one([m.groups() for m in found], field)
        remember(field, found[0][0])
        return value
    amount, amount_limit = match(r'본회출자규모[•▪·:：-]*총(\d+(?:,\d{3})*)억원(이내)?', 'amount')
    count, count_limit = match(r'선정운용사수[•▪·:：-]*총(\d+)개사(이내)?', 'manager_count')
    amount, count = int(amount.replace(',', ''))*100_000_000, int(count)
    match(r'(펀드규모의\d+(?:\.\d+)?%이상을국내소재기업에투자)', 'purpose')
    timeline, = match(r'선정일정(.*?)※상기일정', 'timeline')
    announcement = match(r'(\d{1,2})월(\d{1,2})일블라인드pef위탁운용사선정공고', 'announcement', timeline)
    if date(year, *map(int, announcement)).isoformat() != notice['date']:
        raise ValueError('KTCU table announcement does not match original date')
    closing = match(r'(\d{1,2})월(\d{1,2})일제안서접수마감', 'deadline_day', timeline)
    month, day, hour = match(r'접수마감[:：](\d{1,2})월(\d{1,2})일(\d{1,2})시까지제출', 'deadline_time')
    if closing != (month, day):
        raise ValueError('KTCU closing dates conflict')
    deadline = datetime(year, int(month), int(day), int(hour)).isoformat()+'+09:00'
    if deadline[:10] < notice['date'] or amount <= 0 or count <= 0:
        raise ValueError('KTCU offering values outside supported bounds')
    planned = []
    patterns = [
        (r'(\d{1,2})월(초|중|말)~(\d{1,2})월(초|중|말)1차심사및2차심사대상선정', 'screening', '1차 심사'),
        (r'(\d{1,2})월(초|중|말)현장실사및2차심사', 'screening', '2차 심사'),
        (r'(\d{1,2})월(초|중|말)위탁운용사최종선정', 'selection', '최종 선정'),
    ]
    previous_point = (int(month), 0)
    period_rank = {'초': 0, '중': 1, '말': 2}
    for pattern, stage, label in patterns:
        values = match(pattern, label, timeline)
        start_month, period = int(values[0]), values[1]
        end_month = int(values[2]) if len(values) == 4 else start_month
        end_period = values[3] if len(values) == 4 else period
        start_point, end_point = (start_month, period_rank[period]), (end_month, period_rank[end_period])
        if not (1 <= start_month <= end_month <= 12 and previous_point <= start_point <= end_point):
            raise ValueError('KTCU planned month sequence is ambiguous')
        previous_point = end_point
        date_label = f'{year}년 {start_month}월 {period}'
        if len(values) == 4: date_label += f' ~ {end_month}월 {values[3]}'
        planned.append({'stage': stage, 'label': label, 'original_label': label,
            'date': f'{year}-{start_month:02d}', 'date_label': date_label, 'precision': 'period',
            'status': 'planned', 'source_url': notice['url']})
    purpose = re.sub(r'\s+', ' ', _one(re.findall(
        r'펀드\s*규모의\s*\d+(?:\.\d+)?%\s*이상을\s*국내\s*소재\s*기업에\s*투자', raw), 'purpose quote')).strip()
    return {'commitment_amount_krw': amount,
        'commitment_label': f'{amount/100_000_000:,.0f}억원'+(' 이내' if amount_limit else ''),
        'manager_count': count, 'manager_count_label': f'{count}개사'+(' 이내' if count_limit else ''),
        'deadline': deadline, 'deadline_precision': 'datetime',
        'primary_investment': {'text': purpose, 'source_url': source_url},
        'planned_schedule': planned, 'extraction_evidence': evidence}


def extract_offering(notice):
    text, url, digest = verified_text(notice)
    return parse_offering(notice, text, url, digest)
