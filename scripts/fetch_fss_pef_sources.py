#!/usr/bin/env python
"""Fetch FSS quarterly PEF status source files.

This script searches the FSS common business data board, downloads Excel
attachments for matching PEF status posts, and rewrites the source registry.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html import unescape
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw" / "fss_pef"
REGISTRY_PATH = REPO_ROOT / "data" / "source_registry_fss_pef.csv"
FSS_BASE = "https://www.fss.or.kr"
FSS_BOARD = f"{FSS_BASE}/fss/bbs/B0000079/list.do"


REGISTRY_FIELDS = [
    "source_id",
    "as_of_date",
    "period_label",
    "regime",
    "title",
    "source_url",
    "post_url",
    "download_url",
    "posted_date",
    "original_file_name",
    "local_file",
    "notes",
]


@dataclass(frozen=True)
class FssPost:
    title: str
    post_url: str
    download_url: str
    posted_date: str
    original_file_name: str
    as_of_date: str
    period_label: str
    regime: str

    @property
    def source_id(self) -> str:
        return f"FSS_PEF_{self.period_label.replace('Q', '_Q')}"

    @property
    def local_path(self) -> Path:
        suffix = Path(self.original_file_name).suffix or ".xlsx"
        regime_suffix = "institutional" if self.regime == "institutional" else "management"
        return RAW_DIR / f"{self.source_id}_{regime_suffix}{suffix}"


def fetch_bytes(url: str, *, timeout: int = 60) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        return resp.read()


def fetch_text(url: str) -> str:
    raw = fetch_bytes(url)
    for encoding in ["utf-8", "cp949", "euc-kr"]:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def search_url(query: str, page: int = 1) -> str:
    params = {
        "menuNo": "200111",
        "pageIndex": str(page),
        "searchCnd": "1",
        "searchWrd": query,
    }
    return FSS_BOARD + "?" + urllib.parse.urlencode(params)


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def absolute_url(url: str) -> str:
    return urllib.parse.urljoin(FSS_BASE, unescape(url))


def as_of_from_title(title: str) -> tuple[str, str] | None:
    match = re.search(r"(\d{4})년\s*(\d{1,2})월말\s*기준", title)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    day = calendar.monthrange(year, month)[1]
    quarter = ((month - 1) // 3) + 1
    return f"{year:04d}-{month:02d}-{day:02d}", f"{year:04d}Q{quarter}"


def regime_from_title(title: str) -> str | None:
    if "기관전용" in title:
        return "institutional"
    if "경영참여형" in title or "PEF" in title:
        return "management_participation"
    return None


def parse_posts(html: str) -> list[FssPost]:
    posts: list[FssPost] = []
    row_blocks = re.findall(r"<tr>\s*(.*?)\s*</tr>", html, flags=re.DOTALL | re.IGNORECASE)
    for row in row_blocks:
        title_match = re.search(
            r'<td class="title">\s*<a href="([^"]+)">(.*?)</a>\s*</td>',
            row,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not title_match:
            continue
        title = strip_tags(title_match.group(2))
        regime = regime_from_title(title)
        as_of = as_of_from_title(title)
        if not regime or not as_of:
            continue

        file_match = re.search(
            r'<a href="([^"]*fileDown\.do[^"]*)".*?<span class="name">(.*?)</span>',
            row,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not file_match:
            continue

        date_cells = re.findall(r"<td[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</td>", row)
        posted_date = date_cells[0] if date_cells else ""
        as_of_date, period_label = as_of
        posts.append(
            FssPost(
                title=title,
                post_url=absolute_url(title_match.group(1)),
                download_url=absolute_url(file_match.group(1)),
                posted_date=posted_date,
                original_file_name=strip_tags(file_match.group(2)),
                as_of_date=as_of_date,
                period_label=period_label,
                regime=regime,
            )
        )
    return posts


def max_end_page(html: str) -> int | None:
    values = [int(value) for value in re.findall(r"data-endpage='(\d+)'", html)]
    if values:
        return max(values)
    page_values = [int(value) for value in re.findall(r"data-pageindex='(\d+)'", html)]
    if page_values:
        return max(page_values)
    return None


def discover_posts(queries: list[str], sleep_seconds: float, max_pages: int) -> list[FssPost]:
    by_key: dict[tuple[str, str], FssPost] = {}
    for query in queries:
        page = 1
        end_page: int | None = None
        while True:
            url = search_url(query, page)
            html = fetch_text(url)
            if end_page is None:
                end_page = max_end_page(html)
            page_posts = parse_posts(html)
            for post in page_posts:
                by_key[(post.period_label, post.regime)] = post
            if end_page is not None and page >= end_page:
                break
            if end_page is None and page > 1 and not page_posts:
                break
            if page >= max_pages:
                break
            page += 1
            time.sleep(sleep_seconds)
        time.sleep(sleep_seconds)
    return sorted(by_key.values(), key=lambda p: (p.as_of_date, p.regime))


def download_post(post: FssPost, force: bool) -> bool:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if post.local_path.exists() and not force:
        return False
    data = fetch_bytes(post.download_url, timeout=120)
    post.local_path.write_bytes(data)
    return True


def registry_row(post: FssPost) -> dict[str, str]:
    return {
        "source_id": post.source_id,
        "as_of_date": post.as_of_date,
        "period_label": post.period_label,
        "regime": post.regime,
        "title": post.title,
        "source_url": post.post_url,
        "post_url": post.post_url,
        "download_url": post.download_url,
        "posted_date": post.posted_date,
        "original_file_name": post.original_file_name,
        "local_file": str(post.local_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "notes": "금감원 공통업무자료 첨부파일",
    }


def read_existing_registry(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [{field: row.get(field, "") for field in REGISTRY_FIELDS} for row in rows]


def write_registry(path: Path, posts: list[FssPost]) -> None:
    existing = read_existing_registry(path)
    by_id = {row["source_id"]: row for row in existing if row.get("source_id")}
    for post in posts:
        by_id[post.source_id] = registry_row(post)
    rows = sorted(by_id.values(), key=lambda r: (r.get("as_of_date", ""), r.get("source_id", "")))
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=REGISTRY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch FSS PEF status Excel attachments")
    parser.add_argument("--force", action="store_true", help="Redownload existing files")
    parser.add_argument("--sleep", type=float, default=0.5, help="Delay between FSS requests")
    parser.add_argument("--max-pages", type=int, default=30, help="Safety cap for board pagination per query")
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Board title search query. Can be specified multiple times.",
    )
    parser.add_argument("--no-download", action="store_true", help="Only update registry from search results")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    queries = args.queries or [
        "기관전용 사모집합투자기구 현황",
        "경영참여",
    ]
    posts = discover_posts(queries, args.sleep, args.max_pages)
    if not posts:
        print("No FSS PEF posts found.")
        return 1
    downloaded = 0
    for post in posts:
        if not args.no_download:
            if download_post(post, args.force):
                downloaded += 1
        print(f"{post.period_label}\t{post.regime}\t{post.title}\t{post.original_file_name}")
    write_registry(REGISTRY_PATH, posts)
    print(f"registry={REGISTRY_PATH}")
    print(f"posts={len(posts)} downloaded={downloaded}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
