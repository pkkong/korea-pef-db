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


WIKI_UA = "kpef-lp-logo-review/1.0 (https://github.com/pkkong/korea-pef-db; review only)"


def fetch(url: str, timeout: int = 20) -> tuple[bytes, str]:
    # Wikimedia asks for a descriptive agent and rejects browser look-alikes.
    agent = WIKI_UA if "wiki" in urlparse(url).netloc else UA
    request = Request(url, headers={"User-Agent": agent, "Accept": "*/*"})
    context = ssl.create_default_context()
    try:
        response = urlopen(request, timeout=timeout, context=context)
    except ssl.SSLError:
        legacy = ssl.create_default_context()
        legacy.set_ciphers("DEFAULT:@SECLEVEL=1")
        response = urlopen(request, timeout=timeout, context=legacy)
    with response:
        return response.read(MAX_BYTES + 1), response.headers.get("Content-Type", "")


def wiki_image(title: str, lang: str = "ko") -> str:
    api = (f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=pageimages&piprop=original&redirects=1&format=json&titles="
           + quote(title))
    data = json.loads(fetch(api)[0])
    for page in data.get("query", {}).get("pages", {}).values():
        original = page.get("original", {}).get("source")
        if original:
            return original
    return ""


def commons_files(query: str, limit: int = 4) -> list[str]:
    """Original URLs of Commons files matching a search (logos, symbols)."""
    api = ("https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrnamespace=6&format=json"
           f"&gsrlimit={limit}&prop=imageinfo&iiprop=url&gsrsearch=" + quote(query))
    data = json.loads(fetch(api)[0])
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    return [p["imageinfo"][0]["url"] for p in pages if p.get("imageinfo")]


COMMONS_QUERIES = {
    "kdb": ["KDB Korea Development Bank logo", "한국산업은행 로고"], "kexim": ["Export-Import Bank of Korea logo", "한국수출입은행"],
    "kfcc": ["Saemaul Geumgo logo", "새마을금고 로고"], "cu": ["National Credit Union Federation of Korea logo", "신협 로고"],
    "suhyup": ["Suhyup logo", "수협 로고"], "sema": ["과학기술인공제회"], "kfinco": ["전문건설공제조합"],
    "pck_pension": ["총회연금재단"], "kbiz": ["Korea Federation of SMEs logo", "중소기업중앙회"],
    "mmaa": ["Military Mutual Aid Association logo", "군인공제회"], "kic": ["Korea Investment Corporation logo"],
    "kobc": ["Korea Ocean Business Corporation logo"], "moel_eif": ["Ministry of Employment and Labor Korea logo"],
    "moel_iaci": ["Korea Workers' Compensation and Welfare Service logo", "근로복지공단"], "kafi": ["농업정책보험금융원"],
    "kgrowth": ["Korea Growth Investment Corporation logo"], "koreapost": ["Korea Post logo"], "kamco": ["KAMCO logo"],
}
KNOWN_URLS = {
    "kdb": ["https://www.kdb.co.kr/wcmscontents/hmp/ch/bi/bi/rc/img_symbol_chbi.png"],
    "kbiz": ["https://www.kbiz.or.kr/file/resource/image/AOS_192.png"],
    "mmaa": ["https://www.mmaa.or.kr/images/common/logo.png"],
    "kexim": ["https://www.koreaexim.go.kr/humanframe/theme/resources/assets/img/main/spr_gnb_ci.svg"],
    "pmaa": ["https://www.pmaa.or.kr/icon.png"],
}


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
        for url in KNOWN_URLS.get(code, []):
            if url not in seen:
                seen.add(url)
                save(args.out, code, "registry", url, manifest)
        title = WIKI_TITLES.get(code)
        if title:
            try:
                image = wiki_image(title)
                if image and image not in seen:
                    seen.add(image)
                    save(args.out, code, "wikipedia", image, manifest)
            except Exception as exc:  # noqa: BLE001
                manifest.append({"code": code, "kind": "wikipedia", "url": title, "error": type(exc).__name__})
        for query in COMMONS_QUERIES.get(code, []):
            try:
                for url in commons_files(query):
                    if url not in seen and re.search(r"\.(svg|png|jpg|jpeg|gif)$", url, re.I):
                        seen.add(url)
                        save(args.out, code, f"commons:{query[:20]}", url, manifest)
            except Exception as exc:  # noqa: BLE001
                manifest.append({"code": code, "kind": "commons", "url": query, "error": type(exc).__name__})
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for row in manifest if row.get("file"))
    print(f"saved={ok} attempts={len(manifest)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
