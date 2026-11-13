"""Collect Korea Eximbank notices and project only hash-reviewed PE programs.

The official board mixes PE, VC and other banks' joint programs. Discovery
therefore never turns a new notice into a public GP result by itself.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import platform
import re
import ssl
import subprocess
import tempfile
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from http.cookies import SimpleCookie
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

try:
    from .lp_kexim_listing import extract_kexim_notice_rows
    from .lp_kdb_dns import resolve_kexim_ipv4
    from .lp_ipv4_transport import IPv4HTTPSHandler
    from .lp_transport_errors import transient_dns
    from .lp_attachment_text import extract_attachment, MAX_FILE_BYTES
except ImportError:
    from lp_kexim_listing import extract_kexim_notice_rows
    from lp_kdb_dns import resolve_kexim_ipv4
    from lp_ipv4_transport import IPv4HTTPSHandler
    from lp_transport_errors import transient_dns
    from lp_attachment_text import extract_attachment, MAX_FILE_BYTES

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "data/kexim_program_reviews.json"
BASE = "https://www.koreaexim.go.kr"
BOARD = BASE + "/HPHKBI039M01"
PAGES = 8
CA_CHAIN = ROOT / "services/lp/certs/kexim_ca_chain.pem"
ATTACHMENT_PROOF_KIND = "kexim_attachment_body_v1"
PDF_READER_VERSION = "6.10.0"


def _attachment_identity(notice: dict, url: str) -> dict:
    """Bind proof to the first attachment actually supplied by this notice."""
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("KEXIM attachment URL contains whitespace/control characters")
    source_id = notice.get("source_id")
    if (not isinstance(source_id, str) or not re.fullmatch(r"[1-9][0-9]*", source_id)
            or notice.get("url") != f"{BOARD}/{source_id}"
            or notice.get("sha256") != fingerprint(notice)):
        raise ValueError("KEXIM attachment notice identity mismatch")
    attachments = notice.get("attachments")
    if (not isinstance(attachments, list) or not attachments or not isinstance(attachments[0], dict)
            or attachments[0].get("url") != url or not isinstance(attachments[0].get("name"), str)):
        raise ValueError("KEXIM proof is not the original first attachment")
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
    if (parsed.scheme != "https" or parsed.netloc != "www.koreaexim.go.kr"
            or parsed.path != "/comm/getFile" or parsed.fragment
            or set(query) - {"upperNo", "fileNo", "srvcId", "fileTy"}
            or any(len(values) != 1 for values in query.values())
            or ("srvcId" in query and query["srvcId"] != ["BBSTY1"])
            or ("fileTy" in query and query["fileTy"] != ["ATTACH"])
            or query.get("upperNo") != [source_id]
            or len(query.get("fileNo", [])) != 1 or not re.fullmatch(r"[0-9]+", query["fileNo"][0])):
        raise ValueError("KEXIM attachment URL/source mismatch")
    checked_at = notice.get("checked_at")
    if (not isinstance(checked_at, str)
            or datetime.fromisoformat(checked_at.replace("Z", "+00:00")).tzinfo is None):
        raise ValueError("KEXIM attachment proof requires observation timestamp")
    return {"source_id": source_id, "notice_url": notice["url"], "notice_sha256": notice["sha256"],
            "attachment_url": url, "attachment_name": attachments[0]["name"], "checked_at": checked_at}


def _canonical_attachment(raw: bytes) -> dict:
    """Canonical complete-body decoding; separate from platform PDF previews."""
    format_hint = ("pdf" if raw.startswith(b"%PDF") else "hwp" if raw.startswith(bytes.fromhex("d0cf11e0a1b11ae1"))
                   else "zip" if raw.startswith(b"PK") else "unknown")
    version = None
    try:
        if format_hint == "pdf":
            import pypdf
            version = pypdf.__version__
            if version != PDF_READER_VERSION:
                return {"format": format_hint, "pdf_reader_version": version, "extracted": None,
                        "error_code": "pdf_reader_version_mismatch"}
        result = extract_attachment(raw)
        if result["format"] not in ("hwp", "hwpx", "pdf"):
            return {"format": format_hint, "pdf_reader_version": version, "extracted": None,
                    "error_code": "unsupported_attachment_format"}
        return {"format": result["format"], "pdf_reader_version": version,
                "extracted": result, "error_code": None}
    except Exception as error:
        # Preserve a replayable failure without source text, cookies, or decoder
        # exception messages in an operational error field. Never use PrvText.
        protected = any(word in str(error).lower() for word in ("encrypted", "drm", "distribution"))
        return {"format": format_hint, "pdf_reader_version": version, "extracted": None,
                "error_code": "protected_attachment" if protected else "attachment_body_unreadable"}


def retain_attachment_proof(notice: dict, raw: bytes) -> dict:
    """Retain one already-fetched unreviewed file; perform no HTTP or approval."""
    if not isinstance(raw, bytes) or len(raw) > MAX_FILE_BYTES:
        raise ValueError("KEXIM attachment exceeds raw evidence size limit")
    url = notice["attachments"][0]["url"]
    identity = _attachment_identity(notice, url)
    digest = hashlib.sha256(raw).hexdigest()
    if notice.get("attachment_hashes", {}).get(url) != digest:
        raise ValueError("KEXIM attachment hash mismatch")
    proof = {"kind": ATTACHMENT_PROOF_KIND, **identity, "sha256": digest,
             "byte_length": len(raw), "raw_base64": base64.b64encode(raw).decode("ascii"),
             **_canonical_attachment(raw)}
    notice["attachment_proofs"] = {url: proof}
    if proof["error_code"]:
        notice["attachment_read_error"] = proof["error_code"]
    elif proof["format"] != "pdf":
        notice["attachment_texts"][url] = proof["extracted"]["text"]
    return proof


def validate_attachment_proof(notice: dict, url: str | None = None) -> dict | None:
    """Replay retained bytes independently; hash-only legacy records are rejected.

    Returns the canonical complete-body extraction, or None for a faithfully
    replayed failed decoding. PDF attachment_texts remains the legacy layout/OCR
    view and is deliberately not treated as canonical extraction evidence.
    """
    proofs = notice.get("attachment_proofs")
    if not isinstance(proofs, dict) or len(proofs) != 1:
        raise ValueError("KEXIM raw attachment proof missing or ambiguous")
    url = url or next(iter(proofs))
    identity = _attachment_identity(notice, url)
    proof = proofs.get(url)
    expected = {"kind", *identity, "sha256", "byte_length", "raw_base64", "format",
                "pdf_reader_version", "extracted", "error_code"}
    if (not isinstance(proof, dict) or set(proof) != expected or proof.get("kind") != ATTACHMENT_PROOF_KIND
            or any(proof.get(k) != v for k, v in identity.items())):
        raise ValueError("KEXIM attachment proof identity/fields mismatch")
    encoded = proof["raw_base64"]
    if not isinstance(encoded, str) or len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4:
        raise ValueError("KEXIM attachment proof exceeds size limit")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("KEXIM attachment proof has invalid raw encoding") from error
    digest = hashlib.sha256(raw).hexdigest()
    if (len(raw) > MAX_FILE_BYTES or type(proof["byte_length"]) is not int or len(raw) != proof["byte_length"]
            or base64.b64encode(raw).decode("ascii") != encoded or digest != proof["sha256"]
            or notice.get("attachment_hashes", {}).get(url) != digest):
        raise ValueError("KEXIM attachment raw/hash/size mismatch")
    decoded = _canonical_attachment(raw)
    if any(proof[k] != value for k, value in decoded.items()):
        raise ValueError("KEXIM attachment decoded body mismatch")
    if decoded["error_code"]:
        if notice.get("attachment_read_error") != decoded["error_code"]:
            raise ValueError("KEXIM attachment failure marker mismatch")
    elif (decoded["format"] != "pdf"
            and notice.get("attachment_texts", {}).get(url) != decoded["extracted"]["text"]):
        raise ValueError("KEXIM attachment text mismatch")
    return decoded["extracted"]


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


class _BodyWithoutAttachments(HTMLParser):
    """Read the actual body element, excluding adjacent notices and navigation."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.depth = 0
        self.parts = []
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'div' and 'detail-view-box' in dict(attrs).get('class', '').split():
            self.count += 1
            self.depth = 1
        elif self.depth:
            if tag == 'div':
                self.depth += 1
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.depth:
            if tag == 'div':
                self.depth -= 1
            if self.depth:
                self.parts.append('</' + tag + '>')

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)

    def handle_entityref(self, name):
        self.handle_data('&' + name + ';')

    def handle_charref(self, name):
        self.handle_data('&#' + name + ';')


