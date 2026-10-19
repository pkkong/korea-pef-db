"""Evidence-backed LP program pages, shared by preview and future public builds."""
from __future__ import annotations
import argparse
import json
import os
import re
from pathlib import Path
from html import escape
from collections import defaultdict
from datetime import date

ROOT = Path(__file__).resolve().parents[3]

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
            if gp['source_url'] not in {e['url'] for e in p['events'] if e['type'] == '최종 선정'}:
                raise ValueError('Selected GP must link to this program final result event')
        for e in p['events']:
            date.fromisoformat(e['date'])
            if e['date'] > data['as_of']:
                raise ValueError('Future event cannot be a completed timeline event')
    return data

def h(value):
    return escape(str(value or ''), quote=True)

def deadline_label(value):
    return str(value).replace('T', ' ').replace('+09:00', '') if value else '원문 확인 필요'

def source(url, label='공식 원문'):
    if not url.startswith('https://'):
        return h(label)
    return f'<a href="{h(url)}" target="_blank" rel="noopener">{h(label)} ↗</a>'

CSS = '''*{box-sizing:border-box}body{margin:0;background:#fff;color:#171717;font:15px/1.65 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif}main{max-width:1000px;margin:auto;padding:32px 24px 110px}a{color:inherit;text-underline-offset:4px}header{border-bottom:1px solid #e8e8e8;padding-bottom:22px;margin-bottom:24px}h1{word-break:keep-all;overflow-wrap:break-word;font-size:28px;line-height:1.35;letter-spacing:-1px;margin:12px 0}h2{font-size:19px;margin:32px 0 12px}p{margin:8px 0}.muted,small{color:#737373}small{display:block}.eyebrow{font-size:12px;letter-spacing:1px;color:#666}.controls{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0}input,select{font:inherit;border:1px solid #ddd;border-radius:6px;padding:10px;background:white}input{flex:1;min-width:180px}.program{padding:22px 0;border-bottom:1px solid #e8e8e8}.program h2{font-size:18px;margin:8px 0}.program a{text-decoration:none}.program a:hover{text-decoration:underline}.badge{font-size:12px;background:#f3f5f6;border-radius:4px;padding:4px 8px;color:#414b54}.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;padding:20px 0;border-block:1px solid #eee}.facts strong{display:block}.timeline{padding-left:20px}.timeline li{padding:0 0 22px 12px}.timeline time{font-size:13px;color:#737373}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:15px 10px;border-bottom:1px solid #eee;vertical-align:top}th{font-size:12px;color:#737373}.scroll{overflow:auto}nav{position:fixed;bottom:0;left:0;right:0;background:#fffffff5;border-top:1px solid #eee;display:flex;justify-content:center;gap:80px;padding:16px;backdrop-filter:blur(10px)}nav a{text-decoration:none;color:#777}nav .active{color:#171717;font-weight:700}.notice{font-size:13px;color:#737373;background:#f8f8f8;padding:14px 16px;margin:24px 0}[hidden]{display:none!important}@media(max-width:600px){main{padding:22px 18px 90px}h1{font-size:23px}.facts{grid-template-columns:1fr 1fr}nav{gap:65px}td{min-width:105px}}'''

CSS += """.investment-purpose{padding:16px 0;border-bottom:1px solid #e3e8ee}.investment-purpose>strong{font-size:14px;color:#66717e}.investment-purpose p{margin:6px 0;font-size:16px}.investment-purpose>a{font-size:13px;color:#456181}.back{font-size:14px;color:#6d7783;text-decoration:none}.detail-header{margin-top:22px;padding-bottom:22px}.institution{font-size:15px;color:#456181}.detail-meta{display:flex;align-items:center;justify-content:space-between;gap:16px}.detail-meta>a{font-size:14px;color:#365d87}.detail-header h1{margin:12px 0 20px}.event-list{list-style:none;padding:0;margin:0;border-top:2px solid #344c68}.event{display:grid;grid-template-columns:160px minmax(0,1fr) 55px;gap:18px;padding:14px 0;border-bottom:1px solid #e3e8ee;align-items:start}.event time{font-size:14px;color:#53677f;font-variant-numeric:tabular-nums}.event strong{font-size:16px;font-weight:600}.event>a{font-size:13px;color:#4b6786}.event small{font-size:13px;margin-top:4px}.planned{background:#f8f9fb}.planned-label{font-size:12px;color:#687d94;border:1px solid #dce3ec;border-radius:3px;padding:2px 5px;margin-left:6px}#offering .facts{grid-template-columns:1fr 2fr;border-top:1px solid #e3e8ee}section{margin-bottom:30px}#schedule h2{margin-top:0}#selection{margin-bottom:0}@media(max-width:600px){.event{grid-template-columns:minmax(0,1fr) 48px;gap:5px 10px;padding:14px 0}.event time{grid-column:1;grid-row:1}.event>div{grid-column:1/-1;grid-row:2}.event>a{grid-column:2;grid-row:1}.event time{font-size:13px}.event strong{font-size:15px}.detail-meta{align-items:start}.facts strong{font-size:15px}}"""

CSS += """.stage-flow{display:flex;list-style:none;padding:12px 0;gap:20px;color:#53677f;font-size:14px}.stage-flow li+li:before{content:"→";margin-right:20px;color:#aaa}.planned-label:empty{display:none}#offering .facts:has(>div:nth-child(3)){grid-template-columns:1fr 1fr 1fr}"""

