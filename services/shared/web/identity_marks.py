"""Identity marks (small square icons) for GPs and LPs, shared by the GP and LP pages.

One look across services: a 40px rounded tile. A real logo is shown only when it
is a symbol (square-ish mark, app icon, favicon); a wide wordmark squeezed into
a 40px tile is unreadable, so those fall back to a lettered tile. Lettered tiles
use a stable tinted colour per name and the shortest recognisable label: the
Latin acronym the Korean name spells out (엠비케이파트너스 -> MBK) or the first
two syllables.
"""
from __future__ import annotations

import hashlib
import re

TONES = 8
SYMBOL_MAX_RATIO = 1.6
SYMBOL_FILE_RE = re.compile(r"(favicon|icon|ios|aos|apple-touch|symbol|cymbol|emblem|ci_mark|_mark|bm_)", re.I)

# Korean spellings of Latin letter names, longest first at each position.
LETTER_NAMES = sorted(
    [
        ("더블유", "W"), ("에이치", "H"), ("에이", "A"), ("비", "B"), ("씨", "C"), ("디", "D"), ("이", "E"),
        ("에프", "F"), ("지", "G"), ("아이", "I"), ("제이", "J"), ("케이", "K"), ("엘", "L"), ("엠", "M"),
        ("엔", "N"), ("오", "O"), ("피", "P"), ("큐", "Q"), ("알", "R"), ("에스", "S"), ("티", "T"),
        ("유", "U"), ("브이", "V"), ("엑스", "X"), ("와이", "Y"), ("제트", "Z"), ("앤", "&"),
    ],
    key=lambda item: -len(item[0]),
)
# Names whose first two syllables would all read "한국" etc.: the short form the press uses.
KNOWN_SHORT_PREFIXES = (
    ("한국투자", "한투"), ("한국산업은행", "산은"), ("한국자산관리공사", "캠코"), ("한국수출입은행", "수은"),
    ("중소기업은행", "IBK"), ("한국성장금융", "성장"), ("한국벤처투자", "KVIC"), ("한국교직원공제회", "교공"),
)
# Fallback syllables that are themselves a letter name read better with one more syllable (케이스톤 -> 케이스).
LETTER_SYLLABLE_PAIRS = {"케이", "에이", "에스", "제이", "아이", "와이", "브이", "에프", "엑스", "이앤", "제이앤"}
LEGAL_FORMS_RE = re.compile(r"\(주\)|㈜|주식회사|유한책임회사|유한회사|\(유\)|\(舊[^)]*\)")


def spelled_acronym(name: str) -> str:
    """'엠비케이파트너스' -> 'MBK', '이앤에프프라이빗에퀴티' -> 'E&F'; '' when not an acronym.

    Two one-syllable letters alone (이지스 -> EG, 지오 -> GO) are too often ordinary
    syllables, so an acronym needs three letters or a two-syllable letter name.
    """
    text = re.sub(r"\s+", "", LEGAL_FORMS_RE.sub("", name or ""))
    letters: list[str] = []
    long_name = False
    position = 0
    while position < len(text):
        for spelling, letter in LETTER_NAMES:
            if text.startswith(spelling, position):
                letters.append(letter)
                long_name = long_name or (len(spelling) >= 2 and letter != "&")
                position += len(spelling)
                break
        else:
            break
    while letters and letters[-1] == "&":
        letters.pop()
    count = sum(1 for letter in letters if letter != "&")
    if count >= 3 or (count == 2 and long_name):
        acronym = "".join(letters)
        return acronym if len(acronym) <= 4 else ""
    return ""


def mark_label(name: str, curated: str = "") -> str:
    if curated:
        return curated
    text = re.sub(r"\s+", "", LEGAL_FORMS_RE.sub("", name or ""))
    if not text:
        return ""
    for prefix, short in KNOWN_SHORT_PREFIXES:
        if text.startswith(prefix):
            return short
    latin = re.match(r"[A-Za-z0-9&]{2,4}(?![A-Za-z])", text)
    if latin:
        return latin.group(0).upper()
    acronym = spelled_acronym(text)
    if acronym:
        return acronym
    korean = "".join(re.findall(r"[가-힣]", text))
    if korean:
        return korean[:3] if korean[:2] in LETTER_SYLLABLE_PAIRS and len(korean) > 2 else korean[:2]
    return text[:2].upper()


def mark_tone(seed: str) -> int:
    return int(hashlib.sha1((seed or "").encode("utf-8")).hexdigest()[:6], 16) % TONES + 1


def _px(value: str) -> float | None:
    match = re.fullmatch(r"\s*([0-9.]+)px\s*", value or "")
    return float(match.group(1)) if match else None


def logo_is_symbol(logo_url: str, width: str = "", height: str = "") -> bool:
    """True for a mark that reads at icon size; wide wordmarks are False."""
    if not logo_url:
        return False
    w, h = _px(width), _px(height)
    if w and h:
        return w / h <= SYMBOL_MAX_RATIO
    path = logo_url.split("?", 1)[0].rsplit("/", 1)[-1]
    return bool(SYMBOL_FILE_RE.search(path))


def mark_css(selector: str, size: int = 40, radius: int = 10, scope: str = "") -> str:
    """CSS for lettered and logo tiles under ``selector`` (e.g. '.gp-avatar').

    ``scope`` prefixes every rule (e.g. '.lp-sample') to outrank page CSS.
    """
    selector = f"{scope} {selector}".strip()
    palette = [
        ("#e8f0fb", "#2f5d9a"), ("#e3f3ef", "#2b6b5e"), ("#eaf3e4", "#486d32"), ("#faf0de", "#875811"),
        ("#f9e8e8", "#983a3a"), ("#eeeaf9", "#5a4997"), ("#ebeff4", "#425267"), ("#e2f1f6", "#296579"),
    ]
    tones = "".join(
        f"{selector}:not(.has-logo)[data-tone=\"{index}\"],{selector}.fallback-only[data-tone=\"{index}\"]"
        f"{{background:{bg};color:{fg}}}"
        for index, (bg, fg) in enumerate(palette, start=1)
    )
    return (
        f"{selector}{{display:inline-grid;flex:none;place-items:center;overflow:hidden;box-sizing:border-box;"
        f"width:{size}px;height:{size}px;border:0;border-radius:{radius}px;background:#ebeff4;color:#425267;"
        "box-shadow:inset 0 0 0 1px rgba(15,23,42,.04);"
        "font-size:12.5px;font-weight:700;letter-spacing:-.2px;line-height:1}"
        f"{tones}"
        f"{selector}[data-label-length=\"3\"],{selector}[data-label-length=\"4\"]{{font-size:11px;letter-spacing:-.3px}}"
        f"{selector}.has-logo:not(.fallback-only){{background:var(--logo-bg,#fff);box-shadow:inset 0 0 0 1px #e3e7ec}}"
        f"{selector}.has-logo img{{width:{round(size * .66)}px;height:{round(size * .66)}px;object-fit:contain}}"
        f"{selector}.has-logo:not(.fallback-only)>span{{display:none}}"
    )
