"""Offline file queue from retained KGrowth listing/body bytes; no PE approval."""
import argparse
import base64
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit

try:
    from .collect_lp_history_bodies import validate_report, read_body
    from .lp_history_sources import institution, listing_digest
    from .lp_notice_triage import notice_stage
except ImportError:
    from collect_lp_history_bodies import validate_report, read_body
    from lp_history_sources import institution, listing_digest
    from lp_notice_triage import notice_stage

IDENTITY = ('institution_id', 'source_id', 'source_url', 'body_sha256',
            'detail_response_sha256', 'attachment_url', 'attachment_name', 'stage')


def validate_url(url, source_id):
    if not isinstance(url, str) or re.search(r'[\s\\\x00-\x1f\x7f]', url):
        raise ValueError('Invalid historical file URL')
    p = urlsplit(url)
    if (p.scheme != 'https' or p.netloc != 'www.kgrowth.or.kr' or p.path != '/down_file.asp'
            or p.fragment or '#' in url or re.search(r'%(?![0-9a-fA-F]{2})', p.query)):
        raise ValueError('Invalid historical file origin/path')
    pairs = parse_qsl(p.query, keep_blank_values=True, strict_parsing=True)
    query = dict(pairs)
    if (len(pairs) != 2 or set(query) != {'idx', 'SelType'} or query['idx'] != source_id
            or not re.fullmatch(r'[1-9][0-9]*', source_id)
            or not re.fullmatch(r'Notice[1-9][0-9]*', query['SelType'])):
        raise ValueError('Invalid historical file query/source identity')
    return url


class FileLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.active = None
        self.links = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'ul' and (self.depth or 'file_list' in attrs.get('class', '').split()):
            self.depth += 1
        if tag == 'a' and self.depth:
            if self.active is not None:
                raise ValueError('Nested historical file links')
            self.active = {'href': attrs.get('href', ''), 'text': ''}
    def handle_data(self, value):
        if self.active is not None:
            self.active['text'] += value
    def handle_endtag(self, tag):
        if tag == 'a' and self.active is not None:
            self.links.append(self.active)
            self.active = None
        if tag == 'ul' and self.depth:
            self.depth -= 1


def file_labels(notice):
    proof = notice['discovery_provenance']
    raw = base64.b64decode(proof['detail_response_base64'], validate=True)
    if len(raw) > 12*1024*1024 or hashlib.sha256(raw).hexdigest() != proof['detail_response_sha256']:
        raise ValueError('Historical body bytes changed')
    original = read_body(notice['source_id'], raw, 'kgrowth')
    if any(notice.get(key) != value for key, value in original.items()):
        raise ValueError('Historical body differs from retained bytes')
    parser = FileLinks(); parser.feed(raw.decode('cp949'))
    if parser.active is not None or parser.depth:
        raise ValueError('Incomplete historical file list')
    linked = {}
    for link in parser.links:
        url = urljoin(notice['url'], link['href'])
        if '/down_file.asp' not in url:
            raise ValueError('Unsupported original file-list link; adapter review required')
        validate_url(url, notice['source_id'])
        label = ' '.join(link['text'].split())
        if not label or (url in linked and linked[url] != label):
            raise ValueError('Missing or conflicting original file label')
        linked[url] = label
    if set(linked) != set(notice['attachments']) or len(set(notice['attachments'])) != len(notice['attachments']):
        raise ValueError('Original file list differs from parsed attachment URLs')
    return linked


