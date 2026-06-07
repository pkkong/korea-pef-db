from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from daily_news_common import normalize_whitespace, today_seoul

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.lp.src.lp_notice_identity import (
    GENERIC_PROGRAM_NAMES as GENERIC_LP_PROGRAM_NAMES,
    business_key_text,
    clean_notice_text_brackets,
    clean_program_candidate,
    infer_notice_program_name,
    infer_notice_round_name,
    is_generic_program_name,
    normalize_round_name,
    program_candidates,
    strip_lp_round_suffix,
)


def clean_public_lp_text(value: object) -> str:
    return normalize_whitespace(str(value or '').replace('\xa0', ' '))


def safe_float(value: object) -> float:
    try:
        return float(str(value or '0').replace(',', ''))
    except ValueError:
        return 0.0


def lp_event_label(value: object) -> str:
    return {
        "new_notice": "신규 공고",
        "deadline_soon": "마감 임박",
        "deadline_closed": "마감",
        "shortlist": "숏리스트",
        "final_selection": "최종 선정",
        "revision": "정정",
        "cancellation": "취소",
        "performance_update": "성과",
    }.get(str(value or ""), "공고")


def lp_amount_label(value: object) -> str:
    try:
        parsed = float(str(value or "0").replace(",", ""))
    except ValueError:
        return ""
    if parsed <= 0:
        return ""
    if parsed >= 10000:
        return f"{parsed / 10000:,.1f}조"
    return f"{round(parsed):,}억"


