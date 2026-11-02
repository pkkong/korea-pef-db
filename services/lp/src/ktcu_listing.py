"""Shared, pure parsing of the official KTCU notice board."""
import re
from datetime import date
from urllib.parse import urlsplit, parse_qs
try:
    from .lp_board_adapters_pensions import _Document
except ImportError:
    from lp_board_adapters_pensions import _Document


def _root(html, url):
    p = urlsplit(url); q = parse_qs(p.query, keep_blank_values=True)
    if (p.scheme != 'https' or p.netloc != 'www.ktcu.or.kr' or p.path != '/PPW-CSB-000101'
            or p.fragment or set(q) - {'srchKey','srchText','curPage'}
            or any(len(v) != 1 for v in q.values()) or q.get('srchKey', ['sj']) != ['sj']
            or not re.fullmatch('[1-9][0-9]*', q.get('curPage', ['1'])[0])
            or '</html>' not in html.lower()):
        raise ValueError('Invalid KTCU listing route or incomplete HTML')
    root = _Document(html).root
    for key in ('srchKey','srchText'):
        controls = [n.attrs.get('value','') for n in root.nodes('input') if n.attrs.get('name',n.attrs.get('id')) == key]
        for select in root.nodes('select'):
            if select.attrs.get('name',select.attrs.get('id')) == key:
                controls += [n.attrs.get('value','') for n in select.nodes('option') if 'selected' in n.attrs]
        if controls and any(v != q.get(key, ['1' if key == 'curPage' else 'sj' if key == 'srchKey' else ''])[0] for v in controls):
            raise ValueError('KTCU search/page control mismatch')
    # The official form keeps curPage=1 even on page 2+. The visible pager
    # reports the actual response page; use that instead of the static input.
    counts = _page_counts(root)
    requested = int(q.get('curPage', ['1'])[0])
    if counts:
        total, current, last = counts
        if current != requested or not 1 <= current <= last:
            raise ValueError('Invalid KTCU page count')
    else:
        controls = [n.attrs.get('value', '') for n in root.nodes('input')
                    if n.attrs.get('name', n.attrs.get('id')) == 'curPage']
        if controls and any(v != str(requested) for v in controls):
            raise ValueError('KTCU page control mismatch')
    return root, q


def _page_counts(root):
    matches={tuple(map(int,m.groups())) for n in root.nodes('div','sort-tit')
             if (m:=re.fullmatch(r'총\s*([\d,]+)\s*건\s*\(\s*(\d+)\s*/\s*(\d+)\s*페이지\s*\)',n.clean().replace(',','')))}
    if not matches:
        return None
    if len(matches)!=1:
        raise ValueError('Conflicting KTCU page counts')
    return matches.pop()


def last_page(html, url):
    root,q = _root(html,url)
    counts = _page_counts(root)
    return counts[2] if counts else None


def parse_rows(html,url):
    root,q=_root(html,url)
    containers=[n for n in root.nodes('ul') if n.attrs.get('id')=='ulList']
    if len(containers)!=1:
        raise ValueError('Missing or duplicate KTCU board container')
    rows=[];seen=set()
    for node in containers[0].nodes('li'):
        anchors=[(a,m) for a in node.nodes('a') if (m:=re.fullmatch(r"javascript:fn_view\('(\d+)'\);?",a.attrs.get('href','')))]
        if not anchors:
            continue
        if len(anchors)!=1:
            raise ValueError('Ambiguous KTCU row')
        a,m=anchors[0];ident=m[1];title=a.attrs.get('title') or a.clean()
        dates={n.clean() for n in node.nodes('span','date')
               if re.fullmatch(r'20\d{2}[.-]\d{2}[.-]\d{2}', n.clean())}
        if not title or len(dates)!=1 or ident in seen:
            raise ValueError('Invalid or duplicate KTCU row metadata')
        stamp=date.fromisoformat(next(iter(dates)).replace('.','-')).isoformat()
        num=next((n.clean() for n in node.nodes('span','num')), '')
        rows.append({'source_id':'ktcu:'+ident,'url':'https://www.ktcu.or.kr/PPW-CSB-000101/'+ident,
                     'title':title,'date':stamp,'pinned':not num.isdigit()});seen.add(ident)
    if not rows:
        empty=re.search(r'(?:등록된|검색된|조회된)\s*(?:게시물|게시글|자료|내용|결과)(?:이|가)?\s*없',containers[0].clean())
        if not empty or q.get('curPage',['1'])!=['1']:
            raise ValueError('Unconfirmed empty KTCU board')
        counts=[n.clean() for n in root.nodes('div','sort-tit')]
        if not any(re.search(r'총\s*0\s*건',s) for s in counts):
            raise ValueError('Empty KTCU board lacks zero count')
    last_page(html,url)
    return rows