def parse_detail(source_id: str, raw: bytes | str) -> dict:
    page = _decode(raw)
    title = re.search(r'<h1\b[^>]*class="detail-view-title"[^>]*>(.*?)</h1>', page, re.I | re.S)
    date = re.search(r'<span\b[^>]*title="작성일"[^>]*>(.*?)</span>', page, re.I | re.S)
    body = re.search(r'<div\b[^>]*class="detail-view-box"[^>]*>(.*?)<div\b[^>]*class="detail-view-file"', page, re.I | re.S)
    file_area = re.search(r'<div\b[^>]*class="detail-view-file"[^>]*>(.*?)</div>', page, re.I | re.S)
    body_markup = body.group(1) if body else None
    if body_markup is None and not file_area:
        parser = _BodyWithoutAttachments()
        parser.feed(page)
        if parser.count == 1 and parser.depth == 0:
            body_markup = ''.join(parser.parts)
    if not (title and date and body_markup):
        raise ValueError(f"KEXIM notice {source_id} has no stable detail fields")
    date_value = _clean(date.group(1)).replace(".", "-").strip("-")
    datetime.fromisoformat(date_value)
    attachments = []
    if file_area:
        for link in re.finditer(r'<a\b[^>]*href="([^"]*comm/getFile[^"]*)"[^>]*>(.*?)</a>', file_area.group(1), re.I | re.S):
            attachments.append({"name": _clean(link.group(2)), "url": urljoin(BASE, html.unescape(link.group(1)))})
    record = {"source_id": str(source_id), "url": f"{BOARD}/{source_id}",
              "title": _clean(title.group(1)), "date": date_value,
              "body": _clean(body_markup), "attachments": attachments}
    if not record["body"]:
        raise ValueError(f"KEXIM notice {source_id} has an empty body")
    record["sha256"] = fingerprint(record)
    return record


