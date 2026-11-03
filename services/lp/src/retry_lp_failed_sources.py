"""Retry at most two failed LP issuers without recollecting healthy sources."""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
try:
    from . import collect_lp_institution_boards as boards
    from . import collect_priority_lp_programs as priority
except ImportError:
    import collect_lp_institution_boards as boards
    import collect_priority_lp_programs as priority


def retry_reports(direct, priorities, *, checked_at=None, configs=None, fetch_factory=None, collectors=None):
    stamp=checked_at or datetime.now(timezone.utc).isoformat()
    configs=boards.load_configs() if configs is None else configs
    direct=copy.deepcopy(direct);priorities=copy.deepcopy(priorities)
    retried=[]
    # KEXIM has a separate collection job. Reserve one of the two issuer slots
    # only when that run retained a concrete source error.
    previous=priorities.get('sources',{}).get('kexim',{})
    if previous.get('error'):
        callbacks=collectors if collectors is not None else {'kexim':lambda:priority.collect_kexim(stamp)}
        if set(callbacks)!={'kexim'}:
            raise ValueError('recovery may retry only the failed KEXIM priority source')
        fresh=priority.collect(checked_at=stamp,collectors=callbacks)['sources']['kexim']
        # The publisher retains priority sources, not wrapper metadata.
        fresh['retry_history']=previous.get('retry_history',[])+[{'institution_id':'kexim','retried_at':stamp,
            'previous_source':{k:v for k,v in previous.items() if k!='retry_history'}}]
        priorities['sources']['kexim']=fresh
        retried.append('kexim')
    failed=list(dict.fromkeys(h.get('institution_id') for h in direct.get('holds',[])
                if h.get('stage') in {'institution_listing','institution_detail'}
                and h.get('failure_kind')!='official_maintenance'
                and h.get('institution_id') in configs))[:2-len(retried)]
    if failed:
        kwargs={'checked_at':stamp}
        if fetch_factory is not None:kwargs['fetch_factory']=fetch_factory
        direct=boards.retry_failed_sources(direct,{iid:configs[iid] for iid in failed},**kwargs)
        retried.extend(failed)
    return direct,priorities,retried


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True)
    root=parser.parse_args().directory
    direct_path=root/'lp-institution-collection.json';priority_path=root/'lp-priority-collection.json'
    direct,priorities,retried=retry_reports(json.loads(direct_path.read_text()),json.loads(priority_path.read_text()))
    direct_path.write_text(json.dumps(direct,ensure_ascii=False))
    priority_path.write_text(json.dumps(priorities,ensure_ascii=False))
    print(json.dumps({'retried_institutions':retried,'direct_holds':len(direct.get('holds',[])),
                      'priority_errors':[iid for iid,source in priorities['sources'].items() if source.get('error')]}))


if __name__=='__main__':main()
