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