def retain_detail_proof(notice: dict, raw: bytes) -> None:
    """Retain actual detail bytes for automatic followup identity replay."""
    if not isinstance(raw, bytes) or not raw or len(raw) > 12 * 1024 * 1024:
        raise ValueError("Invalid KEXIM detail proof size")
    parsed = parse_detail(str(notice["source_id"]), raw)
    if any(notice.get(key) != value for key, value in parsed.items()):
        raise ValueError("KEXIM detail bytes differ from parsed notice")
    notice["detail_proof"] = {"kind": "kexim_detail_body_v1",
                              "raw_base64": base64.b64encode(raw).decode("ascii"),
                              "sha256": hashlib.sha256(raw).hexdigest(),
                              "byte_length": len(raw)}


def fingerprint(notice: dict) -> str:
    value = [notice["title"], notice["date"], notice["body"]]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def _pdf_text(raw: bytes) -> str:
    from pypdf import PdfReader
    pages = PdfReader(io.BytesIO(raw)).pages
    first_page = (pages[0].extract_text() or "") if pages else ""
    text = "\n".join(page.extract_text(extraction_mode="layout") or page.extract_text() or "" for page in pages)
    if len(first_page.strip()) < 100 and platform.system() == "Darwin":
        # Some official PDFs show Korean text visually but omit it from the
        # extractable layer. macOS Vision reads the first page without a cloud
        # OCR service; a failure leaves the scope unknown rather than guessed.
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf") as source:
                source.write(raw)
                source.flush()
                result = subprocess.run(
                    ["swift", str(ROOT / "services/lp/scripts/ocr_pdf_first_page.swift"), source.name],
                    capture_output=True, text=True, timeout=45, check=True)
                text = result.stdout + " " + text
        except (OSError, subprocess.SubprocessError):
            pass
    return text


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


def _automatically_linked_source_ids(notices: list[dict]) -> set[str]:
    """An accepted raw-proven phase is no longer an unresolved suggestion."""
    try:
        from .kexim_followup import augment_recipe
    except ImportError:
        from kexim_followup import augment_recipe
    checked_at = max((str(n.get("checked_at", "")) for n in notices), default="")
    linked = set()
    for recipe in _recipes():
        try:
            augmented = augment_recipe(recipe, notices, checked_at)
        except (ValueError, KeyError, StopIteration, TypeError):
            continue
        old = {str(s["source_id"]) for s in recipe["sources"]}
        linked.update(str(s["source_id"]) for s in augmented["sources"] if str(s["source_id"]) not in old)
    return linked


