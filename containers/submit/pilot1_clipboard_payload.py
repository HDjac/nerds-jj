"""Second validation boundary: no unapproved text in clipboard telemetry."""
from datetime import datetime
from uuid import UUID
from re import fullmatch

KINDS = {'copy_committed','copy_requested','clipboard_observed','paste_requested','external_paste_blocked','host_paste_shortcut_blocked'}
SURFACES = {'task_sidebar','fuzzing_guide','internal_cli','internal_browser','other_internal'}
METHODS = {'copy_button','sidebar_keyboard','vnc_clipboard','ctrl_shortcut','meta_shortcut','shift_insert','other_internal'}
SOURCES = SURFACES | {'unknown'}
TRANSFERS = {('internal_cli','internal_cli'),('internal_cli','internal_browser'),('internal_browser','internal_cli')}
def normalize_clipboard_observation(data, allow_text=False):
    if not isinstance(data,dict) or not set(data).issubset({
            'event_key','expected_task_run_id','kind','surface','method','source','client_timestamp','text'}):
        raise ValueError('Invalid clipboard observation')
    try:
        key = data['event_key']
        eid=UUID(key[3:] if isinstance(key,str) and key.startswith('cb:') else '')
        task=UUID(data['expected_task_run_id'])
        stamp=datetime.fromisoformat(data['client_timestamp'].replace('Z','+00:00'))
    except (TypeError,ValueError,KeyError,AttributeError) as ex:
        raise ValueError('Invalid clipboard identifier') from ex
    if (eid.version != 4 or key != 'cb:'+str(eid) or str(task) != data['expected_task_run_id']
            or stamp.tzinfo is None or len(data['client_timestamp']) > 40):
        raise ValueError('Noncanonical clipboard fields')
    kind,surface,method,source = (data.get(x) for x in ('kind','surface','method','source'))
    if kind not in KINDS or surface not in SURFACES or method not in METHODS or source not in SOURCES:
        raise ValueError('Unexpected clipboard metadata')
    if kind == 'external_paste_blocked' and (source != 'unknown' or method != 'other_internal'):
        raise ValueError('Blocked external content must not be attributed')
    if kind == 'host_paste_shortcut_blocked' and (source != 'unknown' or
            method not in ('ctrl_shortcut','meta_shortcut') or
            surface not in ('internal_cli','internal_browser')):
        raise ValueError('Invalid host shortcut block')
    result={k:data[k] for k in ('event_key','expected_task_run_id','kind','surface','method','source','client_timestamp')}
    if 'text' in data:
        text=data['text']
        if not allow_text or kind != 'paste_requested' or (source,surface) not in TRANSFERS or \
                not isinstance(text,str) or not 1 <= len(text) <= 2048 or '\x00' in text or \
                (surface == 'internal_cli' and method != 'shift_insert') or \
                (surface == 'internal_browser' and method not in ('ctrl_shortcut','meta_shortcut')):
            raise ValueError('Text collection not permitted')
        result['text']=text
    return result