def split_notice_names(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw_parts = [str(item or "") for item in value]
    else:
        raw_parts = re.split(r"[;,]", str(value or ""))
    names: list[str] = []
    seen: set[str] = set()
    for raw_part in raw_parts:
        for part in re.split(r"[;,]", raw_part):
            name = clean_public_lp_text(part)
            if not name or name in seen:
                continue
            names.append(name)
            seen.add(name)
    return names


def lp_notice_program_label(item: dict[str, object]) -> str:
    program = lp_notice_specific_program_name(item)
    round_name = lp_notice_business_round_name(item)
    program = clean_public_lp_text(program)
    round_name = clean_public_lp_text(round_name)
    if not program:
        return "-"
    if round_name and re.search(rf"(?:^|[^0-9A-Za-z가-힣]){re.escape(round_name)}(?:$|[^0-9가-힣])", program):
        return program
    return " ".join([program, round_name]).strip() or "-"


def lp_notice_amount_label(item: dict[str, object]) -> tuple[str, float]:
    raw_amount = item.get("allocationAmount")
    raw_program_size = item.get("programSize")
    label = lp_amount_label(raw_amount)
    numeric_source = raw_amount
    if not label:
        program_label = lp_amount_label(raw_program_size)
        if program_label:
            label = f"프로그램 {program_label}"
            numeric_source = raw_program_size
    try:
        amount_numeric = float(str(numeric_source or "0").replace(",", ""))
    except ValueError:
        amount_numeric = 0.0
    return label or "-", amount_numeric


def lp_notice_date(value: object):
    text = str(value or "").strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def lp_notice_effective_deadline_date(item: dict[str, object]):
    deadline = lp_notice_date(item.get("applicationDeadline"))
    if not deadline:
        return None
    event_date = lp_notice_date(item.get("latestEventDate") or item.get("eventDate") or item.get("announcedDate"))
    if event_date and (event_date - deadline).days > 180:
        return None
    return deadline


def lp_notice_effective_deadline_value(item: dict[str, object]) -> str:
    deadline = lp_notice_effective_deadline_date(item)
    return deadline.isoformat() if deadline else ""


def korean_date_label(value: object) -> str:
    date_value = lp_notice_date(value)
    if not date_value:
        return clean_public_lp_text(value)
    return f"{date_value.year}년 {date_value.month}월 {date_value.day}일"


def lp_notice_status(item: dict[str, object], report_date: str) -> str:
    event_type = str(item.get("eventType") or "")
    if event_type in {"final_selection", "performance_update"}:
        return "result"
    if event_type == "shortlist":
        return "shortlist"
    if event_type == "cancellation":
        return "cancellation"
    if event_type == "deadline_closed":
        return "closed"
    today = lp_notice_date(report_date)
    deadline = lp_notice_effective_deadline_date(item)
    event_date = lp_notice_date(item.get("eventDate") or item.get("announcedDate"))
    if today and deadline:
        return "open" if deadline >= today else "closed"
    if event_type == "deadline_soon":
        return "open"
    if event_type == "new_notice" and today and event_date:
        return "open" if today - event_date <= timedelta(days=45) else "history"
    return "history"


def lp_notice_public_status(item: dict[str, object], report_date: str) -> str:
    business_status = str(item.get("businessStatus") or "")
    today = lp_notice_date(report_date)
    deadline = lp_notice_effective_deadline_date(item)
    if today and deadline and deadline >= today and business_status not in {"cancellation", "result"}:
        return "open"
    if business_status == "open":
        if today and deadline and deadline < today:
            return "closed"
    if business_status == "shortlist":
        latest_event = lp_notice_date(item.get("latestEventDate") or item.get("eventDate") or item.get("announcedDate"))
        if today and latest_event and (today - latest_event).days > 90:
            return "history"
    if business_status in {"open", "shortlist", "result", "closed", "cancellation", "history"}:
        return business_status
    return lp_notice_status(item, report_date)


def lp_notice_status_label(status: str) -> str:
    return {
        "open": "모집중",
        "shortlist": "1차 선정",
        "result": "선정완료",
        "closed": "마감",
        "cancellation": "취소",
        "history": "지난 공고",
    }.get(status, "공고")


def lp_notice_stage_label(item: dict[str, object], status: str) -> str:
    event_type = str(item.get("eventType") or "")
    stage = str(item.get("stage") or "")
    title = str(item.get("title") or "")
    if any(term in title for term in ["서류심사", "정량평가 결과", "제안서 발표대상", "발표대상"]):
        return "서류심사"
    if event_type == "final_selection" or stage == "selection_result":
        return "최종선정"
    if event_type == "shortlist" or stage == "shortlist":
        return "서류심사"
    if stage == "application" or "접수현황" in title:
        return "접수"
    if event_type == "revision":
        return "변경/정정"
    if event_type == "cancellation":
        return "취소"
    if status == "open":
        return "모집중"
    if status == "shortlist":
        return "1차 선정"
    if status == "cancellation":
        return "취소"
    if status == "closed":
        return "마감"
    return "공고"


def lp_notice_source_label(item: dict[str, object]) -> str:
    return "기사" if str(item.get("sourceType") or "").strip().lower() == "news" else "공식"


def lp_notice_source_note(item: dict[str, object]) -> str:
    links = item.get("sourceLinks") if isinstance(item.get("sourceLinks"), list) else []
    labels: list[str] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        label = "기사" if str(link.get("sourceType") or "").strip().lower() == "news" else "공식"
        if label not in labels:
            labels.append(label)
    if not labels:
        return lp_notice_source_label(item)
    if len(labels) > 1:
        return " · ".join(labels)
    return f"{labels[0]} {len(links)}" if len(links) > 1 else labels[0]


def strip_lp_notice_business_round_suffix(value: object) -> str:
    return strip_lp_round_suffix(value)


def normalize_lp_notice_round_name(value: object) -> str:
    return normalize_round_name(value)


def clean_lp_notice_text_brackets(value: object) -> str:
    return clean_notice_text_brackets(value)


def normalize_lp_notice_generic_token(value: object) -> str:
    text = clean_lp_notice_text_brackets(value)
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", "", text)
    text = strip_lp_notice_business_round_suffix(text)
    text = re.sub(r"\s+(?:1\d차|2\d차|\d+호)\b", "", text)
    return clean_public_lp_text(text)


def is_generic_lp_program_name(value: object) -> bool:
    return is_generic_program_name(value)


def clean_lp_program_candidate(value: object) -> str:
    return clean_program_candidate(value)


def lp_notice_program_candidates(text: object) -> list[str]:
    return program_candidates(text)


def lp_notice_specific_program_name(item: dict[str, object]) -> str:
    return infer_notice_program_name(item) or "-"


def lp_notice_platform_label(item: dict[str, object]) -> str:
    values = [item.get("programName"), item.get("title"), item.get("displayTitle")]
    labels: list[str] = []
    for value in values:
        text = clean_public_lp_text(value)
        for label in GENERIC_LP_PROGRAM_NAMES:
            if label in text and label not in labels:
                labels.append(label)
    return " · ".join(labels)


def lp_notice_public_strategy_label(item: dict[str, object]) -> str:
    strategy = clean_public_lp_text(item.get("strategy") or item.get("purpose") or "")
    if is_generic_lp_program_name(strategy):
        return ""
    return strategy


def lp_notice_business_round_name(item: dict[str, object]) -> str:
    return infer_notice_round_name(item)


def lp_notice_business_key_text(value: object) -> str:
    return business_key_text(value)

def lp_notice_canonical_title(item: dict[str, object]) -> str:
    title = clean_public_lp_text(item.get("displayTitle") or item.get("title") or "")
    replacements = [
        r"^\[[^\]]+\]\s*",
        r"^[【\[]?선정공고[】\]]?\s*",
        r"^공고\s*",
        r"\([^)]*공고\s*제?\d{4}[-\s]?\d+호?[^)]*\)",
        r"20\d{2}년\s*",
        r"위탁운용사\s*선정계획\s*공고",
        r"위탁운용사\s*선정\s*공고",
        r"출자사업\s*계획\s*공고",
        r"공고문",
        r"최종",
    ]
    for pattern in replacements:
        title = re.sub(pattern, "", title, flags=re.IGNORECASE)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", title).lower()


def lp_notice_display_group_key(item: dict[str, object]) -> tuple[str, str]:
    lp_key = str(item.get("lpCode") or item.get("lpName") or "").strip()
    program = lp_notice_specific_program_name(item)
    if program and program != "-" and not is_generic_lp_program_name(program):
        program = lp_notice_business_key_text(program)
        round_name = lp_notice_business_key_text(lp_notice_business_round_name(item))
        return lp_key, f"{program}|{round_name}" if round_name else program
    # Existing businessKey is useful when title-based specific extraction failed.
    business_key = item.get("businessKey")
    if isinstance(business_key, (tuple, list)) and len(business_key) >= 2:
        secondary_key = str(business_key[1] or "").strip()
        if secondary_key:
            if "|" in secondary_key:
                program_key, round_key = secondary_key.split("|", 1)
                program_key = lp_notice_business_key_text(program_key)
                round_key = lp_notice_business_key_text(round_key)
                return lp_key, f"{program_key}|{round_key}" if round_key else program_key
            clean_key = lp_notice_business_key_text(secondary_key)
            if clean_key:
                return lp_key, clean_key
    elif isinstance(business_key, str):
        clean_key = lp_notice_business_key_text(business_key)
        if clean_key:
            return lp_key, clean_key
    # Fallback to title-based anchor (normalized).
    fallback = lp_notice_canonical_title(item)
    return lp_key, fallback


def _normalize_notice_round_key_for_group(item: dict[str, object]) -> tuple[str, str]:
    lp_key = str(item.get("lpCode") or item.get("lpName") or "").strip()
    round_name = lp_notice_business_round_name(item)
    return lp_key, lp_notice_business_key_text(round_name)


def _build_notice_program_round_maps(
    items: list[dict[str, object]],
) -> tuple[dict[tuple[str, str], str], dict[str, set[str]], dict[tuple[str, str], set[str]]]:
    """Build deterministic anchors for LP notice program normalization.

    Returns:
      - preferred program by LP+round
      - unique fallback program candidate per LP
      - round candidates by LP+program
    """
    preferred_by_key: dict[tuple[str, str], tuple[tuple[int, ...], str]] = {}
    lp_programs: dict[str, set[str]] = {}
    rounds_by_business: dict[tuple[str, str], set[str]] = {}

    for item in items:
        lp_key = str(item.get("lpCode") or item.get("lpName") or "").strip()
        if not lp_key:
            continue
        program = lp_notice_specific_program_name(item)
        if not program or program == "-" or is_generic_lp_program_name(program):
            continue
        normalized = lp_notice_business_key_text(program)
        if not normalized:
            continue
        round_key = lp_notice_business_key_text(lp_notice_business_round_name(item))
        quality = lp_notice_display_quality(item)

        for key in [(lp_key, round_key), (lp_key, "")]:
            current = preferred_by_key.get(key)
            if current is None or quality > current[0] or (quality == current[0] and len(program) > len(current[1])):
                preferred_by_key[key] = (quality, program)

        lp_programs.setdefault(lp_key, set()).add(normalized)
        if round_key:
            rounds_by_business.setdefault((lp_key, normalized), set()).add(round_key)

    preferred = {key: program for key, (_, program) in preferred_by_key.items()}
    fallback: dict[str, set[str]] = {lp: values for lp, values in lp_programs.items()}
    return preferred, fallback, rounds_by_business


def _resolve_notice_program_for_group(
    item: dict[str, object],
    program_map: dict[tuple[str, str], str],
    fallback_map: dict[str, set[str]],
) -> dict[str, object]:
    lp_key, round_key = _normalize_notice_round_key_for_group(item)
    program = lp_notice_specific_program_name(item)
    if program and program != "-" and not is_generic_lp_program_name(program):
        return item
    resolved = program_map.get((lp_key, round_key))
    if not resolved and fallback_map.get(lp_key):
        candidates = fallback_map[lp_key]
        if len(candidates) == 1:
            resolved = next(iter(candidates))
    if resolved:
        result = dict(item)
        result["programName"] = resolved
        return result
    return item


def _resolve_notice_round_for_group(item: dict[str, object], round_map: dict[tuple[str, str], str]) -> dict[str, object]:
    round_name = lp_notice_business_round_name(item)
    if round_name:
        return item
    program = lp_notice_specific_program_name(item)
    if not program or program == "-":
        return item
    lp_key = str(item.get("lpCode") or item.get("lpName") or "").strip()
    resolved = round_map.get((lp_key, lp_notice_business_key_text(program)))
    if not resolved:
        return item
    result = dict(item)
    result["roundName"] = resolved
    return result


def lp_notice_program_specificity(item: dict[str, object]) -> int:
    program = lp_notice_specific_program_name(item)
    if program and program != "-" and not is_generic_lp_program_name(program):
        return 1
    text = clean_public_lp_text(item.get("rawExcerpt") or item.get("title") or item.get("programName") or "")
    if text and text != program:
        inferred = lp_notice_specific_program_name({"title": text, "rawExcerpt": text, "programName": text})
        if inferred not in {"", "-", *GENERIC_LP_PROGRAM_NAMES}:
            return 1
    return 0


def lp_notice_display_quality(item: dict[str, object]) -> tuple[object, ...]:
    source_rank = 2 if str(item.get("sourceType") or "").lower() == "official" else 1
    has_document = 1 if item.get("documentUrl") or item.get("attachments") else 0
    has_deadline = 1 if lp_notice_effective_deadline_value(item) else 0
    amount = 1 if safe_float(item.get("allocationAmount") or item.get("programSize")) > 0 else 0
    selected = 1 if split_notice_names(item.get("selectedGpNames")) else 0
    program_specificity = lp_notice_program_specificity(item)
    return (
        source_rank,
        str(item.get("eventDate") or ""),
        program_specificity,
        has_document,
        has_deadline,
        amount,
        selected,
    )


def lp_notice_link_signature(item: dict[str, object]) -> tuple[str, str]:
    return str(item.get("url") or ""), str(item.get("documentUrl") or "")


def merge_lp_notice_display_item(
    primary: dict[str, object],
    secondary: dict[str, object],
    report_date: str | None = None,
) -> dict[str, object]:
    effective_report_date = report_date or today_seoul()
    merged = dict(primary)
    primary_program = lp_notice_specific_program_name(primary)
    secondary_program = lp_notice_specific_program_name(secondary)
    if primary_program == "-" or (
        is_generic_lp_program_name(primary_program) and not is_generic_lp_program_name(secondary_program)
    ):
        merged["programName"] = secondary_program
    else:
        merged["programName"] = primary_program
    primary_round = lp_notice_business_round_name(primary)
    secondary_round = lp_notice_business_round_name(secondary)
    merged["roundName"] = primary_round or secondary_round
    platform = lp_notice_platform_label(primary) or lp_notice_platform_label(secondary)
    if platform:
        merged["programPlatform"] = platform
    for key in [
        "applicationDeadline",
        "announcedDate",
        "eventDate",
        "assetClass",
        "strategy",
        "purpose",
        "programName",
        "roundName",
        "allocationAmount",
        "programSize",
        "selectedGpNames",
        "documentUrl",
        "url",
    ]:
        if not merged.get(key) and secondary.get(key):
            merged[key] = secondary[key]
    if not merged.get("attachments") and secondary.get("attachments"):
        merged["attachments"] = secondary["attachments"]
    selected_names = split_notice_names(merged.get("selectedGpNames")) + split_notice_names(secondary.get("selectedGpNames"))
    if selected_names:
        seen: set[str] = set()
        merged["selectedGpNames"] = [name for name in selected_names if not (name in seen or seen.add(name))]
    source_links = list(merged.get("sourceLinks") or [])
    for source in [primary, secondary]:
        signature = lp_notice_link_signature(source)
        if not signature[0] and not signature[1] and not source.get("attachments"):
            continue
        if not any(link.get("signature") == signature for link in source_links):
            source_links.append(
                {
                    "signature": signature,
                    "sourceType": source.get("sourceType"),
                    "url": source.get("url"),
                    "documentUrl": source.get("documentUrl"),
                    "attachments": source.get("attachments") or [],
                }
            )
    merged["sourceLinks"] = source_links
    merged["sourceCount"] = len(source_links)
    events: list[dict[str, object]] = []
    for source in [primary, secondary]:
        nested_events = source.get("events") if isinstance(source.get("events"), list) else []
        for nested_event in nested_events:
            if not isinstance(nested_event, dict):
                continue
            copied_event = dict(nested_event)
            if not copied_event.get("applicationDeadline") and source.get("applicationDeadline"):
                copied_event["applicationDeadline"] = source.get("applicationDeadline")
            if not copied_event.get("status"):
                copied_event["status"] = lp_notice_status({**source, **copied_event}, effective_report_date)
            if not copied_event.get("stageLabel"):
                copied_event["stageLabel"] = lp_notice_stage_label({**source, **copied_event}, str(copied_event.get("status") or ""))
            nested_notice_id = str(nested_event.get("noticeId") or "")
            nested_title = clean_public_lp_text(nested_event.get("title") or "")
            if any(
                (nested_notice_id and event.get("noticeId") == nested_notice_id)
                or (not nested_notice_id and nested_title and event.get("title") == nested_title)
                for event in events
            ):
                continue
            events.append(copied_event)
        notice_id = str(source.get("noticeId") or "")
        title = clean_public_lp_text(source.get("title") or source.get("displayTitle") or "")
        if not notice_id and not title:
            continue
        if any((event.get("noticeId") == notice_id and notice_id) or (not notice_id and event.get("title") == title) for event in events):
            continue
        event_status = lp_notice_status(source, effective_report_date)
        events.append(
            {
                "noticeId": notice_id,
                "title": title,
                "eventType": source.get("eventType"),
                "eventDate": source.get("eventDate") or source.get("announcedDate"),
                "stage": source.get("stage"),
                "status": event_status,
                "stageLabel": lp_notice_stage_label(source, event_status),
                "applicationDeadline": source.get("applicationDeadline"),
                "sourceType": source.get("sourceType"),
                "url": source.get("url"),
                "documentUrl": source.get("documentUrl"),
            }
        )
    events.sort(
        key=lambda event: (
            str(event.get("eventDate") or ""),
            {"new_notice": 1, "deadline_soon": 2, "shortlist": 3, "final_selection": 4}.get(str(event.get("eventType") or ""), 0),
        ),
        reverse=True,
    )
    if events:
        latest_event_date = lp_notice_date(events[0].get("eventDate"))
        if latest_event_date:
            events = [
                event
                for event in events
                if not (
                    lp_notice_date(event.get("eventDate"))
                    and (latest_event_date - lp_notice_date(event.get("eventDate"))).days > 540
                )
            ]
    merged["events"] = events
    return merged


def consolidate_lp_notice_display_items(items: list[dict[str, object]], report_date: str | None = None) -> list[dict[str, object]]:
    effective_report_date = report_date or today_seoul()
    # 1) Build a stable program anchor per LP+round so generic rows (e.g., 국민성장펀드 3차) can be merged
    # into the same business card when another row contains the true 사업명.
    preferred_program_by_key: dict[tuple[str, str], str] = {}
    fallback_program_by_lp: dict[str, set[str]] = {}
    round_candidates: dict[tuple[str, str], set[str]] = {}
    preferred_program_by_key, fallback_program_by_lp, round_candidates = _build_notice_program_round_maps(items)

    resolved_round_by_key: dict[tuple[str, str], str] = {
        key: next(iter(values)) for key, values in round_candidates.items() if len(values) == 1
    }

    # Normalize fallback LP candidates down to deterministic single options only.
    fallback_program_by_lp = {
        lp_code: next(iter(values)) for lp_code, values in fallback_program_by_lp.items() if len(values) == 1
    }

    normalized_items = [
        _resolve_notice_round_for_group(
            _resolve_notice_program_for_group(item, preferred_program_by_key, fallback_program_by_lp),
            resolved_round_by_key,
        )
        for item in items
    ]

    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for item in normalized_items:
        key = lp_notice_display_group_key(item)
        current = grouped.get(key)
        if current is None:
            grouped[key] = merge_lp_notice_display_item(dict(item), {}, effective_report_date)
            continue
        if lp_notice_display_quality(item) > lp_notice_display_quality(current):
            grouped[key] = merge_lp_notice_display_item(dict(item), current, effective_report_date)
        else:
            grouped[key] = merge_lp_notice_display_item(current, item, effective_report_date)
    rows = list(grouped.values())
    for row in rows:
        events = row.get("events") if isinstance(row.get("events"), list) else []
        event_types = {str(event.get("eventType") or "") for event in events if isinstance(event, dict)}
        event_statuses = {str(event.get("status") or "") for event in events if isinstance(event, dict)}
        row_status = lp_notice_status(row, effective_report_date)
        today = lp_notice_date(effective_report_date)
        deadline = lp_notice_effective_deadline_date(row)
        deadline_is_open = bool(today and deadline and deadline >= today)
        if "cancellation" in event_types:
            row["businessStatus"] = "cancellation"
            row["businessStageLabel"] = "취소"
        elif deadline_is_open:
            row["businessStatus"] = "open"
            row["businessStageLabel"] = "모집중"
        elif "final_selection" in event_types:
            row["businessStatus"] = "result"
            row["businessStageLabel"] = "선정완료"
        elif "result" in event_statuses:
            row["businessStatus"] = "result"
            row["businessStageLabel"] = "선정완료"
        elif "shortlist" in event_types:
            row["businessStatus"] = "shortlist"
            row["businessStageLabel"] = "1차 선정"
        elif row_status == "open" or "open" in event_statuses:
            row["businessStatus"] = "open"
            row["businessStageLabel"] = "모집중"
        elif row_status == "closed" or "closed" in event_statuses:
            row["businessStatus"] = "closed"
            row["businessStageLabel"] = "마감"
        else:
            row["businessStatus"] = "history"
            row["businessStageLabel"] = "지난 공고"
        row["businessStatus"] = str(row.get("businessStatus") or "history")
        if events:
            latest = events[0]
            row["latestEventDate"] = latest.get("eventDate") or row.get("eventDate")
            row["latestEventType"] = latest.get("eventType") or row.get("eventType")
            row["latestEventTitle"] = latest.get("title") or row.get("title")
    rows.sort(
        key=lambda item: str(item.get("latestEventDate") or item.get("eventDate") or item.get("announcedDate") or ""),
        reverse=True,
    )
    return rows
