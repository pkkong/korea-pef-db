"""Repeatable scope and stage assessment of official LP notices.

This catalog does not approve fund terms or GP results for public program pages.
It groups source documents and records which official wording supports PE scope.
"""
from __future__ import annotations

import hashlib
import re


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def notice_stage(title: str) -> str:
    value = compact(title)
    if any(word in value for word in ("정정", "수정", "변경", "연장", "재공고", "취소")):
        return "변경 공고"
    if "우선협상대상자" in value:
        return "우선협상대상자"
    if "faq" in value or "질의응답" in value:
        return "질의응답"
    if any(word in value for word in ("정량평가결과", "서류심사결과", "1차평가결과")):
        return "1차 심사 결과"
    if any(word in value for word in ("접수결과", "접수현황")):
        return "접수 결과"
    if "선정결과" in value or "최종선정" in value:
        return "선정 결과"
    if "공고" in value or "모집" in value:
        return "모집 공고"
    return "단계 확인 필요"


def program_key(notice: dict) -> str:
    """Derive identity from source institution, year and strategy, never ID."""
    institution = notice["institution_id"]
    title = compact(notice["title"])
    year_match = re.search(r"20\d{2}", title)
    year = year_match.group() if year_match else notice["date"][:4]
    if institution == "koreapost":
        if "국내" in title and "공동투자" in title:
            core = "domestic-coinvestment"
        elif "해외사모펀드" in title and "재간접" in title:
            core = "overseas-private-feeder"
        elif "국내" in title and "블라인드pef" in title:
            core = "domestic-blind-pef"
        else:
            core = "other-" + hashlib.sha256(title.encode()).hexdigest()[:12]
        return f"{institution}:{year}:{core}"
    core = title
    quoted = re.search(r"[「『]([^」』]+펀드)[」』]", title)
    if quoted and institution != 'kgrowth':
        core = quoted[1]
    if institution == 'kgrowth':
        core = re.sub(r'^【(?:선정공고|선정결과|접수현황|접수결과|서류심사결과|정량평가결과|'
                      r'우선협상대상자|변경공고|재공고|정정공고|수정공고|취소공고|연장공고)】', '', core)
        core = re.sub(r'\((?:수정|변경|정정|재공고|취소|연장)\)$', '', core)
        # Track and round qualifiers after a quoted fund name distinguish
        # separate offerings. Only remove lifecycle wording, never the track.
        for phrase in ('선정계획변경공고', '선정계획재공고', '선정계획정정공고',
                       '선정계획연장공고', '선정계획취소공고', '선정계획수정공고',
                       '변경공고', '재공고', '정정공고', '수정공고', '연장공고', '취소공고'):
            core = core.replace(phrase, '')
    for phrase in ("한국수출입은행", "위탁운용사", "운용사", "제안서", "선정계획",
                   "출자사업", "계획공고", "접수결과", "접수현황", "서류심사결과",
                   "선정결과", "공고"):
        core = core.replace(phrase, "")
    core = re.sub(r"20\d{2}년도?|[「」『』()\[\]·.,]", "", core)
    return f"{institution}:{year}:" + hashlib.sha256(core.encode()).hexdigest()[:16]


