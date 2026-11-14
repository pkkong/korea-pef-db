"""One schedule-first detail template for every LP program."""
from html import escape
import calendar
import re
from datetime import date, datetime, timedelta, timezone

try:
    from .lp_calendar import deadline_calendar_block
except ImportError:
    from lp_calendar import deadline_calendar_block


def planned_until(event):
    """Conservative upper boundary for display, never a claimed event date.

    A vague early/mid/late-month plan is only certainly past once its whole
    month has passed. Unknown/relative dates receive no invented boundary.
    """
    value = str(event.get('date') or '')
    try:
        if (re.fullmatch(r'20\d{2}-\d{2}-\d{2}(?:T.*)?', value)
                and event.get('precision') in (None, 'date', 'day', 'datetime')):
            return date.fromisoformat(value[:10]).isoformat()
        year = month = None
        for match in re.finditer(r'(?:(20\d{2})\s*년\s*)?(\d{1,2})\s*월', event.get('date_label') or ''):
            explicit_year, next_month = match[1], int(match[2])
            if explicit_year:
                year = int(explicit_year)
            elif year is None or (month is not None and next_month < month):
                return None
            month = next_month
            date(year, month, 1)
        if year and month:
            return date(year, month, calendar.monthrange(year, month)[1]).isoformat()
        if re.fullmatch(r'20\d{2}-\d{2}(?:-\d{2})?', value):
            year, month = map(int, value[:7].split('-'))
            return date(year, month, calendar.monthrange(year, month)[1]).isoformat()
    except ValueError:
        pass
    return None


def _today():
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def planned_badge(event, as_of):
    until = planned_until(event)
    label = '예정일 경과' if until and until < as_of else '예정'
    attrs = f' data-lp-plan-until="{h(until)}"' if until else ''
    return f'<span class="planned-label"{attrs}>{label}</span>'


PLAN_SCRIPT = '''<script>(function(){const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const part=t=>parts.find(p=>p.type===t).value;const today=part('year')+'-'+part('month')+'-'+part('day');document.querySelectorAll('[data-lp-plan-until]').forEach(e=>{e.textContent=e.dataset.lpPlanUntil<today?'예정일 경과':'예정'});document.querySelectorAll('[data-lp-note-until]').forEach(e=>{if(e.dataset.lpNoteUntil<today)e.textContent=e.dataset.lpPastNote});document.querySelectorAll('[data-lp-calendar-until]').forEach(e=>{e.hidden=e.dataset.lpCalendarUntil<today})})();</script>'''

# Public wording only: stored statuses keep their source-specific meaning.
STATUS_DISPLAY = {'선정 결과 발표': '선정 완료', '서류심사 결과': '1차 심사 결과'}
STATUS_ORDER = ('접수 중', '모집 공고', '접수 마감', '접수 결과', '1차 심사 결과', '우선협상대상자', '선정 완료', '결과 보도', '선정 없음', '공고')
# List sections for readers: what is still moving, what has a result, and old notices.
RESULT_STATUSES = ('선정 완료', '결과 보도', '선정 없음')


def display_status(status):
    status = '접수 마감' if str(status).startswith('접수 마감') else str(status)
    return STATUS_DISPLAY.get(status, status)


_TITLE_PREFIX = re.compile(r'^\s*(?:\[[^\]]{1,30}\]\s*)+')
_NOTICE_NUMBER = re.compile(r'\s*\([^()]*공고\s*(?:제\s*)?\d{4}\s*-\s*\d+\s*호?\)\s*$')
_SHORT_YEAR = re.compile(r"^[’'‘]\s*(\d{2})\s*년")


# Notice wording around the fund name: "출자사업 위탁운용사 선정계획 공고" and its variants.
_NOTICE_TAIL = re.compile(
    r'\s*(?:출자\s*사업\s*)?(?:위탁\s*)?(?:운용사\s*)?(?:선정\s*)?(?:계획\s*)?(?:공고|선정)\s*$')
_GP_WORD_BEFORE_TRACK = re.compile(r'\s*위탁\s*운용사\s*(?=\()')


