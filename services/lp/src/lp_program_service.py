"""Evidence-backed LP program pages, shared by preview and future public builds."""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path
from html import escape
from collections import defaultdict
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from services.shared.web.identity_marks import mark_css, mark_tone  # noqa: E402  (shared with GP)

GP_PUBLIC_URL = os.environ.get('GP_PUBLIC_URL', 'https://kpef-gp.vercel.app').rstrip('/')
GP_ALIAS_RULES = ROOT / 'data' / 'gp_alias_merge_rules.csv'
_LEGAL_FORMS = re.compile(r'\(주\)|㈜|주식회사|유한책임회사|유한회사')


def _raw_gp_key(name):
    key = _LEGAL_FORMS.sub('', str(name or ''))
    key = re.sub(r'[\s·.,]+', '', key)
    # Spelling variants of the same romanised words.
    key = key.replace('에퀴티', '에쿼티').replace('매니져스', '매니저스')
    return key.lower()


def _load_gp_alias_rules(path=GP_ALIAS_RULES):
    import csv
    rules = {}
    try:
        with open(path, encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                if row.get('verification_decision') == 'MERGE_ALIAS':
                    rules[_raw_gp_key(row['alias_gp_name'])] = _raw_gp_key(row['canonical_gp_name'])
    except OSError:
        pass
    return rules


_GP_ALIASES = _load_gp_alias_rules()


def gp_name_key(name):
    """Comparison key for one manager across LPs: legal forms, spaces and known
    spelling variants removed, reviewed GP aliases (gp_alias_merge_rules.csv) applied."""
    key = _raw_gp_key(name)
    return _GP_ALIASES.get(key, key)


def gp_profile_index(profiles):
    """Map published GP profile IDs and unambiguous name keys to GP service URLs.

    `profiles` is the GP public contract read at publish time: {profile_id: name}
    for the published snapshot's gp-<id>.html pages. Missing contract -> no links."""
    by_id, by_name, clashes = {}, {}, set()
    for pid, name in (profiles or {}).items():
        if not re.fullmatch(r'[0-9]+', str(pid)) or not str(name or '').strip():
            continue
        url = f'{GP_PUBLIC_URL}/gp-{pid}.html'
        by_id[str(pid)] = url
        key = gp_name_key(name)
        if key in by_name and by_name[key] != url:
            clashes.add(key)
        by_name[key] = url
    for key in clashes:
        by_name.pop(key, None)
    return by_id, by_name


def gp_profile_url(gp, index):
    by_id, by_name = index
    if isinstance(gp, dict):
        if gp.get('master_id') and str(gp['master_id']) in by_id:
            return by_id[str(gp['master_id'])]
        name = gp.get('name')
    else:
        name = gp
    return by_name.get(gp_name_key(name))


def validate(data):
    date.fromisoformat(data['as_of'])
    ids = set()
    for p in data['programs']:
        if not re.fullmatch(r'[a-z0-9_-]+', p['id']) or p['id'] in ids:
            raise ValueError('Invalid or duplicate program ID')
        ids.add(p['id'])
        if not p['events'] or any(not e['url'].startswith('https://') for e in p['events']):
            raise ValueError('Every program/event requires a source')
        if p['status'] == '선정 완료' and not p['selected_gps']:
            raise ValueError('Completed selection requires sourced GP results')
        for gp in p['selected_gps']:
            if not gp.get('source_url') or not gp.get('asset_scope'):
                raise ValueError('GP selections require source and asset scope')
            if gp['source_url'] not in {e['url'] for e in p['events'] if e['type'] in ('최종 선정', '선정 결과')}:
                raise ValueError('Selected GP must link to this program final result event')
        if p.get('preferred_gps'):
            names = p['preferred_gps']
            origin = p.get('manager_list_sources', {}).get('preferred_gps')
            if (not isinstance(names, list) or not all(isinstance(n, str) and n.strip() for n in names)
                    or len(names) != len(set(names)) or origin not in {
                        e['url'] for e in p['events'] if e['type'] == '우선협상대상자'}):
                raise ValueError('Preferred bidders require a distinct sourced preferred stage')
        for e in p['events']:
            date.fromisoformat(e['date'])
            if e['date'] > data['as_of']:
                raise ValueError('Future event cannot be a completed timeline event')
    return data

def h(value):
    return escape(str(value or ''), quote=True)


def assert_selected_gp_history(before, after):
    """Preserve existing GP facts; separately validated additions may be appended.

    This guard does not approve sources. Callers must replay source evidence
    and validate complete projected programs before using it.
    """
    current = {p['id']: p for p in after}
    for previous in before:
        if previous['id'] not in current:
            raise ValueError('Existing program missing')
        selections = current[previous['id']].get('selected_gps', [])
        for gp in previous.get('selected_gps', []):
            if not any(all(candidate.get(key) == value for key, value in gp.items()) for candidate in selections):
                raise ValueError('Existing selected GP evidence changed or disappeared')
        if previous.get('preferred_gps'):
            updated = current[previous['id']]
            if (not set(previous['preferred_gps']) <= set(updated.get('preferred_gps', []))
                    or previous.get('manager_list_sources', {}).get('preferred_gps') !=
                    updated.get('manager_list_sources', {}).get('preferred_gps')):
                raise ValueError('Existing preferred bidder evidence changed or disappeared')

def source(url, label='공식 원문'):
    if not url.startswith('https://'):
        return h(label)
    return f'<a href="{h(url)}" target="_blank" rel="noopener">{h(label)} ↗</a>'

CSS = '''*{box-sizing:border-box}body{margin:0;background:#fff;color:#171717;font:15px/1.65 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif}main{max-width:1000px;margin:auto;padding:32px 24px 110px}a{color:inherit;text-underline-offset:4px}header{border-bottom:1px solid #e8e8e8;padding-bottom:22px;margin-bottom:24px}h1{word-break:keep-all;overflow-wrap:break-word;font-size:28px;line-height:1.35;letter-spacing:-1px;margin:12px 0}h2{font-size:19px;margin:32px 0 12px}p{margin:8px 0}.muted,small{color:#737373}small{display:block}.eyebrow{font-size:12px;letter-spacing:1px;color:#666}.controls{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0}input,select{font:inherit;border:1px solid #ddd;border-radius:6px;padding:10px;background:white}input{flex:1;min-width:180px}.program{padding:22px 0;border-bottom:1px solid #e8e8e8}.program h2{font-size:18px;margin:8px 0}.program a{text-decoration:none}.program a:hover{text-decoration:underline}.badge{font-size:12px;background:#f3f5f6;border-radius:4px;padding:4px 8px;color:#414b54}.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;padding:20px 0;border-block:1px solid #eee}.facts strong{display:block}.timeline{padding-left:20px}.timeline li{padding:0 0 22px 12px}.timeline time{font-size:13px;color:#737373}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:15px 10px;border-bottom:1px solid #eee;vertical-align:top}th{font-size:12px;color:#737373}.scroll{overflow:auto}nav:where(.bottom-nav){position:fixed;bottom:0;left:0;right:0;background:#fffffff5;border-top:1px solid #eee;display:flex;justify-content:center;gap:80px;padding:16px;backdrop-filter:blur(10px)}nav:where(.bottom-nav) a{text-decoration:none;color:#777}nav:where(.bottom-nav) .active{color:#171717;font-weight:700}.notice{font-size:13px;color:#737373;background:#f8f8f8;padding:14px 16px;margin:24px 0}[hidden]{display:none!important}@media(max-width:600px){main{padding:22px 18px 90px}h1{font-size:23px}.facts{grid-template-columns:1fr 1fr}nav:where(.bottom-nav){gap:65px}td{min-width:105px}}'''

CSS += """.investment-purpose{padding:16px 0;border-bottom:1px solid #e3e8ee}.investment-purpose>strong{font-size:14px;color:#66717e}.investment-purpose p{margin:6px 0;font-size:16px}.investment-purpose>a{font-size:13px;color:#456181}.back{font-size:14px;color:#6d7783;text-decoration:none}.detail-header{margin-top:22px;padding-bottom:22px}.institution{font-size:15px;color:#456181}.detail-meta{display:flex;align-items:center;justify-content:space-between;gap:16px}.detail-meta>a{font-size:14px;color:#365d87}.detail-header h1{margin:12px 0 20px}.event-list{list-style:none;padding:0;margin:0;border-top:2px solid #344c68}.event{display:grid;grid-template-columns:160px minmax(0,1fr) 55px;gap:18px;padding:14px 0;border-bottom:1px solid #e3e8ee;align-items:start}.event time{font-size:14px;color:#53677f;font-variant-numeric:tabular-nums}.event strong{font-size:16px;font-weight:600}.event>a{font-size:13px;color:#4b6786}.event small{font-size:13px;margin-top:4px}.planned{background:#f8f9fb}.planned-label{font-size:12px;color:#687d94;border:1px solid #dce3ec;border-radius:3px;padding:2px 5px;margin-left:6px}#offering .facts{grid-template-columns:1fr 2fr;border-top:1px solid #e3e8ee}section{margin-bottom:30px}#schedule h2{margin-top:0}#selection{margin-bottom:0}@media(max-width:600px){.event{grid-template-columns:minmax(0,1fr) 48px;gap:5px 10px;padding:14px 0}.event time{grid-column:1;grid-row:1}.event>div{grid-column:1/-1;grid-row:2}.event>a{grid-column:2;grid-row:1}.event time{font-size:13px}.event strong{font-size:15px}.detail-meta{align-items:start}.facts strong{font-size:15px}}"""

CSS += """.stage-flow{display:flex;list-style:none;padding:12px 0;gap:20px;color:#53677f;font-size:14px}.stage-flow li+li:before{content:"→";margin-right:20px;color:#aaa}.planned-label:empty{display:none}#offering .facts:has(>div:nth-child(3)){grid-template-columns:1fr 1fr 1fr}"""

# 40px monogram slot, like the publisher and GP logo circles in 브리프·GP rows.
INSTITUTION_MARKS = {
    'kgrowth': '성장', 'ibk': 'IBK', 'kdb': 'KDB', 'kexim': '수은', 'koreapost': '우본', 'pck_pension': '총회',
    'ktcu': '교공', 'kfinco': '전문', 'cu': '신협', 'kamco': '캠코', 'sema': '과기', 'kbiz': '중기', 'mmaa': '군공',
    'pmaa': '경찰', 'poba': '행공', 'tp': '사학', 'kfcc': 'MG', 'moel_iaci': '산재', 'moel_eif': '고용',
    'geps': '공무', 'nps': 'NPS', 'cwma': '건근', 'nh_central': '농협', 'suhyup': '수협', 'kic': 'KIC',
}


# Official symbol marks, stored in the repository (services/lp/data/logos/<code>.png,
# 96px squares cut from each institution's own site or Wikimedia) and embedded in
# the page, so a slow or blocking institution site never breaks the icon. Wide
# wordmarks are not used: squeezed into a 40px tile they are unreadable.
LOGO_DIR = Path(__file__).resolve().parents[1] / 'data' / 'logos'


def _load_logos(folder=LOGO_DIR):
    import base64
    logos = {}
    for path in sorted(folder.glob('*.png')) if folder.is_dir() else []:
        logos[path.stem] = 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
    return logos


INSTITUTION_LOGOS = _load_logos()


def logo_css(html_body):
    """Background-image rules for the institution logos a page actually shows."""
    used = sorted(set(re.findall(r'data-logo="([a-z0-9_]+)"', html_body)))
    return ''.join(f'.lp-sample .lp-mark.has-logo[data-logo="{code}"]{{background-image:url({INSTITUTION_LOGOS[code]})}}'
                   for code in used if code in INSTITUTION_LOGOS)


# Tint close to each institution's own colour where it has a well-known one
# (identity_marks palette: 1 blue, 2 teal, 3 green, 4 amber, 5 red, 6 violet, 7 slate, 8 cyan).
INSTITUTION_TONES = {'koreapost': 5, 'kdb': 1, 'ibk': 1, 'kexim': 8, 'kgrowth': 2, 'nps': 1, 'kfcc': 1, 'kamco': 8}


def institution_mark(institution_id, name):
    mark = INSTITUTION_MARKS.get(institution_id)
    if mark:
        return mark
    name = re.sub(r'^(한국|대한|주식회사)', '', str(name or '')).strip()
    return name[:2] or 'LP'


LP_TYPE_LABELS = {
    'Public Pension': '공적연금', 'Fund of Funds': '모태펀드 운용기관', 'Policy Fund of Funds': '정책펀드 운용기관',
    'Policy Bank': '정책금융기관', 'Public Fund': '공공기금', 'Mutual Aid Association': '공제회',
    'Mutual Aid/Industry Association': '공제회', 'Mutual Finance': '상호금융', 'Sovereign Wealth Fund': '국부펀드',
    'Policy Finance Institution': '정책금융기관', 'Public Agency': '공공기관', 'Regional Public Agency': '지역 공공기관',
    'Public Fund / OCIO Mandate': '공공기금',
}


def _load_institution_profiles(path=ROOT / 'data' / 'lp_institutions.csv'):
    """Type and official links per institution code; empty when the master is unreadable."""
    import csv
    try:
        with open(path, encoding='utf-8') as handle:
            return {row['lp_code']: row for row in csv.DictReader(handle) if row.get('lp_code')}
    except (OSError, KeyError):
        return {}


INSTITUTION_PROFILES = _load_institution_profiles()


def institution_header_html(institution_id, title, summary):
    """Institution page header: tile, name, type, counts and official links."""
    profile = INSTITUTION_PROFILES.get(institution_id, {})
    kind = LP_TYPE_LABELS.get(profile.get('lp_type', ''), '')
    links = []
    for label, key in (('공식 홈페이지', 'homepage_url'), ('출자 공고 게시판', 'notice_url')):
        url = profile.get(key, '')
        if url.startswith('https://') or url.startswith('http://'):
            links.append(f'<a href="{h(url)}" target="_blank" rel="noopener noreferrer">{label} ↗</a>')
    tile = institution_mark_html(institution_id, title).replace('class="lp-mark', 'class="lp-mark lp-mark-large', 1)
    return (f'<header class="institution-header">{tile}<div class="institution-heading">'
            + (f'<span class="institution-kind">{h(kind)}</span>' if kind else '')
            + f'<h1>{h(title)}</h1><p>{summary}</p>'
            + (f'<div class="institution-links">{"".join(links)}</div>' if links else '')
            + '</div></header>')


def institution_mark_html(institution_id, name):
    """40px identity tile shared with GP: symbol logo when one reads well, else a tinted label."""
    label = institution_mark(institution_id, name)
    tone = INSTITUTION_TONES.get(institution_id) or mark_tone(str(institution_id or name))
    if institution_id in INSTITUTION_LOGOS:
        return (f'<span class="lp-mark has-logo" data-logo="{h(institution_id)}" data-tone="{tone}" '
                f'data-label-length="{len(label)}" aria-hidden="true"><span>{h(label)}</span></span>')
    return f'<span class="lp-mark" data-tone="{tone}" data-label-length="{len(label)}" aria-hidden="true"><span>{h(label)}</span></span>'


def service_header(path=None):
    """Same header as 브리프 and GP: service title and section tabs."""
    on_institutions = str(path or '').startswith('institution')
    tab = lambda label, href, active: (f'<a class="brief-section-tab{" active" if active else ""}" href="{href}"'
                                       + (' aria-current="page"' if active else '') + f'>{label}</a>')
    return ('<header class="app-header lp-app-header"><div class="service-bar"><strong class="service-title">LP</strong></div>'
            '<nav class="brief-section-tabs" aria-label="LP 메뉴">'
            + tab('출자사업', 'index.html', not on_institutions)
            + tab('출자기관', 'institution-directory.html', on_institutions) + '</nav></header>')


def shell(title, body, as_of, description='', path=None):
    sample_css = (Path(__file__).with_name('lp_sample.css')).read_text()
    newsletter_url = h(os.environ.get('NEWSLETTER_PUBLIC_URL', 'https://kpef-newsletter.vercel.app').rstrip('/'))
    gp_url = h(os.environ.get('GP_PUBLIC_URL', 'https://kpef-gp.vercel.app').rstrip('/'))
    lp_url = os.environ.get('LP_PUBLIC_URL', 'https://kpef-lp.vercel.app').rstrip('/')
    description = description or '국내 기관전용 사모펀드 출자사업 공고·일정·선정 운용사를 공식 원문 기준으로 정리합니다.'
    meta = (f'<meta name="description" content="{h(description)}"><meta property="og:type" content="website">'
            f'<meta property="og:title" content="{h(title)} · LP"><meta property="og:description" content="{h(description)}">'
            + (f'<link rel="canonical" href="{h(lp_url)}/{h(path)}"><meta property="og:url" content="{h(lp_url)}/{h(path)}">' if path is not None else ''))
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{h(title)} · LP</title>{meta}<link rel="stylesheet" href="/assets/service.css"><style>{CSS}\n{sample_css}\n{MARK_CSS}{LOGO_TILE_CSS}{logo_css(body)}</style></head><body class="lp-sample"><main>{service_header(path)}{body}</main><nav class="bottom-nav" aria-label="하단 메뉴"><a href="{newsletter_url}/"><span aria-hidden="true" class="nav-dot nav-icon-brief"></span><strong>브리프</strong></a><a class="active" aria-current="page" href="index.html"><span aria-hidden="true" class="nav-dot nav-icon-lp"></span><strong>LP</strong></a><a href="{gp_url}/"><span aria-hidden="true" class="nav-dot nav-icon-gp"></span><strong>GP</strong></a></nav></body></html>'

NEW_NOTICE_DAYS = 7
LOGO_TILE_CSS = ('.lp-sample .lp-mark.has-logo[data-logo]{background-color:#fff;background-repeat:no-repeat;'
                 'background-position:center;background-size:72%}')
MARK_CSS = (mark_css('.lp-mark', scope='.lp-sample') + mark_css('.lp-mark-large', size=56, radius=14, scope='.lp-sample')
            + '.lp-sample .lp-mark-large{font-size:17px}.lp-sample .lp-mark-large[data-label-length="3"],'
            '.lp-sample .lp-mark-large[data-label-length="4"]{font-size:14px}')
PUBLIC_NOTICE_CONTEXT_VERSION = 'lp-public-notice-context-v1'


def public_notice_context(programs, as_of):
    """LP -> GP public contract: official selection results only (no press-reported
    results, no candidates). Same row shape GP's hydrate_gp_lp_context.py reads."""
    lp_url = os.environ.get('LP_PUBLIC_URL', 'https://kpef-lp.vercel.app').rstrip('/')
    rows = []
    for p in programs:
        if not p.get('selected_gps'):
            continue
        result_dates = [e['date'] for e in p['events'] if e['type'] in ('최종 선정', '선정 결과')]
        rows.append({
            'lpCode': p['institution_id'],
            'lpName': p['institution_name'],
            'noticeId': p['id'],
            'title': p.get('public_title') or p['title'],
            'programName': p.get('list_title') or p.get('public_title') or p['title'],
            'eventType': 'final_selection',
            'eventDate': max(result_dates) if result_dates else max(e['date'] for e in p['events']),
            'announcedDate': min(e['date'] for e in p['events']),
            'noticeUrl': f'{lp_url}/program-{p["id"]}.html',
            'assetClass': 'PE·VC' if p.get('mixed_scope') else 'PE',
            'selectedGpNames': list(dict.fromkeys(g['name'] for g in p['selected_gps'])),
        })
    rows.sort(key=lambda r: (r['eventDate'], r['noticeId']), reverse=True)
    return {'schemaVersion': PUBLIC_NOTICE_CONTEXT_VERSION, 'reportDate': str(as_of)[:10], 'notices': rows}


def build(data, out, gp_profiles=None):
    validate(data)
    profile_index = gp_profile_index(gp_profiles)
    out.mkdir(parents=True, exist_ok=True)
    as_of = data['as_of']
    try:
        from .lp_program_detail import render_detail_body, display_status, STATUS_ORDER, RESULT_STATUSES, clean_title
    except ImportError:
        from lp_program_detail import render_detail_body, display_status, STATUS_ORDER, RESULT_STATUSES, clean_title
    # One public name per institution: the most used stored name, then the shortest.
    names = defaultdict(list)
    for p in data['programs']:
        names[p['institution_id']].append(p['institution_name'])
    canonical = {k: min(set(v), key=lambda n: (-v.count(n), len(n), n)) for k, v in names.items()}
    # Render from shallow copies so stored evidence keeps its source wording.
    latest = lambda p: max(e['date'] for e in p['events'])
    programs = sorted(({**p, 'institution_name': canonical[p['institution_id']]} for p in data['programs']),
                      key=latest, reverse=True)
    # Press-reported results (labelled) and joint PE·VC recruitment, on render copies only.
    reported = data.get('reported_results') or {}
    for p in programs:
        if not (p.get('selected_gps') or p.get('preferred_gps')) and p['id'] in reported:
            p['reported_result'] = reported[p['id']]
        p['mixed_scope'] = bool(re.search(r'벤처|신기술|VC', str(p.get('asset_scope') or '')))
    # A recruitment notice with no parsed deadline is not shown as current after 30 days.
    stale_before = (date.fromisoformat(str(as_of)[:10]) - timedelta(days=30)).isoformat()
    for p in programs:
        status = display_status(p['status'])
        if status == '모집 공고' and max(e['date'] for e in p['events']) < stale_before:
            status = '공고'
        reported_result = p.get('reported_result')
        if reported_result and status not in RESULT_STATUSES:
            # A press-reported outcome is a result, not an open 접수 마감 row.
            status = '선정 없음' if reported_result['stage'] == '선정 없음' else '결과 보도'
        p['display_status'] = status
    # Reader-facing names: curated short names win; otherwise the cleaned source title.
    # Identical names within one institution are told apart by the notice month.
    for p in programs:
        p['public_title'] = clean_title(p['title'])
        p['list_title'] = p.get('display_title') or p['public_title']
    seen = defaultdict(list)
    for p in programs:
        seen[(p['institution_id'], p['list_title'])].append(p)
    for group in seen.values():
        if len(group) > 1:
            for p in group:
                first = min(e['date'] for e in p['events'])
                when = f"{int(first[5:7])}월 공고" if first[:4] == str(as_of)[:4] else f"{first[:4]}년 {int(first[5:7])}월 공고"
                p['list_title'] += f' · {when}'
                p['public_title'] += f' · {when}'
    # Open recruitments first, nearest deadline first; the rest by latest sourced event.
    open_now = sorted((p for p in programs if p['status'] == '접수 중'), key=lambda p: (p.get('deadline') or '9999'))
    programs = open_now + [p for p in programs if p['status'] != '접수 중']
    def short_date(value):
        y, m, d = str(value)[:10].split('-')
        return f'{m}.{d}' if y == str(as_of)[:4] else f'{y}.{m}.{d}'
    gp_programs, institutions = defaultdict(list), defaultdict(list)
    gp_index = {}
    for p in programs:
        institutions[p['institution_id']].append(p)
        for gp in p['selected_gps']:
            key = gp.get('master_id') or gp.get('id')
            if not key or not re.fullmatch(r'[a-zA-Z0-9_-]+', str(key)):
                raise ValueError('GP requires stable safe key')
            gp['page_key'] = str(key)
            gp_index[str(key)] = gp
            gp_programs[str(key)].append((p, gp))
    def row(p):
        status = p['display_status']
        last = max(p['events'], key=lambda e:e['date'])
        dday = ''
        reported = p.get('reported_result')
        if p['selected_gps']:
            timing = f"{short_date(last['date'])} 선정 · {len(p['selected_gps'])}개사"
        elif reported:
            count = len(reported['managers'])
            outcome = '선정 없음' if not count else (f'{count}개사' if reported['complete'] else f'확인 {count}개사')
            timing = f"{short_date(reported['reported_at'])} 보도 · {outcome}"
        elif status in ('1차 심사 결과', '우선협상대상자', '접수 결과') and (
                not p.get('deadline') or last['date'] > str(p['deadline'])[:10]):
            # After the deadline the latest stage is what readers need.
            names = p.get('preferred_gps') if status == '우선협상대상자' else p.get('shortlisted_gps')
            timing = f"{short_date(last['date'])} {status}" + (f" · {len(set(names))}개사" if names else '')
        elif p.get('deadline'):
            timing = f"{short_date(p['deadline'])} 마감"
            if p['status'] == '접수 중':
                dday = f'<span class="program-dday" data-lp-dday="{h(str(p["deadline"])[:10])}"></span>'
        elif p['status'] in ('선정 결과 발표', '선정 완료'):
            timing = f"{short_date(last['date'])} 결과 발표"
        else:
            timing = f"{short_date(last['date'])} 공고"
        # A notice first published within the last week is marked new; the page
        # script drops the mark when the week ends before the next publication.
        first = min(e['date'] for e in p['events'])[:10]
        new_until = (date.fromisoformat(first) + timedelta(days=NEW_NOTICE_DAYS)).isoformat()
        fresh = (f'<span class="program-new" data-lp-new-until="{h(new_until)}">새 공고</span>'
                 if status not in RESULT_STATUSES and status != '공고' and new_until > str(as_of)[:10] else '')
        amount = f"{p['commitment_amount_krw']/100000000:,.0f}억원" if p.get('commitment_amount_krw') else ''
        amount = p.get('list_commitment_label') or p.get('commitment_label') or amount
        if '미확인' in amount:
            # A total that is not this PE track's allocation is not a list amount.
            amount = ''
        return f'<article class="program" data-status="{h(status)}" data-institution="{h(p["institution_id"])}" data-search="{h(p["title"] + " " + p["list_title"])}"><a class="program-link" href="program-{h(p["id"])}.html">{institution_mark_html(p["institution_id"], p["institution_name"])}<div class="program-body"><div class="program-top"><span class="program-institution">{h(p["institution_name"])}{" · PE·VC 공동" if p.get("mixed_scope") else ""}{fresh}</span><span class="program-status{' open' if status == '접수 중' else ''}">{h(status)}</span></div><h2 class="program-title">{h(p["list_title"])}</h2><div class="program-bottom"><span>{h(amount)}</span><span>{h(timing)}{dday}</span></div></div></a></article>'
    options = ''.join(f'<option value="{h(k)}">{h(v[0]["institution_name"])}</option>' for k,v in institutions.items())
    shown = {p['display_status'] for p in programs}
    statuses = ''.join(f'<option>{h(s)}</option>' for s in [*[s for s in STATUS_ORDER if s in shown], *sorted(shown - set(STATUS_ORDER))])
    body = f'<header class="list-header"><p class="result-summary"><span id="count">{len(programs)}개 사업</span> · <a class="list-link" href="institution-directory.html">출자기관 {len(institutions)}곳</a></p></header><div class="controls"><input aria-label="사업 검색" placeholder="기관·사업명 검색"><select aria-label="진행 상태"><option value="">모든 상태</option>{statuses}</select><select aria-label="출자기관"><option value="">모든 기관</option>{options}</select></div>'
    sections = (('진행 중', [p for p in programs if p['display_status'] not in RESULT_STATUSES and p['display_status'] != '공고']),
                ('결과 발표', [p for p in programs if p['display_status'] in RESULT_STATUSES]),
                ('지난 공고', [p for p in programs if p['display_status'] == '공고']))
    for label, group in sections:
        if group:
            body += f'<section class="program-section"><h2 class="section-title">{h(label)} <span>{len(group)}</span></h2>' + ''.join(row(p) for p in group) + '</section>'
    body += '<p id="empty" hidden>조건에 맞는 사업이 없습니다.</p>'
    body += '''<script>const q=document.querySelector('input'),s=document.querySelectorAll('select');function filter(){let n=0;document.querySelectorAll('.program').forEach(r=>{r.hidden=!((r.textContent+" "+r.dataset.search).toLowerCase().includes(q.value.toLowerCase())&&(!s[0].value||r.dataset.status===s[0].value)&&(!s[1].value||r.dataset.institution===s[1].value));if(!r.hidden)n++});document.querySelectorAll('.program-section').forEach(sec=>{const k=sec.querySelectorAll('.program:not([hidden])').length;sec.hidden=k===0;sec.querySelector('.section-title span').textContent=k});document.querySelector('#count').textContent=n+'개 사업';document.querySelector('#empty').hidden=n!==0}q.addEventListener('input',filter);s.forEach(e=>e.addEventListener('change',filter));(function(){const p=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());const today=Date.parse(p+'T00:00:00Z');document.querySelectorAll('[data-lp-new-until]').forEach(e=>{e.hidden=Date.parse(e.dataset.lpNewUntil+'T00:00:00Z')<=today});document.querySelectorAll('[data-lp-dday]').forEach(e=>{const n=Math.round((Date.parse(e.dataset.lpDday+'T00:00:00Z')-today)/86400000);e.textContent=n>0?' · D-'+n:(n===0?' · 오늘 마감':'')})})();</script>'''
    (out/'index.html').write_text(shell('출자사업',body,as_of,path=''))
    for p in programs:
        urls = {}
        for gp in p['selected_gps']:
            url = gp_profile_url(gp, profile_index)
            if url:
                urls[gp['name']] = url
        others = list(p.get('preferred_gps') or []) + list(p.get('shortlisted_gps') or [])
        others += list((p.get('reported_result') or {}).get('managers') or [])
        for name in others:
            url = gp_profile_url(name, profile_index)
            if url:
                urls.setdefault(name, url)
        p['gp_profile_urls'] = urls
        (out/f'program-{p["id"]}.html').write_text(shell(p['public_title'], render_detail_body(p, as_of), as_of,
            description=f"{p['institution_name']} · {p['public_title']} · {display_status(p['status'])}. 모집 일정과 선정 운용사를 공식 원문과 함께 정리합니다.",
            path=f'program-{p["id"]}.html'))
    # The same manager selected by different LPs: one history on every existing page.
    # Grouped by reviewed GP master ID or by the exact name ignoring spaces; spelling
    # variants stay separate until a reviewed identity links them.
    parent = {}
    def find(x):
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x
    for key, entries in gp_programs.items():
        for _, gp in entries:
            ids = [f'k:{key}', 'n:' + gp_name_key(gp['name'])]
            if gp.get('master_id'):
                ids.append(f"m:{gp['master_id']}")
            for other in ids[1:]:
                parent[find(other)] = find(ids[0])
    histories = defaultdict(list)
    for key, entries in gp_programs.items():
        histories[find(f'k:{key}')].extend(entries)
    def selection_count(group):
        return len({gp_name_key(g['name']) for p in group for g in p['selected_gps']})
    def gp_links(group):
        names = {}
        for p in group:
            for g in p['selected_gps']:
                names.setdefault(gp_name_key(g['name']), g)
        return ''.join(f'<li><a href="selected-gp-{h(g["page_key"])}.html">{h(g["name"])}</a></li>' for g in names.values())
    directory = sorted(institutions.items(), key=lambda kv: max(max(e['date'] for e in p['events']) for p in kv[1]), reverse=True)
    for key,group in institutions.items():
        title=group[0]['institution_name']
        selected = selection_count(group)
        summary = f'출자사업 {len(group)}건' + (f' · 선정 운용사 {selected}곳' if selected else '')
        body=f'<a class="back" href="institution-directory.html">← 출자기관</a>{institution_header_html(key, title, summary)}'
        if selected:
            body += f'<section class="institution-gps"><h2>선정 운용사</h2><ul class="gp-names">{gp_links(group)}</ul></section>'
        body += '<h2>출자사업</h2>' + ''.join(row(p) for p in group)
        (out/f'institution-{key}.html').write_text(shell(title,body,as_of,description=f'{title}의 기관전용 사모펀드 출자사업 {summary}.',path=f'institution-{key}.html'))
    rows = ''
    for key, group in directory:
        selected = selection_count(group)
        last = max(max(e['date'] for e in p['events']) for p in group)
        meta = f'출자사업 {len(group)}건' + (f' · 선정 운용사 {selected}곳' if selected else '')
        rows += (f'<article class="program"><a class="program-link" href="institution-{h(key)}.html">'
                 f'{institution_mark_html(key, group[0]["institution_name"])}<div class="program-body">'
                 f'<h2 class="program-title">{h(group[0]["institution_name"])}</h2>'
                 f'<div class="program-bottom"><span>{h(meta)}</span><span>{h(short_date(last))} 최근 공고·결과</span></div></div></a></article>')
    body = f'<header class="list-header"><p class="result-summary">출자기관 {len(directory)}곳</p></header>{rows}'
    (out/'institution-directory.html').write_text(shell('출자기관', body, as_of, description='기관전용 사모펀드 출자사업을 공고한 출자기관 목록입니다.', path='institution-directory.html'))
    for key,group in gp_programs.items():
        gp=gp_index[key]
        merged = list({p['id']: (p, g) for p, g in sorted(histories[find(f'k:{key}')], key=lambda pg: max(e['date'] for e in pg[0]['events']), reverse=True)}.values())
        profile = gp_profile_url(gp, profile_index) or next((u for u in (gp_profile_url(g, profile_index) for _, g in merged) if u), None)
        profile_link = f'<p><a class="gp-profile-link" href="{h(profile)}">GP 프로필 보기 →</a></p>' if profile else ''
        body=f'<a href="index.html">← 출자사업</a><header><div class="eyebrow">GP / 출자사업 선정 이력</div><h1>{h(gp["name"])}</h1><p>선정 이력 {len(merged)}건</p>{profile_link}</header><h2>선정된 사업</h2>'
        for p,g in merged: body+=row(p)+f'<p>{source(g["source_url"],"공식 선정 근거")}</p>'
        body+='<p class="muted">수록된 출자사업의 선정 이력입니다.</p>'
        (out/f'selected-gp-{key}.html').write_text(shell(gp['name'],body,as_of,description=f"{gp['name']}의 출자사업 선정 이력 {len(merged)}건.",path=f'selected-gp-{key}.html'))
    return {'programs':len(programs),'institutions':len(institutions),'gps':len(gp_programs),'as_of':as_of,
            'public_notice_context': public_notice_context(programs, as_of)}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(build(json.loads(args.input.read_text()),args.out),ensure_ascii=False))
