#!/usr/bin/env python3
"""Discover institution-authored LP notices on public association boards.

This collector emits evidence/candidates, never program terms or GP selections.
Failures are holds; consumers must upsert successful notices, not replace archives.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from http.client import IncompleteRead
from functools import partial
import subprocess
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[3]
CHANNELS = {
    'kvca': 'https://www.kvca.or.kr/Program/invest/list.html?a_cd=8&a_gb=board&a_item=0&sm=2_2_2',
    'kofia_212': 'https://www.kofia.or.kr/brd/m_212/list.do',
    'kofia_17': 'https://www.kofia.or.kr/brd/m_17/list.do',
}
MAX_BYTES = 12 * 1024 * 1024

class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
    def nodes(self, tag=None):
        for c in self.children:
            if isinstance(c, Node):
                if tag is None or c.tag == tag:
                    yield c
                yield from c.nodes(tag)
    def text(self):
        if self.tag in {'script', 'style'}:
            return ''
        value = ''.join(c.text() if isinstance(c, Node) else c for c in self.children)
        return (' ' + value + ' ') if self.tag in {'p','div','br','td','th','tr','li'} else value
    def clean(self):
        return re.sub(r'\s+', ' ', self.text()).strip()

class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs)
        self.stack[-1].children.append(n)
        if tag not in {'br','img','hr','meta','link','input','source','wbr','area','base','embed'}:
            self.stack.append(n)
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break
    def handle_data(self, text):
        self.stack[-1].children.append(text)


def valid_date(value):
    m = re.search(r'(?<!\d)(20\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})(?!\d)', value)
    if m:
        try:
            return date(*map(int,m.groups())).isoformat()
        except ValueError:
            pass
    return None


def source_id(url, channel):
    q = parse_qs(urlsplit(url).query)
    ident = q.get('po_no' if channel == 'kvca' else 'seq', [''])[0]
    if not ident.isdigit():
        raise ValueError('missing notice identifier')
    return f'{channel}:{ident}'


def parse_listing(html, url, channel):
    root = Document(html).root
    notices, seen = [], set()
    for row in root.nodes('tr'):
        cells = [n for n in row.children if isinstance(n,Node) and n.tag in {'td','th'}]
        anchors = [a for a in row.nodes('a') if ('listbody.html' if channel == 'kvca' else 'view.do?') in a.attrs.get('href','')]
        if not anchors or not cells:
            continue
        href = urljoin(url,anchors[0].attrs['href'])
        require_same_host(href, url)
        sid = source_id(href,channel)
        if sid in seen:
            continue
        seen.add(sid)
        if channel == 'kvca' and len(cells) >= 4:
            title, issuer, published = cells[2].clean(), cells[1].clean(), valid_date(cells[3].clean())
        else:
            title_cell = next((c for c in cells if anchors[0] in list(c.nodes('a'))), None)
            title, issuer = (title_cell.clean() if title_cell else anchors[0].clean()), None
            published = next((valid_date(c.clean()) for c in cells if valid_date(c.clean())),None)
        notices.append(dict(source_id=sid,url=href,title=title,date=published,issuer_name=issuer))
    pages = {}
    here = urlsplit(url)
    for a in root.nodes('a'):
        href = urljoin(url,a.attrs.get('href',''))
        parsed = urlsplit(href)
        if parsed.netloc != here.netloc or parsed.path != here.path:
            continue
        p = parse_qs(parsed.query).get('page',[''])[0]
        if p.isdigit():
            pages[int(p)] = href
    return notices, pages


def parse_detail(html, url, channel):
    root = Document(html).root
    table = next((t for t in root.nodes('table') if any(n.clean() == ('공고명' if channel == 'kvca' else '제목') for n in t.nodes('th'))),None)
    if table is None:
        raise ValueError('notice content table not found')
    fields, attachments = {}, []
    for row in table.nodes('tr'):
        cells = [n for n in row.children if isinstance(n,Node) and n.tag in {'td','th'}]
        for i,c in enumerate(cells[:-1]):
            if c.tag == 'th' and cells[i+1].tag == 'td':
                fields[c.clean()] = cells[i+1].clean()
        for a in row.nodes('a'):
            href = a.attrs.get('href','')
            if 'download' in href.lower() or 'down.do' in href.lower():
                attachment_url = urljoin(url,href)
                require_same_host(attachment_url, url)
                attachments.append(dict(name=a.clean(),url=attachment_url))
    body = fields.get('공고 내용','') if channel == 'kvca' else next((n.clean() for n in table.nodes() if n.attrs.get('id')=='write'),'')
    if not body:
        raise ValueError('notice body missing')
    links = [dict(url=urljoin(url,a.attrs['href']),label=a.clean()) for a in table.nodes('a') if a.attrs.get('href','').startswith(('http://','https://')) and urlsplit(a.attrs['href']).netloc != urlsplit(url).netloc]
    published=valid_date(fields.get('공고일') or fields.get('작성일',''))
    deadline=valid_date(fields.get('신청기한',''))
    registered=valid_date(fields.get('등록일',''))
    conflict=bool(published and deadline and published>deadline)
    return dict(title=fields.get('공고명') or fields.get('제목'),date=registered if conflict else published,
                issuer_name=fields.get('LP명'),body=body,attachments=attachments,original_links=links,
                claimed_official_date=published,application_deadline=deadline,association_registered_at=registered,
                date_conflict=conflict,date_basis='association_registered_at' if conflict else 'association_claimed_publication')


def load_aliases(root=ROOT):
    scope = json.loads((root/'data/lp_blind_contest_scope.json').read_text())
    targets = set(scope['confirmed_institution_ids'] + scope['priority_verification_ids'])
    aliases = {i:set() for i in targets}
    for path in sorted((root/'data').glob('lp_blind_contest_screening_*.json')):
        for row in json.loads(path.read_text()).get('institutions',[]):
            if row['institution_id'] in targets:
                aliases[row['institution_id']].add(row['name'])
    with (root/'data/lp_institutions.csv').open() as f:
        for row in csv.DictReader(f):
            if row['lp_code'] in targets:
                aliases[row['lp_code']].update([row['lp_name'],*row.get('aliases','').split(';')])
    for i, names in {'koreapost':['우체국보험','우체국예금','우체국금융'],'moel_iaci':['산재보험기금'],'moel_eif':['고용보험기금'],'nh_central':['농협중앙회'],'kfinco':['전문건설공제조합']}.items():
        if i in aliases:
            aliases[i].update(names)
    # Short roman abbreviations and generic aliases create false issuer matches.
    return {i:sorted((s for s in names if len(s)>=3 and re.search('[가-힣]',s)),key=len,reverse=True) for i,names in aliases.items()}


def match_issuer(title, issuer, body, aliases):
    # Fund identity takes precedence over the delegated OCIO named in an LP cell.
    for label,i in [('산재보험기금','moel_iaci'),('고용보험기금','moel_eif')]:
        if label in title or (label in body and issuer and ('삼성' in issuer or '미래에셋' in issuer)):
            return i,'fund_explicit'
    for value,confidence in [(issuer or '', 'issuer_field'),(title,'title_explicit')]:
        hits = {i for i,names in aliases.items() if any(n in value for n in names)}
        if len(hits)==1:
            return next(iter(hits)),confidence
        if len(hits)>1:
            return None,'ambiguous'
    return None,'unmatched'


def classify_scope(title,body):
    pe_pattern = r'(?<![A-Za-z])PEF?(?![A-Za-z])|기관전용\s*사모집합투자기구|경영참여형\s*사모'
    vc_pattern = r'(?<![A-Za-z])VC(?![A-Za-z])|벤처투자조합|신기술사업투자조합'
    if re.search(r'채용|전문위원|국내주식|인덱스|해외채권|해외주식|해외부동산|해외 부동산|OCIO',title,re.I):
        return 'outside'
    if re.search(r'해외|글로벌',title) and not re.search(r'국내|중소|중견|수출',title):
        return 'outside'
    title_pe = bool(re.search(pe_pattern,title,re.I))
    title_blind = bool(re.search(r'블라인드|blind',title,re.I))
    # Prior-fund eligibility/AUM is not evidence about the offered fund.
    offer_windows = []
    for m in re.finditer(r'운용방식|선정유형|선정대상|투자기구|펀드유형|투자부문|투자유형|블라인드', body):
        window = body[max(0,m.start()-60):m.end()+180]
        if not re.search(r'선행|기존|직전|과거|최근|경험|경력|이력|보유|운용중|소진율|AUM|트랙레코드',window,re.I):
            offer_windows.append(window)
    offered = ' '.join(offer_windows)
    pe = title_pe or bool(re.search(pe_pattern,offered,re.I))
    blind = title_blind or bool(re.search(r'(?:운용방식|선정유형|선정대상|펀드유형)[\s:：·ㆍ-]{0,15}(?:국내\s*)?블라인드|블라인드\s*(?:PEF?|펀드).{0,35}(?:선정|모집|공고)',offered,re.I))
    domestic = '국내' in title or '국내' in offered
    mixed_fields=[]
    for m in re.finditer(r'PE\s*부문.{0,100}VC\s*부문',body,re.I):
        window=body[max(0,m.start()-40):m.end()+40]
        if not re.search(r'과거|기존|경력|이력|선행',window):
            mixed_fields.append(m[0])
    vc = bool(re.search(vc_pattern,title+' '+offered+' '+' '.join(mixed_fields),re.I))
    if pe and blind and domestic:
        return 'mixed_pe_blind' if vc else 'pe_blind'
    if vc and not pe:
        return 'vc_only'
    return 'needs_confirmation'


def require_same_host(url, source):
    parsed, expected = urlsplit(url), urlsplit(source)
    if parsed.scheme not in {'http','https'} or parsed.hostname != expected.hostname or parsed.username or parsed.password or parsed.port not in {None,80,443}:
        raise ValueError('cross-host or nonpublic source URL rejected')


class SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_same_host(newurl,req.full_url)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def _fetch_bytes_urllib(url, referer=None):
    headers={'User-Agent':'Mozilla/5.0 (LP public notice collector)','Accept-Encoding':'identity','Connection':'close'}
    if referer:
        headers['Referer']=referer
    if urlsplit(url).hostname not in {'www.kvca.or.kr','www.kofia.or.kr'}:
        raise ValueError('source host is not an enabled association channel')
    with build_opener(SameHostRedirect()).open(Request(url,headers=headers),timeout=20) as response:
        # Bounded reads avoid urllib's read-all handling of some HTTP/1.1 servers.
        parts, size = [], 0
        while True:
            part=response.read(min(65536,MAX_BYTES+1-size))
            if not part:
                break
            parts.append(part);size+=len(part)
            if size>MAX_BYTES:
                raise ValueError('response exceeds 12 MiB limit')
        return b''.join(parts)



class IncompleteHTML(ValueError):
    """A successful HTTP transfer did not contain a complete HTML document."""


def _complete_html(raw, kind):
    try:
        html = decode_html(raw)
    except ValueError as exc:
        # A truncated multi-byte character is another incomplete 200 response.
        # Keep strict decoding, but use the same bounded whole-response recovery.
        raise IncompleteHTML(f'undecodable {kind} HTML') from exc
    if '</html>' not in html.lower():
        raise IncompleteHTML(f'incomplete {kind} HTML')
    return html


def _fetch_bytes_once(url, referer=None, *, html_kind=None):
    try:
        raw = _fetch_bytes_urllib(url, referer)
        if html_kind:
            _complete_html(raw, html_kind)
        return raw
    except (IncompleteRead, IncompleteHTML):
        # KOFIA can truncate a 200 response without a transport exception, as
        # well as send invalid chunk framing. Retry the whole document over
        # HTTP/1.0; validate its HTML too, never accept partial rows as complete.
        command=['curl','--fail','--silent','--show-error',
                 '--http1.0','--user-agent','Mozilla/5.0 (LP public notice collector)',
                 '--header','Accept-Encoding: identity','--header','Connection: close',
                 '--max-time','25','--max-filesize',str(MAX_BYTES),
                 '--proto','=https,http','--proto-redir','=https,http']
        if referer:
            command += ['--referer',referer]
        result=subprocess.run(command+[url],capture_output=True,timeout=30,check=True)
        if len(result.stdout)>MAX_BYTES:
            raise ValueError('response exceeds 12 MiB limit')
        if html_kind:
            _complete_html(result.stdout, html_kind)
        return result.stdout


def _transient_fetch_error(error):
    if isinstance(error, HTTPError):
        return error.code in {408, 429, 500, 502, 503, 504}
    if isinstance(error, URLError):
        return _transient_fetch_error(error.reason)
    if isinstance(error, ssl.SSLError):
        return False
    if isinstance(error, subprocess.CalledProcessError):
        # DNS/connect failures, incomplete transfers and timed-out/closed sockets.
        # Certificate errors, HTTP refusals and response-size limits stay fatal.
        return error.returncode in {6, 7, 18, 28, 52, 55, 56}
    return isinstance(error, (TimeoutError, ConnectionError, IncompleteRead, IncompleteHTML,
                              subprocess.TimeoutExpired))


class _FetchRetryBudget:
    def __init__(self):
        self.remaining = 4

    def consume(self):
        if self.remaining == 0:
            return False
        self.remaining -= 1
        return True


def fetch_bytes(url, referer=None, *, retry_budget=None, html_kind=None):
    # Retry the whole read, never merge bytes from an incomplete response.
    # At most three attempts, with short backoff; exhausted failures still hold.
    for attempt in range(3):
        try:
            return _fetch_bytes_once(url, referer, html_kind=html_kind)
        except Exception as error:
            if (attempt == 2 or not _transient_fetch_error(error)
                    or (retry_budget is not None and not retry_budget.consume())):
                raise
            print(f'Retrying association request ({attempt + 2}/3): {url}', file=sys.stderr)
            time.sleep(attempt + 1)


def decode_html(raw):
    for codec in ('utf-8','cp949'):
        try:
            return raw.decode(codec)
        except UnicodeDecodeError:
            pass
    raise ValueError('HTML encoding not recognized')


def _explicit_empty_listing(html, channel):
    # An empty result is healthy only with the board's actual empty-row marker
    # inside a labelled listing table. Error/bot pages and parser misses hold.
    if not channel.startswith('kofia_'):
        return False
    for table in Document(html).root.nodes('table'):
        headings = {n.clean() for n in table.nodes('th')}
        if not {'번호', '제목', '작성일'}.issubset(headings):
            continue
        for cell in table.nodes('td'):
            if cell.attrs.get('colspan', '').isdigit() and int(cell.attrs['colspan']) > 1:
                if cell.clean() == '등록된 게시물이 없습니다.':
                    return True
    return False


def collect(pages=3, fetch=None, aliases=None, channels=None, checked_at=None):
    # Share four extra attempts across the whole run, so widespread outages do
    # not multiply three retries across every sequential listing/detail read.
    builtin_fetch = fetch is None
    if builtin_fetch:
        fetch = partial(fetch_bytes, retry_budget=_FetchRetryBudget())

    def read_html(url, kind):
        raw = fetch(url, html_kind=kind) if builtin_fetch else fetch(url)
        return _complete_html(raw, kind)
    aliases = load_aliases() if aliases is None else aliases
    channels = CHANNELS if channels is None else channels
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    notices, holds, coverage, seen, unmatched = [],[],{},set(),[]
    for channel,base in channels.items():
        pending={1:base}; done=set(); stats={'pages':[],'discovered':0,'collected':0,'unmatched':0}
        coverage[channel]=stats
        while pending and len(done)<pages:
            number=min(pending); url=pending.pop(number)
            if number in done:
                continue
            done.add(number)
            try:
                html=read_html(url, 'listing')
                found, pagination=parse_listing(html,url,channel)
                if not found and not _explicit_empty_listing(html, channel):
                    raise ValueError('listing parser found no notice rows')
                if not found:
                    # Do not follow navigation from an explicitly empty page.
                    pagination = {}
                stats['pages'].append({'page':number,'url':url,'status':'ok','count':len(found)})
                pending.update({p:u for p,u in pagination.items() if p not in done and p<=pages})
            except Exception as exc:
                holds.append(dict(stage='listing',source_channel=channel,url=url,error=str(exc)))
                stats['pages'].append({'page':number,'url':url,'status':'error'})
                continue
            for candidate in found:
                if candidate['source_id'] in seen:
                    continue
                seen.add(candidate['source_id']);stats['discovered']+=1
                institution,confidence=match_issuer(candidate['title'],candidate['issuer_name'],'',aliases)
                if not institution:
                    stats['unmatched']+=1
                    unmatched.append({**candidate, 'source_channel':channel})
                    continue
                try:
                    html=read_html(candidate['url'], 'detail')
                    detail=parse_detail(html,candidate['url'],channel)
                    title=detail['title'] or candidate['title']
                    issuer=detail['issuer_name'] or candidate['issuer_name']
                    matched,confidence=match_issuer(title,issuer,detail['body'],aliases)
                    if not matched or matched != institution:
                        raise ValueError('issuer changed or ambiguous between listing and detail')
                    attachment_hashes,attachment_texts={},{}
                    attachments=detail['attachments']
                    # One offering document, never submission templates or ZIP bundles.
                    eligible=[a for a in attachments if re.search(r'\.(?:pdf|hwpx?|PDF)$',a['name']) and not re.search(r'양식|서식|제출서류|제안서',a['name'])]
                    for attachment in eligible[:1]:
                        try:
                            data=fetch(attachment['url'],candidate['url'])
                            if data.lstrip().lower().startswith((b'<!doctype html',b'<html')):
                                raise ValueError('attachment returned HTML')
                            try:
                                from .lp_attachment_text import extract_attachment
                            except ImportError:
                                from lp_attachment_text import extract_attachment
                            attachment_hashes[attachment['url']]=hashlib.sha256(data).hexdigest()
                            text=extract_attachment(data)['text'].strip()
                            if not text:
                                raise ValueError('attachment text extraction empty')
                            attachment_texts[attachment['url']]=text
                        except Exception as exc:
                            holds.append(dict(stage='attachment',source_id=candidate['source_id'],url=attachment['url'],error=str(exc)))
                    body=detail['body']
                    published=detail['date'] if detail['date_conflict'] else (detail['date'] or candidate['date'])
                    if not published:
                        raise ValueError('official publication date missing')
                    digest=hashlib.sha256(json.dumps([title,published,body],ensure_ascii=False).encode()).hexdigest()
                    dates={k:detail[k] for k in ('claimed_official_date','application_deadline','association_registered_at','date_basis','date_conflict')}
                    notices.append(dict(source_id=candidate['source_id'],institution_id=institution,url=candidate['url'],title=title,date=published,body=body,sha256=digest,attachment_hashes=attachment_hashes,attachment_texts=attachment_texts,attachments=attachments,checked_at=checked_at,source_channel=channel,source_scope=classify_scope(title,body+' '+' '.join(attachment_texts.values())),source_provenance={'kind':'association_republication','listing_url':url,'reported_issuer':issuer,'original_links':detail['original_links'],'scope_requires_review':True,**dates},match_confidence=confidence))
                    stats['collected']+=1
                except Exception as exc:
                    holds.append(dict(stage='detail',source_id=candidate['source_id'],institution_id=institution,url=candidate['url'],error=str(exc)))
    return dict(checked_at=checked_at,notices=notices,holds=holds,unmatched_notices=unmatched,coverage={'channel_pages':coverage,'notice_count':len(notices),'hold_count':len(holds)},update_policy='upsert_successes_preserve_existing_on_holds')


def main():
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0,str(ROOT))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--pages',type=int,default=3)
    args=parser.parse_args()
    if not 1<=args.pages<=50:
        parser.error('--pages must be between 1 and 50')
    result=collect(args.pages)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['coverage'],ensure_ascii=False))
    # A healthy board may have no recent target notices. It must not become
    # a collection failure or an instruction to erase the retained archive.
    return 0 if any(p['status']=='ok' for c in result['coverage']['channel_pages'].values() for p in c['pages']) else 1

if __name__=='__main__':
    raise SystemExit(main())