def clean_title(title, institution_names=()):
    """Reader-facing program name; the source title is still shown on the detail page.

    Drops board prefixes, notice numbers and the "…위탁운용사 선정계획 공고" tail, and the
    institution's own name (shown next to every title). Keeps track words such as (중형PE).
    """
    original = str(title or '').strip()
    text = _TITLE_PREFIX.sub('', original)
    text = _NOTICE_NUMBER.sub('', text)
    text = _SHORT_YEAR.sub(lambda m: f'20{m[1]}년', text)
    text = re.sub(r'[「」『』]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    trimmed = _GP_WORD_BEFORE_TRACK.sub(' ', text)
    for _ in range(2):
        trimmed = _NOTICE_TAIL.sub('', trimmed).strip()
    names = sorted({n for n in institution_names if n and len(n) >= 3}, key=len, reverse=True)

    def without_names(value):
        for name in names:
            value = re.sub(rf'(?<![가-힣]){re.escape(name)}\s*', '', value, count=1)
        return re.sub(r'\s+', ' ', value).strip(' ·-')

    trimmed = without_names(trimmed)
    # Too little left (e.g. "국내 PE·VC"): keep the notice wording instead.
    if len(re.sub(r'\s', '', trimmed)) < 8:
        trimmed = without_names(text)
    return trimmed or text or original


def h(value):
    return escape(str(value or ''), quote=True)

def link(url, label='원문'):
    if not url or not url.startswith('https://'):
        return ''
    return f'<a href="{h(url)}" target="_blank" rel="noopener">{h(label)} ↗</a>'

_FLOW_STAGE = {'announcement': 0, 'application': 1, 'screening': 2, 'due_diligence': 2,
               'interview': 2, 'preferred': 2, 'preferred_roster': 2, 'selection': 3}


def _flow_step(stage):
    """Map a sourced schedule stage to the four-step reader flow, or None."""
    if stage.get('stage') in _FLOW_STAGE:
        return _FLOW_STAGE[stage['stage']]
    label = str(stage.get('label') or '')
    for pattern, step in (('선정', 3), ('심사|평가|실사|협상', 2), ('접수|마감', 1), ('공고', 0)):
        if re.search(pattern, label):
            return step
    return None


def profile_link(p, name):
    """Small link to the GP service profile when the GP contract has one."""
    url = (p.get('gp_profile_urls') or {}).get(name)
    return f'<small><a class="gp-profile" href="{h(url)}">GP 프로필</a></small>' if url else ''


def reported_block(result, p=None):
    """Press-reported result: always labelled and sourced; never an official fact."""
    scope = f" ({result['scope_note']})" if result.get('scope_note') else ''
    out = (f'<div class="reported-result"><p><span class="badge">보도 기준</span> '
           f'공식 결과 공고가 확인되지 않아 언론 보도를 기준으로 정리했습니다{h(scope)}.</p>')
    if result['managers']:
        out += '<ul class="gp-names">' + ''.join(f'<li>{h(m)}{profile_link(p or {}, m)}</li>' for m in result['managers']) + '</ul>'
        if not result['complete']:
            out += '<p class="muted">보도로 확인된 일부 운용사입니다.</p>'
    else:
        out += f'<p><strong>{h(result["stage"])}</strong></p>'
    if result.get('note'):
        out += f'<p class="muted">{h(result["note"])}</p>'
    out += '<p class="reported-sources">출처 ' + ' · '.join(
        f'<a href="{h(s["url"])}" target="_blank" rel="noopener">{h(s["publisher"])} {h(s["date"].replace("-", "."))} 「{h(s["title"])}」 ↗</a>'
        for s in result['sources']) + '</p></div>'
    return out


def standardized_schedule(stages, as_of=None, *, selection_recorded=False):
    as_of = as_of or _today()
    reached = [_flow_step(e) for e in stages
               if e.get('status') != 'planned' and str(e.get('date') or '')[:10] <= as_of]
    current = max((step for step in reached if step is not None), default=None)
    flow = ''
    for index, name in enumerate(('공고', '접수', '심사', '선정')):
        state = ' class="current" aria-current="step"' if index == current else (' class="done"' if current is not None and index < current else '')
        flow += f'<li{state}>{name}</li>'
    body = f'<section id="schedule"><h2>진행 일정</h2><ol class="stage-flow" aria-label="출자사업 단계">{flow}</ol><ol class="event-list">'
    for e in stages:
        stamp = e.get('date_label') or str(e.get('date') or '').replace('T', ' ').replace('+09:00', '')
        if e['precision'] == 'datetime':
            stamp = stamp[:16]
        badge = (('<span class="planned-label">공고상 예정</span>' if selection_recorded else planned_badge(e, as_of))
                 if e['status']=='planned' else ('<span class="planned-label">공고상 마감</span>' if e['status']=='announced_deadline' else ''))
        note = e.get('detail') or (e['original_label'] if e['stage'] in ('screening', 'due_diligence') else '')
        if note == e['label']:
            note = ''
        evidence = link(e['source_url'], '원문') if e.get('show_source') else ''
        body += f'<li class="event"><time>{h(stamp)}</time><div><strong>{h(e["label"])}</strong> {badge}<small>{h(note)} {evidence}</small></div></li>'
    return body + '</ol></section>'

def render_detail_body(p, as_of=None):
    as_of = as_of or _today()
    selection_recorded = bool(p.get('selected_gps')) or any(e['type'] in ('최종 선정', '선정 결과') for e in p['events'])
    original = next((e['url'] for e in p['events'] if e['type']=='모집 공고'), p['events'][0]['url'])
    original_title = f'<p class="source-title">공고명 {h(p["title"])}</p>' if clean_title(p['title']) != str(p['title']).strip() else ''
    body = f'<a class="back" href="index.html">← 출자사업</a><header class="detail-header"><a class="institution" href="institution-{h(p["institution_id"])}.html">{h(p["institution_name"])}</a><h1>{h(p.get("public_title") or clean_title(p["title"]))}</h1>{original_title}<div class="detail-meta"><span class="badge">{h(p.get("display_status") or display_status(p["status"]))}</span>{"<span class=\"badge\">PE·VC 공동 모집</span>" if p.get("mixed_scope") else ""}{link(original,"출자 공고 원문")}</div>{deadline_calendar_block(p, as_of)}</header>'
    if p.get('schedule_stages'):
        body += standardized_schedule(p['schedule_stages'], as_of, selection_recorded=selection_recorded)
    else:
        body += '<section id="schedule"><h2>진행 일정</h2><ol class="event-list">'
        events = [(e,False) for e in sorted(p['events'],key=lambda e:e['date'])]
        events += [(e,True) for e in p.get('planned_events', [])]
        for event, planned in events:
            stamp = event.get('date_label') or event.get('date') or '일정 미정'
            title = event['title']
            label = event.get('type') or title
            if planned and label.endswith(' 예정'):
                label = label[:-3]
            note = '' if label == title else f'<small>{h(title)}</small>'
            badge = (' <span class="planned-label">공고상 예정</span>' if selection_recorded else ' ' + planned_badge(event, as_of)) if planned else ''
            body += f'<li class="event {"planned" if planned else "recorded"}"><time>{h(stamp)}</time><div><strong>{h(label)}</strong>{badge}{note}</div>{link(event.get("url"))}</li>'
        body += '</ol></section>'
    if p.get('linkage_note'):
        body += f'<p class="notice">{h(p["linkage_note"])}</p>'
    body += '<section id="offering"><h2>모집 개요</h2><div class="facts">'
    body += f'<div><small>투자 분야</small><strong>{h(p["asset_scope"])}</strong></div>'
    if p.get('commitment_label'):
        body += f'<div><small>출자 예정액</small><strong>{h(p["commitment_label"])}</strong></div>'
    if p.get('fund_target_label'):
        body += f'<div><small>결성 목표</small><strong>{h(p["fund_target_label"])}</strong></div>'
    if p.get('manager_count_label'):
        body += f'<div><small>선정 예정</small><strong>{h(p["manager_count_label"])}</strong></div>'
    if not p.get('segments') and p.get('per_fund_amount_krw'):
        amount = f'{p["per_fund_amount_krw"]/100000000:,.0f}억원'
        if p.get('per_fund_qualifier'):
            amount += ' ' + p['per_fund_qualifier']
        body += f'<div><small>펀드당 출자액</small><strong>{h(amount)}</strong></div>'
    body += '</div>'
    if p.get('commitment_detail'):
        body += f'<p class="muted contribution-detail">{h(p["commitment_detail"])}<br>{h(p.get("contribution_note"))}</p>'
    objective = p.get('primary_investment')
    items = objective.get('items', [objective.get('text')]) if objective else []
    if objective and all(re.search(r'미확인\s*$', str(item or '')) for item in items):
        objective = None  # A placeholder is not an investment purpose.
    if objective:
        paragraphs = "".join(f"<p>{h(item)}</p>" for item in objective.get("items", [objective["text"]]))
        body += f'<div class="investment-purpose"><strong>주목적</strong>{paragraphs}</div>'
    segments = p.get('segments', [])
    if segments:
        per_fund = any(s.get('per_fund_max_krw') or s.get('per_fund_amount_krw') for s in segments)
        extra = '<th>펀드당 출자액</th>' if per_fund else ''
        body += f'<div class="scroll"><table class="league-table"><thead><tr><th>리그</th><th>출자 예정액</th><th>선정 예정</th>{extra}</tr></thead><tbody>'
        for segment in segments:
            amount = f'{segment["amount_krw"]/100000000:,.0f}억원' if segment.get('amount_krw') is not None else '—'
            per_amount = segment.get('per_fund_max_krw') or segment.get('per_fund_amount_krw')
            minimum = segment.get('per_fund_min_krw')
            per_label = (f'{minimum/100000000:,.0f}~{per_amount/100000000:,.0f}억원' if minimum and per_amount else f'{per_amount/100000000:,.0f}억원' if per_amount else '')
            extra = (f'<td data-label="펀드당 출자액">{per_label}' + (' 이내' if segment.get('per_fund_max_krw') and not minimum else '') + '</td>') if per_fund and per_amount else ('<td data-label="펀드당 출자액">—</td>' if per_fund else '')
            body += f'<tr><td class="league-name">{h(segment["name"])}</td><td data-label="출자 예정액">{amount}</td><td data-label="선정 예정">{h(segment.get("manager_count") or "—")}</td>{extra}</tr>'
        body += '</tbody></table></div>'
    body += '</section>'
    has_names = any(p.get(k) for k in ('applicants_gps', 'shortlisted_gps', 'preferred_gps', 'selected_gps'))
    result_events = [e for e in p['events'] if e['type'] in ('최종 선정', '선정 결과', '우선협상대상자')]
    awaiting_result = p['status'].startswith('접수 마감') or bool(result_events)
    if p.get('basic_publication') and not has_names and not awaiting_result:
        return body + PLAN_SCRIPT
    heading = ('단계별 GP' if p.get('schedule_stages') or p.get('preferred_gps') else '선정 GP') if has_names else '선정 결과'
    body += '<section id="selection"><h2>' + heading + '</h2>'
    applicants = p.get('applicants_gps', [])
    if applicants:
        body += f'<details class="applicant-list"><summary>접수 {len(applicants)}개 팀</summary><ul>' + ''.join(f'<li>{h(name)}</li>' for name in applicants) + '</ul>' + link(p.get('manager_list_sources', {}).get('applicants_gps'), '접수 원문') + '</details>'
    if p.get('preferred_gps'):
        body += '<h3>우선협상대상자</h3><div class="scroll"><table><thead><tr><th>운용사</th><th>리그</th></tr></thead><tbody>'
        for name in p['preferred_gps']:
            body += f'<tr><td>{h(name)}{profile_link(p, name)}</td><td>{h(p.get("gp_tracks", {}).get(name) or "—")}</td></tr>'
        body += '</tbody></table></div><p>' + link(p.get('manager_list_sources', {}).get('preferred_gps'), '우선협상 결과 원문') + '</p>'
    if p.get('shortlisted_gps'):
        selected = {gp['name']: gp for gp in p['selected_gps']}
        shortlist_url = next((e['url'] for e in p['events'] if e['type']=='서류심사 결과'), '')
        result_pending = p['status'] == '선정 결과 발표'
        result_heading = '선정 결과' if result_pending else '최종 선정'
        body += f'<div class="scroll"><table class="gp-stage-table"><thead><tr><th>운용사</th><th>1차 통과</th><th>{result_heading}</th></tr></thead><tbody>'
        for name in dict.fromkeys(p['shortlisted_gps'] + list(selected)):
            gp = selected.get(name)
            name_html = f'<a href="selected-gp-{h(gp["page_key"])}.html">{h(name)}</a>' if gp else h(name)
            name_html += profile_link(p, name)
            if p.get('gp_tracks', {}).get(name):
                name_html += f'<small>{h(p["gp_tracks"][name])}</small>'
            if gp and gp.get('commitment_amount_krw'):
                name_html += f'<small>출자 예정 {gp["commitment_amount_krw"]/100000000:,.0f}억원</small>'
            first = link(shortlist_url, '통과') if name in p['shortlisted_gps'] else '—'
            final = link(gp['source_url'], '발표' if result_pending else '선정') if gp else '—'
            body += f'<tr><td>{name_html}</td><td>{first}</td><td>{final}</td></tr>'
        body += '</tbody></table></div>'
        if not selected:
            body += f'<p class="muted">서류심사 통과 {len(set(p["shortlisted_gps"]))}개 팀입니다. 최종 선정 명단은 아직 확인되지 않았습니다.</p>'
    elif p['selected_gps']:
        body += '<div class="scroll"><table><thead><tr><th>운용사</th><th>선정 결과</th></tr></thead><tbody>'
        for gp in p['selected_gps']:
            amount = f'<small>출자 예정 {gp["commitment_amount_krw"]/100000000:,.0f}억원</small>' if gp.get('commitment_amount_krw') else ''
            body += f'<tr><td><a href="selected-gp-{h(gp["page_key"])}.html">{h(gp["name"])}</a>{profile_link(p, gp["name"])}{amount}</td><td>{link(gp["source_url"],"선정 결과")}</td></tr>'
        body += '</tbody></table></div>'
    else:
        note = ('최종 선정 명단은 아직 확인되지 않았습니다.' if p.get('preferred_gps') else p.get('gp_stage_note'))
        planned_selection = [e for e in p.get('schedule_stages', []) if e.get('stage') == 'selection' and e.get('status') == 'planned']
        until = max((u for u in (planned_until(e) for e in planned_selection) if u), default=None)
        attrs = ''
        if note and '개별 통보' in note and until:
            past_note = '공고에는 개별 통보로 안내되어 있습니다. 선정 명단은 아직 확인되지 않았습니다.'
            attrs = f' data-lp-note-until="{h(until)}" data-lp-past-note="{h(past_note)}"'
            if until < as_of:
                note = past_note
        if p.get('reported_result'):
            body += reported_block(p['reported_result'], p)
        else:
            announced = any(e['type'] in ('최종 선정', '선정 결과') for e in p['events'])
            fallback = ('선정 결과가 발표됐습니다. 운용사 명단은 결과 원문에서 확인할 수 있습니다.' if announced
                        else '선정 결과는 아직 확인되지 않았습니다.')
            body += f'<p class="muted"{attrs}>{h(note)}</p>' if note else f'<p class="muted">{fallback}</p>'
        if result_events:
            result = max(result_events, key=lambda event: event['date'])
            label = '우선협상 결과 원문' if result['type'] == '우선협상대상자' else '선정 결과 원문'
            if not p.get('preferred_gps') or result['url'] != p.get('manager_list_sources', {}).get('preferred_gps'):
                body += f'<p>{link(result["url"], label)}</p>'
    # Only an official result table that labels every selected manager 'PE' (e.g. KDB).
    pe_only = bool(p.get('selected_gps')) and all((p.get('gp_tracks') or {}).get(g['name']) == 'PE' for g in p['selected_gps'])
    if p.get('mixed_scope') and pe_only:
        body += '<p class="muted">PE·VC 공동 모집 사업 중 PE 부문 선정 운용사입니다.</p>'
    elif p.get('mixed_scope') and (p.get('selected_gps') or p.get('preferred_gps') or p.get('shortlisted_gps')):
        body += '<p class="muted">PE·VC 공동 모집 사업이라 선정 운용사에 벤처캐피탈이 포함될 수 있습니다.</p>'
    body += '</section>'
    return body + PLAN_SCRIPT
