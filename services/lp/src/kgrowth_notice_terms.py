"""Extract offering facts from labeled official documents, never notice recipes.

Only a recognized offering layout with reconciled totals is publishable.
Unknown layouts and ambiguous obligations stay in the review queue.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlparse

try:
    from .lp_notice_triage import _scope_from_source, program_key, notice_stage
except ImportError:
    from lp_notice_triage import _scope_from_source, program_key, notice_stage

HOST = "www.kgrowth.or.kr"
NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?"


def _money(value):
    amount = Decimal(value.replace(",", "")) * 100_000_000
    if amount <= 0 or amount != amount.to_integral_value():
        raise ValueError("출자금액 단위 또는 범위 불일치")
    if amount % 100_000_000:
        raise ValueError("억원 단위 소수 금액의 표시는 추가 지원 필요")
    return int(amount)


def _squash(raw):
    positions = [i for i, char in enumerate(raw) if not char.isspace() and char != "\u200b"]
    return "".join(raw[i] for i in positions), positions


def is_offering_text(raw):
    first = re.sub(r"\s+", "", raw[:700])
    return bool(re.search(r"선정계획(?:공고)?|출자사업계획공고", first)) and not bool(
        re.search(r"제출서류|관련서식|제안서작성|신청서양식", first[:180]))


def extract_offering(notice):
    if urlparse(notice["url"]).hostname != HOST or urlparse(notice["url"]).scheme != "https" or not notice.get("sha256"):
        raise ValueError("공식 공고 근거 없음")
    results = []
    sources = dict(notice.get("attachment_texts", {}))
    sources.update({url: doc["text"] for url, doc in notice.get("attachment_documents", {}).items() if doc.get("text")})
    for url, raw in sources.items():
        if not is_offering_text(raw):
            continue
        digest = notice.get("attachment_hashes", {}).get(url)
        if urlparse(url).hostname != HOST or not digest:
            raise ValueError("첨부 원문 근거 없음")
        text, positions = _squash(raw)
        evidence = {}

        def match(pattern, field):
            hits = list(re.finditer(pattern, text, re.S))
            if len(hits) != 1:
                raise ValueError(f"{field}: 항목 누락 또는 중복")
            hit = hits[0]
            evidence[field] = {"source_url": notice["url"], "attachment_url": url,
                               "sha256": digest, "quote": raw[positions[hit.start()]:positions[hit.end()-1]+1]}
            return hit

        budget = match(r"위탁운용금액[▪○□:：]*(.*?)선정운용사수", "출자규모")
        amounts = list(re.finditer(r"(" + NUMBER + r")억원(이내)?", budget[1]))
        if len(amounts) != 1:
            raise ValueError("위탁운용금액의 총액 미확인")
        amount = _money(amounts[0][1])
        limit = bool(amounts[0][2])
        managers = match(r"선정운용사수[▪○□:：]*총?(\d+)개(?:운용사|사)", "선정 수")
        count = int(managers[1])
        if not 0 < count <= 1000:
            raise ValueError("선정 수 범위 불일치")
        deadline = match(r"접수일시[▪○□:：]*(20\d{2})[.년](\d{1,2})[.월](\d{1,2})[.일]?"
                         r"(?:\([월화수목금토일]\))?(\d{1,2}):(\d{2})[~∼～](\d{1,2}):(\d{2})", "접수 마감")
        values = list(map(int, deadline.groups()))
        start = datetime(*values[:5])
        end = datetime(*values[:3], *values[5:])
        if start >= end or end.date().isoformat() < notice["date"]:
            raise ValueError("접수 일정 범위 불일치")
        purpose = match(r"주목적투자[▪○□:：]+(.*?)(?=출자조건|출자자제한|수탁회사)", "주목적")
        target = re.search(r"투자대상기업은법인형태의(.+?)\*?으로투자기간", purpose[1])
        if not target:
            raise ValueError("주목적 투자대상 문구 미확인")
        target_start = purpose.start(1) + target.start(1)
        target_end = purpose.start(1) + target.end(1)
        target_label = raw[positions[target_start]:positions[target_end-1]+1].rstrip("*")
        obligations = []
        warnings = []
        purpose_raw = raw[positions[purpose.start(1)]:positions[purpose.end(1)-1]+1]
        for item in re.finditer(r"(?:^|\n)\s*[①②③④⑤]\s*([^\n]+)", purpose_raw):
            expression = re.sub(r"\s+", "", item[1])
            if not any(word in expression for word in ("투자", "출자")):
                continue
            # Preserve ambiguous ratios in evidence instead of assigning a
            # guessed denominator or presenting a proposal as a fixed duty.
            if "자율제안" in expression:
                warnings.append("자율 제안이 함께 기재된 주목적 비율은 수치화하지 않음")
                subject = re.match(r"(.+?기업)\s*에\s*[「『]", item[1])
                if subject:
                    obligations.append(re.sub(r"\s+", " ", subject[1]).replace("*", "").strip() + " 투자")
                continue
            obligations.append(re.sub(r"\s+", " ", item[1]).strip())
        table = match(r"출자금액구분운용사수펀드당출자금액총출자금액(.*?)(?=주목적투자)", "분야별 출자")
        row_pattern = re.compile(r"([가-힣A-Za-z·()]+?리그)(\d+)개(" + NUMBER + r")억원(이내)?"
                                 r"(?:((?:" + NUMBER + r"))억원)?")
        rows = list(row_pattern.finditer(table[1]))
        if not rows or "".join(row[0] for row in rows) != table[1]:
            raise ValueError("분야별 표 열 또는 병합 셀 미확인")
        segments = []
        table_totals = []
        for row in rows:
            per_fund, managers_count = _money(row[3]), int(row[2])
            label_start, label_end = table.start(1) + row.start(1), table.start(1) + row.end(1)
            label = re.sub(r"\s+", " ", raw[positions[label_start]:positions[label_end-1]+1]).strip()
            if managers_count <= 0:
                raise ValueError("분야별 선정 수 미확인")
            segment = {"name": label, "amount_krw": per_fund * managers_count,
                       "manager_count": managers_count, "per_fund_amount_krw": per_fund,
                       "amount_basis": "명시된 펀드당 출자액 × 선정 수"}
            if row[4]:
                segment["per_fund_max_krw"] = per_fund
            if row[5]:
                table_totals.append(_money(row[5]))
            segments.append(segment)
        if (sum(s["amount_krw"] for s in segments) != amount or
                sum(s["manager_count"] for s in segments) != count or
                set(table_totals) != {amount} or len({s["name"] for s in segments}) != len(segments)):
            raise ValueError("분야별 금액·선정 수와 공고 총계 불일치")
        planned = []
        for m in re.finditer(r"심사결과발표[▪○□:：]*(20\d{2})년(\d{1,2})월(?:중|예정)?", text):
            month = datetime(int(m[1]), int(m[2]), 1)
            if month.strftime("%Y-%m") < end.strftime("%Y-%m"):
                raise ValueError("심사 일정이 접수 이전임")
            planned.append({"stage": "selection", "label": "심사 결과 발표", "original_label": "심사 결과 발표",
                            "date": month.strftime("%Y-%m"), "precision": "month", "status": "planned",
                            "source_url": notice["url"], "show_source": True})
        results.append({"commitment_amount_krw": amount,
                        "commitment_label": f"총 {amount/100_000_000:,.0f}억원" + (" 이내" if limit else ""),
                        "manager_count_label": f"{count}개사", "deadline": end.isoformat() + "+09:00",
                        "segments": segments, "primary_investment": {"text": target_label,
                        **({"items": [target_label, *obligations]} if obligations else {}), "source_url": notice["url"]},
                        "planned_schedule": planned, "extraction_evidence": evidence,
                        "extraction_warnings": warnings, "terms_auto_extracted": True})
    if len(results) != 1:
        raise ValueError("지원되는 모집 공고문이 없거나 여러 개임")
    return results[0]


def discovery(notices):
    """Read every found offering; known programs are connected by source URL."""
    extracted, holds, candidates = {}, [], []
    for n in notices:
        title = re.sub(r"\s+", "", n["title"])
        if "【기타】" in title or "제출서식" in title:
            continue
        if not any(word in title for word in ("선정계획", "출자사업", "선정결과", "접수결과", "접수현황", "서류심사결과", "우선협상대상자")):
            continue
        scope, reason = _scope_from_source({**n, "institution_id": "kgrowth",
                                           "attachment_texts": {u: t for u, t in n.get("attachment_texts", {}).items() if is_offering_text(t)}})
        key = program_key({**n, "institution_id": "kgrowth"}).replace(":", "-")
        candidate = {"institution_id": "kgrowth", "source_id": n["source_id"], "url": n["url"],
                     "title": n["title"], "date": n["date"], "program_key": key,
                     "stage": notice_stage(n["title"]),
                     "scope": scope, "scope_reason": reason, "recruitment_url": n["url"]}
        candidates.append(candidate)
        if candidate['stage'] not in ('모집 공고', '변경 공고'):
            continue
        try:
            if candidate["stage"] != "모집 공고":
                raise ValueError("변경·재공고는 기존 사업과의 대조 필요")
            extracted[n["url"]] = extract_offering(n)
        except ValueError as exc:
            holds.append({"program_id": key, "source_url": n["url"], "reason": str(exc)})
    return extracted, holds, candidates
