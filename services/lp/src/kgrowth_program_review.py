"""Evidence-bound review recipes and repeatable program projection.

Recipes approve source fingerprints and field evidence, never rendered HTML.
Unrecognised notices remain candidates; no fuzzy business or GP merging.
"""
import hashlib
import json
import re
from pathlib import Path
from datetime import datetime

REGISTRY = Path(__file__).resolve().parents[3] / 'data/kgrowth_program_reviews.json'


def recipes():
    return json.loads(REGISTRY.read_text()) if REGISTRY.exists() else []


def fingerprint(notice):
    return hashlib.sha256(json.dumps([notice['title'], notice['date'], notice['body']], ensure_ascii=False).encode()).hexdigest()


def notice_classification(notice):
    path = REGISTRY.with_name('kgrowth_notice_classifications.json')
    rows = json.loads(path.read_text()) if path.exists() else []
    row = next((r for r in rows if r['source_id'] == str(notice['source_id'])), None)
    if row and notice.get('body') is not None and fingerprint(notice) == row['sha256'] and notice.get('attachment_hashes', {}) == row.get('attachment_hashes', {}):
        return row
    return None


def matching_recipe_title(recipe, title):
    compact = re.sub(r'\s+', '', title).casefold()
    terms = recipe.get('match_terms') or [recipe['source_title']]
    return all(re.sub(r'\s+', '', term).casefold() in compact for term in terms)


def link_suggestions(notices):
    """Suggest review targets; a suggestion never approves a stage or GP."""
    reviewed = recipes()
    attached = {'1047', '1075', '1090', '1100'}
    attached.update(str(source['source_id']) for recipe in reviewed for source in recipe['sources'])
    suggestions = []
    for notice in notices:
        if str(notice['source_id']) in attached or notice_classification(notice):
            continue
        title = notice['title']
        if '제출서식' in title or '【기타】' in title:
            continue
        compact = re.sub(r'\s+', '', title)
        stage = ('정정·변경' if any(word in title for word in ('정정', '변경', '취소', '연장')) else
                 '접수 현황' if '접수현황' in compact else
                 '서류심사 결과' if '서류심사' in compact else
                 '최종 선정' if '선정결과' in compact else None)
        if not stage:
            continue
        targets = [{'id':recipe['id'], 'title':recipe['title']} for recipe in reviewed
                   if matching_recipe_title(recipe, title)]
        if '은행권중견기업밸류업펀드(3차)' in compact:
            targets.append({'id':'kgrowth-2026-bank-valueup-3',
                            'title':'은행권 중견기업 밸류업펀드(3차)'})
        if targets:
            suggestions.append({'source_id':str(notice['source_id']), 'date':notice['date'],
                                'title':title, 'url':notice['url'], 'stage':stage,
                                'sha256':fingerprint(notice),
                                'attachment_hashes':notice.get('attachment_hashes', {}),
                                'programs':targets})
    return suggestions


def candidate_queue(notices):
    groups = {}
    for n in notices:
        title = n['title']
        match = re.search(r'「([^」]+)」', title)
        if not match or '【기타】' in title:
            key, disposition = n['source_id'], '사업 공고 아님'
        else:
            # Keep series/track labels verbatim; 2호 and 2차 are not aliases.
            key = re.sub(r'\s+', '', match[1])
            disposition = '사업 연결 검토'
        group = groups.setdefault(key, {'title':match[1] if match else title,
                                       'disposition':disposition, 'notices':[]})
        stage = ('재공고·변경' if any(w in title for w in ['재공고','정정','연장','취소']) else
                 '제출 서식' if '제출서식' in title else
                 '1차 심사' if '서류심사' in title else
                 '최종 선정' if '선정결과' in re.sub(r'\s+', '',title) else
                 '접수 현황' if '접수현황' in re.sub(r'\s+', '',title) else '모집 공고')
        classification = notice_classification(n)
        if classification:
            group['disposition'] = classification['label']
        group['notices'].append({'source_id':n['source_id'], 'title':title, 'date':n['date'],
                                 'url':n['url'], 'stage':stage})
        if stage == '재공고·변경':
            group['disposition'] = '기존 차수와 분리 검토'
    return list(groups.values())


