"""Collect Korea Post's official domestic blind PEF notices, fail closed.

The reviewed recruitment notice is the only publishable stage. Later notices
are connection candidates until their exact source and GP evidence is reviewed.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import ssl
import io
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse
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


def _compat_context():
    """Certificate-verifying context that also offers older server ciphers.

    Used only after a TLS handshake refusal from the official host (observed
    2026-11-12 22:00 KST while browsers still connected). Verification of the
    certificate chain and host name is unchanged.
    """
    context = ssl.create_default_context()
    context.set_ciphers("DEFAULT:@SECLEVEL=1")
    context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
    return context


def _handshake_refused(error):
    reason = getattr(error, "reason", error)
    return isinstance(reason, ssl.SSLError) and "HANDSHAKE_FAILURE" in str(reason).upper()


def _get(url):
    request = Request(_official_url(url), headers={"User-Agent": "Mozilla/5.0", "Referer": LIST_URL})
    context = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=25, context=context) as response:
                _official_url(response.geturl())
                raw = response.read(25 * 1024 * 1024 + 1)
                if not raw or len(raw) > 25 * 1024 * 1024:
                    raise ValueError('Korea Post response exceeds bounded evidence limit')
                return raw
        except HTTPError as error:
            if error.code in (404, 410) or attempt == 3:
                raise
            time.sleep(attempt + 1)
        except (URLError, TimeoutError, ssl.SSLError) as error:
            if attempt == 3:
                raise
            if context is None and _handshake_refused(error):
                context = _compat_context()
                continue
            time.sleep(2 * (attempt + 1))


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
        if (parsed.scheme != "https" or parsed.hostname != "www.kpasset.go.kr" or parsed.username or parsed.password
                or parsed.path != "/board.es" or params.get("bid") != ["0041"] or params.get("act") != ["view"]):
            continue
        number = params.get("list_no", [""])[0]
        if number.isdigit():
            links.append((number, unescape(title_match.group(1))))
    return list(dict.fromkeys(links))



def _date_window(checked_at):
    checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    if checked.tzinfo is None:
        raise ValueError("checked_at requires a timezone")
    end = checked.astimezone(timezone(timedelta(hours=9))).date()
    return (end - timedelta(days=364)).isoformat(), end.isoformat()


class _SearchInputs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name"):
            self.values.setdefault(attrs["name"], []).append(attrs.get("value", ""))



class _Pagination(_SearchInputs):
    def __init__(self):
        super().__init__()
        self.stack, self.links = [], []
        self.pager_depth = None
        self.pager_count = 0

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        attrs = dict(attrs)
        if tag == "div" and "board_pager" in attrs.get("class", "").split():
            self.pager_count += 1
            self.pager_depth = len(self.stack)
        if self.pager_depth is not None and tag == "a":
            self.links.append(attrs)
        if tag not in {"input", "br", "hr", "img", "meta", "link", "col", "area", "source", "wbr"}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                del self.stack[index:]
                break
        if self.pager_depth is not None and len(self.stack) <= self.pager_depth:
            self.pager_depth = None


def _listing_last_page(html, url):
    """Return an observed final numeric pager, never a guessed page boundary.

    Only a contiguous, first-page number block shorter than ten is conclusive
    without an explicit last-page control. Larger/unrecognized blocks remain
    unknown. A bare empty table is never evidence of an empty date window.
    """
    if isinstance(html, bytes):
        html = html.decode("utf-8")
    request = urlparse(url)
    query = parse_qs(request.query, keep_blank_values=True)
    if (request.scheme != "https" or request.hostname != "www.kpasset.go.kr"
            or request.username or request.password or request.port not in {None, 443}
            or request.fragment or request.path != "/board.es" or query.get("bid") != ["0041"]
            or query.get("mid") != ["a10510000000"] or len(query.get("nPage", [])) != 1
            or not query["nPage"][0].isdigit() or int(query["nPage"][0]) < 1):
        raise ValueError("Invalid Korea Post listing pager request")
    parser = _Pagination()
    parser.feed(html)
    if not parser.pager_count:
        return None
    if parser.pager_count != 1 or "</html>" not in html.lower():
        raise ValueError("Incomplete or ambiguous Korea Post pagination")
    requested = int(query["nPage"][0])
    forms = parser.values.get("nPage", [])
    if not forms or any(not value.isdigit() or int(value) != requested for value in forms):
        raise ValueError("Korea Post listing page was not echoed")
    if not parser.values.get("bid") or any(value != "0041" for value in parser.values["bid"]):
        raise ValueError("Korea Post listing pager board differs")
    pages, current = set(), []
    for anchor in parser.links:
        target = urlparse(urljoin(url, anchor.get("href", "")))
        params = parse_qs(target.query, keep_blank_values=True)
        if (target.scheme != "https" or target.hostname != "www.kpasset.go.kr"
                or target.username or target.password or target.port not in {None, 443}
                or target.fragment or target.path != "/board.es" or params.get("bid") != ["0041"]
                or params.get("mid") != ["a10510000000"] or len(params.get("nPage", [])) != 1
                or not params["nPage"][0].isdigit() or int(params["nPage"][0]) < 1):
            raise ValueError("Invalid official Korea Post pager link")
        for key in ("keySDate", "keyEDate"):
            if key in params and params[key] != query.get(key):
                raise ValueError("Korea Post pager date filters differ")
        if set(params) - {"mid", "bid", "nPage", "keySDate", "keyEDate"}:
            return None
        number = int(params["nPage"][0])
        pages.add(number)
        classes = set(anchor.get("class", "").split())
        if "pageNow" in classes:
            current.append(number)
        elif "pageNone" not in classes:
            return None
    if not pages:
        return None
    last = max(pages)
    if current != ([requested] if requested <= last else []):
        raise ValueError("Korea Post current page marker differs")
    if last >= 10 or pages != set(range(1, last + 1)):
        return None
    return last


def _listing_filter_evidence(raw, start, end):
    parser = _SearchInputs()
    parser.feed(raw.decode("utf-8"))
    for key, expected in (("keySDate", start), ("keyEDate", end)):
        if any(value != expected for value in parser.values.get(key, [])):
            raise ValueError("Official Korea Post listing date filters differ from requested window")
    confirmed = all(parser.values.get(key) for key in ("keySDate", "keyEDate"))
    return "echo_confirmed" if confirmed else "unknown"


def _explicit_empty_listing(raw):
    html = raw.decode("utf-8")
    parser = _SearchInputs()
    parser.feed(html)
    return (parser.values.get("bid") and all(value == "0041" for value in parser.values["bid"]) and bool(re.search(
        r"(?:등록된|검색된|조회된)\s*게시물(?:이|은)?\s*없습니다[.]?", _text(html))))


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


def _recruitment_title(title):
    compact = re.sub(r"\s+", "", title)
    return "공고" in compact and not any(
        term in compact for term in ("결과", "우선협상", "정량평가", "서류심사"))


def discovery_candidates(notices):
    recipe = json.loads(REGISTRY.read_text())
    approved = {SOURCE_ID} | {s["source_id"] for s in recipe.get("stages", [])}
    return [{"institution_id": "koreapost", "source_id": n["source_id"],
             "title": n["title"], "date": n["date"], "url": n["url"]}
            for n in notices if n["source_id"] not in approved
            and not _current_program_title(n["title"])]


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


def extract_preferred(recruitment_notice, preferred_notice, *, checked_at=None):
    """Pure independently checked pre-final roster; no registry or GP-ID mutation."""
    for n in (recruitment_notice, preferred_notice):
        if (any(n.get(k) in (True, 1, 'true', '1') for k in ('restricted', 'closed', 'owner_closed'))
                or n.get('status') in ('restricted', 'closed', 'owner_closed')):
            raise ValueError('Restricted preferred roster evidence')
    if re.search(r'국내\s*공동\s*투자', recruitment_notice.get('title', '')):
        try:
            from .koreapost_coinvestment_preferred import extract_preferred as extract_coinvestment
        except ImportError:
            from koreapost_coinvestment_preferred import extract_preferred as extract_coinvestment
        return extract_coinvestment(recruitment_notice, preferred_notice,
                                    checked_at=checked_at or datetime.now(timezone.utc).isoformat())
    source = recruitment_notice
    ident = re.fullmatch(r"0041:([1-9][0-9]*)", source.get("source_id", ""))
    if (not ident or source.get("institution_id", "koreapost") != "koreapost"
            or source.get("url") != f"{BASE}/board.es?mid=a10510000000&bid=0041&act=view&list_no={ident[1]}"
            or source.get("sha256") != _fingerprint(source)
            or not source.get("body", "").strip()
            or not re.search(r"위탁운용사\s*선정\s*공고", source.get("title", ""))
            or re.search(r"재공고|정정|변경|취소", source["title"])):
        raise ValueError("Unverified recruitment source")
    datetime.strptime(source["date"], "%Y-%m-%d")
    if set(re.findall(r"20\d{2}", source["title"])) != {source["date"][:4]}:
        raise ValueError("Recruitment year mismatch")
    items = _automatic_followups(source, [preferred_notice], checked_at or datetime.now(timezone.utc).isoformat())
    item = items[0]
    n = item["notice"]
    return {"event": {"type": item["event"], "date": n["date"], "title": n["title"], "url": n["url"]},
            "rosters": [{"league": league, "names": names, "source_url": n["url"], "source_sha256": n["sha256"]}
                        for league, names in item["rosters"].items()],
            "preferred_gps": item["names"], "source_url": n["url"]}


def _automatic_followups(source, notices, checked_at):
    """Recognize only plain same-business interim notices, never final winners."""
    compact = lambda value: re.sub(r"\s+", "", value)
    year = source["date"][:4]
    stem = re.sub(r"^20\d{2}년(?:도)?", "", compact(source["title"]))
    stem = stem.split("위탁운용사선정공고", 1)[0]
    if not re.fullmatch(r"(?:우체국금융|우체국예금|우정사업본부)국내블라인드PEF", stem):
        raise ValueError("Unsupported recruitment identity")
    ceiling = datetime.fromisoformat(checked_at.replace("Z", "+00:00")).date()
    results = []
    seen = set()
    for n in notices:
        ident = n.get("source_id", "")
        match = re.fullmatch(r"0041:([1-9][0-9]*)", ident)
        expected = f"{BASE}/board.es?mid=a10510000000&bid=0041&act=view&list_no={match[1]}" if match else None
        if (not match or n.get("url") != expected or n.get("institution_id", "koreapost") != "koreapost"
                or n.get("sha256") != _fingerprint(n)
                or any(n.get(k) for k in ("attachments", "attachment_hashes", "attachment_texts"))):
            raise ValueError("Unverified followup source")
        day = datetime.strptime(n["date"], "%Y-%m-%d").date()
        if n["date"][:4] != year or n["date"] <= source["date"] or day > ceiling:
            raise ValueError("Followup date outside recruitment sequence")
        title = compact(n["title"])
        years = re.findall(r"20\d{2}", n["title"] + " " + n["body"])
        if not years or set(years) != {year}:
            raise ValueError("Followup year unclear")
        title = re.sub(r"^20\d{2}년(?:도)?", "", title)
        body = compact(n["body"])
        if stem not in body or re.search(r"취소|정정|변경|재공고|해외|공동투자|VC|벤처", n["title"] + n["body"], re.I):
            raise ValueError("Different or changed followup business")
        if title == stem + "위탁운용사선정우선협상대상자안내":
            event = "우선협상대상자"
            if ("우선협상대상자" not in body or "최종선정예정" not in body
                    or re.search(r'최종선정(?:완료|결과|확정)|조건부|예비대상', body)):
                raise ValueError("Pre-final status unclear")
            rosters = {}
            for line in n["body"].splitlines():
                m = re.fullmatch(r"\s*[-•ㅇ]?\s*(일반리그|루키리그)\s*[:：]\s*(.+?)\s*", line)
                if not m:
                    if "리그" in line: raise ValueError("Unrecognized league row")
                    continue
                if m[1] in rosters: raise ValueError("Duplicate league")
                value = re.sub(r"\s*\(가나다\s*순\)\s*$", "", m[2])
                names = [name.strip() for name in value.split(",")]
                if not names or any(not re.fullmatch(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9 .&·-]{0,79}", name) for name in names):
                    raise ValueError("Ambiguous manager names")
                rosters[m[1]] = names
            if set(rosters) != {"일반리그", "루키리그"}: raise ValueError("Missing league roster")
            names = rosters["일반리그"] + rosters["루키리그"]
            if len({compact(name).casefold() for name in names}) != len(names): raise ValueError("Duplicate preferred manager")
        else:
            raise ValueError("Unrecognized automatic followup stage")
        if event in seen: raise ValueError("Conflicting followup notices")
        seen.add(event)
        results.append({"notice": n, "event": event, "names": names, "rosters": rosters})
    return sorted(results, key=lambda item: item["notice"]["date"])


def _reviewed_project(notices: list[dict], checked_at: str) -> tuple[list[dict], list[dict]]:
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


def project(notices: list[dict], checked_at: str) -> tuple[list[dict], list[dict]]:
    programs, holds = _reviewed_project(notices, checked_at)
    try:
        from .koreapost_coinvestment_preferred import validate_detail_proof, validate_attachment_proof
    except ImportError:
        from koreapost_coinvestment_preferred import validate_detail_proof, validate_attachment_proof
    for notice in notices:
        if not re.search(r'국내\s*공동\s*투자', notice.get('title', '')):
            continue
        try:
            if 'detail_proof' in notice:
                validate_detail_proof(notice)
            if 'attachment_proofs' in notice:
                validate_attachment_proof(notice)
        except (ValueError, KeyError, TypeError):
            holds.append({'stage':'institution_attachment_text','institution_id':'koreapost',
                          'source_id':notice.get('source_id'),'url':notice.get('url'),
                          'reason':'coinvestment_raw_proof_invalid','error':'coinvestment_raw_proof_invalid'})
    return programs, holds


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
    window_start, window_end = _date_window(checked_at)
    discovered, seen_rows = {}, set()
    listing_pages = []
    for page in range(1, 11):
        url = LIST_URL + "&" + urlencode({"keySDate": window_start, "keyEDate": window_end, "nPage": page})
        raw = fetch(url)
        filter_evidence = _listing_filter_evidence(raw, window_start, window_end)
        links = _listing(raw)
        advertised_last = _listing_last_page(raw, url)
        listing_pages.append({"url": url, "row_count": len(links),
                              "date_filter_validation": filter_evidence,
                              "advertised_last_page": advertised_last,
                              "sha256": hashlib.sha256(raw).hexdigest()})
        if not links:
            if not _explicit_empty_listing(raw):
                raise ValueError("Official Korea Post listing has no recognized notices or explicit empty result")
            pagination_end = "explicit_empty"
            break
        page_ids = {number for number, _ in links}
        if not page_ids - seen_rows:
            raise ValueError("Official Korea Post listing pagination did not advance")
        seen_rows.update(page_ids)
        for number, title in links:
            if _pe_discovery_title(title):
                discovered[number] = title
        if advertised_last is not None and page > advertised_last:
            raise ValueError("Populated Korea Post page exceeds advertised final page")
        if advertised_last == page:
            pagination_end = "advertised_last_page"
            break
        if len(links) < 10 and advertised_last is None:
            pagination_end = "short_page"
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
        raw_detail = fetch(url)
        notice = _detail(number, raw_detail)
        coinvestment = bool(re.search(r'국내\s*공동\s*투자',notice['title']))
        if coinvestment:
            try:
                from .capture_koreapost_preferred import detail_proof, attachment_proof
            except ImportError:
                from capture_koreapost_preferred import detail_proof, attachment_proof
            notice['detail_proof'] = detail_proof(notice,raw_detail)
        if not _pe_discovery_title(notice["title"]):
            if number == "400":
                raise ValueError("Reviewed Korea Post notice no longer matches program")
            continue
        official_date = date.fromisoformat(notice["date"]).isoformat()
        if not window_start <= official_date <= window_end and notice["source_id"] not in reviewed_ids:
            continue
        notice["attachment_hashes"] = {}
        notice["attachment_texts"] = {}
        attachments_to_verify = (notice["attachments"] if notice["source_id"] in reviewed_ids
                                 or _current_program_title(notice["title"]) else
                                 notice["attachments"][:1] if _recruitment_title(notice["title"]) else [])
        for attachment_url in attachments_to_verify:
            raw = fetch(attachment_url)
            if not raw.startswith((b"%PDF", b"PK", bytes.fromhex("d0cf11e0"))):
                raise ValueError("Official Korea Post attachment is invalid")
            notice["attachment_hashes"][attachment_url] = hashlib.sha256(raw).hexdigest()
            if coinvestment and attachment_url == notice['attachments'][0]:
                try:
                    proof = attachment_proof(notice,raw)
                except Exception as error:
                    proof = {'kind':'koreapost_attachment_body_v1','raw_base64':base64.b64encode(raw).decode('ascii'),
                             'sha256':hashlib.sha256(raw).hexdigest(),'byte_length':len(raw),
                             'pdf_reader_version':'6.10.0','read_error':type(error).__name__}
                notice['attachment_proofs'] = {attachment_url:proof}
            if raw.startswith(b"%PDF"):
                try:
                    notice["attachment_texts"][attachment_url] = _pdf_text(raw)
                except Exception as error:
                    if notice["source_id"] in reviewed_ids:
                        raise
                    notice["attachment_read_error"] = type(error).__name__
        notices.append(notice)
    programs, holds = project(notices, checked_at)
    return {"checked_at": checked_at, "notices": notices, "programs": programs,
            "holds": holds, "link_suggestions": _suggestions(notices),
            "discovery_candidates": discovery_candidates(notices),
            "collection_coverage": {"window_start": window_start, "window_end": window_end,
                                    "window_days": 365, "date_basis": "Asia/Seoul",
                                    "listing_pages": listing_pages, "pagination_end": pagination_end,
                                    "date_filter_validation": "echo_confirmed" if all(
                                        p["date_filter_validation"] == "echo_confirmed" for p in listing_pages) else "unknown",
                                    "window_completeness": "not_assessed"}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    seed = next(p for p in json.loads((ROOT / "data/lp_programs_pilot.json").read_text())["programs"]
                if p["id"] == PROGRAM_ID)
    report = collect(seed, datetime.now(timezone.utc).isoformat())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.output)
    print(json.dumps({"notices": len(report["notices"]), "programs": len(report["programs"]),
                      "holds": len(report["holds"]),
                      "discovery_candidates": len(report["discovery_candidates"])}))


if __name__ == "__main__":
    main()
