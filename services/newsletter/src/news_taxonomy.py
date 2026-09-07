"""Canonical public taxonomy contract for newsletter articles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


TAG_TAXONOMY_VERSION = "news-taxonomy-v1"

SECTION_LABELS = {
    "AI_PE": "AI & PE",
    "NationalGrowthFund": "국민성장펀드",
    "Deal": "Deal",
    "LP": "LP",
    "GP": "GP",
    "Market": "Market",
}
SECTION_LABEL_TO_CODE = {label: code for code, label in SECTION_LABELS.items()}
PRIMARY_TOPIC_BY_SECTION = {
    "AI_PE": "AI_PE",
    "NationalGrowthFund": "NationalGrowthFund",
    "Deal": "Deal",
    "LP": "LP",
    "GP": "GP",
}
PRIMARY_SECTION_TOPICS = set(PRIMARY_TOPIC_BY_SECTION.values())


DEAL_FINANCING_KEYWORDS = [
    "리캡", "인수금융", "리파이낸싱", "사모대출", "프라이빗크레딧",
    "private credit", "메자닌", "DIP", "전환사채", "CB", "대출", "파이낸싱",
]
DEAL_ISSUE_KEYWORDS = ["무산", "분쟁", "소송", "가격 이견", "리스크", "부실", "시끌", "장고"]

# Rendering and publication validation must use the same conflict precedence.
# For example, a distressed restructuring story is Issue before Ownership;
# a recap story remains Financing even when its title also mentions value-up.
DEAL_SUBCATEGORY_RULES = (
    ("Financing", DEAL_FINANCING_KEYWORDS),
    ("Secondary", ["세컨더리", "컨티뉴에이션", "continuation"]),
    ("Issue", DEAL_ISSUE_KEYWORDS),
    ("Ownership", ["밸류업", "PMI", "구조조정", "턴어라운드", "운영 개선", "실적", "수익성", "수익성 개선", "손본다", "숨겨진 가치", "가치 재평가", "재평가"]),
    ("Signing·Closing", ["SPA", "본계약", "계약 체결", "클로징", "자금 납입", "마무리", "완료"]),
    ("Auction", ["입찰", "우선협상", "숏리스트", "주관사", "매각주관", "원매자", "인수의향", "제안"]),
    ("Exit", ["엑시트", "회수", "매각", "IPO", "블록딜", "청산"]),
)


def deal_subcategory(text: str) -> str:
    """Return the first explicit Deal subtype signal, or no signal."""
    lowered = text.lower()
    for category, keywords in DEAL_SUBCATEGORY_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return category
    return ""


@dataclass(frozen=True)
class NewsClassification:
    section: str
    topic_tags: tuple[str, ...]
    gp_entities: tuple[str, ...] = ()
    lp_entities: tuple[str, ...] = ()
    tag_version: str = TAG_TAXONOMY_VERSION


def split_tag_values(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_values = [str(item or "") for item in value]
    else:
        raw_values = str(value or "").replace(";", ",").split(",")
    return [part.strip() for part in raw_values if part and part.strip()]


def canonical_section(value: object) -> str:
    text = str(value or "").strip()
    return SECTION_LABEL_TO_CODE.get(text, text)


def dedupe_values(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def canonical_topic_values(section: object, topic_values: Iterable[object]) -> list[str]:
    section_code = canonical_section(section)
    values = [
        value
        for value in dedupe_values(topic_values)
        if value not in PRIMARY_SECTION_TOPICS or value == section_code
    ]
    primary_topic = PRIMARY_TOPIC_BY_SECTION.get(section_code)
    if primary_topic and primary_topic not in values:
        values.append(primary_topic)
    return values


def build_classification(
    *,
    section: object,
    topic_tags: Iterable[object] = (),
    gp_entities: Iterable[object] = (),
    lp_entities: Iterable[object] = (),
) -> NewsClassification:
    section_code = canonical_section(section) or "Market"
    return NewsClassification(
        section=section_code,
        topic_tags=tuple(canonical_topic_values(section_code, topic_tags)),
        gp_entities=tuple(dedupe_values(gp_entities)),
        lp_entities=tuple(dedupe_values(lp_entities)),
    )
