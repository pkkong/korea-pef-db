#!/usr/bin/env python3
"""Discover official notices and retain verified attachment body evidence.

Collection failure never replaces an existing output. Listing-only diagnostics
retain incomplete evidence with an unsuccessful exit. The publisher checks
source-derived terms before refreshing or introducing any public program.
"""
import argparse
import copy
import hashlib
import json
import re
import time
from urllib.error import URLError
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener
from kgrowth_program_review import recipes, candidate_queue, link_suggestions, reviewed_programs
from lp_attachment_text import extract_attachment
from kgrowth_notice_terms import discovery as discover_terms
from kgrowth_listing import BASE, LIST_URL, discover_window

ROOT = Path(__file__).resolve().parents[3]
PROGRAM_ID = "kgrowth-2026-bank-valueup-3"
KNOWN_IDS = (1047, 1075, 1090, 1100)
KNOWN_EVENTS = {1047: ("2026-06-04", "모집 공고"), 1075: ("2026-07-07", "접수 현황"),
                1090: ("2026-07-23", "서류심사 결과"), 1100: ("2026-07-31", "최종 선정")}
PROJECT = "은행권중견기업밸류업펀드(3차)"
NAME_ALIASES = {"우리프라이빗에쿼티자산운용": "우리프라이빗에퀴티자산운용"}


def compact(value):
    return re.sub(r"\s+", "", value).replace("\u200b", "")


def notice_url(source_id):
    return BASE + f"notice_view.asp?idx={source_id}&str_type=1&tab=1"


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = {"title": [], "date": [], "body": []}
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        zone = self.stack[-1][1] if self.stack else None
        if "view_info" in classes:
            zone = "info"
        elif "veiw_contents" in classes:
            zone = "body"
        elif zone == "info" and "tit" in classes:
            zone = "title"
        elif zone == "info" and "date" in classes:
            zone = "date"
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in ("p", "tr", "br", "div") and zone in self.parts:
            self.parts[zone].append("\n")
        if tag not in ("br", "img", "input", "meta", "link", "hr", "source", "wbr"):
            self.stack.append((tag, zone))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, text):
        zone = self.stack[-1][1] if self.stack else None
        if zone in self.parts and not any(t in ("script", "style") for t, _ in self.stack):
            self.parts[zone].append(text)

    def value(self, field):
        return "\n".join(line for line in
                         (re.sub(r"\s+", " ", x).strip() for x in
                          "".join(self.parts[field]).replace("\u200b", "").splitlines()) if line)


def event_type(title, body):
    text = compact(title)
    if any(word in text for word in ("취소", "정정", "수정", "연장", "재공고")):
        return None
    if "서류심사" in text and "통과" in body:
        return "서류심사 결과"
    if "접수현황" in text and "신청" in body:
        return "접수 현황"
    if "선정결과" in text and "서류" not in text and "선정 결과" in body and "운용사명" in body:
        return "최종 선정"
    if "선정계획공고" in text and "공고" in body:
        return "모집 공고"
    return None


def parse_notice(source_id, raw):
    page = Page()
    page.feed(raw.decode("cp949"))
    title, body = page.value("title"), page.value("body")
    match = re.search(r"\d{4}-\d{2}-\d{2}", page.value("date"))
    if not title or not body or not match or "비정상적인 접근" in raw.decode("cp949"):
        raise ValueError(f"Official notice {source_id} has missing/invalid content")
    date = match.group()
    digest = hashlib.sha256(json.dumps([title, date, body], ensure_ascii=False).encode()).hexdigest()
    attachments = [urljoin(BASE, link) for link in page.links if "down_file.asp" in link]
    return {"source_id": str(source_id), "url": notice_url(source_id), "title": title,
            "date": date, "body": body, "sha256": digest,
            "event_type": event_type(title, body), "attachments": attachments}


def extract_teams(body, expected, bullets=True):
    match = re.search(r"운용사명\s*\(가나다순\)", body)
    if not match:
        raise ValueError("Explicit manager list heading missing")
    section = re.split(r"\n\s*문의\s*:", body[match.end():])[0]
    if bullets:
        names = re.findall(r"(?:^|\n)\s*-\s+([^\n]+)", section)
    else:
        names = [line.strip() for line in section.splitlines() if line.strip()]
    names = [NAME_ALIASES.get(name.strip(), name.strip()) for name in names]
    if len(names) != expected or len(set(names)) != expected:
        raise ValueError(f"Expected {expected} unique official manager teams, got {len(names)}")
    return names


