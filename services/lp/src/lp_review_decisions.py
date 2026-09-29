"""Apply human decisions only while all reviewed evidence still matches."""
import copy
import hashlib
import re
from datetime import date


def apply_decisions(data, notices, decisions):
    if not decisions:
        data['review_outcomes']=[]
        return data
    by_id={str(n['source_id']):n for n in notices}
    programs={p['id']:p for p in data['programs']}
    outcomes=[]
    latest={}
    for decision in sorted(decisions,key=lambda d:int(d['id'])):
        latest[decision['source_id']]=decision
    newest_program={}
    for d in latest.values():
        if d['action']=='approve' and isinstance(d.get('program'),dict):
            key=d['program'].get('id')
            newest_program[key]=max(newest_program.get(key,0),int(d['id']))
    for d in sorted(latest.values(),key=lambda d:int(d['id'])):
        try:
            for old in d['evidence']:
                current=by_id[str(old['source_id'])]
                if any(current.get(k)!=old.get(k) for k in ('title','date','body','attachment_hashes')):
                    raise ValueError('검토 후 원문이 변경되었습니다')
            if d['action']!='approve':
                outcomes.append({'id':d['id'],'status':d['action']});continue
            p=copy.deepcopy(d['program'])
            if int(d['id'])!=newest_program[p['id']]:
                outcomes.append({'id':d['id'],'status':'superseded'});continue
            validate_reviewed_program(p,d['evidence'])
            p['manual_review_id']=d['id']
            programs[p['id']]=p
            outcomes.append({'id':d['id'],'status':'published'})
        except (ValueError,KeyError,TypeError) as exc:
            outcomes.append({'id':d['id'],'status':'needs_review','reason':str(exc)})
    data['programs']=list(programs.values())
    data['review_outcomes']=outcomes
    return data


def validate_reviewed_program(p,evidence):
    if p.get('institution_id')!='kgrowth' or not re.fullmatch(r'kgrowth-[a-z0-9_-]+',p.get('id','')):
        raise ValueError('잘못된 사업 ID')
    if not p.get('title') or not p.get('asset_scope'):
        raise ValueError('사업명과 투자 분야가 필요합니다')
    amount=p.get('commitment_amount_krw')
    if amount is not None and (type(amount) not in (int,float) or not 0<amount<10**16):
        raise ValueError('출자액을 확인해 주세요')
    sources={n['url']:n for n in evidence}
    if not p.get('events') or not p.get('schedule_stages'):
        raise ValueError('원문이 연결된 일정이 필요합니다')
    for e in p['events']:
        if e['url'] not in sources or e['date']!=sources[e['url']]['date']:
            raise ValueError('공고 게시일과 출처가 일치하지 않습니다')
    for s in p['schedule_stages']:
        if s.get('source_url') not in sources:
            raise ValueError('일정 원문이 필요합니다')
        if s.get('precision') not in ('date','datetime','month') or s.get('status') not in ('confirmed','planned','announced_deadline'):
            raise ValueError('일정 형식이 올바르지 않습니다')
        for key in ('stage','label','original_label','date'):
            if not s.get(key):raise ValueError('일정 항목이 누락되었습니다')
        date.fromisoformat(s['date'][:10])
    if len({g['name'] for g in p.get('selected_gps',[])})!=len(p.get('selected_gps',[])):
        raise ValueError('선정 GP가 중복됩니다')
    if p.get('shortlisted_gps') and not {g['name'] for g in p.get('selected_gps',[])} <= set(p['shortlisted_gps']):
        raise ValueError('선정 GP와 서류 통과 명단을 확인해 주세요')
    for g in p.get('selected_gps',[]):
        if not g.get('id') and not g.get('master_id'):
            g['id']='kgrowth-'+hashlib.sha256(g['name'].encode()).hexdigest()[:16]
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',str(g.get('master_id') or g.get('id'))):
            raise ValueError('잘못된 GP 식별자')
    p['institution_name']='한국성장금융'
    from lp_program_service import validate
    validate({'as_of':date.today().isoformat(),'programs':[p]})
