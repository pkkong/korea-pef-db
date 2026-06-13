#!/usr/bin/env python
"""Create optional AI enrichment data for the public newsletter.

The daily publisher must keep working even when external AI tools are missing.
This script therefore writes the same JSON contract in local mode, while also
supporting NotebookLM CLI or a custom command as an optional provider.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from daily_news_common import (
    DEFAULT_EXPORT_DIR,
    clean_investment_memo_summary_line,
    clean_investment_memo_summary_lines,
    normalize_whitespace,
    today_seoul,
)


SECTION_CHOICES = ("AI_PE", "NationalGrowthFund", "Deal", "LP", "GP", "Market")
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_NOTEBOOKLM_REVIEW_QUERY_LIMIT = 1
SCRIPT_PATH = Path(__file__).resolve()
SERVICE_ROOT = SCRIPT_PATH.parents[1]
DEFAULT_CLASSIFICATION_RULES = SERVICE_ROOT / "data" / "newsletter_classification_rules.md"


class NotebookLMReviewError(RuntimeError):
    def __init__(self, message: str, metadata: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.metadata = metadata or {}


def compact_date(value: str) -> str:
    return str(value or "").replace("-", "")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Missing review queue: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def title_fallback_summary_lines(title: object) -> list[str]:
    title_text = normalize_whitespace(str(title or ""))
    if len(title_text) < 8:
        return []
    simplified = re.sub(r"^\[[^\]]+\]\s*", "", title_text).strip(" \"“”‘’")
    candidates: list[str] = []
    if "본입찰" in simplified and "참여" in simplified:
        asset = re.split(r"\s*매각\s*", simplified, maxsplit=1)[0].strip(" \"“”‘’,")
        candidates.append(f"{asset} 매각 본입찰 경쟁 구도" if asset else "매각 본입찰 경쟁 구도")
    private_credit_match = re.search(r"(기준\s*강화|리스크|시장|스프레드)", simplified) if "사모대출" in simplified else None
    if private_credit_match:
        if "기준" in private_credit_match.group(1):
            candidates.append("사모대출 운용사 대출 심사 기준 강화")
        else:
            candidates.append("사모대출 시장 리스크 점검")
    if "투자유치" in simplified:
        company = re.split(r"[,，]|투자유치", simplified, maxsplit=1)[0].strip(" \"“”‘’")
        candidates.append(f"{company} 투자유치 거래 이벤트" if company else "투자유치 거래 이벤트")
    if "매각" in simplified and not candidates:
        asset = re.split(r"\s*매각\s*", simplified, maxsplit=1)[0].strip(" \"“”‘’,")
        candidates.append(f"{asset} 매각 프로세스 업데이트" if asset else "매각 프로세스 업데이트")
    if "펀드" in simplified and not candidates:
        candidates.append("펀드 조성·운용 업데이트")

    lines: list[str] = []
    for candidate in candidates:
        line = clean_investment_memo_summary_line(candidate, title_text, max_length=64)
        if line and line not in lines:
            lines.append(line)
        if len(lines) >= 2:
            break
    return lines


def memo_summary_lines(value: object, title: object = "") -> list[str]:
    text = normalize_whitespace(str(value or ""))
    title_text = normalize_whitespace(str(title or ""))
    if not text or len(text) < 8:
        return title_fallback_summary_lines(title)
    text_key = re.sub(r"[\s·ㆍ.,()\\[\\]{}'\"`]+", "", text).lower()
    title_key = re.sub(r"[\s·ㆍ.,()\\[\\]{}'\"`]+", "", title_text).lower()
    if title_key and text_key == title_key:
        return title_fallback_summary_lines(title)
    text = re.sub(r"\[[^\]]*본 기사는[^\]]*\]", " ", text)
    text = re.sub(r"이 기사는\s*20\d{2}년\s*\d{1,2}월\s*\d{1,2}일[^.。]*", " ", text)
    text = re.sub(r"▲[^.。]{0,80}", " ", text)
    text = normalize_whitespace(text)
    parts = [
        normalize_whitespace(part)
        for part in re.split(
            r"(?<=[!?。])(?=\s*[가-힣A-Z0-9\"“‘<])\s*|(?<=\.)(?=\s*[가-힣A-Z\"“‘<])\s*|(?<=\.)\s+(?=[0-9])|…\s*|\s{2,}|\s*[;；]\s*",
            text,
        )
        if normalize_whitespace(part)
    ]
    if len(parts) <= 1:
        parts = [
            normalize_whitespace(part)
            for part in re.split(r"\s*,\s*(?=[가-힣A-Za-z0-9]{2,})", text)
            if normalize_whitespace(part)
        ]
    lines: list[str] = []
    for part in parts:
        line = part.strip(" \t\r\n-–—·,.;:。")
        line = re.sub(r"^\[[^\]]+\]\s*", "", line)
        line = clean_investment_memo_summary_line(line, title, max_length=64)
        if len(line) < 8:
            continue
        if line not in lines:
            lines.append(line)
        if len(lines) >= 3:
            break
    return lines or title_fallback_summary_lines(title)


def base_article(row: dict[str, str]) -> dict[str, Any]:
    return {
        "news_id": row.get("news_id", ""),
        "title": row.get("title", ""),
        "publisher": row.get("publisher", ""),
        "source_url": row.get("source_url", ""),
        "normalized_source_url": row.get("normalized_source_url", ""),
        "current_category": row.get("current_category", ""),
        "section_tags": row.get("section_tags", ""),
        "topic_tags": row.get("topic_tags", ""),
        "gp_names": row.get("gp_names", ""),
        "summary_text": row.get("summary_text", ""),
    }


def local_enrich(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    for row in rows:
        article = base_article(row)
        article.update(
            {
                "provider": "local-rule",
                "section_suggestion": row.get("section_tags") or "",
                "section_suggestion_raw": row.get("section_tags") or "",
                "suggestion_status": "ok",
                "summary_lines": memo_summary_lines(row.get("summary_text", ""), row.get("title", "")),
                "confidence": 0.0,
            }
        )
        articles.append(article)
    return articles


def enrichment_prompt(report_date: str, rows: list[dict[str, str]]) -> str:
    payload = {
        "task": "Korea PEF newsletter enrichment",
        "report_date": report_date,
        "instructions": [
            "Return strict JSON only, no markdown.",
            "For each article, choose section_suggestion from AI_PE, NationalGrowthFund, Deal, LP, GP, Market.",
            "Classify by the article's main subject, not by incidental keywords.",
            "AI_PE only when AI is the investment/market theme itself; if the main subject is GP fundraising, choose GP.",
            "NationalGrowthFund only when the fund program itself is the main subject; if a GP's fundraising strategy is the subject, choose GP.",
            "Deal is for a specific acquisition, sale, financing, IPO, block trade, or transaction process.",
            "LP is for allocator activity such as LP commitments, CIO changes, pension/fund allocation, and mandate selection.",
            "GP is for managers, fund closes, GP fundraising, GP strategy, GP personnel, and GP-level performance.",
            "Market is for regulation, market structure, private credit market commentary, conferences, and broad trend pieces.",
            "Write summary_lines in Korean, 3 short lines when the article has enough information; use 2 lines rather than inventing missing facts.",
            "Do not use casual newsletter/Newneek-style narration; the reader is an investment professional scanning deal flow.",
            "Use clipped memo-style fragments, not full article prose; avoid friendly commentary, rhetorical questions, or emoji-like tone.",
            "Prefer this order: line 1 event, line 2 numbers/parties/status, line 3 why it matters for PE, LP, or GP readers.",
            "Do not repeat the article title as a summary line.",
            "Avoid endings such as 했다, 전망이다, 사례다, 했어요, 해요, 입니다.",
            "Use gp_names/lp_names only when the article clearly names those entities.",
        ],
        "known_error_examples": [
            {"title_pattern": "국민성장펀드 잡은 IMM…레버리지는 없다", "section": "GP", "reason": "국민성장펀드보다 GP 펀드레이징 전략이 본문 주제"},
            {"title_pattern": "2000억대 체급 깬 대신PE AI·반도체 4000억 펀드 시동", "section": "GP", "reason": "AI 키워드보다 GP 블라인드펀드 조성이 본문 주제"},
            {"title_pattern": "목표액 2배로 모았다 엑시나 2000억 투자유치", "section": "Deal", "reason": "운용사 펀드레이징이 아니라 특정 회사 투자유치 거래"},
            {"title_pattern": "GP 스테이크", "section": "Market", "reason": "특정 운용사 소식보다 운용사 지분투자 시장 구조"},
            {"title_pattern": "사모대출 시장 경고등", "section": "Market", "reason": "특정 딜이 아니라 시장 코멘터리"},
            {"title_pattern": "해외 사모대출 56조", "section": "Market", "reason": "특정 LP 출자나 딜이 아니라 금융권 사모대출 시장 점검"},
            {"title_pattern": "키움인베 600억 벤처모펀드 출격", "section": "GP", "reason": "운용사 펀드 조성 기사"},
            {"title_pattern": "법원, 고려아연에 투자 관련 문서 제출 명령", "section": "Market", "reason": "LP 출자활동이 아니라 분쟁/거버넌스 이슈"},
        ],
        "schema": {
            "articles": [
                {
                    "news_id": "string",
                    "section_suggestion": "AI_PE|NationalGrowthFund|Deal|LP|GP|Market",
                    "summary_lines": ["string", "string", "string"],
                    "gp_names": ["string"],
                    "lp_names": ["string"],
                    "confidence": 0.0,
                    "notes": "short internal reason",
                }
            ]
        },
        "articles": [base_article(row) for row in rows],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def notebooklm_source_pack_text(report_date: str, rows: list[dict[str, str]]) -> str:
    lines = [
        f"# KPEF Newsletter Source Pack - {report_date}",
        "",
        "This source pack is generated from the newsletter review queue.",
        "Use it as the authoritative article packet for summary and classification.",
        "",
        "## Classification Choices",
        "",
        "- AI_PE",
        "- NationalGrowthFund",
        "- Deal",
        "- LP",
        "- GP",
        "- Market",
        "",
        "## Articles",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        title = normalize_whitespace(row.get("title", ""))
        url = normalize_whitespace(row.get("normalized_source_url") or row.get("source_url", ""))
        publisher = normalize_whitespace(row.get("publisher", ""))
        summary = normalize_whitespace(row.get("summary_text", ""))
        current_section = normalize_whitespace(row.get("section_tags") or row.get("current_category", ""))
        candidate_tags = normalize_whitespace(row.get("topic_tags", ""))
        gp_names = normalize_whitespace(row.get("gp_names", ""))
        published_at = normalize_whitespace(row.get("published_at") or row.get("published") or row.get("published_at_iso", ""))
        news_id = normalize_whitespace(row.get("news_id", ""))
        excerpt = normalize_whitespace(
            row.get("body_excerpt")
            or row.get("excerpt")
            or row.get("snippet")
            or row.get("description")
            or summary
        )
        lines.extend(
            [
                f"### Article {index}: {title or news_id or url}",
                "",
                f"- news_id: {news_id}",
                f"- url: {url}",
                f"- publisher: {publisher}",
                f"- published_at: {published_at}",
                f"- current_section: {current_section}",
                f"- candidate_tags: {candidate_tags}",
                f"- gp_names: {gp_names}",
                "",
                "#### Excerpt",
                "",
                excerpt[:2400] if excerpt else "(no excerpt available)",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def notebooklm_review_question(report_date: str, rows: list[dict[str, str]]) -> str:
    article_ids = [str(row.get("news_id") or "").strip() for row in rows]
    return (
        f"You are reviewing the KPEF daily newsletter for {report_date}.\n"
        "Use only the uploaded classification rules and source pack.\n"
        "For every article in the source pack, Return strict JSON only with this exact top-level schema:\n"
        "{\n"
        '  "articles": [\n'
        "    {\n"
        '      "news_id": "same news_id from source pack",\n'
        '      "section_suggestion": "AI_PE | NationalGrowthFund | Deal | LP | GP | Market",\n'
        '      "summary_lines": ["Korean memo line 1", "Korean memo line 2", "Korean memo line 3"],\n'
        '      "short_summary_100": "Korean summary within 100 characters",\n'
        '      "gp_names": [],\n'
        '      "lp_names": [],\n'
        '      "deal_targets": [],\n'
        '      "confidence": 0.0,\n'
        '      "notes": "one short Korean reason for classification"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Return one article object for every news_id below, in the same order.\n"
        "- Classify by the main subject, not incidental keywords.\n"
        "- Do not use full article prose endings such as 했다, 한다, 전망이다, 사례다.\n"
        "- Use concise investment memo fragments.\n"
        "- If information is thin, write two useful summary lines rather than inventing a third.\n"
        "- Do not include markdown fences or commentary outside JSON.\n\n"
        "Expected news_id order:\n"
        + "\n".join(f"- {news_id}" for news_id in article_ids if news_id)
    )


def write_notebooklm_source_files(
    *,
    out_dir: Path,
    report_date: str,
    rows: list[dict[str, str]],
    rules_path: Path = DEFAULT_CLASSIFICATION_RULES,
) -> dict[str, object]:
    dated = compact_date(report_date)
    source_dir = out_dir / "notebooklm_sources" / dated
    source_dir.mkdir(parents=True, exist_ok=True)
    source_pack = notebooklm_source_pack_text(report_date, rows)
    rules_text = rules_path.read_text(encoding="utf-8") if rules_path.exists() else fallback_classification_rules_text()
    source_pack_path = source_dir / f"daily_news_source_pack_{dated}.md"
    rules_out_path = source_dir / "newsletter_classification_rules.md"
    question_path = source_dir / f"notebooklm_review_question_{dated}.txt"
    source_pack_path.write_text(source_pack, encoding="utf-8")
    rules_out_path.write_text(rules_text.rstrip() + "\n", encoding="utf-8")
    question = notebooklm_review_question(report_date, rows)
    question_path.write_text(question + "\n", encoding="utf-8")
    fingerprint = hashlib.sha256(
        "\n---rules---\n".join([rules_text, source_pack, question]).encode("utf-8")
    ).hexdigest()
    metadata = {
        "report_date": report_date,
        "article_count": len(rows),
        "source_pack_path": str(source_pack_path),
        "rules_path": str(rules_out_path),
        "question_path": str(question_path),
        "source_pack_fingerprint": fingerprint,
    }
    metadata_path = source_dir / f"notebooklm_source_pack_{dated}.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        **metadata,
        "source_pack_text": source_pack,
        "rules_text": rules_text,
        "question": question,
        "source_pack_path_obj": source_pack_path,
        "rules_path_obj": rules_out_path,
        "question_path_obj": question_path,
        "metadata_path": str(metadata_path),
    }


def fallback_classification_rules_text() -> str:
    return """# KPEF Newsletter Classification Rules

