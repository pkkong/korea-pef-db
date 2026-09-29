"""Read-only review of official public notices; no accounts or approval controls."""
from difflib import unified_diff
from html import escape
from lp_program_service import shell


def render_review(data,report,previous):
    old={str(n['source_id']):n for n in previous.get('tracked_notices',[])}
    programs=data['programs']
    body='<header><h1>공고 검토</h1><p class="muted">공고와 정리된 사업 정보를 확인하는 화면입니다. 수정·반영할 내용은 대화에서 알려주세요.</p></header>'
    notices=sorted(report['notices'],key=lambda n:n['date'],reverse=True)
    for n in notices:
        p=next((p for p in programs if any(e['url']==n['url'] for e in p['events'])),None)
        label='사업 연결됨' if p else '정리 대기'
        before=old.get(str(n['source_id']))
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
            body+='<p class="muted">아직 사업 정보로 정리하지 않은 공고입니다.</p>'
        if changed:
            diff='\n'.join(unified_diff(before.get('body','').splitlines(),n['body'].splitlines(),fromfile='이전 원문',tofile='현재 원문',lineterm=''))
            if diff:body+='<h2>바뀐 내용</h2><pre>'+escape(diff)+'</pre>'
            if before.get('attachment_hashes')!=n.get('attachment_hashes'):
                body+='<p>첨부파일이 변경되었습니다. 원문에서 확인해 주세요.</p>'
        body+='<h2>공고 본문</h2><pre>'+escape(n['body'])+'</pre></div></details>'
    style='<style>.review-notice{border-bottom:1px solid #e5e5e5}.review-notice summary{cursor:pointer;padding:18px 0;list-style:none}.review-notice summary strong{display:block;font-size:15px;line-height:1.5;margin-top:5px;overflow-wrap:anywhere}.review-content{padding-bottom:20px}.review-content h2{font-size:15px;margin:20px 0 10px}.review-content pre{font:13px/1.7 inherit;white-space:pre-wrap;overflow-wrap:anywhere;background:#fafafa;padding:14px}.review-content th{width:24%;min-width:0}.review-content td{min-width:0;overflow-wrap:anywhere}.review-content table{table-layout:fixed}</style>'
    html=shell('공고 검토',style+body,data['as_of'])
    return html.replace('href="index.html"','href="/samples/lp/index.html"')