def team_sections(body, layout=None):
    """Explicit Korean section headings and manager rows; no entity guesses."""
    if layout:
        heading = layout['heading']
        if body.count(heading) != 1:
            raise ValueError('Manager heading missing or ambiguous')
        section = body.split(heading, 1)[1].split('문의', 1)[0]
        if layout.get('row_separator'):
            section = section.replace(layout['row_separator'], '\n')
        names = [re.sub(r'^[-•]\s*', '', line.strip()) for line in section.splitlines() if line.strip()]
        if len(names) != layout['count'] or len(set(names)) != len(names):
            raise ValueError('Manager list count differs from reviewed evidence')
        return {layout['track']:names}
    result, current = {}, None
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith('문의'):
            break
        if line.startswith('ㅇ '):
            if '신청 펀드 수' in line:
                continue
            heading = line[2:].split('신청 회사명')[0].strip().rstrip(':').strip().strip('[]')
            current = re.sub(r'\s+', '', heading)
            if current in result:
                raise ValueError('Duplicate manager section')
            result[current] = []
        elif current and line and line not in ('운용사명', '운용사 명'):
            result[current].append(re.sub(r'^-\s*', '', line))
    if not result or any(not names or len(names) != len(set(names)) for names in result.values()):
        raise ValueError('Missing or duplicate manager rows')
    return result


