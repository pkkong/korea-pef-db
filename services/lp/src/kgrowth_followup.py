"""Conservative final-result recognition over retained KGrowth evidence only."""
import hashlib
import json
import re
from datetime import date


def compact(text):
    return re.sub(r'\s+', '', text)


def fingerprint(n):
    return hashlib.sha256(json.dumps([n['title'],n['date'],n['body']],ensure_ascii=False).encode()).hexdigest()


def quoted(title):
    hits=re.findall(r'「([^「」]+)」|『([^『』]+)』',title)
    if len(hits)!=1:return None
    return compact(next(v for v in hits[0] if v))


def verified(n):
    if not isinstance(n,dict):return False
    if not all(isinstance(n.get(k),str) and n[k].strip() for k in ('title','body','date','url','sha256')):return False
    sid=n.get('source_id')
    if not isinstance(sid,(str,int)) or isinstance(sid,bool) or not re.fullmatch(r'[0-9]+',str(sid)):return False
    if n['url']!=f'https://www.kgrowth.or.kr/notice_view.asp?idx={sid}&str_type=1&tab=1':return False
    try:
        if date.fromisoformat(n['date']).isoformat()!=n['date']:return False
    except ValueError:return False
    return n['sha256']==fingerprint(n)


def _recognize_followup(recipe, recruitment, preceding_teams, expected_manager_count,
                       notices, approved_source_ids, *, as_of):
    """Return match/layout/evidence or a safe hold; never mutate or fetch inputs."""
    def held(reason):return {'match':None,'layout':None,'evidence':None,'hold':reason}
    try:today=date.fromisoformat(as_of)
    except (ValueError,TypeError):return held('invalid_as_of')
    if (not isinstance(recipe,dict) or not isinstance(recipe.get('tracks'),(list,dict))
            or len(recipe['tracks'])!=1 or not isinstance(next(iter(recipe['tracks'])),str)):
        return held('requires_single_track')
    track=next(iter(recipe['tracks']))
    if (not isinstance(preceding_teams,dict) or set(preceding_teams)!={track}
            or not isinstance(preceding_teams[track],list) or not preceding_teams[track]
            or any(not isinstance(n,str) or not n.strip() for n in preceding_teams[track])):
        return held('invalid_preceding_teams')
    prior=[compact(n) for n in preceding_teams[track]]
    if len(prior)!=len(set(prior)):return held('ambiguous_preceding_teams')
    if type(expected_manager_count)is not int or expected_manager_count<1:return held('invalid_manager_count')
    if not verified(recruitment):return held('invalid_recruitment_evidence')
    fund=quoted(recruitment['title'])
    if not fund:return held('ambiguous_recruitment_title')
    funds={fund}
    label=recipe.get('title','')
    if isinstance(label,str):
        label=re.sub(r'^20[0-9]{2}\s+','',label)
        label=re.sub(r'\s*·\s*재공고\s*$','',label)
        if label.strip():funds.add(compact(label))
    start=date.fromisoformat(recruitment['date'])
    if start>today:return held('future_recruitment')
    reopen='재공고' in recruitment['title']
    approved={str(s) for s in approved_source_ids}
    candidates=[]
    for n in notices:
        if not isinstance(n,dict) or not isinstance(n.get('title'),str):continue
        title=n['title'];short=compact(title)
        if quoted(title) not in funds or ('재공고' in title)!=reopen:continue
        if '선정결과' not in short:continue
        if re.search(r'서류|1차|정량|중간|우선협상|예비|예정|조건부|후보',short):continue
        if re.search(r'정정|변경|수정|취소|연장',short):return held('amended_result_requires_review')
        if not verified(n):return held('invalid_result_evidence')
        if n.get('attachments') or n.get('attachment_hashes'):return held('result_attachments_require_review')
        published=date.fromisoformat(n['date'])
        if published<start or published>today or published.year!=start.year:return held('result_date_mismatch')
        candidates.append(n)
    if not candidates:return held('no_matching_result')
    # Even identical repeats are ambiguous input, never silently select a version.
    if len(candidates)!=1:return held('multiple_result_records')
    n=candidates[0]
    if str(n['source_id']) in approved:return held('result_already_approved')
    body=n['body']
    body_short=compact(body)
    if quoted(body.splitlines()[0]) not in funds or '선정결과' not in compact(body.splitlines()[0]):
        return held('result_body_identity_missing')
    if ('재공고' in body.splitlines()[0])!=reopen:return held('result_body_round_mismatch')
    if re.search(r'정정|변경|수정|취소|연장|예정|첨부|우선협상|예비|조건부',body_short):return held('non_simple_result_body')
    lines=[line.strip() for line in body.splitlines() if line.strip()]
    positions=[i for i,line in enumerate(lines) if re.fullmatch(r'(?:ㅇ\s*|[-•]\s*)?운용사\s*명\s*\(\s*가나다\s*순\s*\)',line)]
    if len(positions)!=1:return held('manager_heading_missing_or_ambiguous')
    names=[re.sub(r'^[-•]\s*','',line) for line in lines[positions[0]+1:]]
    normalized=[compact(name) for name in names]
    if (len(names)!=expected_manager_count or len(normalized)!=len(set(normalized))
            or any(name not in prior for name in normalized)):
        return held('manager_count_or_prior_membership_mismatch')
    heading=lines[positions[0]]
    # The existing layout parser requires this heading to occur exactly once.
    if body.count(heading)!=1:return held('ambiguous_manager_heading')
    return {'match':n,'layout':{'heading':heading,'track':track,'count':expected_manager_count},
            'evidence':{'source_url':n['url'],'sha256':n['sha256'],'date':n['date'],
                        'event':'최종 선정','names':names,'track':track},'hold':None}


