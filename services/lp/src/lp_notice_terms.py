"""Derive publishable single-track PE programs from official source text.

Rules describe label/value and table formats, never individual notice IDs.
Ambiguous, amended, multi-track or incomplete sources remain candidates.
Every extracted field keeps its source quote and document fingerprint.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

try:
    from .lp_notice_triage import assess_candidates, compact
except ImportError:
    from lp_notice_triage import assess_candidates, compact

INSTITUTIONS = {
    "koreapost": ("우정사업본부", "www.kpasset.go.kr"),
    "kexim": ("한국수출입은행", "www.koreaexim.go.kr"),
    "ktcu": ("한국교직원공제회", "www.ktcu.or.kr"),
    "kgrowth": ("한국성장금융", "www.kgrowth.or.kr"),
}
NUMBER = r"\d+(?:,\d{3})*"


def _one(values, field):
    unique = {str(value): value for value in values}
    if len(unique) != 1:
        raise ValueError(f"{field}: 원문 값 누락 또는 불일치")
    return next(iter(unique.values()))


def _readable(value):
    """Repair a few common PDF spacing losses without inventing a summary."""
    value = re.sub(r"주\d+\)", "", value).strip()
    for raw, spaced in (
        ("조건을충족하는", "조건을 충족하는 "), ("제약·바이오분야", "제약·바이오 분야 "),
        ("임상3상추진", "임상3상 추진"),
        ("추진중인기업", "추진 중인 기업"), ("약정총액의", " 약정총액의 "),
        ("펀드약정액의", " 펀드 약정액의 "), ("이상투자", " 이상 투자"),
    ):
        value = value.replace(raw, spaced)
    return re.sub(r"\s+", " ", value).strip()


def extract_terms(notice):
    institution = notice["institution_id"]
    if institution == "kgrowth":
        try:
            from .kgrowth_notice_terms import extract_offering
        except ImportError:
            from kgrowth_notice_terms import extract_offering
        return extract_offering(notice)
    name, host = INSTITUTIONS[institution]
    if urlparse(notice["url"]).scheme != "https" or urlparse(notice["url"]).hostname != host:
        raise ValueError("공식 기관 주소가 아님")
    if not notice.get("sha256"):
        raise ValueError("공고 본문 지문 없음")
    # The body is authoritative; attachments are usable only with retained bytes.
    sources = [(notice["url"], notice.get("body", ""), notice.get("sha256"))]
    for url, text in notice.get("attachment_texts", {}).items():
        digest = notice.get("attachment_hashes", {}).get(url)
        if not digest or urlparse(url).hostname != host:
            raise ValueError("첨부 텍스트의 공식 원문 근거 없음")
        sources.append((url, text, digest))
    facts = defaultdict(list)
    evidence = defaultdict(list)

    def remember(field, value, url, digest, quote):
        facts[field].append(value)
        evidence[field].append({"source_url": url, "sha256": digest, "quote": quote})

    for url, raw, digest in sources:
        text = compact(raw)
        # Limit simple amounts to a labeled total, never fund size or GP capital.
        for m in re.finditer(r"(?:투자규모|출자규모)[:：·\-()]*총(" + NUMBER + r")억원(이내)?", text):
            remember("base_amount", int(m[1].replace(",", "")) * 100_000_000, url, digest, m[0])
            remember("amount_limit", bool(m[2]), url, digest, m[0])
        for m in re.finditer(r"선정운용사수[:：()\-]*총?(\d+)개(?:운용사|사)", text):
            remember("manager_count", int(m[1]), url, digest, m[0])
        for m in re.finditer(r"(?:제안서접수마감일|접수마감시한|접수마감일시)[:：·\-]*"
                             r"(20\d{2})[.년](\d{1,2})[.월](\d{1,2})[.일]?"
                             r"(?:\([월화수목금토일]\))?[,·]?(\d{1,2})(?:시|:)(\d{2})?", text):
            stamp = datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5] or 0))
            remember("deadline", stamp.isoformat() + "+09:00", url, digest, m[0])
        # Numbered body sections preserve spacing and provide bounded strategy text.
        for m in re.finditer(r"(?:^|\n)\s*\d+[.)]\s*(?:투자전략|주목적)\s*[:：]\s*([^\n]+)", raw):
            remember("purpose", re.sub(r"\s+", " ", m[1]).strip(), url, digest, m[0])
        # A single-row mother-fund plan. Require the table headings, units and
        # explicit spacing between every number; concatenated PDF numbers fail.
        table = re.search(r"출자분야별출자계획(.*?)(?:-\s*3\s*-|3\.출자분야및투자대상)", raw, re.S)
        if table:
            section = table[1]
            headings = compact(section)
            if all(word in headings for word in ("단위:억원", "출자예산", "결성", "목표액", "조합수", "자조합", "출자액")):
                rows = list(re.finditer(r"(?<![\d,])(" + NUMBER + r")\s+(" + NUMBER + r")\s+(\d+)개\s+(" + NUMBER + r")\s+[․·]?\s*기관전용", section))
                row = _one([m.groups() for m in rows], "단일 출자분야 표")
                budget, target, count, per_fund = [int(v.replace(",", "")) for v in row]
                if budget != count * per_fund or count != 1:
                    raise ValueError("다중 분야 또는 표 금액 합계 불일치")
                remember("base_amount", budget * 100_000_000, url, digest, rows[0][0])
                remember("fund_target", target * 100_000_000, url, digest, rows[0][0])
                remember("manager_count", count, url, digest, rows[0][0])
        # A co-investor matrix: header order binds each value to an LP. Require
        # an explicit total column and reconcile it with the row and plan text.
        joint = re.search(r"공동출자자\s*출자\s*예정\s*금액.*?구분(.*?)출자금액\s*"
                          r"((?:" + NUMBER + r"\s+){2,}" + NUMBER + r")", raw, re.S)
        if joint:
            header = compact(joint[1])
            names = re.findall(r"한국수출입은행|중소기업은행|한국산업은행", header)
            if header != "".join(names) + "공동출자합계" or len(names) != len(set(names)):
                raise ValueError("공동출자 기관별 금액 열 미확인")
            numbers = [int(v.replace(",", "")) for v in joint[2].split()]
            if len(numbers) != len(names) + 1 or sum(numbers[:-1]) != numbers[-1] or name not in names:
                raise ValueError("공동출자 기관별 금액 합계 불일치")
            announced = re.findall(r"공동출자자.{0,10}총(" + NUMBER + r")억원", text)
            if _one([int(v.replace(",", "")) for v in announced], "공동출자 총액") != numbers[-1]:
                raise ValueError("공동출자 본문과 표 불일치")
            allocation = dict(zip(names, [n * 100_000_000 for n in numbers[:-1]]))
            remember("joint_allocations", allocation, url, digest, joint[0])
        purpose = re.search(r"주목적투자대상(.*?)(?:-\s*4\s*-|4\.주요출자조건)", text, re.S)
        if purpose and not facts["purpose"]:
            sentence = re.search(r"조건을충족하는(.*?)에약정총액의(\d+)%이상투자", purpose[1])
            if sentence:
                value = _readable("공고상 조건을 충족하는 " + sentence[1] + "에약정총액의" + sentence[2] + "%이상투자")
                remember("purpose", value, url, digest, sentence[0])

    amount = _one(facts["base_amount"], "출자규모")
    count = _one(facts["manager_count"], "선정 수")
    deadline = _one(facts["deadline"], "접수 마감")
    purpose = _one(facts["purpose"], "주목적")
    if amount <= 0 or count <= 0 or deadline[:10] < notice["date"] or not 10 <= len(purpose) <= 260:
        raise ValueError("모집 개요 범위 불일치")
    joint_context = any("공동출자자" in compact(raw) or "모태펀드" in compact(raw) for _, raw, _ in sources)
    allocations = _one(facts["joint_allocations"], "공동출자 기관별 배분") if joint_context else None
    result = {"commitment_amount_krw": amount, "commitment_label": f"{amount/100_000_000:,.0f}억원" + (" 이내" if True in facts["amount_limit"] else ""),
              "manager_count_label": f"{count}개사", "deadline": deadline,
              "primary_investment": {"text": purpose, "source_url": notice["url"]},
              "extraction_evidence": dict(evidence)}
    if allocations:
        # Base amount belongs to the mother fund, not the site publishing it.
        if not any(re.match(r"(?:-1-)?모태펀드", compact(raw)) for _, raw, _ in sources):
            raise ValueError("공동사업 주출자자 미확인")
        total = amount + sum(allocations.values())
        result.update(commitment_amount_krw=allocations[name], total_commitment_amount_krw=total,
                      commitment_label=f"총 {total/100_000_000:,.0f}억원" + (" 이내" if True in facts["amount_limit"] else "") + " (예정)",
                      list_commitment_label=f"수은 {allocations[name]/100_000_000:,.0f}억원 · 공동출자",
                      commitment_detail=" · ".join([f"모태펀드 {amount/100_000_000:,.0f}억원"] + [f"{n} {a/100_000_000:,.0f}억원" for n, a in allocations.items()]),
                      contribution_allocations={"모태펀드": amount, **allocations},
                      contribution_note="공동출자자별 출자 승인 필요")
    if facts["fund_target"]:
        target = _one(facts["fund_target"], "결성 목표")
        if target < result.get("total_commitment_amount_krw", amount):
            raise ValueError("출자액이 결성 목표를 초과")
        result["fund_target_label"] = f"{target/100_000_000:,.0f}억원"
    return result


def project_discovered(candidates, notices, checked_at):
    """Reassess official source, then publish only complete, unambiguous groups."""
    assessed = assess_candidates(candidates, notices)
    groups = defaultdict(list)
    by_url = {n["url"]: n for n in notices}
    for candidate in assessed:
        groups[candidate["program_key"]].append(candidate)
    programs, holds = [], []
    for key, members in groups.items():
        if members[0]["scope"] != "pe_eligible":
            continue
        identity = re.sub(r"[^a-z0-9_-]", "-", key)
        try:
            originals = [m for m in members if m["stage"] == "모집 공고"]
            original = _one([m["url"] for m in originals], "모집 원공고")
            if any(m["stage"] in ("변경 공고", "단계 확인 필요") for m in members):
                raise ValueError("변경 또는 미확인 단계의 공고 있음")
            notice = by_url[original]
            terms = extract_terms(notice)
            name = INSTITUTIONS[notice["institution_id"]][0]
            p = {"id": identity, "institution_id": notice["institution_id"], "institution_name": name,
                 "title": notice["title"], "asset_scope": "PE", "status": "모집 공고", "selected_gps": [],
                 "events": [], "schedule_stages": [], "auto_extracted": True,
                 "source_program_key": key, "extraction_version": 1, "checked_at": checked_at, **terms}
            stage_keys = {"모집 공고": "announcement", "접수 결과": "application",
                          "1차 심사 결과": "screening", "우선협상대상자": "selection", "선정 결과": "selection"}
            for m in sorted(members, key=lambda x: (x["date"], x["source_id"])):
                if m["date"] > str(checked_at)[:10]:
                    raise ValueError("미래의 결과 공고")
                p["events"].append({"date": m["date"], "type": m["stage"], "title": m["title"], "url": m["url"]})
                p["schedule_stages"].append({"stage": stage_keys[m["stage"]], "label": m["stage"],
                                             "original_label": m["stage"], "date": m["date"], "precision": "date",
                                             "status": "confirmed", "source_url": m["url"], "show_source": True})
            p["schedule_stages"].append({"stage": "application", "label": "접수 마감", "original_label": "접수 마감",
                                         "date": p["deadline"], "precision": "datetime", "status": "announced_deadline",
                                         "source_url": original, "show_source": True})
            p["schedule_stages"].extend(terms.get("planned_schedule", []))
            p["schedule_stages"].sort(key=lambda s: s["date"])
            latest = max(members, key=lambda m: (m["date"], m["source_id"]))["stage"]
            if latest != "모집 공고":
                p["status"] = "선정 결과 발표" if latest == "선정 결과" else latest
            else:
                now = datetime.fromisoformat(str(checked_at))
                ended = (datetime.fromisoformat(p["deadline"]) < now if now.tzinfo
                         else p["deadline"][:10] < str(checked_at)[:10])
                p["status"] = "접수 마감" if ended else "접수 중"
            p["gp_stage_note"] = "운용사 명단은 단계별 원문 참조" if latest != "모집 공고" else "선정 결과 미확인"
            programs.append(p)
        except (ValueError, KeyError) as error:
            holds.append({"program_id": identity, "reason": str(error)})
    return programs, holds