def _scope_from_source(notice: dict) -> tuple[str, str]:
    body = compact(notice.get("body", ""))
    title = compact(notice.get("title", ""))
    attachments = compact(" ".join(notice.get("attachment_texts", {}).values()))
    names = compact(" ".join(a.get("name", "") for a in notice.get("attachments", [])
                             if isinstance(a, dict)))
    # A legal form mentioned in an appendix about manager eligibility is not
    # necessarily an eligible form for this particular solicitation.
    pe_form = vc_form = False
    source_text = attachments + body
    # A multi-line legal-form table includes law citations between its forms.
    # Stop at its footnote, before other fund forms in personnel appendices.
    legal_table = re.search(r"출자대상투자기구(.*?)(?:※|심사결과|운용사신청자격)", source_text)
    if legal_table:
        forms = legal_table[1]
        if "기관전용사모집합투자기구" in forms and any(f in forms for f in ("벤처투자조합", "신기술사업투자조합")):
            return "mixed_legal_forms", "공식 출자대상 표에 PE와 VC 신청 형태가 함께 표시됨"
    for label in re.finditer(r"출자대상|신청가능조합형태|펀드형태|투자기구및선정대상", source_text):
        window = source_text[label.end():label.end() + 100]
        pe = re.search(r"기관전용사모(?:집합투자기구)?", window)
        vc = re.search(r"벤처투자조합|신기술사업투자조합", window)
        if not (pe or vc):
            continue
        # The first legal form after the eligibility heading is decisive;
        # appendix references to other fund forms must not widen eligibility.
        between = (window[pe.end():vc.start()] if pe and vc and pe.start() < vc.start()
                   else window[vc.end():pe.start()] if pe and vc else "")
        if pe and vc and re.fullmatch(r"(?:[,·/]|및|또는|와|과)*", between):
            pe_form = vc_form = True
        elif pe and (not vc or pe.start() < vc.start()):
            pe_form = True
        else:
            vc_form = True
        break
    if "vc부문" in names or ("벤처펀드(vc)" in body and vc_form):
        return "vc_only", "공식 공고가 VC 펀드 형태를 명시"
    if "해외사모펀드" in title and ("pe,pd" in body or "pe·pd" in body):
        return "pe_related_mandate", "공식 공고가 해외 PE·PD 투자관리 위탁을 명시"
    if pe_form and not vc_form:
        return "pe_eligible", "공식 첨부가 기관전용 사모펀드의 신청 가능성을 명시"
    if vc_form and not pe_form:
        return "vc_only", "공식 공고가 벤처투자조합 등의 신청 형태를 명시"
    if pe_form and vc_form:
        return "mixed_legal_forms", "공식 공고에 PE와 VC 신청 형태가 함께 표시됨"
    if "pef" in title:
        return "pe_eligible", "공식 공고 제목이 PEF 사업을 명시"
    return "unknown", "모집 원공고에서 펀드 형태를 확인하지 못함"


def assess_candidates(candidates: list[dict], notices: list[dict]) -> list[dict]:
    """Reassess from retained official documents on every publish run."""
    by_url = {notice["url"]: notice for notice in notices}
    groups: dict[str, list[dict]] = {}
    for candidate in candidates:
        source = by_url.get(candidate["url"])
        if source is None:
            raise ValueError("LP candidate has no retained official source")
        enriched = {**candidate, "program_key": program_key(source),
                    "stage": notice_stage(source["title"])}
        groups.setdefault(enriched["program_key"], []).append(enriched)
    result = []
    for members in groups.values():
        recruitment = next((by_url[m["url"]] for m in sorted(members, key=lambda m: m["date"])
                            if m["stage"] == "모집 공고"), None)
        if recruitment is None:
            # Supporting originals must come from another official bank, and
            # match the same derived institution/year/business key themselves.
            from urllib.parse import urlparse
            related = [n for n in notices if n.get("related_program_key") == members[0]["program_key"]
                       and n.get("institution_id") == "kdb" and urlparse(n["url"]).hostname == "www.kdb.co.kr"
                       and notice_stage(n["title"]) == "모집 공고"
                       and program_key({**n, "institution_id": members[0]["institution_id"]}) == members[0]["program_key"]]
            if len(related) == 1:
                recruitment = related[0]
        anchor = recruitment or by_url[min(members, key=lambda m: m["date"])["url"]]
        scope, reason = _scope_from_source(anchor)
        for member in members:
            result.append({**member, "scope": scope, "scope_reason": reason,
                           "scope_source_url": anchor["url"],
                           "recruitment_url": recruitment["url"] if recruitment else None})
    return sorted(result, key=lambda item: (item["date"], item["source_id"]))
