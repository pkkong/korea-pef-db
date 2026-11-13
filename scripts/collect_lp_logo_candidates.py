#!/usr/bin/env python3
"""Collect official logo candidates for LP institutions (run on GitHub Actions).

For each institution: the homepage's icon links (apple-touch-icon, icon),
og:image and <img> tags that look like a logo/CI/symbol, plus the Korean
Wikipedia infobox image. Files and a manifest go to --out; a person picks the
mark to use. Nothing here is published.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import ssl
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
LOGO_HINT = re.compile(r"(logo|symbol|cymbol|emblem|ci[_\-.]|[_\-/]ci\b|bi[_\-.]|brand|header_logo|h_logo)", re.I)
MAX_BYTES = 3_000_000
EXTRA = {
    "pck_pension": ("총회연금재단", "https://www.pckpension.or.kr"),
    "kfinco": ("전문건설공제조합", "https://www.kfinco.co.kr"),
    "moel_iaci": ("근로복지공단", "https://www.comwel.or.kr"),
    "moel_eif": ("고용노동부", "https://www.moel.go.kr"),
}
WIKI_TITLES = {
    "nps": "국민연금공단", "kdb": "한국산업은행", "ibk": "IBK기업은행", "kexim": "한국수출입은행",
    "koreapost": "우정사업본부", "kamco": "한국자산관리공사", "kic": "한국투자공사", "kfcc": "새마을금고",
    "cu": "신용협동조합중앙회", "suhyup": "수산업협동조합중앙회", "kbiz": "중소기업중앙회", "tp": "사립학교교직원연금공단",
    "geps": "공무원연금공단", "ktcu": "한국교직원공제회", "mmaa": "군인공제회", "pmaa": "경찰공제회",
    "poba": "대한지방행정공제회", "sema": "과학기술인공제회", "kvic": "한국벤처투자", "kgrowth": "한국성장금융투자운용",
    "cwma": "건설근로자공제회", "kosme": "중소벤처기업진흥공단", "kobc": "한국해양진흥공사", "moel_iaci": "근로복지공단",
    "moel_eif": "고용노동부", "kafi": "농업정책보험금융원", "sba": "서울경제진흥원",
}


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "link" and "icon" in a.get("rel", "").lower() and a.get("href"):
            self.found.append((f"link:{a.get('rel')}:{a.get('sizes', '')}", a["href"]))
        elif tag == "meta" and a.get("property", "").lower() == "og:image" and a.get("content"):
            self.found.append(("og:image", a["content"]))
        elif tag == "img" and a.get("src"):
            hint = " ".join([a.get("src", ""), a.get("alt", ""), a.get("class", ""), a.get("id", "")])
            if LOGO_HINT.search(hint) or "로고" in a.get("alt", ""):
                self.found.append((f"img:{a.get('alt', '')[:30]}", a["src"]))


def fetch(url: str, timeout: int = 20) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    context = ssl.create_default_context()
    try:
        response = urlopen(request, timeout=timeout, context=context)
    except ssl.SSLError:
        legacy = ssl.create_default_context()
        legacy.set_ciphers("DEFAULT:@SECLEVEL=1")
        response = urlopen(request, timeout=timeout, context=legacy)
    with response:
        return response.read(MAX_BYTES + 1), response.headers.get("Content-Type", "")


def wiki_image(title: str) -> str:
    api = ("https://ko.wikipedia.org/w/api.php?action=query&prop=pageimages&piprop=original&redirects=1&format=json&titles="
           + quote(title))
    data = json.loads(fetch(api)[0])
    for page in data.get("query", {}).get("pages", {}).values():
        original = page.get("original", {}).get("source")
        if original:
            return original
    return ""


def save(out: Path, code: str, kind: str, url: str, manifest: list[dict]) -> None:
    try:
        body, ctype = fetch(url)
    except Exception as exc:  # noqa: BLE001
        manifest.append({"code": code, "kind": kind, "url": url, "error": type(exc).__name__})
        return
    if len(body) > MAX_BYTES or len(body) < 60:
        manifest.append({"code": code, "kind": kind, "url": url, "error": f"size:{len(body)}"})
        return
    ext = Path(urlparse(url).path).suffix.lower()[:5] or {"image/svg+xml": ".svg", "image/png": ".png"}.get(ctype.split(";")[0], ".bin")
    name = f"{code}-{hashlib.sha1(url.encode()).hexdigest()[:8]}{ext}"
    (out / name).write_bytes(body)
    manifest.append({"code": code, "kind": kind, "url": url, "file": name, "bytes": len(body), "type": ctype})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    institutions = {}
    with (ROOT / "data" / "lp_institutions.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            institutions[row["lp_code"]] = (row["lp_name"], row["homepage_url"])
    institutions.update(EXTRA)
    manifest: list[dict] = []
    for code, (name, homepage) in sorted(institutions.items()):
        if code not in WIKI_TITLES and code not in EXTRA and code not in {
            "nps", "kvic", "kgrowth", "kafi", "kdb", "koreapost", "poba", "ktcu", "pmaa", "cu", "kfcc", "kexim", "tp",
            "geps", "mmaa", "cwma", "kbiz", "ibk", "kic", "sema", "suhyup", "kosme", "sba", "kamco", "kobc",
        }:
            continue
        print(f"== {code} {name} {homepage}", flush=True)
        seen: set[str] = set()
        try:
            html, _ = fetch(homepage)
            parser_ = Links()
            parser_.feed(html.decode("utf-8", "ignore"))
            candidates = parser_.found[:14]
        except Exception as exc:  # noqa: BLE001
            manifest.append({"code": code, "kind": "homepage", "url": homepage, "error": type(exc).__name__})
            candidates = []
        candidates += [("default:apple-touch-icon", "/apple-touch-icon.png"), ("default:favicon", "/favicon.ico")]
        for kind, href in candidates:
            url = urljoin(homepage + "/", href.strip())
            if url in seen or not url.startswith("http"):
                continue
            seen.add(url)
            save(args.out, code, kind, url, manifest)
        title = WIKI_TITLES.get(code)
        if title:
            try:
                image = wiki_image(title)
                if image:
                    save(args.out, code, "wikipedia", image, manifest)
            except Exception as exc:  # noqa: BLE001
                manifest.append({"code": code, "kind": "wikipedia", "url": title, "error": type(exc).__name__})
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for row in manifest if row.get("file"))
    print(f"saved={ok} attempts={len(manifest)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