def shell(title, body, as_of):
    sample_css = (Path(__file__).with_name('lp_sample.css')).read_text()
    newsletter_url = h(os.environ.get('NEWSLETTER_PUBLIC_URL', 'https://kpef-newsletter.vercel.app').rstrip('/'))
    gp_url = h(os.environ.get('GP_PUBLIC_URL', 'https://kpef-gp.vercel.app').rstrip('/'))
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{h(title)} · LP</title><link rel="stylesheet" href="/assets/service.css"><style>{CSS}\n{sample_css}</style></head><body class="lp-sample"><main><div class="sample-brand"><a href="{newsletter_url}/">Korea PEF</a><span>LP</span></div>{body}</main><nav class="bottom-nav" aria-label="하단 메뉴"><a href="{newsletter_url}/"><span aria-hidden="true" class="nav-dot nav-icon-brief"></span><strong>브리프</strong></a><a class="active" aria-current="page" href="index.html"><span aria-hidden="true" class="nav-dot nav-icon-lp"></span><strong>LP</strong></a><a href="{gp_url}/"><span aria-hidden="true" class="nav-dot nav-icon-gp"></span><strong>GP</strong></a></nav></body></html>'

def build(data, out):
    validate(data)
    out.mkdir(parents=True, exist_ok=True)
    as_of = data['as_of']
    programs = sorted(data['programs'], key=lambda p: max(e['date'] for e in p['events']), reverse=True)
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
        status = '접수 마감' if p['status'].startswith('접수 마감') else p['status']
        latest = max(p['events'], key=lambda e:e['date'])
        if p['selected_gps']:
            timing = f"{latest['date'][5:].replace('-', '.')} 선정 · {len(p['selected_gps'])}개사"
        elif p.get('deadline'):
            timing = f"{p['deadline'][5:10].replace('-', '.')} 마감"
        else:
            timing = f"{latest['date'][5:].replace('-', '.')} 공고"
        amount = f"{p['commitment_amount_krw']/100000000:,.0f}억원" if p.get('commitment_amount_krw') else ''
        amount = p.get('list_commitment_label', amount)
        if p['id'] == 'pck-pension-2026-h2-pe':
            amount = ''
        return f'<article class="program" data-status="{h(p["status"])}" data-institution="{h(p["institution_id"])}" data-search="{h(p["title"])}"><a class="program-link" href="program-{h(p["id"])}.html"><div class="program-top"><span class="program-institution">{h(p["institution_name"])}</span><span class="program-status">{h(status)}</span></div><h2 class="program-title">{h(p.get("display_title",p["title"]))}</h2><div class="program-bottom"><span>{h(amount)}</span><span>{h(timing)}</span></div></a></article>'
    options = ''.join(f'<option value="{h(k)}">{h(v[0]["institution_name"])}</option>' for k,v in institutions.items())
    statuses = ''.join(f'<option>{h(s)}</option>' for s in sorted({p['status'] for p in programs}))
    body = f'<header class="list-header"><h1>출자사업</h1><span id="count">{len(programs)}개 사업</span></header><div class="controls"><input aria-label="사업 검색" placeholder="기관·사업명 검색"><select aria-label="진행 상태"><option value="">모든 상태</option>{statuses}</select><select aria-label="출자기관"><option value="">모든 기관</option>{options}</select></div>'+''.join(row(p) for p in programs)+'<p id="empty" hidden>조건에 맞는 사업이 없습니다.</p>'
    body += '''<script>const q=document.querySelector('input'),s=document.querySelectorAll('select');function filter(){let n=0;document.querySelectorAll('.program').forEach(r=>{r.hidden=!((r.textContent+" "+r.dataset.search).toLowerCase().includes(q.value.toLowerCase())&&(!s[0].value||r.dataset.status===s[0].value)&&(!s[1].value||r.dataset.institution===s[1].value));if(!r.hidden)n++});document.querySelector('#count').textContent=n+'개 사업';document.querySelector('#empty').hidden=n!==0}q.addEventListener('input',filter);s.forEach(e=>e.addEventListener('change',filter));</script>'''
    (out/'index.html').write_text(shell('출자사업',body,as_of))
    try:
        from .lp_program_detail import render_detail_body
    except ImportError:
        from lp_program_detail import render_detail_body
    for p in programs:
        (out/f'program-{p["id"]}.html').write_text(shell(p['title'], render_detail_body(p), as_of))
    for key,group in institutions.items():
        title=group[0]['institution_name']
        body=f'<a href="index.html">← 출자사업</a><header><div class="eyebrow">출자기관</div><h1>{h(title)}</h1><p>연결된 출자사업 {len(group)}건</p></header>'+''.join(row(p) for p in group)
        (out/f'institution-{key}.html').write_text(shell(title,body,as_of))
    for key,group in gp_programs.items():
        gp=gp_index[key]
        body=f'<a href="index.html">← 출자사업</a><header><div class="eyebrow">GP / 출자사업 선정 이력</div><h1>{h(gp["name"])}</h1><p>선정 이력 {len(group)}건</p></header><h2>선정된 사업</h2>'
        for p,g in group: body+=row(p)+f'<p>{source(g["source_url"],"공식 선정 근거")}</p>'
        body+='<p class="muted">수록된 출자사업의 선정 이력입니다.</p>'
        (out/f'selected-gp-{key}.html').write_text(shell(gp['name'],body,as_of))
    return {'programs':len(programs),'institutions':len(institutions),'gps':len(gp_programs),'as_of':as_of}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(build(json.loads(args.input.read_text()),args.out),ensure_ascii=False))
