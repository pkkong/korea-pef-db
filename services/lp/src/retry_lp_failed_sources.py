"""Retry at most two failed LP issuers without recollecting healthy sources."""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
try:
    from . import collect_lp_institution_boards as boards
    from . import collect_priority_lp_programs as priority
    from . import collect_shared_lp_notices as shared
    from .collect_lp_original_notices import enrich
except ImportError:
    import collect_lp_institution_boards as boards
    import collect_priority_lp_programs as priority
    import collect_shared_lp_notices as shared
    from collect_lp_original_notices import enrich


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


def reuse_institution_evidence(original, recovered):
    """Reuse a trusted completed recovery without fetching an issuer again.

    The workflow checks repository/run provenance before calling this function.
    Only originally failed issuers may differ; healthy receipts and error history
    must remain intact. The normal publisher still replays source proofs.
    """
    failed = {h.get('institution_id') for h in original.get('holds', [])
              if h.get('stage') in {'institution_listing', 'institution_detail'}
              and h.get('failure_kind') != 'official_maintenance'}
    if not failed or None in failed or len(failed) > 2:
        raise ValueError('retained recovery requires one or two originally failed issuers')
    start = original.get('initial_checked_at', original.get('checked_at'))
    if not start or recovered.get('initial_checked_at') != start:
        raise ValueError('retained recovery belongs to another collection')
    old_coverage, new_coverage = original.get('coverage', {}), recovered.get('coverage', {})
    if set(old_coverage) != set(new_coverage) or not failed <= set(old_coverage):
        raise ValueError('retained recovery institution scope differs')
    healthy = set(old_coverage) - failed
    if any(old_coverage[i] != new_coverage[i] for i in healthy):
        raise ValueError('retained recovery changed healthy coverage')
    def healthy_records(report, field):
        return [n for n in report.get(field, []) if n.get('institution_id') not in failed]
    if any(healthy_records(original, field) != healthy_records(recovered, field)
           for field in ('notices', 'holds')):
        raise ValueError('retained recovery changed healthy evidence')
    if any(n.get('institution_id') not in old_coverage for n in recovered.get('notices', [])):
        raise ValueError('retained recovery contains an unexpected issuer')
    history = original.get('retry_history', [])
    new_history = recovered.get('retry_history', [])
    added = new_history[len(history):]
    if (new_history[:len(history)] != history or len(added) != len(failed)
            or {h.get('institution_id') for h in added} != failed):
        raise ValueError('retained recovery error history differs')
    for previous in added:
        iid = previous['institution_id']
        if (previous.get('previous_checked_at') != original.get('checked_at')
                or previous.get('previous_coverage') != old_coverage[iid]
                or previous.get('previous_holds') != [h for h in original['holds'] if h.get('institution_id') == iid]):
            raise ValueError('retained recovery did not preserve the original failure')
    if any(h.get('stage') in {'institution_listing', 'institution_detail', 'institution_depth'}
           and h.get('institution_id') in failed for h in recovered.get('holds', [])):
        raise ValueError('retained recovery still has failed source reads')
    previous_urls = {n['url'] for n in original.get('notices', [])}
    if not previous_urls <= {n['url'] for n in recovered.get('notices', [])}:
        raise ValueError('retained recovery removed existing notice URLs')
    return copy.deepcopy(recovered)


def retry_association(report, *, checked_at=None):
    """Refresh one failed association stream; healthy streams remain untouched."""
    result=copy.deepcopy(report)
    def channel_of(hold):
        return hold.get('source_channel') or hold.get('source_id','').split(':',1)[0]
    failed=list(dict.fromkeys(channel_of(h) for h in report.get('holds',[])
                if h.get('stage') in {'listing','detail'} and channel_of(h) in shared.CHANNELS))[:1]
    if not failed:return result,[]
    channel=failed[0];stamp=checked_at or datetime.now(timezone.utc).isoformat()
    fresh=enrich(shared.collect(pages=3,channels={channel:shared.CHANNELS[channel]},checked_at=stamp),checked_at=stamp)
    old={n['source_id']:n for n in result.get('notices',[])}
    for notice in fresh['notices']:
        previous=old.get(notice['source_id'])
        if previous and previous.get('sha256')==notice.get('sha256'):
            # A repeated association post cannot erase a verified issuer original.
            original=previous.get('original_notices')
            notice={**previous,**notice}
            if original and not notice.get('original_notices'):notice['original_notices']=original
        old[notice['source_id']]=notice
    replaced=[h for h in report.get('holds',[]) if channel_of(h)==channel and h.get('stage') in {'listing','detail'}]
    result.setdefault('retry_history',[]).append({'source_channel':channel,'retried_at':stamp,
        'previous_checked_at':report.get('checked_at'),'previous_holds':replaced,
        'previous_coverage':copy.deepcopy(report.get('coverage',{}).get('channel_pages',{}).get(channel)),
        'transport':copy.deepcopy(fresh['coverage'].get('transport'))})
    result['notices']=list(old.values())
    result['holds']=[h for h in result.get('holds',[]) if h not in replaced]+fresh['holds']
    coverage=result.setdefault('coverage',{})
    coverage.setdefault('channel_pages',{}).update(fresh['coverage']['channel_pages'])
    coverage.update(notice_count=len(result['notices']),hold_count=len(result['holds']))
    result.setdefault('unmatched_notices',[]).extend(fresh.get('unmatched_notices',[]))
    result['checked_at']=stamp
    return result,failed


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True)
    root=parser.parse_args().directory
    direct_path=root/'lp-institution-collection.json';priority_path=root/'lp-priority-collection.json'
    shared_path=root/'lp-shared-collection.json'
    direct,priorities,retried=retry_reports(json.loads(direct_path.read_text()),json.loads(priority_path.read_text()))
    association,channels=retry_association(json.loads(shared_path.read_text()))
    direct_path.write_text(json.dumps(direct,ensure_ascii=False))
    priority_path.write_text(json.dumps(priorities,ensure_ascii=False))
    shared_path.write_text(json.dumps(association,ensure_ascii=False))
    print(json.dumps({'retried_institutions':retried,'direct_holds':len(direct.get('holds',[])),
                      'retried_association_channels':channels,
                      'priority_errors':[iid for iid,source in priorities['sources'].items() if source.get('error')]}))


if __name__=='__main__':main()
