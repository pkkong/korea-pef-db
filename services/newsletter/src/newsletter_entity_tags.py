"""GP·LP display tags for Brief articles.

Tags are for readers: which managers (GP) and which investors (LP) an article
is about. They are computed from each article's title and summary when the
public archive is built, so every rebuild re-tags the whole rolling archive.

They do not feed article selection or section classification; those stay with
the daily pipeline.

Sources (docs/data_operating_model.md):
- GP: the published GP snapshot's directory page ``gps.html`` (GP -> Brief
  contract: ``gp-card`` ``data-name``/``data-url``/``data-active``), read
  read-only through Supabase REST, plus reviewed aliases in
  ``services/newsletter/data/news_gp_alias_overrides.csv``.
- LP: the repository's LP institution master ``data/lp_institutions.csv`` plus
  ``services/newsletter/data/news_lp_alias_overrides.csv``. No network.

Failure isolation: each source loads on its own. If one fails, articles keep
the tags of that kind they had in the previous archive, the other kind is still
tagged, and the Brief build never stops because of tagging.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[3]
LP_INSTITUTIONS_CSV = REPO_ROOT / "data" / "lp_institutions.csv"
LP_ALIAS_OVERRIDES = REPO_ROOT / "services" / "newsletter" / "data" / "news_lp_alias_overrides.csv"
GP_ALIAS_OVERRIDES = REPO_ROOT / "services" / "newsletter" / "data" / "news_gp_alias_overrides.csv"

MAX_GP_TAGS = 4
MAX_LP_TAGS = 3

# --- GP directory contract -------------------------------------------------

GP_DIRECTORY_CARD_RE = re.compile(r'<article class="gp-card"([^>]*)>')
GP_DIRECTORY_NAME_RE = re.compile(r'\bdata-name="([^"]+)"')
GP_DIRECTORY_URL_RE = re.compile(r'\bdata-url="gp-([0-9]+)[.]html"')
GP_DIRECTORY_ACTIVE_RE = re.compile(r'\bdata-active="1"')


def parse_gp_directory(page_html: str) -> list[tuple[str, str, bool, bool]]:
    """(ref, public name, has profile page, active) for every directory card."""
    entries: dict[str, tuple[str, str, bool, bool]] = {}
    for match in GP_DIRECTORY_CARD_RE.finditer(page_html or ""):
        attrs = match.group(1)
        name_match = GP_DIRECTORY_NAME_RE.search(attrs)
        if not name_match:
            continue
        name = " ".join(unescape(name_match.group(1)).split())
        if not name:
            continue
        url_match = GP_DIRECTORY_URL_RE.search(attrs)
        active = bool(GP_DIRECTORY_ACTIVE_RE.search(attrs))
        if url_match:
            entries[name] = (f"gp:{url_match.group(1)}", name, True, active)
        elif name not in entries:
            entries[name] = (f"gp-name:{hashlib.sha1(name.encode('utf-8')).hexdigest()[:10]}", name, False, active)
    return list(entries.values())


def fetch_gp_directory_html(timeout: int = 30) -> str:
    """Read gps.html of the published GP snapshot (read-only REST)."""
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not base_url or not key:
        raise LookupError("no_credentials")
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}

    def get(path: str) -> object:
        with urlopen(Request(f"{base_url}/rest/v1/{path}", headers=headers), timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    snapshots = get("gp_public_snapshots?select=snapshot_id&status=eq.published&order=published_at.desc&limit=1")
    if not isinstance(snapshots, list) or not snapshots or not snapshots[0].get("snapshot_id"):
        raise LookupError("no_published_gp_snapshot")
    snapshot_id = quote(str(snapshots[0]["snapshot_id"]), safe="")
    pages = get(f"gp_public_pages?select=page_html&snapshot_id=eq.{snapshot_id}&page_path=eq.gps.html&limit=1")
    if not isinstance(pages, list) or not pages or not pages[0].get("page_html"):
        raise LookupError("no_gp_directory_page")
    return str(pages[0]["page_html"])


# --- Matching --------------------------------------------------------------

HANGUL = "가-힣"
# A short alias may be followed by a particle (캠코는, 산은이) but not by more of a word (산은캐피탈).
PARTICLE_START = "은는이가을를의과와도에로측등만"
# Names that are often not acting as a private equity manager in the news.
GP_CONTEXT_GATED_NAME_RE = re.compile(
    r"(증권|은행|자산운용|투자운용|금융투자|생명|화재|보험|공사|공단|에너지|상사|카운티|플랫폼|홀딩스)$"
)
# For a gated name the PE word must sit next to it (NH투자증권 PE본부), not just
# anywhere in the article (KB자산운용이 ... 위탁운용사(GP) 선정 출자).
GATED_CONTEXT_BEFORE = 12
GATED_CONTEXT_AFTER = 16
PE_CONTEXT_RE = re.compile(
    r"(?<![A-Za-z])(?:PEF?|GP)(?![A-Za-z])|사모|블라인드|바이아웃|위탁\s*운용|프라이빗\s*에[쿼퀴]티",
    re.IGNORECASE,
)
PRIOR_ROLE_BEFORE_RE = re.compile(r"(?:^|[^가-힣])(?:전|前)\s*$")
PRIOR_ROLE_AFTER_RE = re.compile(r"^\s*(?:출신|에서\s*독립)")
# LP aliases too generic to name one institution.
LP_EXCLUDED_ALIASES = {
    "모태펀드", "국부펀드", "기금운용본부", "서울시 펀드", "콘텐츠펀드", "영화펀드", "스포츠산업펀드",
    "CU", "TP", "HF", "SBA", "KOSAF",
}


def compact_key(value: str) -> str:
    value = re.sub(r"\(주\)|㈜|주식회사|유한회사|유한책임회사|\(유\)", "", value or "")
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value).lower()


def _hangul_count(value: str) -> int:
    return len(re.findall(f"[{HANGUL}]", value))


def compile_alias(alias: str) -> re.Pattern[str] | None:
    alias = " ".join((alias or "").split())
    if len(compact_key(alias)) < 2:
        return None
    body = r"\s*".join(re.escape(part) for part in alias.split(" "))
    first, last = alias[0], alias[-1]
    left = r"(?<![A-Za-z0-9])" if first.isascii() and first.isalnum() else f"(?<![{HANGUL}])"
    strict_right = (last.isascii() and last.isalnum()) or (not re.search(r"[A-Za-z0-9]", alias) and _hangul_count(alias) <= 3)
    if strict_right:
        right = rf"(?![A-Za-z0-9])(?=$|[^{HANGUL}]|[{PARTICLE_START}])"
    else:
        right = ""
    return re.compile(left + body + right, re.IGNORECASE)


@dataclass(frozen=True)
class EntityAlias:
    kind: str  # "GP" or "LP"
    ref: str
    name: str
    alias: str
    pattern: re.Pattern[str]
    needs_pe_context: bool = False


@dataclass
class TagCatalog:
    aliases: list[EntityAlias] = field(default_factory=list)
    status: dict[str, str] = field(default_factory=dict)

    def available(self, kind: str) -> bool:
        return self.status.get(kind, "").startswith("ok")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def _add(target: list[EntityAlias], seen: set[tuple[str, str]], kind: str, ref: str, name: str, alias: str,
         needs_pe_context: bool = False) -> None:
    key = (ref, compact_key(alias))
    if key in seen:
        return
    pattern = compile_alias(alias)
    if pattern is None:
        return
    seen.add(key)
    target.append(EntityAlias(kind, ref, name, alias, pattern, needs_pe_context))


def load_lp_aliases(institutions: Path = LP_INSTITUTIONS_CSV, overrides: Path = LP_ALIAS_OVERRIDES) -> list[EntityAlias]:
    rows = _read_csv(institutions)
    names = {row["lp_code"]: row["lp_name"] for row in rows if row.get("lp_code") and row.get("lp_name")}
    alias_owners: dict[str, set[str]] = {}
    candidates: list[tuple[str, str]] = []
    for row in rows:
        code = row.get("lp_code", "")
        if code not in names:
            continue
        for alias in [row["lp_name"], *row.get("aliases", "").split(";")]:
            alias = alias.strip()
            if alias and alias not in LP_EXCLUDED_ALIASES:
                candidates.append((code, alias))
                alias_owners.setdefault(compact_key(alias), set()).add(code)
    for row in _read_csv(overrides):
        code, alias = row.get("lp_code", ""), row.get("alias_name", "")
        if row.get("display_name") and code not in names:
            names[code] = row["display_name"]
        if code in names and alias:
            candidates.append((code, alias))
            alias_owners.setdefault(compact_key(alias), set()).add(code)
    aliases: list[EntityAlias] = []
    seen: set[tuple[str, str]] = set()
    for code, alias in candidates:
        owners = alias_owners.get(compact_key(alias), set())
        # An alias two institutions share names neither, unless it is one's own name.
        if len(owners) > 1 and compact_key(names[code]) != compact_key(alias):
            continue
        _add(aliases, seen, "LP", f"lp:{code}", names[code], alias)
    return aliases


def gp_name_variants(name: str) -> list[str]:
    variants = [name]
    for a, b in (("에쿼티", "에퀴티"), ("에퀴티", "에쿼티")):
        if a in name:
            variants.append(name.replace(a, b))
    for suffix in ("프라이빗에쿼티", "프라이빗에퀴티"):
        if name.endswith(suffix) and len(name) - len(suffix) >= 2:
            variants.append(name[: -len(suffix)] + "PE")
    # 뉴젠인베스트먼트 -> 뉴젠인베 (press shorthand); a one-syllable stem is too vague.
    if name.endswith("인베스트먼트") and len(name) - len("인베스트먼트") >= 2:
        variants.append(name[: -len("인베스트먼트")] + "인베")
    return list(dict.fromkeys(variants))


def load_gp_aliases(page_html: str, overrides: Path = GP_ALIAS_OVERRIDES,
                    lp_names: Iterable[str] = ()) -> list[EntityAlias]:
    """GP aliases; institutions that are LPs are left to the LP tags."""
    lp_keys = {compact_key(name) for name in lp_names}
    directory = [entry for entry in parse_gp_directory(page_html) if compact_key(entry[1]) not in lp_keys]
    # Every card can be the target of a reviewed alias; only active or profiled
    # managers are matched by their own name (dissolved houses without a profile
    # are mostly unrelated companies when their names appear in news).
    by_name = {name: (ref, name) for ref, name, _, _ in directory}
    own_name = [(ref, name) for ref, name, has_profile, active in directory if has_profile or active]
    names = [name for _, name in own_name]
    aliases: list[EntityAlias] = []
    seen: set[tuple[str, str]] = set()

    def add(ref: str, name: str, alias: str) -> None:
        _add(aliases, seen, "GP", ref, name, alias, bool(GP_CONTEXT_GATED_NAME_RE.search(name)))

    for ref, name in own_name:
        for variant in gp_name_variants(name):
            add(ref, name, variant)
    for row in _read_csv(overrides):
        standard, alias = row.get("standard_gp_name", ""), row.get("alias_name", "")
        if not standard or not alias:
            continue
        target = by_name.get(standard)
        if target is None:
            # The directory may use a shorter public name (어펄마캐피탈 for 어펄마캐피탈매니져스코리아).
            prefixed = [n for n in names if len(n) >= 4 and standard.startswith(n)]
            if len(prefixed) == 1:
                target = by_name[prefixed[0]]
        if target is None:
            continue  # reviewed alias of a manager the published directory does not list
        add(target[0], target[1], alias)
        add(target[0], target[1], standard)
    return aliases


def load_catalog(
    fetch_gp_html: Callable[[], str] = fetch_gp_directory_html,
    lp_institutions: Path = LP_INSTITUTIONS_CSV,
    lp_overrides: Path = LP_ALIAS_OVERRIDES,
    gp_overrides: Path = GP_ALIAS_OVERRIDES,
) -> TagCatalog:
    """Load both sources independently; a failure in one never stops the other."""
    catalog = TagCatalog()
    lp_aliases: list[EntityAlias] = []
    try:
        lp_aliases = load_lp_aliases(lp_institutions, lp_overrides)
        catalog.status["LP"] = f"ok:{len({a.ref for a in lp_aliases})}"
    except Exception as exc:  # noqa: BLE001 - tags are optional
        catalog.status["LP"] = f"unavailable:{type(exc).__name__}"
    gp_aliases: list[EntityAlias] = []
    try:
        gp_aliases = load_gp_aliases(fetch_gp_html(), gp_overrides, {a.name for a in lp_aliases} | {a.alias for a in lp_aliases})
        if not gp_aliases:
            raise LookupError("empty_gp_directory")
        catalog.status["GP"] = f"ok:{len({a.ref for a in gp_aliases})}"
    except Exception as exc:  # noqa: BLE001 - tags are optional
        reason = str(exc) if isinstance(exc, LookupError) else type(exc).__name__
        catalog.status["GP"] = f"unavailable:{reason}"
        gp_aliases = []
    catalog.aliases = lp_aliases + gp_aliases
    return catalog


def _has_pe_context_near(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - GATED_CONTEXT_BEFORE):end + GATED_CONTEXT_AFTER]
    return bool(PE_CONTEXT_RE.search(window.replace(text[start:end], " ")))


def _is_prior_role(text: str, start: int, end: int) -> bool:
    return bool(PRIOR_ROLE_BEFORE_RE.search(text[max(0, start - 3):start]) or PRIOR_ROLE_AFTER_RE.search(text[end:end + 8]))


def tag_text(title: str, summary: str, catalog: TagCatalog) -> dict[str, list[str]]:
    """GP and LP names an article is about, in order of first mention."""
    text = f"{title or ''}\n{summary or ''}"
    hits: list[tuple[int, int, EntityAlias]] = []
    for alias in catalog.aliases:
        for match in alias.pattern.finditer(text):
            if _is_prior_role(text, match.start(), match.end()):
                continue
            if alias.needs_pe_context and not _has_pe_context_near(text, match.start(), match.end()):
                continue
            hits.append((match.start(), match.end(), alias))
            break
    # A shorter match inside another entity's longer match is part of that name.
    kept = [
        (start, end, alias)
        for start, end, alias in hits
        if not any(
            other.ref != alias.ref and o_start <= start and end <= o_end and (o_end - o_start) > (end - start)
            for o_start, o_end, other in hits
        )
    ]
    first_seen: dict[str, tuple[int, EntityAlias]] = {}
    for start, _, alias in kept:
        if alias.ref not in first_seen or start < first_seen[alias.ref][0]:
            first_seen[alias.ref] = (start, alias)
    ordered = sorted(first_seen.values(), key=lambda item: item[0])
    lp_names = list(dict.fromkeys(a.name for _, a in ordered if a.kind == "LP"))[:MAX_LP_TAGS]
    lp_keys = {compact_key(name) for name in lp_names}
    gp_names = [name for name in dict.fromkeys(a.name for _, a in ordered if a.kind == "GP") if compact_key(name) not in lp_keys]
    return {"gpNames": gp_names[:MAX_GP_TAGS], "lpNames": lp_names}


def _article_summary(article: dict[str, object]) -> str:
    summary = str(article.get("summaryText") or "")
    lines = article.get("summaryLines")
    if isinstance(lines, list):
        summary = " ".join([summary, *[str(line) for line in lines]])
    return summary


def _url_key(article: dict[str, object]) -> str:
    return str(article.get("url") or article.get("sourceUrl") or "").strip()


def tag_archive_entries(
    entries: list[dict[str, object]],
    catalog: TagCatalog,
    previous_entries: Iterable[dict[str, object]] = (),
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Return re-tagged copies of archive entries and a small report.

    For a kind whose source is unavailable, each article keeps that kind's tags
    from ``previous_entries`` (or its own), so an outage never wipes tags.
    """
    previous: dict[str, dict[str, list[str]]] = {}
    for entry in previous_entries:
        for article in entry.get("articles", []) if isinstance(entry, dict) else []:
            if isinstance(article, dict) and _url_key(article):
                previous[_url_key(article)] = {
                    "gpNames": [str(n) for n in article.get("gpNames") or []],
                    "lpNames": [str(n) for n in article.get("lpNames") or []],
                }
    fields = {"GP": "gpNames", "LP": "lpNames"}
    counts = {"articles": 0, "with_gp": 0, "with_lp": 0}
    tagged_entries: list[dict[str, object]] = []
    for entry in entries:
        next_entry = dict(entry)
        articles = []
        for article in entry.get("articles", []) or []:
            if not isinstance(article, dict):
                continue
            next_article = dict(article)
            tags = tag_text(str(article.get("title") or ""), _article_summary(article), catalog)
            kept = previous.get(_url_key(article), {})
            for kind, key in fields.items():
                if catalog.available(kind):
                    next_article[key] = tags[key]
                else:
                    next_article[key] = kept.get(key) or [str(n) for n in article.get(key) or []]
            counts["articles"] += 1
            counts["with_gp"] += bool(next_article["gpNames"])
            counts["with_lp"] += bool(next_article["lpNames"])
            articles.append(next_article)
        next_entry["articles"] = articles
        tagged_entries.append(next_entry)
    return tagged_entries, {"status": dict(catalog.status), **counts}


_CATALOG: TagCatalog | None = None


def default_catalog() -> TagCatalog:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = load_catalog()
    return _CATALOG


def apply_display_tags(
    entries: list[dict[str, object]],
    previous_entries: Iterable[dict[str, object]] = (),
    catalog: TagCatalog | None = None,
) -> list[dict[str, object]]:
    """Archive entries with GP·LP display tags; the input unchanged on any error."""
    try:
        tagged, report = tag_archive_entries(entries, catalog or default_catalog(), previous_entries)
    except Exception as exc:  # noqa: BLE001 - the Brief must publish without tags
        print(f"::warning::Brief GP/LP tags skipped: {type(exc).__name__}", flush=True)
        return entries
    status = report["status"]
    print(
        "brief_entity_tags "
        + " ".join(f"{kind.lower()}={status.get(kind, '')}" for kind in ("GP", "LP"))
        + f" articles={report['articles']} with_gp={report['with_gp']} with_lp={report['with_lp']}",
        flush=True,
    )
    for kind in ("GP", "LP"):
        if not str(status.get(kind, "")).startswith("ok"):
            print(f"::warning::Brief {kind} tags kept from the previous archive ({status.get(kind)}).", flush=True)
    return tagged