def link_suggestions(notices: list[dict]) -> list[dict]:
    """New official stages are review candidates, never approved GP updates."""
    approved = _approved_source_ids() | _automatically_linked_source_ids(notices)
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


def discovery_candidates(notices: list[dict]) -> list[dict]:
    """Unmatched fund notices need PE-scope review before becoming programs."""
    approved = _approved_source_ids() | _automatically_linked_source_ids(notices)
    linked = {item["source_id"] for item in link_suggestions(notices)}
    return [{"institution_id": "kexim", "source_id": str(n["source_id"]),
             "title": n["title"], "date": n["date"], "url": n["url"]}
            for n in notices if str(n["source_id"]) not in approved
            and str(n["source_id"]) not in linked]


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
    try:
        from .kexim_followup import augment_recipe
    except ImportError:
        from kexim_followup import augment_recipe
    recipe = augment_recipe(recipe, notices, checked_at)
    sources = _reviewed_source(recipe, by_id)
    approved_ids = {str(source["source_id"]) for source in recipe["sources"]}
    for notice in notices:
        if str(notice.get("source_id", "")) not in approved_ids and _title_matches(recipe, notice["title"]):
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
    if shortlist:
        screening_source = next(n for a, n in sources if a["event"] == "서류심사 결과")
        p.setdefault("manager_list_sources", {})["shortlisted_gps"] = screening_source["url"]
        p["status"] = "서류심사 결과"
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
    by_id = {str(notice.get("source_id", "")): notice for notice in notices}
    programs, holds = [], []
    for recipe in _recipes():
        try:
            programs.append(_project_one(recipe, by_id, notices, checked_at))
        except (ValueError, KeyError, StopIteration) as error:
            holds.append({"program_id": recipe["id"], "reason": str(error)})
    # Derive these signals from retained proof on every projection. Priority
    # artifact loading re-projects rather than trusting collector-supplied holds.
    # A new attachment failure must not erase unrelated reviewed programs.
    approved = _approved_source_ids()
    for notice in notices:
        if str(notice.get("source_id")) in approved or "attachment_proofs" not in notice:
            continue
        error_code = None
        try:
            if validate_attachment_proof(notice) is None:
                error_code = next(iter(notice["attachment_proofs"].values()))["error_code"]
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            error_code = "attachment_proof_invalid"
        if error_code:
            attachments = notice.get("attachments")
            first = attachments[0] if isinstance(attachments, list) and attachments else {}
            holds.append({"stage": "institution_attachment_text", "institution_id": "kexim",
                          "source_id": str(notice.get("source_id", "")), "url": notice.get("url"),
                          "attachment_url": first.get("url") if isinstance(first, dict) else None,
                          "reason": error_code, "error": error_code})
    return programs, holds


class _ManualRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _official_fetch(url: str, cookies: dict[str, str] | None = None) -> bytes:
    if not url.startswith(BASE + "/"):
        raise ValueError("Unexpected KEXIM URL")
    # The official endpoint's chain verifies against this pinned DigiCert G2
    # root and Thawte intermediate.  Keep hostname and TLS verification on.
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(CA_CHAIN))
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), _ManualRedirect())
    recovery_opener = None
    cookies = cookies if cookies is not None else {}
    current = url
    referer = BOARD
    for redirect in range(8):
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                   "Referer": referer,
                   "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
                   "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6"}
        if cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
        req = Request(current, headers=headers)
        response = None
        redirect_error = None
        for attempt in range(3):
            try:
                response = (recovery_opener or opener).open(req, timeout=25)
                break
            except HTTPError as exc:
                if exc.code not in (301, 302, 303, 307, 308):
                    raise
                redirect_error = exc
                break
            except (URLError, TimeoutError, ConnectionError) as exc:
                dns_failure = transient_dns(exc)
                # Unwrap only typed transport errors; text is never a retry signal.
                reason = exc
                seen = set()
                while isinstance(reason, URLError) and id(reason) not in seen:
                    seen.add(id(reason))
                    reason = reason.reason
                connection_failure = isinstance(reason, (TimeoutError, ConnectionError))
                # Certificate, HTTP and content failures must never select DNS recovery.
                if attempt == 2 or not (dns_failure or connection_failure):
                    raise
                if dns_failure and recovery_opener is None:
                    recovery_opener = build_opener(ProxyHandler({}),
                        IPv4HTTPSHandler(context=context, fallback_resolver=resolve_kexim_ipv4), _ManualRedirect())
                time.sleep(attempt + 1)
        if response is not None:
            with response:
                if not response.geturl().startswith(BASE + "/"):
                    raise ValueError("KEXIM redirected outside official domain")
                raw = response.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES:
                    raise ValueError("KEXIM response exceeds raw evidence size limit")
                return raw
        if redirect_error is None:
            raise ValueError("Official KEXIM response missing")
        stored = SimpleCookie()
        for value in redirect_error.headers.get_all("Set-Cookie", []):
            stored.load(value)
        for key, morsel in stored.items():
            cookies[key] = morsel.value
        location = redirect_error.headers.get("Location")
        if not location:
            raise ValueError("KEXIM cookie redirect has no location")
        referer, current = current, urljoin(current, location)
        if not current.startswith(BASE + "/"):
            raise ValueError("KEXIM redirected outside official domain")
    raise ValueError(f"Too many KEXIM cookie redirects: {url}")


