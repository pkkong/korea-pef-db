"""Read-only review of official public notices; no accounts or approval controls."""
from difflib import unified_diff
from html import escape
from lp_program_service import shell
from kgrowth_program_review import link_suggestions, notice_classification


def render_review(data,report,previous):
    old={n['url']:n for n in previous.get('tracked_notices',[])+previous.get('priority_notices',[])}
    programs=data['programs']
    body='<header><h1>공고 검토</h1><p class="muted">공고와 정리된 사업 정보를 확인하는 화면입니다. 수정·반영할 내용은 대화에서 알려주세요.</p></header>'
    suggestions=data.get('link_suggestions', link_suggestions(report['notices']))
    suggested_sources={item['url'] for item in suggestions}
    discovery=data.get('discovery_candidates', [])
    discovery_sources={item['url'] for item in discovery}
    institutions={'ktcu':'한국교직원공제회','koreapost':'우정사업본부','kexim':'한국수출입은행'}
    if discovery:
        labels={'pe_eligible':'PE 신청 가능','vc_only':'VC · PE 목록 제외',
                'pe_related_mandate':'PE·PD 투자관리 위탁','mixed_legal_forms':'PE·VC 모두 가능',
                'unknown':'펀드 형태 확인 필요'}
        groups={}
        for item in discovery:
            groups.setdefault(item.get('program_key') or item['url'],[]).append(item)
        body+='<section class="review-queue"><h2>새 출자공고 후보</h2><p class="muted">공식 공고의 펀드 형태와 사업명을 기준으로 자동 분류했습니다.</p>'
        for members in sorted(groups.values(),key=lambda group:max(item['date'] for item in group),reverse=True):
            members.sort(key=lambda item:(item['date'],item['source_id']))
            first=next((item for item in members if item.get('stage')=='모집 공고'),members[0])
            name=institutions.get(first['institution_id'],first['institution_id'])
            scope=labels.get(first.get('scope'), '펀드 형태 확인 필요')
            body+=f'<div class="review-program-group"><small>{escape(name)} · {escape(scope)}</small><h3>{escape(first["title"])}</h3>'
            if not any(item.get('recruitment_url') for item in members):
                body+='<p class="muted">모집 원공고 확인 필요</p>'
            body+='<ul>'
            for item in members:
                stage=item.get('stage') or '공고'
                body+=f'<li><small>{escape(item["date"])} · {escape(stage)}</small><a target="_blank" rel="noopener" href="{escape(item["url"],quote=True)}">{escape(item["title"])} ↗</a></li>'
            body+='</ul></div>'
        body+='</section>'
    if suggestions:
        published={p['id'] for p in programs}
        body+='<section class="review-queue"><h2>새 단계 연결 후보</h2><ul>'
        for item in sorted(suggestions,key=lambda s:s['date'],reverse=True):
            targets=' · '.join(
                f'<a href="/samples/lp/program-{escape(p["id"],quote=True)}.html">{escape(p["title"])}</a>'
                for p in item['programs'] if p['id'] in published)
            if len(item['programs'])>1:
                targets+=' · 차수 확인 필요'
            body+=f'<li><small>{escape(item["date"])} · {escape(item["stage"])}</small><strong>{escape(item["title"])}</strong><span>{targets}</span> <a target="_blank" rel="noopener" href="{escape(item["url"],quote=True)}">공고 원문 ↗</a></li>'
        body+='</ul></section>'
    related_urls={e['url'] for p in programs for e in p['events']} | suggested_sources | discovery_sources
    priority_notices=[n for n in data.get('priority_notices',[]) if n['url'] in related_urls]
    notices=sorted(report['notices']+priority_notices,key=lambda n:n['date'],reverse=True)
    for n in notices:
        p=next((p for p in programs if any(e['url']==n['url'] for e in p['events'])),None)
        classification=notice_classification(n) if n.get('institution_id','kgrowth')=='kgrowth' else None
        label=('사업 연결됨' if p else '기존 사업 연결 후보' if n['url'] in suggested_sources
               else '새 사업 후보' if n['url'] in discovery_sources
               else classification['label'] if classification else '정리 대기')
        before=old.get(n['url'])
        changed=before and any(before.get(k)!=n.get(k) for k in ('body','title','date','attachment_hashes'))
        if changed:label='원문 변경'
        body+=f'<details class="review-notice"><summary><small>{escape(n["date"])} · {label}</small><strong>{escape(n["title"])}</strong></summary><div class="review-content">'
        body+=f'<p><a target="_blank" rel="noopener" href="{escape(n["url"],quote=True)}">공고 원문 ↗</a></p>'
        if p:
            body+=f'<h2>연결된 사업</h2><p><a href="/samples/lp/program-{escape(p["id"],quote=True)}.html">{escape(p["title"])} ↗</a></p><table><tbody>'
            purpose=p.get('primary_investment') or {}
            fields=[('출자규모',p.get('commitment_label') or '미확인'),('선정 예정',p.get('manager_count_label') or '공고 원문 참고'),('접수 마감',p.get('deadline') or '미확인'),('주목적',' / '.join(purpose.get('items') or [purpose.get('text','미확인')])),('선정 GP',' · '.join(g['name'] for g in p['selected_gps']) or '미확인')]
            for name,value in fields:body+=f'<tr><th>{name}</th><td>{escape(value)}</td></tr>'
            body+='</tbody></table>'
        else:
            note=classification['reason'] if classification else '아직 사업 정보로 정리하지 않은 공고입니다.'
            body+='<p class="muted">'+escape(note)+'</p>'
        if changed:
            diff='\n'.join(unified_diff(before.get('body','').splitlines(),n['body'].splitlines(),fromfile='이전 원문',tofile='현재 원문',lineterm=''))
            if diff:body+='<h2>바뀐 내용</h2><pre>'+escape(diff)+'</pre>'
            if before.get('attachment_hashes')!=n.get('attachment_hashes'):
                body+='<p>첨부파일이 변경되었습니다. 원문에서 확인해 주세요.</p>'
        body+='<h2>공고 본문</h2><pre>'+escape(n['body'])+'</pre></div></details>'
    style='<style>.review-queue ul{list-style:none;padding:0}.review-program-group{border-bottom:1px solid #e5e5e5;padding:16px 0}.review-program-group h3{font-size:16px;line-height:1.5;margin:6px 0}.review-program-group li{padding:7px 0;overflow-wrap:anywhere}.review-program-group li>*{display:block;margin:2px 0}.review-queue small{color:#64748b}.review-notice{border-bottom:1px solid #e5e5e5}.review-notice summary{cursor:pointer;padding:18px 0;list-style:none}.review-notice summary strong{display:block;font-size:15px;line-height:1.5;margin-top:5px;overflow-wrap:anywhere}.review-content{padding-bottom:20px}.review-content h2{font-size:15px;margin:20px 0 10px}.review-content pre{font:13px/1.7 inherit;white-space:pre-wrap;overflow-wrap:anywhere;background:#fafafa;padding:14px}.review-content th{width:24%;min-width:0}.review-content td{min-width:0;overflow-wrap:anywhere}.review-content table{table-layout:fixed}</style>'
    html=shell('공고 검토',style+body,data['as_of'])
    return html.replace('href="index.html"','href="/samples/lp/index.html"')
