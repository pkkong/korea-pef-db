"""Collect Korea Eximbank notices and project only hash-reviewed PE programs.

The official board mixes PE, VC and other banks' joint programs. Discovery
therefore never turns a new notice into a public GP result by itself.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

try:
    from .build_lp_commitment_monitor import extract_kexim_notice_rows
except ImportError:
    from build_lp_commitment_monitor import extract_kexim_notice_rows

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "data/kexim_program_reviews.json"
BASE = "https://www.koreaexim.go.kr"
BOARD = BASE + "/HPHKBI039M01"
PAGES = 8


def _clean(markup: str) -> str:
    markup = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", markup, flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", markup))).strip()


def _decode(raw: bytes | str) -> str:
    if isinstance(raw, str):
        return raw
    for encoding in ("utf-8", "cp949", "euc-kr"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError("Official KEXIM page encoding is unreadable")


def parse_detail(source_id: str, raw: bytes | str) -> dict:
    page = _decode(raw)
    title = re.search(r'<h1\b[^>]*class="detail-view-title"[^>]*>(.*?)</h1>', page, re.I | re.S)
    date = re.search(r'<span\b[^>]*title="작성일"[^>]*>(.*?)</span>', page, re.I | re.S)
    body = re.search(r'<div\b[^>]*class="detail-view-box"[^>]*>(.*?)<div\b[^>]*class="detail-view-file"', page, re.I | re.S)
    file_area = re.search(r'<div\b[^>]*class="detail-view-file"[^>]*>(.*?)</div>', page, re.I | re.S)
    if not (title and date and body):
        raise ValueError(f"KEXIM notice {source_id} has no stable detail fields")
    date_value = _clean(date.group(1)).replace(".", "-").strip("-")
    datetime.fromisoformat(date_value)
    attachments = []
    if file_area:
        for link in re.finditer(r'<a\b[^>]*href="([^"]*comm/getFile[^"]*)"[^>]*>(.*?)</a>', file_area.group(1), re.I | re.S):
            attachments.append({"name": _clean(link.group(2)), "url": urljoin(BASE, html.unescape(link.group(1)))})
    record = {"source_id": str(source_id), "url": f"{BOARD}/{source_id}",
              "title": _clean(title.group(1)), "date": date_value,
              "body": _clean(body.group(1)), "attachments": attachments}
    if not record["body"]:
        raise ValueError(f"KEXIM notice {source_id} has an empty body")
    record["sha256"] = fingerprint(record)
    return record


def fingerprint(notice: dict) -> str:
    value = [notice["title"], notice["date"], notice["body"]]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def _recipes() -> list[dict]:
    return json.loads(REGISTRY.read_text()) if REGISTRY.exists() else []


def _title_matches(recipe: dict, title: str) -> bool:
    compact = re.sub(r"\s+", "", title).casefold()
    return any(all(re.sub(r"\s+", "", term).casefold() in compact for term in group)
               for group in recipe["match_groups"])


def _stage(title: str) -> str | None:
    compact = re.sub(r"\s+", "", title)
    if any(word in compact for word in ("정정", "변경", "취소", "연장", "재공고")):
        return "정정·변경"
    if "서류심사결과" in compact:
        return "서류심사 결과"
    if "접수결과" in compact or "접수현황" in compact:
        return "접수 현황"
    if "선정결과" in compact:
        return "최종 선정"
    if "공고" in compact:
        return "모집 공고"
    return None


def _approved_source_ids() -> set[str]:
    return {str(source["source_id"]) for recipe in _recipes() for source in recipe["sources"]}


def link_suggestions(notices: list[dict]) -> list[dict]:
    """New official stages are review candidates, never approved GP updates."""
    approved = _approved_source_ids()
    result = []
    for notice in notices:
        if str(notice["source_id"]) in approved:
            continue
        stage = _stage(notice["title"])
        if stage not in ("접수 현황", "서류심사 결과", "최종 선정", "정정·변경"):
            continue
        matches = [{"id": r["id"], "title": r["title"]} for r in _recipes()
                   if _title_matches(r, notice["title"])]
        if matches:
            result.append({"source_id": str(notice["source_id"]), "date": notice["date"],
                           "title": notice["title"], "url": notice["url"], "stage": stage,
                           "sha256": fingerprint(notice),
                           "attachment_hashes": notice.get("attachment_hashes", {}),
                           "programs": matches})
    return result


def _reviewed_source(recipe: dict, notices: dict[str, dict]) -> list[tuple[dict, dict]]:
    sources = []
    for approved in recipe["sources"]:
        source_id = str(approved["source_id"])
        notice = notices.get(source_id)
        if not notice:
            raise ValueError(f"공식 공고 {source_id} 수집 실패")
        if fingerprint(notice) != approved["sha256"]:
            raise ValueError(f"공식 공고 {source_id} 원문 변경")
        if notice.get("attachment_hashes", {}) != approved["attachment_hashes"]:
            raise ValueError(f"공식 공고 {source_id} 첨부 변경")
        if notice["date"] != approved["date"] or _stage(notice["title"]) != approved["event"]:
            raise ValueError(f"공식 공고 {source_id} 단계 변경")
        sources.append((approved, notice))
    return sources


def _verified_facts(recipe: dict, notices: dict[str, dict]) -> dict:
    facts = {}
    for field, evidence in recipe["facts"].items():
        notice = notices[str(evidence["source_id"])]
        attachment_url = evidence["attachment_url"]
        if attachment_url not in notice.get("attachment_hashes", {}) or not evidence.get("quote"):
            raise ValueError(f"{field} 공식 첨부 근거 없음")
        # HWP and PDF tables were reviewed with rendered originals. The exact
        # quoted fact is anchored to the checked attachment SHA-256 above.
        facts[field] = evidence["value"]
    return facts


def _project_one(recipe: dict, by_id: dict[str, dict], notices: list[dict], checked_at: str) -> dict:
    sources = _reviewed_source(recipe, by_id)
    approved_ids = {str(source["source_id"]) for source in recipe["sources"]}
    for notice in notices:
        if str(notice["source_id"]) not in approved_ids and _title_matches(recipe, notice["title"]):
            if _stage(notice["title"]):
                raise ValueError(f"새 단계 공고 {notice['source_id']} 연결 검토 필요")
    facts = _verified_facts(recipe, by_id)
    p = {"id": recipe["id"], "institution_id": "kexim", "institution_name": "한국수출입은행",
         "title": recipe["title"], "display_title": recipe["title"], "asset_scope": "PE",
         "status": "모집 공고", "events": [], "schedule_stages": [], "selected_gps": [],
         "shortlisted_gps": [], "gp_tracks": {}, "checked_at": checked_at, **facts}
    order = {"모집 공고": "announcement", "접수 현황": "application",
             "서류심사 결과": "screening", "최종 선정": "selection"}
    labels = {"모집 공고": "모집 공고", "접수 현황": "접수 결과",
              "서류심사 결과": "서류심사 결과", "최종 선정": "선정 결과 발표"}
    for approved, notice in sorted(sources, key=lambda pair: pair[1]["date"]):
        event = approved["event"]
        p["events"].append({"date": notice["date"], "type": event,
                            "title": notice["title"], "url": notice["url"]})
        stage = {"stage": order[event], "label": labels[event], "original_label": event,
                 "date": notice["date"], "precision": "date", "status": "confirmed",
                 "source_url": notice["url"], "show_source": True}
        if approved.get("team_count"):
            stage["detail"] = f"{approved['team_count']}개 팀"
        p["schedule_stages"].append(stage)
    recruitment = next(notice for approved, notice in sources if approved["event"] == "모집 공고")
    if p.get("deadline"):
        p["schedule_stages"].append({"stage": "application", "label": "접수 마감",
                                    "original_label": "접수 마감", "date": p["deadline"],
                                    "precision": "datetime", "status": "announced_deadline",
                                    "source_url": recruitment["url"], "show_source": True})
    for planned in recipe.get("planned_stages", []):
        p["schedule_stages"].append({**planned, "status": "planned",
                                    "source_url": recruitment["url"], "show_source": True})
    p["schedule_stages"].sort(key=lambda item: (str(item.get("date") or "9999")[:10],
                                                 item.get("status") != "announced_deadline"))
    lists = recipe.get("manager_lists", {})
    applicants = lists.get("applicants", {})
    shortlist = lists.get("shortlist", {})
    selected = lists.get("selected", {})
    stage_lists = {"applicants": ("접수 현황", applicants),
                   "shortlist": ("서류심사 결과", shortlist),
                   "selected": ("최종 선정", selected)}
    for stage_key, (event, teams) in stage_lists.items():
        if not teams:
            continue
        approved = next((a for a, _ in sources if a["event"] == event), None)
        evidence = recipe.get("manager_evidence", {}).get(stage_key, {})
        if not approved or sum(map(len, teams.values())) != approved.get("team_count"):
            raise ValueError(f"{stage_key} GP 수가 공식 단계와 다름")
        if (evidence.get("source_id") != approved["source_id"] or
                evidence.get("attachment_url") not in approved["attachment_hashes"] or
                not evidence.get("quote")):
            raise ValueError(f"{stage_key} GP 명단 근거 없음")
    aliases = recipe.get("name_aliases", {})
    normalize = lambda name: aliases.get(name, name)
    for track, names in shortlist.items():
        if applicants and not {normalize(n) for n in names} <= {normalize(n) for n in applicants[track]}:
            raise ValueError(f"{track} 서류통과 GP가 접수 GP에 없음")
    for track, names in selected.items():
        earlier = shortlist or applicants
        if earlier and not {normalize(n) for n in names} <= {normalize(n) for n in earlier[track]}:
            raise ValueError(f"{track} 선정 GP가 이전 단계에 없음")
    p["applicants_gps"] = [n for names in applicants.values() for n in names]
    p["shortlisted_gps"] = [n for names in shortlist.values() for n in names]
    if p["applicants_gps"]:
        app_source = next(n for a,n in sources if a["event"] == "접수 현황")
        p["manager_list_sources"] = {"applicants_gps": app_source["url"]}
        p["status"] = "접수 마감"
    for stage_teams in (applicants, shortlist, selected):
        for track, names in stage_teams.items():
            for name in names:
                p["gp_tracks"][name] = track
    if selected:
        final_approved, final_source = next((a,n) for a,n in sources if a["event"] == "최종 선정")
        allocation = recipe.get("allocation_evidence", {})
        per_gp = allocation.get("per_gp_krw", {})
        if (allocation.get("source_id") != final_approved["source_id"] or
                allocation.get("attachment_url") not in final_approved["attachment_hashes"] or
                not allocation.get("quote") or set(per_gp) != set(selected)):
            raise ValueError("GP별 출자 예정액의 공식 선정 근거 없음")
        if sum(len(names) * per_gp[track] for track, names in selected.items()) != p.get("commitment_amount_krw"):
            raise ValueError("GP별 출자 예정액 합계 불일치")
        for track, names in selected.items():
            for name in names:
                p["selected_gps"].append({"id": "kexim-" + hashlib.sha256(name.encode()).hexdigest()[:16],
                                          "name": name, "source_url": final_source["url"],
                                          "asset_scope": track,
                                          "commitment_amount_krw": per_gp[track]})
        # Both 2026 final-result PDFs explicitly defer formal confirmation to
        # an approval/body decision; the page must not say that approval occurred.
        p["status"] = "선정 결과 발표"
        p["selection_note"] = p.get("linkage_note", "")
    p["review_evidence"] = recipe["facts"]
    return p


def project(notices: list[dict], checked_at: str) -> tuple[list[dict], list[dict]]:
    by_id = {str(notice["source_id"]): notice for notice in notices}
    programs, holds = [], []
    for recipe in _recipes():
        try:
            programs.append(_project_one(recipe, by_id, notices, checked_at))
        except (ValueError, KeyError, StopIteration) as error:
            holds.append({"program_id": recipe["id"], "reason": str(error)})
    return programs, holds


def _official_fetch(url: str) -> bytes:
    if not url.startswith(BASE + "/"):
        raise ValueError("Unexpected KEXIM URL")
    req = Request(url, headers={"User-Agent": "Mozilla/5.0",
                                "Referer": BOARD,
                                "Accept": "text/html,application/pdf,application/octet-stream,*/*"})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=25) as response:
                if not response.geturl().startswith(BASE + "/"):
                    raise ValueError("KEXIM redirected outside official domain")
                return response.read()
        except (URLError, HTTPError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def collect(checked_at: str, fetch=None) -> dict:
    """Discover board pages, fetch first evidence attachment, then re-project."""
    datetime.fromisoformat(checked_at)
    fetch = fetch or _official_fetch
    discovered = set()
    for page_no in range(1, PAGES + 1):
        page_url = f"{BOARD}?curPage={page_no}"
        page = _decode(fetch(page_url))
        for row in extract_kexim_notice_rows(page, page_url, ["펀드"]):
            if row["announced_date"] >= "2026-01-01":
                match = re.search(r"/HPHKBI039M01/(\d+)", row["link"])
                if match:
                    discovered.add(match.group(1))
    if not discovered:
        raise ValueError("KEXIM official board yielded no 2026 fund notices")
    discovered.update(_approved_source_ids())
    notices = []
    for source_id in sorted(discovered, key=int):
        notice = parse_detail(source_id, fetch(f"{BOARD}/{source_id}"))
        notice["checked_at"] = checked_at
        notice["attachment_hashes"] = {}
        if notice["attachments"]:
            attachment = notice["attachments"][0]
            raw = fetch(attachment["url"])
            if not raw.startswith((b"%PDF", b"PK", bytes.fromhex("d0cf11e0"))):
                raise ValueError(f"KEXIM attachment {source_id} has unexpected format")
            notice["attachment_hashes"][attachment["url"]] = hashlib.sha256(raw).hexdigest()
        notices.append(notice)
    programs, holds = project(notices, checked_at)
    return {"checked_at": checked_at, "notices": notices, "programs": programs,
            "holds": holds, "link_suggestions": link_suggestions(notices)}
