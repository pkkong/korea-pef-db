"""Offline inventory of supplied LP evidence records, not historical completeness."""
import argparse
import csv
from collections import defaultdict
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
DISCLAIMER = ('Provided report subset only; not all Supabase historical documents. Counts are evidence records, '
              'not PE businesses or market coverage. Source authenticity and raw-byte hashes have not been replay-verified.')


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('invalid date')
    return date.fromisoformat(value)


def valid_url(value):
    if not isinstance(value, str) or len(value) > 8192 or re.search(r'[\x00-\x20\x7f\\]', value):
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == 'https' and bool(p.hostname) and '.' in p.hostname and not p.username
                and not p.password and not p.fragment and p.port in (None, 443))
    except ValueError:
        return False


def digest(value):
    return isinstance(value, str) and bool(re.fullmatch('[0-9a-f]{64}', value))


INDEX_FIELDS = {'institution_id','url','date','title','source_id','content_hash',
                'source_sha256','body_present','attachment_hashes','event_type'}


def validate_index(report):
    if (report.get('kind') != 'lp_document_index_v1'
            or type(report.get('database_index_complete')) is not bool
            or type(report.get('row_limit')) is not int or report['row_limit'] < 1
            or type(report.get('database_rows')) is not int or report['database_rows'] < 0
            or not isinstance(report.get('records'),list)
            or report['database_rows'] != len(report['records'])
            or report['database_rows'] > report['row_limit']):
        raise ValueError('invalid database index contract')
    try:
        stamp=datetime.fromisoformat(report['checked_at'].replace('Z','+00:00'))
        if stamp.tzinfo is None:raise ValueError()
    except (KeyError,ValueError,AttributeError,TypeError):
        raise ValueError('invalid database index checked_at') from None


def valid_index_record(n):
    return (not set(n)-INDEX_FIELDS and 'institution_id' in n
            and (n['institution_id'] is None or isinstance(n['institution_id'],str))
            and type(n.get('body_present')) is bool and digest(n.get('content_hash'))
            and 'source_sha256' in n and (n['source_sha256'] is None or digest(n['source_sha256']))
            and isinstance(n.get('attachment_hashes'),dict)
            and (n.get('source_id') is None or isinstance(n['source_id'],str))
            and (n.get('event_type') is None or isinstance(n['event_type'],str)))


