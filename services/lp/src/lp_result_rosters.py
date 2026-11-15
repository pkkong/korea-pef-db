"""PE managers named in an official result notice, for boards without a dedicated parser.

Each layout below was read from the institutions' own result notices (2020-2026):
- press release on the board (군인공제회): "PE분야는 △IMM인베스트먼트, △JKL파트너스, △제이앤프라이빗에쿼티(루키) 등 3곳이다. VC분야는 …"
- numbered sections (총회연금): "1) PEF 4개사 : 스톤브릿지캐피탈 / IMM인베스트먼트 / … 2) VC 2개사 : …"
- league lists (공무원연금): "<대형리그> 1. 아이엠엠프라이빗에쿼티 2. 엠비케이파트너스 <중형리그> 1. …"
- one line (캠코): "□ 선정 운용사 : (주)제이케이엘파트너스"
- glued result table (캠코): "지원분야 운용사명(가나다 순) 일반 브이아이지파트너스오퍼스프라이빗에퀴티… 루키 …"

A roster is returned only when every name passes the GP-name rule or is a known manager,
and any stated count matches. Anything else returns None: a missing roster is better than
a wrong or partial one.
"""
import re

_ANNOTATION = re.compile(r'\((?:루키|Co-?GP|공동운용|가나다\s*순)\)|\(주\)|㈜|주식회사', re.I)


def _clean(name):
    return _ANNOTATION.sub('', name).strip(' .·,/△-')


def _validated(names, known, valid, count=None):
    names = [_clean(n) for n in names if _clean(n)]
    if not names or len(set(names)) != len(names):
        return None
    keys = {re.sub(r'\s+', '', k) for k in known}
    if not all(valid(re.sub(r'\s+', '', n)) or re.sub(r'\s+', '', n) in keys for n in names):
        return None
    if count is not None and count != len(names):
        return None
    return names


def pe_result_roster(text, *, known=frozenset(), valid, split_glued=None, pe_only_program=False):
    """[(league or 'PE', [names])] or None."""
    t = re.sub(r'\s+', ' ', text or '')
    # 1. Press release: PE part ends where the VC part starts.
    m = re.search(r'PE\s*분야(?:는|은)?\s*(△.+?)(?:등\s*(\d+)\s*(?:곳|개사))', t)
    if m:
        names = _validated(re.split(r'\s*△\s*', m[1])[1:], known, valid, int(m[2]))
        return [('PE', names)] if names else None
    # 2. Numbered sections: "N) PEF (N개사)? : A / B / C".
    m = re.search(r'\d\)\s*PEF?\s*(?:(\d+)\s*개사)?\s*[:：]\s*(.+?)(?=\s\d\)\s|\s\d\.\s|$)', t)
    if m:
        names = _validated(m[2].split('/'), known, valid, int(m[1]) if m[1] else None)
        return [('PE', names)] if names else None
    mixed = re.search(r'(?<![A-Za-z])VC(?![A-Za-z])|벤처', t)
    if mixed and not pe_only_program:
        return None  # a mixed result with no readable PE part
    # 3. League lists: "<대형리그> 1. A 2. B".
    leagues = re.findall(r'<\s*([^<>]{1,12}리그)\s*>((?:\s*\d+\.\s*[^<>*]+?)+)(?=\s*<|\s*\*|$)', t)
    if leagues:
        roster = []
        for league, items in leagues:
            names = _validated(re.findall(r'\d+\.\s*(.+?)(?=\s+\d+\.|$)', items.strip()), known, valid)
            if not names:
                return None
            roster.append((league.strip(), names))
        return roster
    # 4. One line: "선정 운용사 : (주)A" (comma-separated allowed).
    m = re.search(r'선정\s*운용사\s*[:：]\s*(.+?)(?=\s*□|\s*※|$)', t)
    if m:
        names = _validated(re.split(r'\s*,\s*', m[1]), known, valid)
        return [('PE', names)] if names else None
    # 5. Glued result table: "운용사명(가나다 순) 일반 XXXX 루키 YYYY".
    m = re.search(r'운용사명\s*\(가나다\s*순\)\s*(.+)$', t)
    if m and split_glued:
        parts = re.split(r'\s*(일\s*반|루\s*키|대\s*형|중\s*형|소\s*형)\s+', ' ' + m[1])
        roster = []
        for label, glued in zip(parts[1::2], parts[2::2]):
            names = split_glued(glued.strip(), known)
            names = _validated(names or [], known, valid)
            if not names:
                return None
            roster.append((re.sub(r'\s+', '', label), names))
        return roster or None
    return None
