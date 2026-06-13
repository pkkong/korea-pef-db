from __future__ import annotations

import re
from dataclasses import dataclass


GENERIC_PROGRAM_NAMES = {
    "국민성장펀드",
    "모태펀드",
    "농식품모태펀드",
    "농림수산식품모태펀드",
    "공급망안정화기금",
}

NOTICE_BUSINESS_STOP_TERMS = [
    "출자공고",
    "공고",
    "최종",
    "선정",
    "선정결과",
    "선정계획",
    "서류심사",
    "정량평가",
    "위탁운용사",
    "운영",
    "결정",
    "자료",
    "발표",
    "결과",
]

PROGRAM_NOISE_TERMS = [
    "벤처투자마트",
    "벤처투자종합포털",
    "주식유통정보",
    "비상장주식거래플랫폼",
    "VC구주유통망",
    "신청 정보 확인",
    "동의하지 않은 경우",
    "경우에는 본회",
    "부합하는 경우",
    "목록에서 발견",
    "고객센터",
    "FAQ",
]

LP_NON_BUSINESS_ROUNDS = {"상반기", "하반기", "정시", "수시"}

LP_NOTICE_NOISE_PATTERNS = [
    r"최종",
    r"선정\s*계획",
    r"선정\s*결과(?:\s*발표)?",
    r"서류심사\s*결과",
    r"정량평가\s*결과",
    r"출자사업\s*계획",
    r"운용사\s*선정\s*계획",
    r"운영",
    r"공고(?:문)?",
    r"자료",
]


@dataclass(frozen=True)
class LpNoticeIdentity:
    program_name: str
    round_name: str
    platform_name: str
    program_key: str
    round_key: str
    business_key: str
    specificity: int


