#!/usr/bin/env python3
"""Collect official notices; publish only the previously reviewed program.

Failure never replaces an existing output. New/changed evidence is retained in
the review queue while the last reviewed program is preserved.
"""
import argparse
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

ROOT = Path(__file__).resolve().parents[3]
BASE = "https://www.kgrowth.or.kr/"
LIST_URL = BASE + "notice.asp?str_type=1&tab=1"
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


def collect(seed, baseline=None, fetch=None):
    opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def get(url, referer=LIST_URL):
        with opener.open(Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer}), timeout=25) as response:
            if urlparse(response.geturl()).hostname != "www.kgrowth.or.kr":
                raise ValueError("Unexpected official source redirect")
            return response.read()

    fetch = fetch or get
    checked = datetime.now(timezone.utc).isoformat()
    listing = Page()
    listing.feed(fetch(LIST_URL).decode("cp949"))
    discovered = set()
    for link in listing.links:
        url = urlparse(urljoin(BASE, link))
        if url.hostname == "www.kgrowth.or.kr" and url.path == "/notice_view.asp":
            idx = parse_qs(url.query).get("idx", [""])[0]
            if idx.isdigit():
                discovered.add(int(idx))
    if not discovered:
        raise ValueError("Official listing yielded no notice links")
    notices = []
    for idx in sorted(discovered | set(KNOWN_IDS)):
        notice = parse_notice(idx, fetch(notice_url(idx)))
        notice["checked_at"] = checked
        notice["attachment_hashes"] = {}
        if idx in KNOWN_IDS:
            for url in notice["attachments"]:
                raw = fetch(url, notice["url"])
                if not raw.startswith((b"%PDF", b"PK", bytes.fromhex("d0cf11e0"))):
                    raise ValueError(f"Invalid attachment for {idx}")
                notice["attachment_hashes"][url] = hashlib.sha256(raw).hexdigest()
        notices.append(notice)
    baseline = baseline or {}
    candidates = baseline.get("programs") or seed.get("programs", [])
    program = copy.deepcopy(next(p for p in candidates if p["id"] == PROGRAM_ID))
    previous = {str(n["source_id"]): n for n in baseline.get("accepted_notices", baseline.get("notices", []))}
    review = []
    changed = False
    for notice in notices:
        sid = notice["source_id"]
        if int(sid) not in KNOWN_IDS:
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
    return {"checked_at": checked, "notices": notices, "accepted_notices": accepted,
            "programs": [program], "review": review, "requires_review": changed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--seed", type=Path, default=ROOT / "data/lp_programs_pilot.json")
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    result = collect(json.loads(args.seed.read_text()), baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.output)
    print(json.dumps({"notices": len(result["notices"]), "programs": len(result["programs"]),
                      "review": len(result["review"])}))


if __name__ == "__main__":
    main()