def collect(checked_at: str, fetch=None) -> dict:
    """Discover board pages, fetch first evidence attachment, then re-project."""
    checked = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    if checked.tzinfo is None:
        raise ValueError('KEXIM collection timestamp requires timezone')
    window_end = checked.astimezone(ZoneInfo('Asia/Seoul')).date()
    window_start = window_end - timedelta(days=364)
    if fetch is None:
        cookies = {}
        fetch = lambda url: _official_fetch(url, cookies)
    discovered = set()
    for page_no in range(1, PAGES + 1):
        page_url = f"{BOARD}?curPage={page_no}"
        page = _decode(fetch(page_url))
        for row in extract_kexim_notice_rows(page, page_url, ["펀드"]):
            if window_start.isoformat() <= row["announced_date"] <= window_end.isoformat():
                match = re.search(r"/HPHKBI039M01/(\d+)", row["link"])
                if match:
                    discovered.add(match.group(1))
    if not discovered:
        raise ValueError("KEXIM official board yielded no fund notices in rolling-year window")
    discovered.update(_approved_source_ids())
    notices = []
    for source_id in sorted(discovered, key=int):
        raw_detail = fetch(f"{BOARD}/{source_id}")
        notice = parse_detail(source_id, raw_detail)
        if source_id not in _approved_source_ids():
            retain_detail_proof(notice, raw_detail)
        notice["checked_at"] = checked_at
        notice["attachment_hashes"] = {}
        notice["attachment_texts"] = {}
        if notice["attachments"]:
            attachment = notice["attachments"][0]
            approved = source_id in _approved_source_ids()
            if not approved:
                _attachment_identity(notice, attachment["url"])
            raw = fetch(attachment["url"])
            if not isinstance(raw, bytes) or len(raw) > MAX_FILE_BYTES:
                raise ValueError("KEXIM attachment exceeds raw evidence size limit")
            if approved and not raw.startswith((b"%PDF", b"PK", bytes.fromhex("d0cf11e0"))):
                raise ValueError(f"KEXIM attachment {source_id} has unexpected format")
            notice["attachment_hashes"][attachment["url"]] = hashlib.sha256(raw).hexdigest()
            if not approved:
                retain_attachment_proof(notice, raw)
            if raw.startswith(b"%PDF") and not approved:
                # Unreviewed notices need the legal fund form from the official
                # plan, not a guess from the headline or an attachment name.
                # Preserve this legacy layout/OCR view even when the separate
                # canonical proof failed; it cannot clear that failure marker.
                try:
                    notice["attachment_texts"][attachment["url"]] = _pdf_text(raw)
                except Exception as error:
                    notice.setdefault("attachment_read_error", type(error).__name__)
        notices.append(notice)
    programs, holds = project(notices, checked_at)
    try:
        from .collect_kdb_related import collect_related
    except ImportError:
        from collect_kdb_related import collect_related
    candidates = discovery_candidates(notices)
    supporting, supporting_holds = collect_related(candidates, [{**n, "institution_id": "kexim"} for n in notices], checked_at)
    return {"checked_at": checked_at, "notices": notices, "programs": programs,
            "holds": holds, "link_suggestions": link_suggestions(notices),
            "discovery_candidates": candidates, "supporting_notices": supporting, "supporting_holds": supporting_holds}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = collect(datetime.now(timezone.utc).isoformat())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.output)
    print(json.dumps({"notices": len(report["notices"]), "programs": len(report["programs"]),
                      "holds": len(report["holds"])}))


if __name__ == "__main__":
    main()