Use one representative section per article.

## Sections

- AI_PE: AI is the investment or private market theme itself.
- NationalGrowthFund: the national growth fund program is the main subject.
- Deal: specific acquisition, sale, financing, IPO, block trade, or transaction process.
- LP: allocator activity, LP commitments, CIO changes, pension/fund allocation, mandate selection.
- GP: managers, GP fundraising, fund closes, GP strategy, GP personnel, GP-level performance.
- Market: regulation, market structure, private credit commentary, conferences, broad trend pieces.

Classify by the main subject. Incidental keywords do not control the section.
"""


def cached_notebooklm_payload(out_dir: Path, report_date: str, fingerprint: str) -> dict[str, Any] | None:
    dated = compact_date(report_date)
    output_path = out_dir / f"daily_news_ai_enrichment_{dated}.json"
    if not output_path.exists():
        return None
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if payload.get("provider") != "notebooklm-notebook":
        return None
    if payload.get("source_pack_fingerprint") != fingerprint:
        return None
    if not isinstance(payload.get("articles"), list):
        return None
    return payload


def section_from_source_row(row: dict[str, str]) -> str:
    section = str(row.get("section_tags") or "").split(",", 1)[0].strip()
    return section or str(row.get("current_category") or "").strip()


def audit_rows(articles: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for article in articles:
        current = section_from_source_row({key: str(article.get(key) or "") for key in ["section_tags", "current_category"]})
        suggestion = str(article.get("section_suggestion") or "").strip()
        suggestion_status = str(article.get("suggestion_status") or "").strip()
        status = suggestion_status or ("conflict" if suggestion and current and suggestion != current else "ok")
        rows.append(
            {
                "news_id": str(article.get("news_id") or ""),
                "title": str(article.get("title") or ""),
                "current_section": current,
                "section_suggestion": suggestion,
                "section_suggestion_raw": str(article.get("section_suggestion_raw") or ""),
                "suggestion_status": suggestion_status,
                "status": status,
                "confidence": str(article.get("confidence") or ""),
                "notes": str(article.get("notes") or ""),
                "source_url": str(article.get("source_url") or ""),
            }
        )
    return rows


def write_audit_files(out_dir: Path, report_date: str, provider: str, articles: list[dict[str, Any]], write_latest: bool) -> None:
    dated = compact_date(report_date)
    rows = audit_rows(articles)
    headers = [
        "news_id",
        "title",
        "current_section",
        "section_suggestion",
        "section_suggestion_raw",
        "suggestion_status",
        "status",
        "confidence",
        "notes",
        "source_url",
    ]
    csv_path = out_dir / f"daily_news_ai_enrichment_audit_{dated}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    conflicts = [row for row in rows if row["status"] == "conflict"]
    md_lines = [
        f"# Daily News AI Enrichment Audit - {report_date}",
        "",
        f"- provider: {provider}",
        f"- articles: {len(rows)}",
        f"- conflicts: {len(conflicts)}",
        "",
    ]
    if conflicts:
        md_lines.append("## Conflicts")
        md_lines.append("")
        for row in conflicts:
            md_lines.append(
                f"- {row['current_section']} -> {row['section_suggestion']} | {row['title']} | {row['notes']}".rstrip()
            )
    else:
        md_lines.append("No AI classification conflicts.")
    md_path = out_dir / f"daily_news_ai_enrichment_audit_{dated}.md"
    md_path.write_text("\n".join(md_lines).rstrip() + "\n", encoding="utf-8")
    if write_latest:
        (out_dir / "daily_news_ai_enrichment_audit_latest.csv").write_text(csv_path.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
        (out_dir / "daily_news_ai_enrichment_audit_latest.md").write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")


def extract_json_object(value: str) -> dict[str, Any]:
    text = value.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("AI enrichment output must be a JSON object")
    if "articles" not in data and isinstance(data.get("answer"), str):
        return extract_json_object(str(data["answer"]))
    return data


def normalize_ai_articles(data: dict[str, Any], source_rows: list[dict[str, str]], provider: str) -> list[dict[str, Any]]:
    raw_articles = data.get("articles")
    if not isinstance(raw_articles, list):
        raise ValueError("AI enrichment output missing articles list")
    raw_by_id = {
        str(raw.get("news_id") or ""): raw
        for raw in raw_articles
        if isinstance(raw, dict) and str(raw.get("news_id") or "")
    }
    articles: list[dict[str, Any]] = []
    for index, source in enumerate(source_rows):
        raw = raw_by_id.get(str(source.get("news_id") or ""))
        if raw is None and index < len(raw_articles) and isinstance(raw_articles[index], dict):
            raw = raw_articles[index]
        if not isinstance(raw, dict):
            raw = {}
        article = base_article(source)
        raw_section = str(raw.get("section_suggestion") or raw.get("section") or "").strip()
        section = raw_section if raw_section in SECTION_CHOICES else ""
        current_section = section_from_source_row(source)
        if section:
            suggestion_status = "conflict" if current_section and section != current_section else "ok"
        elif raw_section:
            suggestion_status = "invalid"
        else:
            suggestion_status = "missing"
        summary_lines = raw.get("summary_lines") or raw.get("summaryLines") or []
        if isinstance(summary_lines, str):
            summary_lines = [part.strip() for part in re.split(r"\n+|\s*\|\s*", summary_lines) if part.strip()]
        cleaned_summary_lines = clean_investment_memo_summary_lines(summary_lines, article.get("title", ""), limit=3)
        if not cleaned_summary_lines:
            cleaned_summary_lines = memo_summary_lines(source.get("summary_text", ""), source.get("title", ""))
        article.update(
            {
                "provider": provider,
                "section_suggestion": section,
                "section_suggestion_raw": raw_section,
                "suggestion_status": suggestion_status,
                "summary_lines": cleaned_summary_lines,
                "gp_names_ai": raw.get("gp_names") if isinstance(raw.get("gp_names"), list) else [],
                "lp_names_ai": raw.get("lp_names") if isinstance(raw.get("lp_names"), list) else [],
                "confidence": raw.get("confidence", ""),
                "notes": normalize_whitespace(str(raw.get("notes") or "")),
            }
        )
        articles.append(article)
    return articles


def command_enrich(command: str, prompt: str, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"command failed with exit {completed.returncode}")
    return normalize_ai_articles(extract_json_object(completed.stdout), rows, "command")


def resolve_nlm_bin(value: str = "") -> str:
    candidates = [value, os.environ.get("NEWSLETTER_NLM_BIN", ""), "nlm"]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        if "/" in text:
            path = Path(text).expanduser()
            if path.exists() and os.access(path, os.X_OK):
                return str(path)
        else:
            found = shutil.which(text)
            if found:
                return found
    return ""


def run_nlm_command(args: list[str], *, nlm_bin: str = "", profile: str = "", timeout: int = 120) -> str:
    resolved = resolve_nlm_bin(nlm_bin)
    if not resolved:
        raise RuntimeError("nlm command is not installed. Install notebooklm-mcp-cli and run nlm login first.")
    command = [resolved, *args]
    if profile:
        command.extend(["--profile", profile])
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = normalize_whitespace(completed.stderr or completed.stdout)
        raise RuntimeError(detail or f"nlm command failed with exit {completed.returncode}: {' '.join(args)}")
    return completed.stdout


def notebooklm_readiness(nlm_bin: str = "", profile: str = "", timeout: int = 30) -> tuple[bool, str]:
    try:
        output = run_nlm_command(["login", "--check"], nlm_bin=nlm_bin, profile=profile, timeout=timeout)
    except RuntimeError as exc:
        return False, str(exc)
    return True, normalize_whitespace(output) or "NotebookLM CLI ready"


def parse_notebook_id_from_create(output: str) -> str:
    text = output.strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        for key in ("id", "notebook_id", "notebookId"):
            if data.get(key):
                return str(data[key])
    match = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", text)
    return match.group(0) if match else ""


def notebooklm_list_notebooks(nlm_bin: str = "", profile: str = "", timeout: int = 60) -> list[dict[str, Any]]:
    try:
        output = run_nlm_command(["notebook", "list", "--json"], nlm_bin=nlm_bin, profile=profile, timeout=timeout)
        data = json.loads(output)
    except (RuntimeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def notebooklm_find_notebook_by_title(title: str, nlm_bin: str = "", profile: str = "") -> str:
    for row in notebooklm_list_notebooks(nlm_bin, profile):
        if isinstance(row, dict) and str(row.get("title") or "") == title and row.get("id"):
            return str(row["id"])
    return ""


def notebooklm_create_notebook(title: str, nlm_bin: str = "", profile: str = "", timeout: int = 60) -> str:
    output = run_nlm_command(["notebook", "create", title, "--json"], nlm_bin=nlm_bin, profile=profile, timeout=timeout)
    notebook_id = parse_notebook_id_from_create(output)
    if not notebook_id:
        raise RuntimeError("Could not parse NotebookLM notebook id from create output")
    return notebook_id


def notebooklm_add_file_source(
    notebook_id: str,
    path: Path,
    *,
    nlm_bin: str = "",
    profile: str = "",
    timeout: int = 600,
) -> None:
    run_nlm_command(
        ["source", "add", notebook_id, "--file", str(path), "--wait", "--wait-timeout", str(timeout)],
        nlm_bin=nlm_bin,
        profile=profile,
        timeout=max(timeout + 30, 120),
    )


def notebooklm_query_once(
    notebook_id: str,
    question: str,
    *,
    nlm_bin: str = "",
    profile: str = "",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    output = run_nlm_command(
        ["notebook", "query", notebook_id, question, "--json", "--timeout", str(timeout)],
        nlm_bin=nlm_bin,
        profile=profile,
        timeout=max(timeout + 30, DEFAULT_TIMEOUT_SECONDS),
    )
    return extract_json_object(output)


def notebooklm_enrich_daily_notebook(
    *,
    report_date: str,
    rows: list[dict[str, str]],
    out_dir: Path,
    timeout: int,
    nlm_bin: str = "",
    profile: str = "",
    notebook_id: str = "",
    rules_path: Path = DEFAULT_CLASSIFICATION_RULES,
) -> tuple[list[dict[str, Any]], str, dict[str, object]]:
    source_files = write_notebooklm_source_files(
        out_dir=out_dir,
        report_date=report_date,
        rows=rows,
        rules_path=rules_path,
    )
    fingerprint = str(source_files["source_pack_fingerprint"])
    cached = cached_notebooklm_payload(out_dir, report_date, fingerprint)
    if cached:
        return list(cached["articles"]), str(source_files["question"]), {
            **source_files,
            "cache_hit": True,
            "notebook_id": str(cached.get("notebook_id") or ""),
            "notebook_title": str(cached.get("notebook_title") or ""),
        }

    title = f"KPEF Newsletter Review {report_date}"
    actual_notebook_id = ""
    try:
        actual_notebook_id = notebook_id or notebooklm_find_notebook_by_title(title, nlm_bin, profile)
        if not actual_notebook_id:
            actual_notebook_id = notebooklm_create_notebook(title, nlm_bin, profile, timeout=min(timeout, 120))
        notebooklm_add_file_source(
            actual_notebook_id,
            Path(str(source_files["rules_path_obj"])),
            nlm_bin=nlm_bin,
            profile=profile,
        )
        notebooklm_add_file_source(
            actual_notebook_id,
            Path(str(source_files["source_pack_path_obj"])),
            nlm_bin=nlm_bin,
            profile=profile,
        )
        data = notebooklm_query_once(
            actual_notebook_id,
            str(source_files["question"]),
            nlm_bin=nlm_bin,
            profile=profile,
            timeout=timeout,
        )
    except RuntimeError as exc:
        raise NotebookLMReviewError(
            str(exc),
            {
                **source_files,
                "cache_hit": False,
                "notebook_id": actual_notebook_id,
                "notebook_title": title,
            },
        ) from exc
    articles = normalize_ai_articles(data, rows, "notebooklm-notebook")
    return articles, str(source_files["question"]), {
        **source_files,
        "cache_hit": False,
        "notebook_id": actual_notebook_id,
        "notebook_title": title,
    }


def write_outputs(
    *,
    out_dir: Path,
    report_date: str,
    provider: str,
    rows: list[dict[str, str]],
    articles: list[dict[str, Any]],
    prompt: str,
    write_latest: bool,
    metadata: dict[str, object] | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dated = compact_date(report_date)
    payload = {
        "report_date": report_date,
        "provider": provider,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "article_count": len(articles),
        "articles": articles,
    }
    if metadata:
        for key, value in metadata.items():
            if key.endswith("_obj") or key in {"source_pack_text", "rules_text", "question"}:
                continue
            payload[key] = value
    output_path = out_dir / f"daily_news_ai_enrichment_{dated}.json"
    prompt_path = out_dir / f"daily_news_ai_enrichment_prompt_{dated}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    if write_latest:
        (out_dir / "daily_news_ai_enrichment_latest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_dir / "daily_news_ai_enrichment_prompt_latest.json").write_text(prompt + "\n", encoding="utf-8")
    write_audit_files(out_dir, report_date, provider, articles, write_latest)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build optional AI enrichment data for daily PEF newsletter articles")
    parser.add_argument("--date", default=today_seoul())
    parser.add_argument("--review-file", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--provider", default=os.environ.get("NEWSLETTER_AI_PROVIDER", "local"))
    parser.add_argument("--command", default=os.environ.get("NEWSLETTER_AI_COMMAND", ""))
    parser.add_argument("--notebook-id", default=os.environ.get("NEWSLETTER_NOTEBOOKLM_NOTEBOOK_ID", ""))
    parser.add_argument("--nlm-bin", default=os.environ.get("NEWSLETTER_NLM_BIN", ""))
    parser.add_argument("--nlm-profile", default=os.environ.get("NEWSLETTER_NLM_PROFILE", ""))
    parser.add_argument("--classification-rules", type=Path, default=DEFAULT_CLASSIFICATION_RULES)
    parser.add_argument("--notebooklm-review-query-limit", type=int, default=int(os.environ.get("NEWSLETTER_NOTEBOOKLM_REVIEW_QUERY_LIMIT", str(DEFAULT_NOTEBOOKLM_REVIEW_QUERY_LIMIT))))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("NEWSLETTER_AI_TIMEOUT_SECONDS", "180")))
    parser.add_argument("--strict", action="store_true", default=os.environ.get("NEWSLETTER_AI_STRICT", "0") == "1")
    parser.add_argument("--check-only", action="store_true", help="Check provider readiness without reading or writing news artifacts")
    parser.add_argument("--no-latest", action="store_true")
    args = parser.parse_args()

    provider = str(args.provider or "local").strip().lower()
    if provider in {"off", "none", "0", "false"}:
        print("ai_enrichment_status=skipped")
        return 0
    if args.check_only:
        if provider in {"local", "local-rule", "fallback"}:
            print("ai_enrichment_check=ok provider=local-rule")
            return 0
        if provider in {"command", "custom"}:
            if args.command:
                print("ai_enrichment_check=ok provider=command")
                return 0
            print("ai_enrichment_check=fail provider=command reason=missing_command")
            return 1
        if provider in {"notebooklm", "notebooklm-cli", "nlm"}:
            ok, message = notebooklm_readiness(args.nlm_bin, args.nlm_profile, min(args.timeout, 60))
            print(f"ai_enrichment_check={'ok' if ok else 'fail'} provider=notebooklm message={message}")
            return 0 if ok else 1
        print(f"ai_enrichment_check=fail provider={args.provider} reason=unknown_provider")
        return 1
    review_file = args.review_file or args.out_dir / f"daily_news_review_queue_{compact_date(args.date)}.csv"
    rows = read_csv(review_file)
    prompt = enrichment_prompt(args.date, rows)
    metadata: dict[str, object] = {}
    if provider in {"local", "local-rule", "fallback"}:
        articles = local_enrich(rows)
        provider_name = "local-rule"
    elif provider in {"command", "custom"}:
        if not args.command:
            raise SystemExit("--command or NEWSLETTER_AI_COMMAND is required for command provider")
        articles = command_enrich(args.command, prompt, rows)
        provider_name = "command"
    elif provider in {"notebooklm", "notebooklm-cli", "nlm"}:
        if args.notebooklm_review_query_limit != 1:
            raise SystemExit("--notebooklm-review-query-limit must be 1 for date-notebook review mode")
        try:
            articles, prompt, metadata = notebooklm_enrich_daily_notebook(
                report_date=args.date,
                rows=rows,
                out_dir=args.out_dir,
                timeout=args.timeout,
                nlm_bin=args.nlm_bin,
                profile=args.nlm_profile,
                notebook_id=args.notebook_id,
                rules_path=args.classification_rules,
            )
            provider_name = "notebooklm-notebook"
        except RuntimeError as exc:
            if args.strict:
                raise
            articles = local_enrich(rows)
            provider_name = "local-rule"
            error_metadata = exc.metadata if isinstance(exc, NotebookLMReviewError) else {}
            metadata = {
                **error_metadata,
                "fallback_from": "notebooklm-notebook",
                "fallback_reason": normalize_whitespace(str(exc))[:1000],
            }
    elif provider in {"notebooklm-batch", "notebooklm-cli-batch", "nlm-batch"}:
        raise SystemExit("NotebookLM batch query mode is disabled. Use provider=notebooklm for one date notebook review.")
    else:
        raise SystemExit(f"Unknown AI provider: {args.provider}")
    output_path = write_outputs(
        out_dir=args.out_dir,
        report_date=args.date,
        provider=provider_name,
        rows=rows,
        articles=articles,
        prompt=prompt,
        write_latest=not args.no_latest,
        metadata=metadata,
    )
    print(f"ai_enrichment_status=ok provider={provider_name} articles={len(articles)} output={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