def project(recipe, notices, checked_at=None):
    by_id = {str(n['source_id']):n for n in notices}
    sources = []
    for approved in recipe['sources']:
        n = by_id.get(str(approved['source_id']))
        if n is None or fingerprint(n) != approved['sha256']:
            raise ValueError('Approved source missing or changed')
        if n.get('attachment_hashes', {}) != approved.get('attachment_hashes', {}):
            raise ValueError('Approved attachment changed')
        sources.append((approved, n))
    source_ids = {str(s['source_id']) for s in recipe['sources']}
    exclusions = {str(e['source_id']):e for e in recipe.get('related_exclusions', [])}
    for n in notices:
        excluded = exclusions.get(str(n['source_id']))
        if excluded and fingerprint(n) == excluded['sha256'] and n.get('attachment_hashes', {}) == excluded.get('attachment_hashes', {}):
            continue
        if n['source_id'] not in source_ids and matching_recipe_title(recipe, n['title']) and '【제출서식】' not in n['title']:
            raise ValueError('New related notice requires review')
    # Every reviewed offering field has an exact excerpt from a fetched body
    # or a separately retained, hash-bound attachment text.
    facts = {}
    for field, evidence in recipe.get('facts', {}).items():
        n = by_id[str(evidence['source_id'])]
        attachment_url = evidence.get('attachment_url')
        if evidence.get('evidence_mode') == 'file_hash_reviewed':
            approved = next(s for s in recipe['sources'] if str(s['source_id']) == str(evidence['source_id']))
            if not attachment_url or attachment_url not in approved.get('attachment_hashes', {}) or not evidence.get('quote'):
                raise ValueError(f'Missing hash-bound file evidence: {field}')
            # The source attachment hash was already checked above. This mode
            # is for reviewed HWP text that the workflow cannot re-extract.
        else:
            text = n.get('attachment_texts', {}).get(attachment_url, '') if attachment_url else n['body']
            if not evidence.get('quote') or evidence['quote'] not in text:
                raise ValueError(f'Field evidence no longer matches: {field}')
        facts[field] = evidence['value']
    p = {'id':recipe['id'], 'institution_id':'kgrowth', 'institution_name':'한국성장금융',
         'title':recipe['title'], 'display_title':recipe['title'], 'asset_scope':recipe['asset_scope'],
         'status':'모집 공고', 'events':[], 'schedule_stages':[], 'selected_gps':[],
         'shortlisted_gps':[], 'gp_tracks':{}, **facts}
    stage_map = {'모집 공고':('announcement','모집 공고'), '서류심사 결과':('screening','1차 심사 결과'),
                 '최종 선정':('selection','최종 선정'), '접수 현황':('application','접수 현황')}
    applicants, shortlist, final = {}, {}, {}
    for approved,n in sorted(sources,key=lambda pair:pair[1]['date']):
        event = approved['event']
        p['events'].append({'date':n['date'], 'title':n['title'], 'type':event, 'url':n['url']})
        stage,label = stage_map[event]
        p['schedule_stages'].append({'stage':stage,'label':label,'original_label':event,'date':n['date'],
                                    'precision':'date','status':'confirmed','source_url':n['url'],'show_source':True})
        if event in ('접수 현황','서류심사 결과','최종 선정'):
            teams = team_sections(n['body'], approved.get('manager_layout'))
            if set(teams) != set(recipe['tracks']):
                raise ValueError('Manager tracks differ from reviewed program')
            p['schedule_stages'][-1]['detail'] = f"{sum(len(names) for names in teams.values())}개 팀"
            if event == '접수 현황':
                p['status'] = '심사 중'
                applicants = teams
                p['manager_list_sources'] = {'applicants_gps':n['url']}
                p['applicants_gps'] = [name for names in teams.values() for name in names]
            elif event == '서류심사 결과':
                p['status'] = '심사 중'
                shortlist = teams
            else:
                final = teams
                final_url = n['url']
    for track,names in shortlist.items():
        aliases = recipe.get('name_aliases', {})
        if applicants and not {aliases.get(n,n) for n in names} <= {aliases.get(n,n) for n in applicants[track]}:
            raise ValueError('Shortlisted manager not found among applicants in this track')
        p['shortlisted_gps'].extend(names)
        for name in names:
            p['gp_tracks'][name] = recipe['tracks'][track]
    for track,names in final.items():
        prior = shortlist or applicants
        aliases = recipe.get('name_aliases', {})
        if prior and not {aliases.get(n,n) for n in names} <= {aliases.get(n,n) for n in prior[track]}:
            raise ValueError('Final manager not found in preceding stage')
        for name in names:
            # A source-derived identity is not a match to an existing GP master.
            key = 'kgrowth-' + hashlib.sha256(name.encode()).hexdigest()[:16]
            p['selected_gps'].append({'id':key, 'name':name, 'source_url':final_url,
                                     'asset_scope':recipe['tracks'][track]})
            master_id = recipe.get('gp_master_ids', {}).get(name)
            if master_id:
                p['selected_gps'][-1].update(master_id=master_id, master_name=name, identity_match='reviewed_exact_name')
            p['gp_tracks'][name] = recipe['tracks'][track]
    if final:
        p['status'] = '선정 완료'
    if p.get('deadline'):
        recruitment = next(n for approved,n in sources if approved['event']=='모집 공고')
        p['schedule_stages'].append({'stage':'application','label':'접수 마감','original_label':'접수 마감',
                                    'date':p['deadline'],'precision':'datetime','status':'announced_deadline',
                                    'source_url':recruitment['url'],'show_source':True})
        p['schedule_stages'].sort(key=lambda s:(s['date'][:10], 0 if s['status']=='announced_deadline' else 1, s['date']))
    if p['status'] == '모집 공고' and p.get('deadline') and checked_at:
        if datetime.fromisoformat(checked_at) >= datetime.fromisoformat(p['deadline']):
            p['status'] = '접수 마감'
    p['review_evidence'] = recipe['facts']
    return p


def reviewed_programs(notices, checked_at=None):
    programs, holds = [], []
    for recipe in recipes():
        try:
            programs.append(project(recipe, notices, checked_at))
        except (ValueError, KeyError) as error:
            holds.append({'program_id':recipe['id'], 'reason':str(error)})
    return programs, holds
