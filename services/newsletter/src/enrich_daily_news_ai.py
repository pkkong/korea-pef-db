#!/usr/bin/env python
"""Create optional AI enrichment data for the public newsletter.

The daily publisher must keep working even when external AI tools are missing.
This script therefore writes the same JSON contract in local mode, while also
supporting NotebookLM CLI or a custom command as an optional provider.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
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
DEFAULT_NOTEBOOKLM_BATCH_SIZE = 5
DEFAULT_NOTEBOOKLM_MAX_PROMPT_CHARS = 6500
DEFAULT_NOTEBOOKLM_BATCH_DELAY_SECONDS = 5
DEFAULT_NOTEBOOKLM_RETRIES = 2
SCRIPT_PATH = Path(__file__).resolve()


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


def notebooklm_readiness(notebook_id: str, nlm_bin: str = "", profile: str = "", timeout: int = 30) -> tuple[bool, str]:
    resolved = resolve_nlm_bin(nlm_bin)
    if not resolved:
        return False, "nlm command is not installed. Install notebooklm-mcp-cli and run nlm login first."
    if not notebook_id:
        return False, "NotebookLM provider requires --notebook-id or NEWSLETTER_NOTEBOOKLM_NOTEBOOK_ID."
    command = [resolved, "login", "--check"]
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
        return False, detail or "NotebookLM login check failed. Run nlm login."
    return True, f"NotebookLM CLI ready: {resolved}"


def notebooklm_enrich(
    notebook_id: str,
    prompt: str,
    rows: list[dict[str, str]],
    timeout: int,
    nlm_bin: str = "",
    profile: str = "",
) -> list[dict[str, Any]]:
    resolved = resolve_nlm_bin(nlm_bin)
    if not resolved:
        raise RuntimeError("nlm command is not installed. Install notebooklm-mcp-cli and run nlm login first.")
    if not notebook_id:
        raise RuntimeError("NotebookLM provider requires --notebook-id or NEWSLETTER_NOTEBOOKLM_NOTEBOOK_ID.")
    command = [resolved, "notebook", "query", notebook_id, prompt, "--timeout", str(timeout)]
    if profile:
        command.extend(["--profile", profile])
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(timeout + 20, DEFAULT_TIMEOUT_SECONDS),
        check=False,
    )
    if completed.returncode != 0:
        detail = normalize_whitespace(completed.stderr or completed.stdout)
        raise RuntimeError(detail or f"nlm query failed with exit {completed.returncode}")
    return normalize_ai_articles(extract_json_object(completed.stdout), rows, "notebooklm-cli")


def notebooklm_row_batches(
    report_date: str,
    rows: list[dict[str, str]],
    *,
    batch_size: int = DEFAULT_NOTEBOOKLM_BATCH_SIZE,
    max_prompt_chars: int = DEFAULT_NOTEBOOKLM_MAX_PROMPT_CHARS,
) -> list[list[dict[str, str]]]:
    batches: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    safe_batch_size = max(1, batch_size)
    for row in rows:
        candidate = current + [row]
        prompt_too_long = len(enrichment_prompt(report_date, candidate)) > max_prompt_chars
        batch_too_large = len(candidate) > safe_batch_size
        if current and (prompt_too_long or batch_too_large):
            batches.append(current)
            current = [row]
        else:
            current = candidate
    if current:
        batches.append(current)
    return batches


def notebooklm_enrich_batched(
    notebook_id: str,
    report_date: str,
    rows: list[dict[str, str]],
    timeout: int,
    nlm_bin: str = "",
    profile: str = "",
    batch_size: int = DEFAULT_NOTEBOOKLM_BATCH_SIZE,
    max_prompt_chars: int = DEFAULT_NOTEBOOKLM_MAX_PROMPT_CHARS,
    batch_delay_seconds: float = DEFAULT_NOTEBOOKLM_BATCH_DELAY_SECONDS,
    retries: int = DEFAULT_NOTEBOOKLM_RETRIES,
) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    batches = notebooklm_row_batches(
        report_date,
        rows,
        batch_size=batch_size,
        max_prompt_chars=max_prompt_chars,
    )
    for index, batch in enumerate(batches, start=1):
        if index > 1 and batch_delay_seconds > 0:
            time.sleep(batch_delay_seconds)
        batch_prompt = enrichment_prompt(report_date, batch)
        for attempt in range(max(1, retries + 1)):
            try:
                articles.extend(notebooklm_enrich(notebook_id, batch_prompt, batch, timeout, nlm_bin, profile))
                break
            except RuntimeError as exc:
                message = str(exc)
                retryable = "RESOURCE_EXHAUSTED" in message or "INVALID_ARGUMENT" in message
                if not retryable or attempt >= retries:
                    raise RuntimeError(f"NotebookLM batch {index}/{len(batches)} failed: {exc}") from exc
                time.sleep(batch_delay_seconds + (30 * (attempt + 1)))
    return articles


def write_outputs(
    *,
    out_dir: Path,
    report_date: str,
    provider: str,
    rows: list[dict[str, str]],
    articles: list[dict[str, Any]],
    prompt: str,
    write_latest: bool,
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
    parser.add_argument("--notebooklm-batch-size", type=int, default=int(os.environ.get("NEWSLETTER_NOTEBOOKLM_BATCH_SIZE", str(DEFAULT_NOTEBOOKLM_BATCH_SIZE))))
    parser.add_argument(
        "--notebooklm-max-prompt-chars",
        type=int,
        default=int(os.environ.get("NEWSLETTER_NOTEBOOKLM_MAX_PROMPT_CHARS", str(DEFAULT_NOTEBOOKLM_MAX_PROMPT_CHARS))),
    )
    parser.add_argument(
        "--notebooklm-batch-delay",
        type=float,
        default=float(os.environ.get("NEWSLETTER_NOTEBOOKLM_BATCH_DELAY_SECONDS", str(DEFAULT_NOTEBOOKLM_BATCH_DELAY_SECONDS))),
    )
    parser.add_argument(
        "--notebooklm-retries",
        type=int,
        default=int(os.environ.get("NEWSLETTER_NOTEBOOKLM_RETRIES", str(DEFAULT_NOTEBOOKLM_RETRIES))),
    )
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("NEWSLETTER_AI_TIMEOUT_SECONDS", "180")))
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
            ok, message = notebooklm_readiness(args.notebook_id, args.nlm_bin, args.nlm_profile, min(args.timeout, 60))
            print(f"ai_enrichment_check={'ok' if ok else 'fail'} provider=notebooklm message={message}")
            return 0 if ok else 1
        print(f"ai_enrichment_check=fail provider={args.provider} reason=unknown_provider")
        return 1
    review_file = args.review_file or args.out_dir / f"daily_news_review_queue_{compact_date(args.date)}.csv"
    rows = read_csv(review_file)
    prompt = enrichment_prompt(args.date, rows)
    if provider in {"local", "local-rule", "fallback"}:
        articles = local_enrich(rows)
        provider_name = "local-rule"
    elif provider in {"command", "custom"}:
        if not args.command:
            raise SystemExit("--command or NEWSLETTER_AI_COMMAND is required for command provider")
        articles = command_enrich(args.command, prompt, rows)
        provider_name = "command"
    elif provider in {"notebooklm", "notebooklm-cli", "nlm"}:
        articles = notebooklm_enrich_batched(
            args.notebook_id,
            args.date,
            rows,
            args.timeout,
            args.nlm_bin,
            args.nlm_profile,
            args.notebooklm_batch_size,
            args.notebooklm_max_prompt_chars,
            args.notebooklm_batch_delay,
            args.notebooklm_retries,
        )
        provider_name = "notebooklm-cli"
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
    )
    print(f"ai_enrichment_status=ok provider={provider_name} articles={len(articles)} output={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
