"""One schedule-first detail template for every LP program."""
from html import escape

def h(value):
    return escape(str(value or ''), quote=True)

def link(url, label='원문'):
    if not url or not url.startswith('https://'):
        return ''
    return f'<a href="{h(url)}" target="_blank" rel="noopener">{h(label)} ↗</a>'

def standardized_schedule(stages):
    body = '<section id="schedule"><h2>진행 일정</h2><ol class="stage-flow" aria-label="출자사업 단계"><li>공고</li><li>접수</li><li>심사</li><li>선정</li></ol><ol class="event-list">'
    for e in stages:
        stamp = e.get('date_label') or str(e.get('date') or '').replace('T', ' ').replace('+09:00', '')
        if e['precision'] == 'datetime':
            stamp = stamp[:16]
        badge = '예정' if e['status']=='planned' else ('공고상 마감' if e['status']=='announced_deadline' else '')
        note = e['original_label'] if e['stage'] in ('screening', 'due_diligence') else ''
        body += f'<li class="event"><time>{h(stamp)}</time><div><strong>{h(e["label"])}</strong> <span class="planned-label">{h(badge)}</span><small>{h(note)}</small></div></li>'
    return body + '</ol></section>'

def render_detail_body(p):
    original = next((e['url'] for e in p['events'] if e['type']=='모집 공고'), p['events'][0]['url'])
    body = f'<a class="back" href="index.html">← 출자사업</a><header class="detail-header"><a class="institution" href="institution-{h(p["institution_id"])}.html">{h(p["institution_name"])}</a><h1>{h(p["title"])}</h1><div class="detail-meta"><span class="badge">{h(p["status"])}</span>{link(original,"출자 공고 원문")}</div></header>'
    if p.get('schedule_stages'):
        body += standardized_schedule(p['schedule_stages'])
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
            body += f'<li class="event {"planned" if planned else "recorded"}"><time>{h(stamp)}</time><div><strong>{h(label)}</strong>{" <span class=planned-label>예정</span>" if planned else ""}{note}</div>{link(event.get("url"))}</li>'
        body += '</ol></section>'
    if p.get('linkage_note'):
        body += f'<p class="notice">{h(p["linkage_note"])}</p>'
    body += '<section id="offering"><h2>모집 개요</h2><div class="facts">'
    body += f'<div><small>투자 분야</small><strong>{h(p["asset_scope"])}</strong></div>'
    if p.get('commitment_label'):
        body += f'<div><small>출자 예정액</small><strong>{h(p["commitment_label"])}</strong></div>'
    if p.get('manager_count_label'):
        body += f'<div><small>선정 예정</small><strong>{h(p["manager_count_label"])}</strong></div>'
    body += '</div>'
    objective = p.get('primary_investment')
    if objective:
        paragraphs = "".join(f"<p>{h(item)}</p>" for item in objective.get("items", [objective["text"]]))
        body += f'<div class="investment-purpose"><strong>주목적</strong>{paragraphs}</div>'
    segments = p.get('segments', [])
    if segments:
        per_fund = any(s.get('per_fund_max_krw') for s in segments)
        extra = '<th>펀드당 출자 한도</th>' if per_fund else ''
        body += f'<div class="scroll"><table><thead><tr><th>리그</th><th>출자 예정액</th><th>선정 예정</th>{extra}</tr></thead><tbody>'
        for segment in segments:
            amount = f'{segment["amount_krw"]/100000000:,.0f}억원' if segment.get('amount_krw') is not None else '미확인'
            extra = f'<td>{segment["per_fund_max_krw"]/100000000:,.0f}억원 이내</td>' if per_fund and segment.get('per_fund_max_krw') else ('<td>미확인</td>' if per_fund else '')
            body += f'<tr><td>{h(segment["name"])}</td><td>{amount}</td><td>{h(segment.get("manager_count") or "미확인")}</td>{extra}</tr>'
        body += '</tbody></table></div>'
    body += '</section><section id="selection"><h2>' + ('단계별 GP' if p.get('schedule_stages') else '선정 GP') + '</h2>'
    if p['selected_gps']:
        body += '<div class="scroll"><table><thead><tr><th>운용사</th><th>선정 결과</th></tr></thead><tbody>'
        for gp in p['selected_gps']:
            body += f'<tr><td><a href="selected-gp-{h(gp["page_key"])}.html">{h(gp["name"])}</a></td><td>{link(gp["source_url"],"선정 결과")}</td></tr>'
        body += '</tbody></table></div>'
    else:
        body += f'<p class="muted">{h(p.get("gp_stage_note"))}</p>' if p.get('gp_stage_note') else '<p class="muted">선정 결과 미확인</p>'
    body += '</section>'
    return body
