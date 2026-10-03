"""Collect Korea Post's official domestic blind PEF notices, fail closed.

The reviewed recruitment notice is the only publishable stage. Later notices
are connection candidates until their exact source and GP evidence is reviewed.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import time
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, quote, urljoin, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "data/koreapost_program_review.json"
BASE = "https://www.kpasset.go.kr"
LIST_URL = BASE + "/board.es?mid=a10510000000&bid=0041"
SOURCE_ID = "0041:400"
PROGRAM_ID = "koreapost-2026-domestic-pe"


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "tr", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def value(self):
        return "\n".join(
            line for line in (re.sub(r"\s+", " ", x).strip()
                              for x in "".join(self.parts).splitlines()) if line
        )


def _text(fragment):
    p = _Text()
    p.feed(fragment)
    return p.value()


def _fingerprint(notice):
    parts = [notice["title"], notice["date"], notice["body"]]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()


def _official_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "www.kpasset.go.kr":
        raise ValueError("Unexpected Korea Post source host")
    return url


def _get(url):
    request = Request(_official_url(url), headers={"User-Agent": "Mozilla/5.0", "Referer": LIST_URL})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=25) as response:
                _official_url(response.geturl())
                return response.read()
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def _listing(html_bytes):
    html = html_bytes.decode("utf-8")
    links = []
    for tag in re.findall(r"<a\b[^>]*>", html, flags=re.IGNORECASE):
        href_match = re.search(r'\bhref="([^"]+)"', tag)
        title_match = re.search(r'\btitle="([^"]+)"', tag)
        if not href_match or not title_match:
            continue
        href = unescape(href_match.group(1))
        url = urljoin(BASE, href)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if parsed.path != "/board.es" or params.get("bid") != ["0041"] or params.get("act") != ["view"]:
            continue
        number = params.get("list_no", [""])[0]
        if number.isdigit():
            links.append((number, unescape(title_match.group(1))))
    return list(dict.fromkeys(links))


def _related(title):
    compact = re.sub(r"\s+", "", title).casefold()
    return ("우체국" in compact and "국내" in compact and "블라인드pef" in compact
            and "2025" not in compact)


def _pe_discovery_title(title):
    compact = re.sub(r"\s+", "", title).casefold()
    return ("우체국" in compact or "우정사업본부" in compact) and any(
        term in compact for term in ("pef", "사모펀드", "사모투자", "공동투자전략"))


def _current_program_title(title):
    years = re.findall(r"20\d{2}", title)
    return _related(title) and (not years or "2026" in years)


def discovery_candidates(notices):
    recipe = json.loads(REGISTRY.read_text())
    approved = {SOURCE_ID} | {s["source_id"] for s in recipe.get("stages", [])}
    return [{"institution_id": "koreapost", "source_id": n["source_id"],
             "title": n["title"], "date": n["date"], "url": n["url"]}
            for n in notices if n["source_id"] not in approved
            and n["date"] >= "2026-01-01" and not _current_program_title(n["title"])]


def _detail(number, raw):
    html = raw.decode("utf-8")
    title_match = re.search(r'<p\s+class="title"[^>]*>(.*?)</p>', html, re.I | re.S)
    body_match = re.search(r'<td\s+colspan="4"\s+class="tb_contents"[^>]*>(.*?)</td>', html, re.I | re.S)
    date_match = re.search(r'작성일시\s*</th>\s*<td[^>]*>\s*(\d{4}-\d{2}-\d{2})', html, re.I | re.S)
    if not title_match or not body_match or not date_match:
        raise ValueError(f"Official Korea Post detail {number} is incomplete")
    title, body, date = _text(title_match.group(1)), _text(body_match.group(1)), date_match.group(1)
    if not title or not body:
        raise ValueError(f"Official Korea Post detail {number} is empty")
    attachments = []
    for tag in re.findall(r"<a\b[^>]*>", html, flags=re.IGNORECASE):
        href_match = re.search(r'\bhref="([^"]+)"', tag)
        if href_match:
            href = unescape(href_match.group(1))
            if urlparse(href).path == "/download.es":
                # Spaces and Korean filenameOrg text require percent encoding.
                url = urljoin(BASE, quote(href, safe=":/?&=%"))
                _official_url(url)
                attachments.append(url)
    notice = {"source_id": f"0041:{number}", "url": f"{BASE}/board.es?mid=a10510000000&bid=0041&act=view&list_no={number}",
              "title": title, "date": date, "body": body,
              "attachments": list(dict.fromkeys(attachments))}
    notice["sha256"] = _fingerprint(notice)
    return notice


def _pdf_text(raw):
    from pypdf import PdfReader
    text = " ".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    return re.sub(r"\s+", " ", text).strip()


def _deadline_passed(checked_at, deadline):
    checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    ending = datetime.fromisoformat(deadline)
    if checked.tzinfo is None:
        raise ValueError("checked_at requires a timezone")
    return checked >= ending


def project(notices: list[dict], checked_at: str) -> tuple[list[dict], list[dict]]:
    """Recheck live evidence against the reviewed source, never trust a payload."""
    recipe = json.loads(REGISTRY.read_text())
    by_id = {n["source_id"]: n for n in notices}
    hold = lambda reason: ([], [{"program_id": PROGRAM_ID, "reason": reason}])
    if SOURCE_ID not in by_id:
        return hold("공식 모집 공고 확인 실패")
    source = by_id[SOURCE_ID]
    if (source["title"] != recipe["source_title"] or source["date"] != recipe["source_date"]
            or _fingerprint(source) != recipe["sha256"] or source.get("sha256") != recipe["sha256"]):
        return hold("검토된 공고 원문 변경")
    if source.get("attachment_hashes") != recipe["attachment_hashes"]:
        return hold("검토된 공고 첨부 변경")
    pdf_url = recipe["pdf_url"]
    pdf_text = source.get("attachment_texts", {}).get(pdf_url, "")
    for fact in recipe["facts"]:
        text = pdf_text if fact["source"] == "pdf" else source["body"]
        if fact["quote"] not in text:
            return hold(f"검토된 문구 변경: {fact['field']}")
    approved_ids = {SOURCE_ID} | {s["source_id"] for s in recipe.get("stages", [])}
    if any(n["source_id"] not in approved_ids and _current_program_title(n["title"]) for n in notices):
        return hold("새 단계 공고 연결·GP 명단 검토 필요")
    program = copy.deepcopy(recipe["program"])
    program["checked_at"] = checked_at
    program["collection_checked_at"] = checked_at
    program["status"] = "접수 마감" if _deadline_passed(checked_at, program["deadline"]) else "모집 공고"
    # A final GP never originates from the recruitment document.
    program["selected_gps"] = []
    program["applicants_gps"] = []
    program["shortlisted_gps"] = []
    stages = {"접수 현황": ("application", "접수 현황"),
              "서류심사 결과": ("screening", "1차 심사 결과"),
              "최종 선정": ("selection", "최종 선정")}
    for approved in recipe.get("stages", []):
        event = approved["event"]
        if event not in stages:
            return hold("검토된 우정사업본부 단계 유형이 잘못됨")
        n = by_id.get(approved["source_id"])
        if (not n or n["title"] != approved["title"] or n["date"] != approved["date"]
                or _fingerprint(n) != approved["sha256"] or n.get("sha256") != approved["sha256"]
                or n.get("attachment_hashes", {}) != approved.get("attachment_hashes", {})):
            return hold("검토된 우정사업본부 후속 공고 변경 또는 누락")
        source_text = n["body"] + " " + " ".join(n.get("attachment_texts", {}).values())
        if any(quote not in source_text for quote in approved.get("quotes", [])):
            return hold("우정사업본부 단계별 GP 근거 문구 변경")
        names = approved.get("manager_names", [])
        if len(names) != len(set(names)) or (names and any(name not in source_text for name in names)):
            return hold("우정사업본부 단계별 GP 명단 근거 불일치")
        stage,label = stages[event]
        program["events"].append({"date": n["date"], "type": event, "title": n["title"], "url": n["url"]})
        program["schedule_stages"] = [s for s in program["schedule_stages"]
                                      if s["stage"] != stage or s["status"] == "announced_deadline"]
        program["schedule_stages"].append({"stage": stage, "label": label, "original_label": event,
                                            "date": n["date"], "precision": "date", "status": "confirmed",
                                            "source_url": n["url"], "detail": f"{len(names)}개 팀" if names else None})
        if event == "접수 현황":
            program["applicants_gps"] = names
            program["status"] = "심사 중"
        elif event == "서류심사 결과":
            if program["applicants_gps"] and not set(names) <= set(program["applicants_gps"]):
                return hold("우정사업본부 1차 GP가 접수 명단과 다름")
            program["shortlisted_gps"] = names
            program["status"] = "심사 중"
        else:
            prior = program["shortlisted_gps"] or program["applicants_gps"]
            if prior and not set(names) <= set(prior):
                return hold("우정사업본부 최종 GP가 앞 단계 명단과 다름")
            if not names:
                return hold("우정사업본부 선정 결과에 GP 명단 없음")
            program["selected_gps"] = [{"id": "koreapost-" + hashlib.sha256(name.encode()).hexdigest()[:16],
                                        "name": name, "source_url": n["url"], "asset_scope": "국내 PE"}
                                       for name in names]
            program["status"] = "선정 완료"
    return [program], []


def _suggestions(notices):
    candidates = []
    approved_ids = {SOURCE_ID} | {s["source_id"] for s in json.loads(REGISTRY.read_text()).get("stages", [])}
    for notice in notices:
        if notice["source_id"] in approved_ids or not _current_program_title(notice["title"]):
            continue
        title = re.sub(r"\s+", "", notice["title"])
        stage = ("정정·변경" if any(t in title for t in ("정정", "변경", "연장", "취소", "재공고")) else
                 "접수 현황" if "접수" in title else
                 "1차 심사 결과" if any(t in title for t in ("정량평가", "서류심사", "1차평가")) else
                 "최종 선정" if any(t in title for t in ("최종", "선정결과", "선정안내")) else
                 "후속 공고")
        candidates.append({"source_id": notice["source_id"], "url": notice["url"],
                           "date": notice["date"], "title": notice["title"], "stage": stage,
                           "sha256": notice["sha256"],
                           "attachment_hashes": notice.get("attachment_hashes", {}),
                           "programs": [{"id": PROGRAM_ID, "title": "2026 국내 블라인드 PEF"}]})
    return candidates


def collect(seed_program: dict, checked_at: str, fetch=None) -> dict:
    if seed_program["id"] != PROGRAM_ID:
        raise ValueError("Unexpected Korea Post program seed")
    fetch = fetch or _get
    recipe = json.loads(REGISTRY.read_text())
    discovered = {}
    for page in range(1, 11):
        url = LIST_URL + f"&nPage={page}"
        links = _listing(fetch(url))
        if page == 1 and not links:
            raise ValueError("Official Korea Post listing has no notice links")
        if not links:
            break
        for number, title in links:
            if _pe_discovery_title(title):
                discovered[number] = title
        if len(links) < 10:
            break
    else:
        raise ValueError("Korea Post listing pagination exceeded safety limit")
    # Keep the known source under observation if pagination is changed.
    discovered.setdefault("400", seed_program["title"])
    for stage in recipe.get("stages", []):
        discovered.setdefault(stage["source_id"].split(":")[-1], stage["title"])
    notices = []
    reviewed_ids = {SOURCE_ID} | {s["source_id"] for s in recipe.get("stages", [])}
    for number in sorted(discovered, key=int):
        url = f"{BASE}/board.es?mid=a10510000000&bid=0041&act=view&list_no={number}"
        notice = _detail(number, fetch(url))
        if not _pe_discovery_title(notice["title"]):
            if number == "400":
                raise ValueError("Reviewed Korea Post notice no longer matches program")
            continue
        if notice["date"] < "2026-01-01" and notice["source_id"] not in reviewed_ids:
            continue
        notice["attachment_hashes"] = {}
        notice["attachment_texts"] = {}
        attachments_to_verify = (notice["attachments"] if notice["source_id"] in reviewed_ids
                                 or _current_program_title(notice["title"]) else [])
        for attachment_url in attachments_to_verify:
            raw = fetch(attachment_url)
            if not raw.startswith((b"%PDF", b"PK", bytes.fromhex("d0cf11e0"))):
                raise ValueError("Official Korea Post attachment is invalid")
            notice["attachment_hashes"][attachment_url] = hashlib.sha256(raw).hexdigest()
            if raw.startswith(b"%PDF"):
                notice["attachment_texts"][attachment_url] = _pdf_text(raw)
        notices.append(notice)
    programs, holds = project(notices, checked_at)
    return {"checked_at": checked_at, "notices": notices, "programs": programs,
            "holds": holds, "link_suggestions": _suggestions(notices),
            "discovery_candidates": discovery_candidates(notices)}