def recognize_followup(recipe, recruitment, preceding_teams, expected_manager_count,
                       notices, approved_source_ids, *, as_of):
    """Also derive a unique, hash-verified applicant roster when none is supplied."""
    if preceding_teams:
        return _recognize_followup(recipe,recruitment,preceding_teams,expected_manager_count,
                                   notices,approved_source_ids,as_of=as_of)
    def held(reason):return {'match':None,'layout':None,'evidence':None,'hold':reason}
    if not verified(recruitment) or not isinstance(recipe,dict) or len(recipe.get('tracks',{}))!=1:
        return held('invalid_recruitment_or_tracks')
    track=next(iter(recipe['tracks']))
    fund=quoted(recruitment['title']);reopen='재공고' in recruitment['title']
    candidates=[]
    for n in notices:
        if not isinstance(n,dict) or not isinstance(n.get('title'),str):continue
        if quoted(n['title'])!=fund or ('재공고' in n['title'])!=reopen or '접수현황' not in compact(n['title']):continue
        if not verified(n):return held('invalid_applicant_evidence')
        if n.get('attachments') or n.get('attachment_hashes'):return held('applicant_attachments_require_review')
        if (n['date']<recruitment['date'] or n['date'][:4]!=recruitment['date'][:4]
                or n['date']>as_of):return held('applicant_date_mismatch')
        if re.search(r'정정|변경|수정|취소|연장',n['title']):return held('amended_applicant')
        if re.search(r'첨부|우선협상|예비|조건부',n['body']):return held('non_simple_applicant_body')
        lines=[line.strip() for line in n['body'].splitlines() if line.strip()]
        if (not lines or quoted(lines[0])!=fund or '접수현황' not in compact(lines[0])
                or ('재공고' in lines[0])!=reopen):return held('applicant_body_identity_missing')
        counts=re.findall(r'신청\s*펀드\s*수\s*[:：]\s*총\s*([0-9]+)\s*개',n['body'])
        positions=[i for i,line in enumerate(lines) if re.fullmatch(r'(?:ㅇ\s*|[-•]\s*)?운용사\s*명\s*\(\s*가나다\s*순\s*\)',line)]
        if len(counts)!=1 or len(positions)!=1:return held('ambiguous_applicant_roster')
        names=[re.sub(r'^[-•]\s*','',line) for line in lines[positions[0]+1:]]
        if (not names or len(names)!=int(counts[0]) or len(set(map(compact,names)))!=len(names)
                or any(not re.fullmatch(r'[가-힣A-Za-z0-9&·㈜(). /-]+',name) for name in names)):
            return held('invalid_applicant_roster')
        candidates.append((n,names,{'heading':lines[positions[0]],'track':track,'count':len(names)}))
    if len(candidates)!=1:return held('missing_or_multiple_applicant_records')
    n,names,layout=candidates[0]
    result=_recognize_followup(recipe,recruitment,{track:names},expected_manager_count,notices,approved_source_ids,as_of=as_of)
    if result['hold']:return result
    if n['date']>=result['match']['date']:return held('applicant_not_before_result')
    result.update(preceding_match=n,preceding_layout=layout)
    return result