def normalize_whitespace(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def clean_notice_text_brackets(value: object) -> str:
    text = normalize_whitespace(value)
    if not text:
        return ""
    text = re.sub(r"^[\"'`‘’“”\s]+|[\"'`’”\s]+$", "", text)
    for opener, closer in [("(", ")"), ("[", "]"), ("【", "】"), ("「", "」"), ("『", "』")]:
        if text.startswith(opener) and text.endswith(closer):
            text = text[len(opener) : -len(closer)]
            break
    text = re.sub(r"^\[[^\]]*\]\s*", "", text)
    text = re.sub(r"^\([^)]*\)\s*", "", text)
    return normalize_whitespace(text)


def strip_lp_round_suffix(value: object) -> str:
    text = normalize_whitespace(value)
    if not text:
        return ""
    normalized = text
    while True:
        updated = re.sub(
            r"\s*\(?\s*(?:\d+차|\d+호|\d+차년도|상반기|하반기|정시|수시)\s*\)?\s*$",
            "",
            normalized,
            flags=re.IGNORECASE,
        )
        if updated == normalized:
            return normalize_whitespace(normalized)
        normalized = normalize_whitespace(updated)


def normalize_round_name(value: object) -> str:
    text = normalize_whitespace(value)
    if not text:
        return ""
    text = re.sub(r"[()（）]", "", text)
    round_match = re.search(r"(\d+차년도|\d+차|\d+호)", text)
    if round_match:
        text = round_match.group(1)
    if re.fullmatch(r"\d+차|\d+호|\d+차년도", text):
        return text
    if text in LP_NON_BUSINESS_ROUNDS:
        return ""
    if re.search(r"(상반기|하반기|정시|수시)", text) and not re.search(r"\d", text):
        return ""
    return text


def normalize_program_name_text(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", strip_lp_round_suffix(normalize_whitespace(value)))


GENERIC_PROGRAM_NAME_KEYS = {normalize_program_name_text(name) for name in GENERIC_PROGRAM_NAMES}


def strip_business_round_suffix(value: object) -> str:
    text = normalize_whitespace(value)
    if not text:
        return ""
    text = strip_lp_round_suffix(text)
    for round_name in [
        "1차",
        "2차",
        "3차",
        "4차",
        "5차",
        "6차",
        "7차",
        "8차",
        "9차",
        "10차",
        "1호",
        "2호",
        "3호",
        "4호",
        "5호",
        "6호",
        "7호",
        "8호",
        "9호",
        "10호",
    ]:
        text = re.sub(rf"\s*\(?\s*{re.escape(round_name)}\s*\)?", " ", text)
    return normalize_whitespace(text)


def strip_program_noise(value: object) -> str:
    text = normalize_whitespace(value)
    if not text:
        return ""
    text = re.sub(r"^[\u3010\[]?선정(?:공고|결과)?[\u3011\]]?\s*", "", text)
    text = re.sub(r"^[\"'「『\s]+|[\"'」』\s]+$", "", text)
    text = strip_business_round_suffix(text)
    for pattern in LP_NOTICE_NOISE_PATTERNS:
        text = re.sub(rf"\s*{pattern}\s*(?:$|(?=[가-힣A-Za-z0-9]))", "", text)
    return normalize_whitespace(text).strip(" -·:;・")


def is_generic_program_name(value: object) -> bool:
    normalized = normalize_program_name_text(value)
    return normalized in GENERIC_PROGRAM_NAME_KEYS


def normalized_notice_text(value: object) -> str:
    text = clean_notice_text_brackets(value)
    if not text:
        return ""
    return strip_program_noise(text)


def program_is_business_specific(candidate: str) -> bool:
    if not candidate:
        return False
    if any(term in candidate for term in PROGRAM_NOISE_TERMS):
        return False
    normalized = normalize_program_name_text(normalized_notice_text(candidate))
    if not normalized or is_generic_program_name(normalized):
        return False
    cleaned = normalized_notice_text(candidate)
    if len(cleaned) < 6:
        return False
    if re.search(r"(최종|선정|선정결과|서류심사|결과|공고|개최|운영|자료)", cleaned):
        return False
    if re.search(r"(운용계획상|투자하고자|보유하고|최근\s*3년|이해관계|제반\s*장치|대응방안)", cleaned):
        return False
    if re.search(r"(가치형이나|고배당형에|동의하지|신청\s*정보|공지\s*-|FAQ)", cleaned):
        return False
    if re.search(r"(목록에서\s*발견|법령|위반|자산건전성|도덕적|사회적\s*물의|운용사로서|사실상)", cleaned):
        return False
    if re.search(r"(운용성과|제출하지\s*못할|미제출|상세한\s*이유|고의|과실|청산펀드.*기준|기준\s*$)", cleaned):
        return False
    return True


def program_is_specific_and_not_platform_only(candidate: str) -> bool:
    normalized = normalize_program_name_text(candidate)
    return bool(normalized and program_is_business_specific(candidate) and not is_generic_program_name(normalized))


def cleanup_program_noise_prefix(text: str) -> str:
    text = normalize_whitespace(text)
    if not text:
        return ""
    text = re.sub(r"^\d+\s*일\s*", "", text)
    text = re.sub(r"^\d+\s*(?:차|호)\s*", "", text)
    text = re.sub(r"^\d+월\s*\d+일\s*", "", text)
    text = re.sub(r"^[가-힣A-Za-z0-9&·ㆍ\-]+[은는이가]\s+", "", text)
    return normalize_whitespace(text)


def clean_notice_program_name_text(value: object) -> str:
    text = clean_notice_text_brackets(value)
    if not text:
        return ""
    text = re.sub(r"^[【\[\(]?(?:선정(?:공고|결과)?|최종\s*선정|서류심사\s*결과|정량평가\s*결과)?[】\]\)]?\s*", "", text)
    text = strip_lp_round_suffix(text)
    for term in NOTICE_BUSINESS_STOP_TERMS:
        text = re.sub(rf"[\s,./｜|·-]*{re.escape(term)}.*$", "", text)
    text = re.sub(r"\s+출자사업\s*계획.*$", "", text)
    text = re.sub(r"\s+위탁운용사\s*선정\s*계획.*$", "", text)
    text = re.sub(r"\s+운용사\s*선정\s*계획.*$", "", text)
    text = re.sub(r"\s+공고문.*$", "", text)
    text = normalize_whitespace(text)
    text = strip_program_noise(text)
    text = strip_business_round_suffix(text)
    text = re.sub(r"\[.*?\]", "", text)
    text = text.replace("선정공고", "")
    text = text.replace("출자공고", "")
    text = normalize_whitespace(text).strip(" -·:;・")
    return cleanup_program_noise_prefix(text)


def clean_program_candidate(value: object) -> str:
    return clean_notice_program_name_text(value)


def program_candidates_from_brackets(raw: str, patterns: list[str]) -> list[str]:
    candidates: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, raw):
            candidate = clean_program_candidate(match.group(1))
            if candidate:
                candidates.append(candidate)
    return candidates


def program_candidates_from_tokens(raw: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(
        r"([가-힣A-Za-z0-9&·ㆍ\-\s]{2,90}(?:펀드|출자사업|투자조합|계정|리그|특정투자지주|전략펀드)(?:\([^)]*\))?)",
        raw,
    ):
        candidate = clean_program_candidate(match.group(1))
        if candidate:
            candidates.append(candidate)
    return candidates


def program_candidates(text: object) -> list[str]:
    raw = normalize_whitespace(text)
    if not raw:
        return []
    candidates: list[str] = []
    quote_patterns = [
        r"[「『\"]([^」』\"]{2,80}(?:펀드|출자사업|투자조합|계정|리그|분야)(?:\([^)]*\))?[^」』\"]*)[」』\"]",
        r"[\[【]([^\]】]{2,80}(?:펀드|출자사업|투자조합|계정|리그|분야)(?:\([^)]*\))?[^\]】]*)[\]】]",
    ]
    candidates.extend(program_candidates_from_brackets(raw, quote_patterns))
    titleish = re.split(r"(?:\n|\. | \| )", raw, maxsplit=1)[0]
    titleish = re.sub(r"^[^,，:：]{1,18}[,，:：]\s*", "", titleish)
    candidates.extend(program_candidates_from_tokens(titleish))
    candidates.extend(program_candidates_from_tokens(raw))
    cleaned: list[str] = []
    for candidate in candidates:
        value = clean_program_candidate(candidate)
        if value and value not in cleaned:
            cleaned.append(value)

    def score(value: str) -> tuple[int, int, int, str]:
        normalized = normalize_program_name_text(value)
        has_generic_core = 1 if normalized in GENERIC_PROGRAM_NAME_KEYS else 0
        long_bonus = -len(value)
        has_round = 1 if re.search(r"(\d+차|\d+호)", value) else 0
        return (has_generic_core, long_bonus, -has_round, value)

    cleaned.sort(key=score)
    return cleaned


def infer_program_name(text: object) -> str:
    normalized = normalize_whitespace(text)
    candidates = program_candidates(normalized)
    for candidate in candidates:
        if not is_generic_program_name(candidate):
            return candidate
    if candidates:
        return candidates[0]
    for generic in ["공급망안정화기금", "국민성장펀드", "농식품모태펀드", "농림수산식품모태펀드", "모태펀드"]:
        if generic in normalized:
            return "농식품모태펀드" if generic == "농림수산식품모태펀드" else generic
    return ""


def infer_round_name(text: object) -> str:
    raw = normalize_whitespace(text)
    patterns = [
        r"\((\d+차|\d+호)\)",
        r"(\d+차년도)",
        r"(\d+호)(?:\s*(?:출자|공고|선정|간접투자)?)?",
        r"(\d+차)(?:\s*(?:출자|공고|선정|간접투자|출항)?)?",
        r"(상반기|하반기|정시|수시)\s*(?:출자|공고|선정)?",
        r"(대형|중형|루키|도전|코스닥|M&A|세컨더리)\s*(?:리그|분야)",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            candidate = normalize_round_name(match.group(1))
            if candidate:
                return candidate
    return ""


def infer_round_name_with_fallback(text: object) -> str:
    raw = normalize_whitespace(text)
    round_name = infer_round_name(raw)
    if round_name:
        return round_name
    match = re.search(r"(\d+차년도|\d+차|\d+호)", raw, flags=re.IGNORECASE)
    if match:
        return normalize_round_name(match.group(1))
    return ""


def notice_platform_name(row: dict[str, object]) -> str:
    for key in ["program_name", "programName", "strategy", "title", "raw_excerpt", "rawExcerpt"]:
        text = normalize_whitespace(row.get(key))
        if not text:
            continue
        for generic in sorted(GENERIC_PROGRAM_NAMES, key=len, reverse=True):
            if generic in text:
                return generic
        inferred = infer_program_name(text)
        if inferred and is_generic_program_name(inferred):
            return inferred
    return ""


def infer_notice_program_name(row: dict[str, object]) -> str:
    stored = clean_program_candidate(row.get("program_name", row.get("programName")))
    best_title_candidate = ""
    for key in ["title", "displayTitle"]:
        title_text = normalize_whitespace(row.get(key))
        if not title_text:
            continue
        title_text = re.sub(r"^\([^)]*공고[^)]*\)\s*", "", title_text)
        title_specific_candidates = [
            clean_program_candidate(candidate)
            for candidate in program_candidates(title_text)
            if program_is_specific_and_not_platform_only(clean_program_candidate(candidate))
        ]
        if title_specific_candidates:
            candidate = max(title_specific_candidates, key=len)
            if len(candidate) > len(best_title_candidate):
                best_title_candidate = candidate
        title_fallback = clean_program_candidate(title_text)
        if (
            title_fallback
            and program_is_specific_and_not_platform_only(title_fallback)
            and any(term in title_text for term in ["운용사", "출자사업", "공모", "투자조합", "대체투자상품", "대체투자"])
        ):
            if len(title_fallback) > len(best_title_candidate):
                best_title_candidate = title_fallback
    if stored and program_is_specific_and_not_platform_only(stored):
        title_blob = business_key_text(" ".join(str(row.get(key) or "") for key in ["title", "displayTitle", "raw_excerpt", "rawExcerpt"]))
        stored_key = business_key_text(stored)
        if best_title_candidate and stored_key and stored_key not in title_blob:
            return best_title_candidate
        return stored
    if best_title_candidate:
        return best_title_candidate
    text = normalize_whitespace(
        " ".join(
            str(value or "")
            for value in [
                row.get("title", ""),
                row.get("displayTitle", ""),
                row.get("raw_excerpt", row.get("rawExcerpt", "")),
                row.get("program_name", row.get("programName", "")),
                row.get("round_name", row.get("roundName", "")),
            ]
        )
    )
    specific_candidates: list[str] = []
    generic_candidates: list[str] = []
    for candidate in program_candidates(text):
        cleaned = clean_program_candidate(candidate)
        if not cleaned:
            continue
        if program_is_specific_and_not_platform_only(cleaned):
            specific_candidates.append(cleaned)
        elif cleaned not in generic_candidates:
            generic_candidates.append(cleaned)
    if specific_candidates:
        return max(specific_candidates, key=len)
    specific = max(generic_candidates, key=len, default="")
    if specific and specific not in GENERIC_PROGRAM_NAMES and specific != "-":
        return specific
    if stored:
        return stored
    for generic in ["공급망안정화기금", "국민성장펀드", "농식품모태펀드", "농림수산식품모태펀드", "모태펀드"]:
        if generic in text:
            return "농식품모태펀드" if generic == "농림수산식품모태펀드" else generic
    return ""


def infer_notice_round_name(row: dict[str, object]) -> str:
    text = normalize_whitespace(
        " ".join(str(value or "") for value in [row.get("title", ""), row.get("displayTitle", ""), row.get("raw_excerpt", row.get("rawExcerpt", ""))])
    )
    searchable_text = re.sub(r"\([^)]*공고\s*제?\s*\d{4}[-\s]?\d+호?[^)]*\)", " ", text)
    searchable_text = re.sub(r"공고\s*제?\s*\d{4}[-\s]?\d+호?", " ", searchable_text)
    searchable_text = normalize_whitespace(searchable_text)
    text_round = infer_round_name_with_fallback(searchable_text)
    if text_round:
        return text_round
    stored_round = normalize_round_name(row.get("round_name", row.get("roundName")))
    if stored_round and re.search(re.escape(stored_round), searchable_text):
        return stored_round
    stored_program = clean_program_candidate(row.get("program_name", row.get("programName")))
    if stored_round and program_is_specific_and_not_platform_only(stored_program):
        return stored_round
    return ""


def business_key_text(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", normalize_whitespace(value)).lower()


def notice_business_key(row: dict[str, object]) -> str:
    program = infer_notice_program_name(row)
    if not program:
        text = normalize_whitespace(
            " ".join(
                str(row.get(key) or "")
                for key in ["title", "program_name", "programName", "round_name", "roundName", "raw_excerpt", "rawExcerpt"]
            )
        )
        program = infer_program_name(text)
    round_name = infer_notice_round_name(row)
    if not program:
        return ""
    program_key = business_key_text(program)
    round_key = business_key_text(round_name)
    return f"{program_key}|{round_key}" if round_key else program_key


def notice_program_specificity(row: dict[str, object]) -> int:
    text = normalize_whitespace(
        " ".join(
            str(value or "")
            for value in [
                row.get("title", ""),
                row.get("raw_excerpt", row.get("rawExcerpt", "")),
                row.get("program_name", row.get("programName", "")),
                row.get("round_name", row.get("roundName", "")),
            ]
        )
    )
    inferred = infer_program_name(text)
    candidate = clean_program_candidate(row.get("program_name", row.get("programName")))
    for value in [candidate, inferred]:
        if value and not is_generic_program_name(value):
            return 1
    return 0


def notice_identity(row: dict[str, object]) -> LpNoticeIdentity:
    program_name = infer_notice_program_name(row)
    round_name = infer_notice_round_name(row)
    platform_name = notice_platform_name(row)
    program_key = business_key_text(program_name)
    round_key = business_key_text(round_name)
    business_key = f"{program_key}|{round_key}" if program_key and round_key else program_key
    return LpNoticeIdentity(
        program_name=program_name,
        round_name=round_name,
        platform_name=platform_name,
        program_key=program_key,
        round_key=round_key,
        business_key=business_key,
        specificity=notice_program_specificity(row),
    )


def notice_specific_map_key(lp_code: str, round_key: str, platform_key: str) -> tuple[str, str, str]:
    return (lp_code, round_key, platform_key)


def extract_notice_program_candidates(text: str) -> list[str]:
    candidates = program_candidates(text)
    deduped: list[str] = []
    for candidate in candidates:
        cleaned = clean_program_candidate(candidate)
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped


# Compatibility aliases keep existing call sites readable during the staged refactor.
_notice_platform_name = notice_platform_name
_notice_specific_map_key = notice_specific_map_key
_strip_lp_round_suffix = strip_lp_round_suffix
_normalize_program_name_text = normalize_program_name_text
_strip_business_round_suffix = strip_business_round_suffix
_strip_program_noise = strip_program_noise
_program_is_business_specific = program_is_business_specific
_program_is_specific_and_not_platform_only = program_is_specific_and_not_platform_only
_cleanup_program_noise_prefix = cleanup_program_noise_prefix
_extract_notice_program_candidates = extract_notice_program_candidates
_program_candidates_from_brackets = program_candidates_from_brackets
_program_candidates_from_tokens = program_candidates_from_tokens
_notice_program_specificity = notice_program_specificity