def build(inputs, *, as_of, start='2023-01-01', scope=None, names=None):
    """inputs: [{kind, report, path?, sha256?}]; never mutate reports."""
    first, last = day(start), day(as_of)
    if first > last:
        raise ValueError('start after as_of')
    scope = scope or json.loads((ROOT/'data/lp_blind_contest_scope.json').read_text())
    ids = list(dict.fromkeys(scope['confirmed_institution_ids'] + scope['priority_verification_ids']))
    if names is None:
        with (ROOT/'data/lp_institutions.csv').open() as source:
            names = {r['lp_code']: r['lp_name'] for r in csv.DictReader(source)}
        for path in sorted((ROOT/'data').glob('lp_blind_contest_screening_*.json')):
            names.update({r['institution_id']: r['name'] for r in json.loads(path.read_text()).get('institutions', [])})
    seen_issuers, identities, issues, provenance = set(), defaultdict(list), [], []
    unknown_issuer_records=[]

    def issue(kind, index, issuer=None):
        issues.append({'kind':kind, 'input_index':index, 'institution_id':issuer})

    for index, item in enumerate(inputs):
        kind, report = item['kind'], item['report']
        if kind not in {'growth','priority','institution','database_index'} or not isinstance(report, dict):
            raise ValueError('invalid input report')
        provenance.append({'kind':kind, 'path':item.get('path'), 'sha256':item.get('sha256'),
                           'checked_at':report.get('checked_at')})
        streams = []
        if kind == 'database_index':
            validate_index(report)
            provenance[-1].update({k:report[k] for k in ('database_index_complete','database_rows','row_limit')})
            streams.append((None,{'notices':report['records']}))
        elif kind == 'growth':
            streams.append(('kgrowth', report))
        elif kind == 'priority':
            sources = report.get('sources')
            if not isinstance(sources, dict):
                issue('missing_sources',index); continue
            for iid, source in sources.items():
                if iid not in {'ktcu','koreapost','kexim'} or not isinstance(source,dict):
                    issue('invalid_priority_source',index); continue
                streams.append((iid, source))
        else:
            coverage_map=report.get('coverage', {})
            if not isinstance(coverage_map,dict):raise ValueError('invalid coverage map')
            for iid, coverage in coverage_map.items():
                if iid in ids and isinstance(coverage,dict):seen_issuers.add(iid)
            streams.append((None,report))
        for inherited, source in streams:
            notices=source.get('notices')
            if not isinstance(notices,list):
                issue('missing_notices',index,inherited);continue
            if inherited:seen_issuers.add(inherited)
            supporting=source.get('supporting_notices',[])
            if not isinstance(supporting,list):
                issue('invalid_supporting_notices',index,inherited);supporting=[]
            records=[(n,False) for n in notices]+[(n,True) for n in supporting]
            for n,is_supporting in records:
                if not isinstance(n,dict):issue('invalid_record',index,inherited);continue
                if kind=='database_index' and not valid_index_record(n):
                    issue('invalid_index_record',index);continue
                if kind=='database_index' and n['institution_id'] is None:
                    unknown_issuer_records.append({'input_index':index, **{k:n.get(k) for k in
                        ('url','date','source_id','content_hash')}})
                iid=n.get('institution_id') if is_supporting else inherited or n.get('institution_id')
                if iid not in ids or (not is_supporting and inherited and n.get('institution_id',inherited)!=inherited):
                    issue('invalid_issuer',index,inherited);continue
                seen_issuers.add(iid)
                if not valid_url(n.get('url')):issue('invalid_url',index,iid);continue
                try:published=day(n.get('date'))
                except ValueError:issue('invalid_date',index,iid);continue
                body_valid=(n['body_present'] if kind=='database_index' else
                            isinstance(n.get('body'),str) and bool(n['body'].strip()) and digest(n.get('sha256')))
                valid=bool(body_valid and isinstance(n.get('title'),str) and n['title'].strip())
                if not valid:issue('unverified_record',index,iid)
                attachments=set()
                raw=n.get('attachment_hashes',{})
                if not isinstance(raw,dict):issue('invalid_attachment_map',index,iid)
                else:
                    for url, sha in raw.items():
                        if valid_url(url) and digest(sha):attachments.add((url,sha))
                        else:issue('invalid_attachment_hash_pair',index,iid)
                identities[(iid,n['url'])].append((published,valid,attachments))
    buckets=defaultdict(list); conflict=defaultdict(int); outside=defaultdict(int); held=defaultdict(int)
    for (iid,url), versions in identities.items():
        dates={v[0] for v in versions}
        if len(dates)>1:
            conflict[iid]+=1
            issues.append({'kind':'publication_date_conflict','institution_id':iid,
                           'identity_sha256':hashlib.sha256(url.encode()).hexdigest(),
                           'dates':sorted(d.isoformat() for d in dates)})
            continue
        published=next(iter(dates))
        valid=[v for v in versions if v[1]]
        if not valid:held[iid]+=1;continue
        if not first<=published<=last:outside[iid]+=1;continue
        attachments=set().union(*(v[2] for v in valid))
        buckets[(iid,published.year)].append((published,attachments))
    rows=[]
    for iid in ids:
        for year in range(first.year,last.year+1):
            values=buckets[(iid,year)]
            dates=[v[0].isoformat() for v in values]
            pairs=set().union(*(v[1] for v in values)) if values else set()
            rows.append({'institution_id':iid,'name':names.get(iid,iid),'year':year,
                         'input_status':'provided' if iid in seen_issuers else 'not_provided',
                         'evidence_record_count':len(values) if iid in seen_issuers else None,
                         'attachment_hash_pair_count':len(pairs) if iid in seen_issuers else None,
                         'observed_min_date':min(dates) if dates else None,'observed_max_date':max(dates) if dates else None,
                         'history_completeness':'UNVERIFIED'})
    return {'version':1,'window':{'start':start,'end':as_of},'disclaimer':DISCLAIMER,
            'input_provenance':provenance,'rows':rows,'issues':issues,'unknown_issuer_records':unknown_issuer_records,
            'institution_exclusions':[{ 'institution_id':iid,'date_conflicts':conflict[iid],
                'unverified_identities':held[iid],'out_of_window':outside[iid]} for iid in ids],
            'validation':'structural_only_no_source_replay','history_completeness':'UNVERIFIED'}


def markdown(report):
    lines=['# 제공된 LP 과거 원문 기록 집계','',
           '입력한 보고서 일부의 기록 수입니다. 전체 DB·PE 사업 수·시장 수집률이 아니며 원문 재검증과 연도별 완전성 확인은 하지 않았습니다.',
           f"기간: {report['window']['start']} ~ {report['window']['end']}",'',
           '| 기관 | 연도 | 입력 | 원문 기록 | 첨부 지문 쌍 | 최초 관측일 | 최종 관측일 |',
           '|---|---:|---|---:|---:|---|---|']
    for r in report['rows']:
        vals=[r[k] for k in ('name','year','input_status','evidence_record_count','attachment_hash_pair_count','observed_min_date','observed_max_date')]
        lines.append('| '+' | '.join('미제공/미관측' if v is None else str(v).replace('|','\\|').replace('\n',' ') for v in vals)+' |')
    lines+=['',f"제외·검토 항목: {len(report['issues'])}건. 모든 연도 완전성: UNVERIFIED."]
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser()
    for kind in ('growth','priority','institution','database_index'):p.add_argument('--'+kind.replace('_','-'),type=Path,action='append',default=[])
    p.add_argument('--start',default='2023-01-01');p.add_argument('--as-of',required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args();inputs=[]
    for kind in ('growth','priority','institution','database_index'):
        for path in getattr(args,kind):
            raw=path.read_bytes()
            inputs.append({'kind':kind,'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'report':json.loads(raw)})
    report=build(inputs,as_of=args.as_of,start=args.start)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'lp-history-coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (args.output_dir/'lp-history-coverage.md').write_text(markdown(report))


if __name__=='__main__':main()
