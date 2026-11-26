"""2020+ history notices retained in LP state (user decision 2026-11-14/15).

Collected by collect_lp_institution_history.py in Actions, reviewed offline, then
imported once through the daily board collection (`history_import` in the
institution collection). Each run re-validates every retained notice: listing and
detail receipts against their hashes, the board adapter's re-parse, the body hash,
and attachments observed on the detail receipt. Attachment bytes are not kept (the
state is near its size bound); their hashes and the text extracted from them in the
collecting run are.
"""
import copy

try:
    from . import collect_lp_institution_boards as boards
except ImportError:
    import collect_lp_institution_boards as boards

KIND = 'lp_history_notice_v1'
JOINT_KIND = 'lp_newdeal_joint_history_notice_v1'
JOINT_IMPORT_KIND = 'lp_newdeal_joint_history_import_v1'
JOINT_FOLLOWUP_IMPORT_KIND = 'lp_newdeal_joint_followup_import_v1'
JOINT_STAGES_IMPORT_KIND = 'lp_newdeal_joint_stages_import_v1'
KDB_PRESS_KIND = 'lp_kdb_projected_press_notice_v1'
KDB_MATERIALS_IMPORT_KIND = 'lp_kdb_materials_joint_history_import_v1'
ENTERPRISE_2022_KIND = 'lp_enterprise_newdeal_2022_notice_v1'
ENTERPRISE_2022_IMPORT_KIND = 'lp_enterprise_newdeal_2022_import_v1'
PROJECTED_KINDS = {JOINT_KIND, KDB_PRESS_KIND, ENTERPRISE_2022_KIND}


def validate_history_notice(raw, checked_at):
    if raw.get('history_import') == JOINT_KIND:
        try:
            from .lp_newdeal_history_import import validate_retained_notice
        except ImportError:
            from lp_newdeal_history_import import validate_retained_notice
        return validate_retained_notice(raw, checked_at)
    if raw.get('history_import') == KDB_PRESS_KIND:
        try:
            from .lp_kdb_materials_history_import import validate_retained_press
        except ImportError:
            from lp_kdb_materials_history_import import validate_retained_press
        return validate_retained_press(raw, checked_at)
    if raw.get('history_import') == ENTERPRISE_2022_KIND:
        try:
            from .lp_enterprise_newdeal_2022 import validate_retained_notice
        except ImportError:
            from lp_enterprise_newdeal_2022 import validate_retained_notice
        return validate_retained_notice(raw, checked_at)
    if raw.get('history_import') != KIND:
        raise ValueError('not an imported history notice')
    n = copy.deepcopy(raw)
    n.setdefault('attachment_bytes', {})
    if n['attachment_bytes']:
        raise ValueError('history notices keep no attachment bytes')
    validated = boards.validate_notice(n, checked_at, history_listing=True, require_attachment_bytes=False)
    validated['history_import'] = KIND
    return validated


def update_catalog(current, incoming, checked_at):
    """Retained history notices plus a new import; the retained version of a URL wins."""
    retained, holds = {}, []
    for raw in current.get('history_notices', []) + (incoming or {}).get('notices', []):
        try:
            n = validate_history_notice(raw, checked_at)
            retained.setdefault(n['url'], n)
        except (ValueError, KeyError, TypeError) as exc:
            holds.append({'stage': 'history_validation', 'url': raw.get('url'), 'error': str(exc)[:300]})
    return {'history_notices': list(retained.values()), 'history_notice_holds': holds}