def official_fetcher():
    opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def get(url, referer=LIST_URL):
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
        for attempt in range(3):
            try:
                with opener.open(request, timeout=25) as response:
                    if urlparse(response.geturl()).hostname != "www.kgrowth.or.kr":
                        raise ValueError("Unexpected official source redirect")
                    raw = response.read(12 * 1024 * 1024 + 1)
                    if len(raw) > 12 * 1024 * 1024:
                        raise ValueError('Official Korea Growth response exceeds 12 MiB')
                    return raw
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
    return get


def collect(seed, baseline=None, fetch=None, listing_pages=3, *, lookback_days=None, as_of=None):
    baseline = baseline or {}
    fetch = fetch or official_fetcher()
    checked = datetime.now(timezone.utc).isoformat()
    if not 1 <= listing_pages <= 20:
        raise ValueError("Listing page limit must be between 1 and 20")
    discovered = set()
    listing_urls = []
    inventory = None
    if lookback_days is not None:
        inventory = discover_window(fetch, days=lookback_days, as_of=as_of, max_pages=listing_pages)
        if not inventory['complete']:
            raise ValueError('Korea Growth date discovery incomplete: ' + inventory['boundary'])
        discovered = {int(row['source_id']) for row in inventory['rows']}
        listing_urls = [receipt['url'] for receipt in inventory['receipts']]
    pending = [] if inventory is not None else [LIST_URL]
    while pending and len(listing_urls) < listing_pages:
        listing_url = pending.pop(0)
        listing = Page()
        listing.feed(fetch(listing_url).decode("cp949"))
        listing_urls.append(listing_url)
        page_ids = set()
        for link in listing.links:
            url = urlparse(urljoin(BASE, link))
            if url.hostname == "www.kgrowth.or.kr" and url.path == "/notice_view.asp":
                idx = parse_qs(url.query).get("idx", [""])[0]
                if idx.isdigit():
                    page_ids.add(int(idx))
            paging = re.fullmatch(r"javascript:ListView\((\d+),1,0\)", link, re.I)
            if paging and 1 < int(paging[1]) <= listing_pages:
                next_url = LIST_URL + "&page=" + paging[1]
                if next_url not in pending + listing_urls:
                    pending.append(next_url)
        if not page_ids:
            raise ValueError("Official listing page yielded no notice links")
        discovered.update(page_ids)
    if not discovered:
        raise ValueError("Official listing yielded no notice links")
    # Discovery and approval are separate: keep following unreviewed notices
    # even when the next batch of announcements pushes them off the listing.
    tracked = {int(n['source_id']) for n in baseline.get('tracked_notices',
               baseline.get('accepted_notices', baseline.get('notices', [])))
               if str(n.get('source_id', '')).isdigit()}
    approved_sources = {int(s['source_id']):s for r in recipes() for s in r['sources']}
    listing_dates = {row['source_id']: row['date'] for row in inventory['rows']} if inventory else {}
    notices = []
    for idx in sorted(discovered | tracked | set(KNOWN_IDS) | set(approved_sources)):
        notice = parse_notice(idx, fetch(notice_url(idx)))
        if str(idx) in listing_dates and listing_dates[str(idx)] != notice['date']:
            raise ValueError(f'Official listing and notice {idx} publication dates differ')
        notice["checked_at"] = checked
        notice["attachment_hashes"] = {}
        if notice['attachments']:
            for url in notice["attachments"]:
                raw = fetch(url, notice["url"])
                if not raw.startswith((b"%PDF", b"PK", bytes.fromhex("d0cf11e0"))):
                    raise ValueError(f"Invalid attachment for {idx}")
                notice["attachment_hashes"][url] = hashlib.sha256(raw).hexdigest()
                try:
                    document = extract_attachment(raw)
                    notice.setdefault('attachment_documents', {})[url] = document
                    if document['text']:
                        notice.setdefault('attachment_texts', {})[url] = re.sub(r'\s+', ' ', document['text']).strip()
                except ValueError as error:
                    notice.setdefault('attachment_errors', {})[url] = str(error)
                    if url in approved_sources.get(idx, {}).get('text_attachments', []):
                        raise ValueError(f'Reviewed attachment extraction failed: {error}') from error
        notices.append(notice)
    candidates = baseline.get("programs") or seed.get("programs", [])
    program = copy.deepcopy(next(p for p in candidates if p["id"] == PROGRAM_ID))
    previous = {str(n["source_id"]): n for n in baseline.get("accepted_notices", baseline.get("notices", []))}
    review = []
    changed = False
    for notice in notices:
        sid = notice["source_id"]
        if int(sid) not in KNOWN_IDS:
            if PROJECT in compact(notice["title"]):
                changed = True
            review.append({"source_id": sid, "url": notice["url"], "reason": "새 공고 · 사업 연결 및 원문 검토 필요"})
            continue
        if PROJECT not in compact(notice["title"]) or not notice["event_type"]:
            raise ValueError(f"Known source {sid} no longer matches reviewed program")
        if not previous and (notice["date"], notice["event_type"]) != KNOWN_EVENTS[int(sid)]:
            raise ValueError(f"Initial source {sid} differs from reviewed date/stage")
        if sid in previous and (notice["sha256"] != previous[sid].get("sha256") or
                                notice["attachment_hashes"] != previous[sid].get("attachment_hashes")):
            changed = True
            review.append({"source_id": sid, "url": notice["url"], "reason": "검토된 원문 또는 첨부 변경 · 기존 사업 정보 보존"})
    by_id = {int(n["source_id"]): n for n in notices}
    if not changed:
        # Only exact, already reviewed GP names can be retained. No name inference.
        final = by_id[1100]
        selected = extract_teams(final["body"], 3, bullets=False)
        if set(selected) != {g["name"] for g in program.get("selected_gps", [])}:
            raise ValueError("Official final managers differ from reviewed selection")
        applicants = extract_teams(by_id[1075]["body"], 17)
        shortlist = extract_teams(by_id[1090]["body"], 6)
        if not set(selected) <= set(shortlist) <= set(applicants):
            raise ValueError("Official stage manager lists do not reconcile")
        program["applicants_gps"] = applicants
        program["shortlisted_gps"] = shortlist
        program["manager_list_sources"] = {"applicants_gps": by_id[1075]["url"],
                                           "shortlisted_gps": by_id[1090]["url"]}
        program["events"] = [{"date": by_id[i]["date"], "type": by_id[i]["event_type"],
                               "title": by_id[i]["title"], "url": by_id[i]["url"]} for i in KNOWN_IDS]
        for stage in program.get("schedule_stages", []):
            source_id = parse_qs(urlparse(stage.get("source_url", "")).query).get("idx", [""])[0]
            if source_id.isdigit() and int(source_id) in by_id:
                source = by_id[int(source_id)]
                stage.update(date=source["date"], source_url=source["url"])
        program["checked_at"] = checked
        program["collection_checked_at"] = checked
    # Keep the accepted fingerprint until a reviewer explicitly accepts a change.
    # Otherwise a second run could silently accept yesterday's quarantined edit.
    accepted = baseline.get("accepted_notices", baseline.get("notices", [])) or notices
    additions, holds = reviewed_programs(notices, checked)
    reviewed_ids = {str(s['source_id']) for r in recipes() if r['id'] in {p['id'] for p in additions} for s in r['sources']}
    review = [item for item in review if item['source_id'] not in reviewed_ids]
    offering_terms, term_holds, offering_candidates = discover_terms(notices)
    coverage = {"listing_urls": listing_urls, "discovered_count": len(discovered),
                "fetched_count": len(notices), "missing_source_ids": sorted(str(i) for i in discovered - {int(n['source_id']) for n in notices}),
                "attachments": [{"source_id": n['source_id'], "source_url": n['url'], "attachment_url": url,
                                 "sha256": digest, "format": n.get('attachment_documents', {}).get(url, {}).get('format'),
                                 "readable": bool(n.get('attachment_texts', {}).get(url)),
                                 "reason": n.get('attachment_errors', {}).get(url, '')}
                                for n in notices for url, digest in n.get('attachment_hashes', {}).items()]}
    if inventory is not None:
        coverage['date_discovery'] = inventory
    return {"checked_at": checked, "notices": notices, "tracked_notices": notices,
            "accepted_notices": accepted,
            "candidate_groups": candidate_queue([n for n in notices if n['source_id'] in {i['source_id'] for i in review}]),
            "link_suggestions": link_suggestions(notices),
            "reviewed_programs": additions, "program_holds": holds,
            "offering_terms": offering_terms, "extraction_holds": term_holds,
            "offering_candidates": offering_candidates, "collection_coverage": coverage,
            "programs": [program], "review": review, "requires_review": changed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--seed", type=Path, default=ROOT / "data/lp_programs_pilot.json")
    parser.add_argument("--listing-pages", type=int, default=3)
    parser.add_argument("--lookback-days", type=int, help="Discover by official publication date, bounded by --listing-pages")
    parser.add_argument("--as-of", help="Inclusive publication window end (YYYY-MM-DD), default current Seoul date")
    parser.add_argument("--inventory-only", action="store_true", help="Keep listing evidence without details, DB writes or publication")
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    if args.inventory_only:
        if args.lookback_days is None:
            parser.error('--inventory-only requires --lookback-days')
        result = discover_window(official_fetcher(), days=args.lookback_days, as_of=args.as_of, max_pages=args.listing_pages)
    else:
        result = collect(json.loads(args.seed.read_text()), baseline, listing_pages=args.listing_pages,
                         lookback_days=args.lookback_days, as_of=args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.output)
    if args.inventory_only:
        print(json.dumps({key: value for key, value in result.items() if key not in {'rows', 'receipts'}} |
                         {'rows': len(result['rows']), 'pages': len(result['receipts'])}))
        if not result['complete']:
            raise SystemExit('Korea Growth date discovery incomplete: ' + result['boundary'])
        return
    lines = ['# 한국성장금융 공고 검토', '', '## 신규 공개 대상', '']
    lines += [f"- {p['title']}" for p in result['reviewed_programs']]
    coverage = result['collection_coverage']
    lines += ['', '## 수집 범위', '',
              f"- 공식 목록 {len(coverage['listing_urls'])}페이지 · 발견 {coverage['discovered_count']}건 · 수집 {coverage['fetched_count']}건",
              f"- 발견 후 누락: {len(coverage['missing_source_ids'])}건",
              f"- 첨부 {len(coverage['attachments'])}개 · 본문 읽기 완료 {sum(a['readable'] for a in coverage['attachments'])}개"]
    if coverage.get('date_discovery'):
        inventory = coverage['date_discovery']
        lines += [f"- 게시일 범위 {inventory['window']['start']}~{inventory['window']['end']} · 탐색 경계 {inventory['boundary']}"]
    lines += ['', '## 첨부 읽기 실패', '']
    lines += [f"- [{a['source_id']}]({a['source_url']}): {a['reason']}" for a in coverage['attachments']
              if not a['readable'] and a.get('reason')]
    lines += ['', '## 항목 추출 보류', '']
    lines += [f"- [{h['program_id']}]({h['source_url']}): {h['reason']}" for h in result['extraction_holds']]
    lines += ['', '## 확인이 필요한 사업', '']
    for hold in result['program_holds']:
        lines.append(f"- {hold['program_id']}: {hold['reason']}")
    lines += ['', '## 기존 사업의 새 단계 후보', '']
    for item in result['link_suggestions']:
        targets = ', '.join(program['title'] for program in item['programs'])
        lines.append(f"- {item['date']} · {item['stage']} · [{item['title']}]({item['url']}) → {targets}")
    for group in result['candidate_groups']:
        lines += ['', f"### {group['title']} — {group['disposition']}", '']
        lines += [f"- {n['date']} · {n['stage']} · [{n['title']}]({n['url']})" for n in group['notices']]
    args.output.with_suffix('.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({"notices": len(result["notices"]), "programs": len(result["programs"])+len(result['reviewed_programs']),
                      "review": len(result["review"])}))


if __name__ == "__main__":
    main()
