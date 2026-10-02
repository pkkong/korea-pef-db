"""Collect the Teachers' Mutual Aid Association's official PEF notices.

New result notices are review candidates.  Only hash-bound, manually reviewed
sources may alter the public program or GP list.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
BASE = "https://www.ktcu.or.kr"
LIST = BASE + "/PPW-CSB-000101?srchKey=sj&srchText=PEF"
REVIEW = ROOT / "data/ktcu_program_review.json"
PROGRAM_ID = "ktcu-2026-blind-pef"


def _clean(value):
    return re.sub(r"\s+", " ", value).strip()


class NoticePage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.title = []
        self.date = []
        self.body = []
        self.attachments = []
        self.link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        zone = self.stack[-1][1] if self.stack else None
        if "notice-tit" in classes:
            zone = "heading"
        elif "notice-cont" in classes:
            zone = "body"
        elif zone == "heading" and tag == "h3":
            zone = "title"
        elif zone == "heading" and "date" in classes:
            zone = "date"
        if tag == "a" and "/comm/getFile?" in attrs.get("href", ""):
            self.link = attrs["href"]
        if tag in ("br", "p", "li", "tr", "div") and zone == "body":
            self.body.append("\n")
        if tag not in ("br", "img", "input", "meta", "link", "hr", "source", "wbr"):
            self.stack.append((tag, zone))

    def handle_endtag(self, tag):
        if tag == "a" and self.link:
            self.attachments.append((self.link, _clean(getattr(self, "link_text", ""))))
            self.link = None
            self.link_text = ""
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, value):
        zone = self.stack[-1][1] if self.stack else None
        if zone == "title":
            self.title.append(value)
        elif zone == "date":
            self.date.append(value)
        elif zone == "body":
            self.body.append(value)
        if self.link:
            self.link_text = getattr(self, "link_text", "") + value


def parse_notice(source_id, raw):
    page = NoticePage()
    page.feed(raw.decode("utf-8"))
    title, date, body = _clean(" ".join(page.title)), _clean(" ".join(page.date)), _clean(" ".join(page.body))
    if not title or not re.fullmatch(r"20\d\d-\d\d-\d\d", date) or len(body) < 30:
        raise ValueError(f"Invalid KTCU notice {source_id}")
    digest = hashlib.sha256(json.dumps([title, date, body], ensure_ascii=False).encode()).hexdigest()
    return {"source_id": str(source_id), "url": f"{BASE}/PPW-CSB-000101/{source_id}",
            "title": title, "date": date, "body": body, "sha256": digest,
            "attachments": [{"url": urljoin(BASE, path), "name": name} for path, name in page.attachments]}


def project(notices, checked_at, seed_program=None):
    recipe = json.loads(REVIEW.read_text())
    seed = seed_program or next(p for p in json.loads((ROOT / "data/lp_programs_pilot.json").read_text())["programs"]
                                if p["id"] == PROGRAM_ID)
    found = {str(n["source_id"]): n for n in notices}
    approved = recipe["sources"]
    holds = []
    for source in approved:
        n = found.get(str(source["source_id"]))
        actual_hash = (hashlib.sha256(json.dumps([n["title"], n["date"], n["body"]], ensure_ascii=False).encode()).hexdigest()
                       if n and all(k in n for k in ("title", "date", "body")) else None)
        if not n or n.get("sha256") != actual_hash or any(n.get(k) != source[k] for k in ("url", "title", "date", "sha256")):
            holds.append({"program_id": PROGRAM_ID, "reason": "검토된 교직원공제회 원문 변경 또는 누락"})
            return [], holds
        for file_name, digest in source.get("attachment_hashes", {}).items():
            if n.get("attachment_hashes", {}).get(file_name) != digest:
                holds.append({"program_id": PROGRAM_ID, "reason": "검토된 교직원공제회 첨부 변경 또는 누락"})
                return [], holds
        for quote in source.get("body_quotes", []):
            if quote not in n["body"]:
                holds.append({"program_id": PROGRAM_ID, "reason": "교직원공제회 핵심 조건 문구 변경"})
                return [], holds
        for quote in source.get("attachment_quotes", []):
            if quote not in n.get("attachment_text", ""):
                holds.append({"program_id": PROGRAM_ID, "reason": "교직원공제회 PDF 조건 확인 실패"})
                return [], holds
    if any(n["source_id"] not in {s["source_id"] for s in approved} for n in notices):
        return [], [{"program_id": PROGRAM_ID, "reason": "교직원공제회 새 단계 공고 연결·GP 명단 검토 필요"}]
    program = copy.deepcopy(seed)
    program["status"] = "접수 마감" if datetime.fromisoformat(checked_at) >= datetime.fromisoformat(program["deadline"]) else "접수 중"
    program["events"] = [e for e in program["events"] if e["type"] != "공고상 접수 마감"]
    program["selected_gps"] = []
    program["shortlisted_gps"] = []
    program["applicants_gps"] = []
    stage_names = {"접수 현황": ("application", "접수 현황"),
                   "서류심사 결과": ("screening", "1차 심사 결과"),
                   "최종 선정": ("selection", "최종 선정")}
    for source in approved:
        event = source.get("event", "모집 공고")
        if event == "모집 공고":
            continue
        if event not in stage_names:
            raise ValueError("Unknown reviewed KTCU stage")
        n = found[str(source["source_id"])]
        names = source.get("manager_names", [])
        if len(names) != len(set(names)) or any(name not in n["body"] + " " + n.get("attachment_text", "")
                                                   for name in names):
            holds.append({"program_id": PROGRAM_ID, "reason": "교직원공제회 단계별 GP 명단 근거 불일치"})
            return [], holds
        program["events"].append({"date": n["date"], "type": event, "title": n["title"], "url": n["url"]})
        stage, label = stage_names[event]
        program["schedule_stages"] = [s for s in program["schedule_stages"] if s["stage"] != stage or s["status"] == "announced_deadline"]
        program["schedule_stages"].append({"stage": stage, "label": label, "original_label": event,
                                            "date": n["date"], "precision": "day", "status": "confirmed",
                                            "source_url": n["url"], "detail": f"{len(names)}개 팀" if names else None})
        if event == "접수 현황":
            program["applicants_gps"] = names
            program["status"] = "심사 중"
        elif event == "서류심사 결과":
            if program["applicants_gps"] and not set(names) <= set(program["applicants_gps"]):
                holds.append({"program_id": PROGRAM_ID, "reason": "교직원공제회 서류 통과 GP가 접수 명단과 다름"})
                return [], holds
            program["shortlisted_gps"] = names
            program["status"] = "심사 중"
        else:
            prior = program["shortlisted_gps"] or program["applicants_gps"]
            if prior and not set(names) <= set(prior):
                holds.append({"program_id": PROGRAM_ID, "reason": "교직원공제회 최종 GP가 앞 단계 명단과 다름"})
                return [], holds
            if not names:
                holds.append({"program_id": PROGRAM_ID, "reason": "교직원공제회 선정 결과에 GP 명단 없음"})
                return [], holds
            program["selected_gps"] = [{"id": "ktcu-" + hashlib.sha256(name.encode()).hexdigest()[:16],
                                        "name": name, "source_url": n["url"], "asset_scope": "PE"}
                                       for name in names]
            program["status"] = "선정 완료"
    program["checked_at"] = checked_at
    program["collection_checked_at"] = checked_at
    return [program], holds


def link_suggestions(notices, title):
    approved_ids = {s["source_id"] for s in json.loads(REVIEW.read_text())["sources"]}
    return [{"source_id": n["source_id"], "title": n["title"], "date": n["date"], "url": n["url"],
             "stage": "후속 공고", "programs": [{"id": PROGRAM_ID, "title": title}],
             "sha256": n["sha256"], "attachment_hashes": n.get("attachment_hashes", {})}
            for n in notices if n["source_id"] not in approved_ids]


def collect(seed_program, checked_at, fetch=None):
    def get(url):
        if urlparse(url).hostname != "www.ktcu.or.kr":
            raise ValueError("Unexpected KTCU source host")
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=25) as response:
            if urlparse(response.geturl()).hostname != "www.ktcu.or.kr":
                raise ValueError("Unexpected KTCU redirect")
            return response.read()

    fetch = fetch or get
    listing = fetch(LIST).decode("utf-8")
    ids = set(re.findall(r"fn_view\('([0-9]+)'\).*?>([^<]+)</a>", listing))
    if not ids:
        raise ValueError("KTCU official listing yielded no notices")
    recipe = json.loads(REVIEW.read_text())
    selected = {source["source_id"] for source in recipe["sources"]}
    for source_id, title in ids:
        if "2026" in title and "PEF" in title and ("블라인드" in title or "선정" in title):
            selected.add(source_id)
    notices = []
    approved_by_id = {s["source_id"]: s for s in recipe["sources"]}
    for source_id in sorted(selected, key=int):
        notice = parse_notice(source_id, fetch(f"{BASE}/PPW-CSB-000101/{source_id}"))
        notice["attachment_hashes"] = {}
        if source_id in approved_by_id:
            names = set(approved_by_id[source_id].get("attachment_hashes", {}))
            for attachment in notice["attachments"]:
                if attachment["name"] not in names:
                    continue
                raw = fetch(attachment["url"])
                if not raw.startswith(b"%PDF"):
                    raise ValueError("Reviewed KTCU PDF invalid")
                notice["attachment_hashes"][attachment["name"]] = hashlib.sha256(raw).hexdigest()
                from pypdf import PdfReader
                notice["attachment_text"] = _clean(" ".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages))
        # Download tokens rotate on each page load; the notice is the stable
        # original link, while the verified filename and content hash persist.
        notice["attachments"] = [{"name": a["name"]} for a in notice["attachments"]]
        notices.append(notice)
    programs, holds = project(notices, checked_at, seed_program)
    suggestions = link_suggestions(notices, seed_program["title"])
    return {"notices": notices, "programs": programs, "holds": holds, "link_suggestions": suggestions}
