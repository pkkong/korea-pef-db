"""Render the separate LP directory review input; never publishes or mutates a DB."""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def render(input_path: Path, out: Path, include_all: bool = False) -> dict:
    data = json.loads(input_path.read_text())
    rows = data['entities']
    routes = {r['id']: r for r in data['routes']}
    ids = [r['id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate entity IDs')
    if any(r['legal_route'] not in routes for r in rows):
        raise ValueError('Unknown legal route')
    total = len(rows)
    if not include_all:
        rows = [r for r in rows if r.get('notice_collection', {}).get('priority') == '우선 조사']
    rows = sorted(rows, key=lambda r: (r.get('institution_category', ''), r['name']))
    e = lambda s: html.escape(str(s or '—'), quote=True)
    def link(url, label):
        return f'<a href="{e(url)}" target="_blank" rel="noopener">{e(label)}</a>' if url and url.startswith(('https://', 'http://')) else e(label)
    dates = f"명부 조회 {data['as_of']} · 통합 검토 {data.get('reviewed_at', data['as_of'])}"
    body, md = [], [f"# {'전체 참고 명단' if include_all else 'LP 공고 관리 대상'}\n\n{dates}\n", '법적 후보 전체와 공고 관리 대상을 구분합니다.', '\n']
    for row in rows:
        refs = [link(row.get('legal_source_url'), '법령')]
        for evidence in row.get('activity_evidence', []):
            refs.append(link(evidence['url'], evidence.get('type', '활동 근거')))
        for source in row.get('directory_evidence', []):
            refs.append(link(source['url'], source['source_name']))
        for source in row.get('notice_discovery_evidence', []):
            refs.append(link(source['url'], source.get('title', '공고 발견 근거')))
            if source.get('official_url'):
                refs.append(link(source['official_url'], '기관 원문'))
        notes = ' '.join(row.get('notes', []))
        kind = row.get('institution_category') or row.get('financial_subtype') or row['entity_kind']
        collection = row.get('notice_collection', {})
        info = f"<details><summary>출처·확인할 내용</summary><p>{' · '.join(refs)}</p><p>{e(row['legal_reference'])}</p><p>{e(notes)}</p></details>"
        if not include_all:
            body.append(f"<tr><td>{e(row['name'])}<small>{e(kind)}</small></td><td>{e(collection.get('selection_method', '확인 필요'))}</td><td>{info}</td></tr>")
            continue
        body.append(f"<tr><td>{e(row['name'])}<small>{e(kind)}</small>{info}</td><td>{e(collection.get('priority', '미분류'))}<small>{e(collection.get('reason'))}</small></td><td>{e(routes[row['legal_route']]['label'])}{'<small>분류 후보</small>' if row['eligibility_review'] == '개별 근거 확인 필요' else ''}</td><td>{e(row['eligibility_review'])}<small>{e(row['identity_review'])}</small></td><td>출자 이력 검수 대기</td></tr>")
    for route in routes.values():
        group = [r for r in rows if r['legal_route'] == route['id']]
        md.append(f"\n## {route['label']} ({len(group)})\n")
        for row in group:
            md.append(f"- **{row['name']}** · {row['entity_kind']} · {row['eligibility_review']}\n  근거: {row.get('legal_source_url')}\n  {' '.join(row.get('notes', []))}\n")
            md.append(f"  기관 분류: {row.get('institution_category', '미분류')} · 공고 수집: {row.get('notice_collection', {}).get('priority', '미분류')}\n")
            for source in row.get('activity_evidence', []):
                md.append(f"  활동 근거: [{source.get('type', '활동 근거')}]({source['url']}) · {source.get('note', '')}\n")
            for source in row.get('directory_evidence', []):
                md.append(f"  명부: [{source['source_name']}]({source['url']}) · 조회 {source.get('checked_at', data['as_of'])}\n")
            for source in row.get('notice_discovery_evidence', []):
                md.append(f"  공고 발견: [{source.get('title', '발견 근거')}]({source['url']}) · {source.get('verification_status', '원문 확인 대기')}\n")
                if source.get('official_url'):
                    md.append(f"  기관 원문: {source['official_url']}\n")
        if not group:
            md.append('명부 추가 확인 필요. 해당 유형이 없다는 뜻은 아님.\n')
    page = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LP 기본 명단</title><style>body{font:15px/1.6 -apple-system,BlinkMacSystemFont,sans-serif;color:#253248;margin:32px auto;padding:0 24px;max-width:1200px}h1{font-size:27px}p,small{color:#66758b}small{display:block;font-size:12px}input{font:inherit;padding:10px;width:300px;max-width:85%;margin:16px 0}table{width:100%;border-collapse:collapse}th,td{text-align:left;border-bottom:1px solid #dfe5eb;padding:14px;vertical-align:top}th{background:#f6f8fa;white-space:nowrap}.scroll{overflow:auto}td{min-width:150px}details{font-size:12px;max-width:350px}summary{cursor:pointer;color:#245789}a{color:#245789}footer{font-size:13px;margin-top:24px}</style>'''
    page += f"<h1>{'전체 참고 명단' if include_all else 'LP 공고 관리 대상'}</h1><p>{e(dates)} · {len(rows)}개<br>사용자 지정 기관과 PE 모집 조사 대상을 정리했습니다. 실제 출자·공모 빈도는 별도 확인합니다.</p>"
    if not include_all:
        page += '<p><a href="all.html">보류·수집 제외를 포함한 전체 참고 명단</a></p>'
    headings = '<th>기관·자금명</th><th>공고 수집</th><th>법적 유형</th><th>확인 상태</th><th>실제 출자 이력</th>' if include_all else '<th>기관·자금명</th><th>모집 확인 상태</th><th>근거</th>'
    page += f'<input aria-label="기관·유형 검색" placeholder="기관·유형 검색"><span id="count">{len(rows)}개</span><div class="scroll"><table><thead><tr>{headings}</tr></thead><tbody>'
    page += ''.join(body) + '</tbody></table></div><footer>공고가 없거나 위탁 방식이라는 이유로 제외하지 않았습니다. 협회·공식 안내 명부는 개별 인가·등록 상태와 다를 수 있습니다. 운영 사이트에는 반영하지 않았습니다.</footer>'
    if include_all:
        held = data.get('excluded_insurance_directory_rows', []) if include_all else []
        page += f'<h2>보험회사 유형 확인 보류 {len(held)}개</h2><p>위 {len(rows)}개와 별도로 보관합니다. LP 참여가 불가능하다고 확정한 회사가 아닙니다.</p><ul>'
        md.append(f'\n## 보험회사 유형 확인 보류 {len(held)}개\n\n본 명단과 별도로 보관하며, LP 참여 불가 확정이 아닙니다.\n')
        for row in held:
            refs = [link(s['source_url'], s['association_name']) for s in row['sources']]
            page += f"<li><strong>{e(row['company_name'])}</strong><p>{e(row['rejection_reason'])}<br>{' · '.join(refs)}</p></li>"
            md.append(f"- **{row['company_name']}**: {row['rejection_reason']}\n")
            for source in row['sources']:
                md.append(f"  출처: [{source['association_name']}]({source['source_url']}) · 조회 {source['checked_at']}\n")
        page += '</ul>'
    candidates = data.get('notice_discovery_candidates', []) if include_all else []
    if candidates:
        page += f'<h2>PE 여부·출자 주체 조사 대기 {len(candidates)}개</h2><p>본 명단과 별도인 발견 후보입니다.</p><ul>'
        md.append('\n## PE 여부·출자 주체 조사 대기\n')
        for row in candidates:
            page += f"<li>{e(row['name'])} · {e(row['institution_category_candidate'])}<p>{e(row['reason'])} {link(row['source_url'], '발견 출처')}</p></li>"
            md.append(f"- {row['name']} · {row['institution_category_candidate']}: {row['reason']} [발견 출처]({row['source_url']})\n")
        page += '</ul>'
    page += "<script>document.querySelector('input').addEventListener('input',e=>{let n=0;document.querySelectorAll('tbody tr').forEach(r=>{r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase());if(!r.hidden)n++});document.querySelector('#count').textContent=n+'개'})</script></html>"
    out.mkdir(parents=True, exist_ok=True)
    (out / 'index.html').write_text(page)
    (out / 'lp_list.md').write_text('\n'.join(md))
    summary = {'count': len(rows), 'total_reference_count': total, 'unique_ids': len(set(ids)), 'routes': dict(Counter(r['legal_route'] for r in rows)), 'source_input': str(input_path), 'public_write': False}
    (out / 'validation.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    if not include_all:
        render(input_path, out / 'reference', include_all=True)
        (out / 'all.html').write_text((out / 'reference/index.html').read_text())
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'data/lp_directory_review.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.input, args.out), ensure_ascii=False))
