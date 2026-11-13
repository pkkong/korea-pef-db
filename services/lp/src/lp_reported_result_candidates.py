"""Find press reports of LP selection results that the LP service has not reflected yet.

Why: many LPs announce their selected managers only to the applicants, so the
LP service fills the gap with press-reported results (data/lp_reported_results.json,
user decision 2026-11-12). That file is curated by hand and goes stale. The Brief
service already collects PE news every day; this module reads its public read
model (the documented Brief → LP public contract) and lists articles that look
like selection-result reports for a published LP program.

The output is a review list, not data to publish. A person or agent checks each
candidate against the article, writes full manager names and the PE/VC split, and
then edits data/lp_reported_results.json. Nothing here changes public pages.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INSTITUTIONS_CSV = ROOT / 'data' / 'lp_institutions.csv'
REPORTED_RESULTS = ROOT / 'data' / 'lp_reported_results.json'

# Short names the press uses that the institution registry does not list.
EXTRA_ALIASES = {
    'pck_pension': ('총회연금재단', '총회연금', '대한예수교장로회 총회연금재단'),
    'kfinco': ('전문건설공제조합', '전문조합', 'K-FINCO'),
    'moel_iaci': ('산재기금', '산재보험기금'),
    'moel_eif': ('고용기금', '고용보험기금'),
    'mmaa': ('군공',),
    'poba': ('지방행정공제회', '행공'),
    'kbiz': ('중기중앙회',),
    'koreapost': ('우본', '우체국'),
}
# Aliases too generic to identify one institution inside a news headline.
AMBIGUOUS_ALIASES = {'CU', 'TP', 'HF', 'SBA', 'IBK', 'KIC'}

RESULT_WORDS = re.compile(r'(선정|확정|낙점|뽑혀|뽑았|품에|이름\s*올|통과|결정)')
MANAGER_WORDS = re.compile(r'(위탁\s*운용사|운용사|GP|PEF|PE|블라인드)')
# Announcements of a coming selection, not a result.
FUTURE_WORDS = re.compile(r'(뽑는다|선정\s*(?:착수|나선|나섰|추진|예정|계획|절차)|모집|공고|앞둔|앞두고|도전|출사표|숏리스트|후보|경쟁|PT|프레젠테이션)')

NEWSLETTER_VIEW = 'newsletter_public_issue_articles'
NEWSLETTER_FIELDS = 'issue_date,publisher,title,summary_text,source_url,normalized_url,article_published_at'


@dataclass
class Candidate:
    program_id: str
    institution: str
    program_title: str
    reason: str
    articles: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            'program_id': self.program_id,
            'institution': self.institution,
            'program_title': self.program_title,
            'reason': self.reason,
            'articles': self.articles,
        }


def load_aliases(path: Path = INSTITUTIONS_CSV) -> dict[str, tuple[str, ...]]:
    aliases: dict[str, set[str]] = {}
    with path.open(encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            names = {row['lp_name'], *(a.strip() for a in (row.get('aliases') or '').split(';'))}
            aliases.setdefault(row['lp_code'], set()).update(n for n in names if n)
    for code, extra in EXTRA_ALIASES.items():
        aliases.setdefault(code, set()).update(extra)
    return {
        code: tuple(sorted((n for n in names if n not in AMBIGUOUS_ALIASES and len(n) >= 2), key=len, reverse=True))
        for code, names in aliases.items()
    }


def _alias_in(text: str, alias: str) -> bool:
    if re.fullmatch(r'[A-Za-z0-9-]+', alias):
        return re.search(rf'(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])', text) is not None
    return alias in text


def institutions_in(text: str, aliases: dict[str, tuple[str, ...]]) -> set[str]:
    found = set()
    for code, names in aliases.items():
        if any(_alias_in(text, name) for name in names):
            found.add(code)
    # 고용보험기금·산재보험기금 also appear as aliases of 근로복지공단; keep the fund itself.
    if found & {'moel_eif', 'moel_iaci'}:
        found.discard('comwel')
    return found


GENERIC_TITLE_WORDS = {'펀드', '위탁', '운용사', '위탁운용사', '선정', '출자', '사업', '공고', '계획', '결과', '국내', '블라인드',
                       '모집', '대체투자', '사모투자', '블라인드펀드', '출자사업', '하반기', '상반기', '부문', '분야'}


def title_words(text: str) -> set[str]:
    words = set()
    for word in re.findall(r'[가-힣A-Za-z0-9]{2,}', text or ''):
        if word in GENERIC_TITLE_WORDS or re.fullmatch(r'20\d{2}년?|\d+', word):
            continue
        words.add(word)
        # Korean compounds: also match on 2-character leading pieces like 남부권 → 남부.
        if re.fullmatch(r'[가-힣]{3,}', word):
            words.add(word[:2])
    return words - GENERIC_TITLE_WORDS


def is_result_report(title: str) -> bool:
    return bool(RESULT_WORDS.search(title) and MANAGER_WORDS.search(title) and not FUTURE_WORDS.search(title))


def article_key(article: dict) -> str:
    return (article.get('normalized_url') or article.get('source_url') or article.get('title') or '').strip()


def _program_year(program: dict) -> int | None:
    dates = [e.get('date') for e in program.get('events') or [] if isinstance(e, dict) and e.get('date')]
    years = [int(d[:4]) for d in dates if re.match(r'\d{4}-', d)]
    if years:
        return max(years)
    match = re.search(r'(20\d{2})', program.get('id', ''))
    return int(match.group(1)) if match else None


def _has_official_result(program: dict) -> bool:
    return bool(program.get('selected_gps') or program.get('preferred_gps'))


def find_candidates(programs: list[dict], articles: list[dict], reported: list[dict],
                    aliases: dict[str, tuple[str, ...]]) -> dict:
    """Group result-like articles by the LP program they most likely report on."""
    reported_by_program = {r['program_id']: r for r in reported}
    cited = {s.get('url', '').strip() for r in reported for s in r.get('sources', [])}
    programs_by_inst: dict[str, list[dict]] = {}
    for program in programs:
        programs_by_inst.setdefault(program.get('institution_id', ''), []).append(program)

    candidates: dict[str, Candidate] = {}
    unmatched: list[dict] = []
    seen: set[str] = set()
    for article in sorted(articles, key=lambda a: (a.get('issue_date') or ''), reverse=True):
        title = (article.get('title') or '').strip()
        key = article_key(article)
        if not title or key in seen or not is_result_report(title):
            continue
        seen.add(key)
        if (article.get('source_url') or '').strip() in cited or (article.get('normalized_url') or '').strip() in cited:
            continue
        insts = institutions_in(title, aliases)
        if not insts:
            continue
        year = int((article.get('issue_date') or '0000')[:4] or 0)
        entry = {
            'date': article.get('issue_date'),
            'publisher': article.get('publisher'),
            'title': title,
            'url': article.get('source_url') or article.get('normalized_url'),
            'summary': (article.get('summary_text') or '')[:240],
        }
        matched = False
        for inst in sorted(insts):
            pool = [p for p in programs_by_inst.get(inst, [])
                    if _program_year(p) is None or _program_year(p) in (year, year - 1)]
            # Prefer programs whose title shares a distinctive word with the headline
            # (남부권, 세컨더리, 무공해차 ...). A headline without one can only be about
            # a program that has no official roster yet.
            words = title_words(title)
            overlap = {p['id']: len(words & title_words(f"{p.get('title', '')} {p.get('display_title') or ''}")) for p in pool}
            best = max(overlap.values(), default=0)
            if best:
                pool = [p for p in pool if overlap[p['id']] == best]
            else:
                pool = [p for p in pool if not _has_official_result(p)]
            for program in pool:
                pid = program['id']
                existing = reported_by_program.get(pid)
                if _has_official_result(program):
                    reason = '공식 명단 있음 — 보도 내용과 다르면 확인'
                elif existing is None:
                    reason = '결과 미반영'
                elif not existing.get('complete'):
                    reason = '보도 기준 결과가 일부만 반영됨'
                else:
                    reason = '보도 기준 결과 반영됨 — 새 기사 확인'
                cand = candidates.setdefault(pid, Candidate(
                    pid, program.get('institution_name') or inst,
                    program.get('display_title') or program.get('title') or pid, reason))
                cand.articles.append(entry)
                matched = True
        if not matched:
            unmatched.append({**entry, 'institutions': sorted(insts)})

    order = {'결과 미반영': 0, '보도 기준 결과가 일부만 반영됨': 1, '보도 기준 결과 반영됨 — 새 기사 확인': 2,
             '공식 명단 있음 — 보도 내용과 다르면 확인': 3}
    ranked = sorted(candidates.values(), key=lambda c: (order.get(c.reason, 9), c.institution, c.program_id))
    return {'candidates': [c.as_dict() for c in ranked], 'unmatched_institution_articles': unmatched}


def render_markdown(result: dict, since: str) -> str:
    lines = [f'# LP 선정 결과 보도 후보 ({since} 이후 브리프 기사)', '']
    lines.append('공개 페이지를 바꾸지 않는다. 기사 원문을 확인해 `data/lp_reported_results.json`을 고친다'
                 '(절차: `docs/lp_reported_results_operations.md`).')
    lines.append('')
    if not result['candidates']:
        lines.append('새 후보 없음.')
    for cand in result['candidates']:
        lines.append(f"## {cand['institution']} · {cand['program_title']}")
        lines.append(f"- 사업: `{cand['program_id']}` — {cand['reason']}")
        for art in cand['articles']:
            lines.append(f"- {art['date']} {art['publisher']}: [{art['title']}]({art['url']})")
        lines.append('')
    if result['unmatched_institution_articles']:
        lines.append('## 공개 사업과 연결되지 않은 결과 기사')
        lines.append('공개 범위 밖(VC 전용 등)이거나 아직 공개하지 않은 사업일 수 있다.')
        for art in result['unmatched_institution_articles']:
            lines.append(f"- {art['date']} {art['publisher']} ({', '.join(art['institutions'])}): [{art['title']}]({art['url']})")
    return '\n'.join(lines) + '\n'


def fetch_articles(since: date, page_size: int = 1000) -> list[dict]:
    """All Brief articles since `since`, page by page (PostgREST caps one response)."""
    base = os.environ['SUPABASE_URL'].rstrip('/')
    key = os.environ['SUPABASE_PUBLISHABLE_KEY']
    rows: list[dict] = []
    for offset in range(0, 100_000, page_size):
        query = urllib.parse.urlencode({'select': NEWSLETTER_FIELDS, 'issue_date': f'gte.{since.isoformat()}',
                                        'order': 'issue_date.desc,article_id.asc', 'limit': str(page_size),
                                        'offset': str(offset)})
        request = urllib.request.Request(f'{base}/rest/v1/{NEWSLETTER_VIEW}?{query}',
                                         headers={'apikey': key, 'Authorization': f'Bearer {key}', 'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            page = json.loads(response.read().decode('utf-8'))
        rows.extend(page)
        if len(page) < page_size:
            break
    return rows


def fetch_programs() -> list[dict]:
    import psycopg
    with psycopg.connect(os.environ['SUPABASE_DB_URL'], connect_timeout=20, prepare_threshold=None,
                         application_name='lp-reported-result-candidates') as conn:
        conn.read_only = True
        row = conn.execute("SELECT data->'programs' FROM lp_program_private.program_state WHERE id=1").fetchone()
    return list(row[0] or []) if row else []


def load_reported(path: Path = REPORTED_RESULTS) -> list[dict]:
    return list(json.loads(path.read_text(encoding='utf-8')).get('results', []))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--days', type=int, default=180, help='look back this many days of Brief articles')
    parser.add_argument('--json-out', type=Path)
    parser.add_argument('--markdown-out', type=Path)
    args = parser.parse_args(argv)
    since = date.today() - timedelta(days=args.days)
    result = find_candidates(fetch_programs(), fetch_articles(since), load_reported(), load_aliases())
    result['since'] = since.isoformat()
    text = render_markdown(result, since.isoformat())
    if args.json_out:
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.markdown_out:
        args.markdown_out.write_text(text, encoding='utf-8')
    print(text)
    print(json.dumps({'candidates': len(result['candidates']),
                      'unmatched': len(result['unmatched_institution_articles'])}), file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