def label_kind(label, stage):
    # References and templates stay distinct, including reference spreadsheets.
    if re.search(r'공고(?:문)?.*?(?:및|[·ㆍ+]).*?(?:서식|양식|제안서|제출서류|주목적\s*투자|공동기준|투자\s*가이드라인)', label):
        return 'unconfirmed'  # A combined offering/template/reference is ambiguous.
    if re.search(r'주목적\s*투자분야|투자\s*가이드라인|공동기준|미래유망산업\s*품목', label):
        return 'investment_reference'
    if re.search(r'제출\s*서류.*(?:서식|양식)|(?:서식|양식).*제출\s*서류|제안서\s*(?:양식|서식)|동의서', label):
        return 'submission_template'
    if re.search(r'FAQ|질의\s*응답', label, re.I):
        return 'faq'
    if not re.search(r'\.(?:pdf|hwp|hwpx|docx)$', label, re.I):
        return 'unconfirmed'
    if stage in {'선정 결과', '접수 결과', '1차 심사 결과'} and re.search(r'선정.*결과|서류.*결과|지원\s*현황|접수\s*현황', label):
        return 'stage_result'
    if stage in {'모집 공고', '변경 공고'} and re.search(r'선정\s*계획.*공고|공고문', label):
        return 'recruitment_announcement'
    return 'unconfirmed'


def plan(history, bodies, completed=(), *, limit=4):
    if type(limit) is not int or not 1 <= limit <= 4 or institution(history) != 'kgrowth':
        raise ValueError('Bounded KGrowth historical queue required')
    body_queue = validate_report(history, bodies)
    if history['window']['start'] != '2023-01-01' or bodies['holds']:
        raise ValueError('Fixed-start unblocked body evidence required')
    eligible, excluded, held, dates = {}, [], [], {}
    for n in bodies['documents']:
        stage = notice_stage(n['title']); primary = []
        for url, name in file_labels(n).items():
            kind = label_kind(name, stage)
            row = {'institution_id': 'kgrowth', 'source_id': n['source_id'], 'source_url': n['url'],
                   'body_sha256': n['sha256'], 'detail_response_sha256': n['discovery_provenance']['detail_response_sha256'],
                   'attachment_url': url, 'attachment_name': name, 'stage': stage}
            if kind in {'recruitment_announcement', 'stage_result'}:
                primary.append(row)
            elif kind == 'unconfirmed':
                held.append({**row, 'reason': 'unclassified_original_label'})
            else:
                excluded.append({**row, 'reason': kind})
        if len(primary) == 1:
            eligible[n['source_id']] = primary[0]; dates[n['source_id']] = n['date']
        elif len(primary) > 1:
            held.append({'source_url': n['url'], 'source_id': n['source_id'],
                         'reason': 'multiple_primary_files', 'candidate_count': len(primary)})
    done = set()
    ordered = sorted(eligible, key=lambda ident: (dates[ident], int(ident)))
    for record in completed:
        ident = record.get('source_id') if isinstance(record, dict) else None
        expected = ordered[len(done)] if len(done) < len(ordered) else None
        if (ident not in eligible or ident != expected or any(record.get(k) != eligible[ident][k] for k in IDENTITY)
                or not re.fullmatch('[a-f0-9]{64}', record.get('attachment_sha256', ''))):
            raise ValueError('Completed file does not follow the source-discovered queue')
        done.add(ident)
    pending = [ident for ident in ordered if ident not in done]
    return {'kind': 'kgrowth_history_attachment_plan_v1', 'institution_id': 'kgrowth',
            'window': history['window'], 'listing_digest': listing_digest(history),
            'validated_body_documents': len(bodies['documents']), 'body_pending': body_queue['pending_count'],
            'eligible_files': len(eligible), 'completed_files': len(done), 'pending_files': len(pending),
            'rows': [eligible[ident] for ident in pending[:limit]], 'excluded': excluded, 'holds': held,
            'source_history_complete': False, 'pe_approval': False, 'selected_gp_approval': False,
            'official_http_requests': 0, 'downloaded_files': 0, 'database_writes': 0,
            'published': False, 'raw_file_validation': 'not_started'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('listing-state', 'body-state', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    args = p.parse_args()
    def load(path):
        if path.stat().st_size > 32*1024*1024:
            raise ValueError('Historical source artifact exceeds size limit')
        return json.loads(path.read_text())
    result = plan(load(args.listing_state), load(args.body_state))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False))
    print(json.dumps({k: result[k] for k in ('validated_body_documents', 'body_pending', 'eligible_files', 'pending_files')}))


if __name__ == '__main__':
    main()
